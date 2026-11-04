import logging
from collections.abc import Iterable
from datetime import date

from nutrition import pricing
from nutrition.domain import Ingredient, PriceEstimate
from nutrition.ports import grocery_price_source
from nutrition.services import stored_week_plan

from .lists import GroceryList, build_grocery_list

logger = logging.getLogger(__name__)


def week_prices(ingredients: Iterable[Ingredient]) -> dict[str, PriceEstimate]:
    wanted = list(ingredients)
    try:
        quotes = grocery_price_source().quotes(wanted)
    except Exception:  # noqa: BLE001 - a broken price source must not take the grocery list down
        logger.exception('The grocery price connector failed; listing the groceries without prices.')
        quotes = {}
    return pricing.estimates(wanted, quotes or {})


def grocery_list_for(user, monday: date | None = None) -> GroceryList | None:
    plan = stored_week_plan(user, monday)
    if plan is None:
        return None
    return build_grocery_list(plan, week_prices(plan.ingredients().values()))
