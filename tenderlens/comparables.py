from bisect import bisect_left
from collections import defaultdict
from datetime import timedelta

from tenderlens.models import AnalysisConfig, ComparableSet, ContractPrice, Item
from tenderlens.numeric import price_median


def group_key(item: Item, baseline: bool = False) -> tuple:
    basis = (item.currency, item.vat_basis, item.delivery_basis)
    if baseline:
        return basis
    return basis + (item.paper_format, item.density_g_m2, item.sheets_per_pack,
                    item.unit, item.delivery_region)


class ComparableIndex:
    """Sort once; select history by date before checking quantities and contracts."""

    def __init__(self, items: tuple[Item, ...] | list[Item], baseline: bool = False):
        self.baseline = baseline
        groups = defaultdict(list)
        for item in items:
            groups[group_key(item, baseline)].append(item)
        self.groups = {}
        for key, group in groups.items():
            ordered = sorted(group, key=lambda item: (item.contract_date, item.item_id))
            self.groups[key] = (ordered, [item.contract_date for item in ordered])

    def find(self, target: Item, config: AnalysisConfig) -> ComparableSet:
        ordered, dates = self.groups.get(group_key(target, self.baseline), ([], []))
        # date.min is a valid input; saturate instead of overflowing timedelta.
        start = target.contract_date - timedelta(days=min(config.window_days, target.contract_date.toordinal() - 1))
        left = bisect_left(dates, start)
        right = bisect_left(dates, target.contract_date)
        matches = [item for item in ordered[left:right]
                   if item.contract_id != target.contract_id
                   and (self.baseline or target.quantity <= item.quantity * 2
                        and item.quantity <= target.quantity * 2)]
        prices = defaultdict(list)
        for item in matches:
            prices[item.contract_id].append(item.unit_price)
        references = tuple(ContractPrice(key, price_median(values)) for key, values in sorted(prices.items()))
        return ComparableSet(tuple(sorted(matches, key=lambda item: item.item_id)), references)


def find_comparables(target: Item, items: tuple[Item, ...] | list[Item], config: AnalysisConfig) -> ComparableSet:
    return ComparableIndex(items, config.algorithm_version == "baseline_v1").find(target, config)
