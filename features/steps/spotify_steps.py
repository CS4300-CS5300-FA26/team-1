"""Step definitions for features/spotify.feature (story D-7).

Spotify's token endpoint and GET /v1/me are replaced by `spotify.testing.FakeSpotify`, so the scenarios run the real
OAuth views (state check, code exchange, account rules) without calling the network.
"""

from behave import given, then, when
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from core.models import UserProfile
from spotify import services
from spotify.models import SpotifyAccount
from spotify.testing import TEST_SETTINGS, FakeSpotify, approve, start, state_from

User = get_user_model()

VALID_PASSWORD = 'Tr4ining-Plan-2026!'


def use_fake_spotify(context):
    """Configure Spotify for this scenario and route its HTTP calls to a fake."""
    override = override_settings(**TEST_SETTINGS)
    override.enable()
    context.add_cleanup(override.disable)
    context.spotify = FakeSpotify(display_name='DJ Lifts', email='lifter@example.com')
    installed = context.spotify.installed()
    installed.__enter__()
    context.add_cleanup(installed.__exit__, None, None, None)


def create_member(context):
    user = User.objects.create_user('lifter', 'lifter@example.com', VALID_PASSWORD)
    UserProfile.objects.create(user=user, onboarding_completed=True)
    context.user = user
    return user


def log_in(context):
    use_fake_spotify(context)
    context.test.client.force_login(create_member(context))


# --- Link, decline, unlink ---------------------------------------------------------------------------------------


@given('Spotify is not linked')
def step_not_linked(context):
    log_in(context)
    context.test.assertFalse(SpotifyAccount.objects.filter(user=context.user).exists())


@when("I approve access on Spotify's authorization page")
def step_approve(context):
    context.response = approve(context.test.client, 'link')


@then('I return to settings and see "Spotify connected" with my Spotify name')
def step_see_connected(context):
    context.test.assertRedirects(context.response, reverse('user_profile'), fetch_redirect_response=False)
    context.response = context.test.client.get(reverse('user_profile'))
    context.test.assertContains(context.response, 'Spotify connected as DJ Lifts.')  # the confirmation
    context.test.assertContains(context.response, '<span class="connection-pill__name">DJ Lifts</span>')  # the pill


@given("I am on Spotify's authorization page")
def step_on_authorization_page(context):
    log_in(context)
    response = start(context.test.client, 'link')
    context.test.assertTrue(response['Location'].startswith('https://accounts.spotify.com/authorize?'))
    context.state = state_from(response)


@when('I decline access')
def step_decline(context):
    # What Spotify sends back when the user clicks "Cancel" on its consent page.
    context.response = context.test.client.get(
        reverse('spotify_callback'), {'error': 'access_denied', 'state': context.state}
    )


@then('I return to settings and see "Spotify not connected"')
def step_see_not_connected(context):
    context.test.assertRedirects(context.response, reverse('user_profile'), fetch_redirect_response=False)
    context.response = context.test.client.get(reverse('user_profile'))
    context.test.assertContains(context.response, 'Spotify not connected')
    context.test.assertContains(context.response, 'Link to Spotify')


@given('Spotify is linked')
def step_linked(context):
    log_in(context)
    approve(context.test.client, 'link')
    context.test.assertTrue(SpotifyAccount.objects.filter(user=context.user).exists())


@when('I click "Disconnect Spotify"')
def step_disconnect(context):
    page = context.test.client.get(reverse('user_profile'))
    context.test.assertContains(page, 'Disconnect Spotify')
    context.response = context.test.client.post(reverse('spotify_unlink'), follow=True)
    context.test.assertFalse(SpotifyAccount.objects.filter(user=context.user).exists())


# --- Log in with Spotify -------------------------------------------------------------------------------------------


@given('I have a FitPro account linked to Spotify')
def step_member_linked(context):
    use_fake_spotify(context)
    SpotifyAccount.objects.create(user=create_member(context), spotify_id=context.spotify.user_id)


@given('I have a FitPro account with the same email as my Spotify account, but Spotify is not linked')
def step_member_same_email(context):
    use_fake_spotify(context)
    create_member(context)
    context.test.assertEqual(context.user.email, context.spotify.email)


@when('I log in with Spotify and approve access')
def step_log_in_with_spotify(context):
    context.response = approve(context.test.client, 'login')


@then('I am logged in and taken to my dashboard')
def step_logged_in_dashboard(context):
    context.test.assertRedirects(context.response, reverse('dashboard'))
    context.test.assertEqual(int(context.test.client.session['_auth_user_id']), context.user.pk)


@then('I am told to log in with my password and link Spotify from my profile')
def step_told_to_link(context):
    context.test.assertRedirects(context.response, reverse('login'), fetch_redirect_response=False)
    context.response = context.test.client.get(reverse('login'))
    context.test.assertContains(context.response, services.NOT_LINKED_FOR_LOGIN)
    context.test.assertFalse(SpotifyAccount.objects.exists())
