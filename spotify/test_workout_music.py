"""Playlist search, start playback, and the workout music rules (story: a workout playlist starts with the session)."""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from . import client, services
from .models import SpotifyAccount
from .testing import TEST_SETTINGS, FakeSpotify

User = get_user_model()


@override_settings(**TEST_SETTINGS)
class WorkoutMusicTestCase(TestCase):
    def setUp(self):
        self.spotify = self.enterContext(FakeSpotify().installed())
        self.user = User.objects.create_user('lifter', 'lifter@example.com', 'Tr4ining-Plan-2026!')

    def link(self, user=None, **fields):
        values = {
            'spotify_id': 'spotify-user-1',
            'access_token': 'stored-access',
            'refresh_token': 'stored-refresh',
            'expires_at': timezone.now() + timedelta(hours=1),
        }
        values.update(fields)
        return SpotifyAccount.objects.create(user=user or self.user, **values)


class SearchPlaylistTests(WorkoutMusicTestCase):
    def test_searches_playlists_with_the_query_and_a_small_limit(self):
        client.search_playlist('token', 'leg day workout')
        [params] = self.spotify.searches()
        self.assertEqual(params['q'], ['leg day workout'])
        self.assertEqual(params['type'], ['playlist'])
        self.assertEqual(params['limit'], ['5'])
        self.assertEqual(self.spotify.requests[0].get_header('Authorization'), 'Bearer token')

    def test_returns_the_first_usable_playlist(self):
        self.spotify.playlists = [
            None,
            {'id': 'bad/id', 'name': 'Path tricks'},
            {'id': 'NoName1', 'name': ''},
            {'id': 'Good123', 'name': 'Leg Day Bangers'},
            {'id': 'Later99', 'name': 'Second'},
        ]
        playlist = client.search_playlist('token', 'legs workout')
        self.assertEqual(playlist, client.Playlist(id='Good123', name='Leg Day Bangers'))
        assert playlist is not None  # for mypy; the line above already checked it
        self.assertEqual(playlist.uri, 'spotify:playlist:Good123')
        self.assertEqual(playlist.url, 'https://open.spotify.com/playlist/Good123')

    def test_returns_none_when_nothing_is_found(self):
        self.spotify.playlists = []
        self.assertIsNone(client.search_playlist('token', 'nothing'))

    def test_spotify_being_down_raises_unavailable(self):
        self.spotify.search_error = 'down'
        with self.assertRaises(client.SpotifyUnavailable):
            client.search_playlist('token', 'push workout')


class StartPlaybackTests(WorkoutMusicTestCase):
    def test_puts_the_playlist_as_the_context(self):
        client.start_playback('token', 'spotify:playlist:Good123')
        self.assertEqual(self.spotify.plays(), [{'context_uri': 'spotify:playlist:Good123'}])
        self.assertEqual(self.spotify.requests[0].get_method(), 'PUT')

    def test_the_error_reason_is_kept(self):
        for error, reason in (('no_device', 'NO_ACTIVE_DEVICE'), ('premium', 'PREMIUM_REQUIRED')):
            self.spotify.play_error = error
            with self.assertRaises(client.SpotifyError) as caught:
                client.start_playback('token', 'spotify:playlist:Good123')
            self.assertEqual(caught.exception.reason, reason)


class SearchQueryTests(TestCase):
    def test_drops_the_single_letter_variant(self):
        self.assertEqual(services.workout_search_query('Upper Body A'), 'upper body workout')
        self.assertEqual(services.workout_search_query('Full Body B'), 'full body workout')

    def test_keeps_plain_names(self):
        self.assertEqual(services.workout_search_query('Push'), 'push workout')
        self.assertEqual(services.workout_search_query('Starter Full Body'), 'starter full body workout')

    def test_falls_back_to_gym_for_an_empty_name(self):
        self.assertEqual(services.workout_search_query(''), 'gym workout')


