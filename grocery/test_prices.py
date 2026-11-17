"""Tests for D-6's price source and its data file (grocery/data/price_quotes.json, ADR-009)."""

import json
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import UserProfile
from nutrition import pricing
from nutrition.domain import Ingredient, Nutrients
from nutrition.recipe_sources import CatalogRecipeSource
from nutrition.services import PRICES_CONNECTED

from .prices import DATA_FILE, PriceFileError, StoredGroceryPrices, read_quotes

User = get_user_model()
PASSWORD = 'Tr4ining-Plan-2026!'

GOOD = {'price': '2.00', 'quantity': '1', 'unit': 'lb', 'source': 'A grocer', 'observed_on': '2026-09-01'}


def read_data(data) -> dict:
    """Write `data` as a price file and read it back through `read_quotes`."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'quotes.json'
        path.write_text(data if isinstance(data, str) else json.dumps(data), encoding='utf-8')
        return read_quotes(path)


class PriceFileFormatTests(SimpleTestCase):
    def test_a_valid_file_is_read_into_quotes(self):
        quotes = read_data({'quotes': {'white-rice': [GOOD]}})
        quote = quotes['white-rice'][0]
        self.assertEqual(
            (quote.price, quote.quantity, quote.unit, quote.source, quote.observed_on),
            (Decimal('2.00'), Decimal('1'), 'lb', 'A grocer', date(2026, 9, 1)),
        )

    def test_a_bad_file_names_the_entry_at_fault(self):
        cases = {
            'a unit that is not allowed': ({**GOOD, 'unit': 'bushel'}, 'unit'),
            'no source': ({**GOOD, 'source': ' '}, 'needs a source'),
            'a price of zero': ({**GOOD, 'price': '0'}, 'greater than zero'),
            'a negative quantity': ({**GOOD, 'quantity': '-1'}, 'greater than zero'),
            'a price that is not a number': ({**GOOD, 'price': 'cheap'}, 'not a number'),
            'a price that is not finite': ({**GOOD, 'price': 'NaN'}, 'greater than zero'),
            'a missing date': ({k: v for k, v in GOOD.items() if k != 'observed_on'}, 'observed_on'),
            'a date that is not a date': ({**GOOD, 'observed_on': 'last week'}, 'observed_on'),
        }
        for name, (entry, message) in cases.items():
            with self.subTest(name), self.assertRaisesMessage(PriceFileError, message):
                read_data({'quotes': {'white-rice': [entry]}})

    def test_an_ingredient_with_no_quotes_is_an_error(self):
        with self.assertRaisesMessage(PriceFileError, 'has no quotes'):
            read_data({'quotes': {'white-rice': []}})

    def test_a_file_that_is_not_a_price_file_is_an_error(self):
        for name, text in {'not json': 'nope', 'no quotes key': '{"other": 1}', 'a list': '[]'}.items():
            with self.subTest(name), self.assertRaisesMessage(PriceFileError, 'Could not read the price file'):
                read_data(text)

    def test_a_missing_file_is_an_error(self):
        with self.assertRaisesMessage(PriceFileError, 'Could not read the price file'):
            read_quotes(Path('/nonexistent/quotes.json'))


class ShippedPriceFileTests(TestCase):
    """The data file in the repo: every quote is valid, cited, and usable for the ingredient it prices."""

    quotes: dict[str, tuple[pricing.PriceQuote, ...]]
    catalog: dict[str, Ingredient]

    @classmethod
    def setUpTestData(cls):
        cls.quotes = read_quotes(DATA_FILE)
        cls.catalog = {i.key: i for r in CatalogRecipeSource().recipes() for i in r.ingredients.values()}

    def test_the_file_is_valid_and_not_empty(self):
        self.assertGreater(len(self.quotes), 0)

    def test_every_quote_is_for_an_ingredient_in_the_recipe_catalog(self):
        # A typo in a key would silently price nothing.
        self.assertEqual(set(self.quotes) - set(self.catalog), set())

    def test_every_quote_can_be_converted_to_grams_for_its_ingredient(self):
        for key, quotes in self.quotes.items():
            with self.subTest(key):
                for quote in quotes:
                    grams = pricing.quote_grams(quote, self.catalog[key])
                    self.assertIsNotNone(grams, f'{key}: {quote.unit} needs a density or weight each in the catalog.')

    def test_every_quote_has_a_source_and_a_date(self):
        for key, quotes in self.quotes.items():
            for quote in quotes:
                with self.subTest(key):
                    self.assertTrue(quote.source)
                    self.assertIsNotNone(quote.observed_on)

    def test_the_prices_are_plausible_grocery_prices(self):
        # A guard against a slipped decimal point: no ingredient costs under a cent or over $50 a gram-package.
        for key, quotes in self.quotes.items():
            for quote in quotes:
                with self.subTest(key):
                    grams = pricing.quote_grams(quote, self.catalog[key])
                    assert grams is not None
                    per_gram = quote.price / grams
                    self.assertGreater(per_gram, Decimal('0.0005'))  # about $0.23 a pound
                    self.assertLess(per_gram, Decimal('0.05'))  # about $22 a pound


class StoredGroceryPricesTests(SimpleTestCase):
    def setUp(self):
        self.rice = Ingredient('white-rice', 'White rice', Nutrients(), grams_per_ml=0.782)
        self.unknown = Ingredient('dragon-fruit', 'Dragon fruit', Nutrients())

    def test_it_returns_quotes_only_for_ingredients_it_knows(self):
        quotes = StoredGroceryPrices().quotes([self.rice, self.unknown])
        self.assertEqual(set(quotes), {'white-rice'})
        self.assertTrue(all(isinstance(q, pricing.PriceQuote) for q in quotes['white-rice']))

    def test_the_meal_plan_can_average_its_quotes_into_a_price(self):
        estimates = pricing.estimates([self.rice], StoredGroceryPrices().quotes([self.rice]))
        # $1.118 a pound
        self.assertAlmostEqual(float(estimates['white-rice'].price_per_gram * pricing.GRAMS_PER_UNIT['lb']), 1.118, 6)

    def test_it_returns_nothing_when_asked_about_nothing(self):
        self.assertEqual(dict(StoredGroceryPrices().quotes([])), {})


class RealWiringTests(TestCase):
    """With D-6 connected to the real catalog and the real price file, the meal plan and the list are costed."""

    def setUp(self):
        self.user = User.objects.create_user('wired', 'wired@example.com', PASSWORD)
        self.profile = UserProfile.objects.create(
            user=self.user,
            onboarding_completed=True,
            weekly_food_budget=Decimal('500.00'),
            planned_meals=['breakfast', 'lunch', 'dinner'],
        )
        self.client.force_login(self.user)

    def test_the_meal_plan_is_costed_with_the_real_prices(self):
        response = self.client.get(reverse('meal_plan'))
        result = response.context['result']
        self.assertEqual(result.prices, PRICES_CONNECTED)
        self.assertIsNotNone(result.cost)
        self.assertGreater(result.cost, 0)
        self.assertTrue(result.budget_applied)
        self.assertContains(response, f'Est. ${result.cost}')
        self.assertNotContains(response, 'only available for some ingredients')

    def test_a_low_budget_shows_the_over_budget_notice(self):
        self.profile.weekly_food_budget = Decimal('5.00')
        self.profile.save()
        response = self.client.get(reverse('meal_plan'))
        result = response.context['result']
        self.assertGreater(result.over_budget_by, 0)
        text = ' '.join(response.content.decode().split())
        self.assertIn(f'${result.over_budget_by} over your $5.00 budget.', text)

    def test_the_priced_recipes_still_make_a_varied_week(self):
        # Only fully priced recipes are planned, so the real price file has to cover enough of the catalog.
        plan = self.client.get(reverse('meal_plan')).context['result'].plan
        self.assertGreaterEqual(len(plan.recipe_ids()), 6)

    def test_every_planned_recipe_is_fully_priced(self):
        plan = self.client.get(reverse('meal_plan')).context['result'].plan
        priced = set(read_quotes(DATA_FILE))
        for meal in plan.meals:
            with self.subTest(meal.recipe.id):
                self.assertLessEqual(set(meal.recipe.grams_by_ingredient()), priced)

    def test_the_grocery_list_has_a_total_that_matches_the_meal_plan(self):
        result = self.client.get(reverse('meal_plan')).context['result']  # D-5 stores this week's plan
        response = self.client.get(reverse('grocery_list'))
        groceries = response.context['groceries']
        self.assertGreater(len(groceries.items), 5)
        self.assertEqual(groceries.unpriced, 0)
        self.assertEqual(groceries.total, result.cost)
        self.assertContains(response, f'Est. ${groceries.total}')
        self.assertNotContains(response, 'No price yet')
