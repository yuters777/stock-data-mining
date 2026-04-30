"""Tests for scripts/_production_mirror/nyse_calendar.py.

Production reference: market-engine market_calendar_day table schema.
Coverage: load, is_trading_day, get_session_mode, get_early_close_et,
trading_days_between.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts._production_mirror.nyse_calendar import (
    get_early_close_et,
    get_session_mode,
    is_trading_day,
    load_calendar,
    trading_days_between,
)


def test_load_calendar_has_expected_columns():
    """Calendar CSV loads with required columns."""
    cal = load_calendar()
    assert "trading_date_et" in cal.columns
    assert "session_mode" in cal.columns
    assert "early_close_et" in cal.columns


def test_load_calendar_row_count():
    """Calendar has ≥ 1200 rows (5-year span 2021-2026)."""
    cal = load_calendar()
    assert len(cal) >= 1200


def test_is_trading_day_regular_weekday():
    """A known NYSE trading day returns True."""
    # 2023-01-03 was a Tuesday (first trading day of 2023)
    assert is_trading_day(date(2023, 1, 3)) is True


def test_is_trading_day_weekend_returns_false():
    """Saturday is not a trading day."""
    # 2023-01-07 was a Saturday
    assert is_trading_day(date(2023, 1, 7)) is False


def test_is_trading_day_holiday_returns_false():
    """NYSE holiday returns False."""
    # 2023-01-02 was a NYSE holiday (New Year's Day observed)
    assert is_trading_day(date(2023, 1, 2)) is False


def test_get_session_mode_standard_day():
    """Standard trading day returns 'standard'."""
    assert get_session_mode(date(2023, 6, 15)) == "standard"


def test_get_session_mode_non_trading_day_returns_none():
    """Non-trading day returns None."""
    assert get_session_mode(date(2023, 1, 7)) is None  # Saturday


def test_get_early_close_et_standard_day_is_none():
    """Standard day returns None for early_close_et."""
    result = get_early_close_et(date(2023, 6, 15))
    assert result is None


def test_get_early_close_et_black_friday():
    """Black Friday 2022 is an early-close day (13:00 ET)."""
    # 2022-11-25 is Black Friday
    mode = get_session_mode(date(2022, 11, 25))
    assert mode == "early_close"
    ec = get_early_close_et(date(2022, 11, 25))
    assert ec is not None
    assert "13:" in ec or "12:" in ec  # typically 13:00 or early afternoon


def test_trading_days_between_exclusive_inclusive():
    """trading_days_between is exclusive of start, inclusive of end."""
    # 2023-01-03 (Tue) and 2023-01-04 (Wed) are consecutive trading days
    n = trading_days_between(date(2023, 1, 3), date(2023, 1, 4))
    assert n == 1


def test_trading_days_between_across_weekend():
    """Counting across a weekend skips the non-trading days."""
    # Fri 2023-01-06 to Mon 2023-01-09: 1 trading day (Mon only, exclusive of Fri)
    n = trading_days_between(date(2023, 1, 6), date(2023, 1, 9))
    assert n == 1


def test_trading_days_between_zero_for_same_day():
    """Same start and end returns 0 (start is exclusive)."""
    n = trading_days_between(date(2023, 1, 3), date(2023, 1, 3))
    assert n == 0
