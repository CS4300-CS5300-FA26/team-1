"""Connectors between the meal plan (D-5) and the features built alongside it (ADR-008).

Each connector is an interface the meal plan owns, and a setting that names the class implementing it. A
teammate plugs their feature in by writing a class with the method below and pointing the setting at it;
nothing in the meal plan changes. Until then, `nutrition.connectors` supplies a "not connected yet" default and
the meal plan falls back as described in ADR-008.

| Setting                            | Implemented by                   | Default (until then)            |
| ---------------------------------- | -------------------------------- | ------------------------------- |
| NUTRITION_RECIPE_SOURCE            | D-5: FitPro's catalog            | `CatalogRecipeSource`           |
| NUTRITION_MACRO_TARGETS_PROVIDER   | D-4 Macro Generation             | `NoMacroTargets` -> Daily Values |
| NUTRITION_GROCERY_PRICE_SOURCE     | D-6 Grocery List Generation      | `NoGroceryPrices` -> no costs   |
| NUTRITION_WORKOUTS_LINK            | D-3 Workout Split ("This Week")  | the dashboard                   |

In the other direction, D-6 reads the stored week from `nutrition.services.stored_week_plan`.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Protocol, cast

from django.conf import settings
from django.utils.module_loading import import_string

from .domain import Ingredient, MacroTargets, Recipe
from .pricing import PriceQuote


class RecipeServiceUnavailable(Exception):  # noqa: N818 - reads naturally at the call site
    """The recipe source can't return usable recipes right now."""


class RecipeSource(Protocol):
    def recipes(self) -> Sequence[Recipe]:
        """Every recipe that can be planned, with weighed ingredients. Raise RecipeServiceUnavailable on failure."""
        ...


class MacroTargetsProvider(Protocol):
    """D-4 Macro Generation."""

    def weekly_targets(self, user, week_start: date) -> Sequence[MacroTargets] | None:
        """Seven daily targets for the user's week (Monday first; rest days can differ), or None if none yet."""
        ...


class GroceryPriceSource(Protocol):
    """D-6 Grocery List Generation."""

    def quotes(self, ingredients: Sequence[Ingredient]) -> Mapping[str, Sequence[PriceQuote]]:
        """Price quotes per ingredient key. Leave out ingredients with no price; return {} if prices are down.

        Ingredients carry their USDA FoodData Central id and name to match products against. Quotes can use any
        unit in `nutrition.pricing.UNITS`; the meal plan averages them per ingredient.
        """
        ...


def recipe_source() -> RecipeSource:
    return cast(RecipeSource, import_string(settings.NUTRITION_RECIPE_SOURCE)())


def macro_targets_provider() -> MacroTargetsProvider:
    return cast(MacroTargetsProvider, import_string(settings.NUTRITION_MACRO_TARGETS_PROVIDER)())


def grocery_price_source() -> GroceryPriceSource:
    return cast(GroceryPriceSource, import_string(settings.NUTRITION_GROCERY_PRICE_SOURCE)())
