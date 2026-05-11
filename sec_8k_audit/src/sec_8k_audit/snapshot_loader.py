"""Loads the SQLite production snapshot for audit queries."""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


def load_snapshot(snapshot_db_path: Path) -> sqlite3.Connection:
    """Open snapshot SQLite file in read-only mode.

    Args:
        snapshot_db_path: Path to the .db snapshot file.

    Returns:
        sqlite3.Connection opened in read-only URI mode.

    Raises:
        FileNotFoundError: If snapshot_db_path does not exist.
        sqlite3.OperationalError: If file cannot be opened as SQLite.
    """
    if not snapshot_db_path.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot_db_path}")

    uri = f"file:{snapshot_db_path.resolve()}?mode=ro"
    logger.info("Opening snapshot: %s", uri)
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn
