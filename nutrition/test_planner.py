"""Unit tests for the pure meal planner (no database, no network)."""

import itertools
import random
from collections import Counter
from decimal import Decimal
from typing import Any

from django.test import SimpleTestCase

from .domain import MEALS, MacroTargets, MealPlan, PlannedDay, PlannedMeal, Recipe
from .planner import DAY_NAMES, NoRecipesError, build_week_plan, meal_shares
from .testing import (
    FIXED_BREAKFASTS,
    FIXED_LOWEST_WEEKLY_COST,
    FIXED_MAINS,
    FIXED_RECIPES,
    FIXED_WEEKLY_TARGETS,
    recipe,
)

BIG_BUDGET = Decimal('500')


def recipe_ids(plan: MealPlan) -> list[str]:
    return [meal.recipe.id for day in plan.days for meal in day.meals]


class WeekShapeTests(SimpleTestCase):
    def test_every_day_has_each_chosen_meal_in_order(self):
        plan = build_week_plan(FIXED_RECIPES, BIG_BUDGET)
        self.assertEqual([day.day_name for day in plan.days], list(DAY_NAMES))
        for day in plan.days:
            self.assertEqual([meal.meal for meal in day.meals], list(MEALS))

    def test_meal_patterns(self):
        patterns = [('breakfast', 'dinner'), ('lunch', 'dinner'), ('dinner',), ('dinner', 'breakfast')]
        for meals in patterns:
            with self.subTest(meals=meals):
                plan = build_week_plan(FIXED_RECIPES, BIG_BUDGET, meals)
                expected = [meal for meal in MEALS if meal in meals]  # always in day order
                self.assertTrue(all([m.meal for m in day.meals] == expected for day in plan.days))

    def test_breakfasts_are_breakfast_recipes_and_lunch_and_dinner_are_mains(self):
        plan = build_week_plan(FIXED_RECIPES, BIG_BUDGET)
        for day in plan.days:
            for meal in day.meals:
                expected = 'breakfast' if meal.meal == 'breakfast' else 'main'
                self.assertEqual(meal.recipe.course, expected)

    def test_unknown_or_no_meals_are_rejected(self):
        for meals in [(), ('brunch',)]:
            with self.subTest(meals=meals), self.assertRaises(ValueError):
                build_week_plan(FIXED_RECIPES, BIG_BUDGET, meals)


class EveryMealDifferentTests(SimpleTestCase):
    def test_every_meal_in_the_week_is_a_different_recipe(self):
        for targets in (None, FIXED_WEEKLY_TARGETS):
            with self.subTest(with_targets=targets is not None):
                ids = recipe_ids(build_week_plan(FIXED_RECIPES, BIG_BUDGET, targets=targets))
                self.assertEqual(len(ids), 21)
                self.assertEqual(len(set(ids)), 21)

    def test_still_all_different_when_the_budget_is_too_low(self):
        ids = recipe_ids(build_week_plan(FIXED_RECIPES, Decimal('1')))
        self.assertEqual(len(set(ids)), len(ids))

    def test_too_few_recipes_repeats_as_evenly_as_possible(self):
        plan = build_week_plan([recipe('b', '1.00', 'breakfast'), *FIXED_MAINS[:5]], BIG_BUDGET)
        breakfasts = Counter(day.meals[0].recipe.id for day in plan.days)
        mains = Counter(m.recipe.id for day in plan.days for m in day.meals[1:])
        self.assertEqual(breakfasts, {'b': 7})
        self.assertEqual(sorted(mains.values()), [2, 3, 3, 3, 3])  # 14 meals over 5 mains

    def test_missing_course_is_an_error_only_if_a_meal_needs_it(self):
        with self.assertRaises(NoRecipesError):
            build_week_plan(FIXED_MAINS, BIG_BUDGET)  # breakfast needed, none available
        self.assertEqual(len(build_week_plan(FIXED_MAINS, BIG_BUDGET, ('lunch', 'dinner')).days), 7)

    def test_no_recipes_is_an_error(self):
        with self.assertRaises(NoRecipesError):
            build_week_plan([], BIG_BUDGET)


