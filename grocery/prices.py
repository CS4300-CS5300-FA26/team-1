import json
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import cache
from pathlib import Path

from nutrition.domain import Ingredient
from nutrition.pricing import UNITS, PriceQuote

DATA_FILE = Path(__file__).resolve().parent / 'data' / 'price_quotes.json'


class PriceFileError(ValueError):
    """The price file is malformed; the message says which entry."""


def _positive(value: object, where: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise PriceFileError(f'{where}: {value!r} is not a number.') from exc
    if not number.is_finite() or number <= 0:
        raise PriceFileError(f'{where}: must be greater than zero.')
    return number


def read_quotes(path: Path = DATA_FILE) -> dict[str, tuple[PriceQuote, ...]]:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        raw = data['quotes']
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PriceFileError(f'Could not read the price file {path.name}: {exc}') from exc
    quotes: dict[str, tuple[PriceQuote, ...]] = {}
    for key, entries in raw.items():
        found = []
        for index, entry in enumerate(entries, start=1):
            where = f'{key} quote {index}'
            unit = str(entry.get('unit', '')).strip().lower()
            if unit not in UNITS:
                raise PriceFileError(f'{where}: unit {unit!r} must be one of {", ".join(UNITS)}.')
            source = str(entry.get('source', '')).strip()
            if not source:
                raise PriceFileError(f'{where}: every quote needs a source.')
            try:
                observed = date.fromisoformat(entry['observed_on'])
            except (KeyError, TypeError, ValueError) as exc:
                raise PriceFileError(f'{where}: observed_on must be a date like 2026-09-01.') from exc
            found.append(
                PriceQuote(
                    price=_positive(entry.get('price'), f'{where} price'),
                    quantity=_positive(entry.get('quantity'), f'{where} quantity'),
                    unit=unit,
                    source=source,
                    observed_on=observed,
                )
            )
        if not found:
            raise PriceFileError(f'{key}: has no quotes; remove the key instead.')
        quotes[key] = tuple(found)
    return quotes


@cache
def _stored_quotes() -> Mapping[str, tuple[PriceQuote, ...]]:
    return read_quotes()  # read once per process, since the meal plan asks on every page view


class StoredGroceryPrices:
    """Implements `nutrition.ports.GroceryPriceSource` from the reviewed price file."""

    def quotes(self, ingredients: Sequence[Ingredient]) -> Mapping[str, Sequence[PriceQuote]]:
        stored = _stored_quotes()
        return {ingredient.key: stored[ingredient.key] for ingredient in ingredients if ingredient.key in stored}
