"""The workout screen and starting a workout with music (story: a workout playlist starts with the session).

The Gherkin scenarios are in features/workout_music.feature.
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import UserProfile
from spotify.models import SpotifyAccount
from spotify.testing import TEST_SETTINGS, UNCONFIGURED_SETTINGS, FakeSpotify

PASSWORD = 'Correct-Horse-9'
MONDAY = date(2026, 11, 16)  # every plan trains on Monday
TUESDAY = MONDAY + timedelta(days=1)  # a beginner's rest day


@override_settings(**TEST_SETTINGS)
class WorkoutTestBase(TestCase):
    def setUp(self):
        self.spotify = self.enterContext(FakeSpotify().installed())
        self.today = self.enterContext(mock.patch('django.utils.timezone.localdate', return_value=MONDAY))
        self.user = self.make_user('alice')
        self.client.force_login(self.user)

    def make_user(self, username, completed=True):
        user = User.objects.create_user(username, f'{username}@example.com', PASSWORD)
        fields = {
            'goal': 'build_muscle',
            'height_inches': 70,
            'weight': Decimal('180'),
            'experience_level': 'beginner',
            'equipment': ['dumbbells'],
        }
        UserProfile.objects.create(user=user, onboarding_completed=completed, **(fields if completed else {}))
        return user

    def link(self, user=None):
        SpotifyAccount.objects.create(
            user=user or self.user,
            spotify_id=f'spotify-{(user or self.user).username}',
            access_token='stored-access',
            refresh_token='stored-refresh',
            expires_at=timezone.now() + timedelta(hours=1),
        )

    def start(self):
        return self.client.post(reverse('start_workout'), follow=True)


class StartWorkoutTests(WorkoutTestBase):
    def test_login_required(self):
        self.client.logout()
        response = self.client.post(reverse('start_workout'))
        self.assertRedirects(
            response, f'{reverse("login")}?next={reverse("start_workout")}', fetch_redirect_response=False
        )

    def test_post_only(self):
        self.assertEqual(self.client.get(reverse('start_workout')).status_code, 405)

    def test_csrf_is_enforced(self):
        csrf_client = self.client_class(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(reverse('start_workout')).status_code, 403)
        self.assertEqual(self.spotify.requests, [])

    def test_unfinished_onboarding_goes_to_onboarding(self):
        self.client.force_login(self.make_user('newbie', completed=False))
        self.assertRedirects(self.client.post(reverse('start_workout')), reverse('onboarding'))

    def test_playing_redirects_to_the_workout_screen_with_the_playlist(self):
        self.link()
        response = self.start()
        self.assertRedirects(response, reverse('workout'))
        self.assertContains(response, 'Now playing on Spotify: <strong>Beast Mode Workout</strong>', html=False)
        self.assertContains(response, 'Goblet Squat')  # Monday's exercises
        self.assertEqual(self.spotify.searches()[0]['q'], ['full body workout'])

    def test_reloading_the_workout_screen_does_not_start_the_music_again(self):
        self.link()
        self.start()
        plays = len(self.spotify.plays())
        response = self.client.get(reverse('workout'))
        self.assertContains(response, 'Beast Mode Workout')
        self.assertEqual(len(self.spotify.plays()), plays)

    def test_not_linked_offers_linking(self):
        response = self.start()
        self.assertContains(response, 'Link Spotify for music')
        self.assertContains(response, f'action="{reverse("spotify_link")}"')
        self.assertEqual(self.spotify.requests, [])

    @override_settings(**UNCONFIGURED_SETTINGS)
    def test_spotify_switched_off_starts_the_workout_without_a_link_button(self):
        response = self.start()
        self.assertRedirects(response, reverse('workout'))
        self.assertContains(response, "Music from Spotify isn't available right now.")
        self.assertNotContains(response, 'Link Spotify for music')
        self.assertEqual(self.spotify.requests, [])

    def test_cannot_play_shows_open_in_spotify(self):
        self.link()
        self.spotify.play_error = 'premium'
        response = self.start()
        self.assertContains(response, "Your workout has started, but the music didn't.")
        self.assertContains(response, 'href="https://open.spotify.com/playlist/WorkoutMix123"')
        self.assertContains(response, 'Open in Spotify')

    def test_no_playlist_found_has_no_link(self):
        self.link()
        self.spotify.playlists = []
        response = self.start()
        self.assertContains(response, 'couldn&#x27;t find a playlist')
        self.assertNotContains(response, 'Open in Spotify')

    def test_playlist_names_from_spotify_are_escaped(self):
        self.link()
        self.spotify.playlists = [{'id': 'Evil1', 'name': '<script>alert(1)</script>'}]
        response = self.start()
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')

    def test_rest_day_starts_nothing(self):
        self.link()
        self.today.return_value = TUESDAY
        response = self.start()
        self.assertRedirects(response, reverse('this_week'))
        self.assertContains(response, 'Today is a rest day')
        self.assertEqual(self.spotify.requests, [])


class WorkoutScreenTests(WorkoutTestBase):
    def test_login_required(self):
        self.client.logout()
        response = self.client.get(reverse('workout'))
        self.assertRedirects(response, f'{reverse("login")}?next={reverse("workout")}', fetch_redirect_response=False)

    def test_before_starting_it_offers_the_start_button(self):
        response = self.client.get(reverse('workout'))
        self.assertContains(response, "Start today's workout")
        self.assertContains(response, 'Goblet Squat')
        self.assertNotContains(response, 'music-heading')

    def test_yesterdays_music_is_not_shown_today(self):
        self.link()
        self.start()
        self.today.return_value = MONDAY + timedelta(days=2)  # Wednesday, also a training day
        response = self.client.get(reverse('workout'))
        self.assertNotContains(response, 'Beast Mode Workout')
        self.assertContains(response, "Start today's workout")

    def test_rest_day(self):
        self.today.return_value = TUESDAY
        response = self.client.get(reverse('workout'))
        self.assertContains(response, 'Today is a rest day.')
        self.assertNotContains(response, "Start today's workout")


class ThisWeekStartButtonTests(WorkoutTestBase):
    def test_shown_once_on_a_training_day(self):
        response = self.client.get(reverse('this_week'))
        self.assertContains(response, "Start today's workout", count=1)

    def test_hidden_on_a_rest_day(self):
        self.today.return_value = TUESDAY
        self.assertNotContains(self.client.get(reverse('this_week')), "Start today's workout")
