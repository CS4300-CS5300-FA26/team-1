from django.conf import settings
from django.db import models
from django.db.models import Q

from core.models import EQUIPMENT_CHOICES

from .domain import DAY_NAMES, OTHER_EQUIPMENT

EQUIPMENT_CLASS_CHOICES = [*EQUIPMENT_CHOICES, (OTHER_EQUIPMENT, 'Other equipment')]


class Exercise(models.Model):
    """One exercise from FitPro's catalog (data/exercise_catalog.json, ADR-014). Text only: no images or video.

    Used for the how-to steps shown while logging a workout (see exercise_links.py). An exercise that leaves the
    catalog file is marked `is_active=False` instead of being deleted.
    """

    source_id = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150)
    body_part = models.CharField(max_length=40)
    target = models.CharField(max_length=40)
    equipment = models.CharField(max_length=40)
    equipment_class = models.CharField(max_length=10, choices=EQUIPMENT_CLASS_CHOICES)
    secondary_muscles = models.JSONField(default=list)
    steps = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name', 'source_id']

    def __str__(self):
        return self.name


class WorkoutSession(models.Model):
    """One training day of the user's weekly plan (plans.WeeklyPlan, ADR-012) that they started.

    `exercises` is a copy of that day's exercises when the session started (the plan's own shape:
    `[{'name': ..., 'sets': ..., 'reps': ...}]`), so switching the week's split later doesn't change a workout that
    is under way or already done. The session is kept if the plan row goes away.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='workout_sessions')
    weekly_plan = models.ForeignKey(
        'plans.WeeklyPlan', on_delete=models.SET_NULL, null=True, blank=True, related_name='workout_sessions'
    )
    day = models.PositiveSmallIntegerField(choices=list(enumerate(DAY_NAMES)))
    title = models.CharField(max_length=60)
    exercises = models.JSONField(default=list)
    performed_on = models.DateField()
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-performed_on', '-started_at']
        constraints = [
            # One session per day of a weekly plan, so double-clicking Start can't make two.
            models.UniqueConstraint(
                fields=['weekly_plan', 'day'],
                condition=Q(weekly_plan__isnull=False),
                name='workouts_one_session_per_plan_day',
            ),
            models.CheckConstraint(condition=Q(day__lte=6), name='workouts_session_day_in_week'),
        ]

    def __str__(self):
        return f'{self.user} {self.title} on {self.performed_on}'

    @property
    def is_complete(self) -> bool:
        return self.completed_at is not None


class LoggedSet(models.Model):
    """One set the user did of the session's exercise at `position` (1 = the first exercise of the day).

    Exactly one of `reps` (with `weight_lb`, empty for bodyweight work), `seconds` (a hold such as a plank), or
    `minutes` (cardio). `exercise_name` is copied from the session so progress can be followed across weeks.
    """

    session = models.ForeignKey(WorkoutSession, on_delete=models.CASCADE, related_name='sets')
    position = models.PositiveSmallIntegerField()
    exercise_name = models.CharField(max_length=100)
    set_number = models.PositiveSmallIntegerField()
    reps = models.PositiveSmallIntegerField(null=True, blank=True)
    weight_lb = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    seconds = models.PositiveSmallIntegerField(null=True, blank=True)
    minutes = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ['session', 'position', 'set_number']
        constraints = [
            models.UniqueConstraint(fields=['session', 'position', 'set_number'], name='workouts_one_set_per_number'),
            models.CheckConstraint(condition=Q(position__gt=0), name='workouts_set_position_positive'),
            models.CheckConstraint(condition=Q(set_number__gt=0), name='workouts_set_number_positive'),
            # Exactly one of reps, seconds, or minutes, and only reps can carry a weight.
            models.CheckConstraint(
                condition=(
                    Q(reps__gt=0, seconds__isnull=True, minutes__isnull=True)
                    | Q(seconds__gt=0, reps__isnull=True, minutes__isnull=True, weight_lb__isnull=True)
                    | Q(minutes__gt=0, reps__isnull=True, seconds__isnull=True, weight_lb__isnull=True)
                ),
                name='workouts_set_one_amount',
            ),
            models.CheckConstraint(
                condition=Q(weight_lb__isnull=True) | Q(weight_lb__gte=0), name='workouts_set_weight_not_negative'
            ),
        ]

    def __str__(self):
        if self.minutes:
            amount = f'{self.minutes} min'
        elif self.seconds:
            amount = f'{self.seconds} sec'
        else:
            amount = f'{self.reps} reps'
        return f'{self.exercise_name} set {self.set_number}: {amount}'
