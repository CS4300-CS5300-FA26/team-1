from django.conf import settings
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


class SavedMealPlan(models.Model):
    """A meal plan the user chose to keep for one week (Monday `week_start` to the Sunday after).

    `plan` is a snapshot of the validated plan (see nutrition/plan_store.py), so a saved week stays the
    same even when the recipe source's results change.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='saved_meal_plans')
    week_start = models.DateField()
    saved_at = models.DateTimeField(auto_now=True)
    plan = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'week_start'], name='nutrition_one_saved_plan_per_week')]
        ordering = ['-week_start']

    def __str__(self):
        return f'{self.user} week of {self.week_start}'
