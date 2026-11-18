"""Doing the workouts of the weekly plan: starting a training day, logging its sets, and history.

The week's split comes from the `plans` app (plans.WeeklyPlan, ADR-012); this module never makes or changes a plan.
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

from plans.models import WeeklyPlan
from plans.services import week_start_for

from .domain import MINUTES, Target, parse_target
from .exercise_links import catalog_id_for
from .models import Exercise, LoggedSet, WorkoutSession


class NotATrainingDay(ValueError):
    """The day asked for is a rest day, or not a day of the plan."""


def current_weekly_plan(user: User, today: date | None = None) -> WeeklyPlan | None:
    """This week's saved plan, or None. Never makes one: the plans app does that when This Week is opened."""
    week_start = week_start_for(today or timezone.localdate())
    return WeeklyPlan.objects.filter(user=user, week_start=week_start).first()


def training_day(plan: WeeklyPlan, day: int) -> dict:
    """The plan's entry for weekday `day` (0 = Monday), if it has exercises."""
    days = plan.data.get('days') or []
    if not 0 <= day < len(days) or not days[day].get('exercises'):
        raise NotATrainingDay(day)
    return days[day]


def start_session(user: User, plan: WeeklyPlan, day: int, today: date | None = None) -> WorkoutSession:
    """The session for one training day of the user's plan: the one already started, or a new one. Safe to call
    twice."""
    if plan.user_id != user.pk:
        raise NotATrainingDay(day)  # never start a session on someone else's plan
    entry = training_day(plan, day)
    try:
        with transaction.atomic():
            session, _ = WorkoutSession.objects.get_or_create(
                weekly_plan=plan,
                day=day,
                defaults={
                    'user': user,
                    'title': str(entry.get('name') or 'Workout')[:60],
                    'exercises': [
                        {
                            'name': str(item['name'])[:100],
                            'sets': item.get('sets', 1),
                            'reps': str(item.get('reps', '')),
                        }
                        for item in entry['exercises']
                    ],
                    'performed_on': today or timezone.localdate(),
                },
            )
    except IntegrityError:
        session = WorkoutSession.objects.get(weekly_plan=plan, day=day)
    return session


def sessions_by_day(user: User, plan: WeeklyPlan) -> dict[int, WorkoutSession]:
    return {session.day: session for session in WorkoutSession.objects.filter(user=user, weekly_plan=plan)}


# --- Logging a workout ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SetRow:
    number: int
    reps: int | None
    weight_lb: Decimal | None
    seconds: int | None
    minutes: int | None


@dataclass(frozen=True)
class ExerciseLog:
    position: int
    name: str
    target: Target
    catalog: Exercise | None
    rows: list[SetRow]
    last_weight_lb: Decimal | None


def session_log(session: WorkoutSession) -> list[ExerciseLog]:
    """Each exercise of the session with a row per planned set, filled in from what's logged.

    Empty weights start from the last weight the user logged for that exercise, so the next workout needs few edits.
    """
    exercises = [item for item in session.exercises if isinstance(item, dict) and item.get('name')]
    logged = {(s.position, s.set_number): s for s in session.sets.all()}
    names = [item['name'] for item in exercises]
    last_weights = last_weights_for(session.user, names, before=session)
    ids = {name: catalog_id_for(name) for name in names}
    catalog = {e.source_id: e for e in Exercise.objects.filter(source_id__in=[i for i in ids.values() if i])}

    result = []
    for position, item in enumerate(exercises, start=1):
        target = parse_target(item.get('sets', 1), item.get('reps', ''))
        name = item['name']
        rows = []
        for number in range(1, target.sets + 1):
            saved = logged.get((position, number))
            rows.append(
                SetRow(
                    number=number,
                    reps=saved.reps if saved else None,
                    weight_lb=saved.weight_lb if saved else last_weights.get(name),
                    seconds=saved.seconds if saved else None,
                    minutes=saved.minutes if saved else None,
                )
            )
        result.append(
            ExerciseLog(
                position=position,
                name=name,
                target=target,
                catalog=catalog.get(ids[name] or ''),
                rows=rows,
                last_weight_lb=last_weights.get(name) if target.kind != MINUTES else None,
            )
        )
    return result


def last_weights_for(user: User, names: Iterable[str], before: WorkoutSession | None = None) -> dict[str, Decimal]:
    """The heaviest weight in the user's most recent session for each exercise name (their own sets only)."""
    weights: dict[str, Decimal] = {}
    for name in set(names):
        sets = LoggedSet.objects.filter(session__user=user, exercise_name=name, weight_lb__isnull=False)
        if before is not None:
            sets = sets.exclude(session=before)
        latest = (
            sets.order_by('-session__performed_on', '-session__started_at').values_list('session', flat=True).first()
        )
        if latest is not None:
            best = sets.filter(session=latest).aggregate(best=Max('weight_lb'))['best']
            if best is not None:
                weights[name] = best
    return weights


# (position, set number) -> (reps, weight, seconds, minutes)
Entries = Mapping[tuple[int, int], tuple[int | None, Decimal | None, int | None, int | None]]


@transaction.atomic
def save_session(session: WorkoutSession, entries: Entries, names: Mapping[int, str], finish: bool) -> None:
    """Store the sets the user filled in. A set with no amount is not stored (and a stored one the user cleared is
    removed). `names` maps each position to its exercise name."""
    for (position, number), (reps, weight, seconds, minutes) in entries.items():
        if not reps and not seconds and not minutes:
            LoggedSet.objects.filter(session=session, position=position, set_number=number).delete()
            continue
        LoggedSet.objects.update_or_create(
            session=session,
            position=position,
            set_number=number,
            defaults={
                'exercise_name': names[position],
                'reps': reps or None,
                'weight_lb': weight if reps else None,
                'seconds': None if reps else (seconds or None),
                'minutes': None if reps or seconds else minutes,
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


def planned_workouts(plan: WeeklyPlan) -> int:
    return sum(1 for day in plan.data.get('days') or [] if day.get('exercises'))


def weekly_summaries(user: User, weeks: int = 8, today: date | None = None) -> list[WeekSummary]:
    """Consistency (workouts completed against planned) and volume (reps x weight lifted) for the last `weeks`
    weeks, newest first. Weeks with no plan count what was done against 0 planned."""
    this_monday = week_start_for(today or timezone.localdate())
    first_monday = this_monday - timedelta(weeks=weeks - 1)

    planned = {
        plan.week_start: planned_workouts(plan)
        for plan in WeeklyPlan.objects.filter(user=user, week_start__gte=first_monday)
    }
    completed: dict[date, int] = {}
    for performed_on in WorkoutSession.objects.filter(
        user=user, completed_at__isnull=False, performed_on__gte=first_monday
    ).values_list('performed_on', flat=True):
        week = week_start_for(performed_on)
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
            week = week_start_for(row['session__performed_on'])
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
