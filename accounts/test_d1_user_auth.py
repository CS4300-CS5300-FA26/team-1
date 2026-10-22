"""Extra tests for user story D-1 (user-auth): acceptance-level behavior and security.

The accounts app's original tests live in accounts/tests.py; these add to them.
"""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

User = get_user_model()
PASSWORD = 'Tr4ining-Plan-2026!'


class RegistrationD1Tests(TestCase):
    def register(self, username='sam', email='sam@example.com', password=PASSWORD, confirm=None):
        return self.client.post(reverse('register'), {
            'username': username,
            'email': email,
            'password1': password,
            'password2': password if confirm is None else confirm,
        })

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

    # Scenario: Email already registered
    def test_duplicate_email_shows_message_and_stays_on_register_page(self):
        User.objects.create_user('first', 'sam@example.com', PASSWORD)
        response = self.register(username='second', email='sam@example.com')
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

    # Password requirements (AUTH_PASSWORD_VALIDATORS: 10+ characters, not common, not numeric)
    def test_nine_character_password_rejected(self):
        self.assertEqual(self.register(password='Abc!12345').status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_common_password_rejected(self):
        self.assertEqual(self.register(password='password123').status_code, 200)
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


class LoginD1Tests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('sam', 'sam@example.com', PASSWORD)

    def log_in(self, identifier='sam@example.com', password=PASSWORD):
        return self.client.post(reverse('login'), {'username': identifier, 'password': password})

    def test_login_with_email(self):
        self.assertRedirects(self.log_in(), reverse('home'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_login_email_is_case_insensitive(self):
        self.assertRedirects(self.log_in(' SAM@Example.com '), reverse('home'))

    def test_login_with_username_still_works(self):
        self.assertRedirects(self.log_in('sam'), reverse('home'))

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

    def test_session_key_changes_on_login(self):
        self.client.get(reverse('login'))
        key_before = self.client.session.session_key
        self.log_in()
        self.assertNotEqual(self.client.session.session_key, key_before)

    def test_login_post_requires_csrf_token(self):
        strict_client = Client(enforce_csrf_checks=True)
        response = strict_client.post(reverse('login'), {'username': 'sam@example.com', 'password': PASSWORD})
        self.assertEqual(response.status_code, 403)

    def test_password_is_not_echoed_back_on_failed_login(self):
        response = self.log_in(password='definitely-the-wrong-one')
        self.assertNotContains(response, 'definitely-the-wrong-one')