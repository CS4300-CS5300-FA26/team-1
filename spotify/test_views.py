"""Link, log in, sign up, unlink, the callback's checks, and the connection check endpoint (story D-7).

The Gherkin scenarios are in features/spotify.feature. Spotify's HTTP endpoints are faked (spotify/testing.py).
"""

import time
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import ThrottleCounter
from core.models import UserProfile

from . import oauth, services, views
from .models import SpotifyAccount
from .testing import TEST_SETTINGS, UNCONFIGURED_SETTINGS, FakeSpotify, approve, decline, start, state_from

User = get_user_model()
PASSWORD = 'Tr4ining-Plan-2026!'


@override_settings(**TEST_SETTINGS)
class SpotifyViewTestCase(TestCase):
    def setUp(self):
        self.spotify = self.enterContext(FakeSpotify().installed())

    def make_user(self, username='lifter', email='lifter@example.com', onboarded=True):
        user = User.objects.create_user(username, email, PASSWORD)
        UserProfile.objects.create(user=user, onboarding_completed=onboarded)
        return user

    def log_in(self, user=None):
        user = user or self.make_user()
        self.client.force_login(user)
        return user

    def link_to(self, user, spotify_id='spotify-user-1'):
        return SpotifyAccount.objects.create(
            user=user, spotify_id=spotify_id, display_name='DJ Lifts', access_token='a', refresh_token='r'
        )

    def assert_message(self, response, text):
        self.assertIn(text, [str(m) for m in response.wsgi_request._messages])

    def assert_logged_out(self):
        self.assertNotIn('_auth_user_id', self.client.session)


class StartTests(SpotifyViewTestCase):
    def test_link_redirects_to_spotify_with_state_and_scopes(self):
        self.log_in()
        response = start(self.client, 'link')

        url = urlsplit(response['Location'])
        self.assertEqual(f'{url.scheme}://{url.netloc}{url.path}', 'https://accounts.spotify.com/authorize')
        query = parse_qs(url.query)
        self.assertEqual(query['redirect_uri'], [TEST_SETTINGS['SPOTIFY_REDIRECT_URI']])
        self.assertEqual(query['scope'][0].split(), settings.SPOTIFY_SCOPES)
        stored = self.client.session[oauth.SESSION_KEY]
        self.assertEqual(stored['state'], query['state'][0])
        self.assertEqual(stored['mode'], 'link')

    def test_each_attempt_gets_a_new_state(self):
        self.assertNotEqual(state_from(start(self.client, 'login')), state_from(start(self.client, 'login')))

    def test_starting_a_flow_is_post_only(self):
        self.log_in()
        for name in ('spotify_link', 'spotify_login', 'spotify_signup'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 405)

    def test_linking_requires_login(self):
        self.assertRedirects(start(self.client, 'link'), reverse('login'), fetch_redirect_response=False)

    def test_logged_in_users_dont_log_in_or_sign_up_again(self):
        self.log_in()
        for mode in ('login', 'signup'):
            self.assertRedirects(start(self.client, mode), reverse('user_profile'))

    @override_settings(**UNCONFIGURED_SETTINGS)
    def test_without_configuration_the_user_is_told_and_the_error_is_logged(self):
        with self.assertLogs('spotify', 'ERROR') as logs:
            response = start(self.client, 'login')
        self.assertRedirects(response, reverse('login'))
        self.assert_message(response, views.NOT_AVAILABLE)
        self.assertIn('SPOTIFY_CLIENT_ID', logs.output[0])

    @override_settings(AUTH_THROTTLE={**settings.AUTH_THROTTLE, 'spotify_auth': (2, 900)})
    def test_log_in_and_sign_up_starts_are_rate_limited(self):
        start(self.client, 'login')
        start(self.client, 'signup')
        with self.assertLogs('accounts.security', 'WARNING'):
            response = start(self.client, 'login')
        self.assertRedirects(response, reverse('login'))
        self.assertTrue(ThrottleCounter.objects.filter(scope='spotify-auth-ip').exists())


