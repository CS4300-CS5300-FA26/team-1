"""Gunicorn's access logger, with account link tokens redacted (ADR-018). Set as `logger_class` in gunicorn.conf.py.

Imported only by Gunicorn, which doesn't run on Windows; Django never imports this module.
"""

from gunicorn.glogging import Logger

from .log_redaction import redact_account_tokens

# Every atom that can hold the request path or a URL: the path and request line, the referrer (pages opened from a
# link send it as their Referer), and the same values reachable as {header}i and {environ}e atoms.
_URL_ATOMS = ('U', 'r', 'f', '{referer}i', '{path_info}e', '{raw_uri}e', '{http_referer}e')


class RedactingLogger(Logger):
    def atoms(self, resp, req, environ, request_time):
        atoms = super().atoms(resp, req, environ, request_time)
        for key in _URL_ATOMS:
            value = atoms.get(key)
            if isinstance(value, str):
                atoms[key] = redact_account_tokens(value)
        return atoms
