"""Workout plans and sessions for the views: the stored weekly plan, starting and logging a workout, and history.

Every function takes the user and only reads or writes that user's rows (AGENTS.md "Authorization").
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Max, Sum
from django.utils import timezone

from core.models import UserProfile

from .domain import DAY_NAMES, DAYS_PER_WEEK_CHOICES, DEFAULT_DAYS
from .models import (
    Exercise,
    LoggedSet,
    PlannedExercise,
    PlannedWorkout,
    WorkoutPlan,
    WorkoutPreference,
    WorkoutSession,
)
from .planner import PlanInputs, plan_week

# Bump when the planner's rules change, so stored plans made by older rules are remade.
PLANNER_VERSION = 1


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def days_per_week(user: User, profile: UserProfile) -> int:
    """The user's chosen training days, else the default for their experience level."""
    chosen = WorkoutPreference.objects.filter(user=user).values_list('days_per_week', flat=True).first()
    return chosen if chosen in DAYS_PER_WEEK_CHOICES else DEFAULT_DAYS.get(profile.experience_level, 3)


def plan_inputs(user: User, profile: UserProfile) -> dict:
    """What a plan is made from, as stored on it. When this changes, the stored plan is remade."""
    return {
        'goal': profile.goal,
        'experience': profile.experience_level,
        'equipment': sorted(profile.equipment),
        'days': days_per_week(user, profile),
        'version': PLANNER_VERSION,
    }


def set_days_per_week(user: User, days: int) -> None:
    if days not in DAYS_PER_WEEK_CHOICES:
        raise ValueError(f'Unsupported training days: {days}')
    WorkoutPreference.objects.update_or_create(user=user, defaults={'days_per_week': days})


# --- The weekly plan ------------------------------------------------------------------------------------------------


def current_plan(user: User, profile: UserProfile, today: date | None = None) -> WorkoutPlan:
    """This week's plan, made the first time it's asked for and reused all week.

    It is remade when what it was made from changes (goal, experience, equipment, training days, planner rules) or
    when one of its exercises has left the catalog.
    """
    week_start = monday_of(today or timezone.localdate())
    inputs = plan_inputs(user, profile)
    plan = WorkoutPlan.objects.filter(user=user, week_start=week_start).first()
    if plan is not None and plan.inputs == inputs and not _has_retired_exercise(plan):
        return plan
    return _make_plan(user, week_start, inputs, seed=plan.seed if plan else week_start.toordinal())


def new_plan(user: User, profile: UserProfile, today: date | None = None) -> WorkoutPlan:
    """Replace this week's plan with a different selection of exercises."""
    week_start = monday_of(today or timezone.localdate())
    existing = WorkoutPlan.objects.filter(user=user, week_start=week_start).first()
    seed = existing.seed + 1 if existing else week_start.toordinal()
    return _make_plan(user, week_start, plan_inputs(user, profile), seed=seed)


def _has_retired_exercise(plan: WorkoutPlan) -> bool:
    return PlannedExercise.objects.filter(workout__plan=plan, exercise__is_active=False).exists()


def _make_plan(user: User, week_start: date, inputs: dict, seed: int) -> WorkoutPlan:
    catalog = dict(Exercise.objects.filter(is_active=True).values_list('source_id', 'pk'))
    days = plan_week(
        PlanInputs(
            goal=inputs['goal'],
            experience=inputs['experience'],
            equipment=tuple(inputs['equipment']),
            days=inputs['days'],
            seed=seed,
        ),
        catalog,
    )
    try:
        with transaction.atomic():
            # Sessions already logged against the old plan survive it (their link to it is cleared).
            WorkoutPlan.objects.filter(user=user, week_start=week_start).delete()
            plan = WorkoutPlan.objects.create(user=user, week_start=week_start, inputs=inputs, seed=seed)
            for day in days:
                workout = PlannedWorkout.objects.create(plan=plan, day=day.day, title=day.title)
                PlannedExercise.objects.bulk_create(
                    PlannedExercise(
                        workout=workout,
                        position=position,
                        exercise_id=item.exercise_id,
                        sets=item.prescription.sets,
                        reps_min=item.prescription.reps_min,
                        reps_max=item.prescription.reps_max,
                        rest_seconds=item.prescription.rest_seconds,
                        minutes=item.prescription.minutes,
                    )
                    for position, item in enumerate(day.items, start=1)
                )
    except IntegrityError:
        # Another request made this week's plan at the same moment; use theirs.
        return WorkoutPlan.objects.get(user=user, week_start=week_start)
    return plan


