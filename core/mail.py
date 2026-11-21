"""Send email through Resend's HTTP API (ADR-017), as a Django email backend.

Selected in `MAILERS` (fitpro/settings.py). Uses the standard library, like spotify/client.py, so there is no SDK
dependency. Every failure raises `EmailNotSent` and is logged on the `fitpro.email` logger with a reason only. Log lines
never include a recipient address, a subject, a body, or the API key.

Resend docs: https://resend.com/docs/api-reference/emails/send-email (request),
https://resend.com/docs/api-reference/errors (error codes), https://resend.com/docs/api-reference/rate-limit
(quota and rate limit), https://resend.com/docs/dashboard/emails/idempotency-keys (idempotency).
"""

import hashlib
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger('fitpro.email')

SEND_URL = 'https://api.resend.com/emails'
TIMEOUT_SECONDS = 10
# Resend rejects requests without a User-Agent (HTTP 403).
USER_AGENT = 'fitpro-app/1.0'
QUOTA_CODES = frozenset({'daily_quota_exceeded', 'monthly_quota_exceeded', 'email_above_quota'})


class EmailNotSent(Exception):
    """Resend didn't accept the message. `code` is Resend's error code, or a short reason of ours."""

    def __init__(self, code: str):
        super().__init__(f'Email not sent: {code}')
        self.code = code


class EmailQuotaExceeded(EmailNotSent):
    """The plan's daily or monthly sending quota is used up. Nothing more sends until it resets."""


class ResendEmailBackend(BaseEmailBackend):
    """One HTTPS request per message. Configure with `OPTIONS: {'api_key': ...}`.

    Supports plain text and HTML (an `EmailMultiAlternatives` text/html alternative, or `content_subtype = 'html'`),
    cc, bcc, reply-to, and extra headers. Attachments aren't supported, because account email never needs them.
    """

    def __init__(self, api_key: str = '', timeout: int = TIMEOUT_SECONDS, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key
        self.timeout = timeout

    def send_messages(self, email_messages) -> int:
        if not email_messages:
            return 0
        if not self.api_key:
            logger.error('Email is not configured: no Resend API key (RESEND_API_KEY). Email is not being sent.')
            raise EmailNotSent('not_configured')
        sent = 0
        for message in email_messages:
            self._send(_payload(message))
            sent += 1
        return sent

    def _send(self, payload: dict) -> None:
        body = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode()
        request = Request(  # noqa: S310 (fixed https URL)
            SEND_URL,
            data=body,
            headers={
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'User-Agent': USER_AGENT,
                # The same payload within 24 hours is sent once, so a retried request can't send twice.
                'Idempotency-Key': f'fitpro/{hashlib.sha256(body).hexdigest()}',
            },
            method='POST',
        )
        try:
            # Only ever called with the constant https:// URL above, so no file:// or other scheme can reach it.
            with urlopen(request, timeout=self.timeout) as response:  # nosec B310  # noqa: S310
                response.read()
        except HTTPError as exc:
            raise _http_error(exc) from None
        except (URLError, TimeoutError, OSError) as exc:
            logger.warning('Resend could not be reached (%s); email not sent.', type(exc).__name__)
            raise EmailNotSent('unreachable') from None


def _payload(message) -> dict:
    """The Resend request body for a Django EmailMessage."""
    if message.attachments:
        raise ValueError('ResendEmailBackend does not send attachments.')
    html = message.body if message.content_subtype == 'html' else None
    text = None if html is not None else message.body
    for content, mimetype in getattr(message, 'alternatives', []):
        if mimetype == 'text/html' and html is None:
            html = content
    payload: dict[str, object] = {
        'from': _header_value(message.from_email),
        'to': [_header_value(address) for address in message.to],
        'subject': _header_value(message.subject),
    }
    if text is not None:
        payload['text'] = text
    if html is not None:
        payload['html'] = html
    for key, addresses in (('cc', message.cc), ('bcc', message.bcc), ('reply_to', message.reply_to)):
        if addresses:
            payload[key] = [_header_value(address) for address in addresses]
    if message.extra_headers:
        payload['headers'] = {_header_value(k): _header_value(v) for k, v in message.extra_headers.items()}
    return payload


def _header_value(value) -> str:
    """Refuse CR/LF in anything that becomes an email header (Django only checks this in EmailMessage.message())."""
    text = str(value)
    if '\r' in text or '\n' in text:
        raise ValueError('Email header values cannot contain newlines.')
    return text


def _http_error(exc: HTTPError) -> EmailNotSent:
    try:
        body = json.loads(exc.read() or b'{}')
    except ValueError:
        body = {}
    name = body.get('name') if isinstance(body, dict) else None
    # From the network, so keep only short, printable text (no CR/LF log injection).
    code = ''.join(ch for ch in name[:40] if ch.isprintable()) if isinstance(name, str) else ''
    if code in QUOTA_CODES:
        logger.error('Email quota exhausted (%s): email is not being sent until the quota resets.', code)
        return EmailQuotaExceeded(code)
    if code == 'rate_limit_exceeded' or exc.code == 429:
        logger.warning('Resend rate limit reached (HTTP %s %s); email not sent.', exc.code, code)
        return EmailNotSent(code or 'rate_limited')
    if exc.code in (401, 403):
        logger.error(
            'Resend refused the request (HTTP %s %s): check RESEND_API_KEY, its permissions, and that '
            'DEFAULT_FROM_EMAIL is on a verified domain. Email is not being sent.',
            exc.code,
            code,
        )
        return EmailNotSent(code or 'unauthorized')
    if exc.code >= 500:
        logger.warning('Resend is unavailable (HTTP %s %s); email not sent.', exc.code, code)
        return EmailNotSent(code or 'unavailable')
    logger.warning('Resend rejected the email (HTTP %s %s).', exc.code, code)
    return EmailNotSent(code or f'http_{exc.code}')
