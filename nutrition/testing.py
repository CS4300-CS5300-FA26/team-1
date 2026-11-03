"""Test doubles for the meal plan's connectors, shared by unit tests, Gherkin steps, and browser tests.

Point a NUTRITION_* setting at one with override_settings. They also show teammates the shape of data their
connector must return (D-4 macro targets, D-6 price quotes).
"""

from decimal import Decimal

from .domain import Ingredient, MacroTargets, Nutrients, Recipe, RecipeLine
from .ports import RecipeServiceUnavailable
from .pricing import PriceQuote


def ingredient(key, protein, carbs, fat, **extra) -> Ingredient:
    """A made-up test ingredient (per 100 g); energy from 4/4/9 kcal per gram."""
    kcal = 4 * protein + 4 * carbs + 9 * fat
    return Ingredient(
        key=key, name=key.replace('-', ' ').capitalize(), per_100g=Nutrients(kcal, protein, carbs, fat), **extra
    )


OATS = ingredient('oats', 13, 68, 7)
EGGS = ingredient('eggs', 13, 1, 10, grams_per_each=50)
MILK = ingredient('milk', 3, 5, 3, grams_per_ml=1.03)
RICE = ingredient('rice', 7, 80, 1)
CHICKEN = ingredient('chicken', 22, 0, 3)
BEANS = ingredient('beans', 6, 16, 1)
PASTA = ingredient('pasta', 13, 75, 2)
TUNA = ingredient('tuna', 19, 0, 1)


def recipe(id, course, *lines, title=None) -> Recipe:
    return Recipe(
        id=id,
        title=title or id.replace('-', ' ').capitalize(),
        course=course,
        lines=tuple(RecipeLine(f'{grams:g} g {ing.name.lower()}', ing, grams) for ing, grams in lines)
        + (RecipeLine('Salt and pepper'),),
        steps=('Cook it.', 'Eat it.'),
        ready_in_minutes=10,
    )


FIXED_RECIPES = (
    recipe('oat-porridge', 'breakfast', (OATS, 80), (MILK, 250)),
    recipe('scrambled-eggs', 'breakfast', (EGGS, 150), (MILK, 50)),
    recipe('egg-oats', 'breakfast', (OATS, 50), (EGGS, 100)),
    recipe('milk-oats', 'breakfast', (OATS, 60), (MILK, 300)),
    recipe('chicken-rice', 'main', (CHICKEN, 150), (RICE, 90)),
    recipe('bean-rice', 'main', (BEANS, 200), (RICE, 80)),
    recipe('tuna-pasta', 'main', (TUNA, 120), (PASTA, 90)),
    recipe('chicken-pasta', 'main', (CHICKEN, 140), (PASTA, 85)),
    recipe('bean-pasta', 'main', (BEANS, 180), (PASTA, 80)),
    recipe('tuna-rice', 'main', (TUNA, 130), (RICE, 85)),
    recipe('egg-rice', 'main', (EGGS, 150), (RICE, 90), (BEANS, 60)),
)

# A training-week shape like D-4 is expected to produce: lower carbs on the two rest days.
TRAINING_DAY = MacroTargets(protein_g=150, carbs_g=250, fat_g=60)
REST_DAY = MacroTargets(protein_g=150, carbs_g=180, fat_g=60)
FIXED_WEEKLY_TARGETS = (TRAINING_DAY, TRAINING_DAY, REST_DAY, TRAINING_DAY, TRAINING_DAY, REST_DAY, TRAINING_DAY)

# Every ingredient sells for $2.00 per 500 g package, so a week costs $2.00 per package bought.
FLAT_QUOTE = PriceQuote(price=Decimal('2.00'), quantity=Decimal('500'), unit='g', source='Test grocer')


class FixedRecipeSource:
    def recipes(self):
        return list(FIXED_RECIPES)


class UnavailableRecipeSource:
    def recipes(self):
        raise RecipeServiceUnavailable('Simulated outage.')


class FixedMacroTargets:
    """Stands in for D-4: the same training week of targets for everyone."""

    def weekly_targets(self, user, week_start):
        return list(FIXED_WEEKLY_TARGETS)


class BrokenMacroTargets:
    def weekly_targets(self, user, week_start):
        raise RuntimeError('Simulated bug in the macro connector.')


class FlatGroceryPrices:
    """Stands in for D-6: every ingredient it's asked about costs $2.00 per 500 g."""

    def quotes(self, ingredients):
        return {i.key: [FLAT_QUOTE] for i in ingredients}


class BreakfastOnlyGroceryPrices:
    """Prices for breakfast ingredients only, so mains can't be priced (an incomplete price list)."""

    def quotes(self, ingredients):
        return {i.key: [FLAT_QUOTE] for i in ingredients if i.key in {'oats', 'eggs', 'milk'}}


class BrokenGroceryPrices:
    def quotes(self, ingredients):
        raise RuntimeError('Simulated bug in the price connector.')
