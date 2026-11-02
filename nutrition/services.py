"""Use cases for the weekly meal plan (story D-5, ADR-008). The one place that wires the connectors to the planner.

* `current_meal_plan`: this week's plan for a user. The stored plan is reused while what it was made from (budget,
  meals, daily targets, whether prices are connected) is unchanged; otherwise a new one is made and stored.
* `new_meal_plan`: replace this week's plan with a different one.
* `stored_week_plan`: for D-6 (grocery list) and other features: the stored plan, read-only. None when the user has
  no plan this week (D-6's "Empty week" scenario).

Fallbacks when a connected feature has nothing yet (each is shown to the user):
* no personal macro targets (D-4)  -> the FDA Daily Values for a 2,000-calorie diet;
* no prices (D-6)                  -> no cost estimate, and the plan isn't limited by the budget;
* no weekly budget                 -> a plan chosen for nutrition alone, with its cost shown if prices exist.
"""

import logging
import secrets
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from . import pricing
from .domain import MacroTargets, PlannedMeal, PriceEstimate, Recipe, WeekPlan, purchase_cost
from .models import PlannedMealEntry, WeeklyMealPlan
from .planner import NoRecipesError, build_week_plan, covers_meals, recipes_with_prices
from .ports import RecipeServiceUnavailable, grocery_price_source, macro_targets_provider, recipe_source
from .targets import published_weekly_targets

logger = logging.getLogger(__name__)

PRICES_CONNECTED = 'connected'  # every planned meal can be priced
PRICES_INCOMPLETE = 'incomplete'  # some prices, but too few recipes fully priced to plan with
PRICES_NOT_CONNECTED = 'not_connected'  # no prices at all (D-6 not connected yet, or down)


@dataclass(frozen=True)
class MealPlanResult:
    """This week's plan and how it was made, for the page. `plan` is None when recipes are unavailable."""

    week_start: date
    plan: WeekPlan | None
    personal_targets: bool = False
    prices: str = PRICES_NOT_CONNECTED
    budget: Decimal | None = None
    cost: Decimal | None = None

    @property
    def unavailable(self) -> bool:
        return self.plan is None

    @property
    def budget_applied(self) -> bool:
        return self.budget is not None and self.prices == PRICES_CONNECTED

    @property
    def over_budget_by(self) -> Decimal | None:
        if not self.budget_applied or self.cost is None or self.budget is None:
            return None
        return max(self.cost - self.budget, Decimal('0.00'))

    @property
    def week_end(self) -> date:
        return self.week_start + timedelta(days=6)


def week_start(today: date | None = None) -> date:
    """Monday of the current week."""
    today = today or timezone.localdate()
    return today - timedelta(days=today.weekday())


def current_meal_plan(user, meals, budget: Decimal | None, today: date | None = None) -> MealPlanResult:
    return _meal_plan(user, tuple(meals), budget, week_start(today), regenerate=False)


def new_meal_plan(user, meals, budget: Decimal | None, today: date | None = None) -> MealPlanResult:
    return _meal_plan(user, tuple(meals), budget, week_start(today), regenerate=True)


def stored_week_plan(user, monday: date | None = None) -> WeekPlan | None:
    """The user's stored plan for the week starting `monday` (this week by default), or None if there isn't one.

    Read-only, for other features: D-6 combines `plan.meals[i].lines()` (each ingredient line with its grams for
    that meal's servings) into a grocery list. Never creates a plan.
    """
    stored = WeeklyMealPlan.objects.filter(user=user, week_start=monday or week_start()).first()
    if stored is None:
        return None
    try:
        recipes = {r.id: r for r in recipe_source().recipes()}
    except RecipeServiceUnavailable:
        return None
    return _load(stored, recipes)


