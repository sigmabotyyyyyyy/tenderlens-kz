"""Transactional persistence. Prices are stored as integer tiyn; derived values as exact strings."""
import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from tenderlens.models import AnalysisConfig, AnalysisResult, Item, ValidationReport


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


def _price_minor(price: Decimal) -> int:
    return int(Fraction(price) * 100)


def _result_from_json(content: str, comparable_ids: Iterable[str]) -> AnalysisResult:
    value = json.loads(content)
    for key in ("reference_price", "ratio", "deviation_percent"):
        value[key] = Decimal(value[key]) if value[key] is not None else None
    value["comparable_item_ids"] = tuple(comparable_ids)
    return AnalysisResult(**value)


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS datasets (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                    file_hash TEXT NOT NULL UNIQUE,
                    dataset_kind TEXT NOT NULL CHECK(dataset_kind IN ('real','synthetic')),
                    imported_at TEXT NOT NULL, accepted_count INTEGER NOT NULL,
                    rejected_count INTEGER NOT NULL, validation_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS items (
                    dataset_id INTEGER NOT NULL, item_id TEXT NOT NULL,
                    unit_price_minor INTEGER NOT NULL CHECK(unit_price_minor > 0),
                    data_json TEXT NOT NULL, PRIMARY KEY(dataset_id,item_id),
                    FOREIGN KEY(dataset_id) REFERENCES datasets(id)
                );
                CREATE TABLE IF NOT EXISTS analysis_runs (
                    id INTEGER PRIMARY KEY, dataset_id INTEGER NOT NULL,
                    algorithm_version TEXT NOT NULL, config_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('completed','failed')),
                    UNIQUE(id,dataset_id), FOREIGN KEY(dataset_id) REFERENCES datasets(id)
                );
                CREATE TABLE IF NOT EXISTS results (
                    run_id INTEGER NOT NULL, dataset_id INTEGER NOT NULL, item_id TEXT NOT NULL,
                    data_json TEXT NOT NULL, PRIMARY KEY(run_id,item_id),
                    UNIQUE(run_id,dataset_id,item_id),
                    FOREIGN KEY(run_id,dataset_id) REFERENCES analysis_runs(id,dataset_id),
                    FOREIGN KEY(dataset_id,item_id) REFERENCES items(dataset_id,item_id)
                );
                CREATE TABLE IF NOT EXISTS result_comparables (
                    run_id INTEGER NOT NULL, dataset_id INTEGER NOT NULL,
                    target_item_id TEXT NOT NULL, comparable_item_id TEXT NOT NULL,
                    PRIMARY KEY(run_id,target_item_id,comparable_item_id),
                    FOREIGN KEY(run_id,dataset_id,target_item_id) REFERENCES results(run_id,dataset_id,item_id),
                    FOREIGN KEY(dataset_id,comparable_item_id) REFERENCES items(dataset_id,item_id)
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    run_id INTEGER NOT NULL, item_id TEXT NOT NULL,
                    review_status TEXT NOT NULL CHECK(review_status IN ('needs_check','explained','unclear')),
                    comment TEXT NOT NULL CHECK(length(comment)<=2000), updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id,item_id), FOREIGN KEY(run_id,item_id) REFERENCES results(run_id,item_id)
                );
            """)
            self._migrate(db)

    @staticmethod
    def _migrate(db: sqlite3.Connection) -> None:
        """Upgrade v1 in one transaction; keep datasets, runs and reviews intact."""
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > 2:
            raise ValueError("База создана более новой версией TenderLens")
        if version == 2:
            return
        db.execute("BEGIN IMMEDIATE")
        item_columns = {row[1] for row in db.execute("PRAGMA table_info(items)")}
        if "item_key" not in item_columns:
            db.execute("ALTER TABLE items ADD COLUMN item_key INTEGER")
            db.execute("UPDATE items SET item_key=rowid")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS items_key ON items(item_key)")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS items_key_dataset ON items(item_key,dataset_id)")
        result_columns = {row[1] for row in db.execute("PRAGMA table_info(results)")}
        if "item_key" not in result_columns:
            db.execute("ALTER TABLE results ADD COLUMN item_key INTEGER")
            db.execute("""UPDATE results SET item_key=(SELECT item_key FROM items
                WHERE items.dataset_id=results.dataset_id AND items.item_id=results.item_id)""")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS results_key ON results(run_id,dataset_id,item_key)")
        link_columns = {row[1] for row in db.execute("PRAGMA table_info(result_comparables)")}
        if "target_item_id" in link_columns:
            db.execute("ALTER TABLE result_comparables RENAME TO result_comparables_legacy")
            db.execute("""CREATE TABLE result_comparables (
                run_id INTEGER NOT NULL, dataset_id INTEGER NOT NULL,
                target_item_key INTEGER NOT NULL, comparable_item_key INTEGER NOT NULL,
                PRIMARY KEY(run_id,target_item_key,comparable_item_key),
                FOREIGN KEY(run_id,dataset_id,target_item_key) REFERENCES results(run_id,dataset_id,item_key),
                FOREIGN KEY(comparable_item_key,dataset_id) REFERENCES items(item_key,dataset_id)
            ) WITHOUT ROWID""")
            db.execute("""INSERT INTO result_comparables
                SELECT old.run_id,old.dataset_id,target.item_key,comparable.item_key
                FROM result_comparables_legacy old
                JOIN items target ON target.dataset_id=old.dataset_id AND target.item_id=old.target_item_id
                JOIN items comparable ON comparable.dataset_id=old.dataset_id AND comparable.item_id=old.comparable_item_id""")
            old_count = db.execute("SELECT count(*) FROM result_comparables_legacy").fetchone()[0]
            new_count = db.execute("SELECT count(*) FROM result_comparables").fetchone()[0]
            if old_count != new_count:
                raise ValueError("Миграция остановлена: не удалось восстановить все связи аналогов")
            db.execute("DROP TABLE result_comparables_legacy")
        db.execute("PRAGMA user_version=2")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def datasets(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM datasets ORDER BY id DESC")]

    def dataset(self, dataset_id: int) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
            if row is None:
                raise ValueError("Набор данных не найден")
            return dict(row)

    def save_dataset(self, name: str, digest: str, kind: str, report: ValidationReport) -> int:
        if not report.items:
            raise ValueError("Нет корректных строк: набор не сохранён")
        with self.connect() as db:
            existing = db.execute("SELECT id,dataset_kind FROM datasets WHERE file_hash=?", (digest,)).fetchone()
            if existing:
                if existing["dataset_kind"] != kind:
                    raise ValueError("Этот файл уже загружен с другим типом набора. Изменять маркировку нельзя.")
                return existing["id"]
            summary = {"errors": [asdict(error) for error in report.errors], "warnings": report.warnings}
            dataset_id = db.execute(
                "INSERT INTO datasets(name,file_hash,dataset_kind,imported_at,accepted_count,rejected_count,validation_json) VALUES(?,?,?,?,?,?,?)",
                (name, digest, kind, _now(), len(report.items), len(report.errors), _json(summary)),
            ).lastrowid
            next_key = db.execute("SELECT coalesce(max(item_key),0)+1 FROM items").fetchone()[0]
            db.executemany("INSERT INTO items(dataset_id,item_id,unit_price_minor,data_json,item_key) VALUES(?,?,?,?,?)", (
                (dataset_id, item.item_id, _price_minor(item.unit_price), _json(item.to_row()), next_key + index)
                for index, item in enumerate(report.items)
            ))
            return dataset_id

    def items(self, dataset_id: int) -> tuple[Item, ...]:
        with self.connect() as db:
            rows = db.execute("SELECT data_json FROM items WHERE dataset_id=? ORDER BY item_id", (dataset_id,))
            return tuple(Item.from_row(json.loads(row[0])) for row in rows)

    def save_run(self, dataset_id: int, config: AnalysisConfig, results: Iterable[AnalysisResult]) -> int:
        with self.connect() as db:
            keys = {row["item_id"]: row["item_key"] for row in db.execute(
                "SELECT item_id,item_key FROM items WHERE dataset_id=?", (dataset_id,))}
            if not keys:
                raise ValueError("Нет позиций для анализа")
            run_id = db.execute(
                "INSERT INTO analysis_runs(dataset_id,algorithm_version,config_json,created_at,state) VALUES(?,?,?,?,?)",
                (dataset_id, config.algorithm_version, _json(config.to_dict()), _now(), "completed"),
            ).lastrowid
            seen = set()
            for result in results:
                if result.item_id not in keys or result.item_id in seen:
                    raise ValueError("Запуск должен содержать по одному результату для каждой позиции набора")
                seen.add(result.item_id)
                # Relations are the only persisted copy of the comparable IDs.
                metadata = {key: getattr(result, key) for key in result.__dataclass_fields__
                            if key != "comparable_item_ids"}
                target_key = keys[result.item_id]
                db.execute("INSERT INTO results(run_id,dataset_id,item_id,data_json,item_key) VALUES(?,?,?,?,?)",
                           (run_id, dataset_id, result.item_id, _json(metadata), target_key))
                db.executemany("INSERT INTO result_comparables VALUES(?,?,?,?)", (
                    (run_id, dataset_id, target_key, keys.get(comparable_id, -1))
                    for comparable_id in result.comparable_item_ids
                ))
            if seen != keys.keys():
                raise ValueError("Запуск должен содержать по одному результату для каждой позиции набора")
            return run_id

    def runs(self, dataset_id: int) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM analysis_runs WHERE dataset_id=? ORDER BY id DESC", (dataset_id,))]

    def run(self, run_id: int) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM analysis_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise ValueError("Запуск не найден")
            return dict(row)

    def results(self, run_id: int, include_comparables: bool = True) -> tuple[AnalysisResult, ...]:
        with self.connect() as db:
            links = defaultdict(list)
            if include_comparables:
                for row in db.execute("""SELECT links.target_item_key,items.item_id FROM result_comparables links
                    JOIN items ON items.item_key=links.comparable_item_key
                    WHERE links.run_id=? ORDER BY links.target_item_key,items.item_id""", (run_id,)):
                    links[row[0]].append(row[1])
            return tuple(_result_from_json(row["data_json"], links[row["item_key"]]) for row in db.execute(
                "SELECT data_json,item_key FROM results WHERE run_id=? ORDER BY item_id", (run_id,)))

    def result(self, run_id: int, item_id: str) -> AnalysisResult:
        """Load full evidence for one card instead of every target in the run."""
        with self.connect() as db:
            row = db.execute("SELECT data_json,item_key FROM results WHERE run_id=? AND item_id=?", (run_id, item_id)).fetchone()
            if row is None:
                raise ValueError("Позиция отсутствует в этом запуске")
            links = (link[0] for link in db.execute("""SELECT items.item_id FROM result_comparables links
                JOIN items ON items.item_key=links.comparable_item_key
                WHERE links.run_id=? AND links.target_item_key=? ORDER BY items.item_id""", (run_id, row["item_key"])))
            return _result_from_json(row["data_json"], links)

    def reviews(self, run_id: int) -> dict[str, dict]:
        with self.connect() as db:
            return {row["item_id"]: dict(row) for row in db.execute("SELECT * FROM reviews WHERE run_id=?", (run_id,))}

    def save_review(self, run_id: int, item_id: str, status: str, comment: str) -> None:
        if status not in ("needs_check", "explained", "unclear"):
            raise ValueError("Неизвестный статус ручной проверки")
        if len(comment) > 2000:
            raise ValueError("Комментарий должен содержать не более 2000 символов")
        with self.connect() as db:
            exists = db.execute("SELECT 1 FROM results WHERE run_id=? AND item_id=?", (run_id, item_id)).fetchone()
            if not exists:
                raise ValueError("Позиция отсутствует в этом запуске")
            db.execute("""INSERT INTO reviews VALUES(?,?,?,?,?)
                ON CONFLICT(run_id,item_id) DO UPDATE SET
                review_status=excluded.review_status,comment=excluded.comment,updated_at=excluded.updated_at""",
                (run_id, item_id, status, comment, _now()))
