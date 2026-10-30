"""Test doubles for the meal planner's plug-in points, shared by unit tests and Gherkin steps.

Point NUTRITION_RECIPE_SOURCE / NUTRITION_MACRO_TARGETS_PROVIDER at these with override_settings.
They also document the shape of data a real provider must return (D-4 macro targets, recipe APIs).
"""

from decimal import Decimal

from .domain import Ingredient, MacroTargets, Recipe, RecipeDetails
from .ports import RecipeServiceUnavailable


def recipe(id, cost, course='main', protein=30, carbs=50, fat=10, title=None) -> Recipe:
    return Recipe(
        id=id,
        title=title or f'Recipe {id}',
        course=course,
        cost_per_serving=Decimal(cost),
        protein_g=protein,
        carbs_g=carbs,
        fat_g=fat,
    )


# A fixed catalog with known prices, so expected totals can be worked out by hand.
# 8 breakfasts at $0.50, $0.60 ... $1.20, and 16 mains at $1.00, $1.10 ... $2.50; protein rises with price.
FIXED_BREAKFASTS = tuple(
    recipe(
        f'b{i}', f'{0.50 + i / 10:.2f}', course='breakfast', protein=10 + 2 * i, carbs=40, fat=8, title=f'Breakfast {i}'
    )
    for i in range(8)
)
FIXED_MAINS = tuple(
    recipe(f'm{i}', f'{1.00 + i / 10:.2f}', course='main', protein=15 + 3 * i, carbs=55, fat=12, title=f'Main {i}')
    for i in range(16)
)
FIXED_RECIPES = FIXED_BREAKFASTS + FIXED_MAINS

# Lowest-cost three-meal week, every meal different: the 7 cheapest breakfasts ($0.50 to $1.10 = $5.60)
# plus the 14 cheapest mains ($1.00 to $2.30 = $23.10).
FIXED_LOWEST_WEEKLY_COST = Decimal('28.70')

# A training-week shape like D-4 is expected to produce: lower carbs on the two rest days.
TRAINING_DAY = MacroTargets(protein_g=150, carbs_g=200, fat_g=40)
REST_DAY = MacroTargets(protein_g=150, carbs_g=150, fat_g=40)
FIXED_WEEKLY_TARGETS = (TRAINING_DAY, TRAINING_DAY, REST_DAY, TRAINING_DAY, TRAINING_DAY, REST_DAY, TRAINING_DAY)


def fixed_details(recipe: Recipe) -> RecipeDetails:
    return RecipeDetails(
        ingredients=(Ingredient(text=f'1 cup {recipe.title} base'), Ingredient(text='Salt and pepper')),
        steps=(f'Prepare the {recipe.title}.', 'Serve.'),
        ready_in_minutes=15,
    )


class FixedRecipeSource:
    attribution = 'Test recipes.'

    def budget_recipes(self):
        return list(FIXED_RECIPES)

    def recipe_details(self, recipe):
        return fixed_details(recipe)


class DetailsUnavailableRecipeSource(FixedRecipeSource):
    """Recipes load, but ingredients and steps don't (the details call is down)."""

    def recipe_details(self, recipe):
        raise RecipeServiceUnavailable('Simulated details outage.')


class UnavailableRecipeSource:
    attribution = 'Test recipes.'

    def budget_recipes(self):
        raise RecipeServiceUnavailable('Simulated outage.')

    def recipe_details(self, recipe):
        raise RecipeServiceUnavailable('Simulated outage.')


class FixedMacroTargets:
    """Stands in for D-4: the same week of targets for everyone."""

    def weekly_targets(self, user, week_start):
        return list(FIXED_WEEKLY_TARGETS)
