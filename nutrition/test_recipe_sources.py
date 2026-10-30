"""Tests for the recipe source adapters. Spoonacular is faked at the HTTP layer; nothing hits the network."""

import io
import json
import urllib.error
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from .ports import RecipeServiceUnavailable, recipe_source
from .recipe_sources import SpoonacularRecipeSource, StarterCatalogSource


def spoonacular_item(id=1, price=180.0, protein=42.0, image='https://img.spoonacular.com/recipes/1-312x231.jpg'):
    """One complexSearch result with addRecipeNutrition=true (only the fields we read)."""
    return {
        'id': id,
        'title': f'Chicken rice bowl {id}',
        'image': image,
        'sourceUrl': 'https://example.com/chicken-rice-bowl',
        'servings': 4,
        'pricePerServing': price,
        'nutrition': {
            'nutrients': [
                {'name': 'Calories', 'amount': 520.0, 'unit': 'kcal'},
                {'name': 'Protein', 'amount': protein, 'unit': 'g'},
                {'name': 'Carbohydrates', 'amount': 55.0, 'unit': 'g'},
                {'name': 'Fat', 'amount': 9.0, 'unit': 'g'},
            ]
        },
    }


def http_response(payload):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    response = mock.MagicMock()
    response.__enter__.return_value = io.BytesIO(body)
    return response


