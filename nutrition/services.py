"""Use cases for the meal plan (ADR-008): this week's plan, saving it, generating a new one, and meal details.

This is the one place that wires the configured ports to the planner. Other features (for example the
D-6 grocery list) should call these functions rather than reaching into the planner or the sources.

Which plan a user sees this week, in order:
1. their unsaved draft (kept in the server-side session), if it still matches their budget and meals;
2. the plan they saved for this week (SavedMealPlan);
3. a freshly generated plan, which becomes the draft.
"Save meal plan" stores the current plan for the week; "Generate a new meal plan" replaces the draft with
one that avoids the recipes already shown this week.
"""

import logging
from collections.abc import Collection, MutableMapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from . import plan_store
from .domain import MEALS, MacroTargets, MealPlan, Recipe, RecipeDetails
from .models import SavedMealPlan
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
    user,
    budget: Decimal | None,
    meals: Sequence[str] = MEALS,
    today: date | None = None,
    avoid: Collection[str] = frozenset(),
) -> MealPlanResult:
    """Generate this week's meals for `user`. A missing or negative budget counts as $0.

    Never raises for an unavailable recipe service; the result says so instead.
    """
    budget = max(budget or Decimal(0), Decimal(0))
    targets = _targets_or_none(user, week_start(today))
    source = recipe_source()
    try:
        plan = build_week_plan(source.budget_recipes(), budget, meals, targets, avoid)
    except (RecipeServiceUnavailable, NoRecipesError):
        return MealPlanResult(plan=None)
    return MealPlanResult(plan=plan, attribution=source.attribution)


DRAFT_SESSION_KEY = 'nutrition.meal_plan_draft'


@dataclass(frozen=True)
class CurrentPlan:
    """The plan a user sees this week, and whether it's the one they saved."""

    week_start: date
    snapshot: plan_store.Snapshot | None
    saved: SavedMealPlan | None = None

    @property
    def plan(self) -> MealPlan | None:
        return self.snapshot.plan if self.snapshot else None

    @property
    def attribution(self) -> str:
        return self.snapshot.attribution if self.snapshot else ''

    @property
    def unavailable(self) -> bool:
        return self.snapshot is None

    @property
    def is_saved(self) -> bool:
        if self.saved is None or self.snapshot is None:
            return False
        return plan_store.dump(self.snapshot) == self.saved.plan

    @property
    def week_end(self) -> date:
        return self.week_start + timedelta(days=6)


def _fingerprint(monday: date, budget: Decimal | None, meals: Sequence[str]) -> str:
    """What a draft was generated for; a draft for a different week, budget, or meals is stale."""
    return f'{monday.isoformat()}|{max(budget or Decimal(0), Decimal(0)):.2f}|{",".join(meals)}'


def _recipe_ids(plan: MealPlan | None) -> set[str]:
    return {meal.recipe.id for day in plan.days for meal in day.meals} if plan else set()


def current_meal_plan(
    user, session: MutableMapping, budget: Decimal | None, meals: Sequence[str], today: date | None = None
) -> CurrentPlan:
    """The plan to show this week: the matching draft, else the saved plan, else a new plan (kept as the draft)."""
    monday = week_start(today)
    fingerprint = _fingerprint(monday, budget, meals)
    saved = SavedMealPlan.objects.filter(user=user, week_start=monday).first()

    draft = session.get(DRAFT_SESSION_KEY)
    snapshot = None
    if draft and draft.get('fingerprint') == fingerprint:
        snapshot = plan_store.load(draft.get('plan'))
    if snapshot is None:
        session.pop(DRAFT_SESSION_KEY, None)
        if saved:
            snapshot = plan_store.load(saved.plan)
    if snapshot is None:
        result = weekly_meal_plan(user, budget, meals, today)
        if result.plan:
            snapshot = plan_store.Snapshot(result.plan, result.attribution)
            _store_draft(session, fingerprint, snapshot, seen=_recipe_ids(result.plan))
    return CurrentPlan(week_start=monday, snapshot=snapshot, saved=saved)


def save_meal_plan(
    user, session: MutableMapping, budget: Decimal | None, meals: Sequence[str], today: date | None = None
) -> CurrentPlan | None:
    """Keep the current plan as this week's saved plan. None if there's no plan to save."""
    current = current_meal_plan(user, session, budget, meals, today)
    if current.snapshot is None:
        return None
    saved, _ = SavedMealPlan.objects.update_or_create(
        user=user, week_start=current.week_start, defaults={'plan': plan_store.dump(current.snapshot)}
    )
    session.pop(DRAFT_SESSION_KEY, None)
    return CurrentPlan(week_start=current.week_start, snapshot=current.snapshot, saved=saved)


def generate_new_meal_plan(
    user, session: MutableMapping, budget: Decimal | None, meals: Sequence[str], today: date | None = None
) -> CurrentPlan | None:
    """Replace the draft with a plan that avoids the recipes already shown this week. None if unavailable."""
    current = current_meal_plan(user, session, budget, meals, today)
    draft = session.get(DRAFT_SESSION_KEY) or {}
    seen = set(draft.get('seen', [])) | _recipe_ids(current.plan)
    result = weekly_meal_plan(user, budget, meals, today, avoid=seen)
    if result.plan is None:
        return None
    snapshot = plan_store.Snapshot(result.plan, result.attribution)
    fingerprint = _fingerprint(current.week_start, budget, meals)
    _store_draft(session, fingerprint, snapshot, seen=seen | _recipe_ids(result.plan))
    return CurrentPlan(week_start=current.week_start, snapshot=snapshot, saved=current.saved)


def discard_draft(session: MutableMapping) -> None:
    """Drop the unsaved draft, so the saved plan (if any) shows again."""
    session.pop(DRAFT_SESSION_KEY, None)


def _store_draft(session: MutableMapping, fingerprint: str, snapshot: plan_store.Snapshot, seen: set[str]) -> None:
    session[DRAFT_SESSION_KEY] = {'fingerprint': fingerprint, 'plan': plan_store.dump(snapshot), 'seen': sorted(seen)}


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
