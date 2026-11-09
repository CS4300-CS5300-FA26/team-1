"""Spotify account rules and the access token helper (story D-7, ADR-010).

Accounts are matched on the Spotify user id only. Spotify doesn't guarantee the email on GET /v1/me is verified,
so matching on email would let anyone who sets a victim's address on a Spotify account log in as the victim.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from core.models import UserProfile

from . import client
from .models import SpotifyAccount

logger = logging.getLogger('spotify')

# Refresh this long before Spotify's expiry so a token never dies between handing it out and using it.
REFRESH_MARGIN = timedelta(seconds=60)

ALREADY_LINKED_ELSEWHERE = 'That Spotify account is already linked to a different FitPro account.'
NOT_LINKED_FOR_LOGIN = (
    'No FitPro account is linked to that Spotify account. Log in with your email and password, then link Spotify '
    'from your profile.'
)
EMAIL_EXISTS_FOR_SIGNUP = (
    'An account with this email already exists. Log in with your email and password, then link Spotify from '
    'your profile.'
)
ALREADY_LINKED_FOR_SIGNUP = 'That Spotify account already has a FitPro account. Use "Log in with Spotify" instead.'
SIGNUP_RETRY = "Signing up with Spotify didn't finish. Please try again."
UNLINK_BLOCKED = (
    "You signed up with Spotify, so it is your only way to log in. Spotify can't be disconnected until your "
    'account has a password.'
)


class SpotifyAccountError(Exception):
    """A link, login, signup, or unlink that the rules don't allow. The message is safe to show the user."""


class NotLinked(Exception):
    """The user has no Spotify account linked."""


class NeedsRelink(Exception):
    """The stored refresh token no longer works; the user has to link Spotify again."""


# --- Tokens ----------------------------------------------------------------------------------------------------


def _store_tokens(account: SpotifyAccount, tokens: client.Tokens) -> None:
    account.access_token = tokens.access_token
    account.expires_at = timezone.now() + timedelta(seconds=tokens.expires_in)
    if tokens.scope:
        account.scopes = tokens.scope
    # Spotify only sometimes rotates the refresh token; keep the old one unless a new one came back.
    if tokens.refresh_token:
        account.refresh_token = tokens.refresh_token
    account.needs_relink = False


def _is_fresh(account: SpotifyAccount) -> bool:
    return bool(account.access_token and account.expires_at and account.expires_at - timezone.now() > REFRESH_MARGIN)


def get_access_token(user) -> str:
    """A valid access token for `user`'s Spotify account, refreshing it if it expires within a minute.

    Raises NotLinked, NeedsRelink (the refresh token was rejected; tokens are cleared and needs_relink is set), or
    client.SpotifyUnavailable / client.SpotifyError when Spotify can't answer.
    """
    account = SpotifyAccount.objects.filter(user=user).first()
    if account is None:
        raise NotLinked
    if account.needs_relink:
        raise NeedsRelink
    if _is_fresh(account):
        return account.access_token

    with transaction.atomic():
        # Lock the row so parallel requests refresh once: the others wait here, then see the fresh token.
        account = SpotifyAccount.objects.select_for_update().get(pk=account.pk)
        if account.needs_relink:
            raise NeedsRelink
        if _is_fresh(account):
            return account.access_token
        # No refresh token means one that could no longer be decrypted; it is as unusable as a rejected one.
        if account.refresh_token:
            try:
                tokens = client.refresh_access_token(account.refresh_token)
            except client.InvalidGrant:
                pass
            else:
                _store_tokens(account, tokens)
                account.save()
                return account.access_token
        # Saved inside the transaction and raised after it, so the cleared tokens are committed, not rolled back.
        account.clear_tokens()
        account.needs_relink = True
        account.save()
    logger.info('Spotify refresh token rejected for user %s; relink needed', account.user_id)
    raise NeedsRelink


@dataclass(frozen=True)
class Status:
    state: str  # ok, error, needs_relink, not_linked
    message: str
    display_name: str = ''

    def as_json(self) -> dict[str, str]:
        return {'state': self.state, 'message': self.message, 'display_name': self.display_name}


