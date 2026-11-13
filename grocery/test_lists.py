"""Tests for combining a meal plan into a grocery list and showing amounts the way shoppers say them (D-6)."""

from decimal import Decimal

from django.test import SimpleTestCase

from nutrition.domain import PlannedMeal, PriceEstimate, WeekPlan, purchase_cost
from nutrition.testing import BEANS, EGGS, FIXED_WEEKLY_TARGETS, MILK, OATS, RICE, recipe

from .lists import build_grocery_list, describe_amount
from .testing import CUP_OF_RICE_G
from .testing import RICE as DENSE_RICE

FLAT = PriceEstimate(price_per_gram=Decimal('0.004'), package_grams=Decimal('500'), quote_count=1)  # $2 per 500 g


def week(*recipes_by_day, meal='dinner') -> WeekPlan:
    """A seven-day plan with one meal a day from the recipes given (Monday first)."""
    assert len(recipes_by_day) == 7
    meals = tuple(
        PlannedMeal(day=day, meal=meal, recipe=r, servings=Decimal(1)) for day, r in enumerate(recipes_by_day)
    )
    return WeekPlan(meals=meals, daily_targets=FIXED_WEEKLY_TARGETS, meal_keys=(meal,))


class DescribeAmountTests(SimpleTestCase):
    def test_volume_ingredients_are_shown_in_cups(self):
        self.assertEqual(describe_amount(DENSE_RICE, 3 * CUP_OF_RICE_G), '3 cups')
        self.assertEqual(describe_amount(DENSE_RICE, CUP_OF_RICE_G), '1 cup')

    def test_cups_are_rounded_to_the_nearest_quarter_with_fractions(self):
        self.assertEqual(describe_amount(DENSE_RICE, 1.5 * CUP_OF_RICE_G), '1½ cups')
        self.assertEqual(describe_amount(DENSE_RICE, 0.25 * CUP_OF_RICE_G), '¼ cup')
        self.assertEqual(describe_amount(DENSE_RICE, 2.74 * CUP_OF_RICE_G), '2¾ cups')
        self.assertEqual(describe_amount(DENSE_RICE, 2.9 * CUP_OF_RICE_G), '3 cups')

    def test_small_volumes_use_tablespoons_then_teaspoons(self):
        tbsp = CUP_OF_RICE_G / 16
        self.assertEqual(describe_amount(DENSE_RICE, 2 * tbsp), '2 tbsp')
        self.assertEqual(describe_amount(DENSE_RICE, 1 * tbsp), '1 tbsp')
        self.assertEqual(describe_amount(DENSE_RICE, tbsp / 3), '1 tsp')
        self.assertEqual(describe_amount(DENSE_RICE, 0.001), '¼ tsp')  # never rounded down to nothing

    def test_ingredients_with_a_weight_each_are_counted_and_rounded_up(self):
        self.assertEqual(describe_amount(EGGS, 150), '3')
        self.assertEqual(describe_amount(EGGS, 160), '4')  # 3.2 eggs: you can't buy part of one
        self.assertEqual(describe_amount(EGGS, 1), '1')

    def test_everything_else_is_shown_in_ounces_then_pounds(self):
        self.assertEqual(describe_amount(BEANS, 200), '7 oz')
        self.assertEqual(describe_amount(BEANS, 453.59237), '1 lb')
        self.assertEqual(describe_amount(BEANS, 453.59237 * 1.5), '1½ lb')
        self.assertEqual(describe_amount(BEANS, 453.59237 * 2.1), '2 lb')
        self.assertEqual(describe_amount(BEANS, 1), '½ oz')

    def test_floating_point_dust_does_not_change_an_amount(self):
        self.assertEqual(describe_amount(DENSE_RICE, (2 * CUP_OF_RICE_G) + CUP_OF_RICE_G + 1e-9), '3 cups')
        self.assertEqual(describe_amount(EGGS, 150.0000001), '3')


