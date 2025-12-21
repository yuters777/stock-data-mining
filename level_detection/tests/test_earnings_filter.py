"""
Tests for Earnings Filter Module.

Note: Some tests require yfinance to be installed.
Tests will skip gracefully if yfinance is not available.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch
import sys

import pandas as pd
import pytest

from level_detection.earnings_filter import (
    EarningsCheckResult,
    EarningsFilter,
)

# Check if yfinance is available
try:
    import yfinance
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

yfinance_required = pytest.mark.skipif(
    not YFINANCE_AVAILABLE,
    reason="yfinance not installed"
)


class TestEarningsCheckResult:
    """Test EarningsCheckResult dataclass."""

    def test_blocked_result(self):
        """Test blocked result representation."""
        result = EarningsCheckResult(
            blocked=True,
            reason="Earnings TODAY",
            next_earnings=pd.Timestamp("2025-01-15"),
            days_until=0,
            ticker="AAPL",
        )

        assert result.blocked is True
        assert "BLOCKED" in str(result)
        assert result.days_until == 0

    def test_ok_result(self):
        """Test OK result representation."""
        result = EarningsCheckResult(
            blocked=False,
            reason="Next earnings in 30 days",
            next_earnings=pd.Timestamp("2025-02-15"),
            days_until=30,
            ticker="TSLA",
        )

        assert result.blocked is False
        assert "OK" in str(result)


class TestEarningsFilter:
    """Test EarningsFilter class."""

    @pytest.fixture
    def earnings_filter(self):
        """Create EarningsFilter instance."""
        return EarningsFilter()

    @pytest.fixture
    def mock_earnings_dates(self):
        """Create mock earnings dates DataFrame."""
        dates = pd.date_range("2025-01-15", periods=4, freq="90D")
        return pd.DataFrame({"EPS": [1.5, 1.6, 1.7, 1.8]}, index=dates)

    @yfinance_required
    def test_check_earnings_today_blocks(self, earnings_filter, mock_earnings_dates):
        """Test that earnings today blocks trading."""
        check_date = mock_earnings_dates.index[0]  # Same as first earnings

        with patch("level_detection.earnings_filter.yf") as mock_yf:
            mock_stock = MagicMock()
            mock_stock.earnings_dates = mock_earnings_dates
            mock_yf.Ticker.return_value = mock_stock

            result = earnings_filter.check_earnings_conflict("AAPL", check_date)

            assert result.blocked is True
            assert "TODAY" in result.reason

    @yfinance_required
    def test_check_earnings_tomorrow_warns(self, earnings_filter, mock_earnings_dates):
        """Test that earnings tomorrow shows warning."""
        check_date = mock_earnings_dates.index[0] - pd.Timedelta(days=1)

        with patch("level_detection.earnings_filter.yf") as mock_yf:
            mock_stock = MagicMock()
            mock_stock.earnings_dates = mock_earnings_dates
            mock_yf.Ticker.return_value = mock_stock

            result = earnings_filter.check_earnings_conflict("AAPL", check_date)

            assert result.blocked is False
            assert "tomorrow" in result.reason.lower()
            assert result.days_until == 1

    @yfinance_required
    def test_check_earnings_future_ok(self, earnings_filter, mock_earnings_dates):
        """Test that distant earnings is OK."""
        check_date = mock_earnings_dates.index[0] - pd.Timedelta(days=30)

        with patch("level_detection.earnings_filter.yf") as mock_yf:
            mock_stock = MagicMock()
            mock_stock.earnings_dates = mock_earnings_dates
            mock_yf.Ticker.return_value = mock_stock

            result = earnings_filter.check_earnings_conflict("AAPL", check_date)

            assert result.blocked is False
            assert result.days_until == 30

    @yfinance_required
    def test_check_no_earnings_data(self, earnings_filter):
        """Test handling when no earnings data available."""
        with patch("level_detection.earnings_filter.yf") as mock_yf:
            mock_stock = MagicMock()
            mock_stock.earnings_dates = None
            mock_yf.Ticker.return_value = mock_stock

            result = earnings_filter.check_earnings_conflict("AAPL")

            assert result.blocked is False
            assert "No earnings data" in result.reason

    @yfinance_required
    def test_check_empty_earnings(self, earnings_filter):
        """Test handling when earnings data is empty."""
        with patch("level_detection.earnings_filter.yf") as mock_yf:
            mock_stock = MagicMock()
            mock_stock.earnings_dates = pd.DataFrame()
            mock_yf.Ticker.return_value = mock_stock

            result = earnings_filter.check_earnings_conflict("AAPL")

            assert result.blocked is False


class TestMultipleTickers:
    """Test checking multiple tickers."""

    @pytest.fixture
    def earnings_filter(self):
        """Create EarningsFilter instance."""
        return EarningsFilter()

    @yfinance_required
    def test_check_multiple_tickers(self, earnings_filter):
        """Test checking multiple tickers."""
        with patch("level_detection.earnings_filter.yf") as mock_yf:
            mock_stock = MagicMock()
            mock_stock.earnings_dates = None
            mock_yf.Ticker.return_value = mock_stock

            results = earnings_filter.check_multiple_tickers(["AAPL", "TSLA", "MSFT"])

            assert len(results) == 3
            assert "AAPL" in results
            assert "TSLA" in results
            assert "MSFT" in results

    @yfinance_required
    def test_get_blocked_tickers(self, earnings_filter):
        """Test getting blocked tickers list."""
        dates_today = pd.DataFrame(
            {"EPS": [1.5]},
            index=[pd.Timestamp.now().normalize()]
        )
        dates_future = pd.DataFrame(
            {"EPS": [1.5]},
            index=[pd.Timestamp.now().normalize() + pd.Timedelta(days=30)]
        )

        def mock_ticker_side_effect(ticker):
            mock_stock = MagicMock()
            if ticker == "AAPL":
                mock_stock.earnings_dates = dates_today
            else:
                mock_stock.earnings_dates = dates_future
            return mock_stock

        with patch("level_detection.earnings_filter.yf") as mock_yf:
            mock_yf.Ticker.side_effect = mock_ticker_side_effect
            blocked = earnings_filter.get_blocked_tickers(["AAPL", "TSLA"])

            assert "AAPL" in blocked
            assert "TSLA" not in blocked

    @yfinance_required
    def test_get_tradeable_tickers(self, earnings_filter):
        """Test getting tradeable tickers list."""
        with patch("level_detection.earnings_filter.yf") as mock_yf:
            mock_stock = MagicMock()
            mock_stock.earnings_dates = pd.DataFrame(
                {"EPS": [1.5]},
                index=[pd.Timestamp.now().normalize() + pd.Timedelta(days=30)]
            )
            mock_yf.Ticker.return_value = mock_stock

            tradeable = earnings_filter.get_tradeable_tickers(["AAPL", "TSLA"])

            assert len(tradeable) == 2


class TestFormatReport:
    """Test earnings report formatting."""

    @yfinance_required
    def test_format_earnings_report(self):
        """Test earnings report generation."""
        filter_instance = EarningsFilter()

        with patch("level_detection.earnings_filter.yf") as mock_yf:
            mock_stock = MagicMock()
            mock_stock.earnings_dates = None
            mock_yf.Ticker.return_value = mock_stock

            report = filter_instance.format_earnings_report(["AAPL", "TSLA"])

            assert "EARNINGS CALENDAR CHECK" in report
            assert "AAPL" in report
            assert "TSLA" in report


class TestCaching:
    """Test caching functionality."""

    @yfinance_required
    def test_cache_is_used(self):
        """Test that cached data is reused."""
        filter_instance = EarningsFilter(cache_hours=24)

        with patch("level_detection.earnings_filter.yf") as mock_yf:
            mock_stock = MagicMock()
            mock_stock.earnings_dates = pd.DataFrame(
                {"EPS": [1.5]},
                index=[pd.Timestamp.now().normalize() + pd.Timedelta(days=30)]
            )
            mock_yf.Ticker.return_value = mock_stock

            # First call - fetches data
            filter_instance.check_earnings_conflict("AAPL")
            # Second call - should use cache
            filter_instance.check_earnings_conflict("AAPL")

            # Should only be called once due to caching
            assert mock_yf.Ticker.call_count == 1

    def test_clear_cache(self):
        """Test clearing cache."""
        filter_instance = EarningsFilter()
        filter_instance._cache["AAPL"] = (pd.DataFrame(), datetime.now())

        filter_instance.clear_cache()

        assert len(filter_instance._cache) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
