"""The meal plan report page and the ingredients CSV download."""

import csv
import io
from dataclasses import replace
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.models import UserProfile

from .domain import Ingredient, RecipeDetails
from .planner import build_week_plan
from .report import build_report, ingredients_csv, safe_cell
from .testing import FIXED_LOWEST_WEEKLY_COST, FIXED_RECIPES, fixed_details

User = get_user_model()
PASSWORD = 'Tr4ining-Plan-2026!'
FIXED_SOURCE = 'nutrition.testing.FixedRecipeSource'


def report_for(budget, details_for=lambda meal: fixed_details(meal.recipe)):
    return build_report(build_week_plan(FIXED_RECIPES, Decimal(budget)), details_for)


class ReportMathTests(SimpleTestCase):
    def test_within_budget(self):
        report = report_for('50')
        self.assertEqual(report.percent_used, 57)  # $28.70 of $50
        self.assertEqual(report.meter_percent, 57)
        self.assertEqual(report.remaining, Decimal('21.30'))
        self.assertEqual(report.daily_budget, Decimal('7.14'))

    def test_exactly_at_budget(self):
        report = report_for(FIXED_LOWEST_WEEKLY_COST)
        self.assertEqual((report.percent_used, report.meter_percent, report.remaining), (100, 100, Decimal('0.00')))

    def test_over_budget_caps_the_meter_but_not_the_percentage(self):
        report = report_for('10')
        self.assertEqual(report.percent_used, 287)
        self.assertEqual(report.meter_percent, 100)
        self.assertEqual(report.remaining, Decimal('0.00'))

    def test_zero_budget_does_not_divide_by_zero(self):
        report = report_for('0')
        self.assertEqual((report.percent_used, report.meter_percent, report.daily_budget), (0, 100, Decimal('0.00')))
        self.assertTrue(all(day.percent_of_daily_budget == 0 for day in report.days))

    def test_day_bars_share_one_scale_that_fits_the_daily_budget_line(self):
        report = report_for('50')
        self.assertTrue(all(0 < day.bar_percent < 100 for day in report.days))
        self.assertLess(report.daily_budget_marker_percent, 100)
        biggest = max(report.days, key=lambda d: d.day.cost)
        self.assertEqual(max(d.bar_percent for d in report.days), biggest.bar_percent)

    def test_ingredient_counts_and_missing_details(self):
        report = report_for('50', details_for=lambda meal: None if meal.meal == 'lunch' else fixed_details(meal.recipe))
        self.assertEqual(report.missing_details, 7)
        self.assertEqual(report.ingredient_count, 14 * 2)  # 14 breakfasts and dinners, 2 lines each


class CsvTests(SimpleTestCase):
    def test_formula_like_cells_are_neutralised(self):
        for value in ('=HYPERLINK("http://evil")', '+1', '-1', '@SUM(A1)', '\tx', '\rx'):
            with self.subTest(value=value):
                self.assertEqual(safe_cell(value), "'" + value)
        self.assertEqual(safe_cell('2 cups rice'), '2 cups rice')
        self.assertEqual(safe_cell(Decimal('1.50')), '1.50')

    def test_csv_has_a_header_and_one_row_per_ingredient_line(self):
        rows = list(csv.reader(io.StringIO(ingredients_csv(report_for('50')))))
        self.assertEqual(rows[0], ['Day', 'Meal', 'Recipe', 'Ingredient', 'Cost per serving (USD)'])
        self.assertEqual(len(rows), 1 + 21 * 2)
        self.assertEqual(rows[1], ['Monday', 'Breakfast', 'Breakfast 0', '1 cup Breakfast 0 base', '0.50'])

    def test_hostile_recipe_text_cannot_become_a_formula(self):
        hostile = RecipeDetails(ingredients=(Ingredient(text='=cmd|"/c calc"!A1'),), steps=())
        plan = build_week_plan([replace(r, title='@evil') if r.id == 'b0' else r for r in FIXED_RECIPES], Decimal('50'))
        rows = list(csv.reader(io.StringIO(ingredients_csv(build_report(plan, lambda meal: hostile)))))
        self.assertEqual(rows[1][2:4], ["'@evil", '\'=cmd|"/c calc"!A1'])


