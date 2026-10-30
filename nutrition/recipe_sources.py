"""Recipe sources: adapters behind the `nutrition.ports.RecipeSource` interface (ADR-008).

Every source validates what it returns, so the planner and pages only ever see well-formed domain
objects. Anything that goes wrong (network, quota, bad data, missing configuration) surfaces as
RecipeServiceUnavailable, which the pages turn into "temporarily unavailable" notices.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import asdict
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any

from django.conf import settings

from . import cache
from .domain import Ingredient, Recipe, RecipeDetails, money
from .ports import RecipeServiceUnavailable

logger = logging.getLogger(__name__)

STARTER_CATALOG = Path(__file__).resolve().parent / 'data' / 'starter_recipes.json'

# Bounds on third-party text, so one odd recipe can't bloat the cache or the page.
MAX_TITLE = 200
MAX_INGREDIENTS = 60
MAX_INGREDIENT_TEXT = 300
MAX_STEPS = 40
MAX_STEP_TEXT = 1000

BAD_DATA = (ValueError, KeyError, TypeError, AttributeError, ArithmeticError)


class StarterCatalogSource:
    """The built-in catalog in data/starter_recipes.json. No network, so it is always available."""

    attribution = 'Starter recipes from FitPro, with estimated grocery prices.'

    def _catalog(self) -> list[dict]:
        try:
            return json.loads(STARTER_CATALOG.read_text(encoding='utf-8'))['recipes']
        except (OSError, *BAD_DATA) as exc:
            logger.error('Starter recipe catalog is unreadable: %s', type(exc).__name__)
            raise RecipeServiceUnavailable('Starter catalog unreadable.') from exc

    def budget_recipes(self) -> Sequence[Recipe]:
        try:
            return [
                Recipe(
                    id=item['id'],
                    title=item['title'],
                    course=item['course'],
                    cost_per_serving=money(item['cost_per_serving']),
                    protein_g=float(item['protein_g']),
                    carbs_g=float(item['carbs_g']),
                    fat_g=float(item['fat_g']),
                )
                for item in self._catalog()
            ]
        except BAD_DATA as exc:
            logger.error('Starter recipe catalog has a bad recipe: %s', type(exc).__name__)
            raise RecipeServiceUnavailable('Starter catalog invalid.') from exc

    def recipe_details(self, recipe: Recipe) -> RecipeDetails:
        item = next((r for r in self._catalog() if r.get('id') == recipe.id), None)
        if item is None:
            raise RecipeServiceUnavailable(f'{recipe.id} is not in the starter catalog.')
        return RecipeDetails(
            ingredients=tuple(Ingredient(text=str(text)) for text in item.get('ingredients', [])),
            steps=tuple(str(step) for step in item.get('steps', [])),
            ready_in_minutes=item.get('ready_in_minutes'),
        )


class SpoonacularRecipeSource:
    """Cheap breakfasts and main courses from Spoonacular, cached in the database for everyone.

    Quota use is bounded by design:
    * The two searches don't depend on the user, so one cached result serves every request for
      NUTRITION_RECIPE_CACHE_SECONDS, whatever users do.
    * Details (ingredients and steps) are fetched only for a recipe someone opens from their own plan,
      and cached for NUTRITION_RECIPE_DETAILS_CACHE_SECONDS. Users can't ask for arbitrary recipes.
    * A failure is remembered for NUTRITION_RECIPE_FAILURE_CACHE_SECONDS, so a down or over-quota
      API isn't retried on every page view.
    """

    attribution = 'Recipe data from Spoonacular.'
    BASE_URL = 'https://api.spoonacular.com'
    SEARCHES = {'breakfast': 'breakfast', 'main': 'main course'}  # our course -> Spoonacular meal type
    SEARCH_PARAMS = {'sort': 'price', 'sortDirection': 'asc', 'addRecipeNutrition': 'true', 'number': '40'}
    MAX_RESPONSE_BYTES = 2_000_000
    # Only images from Spoonacular's own HTTPS hosts are shown.
    IMAGE_PREFIXES = ('https://img.spoonacular.com/', 'https://spoonacular.com/')

    def budget_recipes(self) -> Sequence[Recipe]:
        recipes: dict[str, Recipe] = {}
        for course, meal_type in self.SEARCHES.items():
            found = self._cached(
                f'spoonacular:search:{course}:v1',
                '/recipes/complexSearch',
                {'type': meal_type, **self.SEARCH_PARAMS},
                settings.NUTRITION_RECIPE_CACHE_SECONDS,
                partial(self._search_to_cache, course=course),
            )
            for data in found:
                recipe = _recipe_from_dict(data)
                recipes.setdefault(recipe.id, recipe)  # a dish tagged as both stays in its first course
        return list(recipes.values())

    def recipe_details(self, recipe: Recipe) -> RecipeDetails:
        spoonacular_id = recipe.id.removeprefix('spoonacular-')
        if not (recipe.id.startswith('spoonacular-') and spoonacular_id.isdigit()):
            raise RecipeServiceUnavailable(f'{recipe.id} is not a Spoonacular recipe.')
        data = self._cached(
            f'spoonacular:recipe:{spoonacular_id}:v1',
            f'/recipes/{spoonacular_id}/information',
            {'includeNutrition': 'false'},
            settings.NUTRITION_RECIPE_DETAILS_CACHE_SECONDS,
            lambda body: _details_to_dict(self._parse_details(body)),
        )
        return _details_from_dict(data)

    # -- fetching and caching -------------------------------------------------------------------

    def _cached(self, key: str, path: str, params: dict, seconds: int, parse: Callable[[bytes], Any]) -> Any:
        """Cached, validated data for one API call; fetch and parse it on a miss."""
        value = cache.get(key)
        if value is not None:
            return value
        failed_key = f'{key}:failed'
        if cache.get(failed_key):
            raise RecipeServiceUnavailable('Spoonacular failed recently; not retrying yet.')
        try:
            value = parse(self._fetch(path, params))
        except RecipeServiceUnavailable:
            cache.set(failed_key, True, settings.NUTRITION_RECIPE_FAILURE_CACHE_SECONDS)
            raise
        cache.set(key, value, seconds)
        return value

    def _fetch(self, path: str, params: dict) -> bytes:
        api_key = settings.SPOONACULAR_API_KEY
        if not api_key:
            logger.error('RECIPE_SOURCE is spoonacular but SPOONACULAR_API_KEY is not set.')
            raise RecipeServiceUnavailable('Spoonacular API key missing.')
        # The key goes in a header, not the query string, so it never appears in URLs or logs.
        request = urllib.request.Request(  # noqa: S310 - fixed https:// base URL, not user-controlled
            f'{self.BASE_URL}{path}?{urllib.parse.urlencode(params)}',
            headers={'x-api-key': api_key, 'Accept': 'application/json'},
        )
        try:
            with urllib.request.urlopen(  # noqa: S310  # nosec B310 - fixed https:// base URL above
                request, timeout=settings.NUTRITION_RECIPE_TIMEOUT_SECONDS
            ) as response:
                body = response.read(self.MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            # 401 bad key, 402 daily quota used up, 5xx outage: all mean "no suggestions right now".
            logger.warning('Spoonacular returned HTTP %s for %s', exc.code, path)
            raise RecipeServiceUnavailable(f'HTTP {exc.code}') from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning('Spoonacular request failed: %s', type(exc).__name__)
            raise RecipeServiceUnavailable('Request failed.') from exc
        if len(body) > self.MAX_RESPONSE_BYTES:
            logger.warning('Spoonacular response exceeded %s bytes', self.MAX_RESPONSE_BYTES)
            raise RecipeServiceUnavailable('Response too large.')
        return body

    # -- validation -----------------------------------------------------------------------------

    def _json(self, body: bytes) -> Any:
        try:
            return json.loads(body)
        except ValueError as exc:
            logger.warning('Spoonacular response was not JSON.')
            raise RecipeServiceUnavailable('Malformed response.') from exc

    def _search_to_cache(self, body: bytes, course: str) -> list[dict]:
        return [_recipe_to_dict(recipe) for recipe in self._parse_search(body, course)]

    def _parse_search(self, body: bytes, course: str) -> list[Recipe]:
        """Validate a search; skip malformed recipes, and fail if none are usable."""
        data = self._json(body)
        results = data.get('results') if isinstance(data, dict) else None
        if not isinstance(results, list):
            logger.warning('Spoonacular search response had no results list.')
            raise RecipeServiceUnavailable('Malformed response.')
        recipes = []
        for item in results:
            try:
                recipes.append(self._recipe_from(item, course))
            except BAD_DATA:
                continue  # one bad recipe shouldn't sink the whole week
        if not recipes:
            logger.warning('Spoonacular returned no usable %s recipes (%s results).', course, len(results))
            raise RecipeServiceUnavailable('No usable recipes.')
        return recipes

    def _recipe_from(self, item: dict, course: str) -> Recipe:
        nutrients = {n['name']: n for n in item['nutrition']['nutrients']}

        def grams(name: str) -> float:
            nutrient = nutrients[name]
            if nutrient['unit'] != 'g':
                raise ValueError(f'{name} is not in grams')
            return float(nutrient['amount'])

        image = item.get('image') or ''
        return Recipe(
            id=f'spoonacular-{int(item["id"])}',
            title=str(item['title'])[:MAX_TITLE],
            course=course,
            # Spoonacular prices are US cents per serving.
            cost_per_serving=money(Decimal(str(item['pricePerServing'])) / 100),
            protein_g=grams('Protein'),
            carbs_g=grams('Carbohydrates'),
            fat_g=grams('Fat'),
            image_url=image if isinstance(image, str) and image.startswith(self.IMAGE_PREFIXES) else '',
        )

    def _parse_details(self, body: bytes) -> RecipeDetails:
        data = self._json(body)
        try:
            ingredients = tuple(
                Ingredient(text=str(item['original'])[:MAX_INGREDIENT_TEXT], name=str(item.get('name', ''))[:MAX_TITLE])
                for item in data['extendedIngredients'][:MAX_INGREDIENTS]
                if str(item.get('original', '')).strip()
            )
            # Use the structured steps only; the free-text `instructions` field can contain HTML.
            steps = tuple(
                str(step['step'])[:MAX_STEP_TEXT]
                for section in data.get('analyzedInstructions') or []
                for step in section.get('steps', [])
                if str(step.get('step', '')).strip()
            )[:MAX_STEPS]
            ready = data.get('readyInMinutes')
            source_url = data.get('sourceUrl') or ''
            return RecipeDetails(
                ingredients=ingredients,
                steps=steps,
                ready_in_minutes=int(ready) if isinstance(ready, int | float) and ready > 0 else None,
                source_url=source_url if isinstance(source_url, str) and source_url.startswith('https://') else '',
            )
        except BAD_DATA as exc:
            logger.warning('Spoonacular recipe details were not in the expected shape: %s', type(exc).__name__)
            raise RecipeServiceUnavailable('Malformed recipe details.') from exc


# Cached data is stored as plain JSON (only validated values) and rebuilt into domain objects.


def _recipe_to_dict(recipe: Recipe) -> dict:
    return {**asdict(recipe), 'cost_per_serving': str(recipe.cost_per_serving)}


def _recipe_from_dict(data: dict) -> Recipe:
    return Recipe(**{**data, 'cost_per_serving': Decimal(data['cost_per_serving'])})


def _details_to_dict(details: RecipeDetails) -> dict:
    return asdict(details)


def _details_from_dict(data: dict) -> RecipeDetails:
    return RecipeDetails(
        ingredients=tuple(Ingredient(**item) for item in data['ingredients']),
        steps=tuple(data['steps']),
        ready_in_minutes=data['ready_in_minutes'],
        source_url=data['source_url'],
    )
