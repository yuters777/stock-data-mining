"""Tests for scripts/_backtest_lib_m4.py — synthetic data only."""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List
from unittest.mock import patch

import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts._backtest_lib_m4 import (
    compute_ema_21,
    compute_rsi_14,
    run_module4_backtest,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_bars_4h(
    n: int = 60,
    base_price: float = 100.0,
    streak_start: int = 10,
    recovery_bar: int = 20,
    streak_close: float = 99.0,
    recovery_price: float = 110.0,
) -> pd.DataFrame:
    """Synthetic 4H RTH bars.

    Bars 0..streak_start-1: flat (close == open, no streak).
    Bars streak_start..streak_start+2: RED (close < open) — 3-bar streak.
    Bar streak_start+3: entry candidate (RSI/VIX gates checked externally).
    Bar recovery_bar: close = recovery_price (EMA21 touch candidate).
    """
    rows = []
    base = date(2022, 1, 3)
    price = base_price
    for i in range(n):
        d = base + timedelta(days=(i // 2))
        bar_idx = (i % 2) + 1
        if streak_start <= i < streak_start + 3:
            o, c = price + 1.0, price - 0.5  # RED bar
        elif i == recovery_bar:
            o, c = price, recovery_price
        else:
            o, c = price, price + 0.1  # slight green / flat
        rows.append({
            "date_et": d,
            "bar_index": bar_idx,
            "open": o,
            "high": max(o, c) + 0.2,
            "low": min(o, c) - 0.2,
            "close": c,
            "volume": 10000,
            "timestamp_et": pd.Timestamp(f"{d} {'09:30' if bar_idx == 1 else '13:30'}"),
        })
        price = c
    return pd.DataFrame(rows)


def _make_vix_df(value: float = 30.0, n_days: int = 300) -> pd.DataFrame:
    """Synthetic VIX daily — constant value."""
    base = date(2021, 12, 1)
    rows = [{"date": pd.Timestamp(base + timedelta(days=i)), "vix_close": value} for i in range(n_days)]
    return pd.DataFrame(rows)


def _empty_earnings() -> pd.DataFrame:
    return pd.DataFrame({"ticker": [], "earnings_date": pd.to_datetime([])})


def _run_with_synthetic(
    bars_4h: pd.DataFrame,
    vix_df: pd.DataFrame,
    earnings_df: pd.DataFrame,
    earnings_buffer_days: int = 0,
    date_range=("2022-01-01", "2023-12-31"),
):
    """Run M4 backtest patching the data-loading layer with synthetic bars."""
    import scripts._backtest_lib_m4 as lib

    def fake_load_m5(data_root, ticker):
        # Return a dummy M5 df — aggregate_m5_to_4h_rth will be mocked
        return pd.DataFrame()

    def fake_aggregate(df_m5):
        return bars_4h.copy()

    with patch.object(lib, "load_m5_extended", fake_load_m5), \
         patch.object(lib, "aggregate_m5_to_4h_rth", fake_aggregate):
        trades = run_module4_backtest(
            universe=["AAPL"],
            date_range=date_range,
            earnings_buffer_days=earnings_buffer_days,
            data_root=Path("/fake"),
            earnings_df=earnings_df,
            vix_df=vix_df,
        )
    return trades


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_rsi_14_none_when_insufficient():
    assert compute_rsi_14([100.0] * 14) is None


def test_rsi_14_returns_float_with_enough_data():
    closes = [100.0 - i * 0.5 for i in range(20)]  # downtrend → low RSI
    rsi = compute_rsi_14(closes)
    assert rsi is not None
    assert 0.0 <= rsi <= 100.0


def test_ema_21_none_when_insufficient():
    assert compute_ema_21([100.0] * 20) is None


def test_ema_21_returns_float():
    closes = [100.0 + i * 0.1 for i in range(30)]
    ema = compute_ema_21(closes)
    assert ema is not None
    assert isinstance(ema, float)


def test_streak_triggers_entry():
    """3 consecutive RED bars + VIX≥25 + RSI<35 → trade is opened."""
    # Build bars where entry conditions are met at bar 13 (after 3-bar streak at 10-12)
    # Use a strong downtrend so RSI<35
    rows = []
    base = date(2022, 1, 3)
    price = 100.0
    for i in range(50):
        d = base + timedelta(days=(i // 2))
        bar_idx = (i % 2) + 1
        # Strong downtrend → ensures RSI<35
        o = price + 0.5
        c = price - 1.0
        rows.append({
            "date_et": d,
            "bar_index": bar_idx,
            "open": o,
            "high": o + 0.2,
            "low": c - 0.2,
            "close": c,
            "volume": 10000,
            "timestamp_et": pd.Timestamp(f"{d} {'09:30' if bar_idx == 1 else '13:30'}"),
        })
        price = c

    bars = pd.DataFrame(rows)
    vix = _make_vix_df(30.0)
    earnings = _empty_earnings()

    trades = _run_with_synthetic(bars, vix, earnings, earnings_buffer_days=0)
    # With strong downtrend, at least one entry should be triggered
    assert len(trades) >= 1


def test_vix_gate_blocks_entry():
    """VIX < 25 blocks entry."""
    rows = []
    base = date(2022, 1, 3)
    price = 100.0
    for i in range(50):
        d = base + timedelta(days=(i // 2))
        bar_idx = (i % 2) + 1
        o = price + 0.5
        c = price - 1.0
        rows.append({
            "date_et": d,
            "bar_index": bar_idx,
            "open": o,
            "high": o + 0.2,
            "low": c - 0.2,
            "close": c,
            "volume": 10000,
            "timestamp_et": pd.Timestamp(f"{d} {'09:30' if bar_idx == 1 else '13:30'}"),
        })
        price = c

    bars = pd.DataFrame(rows)
    vix = _make_vix_df(20.0)  # VIX < 25 — should block all entries
    earnings = _empty_earnings()

    trades = _run_with_synthetic(bars, vix, earnings, earnings_buffer_days=0)
    assert len(trades) == 0


def test_earnings_filter_blocks_entry():
    """earnings_buffer_days=3 blocks entry on a date within ±3d of earnings."""
    rows = []
    base = date(2022, 1, 3)
    price = 100.0
    for i in range(50):
        d = base + timedelta(days=(i // 2))
        bar_idx = (i % 2) + 1
        o = price + 0.5
        c = price - 1.0
        rows.append({
            "date_et": d,
            "bar_index": bar_idx,
            "open": o,
            "high": o + 0.2,
            "low": c - 0.2,
            "close": c,
            "volume": 10000,
            "timestamp_et": pd.Timestamp(f"{d} {'09:30' if bar_idx == 1 else '13:30'}"),
        })
        price = c

    bars = pd.DataFrame(rows)
    vix = _make_vix_df(30.0)

    # Earnings on every date in range → buffer=3 blocks everything
    dates_in_range = pd.date_range("2022-01-01", "2023-12-31", freq="D")
    earnings = pd.DataFrame({
        "ticker": ["AAPL"] * len(dates_in_range),
        "earnings_date": dates_in_range,
    })

    trades = _run_with_synthetic(bars, vix, earnings, earnings_buffer_days=3)
    assert len(trades) == 0


def test_ema21_touch_exits_trade():
    """First 4H bar where close ≥ EMA21 exits the trade with reason ema21_touch."""
    # Build: flat bars then sharp drop (entry), then sharp recovery (EMA21 touch)
    rows = []
    base = date(2022, 1, 3)
    # Phase 1: 30 flat-ish bars for EMA21 warmup around 100
    price = 100.0
    for i in range(30):
        d = base + timedelta(days=(i // 2))
        bar_idx = (i % 2) + 1
        o = price + 0.1
        c = price - 0.05
        rows.append({
            "date_et": d,
            "bar_index": bar_idx,
            "open": o,
            "high": o + 0.1,
            "low": c - 0.1,
            "close": c,
            "volume": 10000,
            "timestamp_et": pd.Timestamp(f"{d} {'09:30' if bar_idx == 1 else '13:30'}"),
        })
        price = c

    # Phase 2: 3 deep RED bars (streak) + enough downtrend for RSI<35
    for j in range(15):
        i = 30 + j
        d = base + timedelta(days=(i // 2) + 15)
        bar_idx = (i % 2) + 1
        o = price + 0.5
        c = price - 2.0
        rows.append({
            "date_et": d,
            "bar_index": bar_idx,
            "open": o,
            "high": o + 0.2,
            "low": c - 0.2,
            "close": c,
            "volume": 10000,
            "timestamp_et": pd.Timestamp(f"{d} {'09:30' if bar_idx == 1 else '13:30'}"),
        })
        price = c

    # Phase 3: strong recovery bar that should exceed EMA21
    i = 45
    d = base + timedelta(days=(i // 2) + 22)
    bar_idx = 1
    recovery_price = rows[0]["close"] + 5.0  # well above initial EMA21 warmup level
    rows.append({
        "date_et": d,
        "bar_index": bar_idx,
        "open": price,
        "high": recovery_price + 1.0,
        "low": price - 0.1,
        "close": recovery_price,
        "volume": 10000,
        "timestamp_et": pd.Timestamp(f"{d} 09:30"),
    })

    bars = pd.DataFrame(rows)
    vix = _make_vix_df(30.0, n_days=500)
    earnings = _empty_earnings()

    trades = _run_with_synthetic(bars, vix, earnings, earnings_buffer_days=0)
    ema21_exits = [t for t in trades if t["exit_reason"] == "ema21_touch"]
    assert len(ema21_exits) >= 1


def test_hard_max_exits_at_10_bars():
    """Trade open for 10 bars without EMA21 touch closes at hard_max."""
    # Build: downtrend entry, then flat recovery that never touches EMA21
    rows = []
    base = date(2022, 1, 3)
    price = 100.0
    for i in range(60):
        d = base + timedelta(days=(i // 2))
        bar_idx = (i % 2) + 1
        # Strong downtrend throughout → RSI<35, no EMA21 touch
        o = price + 0.5
        c = price - 1.0
        rows.append({
            "date_et": d,
            "bar_index": bar_idx,
            "open": o,
            "high": o + 0.2,
            "low": c - 0.2,
            "close": c,
            "volume": 10000,
            "timestamp_et": pd.Timestamp(f"{d} {'09:30' if bar_idx == 1 else '13:30'}"),
        })
        price = c

    bars = pd.DataFrame(rows)
    vix = _make_vix_df(30.0)
    earnings = _empty_earnings()

    trades = _run_with_synthetic(bars, vix, earnings, earnings_buffer_days=0)
    hard_max = [t for t in trades if t["exit_reason"] == "hard_max"]
    assert len(hard_max) >= 1
    for t in hard_max:
        assert t["bars_held"] == 10
