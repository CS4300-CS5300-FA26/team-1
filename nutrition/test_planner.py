"""Unit tests for the pure meal planner (no database, no network)."""

import itertools
import random
from collections import Counter
from decimal import Decimal
from typing import Any

from django.test import SimpleTestCase

from .domain import MacroTargets, MealPlan, PlannedDay, Recipe, money
from .planner import DAY_NAMES, MAX_USES_PER_RECIPE, SERVINGS_PER_DAY, NoRecipesError, build_week_plan
from .testing import FIXED_LOWEST_WEEKLY_COST, FIXED_RECIPES, FIXED_WEEKLY_TARGETS, recipe


class LowestCostWeekTests(SimpleTestCase):
    def test_plan_has_one_recipe_for_each_day_monday_first(self):
        plan = build_week_plan(FIXED_RECIPES, Decimal('50'))
        self.assertEqual([day.day_name for day in plan.days], list(DAY_NAMES))
        self.assertTrue(all(day.servings == SERVINGS_PER_DAY for day in plan.days))

    def test_without_targets_the_lowest_cost_week_is_used(self):
        plan = build_week_plan(FIXED_RECIPES, Decimal('50'))
        self.assertEqual(plan.total_cost, FIXED_LOWEST_WEEKLY_COST)

    def test_no_recipe_is_used_more_than_the_variety_cap(self):
        plan = build_week_plan(FIXED_RECIPES, Decimal('50'))
        uses = Counter(day.recipe.id for day in plan.days)
        self.assertLessEqual(max(uses.values()), MAX_USES_PER_RECIPE)

    def test_cap_rises_when_there_are_too_few_recipes_to_fill_a_week(self):
        plan = build_week_plan([recipe('a', '1.00'), recipe('b', '2.00')], Decimal('100'))
        self.assertEqual(len(plan.days), 7)
        self.assertEqual(Counter(day.recipe.id for day in plan.days), {'a': 4, 'b': 3})

    def test_single_recipe_fills_the_whole_week(self):
        plan = build_week_plan([recipe('only', '1.00')], Decimal('100'))
        self.assertEqual({day.recipe.id for day in plan.days}, {'only'})
        self.assertEqual(plan.total_cost, Decimal('21.00'))

    def test_duplicate_recipe_ids_count_once(self):
        doubled = list(FIXED_RECIPES) + list(FIXED_RECIPES)
        self.assertEqual(build_week_plan(doubled, Decimal('50')), build_week_plan(FIXED_RECIPES, Decimal('50')))

    def test_same_input_gives_the_same_plan_whatever_the_order(self):
        shuffled = list(FIXED_RECIPES)
        random.Random(7).shuffle(shuffled)
        self.assertEqual(build_week_plan(shuffled, Decimal('50')), build_week_plan(FIXED_RECIPES, Decimal('50')))

    def test_no_recipes_is_an_error(self):
        with self.assertRaises(NoRecipesError):
            build_week_plan([], Decimal('50'))


class BudgetBoundaryTests(SimpleTestCase):
    """Boundary values around the lowest possible weekly cost ($23.10 for FIXED_RECIPES)."""

    def test_budget_exactly_at_the_lowest_cost_is_within_budget(self):
        plan = build_week_plan(FIXED_RECIPES, FIXED_LOWEST_WEEKLY_COST)
        self.assertTrue(plan.within_budget)
        self.assertEqual(plan.over_budget_by, Decimal('0.00'))

    def test_one_cent_under_the_lowest_cost_is_over_by_one_cent(self):
        plan = build_week_plan(FIXED_RECIPES, FIXED_LOWEST_WEEKLY_COST - Decimal('0.01'))
        self.assertFalse(plan.within_budget)
        self.assertEqual(plan.over_budget_by, Decimal('0.01'))
        self.assertEqual(plan.total_cost, FIXED_LOWEST_WEEKLY_COST)

    def test_budget_too_low_returns_the_lowest_cost_plan_and_the_shortfall(self):
        plan = build_week_plan(FIXED_RECIPES, Decimal('10'), FIXED_WEEKLY_TARGETS)
        self.assertEqual(plan.total_cost, FIXED_LOWEST_WEEKLY_COST)
        self.assertEqual(plan.over_budget_by, Decimal('13.10'))

    def test_zero_budget_is_over_by_the_whole_cost(self):
        plan = build_week_plan(FIXED_RECIPES, Decimal('0'))
        self.assertEqual(plan.over_budget_by, FIXED_LOWEST_WEEKLY_COST)

    def test_budget_is_rounded_to_cents(self):
        self.assertEqual(build_week_plan(FIXED_RECIPES, Decimal('50.004')).budget, Decimal('50.00'))


