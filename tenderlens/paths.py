"""Writable local paths shared by the command line and the application."""
import os
from pathlib import Path


def default_db_path() -> Path:
    """Use an explicit environment path or data/app.sqlite3 in the working directory.

    Nothing is resolved relative to the installed package: site-packages may be
    read-only, and running from the project root must keep the existing database.
    """
    configured = os.environ.get("TENDERLENS_DB")
    return Path(configured).expanduser() if configured else Path.cwd() / "data" / "app.sqlite3"
