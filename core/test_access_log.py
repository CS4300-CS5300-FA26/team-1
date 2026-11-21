"""The production access log must not record query strings (gunicorn.conf.py, ADR-010).

Spotify's OAuth callback carries a one-time `code` and the `state` in its query string, and the access log goes to
Cloud Logging. Gunicorn's default format logs both, through the request line `%(r)s` and the referrer `%(f)s`.
"""

import importlib.util
import runpy
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import skipUnless

from django.conf import settings
from django.test import SimpleTestCase

CONFIG = runpy.run_path(str(Path(settings.BASE_DIR) / 'gunicorn.conf.py'))
CODE, STATE = 'AQDsecretOneTimeCode', 'secretState123'
PATH = '/auth-callback/spotify'
QUERY = f'code={CODE}&state={STATE}'
LEAKS = ('?', CODE, STATE)


class AccessLogFormatTests(SimpleTestCase):
    def test_access_log_goes_to_stdout(self):
        self.assertEqual(CONFIG['accesslog'], '-')

    def test_the_spotify_callback_is_logged_without_its_query_string(self):
        # The values Gunicorn fills each atom with for this request (glogging.Logger.atoms).
        atoms = defaultdict(
            lambda: '-',
            h='10.0.0.1',
            t='[09/Nov/2026:20:00:00 +0000]',
            r=f'GET {PATH}?{QUERY} HTTP/1.1',
            m='GET',
            U=PATH,
            q=QUERY,
            H='HTTP/1.1',
            s='302',
            b='0',
            f=f'https://fitpro.example.com{PATH}?{QUERY}',
            a='Mozilla/5.0',
        )
        line = CONFIG['access_log_format'] % atoms
        self.assertIn(f'"GET {PATH} HTTP/1.1" 302', line)
        for secret in LEAKS:
            self.assertNotIn(secret, line)

    @skipUnless(importlib.util.find_spec('fcntl'), "Gunicorn can't be imported on Windows; CI runs this on Linux")
    def test_gunicorns_own_logger_leaves_the_query_string_out(self):
        from gunicorn.glogging import Logger

        response = SimpleNamespace(status='302 Found', status_code=302, sent=0, response_length=0, headers=[])
        request = SimpleNamespace(headers=[('REFERER', f'https://fitpro.example.com{PATH}?{QUERY}')])
        environ = {
            'REQUEST_METHOD': 'GET',
            'RAW_URI': f'{PATH}?{QUERY}',
            'PATH_INFO': PATH,
            'QUERY_STRING': QUERY,
            'SERVER_PROTOCOL': 'HTTP/1.1',
            'REMOTE_ADDR': '10.0.0.1',
            'HTTP_REFERER': f'https://fitpro.example.com{PATH}?{QUERY}',
            'HTTP_USER_AGENT': 'Mozilla/5.0',
        }
        logger = Logger.__new__(Logger)  # atoms() needs no logging handlers
        logger.cfg = SimpleNamespace(env={})
        atoms = logger.atoms(response, request, environ, timedelta(milliseconds=5))

        self.assertIn(QUERY, atoms['r'])  # the default format would have logged it
        line = CONFIG['access_log_format'] % atoms
        self.assertIn(f'"GET {PATH} HTTP/1.1" 302', line)
        for secret in LEAKS:
            self.assertNotIn(secret, line)


# Email confirmation and password reset links carry a one-time token in the path (ADR-018, PR review).
UID, TOKEN = 'MQ', 'd3f8k2-7c1e0b9a4f6d2e8c5b3a1f0e9d7c6b5a'
TOKEN_PATHS = (f'/accounts/verify/{UID}/{TOKEN}/', f'/accounts/password/reset/{UID}/{TOKEN}/')
SAFE_PATHS = (
    '/accounts/verify/sent/',
    '/accounts/verify/resend/',
    '/accounts/password/reset/',
    '/accounts/password/reset/sent/',
    '/accounts/password/reset/done/',
    '/plans/this-week/',
)


class TokenRedactionTests(SimpleTestCase):
    def test_tokens_in_account_links_are_redacted(self):
        from fitpro.log_redaction import redact_account_tokens

        for path in (*TOKEN_PATHS, f'/accounts/password/reset/{UID}/set-password/'):
            with self.subTest(path=path):
                redacted = redact_account_tokens(f'GET {path} HTTP/1.1')
                self.assertNotIn(TOKEN, redacted)
                self.assertNotIn(f'/{UID}/', redacted)
                self.assertIn('[redacted]', redacted)

    def test_other_paths_are_left_alone(self):
        from fitpro.log_redaction import redact_account_tokens

        for path in SAFE_PATHS:
            with self.subTest(path=path):
                self.assertEqual(redact_account_tokens(f'GET {path} HTTP/1.1'), f'GET {path} HTTP/1.1')

    def test_django_error_logs_are_redacted(self):
        # Django logs "Internal Server Error: <path>" for a 500, so a failure on a valid link would log its token.
        import logging

        from fitpro.log_redaction import RedactAccountTokens

        record = logging.LogRecord('django.request', logging.ERROR, __file__, 1, '%s: %s', None, None)
        record.args = ('Internal Server Error', TOKEN_PATHS[0])
        self.assertTrue(RedactAccountTokens().filter(record))
        self.assertNotIn(TOKEN, record.getMessage())

    def test_the_console_handler_uses_the_filter(self):
        import logging

        from fitpro.log_redaction import RedactAccountTokens

        logging_config: dict = settings.LOGGING
        self.assertEqual(logging_config['handlers']['console']['filters'], ['redact_account_tokens'])
        handlers = [
            h for h in logging.getLogger().handlers if any(isinstance(f, RedactAccountTokens) for f in h.filters)
        ]
        self.assertTrue(handlers, 'settings.LOGGING should attach the filter to the root console handler')

    def test_gunicorn_uses_the_redacting_logger(self):
        self.assertEqual(CONFIG['logger_class'], 'fitpro.gunicorn_logging.RedactingLogger')

    @skipUnless(importlib.util.find_spec('fcntl'), "Gunicorn can't be imported on Windows; CI runs this on Linux")
    def test_the_access_log_never_holds_a_token(self):
        from fitpro.gunicorn_logging import RedactingLogger

        for path in TOKEN_PATHS:
            referer = f'https://fitpro-app.tech{path}'  # pages opened from the link send it as their Referer
            response = SimpleNamespace(status='200 OK', status_code=200, sent=0, response_length=0, headers=[])
            request = SimpleNamespace(headers=[('REFERER', referer)])
            environ = {
                'REQUEST_METHOD': 'GET',
                'RAW_URI': path,
                'PATH_INFO': path,
                'QUERY_STRING': '',
                'SERVER_PROTOCOL': 'HTTP/1.1',
                'REMOTE_ADDR': '10.0.0.1',
                'HTTP_REFERER': referer,
                'HTTP_USER_AGENT': 'Mozilla/5.0',
            }
            logger = RedactingLogger.__new__(RedactingLogger)  # atoms() needs no logging handlers
            logger.cfg = SimpleNamespace(env={})
            atoms = logger.atoms(response, request, environ, timedelta(milliseconds=5))
            with self.subTest(path=path):
                line = CONFIG['access_log_format'] % atoms
                self.assertIn('[redacted]', line)
                for key in ('U', 'r', 'f', '{referer}i', '{path_info}e', '{raw_uri}e', '{http_referer}e'):
                    self.assertNotIn(TOKEN, atoms[key], key)
