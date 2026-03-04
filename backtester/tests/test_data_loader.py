"""Tests for backtester.data_loader — CSV loading, session tagging, D1 aggregation, validation."""

import pytest
import pandas as pd
import numpy as np
from datetime import date
from pathlib import Path

from backtester.data_loader import (
    load_m5, assign_trading_day, tag_session, tag_dataframe,
    aggregate_d1, validate_data, load_all_tickers, prepare_backtester_data,
)


DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


# ── Test load_m5 ──────────────────────────────────────────────────────────

class TestLoadM5:
    def test_load_nvda(self):
        """Load NVDA_data.csv and verify basic properties."""
        df = load_m5("NVDA", DATA_DIR)
        assert len(df) > 40_000  # spec: ~45k rows
        assert list(df.columns) == ["Datetime", "Open", "High", "Low", "Close", "Volume", "Ticker"]
        assert df["Ticker"].iloc[0] == "NVDA"
        assert pd.api.types.is_datetime64_any_dtype(df["Datetime"])

    def test_load_tsla(self):
        df = load_m5("TSLA", DATA_DIR)
        assert len(df) > 30_000
        assert df["Ticker"].iloc[0] == "TSLA"

    def test_load_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            load_m5("FAKE_TICKER", DATA_DIR)

    def test_chronological_order(self):
        df = load_m5("NVDA", DATA_DIR)
        assert df["Datetime"].is_monotonic_increasing

    def test_dtypes(self):
        df = load_m5("NVDA", DATA_DIR)
        assert df["Open"].dtype == np.float64
        assert df["Volume"].dtype in (np.int64, np.int32)


# ── Test assign_trading_day ───────────────────────────────────────────────

class TestAssignTradingDay:
    def test_saturday_bar_maps_to_friday(self):
        """Saturday IST 00:30 → Friday's trading day (spec example)."""
        dt = pd.Timestamp("2025-02-15 00:30:00")  # Saturday
        assert dt.dayofweek == 5  # Saturday
        td = assign_trading_day(dt)
        assert td == date(2025, 2, 14)  # Friday

    def test_saturday_early_morning(self):
        """Saturday 02:55 → Friday."""
        dt = pd.Timestamp("2025-02-15 02:55:00")
        assert assign_trading_day(dt) == date(2025, 2, 14)

    def test_weekday_post_midnight(self):
        """Tuesday 01:00 → Monday (post-market spillover)."""
        dt = pd.Timestamp("2025-02-11 01:00:00")  # Tuesday
        assert dt.dayofweek == 1
        assert assign_trading_day(dt) == date(2025, 2, 10)  # Monday

    def test_regular_session_bar(self):
        """Normal weekday bar stays same day."""
        dt = pd.Timestamp("2025-02-10 17:00:00")  # Monday
        assert assign_trading_day(dt) == date(2025, 2, 10)

    def test_pre_market_bar(self):
        """Pre-market 11:00 stays same day."""
        dt = pd.Timestamp("2025-02-10 11:00:00")
        assert assign_trading_day(dt) == date(2025, 2, 10)

    def test_post_market_2355(self):
        """23:55 stays same day."""
        dt = pd.Timestamp("2025-02-10 23:55:00")
        assert assign_trading_day(dt) == date(2025, 2, 10)

    def test_midnight_exactly(self):
        """Midnight 00:00 on a weekday → previous day."""
        dt = pd.Timestamp("2025-02-11 00:00:00")  # Tuesday midnight
        assert assign_trading_day(dt) == date(2025, 2, 10)


# ── Test tag_session ──────────────────────────────────────────────────────

class TestTagSession:
    def test_pre_market_1100(self):
        assert tag_session(pd.Timestamp("2025-02-10 11:00:00")) == "PRE_MARKET"

    def test_pre_market_1625(self):
        assert tag_session(pd.Timestamp("2025-02-10 16:25:00")) == "PRE_MARKET"

    def test_regular_1630(self):
        assert tag_session(pd.Timestamp("2025-02-10 16:30:00")) == "REGULAR"

    def test_regular_1700(self):
        assert tag_session(pd.Timestamp("2025-02-10 17:00:00")) == "REGULAR"

    def test_regular_2255(self):
        assert tag_session(pd.Timestamp("2025-02-10 22:55:00")) == "REGULAR"

    def test_regular_close_bar_2300(self):
        """23:00 is the close bar — still REGULAR."""
        assert tag_session(pd.Timestamp("2025-02-10 23:00:00")) == "REGULAR"

    def test_post_market_2305(self):
        assert tag_session(pd.Timestamp("2025-02-10 23:05:00")) == "POST_MARKET"

    def test_post_market_0100(self):
        assert tag_session(pd.Timestamp("2025-02-11 01:00:00")) == "POST_MARKET"

    def test_post_market_0255(self):
        assert tag_session(pd.Timestamp("2025-02-11 02:55:00")) == "POST_MARKET"

    def test_post_market_0000(self):
        assert tag_session(pd.Timestamp("2025-02-11 00:00:00")) == "POST_MARKET"