class CallbackStateTests(SpotifyViewTestCase):
    """The callback only acts on a state this browser was given, once, within 10 minutes."""

    def test_mismatched_state_is_rejected_before_any_token_request(self):
        user = self.log_in()
        start(self.client, 'link')
        with self.assertLogs('spotify', 'WARNING'):
            response = self.client.get(reverse('spotify_callback'), {'code': 'c', 'state': 'forged'})
        self.assertRedirects(response, reverse('user_profile'))
        self.assert_message(response, views.INVALID_STATE)
        self.assertEqual(self.spotify.requests, [])
        self.assertFalse(SpotifyAccount.objects.filter(user=user).exists())

    def test_missing_state_is_rejected(self):
        start(self.client, 'login')
        with self.assertLogs('spotify', 'WARNING'):
            response = self.client.get(reverse('spotify_callback'), {'code': 'c'})
        self.assertRedirects(response, reverse('login'))
        self.assertEqual(self.spotify.requests, [])

    def test_a_callback_without_a_flow_in_the_session_is_rejected(self):
        with self.assertLogs('spotify', 'WARNING'):
            response = self.client.get(reverse('spotify_callback'), {'code': 'c', 'state': 'anything'})
        self.assertRedirects(response, reverse('login'))
        self.assertEqual(self.spotify.requests, [])

    def test_a_state_works_only_once(self):
        self.log_in()
        state = state_from(start(self.client, 'link'))
        self.client.get(reverse('spotify_callback'), {'code': 'c', 'state': state})
        with self.assertLogs('spotify', 'WARNING'):
            response = self.client.get(reverse('spotify_callback'), {'code': 'c', 'state': state})
        self.assert_message(response, views.INVALID_STATE)
        self.assertEqual(len(self.spotify.grants('authorization_code')), 1)

    def test_an_expired_state_is_rejected(self):
        state = state_from(start(self.client, 'login'))
        session = self.client.session
        session[oauth.SESSION_KEY]['started'] = int(time.time()) - oauth.FLOW_TTL_SECONDS - 1
        session.save()
        with self.assertLogs('spotify', 'WARNING'):
            self.client.get(reverse('spotify_callback'), {'code': 'c', 'state': state})
        self.assertEqual(self.spotify.requests, [])

    def test_declining_on_spotify_returns_to_the_profile(self):
        self.log_in()
        response = decline(self.client, 'link')
        self.assertRedirects(response, reverse('user_profile'))
        self.assert_message(response, views.DECLINED)
        self.assertEqual(self.spotify.requests, [])
        self.assertContains(self.client.get(reverse('user_profile')), 'Spotify not connected')

    def test_declining_a_log_in_returns_to_the_login_page(self):
        self.assertRedirects(decline(self.client, 'login'), reverse('login'))
        self.assert_logged_out()

    def test_other_spotify_errors_are_reported_generically(self):
        self.log_in()
        with self.assertLogs('spotify', 'WARNING'):
            response = approve(self.client, 'link', code=None, error='server_error')
        self.assert_message(response, views.SPOTIFY_ERROR)

    def test_a_missing_code_is_an_error(self):
        self.log_in()
        response = approve(self.client, 'link', code=None)
        self.assert_message(response, views.SPOTIFY_ERROR)
        self.assertEqual(self.spotify.requests, [])

    def test_a_link_finishing_in_a_different_session_user_is_rejected(self):
        self.log_in()
        state = state_from(start(self.client, 'link'))
        # Defence in depth: Django's login() and logout() flush the session, so this takes a session whose user
        # changed while keeping the pending flow.
        other = self.make_user('other', 'other@example.com')
        session = self.client.session
        session['_auth_user_id'] = str(other.pk)
        session['_auth_user_hash'] = other.get_session_auth_hash()
        session.save()
        response = self.client.get(reverse('spotify_callback'), {'code': 'c', 'state': state})
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
        self.assert_message(response, views.INVALID_STATE)
        self.assertFalse(SpotifyAccount.objects.exists())

    def test_spotify_failures_during_the_exchange(self):
        self.log_in()
        for error, message in (('invalid_grant', views.SPOTIFY_ERROR), ('down', views.SPOTIFY_DOWN)):
            self.spotify.exchange_error = error
            with self.subTest(error=error), self.assertLogs('spotify', 'WARNING'):
                response = approve(self.client, 'link')
                self.assertRedirects(response, reverse('user_profile'))
                self.assert_message(response, message)
        self.assertFalse(SpotifyAccount.objects.exists())


