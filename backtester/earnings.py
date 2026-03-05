"""
Earnings calendar loader for the False Breakout Strategy Backtester.

Pre-loads earnings dates via yfinance, caches to JSON, and provides
lookup methods for the filter chain.

Usage:
    cal = EarningsCalendar(cache_dir="cache")
    cal.load(["AAPL", "TSLA", "NVDA"])
    dates = cal.get_earnings_dates("AAPL")  # set of datetime.date
    cal.as_filter_config()  # dict[str, set] for FilterChainConfig.earnings_dates
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# How many days after earnings to also block (post-earnings volatility)
DEFAULT_POST_EARNINGS_DAYS = 1


def _fetch_earnings_dates(ticker: str) -> list[date]:
    """Fetch historical earnings dates for a ticker via yfinance.

    Returns a list of date objects for each known earnings date.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed; cannot fetch earnings dates")
        return []

    try:
        stock = yf.Ticker(ticker)
        # yfinance exposes earnings_dates as a DataFrame with DatetimeIndex
        ed = stock.earnings_dates
        if ed is None or ed.empty:
            logger.info(f"{ticker}: no earnings dates found via yfinance")
            return []

        dates = sorted(set(d.date() for d in ed.index))
        logger.info(f"{ticker}: fetched {len(dates)} earnings dates")
        return dates
    except Exception as e:
        logger.warning(f"{ticker}: failed to fetch earnings dates: {e}")
        return []


class EarningsCalendar:
    """Manages earnings date lookups with JSON file caching."""

    CACHE_FILENAME = "earnings_cache.json"

    def __init__(self, cache_dir: Optional[str | Path] = None,
                 post_earnings_days: int = DEFAULT_POST_EARNINGS_DAYS):
        """
        Args:
            cache_dir: Directory for the JSON cache file. None = no caching.
            post_earnings_days: Number of days after earnings to also flag.
        """
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.post_earnings_days = post_earnings_days
        # ticker -> set of datetime.date
        self._dates: dict[str, set[date]] = {}

    @property
    def cache_path(self) -> Optional[Path]:
        if self.cache_dir is None:
            return None
        return self.cache_dir / self.CACHE_FILENAME

    def _load_cache(self) -> dict[str, list[str]]:
        """Load cache from JSON file. Returns empty dict if missing/corrupt."""
        if self.cache_path is None or not self.cache_path.exists():
            return {}
        try:
            with open(self.cache_path, "r") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to read earnings cache: {e}")
            return {}

    def _save_cache(self):
        """Persist current dates to JSON cache."""
        if self.cache_path is None:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        data = {}
        for ticker, dates in self._dates.items():
            data[ticker] = sorted(d.isoformat() for d in dates)
        try:
            with open(self.cache_path, "w") as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved earnings cache: {self.cache_path}")
        except OSError as e:
            logger.warning(f"Failed to write earnings cache: {e}")

    def load(self, tickers: list[str], force_refresh: bool = False):
        """Load earnings dates for the given tickers.

        Uses cached data when available. Fetches from yfinance for any
        tickers not in cache (or all if force_refresh=True).

        Args:
            tickers: List of stock symbols.
            force_refresh: If True, ignore cache and re-fetch everything.
        """
        cache = {} if force_refresh else self._load_cache()
        needs_fetch = []

        for ticker in tickers:
            if ticker in cache and not force_refresh:
                self._dates[ticker] = set(
                    date.fromisoformat(d) for d in cache[ticker]
                )
                logger.debug(f"{ticker}: loaded {len(self._dates[ticker])} "
                             f"earnings dates from cache")
            else:
                needs_fetch.append(ticker)

        if needs_fetch:
            logger.info(f"Fetching earnings dates for: {needs_fetch}")
            for ticker in needs_fetch:
                fetched = _fetch_earnings_dates(ticker)
                self._dates[ticker] = set(fetched)

            self._save_cache()

    def get_earnings_dates(self, ticker: str) -> set[date]:
        """Get the set of earnings dates for a ticker.

        Returns an empty set if ticker was not loaded.
        """
        return self._dates.get(ticker, set())

    def is_earnings_day(self, ticker: str, trade_date: date) -> bool:
        """Check if trade_date is an earnings day for the ticker."""
        return trade_date in self._dates.get(ticker, set())

    def is_post_earnings(self, ticker: str, trade_date: date,
                         days: Optional[int] = None) -> bool:
        """Check if trade_date falls within post_earnings_days after an earnings date."""
        if days is None:
            days = self.post_earnings_days
        earnings = self._dates.get(ticker, set())
        from datetime import timedelta
        for ed in earnings:
            delta = (trade_date - ed).days
            if 1 <= delta <= days:
                return True
        return False

    def as_filter_config(self) -> dict[str, set]:
        """Convert to the format expected by FilterChainConfig.earnings_dates.

        Returns dict mapping ticker -> set of pd.Timestamp (normalized).
        The filter chain checks both pd.Timestamp and datetime.date,
        so we provide datetime.date objects which the filter accepts.
        """
        import pandas as pd
        result = {}
        for ticker, dates in self._dates.items():
            # Include both earnings days and post-earnings days
            expanded = set()
            from datetime import timedelta
            for d in dates:
                expanded.add(pd.Timestamp(d).normalize())
                for offset in range(1, self.post_earnings_days + 1):
                    expanded.add(pd.Timestamp(d + timedelta(days=offset)).normalize())
            result[ticker] = expanded
        return result
