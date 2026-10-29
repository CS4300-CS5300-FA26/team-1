"""Tests for user story D-1 (user-auth): registration, login, and logout.

The Gherkin scenarios for this story are in features/user_auth.feature. The redirect to
the onboarding questionnaire after login is tested in core/test_onboarding.py.
"""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import UserProfile

from .forms import LoginForm, RegisterForm
from .models import ThrottleEvent

User = get_user_model()
PASSWORD = 'Tr4ining-Plan-2026!'


class RegisterTests(TestCase):
    def register(self, username='sam', email='sam@example.com', password=PASSWORD, confirm=None):
        return self.client.post(reverse('register'), {
            'username': username,
            'email': email,
            'password1': password,
            'password2': password if confirm is None else confirm,
        })

    def test_register_page_renders(self):
        response = self.client.get(reverse('register'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create your account')

    # Scenario: Successful registration
    def test_registration_logs_in_and_goes_to_onboarding(self):
        response = self.register()
        self.assertRedirects(response, reverse('onboarding'))
        user = User.objects.get(username='sam')
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_password_is_hashed_not_stored_in_plain_text(self):
        self.register()
        user = User.objects.get(username='sam')
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))

    def test_email_is_stored_lowercase_and_trimmed(self):
        self.register(email='  Sam@Example.COM ')
        self.assertEqual(User.objects.get(username='sam').email, 'sam@example.com')

    def test_session_key_changes_on_registration(self):
        self.client.get(reverse('register'))
        key_before = self.client.session.session_key
        self.register()
        self.assertNotEqual(self.client.session.session_key, key_before)

    def test_logged_in_user_is_redirected_away(self):
        self.client.force_login(User.objects.create_user('ed', 'ed@example.com', PASSWORD))
        self.assertRedirects(self.client.get(reverse('register')), reverse('home'))

    # Scenario: Email already registered
    def test_duplicate_email_rejected_case_insensitively(self):
        User.objects.create_user('first', 'sam@example.com', PASSWORD)
        response = self.register(username='second', email='SAM@example.com')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/register.html')
        self.assertContains(response, 'already exists')
        self.assertFalse(User.objects.filter(username='second').exists())
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_database_rejects_duplicate_email_if_form_check_is_bypassed(self):
        # Two sign-ups racing past clean_email(): the unique index must stop the second one.
        User.objects.create_user('first', 'sam@example.com', PASSWORD)
        with mock.patch.object(RegisterForm, 'clean_email', lambda self: self.cleaned_data['email'].lower()):
            response = self.register(username='second', email='SAM@example.com')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertFalse(User.objects.filter(username='second').exists())
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_database_enforces_unique_email_case_insensitively(self):
        User.objects.create_user('first', 'sam@example.com', PASSWORD)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user('second', 'SAM@Example.com', PASSWORD)

    def test_blank_emails_do_not_collide(self):
        User.objects.create_user('a', '', PASSWORD)
        User.objects.create_user('b', '', PASSWORD)

    # Email format (format only: we do not verify that the address is real)
    def test_invalid_email_rejected(self):
        bad_emails = ['not-an-email', 'missing-at.example.com', '@example.com', 'sam@', 'sam@@example.com', 'sam example@x.com']
        for email in bad_emails:
            with self.subTest(email=email):
                response = self.register(email=email)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, 'accounts/register.html')
                self.assertFormError(response.context['form'], 'email', 'Enter a valid email address.')
                self.assertFalse(User.objects.exists())
                self.assertNotIn('_auth_user_id', self.client.session)

    def test_blank_email_rejected(self):
        response = self.register(email='')
        self.assertFormError(response.context['form'], 'email', 'This field is required.')
        self.assertFalse(User.objects.exists())

    def test_password_mismatch_rejected(self):
        self.assertEqual(self.register(confirm='something-else-entirely-1').status_code, 200)
        self.assertFalse(User.objects.exists())

    # Password requirements (AUTH_PASSWORD_VALIDATORS: 10+ characters, not common, not numeric)
    def test_nine_character_password_rejected(self):
        self.assertEqual(self.register(password='Abc!12345').status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_common_password_rejected(self):
        self.assertEqual(self.register(password='password123').status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_numeric_password_rejected(self):
        self.assertEqual(self.register(password='4815162342108').status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_password_too_similar_to_email_rejected(self):
        self.register(username='tp', email='trainingplan@example.com', password='trainingplan@example.com')
        self.assertFalse(User.objects.exists())

    # Usernames may not look like emails (keeps "log in with email" unambiguous)
    def test_username_containing_at_sign_rejected(self):
        response = self.register(username='victim@example.com', email='attacker@example.com')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_register_post_requires_csrf_token(self):
        strict_client = Client(enforce_csrf_checks=True)
        response = strict_client.post(reverse('register'), {
            'username': 'sam', 'email': 'sam@example.com', 'password1': PASSWORD, 'password2': PASSWORD,
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.exists())


class LoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('sam', 'sam@example.com', PASSWORD)
        # These tests are about logging in as a returning user, so onboarding is done.
        UserProfile.objects.create(user=self.user, onboarding_completed=True)

    def log_in(self, identifier='sam@example.com', password=PASSWORD, **extra):
        return self.client.post(reverse('login'), {'username': identifier, 'password': password, **extra})

    def test_login_page_renders(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Log in')

    def test_login_with_email(self):
        self.assertRedirects(self.log_in(), reverse('dashboard'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_login_email_is_case_insensitive(self):
        self.assertRedirects(self.log_in(' SAM@Example.com '), reverse('dashboard'))

    def test_login_with_username_still_works(self):
        self.assertRedirects(self.log_in('sam'), reverse('dashboard'))

    def test_login_with_email_longer_than_a_username(self):
        # User.username allows 150 characters, User.email allows 254.
        long_email = f"{'a' * 200}@example.com"
        user = User.objects.create_user('longmail', long_email, PASSWORD)
        UserProfile.objects.create(user=user, onboarding_completed=True)
        self.assertRedirects(self.log_in(long_email), reverse('dashboard'))
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_login_field_allows_an_email_length_value(self):
        # The browser enforces maxlength, so a 150 here would block long emails client-side.
        field = LoginForm().fields['username']
        self.assertEqual(field.max_length, 254)
        self.assertEqual(field.widget.attrs['maxlength'], 254)

    def test_login_honours_safe_next(self):
        response = self.log_in(next='/users/')
        self.assertRedirects(response, '/users/', fetch_redirect_response=False)

    def test_login_ignores_external_next(self):
        self.assertRedirects(self.log_in(next='https://evil.example.com/'), reverse('dashboard'))

    # Scenario: Wrong password
    def test_wrong_password_shows_generic_error_and_stays_logged_out(self):
        response = self.log_in(password='definitely-the-wrong-one')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/login.html')
        self.assertContains(response, 'Invalid email or password')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_unknown_email_gives_the_same_error_as_wrong_password(self):
        wrong_password = self.log_in(password='definitely-the-wrong-one')
        unknown_email = self.log_in('nobody@example.com')
        self.assertContains(unknown_email, 'Invalid email or password')
        self.assertEqual(
            wrong_password.context['form'].non_field_errors(),
            unknown_email.context['form'].non_field_errors(),
        )

    def test_inactive_account_gets_the_same_generic_error(self):
        self.user.is_active = False
        self.user.save()
        self.assertContains(self.log_in(), 'Invalid email or password')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_password_is_not_echoed_back_on_failed_login(self):
        response = self.log_in(password='definitely-the-wrong-one')
        self.assertNotContains(response, 'definitely-the-wrong-one')

    def test_session_key_changes_on_login(self):
        self.client.get(reverse('login'))
        key_before = self.client.session.session_key
        self.log_in()
        self.assertNotEqual(self.client.session.session_key, key_before)

    def test_login_post_requires_csrf_token(self):
        strict_client = Client(enforce_csrf_checks=True)
        response = strict_client.post(reverse('login'), {'username': 'sam@example.com', 'password': PASSWORD})
        self.assertEqual(response.status_code, 403)


class LogoutTests(TestCase):
    def test_logout_requires_post_and_clears_session(self):
        self.client.force_login(User.objects.create_user('sam', 'sam@example.com', PASSWORD))
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        response = self.client.post(reverse('logout'))
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)


class LoginThrottleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('sam', 'sam@example.com', PASSWORD)
        UserProfile.objects.create(user=self.user, onboarding_completed=True)

    def log_in(self, identifier='sam@example.com', password='wrong-password-123', **extra):
        return self.client.post(reverse('login'), {'username': identifier, 'password': password}, **extra)

    def fail_times(self, count, **kwargs):
        for _ in range(count):
            self.assertEqual(self.log_in(**kwargs).status_code, 200)

    def test_locks_out_after_too_many_failures_even_with_the_right_password(self):
        self.fail_times(5)
        response = self.log_in(password=PASSWORD)
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, 'Too many attempts', status_code=429)
        self.assertIn('Retry-After', response)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_lockout_is_case_and_whitespace_insensitive(self):
        self.fail_times(5)
        self.assertEqual(self.log_in(' SAM@example.com ', PASSWORD).status_code, 429)

    def test_lockout_expires_after_the_window(self):
        self.fail_times(5)
        ThrottleEvent.objects.update(created_at=timezone.now() - timedelta(minutes=16))
        self.assertEqual(self.log_in(password=PASSWORD).status_code, 302)

    def test_lockout_does_not_apply_to_other_ips(self):
        self.fail_times(5, REMOTE_ADDR='10.0.0.1')
        self.assertEqual(self.log_in(password=PASSWORD, REMOTE_ADDR='10.0.0.2').status_code, 302)

    def test_successful_login_resets_the_counter(self):
        self.fail_times(4)
        self.assertEqual(self.log_in(password=PASSWORD).status_code, 302)
        self.client.post(reverse('logout'))
        self.fail_times(4)

    def test_one_ip_is_blocked_after_spraying_many_identifiers(self):
        for i in range(20):
            self.log_in(f'user{i}@example.com')
        self.assertEqual(self.log_in('another@example.com').status_code, 429)

    def test_throttle_table_stores_hashes_not_identifiers(self):
        self.log_in()
        for event in ThrottleEvent.objects.all():
            self.assertEqual(len(event.key), 64)
            self.assertNotIn('sam', event.key)

    def test_forged_forwarded_for_entries_cannot_dodge_the_limit(self):
        # Only the second-to-last X-Forwarded-For entry (added by the load balancer) is trusted.
        with override_settings(BEHIND_HTTPS_PROXY=True):
            for i in range(5):
                self.log_in(HTTP_X_FORWARDED_FOR=f'6.6.6.{i}, 9.9.9.9, 130.211.0.1')
            self.assertEqual(
                self.log_in(password=PASSWORD, HTTP_X_FORWARDED_FOR='1.2.3.4, 9.9.9.9, 130.211.0.1').status_code, 429)


class RegisterThrottleTests(TestCase):
    def register(self, n, **extra):
        return self.client.post(reverse('register'), {
            'username': f'user{n}', 'email': f'user{n}@example.com', 'password1': 'x', 'password2': 'x',
        }, **extra)

    def test_registration_attempts_are_limited_per_ip(self):
        for n in range(10):
            self.assertEqual(self.register(n).status_code, 200)
        response = self.register(11)
        self.assertEqual(response.status_code, 429)
        self.assertIn('Retry-After', response)
        self.assertEqual(self.register(12, REMOTE_ADDR='10.0.0.9').status_code, 200)

    def test_viewing_the_form_is_not_counted(self):
        for _ in range(15):
            self.assertEqual(self.client.get(reverse('register')).status_code, 200)
