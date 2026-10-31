"""Turning the grocery price connector's quotes (D-6) into one average price per ingredient.

The connector may return several quotes for an ingredient (different products, sizes, or stores), in whatever
unit the product is sold by. Each quote is converted to a price per gram and a package weight; the estimate is
the average of both across the quotes that could be converted, so meal plan costs track what the grocery list
shows. Volume and count units need the ingredient's density or weight each (from USDA portion data); quotes that
can't be converted are skipped and logged.
"""

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from .domain import Ingredient, PriceEstimate

logger = logging.getLogger(__name__)

# Exact conversions (NIST Handbook 44). Volume and count conversions also need the ingredient's density.
GRAMS_PER_UNIT = {'g': Decimal('1'), 'kg': Decimal('1000'), 'oz': Decimal('28.349523125'), 'lb': Decimal('453.59237')}
ML_PER_UNIT = {
    'ml': Decimal('1'),
    'l': Decimal('1000'),
    'fl oz': Decimal('29.5735295625'),
    'cup': Decimal('236.5882365'),
    'pt': Decimal('473.176473'),
    'qt': Decimal('946.352946'),
    'gal': Decimal('3785.411784'),
}
UNITS = (*GRAMS_PER_UNIT, *ML_PER_UNIT, 'each')


@dataclass(frozen=True)
class PriceQuote:
    """One product price from the grocery price connector: `price` dollars for `quantity` `unit` of the item."""

    price: Decimal
    quantity: Decimal
    unit: str
    source: str = ''  # store or product, for logs and debugging
    observed_on: date | None = None


def quote_grams(quote: PriceQuote, ingredient: Ingredient) -> Decimal | None:
    """The quote's package weight in grams, or None if its unit can't be converted for this ingredient."""
    unit = quote.unit.strip().lower()
    if unit in GRAMS_PER_UNIT:
        return quote.quantity * GRAMS_PER_UNIT[unit]
    if unit in ML_PER_UNIT and ingredient.grams_per_ml:
        return quote.quantity * ML_PER_UNIT[unit] * Decimal(str(ingredient.grams_per_ml))
    if unit == 'each' and ingredient.grams_per_each:
        return quote.quantity * Decimal(str(ingredient.grams_per_each))
    return None


def estimate(ingredient: Ingredient, quotes: Iterable[PriceQuote]) -> PriceEstimate | None:
    """The average price per gram and package weight across the usable quotes; None if none are usable."""
    per_gram: list[Decimal] = []
    packages: list[Decimal] = []
    for quote in quotes:
        try:
            grams = quote_grams(quote, ingredient)
            usable = grams is not None and grams > 0 and Decimal(quote.price) > 0
        except (InvalidOperation, TypeError, AttributeError):
            usable = False
        if not usable or grams is None:
            logger.warning('Skipping a price quote for %s that cannot be converted to grams.', ingredient.key)
            continue
        per_gram.append(Decimal(quote.price) / grams)
        packages.append(grams)
    if not per_gram:
        return None
    return PriceEstimate(
        price_per_gram=sum(per_gram, Decimal(0)) / len(per_gram),
        package_grams=sum(packages, Decimal(0)) / len(packages),
        quote_count=len(per_gram),
    )


def estimates(
    ingredients: Sequence[Ingredient], quotes: Mapping[str, Sequence[PriceQuote]]
) -> dict[str, PriceEstimate]:
    """Average prices for every ingredient that has at least one usable quote."""
    found = {}
    for ingredient in ingredients:
        price = estimate(ingredient, quotes.get(ingredient.key, ()))
        if price is not None:
            found[ingredient.key] = price
    return found
