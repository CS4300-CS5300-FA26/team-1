"""Step definitions for features/meal_plan.feature (story D-5).

The meal plan reaches D-4 (macro targets) and D-6 (grocery prices) through connectors (ADR-008), so these steps
plug in the stand-ins from nutrition.testing with override_settings. That keeps the scenarios independent of
teammates' work in progress, and of the real catalog's numbers.
"""

from decimal import Decimal

from behave import given, then, when
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from core.models import UserProfile
from nutrition import pricing
from nutrition.domain import DAY_NAMES
from nutrition.planner import build_week_plan
from nutrition.testing import FIXED_RECIPES, FlatGroceryPrices

User = get_user_model()

VALID_PASSWORD = '<M42HVb-;p(!2cve9!'
RECIPES = 'nutrition.testing.FixedRecipeSource'
PRICES = 'nutrition.testing.FlatGroceryPrices'
TARGETS = 'nutrition.testing.FixedMacroTargets'


def use_settings(context, **overrides):
    """Apply settings for this scenario only."""
    override = override_settings(**overrides)
    override.enable()
    context.add_cleanup(override.disable)


def log_in_with_budget(context, budget):
    user = User.objects.create_user('planner', 'planner@example.com', VALID_PASSWORD)
    UserProfile.objects.create(
        user=user,
        onboarding_completed=True,
        weekly_food_budget=Decimal(budget),
        planned_meals=['breakfast', 'lunch', 'dinner'],
    )
    context.test.assertTrue(context.test.client.login(username='planner', password=VALID_PASSWORD))
    context.budget = Decimal(budget)


def page_text(context) -> str:
    return ' '.join(context.response.content.decode().split())


@given('my weekly food budget is ${budget:d} and my macro targets are set')
def step_budget_and_targets(context, budget):
    use_settings(
        context,
        NUTRITION_RECIPE_SOURCE=RECIPES,
        NUTRITION_GROCERY_PRICE_SOURCE=PRICES,
        NUTRITION_MACRO_TARGETS_PROVIDER=TARGETS,
    )
    log_in_with_budget(context, budget)


@given('my weekly food budget is ${budget:d}')
def step_budget(context, budget):
    use_settings(context, NUTRITION_RECIPE_SOURCE=RECIPES, NUTRITION_GROCERY_PRICE_SOURCE=PRICES)
    log_in_with_budget(context, budget)


@given('the recipe service is unavailable')
def step_service_unavailable(context):
    use_settings(context, NUTRITION_RECIPE_SOURCE='nutrition.testing.UnavailableRecipeSource')
    log_in_with_budget(context, 50)


@given('my macro targets have not been generated yet')
def step_no_targets(context):
    # The default connector: D-4 isn't plugged in, so there are no personal targets.
    use_settings(context, NUTRITION_MACRO_TARGETS_PROVIDER='nutrition.connectors.NoMacroTargets')
    log_in_with_budget(context, 50)


@given('grocery prices are not available yet')
def step_no_prices(context):
    # The default connector: D-6 isn't plugged in, so there are no prices.
    use_settings(context, NUTRITION_GROCERY_PRICE_SOURCE='nutrition.connectors.NoGroceryPrices')
    log_in_with_budget(context, 50)


@when('I open Meal Plan')
def step_open_meal_plan(context):
    context.response = context.test.client.get(reverse('meal_plan'))
    context.test.assertEqual(context.response.status_code, 200)


@then('I see recipes for each day of the week')
def step_recipes_each_day(context):
    plan = context.response.context['result'].plan
    for index, day in enumerate(DAY_NAMES):
        meals = plan.day_meals(index)
        context.test.assertEqual(len(meals), 3)
        context.test.assertContains(context.response, day)
        for meal in meals:
            context.test.assertContains(context.response, meal.recipe.title)


@then('the estimated weekly cost is ${limit:d} or less')
def step_cost_within(context, limit):
    result = context.response.context['result']
    context.test.assertIsNotNone(result.cost)
    context.test.assertLessEqual(result.cost, Decimal(limit))
    context.test.assertContains(context.response, f'Est. ${result.cost}')


@then('I see the lowest-cost plan available')
def step_lowest_cost(context):
    result = context.response.context['result']
    ingredients = list({k: i for r in FIXED_RECIPES for k, i in r.ingredients.items()}.values())
    prices = pricing.estimates(ingredients, FlatGroceryPrices().quotes(ingredients))
    cheapest = build_week_plan(
        FIXED_RECIPES, ['breakfast', 'lunch', 'dinner'], result.plan.daily_targets, prices=prices, budget=Decimal(0)
    ).cost
    context.test.assertEqual(result.cost, cheapest)
    context.test.assertContains(context.response, 'this is the lowest-cost plan available')


@then('a notice showing how far it is over my budget')
def step_over_budget_notice(context):
    result = context.response.context['result']
    context.test.assertGreater(result.over_budget_by, 0)
    context.test.assertContains(context.response, f'${result.over_budget_by} over your ${context.budget:.2f} budget.')


@then('I see that meal suggestions are temporarily unavailable')
def step_unavailable_notice(context):
    context.test.assertContains(context.response, 'Meal suggestions are temporarily unavailable.')


@then('I can still open This Week and start a workout')
def step_workouts_still_reachable(context):
    # "This Week" belongs to D-3, which plugs its page into NUTRITION_WORKOUTS_LINK. Until then it's the dashboard.
    home = reverse(settings.NUTRITION_WORKOUTS_LINK['url_name'])
    context.test.assertContains(context.response, f'href="{home}"')
    context.test.assertEqual(context.test.client.get(home).status_code, 200)


@then('I am told the plan uses the published Daily Values')
def step_daily_values(context):
    context.test.assertIn("Your personal macro targets aren't ready yet", page_text(context))
    context.test.assertIn('FDA Daily Values', page_text(context))


@then("I am told there is no cost estimate and my budget isn't applied yet")
def step_no_cost(context):
    context.test.assertIn(
        "Grocery prices aren't available yet, so there's no cost estimate and this plan isn't limited by your "
        'weekly budget.',
        page_text(context),
    )
    context.test.assertNotContains(context.response, 'Est. $')