@override_settings(SPOONACULAR_API_KEY='test-key-not-real')
class SpoonacularRecipeSourceTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        patcher = mock.patch('nutrition.recipe_sources.urllib.request.urlopen')
        self.urlopen = patcher.start()
        self.addCleanup(patcher.stop)

    def fetch(self):
        return SpoonacularRecipeSource().budget_recipes()

    def test_parses_price_in_cents_and_macros_per_serving(self):
        self.urlopen.return_value = http_response({'results': [spoonacular_item(price=163.15)]})
        (recipe,) = self.fetch()
        self.assertEqual(recipe.id, 'spoonacular-1')
        self.assertEqual(recipe.cost_per_serving, Decimal('1.63'))
        self.assertEqual((recipe.protein_g, recipe.carbs_g, recipe.fat_g), (42.0, 55.0, 9.0))
        self.assertEqual(recipe.image_url, 'https://img.spoonacular.com/recipes/1-312x231.jpg')

    def test_api_key_is_sent_in_a_header_and_never_in_the_url(self):
        self.urlopen.return_value = http_response({'results': [spoonacular_item()]})
        self.fetch()
        request = self.urlopen.call_args.args[0]
        self.assertEqual(request.get_header('X-api-key'), 'test-key-not-real')
        self.assertNotIn('test-key-not-real', request.full_url)
        self.assertTrue(request.full_url.startswith('https://api.spoonacular.com/'))
        self.assertIn('sort=price', request.full_url)
        self.assertIsNotNone(self.urlopen.call_args.kwargs['timeout'])

    def test_results_are_cached_so_the_api_is_called_once(self):
        self.urlopen.return_value = http_response({'results': [spoonacular_item()]})
        self.fetch()
        self.fetch()
        self.assertEqual(self.urlopen.call_count, 1)

    def test_malformed_items_are_skipped(self):
        items = [
            spoonacular_item(id=1),
            {'id': 2, 'title': 'No nutrition', 'pricePerServing': 100},
            spoonacular_item(id=3, price=-5),
            spoonacular_item(id=4, price='NaN'),
            {**spoonacular_item(id=5), 'title': ''},
        ]
        self.urlopen.return_value = http_response({'results': items})
        self.assertEqual([r.id for r in self.fetch()], ['spoonacular-1'])

    def test_nutrients_not_in_grams_are_rejected(self):
        item = spoonacular_item()
        item['nutrition']['nutrients'][1]['unit'] = 'mg'
        self.urlopen.return_value = http_response({'results': [item]})
        with self.assertRaises(RecipeServiceUnavailable):
            self.fetch()

    def test_untrusted_image_and_source_urls_are_dropped(self):
        item = {**spoonacular_item(image='http://img.spoonacular.com/x.jpg'), 'sourceUrl': 'javascript:alert(1)'}
        self.urlopen.return_value = http_response(
            {'results': [item, spoonacular_item(id=2, image='https://evil.example/x.jpg')]}
        )
        recipes = self.fetch()
        self.assertEqual([r.image_url for r in recipes], ['', ''])
        self.assertEqual(recipes[0].source_url, '')

    def test_failures_become_unavailable(self):
        failures = {
            'quota used up': urllib.error.HTTPError('u', 402, 'Payment Required', {}, None),  # type: ignore[arg-type]
            'bad key': urllib.error.HTTPError('u', 401, 'Unauthorized', {}, None),  # type: ignore[arg-type]
            'network down': urllib.error.URLError('connection refused'),
            'timeout': TimeoutError(),
        }
        for name, error in failures.items():
            with self.subTest(name):
                cache.clear()
                self.urlopen.side_effect = error
                with self.assertRaises(RecipeServiceUnavailable):
                    self.fetch()

    def test_bad_payloads_become_unavailable(self):
        payloads = {
            'not json': b'<html>oops</html>',
            'no results key': {'status': 'failure'},
            'results not a list': {'results': {'id': 1}},
            'no usable recipes': {'results': []},
            'too large': b'{"results": [' + b' ' * (SpoonacularRecipeSource.MAX_RESPONSE_BYTES + 1) + b']}',
        }
        for name, payload in payloads.items():
            with self.subTest(name):
                cache.clear()
                self.urlopen.return_value = http_response(payload)
                with self.assertRaises(RecipeServiceUnavailable):
                    self.fetch()

    def test_a_failure_is_remembered_briefly_so_the_api_is_not_hammered(self):
        self.urlopen.side_effect = urllib.error.URLError('down')
        with self.assertRaises(RecipeServiceUnavailable):
            self.fetch()
        with self.assertRaises(RecipeServiceUnavailable):
            self.fetch()
        self.assertEqual(self.urlopen.call_count, 1)

    @override_settings(SPOONACULAR_API_KEY='')
    def test_missing_api_key_is_unavailable_without_a_request(self):
        with self.assertLogs('nutrition.recipe_sources', level='ERROR'), self.assertRaises(RecipeServiceUnavailable):
            self.fetch()
        self.urlopen.assert_not_called()

    def test_api_key_never_appears_in_logs(self):
        self.urlopen.side_effect = urllib.error.HTTPError('u', 401, 'Unauthorized', {}, None)  # type: ignore[arg-type]
        with (
            self.assertLogs('nutrition.recipe_sources', level='WARNING') as logs,
            self.assertRaises(RecipeServiceUnavailable),
        ):
            self.fetch()
        self.assertNotIn('test-key-not-real', '\n'.join(logs.output))


class StarterCatalogSourceTests(SimpleTestCase):
    def test_catalog_has_enough_valid_recipes_for_a_varied_week(self):
        recipes = StarterCatalogSource().budget_recipes()
        self.assertGreaterEqual(len({r.id for r in recipes}), 7)
        self.assertTrue(all(r.cost_per_serving > 0 for r in recipes))

    def test_unreadable_catalog_is_unavailable(self):
        with (
            mock.patch('nutrition.recipe_sources.STARTER_CATALOG', Path('does-not-exist.json')),
            self.assertLogs('nutrition.recipe_sources', level='ERROR'),
            self.assertRaises(RecipeServiceUnavailable),
        ):
            StarterCatalogSource().budget_recipes()


class SourceSelectionTests(SimpleTestCase):
    def test_default_source_is_the_starter_catalog(self):
        self.assertIsInstance(recipe_source(), StarterCatalogSource)

    @override_settings(NUTRITION_RECIPE_SOURCE='nutrition.recipe_sources.SpoonacularRecipeSource')
    def test_source_is_chosen_by_setting(self):
        self.assertIsInstance(recipe_source(), SpoonacularRecipeSource)
