"""Tests for send_account_email (ADR-017). Mail goes to Django's in-memory outbox; nothing reaches Resend."""

from typing import cast
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.test import TestCase, override_settings

from core.mail import EmailNotSent, EmailQuotaExceeded

from .emails import EMAIL_NOT_SENT_MESSAGE, send_account_email
from .models import ThrottleCounter

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

    def test_the_user_facing_message_names_no_cause(self):
        for word in ('quota', 'Resend', 'limit', 'account'):
            self.assertNotIn(word.lower(), EMAIL_NOT_SENT_MESSAGE.lower())


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

    @override_settings(AUTH_THROTTLE={**settings.AUTH_THROTTLE, 'email_recipient': (1, 60 * 60)})
    def test_a_blocked_send_never_reaches_the_mailer(self):
        send_account_email(ADDRESS, 'Hi', 'Hello')
        with mock.patch('accounts.emails.EmailMultiAlternatives.send') as send:
            self.assertFalse(send_account_email(ADDRESS, 'Hi', 'Hello'))
        send.assert_not_called()
