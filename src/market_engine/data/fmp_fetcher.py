"""
FMP (Financial Modeling Prep) data fetcher.

Fetches research data for the watchlist and writes results to the SQLite DB.
Entry point: run_category_fetchers(db_path, symbols) — iterates _CATEGORY_FETCHERS.
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine

from market_engine.db.connection import open_db

logger = logging.getLogger(__name__)

FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
_FMP_API_KEY = os.environ.get("FMP_API_KEY", "")

# ---------------------------------------------------------------------------
# HTTP helper (stdlib only, no aiohttp dependency in this module)
# ---------------------------------------------------------------------------

async def _fmp_get(path: str, params: dict[str, str] | None = None) -> Any:
    """Minimal async FMP GET — wraps urllib in executor to avoid aiohttp dep."""
    import urllib.parse
    import urllib.request

    qp = urllib.parse.urlencode({**(params or {}), "apikey": _FMP_API_KEY})
    url = f"{FMP_BASE_URL}{path}?{qp}"
    loop = asyncio.get_event_loop()

    def _fetch() -> bytes:
        with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310
            return resp.read()

    raw = await loop.run_in_executor(None, _fetch)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Per-category fetch functions
# ---------------------------------------------------------------------------

async def _fetch_earnings(db_path: str | Path, symbols: list[str]) -> int:
    """Fetch latest earnings and upsert into fmp_earnings."""
    fetched = 0
    for symbol in symbols:
        try:
            data = await _fmp_get(f"/earnings/{symbol}", {"limit": "4"})
            if not isinstance(data, list):
                continue
            async with open_db(db_path) as db:
                for row in data:
                    await db.execute(
                        "INSERT OR REPLACE INTO fmp_earnings"
                        " (symbol, date, eps_actual, eps_est, rev_actual, rev_est)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            symbol,
                            row.get("date"),
                            row.get("eps"),
                            row.get("epsEstimated"),
                            row.get("revenue"),
                            row.get("revenueEstimated"),
                        ),
                    )
                await db.commit()
            fetched += len(data)
        except Exception:
            logger.exception("earnings fetch failed for %s", symbol)
    return fetched


async def _fetch_analyst_estimates(db_path: str | Path, symbols: list[str]) -> int:
    """Fetch analyst estimates and upsert into fmp_analyst_estimates."""
    fetched = 0
    for symbol in symbols:
        try:
            data = await _fmp_get(f"/analyst-estimates/{symbol}", {"period": "annual", "limit": "2"})
            if not isinstance(data, list):
                continue
            async with open_db(db_path) as db:
                for row in data:
                    await db.execute(
                        "INSERT OR REPLACE INTO fmp_analyst_estimates"
                        " (symbol, period, eps_avg, rev_avg)"
                        " VALUES (?, ?, ?, ?)",
                        (
                            symbol,
                            row.get("period"),
                            row.get("estimatedEpsAvg"),
                            row.get("estimatedRevenueAvg"),
                        ),
                    )
                await db.commit()
            fetched += len(data)
        except Exception:
            logger.exception("analyst estimates fetch failed for %s", symbol)
    return fetched


async def _fetch_news(db_path: str | Path, symbols: list[str]) -> int:
    """Fetch company news and insert into fmp_news."""
    fetched = 0
    for symbol in symbols:
        try:
            data = await _fmp_get("/stock_news", {"tickers": symbol, "limit": "10"})
            if not isinstance(data, list):
                continue
            async with open_db(db_path) as db:
                for row in data:
                    await db.execute(
                        "INSERT OR IGNORE INTO fmp_news (symbol, title, url, published_at)"
                        " VALUES (?, ?, ?, ?)",
                        (symbol, row.get("title"), row.get("url"), row.get("publishedDate")),
                    )
                await db.commit()
            fetched += len(data)
        except Exception:
            logger.exception("news fetch failed for %s", symbol)
    return fetched


async def _fetch_sec_filings(db_path: str | Path, symbols: list[str]) -> int:
    """Fetch SEC filings and insert into fmp_sec_filings."""
    fetched = 0
    for symbol in symbols:
        try:
            data = await _fmp_get(f"/sec_filings/{symbol}", {"limit": "5"})
            if not isinstance(data, list):
                continue
            async with open_db(db_path) as db:
                for row in data:
                    await db.execute(
                        "INSERT OR IGNORE INTO fmp_sec_filings"
                        " (symbol, form_type, filed_at, url)"
                        " VALUES (?, ?, ?, ?)",
                        (symbol, row.get("type"), row.get("fillingDate"), row.get("link")),
                    )
                await db.commit()
            fetched += len(data)
        except Exception:
            logger.exception("sec filings fetch failed for %s", symbol)
    return fetched


async def _fetch_insider_trades(db_path: str | Path, symbols: list[str]) -> int:
    """Fetch insider trades and insert into fmp_insider_trades."""
    fetched = 0
    for symbol in symbols:
        try:
            data = await _fmp_get(f"/insider-trading", {"symbol": symbol, "limit": "10"})
            if not isinstance(data, list):
                continue
            async with open_db(db_path) as db:
                for row in data:
                    await db.execute(
                        "INSERT OR IGNORE INTO fmp_insider_trades"
                        " (symbol, insider, trade_type, shares, price, filed_at)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            symbol,
                            row.get("reportingName"),
                            row.get("transactionType"),
                            row.get("securitiesTransacted"),
                            row.get("price"),
                            row.get("filingDate"),
                        ),
                    )
                await db.commit()
            fetched += len(data)
        except Exception:
            logger.exception("insider trades fetch failed for %s", symbol)
    return fetched


async def _fetch_press_releases(db_path: str | Path, symbols: list[str]) -> int:
    """
    Fetch press releases and insert into fmp_press_releases.

    PRESERVED for future revival — function is NOT called at runtime.
    Category removed from _CATEGORY_FETCHERS on 2026-05-05: FMP endpoint
    returns HTTP 404 for all 27 watchlist tickers (Day-47 diagnostic +
    multiple cron log evidence).  Re-enable by adding "press_releases" back
    to _CATEGORY_FETCHERS once FMP restores or migrates the endpoint.
    fmp_press_releases TABLE is preserved (mcp/services.py reads it gracefully).
    """
    fetched = 0
    for symbol in symbols:
        try:
            data = await _fmp_get(f"/press-releases/{symbol}", {"limit": "5"})
            if not isinstance(data, list):
                continue
            async with open_db(db_path) as db:
                for row in data:
                    await db.execute(
                        "INSERT OR IGNORE INTO fmp_press_releases"
                        " (symbol, title, content, published_at)"
                        " VALUES (?, ?, ?, ?)",
                        (symbol, row.get("title"), row.get("text"), row.get("date")),
                    )
                await db.commit()
            fetched += len(data)
        except Exception:
            logger.exception("press releases fetch failed for %s", symbol)
    return fetched


# ---------------------------------------------------------------------------
# Category registry
#
# NOTE: 2026-05-05 — press_releases category disabled. FMP endpoint returns
# HTTP 404 for all 27 watchlist tickers (verified Day 47 diagnostic + multiple
# cron log evidence). Function _fetch_press_releases preserved below for future
# revival when FMP restores or migrates endpoint. fmp_press_releases TABLE also
# preserved (mcp/services.py:962 gracefully handles empty corroboration).
# ---------------------------------------------------------------------------

FetcherFn = Callable[[str | Path, list[str]], Coroutine[Any, Any, int]]

_CATEGORY_FETCHERS: dict[str, FetcherFn] = {
    "earnings":           _fetch_earnings,
    "analyst_estimates":  _fetch_analyst_estimates,
    "news":               _fetch_news,
    "sec_filings":        _fetch_sec_filings,
    "insider_trades":     _fetch_insider_trades,
    # "press_releases": _fetch_press_releases,  # disabled 2026-05-05: FMP 404s
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run_category_fetchers(db_path: str | Path, symbols: list[str]) -> dict[str, int]:
    """Run all active category fetchers and return per-category row counts."""
    results: dict[str, int] = {}
    fetched_categories: list[str] = []

    for category, fetcher in _CATEGORY_FETCHERS.items():
        logger.info("fetching category=%s for %d symbols", category, len(symbols))
        try:
            count = await fetcher(db_path, symbols)
            results[category] = count
            fetched_categories.append(category)
        except Exception:
            logger.exception("category fetcher %s raised unexpectedly", category)
            results[category] = -1

    logger.info("fetched_categories=%r total_rows=%d", fetched_categories, sum(v for v in results.values() if v >= 0))
    return results
