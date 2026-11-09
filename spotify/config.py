"""Spotify app credentials and the token encryption key, read from settings (story D-7, ADR-010).

All four values come from `.env` locally and from mounted secrets in Kubernetes (see `fitpro/settings.py`).
With none of them set, Spotify sign-in is simply switched off and its buttons are hidden. With only some of them
set, the app refuses to start (see `SpotifyConfig.ready`), because that is always a configuration mistake.
"""

from dataclasses import dataclass

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

REQUIRED_SETTINGS = (
    'SPOTIFY_CLIENT_ID',
    'SPOTIFY_CLIENT_SECRET',
    'SPOTIFY_REDIRECT_URI',
    'SPOTIFY_TOKEN_ENCRYPTION_KEY',
)


@dataclass(frozen=True)
class Credentials:
    client_id: str
    client_secret: str
    redirect_uri: str


def missing_settings() -> list[str]:
    """Names (never values) of the required settings that are empty."""
    return [name for name in REQUIRED_SETTINGS if not str(getattr(settings, name, '') or '').strip()]


def is_configured() -> bool:
    return not missing_settings()


def credentials() -> Credentials:
    """The app's client id, secret, and registered redirect URI. Raises ImproperlyConfigured naming what's missing."""
    missing = missing_settings()
    if missing:
        raise ImproperlyConfigured(
            f'Spotify is not configured: set {", ".join(missing)} in .env (see .env.example and ADR-010).'
        )
    return Credentials(
        client_id=settings.SPOTIFY_CLIENT_ID.strip(),
        client_secret=settings.SPOTIFY_CLIENT_SECRET.strip(),
        redirect_uri=settings.SPOTIFY_REDIRECT_URI.strip(),
    )


def encryption_keys() -> list[str]:
    """Fernet keys, newest first. A comma-separated list lets an old key keep decrypting during a rotation."""
    return [key.strip() for key in str(settings.SPOTIFY_TOKEN_ENCRYPTION_KEY or '').split(',') if key.strip()]


def check_startup_config() -> None:
    """Fail at startup on a half-finished configuration or a malformed key, instead of on a user's first click."""
    missing = missing_settings()
    if missing and len(missing) < len(REQUIRED_SETTINGS):
        raise ImproperlyConfigured(
            f'Spotify is partly configured: {", ".join(missing)} missing. Set all of '
            f'{", ".join(REQUIRED_SETTINGS)}, or none of them to switch Spotify sign-in off.'
        )
    for key in encryption_keys():
        try:
            Fernet(key)
        except ValueError as exc:
            raise ImproperlyConfigured(
                'SPOTIFY_TOKEN_ENCRYPTION_KEY must be a Fernet key (32 url-safe base64-encoded bytes). Generate one '
                'with: uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            ) from exc
