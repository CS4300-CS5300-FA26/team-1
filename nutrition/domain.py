"""Value types shared by the meal planner and its plug-in points (see ADR-008).

These are plain, immutable dataclasses with no Django imports, so the planner can be tested without a
database and other features (macros, grocery list) can produce or consume them without depending on
this app's internals.
"""

import math
from dataclasses import dataclass
from decimal import Decimal

CENT = Decimal('0.01')


def money(value: Decimal | int | str) -> Decimal:
    """Round to whole cents. Every price in the planner goes through this."""
    return Decimal(value).quantize(CENT)


@dataclass(frozen=True)
class MacroTargets:
    """One day's macronutrient targets, in grams."""

    protein_g: int
    carbs_g: int
    fat_g: int

    def __post_init__(self):
        if min(self.protein_g, self.carbs_g, self.fat_g) < 0:
            raise ValueError('Macro targets cannot be negative.')


@dataclass(frozen=True)
class Recipe:
    """A recipe as the planner needs it: price and macros are per serving."""

    id: str
    title: str
    cost_per_serving: Decimal
    protein_g: float
    carbs_g: float
    fat_g: float
    image_url: str = ''
    source_url: str = ''

    def __post_init__(self):
        if not self.title.strip():
            raise ValueError('A recipe needs a title.')
        if self.cost_per_serving <= 0:
            raise ValueError('A recipe needs a positive cost per serving.')
        macros = (self.protein_g, self.carbs_g, self.fat_g)
        if not all(math.isfinite(m) and m >= 0 for m in macros):
            raise ValueError('Macros must be finite and not negative.')


@dataclass(frozen=True)
class PlannedDay:
    """One day of the plan: a recipe cooked for `servings` portions."""

    day_name: str
    recipe: Recipe
    servings: int
    targets: MacroTargets | None = None

    @property
    def cost(self) -> Decimal:
        return money(self.recipe.cost_per_serving * self.servings)

    @property
    def protein_g(self) -> int:
        return round(self.recipe.protein_g * self.servings)

    @property
    def carbs_g(self) -> int:
        return round(self.recipe.carbs_g * self.servings)

    @property
    def fat_g(self) -> int:
        return round(self.recipe.fat_g * self.servings)


@dataclass(frozen=True)
class MealPlan:
    """A week of planned days and what it costs against the user's budget."""

    days: tuple[PlannedDay, ...]
    budget: Decimal

    @property
    def total_cost(self) -> Decimal:
        return money(sum((day.cost for day in self.days), Decimal(0)))

    @property
    def over_budget_by(self) -> Decimal:
        """How far the plan is over budget; zero when it fits."""
        return max(money(self.total_cost - self.budget), Decimal('0.00'))

    @property
    def within_budget(self) -> bool:
        return self.total_cost <= self.budget

    @property
    def uses_macro_targets(self) -> bool:
        return any(day.targets is not None for day in self.days)
