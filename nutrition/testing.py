"""Test doubles for the meal planner's plug-in points, shared by unit tests and Gherkin steps.

Point NUTRITION_RECIPE_SOURCE / NUTRITION_MACRO_TARGETS_PROVIDER at these with override_settings.
They also document the shape of data a real provider must return (D-4 macro targets, recipe APIs).
"""

from decimal import Decimal

from .domain import MacroTargets, Recipe
from .ports import RecipeServiceUnavailable


def recipe(id, cost, protein=30, carbs=50, fat=10, title=None) -> Recipe:
    return Recipe(
        id=id,
        title=title or f'Recipe {id}',
        cost_per_serving=Decimal(cost),
        protein_g=protein,
        carbs_g=carbs,
        fat_g=fat,
    )


# A small, fixed catalog with known prices, so expected totals can be worked out by hand.
# At 3 servings a day and at most 2 uses per recipe, the lowest-cost week is
# 2 x oats + 2 x lentils + 2 x chili + 1 x rice bowl = 3 x (2*0.90 + 2*1.00 + 2*1.20 + 1.50) = $23.10.
FIXED_RECIPES = (
    recipe('oats', '0.90', protein=12, carbs=55, fat=10, title='Peanut butter oats'),
    recipe('lentils', '1.00', protein=18, carbs=60, fat=6, title='Lentil curry'),
    recipe('chili', '1.20', protein=20, carbs=45, fat=7, title='Bean chili'),
    recipe('rice-bowl', '1.50', protein=42, carbs=55, fat=9, title='Chicken rice bowl'),
    recipe('pasta', '1.80', protein=38, carbs=62, fat=12, title='Turkey pasta'),
    recipe('burrito', '2.20', protein=45, carbs=60, fat=14, title='Chicken burrito bowl'),
)
FIXED_LOWEST_WEEKLY_COST = Decimal('23.10')

# A training-week shape like D-4 is expected to produce: lower carbs on the two rest days.
TRAINING_DAY = MacroTargets(protein_g=150, carbs_g=200, fat_g=40)
REST_DAY = MacroTargets(protein_g=150, carbs_g=150, fat_g=40)
FIXED_WEEKLY_TARGETS = (TRAINING_DAY, TRAINING_DAY, REST_DAY, TRAINING_DAY, TRAINING_DAY, REST_DAY, TRAINING_DAY)


class FixedRecipeSource:
    attribution = 'Test recipes.'

    def budget_recipes(self):
        return list(FIXED_RECIPES)


class UnavailableRecipeSource:
    attribution = 'Test recipes.'

    def budget_recipes(self):
        raise RecipeServiceUnavailable('Simulated outage.')


class FixedMacroTargets:
    """Stands in for D-4: the same week of targets for everyone."""

    def weekly_targets(self, user, week_start):
        return list(FIXED_WEEKLY_TARGETS)
