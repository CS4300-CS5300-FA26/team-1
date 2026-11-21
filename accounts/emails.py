"""Account email: sign-up confirmation, "you already have an account", and password reset (ADR-017, ADR-018).

The views never wait for these emails and never show whether one went out. Sign-up, "forgot password", and "resend
confirmation" only email some addresses (those with, or without, an account), so an error, or a slower response while
Resend answers, would reveal which addresses have accounts (ADR-018). The email is built during the request and sent
on a small background thread pool; a failure is logged (here, by `core.mail`, and by `accounts.throttle` for the
per-recipient limit), never shown.

Links are built from the request, so they use the host the person is on. ALLOWED_HOSTS limits that to our own
hostnames, which stops a forged Host header from putting someone else's domain in a link.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.db import connections
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from core.mail import EmailNotSent

from . import throttle
from .tokens import email_verification_token

logger = logging.getLogger('accounts.security')

# Per Gunicorn worker. Threads start on first use (after the fork), and at exit Python waits for queued sends.
_background = ThreadPoolExecutor(max_workers=2, thread_name_prefix='account-email')

VERIFY_SUBJECT = 'Confirm your email for FitPro'
ACCOUNT_EXISTS_SUBJECT = 'You already have a FitPro account'
RESET_SUBJECT = 'Reset your FitPro password'


def send_account_email(to: str, subject: str, text: str, html: str | None = None) -> bool:
    """Send one email to one address. Returns True if the mailer accepted it, False otherwise.

    Counts against `AUTH_THROTTLE['email_recipient']` before sending, so a form can't be used to flood one inbox or
    use up the day's quota quickly. The count is given back when the send fails (quota, outage, timeout), because
    nothing reached the inbox and the page asks the person to try again later. A timeout may hide a send Resend did
    accept, so in that rare case an address can get one email over the limit.
    """
    if throttle.acquire_email_recipient(to):
        return False
    message = EmailMultiAlternatives(subject=subject, body=text, to=[to])
    if html is not None:
        message.attach_alternative(html, 'text/html')
    try:
        message.send()
    except EmailNotSent:
        throttle.release_email_recipient(to)
        return False
    return True


def send_verification_email(request, user, via_spotify: bool = False) -> None:
    """Send, in the background, the link that confirms `user`'s email and activates the account."""
    path = reverse('verify_email', args=[_uid(user), email_verification_token.make_token(user)])
    text = render_to_string(
        'accounts/email/verify_email.txt', {'link': request.build_absolute_uri(path), 'via_spotify': via_spotify}
    )
    _deliver(user.email, VERIFY_SUBJECT, text, f'Confirmation link for user {user.pk}')


def send_account_exists_email(request, email: str) -> None:
    """Tell the owner of `email`, in the background, that someone tried to sign up with it."""
    text = render_to_string(
        'accounts/email/account_exists.txt',
        {
            'login_link': request.build_absolute_uri(reverse('login')),
            'reset_link': request.build_absolute_uri(reverse('password_reset')),
        },
    )
    _deliver(email, ACCOUNT_EXISTS_SUBJECT, text, '"Account exists" email')


def send_password_reset_email(request, user) -> None:
    """Send, in the background, a single-use link to choose a new password (Django's password reset token)."""
    path = reverse('password_reset_confirm', args=[_uid(user), default_token_generator.make_token(user)])
    text = render_to_string(
        'accounts/email/password_reset.txt',
        {'link': request.build_absolute_uri(path), 'username': user.get_username()},
    )
    _deliver(user.email, RESET_SUBJECT, text, f'Password reset link for user {user.pk}')


def _deliver(to: str, subject: str, text: str, label: str) -> None:
    """Hand the email to the background pool, so the response never waits for Resend (up to its 10-second timeout).

    `label` names the email in logs without the address. With ACCOUNT_EMAIL_IN_BACKGROUND off (tests), it sends here.
    """
    if settings.ACCOUNT_EMAIL_IN_BACKGROUND:
        _background.submit(_send_and_log, to, subject, text, label, close_db=True)
    else:
        _send_and_log(to, subject, text, label)


def _send_and_log(to: str, subject: str, text: str, label: str, close_db: bool = False) -> None:
    try:
        if not send_account_email(to, subject, text):
            logger.warning('%s not sent', label)
    except Exception:
        # Nothing waits on this thread, so log anything unexpected instead of losing it.
        logger.exception('%s failed', label)
    finally:
        if close_db:
            connections.close_all()  # this thread's own database connections (they are per thread)


def _uid(user) -> str:
    return urlsafe_base64_encode(force_bytes(user.pk))