def _meal_plan(user, meals: tuple[str, ...], budget: Decimal | None, monday: date, regenerate: bool) -> MealPlanResult:
    budget = max(budget, Decimal(0)) if budget is not None else None
    targets, personal = _targets(user, monday)
    try:
        recipes = list(recipe_source().recipes())
    except RecipeServiceUnavailable:
        return MealPlanResult(week_start=monday, plan=None)
    prices, price_status = _prices(recipes, meals)
    inputs = {
        'meals': list(meals),
        'budget': str(budget) if budget is not None else None,
        'targets': [[t.protein_g, t.carbs_g, t.fat_g] for t in targets],
        'priced': price_status == PRICES_CONNECTED,
    }
    stored = WeeklyMealPlan.objects.filter(user=user, week_start=monday).first()
    plan = None
    if stored is not None and stored.inputs == inputs and not regenerate:
        plan = _load(stored, {r.id: r for r in recipes})
    if plan is None:
        avoid = _load_ids(stored) if regenerate and stored is not None else set()
        try:
            plan = _generate_and_store(
                user, monday, recipes, meals, targets, prices, price_status, budget, inputs, avoid
            )
        except NoRecipesError:
            logger.error('The recipe catalog has no recipes for one of the meals %s.', ', '.join(meals))
            return MealPlanResult(week_start=monday, plan=None)
    cost = purchase_cost(plan.grams_needed(), prices) if price_status == PRICES_CONNECTED else None
    return MealPlanResult(
        week_start=monday, plan=plan, personal_targets=personal, prices=price_status, budget=budget, cost=cost
    )


def _generate_and_store(user, monday, recipes, meals, targets, prices, price_status, budget, inputs, avoid) -> WeekPlan:
    seed = secrets.randbelow(2**31)
    priced = price_status == PRICES_CONNECTED
    result = build_week_plan(
        recipes,
        meals,
        targets,
        prices=prices if priced else None,
        budget=budget if priced else None,
        seed=seed,
        avoid=avoid,
    )
    with transaction.atomic():
        stored, _ = WeeklyMealPlan.objects.update_or_create(
            user=user, week_start=monday, defaults={'inputs': inputs, 'seed': seed}
        )
        stored.entries.all().delete()
        PlannedMealEntry.objects.bulk_create(
            PlannedMealEntry(plan=stored, day=m.day, meal=m.meal, recipe_id=m.recipe.id, servings=m.servings)
            for m in result.plan.meals
        )
    return result.plan


def _load(stored: WeeklyMealPlan, recipes: dict[str, Recipe]) -> WeekPlan | None:
    """Rebuild a stored plan; None if it no longer fits (a recipe left the catalog, or the data is unreadable)."""
    meals = tuple(stored.inputs.get('meals') or ())
    order = {meal: index for index, meal in enumerate(meals)}
    entries = sorted(stored.entries.all(), key=lambda e: (e.day, order.get(e.meal, len(order))))
    if not meals or len(entries) != 7 * len(meals) or any(e.recipe_id not in recipes for e in entries):
        return None
    try:
        targets = tuple(MacroTargets(*values) for values in stored.inputs['targets'])
        planned = tuple(PlannedMeal(e.day, e.meal, recipes[e.recipe_id], e.servings) for e in entries)
        return WeekPlan(meals=planned, daily_targets=targets, meal_keys=meals)
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning('Ignoring an unreadable stored meal plan: %s', type(exc).__name__)
        return None


def _load_ids(stored: WeeklyMealPlan) -> set[str]:
    return set(stored.entries.values_list('recipe_id', flat=True))


def _targets(user, monday: date) -> tuple[tuple[MacroTargets, ...], bool]:
    """Seven daily targets from the macro connector (D-4), or the published Daily Values. True if personal."""
    try:
        targets = macro_targets_provider().weekly_targets(user, monday)
    except Exception:  # noqa: BLE001 - a teammate's connector failing must not take the meal plan down
        logger.exception('The macro targets connector failed; using the published Daily Values.')
        targets = None
    if targets is not None:
        targets = tuple(targets)
        if len(targets) == 7 and all(isinstance(t, MacroTargets) for t in targets):
            return targets, True
        logger.error('The macro targets connector returned an invalid week; using the published Daily Values.')
    return published_weekly_targets(), False


def _prices(recipes: list[Recipe], meals: tuple[str, ...]) -> tuple[dict[str, PriceEstimate], str]:
    """Average prices from the grocery price connector (D-6), and whether they are enough to plan with."""
    ingredients = list({key: i for r in recipes for key, i in r.ingredients.items()}.values())
    try:
        quotes = grocery_price_source().quotes(ingredients)
    except Exception:  # noqa: BLE001 - a teammate's connector failing must not take the meal plan down
        logger.exception('The grocery price connector failed; planning without prices.')
        quotes = {}
    estimates = pricing.estimates(ingredients, quotes or {})
    if not estimates:
        return {}, PRICES_NOT_CONNECTED
    if covers_meals(recipes_with_prices(recipes, estimates), meals):
        return estimates, PRICES_CONNECTED
    return estimates, PRICES_INCOMPLETE