# ── Test tag_dataframe ────────────────────────────────────────────────────

class TestTagDataframe:
    def test_adds_columns(self):
        df = pd.DataFrame({
            "Datetime": [
                pd.Timestamp("2025-02-10 11:00:00"),
                pd.Timestamp("2025-02-10 17:00:00"),
                pd.Timestamp("2025-02-11 01:00:00"),
            ],
        })
        tagged = tag_dataframe(df)
        assert "trading_day" in tagged.columns
        assert "session" in tagged.columns
        assert tagged["session"].tolist() == ["PRE_MARKET", "REGULAR", "POST_MARKET"]

    def test_saturday_bar_tagging(self):
        df = pd.DataFrame({
            "Datetime": [pd.Timestamp("2025-02-15 00:30:00")],  # Saturday
        })
        tagged = tag_dataframe(df)
        assert tagged["trading_day"].iloc[0] == date(2025, 2, 14)
        assert tagged["session"].iloc[0] == "POST_MARKET"


# ── Test aggregate_d1 ────────────────────────────────────────────────────

class TestAggregateD1:
    def test_basic_aggregation(self):
        """Regular session bars aggregate correctly."""
        df = pd.DataFrame({
            "Datetime": pd.date_range("2025-02-10 16:30", periods=6, freq="5min"),
            "Open": [100.0, 101.0, 102.0, 101.5, 100.5, 101.0],
            "High": [101.0, 102.0, 103.0, 102.0, 101.0, 101.5],
            "Low": [99.5, 100.5, 101.5, 101.0, 100.0, 100.5],
            "Close": [101.0, 102.0, 101.5, 101.0, 101.0, 101.2],
            "Volume": [1000, 1200, 1100, 900, 800, 1000],
            "Ticker": ["TEST"] * 6,
        })
        tagged = tag_dataframe(df)
        d1 = aggregate_d1(tagged)

        assert len(d1) == 1
        assert d1["Open"].iloc[0] == 100.0   # first bar open
        assert d1["High"].iloc[0] == 103.0   # max high
        assert d1["Low"].iloc[0] == 99.5     # min low
        assert d1["Close"].iloc[0] == 101.2  # last bar close
        assert d1["Volume"].iloc[0] == 6000  # sum

    def test_pre_market_excluded(self):
        """Pre-market bars should not appear in D1 aggregation."""
        df = pd.DataFrame({
            "Datetime": [
                pd.Timestamp("2025-02-10 11:00:00"),  # pre-market
                pd.Timestamp("2025-02-10 16:30:00"),  # regular
                pd.Timestamp("2025-02-10 17:00:00"),  # regular
            ],
            "Open": [100.0, 105.0, 106.0],
            "High": [101.0, 106.0, 107.0],
            "Low": [99.0, 104.0, 105.0],
            "Close": [100.5, 106.0, 106.5],
            "Volume": [500, 1000, 1200],
            "Ticker": ["TEST"] * 3,
        })
        tagged = tag_dataframe(df)
        d1 = aggregate_d1(tagged)

        assert len(d1) == 1
        assert d1["Open"].iloc[0] == 105.0  # first regular bar, not pre-market

    def test_real_data_trading_days(self):
        """NVDA D1 should produce a reasonable number of trading days."""
        df = load_m5("NVDA", DATA_DIR)
        tagged = tag_dataframe(df)
        d1 = aggregate_d1(tagged)
        # ~235 trading days for ~11 months of data
        assert 200 <= len(d1) <= 260

    def test_empty_regular_session(self):
        """All pre-market bars → empty D1."""
        df = pd.DataFrame({
            "Datetime": [pd.Timestamp("2025-02-10 11:00:00")],
            "Open": [100.0], "High": [101.0], "Low": [99.0],
            "Close": [100.5], "Volume": [500], "Ticker": ["TEST"],
        })
        tagged = tag_dataframe(df)
        d1 = aggregate_d1(tagged)
        assert len(d1) == 0


