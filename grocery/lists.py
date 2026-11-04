from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from nutrition.domain import Ingredient, PriceEstimate, WeekPlan, money, purchase_cost
from nutrition.pricing import GRAMS_PER_UNIT, ML_PER_UNIT

CUP_ML = ML_PER_UNIT['cup']
TBSP_ML = CUP_ML / 16
TSP_ML = TBSP_ML / 3
POUND_G = GRAMS_PER_UNIT['lb']
OUNCE_G = GRAMS_PER_UNIT['oz']

# Switching units a tenth of a percent early keeps "3 tsp" from showing instead of "1 tbsp".
BOUNDARY = Decimal('0.999')

QUARTER = Decimal('0.25')
HALF = Decimal('0.5')
FRACTION_SYMBOLS = {Decimal('0.25'): '¼', Decimal('0.5'): '½', Decimal('0.75'): '¾'}


def _nearest(value: Decimal, step: Decimal) -> Decimal:
    """`value` rounded to the nearest multiple of `step`, but never down to zero."""
    rounded = (value / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step
    return max(rounded, step)


def _number(value: Decimal) -> str:
    """3 -> '3', 1.5 -> '1½', 0.25 -> '¼'."""
    whole = int(value)
    symbol = FRACTION_SYMBOLS.get(value - whole, '')
    if not symbol:
        return str(whole)
    return f'{whole}{symbol}' if whole else symbol


def _with_unit(value: Decimal, singular: str, plural: str) -> str:
    return f'{_number(value)} {singular if value <= 1 else plural}'


def describe_amount(ingredient: Ingredient, grams: float) -> str:
    """The grams as a shopper would say them: '3 cups', '2 tbsp', '6', '1½ lb', '5½ oz'."""
    weight = Decimal(str(round(grams, 3)))
    if ingredient.grams_per_ml:
        millilitres = weight / Decimal(str(ingredient.grams_per_ml))
        if millilitres >= CUP_ML / 4 * BOUNDARY:
            return _with_unit(_nearest(millilitres / CUP_ML, QUARTER), 'cup', 'cups')
        if millilitres >= TBSP_ML * BOUNDARY:
            return _with_unit(_nearest(millilitres / TBSP_ML, HALF), 'tbsp', 'tbsp')
        return _with_unit(_nearest(millilitres / TSP_ML, QUARTER), 'tsp', 'tsp')
    if ingredient.grams_per_each:
        count = (weight / Decimal(str(ingredient.grams_per_each))).to_integral_value(rounding=ROUND_CEILING)
        return str(max(int(count), 1))
    if weight >= POUND_G * BOUNDARY:
        return _with_unit(_nearest(weight / POUND_G, QUARTER), 'lb', 'lb')
    return _with_unit(_nearest(weight / OUNCE_G, HALF), 'oz', 'oz')


@dataclass(frozen=True)
class GroceryItem:
    ingredient: Ingredient
    grams: float
    amount: str  # '3 cups', '6', '1½ lb'
    packages: int | None = None  # whole packages to buy; None if there's no price
    cost: Decimal | None = None  # what those packages cost; None if there's no price

    @property
    def name(self) -> str:
        return self.ingredient.name


@dataclass(frozen=True)
class GroceryList:
    items: tuple[GroceryItem, ...]
    pantry: tuple[str, ...]  # recipe lines with no weight (salt, spices), each listed once
    total: Decimal | None  # whole-package cost of every item; None unless every item has a price
    priced_total: Decimal  # the cost of the items that do have a price
    unpriced: int  # how many items have no price

    @property
    def priced(self) -> int:
        return len(self.items) - self.unpriced

    @property
    def has_prices(self) -> bool:
        return self.priced > 0


def build_grocery_list(plan: WeekPlan, prices: Mapping[str, PriceEstimate]) -> GroceryList:
    grams: dict[str, float] = {}
    ingredients: dict[str, Ingredient] = {}
    pantry: dict[str, None] = {}  # a dict keeps first-seen order
    for meal in plan.meals:
        for line, line_grams in meal.lines():
            if line.ingredient is None or line_grams is None:
                pantry.setdefault(line.text)
                continue
            key = line.ingredient.key
            grams[key] = grams.get(key, 0.0) + line_grams   # <- this is where rice gets combined
            ingredients[key] = line.ingredient

    items = []
    for key in sorted(grams, key=lambda k: (ingredients[k].name.lower(), k)):
        price = prices.get(key)
        items.append(
            GroceryItem(
                ingredient=ingredients[key],
                grams=grams[key],
                amount=describe_amount(ingredients[key], grams[key]),
                packages=price.packages_for(grams[key]) if price else None,
                cost=money(price.cost_for(grams[key])) if price else None,
            )
        )
    priced_total = money(sum((item.cost for item in items if item.cost is not None), Decimal(0)))
    return GroceryList(
        items=tuple(items),
        pantry=tuple(pantry),
        total=purchase_cost(grams, dict(prices)),
        priced_total=priced_total,
        unpriced=sum(1 for item in items if item.cost is None),
    )