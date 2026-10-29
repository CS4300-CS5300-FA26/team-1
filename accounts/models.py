from django.db import models
from django.utils import timezone


class ThrottleEvent(models.Model):
    """One counted attempt (failed login, registration POST) used for rate limiting.

    Stored in the database rather than the cache because the Deployment runs several pods and
    Django's default cache is per-process, which would multiply every limit by the pod count.
    `key` is a hash, so no emails or usernames are written to this table.
    """

    scope = models.CharField(max_length=32)
    key = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=['scope', 'key', 'created_at'])]
