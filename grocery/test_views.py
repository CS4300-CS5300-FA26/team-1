"""Tests for the Grocery List page (story D-6)."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import UserProfile
from nutrition.services import week_start

from .testing import PLAIN_BEANS, rice_on_monday_and_wednesday, store_week

User = get_user_model()
PASSWORD = 'Tr4ining-Plan-2026!'
RICE_RECIPES = 'grocery.testing.RiceRecipeSource'
FLAT_PRICES = 'nutrition.testing.FlatGroceryPrices'
NO_PRICES = 'nutrition.connectors.NoGroceryPrices'
BROKEN_PRICES = 'nutrition.testing.BrokenGroceryPrices'
RICE_ONLY_PRICES = 'grocery.testing.RiceOnlyPrices'


def page_text(response) -> str:
    return ' '.join(response.content.decode().split())


def make_user(name='sam', budget='50.00', onboarded=True):
    user = User.objects.create_user(name, f'{name}@example.com', PASSWORD)
    UserProfile.objects.create(
        user=user,
        onboarding_completed=onboarded,
        weekly_food_budget=Decimal(budget) if budget is not None else None,
        planned_meals=['dinner'],
    )
    return user


class AccessTests(TestCase):
    def test_login_is_required(self):
        response = self.client.get(reverse('grocery_list'))
        self.assertRedirects(
            response, f'{reverse("login")}?next={reverse("grocery_list")}', fetch_redirect_response=False
        )

    def test_users_who_have_not_onboarded_are_sent_to_onboarding(self):
        self.client.force_login(make_user(onboarded=False))
        self.assertRedirects(
            self.client.get(reverse('grocery_list')), reverse('onboarding'), fetch_redirect_response=False
        )

    def test_the_page_is_in_the_navigation(self):
        self.client.force_login(make_user())
        response = self.client.get(reverse('grocery_list'))
        self.assertContains(response, f'href="{reverse("grocery_list")}" aria-current="page">Grocery list</a>')
        self.assertContains(self.client.get(reverse('dashboard')), f'href="{reverse("grocery_list")}"')


@override_settings(NUTRITION_RECIPE_SOURCE=RICE_RECIPES, NUTRITION_GROCERY_PRICE_SOURCE=FLAT_PRICES)
class EmptyWeekTests(TestCase):
    """Scenario: Empty week."""

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_with_no_meal_plan_there_is_a_prompt_to_create_one_first(self):
        response = self.client.get(reverse('grocery_list'))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['groceries'])
        self.assertIn("You don't have a meal plan for this week yet.", page_text(response))
        self.assertContains(response, f'href="{reverse("meal_plan")}">Create a meal plan</a>')
        self.assertNotContains(response, 'Ingredients to buy')

    def test_opening_the_list_never_creates_a_meal_plan(self):
        self.client.get(reverse('grocery_list'))
        self.assertEqual(self.user.meal_plans.count(), 0)

    def test_a_plan_from_last_week_does_not_count(self):
        store_week(self.user, [PLAIN_BEANS.id] * 7, monday=week_start() - timedelta(days=7))
        self.assertIsNone(self.client.get(reverse('grocery_list')).context['groceries'])

    @override_settings(NUTRITION_RECIPE_SOURCE='nutrition.testing.UnavailableRecipeSource')
    def test_if_recipes_cannot_be_loaded_it_still_asks_for_a_meal_plan(self):
        store_week(self.user, [PLAIN_BEANS.id] * 7)
        response = self.client.get(reverse('grocery_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create a meal plan')


@override_settings(NUTRITION_RECIPE_SOURCE=RICE_RECIPES, NUTRITION_GROCERY_PRICE_SOURCE=FLAT_PRICES)
class CombinedListTests(TestCase):
    """Scenario: Ingredients combined."""

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        rice_on_monday_and_wednesday(self.user)

    def test_rice_is_listed_once_as_three_cups(self):
        response = self.client.get(reverse('grocery_list'))
        self.assertContains(response, '<th scope="row">Rice</th>', count=1)
        row = page_text(response).split('<th scope="row">Rice</th>')[1].split('</tr>')[0]
        self.assertIn('3 cups', row)

    def test_the_list_shows_an_estimated_total_cost(self):
        response = self.client.get(reverse('grocery_list'))
        groceries = response.context['groceries']
        self.assertIsNotNone(groceries.total)
        self.assertGreater(groceries.total, 0)
        self.assertContains(response, f'Est. ${groceries.total}')
        self.assertContains(response, 'Estimated total')

    def test_each_item_shows_its_cost_and_the_page_explains_the_estimate(self):
        text = page_text(self.client.get(reverse('grocery_list')))
        self.assertIn('Beans', text)
        self.assertIn('buys whole packages', text)
        self.assertNotIn('No price yet', text)

    def test_pantry_staples_are_listed_apart(self):
        response = self.client.get(reverse('grocery_list'))
        self.assertContains(response, 'Check your pantry')
        self.assertContains(response, '<li class="chip">Salt and pepper</li>', count=1)

    def test_it_shows_only_the_signed_in_users_plan(self):
        other = make_user('other')
        store_week(other, [PLAIN_BEANS.id] * 7)
        # sam (setUp) has rice; other has only beans. Sign in as the other user.
        self.client.force_login(other)
        response = self.client.get(reverse('grocery_list'))
        self.assertNotContains(response, '<th scope="row">Rice</th>')
        self.assertContains(response, '<th scope="row">Beans</th>')

    def test_a_budget_the_list_goes_over_is_reported(self):
        profile = self.user.userprofile
        profile.weekly_food_budget = Decimal('1.00')
        profile.save()
        response = self.client.get(reverse('grocery_list'))
        over = response.context['over_budget_by']
        self.assertEqual(over, response.context['groceries'].total - Decimal('1.00'))
        self.assertIn(f'${over} over your $1.00 budget.', page_text(response))

    def test_a_list_within_budget_has_no_over_budget_notice(self):
        response = self.client.get(reverse('grocery_list'))
        self.assertIsNone(response.context['over_budget_by'])
        self.assertNotContains(response, 'over your')

    def test_without_a_budget_there_is_no_comparison(self):
        profile = self.user.userprofile
        profile.weekly_food_budget = None
        profile.save()
        response = self.client.get(reverse('grocery_list'))
        self.assertIsNone(response.context['over_budget_by'])
        self.assertNotContains(response, 'of your $')


@override_settings(NUTRITION_RECIPE_SOURCE=RICE_RECIPES)
class PriceFallbackTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        rice_on_monday_and_wednesday(self.user)

    @override_settings(NUTRITION_GROCERY_PRICE_SOURCE=NO_PRICES)
    def test_without_prices_the_list_still_shows_and_says_there_is_no_estimate(self):
        response = self.client.get(reverse('grocery_list'))
        text = page_text(response)
        self.assertEqual(response.status_code, 200)
        self.assertIn('3 cups', text)
        self.assertIn("Grocery prices aren't available yet, so there's no cost estimate.", text)
        self.assertNotContains(response, 'Est. $')
        self.assertNotContains(response, '<tfoot>')
        self.assertContains(response, 'No price yet', count=2)

    @override_settings(NUTRITION_GROCERY_PRICE_SOURCE=RICE_ONLY_PRICES)
    def test_with_some_prices_only_the_priced_items_are_totalled(self):
        response = self.client.get(reverse('grocery_list'))
        groceries = response.context['groceries']
        text = page_text(response)
        self.assertIsNone(groceries.total)
        self.assertEqual((groceries.priced, groceries.unpriced), (1, 1))
        self.assertIn("Prices are only available for 1 of 2 ingredients, so there's no total yet.", text)
        self.assertIn('Total of priced ingredients', text)
        self.assertNotContains(response, 'Est. $')
        self.assertContains(response, 'No price yet', count=1)

    @override_settings(NUTRITION_GROCERY_PRICE_SOURCE=BROKEN_PRICES)
    def test_a_broken_price_source_cannot_take_the_list_down(self):
        with self.assertLogs('grocery.services', level='ERROR'):
            response = self.client.get(reverse('grocery_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '3 cups')
        self.assertNotContains(response, 'Est. $')


@override_settings(
    NUTRITION_RECIPE_SOURCE='nutrition.testing.FixedRecipeSource', NUTRITION_GROCERY_PRICE_SOURCE=FLAT_PRICES
)
class MatchesTheMealPlanTests(TestCase):
    """The list's total and the meal plan's estimate come from the same prices, so they must agree."""

    def test_the_total_is_the_meal_plans_estimate(self):
        user = User.objects.create_user('match', 'match@example.com', PASSWORD)
        UserProfile.objects.create(
            user=user,
            onboarding_completed=True,
            weekly_food_budget=Decimal('500.00'),
            planned_meals=['breakfast', 'lunch', 'dinner'],
        )
        self.client.force_login(user)
        plan_page = self.client.get(reverse('meal_plan'))  # D-5 makes and stores this week's plan
        cost = plan_page.context['result'].cost
        self.assertIsNotNone(cost)
        response = self.client.get(reverse('grocery_list'))
        self.assertEqual(response.context['groceries'].total, cost)
        self.assertContains(response, f'Est. ${cost}')
        self.assertContains(plan_page, f'Est. ${cost}')

    def test_every_ingredient_in_the_meal_plan_is_on_the_list(self):
        user = User.objects.create_user('every', 'every@example.com', PASSWORD)
        UserProfile.objects.create(
            user=user, onboarding_completed=True, weekly_food_budget=Decimal('500.00'), planned_meals=['dinner']
        )
        self.client.force_login(user)
        plan = self.client.get(reverse('meal_plan')).context['result'].plan
        groceries = self.client.get(reverse('grocery_list')).context['groceries']
        self.assertEqual({i.ingredient.key for i in groceries.items}, set(plan.grams_needed()))
        for item in groceries.items:
            self.assertAlmostEqual(item.grams, plan.grams_needed()[item.ingredient.key], places=6)
