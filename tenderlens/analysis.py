from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Iterator

from tenderlens.comparables import ComparableIndex
from tenderlens.models import AnalysisConfig, AnalysisResult, ComparableSet, Item
from tenderlens.numeric import CALCULATION_PRECISION, price_median


def _calculate(target: Item, comparables: ComparableSet, config: AnalysisConfig) -> AnalysisResult:
    count = len(comparables.contract_prices)
    reference = price_median(entry.price for entry in comparables.contract_prices) if count else None
    ids = tuple(item.item_id for item in comparables.items)
    if count < config.min_comparable_contracts:
        return AnalysisResult(target.item_id, "insufficient_data", reference, None, None, count, ids)
    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        ratio = target.unit_price / reference
        deviation = (ratio - 1) * 100
    # Decimal multiplication can itself round an arbitrarily precise threshold.
    # Fractions keep the decision exact, independently of the Decimal context.
    status = "flagged" if Fraction(target.unit_price) >= Fraction(reference) * Fraction(config.price_ratio_threshold) else "not_flagged"
    return AnalysisResult(target.item_id, status, reference, ratio, deviation, count, ids)


def analyze_item(target: Item, items: tuple[Item, ...] | list[Item], config: AnalysisConfig | None = None) -> AnalysisResult:
    config = config or AnalysisConfig()
    index = ComparableIndex(items, config.algorithm_version == "baseline_v1")
    return _calculate(target, index.find(target, config), config)


def analyze_dataset(items: tuple[Item, ...] | list[Item], config: AnalysisConfig | None = None) -> tuple[AnalysisResult, ...]:
    return tuple(iter_analysis(items, config))


def iter_analysis(items: tuple[Item, ...] | list[Item], config: AnalysisConfig | None = None) -> Iterator[AnalysisResult]:
    """Calculate one target at a time so persistence need not retain all links."""
    config = config or AnalysisConfig()
    index = ComparableIndex(items, config.algorithm_version == "baseline_v1")
    for item in sorted(items, key=lambda value: value.item_id):
        yield _calculate(item, index.find(item, config), config)


def threshold_percent(config: AnalysisConfig) -> str:
    """Format the actual threshold, without rounding it to a whole percentage."""
    with localcontext() as context:
        context.prec = max(CALCULATION_PRECISION, len(config.price_ratio_threshold.as_tuple().digits) + 3)
        threshold = format((config.price_ratio_threshold - Decimal(1)) * 100, "f")
        if "." in threshold:
            threshold = threshold.rstrip("0").rstrip(".")
    return threshold


def explain(result: AnalysisResult, config: AnalysisConfig) -> str:
    if result.status == "insufficient_data":
        return (f"Недостаточно данных: найдено {result.comparable_contracts_count} договоров-аналогов, "
                f"требуется {config.min_comparable_contracts}. Решение о цене не принимается.")
    sign = "достигает или превышает" if result.status == "flagged" else "не достигает"
    # Different grammatical cases keep a numeric threshold clear in either branch.
    threshold_word = "порог" if result.status == "flagged" else "порога"
    return (f"Отклонение от медианы: {result.deviation_percent:+.1f}%. "
            f"Цена {sign} {threshold_word} {threshold_percent(config)}%. "
            f"В сравнении {result.comparable_contracts_count} разных договоров. "
            "Это результат ценового правила, а не заключение о нарушении.")
