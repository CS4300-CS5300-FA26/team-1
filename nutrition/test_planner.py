"""Unit tests for the meal plan's pure parts: value types, price averaging, the published targets, and the planner."""

import itertools
from collections import Counter
from decimal import Decimal

from django.test import SimpleTestCase

from . import pricing
from .domain import (
    Ingredient,
    MacroTargets,
    Nutrients,
    PlannedMeal,
    PriceEstimate,
    Recipe,
    RecipeLine,
    WeekPlan,
    purchase_cost,
)
from .planner import NoRecipesError, build_week_plan, covers_meals, recipes_with_prices
from .pricing import PriceQuote
from .targets import DAILY_VALUES, published_weekly_targets
from .testing import (
    BEANS,
    CHICKEN,
    EGGS,
    FIXED_RECIPES,
    FIXED_WEEKLY_TARGETS,
    FLAT_QUOTE,
    MILK,
    OATS,
    RICE,
    ingredient,
    recipe,
)

ALL_MEALS = ('breakfast', 'lunch', 'dinner')


def flat_prices(recipes=FIXED_RECIPES):
    ingredients = list({k: i for r in recipes for k, i in r.ingredients.items()}.values())
    return pricing.estimates(ingredients, {i.key: [FLAT_QUOTE] for i in ingredients})