class AvoidTests(SimpleTestCase):
    """Recipes to avoid (plans already shown) are used only when nothing else fits."""

    def test_avoided_recipes_are_replaced_when_there_are_others(self):
        first = build_week_plan(FIXED_RECIPES, BIG_BUDGET, ('dinner',))
        second = build_week_plan(FIXED_RECIPES, BIG_BUDGET, ('dinner',), avoid=recipe_ids(first))
        self.assertFalse(set(recipe_ids(first)) & set(recipe_ids(second)))  # 16 mains: 7 fresh ones exist

    def test_avoided_recipes_fill_in_when_there_are_not_enough_others(self):
        first = build_week_plan(FIXED_RECIPES, BIG_BUDGET)
        second = build_week_plan(FIXED_RECIPES, BIG_BUDGET, avoid=recipe_ids(first))
        breakfasts = {day.meals[0].recipe.id for day in second.days}
        self.assertEqual(breakfasts & {'b7'}, {'b7'})  # the one unused breakfast is used
        self.assertEqual(len(set(recipe_ids(second))), 21)  # still all different

    def test_avoid_still_respects_a_budget_that_can_be_met(self):
        first = build_week_plan(FIXED_RECIPES, Decimal('35'))
        second = build_week_plan(FIXED_RECIPES, Decimal('35'), avoid=recipe_ids(first))
        self.assertLessEqual(second.total_cost, Decimal('35'))
        self.assertNotEqual(recipe_ids(first), recipe_ids(second))

    def test_avoid_with_a_budget_too_low_picks_the_cheapest_new_recipes(self):
        first = build_week_plan(FIXED_RECIPES, Decimal('1'), ('dinner',))
        second = build_week_plan(FIXED_RECIPES, Decimal('1'), ('dinner',), avoid=recipe_ids(first))
        self.assertEqual(recipe_ids(second), [f'm{i}' for i in range(7, 14)])


class MacroRowTests(SimpleTestCase):
    def test_macro_rows_show_grams_targets_and_capped_percentages(self):
        meal = PlannedMeal('dinner', recipe('x', '1', protein=30, carbs=80, fat=0), MacroTargets(60, 40, 0))
        rows = {row.label: row for row in meal.macros()}
        self.assertEqual((rows['Protein'].grams, rows['Protein'].target, rows['Protein'].percent), (30, 60, 50))
        self.assertEqual(rows['Carbs'].percent, 100)  # 200% of target is drawn as a full bar
        self.assertEqual(rows['Fat'].percent, 0)  # a 0 g target can't be divided by

    def test_macro_rows_without_targets(self):
        rows = PlannedMeal('dinner', recipe('x', '1')).macros()
        self.assertTrue(all(row.target is None and row.percent == 0 for row in rows))


class LowestCostTests(SimpleTestCase):
    def test_without_targets_the_lowest_cost_week_is_used(self):
        self.assertEqual(build_week_plan(FIXED_RECIPES, BIG_BUDGET).total_cost, FIXED_LOWEST_WEEKLY_COST)

    def test_cheapest_recipes_come_first_in_the_week(self):
        monday = build_week_plan(FIXED_RECIPES, BIG_BUDGET).days[0]
        self.assertEqual(monday.meals[0].recipe.id, 'b0')
        self.assertEqual(monday.meals[1].recipe.id, 'm0')

    def test_fewer_meals_cost_less(self):
        three = build_week_plan(FIXED_RECIPES, BIG_BUDGET).total_cost
        dinner_only = build_week_plan(FIXED_RECIPES, BIG_BUDGET, ('dinner',)).total_cost
        self.assertEqual(dinner_only, Decimal('9.10'))  # 7 cheapest mains: $1.00 to $1.60
        self.assertLess(dinner_only, three)

    def test_duplicate_recipe_ids_count_once(self):
        doubled = list(FIXED_RECIPES) * 2
        self.assertEqual(build_week_plan(doubled, BIG_BUDGET), build_week_plan(FIXED_RECIPES, BIG_BUDGET))

    def test_same_input_gives_the_same_plan_whatever_the_order(self):
        shuffled = list(FIXED_RECIPES)
        random.Random(7).shuffle(shuffled)
        for targets in (None, FIXED_WEEKLY_TARGETS):
            with self.subTest(with_targets=targets is not None):
                self.assertEqual(
                    build_week_plan(shuffled, BIG_BUDGET, targets=targets),
                    build_week_plan(FIXED_RECIPES, BIG_BUDGET, targets=targets),
                )


