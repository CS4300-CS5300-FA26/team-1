"""The few Spotify Web API calls FitPro makes, over HTTPS with the standard library.

Spotify's OAuth 2.0 Authorization Code flow (ADR-010):
https://developer.spotify.com/documentation/web-api/tutorials/code-flow
https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens

Nothing here logs a token, a code, or a response body. Errors carry Spotify's short error code only.
"""

import base64
import json
import logging
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import credentials

logger = logging.getLogger('spotify')

AUTHORIZE_URL = 'https://accounts.spotify.com/authorize'
TOKEN_URL = 'https://accounts.spotify.com/api/token'  # noqa: S105  # nosec B105: an endpoint URL, not a secret
ME_URL = 'https://api.spotify.com/v1/me'
SEARCH_URL = 'https://api.spotify.com/v1/search'
PLAY_URL = 'https://api.spotify.com/v1/me/player/play'
TIMEOUT_SECONDS = 10

# Spotify ids are base-62. Checking keeps anything else out of the URIs and links built from them.
_SPOTIFY_ID = re.compile(r'[A-Za-z0-9]{1,64}')


class SpotifyError(Exception):
    """Spotify answered with something we can't use.

    `reason` is the Web API's short reason code when it sent one (for example PREMIUM_REQUIRED or NO_ACTIVE_DEVICE).
    """

    def __init__(self, message: str = '', reason: str = ''):
        super().__init__(message)
        self.reason = reason


class SpotifyUnavailable(SpotifyError):
    """Spotify couldn't be reached, timed out, rate limited us, or had a server error. Worth retrying later."""


class InvalidGrant(SpotifyError):
    """The authorization code or refresh token was rejected (expired, already used, or access revoked)."""


class SpotifyUnauthorized(SpotifyError):
    """The Web API rejected the access token (HTTP 401)."""


@dataclass(frozen=True)
class Tokens:
    access_token: str
    expires_in: int
    scope: str
    # Spotify may or may not return a new refresh token when refreshing; None means keep the old one.
    refresh_token: str | None

    def __repr__(self):  # keep tokens out of tracebacks and debug output
        return f'Tokens(expires_in={self.expires_in}, scope={self.scope!r})'


@dataclass(frozen=True)
class Profile:
    """The identity fields of GET /v1/me. `email` is not verified by Spotify, so it never links accounts."""

    id: str
    display_name: str
    email: str


@dataclass(frozen=True)
class Playlist:
    """A playlist found by search. Built only from a validated id, so its URI and link are always well formed."""

    id: str
    name: str

    @property
    def uri(self) -> str:
        return f'spotify:playlist:{self.id}'

    @property
    def url(self) -> str:
        """The playlist on open.spotify.com, which opens the Spotify app or web player."""
        return f'https://open.spotify.com/playlist/{self.id}'


def authorize_url(state: str, scopes: list[str]) -> str:
    creds = credentials()
    query = urlencode(
        {
            'response_type': 'code',
            'client_id': creds.client_id,
            'redirect_uri': creds.redirect_uri,
            'scope': ' '.join(scopes),
            'state': state,
        }
    )
    return f'{AUTHORIZE_URL}?{query}'


