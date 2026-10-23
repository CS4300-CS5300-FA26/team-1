"""Tests for user story D-1 (user-auth): registration, login, and logout.

The Gherkin scenarios for this story are in features/user_auth.feature. The redirect to
the onboarding questionnaire after login is tested in core/test_onboarding.py.
"""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from core.models import UserProfile

from .forms import LoginForm

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
        response = self.log_in(next='/admin/')
        self.assertRedirects(response, '/admin/', fetch_redirect_response=False)

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
