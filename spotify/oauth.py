"""The `state` half of the OAuth flow: one random, single-use, short-lived value per sign-in attempt.

`begin()` stores the state and the mode (link, login, or signup) in the user's session before sending them to
Spotify; `finish()` takes them back out exactly once in the callback. Matching the returned state to the session
proves the callback belongs to a flow this browser started (RFC 6749 section 10.12, CSRF on the redirect URI).
"""

import secrets
import time
from dataclasses import dataclass

from django.conf import settings

from . import client

SESSION_KEY = 'spotify_oauth'
MODES = ('link', 'login', 'signup')
# Long enough to read Spotify's consent page (and log in to Spotify first), short enough that a leaked URL dies.
FLOW_TTL_SECONDS = 10 * 60


@dataclass(frozen=True)
class Flow:
    mode: str
    user_id: int | None  # the logged-in user who started a link, so the callback links to the same account


def begin(request, mode: str) -> str:
    """Remember a new flow in the session and return the Spotify authorize URL to redirect to."""
    if mode not in MODES:
        raise ValueError(f'Unknown Spotify flow mode {mode!r}')
    state = secrets.token_urlsafe(32)
    request.session[SESSION_KEY] = {
        'state': state,
        'mode': mode,
        'user_id': request.user.pk if mode == 'link' else None,
        'started': int(time.time()),
    }
    return client.authorize_url(state, settings.SPOTIFY_SCOPES)


def peek_mode(request) -> str | None:
    """The mode of the pending flow, if any, without consuming it (to pick where an error sends the user)."""
    stored = request.session.get(SESSION_KEY)
    return stored.get('mode') if isinstance(stored, dict) else None


def finish(request, returned_state: str | None) -> Flow | None:
    """Consume the pending flow. Returns it only if `returned_state` matches and it hasn't expired."""
    stored = request.session.pop(SESSION_KEY, None)
    if not isinstance(stored, dict) or not returned_state:
        return None
    expected = stored.get('state')
    if not isinstance(expected, str) or not secrets.compare_digest(expected, returned_state):
        return None
    if time.time() - int(stored.get('started', 0)) > FLOW_TTL_SECONDS:
        return None
    if stored.get('mode') not in MODES:
        return None
    return Flow(mode=stored['mode'], user_id=stored.get('user_id'))
