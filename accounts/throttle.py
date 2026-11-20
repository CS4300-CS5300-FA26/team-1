"""Database-backed rate limiting for login, registration, Spotify, the AI trainer, and new meal plans.

Meal plans also have an in-flight limit (`meal_plan_slot`): how many can be made at once.

See ADR-006, ADR-010, ADR-014, and ADR-016.
"""

import hashlib
import logging
import math
from contextlib import contextmanager
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .models import ThrottleCounter

logger = logging.getLogger('accounts.security')

LOGIN_ID = 'login-id'  # login attempts for one identifier from one IP
LOGIN_IP = 'login-ip'  # login attempts from one IP, whatever the identifier
REGISTER_IP = 'register-ip'  # registration attempts from one IP
REGISTER_TAKEN_IP = 'register-taken-ip'  # registration answers to one IP that said an account exists (ADR-016)
SPOTIFY_AUTH_IP = 'spotify-auth-ip'  # Spotify log-in or sign-up flows started from one IP
SPOTIFY_STATUS_USER = 'spotify-status'  # Spotify connection checks by one user
SPOTIFY_PLAYBACK_USER = 'spotify-playback'  # workout playlists started by one user
AI_TRAINER_USER = 'ai-trainer'  # AI trainer (OpenAI) calls by one user (ADR-014)
MEAL_PLAN_USER = 'meal-plan'  # meal plans made for one user (ADR-016)
MEAL_PLAN_RUNNING_USER = 'meal-plan-running'  # meal plans being made right now for one user (ADR-016)
MEAL_PLAN_RUNNING_ALL = 'meal-plan-running-all'  # meal plans being made right now for everyone (ADR-016)

THROTTLED_MESSAGE = 'Too many attempts. Please wait a while and try again.'


def client_ip(request):
    """Best guess at the caller's IP address.

    Behind the GKE load balancer REMOTE_ADDR is the balancer, and X-Forwarded-For ends with
    "<client ip>, <balancer ip>". Only the entry the balancer added can be trusted; anything
    to its left is supplied by the client and could be forged to dodge the limit.
    """
    remote = request.META.get('REMOTE_ADDR', '')
    if settings.BEHIND_HTTPS_PROXY:
        hops = [h.strip() for h in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',') if h.strip()]
        if len(hops) >= 2:
            return hops[-2]
    return remote


def _safe_for_log(value):
    """Return a single-line representation safe to include in plain-text logs."""
    return str(value).replace('\r', '').replace('\n', '')


def _digest(*parts):
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()


def _window(limit_name):
    attempts, seconds = settings.AUTH_THROTTLE[limit_name]
    return attempts, timedelta(seconds=seconds)


def _lock_counter(scope, key):
    """Return the (scope, key) row, locked until the surrounding transaction ends."""
    try:
        with transaction.atomic():
            ThrottleCounter.objects.get_or_create(scope=scope, key=key)
    except IntegrityError:  # another request created it first; it exists now
        pass
    return ThrottleCounter.objects.select_for_update().get(scope=scope, key=key)


def acquire(*checks):
    """Count one attempt against every (scope, key, limit_name) check, all or nothing.

    Returns 0 if the attempt is allowed. Otherwise nothing is counted and the return value is
    the number of seconds until the earliest window that blocks it ends (for Retry-After).

    The rows are locked (SELECT ... FOR UPDATE) in a fixed order while they are read and
    incremented, so parallel requests are serialized per key and can't all see "under the
    limit" at once. Counting happens before the password is checked for the same reason; a
    successful login gives its attempt back with `refund()`.
    """
    now = timezone.now()
    with transaction.atomic():
        rows = []
        for scope, key, limit_name in sorted(checks):
            attempts, window = _window(limit_name)
            row = _lock_counter(scope, key)
            if now - row.window_started >= window:
                row.count, row.window_started = 0, now
            rows.append((row, attempts, window))

        waits = [
            (row.window_started + window - now).total_seconds()
            for row, attempts, window in rows
            if row.count >= attempts
        ]
        for row, _, _ in rows:
            if not waits:
                row.count += 1
            row.save(update_fields=['count', 'window_started'])
    if waits:
        return max(1, math.ceil(max(waits)))
    _prune()
    return 0


def refund(scope, key, reset=False):
    """Give back an attempt, or zero the counter when `reset` is true."""
    with transaction.atomic():
        row = ThrottleCounter.objects.select_for_update().filter(scope=scope, key=key).first()
        if row:
            row.count = 0 if reset else max(0, row.count - 1)
            row.save(update_fields=['count'])


def _prune():
    """Delete counters whose window is over. Indexed on window_started, so it is cheap to run inline."""
    longest = max(seconds for _, seconds in settings.AUTH_THROTTLE.values())
    ThrottleCounter.objects.filter(window_started__lt=timezone.now() - timedelta(seconds=longest)).delete()


def login_keys(identifier, ip):
    """Normalise the typed identifier so "Sam@Example.com " and "sam@example.com" share a counter."""
    return {LOGIN_ID: _digest(identifier.strip().lower(), ip), LOGIN_IP: _digest(ip)}


def acquire_login(identifier, ip):
    """Count a login attempt before the password is checked. Returns 0 or the seconds to wait."""
    keys = login_keys(identifier, ip)
    wait = acquire((LOGIN_ID, keys[LOGIN_ID], 'login'), (LOGIN_IP, keys[LOGIN_IP], 'login_ip'))
    if wait:
        logger.warning('Login throttled for ip=%s', _safe_for_log(ip))
    return wait


