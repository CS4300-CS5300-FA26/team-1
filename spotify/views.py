"""Spotify link, log in, sign up, unlink, and connection check (story D-7, ADR-010).

All three entry points start the same OAuth flow and come back to one callback, which knows what to do from the
mode stored in the session next to `state`. Starting a flow is a POST, so another site can't start one for a user.
"""

import logging

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from accounts import throttle
from accounts.views import after_login_url

from . import client, oauth, services

logger = logging.getLogger('spotify')

# Where each flow returns to when it can't finish.
RETURN_TO = {'link': 'user_profile', 'login': 'login', 'signup': 'register'}

NOT_AVAILABLE = "Spotify sign-in isn't available right now."
INVALID_STATE = 'That Spotify sign-in link was invalid or has expired, so nothing was changed. Please try again.'
DECLINED = 'Spotify not connected: access was declined on Spotify.'
SPOTIFY_ERROR = "Spotify couldn't complete the sign-in. Please try again."
SPOTIFY_DOWN = "We couldn't reach Spotify. Please try again in a few minutes."


@require_POST
def start(request, mode):
    """Send the browser to Spotify's consent page for a link, log-in, or sign-up."""
    if mode == 'link' and not request.user.is_authenticated:
        return redirect('login')
    if mode != 'link' and request.user.is_authenticated:
        return redirect('user_profile')
    if mode != 'link' and throttle.acquire_spotify_auth(throttle.client_ip(request)):
        messages.error(request, throttle.THROTTLED_MESSAGE)
        return redirect(RETURN_TO[mode])
    try:
        url = oauth.begin(request, mode)
    except ImproperlyConfigured as exc:
        logger.error('%s', exc)  # names the missing settings, never their values
        messages.error(request, NOT_AVAILABLE)
        return redirect(RETURN_TO[mode])
    return HttpResponseRedirect(url)


@require_GET
@never_cache
def callback(request):
    """Spotify redirects here with ?code&state, or ?error&state if the user declined."""
    fallback_mode = oauth.peek_mode(request) or 'login'
    flow = oauth.finish(request, request.GET.get('state'))
    if flow is None:
        logger.warning('Spotify callback rejected: missing, mismatched, or expired state')
        messages.error(request, INVALID_STATE)
        return redirect(RETURN_TO['link'] if request.user.is_authenticated else RETURN_TO[fallback_mode])

    back = RETURN_TO[flow.mode]
    error = request.GET.get('error')
    if error:
        if error == 'access_denied':
            messages.info(request, DECLINED)
        else:
            logger.warning('Spotify authorization returned an error')
            messages.error(request, SPOTIFY_ERROR)
        return redirect(back)

    code = request.GET.get('code')
    if not code:
        messages.error(request, SPOTIFY_ERROR)
        return redirect(back)
    if flow.mode == 'link' and (not request.user.is_authenticated or request.user.pk != flow.user_id):
        # The session changed hands (logout, another login) since the link began; don't link to someone else.
        messages.error(request, INVALID_STATE)
        return redirect('login')

    try:
        tokens = client.exchange_code(code)
        profile = client.current_user(tokens.access_token)
    except client.SpotifyUnavailable:
        messages.error(request, SPOTIFY_DOWN)
        return redirect(back)
    except client.SpotifyError:
        messages.error(request, SPOTIFY_ERROR)
        return redirect(back)

    try:
        if flow.mode == 'link':
            account = services.link(request.user, profile, tokens)
            messages.success(request, f'Spotify connected as {account.name}.')
            return redirect('user_profile')
        finish = services.user_for_login if flow.mode == 'login' else services.sign_up
        user = finish(profile, tokens)
    except services.SpotifyAccountError as exc:
        messages.error(request, str(exc))
        return redirect(back)

    # login() rotates the session key, which prevents session fixation.
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    if not user.has_usable_password():
        # Accounts created with "Sign up with Spotify" have no password. Ask for one on every Spotify sign-in until
        # it's set, so Spotify is never the only way in; a new user goes on to onboarding afterwards.
        return redirect('set_password')
    return redirect(after_login_url(user))


@require_POST
@login_required
def unlink(request):
    try:
        services.unlink(request.user)
    except services.SpotifyAccountError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, 'Spotify disconnected.')
    return redirect('user_profile')


@require_GET
@never_cache
@login_required
def status(request):
    """Connection check for the profile page: a token (refreshed if needed) and GET /v1/me. Never returns tokens."""
    if throttle.acquire_spotify_status(request.user.pk):
        return JsonResponse({'state': 'error', 'message': throttle.THROTTLED_MESSAGE, 'display_name': ''}, status=429)
    return JsonResponse(services.connection_status(request.user).as_json())