class ValueTypeTests(SimpleTestCase):
    def test_nutrients_add_and_scale_and_reject_bad_values(self):
        total = Nutrients(100, 10, 5, 2) + Nutrients(50, 1, 1, 1).scaled(2)
        self.assertEqual(total, Nutrients(200, 12, 7, 4))
        for bad in ((-1, 0, 0, 0), (float('nan'), 0, 0, 0), (0, float('inf'), 0, 0)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                Nutrients(*bad)

    def test_macro_targets_are_positive_and_imply_energy(self):
        self.assertEqual(MacroTargets(50, 275, 78).kcal, 2002)
        with self.assertRaises(ValueError):
            MacroTargets(0, 100, 50)

    def test_recipe_nutrients_come_from_line_weights(self):
        self.assertEqual(RecipeLine('x', OATS, 50).nutrients, OATS.per_100g.scaled(0.5))
        porridge = FIXED_RECIPES[0]  # 80 g oats, 250 g milk
        expected = OATS.per_100g.scaled(0.8) + MILK.per_100g.scaled(2.5)
        self.assertAlmostEqual(porridge.nutrients.protein_g, expected.protein_g)
        self.assertEqual(porridge.grams_by_ingredient(), {'oats': 80, 'milk': 250})

    def test_lines_and_recipes_are_validated(self):
        with self.assertRaises(ValueError):
            RecipeLine('x', OATS, None)
        with self.assertRaises(ValueError):
            RecipeLine('x', None, 10)
        with self.assertRaises(ValueError):
            RecipeLine('x', OATS, 0)
        with self.assertRaises(ValueError):
            Recipe('r', 'R', 'dessert', (RecipeLine('x', OATS, 10),))
        with self.assertRaises(ValueError):
            Recipe('r', 'R', 'main', (RecipeLine('Salt'),))

    def test_planned_meals_scale_by_servings(self):
        meal = PlannedMeal(0, 'breakfast', FIXED_RECIPES[0], Decimal('1.5'))
        self.assertAlmostEqual(meal.nutrients.kcal, FIXED_RECIPES[0].nutrients.kcal * 1.5)
        self.assertEqual([grams for _, grams in meal.lines()], [120, 375, None])

    def test_week_plan_needs_seven_targets(self):
        with self.assertRaises(ValueError):
            WeekPlan(meals=(), daily_targets=(DAILY_VALUES,))


class PricingTests(SimpleTestCase):
    def test_whole_packages_are_bought(self):
        price = PriceEstimate(price_per_gram=Decimal('0.004'), package_grams=Decimal('500'), quote_count=1)
        self.assertEqual(price.package_price, Decimal('2.000'))
        self.assertEqual([price.packages_for(g) for g in (0, 1, 500, 500.0000001, 501)], [0, 1, 1, 1, 2])
        self.assertEqual(price.cost_for(750), Decimal('4.000'))

    def test_purchase_cost_needs_every_price(self):
        price = PriceEstimate(Decimal('0.004'), Decimal('500'), 1)
        self.assertEqual(purchase_cost({'a': 600, 'b': 10}, {'a': price, 'b': price}), Decimal('6.00'))
        self.assertIsNone(purchase_cost({'a': 600, 'c': 1}, {'a': price}))

    def test_units_are_converted_to_grams(self):
        milk = ingredient('milk', 3, 5, 3, grams_per_ml=1.03)
        eggs = ingredient('eggs', 13, 1, 10, grams_per_each=50)
        cases = [
            (PriceQuote(Decimal('1'), Decimal('1'), 'lb'), OATS, Decimal('453.59237')),
            (PriceQuote(Decimal('1'), Decimal('2'), 'kg'), OATS, Decimal('2000')),
            (PriceQuote(Decimal('1'), Decimal('16'), 'OZ'), OATS, Decimal('453.59237')),
            (PriceQuote(Decimal('4'), Decimal('1'), 'gal'), milk, Decimal('3785.411784') * Decimal('1.03')),
            (PriceQuote(Decimal('3'), Decimal('12'), 'each'), eggs, Decimal('600')),
        ]
        for quote, food, grams in cases:
            with self.subTest(unit=quote.unit):
                self.assertEqual(pricing.quote_grams(quote, food), grams)

    def test_unconvertible_quotes_are_skipped_and_logged(self):
        quotes = [PriceQuote(Decimal('3'), Decimal('12'), 'each'), PriceQuote(Decimal('1'), Decimal('1'), 'gal')]
        with self.assertLogs('nutrition.pricing', level='WARNING'):
            self.assertIsNone(pricing.estimate(OATS, quotes))  # oats have no weight each or density
        with self.assertLogs('nutrition.pricing', level='WARNING'):
            self.assertIsNone(pricing.estimate(OATS, [PriceQuote(Decimal('0'), Decimal('1'), 'lb')]))

    def test_estimate_averages_price_per_gram_and_package_size(self):
        quotes = [PriceQuote(Decimal('2.00'), Decimal('500'), 'g'), PriceQuote(Decimal('6.00'), Decimal('1'), 'kg')]
        estimate = pricing.estimate(OATS, quotes)
        assert estimate is not None
        self.assertEqual(estimate.price_per_gram, Decimal('0.005'))  # mean of 0.004 and 0.006
        self.assertEqual(estimate.package_grams, Decimal('750'))
        self.assertEqual(estimate.quote_count, 2)

    def test_estimates_cover_only_ingredients_with_usable_quotes(self):
        found = pricing.estimates([OATS, EGGS], {'oats': [FLAT_QUOTE]})
        self.assertEqual(set(found), {'oats'})


class PublishedTargetsTests(SimpleTestCase):
    def test_fda_daily_values_for_every_day(self):
        self.assertEqual(DAILY_VALUES, MacroTargets(protein_g=50, carbs_g=275, fat_g=78))
        self.assertEqual(published_weekly_targets(), (DAILY_VALUES,) * 7)


class PlannerRuleTests(SimpleTestCase):
    def plan(self, **kwargs):
        defaults = {'recipes': FIXED_RECIPES, 'meals': ALL_MEALS, 'daily_targets': FIXED_WEEKLY_TARGETS}
        return build_week_plan(**{**defaults, **kwargs})

    def test_every_planned_meal_is_filled_from_the_right_course(self):
        plan = self.plan().plan
        self.assertEqual(len(plan.meals), 21)
        for meal in plan.meals:
            self.assertEqual(meal.recipe.course, 'breakfast' if meal.meal == 'breakfast' else 'main')
            self.assertIn(meal.servings, (Decimal('1'), Decimal('1.5'), Decimal('2')))

    def test_variety_at_most_twice_a_week_and_never_twice_a_day(self):
        plan = self.plan(seed=3).plan
        self.assertLessEqual(max(Counter(m.recipe.id for m in plan.meals).values()), 2)
        for day in range(7):
            ids = [m.recipe.id for m in plan.day_meals(day)]
            self.assertEqual(len(ids), len(set(ids)))

    def test_limits_loosen_when_there_are_too_few_recipes(self):
        few = [FIXED_RECIPES[0], FIXED_RECIPES[4]]  # one breakfast, one main
        plan = self.plan(recipes=few).plan
        self.assertEqual({m.recipe.id for m in plan.meals}, {'oat-porridge', 'chicken-rice'})

    def test_only_the_chosen_meals_are_planned(self):
        plan = self.plan(meals=('dinner', 'breakfast')).plan
        self.assertEqual(plan.meal_keys, ('breakfast', 'dinner'))
        self.assertEqual(len(plan.meals), 14)

    def test_the_same_seed_gives_the_same_plan(self):
        self.assertEqual(self.plan(seed=5).plan, self.plan(seed=5).plan)

    def test_days_get_close_to_their_targets(self):
        plan = self.plan().plan
        for day in range(7):
            target, actual = FIXED_WEEKLY_TARGETS[day], plan.day_nutrients(day)
            with self.subTest(day=day):
                self.assertLess(abs(actual.protein_g - target.protein_g) / target.protein_g, 0.5)

    def test_avoided_recipes_are_used_only_when_needed(self):
        # Dinner only: 7 meals from 7 mains, so there is room to avoid what the first plan used.
        first = self.plan(seed=1, meals=('dinner',)).plan
        second = self.plan(seed=1, meals=('dinner',), avoid=first.recipe_ids()).plan
        self.assertLess(len(first.recipe_ids() & second.recipe_ids()), len(first.recipe_ids()))

    def test_bad_input_is_rejected(self):
        with self.assertRaises(ValueError):
            self.plan(meals=())
        with self.assertRaises(ValueError):
            self.plan(daily_targets=FIXED_WEEKLY_TARGETS[:6])
        with self.assertRaises(NoRecipesError):
            self.plan(recipes=[r for r in FIXED_RECIPES if r.course == 'main'])


class PlannerBudgetTests(SimpleTestCase):
    def plan(self, budget, recipes=FIXED_RECIPES, **kwargs):
        return build_week_plan(
            recipes, ALL_MEALS, FIXED_WEEKLY_TARGETS, prices=flat_prices(recipes), budget=budget, **kwargs
        )

    def test_without_prices_there_is_no_cost_and_the_budget_is_ignored(self):
        result = build_week_plan(FIXED_RECIPES, ALL_MEALS, FIXED_WEEKLY_TARGETS, budget=Decimal('1'))
        self.assertIsNone(result.cost)
        self.assertIsNone(result.budget)
        self.assertIsNone(result.over_budget_by)

    def test_cost_is_whole_packages_of_the_weeks_ingredients(self):
        result = self.plan(None)
        packages = sum(-(-int(grams * 1000) // 500_000) for grams in result.plan.grams_needed().values())
        self.assertEqual(result.cost, Decimal('2.00') * packages)

    def test_a_feasible_budget_is_kept(self):
        cheapest = self.plan(Decimal('0')).cost
        assert cheapest is not None
        for budget in (cheapest, cheapest + 4, Decimal('500')):
            with self.subTest(budget=budget):
                result = self.plan(budget)
                assert result.cost is not None
                self.assertLessEqual(result.cost, budget)
                self.assertEqual(result.over_budget_by, Decimal('0.00'))

    def test_a_budget_too_low_gets_the_cheapest_plan_and_how_far_over(self):
        result = self.plan(Decimal('10'))
        assert result.cost is not None and result.over_budget_by is not None
        self.assertEqual(result.over_budget_by, result.cost - Decimal('10'))
        self.assertEqual(result.cost, self.plan(Decimal('0')).cost)

    def test_the_cheapest_plan_does_not_depend_on_the_seed(self):
        # Regression: single-meal swaps used to stall just above a package boundary (1,450 g of milk is three 500 g
        # packages; no one swap saved the 450 g needed), so some seeds found a $30 week when $28 existed.
        costs = {self.plan(Decimal('0'), seed=seed).cost for seed in range(60)}
        self.assertEqual(costs, {Decimal('28.00')})

    def test_the_cheapest_plan_matches_a_brute_force_search(self):
        # Small enough to check every possibility: dinner only, one serving, any recipe any number of times.
        a = recipe('a', 'main', (RICE, 400))
        b = recipe('b', 'main', (RICE, 100), (BEANS, 100))
        c = recipe('c', 'main', (CHICKEN, 300))
        recipes = (a, b, c)
        prices = flat_prices(recipes)
        result = build_week_plan(
            recipes,
            ('dinner',),
            FIXED_WEEKLY_TARGETS,
            prices=prices,
            budget=Decimal('0'),
            portions=(Decimal(1),),
            max_repeats=7,
        )

        def cost_of(week) -> Decimal:
            meals = tuple(PlannedMeal(day, 'dinner', r) for day, r in enumerate(week))
            cost = purchase_cost(WeekPlan(meals, FIXED_WEEKLY_TARGETS, ('dinner',)).grams_needed(), prices)
            assert cost is not None
            return cost

        self.assertEqual(result.cost, min(cost_of(week) for week in itertools.product(recipes, repeat=7)))

    def test_shared_ingredients_make_a_cheaper_week(self):
        # Two mains share rice; the third needs its own two ingredients. Dinner only, so two packages beat three.
        shared_1 = recipe('shared-1', 'main', (RICE, 60), (CHICKEN, 60))
        shared_2 = recipe('shared-2', 'main', (RICE, 60), (CHICKEN, 50))
        alone = recipe('alone', 'main', (BEANS, 60), (EGGS, 60))
        result = build_week_plan(
            (shared_1, shared_2, alone),
            ('dinner',),
            FIXED_WEEKLY_TARGETS,
            prices=flat_prices((shared_1, shared_2, alone)),
            budget=Decimal('0'),
            max_repeats=4,
        )
        self.assertNotIn('alone', result.plan.recipe_ids())

    def test_only_fully_priced_recipes_are_planned_with_prices(self):
        prices = {k: v for k, v in flat_prices().items() if k != 'tuna'}
        priced = recipes_with_prices(FIXED_RECIPES, prices)
        self.assertNotIn('tuna-pasta', {r.id for r in priced})
        result = build_week_plan(FIXED_RECIPES, ALL_MEALS, FIXED_WEEKLY_TARGETS, prices=prices, budget=Decimal('100'))
        self.assertFalse({'tuna-pasta', 'tuna-rice'} & result.plan.recipe_ids())

    def test_covers_meals(self):
        breakfasts = [r for r in FIXED_RECIPES if r.course == 'breakfast']
        self.assertTrue(covers_meals(breakfasts, ('breakfast',)))
        self.assertFalse(covers_meals(breakfasts, ('breakfast', 'dinner')))


class IngredientTypeTests(SimpleTestCase):
    def test_ingredient_holds_optional_densities(self):
        food = Ingredient('x', 'X', Nutrients(), fdc_id=1, grams_per_ml=1.0)
        self.assertIsNone(food.grams_per_each)
