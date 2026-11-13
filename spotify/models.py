from django.conf import settings
from django.db import models

from .fields import EncryptedTextField


class SpotifyAccount(models.Model):
    """A FitPro user's linked Spotify account and its OAuth tokens (story D-7, ADR-010).

    Keyed on the Spotify user id from GET /v1/me, never on email. Both tokens are encrypted at rest and must never
    be logged, rendered, or returned from an endpoint; read the access token through
    `spotify.services.get_access_token`, which refreshes it.
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='spotify_account')
    spotify_id = models.CharField(max_length=255, unique=True)
    display_name = models.CharField(max_length=255, blank=True)
    refresh_token = EncryptedTextField(blank=True)
    access_token = EncryptedTextField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    scopes = models.TextField(blank=True, help_text='Space-separated scopes Spotify granted, as it returned them.')
    # Set when Spotify rejects the refresh token (revoked access, or a token we can no longer decrypt).
    needs_relink = models.BooleanField(default=False)
    linked_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Spotify account {self.spotify_id} for user {self.user_id}'

    @property
    def name(self) -> str:
        """What to call the account on screen: the Spotify display name, or the id if the user has none."""
        return self.display_name or self.spotify_id

    def scope_list(self) -> list[str]:
        return self.scopes.split()

    def clear_tokens(self) -> None:
        # Empty means "no token" (see EncryptedTextField), not a hard-coded credential.
        self.access_token = ''  # nosec B105
        self.refresh_token = ''  # nosec B105
        self.expires_at = None
