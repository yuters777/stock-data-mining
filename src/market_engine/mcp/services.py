"""
MCP (Market Context Provider) services.

Provides structured research context for the LLM decision layer by aggregating
data from multiple SQLite-backed tables.  All reads are via open_db().

Downstream consumer of fmp_press_releases at ~line 962 — gracefully handles
empty table (fetcher disabled 2026-05-05).
"""
import logging
from pathlib import Path
from typing import Any

from market_engine.db.connection import open_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper — check table existence
# ---------------------------------------------------------------------------

async def _has_table(db_path: str | Path, table_name: str) -> bool:
    async with open_db(db_path) as db:
        row = await (await db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )).fetchone()
    return bool(row and row[0])


# ---------------------------------------------------------------------------
# Individual context loaders
# ---------------------------------------------------------------------------

async def get_earnings_context(db_path: str | Path, symbol: str) -> list[dict[str, Any]]:
    async with open_db(db_path) as db:
        cur = await db.execute(
            "SELECT date, eps_actual, eps_est, rev_actual, rev_est"
            " FROM fmp_earnings WHERE symbol=? ORDER BY date DESC LIMIT 4",
            (symbol,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def get_analyst_context(db_path: str | Path, symbol: str) -> list[dict[str, Any]]:
    async with open_db(db_path) as db:
        cur = await db.execute(
            "SELECT period, eps_avg, rev_avg FROM fmp_analyst_estimates"
            " WHERE symbol=? ORDER BY period DESC LIMIT 2",
            (symbol,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def get_news_context(db_path: str | Path, symbol: str) -> list[dict[str, Any]]:
    async with open_db(db_path) as db:
        cur = await db.execute(
            "SELECT title, url, published_at FROM fmp_news"
            " WHERE symbol=? ORDER BY published_at DESC LIMIT 5",
            (symbol,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def get_sec_filings_context(db_path: str | Path, symbol: str) -> list[dict[str, Any]]:
    async with open_db(db_path) as db:
        cur = await db.execute(
            "SELECT form_type, filed_at, url FROM fmp_sec_filings"
            " WHERE symbol=? ORDER BY filed_at DESC LIMIT 5",
            (symbol,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def get_insider_context(db_path: str | Path, symbol: str) -> list[dict[str, Any]]:
    async with open_db(db_path) as db:
        cur = await db.execute(
            "SELECT insider, trade_type, shares, price, filed_at FROM fmp_insider_trades"
            " WHERE symbol=? ORDER BY filed_at DESC LIMIT 5",
            (symbol,),
        )
        return [dict(r) for r in await cur.fetchall()]


# ---------------------------------------------------------------------------
# ~line 962 — press_releases corroboration (graceful empty-table handling)
# ---------------------------------------------------------------------------

async def get_press_releases_context(db_path: str | Path, symbol: str) -> list[dict[str, Any]]:
    """
    Return press-release corroboration for a symbol.

    Fetcher disabled 2026-05-05 — table is preserved but will be empty.
    _has_table guard ensures graceful handling even if table is ever dropped.
    Returns empty list (current behaviour) without raising.
    """
    if not await _has_table(db_path, "fmp_press_releases"):
        logger.debug("fmp_press_releases table absent — returning empty corroboration")
        return []
    async with open_db(db_path) as db:
        cur = await db.execute(
            "SELECT title, content, published_at FROM fmp_press_releases"
            " WHERE symbol=? ORDER BY published_at DESC LIMIT 3",
            (symbol,),
        )
        rows = await cur.fetchall()
    if not rows:
        logger.debug("fmp_press_releases empty for %s (expected: fetcher disabled)", symbol)
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Aggregate context builder
# ---------------------------------------------------------------------------

async def build_symbol_context(db_path: str | Path, symbol: str) -> dict[str, Any]:
    """Aggregate all available research context for a symbol."""
    earnings = await get_earnings_context(db_path, symbol)
    analyst = await get_analyst_context(db_path, symbol)
    news = await get_news_context(db_path, symbol)
    filings = await get_sec_filings_context(db_path, symbol)
    insider = await get_insider_context(db_path, symbol)
    press_releases = await get_press_releases_context(db_path, symbol)

    return {
        "symbol": symbol,
        "earnings": earnings,
        "analyst_estimates": analyst,
        "news": news,
        "sec_filings": filings,
        "insider_trades": insider,
        "press_releases": press_releases,
    }
