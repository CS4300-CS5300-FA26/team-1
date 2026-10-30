"""Tests for the Meal Plan page (story D-5), its details fragment, and the use cases behind them."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import UserProfile

from .domain import MacroTargets
from .services import meal_details, meals_for_pattern, week_start, weekly_meal_plan
from .testing import FIXED_LOWEST_WEEKLY_COST, FIXED_RECIPES, FIXED_WEEKLY_TARGETS, FixedMacroTargets

User = get_user_model()
PASSWORD = 'Tr4ining-Plan-2026!'

FIXED_SOURCE = 'nutrition.testing.FixedRecipeSource'
DOWN_SOURCE = 'nutrition.testing.UnavailableRecipeSource'
DETAILS_DOWN_SOURCE = 'nutrition.testing.DetailsUnavailableRecipeSource'
FIXED_TARGETS = 'nutrition.testing.FixedMacroTargets'
A_WEDNESDAY = date(2026, 10, 28)


def make_user(username='sam', budget='50.00', onboarded=True, meal_pattern='three'):
    user = User.objects.create_user(username, f'{username}@example.com', PASSWORD)
    UserProfile.objects.create(
        user=user,
        onboarding_completed=onboarded,
        weekly_food_budget=Decimal(budget) if budget is not None else None,
        meal_pattern=meal_pattern,
    )
    return user


@override_settings(NUTRITION_RECIPE_SOURCE=FIXED_SOURCE)
class MealPlanAccessTests(TestCase):
    def test_login_required_for_the_page_and_the_details(self):
        for name in ('meal_plan', 'meal_plan_details'):
            with self.subTest(name):
                response = self.client.get(reverse(name))
                self.assertRedirects(
                    response, f'{reverse("login")}?next={reverse(name)}', fetch_redirect_response=False
                )

    def test_users_who_have_not_onboarded_are_sent_to_onboarding(self):
        self.client.force_login(make_user(onboarded=False))
        for name in ('meal_plan', 'meal_plan_details'):
            with self.subTest(name):
                response = self.client.get(reverse(name))
                self.assertRedirects(response, reverse('onboarding'), fetch_redirect_response=False)

    def test_users_without_a_profile_row_are_sent_to_onboarding(self):
        self.client.force_login(User.objects.create_user('noprofile', 'np@example.com', PASSWORD))
        response = self.client.get(reverse('meal_plan'))
        self.assertRedirects(response, reverse('onboarding'), fetch_redirect_response=False)

    def test_plan_uses_only_the_signed_in_users_budget_and_meals(self):
        make_user('rich', budget='500.00', meal_pattern='three')
        self.client.force_login(make_user('frugal', budget='10.00', meal_pattern='dinner'))
        plan = self.client.get(reverse('meal_plan')).context['plan']
        self.assertEqual(plan.budget, Decimal('10.00'))
        self.assertEqual([m.meal for m in plan.days[0].meals], ['dinner'])

    def test_meal_plan_is_in_the_navigation_and_on_the_dashboard(self):
        self.client.force_login(make_user())
        self.assertContains(self.client.get(reverse('dashboard')), f'href="{reverse("meal_plan")}"', count=2)


@override_settings(NUTRITION_RECIPE_SOURCE=FIXED_SOURCE, NUTRITION_MACRO_TARGETS_PROVIDER=FIXED_TARGETS)
class MealPlanPageTests(TestCase):
    def open_meal_plan(self, budget='50.00', meal_pattern='three', **query):
        self.client.force_login(make_user(budget=budget, meal_pattern=meal_pattern))
        with mock.patch('nutrition.views.timezone.localdate', return_value=A_WEDNESDAY):
            return self.client.get(reverse('meal_plan'), query)

    # Scenario: Plan within budget
    def test_within_budget_shows_every_meal_of_the_week_and_the_estimate(self):
        response = self.open_meal_plan('50.00')
        plan = response.context['plan']
        self.assertEqual(len(plan.days), 7)
        for day in plan.days:
            for meal in day.meals:
                self.assertContains(response, meal.recipe.title)
        self.assertLessEqual(plan.total_cost, Decimal('50.00'))
        self.assertContains(response, f'Est. ${plan.total_cost}')
        self.assertContains(response, 'of your $50.00 budget')
        self.assertNotContains(response, 'over your')

    # Scenario: Budget too low
    def test_budget_too_low_shows_the_lowest_cost_plan_and_how_far_over(self):
        response = self.open_meal_plan('10.00')
        self.assertEqual(response.context['plan'].total_cost, FIXED_LOWEST_WEEKLY_COST)
        self.assertContains(response, '$18.70 over your $10.00 budget.')
        self.assertContains(response, 'lowest-cost plan available')

    def test_today_is_selected_by_default_and_the_other_days_are_hidden(self):
        response = self.open_meal_plan()
        self.assertEqual(response.context['selected_day'].day_name, 'Wednesday')
        self.assertContains(response, 'data-day-link="wednesday" aria-current="true"')
        self.assertContains(
            response, 'data-day-panel="wednesday"\n                       aria-labelledby="day-wednesday-title">'
        )
        self.assertContains(response, 'aria-labelledby="day-monday-title" hidden>')
        self.assertContains(response, 'href="?day=tuesday" data-day-step="-1"')
        self.assertContains(response, 'href="?day=thursday" data-day-step="1"')

    def test_day_and_meal_can_be_chosen_in_the_query_string(self):
        response = self.open_meal_plan(day='sunday', meal='dinner')
        sunday = response.context['plan'].days[6]
        self.assertEqual(response.context['selected_day'], sunday)
        self.assertEqual(response.context['selected_meal'], sunday.meal('dinner'))
        self.assertContains(response, 'href="?day=monday" data-day-step="1"')  # wraps around the week

    def test_unknown_day_or_meal_falls_back_to_the_default(self):
        response = self.open_meal_plan(day='funday', meal='brunch')
        self.assertEqual(response.context['selected_day'].day_name, 'Wednesday')
        self.assertEqual(response.context['selected_meal'].meal, 'breakfast')

    def test_a_meal_not_in_the_users_pattern_falls_back_to_their_first_meal(self):
        response = self.open_meal_plan(meal_pattern='lunch_dinner', day='monday', meal='breakfast')
        self.assertEqual(response.context['selected_meal'].meal, 'lunch')

    def test_selected_meal_shows_its_ingredients_steps_and_targets(self):
        response = self.open_meal_plan(day='monday', meal='lunch')
        title = response.context['selected_meal'].recipe.title
        self.assertContains(response, f'<h2 class="h3" id="meal-details-title" tabindex="-1">{title}</h2>', html=False)
        self.assertContains(response, f'1 cup {title} base')
        self.assertContains(response, f'Prepare the {title}.')
        self.assertContains(response, '15 minutes')
        self.assertContains(response, 'Meal target')
        self.assertContains(response, 'data-day="monday" data-meal="lunch" aria-current="true"')

    def test_meal_pattern_from_onboarding_sets_the_meals_shown(self):
        response = self.open_meal_plan(meal_pattern='breakfast_dinner')
        for day in response.context['plan'].days:
            self.assertEqual([m.meal for m in day.meals], ['breakfast', 'dinner'])
        self.assertNotContains(response, 'data-meal="lunch"')

    def test_page_structure_is_accessible(self):
        response = self.open_meal_plan('10.00')
        self.assertContains(response, '<h1 class="card__title mb-0">Weekly meal plan</h1>', html=False)
        self.assertContains(response, '<nav class="day-picker" aria-label="Days of the week">', html=False)
        self.assertContains(response, 'aria-live="polite" data-day-current>Wednesday</p>', html=False)
        self.assertContains(response, '<span class="visually-hidden">Previous day</span>', html=False)
        self.assertContains(response, 'role="status"')
        self.assertContains(response, '<aside class="panel" id="meal-details" aria-label="Selected meal"', html=False)
        self.assertContains(response, '<title>Meal plan | FitPro</title>', html=False)

    @override_settings(NUTRITION_MACRO_TARGETS_PROVIDER='nutrition.macros.NoMacroTargets')
    def test_recipe_text_from_the_source_is_escaped(self):
        # Without targets the cheapest main (m0) is Monday's lunch, so the hostile title is on the page.
        hostile = [replace(r, title='<script>alert(1)</script>') if r.id == 'm0' else r for r in FIXED_RECIPES]
        with mock.patch('nutrition.testing.FixedRecipeSource.budget_recipes', return_value=hostile):
            response = self.open_meal_plan(day='monday', meal='lunch')
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')


@override_settings(NUTRITION_RECIPE_SOURCE=FIXED_SOURCE)
class BudgetEdgeCasePageTests(TestCase):
    def open_meal_plan(self, budget):
        self.client.force_login(make_user(budget=budget))
        return self.client.get(reverse('meal_plan'))

    def test_zero_budget_gets_the_lowest_cost_week_and_the_whole_cost_as_shortfall(self):
        response = self.open_meal_plan('0.00')
        self.assertContains(response, f'${FIXED_LOWEST_WEEKLY_COST} over your $0.00 budget.')

    def test_one_cent_budget(self):
        response = self.open_meal_plan('0.01')
        self.assertContains(response, '$28.69 over your $0.01 budget.')

    def test_missing_budget_counts_as_zero(self):
        response = self.open_meal_plan(None)
        self.assertEqual(response.context['plan'].budget, Decimal('0.00'))
        self.assertContains(response, 'over your $0.00 budget.')

    def test_negative_budget_counts_as_zero(self):
        response = self.open_meal_plan('-5.00')
        self.assertEqual(response.context['plan'].budget, Decimal('0.00'))

    def test_very_large_budget_is_within_budget(self):
        response = self.open_meal_plan('99999.99')
        self.assertTrue(response.context['plan'].within_budget)
        self.assertNotContains(response, 'over your')


@override_settings(NUTRITION_RECIPE_SOURCE=FIXED_SOURCE)
class MealDetailsFragmentTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user())

    def test_fragment_renders_just_the_details_panel(self):
        response = self.client.get(reverse('meal_plan_details'), {'day': 'tuesday', 'meal': 'dinner'})
        self.assertTemplateUsed(response, 'nutrition/_meal_details.html')
        self.assertTemplateNotUsed(response, 'core/base.html')
        self.assertContains(response, 'Tuesday &middot; Dinner')
        self.assertContains(response, 'Ingredients')

    def test_meals_not_in_the_users_plan_are_404(self):
        for query in ({}, {'day': 'monday'}, {'day': 'funday', 'meal': 'lunch'}, {'day': 'monday', 'meal': 'brunch'}):
            with self.subTest(query=query):
                self.assertEqual(self.client.get(reverse('meal_plan_details'), query).status_code, 404)

    @override_settings(NUTRITION_RECIPE_SOURCE=DOWN_SOURCE)
    def test_fragment_is_404_when_there_is_no_plan(self):
        response = self.client.get(reverse('meal_plan_details'), {'day': 'monday', 'meal': 'lunch'})
        self.assertEqual(response.status_code, 404)


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

    @override_settings(NUTRITION_RECIPE_SOURCE=DETAILS_DOWN_SOURCE)
    def test_plan_still_shows_when_only_recipe_details_are_down(self):
        self.client.force_login(make_user())
        response = self.client.get(reverse('meal_plan'))
        self.assertIsNotNone(response.context['plan'])
        self.assertContains(response, 'Ingredients and instructions are temporarily unavailable.')


@override_settings(NUTRITION_RECIPE_SOURCE=FIXED_SOURCE)
class ServiceTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_week_starts_on_monday(self):
        self.assertEqual(week_start(date(2026, 10, 29)), date(2026, 10, 26))  # a Thursday
        self.assertEqual(week_start(date(2026, 10, 26)), date(2026, 10, 26))

    def test_meal_patterns_map_to_meals_and_blank_means_all_three(self):
        self.assertEqual(meals_for_pattern('dinner'), ('dinner',))
        self.assertEqual(meals_for_pattern('breakfast_dinner'), ('breakfast', 'dinner'))
        self.assertEqual(meals_for_pattern(''), ('breakfast', 'lunch', 'dinner'))

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
        self.assertIsNone(meal_details(FIXED_RECIPES[0]))

    def test_empty_recipe_list_counts_as_unavailable(self):
        with mock.patch('nutrition.testing.FixedRecipeSource.budget_recipes', return_value=[]):
            self.assertTrue(weekly_meal_plan(self.user, Decimal('50')).unavailable)
