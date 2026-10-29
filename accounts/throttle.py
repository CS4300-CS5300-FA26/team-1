"""Database-backed rate limiting for login and registration (see ADR-006)."""

import hashlib
import logging
import math
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import ThrottleCounter

logger = logging.getLogger('accounts.security')

LOGIN_ID = 'login-id'  # login attempts for one identifier from one IP
LOGIN_IP = 'login-ip'  # login attempts from one IP, whatever the identifier
REGISTER_IP = 'register-ip'  # registration attempts from one IP

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
    """Count a registration attempt. Returns 0 or the seconds to wait."""
    wait = acquire((REGISTER_IP, _digest(ip), 'register'))
    if wait:
        logger.warning('Registration throttled for ip=%s', _safe_for_log(ip))
    return wait