class MacroTargetTests(SimpleTestCase):
    def test_targets_pick_better_fitting_recipes_when_the_budget_allows(self):
        cheapest = build_week_plan(FIXED_RECIPES, Decimal('50'))
        fitted = build_week_plan(FIXED_RECIPES, Decimal('50'), FIXED_WEEKLY_TARGETS)
        protein = sum(day.protein_g for day in fitted.days)
        self.assertGreater(protein, sum(day.protein_g for day in cheapest.days))
        self.assertLessEqual(fitted.total_cost, Decimal('50'))
        self.assertTrue(fitted.uses_macro_targets)

    def test_each_day_carries_its_own_targets(self):
        plan = build_week_plan(FIXED_RECIPES, Decimal('50'), FIXED_WEEKLY_TARGETS)
        self.assertEqual([day.targets for day in plan.days], list(FIXED_WEEKLY_TARGETS))

    def test_tight_budget_still_fits_even_with_targets(self):
        budget = FIXED_LOWEST_WEEKLY_COST + Decimal('1.00')
        plan = build_week_plan(FIXED_RECIPES, budget, FIXED_WEEKLY_TARGETS)
        self.assertLessEqual(plan.total_cost, budget)

    def test_wrong_number_of_daily_targets_is_rejected(self):
        with self.assertRaises(ValueError):
            build_week_plan(FIXED_RECIPES, Decimal('50'), FIXED_WEEKLY_TARGETS[:6])

    def test_zero_targets_do_not_divide_by_zero(self):
        zero = [MacroTargets(0, 0, 0)] * 7
        self.assertEqual(len(build_week_plan(FIXED_RECIPES, Decimal('50'), zero).days), 7)


class BruteForceTests(SimpleTestCase):
    """Check the greedy planner against exhaustive search on small random catalogs."""

    def all_weeks(self, recipes):
        cap = max(MAX_USES_PER_RECIPE, -(-7 // len(recipes)))
        for week in itertools.product(recipes, repeat=7):
            if max(Counter(r.id for r in week).values()) <= cap:
                yield week

    def week_cost(self, week):
        return money(sum((r.cost_per_serving * SERVINGS_PER_DAY for r in week), Decimal(0)))

    def test_lowest_cost_week_is_truly_the_minimum_and_targets_never_break_a_feasible_budget(self):
        rng = random.Random(2026)
        for trial in range(25):
            recipes = [
                recipe(f'r{i}', f'{rng.randint(50, 400) / 100:.2f}', protein=rng.randint(5, 50))
                for i in range(rng.randint(2, 4))
            ]
            minimum = min(self.week_cost(week) for week in self.all_weeks(recipes))
            budget = minimum + Decimal(rng.randint(0, 2000)) / 100
            with self.subTest(trial=trial):
                self.assertEqual(build_week_plan(recipes, Decimal('0')).total_cost, minimum)
                fitted = build_week_plan(recipes, budget, FIXED_WEEKLY_TARGETS)
                self.assertLessEqual(fitted.total_cost, budget)


class DomainTests(SimpleTestCase):
    def test_recipe_rejects_bad_values(self):
        bad: list[dict[str, Any]] = [
            {'title': ' '},
            {'cost_per_serving': Decimal('0')},
            {'protein_g': -1},
            {'carbs_g': float('nan')},
            {'fat_g': float('inf')},
        ]
        base: dict[str, Any] = {
            'id': 'x',
            'title': 'X',
            'cost_per_serving': Decimal('1'),
            'protein_g': 1,
            'carbs_g': 1,
            'fat_g': 1,
        }
        for override in bad:
            with self.subTest(override=override), self.assertRaises(ValueError):
                Recipe(**{**base, **override})

    def test_negative_macro_targets_are_rejected(self):
        with self.assertRaises(ValueError):
            MacroTargets(-1, 0, 0)

    def test_day_totals_scale_with_servings(self):
        day = PlannedDay('Monday', recipe('a', '1.25', protein=20, carbs=30, fat=5), servings=3)
        self.assertEqual((day.cost, day.protein_g, day.carbs_g, day.fat_g), (Decimal('3.75'), 60, 90, 15))

    def test_empty_plan_costs_nothing(self):
        self.assertEqual(MealPlan(days=(), budget=Decimal('5')).total_cost, Decimal('0.00'))