class CombiningTests(SimpleTestCase):
    def setUp(self):
        self.two_cups = recipe('two-cups', 'main', (DENSE_RICE, 2 * CUP_OF_RICE_G))
        self.one_cup = recipe('one-cup', 'main', (DENSE_RICE, CUP_OF_RICE_G))
        self.beans = recipe('beans', 'main', (BEANS, 200))

    def test_rice_on_monday_and_wednesday_is_listed_once_as_three_cups(self):
        plan = week(self.two_cups, self.beans, self.one_cup, self.beans, self.beans, self.beans, self.beans)
        groceries = build_grocery_list(plan, {})
        rice = [item for item in groceries.items if item.ingredient.key == 'rice']
        self.assertEqual(len(rice), 1)
        self.assertEqual(rice[0].amount, '3 cups')
        self.assertAlmostEqual(rice[0].grams, 3 * CUP_OF_RICE_G, places=6)

    def test_servings_scale_the_amounts(self):
        meals = tuple(
            PlannedMeal(day=day, meal='dinner', recipe=self.one_cup, servings=Decimal('1.5' if day == 0 else '1'))
            for day in range(7)
        )
        plan = WeekPlan(meals=meals, daily_targets=FIXED_WEEKLY_TARGETS, meal_keys=('dinner',))
        # 1.5 + six more servings of one cup each = 7.5 cups
        self.assertEqual(build_grocery_list(plan, {}).items[0].amount, '7½ cups')

    def test_items_are_sorted_by_name_and_each_listed_once(self):
        mixed = recipe('mixed', 'main', (OATS, 80), (MILK, 250), (EGGS, 100))
        groceries = build_grocery_list(week(*[mixed] * 7), {})
        self.assertEqual([item.name for item in groceries.items], ['Eggs', 'Milk', 'Oats'])

    def test_pantry_lines_are_listed_apart_once(self):
        # Every test recipe has an unweighed "Salt and pepper" line.
        groceries = build_grocery_list(week(*[self.beans] * 7), {})
        self.assertEqual(groceries.pantry, ('Salt and pepper',))
        self.assertEqual([item.name for item in groceries.items], ['Beans'])


class CostTests(SimpleTestCase):
    def setUp(self):
        self.rice = recipe('rice-bowl', 'main', (RICE, 100))
        self.beans = recipe('beans', 'main', (BEANS, 100))

    def test_a_cost_per_item_in_whole_packages_and_a_total(self):
        plan = week(*[self.rice] * 4, *[self.beans] * 3)  # 400 g of rice, 300 g of beans: one 500 g package each
        groceries = build_grocery_list(plan, {'rice': FLAT, 'beans': FLAT})
        by_name = {item.name: item for item in groceries.items}
        self.assertEqual(by_name['Rice'].packages, 1)
        self.assertEqual(by_name['Rice'].cost, Decimal('2.00'))
        self.assertEqual(groceries.total, Decimal('4.00'))
        self.assertEqual(groceries.unpriced, 0)
        self.assertTrue(groceries.has_prices)

    def test_going_over_a_package_buys_another(self):
        plan = week(*[self.rice] * 6, self.beans)  # 600 g of rice needs two 500 g packages
        groceries = build_grocery_list(plan, {'rice': FLAT, 'beans': FLAT})
        self.assertEqual({i.name: i.packages for i in groceries.items}, {'Beans': 1, 'Rice': 2})
        self.assertEqual(groceries.total, Decimal('6.00'))

    def test_the_total_is_the_meal_plans_own_estimate(self):
        plan = week(*[self.rice] * 5, *[self.beans] * 2)
        prices = {'rice': FLAT, 'beans': FLAT}
        self.assertEqual(build_grocery_list(plan, prices).total, purchase_cost(plan.grams_needed(), prices))

    def test_some_prices_missing_gives_a_partial_total_but_no_estimate(self):
        plan = week(*[self.rice] * 4, *[self.beans] * 3)
        groceries = build_grocery_list(plan, {'rice': FLAT})
        self.assertIsNone(groceries.total)
        self.assertEqual(groceries.priced_total, Decimal('2.00'))
        self.assertEqual(groceries.unpriced, 1)
        self.assertEqual(groceries.priced, 1)
        beans = next(item for item in groceries.items if item.name == 'Beans')
        self.assertIsNone(beans.cost)
        self.assertIsNone(beans.packages)

    def test_no_prices_at_all(self):
        groceries = build_grocery_list(week(*[self.rice] * 7), {})
        self.assertIsNone(groceries.total)
        self.assertEqual(groceries.priced_total, Decimal('0.00'))
        self.assertFalse(groceries.has_prices)
        self.assertEqual(groceries.unpriced, 1)
