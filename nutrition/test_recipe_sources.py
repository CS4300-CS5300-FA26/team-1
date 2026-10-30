"""Tests for the recipe source adapters and their shared database cache.

Spoonacular is faked at the HTTP layer; nothing hits the network.
"""

import io
import json
import urllib.error
import urllib.parse
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from . import cache
from .models import RecipeCacheEntry
from .ports import RecipeServiceUnavailable, recipe_source
from .recipe_sources import SpoonacularRecipeSource, StarterCatalogSource
from .testing import recipe

API_KEY = 'test-key-not-real'


def search_item(id=1, price=180.0, protein=42.0, image='https://img.spoonacular.com/recipes/1-312x231.jpg'):
    """One complexSearch result with addRecipeNutrition=true (only the fields we read)."""
    return {
        'id': id,
        'title': f'Chicken rice bowl {id}',
        'image': image,
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


def details_payload(**overrides):
    """GET /recipes/{id}/information (only the fields we read)."""
    return {
        'readyInMinutes': 25,
        'sourceUrl': 'https://example.com/chicken-rice-bowl',
        'extendedIngredients': [
            {'name': 'chicken thighs', 'original': '1 lb chicken thighs'},
            {'name': 'rice', 'original': '2 cups cooked rice'},
        ],
        'analyzedInstructions': [
            {
                'name': '',
                'steps': [{'number': 1, 'step': 'Cook the chicken.'}, {'number': 2, 'step': 'Serve over rice.'}],
            }
        ],
        'instructions': '<ol><li><script>alert(1)</script></li></ol>',
        **overrides,
    }


def http_response(payload):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    response = mock.MagicMock()
    response.__enter__.return_value = io.BytesIO(body)
    return response


def fake_api(breakfast=None, main=None, details=None):
    """A urlopen side effect that answers each endpoint with the given payload (or exception)."""

    def respond(request, timeout):
        url = urllib.parse.urlsplit(request.full_url)
        query = dict(urllib.parse.parse_qsl(url.query))
        if url.path == '/recipes/complexSearch':
            payload = breakfast if query['type'] == 'breakfast' else main
        else:
            payload = details
        if isinstance(payload, BaseException):
            raise payload
        return http_response(payload)

    return respond


@override_settings(SPOONACULAR_API_KEY=API_KEY)
class SpoonacularSearchTests(TestCase):
    def setUp(self):
        patcher = mock.patch('nutrition.recipe_sources.urllib.request.urlopen')
        self.urlopen = patcher.start()
        self.addCleanup(patcher.stop)

    def use_api(self, breakfast=None, main=None, details=None):
        breakfast = breakfast if breakfast is not None else {'results': [search_item(id=10, price=95)]}
        main = main if main is not None else {'results': [search_item(id=20, price=163.15)]}
        self.urlopen.side_effect = fake_api(breakfast, main, details or details_payload())

    def fetch(self):
        return SpoonacularRecipeSource().budget_recipes()

    def test_breakfast_and_main_searches_become_courses_with_prices_in_cents(self):
        self.use_api()
        recipes = {r.id: r for r in self.fetch()}
        self.assertEqual(recipes['spoonacular-10'].course, 'breakfast')
        self.assertEqual(recipes['spoonacular-20'].course, 'main')
        self.assertEqual(recipes['spoonacular-20'].cost_per_serving, Decimal('1.63'))
        self.assertEqual(recipes['spoonacular-20'].protein_g, 42.0)
        self.assertEqual(recipes['spoonacular-20'].image_url, 'https://img.spoonacular.com/recipes/1-312x231.jpg')

    def test_a_dish_returned_by_both_searches_is_kept_once(self):
        self.use_api(
            breakfast={'results': [search_item(id=5)]}, main={'results': [search_item(id=5), search_item(id=6)]}
        )
        recipes = self.fetch()
        self.assertEqual(sorted(r.id for r in recipes), ['spoonacular-5', 'spoonacular-6'])
        self.assertEqual(next(r for r in recipes if r.id == 'spoonacular-5').course, 'breakfast')

    def test_api_key_is_sent_in_a_header_and_never_in_the_url(self):
        self.use_api()
        self.fetch()
        for call in self.urlopen.call_args_list:
            request = call.args[0]
            self.assertEqual(request.get_header('X-api-key'), API_KEY)
            self.assertNotIn(API_KEY, request.full_url)
            self.assertTrue(request.full_url.startswith('https://api.spoonacular.com/recipes/complexSearch?'))
            self.assertIn('sort=price', request.full_url)
            self.assertIsNotNone(call.kwargs['timeout'])

    def test_searches_are_cached_in_the_database_for_everyone(self):
        self.use_api()
        self.fetch()
        self.fetch()
        self.assertEqual(self.urlopen.call_count, 2)  # one per course, then served from the cache
        self.assertTrue(RecipeCacheEntry.objects.filter(key='spoonacular:search:main:v1').exists())

    def test_expired_cache_is_refetched(self):
        self.use_api()
        self.fetch()
        RecipeCacheEntry.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.fetch()
        self.assertEqual(self.urlopen.call_count, 4)

    def test_only_validated_fields_are_cached(self):
        item = {**search_item(id=20), 'summary': '<b>huge HTML blob</b>' * 100}
        self.use_api(main={'results': [item]})
        self.fetch()
        cached = RecipeCacheEntry.objects.get(key='spoonacular:search:main:v1').value
        self.assertEqual(
            set(cached[0]), {'id', 'title', 'course', 'cost_per_serving', 'protein_g', 'carbs_g', 'fat_g', 'image_url'}
        )

    def test_malformed_items_are_skipped(self):
        items = [
            search_item(id=1),
            {'id': 2, 'title': 'No nutrition', 'pricePerServing': 100},
            search_item(id=3, price=-5),
            search_item(id=4, price='NaN'),
            {**search_item(id=5), 'title': ''},
        ]
        self.use_api(main={'results': items})
        self.assertIn('spoonacular-1', [r.id for r in self.fetch()])
        self.assertEqual(len([r for r in self.fetch() if r.course == 'main']), 1)

    def test_nutrients_not_in_grams_are_rejected(self):
        item = search_item()
        item['nutrition']['nutrients'][1]['unit'] = 'mg'
        self.use_api(main={'results': [item]})
        with self.assertRaises(RecipeServiceUnavailable):
            self.fetch()

    def test_untrusted_image_urls_are_dropped(self):
        self.use_api(
            main={
                'results': [
                    search_item(id=1, image='http://img.spoonacular.com/x.jpg'),
                    search_item(id=2, image='https://evil.example/x.jpg'),
                ]
            }
        )
        self.assertEqual({r.image_url for r in self.fetch() if r.course == 'main'}, {''})

    def test_failures_become_unavailable(self):
        failures = {
            'quota used up': urllib.error.HTTPError('u', 402, 'Payment Required', {}, None),  # type: ignore[arg-type]
            'bad key': urllib.error.HTTPError('u', 401, 'Unauthorized', {}, None),  # type: ignore[arg-type]
            'network down': urllib.error.URLError('connection refused'),
            'timeout': TimeoutError(),
        }
        for name, error in failures.items():
            with self.subTest(name):
                RecipeCacheEntry.objects.all().delete()
                self.use_api(main=error)
                with self.assertRaises(RecipeServiceUnavailable):
                    self.fetch()

    def test_bad_payloads_become_unavailable(self):
        payloads = {
            'not json': b'<html>oops</html>',
            'not an object': [1, 2],
            'no results key': {'status': 'failure'},
            'results not a list': {'results': {'id': 1}},
            'no usable recipes': {'results': []},
            'too large': b'{"results": [' + b' ' * (SpoonacularRecipeSource.MAX_RESPONSE_BYTES + 1) + b']}',
        }
        for name, payload in payloads.items():
            with self.subTest(name):
                RecipeCacheEntry.objects.all().delete()
                self.use_api(main=payload)
                with self.assertRaises(RecipeServiceUnavailable):
                    self.fetch()

    def test_a_failure_is_remembered_briefly_so_the_api_is_not_hammered(self):
        self.use_api(breakfast=urllib.error.URLError('down'))
        for _ in range(3):
            with self.assertRaises(RecipeServiceUnavailable):
                self.fetch()
        self.assertEqual(self.urlopen.call_count, 1)

    @override_settings(SPOONACULAR_API_KEY='')
    def test_missing_api_key_is_unavailable_without_a_request(self):
        with self.assertLogs('nutrition.recipe_sources', level='ERROR'), self.assertRaises(RecipeServiceUnavailable):
            self.fetch()
        self.urlopen.assert_not_called()

    def test_api_key_never_appears_in_logs(self):
        self.use_api(main=urllib.error.HTTPError('u', 401, 'Unauthorized', {}, None))  # type: ignore[arg-type]
        with (
            self.assertLogs('nutrition.recipe_sources', level='WARNING') as logs,
            self.assertRaises(RecipeServiceUnavailable),
        ):
            self.fetch()
        self.assertNotIn(API_KEY, '\n'.join(logs.output))


@override_settings(SPOONACULAR_API_KEY=API_KEY)
class SpoonacularDetailsTests(TestCase):
    def setUp(self):
        patcher = mock.patch('nutrition.recipe_sources.urllib.request.urlopen')
        self.urlopen = patcher.start()
        self.addCleanup(patcher.stop)
        self.recipe = recipe('spoonacular-20', '1.63')

    def details(self, payload=None):
        self.urlopen.side_effect = fake_api(details=payload if payload is not None else details_payload())
        return SpoonacularRecipeSource().recipe_details(self.recipe)

    def test_ingredients_steps_time_and_source(self):
        details = self.details()
        self.assertEqual([i.text for i in details.ingredients], ['1 lb chicken thighs', '2 cups cooked rice'])
        self.assertEqual(details.steps, ('Cook the chicken.', 'Serve over rice.'))
        self.assertEqual(details.ready_in_minutes, 25)
        self.assertEqual(details.source_url, 'https://example.com/chicken-rice-bowl')
        url = self.urlopen.call_args.args[0].full_url
        self.assertTrue(url.startswith('https://api.spoonacular.com/recipes/20/information?'))

    def test_html_instructions_are_never_used(self):
        details = self.details(details_payload(analyzedInstructions=[]))
        self.assertEqual(details.steps, ())

    def test_details_are_cached_for_a_long_time(self):
        self.details()
        self.details()
        self.assertEqual(self.urlopen.call_count, 1)
        entry = RecipeCacheEntry.objects.get(key='spoonacular:recipe:20:v1')
        self.assertGreater(entry.expires_at, timezone.now() + timedelta(days=29))

    def test_untrusted_source_url_and_bad_ready_time_are_dropped(self):
        details = self.details(details_payload(sourceUrl='javascript:alert(1)', readyInMinutes='soon'))
        self.assertEqual((details.source_url, details.ready_in_minutes), ('', None))

    def test_long_lists_and_text_are_truncated(self):
        many = [{'name': 'x', 'original': 'y' * 1000}] * 100
        details = self.details(details_payload(extendedIngredients=many))
        self.assertEqual(len(details.ingredients), 60)
        self.assertEqual(len(details.ingredients[0].text), 300)

    def test_malformed_details_are_unavailable(self):
        for payload in ({'extendedIngredients': None}, {'analyzedInstructions': 'nope', 'extendedIngredients': []}):
            with self.subTest(payload=payload):
                RecipeCacheEntry.objects.all().delete()
                with self.assertRaises(RecipeServiceUnavailable):
                    self.details(payload)

    def test_only_spoonacular_recipe_ids_can_be_looked_up(self):
        for bad_id in ('starter-lentil-curry', 'spoonacular-../../admin', 'spoonacular-'):
            with self.subTest(bad_id=bad_id), self.assertRaises(RecipeServiceUnavailable):
                SpoonacularRecipeSource().recipe_details(recipe(bad_id, '1.00'))
        self.urlopen.assert_not_called()


class StarterCatalogSourceTests(SimpleTestCase):
    def test_catalog_has_enough_recipes_for_a_three_meal_week_with_no_repeats(self):
        recipes = StarterCatalogSource().budget_recipes()
        self.assertGreaterEqual(len([r for r in recipes if r.course == 'breakfast']), 7)
        self.assertGreaterEqual(len([r for r in recipes if r.course == 'main']), 14)
        self.assertEqual(len({r.id for r in recipes}), len(recipes))

    def test_every_catalog_recipe_has_ingredients_and_steps(self):
        source = StarterCatalogSource()
        for item in source.budget_recipes():
            with self.subTest(recipe=item.id):
                details = source.recipe_details(item)
                self.assertTrue(details.ingredients)
                self.assertTrue(details.steps)

    def test_unknown_recipe_has_no_details(self):
        with self.assertRaises(RecipeServiceUnavailable):
            StarterCatalogSource().recipe_details(recipe('nope', '1.00'))

    def test_unreadable_catalog_is_unavailable(self):
        with (
            mock.patch('nutrition.recipe_sources.STARTER_CATALOG', Path('does-not-exist.json')),
            self.assertLogs('nutrition.recipe_sources', level='ERROR'),
            self.assertRaises(RecipeServiceUnavailable),
        ):
            StarterCatalogSource().budget_recipes()

    def test_invalid_catalog_recipe_is_unavailable(self):
        with (
            mock.patch.object(StarterCatalogSource, '_catalog', return_value=[{'id': 'x', 'title': 'X'}]),
            self.assertLogs('nutrition.recipe_sources', level='ERROR'),
            self.assertRaises(RecipeServiceUnavailable),
        ):
            StarterCatalogSource().budget_recipes()


class CacheTests(TestCase):
    def test_round_trip_expiry_and_cleanup(self):
        cache.set('a', {'x': 1}, 60)
        self.assertEqual(cache.get('a'), {'x': 1})
        self.assertEqual(str(RecipeCacheEntry.objects.get(key='a')), 'a')
        cache.set('a', [2], 60)  # overwrite
        self.assertEqual(cache.get('a'), [2])
        RecipeCacheEntry.objects.filter(key='a').update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertIsNone(cache.get('a'))
        cache.set('b', True, 60)  # writing clears expired rows
        self.assertFalse(RecipeCacheEntry.objects.filter(key='a').exists())
        self.assertIsNone(cache.get('missing'))


class SourceSelectionTests(SimpleTestCase):
    def test_tests_use_the_starter_catalog_and_no_api_key_whatever_env_says(self):
        self.assertIsInstance(recipe_source(), StarterCatalogSource)
        self.assertEqual(settings.SPOONACULAR_API_KEY, '')

    @override_settings(NUTRITION_RECIPE_SOURCE='nutrition.recipe_sources.SpoonacularRecipeSource')
    def test_source_is_chosen_by_setting(self):
        self.assertIsInstance(recipe_source(), SpoonacularRecipeSource)
