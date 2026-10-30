"""A small shared cache for recipe API data, stored in the RecipeCacheEntry table."""

from datetime import timedelta
from typing import Any

from django.utils import timezone

from .models import RecipeCacheEntry


def get(key: str) -> Any | None:
    """The cached value, or None if it is missing or has expired."""
    entry = RecipeCacheEntry.objects.filter(key=key, expires_at__gt=timezone.now()).first()
    return entry.value if entry else None


def set(key: str, value: Any, seconds: int) -> None:  # noqa: A001 - mirrors django.core.cache's API
    """Store a JSON-serialisable value for `seconds`, and clear out anything that has expired."""
    now = timezone.now()
    RecipeCacheEntry.objects.update_or_create(
        key=key, defaults={'value': value, 'expires_at': now + timedelta(seconds=seconds)}
    )
    RecipeCacheEntry.objects.filter(expires_at__lte=now).delete()