def exchange_code(code: str) -> Tokens:
    """Trade the authorization code from the callback for an access token and a refresh token."""
    tokens = _token_request(
        {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': credentials().redirect_uri}
    )
    if not tokens.refresh_token:
        raise SpotifyError('Spotify did not return a refresh token.')
    return tokens


def refresh_access_token(refresh_token: str) -> Tokens:
    return _token_request({'grant_type': 'refresh_token', 'refresh_token': refresh_token})


def current_user(access_token: str) -> Profile:
    data = _send(Request(ME_URL, headers={'Authorization': f'Bearer {access_token}'}))  # noqa: S310 (fixed https URL)
    user_id, display_name, email = data.get('id'), data.get('display_name'), data.get('email')
    if not isinstance(user_id, str) or not user_id:
        raise SpotifyError('GET /v1/me returned no user id.')
    return Profile(
        id=user_id,
        display_name=display_name if isinstance(display_name, str) else '',
        email=email.strip().lower() if isinstance(email, str) else '',
    )


def search_playlist(access_token: str, query: str) -> Playlist | None:
    """The first playlist Spotify's search returns for `query`, or None if there is none.

    https://developer.spotify.com/documentation/web-api/reference/search
    """
    url = f'{SEARCH_URL}?{urlencode({"q": query, "type": "playlist", "limit": 5})}'
    data = _send(Request(url, headers={'Authorization': f'Bearer {access_token}'}))  # noqa: S310 (fixed https URL)
    playlists = data.get('playlists')
    items = playlists.get('items') if isinstance(playlists, dict) else None
    # Spotify has been seen to put null entries in search results, so skip anything that isn't a usable playlist.
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        playlist_id, name = item.get('id'), item.get('name')
        if isinstance(playlist_id, str) and _SPOTIFY_ID.fullmatch(playlist_id) and isinstance(name, str) and name:
            return Playlist(id=playlist_id, name=name)
    return None


def start_playback(access_token: str, context_uri: str) -> None:
    """Play `context_uri` on the user's active Spotify device.

    Spotify only allows this for Premium accounts (403, reason PREMIUM_REQUIRED) and answers 404 (NO_ACTIVE_DEVICE)
    when no device is active. Both come back as SpotifyError with `reason` set.
    https://developer.spotify.com/documentation/web-api/reference/start-a-users-playback
    """
    request = Request(  # noqa: S310 (fixed https URL)
        PLAY_URL,
        data=json.dumps({'context_uri': context_uri}).encode(),
        headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'},
        method='PUT',
    )
    _send(request)


def _token_request(form: dict[str, str]) -> Tokens:
    creds = credentials()
    basic = base64.b64encode(f'{creds.client_id}:{creds.client_secret}'.encode()).decode()
    request = Request(  # noqa: S310 (fixed https URL)
        TOKEN_URL,
        data=urlencode(form).encode(),
        headers={'Authorization': f'Basic {basic}', 'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST',
    )
    data = _send(request)
    access_token, expires_in = data.get('access_token'), data.get('expires_in')
    if not isinstance(access_token, str) or not access_token or not isinstance(expires_in, int):
        raise SpotifyError('Token response was missing access_token or expires_in.')
    refresh = data.get('refresh_token')
    scope = data.get('scope')
    return Tokens(
        access_token=access_token,
        expires_in=expires_in,
        scope=scope if isinstance(scope, str) else '',
        refresh_token=refresh if isinstance(refresh, str) and refresh else None,
    )


def _send(request: Request) -> dict:
    """Send a request and return the JSON body, turning failures into the exceptions above."""
    try:
        # Only ever called with the constant https:// URLs above, so no file:// or other scheme can reach it.
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # nosec B310  # noqa: S310
            body = json.loads(response.read() or b'{}')
    except HTTPError as exc:
        raise _http_error(exc) from None
    except (URLError, TimeoutError, OSError) as exc:
        logger.warning('Spotify request to %s failed: %s', request.full_url.split('?')[0], type(exc).__name__)
        raise SpotifyUnavailable('Spotify could not be reached.') from None
    except ValueError:
        raise SpotifyError('Spotify returned a response that is not JSON.') from None
    if not isinstance(body, dict):
        raise SpotifyError('Spotify returned an unexpected response.')
    return body


def _http_error(exc: HTTPError) -> SpotifyError:
    try:
        body = json.loads(exc.read() or b'{}')
    except ValueError:
        body = {}
    error = body.get('error') if isinstance(body, dict) else None
    # Token endpoint errors are {"error": "invalid_grant", ...}; Web API errors are {"error": {"status", "message"}}.
    code = error if isinstance(error, str) else ''
    # Player errors add a reason, e.g. {"error": {"status": 403, "message": "...", "reason": "PREMIUM_REQUIRED"}}.
    reason = error.get('reason') if isinstance(error, dict) else None
    url = exc.url.split('?')[0] if exc.url else ''
    # These come from the network, so keep only printable characters (no CR/LF log injection).
    safe_code = ''.join(ch for ch in code[:40] if ch.isprintable())
    safe_reason = ''.join(ch for ch in reason[:40] if ch.isprintable()) if isinstance(reason, str) else ''
    logger.warning('Spotify request to %s failed with HTTP %s %s', url, exc.code, safe_code or safe_reason)
    if code == 'invalid_grant':
        return InvalidGrant('Spotify rejected the grant.')
    if exc.code == 401:
        return SpotifyUnauthorized('Spotify rejected the access token.')
    if exc.code == 429 or exc.code >= 500:
        return SpotifyUnavailable(f'Spotify answered HTTP {exc.code}.', reason=safe_reason)
    return SpotifyError(f'Spotify answered HTTP {exc.code}.', reason=safe_reason)
