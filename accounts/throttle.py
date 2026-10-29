"""Database-backed rate limiting for login and registration (see ADR-006)."""

import hashlib
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import ThrottleEvent

logger = logging.getLogger('accounts.security')

LOGIN_ID = 'login-id'  # failed logins for one identifier from one IP
LOGIN_IP = 'login-ip'  # failed logins from one IP, whatever the identifier
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
    return str(value).replace('\r', '').replace('\n', '')


def _digest(*parts):
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()


def login_keys(identifier, ip):
    """Normalise the typed identifier so "Sam@Example.com " and "sam@example.com" share a counter."""
    return {LOGIN_ID: _digest(identifier.strip().lower(), ip), LOGIN_IP: _digest(ip)}


def _limit(name):
    attempts, seconds = settings.AUTH_THROTTLE[name]
    return attempts, timedelta(seconds=seconds)


def _recent(scope, key, window):
    return ThrottleEvent.objects.filter(scope=scope, key=key, created_at__gte=timezone.now() - window)


def is_blocked(scope, key, limit_name):
    attempts, window = _limit(limit_name)
    return _recent(scope, key, window).count() >= attempts


def record(scope, key):
    ThrottleEvent.objects.create(scope=scope, key=key)
    # Prune opportunistically so the table does not grow without bound.
    longest = max(seconds for _, seconds in settings.AUTH_THROTTLE.values())
    ThrottleEvent.objects.filter(created_at__lt=timezone.now() - timedelta(seconds=longest)).delete()


def login_blocked(identifier, ip):
    keys = login_keys(identifier, ip)
    blocked = is_blocked(LOGIN_ID, keys[LOGIN_ID], 'login') or is_blocked(LOGIN_IP, keys[LOGIN_IP], 'login_ip')
    if blocked:
        logger.warning('Login throttled for ip=%s', _safe_for_log(ip))
    return blocked


def record_login_failure(identifier, ip):
    for scope, key in login_keys(identifier, ip).items():
        record(scope, key)


def clear_login_failures(identifier, ip):
    """A successful login resets the per-identifier counter (the per-IP one keeps counting)."""
    ThrottleEvent.objects.filter(scope=LOGIN_ID, key=login_keys(identifier, ip)[LOGIN_ID]).delete()


def register_blocked(ip):
    blocked = is_blocked(REGISTER_IP, _digest(ip), 'register')
    if blocked:
        logger.warning('Registration throttled for ip=%s', _safe_for_log(ip))
    return blocked


def record_register_attempt(ip):
    record(REGISTER_IP, _digest(ip))


def retry_after(limit_name):
    return int(_limit(limit_name)[1].total_seconds())
