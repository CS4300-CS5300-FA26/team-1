"""Turning plans into JSON snapshots and back, for saved plans and the session's unsaved draft.

Snapshots hold only validated domain data. Loading rebuilds (and so re-validates) the domain objects; a
snapshot that no longer fits (an older format, edited data) is treated as missing rather than crashing.
"""

import logging
from dataclasses import asdict, dataclass
from decimal import Decimal

from .domain import MacroTargets, MealPlan, PlannedDay, PlannedMeal, Recipe

logger = logging.getLogger(__name__)

SNAPSHOT_VERSION = 1


@dataclass(frozen=True)
class Snapshot:
    """A plan plus what's needed to show it: where its recipes came from."""

    plan: MealPlan
    attribution: str = ''


def dump(snapshot: Snapshot) -> dict:
    plan = snapshot.plan
    return {
        'version': SNAPSHOT_VERSION,
        'attribution': snapshot.attribution,
        'budget': str(plan.budget),
        'days': [
            {
                'day_name': day.day_name,
                'targets': asdict(day.targets) if day.targets else None,
                'meals': [
                    {
                        'meal': meal.meal,
                        'targets': asdict(meal.targets) if meal.targets else None,
                        'recipe': {**asdict(meal.recipe), 'cost_per_serving': str(meal.recipe.cost_per_serving)},
                    }
                    for meal in day.meals
                ],
            }
            for day in plan.days
        ],
    }


def load(data) -> Snapshot | None:
    """The snapshot in `data`, or None if it's missing or not a valid snapshot."""
    if not data:
        return None
    try:
        if data['version'] != SNAPSHOT_VERSION:
            return None
        plan = MealPlan(
            days=tuple(
                PlannedDay(
                    day_name=str(day['day_name']),
                    targets=MacroTargets(**day['targets']) if day['targets'] else None,
                    meals=tuple(
                        PlannedMeal(
                            meal=str(meal['meal']),
                            targets=MacroTargets(**meal['targets']) if meal['targets'] else None,
                            recipe=Recipe(
                                **{**meal['recipe'], 'cost_per_serving': Decimal(meal['recipe']['cost_per_serving'])}
                            ),
                        )
                        for meal in day['meals']
                    ),
                )
                for day in data['days']
            ),
            budget=Decimal(data['budget']),
        )
        return Snapshot(plan=plan, attribution=str(data.get('attribution', '')))
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        logger.warning('Ignoring an unreadable meal plan snapshot: %s', type(exc).__name__)
        return None
