"""
Nightly health-check tool.

Runs post-market diagnostic pass over the DB + FMP category refresh.
Entry point: run_health_check(db_path, symbols, dry_run=False)
"""
import asyncio
import logging
from pathlib import Path
from typing import Any

from market_engine.data.fmp_fetcher import _CATEGORY_FETCHERS, run_category_fetchers
from market_engine.db.connection import open_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional categories — fetched if present in _CATEGORY_FETCHERS but failures
# do not abort the health check.
# NOTE: "press_releases" removed 2026-05-05 — category no longer registered
# in _CATEGORY_FETCHERS (FMP endpoint returns 404 for all watchlist tickers).
# ---------------------------------------------------------------------------

_FMP_OPTIONAL_CATEGORIES: frozenset[str] = frozenset({
    "news",
    "sec_filings",
    "insider_trades",
    "analyst_estimates",
})

_FMP_REQUIRED_CATEGORIES: frozenset[str] = frozenset({
    "earnings",
})


# ---------------------------------------------------------------------------
# DB diagnostic helpers
# ---------------------------------------------------------------------------

async def _check_table_counts(db_path: str | Path) -> dict[str, int]:
    async with open_db(db_path) as db:
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in await cur.fetchall()]
        counts: dict[str, int] = {}
        for table in tables:
            row = await (await db.execute(f"SELECT COUNT(*) FROM {table}")).fetchone()  # noqa: S608
            counts[table] = row[0] if row else 0
    return counts


async def _check_wal_health(db_path: str | Path) -> dict[str, Any]:
    async with open_db(db_path) as db:
        row = await (await db.execute("PRAGMA wal_checkpoint(PASSIVE)")).fetchone()
        journal = await (await db.execute("PRAGMA journal_mode")).fetchone()
    return {
        "journal_mode": journal[0] if journal else None,
        "wal_busy": row[0] if row else None,
        "wal_log": row[1] if row else None,
        "wal_checkpointed": row[2] if row else None,
    }


# ---------------------------------------------------------------------------
# Health-check orchestration
# ---------------------------------------------------------------------------

async def run_health_check(
    db_path: str | Path,
    symbols: list[str],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run full nightly health check.  Returns structured results dict."""
    logger.info("health_check start dry_run=%s symbols=%d", dry_run, len(symbols))
    results: dict[str, Any] = {}

    table_counts = await _check_table_counts(db_path)
    results["table_counts"] = table_counts
    logger.info("table_counts=%r", table_counts)

    wal = await _check_wal_health(db_path)
    results["wal"] = wal
    logger.info("wal=%r", wal)

    if dry_run:
        logger.info("dry_run=True — skipping FMP category fetches")
        results["fetched_categories"] = {}
        return results

    active_categories = set(_CATEGORY_FETCHERS)
    logger.info("active_categories=%r", sorted(active_categories))

    fetch_results = await run_category_fetchers(db_path, symbols)
    results["fetched_categories"] = fetch_results

    for cat in _FMP_REQUIRED_CATEGORIES:
        if fetch_results.get(cat, -1) < 0:
            logger.error("required category %s failed in health check", cat)

    for cat in _FMP_OPTIONAL_CATEGORIES:
        if cat in fetch_results and fetch_results[cat] < 0:
            logger.warning("optional category %s failed (non-fatal)", cat)

    logger.info("health_check complete results=%r", results)
    return results
