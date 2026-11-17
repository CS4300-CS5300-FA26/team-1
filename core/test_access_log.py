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
