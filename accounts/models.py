from django.db import models
from django.utils import timezone


class ThrottleCounter(models.Model):
    """Attempts counted so far in the current rate-limit window for one key.

    Stored in the database rather than the cache because the Deployment runs several pods and
    Django's default cache is per-process, which would multiply every limit by the pod count.
    There is one row per (scope, key), which concurrent requests lock while they check and
    increment it (see `accounts.throttle.acquire`). `key` is a hash, so no emails or usernames
    are written to this table.
    """

    scope = models.CharField(max_length=32)
    key = models.CharField(max_length=64)
    count = models.PositiveIntegerField(default=0)
    window_started = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['scope', 'key'], name='accounts_throttle_scope_key_uniq')]
        # Serves the cleanup of expired windows, which filters on this column alone.
        indexes = [models.Index(fields=['window_started'])]

    def __str__(self):
        return f'{self.scope}: {self.count} since {self.window_started:%Y-%m-%d %H:%M:%S}'