@dataclass(frozen=True)
class DayOverview:
    index: int
    name: str
    date: date
    is_today: bool
    workout: PlannedWorkout | None
    session: WorkoutSession | None

    @property
    def status(self) -> str:
        if self.workout is None:
            return 'rest'
        if self.session is None:
            return 'planned'
        return 'done' if self.session.is_complete else 'in_progress'


def week_overview(plan: WorkoutPlan, today: date | None = None) -> list[DayOverview]:
    today = today or timezone.localdate()
    workouts = {
        workout.day: workout for workout in plan.workouts.prefetch_related('exercises__exercise').order_by('day')
    }
    sessions = {
        session.planned_workout_id: session
        for session in WorkoutSession.objects.filter(planned_workout__plan=plan, user=plan.user)
    }
    overview = []
    for index, name in enumerate(DAY_NAMES):
        workout = workouts.get(index)
        overview.append(
            DayOverview(
                index=index,
                name=name,
                date=plan.week_start + timedelta(days=index),
                is_today=plan.week_start + timedelta(days=index) == today,
                workout=workout,
                session=sessions.get(workout.pk) if workout else None,
            )
        )
    return overview


def training_days(user: User, week_start: date) -> frozenset[int] | None:
    """Which weekdays (0 = Monday) the user trains that week, for macro targets (D-4: rest days vs training days).

    Reads the stored plan and never makes one. `None` means the user has no plan that week yet.
    """
    plan = WorkoutPlan.objects.filter(user=user, week_start=monday_of(week_start)).first()
    if plan is None:
        return None
    return frozenset(plan.workouts.values_list('day', flat=True))


# --- Doing a workout ------------------------------------------------------------------------------------------------


def start_session(user: User, workout: PlannedWorkout, today: date | None = None) -> WorkoutSession:
    """The session for a planned workout: the one already started, or a new one. Safe to call twice."""
    today = today or timezone.localdate()
    try:
        with transaction.atomic():
            session, _ = WorkoutSession.objects.get_or_create(
                planned_workout=workout, defaults={'user': user, 'title': workout.title, 'performed_on': today}
            )
    except IntegrityError:
        session = WorkoutSession.objects.get(planned_workout=workout)
    return session


@dataclass(frozen=True)
class SetRow:
    number: int
    reps: int | None
    weight_lb: Decimal | None
    minutes: int | None


@dataclass(frozen=True)
class ExerciseLog:
    planned: PlannedExercise
    rows: list[SetRow]
    last_weight_lb: Decimal | None


def session_log(session: WorkoutSession) -> list[ExerciseLog]:
    """Each exercise of the session's planned workout with a row per planned set, filled in from what's logged.

    Empty weights start from the last weight the user logged for that exercise, so the next workout needs few edits.
    """
    if session.planned_workout is None:
        return []
    planned = list(session.planned_workout.exercises.select_related('exercise'))
    logged: dict[tuple[int, int], LoggedSet] = {(s.exercise_id, s.set_number): s for s in session.sets.all()}
    last_weights = last_weights_for(session.user, [p.exercise_id for p in planned], before=session)
    result = []
    for item in planned:
        rows = []
        for number in range(1, item.sets + 1):
            saved = logged.get((item.exercise_id, number))
            rows.append(
                SetRow(
                    number=number,
                    reps=saved.reps if saved else None,
                    weight_lb=saved.weight_lb if saved else last_weights.get(item.exercise_id),
                    minutes=saved.minutes if saved else None,
                )
            )
        result.append(ExerciseLog(planned=item, rows=rows, last_weight_lb=last_weights.get(item.exercise_id)))
    return result


