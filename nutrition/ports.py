"""The two interfaces the meal planner depends on, and how the configured implementations are loaded.

The planner owns these interfaces; implementations live elsewhere (dependency inversion, ADR-008):

* RecipeSource: where recipes come from (the starter catalog, Spoonacular, or a test fake).
* MacroTargetsProvider: daily macro targets. D-4 (macro generation) supplies the real implementation;
  until then `nutrition.macros.NoMacroTargets` returns None and plans are optimised for cost alone.

Swap an implementation by changing NUTRITION_RECIPE_SOURCE or NUTRITION_MACRO_TARGETS_PROVIDER in
settings to a dotted path. Nothing else changes.
"""

from collections.abc import Sequence
from datetime import date
from typing import Protocol, cast

from django.conf import settings
from django.utils.module_loading import import_string

from .domain import MacroTargets, Recipe


class RecipeServiceUnavailable(Exception):  # noqa: N818 - reads naturally at the call site
    """The recipe source could not return usable recipes (down, timed out, misconfigured, bad data)."""


class RecipeSource(Protocol):
    attribution: str  # credit line shown under the plan (some APIs require one)

    def budget_recipes(self) -> Sequence[Recipe]:
        """Return cheap, complete recipes to plan from. Raise RecipeServiceUnavailable on any failure."""
        ...


class MacroTargetsProvider(Protocol):
    def weekly_targets(self, user, week_start: date) -> Sequence[MacroTargets] | None:
        """Return seven daily targets (Monday first) for the user, or None if they have none yet."""
        ...


def recipe_source() -> RecipeSource:
    return cast(RecipeSource, import_string(settings.NUTRITION_RECIPE_SOURCE)())


def macro_targets_provider() -> MacroTargetsProvider:
    return cast(MacroTargetsProvider, import_string(settings.NUTRITION_MACRO_TARGETS_PROVIDER)())
