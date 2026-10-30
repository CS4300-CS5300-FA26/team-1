"""Tests for the Meal Plan page (story D-5) and the weekly_meal_plan use case."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import UserProfile

from .domain import MacroTargets
from .services import week_start, weekly_meal_plan
from .testing import FIXED_LOWEST_WEEKLY_COST, FIXED_RECIPES, FIXED_WEEKLY_TARGETS, FixedMacroTargets

User = get_user_model()
PASSWORD = 'Tr4ining-Plan-2026!'

FIXED_SOURCE = 'nutrition.testing.FixedRecipeSource'
DOWN_SOURCE = 'nutrition.testing.UnavailableRecipeSource'
FIXED_TARGETS = 'nutrition.testing.FixedMacroTargets'


def make_user(username='sam', budget='50.00', onboarded=True):
    user = User.objects.create_user(username, f'{username}@example.com', PASSWORD)
    UserProfile.objects.create(
        user=user,
        onboarding_completed=onboarded,
        weekly_food_budget=Decimal(budget) if budget is not None else None,
    )
    return user


@override_settings(NUTRITION_RECIPE_SOURCE=FIXED_SOURCE)
class MealPlanAccessTests(TestCase):
    def test_login_required(self):
        response = self.client.get(reverse('meal_plan'))
        self.assertRedirects(response, f'{reverse("login")}?next={reverse("meal_plan")}', fetch_redirect_response=False)

    def test_users_who_have_not_onboarded_are_sent_to_onboarding(self):
        self.client.force_login(make_user(onboarded=False))
        self.assertRedirects(
            self.client.get(reverse('meal_plan')), reverse('onboarding'), fetch_redirect_response=False
        )

    def test_users_without_a_profile_row_are_sent_to_onboarding(self):
        self.client.force_login(User.objects.create_user('noprofile', 'np@example.com', PASSWORD))
        self.assertRedirects(
            self.client.get(reverse('meal_plan')), reverse('onboarding'), fetch_redirect_response=False
        )

    def test_plan_uses_only_the_signed_in_users_budget(self):
        make_user('rich', budget='500.00')
        self.client.force_login(make_user('frugal', budget='10.00'))
        plan = self.client.get(reverse('meal_plan')).context['plan']
        self.assertEqual(plan.budget, Decimal('10.00'))

    def test_meal_plan_is_in_the_navigation_and_on_the_dashboard(self):
        self.client.force_login(make_user())
        self.assertContains(self.client.get(reverse('dashboard')), f'href="{reverse("meal_plan")}"', count=2)


@override_settings(NUTRITION_RECIPE_SOURCE=FIXED_SOURCE, NUTRITION_MACRO_TARGETS_PROVIDER=FIXED_TARGETS)
class MealPlanPageTests(TestCase):
    def open_meal_plan(self, budget='50.00'):
        self.client.force_login(make_user(budget=budget))
        return self.client.get(reverse('meal_plan'))

    # Scenario: Plan within budget
    def test_within_budget_shows_a_recipe_for_each_day_and_the_estimate(self):
        response = self.open_meal_plan('50.00')
        plan = response.context['plan']
        self.assertEqual(len(plan.days), 7)
        for day in plan.days:
            self.assertContains(response, f'{day.day_name}: {day.recipe.title}')
        self.assertLessEqual(plan.total_cost, Decimal('50.00'))
        self.assertContains(response, f'Est. ${plan.total_cost}')
        self.assertContains(response, 'of your $50.00 weekly budget')
        self.assertNotContains(response, 'over your')

    def test_macro_targets_are_used_and_shown_per_day(self):
        response = self.open_meal_plan()
        self.assertTrue(response.context['plan'].uses_macro_targets)
        self.assertContains(response, '(target 150 / 200 / 40 g)')
        self.assertContains(response, '(target 150 / 150 / 40 g)')

    # Scenario: Budget too low
    def test_budget_too_low_shows_the_lowest_cost_plan_and_how_far_over(self):
        response = self.open_meal_plan('10.00')
        plan = response.context['plan']
        self.assertEqual(plan.total_cost, FIXED_LOWEST_WEEKLY_COST)
        self.assertEqual(len(plan.days), 7)
        self.assertContains(response, '$13.10 over your $10.00 budget.')
        self.assertContains(response, 'lowest-cost plan available')

    def test_recipe_titles_link_to_their_instructions_when_the_source_has_them(self):
        linked = replace(FIXED_RECIPES[0], source_url='https://example.com/oats')
        with mock.patch('nutrition.testing.FixedRecipeSource.budget_recipes', return_value=[linked]):
            response = self.open_meal_plan()
        self.assertContains(response, '<a href="https://example.com/oats" rel="noopener noreferrer">', count=7)

    def test_recipe_text_from_the_source_is_escaped(self):
        hostile = replace(FIXED_RECIPES[0], title='<script>alert(1)</script>')
        with mock.patch('nutrition.testing.FixedRecipeSource.budget_recipes', return_value=[hostile]):
            response = self.open_meal_plan()
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')

    def test_page_structure_is_accessible(self):
        response = self.open_meal_plan('10.00')
        self.assertContains(response, '<h1 class="card__title mb-0">Weekly meal plan</h1>', html=False)
        self.assertContains(response, 'role="status"')
        self.assertContains(response, '<ol class="media-list', html=False)
        self.assertContains(response, 'aria-current="page"')
        self.assertContains(response, '<title>Meal plan | FitPro</title>', html=False)


@override_settings(NUTRITION_RECIPE_SOURCE=DOWN_SOURCE)
class RecipeServiceUnavailableTests(TestCase):
    # Scenario: Recipe service unavailable
    def test_unavailable_shows_a_notice_and_a_way_back_to_workouts(self):
        self.client.force_login(make_user())
        response = self.client.get(reverse('meal_plan'))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['plan'])
        self.assertContains(response, 'Meal suggestions are temporarily unavailable.')
        self.assertContains(response, f'href="{reverse("dashboard")}"')
        self.assertNotContains(response, 'Est. $')

    def test_rest_of_the_app_still_works_while_recipes_are_down(self):
        self.client.force_login(make_user())
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)


@override_settings(NUTRITION_RECIPE_SOURCE=FIXED_SOURCE)
class WeeklyMealPlanServiceTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_week_starts_on_monday(self):
        self.assertEqual(week_start(date(2026, 10, 29)), date(2026, 10, 26))  # a Thursday
        self.assertEqual(week_start(date(2026, 10, 26)), date(2026, 10, 26))

    def test_no_macro_targets_plans_by_cost_alone(self):
        result = weekly_meal_plan(self.user, Decimal('50'))
        assert result.plan is not None
        self.assertFalse(result.plan.uses_macro_targets)
        self.assertEqual(result.plan.total_cost, FIXED_LOWEST_WEEKLY_COST)
        self.assertEqual(result.attribution, 'Test recipes.')

    @override_settings(NUTRITION_MACRO_TARGETS_PROVIDER=FIXED_TARGETS)
    def test_macro_provider_is_asked_for_this_users_week(self):
        with mock.patch.object(FixedMacroTargets, 'weekly_targets', return_value=list(FIXED_WEEKLY_TARGETS)) as spy:
            weekly_meal_plan(self.user, Decimal('50'), today=date(2026, 10, 29))
        spy.assert_called_once_with(self.user, date(2026, 10, 26))

    @override_settings(NUTRITION_MACRO_TARGETS_PROVIDER=FIXED_TARGETS)
    def test_invalid_targets_from_the_provider_fall_back_to_cost_only(self):
        broken_weeks = [[MacroTargets(150, 200, 60)] * 6, [{'protein_g': 150}] * 7]
        for broken in broken_weeks:
            with (
                self.subTest(broken=broken),
                mock.patch.object(FixedMacroTargets, 'weekly_targets', return_value=broken),
                self.assertLogs('nutrition.services', level='ERROR'),
            ):
                plan = weekly_meal_plan(self.user, Decimal('50')).plan
                assert plan is not None
                self.assertFalse(plan.uses_macro_targets)

    @override_settings(NUTRITION_RECIPE_SOURCE=DOWN_SOURCE)
    def test_unavailable_source_never_raises(self):
        self.assertTrue(weekly_meal_plan(self.user, Decimal('50')).unavailable)

    def test_empty_recipe_list_counts_as_unavailable(self):
        with mock.patch('nutrition.testing.FixedRecipeSource.budget_recipes', return_value=[]):
            self.assertTrue(weekly_meal_plan(self.user, Decimal('50')).unavailable)
