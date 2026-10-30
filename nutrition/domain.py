"""Value types shared by the meal planner and its plug-in points (see ADR-008).

These are plain, immutable dataclasses with no Django imports, so the planner can be tested without a
database and other features (macros, grocery list) can produce or consume them without depending on
this app's internals.
"""

import math
from dataclasses import dataclass
from decimal import Decimal

CENT = Decimal('0.01')

# Meals a plan can cover, in the order they appear in a day.
MEALS = ('breakfast', 'lunch', 'dinner')
# Which kind of recipe fills each meal. Breakfasts and mains come from separate pools.
COURSES = ('breakfast', 'main')
COURSE_FOR_MEAL = {'breakfast': 'breakfast', 'lunch': 'main', 'dinner': 'main'}


def money(value: Decimal | int | str) -> Decimal:
    """Round to whole cents. Every price in the planner goes through this."""
    return Decimal(value).quantize(CENT)


@dataclass(frozen=True)
class MacroTargets:
    """Macronutrient targets in grams (for a day, or for one meal's share of a day)."""

    protein_g: int
    carbs_g: int
    fat_g: int

    def __post_init__(self):
        if min(self.protein_g, self.carbs_g, self.fat_g) < 0:
            raise ValueError('Macro targets cannot be negative.')

    def share(self, fraction: float) -> 'MacroTargets':
        """This target scaled to a fraction of the day (rounded to whole grams)."""
        return MacroTargets(
            protein_g=round(self.protein_g * fraction),
            carbs_g=round(self.carbs_g * fraction),
            fat_g=round(self.fat_g * fraction),
        )


@dataclass(frozen=True)
class Recipe:
    """A recipe as the planner needs it: one serving's price and macros, and the course it fills."""

    id: str
    title: str
    course: str
    cost_per_serving: Decimal
    protein_g: float
    carbs_g: float
    fat_g: float
    image_url: str = ''

    def __post_init__(self):
        if not self.title.strip():
            raise ValueError('A recipe needs a title.')
        if self.course not in COURSES:
            raise ValueError(f'Unknown course {self.course!r}.')
        if self.cost_per_serving <= 0:
            raise ValueError('A recipe needs a positive cost per serving.')
        macros = (self.protein_g, self.carbs_g, self.fat_g)
        if not all(math.isfinite(m) and m >= 0 for m in macros):
            raise ValueError('Macros must be finite and not negative.')


@dataclass(frozen=True)
class Ingredient:
    """One ingredient line. `text` is what people read ("2 cups cooked rice")."""

    text: str
    name: str = ''


@dataclass(frozen=True)
class RecipeDetails:
    """What it takes to cook a recipe: shown when a meal is selected, and the input for a grocery list."""

    ingredients: tuple[Ingredient, ...]
    steps: tuple[str, ...]
    ready_in_minutes: int | None = None
    source_url: str = ''


@dataclass(frozen=True)
class PlannedMeal:
    """One serving of a recipe for one meal of the day."""

    meal: str
    recipe: Recipe
    targets: MacroTargets | None = None

    @property
    def cost(self) -> Decimal:
        return money(self.recipe.cost_per_serving)


@dataclass(frozen=True)
class PlannedDay:
    """The meals planned for one day, and that day's targets when there are any."""

    day_name: str
    meals: tuple[PlannedMeal, ...]
    targets: MacroTargets | None = None

    @property
    def cost(self) -> Decimal:
        return money(sum((meal.cost for meal in self.meals), Decimal(0)))

    @property
    def protein_g(self) -> int:
        return round(sum(meal.recipe.protein_g for meal in self.meals))

    @property
    def carbs_g(self) -> int:
        return round(sum(meal.recipe.carbs_g for meal in self.meals))

    @property
    def fat_g(self) -> int:
        return round(sum(meal.recipe.fat_g for meal in self.meals))

    def meal(self, name: str) -> PlannedMeal | None:
        return next((meal for meal in self.meals if meal.meal == name), None)


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

    def day(self, name: str) -> PlannedDay | None:
        return next((day for day in self.days if day.day_name.lower() == name.lower()), None)
