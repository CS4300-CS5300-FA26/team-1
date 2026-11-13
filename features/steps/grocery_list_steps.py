"""Step definitions for features/grocery_list.feature (story D-6).

The grocery list reads the week's stored meal plan (D-5) and prices from the price connector (ADR-008, ADR-009).
These steps store a plan directly and plug in the stand-ins from nutrition.testing and grocery.testing with
override_settings, so the scenarios don't depend on the planner's choices or on the real catalog's prices.
"""

from decimal import Decimal

from behave import given, then, when
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from core.models import UserProfile
from grocery.testing import rice_on_monday_and_wednesday

User = get_user_model()

VALID_PASSWORD = '<M42HVb-;p(!2cve9!'
RICE_RECIPES = 'grocery.testing.RiceRecipeSource'
FLAT_PRICES = 'nutrition.testing.FlatGroceryPrices'
RICE_ONLY_PRICES = 'grocery.testing.RiceOnlyPrices'


def use_settings(context, **overrides):
    """Apply settings for this scenario only."""
    override = override_settings(**overrides)
    override.enable()
    context.add_cleanup(override.disable)


def log_in(context):
    user = User.objects.create_user('shopper', 'shopper@example.com', VALID_PASSWORD)
    UserProfile.objects.create(
        user=user, onboarding_completed=True, weekly_food_budget=Decimal('50'), planned_meals=['dinner']
    )
    context.test.assertTrue(context.test.client.login(username='shopper', password=VALID_PASSWORD))
    context.user = user


def grocery_text(context) -> str:
    return ' '.join(context.response.content.decode().split())


@given('my meal plan uses 2 cups of rice on Monday and 1 cup on Wednesday')
def step_rice_plan(context):
    use_settings(context, NUTRITION_RECIPE_SOURCE=RICE_RECIPES, NUTRITION_GROCERY_PRICE_SOURCE=FLAT_PRICES)
    log_in(context)
    rice_on_monday_and_wednesday(context.user)


@given('only rice has a price')
def step_only_rice_priced(context):
    use_settings(context, NUTRITION_GROCERY_PRICE_SOURCE=RICE_ONLY_PRICES)


@given('I have no meal plan this week')
def step_no_plan(context):
    use_settings(context, NUTRITION_RECIPE_SOURCE=RICE_RECIPES, NUTRITION_GROCERY_PRICE_SOURCE=FLAT_PRICES)
    log_in(context)


@when('I open Grocery List')
def step_open_grocery_list(context):
    context.response = context.test.client.get(reverse('grocery_list'))
    context.test.assertEqual(context.response.status_code, 200)


@then('I see rice listed once as 3 cups')
def step_rice_once(context):
    context.test.assertContains(context.response, '<th scope="row">Rice</th>', count=1)
    row = grocery_text(context).split('<th scope="row">Rice</th>')[1].split('</tr>')[0]
    context.test.assertIn('3 cups', row)


@then('the list shows an estimated total cost')
def step_total_cost(context):
    groceries = context.response.context['groceries']
    context.test.assertIsNotNone(groceries.total)
    context.test.assertGreater(groceries.total, 0)
    context.test.assertContains(context.response, f'Est. ${groceries.total}')


@then('I see a prompt to create a meal plan first')
def step_prompt_to_plan(context):
    context.test.assertIn("You don't have a meal plan for this week yet.", grocery_text(context))
    context.test.assertContains(context.response, f'href="{reverse("meal_plan")}">Create a meal plan</a>')


@then('I am told there is no total because some prices are missing')
def step_no_total(context):
    context.test.assertIn("so there's no total yet.", grocery_text(context))
    context.test.assertNotContains(context.response, 'Est. $')
