from django.db import models


class RecipeCacheEntry(models.Model):
    """A cached recipe API response (search results or one recipe's details); see nutrition/cache.py.

    Kept in the database, not Django's per-process cache, so every pod and restart shares one copy
    and the recipe API's daily quota is spent once rather than once per process.
    """

    key = models.CharField(max_length=200, unique=True)
    value = models.JSONField()
    expires_at = models.DateTimeField(db_index=True)

    def __str__(self):
        return self.key