def connection_status(user) -> Status:
    """Prove the link works end to end: get a token (refreshing if needed) and call GET /v1/me with it."""
    try:
        profile = client.current_user(get_access_token(user))
    except NotLinked:
        return Status('not_linked', 'Spotify not connected.')
    except NeedsRelink:
        return Status('needs_relink', 'Spotify access was revoked or expired. Link Spotify again to reconnect.')
    except client.SpotifyUnavailable:
        return Status('error', "Spotify isn't responding right now. Try again in a few minutes.")
    except client.SpotifyError:
        return Status('error', 'Spotify rejected the connection check. Try disconnecting and linking again.')

    account = SpotifyAccount.objects.get(user=user)
    if profile.id != account.spotify_id:
        logger.warning('Spotify token for user %s belongs to a different Spotify user', account.user_id)
        return Status('error', 'The connected Spotify account changed. Disconnect and link it again.')
    if profile.display_name and profile.display_name != account.display_name:
        account.display_name = profile.display_name
        account.save(update_fields=['display_name', 'updated_at'])
    return Status('ok', 'Connection OK.', account.name)


# --- Linking, logging in, signing up, unlinking -------------------------------------------------------------------


def link(user, profile: client.Profile, tokens: client.Tokens) -> SpotifyAccount:
    """Attach the Spotify account to `user` (or refresh the link if it is already theirs)."""
    try:
        with transaction.atomic():
            other = SpotifyAccount.objects.select_for_update().filter(spotify_id=profile.id).first()
            if other and other.user_id != user.pk:
                raise SpotifyAccountError(ALREADY_LINKED_ELSEWHERE)
            account = SpotifyAccount.objects.select_for_update().filter(user=user).first()
            if account is None:
                account = SpotifyAccount(user=user)
            account.spotify_id = profile.id
            account.display_name = profile.display_name
            _store_tokens(account, tokens)
            account.save()
    except IntegrityError:
        # Lost a race with another link of the same Spotify id; the unique constraint caught it.
        raise SpotifyAccountError(ALREADY_LINKED_ELSEWHERE) from None
    logger.info('Spotify linked for user %s', user.pk)
    return account


def user_for_login(profile: client.Profile, tokens: client.Tokens) -> User:
    """The active user linked to this Spotify id, with fresh tokens stored. Never falls back to email."""
    with transaction.atomic():
        account = (
            SpotifyAccount.objects.select_for_update().select_related('user').filter(spotify_id=profile.id).first()
        )
        if account is None or not account.user.is_active:
            raise SpotifyAccountError(NOT_LINKED_FOR_LOGIN)
        if profile.display_name:
            account.display_name = profile.display_name
        _store_tokens(account, tokens)
        account.save()
    return account.user


def sign_up(profile: client.Profile, tokens: client.Tokens) -> User:
    """Create a FitPro user with no password, linked to this Spotify account."""
    if SpotifyAccount.objects.filter(spotify_id=profile.id).exists():
        raise SpotifyAccountError(ALREADY_LINKED_FOR_SIGNUP)
    if profile.email and User.objects.filter(email__iexact=profile.email).exists():
        raise SpotifyAccountError(EMAIL_EXISTS_FOR_SIGNUP)
    try:
        with transaction.atomic():
            user = User(username=_unique_username(profile), email=profile.email)
            user.set_unusable_password()
            user.save()
            UserProfile.objects.create(user=user)
            account = SpotifyAccount(user=user, spotify_id=profile.id, display_name=profile.display_name)
            _store_tokens(account, tokens)
            account.save()
    except IntegrityError:
        # A parallel request took the Spotify id, the email, or the username between the checks and the insert; the
        # unique indexes caught it and the transaction rolled back. Say which, now that the other row is committed.
        if SpotifyAccount.objects.filter(spotify_id=profile.id).exists():
            raise SpotifyAccountError(ALREADY_LINKED_FOR_SIGNUP) from None
        if profile.email and User.objects.filter(email__iexact=profile.email).exists():
            raise SpotifyAccountError(EMAIL_EXISTS_FOR_SIGNUP) from None
        raise SpotifyAccountError(SIGNUP_RETRY) from None
    logger.info('User %s signed up with Spotify', user.pk)
    return user


def _unique_username(profile: client.Profile) -> str:
    """A readable username from the Spotify name, without "@" (usernames can't look like emails, see accounts)."""
    base = (slugify(profile.display_name) or slugify(profile.id) or 'spotify-user')[:140]
    candidate, n = base, 1
    while User.objects.filter(username__iexact=candidate).exists():
        n += 1
        candidate = f'{base}-{n}'
    return candidate


def unlink(user) -> None:
    """Forget the Spotify account and its tokens. Refused if Spotify is the user's only way to log in."""
    if not user.has_usable_password():
        raise SpotifyAccountError(UNLINK_BLOCKED)
    deleted, _ = SpotifyAccount.objects.filter(user=user).delete()
    if deleted:
        logger.info('Spotify unlinked for user %s', user.pk)
