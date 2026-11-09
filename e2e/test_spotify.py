"""Browser tests for Spotify on the profile, log-in, and sign-up pages (story D-7), with Playwright + Chromium.

Skipped unless E2E=1 (see e2e/test_meal_plan.py). Spotify's consent page is intercepted in the browser and answered
with the redirect Spotify would send, and the server's calls to Spotify go to `spotify.testing.FakeSpotify`, so
nothing calls the network.
"""

import os
import re
from datetime import timedelta
from unittest import skipUnless
from urllib.parse import parse_qs, urlencode, urlsplit

from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings, tag
from django.utils import timezone
from playwright.sync_api import Browser, Playwright, Route, expect, sync_playwright

from core.models import UserProfile
from spotify.models import SpotifyAccount
from spotify.testing import TEST_SETTINGS, FakeSpotify

User = get_user_model()
PASSWORD = 'Tr4ining-Plan-2026!'


@tag('e2e')
@skipUnless(os.environ.get('E2E') == '1', 'Set E2E=1 to run browser tests.')
@override_settings(**TEST_SETTINGS)
class SpotifyBrowserTests(StaticLiveServerTestCase):
    playwright: Playwright
    browser: Browser

    @classmethod
    def setUpClass(cls):
        os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'  # see e2e/test_meal_plan.py
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()
        os.environ.pop('DJANGO_ALLOW_ASYNC_UNSAFE', None)

    def setUp(self):
        # The redirect URI has to point at the live server, whose port is only known now.
        self.enterContext(override_settings(SPOTIFY_REDIRECT_URI=f'{self.live_server_url}/auth-callback/spotify'))
        self.spotify = self.enterContext(FakeSpotify().installed())
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 900})
        self.page = self.context.new_page()
        self.addCleanup(self.context.close)
        self.user = User.objects.create_user('e2e', 'e2e@example.com', PASSWORD)
        UserProfile.objects.create(user=self.user, onboarding_completed=True)

    def log_in(self):
        self.page.goto(f'{self.live_server_url}/accounts/login/')
        self.page.get_by_label('Email or username').fill('e2e@example.com')
        self.page.get_by_label('Password').fill(PASSWORD)
        self.page.get_by_role('button', name='Log in', exact=True).click()
        self.page.wait_for_url('**/dashboard/')

    def link(self):
        SpotifyAccount.objects.create(
            user=self.user,
            spotify_id=self.spotify.user_id,
            display_name='DJ Lifts',
            access_token='a',
            refresh_token='r',
            expires_at=timezone.now() + timedelta(hours=1),
        )

    def spotify_answers(self, **params):
        """Skip Spotify's consent page: answer with the redirect Spotify sends back after the user's choice.

        Playwright doesn't route requests reached through a redirect, so this intercepts the button's POST, lets
        FitPro answer it (storing the state in the session), and swaps FitPro's redirect to Spotify for the one
        Spotify would make back to the callback. Any other request to Spotify is aborted, so nothing leaves the box.
        """

        def handle(route: Route):
            response = route.fetch(max_redirects=0)
            to_spotify = response.headers['location']
            self.assertTrue(to_spotify.startswith('https://accounts.spotify.com/authorize?'))
            state = parse_qs(urlsplit(to_spotify).query)['state'][0]
            query = urlencode({**params, 'state': state})
            headers = {**response.headers, 'location': f'{self.live_server_url}/auth-callback/spotify?{query}'}
            route.fulfill(status=302, headers=headers)

        self.page.route(re.compile(r'/spotify/(link|login|signup)/$'), handle)
        self.page.route('https://*.spotify.com/**', lambda route: route.abort())

    def pill(self):
        return self.page.locator('[data-spotify-status]')

    def test_link_from_the_profile_then_disconnect_with_the_keyboard(self):
        self.log_in()
        self.page.goto(f'{self.live_server_url}/users/')
        expect(self.page.get_by_text('Spotify not connected')).to_be_visible()
        self.spotify_answers(code='approved')

        self.page.get_by_role('button', name='Link to Spotify').click()
        self.page.wait_for_url('**/users/')

        expect(self.page.get_by_role('status').filter(has_text='Spotify connected as DJ Lifts.')).to_be_visible()
        expect(self.pill()).to_have_attribute('data-state', 'ok')
        expect(self.page.get_by_text('Connection OK')).to_be_visible()

        self.page.get_by_role('button', name='Disconnect Spotify').focus()
        self.page.keyboard.press('Enter')
        self.page.wait_for_load_state()
        expect(self.page.get_by_text('Spotify not connected')).to_be_visible()
        self.assertFalse(SpotifyAccount.objects.exists())

    def test_declining_on_spotify(self):
        self.log_in()
        self.page.goto(f'{self.live_server_url}/users/')
        self.spotify_answers(error='access_denied')
        self.page.get_by_role('button', name='Link to Spotify').click()
        self.page.wait_for_url('**/users/')
        expect(self.page.get_by_text('access was declined on Spotify')).to_be_visible()
        expect(self.page.get_by_role('button', name='Link to Spotify')).to_be_visible()

    def test_pill_pulses_grey_while_checking_then_turns_green(self):
        self.link()
        self.log_in()
        held: list[Route] = []
        self.page.route('**/spotify/status/', lambda route: held.append(route))
        self.page.goto(f'{self.live_server_url}/users/', wait_until='domcontentloaded')

        expect(self.pill()).to_have_attribute('data-state', 'checking')
        expect(self.page.get_by_text('Checking the connection to Spotify')).to_be_visible()
        animation = self.page.locator('[data-spotify-status] .connection-pill__dot').evaluate(
            'el => getComputedStyle(el).animationName'
        )
        self.assertEqual(animation, 'connection-pulse')

        held[0].continue_()
        expect(self.pill()).to_have_attribute('data-state', 'ok')
        expect(self.page.locator('[data-status-help]')).to_be_hidden()

    def test_a_failed_check_turns_red_and_shows_troubleshooting(self):
        self.spotify.me_error = 'down'
        self.link()
        self.log_in()
        self.page.goto(f'{self.live_server_url}/users/')

        expect(self.pill()).to_have_attribute('data-state', 'error')
        expect(self.page.get_by_text("Connection problem: Spotify isn't responding")).to_be_visible()
        expect(self.page.get_by_role('button', name='Reconnect Spotify')).to_be_visible()
        expect(self.page.get_by_role('link', name='Manage apps in your Spotify account')).to_be_visible()

    def test_log_in_with_spotify(self):
        self.link()
        self.spotify_answers(code='approved')
        self.page.goto(f'{self.live_server_url}/accounts/login/')
        self.page.get_by_role('button', name='Log in with Spotify').click()
        self.page.wait_for_url('**/dashboard/')

    def test_sign_up_with_spotify(self):
        self.spotify_answers(code='approved')
        self.page.goto(f'{self.live_server_url}/accounts/register/')
        self.page.get_by_role('button', name='Sign up with Spotify').click()
        self.page.wait_for_url('**/accounts/password/set/')
        self.assertFalse(SpotifyAccount.objects.get(spotify_id=self.spotify.user_id).user.has_usable_password())

        self.page.get_by_label('New password:', exact=True).fill(PASSWORD)
        self.page.get_by_label('New password confirmation').fill(PASSWORD)
        self.page.get_by_role('button', name='Set password and continue').click()
        self.page.wait_for_url('**/onboarding/')
        self.assertTrue(SpotifyAccount.objects.get(spotify_id=self.spotify.user_id).user.check_password(PASSWORD))