def last_weights_for(
    user: User, exercise_ids: Iterable[int], before: WorkoutSession | None = None
) -> dict[int, Decimal]:
    """The heaviest weight in the user's most recent session for each exercise (their own sets only)."""
    weights: dict[int, Decimal] = {}
    for exercise_id in exercise_ids:
        sets = LoggedSet.objects.filter(session__user=user, exercise_id=exercise_id, weight_lb__isnull=False)
        if before is not None:
            sets = sets.exclude(session=before)
        latest = (
            sets.order_by('-session__performed_on', '-session__started_at').values_list('session', flat=True).first()
        )
        if latest is not None:
            best = sets.filter(session=latest).aggregate(best=Max('weight_lb'))['best']
            if best is not None:
                weights[exercise_id] = best
    return weights


@transaction.atomic
def save_session(
    session: WorkoutSession,
    entries: Mapping[tuple[int, int], tuple[int | None, Decimal | None, int | None]],
    finish: bool,
) -> None:
    """Store the sets the user filled in. `entries` maps (exercise id, set number) to (reps, weight, minutes); a set
    with neither reps nor minutes is not stored (and a stored one the user cleared is removed)."""
    for (exercise_id, number), (reps, weight, minutes) in entries.items():
        if not reps and not minutes:
            LoggedSet.objects.filter(session=session, exercise_id=exercise_id, set_number=number).delete()
            continue
        LoggedSet.objects.update_or_create(
            session=session,
            exercise_id=exercise_id,
            set_number=number,
            defaults={
                'reps': reps or None,
                'weight_lb': weight if reps else None,
                'minutes': None if reps else minutes,
            },
        )
    if finish and session.completed_at is None:
        session.completed_at = timezone.now()
        session.save(update_fields=['completed_at'])


# --- History and progress -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WeekSummary:
    week_start: date
    planned: int
    completed: int
    volume_lb: Decimal


def weekly_summaries(user: User, weeks: int = 8, today: date | None = None) -> list[WeekSummary]:
    """Consistency (workouts completed against planned) and volume (reps x weight lifted) for the last `weeks`
    weeks, newest first. Weeks with no plan count what was done against 0 planned."""
    this_monday = monday_of(today or timezone.localdate())
    first_monday = this_monday - timedelta(weeks=weeks - 1)

    planned = {
        plan.week_start: plan.workouts.count()
        for plan in WorkoutPlan.objects.filter(user=user, week_start__gte=first_monday)
    }
    completed: dict[date, int] = {}
    for performed_on in WorkoutSession.objects.filter(
        user=user, completed_at__isnull=False, performed_on__gte=first_monday
    ).values_list('performed_on', flat=True):
        week = monday_of(performed_on)
        completed[week] = completed.get(week, 0) + 1
    volume: dict[date, Decimal] = {}
    lifted = (
        LoggedSet.objects.filter(
            session__user=user, session__completed_at__isnull=False, session__performed_on__gte=first_monday
        )
        .values('session__performed_on')
        .annotate(
            total=Sum(
                ExpressionWrapper(
                    F('reps') * F('weight_lb'), output_field=DecimalField(max_digits=14, decimal_places=1)
                )
            )
        )
    )
    for row in lifted:
        if row['total'] is not None:
            week = monday_of(row['session__performed_on'])
            volume[week] = volume.get(week, Decimal(0)) + row['total']

    return [
        WeekSummary(
            week_start=monday,
            planned=planned.get(monday, 0),
            completed=completed.get(monday, 0),
            volume_lb=volume.get(monday, Decimal(0)),
        )
        for monday in (this_monday - timedelta(weeks=n) for n in range(weeks))
    ]


def recent_sessions(user: User, limit: int = 20) -> list[WorkoutSession]:
    return list(WorkoutSession.objects.filter(user=user, completed_at__isnull=False).prefetch_related('sets')[:limit])


def session_totals(session: WorkoutSession) -> tuple[int, Decimal]:
    """Sets done and volume (reps x weight) for one session."""
    sets = list(session.sets.all())
    volume = sum((Decimal(s.reps) * s.weight_lb for s in sets if s.reps and s.weight_lb), Decimal(0))
    return len(sets), volume
