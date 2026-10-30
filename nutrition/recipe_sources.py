"""Recipe sources: adapters behind the `nutrition.ports.RecipeSource` interface (ADR-008).

Every source validates what it returns, so the planner only ever sees well-formed `Recipe` objects.
Anything that goes wrong (network, quota, bad data, missing configuration) surfaces as
RecipeServiceUnavailable, which the view turns into the "temporarily unavailable" notice.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.cache import cache

from .domain import Recipe, money
from .ports import RecipeServiceUnavailable

logger = logging.getLogger(__name__)

STARTER_CATALOG = Path(__file__).resolve().parent / 'data' / 'starter_recipes.json'


class StarterCatalogSource:
    """The built-in catalog in data/starter_recipes.json. No network, so it is always available."""

    attribution = 'Starter recipes from FitPro, with estimated grocery prices.'

    def budget_recipes(self) -> Sequence[Recipe]:
        try:
            raw = json.loads(STARTER_CATALOG.read_text(encoding='utf-8'))['recipes']
            return [
                Recipe(
                    id=item['id'],
                    title=item['title'],
                    cost_per_serving=money(item['cost_per_serving']),
                    protein_g=float(item['protein_g']),
                    carbs_g=float(item['carbs_g']),
                    fat_g=float(item['fat_g']),
                )
                for item in raw
            ]
        except (OSError, KeyError, TypeError, ValueError, ArithmeticError) as exc:
            logger.error('Starter recipe catalog is unreadable: %s', type(exc).__name__)
            raise RecipeServiceUnavailable('Starter catalog unreadable.') from exc


class SpoonacularRecipeSource:
    """Cheap main courses from Spoonacular's complexSearch, cached for everyone.

    The query does not depend on the user, so one cached result serves every request and no user
    action can trigger extra (billed) API calls. Failures are cached briefly too, so a down or
    over-quota API is not retried on every page view.
    """

    attribution = 'Recipe data from Spoonacular.'
    ENDPOINT = 'https://api.spoonacular.com/recipes/complexSearch'
    CACHE_KEY = 'nutrition:spoonacular:budget-recipes:v1'
    FAILURE_CACHE_KEY = CACHE_KEY + ':failed'
    QUERY = {
        'type': 'main course',
        'sort': 'price',
        'sortDirection': 'asc',
        'addRecipeNutrition': 'true',
        'number': '40',
    }
    MAX_RESPONSE_BYTES = 2_000_000
    # Only images from Spoonacular's own HTTPS hosts are shown.
    IMAGE_PREFIXES = ('https://img.spoonacular.com/', 'https://spoonacular.com/')

    def budget_recipes(self) -> Sequence[Recipe]:
        cached = cache.get(self.CACHE_KEY)
        if cached is not None:
            return cached
        if cache.get(self.FAILURE_CACHE_KEY):
            raise RecipeServiceUnavailable('Spoonacular failed recently; not retrying yet.')
        try:
            recipes = self._parse(self._fetch())
        except RecipeServiceUnavailable:
            cache.set(self.FAILURE_CACHE_KEY, True, settings.NUTRITION_RECIPE_FAILURE_CACHE_SECONDS)
            raise
        cache.set(self.CACHE_KEY, recipes, settings.NUTRITION_RECIPE_CACHE_SECONDS)
        return recipes

    def _fetch(self) -> bytes:
        api_key = settings.SPOONACULAR_API_KEY
        if not api_key:
            logger.error('RECIPE_SOURCE is spoonacular but SPOONACULAR_API_KEY is not set.')
            raise RecipeServiceUnavailable('Spoonacular API key missing.')
        # The key goes in a header, not the query string, so it never appears in URLs or logs.
        request = urllib.request.Request(  # noqa: S310 - fixed https:// URL, not user-controlled
            f'{self.ENDPOINT}?{urllib.parse.urlencode(self.QUERY)}',
            headers={'x-api-key': api_key, 'Accept': 'application/json'},
        )
        try:
            with urllib.request.urlopen(  # noqa: S310  # nosec B310 - fixed https:// URL above
                request, timeout=settings.NUTRITION_RECIPE_TIMEOUT_SECONDS
            ) as response:
                body = response.read(self.MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            # 401 bad key, 402 daily quota used up, 5xx outage: all mean "no suggestions right now".
            logger.warning('Spoonacular returned HTTP %s', exc.code)
            raise RecipeServiceUnavailable(f'HTTP {exc.code}') from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning('Spoonacular request failed: %s', type(exc).__name__)
            raise RecipeServiceUnavailable('Request failed.') from exc
        if len(body) > self.MAX_RESPONSE_BYTES:
            logger.warning('Spoonacular response exceeded %s bytes', self.MAX_RESPONSE_BYTES)
            raise RecipeServiceUnavailable('Response too large.')
        return body

    def _parse(self, body: bytes) -> list[Recipe]:
        """Validate the response; skip malformed items, and fail if none are usable."""
        try:
            results = json.loads(body)['results']
            if not isinstance(results, list):
                raise TypeError('results is not a list')
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning('Spoonacular response was not the expected JSON: %s', type(exc).__name__)
            raise RecipeServiceUnavailable('Malformed response.') from exc

        recipes = []
        for item in results:
            try:
                recipes.append(self._recipe_from(item))
            except (ValueError, KeyError, TypeError, AttributeError, ArithmeticError):
                continue  # one bad recipe shouldn't sink the whole week
        if not recipes:
            logger.warning('Spoonacular returned no usable recipes (%s results).', len(results))
            raise RecipeServiceUnavailable('No usable recipes.')
        return recipes

    def _recipe_from(self, item: dict) -> Recipe:
        nutrients = {n['name']: n for n in item['nutrition']['nutrients']}

        def grams(name: str) -> float:
            nutrient = nutrients[name]
            if nutrient['unit'] != 'g':
                raise ValueError(f'{name} is not in grams')
            return float(nutrient['amount'])

        image = item.get('image') or ''
        source_url = item.get('sourceUrl') or ''
        return Recipe(
            id=f'spoonacular-{int(item["id"])}',
            title=str(item['title'])[:200],
            # Spoonacular prices are US cents per serving.
            cost_per_serving=money(Decimal(str(item['pricePerServing'])) / 100),
            protein_g=grams('Protein'),
            carbs_g=grams('Carbohydrates'),
            fat_g=grams('Fat'),
            image_url=image if image.startswith(self.IMAGE_PREFIXES) else '',
            source_url=source_url if source_url.startswith('https://') else '',
        )
