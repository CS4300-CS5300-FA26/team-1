"""Loading FitPro's recipe catalog (data/recipe_catalog.json) into the database (ADR-008).

Runs after every `migrate` (see `NutritionConfig.ready`), so CI, tests, local databases, and the production
migrate Job all have the current catalog, and from `manage.py load_recipe_catalog`. Idempotent: ingredients and
recipes are matched by key/slug and updated in place, and anything no longer in the file is removed. Every row is
validated with the models' own validators before anything is written, in one transaction, so a bad file changes
nothing and fails loudly (failing the deploy's migrate step rather than serving bad data).
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import CatalogRecipe, Ingredient, RecipeLine

CATALOG_FILE = Path(__file__).resolve().parent / 'data' / 'recipe_catalog.json'

INGREDIENT_FIELDS = (
    'name',
    'fdc_id',
    'fdc_description',
    'kcal_per_100g',
    'protein_per_100g',
    'carbs_per_100g',
    'fat_per_100g',
    'grams_per_ml',
    'grams_per_each',
)
RECIPE_FIELDS = ('title', 'course', 'ready_in_minutes', 'steps')


class CatalogError(ValueError):
    """The catalog file is unreadable or has an invalid entry. Nothing was written."""


@dataclass(frozen=True)
class LoadResult:
    ingredients: int
    recipes: int
    removed_ingredients: int
    removed_recipes: int


def read_catalog(path: Path = CATALOG_FILE) -> dict:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise CatalogError(f'Cannot read {path.name}: {exc}') from exc
    if not (
        isinstance(data, dict) and isinstance(data.get('ingredients'), list) and isinstance(data.get('recipes'), list)
    ):
        raise CatalogError(f'{path.name} needs "ingredients" and "recipes" lists.')
    return data


@transaction.atomic
def load_catalog(data: dict) -> LoadResult:
    ingredients: dict[str, Ingredient] = {}
    for raw in data['ingredients']:
        ingredient = _save_ingredient(raw)
        if ingredient.key in ingredients:
            raise CatalogError(f'Ingredient {ingredient.key!r} appears twice.')
        ingredients[ingredient.key] = ingredient

    slugs: set[str] = set()
    for raw in data['recipes']:
        slug = _save_recipe(raw, ingredients)
        if slug in slugs:
            raise CatalogError(f'Recipe {slug!r} appears twice.')
        slugs.add(slug)

    # Recipes first: their lines protect the ingredients they use.
    _, removed_recipes = CatalogRecipe.objects.exclude(slug__in=slugs).delete()
    _, removed_ingredients = Ingredient.objects.exclude(key__in=ingredients).delete()
    return LoadResult(
        ingredients=len(ingredients),
        recipes=len(slugs),
        removed_ingredients=removed_ingredients.get(Ingredient._meta.label, 0),
        removed_recipes=removed_recipes.get(CatalogRecipe._meta.label, 0),
    )


def _field(raw: Any, name: str, where: str) -> Any:
    try:
        return raw[name]
    except (KeyError, TypeError) as exc:
        raise CatalogError(f'{where} is missing {name!r}.') from exc


def _validate(instance, where: str, exclude: list[str] | None = None) -> None:
    """Run the model's validators; `clean_fields` also converts strings to Decimals."""
    try:
        instance.full_clean(exclude=exclude, validate_unique=False, validate_constraints=False)
    except ValidationError as exc:
        raise CatalogError(f'{where} is invalid: {exc.message_dict}') from exc


def _save_ingredient(raw: dict) -> Ingredient:
    key = _field(raw, 'key', 'An ingredient')
    where = f'Ingredient {key!r}'
    ingredient = Ingredient.objects.filter(key=key).first() or Ingredient(key=key)
    for name in INGREDIENT_FIELDS:
        setattr(ingredient, name, _field(raw, name, where))
    _validate(ingredient, where)
    nutrients = (ingredient.protein_per_100g, ingredient.carbs_per_100g, ingredient.fat_per_100g)
    if ingredient.kcal_per_100g < 0 or not all(0 <= value <= 100 for value in nutrients):
        raise CatalogError(f'{where} has nutrients outside 0-100 g per 100 g.')
    for density in (ingredient.grams_per_ml, ingredient.grams_per_each):
        if density is not None and density <= 0:
            raise CatalogError(f'{where} has a density that is not positive.')
    ingredient.save()
    return ingredient


def _save_recipe(raw: dict, ingredients: dict[str, Ingredient]) -> str:
    slug = _field(raw, 'slug', 'A recipe')
    where = f'Recipe {slug!r}'
    recipe = CatalogRecipe.objects.filter(slug=slug).first() or CatalogRecipe(slug=slug)
    for name in RECIPE_FIELDS:
        setattr(recipe, name, _field(raw, name, where))
    _validate(recipe, where)
    steps = recipe.steps
    if not (isinstance(steps, list) and steps and all(isinstance(s, str) and s.strip() for s in steps)):
        raise CatalogError(f'{where} needs a list of non-empty steps.')

    raw_lines = _field(raw, 'lines', where)
    if not isinstance(raw_lines, list) or not raw_lines:
        raise CatalogError(f'{where} needs ingredient lines.')
    lines = []
    for position, raw_line in enumerate(raw_lines, start=1):
        line_where = f'{where} line {position}'
        key = raw_line.get('ingredient') if isinstance(raw_line, dict) else None
        if key is not None and key not in ingredients:
            raise CatalogError(f'{line_where} uses unknown ingredient {key!r}.')
        line = RecipeLine(
            position=position,
            text=_field(raw_line, 'text', line_where),
            ingredient=ingredients[key] if key is not None else None,
            grams=raw_line.get('grams'),
        )
        _validate(line, line_where, exclude=['recipe'])
        if (line.ingredient is None) != (line.grams is None) or (line.grams is not None and line.grams <= 0):
            raise CatalogError(f'{line_where} needs both an ingredient and a positive weight, or neither.')
        lines.append(line)
    if not any(line.ingredient for line in lines):
        raise CatalogError(f'{where} needs at least one weighed ingredient.')

    recipe.save()
    recipe.lines.all().delete()
    for line in lines:
        line.recipe = recipe
    RecipeLine.objects.bulk_create(lines)
    return slug