class StartWorkoutMusicTests(WorkoutMusicTestCase):
    def test_not_linked_calls_nothing(self):
        music = services.start_workout_music(self.user, 'Push')
        self.assertEqual(music, services.WorkoutMusic(services.MUSIC_NOT_LINKED))
        self.assertEqual(self.spotify.requests, [])

    def test_another_users_link_is_not_used(self):
        other = User.objects.create_user('other', 'other@example.com', 'Tr4ining-Plan-2026!')
        self.link(user=other)
        self.assertEqual(services.start_workout_music(self.user, 'Push').state, services.MUSIC_NOT_LINKED)
        self.assertEqual(self.spotify.requests, [])

    def test_plays_a_playlist_found_for_the_workout(self):
        self.link()
        music = services.start_workout_music(self.user, 'Lower Body A')

        self.assertEqual(music.state, services.MUSIC_PLAYING)
        self.assertEqual(music.playlist_name, 'Beast Mode Workout')
        self.assertEqual(music.playlist_url, 'https://open.spotify.com/playlist/WorkoutMix123')
        self.assertEqual(self.spotify.searches()[0]['q'], ['lower body workout'])
        self.assertEqual(self.spotify.plays(), [{'context_uri': 'spotify:playlist:WorkoutMix123'}])

    def test_no_active_device_offers_the_playlist_link(self):
        self.link()
        self.spotify.play_error = 'no_device'
        music = services.start_workout_music(self.user, 'Push')
        self.assertEqual(music.state, services.MUSIC_CANT_PLAY)
        self.assertEqual(music.message, services.NO_ACTIVE_DEVICE)
        self.assertEqual(music.playlist_url, 'https://open.spotify.com/playlist/WorkoutMix123')

    def test_free_account_offers_the_playlist_link(self):
        self.link()
        self.spotify.play_error = 'premium'
        music = services.start_workout_music(self.user, 'Push')
        self.assertEqual(music.state, services.MUSIC_CANT_PLAY)
        self.assertEqual(music.message, services.PREMIUM_REQUIRED)
        self.assertEqual(music.playlist_name, 'Beast Mode Workout')

    def test_playback_failing_for_another_reason_still_offers_the_link(self):
        self.link()
        self.spotify.play_error = 'down'
        music = services.start_workout_music(self.user, 'Push')
        self.assertEqual((music.state, music.message), (services.MUSIC_CANT_PLAY, services.MUSIC_UNAVAILABLE))
        self.assertTrue(music.playlist_url)

    def test_search_failing_gives_no_link(self):
        self.link()
        self.spotify.search_error = 'offline'
        music = services.start_workout_music(self.user, 'Push')
        self.assertEqual(music, services.WorkoutMusic(services.MUSIC_CANT_PLAY, services.MUSIC_UNAVAILABLE))
        self.assertEqual(self.spotify.plays(), [])

    def test_no_playlist_found(self):
        self.link()
        self.spotify.playlists = []
        music = services.start_workout_music(self.user, 'Push')
        self.assertEqual(music, services.WorkoutMusic(services.MUSIC_CANT_PLAY, services.NO_PLAYLIST))

    def test_revoked_access_asks_to_link_again(self):
        self.link(needs_relink=True)
        music = services.start_workout_music(self.user, 'Push')
        self.assertEqual(music, services.WorkoutMusic(services.MUSIC_NOT_LINKED, services.RELINK_FOR_MUSIC))
        self.assertEqual(self.spotify.requests, [])

    def test_an_expired_token_is_refreshed_first(self):
        self.link(expires_at=timezone.now())
        self.assertEqual(services.start_workout_music(self.user, 'Push').state, services.MUSIC_PLAYING)
        self.assertEqual(len(self.spotify.grants('refresh_token')), 1)

    @override_settings(AUTH_THROTTLE={**settings.AUTH_THROTTLE, 'spotify_playback': (1, 300)})
    def test_starts_are_rate_limited_per_user(self):
        self.link()
        services.start_workout_music(self.user, 'Push')
        calls = len(self.spotify.requests)

        music = services.start_workout_music(self.user, 'Push')
        self.assertEqual(music, services.WorkoutMusic(services.MUSIC_CANT_PLAY, services.MUSIC_THROTTLED))
        self.assertEqual(len(self.spotify.requests), calls)  # nothing more was sent to Spotify

    def test_tokens_never_end_up_in_the_result(self):
        self.link()
        music = services.start_workout_music(self.user, 'Push').as_dict()
        self.assertNotIn('stored-access', repr(music))