@override_settings(NUTRITION_RECIPE_SOURCE=FIXED_SOURCE)
class ReportViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('sam', 'sam@example.com', PASSWORD)
        self.profile = UserProfile.objects.create(
            user=self.user, onboarding_completed=True, weekly_food_budget=Decimal('50.00'), meal_pattern='three'
        )
        self.client.force_login(self.user)

    def test_report_shows_budget_use_daily_spend_and_ingredients(self):
        response = self.client.get(reverse('meal_plan_report'))
        self.assertContains(response, '<h1 class="card__title mb-0">Meal plan report</h1>', html=False)
        self.assertContains(response, '<p class="hero-figure mb-0">$28.70</p>', html=False)
        self.assertContains(response, 'Within budget:</strong> 57% used, $21.30 left.', html=False)
        self.assertContains(response, '<rect class="meter__fill" width="57%"', html=False)
        self.assertContains(response, 'The line marks your daily budget ($7.14).')
        self.assertContains(response, '<th scope="row">Monday</th>', html=False)
        self.assertContains(response, '42 ingredient lines across 21 meals.')
        self.assertContains(response, f'href="{reverse("meal_plan_ingredients_csv")}" download')
        self.assertContains(response, '<summary class="disclosure__summary">Monday', html=False)

    def test_report_shows_the_same_plan_as_the_meal_plan_page(self):
        plan = self.client.get(reverse('meal_plan')).context['plan']
        self.assertEqual(self.client.get(reverse('meal_plan_report')).context['report'].plan, plan)

    def test_over_budget_report(self):
        self.profile.weekly_food_budget = Decimal('10.00')
        self.profile.save()
        response = self.client.get(reverse('meal_plan_report'))
        self.assertContains(response, 'meter mt-4 meter--over')
        self.assertContains(response, '<strong>Over budget</strong> by $18.70 (287% of budget).', html=False)

    def test_zero_budget_report(self):
        self.profile.weekly_food_budget = Decimal('0.00')
        self.profile.save()
        response = self.client.get(reverse('meal_plan_report'))
        self.assertContains(response, '<strong>Over budget</strong> by $28.70.', html=False)
        self.assertContains(response, '&ndash;')  # no "% of daily budget" for a $0 budget

    def test_report_notes_missing_ingredients(self):
        with mock.patch('nutrition.testing.FixedRecipeSource.recipe_details', return_value=None):
            response = self.client.get(reverse('meal_plan_report'))
        self.assertContains(response, 'Ingredients for 21 meals are temporarily unavailable.')

    @override_settings(NUTRITION_RECIPE_SOURCE='nutrition.testing.UnavailableRecipeSource')
    def test_report_when_recipes_are_unavailable(self):
        response = self.client.get(reverse('meal_plan_report'))
        self.assertContains(response, "so there's no report yet.")
        self.assertEqual(self.client.get(reverse('meal_plan_ingredients_csv')).status_code, 404)

    def test_csv_download_is_a_private_attachment_with_a_fixed_name(self):
        response = self.client.get(reverse('meal_plan_ingredients_csv'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertRegex(
            response['Content-Disposition'],
            r'^attachment; filename="fitpro-ingredients-week-of-\d{4}-\d{2}-\d{2}\.csv"$',
        )
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        body = response.content.decode('utf-8')
        self.assertTrue(body.startswith('﻿Day,Meal,Recipe,Ingredient'))

    def test_csv_is_only_ever_the_signed_in_users_plan(self):
        other = User.objects.create_user('other', 'other@example.com', PASSWORD)
        UserProfile.objects.create(
            user=other, onboarding_completed=True, weekly_food_budget=Decimal('500'), meal_pattern='dinner'
        )
        self.client.force_login(other)
        rows = list(
            csv.reader(io.StringIO(self.client.get(reverse('meal_plan_ingredients_csv')).content.decode('utf-8-sig')))
        )
        self.assertEqual({row[1] for row in rows[1:]}, {'Dinner'})

    def test_report_and_csv_need_login_and_onboarding(self):
        self.client.logout()
        for name in ('meal_plan_report', 'meal_plan_ingredients_csv'):
            with self.subTest(name):
                response = self.client.get(reverse(name))
                self.assertRedirects(
                    response, f'{reverse("login")}?next={reverse(name)}', fetch_redirect_response=False
                )
        self.profile.onboarding_completed = False
        self.profile.save()
        self.client.force_login(self.user)
        for name in ('meal_plan_report', 'meal_plan_ingredients_csv'):
            with self.subTest(name):
                self.assertRedirects(
                    self.client.get(reverse(name)), reverse('onboarding'), fetch_redirect_response=False
                )
