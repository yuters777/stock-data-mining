"""Tests for the EarningsCalendar module."""

import json
import pytest
import pandas as pd
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from backtester.earnings import EarningsCalendar, _fetch_earnings_dates


# ── Unit: EarningsCalendar in-memory ──

class TestEarningsCalendarBasic:
    def test_empty_calendar(self):
        cal = EarningsCalendar()
        assert cal.get_earnings_dates("AAPL") == set()
        assert cal.is_earnings_day("AAPL", date(2025, 1, 15)) is False
        assert cal.is_post_earnings("AAPL", date(2025, 1, 16)) is False

    def test_manual_dates(self):
        cal = EarningsCalendar()
        cal._dates["AAPL"] = {date(2025, 1, 30), date(2025, 4, 24)}
        assert cal.is_earnings_day("AAPL", date(2025, 1, 30)) is True
        assert cal.is_earnings_day("AAPL", date(2025, 1, 29)) is False

    def test_post_earnings_check(self):
        cal = EarningsCalendar(post_earnings_days=2)
        cal._dates["TSLA"] = {date(2025, 7, 22)}
        # Day of earnings is NOT post-earnings (it's earnings day itself)
        assert cal.is_post_earnings("TSLA", date(2025, 7, 22)) is False
        # 1 day after
        assert cal.is_post_earnings("TSLA", date(2025, 7, 23)) is True
        # 2 days after
        assert cal.is_post_earnings("TSLA", date(2025, 7, 24)) is True
        # 3 days after — outside window
        assert cal.is_post_earnings("TSLA", date(2025, 7, 25)) is False

    def test_post_earnings_default_1_day(self):
        cal = EarningsCalendar()  # default post_earnings_days=1
        cal._dates["AAPL"] = {date(2025, 1, 30)}
        assert cal.is_post_earnings("AAPL", date(2025, 1, 31)) is True
        assert cal.is_post_earnings("AAPL", date(2025, 2, 1)) is False


# ── Unit: as_filter_config ──

class TestAsFilterConfig:
    def test_includes_earnings_day_and_post(self):
        cal = EarningsCalendar(post_earnings_days=1)
        cal._dates["AAPL"] = {date(2025, 1, 30)}
        config = cal.as_filter_config()

        assert "AAPL" in config
        # Should contain the earnings day + 1 post-earnings day
        assert pd.Timestamp("2025-01-30").normalize() in config["AAPL"]
        assert pd.Timestamp("2025-01-31").normalize() in config["AAPL"]
        # Should NOT contain 2 days after
        assert pd.Timestamp("2025-02-01").normalize() not in config["AAPL"]

    def test_empty_calendar_returns_empty(self):
        cal = EarningsCalendar()
        assert cal.as_filter_config() == {}

    def test_multiple_tickers(self):
        cal = EarningsCalendar(post_earnings_days=0)
        cal._dates["AAPL"] = {date(2025, 1, 30)}
        cal._dates["TSLA"] = {date(2025, 2, 5)}
        config = cal.as_filter_config()
        assert len(config) == 2
        assert pd.Timestamp("2025-01-30").normalize() in config["AAPL"]
        assert pd.Timestamp("2025-02-05").normalize() in config["TSLA"]


# ── Unit: JSON caching ──

class TestCaching:
    def test_save_and_load_cache(self, tmp_path):
        cal = EarningsCalendar(cache_dir=tmp_path)
        cal._dates["AAPL"] = {date(2025, 1, 30), date(2025, 4, 24)}
        cal._save_cache()

        # Verify file exists and is valid JSON
        cache_file = tmp_path / "earnings_cache.json"
        assert cache_file.exists()
        with open(cache_file) as f:
            data = json.load(f)
        assert "AAPL" in data
        assert "2025-01-30" in data["AAPL"]
        assert "2025-04-24" in data["AAPL"]

        # Load into a new calendar
        cal2 = EarningsCalendar(cache_dir=tmp_path)
        cache = cal2._load_cache()
        assert "AAPL" in cache
        assert len(cache["AAPL"]) == 2

    def test_load_uses_cache(self, tmp_path):
        """load() should use cache and not call yfinance for cached tickers."""
        # Pre-populate cache
        cache_data = {"AAPL": ["2025-01-30", "2025-04-24"]}
        cache_file = tmp_path / "earnings_cache.json"
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)

        cal = EarningsCalendar(cache_dir=tmp_path)
        with patch("backtester.earnings._fetch_earnings_dates") as mock_fetch:
            cal.load(["AAPL"])
            mock_fetch.assert_not_called()

        assert cal.is_earnings_day("AAPL", date(2025, 1, 30)) is True

    def test_force_refresh_ignores_cache(self, tmp_path):
        """force_refresh=True should re-fetch even if cache exists."""
        cache_data = {"AAPL": ["2025-01-30"]}
        cache_file = tmp_path / "earnings_cache.json"
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)

        cal = EarningsCalendar(cache_dir=tmp_path)
        with patch("backtester.earnings._fetch_earnings_dates",
                    return_value=[date(2025, 1, 30), date(2025, 4, 24)]) as mock_fetch:
            cal.load(["AAPL"], force_refresh=True)
            mock_fetch.assert_called_once_with("AAPL")

        assert cal.is_earnings_day("AAPL", date(2025, 4, 24)) is True

    def test_no_cache_dir_skips_io(self):
        """When cache_dir is None, no file I/O should happen."""
        cal = EarningsCalendar(cache_dir=None)
        assert cal.cache_path is None
        assert cal._load_cache() == {}
        # _save_cache should be a no-op
        cal._dates["AAPL"] = {date(2025, 1, 30)}
        cal._save_cache()  # should not raise

    def test_corrupt_cache_returns_empty(self, tmp_path):
        cache_file = tmp_path / "earnings_cache.json"
        cache_file.write_text("not valid json{{{")

        cal = EarningsCalendar(cache_dir=tmp_path)
        assert cal._load_cache() == {}


