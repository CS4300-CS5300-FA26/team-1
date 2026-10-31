"""Tests for the recipe catalog: the shipped data, loading it, and the database recipe source (ADR-008).

The test database already holds the shipped catalog (it's loaded after migrations). Loader tests use a small catalog
inside the test's transaction.
"""

import copy
import io
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, IntegrityError, transaction
from django.test import TestCase

from .apps import load_catalog_after_migrate
from .catalog_loader import CatalogError, load_catalog, read_catalog
from .domain import COURSE_FOR_MEAL, MEALS
from .models import CatalogRecipe, Ingredient, RecipeLine
from .ports import RecipeServiceUnavailable, recipe_source
from .recipe_sources import CatalogRecipeSource


def ingredient(key, kcal='100', protein='10', carbs='10', fat='1', **extra):
    return {
        'key': key,
        'name': key.capitalize(),
        'fdc_id': 1,
        'fdc_description': f'{key}, raw',
        'kcal_per_100g': kcal,
        'protein_per_100g': protein,
        'carbs_per_100g': carbs,
        'fat_per_100g': fat,
        'grams_per_ml': None,
        'grams_per_each': None,
        **extra,
    }


SMALL_CATALOG = {
    'ingredients': [
        ingredient('rice', '365', '7.13', '79.95', '0.66'),
        ingredient('eggs', '143', '12.56', '0.72', '9.51'),
    ],
    'recipes': [
        {
            'slug': 'egg-rice',
            'course': 'main',
            'title': 'Egg rice',
            'ready_in_minutes': 20,
            'lines': [
                {'text': '1/2 cup rice', 'ingredient': 'rice', 'grams': '92.5'},
                {'text': '2 eggs', 'ingredient': 'eggs', 'grams': '100'},
                {'text': 'Salt'},
            ],
            'steps': ['Cook the rice.', 'Fry the eggs.'],
        },
        {
            'slug': 'boiled-egg',
            'course': 'breakfast',
            'title': 'Boiled egg',
            'ready_in_minutes': 10,
            'lines': [{'text': '1 egg', 'ingredient': 'eggs', 'grams': '50'}],
            'steps': ['Boil the egg.'],
        },
    ],
}


def small_catalog():
    return copy.deepcopy(SMALL_CATALOG)


class ShippedCatalogTests(TestCase):
    """The real data/recipe_catalog.json, which the test database was migrated with."""

    def setUp(self):
        self.data = read_catalog()

    def test_every_ingredient_cites_usda_food_data_central(self):
        for item in self.data['ingredients']:
            with self.subTest(item=item['key']):
                self.assertIsInstance(item['fdc_id'], int)
                self.assertTrue(item['fdc_description'])
                grams = sum(float(item[f'{n}_per_100g']) for n in ('protein', 'carbs', 'fat'))
                self.assertLessEqual(grams, 100)

    def test_it_holds_no_prices(self):
        # Prices come only from the grocery price connector (D-6).
        for entry in self.data['ingredients'] + self.data['recipes']:
            self.assertFalse([field for field in entry if 'price' in field or 'cost' in field])

    def test_it_can_fill_a_varied_week(self):
        recipes = CatalogRecipeSource().recipes()
        for meal in MEALS:
            with self.subTest(meal=meal):
                # 7 meals each, at most twice per recipe, so at least 4 breakfasts and 7 mains (lunch and dinner).
                course = COURSE_FOR_MEAL[meal]
                self.assertGreaterEqual(sum(r.course == course for r in recipes), 4 if course == 'breakfast' else 7)

    def test_recipes_have_realistic_servings(self):
        for recipe in CatalogRecipeSource().recipes():
            with self.subTest(recipe=recipe.id):
                self.assertTrue(150 < recipe.nutrients.kcal < 900)


class CatalogRecipeSourceTests(TestCase):
    def setUp(self):
        load_catalog(small_catalog())

    def test_recipes_are_built_with_nutrients_from_their_ingredients(self):
        recipes = {r.id: r for r in CatalogRecipeSource().recipes()}
        self.assertEqual(set(recipes), {'egg-rice', 'boiled-egg'})
        egg_rice = recipes['egg-rice']
        self.assertEqual([line.text for line in egg_rice.lines], ['1/2 cup rice', '2 eggs', 'Salt'])
        self.assertEqual(egg_rice.grams_by_ingredient(), {'rice': 92.5, 'eggs': 100.0})
        self.assertAlmostEqual(egg_rice.nutrients.kcal, 365 * 0.925 + 143)
        self.assertEqual(egg_rice.steps, ('Cook the rice.', 'Fry the eggs.'))
        self.assertEqual(egg_rice.ingredients['rice'].fdc_id, 1)

    def test_empty_catalog_is_unavailable_and_logged(self):
        CatalogRecipe.objects.all().delete()
        with self.assertLogs('nutrition.recipe_sources', level='ERROR'), self.assertRaises(RecipeServiceUnavailable):
            CatalogRecipeSource().recipes()

    def test_database_errors_are_unavailable_and_logged(self):
        with (
            mock.patch('django.db.models.query.QuerySet._fetch_all', side_effect=DatabaseError('down')),
            self.assertLogs('nutrition.recipe_sources', level='ERROR'),
            self.assertRaises(RecipeServiceUnavailable),
        ):
            CatalogRecipeSource().recipes()

    def test_it_is_the_configured_source(self):
        self.assertIsInstance(recipe_source(), CatalogRecipeSource)