class BudgetEdgeCaseTests(SimpleTestCase):
    """Equivalence classes and boundaries for the budget ($28.70 is the lowest-cost week)."""

    def test_budget_exactly_at_the_lowest_cost_is_within_budget(self):
        plan = build_week_plan(FIXED_RECIPES, FIXED_LOWEST_WEEKLY_COST, targets=FIXED_WEEKLY_TARGETS)
        self.assertTrue(plan.within_budget)
        self.assertEqual(plan.over_budget_by, Decimal('0.00'))
        self.assertEqual(plan.total_cost, FIXED_LOWEST_WEEKLY_COST)  # no room to trade up

    def test_one_cent_under_the_lowest_cost_is_over_by_one_cent(self):
        plan = build_week_plan(FIXED_RECIPES, FIXED_LOWEST_WEEKLY_COST - Decimal('0.01'))
        self.assertFalse(plan.within_budget)
        self.assertEqual(plan.over_budget_by, Decimal('0.01'))

    def test_small_budget_gets_the_lowest_cost_plan_and_the_shortfall(self):
        plan = build_week_plan(FIXED_RECIPES, Decimal('10'), targets=FIXED_WEEKLY_TARGETS)
        self.assertEqual(plan.total_cost, FIXED_LOWEST_WEEKLY_COST)
        self.assertEqual(plan.over_budget_by, Decimal('18.70'))

    def test_one_cent_budget(self):
        plan = build_week_plan(FIXED_RECIPES, Decimal('0.01'))
        self.assertEqual(plan.over_budget_by, FIXED_LOWEST_WEEKLY_COST - Decimal('0.01'))
        self.assertEqual(len(recipe_ids(plan)), 21)

    def test_zero_budget_still_gets_a_full_week_and_is_over_by_its_whole_cost(self):
        plan = build_week_plan(FIXED_RECIPES, Decimal('0'))
        self.assertEqual(len(recipe_ids(plan)), 21)
        self.assertEqual(plan.over_budget_by, FIXED_LOWEST_WEEKLY_COST)

    def test_negative_budget_is_rejected(self):
        with self.assertRaises(ValueError):
            build_week_plan(FIXED_RECIPES, Decimal('-0.01'))

    def test_huge_budget_stays_within_budget_and_uses_targets(self):
        plan = build_week_plan(FIXED_RECIPES, Decimal('99999.99'), targets=FIXED_WEEKLY_TARGETS)
        self.assertTrue(plan.within_budget)
        self.assertGreater(plan.total_cost, FIXED_LOWEST_WEEKLY_COST)  # spends more to fit macros

    def test_budget_is_rounded_to_cents(self):
        self.assertEqual(build_week_plan(FIXED_RECIPES, Decimal('50.004')).budget, Decimal('50.00'))


