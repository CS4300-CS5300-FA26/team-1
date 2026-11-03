from django.conf import settings
from django.db import models
from django.db.models import Q

from core.models import EQUIPMENT_CHOICES

from .domain import DAY_NAMES, DAYS_PER_WEEK_CHOICES, OTHER_EQUIPMENT

EQUIPMENT_CLASS_CHOICES = [*EQUIPMENT_CHOICES, (OTHER_EQUIPMENT, 'Other equipment')]


class Exercise(models.Model):
    """One exercise from FitPro's catalog (data/exercise_catalog.json, ADR-009). Text only: no images or video.

    Exercises are never deleted, because logged sets point at them. One that leaves the catalog file is marked
    `is_active=False` instead and is no longer planned.
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


class WorkoutPreference(models.Model):
    """The user's own choices about training, kept here so onboarding's UserProfile is untouched."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='workout_preference')
    days_per_week = models.PositiveSmallIntegerField(
        choices=[(n, f'{n} days') for n in DAYS_PER_WEEK_CHOICES], null=True, blank=True
    )

    def __str__(self):
        return f'{self.user} trains {self.days_per_week or "default"} days a week'


class WorkoutPlan(models.Model):
    """A user's workout split for the week starting `week_start` (a Monday).

    `inputs` records what the plan was made for (goal, experience, equipment, days per week, planner version); when
    any of them changes, a new plan is made. `seed` rotates which exercises are picked, so a new plan differs.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='workout_plans')
    week_start = models.DateField()
    created_at = models.DateTimeField(auto_now=True)
    inputs = models.JSONField(default=dict)
    seed = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-week_start']
        constraints = [models.UniqueConstraint(fields=['user', 'week_start'], name='workouts_one_plan_per_week')]

    def __str__(self):
        return f'{self.user} week of {self.week_start}'


class PlannedWorkout(models.Model):
    """One training day of a weekly plan. Rest days have no row."""

    plan = models.ForeignKey(WorkoutPlan, on_delete=models.CASCADE, related_name='workouts')
    day = models.PositiveSmallIntegerField(choices=list(enumerate(DAY_NAMES)))
    title = models.CharField(max_length=60)

    class Meta:
        ordering = ['plan', 'day']
        constraints = [
            models.UniqueConstraint(fields=['plan', 'day'], name='workouts_one_workout_per_day'),
            models.CheckConstraint(condition=Q(day__lte=6), name='workouts_workout_day_in_week'),
        ]

    def __str__(self):
        return f'{DAY_NAMES[self.day]}: {self.title}'


class PlannedExercise(models.Model):
    """An exercise in a planned workout: sets of reps with rest, or minutes for cardio."""

    workout = models.ForeignKey(PlannedWorkout, on_delete=models.CASCADE, related_name='exercises')
    position = models.PositiveSmallIntegerField()
    exercise = models.ForeignKey(Exercise, on_delete=models.PROTECT, related_name='planned')
    sets = models.PositiveSmallIntegerField()
    reps_min = models.PositiveSmallIntegerField(null=True, blank=True)
    reps_max = models.PositiveSmallIntegerField(null=True, blank=True)
    rest_seconds = models.PositiveSmallIntegerField(null=True, blank=True)
    minutes = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ['workout', 'position']
        constraints = [
            models.UniqueConstraint(fields=['workout', 'position'], name='workouts_one_exercise_per_position'),
            models.CheckConstraint(condition=Q(sets__gt=0), name='workouts_planned_sets_positive'),
            # Strength work has a rep range and no minutes; cardio has minutes and no reps.
            models.CheckConstraint(
                condition=(
                    Q(
                        minutes__isnull=True,
                        reps_min__isnull=False,
                        reps_max__isnull=False,
                        reps_min__lte=models.F('reps_max'),
                    )
                    | Q(minutes__gt=0, reps_min__isnull=True, reps_max__isnull=True)
                ),
                name='workouts_planned_reps_or_minutes',
            ),
        ]

    def __str__(self):
        return f'{self.position}. {self.exercise}'

    @property
    def is_timed(self) -> bool:
        return self.minutes is not None

    def rep_range(self) -> str:
        if self.reps_min is None or self.reps_max is None:
            return ''
        return str(self.reps_min) if self.reps_min == self.reps_max else f'{self.reps_min}-{self.reps_max}'


class WorkoutSession(models.Model):
    """A workout the user did (or is doing). Kept after the plan it came from is replaced, so `title` is copied."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='workout_sessions')
    planned_workout = models.ForeignKey(
        PlannedWorkout, on_delete=models.SET_NULL, null=True, blank=True, related_name='sessions'
    )
    title = models.CharField(max_length=60)
    performed_on = models.DateField()
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-performed_on', '-started_at']
        constraints = [
            # One session per planned workout, so double-clicking Start can't make two.
            models.UniqueConstraint(
                fields=['planned_workout'],
                condition=Q(planned_workout__isnull=False),
                name='workouts_one_session_per_planned_workout',
            ),
        ]

    def __str__(self):
        return f'{self.user} {self.title} on {self.performed_on}'

    @property
    def is_complete(self) -> bool:
        return self.completed_at is not None


class LoggedSet(models.Model):
    """One set the user did: `reps` (with `weight_lb`, empty for bodyweight work), or `minutes` for cardio."""

    session = models.ForeignKey(WorkoutSession, on_delete=models.CASCADE, related_name='sets')
    exercise = models.ForeignKey(Exercise, on_delete=models.PROTECT, related_name='logged_sets')
    set_number = models.PositiveSmallIntegerField()
    reps = models.PositiveSmallIntegerField(null=True, blank=True)
    weight_lb = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    minutes = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ['session', 'exercise', 'set_number']
        constraints = [
            models.UniqueConstraint(fields=['session', 'exercise', 'set_number'], name='workouts_one_set_per_number'),
            models.CheckConstraint(condition=Q(set_number__gt=0), name='workouts_set_number_positive'),
            # Exactly one of reps or minutes, and only reps can carry a weight.
            models.CheckConstraint(
                condition=(
                    Q(reps__gt=0, minutes__isnull=True) | Q(minutes__gt=0, reps__isnull=True, weight_lb__isnull=True)
                ),
                name='workouts_set_reps_or_minutes',
            ),
            models.CheckConstraint(
                condition=Q(weight_lb__isnull=True) | Q(weight_lb__gte=0), name='workouts_set_weight_not_negative'
            ),
        ]

    def __str__(self):
        amount = f'{self.minutes} min' if self.minutes else f'{self.reps} reps'
        return f'{self.exercise} set {self.set_number}: {amount}'