class LoaderTests(TestCase):
    def test_loading_is_idempotent_and_updates_in_place(self):
        load_catalog(small_catalog())
        rice_pk = Ingredient.objects.get(key='rice').pk
        data = small_catalog()
        data['ingredients'][0]['protein_per_100g'] = '8.00'
        result = load_catalog(data)
        self.assertEqual(
            (result.ingredients, result.recipes, result.removed_ingredients, result.removed_recipes), (2, 2, 0, 0)
        )
        rice = Ingredient.objects.get(key='rice')
        self.assertEqual((rice.pk, str(rice.protein_per_100g)), (rice_pk, '8.00'))
        self.assertEqual(RecipeLine.objects.filter(recipe__slug='egg-rice').count(), 3)

    def test_entries_no_longer_in_the_file_are_removed(self):
        load_catalog(small_catalog())
        data = small_catalog()
        data['recipes'] = data['recipes'][1:]
        data['ingredients'] = [i for i in data['ingredients'] if i['key'] != 'rice']
        result = load_catalog(data)
        self.assertEqual((result.removed_recipes, result.removed_ingredients), (1, 1))

    def test_invalid_entries_are_rejected_and_nothing_changes(self):
        load_catalog(small_catalog())

        def changed(change):
            data = small_catalog()
            change(data)
            return data

        broken = {
            'unknown ingredient': lambda d: d['recipes'][0]['lines'].append(
                {'text': 'x', 'ingredient': 'no', 'grams': '1'}
            ),
            'no weight': lambda d: d['recipes'][0]['lines'].append({'text': 'x', 'ingredient': 'rice'}),
            'weight, no ingredient': lambda d: d['recipes'][0]['lines'].append({'text': 'x', 'grams': '1'}),
            'zero weight': lambda d: d['recipes'][0]['lines'].append({'text': 'x', 'ingredient': 'rice', 'grams': '0'}),
            'nothing weighed': lambda d: d['recipes'][1].update(lines=[{'text': 'Salt'}]),
            'no lines': lambda d: d['recipes'][1].update(lines=[]),
            'no steps': lambda d: d['recipes'][1].update(steps=[]),
            'blank step': lambda d: d['recipes'][1].update(steps=[' ']),
            'unknown course': lambda d: d['recipes'][1].update(course='dessert'),
            'missing title': lambda d: d['recipes'][1].pop('title'),
            'duplicate recipe': lambda d: d['recipes'].append(d['recipes'][1]),
            'duplicate ingredient': lambda d: d['ingredients'].append(d['ingredients'][0]),
            'protein over 100 g': lambda d: d['ingredients'][0].update(protein_per_100g='101'),
            'negative fat': lambda d: d['ingredients'][0].update(fat_per_100g='-1'),
            'negative energy': lambda d: d['ingredients'][0].update(kcal_per_100g='-5'),
            'zero density': lambda d: d['ingredients'][0].update(grams_per_ml='0'),
            'missing fdc id': lambda d: d['ingredients'][0].pop('fdc_id'),
            'not a number': lambda d: d['ingredients'][0].update(carbs_per_100g='lots'),
        }
        for name, change in broken.items():
            with self.subTest(name), self.assertRaises(CatalogError):
                load_catalog(changed(change))
            self.assertEqual(str(Ingredient.objects.get(key='rice').protein_per_100g), '7.13')
            self.assertEqual(RecipeLine.objects.filter(recipe__slug='egg-rice').count(), 3)

    def test_unreadable_files_are_rejected(self):
        with self.assertRaises(CatalogError):
            read_catalog(Path('does-not-exist.json'))
        for text in ('not json', '[]', '{"ingredients": []}'):
            with (
                self.subTest(text=text),
                mock.patch.object(Path, 'read_text', return_value=text),
                self.assertRaises(CatalogError),
            ):
                read_catalog(Path('catalog.json'))

    def test_the_database_enforces_the_invariants(self):
        load_catalog(small_catalog())
        # Each in its own savepoint: PostgreSQL aborts a transaction after a failed statement.
        with self.assertRaises(IntegrityError), transaction.atomic():
            Ingredient.objects.filter(key='rice').update(protein_per_100g=101)
        with self.assertRaises(IntegrityError), transaction.atomic():
            RecipeLine.objects.filter(ingredient__isnull=True).update(grams=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Ingredient.objects.filter(key='rice').update(grams_per_each=0)

    def test_str(self):
        load_catalog(small_catalog())
        self.assertEqual(str(Ingredient.objects.get(key='rice')), 'Rice')
        self.assertEqual(str(CatalogRecipe.objects.get(slug='egg-rice')), 'Egg rice')
        self.assertEqual(str(RecipeLine.objects.get(text='Salt')), 'Salt')


class LoadAfterMigrateTests(TestCase):
    def test_the_catalog_is_reloaded_after_migrate(self):
        CatalogRecipe.objects.all().delete()
        with mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            load_catalog_after_migrate(sender=None, verbosity=2)
        self.assertTrue(CatalogRecipe.objects.exists())
        self.assertIn('Loaded recipe catalog', out.getvalue())

    def test_other_databases_and_missing_tables_are_skipped(self):
        CatalogRecipe.objects.all().delete()
        load_catalog_after_migrate(sender=None, using='other')
        with mock.patch('django.db.backends.base.introspection.BaseDatabaseIntrospection.table_names', return_value=[]):
            load_catalog_after_migrate(sender=None)
        self.assertFalse(CatalogRecipe.objects.exists())


class LoadRecipeCatalogCommandTests(TestCase):
    def test_loads_the_shipped_catalog(self):
        out = io.StringIO()
        call_command('load_recipe_catalog', stdout=out)
        self.assertIn('recipes and', out.getvalue())

    def test_a_bad_file_is_a_command_error(self):
        with self.assertRaises(CommandError):
            call_command('load_recipe_catalog', file=Path('does-not-exist.json'), stdout=io.StringIO())
