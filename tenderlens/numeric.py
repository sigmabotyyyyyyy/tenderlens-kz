"""Money calculations must not inherit a caller's global Decimal precision."""
from decimal import Decimal, localcontext
from statistics import median
from typing import Iterable

CALCULATION_PRECISION = 64


def price_median(values: Iterable[Decimal]) -> Decimal:
    prices = values if isinstance(values, (list, tuple)) else list(values)
    if len(prices) == 1:
        return prices[0]
    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        return median(prices)
