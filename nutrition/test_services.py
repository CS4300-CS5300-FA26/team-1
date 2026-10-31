"""Tests for the meal plan use cases: the connectors, their fallbacks, stored plans, and the hand-off to D-6."""

from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from .models import CatalogRecipe, PlannedMealEntry, WeeklyMealPlan
from .services import (
    PRICES_CONNECTED,
    PRICES_INCOMPLETE,
    PRICES_NOT_CONNECTED,
    current_meal_plan,
    new_meal_plan,
    stored_week_plan,
    week_start,
)
from .targets import published_weekly_targets
from .testing import FIXED_WEEKLY_TARGETS, FixedMacroTargets

User = get_user_model()
ALL_MEALS = ['breakfast', 'lunch', 'dinner']
A_THURSDAY = date(2026, 10, 29)
ITS_MONDAY = date(2026, 10, 26)

FIXED_TARGETS = 'nutrition.testing.FixedMacroTargets'
FLAT_PRICES = 'nutrition.testing.FlatGroceryPrices'


def make_user(name='sam'):
    return User.objects.create_user(name, f'{name}@example.com', 'Tr4ining-Plan-2026!')


class WeekStartTests(TestCase):
    def test_weeks_start_on_monday(self):
        self.assertEqual(week_start(A_THURSDAY), ITS_MONDAY)
        self.assertEqual(week_start(ITS_MONDAY), ITS_MONDAY)


class MacroTargetFallbackTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_without_d4_the_published_daily_values_are_used(self):
        result = current_meal_plan(self.user, ALL_MEALS, Decimal('50'), A_THURSDAY)
        assert result.plan is not None
        self.assertFalse(result.personal_targets)
        self.assertEqual(result.plan.daily_targets, published_weekly_targets())

    @override_settings(NUTRITION_MACRO_TARGETS_PROVIDER=FIXED_TARGETS)
    def test_personal_targets_from_d4_are_used_for_this_users_week(self):
        with mock.patch.object(FixedMacroTargets, 'weekly_targets', return_value=list(FIXED_WEEKLY_TARGETS)) as spy:
            result = current_meal_plan(self.user, ALL_MEALS, Decimal('50'), A_THURSDAY)
        spy.assert_called_once_with(self.user, ITS_MONDAY)
        assert result.plan is not None
        self.assertTrue(result.personal_targets)
        self.assertEqual(result.plan.daily_targets, FIXED_WEEKLY_TARGETS)

    @override_settings(NUTRITION_MACRO_TARGETS_PROVIDER=FIXED_TARGETS)
    def test_an_invalid_week_from_d4_falls_back_and_is_logged(self):
        for broken in ([FIXED_WEEKLY_TARGETS[0]] * 6, [{'protein_g': 150}] * 7):
            with (
                self.subTest(broken=broken),
                mock.patch.object(FixedMacroTargets, 'weekly_targets', return_value=broken),
                self.assertLogs('nutrition.services', level='ERROR'),
            ):
                self.assertFalse(current_meal_plan(self.user, ALL_MEALS, None, A_THURSDAY).personal_targets)

    @override_settings(NUTRITION_MACRO_TARGETS_PROVIDER='nutrition.testing.BrokenMacroTargets')
    def test_a_crashing_d4_connector_falls_back_and_is_logged(self):
        with self.assertLogs('nutrition.services', level='ERROR'):
            result = current_meal_plan(self.user, ALL_MEALS, None, A_THURSDAY)
        self.assertFalse(result.unavailable)
        self.assertFalse(result.personal_targets)


class PriceFallbackTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_without_d6_there_is_no_cost_and_no_budget_limit(self):
        result = current_meal_plan(self.user, ALL_MEALS, Decimal('5'), A_THURSDAY)
        self.assertEqual(result.prices, PRICES_NOT_CONNECTED)
        self.assertIsNone(result.cost)
        self.assertFalse(result.budget_applied)
        self.assertIsNone(result.over_budget_by)

    @override_settings(NUTRITION_GROCERY_PRICE_SOURCE=FLAT_PRICES)
    def test_with_d6_prices_the_plan_is_costed_and_budgeted(self):
        result = current_meal_plan(self.user, ALL_MEALS, Decimal('500'), A_THURSDAY)
        self.assertEqual(result.prices, PRICES_CONNECTED)
        assert result.cost is not None
        self.assertGreater(result.cost, 0)
        self.assertEqual(result.cost % 2, 0)  # whole $2.00 packages
        self.assertTrue(result.budget_applied)
        self.assertEqual(result.over_budget_by, Decimal('0.00'))

    @override_settings(NUTRITION_GROCERY_PRICE_SOURCE=FLAT_PRICES)
    def test_a_budget_too_low_reports_how_far_over(self):
        result = current_meal_plan(self.user, ALL_MEALS, Decimal('10'), A_THURSDAY)
        assert result.cost is not None
        self.assertEqual(result.over_budget_by, result.cost - Decimal('10'))

    @override_settings(NUTRITION_GROCERY_PRICE_SOURCE=FLAT_PRICES)
    def test_no_budget_plans_for_nutrition_and_still_shows_the_cost(self):
        result = current_meal_plan(self.user, ALL_MEALS, None, A_THURSDAY)
        self.assertIsNotNone(result.cost)
        self.assertFalse(result.budget_applied)
        self.assertIsNone(result.over_budget_by)

    @override_settings(
        NUTRITION_RECIPE_SOURCE='nutrition.testing.FixedRecipeSource',
        NUTRITION_GROCERY_PRICE_SOURCE='nutrition.testing.BreakfastOnlyGroceryPrices',
    )
    def test_too_few_prices_to_plan_with_counts_as_incomplete(self):
        result = current_meal_plan(self.user, ALL_MEALS, Decimal('5'), A_THURSDAY)
        self.assertEqual(result.prices, PRICES_INCOMPLETE)
        self.assertIsNone(result.cost)
        self.assertFalse(result.budget_applied)

    @override_settings(NUTRITION_GROCERY_PRICE_SOURCE='nutrition.testing.BrokenGroceryPrices')
    def test_a_crashing_d6_connector_falls_back_and_is_logged(self):
        with self.assertLogs('nutrition.services', level='ERROR'):
            result = current_meal_plan(self.user, ALL_MEALS, Decimal('50'), A_THURSDAY)
        self.assertEqual(result.prices, PRICES_NOT_CONNECTED)
        self.assertFalse(result.unavailable)

    def test_a_negative_budget_counts_as_zero(self):
        self.assertEqual(current_meal_plan(self.user, ALL_MEALS, Decimal('-5'), A_THURSDAY).budget, Decimal('0'))


class StoredPlanTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def plan_entries(self):
        return list(PlannedMealEntry.objects.filter(plan__user=self.user).values_list('day', 'meal', 'recipe_id'))

    def test_the_plan_is_stored_and_reused_for_the_week(self):
        first = current_meal_plan(self.user, ALL_MEALS, Decimal('50'), A_THURSDAY)
        entries = self.plan_entries()
        self.assertEqual(len(entries), 21)
        again = current_meal_plan(self.user, ALL_MEALS, Decimal('50'), ITS_MONDAY)
        self.assertEqual(self.plan_entries(), entries)
        self.assertEqual(first.plan, again.plan)
        self.assertEqual(WeeklyMealPlan.objects.get(user=self.user).week_start, ITS_MONDAY)

    def test_a_change_in_meals_budget_targets_or_prices_makes_a_new_plan(self):
        current_meal_plan(self.user, ALL_MEALS, Decimal('50'), A_THURSDAY)
        changes = [
            lambda: current_meal_plan(self.user, ['dinner'], Decimal('50'), A_THURSDAY),
            lambda: current_meal_plan(self.user, ['dinner'], Decimal('60'), A_THURSDAY),
        ]
        for change in changes:
            seed = WeeklyMealPlan.objects.get(user=self.user).seed
            with mock.patch('nutrition.services.secrets.randbelow', return_value=seed + 1):
                change()
            self.assertEqual(WeeklyMealPlan.objects.get(user=self.user).seed, seed + 1)
        with override_settings(NUTRITION_MACRO_TARGETS_PROVIDER=FIXED_TARGETS):
            plan = current_meal_plan(self.user, ['dinner'], Decimal('60'), A_THURSDAY).plan
        assert plan is not None
        self.assertEqual(plan.daily_targets, FIXED_WEEKLY_TARGETS)
        with override_settings(NUTRITION_GROCERY_PRICE_SOURCE=FLAT_PRICES):
            self.assertIsNotNone(current_meal_plan(self.user, ['dinner'], Decimal('60'), A_THURSDAY).cost)
        self.assertEqual(len(self.plan_entries()), 7)

    def test_a_recipe_leaving_the_catalog_makes_a_new_plan(self):
        current_meal_plan(self.user, ALL_MEALS, None, A_THURSDAY)
        gone = PlannedMealEntry.objects.filter(plan__user=self.user).first()
        assert gone is not None
        CatalogRecipe.objects.filter(slug=gone.recipe_id).delete()
        result = current_meal_plan(self.user, ALL_MEALS, None, A_THURSDAY)
        assert result.plan is not None
        self.assertEqual(len(self.plan_entries()), 21)
        self.assertNotIn(gone.recipe_id, result.plan.recipe_ids())

    def test_unreadable_stored_inputs_make_a_new_plan(self):
        current_meal_plan(self.user, ALL_MEALS, None, A_THURSDAY)
        WeeklyMealPlan.objects.filter(user=self.user).update(inputs={'meals': ALL_MEALS, 'targets': [[0, 0, 0]] * 7})
        with self.assertLogs('nutrition.services', level='WARNING'):
            self.assertIsNone(stored_week_plan(self.user, ITS_MONDAY))

    def test_a_new_plan_avoids_the_recipes_just_shown(self):
        first = current_meal_plan(self.user, ALL_MEALS, None, A_THURSDAY).plan
        second = new_meal_plan(self.user, ALL_MEALS, None, A_THURSDAY).plan
        assert first is not None and second is not None
        self.assertLess(len(first.recipe_ids() & second.recipe_ids()), len(first.recipe_ids()))
        self.assertEqual(stored_week_plan(self.user, ITS_MONDAY), second)

    def test_each_user_has_their_own_plan(self):
        other = make_user('alex')
        current_meal_plan(other, ['dinner'], None, A_THURSDAY)
        current_meal_plan(self.user, ALL_MEALS, None, A_THURSDAY)
        self.assertEqual(len(self.plan_entries()), 21)
        other_plan = stored_week_plan(other, ITS_MONDAY)
        assert other_plan is not None
        self.assertEqual(other_plan.meal_keys, ('dinner',))


class StoredWeekPlanConnectorTests(TestCase):
    """What D-6 (grocery list) reads."""

    def setUp(self):
        self.user = make_user()

    def test_no_plan_this_week_is_none_and_nothing_is_created(self):
        self.assertIsNone(stored_week_plan(self.user, ITS_MONDAY))
        self.assertFalse(WeeklyMealPlan.objects.exists())

    def test_the_stored_plan_gives_each_meals_ingredient_weights(self):
        current_meal_plan(self.user, ['dinner'], None, A_THURSDAY)
        plan = stored_week_plan(self.user, ITS_MONDAY)
        assert plan is not None
        meal = plan.meals[0]
        weighed = [(line, grams) for line, grams in meal.lines() if grams is not None]
        self.assertTrue(weighed)
        line, grams = weighed[0]
        assert line.grams is not None and line.ingredient is not None
        self.assertAlmostEqual(grams, line.grams * float(meal.servings))
        self.assertTrue(line.ingredient.fdc_id)
        self.assertEqual(sum(plan.grams_needed().values()) > 0, True)

    @override_settings(NUTRITION_RECIPE_SOURCE='nutrition.testing.UnavailableRecipeSource')
    def test_unavailable_recipes_mean_no_plan(self):
        self.assertIsNone(stored_week_plan(self.user, ITS_MONDAY))


@override_settings(NUTRITION_RECIPE_SOURCE='nutrition.testing.UnavailableRecipeSource')
class UnavailableTests(TestCase):
    def test_an_unavailable_recipe_source_never_raises(self):
        result = current_meal_plan(make_user(), ALL_MEALS, Decimal('50'), A_THURSDAY)
        self.assertTrue(result.unavailable)
        self.assertFalse(WeeklyMealPlan.objects.exists())

    @override_settings(NUTRITION_RECIPE_SOURCE='nutrition.testing.FixedRecipeSource')
    def test_no_recipes_for_a_planned_meal_counts_as_unavailable(self):
        with (
            mock.patch('nutrition.testing.FixedRecipeSource.recipes', return_value=[]),
            self.assertLogs('nutrition.services', level='ERROR'),
        ):
            self.assertTrue(current_meal_plan(make_user(), ALL_MEALS, None, A_THURSDAY).unavailable)
