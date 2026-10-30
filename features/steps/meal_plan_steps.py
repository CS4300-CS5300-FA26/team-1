"""Step definitions for features/meal_plan.feature (story D-5).

The recipe source and macro targets are plug-in points (ADR-008), so these steps swap in the test
doubles from nutrition.testing with override_settings. That keeps the scenarios independent of the
real recipe API and of D-4, which will supply real macro targets later.
"""

from decimal import Decimal

from behave import given, then, when
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from core.models import UserProfile
from nutrition.planner import DAY_NAMES
from nutrition.testing import FIXED_LOWEST_WEEKLY_COST

User = get_user_model()

VALID_PASSWORD = '<M42HVb-;p(!2cve9!'


def use_settings(context, **overrides):
    """Apply settings for this scenario only."""
    override = override_settings(**overrides)
    override.enable()
    context.add_cleanup(override.disable)


def log_in_with_budget(context, budget):
    user = User.objects.create_user('planner', 'planner@example.com', VALID_PASSWORD)
    UserProfile.objects.create(user=user, onboarding_completed=True, weekly_food_budget=Decimal(budget))
    context.test.assertTrue(context.test.client.login(username='planner', password=VALID_PASSWORD))
    context.budget = Decimal(budget)


@given('my weekly food budget is ${budget:d} and my macro targets are set')
def step_budget_and_targets(context, budget):
    use_settings(
        context,
        NUTRITION_RECIPE_SOURCE='nutrition.testing.FixedRecipeSource',
        NUTRITION_MACRO_TARGETS_PROVIDER='nutrition.testing.FixedMacroTargets',
    )
    log_in_with_budget(context, budget)


@given('my weekly food budget is ${budget:d}')
def step_budget(context, budget):
    use_settings(context, NUTRITION_RECIPE_SOURCE='nutrition.testing.FixedRecipeSource')
    log_in_with_budget(context, budget)


@given('the recipe service is unavailable')
def step_service_unavailable(context):
    use_settings(context, NUTRITION_RECIPE_SOURCE='nutrition.testing.UnavailableRecipeSource')
    log_in_with_budget(context, 50)


@when('I open Meal Plan')
def step_open_meal_plan(context):
    context.response = context.test.client.get(reverse('meal_plan'))
    context.test.assertEqual(context.response.status_code, 200)


@then('I see recipes for each day of the week')
def step_recipes_each_day(context):
    plan = context.response.context['plan']
    context.test.assertEqual([day.day_name for day in plan.days], list(DAY_NAMES))
    for day in plan.days:
        context.test.assertContains(context.response, f'{day.day_name}: {day.recipe.title}')


@then('the estimated weekly cost is ${limit:d} or less')
def step_cost_within(context, limit):
    plan = context.response.context['plan']
    context.test.assertLessEqual(plan.total_cost, Decimal(limit))
    context.test.assertContains(context.response, f'Est. ${plan.total_cost}')


@then('I see the lowest-cost plan available')
def step_lowest_cost(context):
    plan = context.response.context['plan']
    context.test.assertEqual(len(plan.days), len(DAY_NAMES))
    context.test.assertEqual(plan.total_cost, FIXED_LOWEST_WEEKLY_COST)
    context.test.assertContains(context.response, 'lowest-cost plan available')


@then('a notice showing how far it is over my budget')
def step_over_budget_notice(context):
    over_by = FIXED_LOWEST_WEEKLY_COST - context.budget
    context.test.assertContains(context.response, f'${over_by} over your ${context.budget:.2f} budget.')


@then('I see that meal suggestions are temporarily unavailable')
def step_unavailable_notice(context):
    context.test.assertContains(context.response, 'Meal suggestions are temporarily unavailable.')


@then('I can still open This Week and start a workout')
def step_workouts_still_reachable(context):
    # "This Week" and starting a workout arrive with D-3; today the dashboard is the home screen they will
    # live on. Check the notice links there and that it still loads while the recipe service is down.
    home = reverse('dashboard')
    context.test.assertContains(context.response, f'href="{home}"')
    context.test.assertEqual(context.test.client.get(home).status_code, 200)
