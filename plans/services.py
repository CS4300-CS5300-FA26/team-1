import logging
from datetime import timedelta

from django.utils import timezone

from .generator import generate_plan
from .models import WeeklyPlan
from .starter import starter_plan

logger = logging.getLogger(__name__)


def week_start_for(day):
    """The Monday of the week containing `day`."""
    return day - timedelta(days=day.weekday())


def get_weekly_plan(profile, today=None):
    """Return (plan, is_starter) for the profile's user for the week containing `today`.

    The first visit of a week generates and saves the plan; later visits reuse it. If the
    generator fails, the starter plan is returned and nothing is saved, so the next visit
    tries the generator again.
    """
    today = today or timezone.localdate()
    week_start = week_start_for(today)

    saved = WeeklyPlan.objects.filter(user=profile.user, week_start=week_start).first()
    if saved:
        return saved.data, False

    try:
        plan = generate_plan(profile)
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
