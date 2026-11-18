"""Step definitions for features/workout_music.feature.

Spotify is `spotify.testing.FakeSpotify`, so the scenarios run the real views, token helper, search, and playback
request without calling the network. "Spotify is not linked" is shared with features/spotify.feature.
"""

from datetime import date
from decimal import Decimal
from unittest import mock

from behave import given, then, when
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from core.models import UserProfile
from spotify.testing import TEST_SETTINGS, FakeSpotify, approve

User = get_user_model()

VALID_PASSWORD = 'Tr4ining-Plan-2026!'
# A Monday. Every plan trains on Monday, so "today" always has a workout to start.
TRAINING_DAY = date(2026, 11, 16)
PLAYLIST_ID = 'WorkoutMix123'
PLAYLIST_NAME = 'Beast Mode Workout'


def link_spotify(context):
    override = override_settings(**TEST_SETTINGS)
    override.enable()
    context.add_cleanup(override.disable)
    context.spotify = FakeSpotify()
    context.spotify.playlists = [{'id': PLAYLIST_ID, 'name': PLAYLIST_NAME}]
    installed = context.spotify.installed()
    installed.__enter__()
    context.add_cleanup(installed.__exit__, None, None, None)
    context.user = User.objects.create_user('mover', 'mover@example.com', VALID_PASSWORD)
    UserProfile.objects.create(user=context.user, onboarding_completed=True)
    context.test.client.force_login(context.user)
    approve(context.test.client, 'link')


@given('Spotify is linked and a Spotify device is active')
def step_linked_device_active(context):
    link_spotify(context)


@given('Spotify is linked but no device is active or my account cannot be controlled')
def step_linked_cannot_play(context):
    link_spotify(context)
    context.spotify.play_error = 'no_device'


@when("I start today's workout")
def step_start_workout(context):
    # Fill in the profile so the real plan generator builds the week (not the starter fallback).
    UserProfile.objects.filter(user=context.user).update(
        goal='build_muscle',
        height_inches=70,
        weight=Decimal('180'),
        experience_level='beginner',
        equipment=['dumbbells'],
    )
    patcher = mock.patch('django.utils.timezone.localdate', return_value=TRAINING_DAY)
    patcher.start()
    context.add_cleanup(patcher.stop)

    this_week = context.test.client.get(reverse('this_week'))
    context.test.assertContains(this_week, "Start today's workout")
    context.response = context.test.client.post(reverse('start_workout'), follow=True)


def assert_on_workout_screen(context):
    context.test.assertEqual(context.response.redirect_chain[-1][0], reverse('workout'))
    context.test.assertContains(context.response, "Today's Workout")
    context.test.assertContains(context.response, 'aria-label="Today\'s exercises"')


@then('a playlist starts playing')
def step_playlist_playing(context):
    context.test.assertEqual(context.spotify.plays(), [{'context_uri': f'spotify:playlist:{PLAYLIST_ID}'}])


@then('its name appears on the workout screen')
def step_playlist_name_shown(context):
    assert_on_workout_screen(context)
    context.test.assertContains(
        context.response, f'Now playing on Spotify: <strong>{PLAYLIST_NAME}</strong>', html=False
    )


@then('the workout starts normally')
def step_workout_started(context):
    assert_on_workout_screen(context)


@then('I see a "Link Spotify for music" option')
def step_link_option(context):
    context.test.assertContains(context.response, 'Link Spotify for music')
    context.test.assertContains(context.response, f'action="{reverse("spotify_link")}"')


@then('I see an "Open in Spotify" link for the playlist')
def step_open_in_spotify(context):
    context.test.assertContains(context.response, f'href="https://open.spotify.com/playlist/{PLAYLIST_ID}"')
    context.test.assertContains(context.response, 'Open in Spotify')