# ── Test validate_data ────────────────────────────────────────────────────

class TestValidateData:
    def test_clean_data_passes(self):
        df = pd.DataFrame({
            "Datetime": pd.date_range("2025-01-01", periods=3, freq="5min"),
            "Open": [100.0, 101.0, 102.0],
            "High": [101.0, 102.0, 103.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [100.5, 101.5, 102.5],
            "Volume": [1000, 1100, 1200],
            "Ticker": ["TEST"] * 3,
        })
        errors = validate_data(df)
        assert errors == []

    def test_null_injection_raises(self):
        """NULL values in OHLCV should be caught."""
        df = pd.DataFrame({
            "Datetime": pd.date_range("2025-01-01", periods=3, freq="5min"),
            "Open": [100.0, np.nan, 102.0],
            "High": [101.0, 102.0, 103.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [100.5, 101.5, 102.5],
            "Volume": [1000, 1100, 1200],
        })
        with pytest.raises(ValueError, match="NULL values"):
            validate_data(df)

    def test_high_less_than_low_raises(self):
        df = pd.DataFrame({
            "Datetime": pd.date_range("2025-01-01", periods=3, freq="5min"),
            "Open": [100.0, 101.0, 102.0],
            "High": [101.0, 99.0, 103.0],   # bar 2: high < low
            "Low": [99.0, 100.0, 101.0],
            "Close": [100.5, 99.5, 102.5],
            "Volume": [1000, 1100, 1200],
        })
        with pytest.raises(ValueError, match="High < Low"):
            validate_data(df)

    def test_duplicate_timestamp_raises(self):
        df = pd.DataFrame({
            "Datetime": [
                pd.Timestamp("2025-01-01 10:00"),
                pd.Timestamp("2025-01-01 10:00"),  # duplicate
                pd.Timestamp("2025-01-01 10:10"),
            ],
            "Open": [100.0, 101.0, 102.0],
            "High": [101.0, 102.0, 103.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [100.5, 101.5, 102.5],
            "Volume": [1000, 1100, 1200],
            "Ticker": ["TEST"] * 3,
        })
        with pytest.raises(ValueError, match="Duplicate timestamps"):
            validate_data(df)

    def test_negative_volume_raises(self):
        df = pd.DataFrame({
            "Datetime": pd.date_range("2025-01-01", periods=3, freq="5min"),
            "Open": [100.0, 101.0, 102.0],
            "High": [101.0, 102.0, 103.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [100.5, 101.5, 102.5],
            "Volume": [1000, -1, 1200],
        })
        with pytest.raises(ValueError, match="Negative volume"):
            validate_data(df)

    def test_missing_columns_raises(self):
        df = pd.DataFrame({"Datetime": [1], "Open": [1]})
        with pytest.raises(ValueError, match="Missing columns"):
            validate_data(df)

    def test_real_nvda_passes(self):
        """Real NVDA data should pass validation."""
        df = load_m5("NVDA", DATA_DIR)
        errors = validate_data(df)
        assert errors == []


# ── Test load_all_tickers ─────────────────────────────────────────────────

class TestLoadAllTickers:
    def test_loads_available_tickers(self):
        result = load_all_tickers(DATA_DIR)
        # We know at least NVDA, TSLA, META, MSFT, GOOGL, AMZN are present
        assert len(result) >= 6
        for ticker, df in result.items():
            assert len(df) > 0
            assert "Datetime" in df.columns


# ── Test prepare_backtester_data ──────────────────────────────────────────

class TestPrepareBacktesterData:
    def test_prepare_single_ticker(self, tmp_path):
        """Full pipeline for one ticker produces expected output files."""
        metadata = prepare_backtester_data(DATA_DIR, tmp_path, tickers=["NVDA"])

        assert (tmp_path / "NVDA_m5.parquet").exists()
        assert (tmp_path / "NVDA_d1.parquet").exists()
        assert (tmp_path / "metadata.json").exists()
        assert (tmp_path / "data_quality_report.json").exists()

        assert "NVDA" in metadata["tickers"]
        assert metadata["tickers"]["NVDA"]["m5_bars"] > 40_000

        # Read back and verify
        m5 = pd.read_parquet(tmp_path / "NVDA_m5.parquet")
        assert "trading_day" in m5.columns
        assert "session" in m5.columns

        d1 = pd.read_parquet(tmp_path / "NVDA_d1.parquet")
        assert len(d1) > 200