# ── Unit: _fetch_earnings_dates ──

class TestFetchEarningsDates:
    def test_fetch_returns_dates(self):
        """Mock yfinance to verify the fetch path works."""
        mock_index = pd.DatetimeIndex([
            pd.Timestamp("2025-01-30 16:00:00"),
            pd.Timestamp("2025-04-24 16:00:00"),
        ])
        mock_df = pd.DataFrame({"EPS Estimate": [1.0, 1.1]}, index=mock_index)

        with patch("yfinance.Ticker") as mock_ticker_cls:
            mock_ticker = MagicMock()
            mock_ticker.earnings_dates = mock_df
            mock_ticker_cls.return_value = mock_ticker

            result = _fetch_earnings_dates("AAPL")

        assert len(result) == 2
        assert date(2025, 1, 30) in result
        assert date(2025, 4, 24) in result

    def test_fetch_handles_empty(self):
        with patch("yfinance.Ticker") as mock_ticker_cls:
            mock_ticker = MagicMock()
            mock_ticker.earnings_dates = pd.DataFrame()
            mock_ticker_cls.return_value = mock_ticker

            result = _fetch_earnings_dates("INVALID")

        assert result == []

    def test_fetch_handles_exception(self):
        with patch("yfinance.Ticker") as mock_ticker_cls:
            mock_ticker_cls.side_effect = Exception("API error")
            result = _fetch_earnings_dates("AAPL")
        assert result == []


# ── Integration: earnings filter in FilterChain ──

class TestEarningsFilterIntegration:
    """Verify that EarningsCalendar data properly blocks signals in FilterChain."""

    def test_filter_chain_blocks_earnings_day(self):
        from backtester.core.filter_chain import FilterChain, FilterChainConfig
        from backtester.data_types import (
            Level, LevelType, Signal, SignalDirection, PatternType,
        )

        cal = EarningsCalendar(post_earnings_days=1)
        cal._dates["TEST"] = {date(2025, 3, 3)}
        earnings_config = cal.as_filter_config()

        fc = FilterChain(FilterChainConfig(earnings_dates=earnings_config))

        level = Level(
            price=100.0, level_type=LevelType.RESISTANCE, score=8,
            ticker='TEST', date=pd.Timestamp('2025-03-01'),
            bsu_index=0, atr_d1=3.0, touches=3, is_round_number=True,
        )
        signal = Signal(
            pattern=PatternType.LP1, direction=SignalDirection.SHORT,
            level=level, timestamp=pd.Timestamp('2025-03-03 17:00:00'),
            ticker='TEST', entry_price=99.5, trigger_bar_idx=10,
        )

        result = fc._check_earnings_filter(signal)
        assert result.passed is False
        assert "Earnings day" in result.reason

    def test_filter_chain_blocks_post_earnings_day(self):
        from backtester.core.filter_chain import FilterChain, FilterChainConfig
        from backtester.data_types import (
            Level, LevelType, Signal, SignalDirection, PatternType,
        )

        cal = EarningsCalendar(post_earnings_days=1)
        cal._dates["TEST"] = {date(2025, 3, 3)}
        earnings_config = cal.as_filter_config()

        fc = FilterChain(FilterChainConfig(earnings_dates=earnings_config))

        level = Level(
            price=100.0, level_type=LevelType.RESISTANCE, score=8,
            ticker='TEST', date=pd.Timestamp('2025-03-01'),
            bsu_index=0, atr_d1=3.0, touches=3, is_round_number=True,
        )
        # Day AFTER earnings
        signal = Signal(
            pattern=PatternType.LP1, direction=SignalDirection.SHORT,
            level=level, timestamp=pd.Timestamp('2025-03-04 17:00:00'),
            ticker='TEST', entry_price=99.5, trigger_bar_idx=10,
        )

        result = fc._check_earnings_filter(signal)
        assert result.passed is False

    def test_filter_chain_passes_non_earnings_day(self):
        from backtester.core.filter_chain import FilterChain, FilterChainConfig
        from backtester.data_types import (
            Level, LevelType, Signal, SignalDirection, PatternType,
        )

        cal = EarningsCalendar(post_earnings_days=1)
        cal._dates["TEST"] = {date(2025, 3, 10)}  # earnings on the 10th
        earnings_config = cal.as_filter_config()

        fc = FilterChain(FilterChainConfig(earnings_dates=earnings_config))

        level = Level(
            price=100.0, level_type=LevelType.RESISTANCE, score=8,
            ticker='TEST', date=pd.Timestamp('2025-03-01'),
            bsu_index=0, atr_d1=3.0, touches=3, is_round_number=True,
        )
        # Signal on the 3rd — well before earnings
        signal = Signal(
            pattern=PatternType.LP1, direction=SignalDirection.SHORT,
            level=level, timestamp=pd.Timestamp('2025-03-03 17:00:00'),
            ticker='TEST', entry_price=99.5, trigger_bar_idx=10,
        )

        result = fc._check_earnings_filter(signal)
        assert result.passed is True
