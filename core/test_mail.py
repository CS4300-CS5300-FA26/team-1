"""Tests for the Resend email backend (ADR-017). Every HTTP call is mocked; nothing here reaches Resend."""

import io
import json
from unittest import mock
from urllib.error import HTTPError, URLError

from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.test import SimpleTestCase

from .mail import SEND_URL, USER_AGENT, EmailNotSent, EmailQuotaExceeded, ResendEmailBackend

API_KEY = 're_test_not_a_real_key'
SENDER = 'FitPro <no-reply@fitpro-app.tech>'
RECIPIENT = 'delivered+fitpro@resend.dev'


def message(**kwargs):
    defaults = {'subject': 'Confirm your email', 'body': 'Open the link.', 'from_email': SENDER, 'to': [RECIPIENT]}
    return EmailMultiAlternatives(**(defaults | kwargs))


def http_error(status, name=None, body=None):
    raw = body if body is not None else json.dumps({'statusCode': status, 'name': name, 'message': 'x'}).encode()
    return HTTPError(SEND_URL, status, 'error', None, io.BytesIO(raw))  # type: ignore[arg-type]


class ResendBackendTestCase(SimpleTestCase):
    def setUp(self):
        self.backend = ResendEmailBackend(api_key=API_KEY)
        patcher = mock.patch('core.mail.urlopen')
        self.urlopen = patcher.start()
        self.addCleanup(patcher.stop)
        self.urlopen.return_value.__enter__.return_value.read.return_value = b'{"id": "49a3999c"}'

    def sent_request(self):
        self.urlopen.assert_called_once()
        request = self.urlopen.call_args.args[0]
        return request, json.loads(request.data)


class SendTests(ResendBackendTestCase):
    def test_sends_one_post_to_the_resend_api(self):
        self.assertEqual(self.backend.send_messages([message()]), 1)
        request, payload = self.sent_request()
        self.assertEqual(request.full_url, SEND_URL)
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.get_header('Authorization'), f'Bearer {API_KEY}')
        self.assertEqual(request.get_header('Content-type'), 'application/json')
        self.assertEqual(request.get_header('User-agent'), USER_AGENT)
        self.assertEqual(self.urlopen.call_args.kwargs['timeout'], 10)
        self.assertEqual(
            payload, {'from': SENDER, 'to': [RECIPIENT], 'subject': 'Confirm your email', 'text': 'Open the link.'}
        )

    def test_sends_html_with_its_plain_text_version(self):
        email = message()
        email.attach_alternative('<p>Open the <a href="https://fitpro-app.tech/">link</a>.</p>', 'text/html')
        self.backend.send_messages([email])
        _, payload = self.sent_request()
        self.assertEqual(payload['text'], 'Open the link.')
        self.assertIn('<a href="https://fitpro-app.tech/">', payload['html'])

    def test_an_html_only_message_sends_no_text_field(self):
        email = EmailMessage('Hi', '<p>Hi</p>', SENDER, [RECIPIENT])
        email.content_subtype = 'html'
        self.backend.send_messages([email])
        _, payload = self.sent_request()
        self.assertEqual(payload['html'], '<p>Hi</p>')
        self.assertNotIn('text', payload)

    def test_cc_bcc_reply_to_and_headers_are_passed_on(self):
        email = message(
            cc=['cc@resend.dev'], bcc=['bcc@resend.dev'], reply_to=['help@fitpro-app.tech'], headers={'X-Tag': 'a'}
        )
        self.backend.send_messages([email])
        _, payload = self.sent_request()
        self.assertEqual(payload['cc'], ['cc@resend.dev'])
        self.assertEqual(payload['bcc'], ['bcc@resend.dev'])
        self.assertEqual(payload['reply_to'], ['help@fitpro-app.tech'])
        self.assertEqual(payload['headers'], {'X-Tag': 'a'})

    def test_the_idempotency_key_follows_the_content(self):
        keys = []
        for body in ('one', 'one', 'two'):
            self.urlopen.reset_mock()
            self.backend.send_messages([message(body=body)])
            keys.append(self.sent_request()[0].get_header('Idempotency-key'))
        self.assertEqual(keys[0], keys[1])
        self.assertNotEqual(keys[0], keys[2])
        self.assertTrue(keys[0].startswith('fitpro/'))
        self.assertLessEqual(len(keys[0]), 256)

    def test_nothing_to_send(self):
        self.assertEqual(self.backend.send_messages([]), 0)
        self.urlopen.assert_not_called()


