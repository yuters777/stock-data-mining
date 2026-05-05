"""
Debug HTTP server — exposes read-heavy diagnostic routes for local inspection.

DB access uses get_db() from market_engine.db.connection.
Wave 5b: migrated 1 raw connect call-site (db-stats handler) to get_db().
"""
import json
import logging
from typing import Any

from market_engine.db.connection import get_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Route: GET /debug/db/stats  (~line 42)
# ---------------------------------------------------------------------------

async def handle_db_stats(app: dict[str, Any]) -> dict[str, Any]:
    """Return SQLite page-count, page-size, and WAL info."""
    db = await get_db(app["db_path"])
    try:
        stats: dict[str, Any] = {}
        for pragma in ("page_count", "page_size", "freelist_count", "journal_mode"):
            row = await (await db.execute(f"PRAGMA {pragma}")).fetchone()
            stats[pragma] = row[0] if row else None
        wal_row = await (await db.execute("PRAGMA wal_checkpoint(PASSIVE)")).fetchone()
        stats["wal_checkpoint"] = dict(zip(["busy", "log", "checkpointed"], wal_row or []))
    finally:
        await db.close()
    return stats


# ---------------------------------------------------------------------------
# Route: GET /debug/db/tables
# ---------------------------------------------------------------------------

async def handle_db_tables(app: dict[str, Any]) -> list[dict[str, Any]]:
    """Return list of all tables with approximate row counts."""
    db = await get_db(app["db_path"])
    try:
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in await cur.fetchall()]
        result = []
        for table in tables:
            cnt_row = await (await db.execute(f"SELECT COUNT(*) FROM {table}")).fetchone()  # noqa: S608
            result.append({"table": table, "row_count": cnt_row[0] if cnt_row else 0})
    finally:
        await db.close()
    return result


# ---------------------------------------------------------------------------
# Route: GET /debug/db/recent_events
# ---------------------------------------------------------------------------

async def handle_recent_events(app: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    """Return the N most recent trade events for debugging."""
    db = await get_db(app["db_path"])
    try:
        cur = await db.execute(
            "SELECT id, symbol, event_type, payload, received_at FROM trade_events"
            " ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Simple dispatcher
# ---------------------------------------------------------------------------

_HANDLERS = {
    "/debug/db/stats": handle_db_stats,
    "/debug/db/tables": handle_db_tables,
    "/debug/db/recent_events": handle_recent_events,
}


async def dispatch_debug(path: str, app: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    handler = _HANDLERS.get(path)
    if handler is None:
        return 404, {"error": "not_found"}
    try:
        result = await handler(app)
        return 200, {"data": result}
    except Exception as exc:
        logger.exception("debug route %s failed", path)
        return 500, {"error": str(exc)}
