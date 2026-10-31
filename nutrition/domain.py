"""Value types for the weekly meal plan (story D-5, ADR-008). Plain, immutable, and free of Django.

Nutrients come from the recipe source (FitPro's catalog computes them from USDA FoodData Central). Prices
come from the grocery price connector (D-6). Macro targets come from the macro connector (D-4), or from the
published Daily Values while D-4 isn't connected. Nothing here hard-codes a nutrient amount or a price.
"""

import math
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal

CENT = Decimal('0.01')

DAY_NAMES = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
MEALS = ('breakfast', 'lunch', 'dinner')  # in day order; matches core.models.MEAL_CHOICES
COURSES = ('breakfast', 'main')
COURSE_FOR_MEAL = {'breakfast': 'breakfast', 'lunch': 'main', 'dinner': 'main'}


def money(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(CENT)


@dataclass(frozen=True)
class Nutrients:
    """Energy and macronutrients for some amount of food."""

    kcal: float = 0.0
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0

    def __post_init__(self):
        values = (self.kcal, self.protein_g, self.carbs_g, self.fat_g)
        if not all(math.isfinite(v) and v >= 0 for v in values):
            raise ValueError('Nutrients must be finite and not negative.')

    def __add__(self, other: 'Nutrients') -> 'Nutrients':
        return Nutrients(
            self.kcal + other.kcal,
            self.protein_g + other.protein_g,
            self.carbs_g + other.carbs_g,
            self.fat_g + other.fat_g,
        )

    def scaled(self, factor: float) -> 'Nutrients':
        return Nutrients(self.kcal * factor, self.protein_g * factor, self.carbs_g * factor, self.fat_g * factor)


@dataclass(frozen=True)
class MacroTargets:
    """Daily macronutrient targets in grams."""

    protein_g: float
    carbs_g: float
    fat_g: float

    def __post_init__(self):
        values = (self.protein_g, self.carbs_g, self.fat_g)
        if not all(math.isfinite(v) and v > 0 for v in values):
            raise ValueError('Macro targets must be positive.')

    @property
    def kcal(self) -> float:
        """Energy implied by the targets (4 kcal/g protein and carbohydrate, 9 kcal/g fat)."""
        return 4 * self.protein_g + 4 * self.carbs_g + 9 * self.fat_g


@dataclass(frozen=True)
class Ingredient:
    """A food a recipe uses, with nutrients per 100 g. Optional densities convert volume and count quantities."""

    key: str
    name: str
    per_100g: Nutrients
    fdc_id: int | None = None  # USDA FoodData Central id the nutrients come from
    grams_per_ml: float | None = None
    grams_per_each: float | None = None


@dataclass(frozen=True)
class RecipeLine:
    """One ingredient line, per serving. A line with no ingredient (salt, spices) has no weight or nutrients."""

    text: str
    ingredient: Ingredient | None = None
    grams: float | None = None

    def __post_init__(self):
        if (self.ingredient is None) != (self.grams is None):
            raise ValueError('A line needs both an ingredient and a weight, or neither.')
        if self.grams is not None and not (math.isfinite(self.grams) and self.grams > 0):
            raise ValueError('A line weight must be positive.')

    @property
    def nutrients(self) -> Nutrients:
        if self.ingredient is None or self.grams is None:
            return Nutrients()
        return self.ingredient.per_100g.scaled(self.grams / 100)


@dataclass(frozen=True)
class Recipe:
    id: str
    title: str
    course: str
    lines: tuple[RecipeLine, ...]
    steps: tuple[str, ...] = ()
    ready_in_minutes: int | None = None

    def __post_init__(self):
        if self.course not in COURSES:
            raise ValueError(f'Unknown course {self.course!r}.')
        if not any(line.ingredient for line in self.lines):
            raise ValueError('A recipe needs at least one weighed ingredient.')

    @property
    def nutrients(self) -> Nutrients:
        """Per serving."""
        total = Nutrients()
        for line in self.lines:
            total = total + line.nutrients
        return total

    def grams_by_ingredient(self) -> dict[str, float]:
        """Per serving, keyed by ingredient key (an ingredient on two lines is added up)."""
        grams: dict[str, float] = {}
        for line in self.lines:
            if line.ingredient is not None and line.grams is not None:
                grams[line.ingredient.key] = grams.get(line.ingredient.key, 0.0) + line.grams
        return grams

    @property
    def ingredients(self) -> dict[str, Ingredient]:
        return {line.ingredient.key: line.ingredient for line in self.lines if line.ingredient is not None}


@dataclass(frozen=True)
class PriceEstimate:
    """An ingredient's average price, from the grocery price connector's quotes (see pricing.py)."""

    price_per_gram: Decimal
    package_grams: Decimal  # average package size, so a week buys whole packages
    quote_count: int

    @property
    def package_price(self) -> Decimal:
        return self.price_per_gram * self.package_grams

    def packages_for(self, grams: float) -> int:
        if grams <= 0:
            return 0
        # Rounded to milligrams first, so floating-point dust never buys an extra package.
        return int((Decimal(str(round(grams, 3))) / self.package_grams).to_integral_value(rounding=ROUND_CEILING))

    def cost_for(self, grams: float) -> Decimal:
        """What buying enough whole packages for `grams` costs (unrounded)."""
        return self.packages_for(grams) * self.package_price


@dataclass(frozen=True)
class PlannedMeal:
    day: int  # 0 = Monday
    meal: str
    recipe: Recipe
    servings: Decimal = Decimal(1)

    @property
    def nutrients(self) -> Nutrients:
        return self.recipe.nutrients.scaled(float(self.servings))

    def lines(self) -> list[tuple[RecipeLine, float | None]]:
        """Each recipe line with its weight for this meal's servings (None for unweighed lines)."""
        factor = float(self.servings)
        return [(line, line.grams * factor if line.grams is not None else None) for line in self.recipe.lines]


@dataclass(frozen=True)
class WeekPlan:
    """A week of planned meals. `daily_targets` has seven entries, Monday first."""

    meals: tuple[PlannedMeal, ...]
    daily_targets: tuple[MacroTargets, ...]
    meal_keys: tuple[str, ...] = MEALS
    _by_slot: dict = field(default_factory=dict, init=False, repr=False, compare=False)

    def __post_init__(self):
        if len(self.daily_targets) != len(DAY_NAMES):
            raise ValueError('A week plan needs seven daily targets.')
        object.__setattr__(self, '_by_slot', {(m.day, m.meal): m for m in self.meals})

    def meal(self, day: int, meal: str) -> PlannedMeal | None:
        return self._by_slot.get((day, meal))

    def day_meals(self, day: int) -> list[PlannedMeal]:
        return [m for key in self.meal_keys if (m := self.meal(day, key)) is not None]

    def day_nutrients(self, day: int) -> Nutrients:
        total = Nutrients()
        for meal in self.day_meals(day):
            total = total + meal.nutrients
        return total

    def grams_needed(self) -> dict[str, float]:
        """Total grams of each ingredient the week uses."""
        needed: dict[str, float] = {}
        for meal in self.meals:
            for key, grams in meal.recipe.grams_by_ingredient().items():
                needed[key] = needed.get(key, 0.0) + grams * float(meal.servings)
        return needed

    def ingredients(self) -> dict[str, Ingredient]:
        found: dict[str, Ingredient] = {}
        for meal in self.meals:
            found.update(meal.recipe.ingredients)
        return found

    def recipe_ids(self) -> set[str]:
        return {meal.recipe.id for meal in self.meals}


def purchase_cost(grams_needed: dict[str, float], prices: dict[str, PriceEstimate]) -> Decimal | None:
    """Whole-package cost of buying the week's ingredients, in cents; None if any ingredient has no price."""
    if any(key not in prices for key in grams_needed):
        return None
    return money(sum((prices[key].cost_for(grams) for key, grams in grams_needed.items()), Decimal(0)))
