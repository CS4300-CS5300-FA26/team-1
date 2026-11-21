"""Keep the one-time tokens in emailed account links out of the logs (ADR-018).

Confirmation and password reset links carry a bearer token in the URL path:
/accounts/verify/<uid>/<token>/ and /accounts/password/reset/<uid>/<token>/. Anyone holding one can confirm the
account or choose its password, so neither segment may reach Cloud Logging. Gunicorn's access log goes through
`fitpro.gunicorn_logging.RedactingLogger`, and Django's own log records through `RedactAccountTokens`
(settings.LOGGING).

Pure Python, with no Gunicorn import, so Django can load it on any platform.
"""

import logging
import re

REDACTED = '[redacted]'
# The two path segments after either prefix: the user id and the token (or Django's "set-password" step).
_TOKEN_PATH = re.compile(r'(/accounts/(?:verify|password/reset)/)[^/?#\s"]+/[^/?#\s"]+')


def redact_account_tokens(text: str) -> str:
    """`text` with the uid and token of any confirmation or reset link replaced."""
    return _TOKEN_PATH.sub(rf'\g<1>{REDACTED}', text)


class RedactAccountTokens(logging.Filter):
    """Redact account link tokens from a log record's message and arguments.

    Django logs the request path for 4xx and 5xx responses ("Internal Server Error: /accounts/verify/..."), and a
    server error on a valid link would otherwise log a usable token.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_account_tokens(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact_account_tokens(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: redact_account_tokens(v) if isinstance(v, str) else v for k, v in record.args.items()}
        return True
