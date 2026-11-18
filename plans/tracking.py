"""The connector This Week uses to offer a way to do each workout (ADR-014), in the style of ADR-008's connectors.

`PLANS_WORKOUT_TRACKER` names a class by dotted path with a method
`links(user, week_start, days) -> WorkoutLinks`, where `days` are the saved plan's seven days, Monday first. The
`workouts` app provides it (workouts.tracker.SessionTracker). `plans` never imports that app: with the setting unset,
or if the tracker fails, This Week simply shows the plan without workout buttons.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from django.conf import settings
from django.contrib.auth.models import User
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DayAction:
    """A button for one training day: a POST form when `post` is true, otherwise a link. `status` is shown as text."""

    label: str
    url: str
    post: bool = False
    status: str | None = None


@dataclass(frozen=True)
class WorkoutLinks:
    days: dict[int, DayAction] = field(default_factory=dict)  # weekday (0 = Monday) -> action
    history_url: str | None = None


def workout_links(user: User, week_start: date, days: Sequence[dict]) -> WorkoutLinks:
    path = getattr(settings, 'PLANS_WORKOUT_TRACKER', None)
    if not path:
        return WorkoutLinks()
    try:
        links = import_string(path)().links(user, week_start, days)
    except Exception:  # a tracker bug must never take This Week down with it
        logger.exception('The workout tracker failed for user %s; showing the plan without workout links', user.pk)
        return WorkoutLinks()
    return links if isinstance(links, WorkoutLinks) else WorkoutLinks()
