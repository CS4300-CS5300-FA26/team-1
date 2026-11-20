"""Account email: sign-up confirmation, "you already have an account", and password reset (ADR-017, ADR-018).

Views call these and show `EMAIL_NOT_SENT_MESSAGE` (HTTP 503) when one returns False. Every failure looks the same to
the user: the per-recipient limit, an exhausted quota, Resend being down, or missing configuration. The reason is
logged instead, by `core.mail` for send failures and by `accounts.throttle` for the per-recipient limit.

Links are built from the request, so they use the host the person is on. ALLOWED_HOSTS limits that to our own
hostnames, which stops a forged Host header from putting someone else's domain in a link.
"""

from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from core.mail import EmailNotSent

from . import throttle
from .tokens import email_verification_token

EMAIL_NOT_SENT_MESSAGE = (
    "Something went wrong on our end and we couldn't send the email. "
    'Please try again later, and let us know if it keeps happening.'
)

VERIFY_SUBJECT = 'Confirm your email for FitPro'
ACCOUNT_EXISTS_SUBJECT = 'You already have a FitPro account'
RESET_SUBJECT = 'Reset your FitPro password'


def send_account_email(to: str, subject: str, text: str, html: str | None = None) -> bool:
    """Send one email to one address. Returns True if the mailer accepted it, False otherwise.

    Counts against `AUTH_THROTTLE['email_recipient']` before sending, so a form can't be used to flood one inbox or
    use up the day's quota quickly.
    """
    if throttle.acquire_email_recipient(to):
        return False
    message = EmailMultiAlternatives(subject=subject, body=text, to=[to])
    if html is not None:
        message.attach_alternative(html, 'text/html')
    try:
        message.send()
    except EmailNotSent:
        return False
    return True


def send_verification_email(request, user, via_spotify: bool = False) -> bool:
    """Send the link that confirms `user`'s email and activates the account."""
    path = reverse('verify_email', args=[_uid(user), email_verification_token.make_token(user)])
    text = render_to_string(
        'accounts/email/verify_email.txt', {'link': request.build_absolute_uri(path), 'via_spotify': via_spotify}
    )
    return send_account_email(user.email, VERIFY_SUBJECT, text)


def send_account_exists_email(request, email: str) -> bool:
    """Tell the owner of `email` that someone tried to sign up with it, instead of saying so on the sign-up page."""
    text = render_to_string(
        'accounts/email/account_exists.txt',
        {
            'login_link': request.build_absolute_uri(reverse('login')),
            'reset_link': request.build_absolute_uri(reverse('password_reset')),
        },
    )
    return send_account_email(email, ACCOUNT_EXISTS_SUBJECT, text)


def send_password_reset_email(request, user) -> bool:
    """Send a single-use link to choose a new password (Django's password reset token)."""
    path = reverse('password_reset_confirm', args=[_uid(user), default_token_generator.make_token(user)])
    text = render_to_string(
        'accounts/email/password_reset.txt',
        {'link': request.build_absolute_uri(path), 'username': user.get_username()},
    )
    return send_account_email(user.email, RESET_SUBJECT, text)


def _uid(user) -> str:
    return urlsafe_base64_encode(force_bytes(user.pk))
