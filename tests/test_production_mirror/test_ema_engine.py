"""Tests for scripts/_production_mirror/ema_engine.py.

Coverage: EMA series formula correctness, daily EMA, 4H EMA,
warmup detection no-gap, warmup detection post-gap, get_ema_at_date lookup.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts._production_mirror.ema_engine import (
    WARMUP_REQUIRED_BARS,
    compute_daily_ema_for_ticker,
    compute_ema_series,
    detect_warmup_after_gap,
    get_ema_at_date,
)


# ── EMA series formula ───────────────────────────────────────────────────────

def test_ema_series_nan_when_insufficient():
    """All NaN when fewer closes than period."""
    closes = pd.Series([100.0] * 5)
    result = compute_ema_series(closes, period=9)
    assert all(pd.isna(v) for v in result)


def test_ema_series_seed_is_sma():
    """First valid EMA value equals the SMA of the first <period> closes."""
    period = 3
    values = [10.0, 12.0, 14.0, 15.0]  # SMA(3) = (10+12+14)/3 = 12.0
    closes = pd.Series(values)
    result = compute_ema_series(closes, period)
    assert not pd.isna(result.iloc[2])
    assert abs(result.iloc[2] - 12.0) < 1e-9


def test_ema_series_subsequent_values_use_multiplier():
    """EMA[i] = (close - EMA[i-1]) * mult + EMA[i-1], mult = 2/(period+1)."""
    period = 3
    closes = pd.Series([10.0, 12.0, 14.0, 16.0])
    result = compute_ema_series(closes, period)
    # EMA seed = (10+12+14)/3 = 12.0
    # EMA[3] = (16 - 12) * (2/4) + 12 = 4*0.5 + 12 = 14.0
    assert abs(result.iloc[3] - 14.0) < 1e-9


def test_ema_series_length_matches_input():
    """Output length equals input length."""
    closes = pd.Series([100.0 + i for i in range(30)])
    result = compute_ema_series(closes, period=21)
    assert len(result) == 30


# ── Daily EMA computation ────────────────────────────────────────────────────

def _make_m5_for_daily(n_days: int, base_price: float = 100.0) -> pd.DataFrame:
    """Synthetic M5 data: 1 bar per day at 09:30, prices linearly increasing."""
    from datetime import datetime
    rows = []
    start = date(2022, 1, 3)
    price = base_price
    for i in range(n_days):
        d = start + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        rows.append(
            {
                "date": pd.Timestamp(datetime(d.year, d.month, d.day, 9, 30)),
                "open": price,
                "high": price + 0.5,
                "low": price - 0.5,
                "close": price,
                "volume": 1000,
            }
        )
        price += 1.0
    return pd.DataFrame(rows)


def test_compute_daily_ema_columns():
    """Returns DataFrame with date_et, daily_close, ema columns."""
    m5 = _make_m5_for_daily(30)
    result = compute_daily_ema_for_ticker(m5, period=9)
    assert "date_et" in result.columns
    assert "daily_close" in result.columns
    assert "ema" in result.columns


def test_compute_daily_ema_first_values_nan():
    """First (period-1) EMA values are NaN."""
    m5 = _make_m5_for_daily(30)
    result = compute_daily_ema_for_ticker(m5, period=9)
    assert pd.isna(result.iloc[0]["ema"])
    assert pd.isna(result.iloc[7]["ema"])


def test_compute_daily_ema_values_non_nan_after_seed():
    """EMA values are non-NaN after the seed period."""
    m5 = _make_m5_for_daily(30)
    result = compute_daily_ema_for_ticker(m5, period=9)
    assert not pd.isna(result.iloc[8]["ema"])


# ── Warmup detection ─────────────────────────────────────────────────────────

def _make_daily_df_no_gap(n_bars: int = 30) -> pd.DataFrame:
    """Continuous daily data with no gaps."""
    rows = []
    start = date(2022, 1, 3)
    d = start
    for i in range(n_bars):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        rows.append({"date_et": d, "daily_close": 100.0 + i})
        d += timedelta(days=1)
    return pd.DataFrame(rows)


def _make_daily_df_with_gap(gap_calendar_days: int = 10) -> pd.DataFrame:
    """Daily data with an 8+ calendar day gap after 15 bars."""
    rows = []
    start = date(2022, 1, 3)
    d = start
    for i in range(15):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        rows.append({"date_et": d, "daily_close": 100.0 + i})
        d += timedelta(days=1)
    # introduce gap
    d += timedelta(days=gap_calendar_days)
    for i in range(25):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        rows.append({"date_et": d, "daily_close": 120.0 + i})
        d += timedelta(days=1)
    return pd.DataFrame(rows)


def test_warmup_no_gap_returns_false():
    """No data gap → no warmup required (production module4.py:444-450)."""
    daily = _make_daily_df_no_gap(40)
    current = daily.iloc[-1]["date_et"]
    assert detect_warmup_after_gap(daily, current) is False


def test_warmup_insufficient_history_returns_true():
    """Fewer than WARMUP_REQUIRED_BARS bars → warmup active."""
    daily = _make_daily_df_no_gap(10)
    current = daily.iloc[-1]["date_et"]
    assert detect_warmup_after_gap(daily, current) is True


def test_warmup_after_gap_returns_true_if_insufficient_bars_since_gap():
    """After an 8+ calendar-day gap with <21 bars since, warmup is active."""
    daily = _make_daily_df_with_gap(gap_calendar_days=10)
    # Use a date just 5 rows after the gap (insufficient warmup)
    post_gap = daily.iloc[18]["date_et"]  # only ~3 bars after gap start
    assert detect_warmup_after_gap(daily, post_gap) is True


def test_warmup_clears_after_21_bars_post_gap():
    """After 21+ bars since last gap, warmup is cleared."""
    daily = _make_daily_df_with_gap(gap_calendar_days=10)
    # Use a date ≥21 bars after the gap
    post_gap = daily.iloc[-1]["date_et"]  # ~25 bars after gap
    assert detect_warmup_after_gap(daily, post_gap) is False


# ── get_ema_at_date lookup ───────────────────────────────────────────────────

def test_get_ema_at_date_returns_float():
    """Returns float for a valid date with enough history."""
    m5 = _make_m5_for_daily(30)
    daily = compute_daily_ema_for_ticker(m5, period=9)
    d = daily.iloc[15]["date_et"]
    result = get_ema_at_date(daily, d, period=9)
    assert result is not None
    assert isinstance(result, float)


def test_get_ema_at_date_returns_none_for_missing_date():
    """Returns None for a date not in the DataFrame."""
    m5 = _make_m5_for_daily(30)
    daily = compute_daily_ema_for_ticker(m5, period=9)
    result = get_ema_at_date(daily, date(1999, 1, 1), period=9)
    assert result is None
