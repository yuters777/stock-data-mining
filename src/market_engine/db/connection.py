"""
SQLite connection helper.  All production code must use open_db() or get_db()
rather than calling aiosqlite.connect() directly.  This module is the single
authorised call-site; see tests/architecture/test_sqlite_connection_consistency.py.
"""
import contextlib
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

# 7 production PRAGMAs applied to every connection.
_PRAGMAS: tuple[str, ...] = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA busy_timeout=5000",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA cache_size=-32000",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA foreign_keys=ON",
    "PRAGMA mmap_size=134217728",
)


async def _apply_pragmas(db: aiosqlite.Connection) -> None:
    for pragma in _PRAGMAS:
        await db.execute(pragma)


@contextlib.asynccontextmanager
async def open_db(path: str | Path) -> AsyncIterator[aiosqlite.Connection]:
    """Async context-manager that yields a fully-configured aiosqlite connection."""
    async with aiosqlite.connect(str(path)) as db:
        db.row_factory = aiosqlite.Row
        await _apply_pragmas(db)
        yield db


async def get_db(path: str | Path) -> aiosqlite.Connection:
    """Return a fully-configured aiosqlite connection (caller manages lifecycle)."""
    db = await aiosqlite.connect(str(path))
    db.row_factory = aiosqlite.Row
    await _apply_pragmas(db)
    return db