def release_login(identifier, ip):
    """A successful login clears that identifier's counter and gives the IP its attempt back."""
    keys = login_keys(identifier, ip)
    refund(LOGIN_ID, keys[LOGIN_ID], reset=True)
    refund(LOGIN_IP, keys[LOGIN_IP])


def acquire_register(ip):
    """Count a registration attempt, and reserve a probe. Returns 0 or the seconds to wait.

    The form says when a username or email is taken, so each answer can reveal that an account exists. Those answers
    have their own, lower limit (ADR-016): every attempt reserves one up front, so parallel requests can't race past
    it, and `release_register_probe` gives it back when the answer revealed nothing.
    """
    key = _digest(ip)
    wait = acquire((REGISTER_IP, key, 'register'), (REGISTER_TAKEN_IP, key, 'register_taken'))
    if wait:
        logger.warning('Registration throttled for ip=%s', _safe_for_log(ip))
    return wait


def release_register_probe(ip):
    """The registration answer revealed no existing account: give back the probe `acquire_register` reserved."""
    refund(REGISTER_TAKEN_IP, _digest(ip))


def acquire_spotify_auth(ip):
    """Count a "Log in / Sign up with Spotify" attempt (story D-7). Returns 0 or the seconds to wait."""
    wait = acquire((SPOTIFY_AUTH_IP, _digest(ip), 'spotify_auth'))
    if wait:
        logger.warning('Spotify sign-in throttled for ip=%s', _safe_for_log(ip))
    return wait


def acquire_spotify_status(user_id):
    """Count a Spotify connection check, which calls Spotify's API. Returns 0 or the seconds to wait."""
    wait = acquire((SPOTIFY_STATUS_USER, _digest(str(user_id)), 'spotify_status'))
    if wait:
        logger.warning('Spotify connection check throttled for user=%s', _safe_for_log(user_id))
    return wait


def acquire_spotify_playback(user_id):
    """Count a workout playlist start, which searches Spotify and starts playback. Returns 0 or the seconds to wait."""
    wait = acquire((SPOTIFY_PLAYBACK_USER, _digest(str(user_id)), 'spotify_playback'))
    if wait:
        logger.warning('Workout playlist start throttled for user=%s', _safe_for_log(user_id))
    return wait


def acquire_ai_trainer(user_id):
    """Count a call to the AI trainer, which costs money. Returns 0 or the seconds to wait."""
    wait = acquire((AI_TRAINER_USER, _digest(str(user_id)), 'ai_trainer'))
    if wait:
        logger.warning('AI trainer throttled for user=%s', _safe_for_log(user_id))
    return wait


def acquire_meal_plan(user_id):
    """Count a meal plan about to be made, which runs the CPU-heavy planner. Returns 0 or the seconds to wait."""
    wait = acquire((MEAL_PLAN_USER, _digest(str(user_id)), 'meal_plan'))
    if wait:
        logger.warning('New meal plan throttled for user=%s', _safe_for_log(user_id))
    return wait


def _take_slot(scope, key, limit, lease_seconds):
    """Take one of `limit` in-flight slots for (scope, key). True if one was free.

    Each step is one UPDATE, so it is atomic on its own: PostgreSQL rechecks the WHERE clause against a row another
    request has just changed, so parallel requests can't both take the last slot. Unlike `acquire`, no lock or
    transaction is held while the work runs, and nothing here depends on SELECT ... FOR UPDATE (which SQLite skips).
    """
    now = timezone.now()
    counters = ThrottleCounter.objects.filter(scope=scope, key=key)
    for _ in range(2):  # a second pass only if `_prune` deleted the row between creating and updating it
        try:
            with transaction.atomic():
                ThrottleCounter.objects.get_or_create(scope=scope, key=key)
        except IntegrityError:  # another request created it first; it exists now
            pass
        # window_started is when the latest slot was taken, so every holder started no later than that. Once the
        # lease has passed since then, Gunicorn's timeout has killed any holder still running: free its slots.
        counters.filter(window_started__lte=now - timedelta(seconds=lease_seconds)).update(count=0)
        if counters.filter(count__lt=limit).update(count=F('count') + 1, window_started=now):
            return True
        if counters.exists():
            return False
    return False


def _give_back_slot(scope, key):
    ThrottleCounter.objects.filter(scope=scope, key=key, count__gt=0).update(count=F('count') - 1)


@contextmanager
def meal_plan_slot(user_id):
    """Hold an in-flight slot for one meal planner run while the block runs. Yields True if one was free.

    The planner is CPU-bound and holds a sync Gunicorn worker for the whole run, so the hourly count alone can't stop
    a burst of parallel requests from holding every worker (ADR-016). This limits runs in progress, per user and for
    everyone, across all pods. Slots are given back when the block exits, including on an exception.
    """
    limits = settings.MEAL_PLAN_CONCURRENCY
    slots = (
        (MEAL_PLAN_RUNNING_USER, _digest(str(user_id)), limits['per_user']),
        (MEAL_PLAN_RUNNING_ALL, MEAL_PLAN_RUNNING_ALL, limits['total']),
    )
    held = []
    for scope, key, limit in slots:
        if not _take_slot(scope, key, limit, limits['lease_seconds']):
            logger.warning('New meal plan refused while others run, user=%s scope=%s', _safe_for_log(user_id), scope)
            break
        held.append((scope, key))
    try:
        yield len(held) == len(slots)
    finally:
        for scope, key in reversed(held):
            _give_back_slot(scope, key)
