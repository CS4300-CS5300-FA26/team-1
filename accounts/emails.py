"""Send account email (verification, notices, password reset) through the default mailer (ADR-017).

Views call `send_account_email()` and show `EMAIL_NOT_SENT_MESSAGE` when it returns False. Every failure (the
per-recipient limit, an exhausted quota, Resend being down, missing configuration) looks the same to the user, so the
message never reveals quotas, the provider, or whether an address has an account. The reason is logged instead: by
`core.mail` for send failures and by `accounts.throttle` for the per-recipient limit.
"""

from django.core.mail import EmailMultiAlternatives

from core.mail import EmailNotSent

from . import throttle

EMAIL_NOT_SENT_MESSAGE = "We couldn't send the email right now. Please try again later."


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
