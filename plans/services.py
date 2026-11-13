import logging
from datetime import timedelta
from enum import Enum

from django.db import transaction
from django.utils import timezone

from .generator import available_splits, generate_plan, next_split, split_of
from .models import WeeklyPlan
from .starter import starter_plan

logger = logging.getLogger(__name__)

MAX_SPLIT_SWITCHES = 3  # how many times a user can swap an existing weekly plan's split (ADR-013)
NEXT_SPLIT = 'next'  # the "Switch it up" choice: move to the next split in rotation


class SwitchResult(Enum):
    CHANGED = 'changed'
    UNCHANGED = 'unchanged'  # the user picked the split they are already on
    LIMIT = 'limit'  # no switches left this week
    UNAVAILABLE = 'unavailable'  # that split can't be used right now


def week_start_for(day):
    """The Monday of the week containing `day`."""
    return day - timedelta(days=day.weekday())


def _previous_split(user, week_start):
    """The split style of the user's most recent plan from an earlier week, or None."""
    previous = WeeklyPlan.objects.filter(user=user, week_start__lt=week_start).first()  # newest first
    return split_of(previous.data) if previous else None


def get_weekly_plan(profile, today=None):
    """Return (plan, is_starter) for the profile's user for the week containing `today`.

    The first visit of a week generates and saves the plan, using the split after last week's in
    rotation so the routine changes from week to week (ADR-013); later visits reuse it. If the
    generator fails, the starter plan is returned and nothing is saved, so the next visit tries
    the generator again.
    """
    today = today or timezone.localdate()
    week_start = week_start_for(today)

    saved = WeeklyPlan.objects.filter(user=profile.user, week_start=week_start).first()
    if saved:
        return saved.data, False

    try:
        plan = generate_plan(profile, after=_previous_split(profile.user, week_start))
    except Exception:  # any generator failure (bad data, bug, future external service) falls back
        logger.exception('Plan generation failed for user %s; showing the starter plan', profile.user_id)
        return starter_plan(), True

    # get_or_create so two simultaneous first visits don't create two rows.
    saved, _ = WeeklyPlan.objects.get_or_create(
        user=profile.user,
        week_start=week_start,
        defaults={'data': plan},
    )
    return saved.data, False


def switch_split(profile, choice, today=None):
    """Change this week's split to `choice` (a split key, or NEXT_SPLIT) and return a SwitchResult.

    With no saved plan yet, this simply creates the week's plan with that split and uses up no
    switch. With one, the workouts are rebuilt in the new split but the saved macro targets are
    kept (profile changes apply from next week, ADR-012), and one of the weekly switches is used.
    The plan row is locked so two quick requests can't get past the limit.
    """
    today = today or timezone.localdate()
    week_start = week_start_for(today)
    try:
        with transaction.atomic():
            saved = WeeklyPlan.objects.select_for_update().filter(user=profile.user, week_start=week_start).first()
            if saved is None:
                if choice == NEXT_SPLIT:
                    plan = generate_plan(profile, after=_previous_split(profile.user, week_start))
                else:
                    plan = generate_plan(profile, split=choice)
                WeeklyPlan.objects.create(user=profile.user, week_start=week_start, data=plan)
                return SwitchResult.CHANGED

            current = split_of(saved.data)
            trained = sum(1 for day in saved.data['days'] if day['exercises'])
            target = next_split(current, trained) if choice == NEXT_SPLIT else choice
            if target == current:
                return SwitchResult.UNCHANGED
            if target not in available_splits(trained):
                return SwitchResult.UNAVAILABLE
            switches = saved.data.get('switches', 0)
            if switches >= MAX_SPLIT_SWITCHES:
                return SwitchResult.LIMIT

            plan = generate_plan(profile, split=target)
            plan['macros'] = saved.data['macros']
            plan['switches'] = switches + 1
            saved.data = plan
            saved.save(update_fields=['data'])
            return SwitchResult.CHANGED
    except Exception:  # generator failure, bad data, or a creation race: leave the plan as it was
        logger.exception('Switching the workout split failed for user %s', profile.user_id)
        return SwitchResult.UNAVAILABLE
