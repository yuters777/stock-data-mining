"""Tests for scripts/_production_mirror/bars_4h_reconstructor.py.

Coverage: resample standard day, resample early close, RTH-only filter,
Bar C as final session bar, multi-day, missing data.
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts._production_mirror.bars_4h_reconstructor import reconstruct_4h


def _make_m5_day(
    trading_day: date,
    intervals_et: list,  # list of (hour, minute, close) tuples
    base_price: float = 100.0,
) -> pd.DataFrame:
    """Build synthetic M5 bars for a single day."""
    rows = []
    for h, m, close in intervals_et:
        rows.append(
            {
                "date": datetime(trading_day.year, trading_day.month, trading_day.day, h, m),
                "open": base_price,
                "high": max(base_price, close) + 0.1,
                "low": min(base_price, close) - 0.1,
                "close": close,
                "volume": 1000,
            }
        )
    return pd.DataFrame(rows)


def _make_standard_m5(trading_day: date) -> pd.DataFrame:
    """Full RTH M5 bars for a standard trading day (09:30-16:00)."""
    intervals = []
    # Bar B (09:30-13:30): every 5 min
    for h in range(9, 14):
        start_m = 30 if h == 9 else 0
        end_m = 30 if h == 13 else 60
        for m in range(start_m, end_m, 5):
            intervals.append((h, m, 100.0 + m * 0.01))
    # Bar C (13:30-16:00)
    for h in [13, 14, 15]:
        start_m = 30 if h == 13 else 0
        for m in range(start_m, 60, 5):
            if h == 15 and m >= 60:
                break
            intervals.append((h, m, 102.0 + m * 0.01))
    return _make_m5_day(trading_day, intervals)


# ── Patch NYSE calendar to return known values ─────────────────────────────

def _patch_calendar(mode="standard", early_close=None):
    def fake_get_session_mode(d):
        return mode

    def fake_get_early_close_et(d):
        return early_close

    # The imports are done at call time inside reconstruct_4h; patch the source module
    return (
        patch("scripts._production_mirror.nyse_calendar.get_session_mode", fake_get_session_mode),
        patch("scripts._production_mirror.nyse_calendar.get_early_close_et", fake_get_early_close_et),
    )


def test_rth_only_standard_day_produces_bar_b_and_c():
    """Standard trading day with rth_only=True produces Bar B + Bar C."""
    day = date(2023, 6, 15)
    m5 = _make_standard_m5(day)
    ctx_mode, ctx_ec = _patch_calendar("standard", None)
    with ctx_mode, ctx_ec:
        bars = reconstruct_4h(m5, "TEST", rth_only=True)
    assert not bars.empty
    labels = set(bars["bar_label"].tolist())
    assert "B" in labels
    assert "C" in labels
    assert "A" not in labels
    assert "D" not in labels


def test_bar_c_is_final_session_bar_on_standard_day():
    """Bar C is marked is_final_session_bar=True on a standard day."""
    day = date(2023, 6, 15)
    m5 = _make_standard_m5(day)
    ctx_mode, ctx_ec = _patch_calendar("standard", None)
    with ctx_mode, ctx_ec:
        bars = reconstruct_4h(m5, "TEST", rth_only=True)
    bar_c = bars[bars["bar_label"] == "C"]
    assert not bar_c.empty
    assert bool(bar_c.iloc[0]["is_final_session_bar"]) is True
    bar_b = bars[bars["bar_label"] == "B"]
    assert bool(bar_b.iloc[0]["is_final_session_bar"]) is False


def test_early_close_bar_c_truncates_to_early_close_time():
    """On early-close day (13:00), Bar C covers 13:30-13:00 → only Bar B exists."""
    day = date(2023, 11, 24)  # example early-close day
    # Bars up to 13:00 ET (early close)
    intervals = []
    for h in range(9, 14):
        start_m = 30 if h == 9 else 0
        end_m = 30 if h == 13 else 60
        for m in range(start_m, end_m, 5):
            intervals.append((h, m, 100.0))
    m5 = _make_m5_day(day, intervals)
    # Early close at 13:00 (before 13:30, so only Bars A+B)
    ctx_mode, ctx_ec = _patch_calendar("early_close", "13:00")
    with ctx_mode, ctx_ec:
        bars = reconstruct_4h(m5, "TEST", rth_only=True)
    # RTH-only, early close at 13:00 — Bar B goes 09:30-13:00
    assert not bars.empty
    labels = set(bars["bar_label"].tolist())
    assert "C" not in labels  # no Bar C when early close before 13:30
    assert "B" in labels


def test_early_close_after_1330_creates_short_bar_c():
    """Early close at 14:00 creates a short Bar C (13:30-14:00)."""
    day = date(2023, 7, 3)
    intervals = []
    for h in range(9, 15):
        start_m = 30 if h == 9 else 0
        end_m = 0 if h == 14 else 60
        for m in range(start_m, 60 if h < 14 else 1, 5):
            intervals.append((h, m, 100.0))
    m5 = _make_m5_day(day, intervals)
    ctx_mode, ctx_ec = _patch_calendar("early_close", "14:00")
    with ctx_mode, ctx_ec:
        bars = reconstruct_4h(m5, "TEST", rth_only=True)
    labels = set(bars["bar_label"].tolist())
    assert "B" in labels
    assert "C" in labels
    # Bar C is final
    bar_c = bars[bars["bar_label"] == "C"]
    assert bool(bar_c.iloc[0]["is_final_session_bar"]) is True


def test_non_trading_day_skipped():
    """Non-trading day (session_mode=None) produces no bars."""
    day = date(2023, 1, 7)  # Saturday
    m5 = _make_standard_m5(day)
    ctx_mode, ctx_ec = _patch_calendar(None, None)
    with ctx_mode, ctx_ec:
        bars = reconstruct_4h(m5, "TEST", rth_only=True)
    assert bars.empty


def test_multi_day_produces_bars_for_each_trading_day():
    """Multiple trading days each produce their own set of bars."""
    days = [date(2023, 6, 12), date(2023, 6, 13), date(2023, 6, 14)]
    frames = [_make_standard_m5(d) for d in days]
    m5 = pd.concat(frames, ignore_index=True)

    ctx_mode, ctx_ec = _patch_calendar("standard", None)
    with ctx_mode, ctx_ec:
        bars = reconstruct_4h(m5, "MULTI", rth_only=True)

    dates_in_output = set(bars["date_et"].tolist())
    for d in days:
        assert d in dates_in_output


def test_ohlc_aggregation_correctness():
    """Bar B open = first M5 open, high = max, low = min, close = last M5 close."""
    day = date(2023, 6, 15)
    # 3 M5 bars covering 09:30-09:45 (within Bar B)
    intervals = [
        (9, 30, 102.0),  # open=100, close=102
        (9, 35, 98.0),   # close=98 → low candidate
        (9, 40, 105.0),  # close=105 → high candidate, last close
    ] + [(h, m, 100.0) for h in range(10, 14) for m in range(0, 60, 5) if not (h == 13 and m >= 30)]
    # Add Bar C bars
    intervals += [(13, 30, 100.0), (13, 35, 100.0)]
    m5 = _make_m5_day(day, intervals, base_price=100.0)

    ctx_mode, ctx_ec = _patch_calendar("standard", None)
    with ctx_mode, ctx_ec:
        bars = reconstruct_4h(m5, "TEST", rth_only=True)

    bar_b = bars[bars["bar_label"] == "B"]
    assert not bar_b.empty
    assert float(bar_b.iloc[0]["open"]) == 100.0   # first M5 bar's open
    assert float(bar_b.iloc[0]["high"]) >= 105.0 + 0.1  # max high across all M5 bars in window
    assert float(bar_b.iloc[0]["low"]) <= 98.0 - 0.1    # min low


def test_empty_m5_returns_empty_bars():
    """Empty M5 DataFrame returns empty output."""
    m5 = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    ctx_mode, ctx_ec = _patch_calendar("standard", None)
    with ctx_mode, ctx_ec:
        bars = reconstruct_4h(m5, "EMPTY", rth_only=True)
    assert bars.empty
