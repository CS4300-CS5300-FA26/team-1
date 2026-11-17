"""Test doubles and helpers for the grocery list (story D-6), shared by unit tests and the Gherkin steps.

A stored meal plan is what D-5 leaves for D-6 to read (`nutrition.services.stored_week_plan`). `store_week` writes
one directly, so these tests don't depend on the planner's choices or on the real recipe catalog.
"""

from collections.abc import Sequence
from datetime import date

from nutrition.models import PlannedMealEntry, WeeklyMealPlan
from nutrition.pricing import ML_PER_UNIT
from nutrition.services import week_start
from nutrition.testing import FIXED_WEEKLY_TARGETS, FLAT_QUOTE, ingredient, recipe

# White rice as the USDA catalog has it: 0.782 g per ml, so a cup weighs about 185 g.
RICE = ingredient('rice', 7, 80, 1, grams_per_ml=0.782)
BEANS = ingredient('beans', 6, 16, 1)
CUP_OF_RICE_G = float(ML_PER_UNIT['cup']) * 0.782

TWO_CUPS_OF_RICE = recipe('two-cups-of-rice', 'main', (RICE, 2 * CUP_OF_RICE_G), title='Two cups of rice')
ONE_CUP_OF_RICE = recipe('one-cup-of-rice', 'main', (RICE, CUP_OF_RICE_G), title='One cup of rice')
PLAIN_BEANS = recipe('plain-beans', 'main', (BEANS, 200), title='Plain beans')
RICE_RECIPES = (TWO_CUPS_OF_RICE, ONE_CUP_OF_RICE, PLAIN_BEANS)


class RiceRecipeSource:
    """A recipe source holding only the three recipes above, for the "Ingredients combined" scenario."""

    def recipes(self):
        return list(RICE_RECIPES)


def store_week(user, recipe_ids: Sequence[str], monday: date | None = None, meal: str = 'dinner') -> WeeklyMealPlan:
    """Store a dinner plan for the week: one recipe id per day, Monday first (what D-5 saves after planning)."""
    if len(recipe_ids) != 7:
        raise ValueError('A stored week has a meal for each of the seven days.')
    stored = WeeklyMealPlan.objects.create(
        user=user,
        week_start=monday or week_start(),
        inputs={
            'meals': [meal],
            'budget': None,
            'targets': [[t.protein_g, t.carbs_g, t.fat_g] for t in FIXED_WEEKLY_TARGETS],
            'priced': False,
        },
    )
    PlannedMealEntry.objects.bulk_create(
        PlannedMealEntry(plan=stored, day=day, meal=meal, recipe_id=recipe_id, servings=1)
        for day, recipe_id in enumerate(recipe_ids)
    )
    return stored


def rice_on_monday_and_wednesday(user) -> WeeklyMealPlan:
    """2 cups of rice on Monday, 1 cup on Wednesday, beans on the other days."""
    ids = ['plain-beans'] * 7
    ids[0] = TWO_CUPS_OF_RICE.id
    ids[2] = ONE_CUP_OF_RICE.id
    return store_week(user, ids)


class RiceOnlyPrices:
    """A price source that knows rice and nothing else, for the "some prices missing" cases."""

    def quotes(self, ingredients):
        return {i.key: [FLAT_QUOTE] for i in ingredients if i.key == 'rice'}
