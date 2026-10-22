"""Command-line analysis that also works from an installed wheel."""
import argparse
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Sequence

from tenderlens.analysis import explain
from tenderlens.demo import demo_items, items_csv
from tenderlens.export import export_errors, export_results
from tenderlens.models import AnalysisConfig, ValidationReport
from tenderlens.paths import default_db_path
from tenderlens.service import import_dataset, result_rows, run_analysis
from tenderlens.storage import Store
from tenderlens.validation import MAX_BYTES, validate_csv


def _path(value: str) -> Path:
    if not value.strip():
        raise argparse.ArgumentTypeError("Путь не должен быть пустым")
    return Path(value).expanduser()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="TenderLens KZ — анализ ценовых отклонений",
        epilog="База по умолчанию: TENDERLENS_DB или data/app.sqlite3 в текущей папке.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Проанализировать синтетический пример")
    analyze = sub.add_parser("analyze", help="Проанализировать собственный CSV")
    analyze.add_argument("file", type=_path)
    analyze.add_argument("--kind", choices=("synthetic", "real"), required=True)
    for command in (demo, analyze):
        command.add_argument("--db", type=_path,
                             help="Файл SQLite (по умолчанию TENDERLENS_DB или ./data/app.sqlite3)")
        command.add_argument("--output", type=_path, help="Сохранить результаты в CSV с BOM")
        command.add_argument("--errors", type=_path, help="Сохранить ошибки строк в CSV с BOM")
        command.add_argument("--window", type=int, default=180, help="Окно анализа, 30–365 дней")
        command.add_argument("--min-contracts", type=int, default=20, help="Минимум договоров, 5–100")
        command.add_argument("--threshold", default="1.50", help="Порог отношения цен, 1.10–5.00")
    return parser


def _check_output_paths(args: argparse.Namespace, db_path: Path) -> None:
    """Never let an export replace the input, the database, or another export."""
    protected = {db_path.resolve()}
    if args.command == "analyze":
        protected.add(args.file.resolve())
    for output in (args.output, args.errors):
        if output is None:
            continue
        resolved = output.resolve()
        if resolved in protected:
            raise ValueError("Пути входного CSV, базы и файлов экспорта должны различаться")
        protected.add(resolved)


def _write_export(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _print_errors(report: ValidationReport) -> None:
    for error in report.errors:
        print(f"Строка {error.row_number}, {error.item_id}: {error.reason}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        config = AnalysisConfig(args.window, args.min_contracts, args.threshold)
        db_path = args.db if args.db is not None else default_db_path()
        _check_output_paths(args, db_path)
        kind = "synthetic" if args.command == "demo" else args.kind
        if args.command == "demo":
            content, filename = items_csv(demo_items()), "paper_demo.csv"
        else:
            with args.file.open("rb") as source:
                content = source.read(MAX_BYTES + 1)
            filename = args.file.name
        # Report all-invalid input as well, without creating an empty database.
        report = validate_csv(content, kind)
        for warning in report.warnings:
            print(f"Предупреждение: {warning}")
        if args.errors:
            _write_export(args.errors, export_errors(report))
        if not report.items:
            _print_errors(report)
            raise ValueError("Нет корректных строк: набор не сохранён")
        store = Store(db_path)
        dataset_id, report = import_dataset(store, content, filename, kind)
        run_id = run_analysis(store, dataset_id, config)
        results = store.results(run_id, include_comparables=False)
        if kind == "synthetic":
            print("СИНТЕТИЧЕСКИЕ ДАННЫЕ — вымышленные закупки и организации")
        print(f"Набор {dataset_id}, запуск {run_id}. Принято: {len(report.items)}, отклонено: {len(report.errors)}")
        counts = Counter(result.status for result in results)
        print({status: counts[status] for status in ("flagged", "not_flagged", "insufficient_data")})
        for result in results:
            if result.status == "flagged" or result.item_id in ("TARGET-NORMAL", "TARGET-PACK250"):
                print(f"{result.item_id}: {explain(result, config)}")
        _print_errors(report)
        if args.output:
            _write_export(args.output, export_results(result_rows(store, run_id), dataset_id, run_id, config))
            print(f"Экспорт: {args.output}")
        if args.errors:
            print(f"Ошибки импорта: {args.errors}")
        return 0
    except sqlite3.Error as exc:
        parser.error(f"Ошибка SQLite ({db_path}): {exc}")
    except (ValueError, OSError) as exc:
        parser.error(f"Ошибка: {exc}")
