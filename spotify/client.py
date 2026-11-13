"""The few Spotify Web API calls FitPro makes, over HTTPS with the standard library.

Spotify's OAuth 2.0 Authorization Code flow (ADR-010):
https://developer.spotify.com/documentation/web-api/tutorials/code-flow
https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens

Nothing here logs a token, a code, or a response body. Errors carry Spotify's short error code only.
"""

import base64
import json
import logging
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import credentials

logger = logging.getLogger('spotify')

AUTHORIZE_URL = 'https://accounts.spotify.com/authorize'
TOKEN_URL = 'https://accounts.spotify.com/api/token'  # noqa: S105  # nosec B105: an endpoint URL, not a secret
ME_URL = 'https://api.spotify.com/v1/me'
TIMEOUT_SECONDS = 10


class SpotifyError(Exception):
    """Spotify answered with something we can't use."""


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
    url = exc.url.split('?')[0] if exc.url else ''
    # The error code comes from the network, so keep only printable characters (no CR/LF log injection).
    safe_code = ''.join(ch for ch in code[:40] if ch.isprintable())
    logger.warning('Spotify request to %s failed with HTTP %s %s', url, exc.code, safe_code)
    if code == 'invalid_grant':
        return InvalidGrant('Spotify rejected the grant.')
    if exc.code == 401:
        return SpotifyUnauthorized('Spotify rejected the access token.')
    if exc.code == 429 or exc.code >= 500:
        return SpotifyUnavailable(f'Spotify answered HTTP {exc.code}.')
    return SpotifyError(f'Spotify answered HTTP {exc.code}.')
