"""
Earnings Filter Module.

Checks earnings calendar to filter trades based on v3.4 specification.
Trading should be blocked on earnings days to avoid unpredictable volatility.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class EarningsCheckResult:
    """Result of an earnings check."""

    blocked: bool
    reason: str
    next_earnings: Optional[pd.Timestamp]
    days_until: Optional[int] = None
    ticker: Optional[str] = None

    def __str__(self) -> str:
        """Human-readable representation."""
        status = "BLOCKED" if self.blocked else "OK"
        return f"[{status}] {self.reason}"


class EarningsFilter:
    """
    Filter trades based on earnings calendar (v3.4 specification).

    Uses yfinance to fetch earnings dates and determines if trading
    should be blocked based on proximity to earnings announcements.
    """

    # Days before earnings to issue warning
    WARNING_DAYS: int = 1

    # Days after earnings to potentially block (optional)
    POST_EARNINGS_DAYS: int = 0

    def __init__(self, cache_hours: int = 24):
        """
        Initialize EarningsFilter.

        Args:
            cache_hours: Hours to cache earnings data.
        """
        self._cache: Dict[str, tuple] = {}
        self._cache_hours = cache_hours

    def _get_cached_earnings(
        self, ticker: str
    ) -> Optional[pd.DataFrame]:
        """Get cached earnings data if still valid."""
        if ticker not in self._cache:
            return None

        data, timestamp = self._cache[ticker]
        age_hours = (datetime.now() - timestamp).total_seconds() / 3600

        if age_hours > self._cache_hours:
            del self._cache[ticker]
            return None

        return data

    def _fetch_earnings(self, ticker: str) -> Optional[pd.DataFrame]:
        """
        Fetch earnings dates from yfinance.

        Args:
            ticker: Stock symbol.

        Returns:
            DataFrame with earnings dates or None if unavailable.
        """
        try:
            import yfinance as yf

            stock = yf.Ticker(ticker)
            earnings_dates = stock.earnings_dates

            if earnings_dates is not None and not earnings_dates.empty:
                self._cache[ticker] = (earnings_dates, datetime.now())
                return earnings_dates

            return None

        except Exception as e:
            logger.warning(f"Error fetching earnings for {ticker}: {e}")
            return None

    def check_earnings_conflict(
        self,
        ticker: str,
        check_date: Optional[pd.Timestamp] = None,
    ) -> EarningsCheckResult:
        """
        Check if trading should be blocked due to earnings.

        Args:
            ticker: Stock symbol.
            check_date: Date to check (defaults to today).

        Returns:
            EarningsCheckResult with blocking status and details.
        """
        ticker = ticker.upper()

        if check_date is None:
            check_date = pd.Timestamp.now().normalize()
        elif isinstance(check_date, (str, datetime)):
            check_date = pd.Timestamp(check_date).normalize()

        # Try cache first
        earnings_dates = self._get_cached_earnings(ticker)

        # Fetch if not cached
        if earnings_dates is None:
            earnings_dates = self._fetch_earnings(ticker)

        if earnings_dates is None or earnings_dates.empty:
            return EarningsCheckResult(
                blocked=False,
                reason="No earnings data available",
                next_earnings=None,
                ticker=ticker,
            )

        # Find upcoming earnings (including today)
        try:
            upcoming = earnings_dates[earnings_dates.index >= check_date]
            upcoming = upcoming.head(2)  # Get next 2 earnings dates
        except Exception as e:
            logger.warning(f"Error processing earnings dates for {ticker}: {e}")
            return EarningsCheckResult(
                blocked=False,
                reason=f"Error processing earnings: {str(e)}",
                next_earnings=None,
                ticker=ticker,
            )

        if upcoming.empty:
            return EarningsCheckResult(
                blocked=False,
                reason="No upcoming earnings scheduled",
                next_earnings=None,
                ticker=ticker,
            )

        next_earnings = upcoming.index[0]
        days_until = (next_earnings - check_date).days

        # Decision logic based on days until earnings
        if days_until == 0:
            return EarningsCheckResult(
                blocked=True,
                reason=f"Earnings TODAY ({next_earnings.strftime('%Y-%m-%d')})",
                next_earnings=next_earnings,
                days_until=0,
                ticker=ticker,
            )
        elif days_until == 1:
            return EarningsCheckResult(
                blocked=False,
                reason=f"WARNING: Earnings tomorrow ({next_earnings.strftime('%Y-%m-%d')})",
                next_earnings=next_earnings,
                days_until=1,
                ticker=ticker,
            )
        elif days_until <= 7:
            return EarningsCheckResult(
                blocked=False,
                reason=f"Earnings in {days_until} days ({next_earnings.strftime('%Y-%m-%d')})",
                next_earnings=next_earnings,
                days_until=days_until,
                ticker=ticker,
            )
        else:
            return EarningsCheckResult(
                blocked=False,
                reason=f"Next earnings in {days_until} days",
                next_earnings=next_earnings,
                days_until=days_until,
                ticker=ticker,
            )

    def check_multiple_tickers(
        self,
        tickers: List[str],
        check_date: Optional[pd.Timestamp] = None,
    ) -> Dict[str, EarningsCheckResult]:
        """
        Check earnings conflicts for multiple tickers.

        Args:
            tickers: List of stock symbols.
            check_date: Date to check (defaults to today).

        Returns:
            Dictionary mapping ticker to EarningsCheckResult.
        """
        results = {}

        for ticker in tickers:
            results[ticker] = self.check_earnings_conflict(ticker, check_date)

        return results

    def get_blocked_tickers(
        self,
        tickers: List[str],
        check_date: Optional[pd.Timestamp] = None,
    ) -> List[str]:
        """
        Get list of tickers that are blocked due to earnings.

        Args:
            tickers: List of stock symbols.
            check_date: Date to check (defaults to today).

        Returns:
            List of blocked ticker symbols.
        """
        results = self.check_multiple_tickers(tickers, check_date)
        return [ticker for ticker, result in results.items() if result.blocked]

    def get_tradeable_tickers(
        self,
        tickers: List[str],
        check_date: Optional[pd.Timestamp] = None,
    ) -> List[str]:
        """
        Get list of tickers that are safe to trade.

        Args:
            tickers: List of stock symbols.
            check_date: Date to check (defaults to today).

        Returns:
            List of tradeable ticker symbols.
        """
        results = self.check_multiple_tickers(tickers, check_date)
        return [ticker for ticker, result in results.items() if not result.blocked]

    def format_earnings_report(
        self,
        tickers: List[str],
        check_date: Optional[pd.Timestamp] = None,
    ) -> str:
        """
        Generate formatted earnings report for multiple tickers.

        Args:
            tickers: List of stock symbols.
            check_date: Date to check (defaults to today).

        Returns:
            Formatted report string.
        """
        results = self.check_multiple_tickers(tickers, check_date)

        lines = []
        lines.append("=" * 60)
        lines.append("EARNINGS CALENDAR CHECK")
        lines.append("=" * 60)
        lines.append("")

        blocked = []
        warnings = []
        clear = []

        for ticker, result in sorted(results.items()):
            if result.blocked:
                blocked.append((ticker, result))
            elif result.days_until is not None and result.days_until <= 1:
                warnings.append((ticker, result))
            else:
                clear.append((ticker, result))

        if blocked:
            lines.append("BLOCKED (Do Not Trade):")
            for ticker, result in blocked:
                lines.append(f"  {ticker}: {result.reason}")
            lines.append("")

        if warnings:
            lines.append("WARNINGS (Trade with Caution):")
            for ticker, result in warnings:
                lines.append(f"  {ticker}: {result.reason}")
            lines.append("")

        if clear:
            lines.append("CLEAR (Safe to Trade):")
            for ticker, result in clear:
                lines.append(f"  {ticker}: {result.reason}")
            lines.append("")

        lines.append("=" * 60)
        lines.append(f"Blocked: {len(blocked)} | Warnings: {len(warnings)} | Clear: {len(clear)}")

        return "\n".join(lines)

    def clear_cache(self) -> None:
        """Clear the earnings data cache."""
        self._cache.clear()
        logger.info("Earnings cache cleared")


# Convenience function for quick checks
def check_earnings(
    ticker: str,
    check_date: Optional[pd.Timestamp] = None,
) -> EarningsCheckResult:
    """
    Quick check for earnings conflict.

    Args:
        ticker: Stock symbol.
        check_date: Date to check (defaults to today).

    Returns:
        EarningsCheckResult with blocking status.
    """
    filter_instance = EarningsFilter()
    return filter_instance.check_earnings_conflict(ticker, check_date)
