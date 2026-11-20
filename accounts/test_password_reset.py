"""Password reset (ADR-018). Mail goes to Django's in-memory outbox; nothing reaches Resend."""

from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.models import UserProfile
from spotify.models import SpotifyAccount
from spotify.testing import TEST_SETTINGS

from .emails import RESET_SUBJECT
from .testing import emails_to, link_in

User = get_user_model()
OLD_PASSWORD = 'Tr4ining-Plan-2026!'
NEW_PASSWORD = 'Squat-Bench-Dead-2027?'
EMAIL = 'sam@example.com'


class ResetTestCase(TestCase):
    def make_user(self, active=True, password=OLD_PASSWORD):
        user = User.objects.create_user('sam', EMAIL, password, is_active=active)
        if password is None:
            user.set_unusable_password()
            user.save()
        UserProfile.objects.create(user=user, onboarding_completed=True)
        return user

    def request_reset(self, email=EMAIL, **extra):
        return self.client.post(reverse('password_reset'), {'email': email}, **extra)

    def reset(self, client=None, password=NEW_PASSWORD):
        """Open the newest reset link and choose a new password. Returns the final response."""
        client = client or self.client
        form_url = client.get(link_in(emails_to(EMAIL)[-1]))['Location']  # Django moves the token into the session
        return client.post(form_url, {'new_password1': password, 'new_password2': password})


class RequestTests(ResetTestCase):
    def test_an_account_gets_a_reset_link(self):
        self.make_user()
        response = self.request_reset(' SAM@Example.com ')
        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual([(m.to, m.subject) for m in mail.outbox], [([EMAIL], RESET_SUBJECT)])
        self.assertIn('/accounts/password/reset/', mail.outbox[0].body)
        self.assertIn('sam', mail.outbox[0].body)

    def test_an_unknown_address_gets_the_same_page_and_no_email(self):
        response = self.request_reset('nobody@example.com')
        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(mail.outbox, [])

    def test_a_failed_send_gets_the_usual_page_and_is_logged(self):
        self.make_user()
        with (
            mock.patch('accounts.emails.send_account_email', return_value=False),
            self.assertLogs('accounts.security', 'WARNING') as logs,
        ):
            response = self.request_reset()
        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertIn('not sent', logs.output[0])
        self.assertNotIn(EMAIL, logs.output[0])

    def test_a_used_up_recipient_limit_does_not_reveal_the_account(self):
        # PR review: an address with an account answered 503 once its limit was used up, while an unknown address got
        # the normal page, so tripping the limit told an attacker which addresses have accounts.
        self.make_user()
        for _ in range(settings.AUTH_THROTTLE['email_recipient'][0]):
            self.request_reset()
        registered, unknown = self.request_reset(), self.request_reset('nobody@example.com')
        self.assertEqual((registered.status_code, registered['Location']), (unknown.status_code, unknown['Location']))
        self.assertEqual(self.client.get(registered['Location']).content, self.client.get(unknown['Location']).content)

    def test_requests_are_limited_per_ip(self):
        for _ in range(settings.AUTH_THROTTLE['email_request'][0]):
            self.request_reset('nobody@example.com')
        response = self.request_reset('nobody@example.com')
        self.assertEqual(response.status_code, 429)
        self.assertIn('Retry-After', response)

    def test_an_invalid_address_is_a_form_error(self):
        response = self.request_reset('not-an-email')
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'email', 'Enter a valid email address.')


class ResetTests(ResetTestCase):
    def test_choosing_a_new_password(self):
        self.make_user()
        self.request_reset()
        response = self.reset()
        self.assertRedirects(response, reverse('password_reset_complete'))
        user = User.objects.get()
        self.assertTrue(user.check_password(NEW_PASSWORD))
        self.assertFalse(user.check_password(OLD_PASSWORD))
        login = self.client.post(reverse('login'), {'username': EMAIL, 'password': NEW_PASSWORD})
        self.assertRedirects(login, reverse('dashboard'), fetch_redirect_response=False)

    def test_a_link_works_once(self):
        self.make_user()
        self.request_reset()
        self.reset()
        response = Client().get(link_in(emails_to(EMAIL)[-1]))
        self.assertContains(response, "This link doesn't work")

    def test_other_sessions_are_signed_out(self):
        user = self.make_user()
        elsewhere = Client()
        elsewhere.force_login(user)
        self.request_reset()
        self.reset()
        self.assertRedirects(elsewhere.get(reverse('dashboard')), f'{reverse("login")}?next={reverse("dashboard")}')

    def test_the_new_password_must_meet_the_rules(self):
        self.make_user()
        self.request_reset()
        response = self.reset(password='password')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.get().check_password(OLD_PASSWORD))

    def test_a_spotify_only_account_can_set_a_password(self):
        self.make_user(password=None)
        self.request_reset()
        self.reset()
        self.assertTrue(User.objects.get().check_password(NEW_PASSWORD))


@override_settings(**TEST_SETTINGS)  # an encryption key, so a Spotify link can be stored
class ClaimUnconfirmedAccountTests(ResetTestCase):
    """Someone signs up with a victim's address (for example through Spotify, whose emails aren't verified), and the
    victim recovers the account with a password reset. Only the inbox owner may keep access."""

    def link_spotify(self, user):
        return SpotifyAccount.objects.create(
            user=user, spotify_id='attacker', display_name='x', access_token='a', refresh_token='r'
        )

    def test_a_reset_confirms_the_email_and_removes_the_spotify_link(self):
        user = self.make_user(active=False, password=None)
        self.link_spotify(user)
        self.request_reset()
        with self.assertLogs('accounts.security', 'WARNING') as logs:
            self.assertRedirects(self.reset(), reverse('password_reset_complete'))
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password(NEW_PASSWORD))
        self.assertFalse(SpotifyAccount.objects.exists())
        self.assertIn('Spotify link was removed', logs.output[0])

    def test_a_confirmed_account_keeps_its_spotify_link(self):
        self.link_spotify(self.make_user())
        self.request_reset()
        self.reset()
        self.assertTrue(SpotifyAccount.objects.exists())

    def test_an_unconfirmed_password_sign_up_can_also_recover_by_reset(self):
        self.make_user(active=False)
        self.request_reset()
        self.reset()
        self.assertTrue(User.objects.get().is_active)
