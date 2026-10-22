"""Deterministic synthetic examples; no real organizations or procurement IDs."""
import csv
import io
import json
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from tenderlens.models import CSV_FIELDS, Item

SEED = 70  # Reserved in report metadata; this fixture is entirely deterministic.


def demo_items() -> tuple[Item, ...]:
    base = Item("HIST-001", "DEMO-CONTRACT-001", date(2025, 1, 1), "DEMO-BUYER-01",
                "DEMO-SUPPLIER-01", "Бумага офисная A4, 80 г/м², 500 листов",
                "A4", 80, 500, "pack", 100, Decimal("1800.00"), "KZT",
                "included", "included", "DEMO-REGION-01")
    items = [replace(base, item_id=f"HIST-{i+1:03}", contract_id=f"DEMO-CONTRACT-{i+1:03}",
                     contract_date=base.contract_date + timedelta(days=i),
                     buyer_id=f"DEMO-BUYER-{i % 4 + 1:02}", supplier_id=f"DEMO-SUPPLIER-{i % 6 + 1:02}")
             for i in range(20)]
    # Two rows of the same contract are one comparison, not two votes.
    items.append(replace(items[0], item_id="HIST-REPEAT"))
    target = replace(base, contract_date=date(2025, 2, 1), contract_id="DEMO-TARGET")
    scenarios = [
        ("TARGET-HIGH", {"unit_price": Decimal("3000.00")}),
        ("TARGET-NORMAL", {}),
        ("TARGET-BOUNDARY", {"unit_price": Decimal("2700.00")}),
        ("TARGET-BELOW", {"unit_price": Decimal("2699.99")}),
        ("TARGET-PACK250", {"sheets_per_pack": 250, "unit_price": Decimal("3000.00"),
                            "product_name": "Бумага A4, 80 г/м², 250 листов"}),
        ("TARGET-REGION", {"delivery_region": "DEMO-REGION-02"}),
        ("TARGET-DENSITY", {"density_g_m2": 90, "product_name": "Бумага A4, 90 г/м², 500 листов"}),
        ("OTHER-VAT", {"vat_basis": "excluded"}),
        ("OTHER-DELIVERY", {"delivery_basis": "excluded"}),
        ("OTHER-FORMAT", {"paper_format": "A3", "product_name": "Бумага A3, 80 г/м², 500 листов"}),
        ("OTHER-QUANTITY", {"quantity": 10000, "unit_price": Decimal("99000.00")}),
        ("FUTURE-HIGH", {"contract_date": date(2025, 3, 1), "unit_price": Decimal("50000.00")}),
    ]
    for item_id, overrides in scenarios:
        items.append(replace(target, item_id=item_id, contract_id="DEMO-" + item_id, **overrides))
    return tuple(items)


def items_csv(items: tuple[Item, ...] | list[Item]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerows(item.to_row() for item in items)
    return buffer.getvalue().encode("utf-8")


def write_demo(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    content = items_csv(demo_items())
    (destination / "paper_demo.csv").write_bytes(content)
    # These expected values are hand-specified, never obtained by calling the algorithm.
    expected = {
        "dataset_kind": "synthetic", "seed": SEED, "rows": 33,
        "explanation": "20 исторических договоров по 1800; цели датированы одним днём; дубликат договора имеет ту же цену",
        "items": {
            "TARGET-HIGH": {"status": "flagged", "reference_price": "1800.00", "comparable_contracts_count": 20, "display_deviation": "+66.7%"},
            "TARGET-NORMAL": {"status": "not_flagged", "reference_price": "1800.00", "comparable_contracts_count": 20},
            "TARGET-BOUNDARY": {"status": "flagged", "reference_price": "1800.00", "comparable_contracts_count": 20},
            "TARGET-BELOW": {"status": "not_flagged", "reference_price": "1800.00", "comparable_contracts_count": 20},
            "TARGET-PACK250": {"status": "insufficient_data", "reference_price": None, "comparable_contracts_count": 0},
            "TARGET-REGION": {"status": "insufficient_data", "reference_price": None, "comparable_contracts_count": 0},
            "TARGET-DENSITY": {"status": "insufficient_data", "reference_price": None, "comparable_contracts_count": 0},
        },
    }
    (destination / "expected_results.json").write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n")
    invalid = io.StringIO(newline="")
    writer = csv.DictWriter(invalid, fieldnames=CSV_FIELDS)
    writer.writeheader()
    row = demo_items()[0].to_row()
    writer.writerow(row)
    for item_id, overrides in [
        ("BAD-ZERO", {"unit_price": "0"}), ("BAD-DATE", {"contract_date": "2025-02-30"}),
        ("BAD-VAT", {"vat_basis": "unknown"}), ("DUPLICATE", {}), ("DUPLICATE", {"unit_price": "9999"}),
    ]:
        writer.writerow(dict(row, item_id=item_id, **overrides))
    (destination / "paper_invalid.csv").write_text(invalid.getvalue(), encoding="utf-8")
