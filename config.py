"""Local paths. TENDERLENS_DB allows isolated tests and separate local datasets."""
from pathlib import Path

from tenderlens.paths import default_db_path

ROOT = Path(__file__).resolve().parent
DEMO_PATH = ROOT / "data" / "demo" / "paper_demo.csv"
DB_PATH = default_db_path()
