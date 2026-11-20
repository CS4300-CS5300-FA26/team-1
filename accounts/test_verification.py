"""Email confirmation on sign-up (ADR-018). Mail goes to Django's in-memory outbox; nothing reaches Resend."""

from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from core.models import UserProfile

from .emails import VERIFY_SUBJECT
from .testing import confirm_email, emails_to, link_in
from .tokens import email_verification_token

User = get_user_model()
PASSWORD = 'Tr4ining-Plan-2026!'
EMAIL = 'sam@example.com'


class ConfirmationTestCase(TestCase):
    def register(self, username='sam', email=EMAIL):
        return self.client.post(
            reverse('register'),
            {'username': username, 'email': email, 'password1': PASSWORD, 'password2': PASSWORD},
        )

    def link(self):
        return link_in(emails_to(EMAIL)[-1])


class ConfirmLinkTests(ConfirmationTestCase):
    def setUp(self):
        self.register()

    def test_opening_the_link_only_shows_a_confirm_button(self):
        # Email security scanners open links, so a GET must not confirm anything.
        response = self.client.get(self.link())
        self.assertContains(response, 'Confirm my email')
        self.assertContains(response, EMAIL)
        self.assertFalse(User.objects.get().is_active)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_confirming_activates_logs_in_and_goes_to_onboarding(self):
        self.client.get(reverse('login'))
        key_before = self.client.session.session_key
        response = self.client.post(self.link())
        self.assertRedirects(response, reverse('onboarding'), fetch_redirect_response=False)
        user = User.objects.get()
        self.assertTrue(user.is_active)
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)
        self.assertNotEqual(self.client.session.session_key, key_before)  # session fixation

    def test_then_the_password_works(self):
        self.client.post(self.link())
        self.client.logout()
        response = self.client.post(reverse('login'), {'username': EMAIL, 'password': PASSWORD})
        self.assertRedirects(response, reverse('onboarding'), fetch_redirect_response=False)

    def test_a_link_works_once(self):
        link = self.link()
        self.client.post(link)
        self.client.logout()
        response = self.client.post(link)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "This link doesn't work", status_code=400)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_a_tampered_or_unknown_link_is_refused(self):
        uid, token = self.link().split('/')[-3:-1]
        for path in (
            reverse('verify_email', args=[uid, token[:-1] + ('0' if token[-1] != '0' else '1')]),
            reverse('verify_email', args=['bm90LWEtdWlk', token]),
            reverse('verify_email', args=['!!', token]),
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path).status_code, 400)
        self.assertFalse(User.objects.get().is_active)

    def test_an_expired_link_is_refused(self):
        # Django's token generator works in naive local time (PasswordResetTokenGenerator._now).
        later = datetime.now() + timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT + 60)
        with mock.patch.object(type(email_verification_token), '_now', return_value=later):
            self.assertEqual(self.client.post(self.link()).status_code, 400)
        self.assertFalse(User.objects.get().is_active)

    def test_a_password_reset_token_does_not_confirm_an_email(self):
        user = User.objects.get()
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        response = self.client.post(reverse('verify_email', args=[uid, default_token_generator.make_token(user)]))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.get().is_active)


class UnconfirmedAccountTests(ConfirmationTestCase):
    def test_an_unconfirmed_account_cannot_log_in(self):
        self.register()
        response = self.client.post(reverse('login'), {'username': EMAIL, 'password': PASSWORD})
        self.assertContains(response, 'Invalid email or password')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_the_login_page_points_to_the_resend_and_reset_pages(self):
        response = self.client.get(reverse('login'))
        self.assertContains(response, f'href="{reverse("resend_verification")}"')
        self.assertContains(response, f'href="{reverse("password_reset")}"')


class ResendTests(ConfirmationTestCase):
    def resend(self, email=EMAIL, **extra):
        return self.client.post(reverse('resend_verification'), {'email': email}, **extra)

    def test_an_unconfirmed_sign_up_gets_a_new_link(self):
        self.register()
        response = self.resend(' SAM@Example.com ')
        self.assertRedirects(response, reverse('verify_email_sent'))
        self.assertEqual([m.subject for m in emails_to(EMAIL)], [VERIFY_SUBJECT, VERIFY_SUBJECT])
        self.assertRedirects(confirm_email(self.client, EMAIL), reverse('onboarding'), fetch_redirect_response=False)

    def test_unknown_and_confirmed_addresses_get_the_same_page_and_no_email(self):
        User.objects.create_user('ed', 'ed@example.com', PASSWORD)
        for email in ('nobody@example.com', 'ed@example.com'):
            with self.subTest(email=email):
                self.assertRedirects(self.resend(email), reverse('verify_email_sent'))
        self.assertEqual(mail.outbox, [])

    def test_a_failed_send_shows_the_generic_error(self):
        self.register()
        with mock.patch('accounts.emails.send_account_email', return_value=False):
            response = self.resend()
        self.assertContains(response, 'Something went wrong on our end', status_code=503)

    def test_requests_are_limited_per_ip(self):
        limit = settings.AUTH_THROTTLE['email_request'][0]
        for _ in range(limit):
            self.resend('nobody@example.com')
        response = self.resend('nobody@example.com')
        self.assertEqual(response.status_code, 429)
        self.assertIn('Retry-After', response)
        self.assertEqual(self.resend('nobody@example.com', REMOTE_ADDR='10.0.0.9').status_code, 302)


class ExpiredSignUpTests(ConfirmationTestCase):
    def age(self, user, seconds):
        User.objects.filter(pk=user.pk).update(date_joined=timezone.now() - timedelta(seconds=seconds))

    def test_an_expired_sign_up_frees_its_username_and_email(self):
        self.register()
        self.age(User.objects.get(), settings.PASSWORD_RESET_TIMEOUT + 60)
        mail.outbox.clear()
        self.register()
        user = User.objects.get()
        self.assertFalse(user.is_active)
        self.assertEqual([m.subject for m in mail.outbox], [VERIFY_SUBJECT])  # a new sign-up, not "already exists"
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_recent_sign_ups_and_real_accounts_are_kept(self):
        self.register()
        old = User.objects.create_user('ed', 'ed@example.com', PASSWORD)  # active
        self.age(old, settings.PASSWORD_RESET_TIMEOUT * 10)
        self.register('alex', 'alex@example.com')
        self.assertEqual(set(User.objects.values_list('username', flat=True)), {'sam', 'ed', 'alex'})


@override_settings(AUTH_THROTTLE={**settings.AUTH_THROTTLE, 'email_recipient': (1, 60 * 60)})
class RecipientLimitTests(ConfirmationTestCase):
    def test_sign_ups_count_against_the_per_address_limit(self):
        self.register()
        response = self.client.post(reverse('resend_verification'), {'email': EMAIL})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(len(mail.outbox), 1)
