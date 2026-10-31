"""The recipe source FitPro ships: its catalog in the database, behind `nutrition.ports.RecipeSource` (ADR-008).

A recipe API could replace it later by implementing the same `recipes()` method and changing
NUTRITION_RECIPE_SOURCE.
"""

import logging
from collections.abc import Sequence

from django.db import DatabaseError
from django.db.models import Prefetch

from .domain import Ingredient, Nutrients, Recipe, RecipeLine
from .models import CatalogRecipe
from .models import Ingredient as IngredientRow
from .models import RecipeLine as RecipeLineRow
from .ports import RecipeServiceUnavailable

logger = logging.getLogger(__name__)


class CatalogRecipeSource:
    def recipes(self) -> Sequence[Recipe]:
        lines = Prefetch('lines', queryset=RecipeLineRow.objects.select_related('ingredient').order_by('position'))
        try:
            rows = list(CatalogRecipe.objects.prefetch_related(lines))
        except DatabaseError as exc:
            logger.error('Could not read the recipe catalog: %s', type(exc).__name__)
            raise RecipeServiceUnavailable('Database error.') from exc
        if not rows:
            logger.error('The recipe catalog is empty; run `manage.py migrate` or `manage.py load_recipe_catalog`.')
            raise RecipeServiceUnavailable('Recipe catalog is empty.')
        ingredients: dict[int, Ingredient] = {}
        return [_recipe(row, ingredients) for row in rows]


def ingredient_from_row(row: IngredientRow) -> Ingredient:
    return Ingredient(
        key=row.key,
        name=row.name,
        fdc_id=row.fdc_id,
        per_100g=Nutrients(
            kcal=float(row.kcal_per_100g),
            protein_g=float(row.protein_per_100g),
            carbs_g=float(row.carbs_per_100g),
            fat_g=float(row.fat_per_100g),
        ),
        grams_per_ml=float(row.grams_per_ml) if row.grams_per_ml is not None else None,
        grams_per_each=float(row.grams_per_each) if row.grams_per_each is not None else None,
    )


def _recipe(row: CatalogRecipe, ingredients: dict[int, Ingredient]) -> Recipe:
    lines = []
    for line in row.lines.all():
        if line.ingredient is None or line.grams is None:
            lines.append(RecipeLine(text=line.text))
            continue
        if line.ingredient.pk not in ingredients:
            ingredients[line.ingredient.pk] = ingredient_from_row(line.ingredient)
        lines.append(RecipeLine(text=line.text, ingredient=ingredients[line.ingredient.pk], grams=float(line.grams)))
    return Recipe(
        id=row.slug,
        title=row.title,
        course=row.course,
        lines=tuple(lines),
        steps=tuple(row.steps),
        ready_in_minutes=row.ready_in_minutes,
    )
