"""Test doubles for Spotify (story D-7). Nothing in the tests calls the network.

`FakeSpotify` stands in for Spotify's token endpoint, GET /v1/me, playlist search, and start playback by replacing
`urlopen` in `spotify.client`, so
tests still exercise the real request building and response parsing. `approve()` walks a test client through the
whole OAuth round trip the way a browser would.
"""

import io
import json
from contextlib import contextmanager
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet
from django.urls import reverse

from . import client

TEST_SETTINGS = {
    'SPOTIFY_CLIENT_ID': 'test-client-id',
    'SPOTIFY_CLIENT_SECRET': 'test-client-secret',  # nosec B105: a fake for tests, never sent anywhere
    'SPOTIFY_REDIRECT_URI': 'http://testserver/auth-callback/spotify',
    'SPOTIFY_TOKEN_ENCRYPTION_KEY': Fernet.generate_key().decode(),
}
UNCONFIGURED_SETTINGS = dict.fromkeys(TEST_SETTINGS, '')


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _http_error(url: str, status: int, body: dict) -> HTTPError:
    return HTTPError(url, status, 'error', {}, io.BytesIO(json.dumps(body).encode()))  # type: ignore[arg-type]


class FakeSpotify:
    """A scripted Spotify. Set the *_error attributes to make an endpoint fail:

    exchange_error / refresh_error: 'invalid_grant', 'down' (HTTP 503), or 'offline' (connection refused)
    me_error: 'unauthorized' (HTTP 401), 'down', or 'offline'
    search_error: 'unauthorized', 'down', or 'offline'
    play_error: 'no_device' (HTTP 404 NO_ACTIVE_DEVICE), 'premium' (HTTP 403 PREMIUM_REQUIRED), 'unauthorized', 'down',
        or 'offline'

    Add '_once' to search_error or play_error (e.g. 'unauthorized_once') to fail only the next call to that endpoint.

    `playlists` is what search returns, as Spotify's simplified playlist objects (None entries are allowed).
    """

    def __init__(self, user_id='spotify-user-1', display_name='DJ Lifts', email='dj@example.com'):
        self.user_id = user_id
        self.display_name = display_name
        self.email = email
        self.expires_in = 3600
        self.rotate_refresh_token = False
        self.exchange_error: str | None = None
        self.refresh_error: str | None = None
        self.me_error: str | None = None
        self.search_error: str | None = None
        self.play_error: str | None = None
        self.playlists: list[dict | None] = [{'id': 'WorkoutMix123', 'name': 'Beast Mode Workout'}]
        self.requests: list = []
        self._issued = 0

    # What a test checks afterwards ------------------------------------------------------------------------------

    def grants(self, grant_type: str) -> list[dict[str, list[str]]]:
        """The form bodies of token requests with this grant_type."""
        forms = [parse_qs(r.data.decode()) for r in self.requests if r.full_url == client.TOKEN_URL]
        return [form for form in forms if form.get('grant_type') == [grant_type]]

    def me_calls(self) -> int:
        return sum(1 for r in self.requests if r.full_url == client.ME_URL)

    def searches(self) -> list[dict[str, list[str]]]:
        """The query parameters of each playlist search."""
        return [parse_qs(urlsplit(r.full_url).query) for r in self.requests if _base(r.full_url) == client.SEARCH_URL]

    def plays(self) -> list[dict]:
        """The JSON bodies of each start-playback request."""
        return [json.loads(r.data) for r in self.requests if r.full_url == client.PLAY_URL]

    # The fake endpoints ------------------------------------------------------------------------------------------

    def urlopen(self, request, timeout=None):
        self.requests.append(request)
        if request.full_url == client.TOKEN_URL:
            form = parse_qs(request.data.decode())
            grant = form['grant_type'][0]
            self._fail(request.full_url, self.exchange_error if grant == 'authorization_code' else self.refresh_error)
            return self._tokens(new_refresh=grant == 'authorization_code' or self.rotate_refresh_token)
        if request.full_url == client.ME_URL:
            self._fail(request.full_url, self.me_error)
            return _Response(
                json.dumps({'id': self.user_id, 'display_name': self.display_name, 'email': self.email}).encode()
            )
        if _base(request.full_url) == client.SEARCH_URL:
            self._fail(request.full_url, self._take('search_error'))
            return _Response(json.dumps({'playlists': {'items': self.playlists}}).encode())
        if request.full_url == client.PLAY_URL:
            if request.get_method() != 'PUT':
                raise AssertionError(f'Start playback must be a PUT, not {request.get_method()}')
            self._fail(request.full_url, self._take('play_error'))
            return _Response(b'')  # 204 No Content
        raise AssertionError(f'Unexpected request to {request.full_url}')

    def _take(self, attribute: str) -> str | None:
        """The error set for an endpoint; an '<error>_once' error is cleared after this call."""
        error = getattr(self, attribute)
        if error and error.endswith('_once'):
            setattr(self, attribute, None)
            return error.removesuffix('_once')
        return error

    def _tokens(self, new_refresh: bool) -> _Response:
        self._issued += 1
        body = {
            'access_token': f'access-{self._issued}',
            'token_type': 'Bearer',  # nosec B105: the OAuth token type name, not a secret
            'expires_in': self.expires_in,
            'scope': 'user-read-private user-read-email',
        }
        if new_refresh:
            body['refresh_token'] = f'refresh-{self._issued}'
        return _Response(json.dumps(body).encode())

    @staticmethod
    def _fail(url: str, error: str | None) -> None:
        if error == 'invalid_grant':
            raise _http_error(url, 400, {'error': 'invalid_grant', 'error_description': 'Refresh token revoked'})
        if error == 'unauthorized':
            raise _http_error(url, 401, {'error': {'status': 401, 'message': 'The access token expired'}})
        if error == 'down':
            raise _http_error(url, 503, {'error': {'status': 503, 'message': 'Service unavailable'}})
        if error == 'no_device':
            raise _http_error(
                url, 404, {'error': {'status': 404, 'message': 'Not found', 'reason': 'NO_ACTIVE_DEVICE'}}
            )
        if error == 'premium':
            raise _http_error(
                url, 403, {'error': {'status': 403, 'message': 'Premium required', 'reason': 'PREMIUM_REQUIRED'}}
            )
        if error == 'offline':
            raise URLError(ConnectionRefusedError())

    @contextmanager
    def installed(self):
        """Route every Spotify HTTP call made inside the block to this fake."""
        from unittest import mock

        with mock.patch('spotify.client.urlopen', side_effect=self.urlopen):
            yield self


def _base(url: str) -> str:
    return url.split('?')[0]


def start(test_client, mode: str):
    """POST the "Link / Log in / Sign up with Spotify" button. Returns the response (a redirect to Spotify)."""
    return test_client.post(reverse(f'spotify_{mode}'))


def state_from(response) -> str:
    return parse_qs(urlsplit(response['Location']).query)['state'][0]


def approve(test_client, mode: str, code: str | None = 'auth-code', **callback_params):
    """Start a flow and come back from Spotify as if the user approved. Extra params replace code/state."""
    state = state_from(start(test_client, mode))
    params = {'code': code, 'state': state, **callback_params}
    return test_client.get(reverse('spotify_callback'), {k: v for k, v in params.items() if v is not None})


def decline(test_client, mode: str):
    state = state_from(start(test_client, mode))
    return test_client.get(reverse('spotify_callback'), {'error': 'access_denied', 'state': state})
