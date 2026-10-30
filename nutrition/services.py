"""Use cases: the signed-in user's meal plan for this week, and the details of one planned meal (ADR-008).

This is the one place that wires the configured ports to the planner. Other features (for example the
D-6 grocery list) should call these functions rather than reaching into the planner or the sources.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from .domain import MEALS, MacroTargets, MealPlan, Recipe, RecipeDetails
from .planner import DAY_NAMES, NoRecipesError, build_week_plan
from .ports import RecipeServiceUnavailable, macro_targets_provider, recipe_source

logger = logging.getLogger(__name__)

# Onboarding's meal pattern answer (core.models.MEAL_PATTERN_CHOICES) -> the meals planned each day.
MEALS_FOR_PATTERN = {
    'three': ('breakfast', 'lunch', 'dinner'),
    'breakfast_dinner': ('breakfast', 'dinner'),
    'lunch_dinner': ('lunch', 'dinner'),
    'dinner': ('dinner',),
}


@dataclass(frozen=True)
class MealPlanResult:
    """A plan, or None when suggestions are unavailable. `attribution` credits the recipe source."""

    plan: MealPlan | None
    attribution: str = ''

    @property
    def unavailable(self) -> bool:
        return self.plan is None


def meals_for_pattern(pattern: str) -> tuple[str, ...]:
    """The meals to plan for an onboarding answer; all three if it's blank (users who onboarded before it existed)."""
    return MEALS_FOR_PATTERN.get(pattern, MEALS)


def week_start(today: date | None = None) -> date:
    """Monday of the current week."""
    today = today or timezone.localdate()
    return today - timedelta(days=today.weekday())


def weekly_meal_plan(
    user, budget: Decimal | None, meals: Sequence[str] = MEALS, today: date | None = None
) -> MealPlanResult:
    """Plan this week's meals for `user`. A missing or negative budget counts as $0.

    Never raises for an unavailable recipe service; the result says so instead.
    """
    budget = max(budget or Decimal(0), Decimal(0))
    targets = _targets_or_none(user, week_start(today))
    source = recipe_source()
    try:
        plan = build_week_plan(source.budget_recipes(), budget, meals, targets)
    except (RecipeServiceUnavailable, NoRecipesError):
        return MealPlanResult(plan=None)
    return MealPlanResult(plan=plan, attribution=source.attribution)


def meal_details(recipe: Recipe) -> RecipeDetails | None:
    """Ingredients and steps for a planned recipe, or None if the recipe service can't provide them now."""
    try:
        return recipe_source().recipe_details(recipe)
    except RecipeServiceUnavailable:
        return None


def _targets_or_none(user, monday: date) -> list[MacroTargets] | None:
    """Ask the macro provider for this week's targets; a broken answer means "plan by cost alone"."""
    targets = macro_targets_provider().weekly_targets(user, monday)
    if targets is None:
        return None
    targets = list(targets)
    if len(targets) != len(DAY_NAMES) or not all(isinstance(t, MacroTargets) for t in targets):
        logger.error('Macro targets provider returned an invalid week; planning by cost alone.')
        return None
    return targets
