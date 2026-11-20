"""Account lifecycle for email confirmation (ADR-018).

An account is inactive (`is_active=False`) until its email is confirmed. Django's ModelBackend refuses inactive users,
so they can't log in with a password or keep a session, and Spotify login refuses them too.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

logger = logging.getLogger('accounts.security')
User = get_user_model()


def prune_unconfirmed_accounts() -> None:
    """Delete sign-ups whose confirmation link has expired, so they stop holding a username or an email.

    Only accounts that never logged in are removed; FitPro has no other way to deactivate an account.
    """
    cutoff = timezone.now() - timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT)
    deleted, _ = User.objects.filter(is_active=False, last_login__isnull=True, date_joined__lt=cutoff).delete()
    if deleted:
        logger.info('Deleted %s unconfirmed sign-up records', deleted)


def confirm_email(user) -> None:
    """The person opened the confirmation link, which proves they control the address: activate the account."""
    user.is_active = True
    user.save(update_fields=['is_active'])
    logger.info('Email confirmed for user %s', user.pk)


def claim_unconfirmed_account(user) -> None:
    """A password reset proved control of the address on an account that was never confirmed.

    Someone else may have created the account with this address (for example through "Sign up with Spotify", whose
    emails aren't verified), so remove any Spotify link before activating it. Only the inbox owner keeps access.
    """
    from spotify.models import SpotifyAccount  # spotify imports accounts, so import here, not at module level

    unlinked, _ = SpotifyAccount.objects.filter(user=user).delete()
    confirm_email(user)
    if unlinked:
        logger.warning('Unconfirmed account %s claimed through a password reset; its Spotify link was removed', user.pk)