class MacroTargetTests(SimpleTestCase):
    def test_meal_shares_add_up_to_the_whole_day(self):
        for meals in [MEALS, ('breakfast', 'dinner'), ('lunch', 'dinner'), ('dinner',)]:
            with self.subTest(meals=meals):
                self.assertAlmostEqual(sum(meal_shares(meals).values()), 1.0)
        self.assertEqual(meal_shares(('dinner',)), {'dinner': 1.0})
        self.assertEqual(meal_shares(MEALS), {'breakfast': 0.25, 'lunch': 0.35, 'dinner': 0.40})

    def test_each_meal_gets_its_share_of_the_days_targets(self):
        plan = build_week_plan(FIXED_RECIPES, BIG_BUDGET, ('breakfast', 'dinner'), FIXED_WEEKLY_TARGETS)
        monday = plan.days[0]
        self.assertEqual(monday.targets, FIXED_WEEKLY_TARGETS[0])
        self.assertEqual(monday.meals[0].targets, MacroTargets(58, 77, 15))  # 25 / (25 + 40) of the day
        self.assertEqual(monday.meals[1].targets, MacroTargets(92, 123, 25))

    def test_targets_pick_better_fitting_recipes_when_the_budget_allows(self):
        cheapest = build_week_plan(FIXED_RECIPES, Decimal('60'))
        fitted = build_week_plan(FIXED_RECIPES, Decimal('60'), targets=FIXED_WEEKLY_TARGETS)
        protein = sum(day.protein_g for day in fitted.days)
        self.assertGreater(protein, sum(day.protein_g for day in cheapest.days))
        self.assertLessEqual(fitted.total_cost, Decimal('60'))
        self.assertTrue(fitted.uses_macro_targets)

    def test_wrong_number_of_daily_targets_is_rejected(self):
        with self.assertRaises(ValueError):
            build_week_plan(FIXED_RECIPES, BIG_BUDGET, targets=FIXED_WEEKLY_TARGETS[:6])

    def test_zero_targets_do_not_divide_by_zero(self):
        plan = build_week_plan(FIXED_RECIPES, BIG_BUDGET, targets=[MacroTargets(0, 0, 0)] * 7)
        self.assertEqual(len(plan.days), 7)


class BruteForceTests(SimpleTestCase):
    """Check the greedy planner against exhaustive search on small random catalogs (dinner only, 7 meals)."""

    def all_weeks(self, mains):
        cap = -(-7 // len(mains))  # all different when possible, else as even as possible
        for week in itertools.product(mains, repeat=7):
            if max(Counter(r.id for r in week).values()) <= cap:
                yield week

    def test_lowest_cost_is_the_true_minimum_and_targets_never_break_a_feasible_budget(self):
        rng = random.Random(2026)
        for trial in range(20):
            mains = [
                recipe(f'r{i}', f'{rng.randint(50, 400) / 100:.2f}', protein=rng.randint(5, 50))
                for i in range(rng.randint(2, 4))
            ]
            minimum = min(sum(r.cost_per_serving for r in week) for week in self.all_weeks(mains))
            budget = minimum + Decimal(rng.randint(0, 2000)) / 100
            with self.subTest(trial=trial):
                self.assertEqual(build_week_plan(mains, Decimal('0'), ('dinner',)).total_cost, minimum)
                fitted = build_week_plan(mains, budget, ('dinner',), FIXED_WEEKLY_TARGETS)
                self.assertLessEqual(fitted.total_cost, budget)


class DomainTests(SimpleTestCase):
    def test_recipe_rejects_bad_values(self):
        bad: list[dict[str, Any]] = [
            {'title': ' '},
            {'course': 'dessert'},
            {'cost_per_serving': Decimal('0')},
            {'protein_g': -1},
            {'carbs_g': float('nan')},
            {'fat_g': float('inf')},
        ]
        base: dict[str, Any] = {
            'id': 'x',
            'title': 'X',
            'course': 'main',
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

    def test_day_totals_add_up_its_meals(self):
        day = PlannedDay(
            'Monday',
            meals=(
                PlannedMeal('breakfast', FIXED_BREAKFASTS[0]),  # $0.50, 10 g protein
                PlannedMeal('dinner', FIXED_MAINS[0]),  # $1.00, 15 g protein
            ),
        )
        self.assertEqual((day.cost, day.protein_g, day.carbs_g, day.fat_g), (Decimal('1.50'), 25, 95, 20))
        self.assertIsNone(day.meal('lunch'))
        self.assertEqual(day.meal('dinner'), day.meals[1])

    def test_plan_finds_days_by_name_case_insensitively(self):
        plan = build_week_plan(FIXED_RECIPES, BIG_BUDGET)
        self.assertEqual(plan.day('wednesday'), plan.days[2])
        self.assertIsNone(plan.day('funday'))
