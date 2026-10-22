import hashlib
from dataclasses import asdict
from decimal import Decimal

from tenderlens.analysis import iter_analysis
from tenderlens.models import AnalysisConfig, ValidationReport
from tenderlens.storage import Store
from tenderlens.validation import validate_csv


def import_dataset(store: Store, content: bytes, filename: str, kind: str) -> tuple[int, ValidationReport]:
    report = validate_csv(content, kind)
    dataset_id = store.save_dataset(filename, hashlib.sha256(content).hexdigest(), kind, report)
    return dataset_id, report


def run_analysis(store: Store, dataset_id: int, config: AnalysisConfig) -> int:
    if config.algorithm_version != "median_v1":
        raise ValueError("Базовый метод доступен только в исследовательском эксперименте")
    items = store.items(dataset_id)
    return store.save_run(dataset_id, config, iter_analysis(items, config))


def result_rows(store: Store, run_id: int) -> list[dict]:
    run = store.run(run_id)
    items = {item.item_id: item for item in store.items(run["dataset_id"])}
    reviews = store.reviews(run_id)
    rows = []
    for result in store.results(run_id, include_comparables=False):
        item = items[result.item_id]
        review = reviews.get(result.item_id, {})
        row = item.to_row()
        row.update({key: value for key, value in asdict(result).items() if key != "comparable_item_ids"})
        row["unit_price"] = item.unit_price
        row.update(review_status=review.get("review_status", "unreviewed"), comment=review.get("comment", ""))
        rows.append(row)
    return sorted(rows, key=lambda row: (row["deviation_percent"] is None,
                                        row["deviation_percent"].copy_negate() if row["deviation_percent"] is not None else Decimal(0),
                                        row["item_id"]))
