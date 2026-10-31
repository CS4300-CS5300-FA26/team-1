from decimal import Decimal

from django import template

register = template.Library()

FRACTIONS = {Decimal('0.5'): '½'}


@register.filter
def servings(value) -> str:
    """Decimal('1') -> '1 serving', Decimal('1.5') -> '1½ servings', Decimal('2') -> '2 servings'."""
    amount = Decimal(value)
    whole = int(amount)
    rest = amount - whole
    text = f'{whole if whole else ""}{FRACTIONS.get(rest, "")}' if rest in FRACTIONS else f'{amount.normalize():f}'
    return f'{text} serving' if amount == 1 else f'{text} servings'
