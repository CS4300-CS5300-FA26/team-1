"""The workouts side of the plans app's tracker connector (plans/tracking.py, wired as `PLANS_WORKOUT_TRACKER`).

For each training day of the week's saved plan, it tells This Week whether to offer Start, Continue, or View.
It only reads; starting a workout is a POST to `workouts_start`.
"""

from collections.abc import Sequence
from datetime import date

from django.contrib.auth.models import User
from django.urls import reverse

from plans.models import WeeklyPlan
from plans.tracking import DayAction, WorkoutLinks

from .services import sessions_by_day


class SessionTracker:
    def links(self, user: User, week_start: date, days: Sequence[dict]) -> WorkoutLinks:
        plan = WeeklyPlan.objects.filter(user=user, week_start=week_start).first()
        sessions = sessions_by_day(user, plan) if plan else {}
        actions = {}
        for index, day in enumerate(days):
            if not day.get('exercises'):
                continue
            session = sessions.get(index)
            if session is None:
                actions[index] = DayAction(
                    label='Start workout', url=reverse('workouts_start', args=[index]), post=True
                )
            elif session.is_complete:
                actions[index] = DayAction(
                    label='View workout', url=reverse('workouts_session', args=[session.pk]), status='Done'
                )
            else:
                actions[index] = DayAction(
                    label='Continue workout', url=reverse('workouts_session', args=[session.pk]), status='In progress'
                )
        return WorkoutLinks(days=actions, history_url=reverse('workouts_history'))
