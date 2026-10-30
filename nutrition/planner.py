"""Build a week of budget meals from a list of recipes (pure logic, no I/O; see ADR-008).

Rules:
* One recipe per day, cooked for SERVINGS_PER_DAY portions (meal prep: one batch feeds the day).
* A recipe appears at most MAX_USES_PER_RECIPE times a week, so the week has some variety. With very
  few recipes the cap rises just enough to fill the week.
* If even the lowest-cost week is over budget, that lowest-cost week is returned and the plan reports
  how far over it is.
* Otherwise, with macro targets, each day gets the recipe that best fits that day's targets while the
  rest of the week can still be filled within budget. Without targets, the lowest-cost week is used.
"""

from collections import Counter
from collections.abc import Sequence
from decimal import Decimal
from math import ceil

from .domain import MacroTargets, MealPlan, PlannedDay, Recipe, money

DAY_NAMES = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
SERVINGS_PER_DAY = 3
MAX_USES_PER_RECIPE = 2

# Protein counts double when scoring fit: it's the macro this audience is usually short of.
FIT_WEIGHTS = {'protein_g': 2.0, 'carbs_g': 1.0, 'fat_g': 1.0}


class NoRecipesError(ValueError):
    """There is nothing to plan with."""


def build_week_plan(
    recipes: Sequence[Recipe],
    budget: Decimal,
    targets: Sequence[MacroTargets] | None = None,
    servings_per_day: int = SERVINGS_PER_DAY,
) -> MealPlan:
    """Return the week's plan for `budget` (dollars) from `recipes`, fitting `targets` when given."""
    budget = money(budget)
    if targets is not None and len(targets) != len(DAY_NAMES):
        raise ValueError(f'Expected {len(DAY_NAMES)} daily targets, got {len(targets)}.')

    week = _Week(recipes, servings_per_day)
    lowest_cost = week.cheapest_fill(len(DAY_NAMES), Counter())
    chosen = lowest_cost if targets is None or week.cost_of(lowest_cost) > budget else week.best_fit(targets, budget)

    return MealPlan(
        days=tuple(
            PlannedDay(
                day_name=name,
                recipe=recipe,
                servings=servings_per_day,
                targets=targets[index] if targets is not None else None,
            )
            for index, (name, recipe) in enumerate(zip(DAY_NAMES, chosen, strict=True))
        ),
        budget=budget,
    )


class _Week:
    """The candidate recipes and the costing rules shared by both ways of choosing a week."""

    def __init__(self, recipes: Sequence[Recipe], servings_per_day: int):
        # Unique recipes, cheapest first; ties broken by title and id so the same input gives the same plan.
        unique = {recipe.id: recipe for recipe in recipes}
        self.candidates = sorted(unique.values(), key=lambda r: (r.cost_per_serving, r.title, r.id))
        if not self.candidates:
            raise NoRecipesError('No recipes to plan with.')
        self.servings = servings_per_day
        self.cap = max(MAX_USES_PER_RECIPE, ceil(len(DAY_NAMES) / len(self.candidates)))

    def day_cost(self, recipe: Recipe) -> Decimal:
        return money(recipe.cost_per_serving * self.servings)

    def cost_of(self, chosen: Sequence[Recipe]) -> Decimal:
        return sum((self.day_cost(r) for r in chosen), Decimal(0))

    def cheapest_fill(self, slots: int, used: Counter) -> list[Recipe]:
        """The lowest-cost way to fill `slots` days, given how often each recipe is already used."""
        fill: list[Recipe] = []
        for recipe in self.candidates:
            take = min(self.cap - used[recipe.id], slots - len(fill))
            fill.extend([recipe] * max(take, 0))
            if len(fill) == slots:
                break
        return fill

    def best_fit(self, targets: Sequence[MacroTargets], budget: Decimal) -> list[Recipe]:
        """Day by day, the best-fitting recipe that still leaves the rest of the week affordable.

        A choice is allowed only if the remaining days can still be filled at the lowest possible
        cost within budget. The caller has checked that the lowest-cost week fits, so at every step
        at least one recipe qualifies (the next one in that lowest-cost week) and the week never
        goes over budget.
        """
        chosen: list[Recipe] = []
        used: Counter = Counter()
        spent = Decimal(0)
        for day, day_targets in enumerate(targets):
            remaining_days = len(targets) - day - 1
            best_key, best = None, None
            for recipe in self.candidates:
                if used[recipe.id] >= self.cap:
                    continue
                used[recipe.id] += 1
                rest = self.cost_of(self.cheapest_fill(remaining_days, used))
                used[recipe.id] -= 1
                if spent + self.day_cost(recipe) + rest > budget:
                    continue
                key = (self.fit_error(recipe, day_targets), recipe.cost_per_serving, recipe.title, recipe.id)
                if best_key is None or key < best_key:
                    best_key, best = key, recipe
            assert best is not None  # noqa: S101 - guaranteed by the affordability invariant above
            chosen.append(best)
            used[best.id] += 1
            spent += self.day_cost(best)
        return chosen

    def fit_error(self, recipe: Recipe, targets: MacroTargets) -> float:
        """Weighted relative distance between a day's macros and its targets (0 is a perfect match)."""
        error = 0.0
        for field, weight in FIT_WEIGHTS.items():
            actual = getattr(recipe, field) * self.servings
            target = getattr(targets, field)
            error += weight * abs(actual - target) / max(target, 1)
        return error