class LinkTests(SpotifyViewTestCase):
    def test_link_succeeds(self):
        user = self.log_in()
        response = approve(self.client, 'link')

        self.assertRedirects(response, reverse('user_profile'))
        account = SpotifyAccount.objects.get(user=user)
        self.assertEqual((account.spotify_id, account.display_name), ('spotify-user-1', 'DJ Lifts'))
        self.assertEqual(account.refresh_token, 'refresh-1')
        self.assertEqual(account.scopes, 'user-read-private user-read-email')
        self.assertFalse(account.needs_relink)
        page = self.client.get(reverse('user_profile'))
        self.assertContains(page, 'Spotify connected')
        self.assertContains(page, 'DJ Lifts')
        self.assertContains(page, 'Disconnect Spotify')
        self.assertNotContains(page, 'refresh-1')
        self.assertNotContains(page, 'access-1')

    def test_a_spotify_account_linked_to_another_user_cannot_be_linked_again(self):
        owner = self.make_user('owner', 'owner@example.com')
        self.link_to(owner)
        user = self.log_in()

        response = approve(self.client, 'link')

        self.assert_message(response, services.ALREADY_LINKED_ELSEWHERE)
        self.assertEqual(SpotifyAccount.objects.get(spotify_id='spotify-user-1').user, owner)
        self.assertFalse(SpotifyAccount.objects.filter(user=user).exists())

    def test_relinking_replaces_tokens_and_clears_needs_relink(self):
        user = self.log_in()
        account = self.link_to(user)
        account.needs_relink = True
        account.save()
        approve(self.client, 'link')
        account.refresh_from_db()
        self.assertFalse(account.needs_relink)
        self.assertEqual(account.refresh_token, 'refresh-1')
        self.assertEqual(SpotifyAccount.objects.count(), 1)


class LoginTests(SpotifyViewTestCase):
    def test_a_linked_spotify_account_logs_its_user_in(self):
        user = self.make_user()
        self.link_to(user)
        response = approve(self.client, 'login')
        self.assertRedirects(response, reverse('dashboard'))
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)
        self.assertEqual(SpotifyAccount.objects.get(user=user).access_token, 'access-1')

    def test_users_who_havent_onboarded_go_to_onboarding(self):
        self.link_to(self.make_user(onboarded=False))
        self.assertRedirects(approve(self.client, 'login'), reverse('onboarding'))

    def test_a_matching_email_is_never_used_to_log_in(self):
        # Someone puts a FitPro user's email on their own Spotify account. Spotify doesn't verify it.
        self.make_user('victim', 'dj@example.com')
        response = approve(self.client, 'login')
        self.assertRedirects(response, reverse('login'))
        self.assert_message(response, services.NOT_LINKED_FOR_LOGIN)
        self.assert_logged_out()
        self.assertFalse(SpotifyAccount.objects.exists())

    def test_an_inactive_user_cannot_log_in(self):
        user = self.make_user()
        user.is_active = False
        user.save()
        self.link_to(user)
        approve(self.client, 'login')
        self.assert_logged_out()

    def test_the_session_key_is_rotated(self):
        self.link_to(self.make_user())
        state = state_from(start(self.client, 'login'))
        before = self.client.session.session_key
        self.client.get(reverse('spotify_callback'), {'code': 'c', 'state': state})
        self.assertNotEqual(self.client.session.session_key, before)


class SignupTests(SpotifyViewTestCase):
    def test_sign_up_creates_a_passwordless_user_and_links_spotify(self):
        response = approve(self.client, 'signup')

        self.assertRedirects(response, reverse('onboarding'))
        account = SpotifyAccount.objects.get(spotify_id='spotify-user-1')
        user = account.user
        self.assertEqual((user.username, user.email), ('dj-lifts', 'dj@example.com'))
        self.assertFalse(user.has_usable_password())
        self.assertTrue(UserProfile.objects.filter(user=user).exists())
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_an_existing_local_email_is_not_auto_linked(self):
        existing = self.make_user('sam', 'DJ@example.com')
        response = approve(self.client, 'signup')
        self.assertRedirects(response, reverse('register'))
        self.assert_message(response, services.EMAIL_EXISTS_FOR_SIGNUP)
        self.assert_logged_out()
        self.assertFalse(SpotifyAccount.objects.exists())
        self.assertEqual(User.objects.filter(email__iexact='dj@example.com').get(), existing)

    def test_an_already_linked_spotify_account_cannot_sign_up_again(self):
        self.link_to(self.make_user())
        response = approve(self.client, 'signup')
        self.assert_message(response, services.ALREADY_LINKED_FOR_SIGNUP)
        self.assertEqual(User.objects.count(), 1)

    def test_usernames_are_unique_and_never_contain_at_signs(self):
        self.make_user('dj-lifts', 'someone@example.com')
        self.spotify.display_name = 'DJ @ Lifts'
        approve(self.client, 'signup')
        self.assertEqual(SpotifyAccount.objects.get().user.username, 'dj-lifts-2')

    def test_sign_up_without_an_email_or_display_name(self):
        self.spotify.email, self.spotify.display_name = '', ''
        approve(self.client, 'signup')
        user = SpotifyAccount.objects.get().user
        self.assertEqual((user.username, user.email), ('spotify-user-1', ''))


