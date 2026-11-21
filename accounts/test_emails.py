"""Tests for send_account_email (ADR-017). Mail goes to Django's in-memory outbox; nothing reaches Resend."""

from typing import cast
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.test import TestCase, override_settings
from django.urls import reverse

from core.mail import EmailNotSent, EmailQuotaExceeded

from .emails import _send_and_log, send_account_email
from .models import ThrottleCounter

User = get_user_model()
ADDRESS = 'sam@example.com'


class SendAccountEmailTests(TestCase):
    def test_tests_use_the_in_memory_mailer(self):
        self.assertEqual(settings.MAILERS['default']['BACKEND'], 'django.core.mail.backends.locmem.EmailBackend')
        self.assertEqual(settings.RESEND_API_KEY, '')

    def test_sends_text_and_html_from_the_default_sender(self):
        self.assertTrue(send_account_email(ADDRESS, 'Confirm your email', 'Open the link.', '<p>Open the link.</p>'))
        self.assertEqual(len(mail.outbox), 1)
        sent = cast(EmailMultiAlternatives, mail.outbox[0])
        self.assertEqual(sent.to, [ADDRESS])
        self.assertEqual(sent.from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(sent.body, 'Open the link.')
        self.assertEqual(sent.alternatives[0][1], 'text/html')

    def test_plain_text_only(self):
        self.assertTrue(send_account_email(ADDRESS, 'Hi', 'Hello'))
        self.assertEqual(cast(EmailMultiAlternatives, mail.outbox[0]).alternatives, [])

    def test_a_send_failure_returns_false(self):
        for error in (EmailQuotaExceeded('daily_quota_exceeded'), EmailNotSent('unreachable')):
            with (
                self.subTest(error=error),
                mock.patch('accounts.emails.EmailMultiAlternatives.send', side_effect=error),
            ):
                self.assertFalse(send_account_email(ADDRESS, 'Hi', 'Hello'))


class RecipientLimitTests(TestCase):
    def setUp(self):
        self.limit = settings.AUTH_THROTTLE['email_recipient'][0]

    def test_the_limit_is_five_an_hour(self):
        self.assertEqual(settings.AUTH_THROTTLE['email_recipient'], (5, 60 * 60))

    def test_an_address_gets_at_most_the_limit_per_window(self):
        for _ in range(self.limit):
            self.assertTrue(send_account_email(ADDRESS, 'Hi', 'Hello'))
        with self.assertLogs('accounts.security', 'WARNING') as logs:
            self.assertFalse(send_account_email(' SAM@Example.com ', 'Hi', 'Hello'))
        self.assertEqual(len(mail.outbox), self.limit)
        self.assertNotIn('sam', '\n'.join(logs.output).lower())

    def test_other_addresses_are_not_affected(self):
        for _ in range(self.limit):
            send_account_email(ADDRESS, 'Hi', 'Hello')
        self.assertTrue(send_account_email('alex@example.com', 'Hi', 'Hello'))

    def test_only_a_hash_of_the_address_is_stored(self):
        send_account_email(ADDRESS, 'Hi', 'Hello')
        counter = ThrottleCounter.objects.get(scope='email-recipient')
        self.assertEqual(len(counter.key), 64)
        self.assertNotIn('sam', counter.key)

    def test_failed_sends_do_not_use_up_the_limit(self):
        # PR review: five transient failures used to block the address for an hour, though the page says to try again.
        with mock.patch('accounts.emails.EmailMultiAlternatives.send', side_effect=EmailNotSent('unreachable')):
            for _ in range(self.limit + 2):
                self.assertFalse(send_account_email(ADDRESS, 'Hi', 'Hello'))
        self.assertEqual(ThrottleCounter.objects.get(scope='email-recipient').count, 0)
        self.assertTrue(send_account_email(ADDRESS, 'Hi', 'Hello'))
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(AUTH_THROTTLE={**settings.AUTH_THROTTLE, 'email_recipient': (1, 60 * 60)})
    def test_a_blocked_send_never_reaches_the_mailer(self):
        send_account_email(ADDRESS, 'Hi', 'Hello')
        with mock.patch('accounts.emails.EmailMultiAlternatives.send') as send:
            self.assertFalse(send_account_email(ADDRESS, 'Hi', 'Hello'))
        send.assert_not_called()


@override_settings(ACCOUNT_EMAIL_IN_BACKGROUND=True)
class BackgroundSendTests(TestCase):
    """PR review: forgot password and resend confirmation waited for Resend (up to 10 s) only for addresses with an
    account, so the response time revealed which addresses are registered. Requests now only queue the email."""

    def assert_only_queued(self, method, path, data):
        with (
            mock.patch('accounts.emails._background.submit') as submit,
            mock.patch('accounts.emails.send_account_email') as send,
        ):
            response = getattr(self.client, method)(path, data)
        send.assert_not_called()
        submit.assert_called_once()
        self.assertIs(submit.call_args.args[0], _send_and_log)
        self.assertEqual(submit.call_args.kwargs, {'close_db': True})
        return response

    def test_requests_never_send_during_the_response(self):
        User.objects.create_user('sam', ADDRESS, 'Tr4ining-Plan-2026!')
        User.objects.create_user('pending', 'pending@example.com', 'Tr4ining-Plan-2026!', is_active=False)
        password = 'Tr4ining-Plan-2026!'
        for name, (path, data) in {
            'forgot password': (reverse('password_reset'), {'email': ADDRESS}),
            'resend confirmation': (reverse('resend_verification'), {'email': 'pending@example.com'}),
            'sign-up, new address': (
                reverse('register'),
                {'username': 'new', 'email': 'new@example.com', 'password1': password, 'password2': password},
            ),
            'sign-up, registered address': (
                reverse('register'),
                {'username': 'other', 'email': ADDRESS, 'password1': password, 'password2': password},
            ),
        }.items():
            with self.subTest(name):
                self.assertEqual(self.assert_only_queued('post', path, data).status_code, 302)

    def test_a_background_send_logs_failures_and_closes_its_connections(self):
        with (
            mock.patch('accounts.emails.send_account_email', return_value=False),
            mock.patch('accounts.emails.connections.close_all') as close_all,
            self.assertLogs('accounts.security', 'WARNING') as logs,
        ):
            _send_and_log(ADDRESS, 'Hi', 'Hello', 'Test email', close_db=True)
        close_all.assert_called_once()
        self.assertEqual(logs.output, ['WARNING:accounts.security:Test email not sent'])

    def test_an_unexpected_error_in_the_background_is_logged_not_raised(self):
        with (
            mock.patch('accounts.emails.send_account_email', side_effect=RuntimeError('boom')),
            mock.patch('accounts.emails.connections.close_all'),
            self.assertLogs('accounts.security', 'ERROR') as logs,
        ):
            _send_and_log(ADDRESS, 'Hi', 'Hello', 'Test email', close_db=True)
        self.assertIn('Test email failed', logs.output[0])
