"""Test helpers for the emailed links (ADR-018). Tests run on Django's in-memory mailer, so links are read from
`django.core.mail.outbox`."""

import re

from django.core import mail

_LINK = re.compile(r'https?://[^/\s]+(/accounts/(?:verify|password/reset)/[^/\s]+/[^/\s]+/)')


def emails_to(address):
    return [message for message in mail.outbox if address in message.to]


def link_in(message) -> str:
    """The path of the confirmation or reset link in an email."""
    match = _LINK.search(message.body)
    if match is None:
        raise AssertionError(f'No account link in the email {message.subject!r}')
    return match.group(1)


def confirm_email(client, address):
    """Open the newest confirmation link sent to `address` and press "Confirm my email". Returns the POST response."""
    return client.post(link_in(emails_to(address)[-1]))