class UnlinkTests(SpotifyViewTestCase):
    def test_unlink_deletes_the_link_and_tokens(self):
        user = self.log_in()
        self.link_to(user)
        response = self.client.post(reverse('spotify_unlink'), follow=True)
        self.assertFalse(SpotifyAccount.objects.filter(user=user).exists())
        self.assertContains(response, 'Spotify not connected')
        self.assertContains(response, 'Link to Spotify')

    def test_unlink_is_blocked_when_spotify_is_the_only_way_to_log_in(self):
        approve(self.client, 'signup')
        response = self.client.post(reverse('spotify_unlink'), follow=True)
        self.assertTrue(SpotifyAccount.objects.exists())
        self.assertContains(response, 'can&#x27;t be disconnected until your account has a password')

    def test_unlink_is_post_only(self):
        self.link_to(self.log_in())
        self.assertEqual(self.client.get(reverse('spotify_unlink')).status_code, 405)
        self.assertTrue(SpotifyAccount.objects.exists())


class StatusEndpointTests(SpotifyViewTestCase):
    def test_ok(self):
        self.link_to(self.log_in())
        response = self.client.get(reverse('spotify_status'))
        self.assertEqual(response.json(), {'state': 'ok', 'message': 'Connection OK.', 'display_name': 'DJ Lifts'})
        self.assertIn('no-cache', response['Cache-Control'])

    def test_failures_return_a_message_and_never_tokens(self):
        account = self.link_to(self.log_in())
        account.expires_at = None
        account.save()
        self.spotify.refresh_error = 'invalid_grant'
        with self.assertLogs('spotify', 'INFO'):
            data = self.client.get(reverse('spotify_status')).json()
        self.assertEqual(data['state'], 'needs_relink')
        self.assertEqual(set(data), {'state', 'message', 'display_name'})

    def test_only_the_signed_in_users_link_is_checked(self):
        self.link_to(self.make_user('owner', 'owner@example.com'))
        self.log_in()
        self.assertEqual(self.client.get(reverse('spotify_status')).json()['state'], 'not_linked')
        self.assertNotContains(self.client.get(reverse('user_profile')), 'DJ Lifts')

    def test_requires_login(self):
        response = self.client.get(reverse('spotify_status'))
        self.assertRedirects(response, f'{reverse("login")}?next={reverse("spotify_status")}')

    @override_settings(AUTH_THROTTLE={**settings.AUTH_THROTTLE, 'spotify_status': (1, 300)})
    def test_rate_limited(self):
        self.link_to(self.log_in())
        self.client.get(reverse('spotify_status'))
        with self.assertLogs('accounts.security', 'WARNING'):
            self.assertEqual(self.client.get(reverse('spotify_status')).status_code, 429)


class PageTests(SpotifyViewTestCase):
    def test_login_and_sign_up_pages_offer_spotify(self):
        self.assertContains(self.client.get(reverse('login')), 'Log in with Spotify')
        self.assertContains(self.client.get(reverse('register')), 'Sign up with Spotify')

    def test_profile_shows_link_button_when_not_linked(self):
        self.log_in()
        page = self.client.get(reverse('user_profile'))
        self.assertContains(page, 'Spotify not connected')
        self.assertContains(page, 'Link to Spotify')
        self.assertNotContains(page, 'spotify_status.js')

    def test_profile_shows_the_connection_check_when_linked(self):
        self.link_to(self.log_in())
        page = self.client.get(reverse('user_profile'))
        self.assertContains(page, 'data-status-url="/spotify/status/"')
        self.assertContains(page, 'spotify_status.js')
        self.assertContains(page, 'Connection not checked yet.')

    def test_profile_shows_reconnect_help_when_relink_is_needed(self):
        account = self.link_to(self.log_in())
        account.needs_relink = True
        account.save()
        page = self.client.get(reverse('user_profile'))
        self.assertContains(page, 'Reconnect Spotify')
        self.assertContains(page, 'data-state="error"')

    @override_settings(**UNCONFIGURED_SETTINGS)
    def test_without_configuration_no_spotify_buttons_are_shown(self):
        self.assertNotContains(self.client.get(reverse('login')), 'with Spotify')
        self.assertNotContains(self.client.get(reverse('register')), 'with Spotify')
        self.log_in()
        page = self.client.get(reverse('user_profile'))
        self.assertNotContains(page, 'Link to Spotify')
        self.assertContains(page, "Linking Spotify isn't available right now.")
