from django.contrib.auth.models import User
from django.db import models


class WeeklyPlan(models.Model):
    """The plan generated for one user for one week (Monday to Sunday).

    The plan itself is stored as JSON (see plans/generator.py for its shape) so the exercise
    library can change without a migration, and so a user sees the same plan all week.
    Besides what the generator returns, the JSON may hold 'switches': how many times the user
    has swapped this week's split (see plans/services.py and ADR-013).
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='weekly_plans')
    week_start = models.DateField()  # the Monday of the week this plan covers
    data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-week_start']
        constraints = [
            models.UniqueConstraint(fields=['user', 'week_start'], name='one_plan_per_user_per_week'),
        ]

    def __str__(self):
        return f'{self.user.username}: week of {self.week_start}'
