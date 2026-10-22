import csv
import io
from dataclasses import asdict
from decimal import Decimal

from tenderlens.models import AnalysisConfig, CSV_FIELDS, ValidationReport

RESULT_FIELDS = (*CSV_FIELDS, "status", "reference_price", "ratio", "deviation_percent",
                 "comparable_contracts_count", "review_status", "comment", "dataset_id", "run_id",
                 "algorithm_version", "window_days", "min_comparable_contracts", "price_ratio_threshold",
                 "quantity_min_ratio", "quantity_max_ratio")


def _safe(value):
    if value is None:
        return ""
    if isinstance(value, str) and (value.startswith(("\t", "\r", "\n"))
                                   or value.lstrip().startswith(("=", "+", "-", "@"))):
        return "'" + value
    return value


def _csv(rows: list[dict], fields) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _safe(value) for key, value in row.items()})
    return buffer.getvalue().encode("utf-8-sig")


def export_errors(report: ValidationReport) -> bytes:
    return _csv([asdict(error) for error in report.errors], ("row_number", "item_id", "reason"))


def export_results(rows: list[dict], dataset_id: int, run_id: int, config: AnalysisConfig) -> bytes:
    params = asdict(config)
    return _csv([dict(row, dataset_id=dataset_id, run_id=run_id, **params) for row in rows], RESULT_FIELDS)