class RefusedMessageTests(ResendBackendTestCase):
    def test_newlines_in_header_values_are_refused_before_sending(self):
        for email in (
            message(subject='Hi\r\nBcc: attacker@resend.dev'),
            message(to=['a@resend.dev\nBcc: b@resend.dev']),
            message(headers={'X-Tag': 'a\r\nBcc: b@resend.dev'}),
        ):
            with self.subTest(email=email), self.assertRaises(ValueError):
                self.backend.send_messages([email])
        self.urlopen.assert_not_called()

    def test_attachments_are_refused(self):
        email = message()
        email.attach('plan.txt', 'hello', 'text/plain')
        with self.assertRaises(ValueError):
            self.backend.send_messages([email])
        self.urlopen.assert_not_called()


class FailureTests(ResendBackendTestCase):
    def assert_logs_no_secrets(self, logs):
        text = '\n'.join(logs.output)
        for secret in (API_KEY, RECIPIENT, 'Confirm your email', 'Open the link.'):
            self.assertNotIn(secret, text)

    def test_an_exhausted_quota_is_logged_as_an_error(self):
        for code in ('daily_quota_exceeded', 'monthly_quota_exceeded'):
            self.urlopen.side_effect = http_error(429, code)
            with (
                self.subTest(code=code),
                self.assertLogs('fitpro.email', 'ERROR') as logs,
                self.assertRaises(EmailQuotaExceeded) as raised,
            ):
                self.backend.send_messages([message()])
            self.assertEqual(raised.exception.code, code)
            self.assertIn(f'Email quota exhausted ({code})', logs.output[0])
            self.assert_logs_no_secrets(logs)

    def test_the_per_second_rate_limit_is_not_reported_as_the_quota(self):
        self.urlopen.side_effect = http_error(429, 'rate_limit_exceeded')
        with self.assertLogs('fitpro.email', 'WARNING') as logs, self.assertRaises(EmailNotSent) as raised:
            self.backend.send_messages([message()])
        self.assertNotIsInstance(raised.exception, EmailQuotaExceeded)
        self.assertEqual(raised.exception.code, 'rate_limit_exceeded')
        self.assertIn('rate limit', logs.output[0])
        self.assertNotIn('quota', logs.output[0])

    def test_a_rejected_key_or_sender_points_at_the_configuration(self):
        for status, code in ((401, 'missing_api_key'), (403, 'validation_error')):
            self.urlopen.side_effect = http_error(status, code)
            with (
                self.subTest(status=status),
                self.assertLogs('fitpro.email', 'ERROR') as logs,
                self.assertRaises(EmailNotSent),
            ):
                self.backend.send_messages([message()])
            self.assertIn('RESEND_API_KEY', logs.output[0])
            self.assert_logs_no_secrets(logs)

    def test_server_errors_and_bad_requests_raise(self):
        for status, code in ((500, 'application_error'), (503, 'service_unavailable'), (422, 'invalid_parameter')):
            self.urlopen.side_effect = http_error(status, code)
            with (
                self.subTest(status=status),
                self.assertLogs('fitpro.email', 'WARNING'),
                self.assertRaises(EmailNotSent) as raised,
            ):
                self.backend.send_messages([message()])
            self.assertEqual(raised.exception.code, code)

    def test_an_error_body_that_is_not_json(self):
        self.urlopen.side_effect = http_error(502, body=b'<html>Bad gateway</html>')
        with self.assertLogs('fitpro.email', 'WARNING'), self.assertRaises(EmailNotSent) as raised:
            self.backend.send_messages([message()])
        self.assertEqual(raised.exception.code, 'unavailable')

    def test_error_codes_from_the_network_cannot_inject_log_lines(self):
        self.urlopen.side_effect = http_error(429, 'daily_quota_exceeded\nFAKE LOG LINE')
        with self.assertLogs('fitpro.email', 'WARNING') as logs, self.assertRaises(EmailNotSent):
            self.backend.send_messages([message()])
        self.assertNotIn('\n', logs.output[0])

    def test_network_failures_and_timeouts(self):
        for error in (URLError('no route'), TimeoutError()):
            self.urlopen.side_effect = error
            with (
                self.subTest(error=error),
                self.assertLogs('fitpro.email', 'WARNING'),
                self.assertRaises(EmailNotSent) as raised,
            ):
                self.backend.send_messages([message()])
            self.assertEqual(raised.exception.code, 'unreachable')

    def test_a_missing_key_fails_every_send_without_calling_resend(self):
        with self.assertLogs('fitpro.email', 'ERROR') as logs, self.assertRaises(EmailNotSent) as raised:
            ResendEmailBackend(api_key='').send_messages([message()])
        self.assertEqual(raised.exception.code, 'not_configured')
        self.assertIn('RESEND_API_KEY', logs.output[0])
        self.urlopen.assert_not_called()
