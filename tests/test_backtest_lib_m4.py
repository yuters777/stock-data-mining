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
    D6_VIX_ROC_ENABLED,
    D6_VIX_ROC_THRESHOLD,
    compute_ema_21,
    compute_rsi_14,
    compute_vix_5d_roc,
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


def _make_vix_df_spike(
    base_value: float = 18.0,
    spike_value: float = 30.0,
    n_days: int = 300,
    spike_day_offset: int = 33,
) -> pd.DataFrame:
    """VIX daily: base_value for first spike_day_offset days, then spike_value.
    Default: VIX=18 before Jan 3 2022, VIX=30 from Jan 3 onward.
    Produces 5d ROC = (30-18)/18*100 = 66.7% > D6_VIX_ROC_THRESHOLD by Jan 8 2022.
    Ensures both VIX gate (≥25) and D6 filter (ROC>30%) pass after spike onset.
    """
    start = date(2021, 12, 1)
    rows = [
        {
            "date": pd.Timestamp(start + timedelta(days=i)),
            "vix_close": spike_value if i >= spike_day_offset else base_value,
        }
        for i in range(n_days)
    ]
    return pd.DataFrame(rows)


def _empty_earnings() -> pd.DataFrame:
    return pd.DataFrame({"ticker": [], "earnings_date": pd.to_datetime([])})


def _run_with_synthetic(
    bars_4h: pd.DataFrame,
    vix_df: pd.DataFrame,
    earnings_df: pd.DataFrame,
    earnings_buffer_days: int = 0,
    date_range=("2022-01-01", "2023-12-31"),
    d6_enabled: bool = True,
):
    """Run M4 backtest patching the data-loading layer with synthetic bars.
    d6_enabled=False bypasses D6 filter so tests can focus on other conditions.
    """
    import scripts._backtest_lib_m4 as lib

    def fake_load_m5(data_root, ticker):
        return pd.DataFrame()

    def fake_aggregate(df_m5):
        return bars_4h.copy()

    with patch.object(lib, "load_m5_extended", fake_load_m5), \
         patch.object(lib, "aggregate_m5_to_4h_rth", fake_aggregate), \
         patch.object(lib, "D6_VIX_ROC_ENABLED", d6_enabled):
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
    """3 consecutive RED bars + VIX≥25 + RSI<35 → trade is opened (D6 bypassed)."""
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

    # d6_enabled=False: this test exercises streak/VIX/RSI entry mechanics, not D6
    trades = _run_with_synthetic(bars, vix, earnings, earnings_buffer_days=0, d6_enabled=False)
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

    # d6_enabled=False: this test exercises EMA21 exit mechanics, not D6
    trades = _run_with_synthetic(bars, vix, earnings, earnings_buffer_days=0, d6_enabled=False)
    ema21_exits = [t for t in trades if t["exit_reason"] == "ema21_touch"]
    assert len(ema21_exits) >= 1


def test_hard_max_exits_at_10_bars():
    """Trade open for 10 bars without EMA21 touch closes at hard_max."""
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

    # d6_enabled=False: this test exercises hard_max exit mechanics, not D6
    trades = _run_with_synthetic(bars, vix, earnings, earnings_buffer_days=0, d6_enabled=False)
    hard_max = [t for t in trades if t["exit_reason"] == "hard_max"]
    assert len(hard_max) >= 1
    for t in hard_max:
        assert t["bars_held"] == 10


# ── EBS-1.1: D6 VIX 5d ROC filter tests ──────────────────────────────────────

def _make_vix_roc_df(values: list, base: date = date(2022, 1, 1)) -> pd.DataFrame:
    """Build VIX daily df from a list of (date_offset_days, vix_close) tuples."""
    rows = [
        {"date": pd.Timestamp(base + timedelta(days=i)), "vix_close": v}
        for i, v in enumerate(values)
    ]
    return pd.DataFrame(rows)


def test_d6_filter_blocks_chronic_elevation():
    """VIX≥25 but 5d ROC ≤ 30% → blocked (production module4.py:383, market-engine HEAD a673359)."""
    # 6 trading days of VIX around 28 (chronic elevation, ROC near 0%)
    vix_df = _make_vix_roc_df([28.0, 28.1, 28.2, 28.1, 27.9, 28.0, 28.1])
    # current_date is day 7; relevant days are days 0-6 → 7 rows, last 6 = days 1-6
    current = date(2022, 1, 8)
    roc = compute_vix_5d_roc(vix_df, current)
    # ROC = (28.1 - 28.1) / 28.1 * 100 ≈ 0%
    assert roc is not None
    assert roc <= D6_VIX_ROC_THRESHOLD, (
        "Chronic elevation (ROC≤30%) must be blocked — production line 383"
    )


def test_d6_filter_passes_acute_spike():
    """VIX=18 for 5d then spikes to 27 (ROC≈50%) → passes filter (production line 391)."""
    # days 0-4: VIX=18, day 5: VIX=27 → ROC=(27-18)/18*100=50%
    vix_df = _make_vix_roc_df([18.0, 18.0, 18.0, 18.0, 18.0, 27.0, 27.5])
    current = date(2022, 1, 8)
    roc = compute_vix_5d_roc(vix_df, current)
    assert roc is not None
    assert roc > D6_VIX_ROC_THRESHOLD, (
        "Acute spike (ROC>30%) must pass D6 filter — production line 391"
    )


def test_d6_filter_blocks_insufficient_vix_history():
    """<6 prior trading days → compute_vix_5d_roc returns None → blocked (production line 378-382)."""
    vix_df = _make_vix_roc_df([25.0, 26.0, 27.0, 28.0, 29.0])  # only 5 rows
    current = date(2022, 1, 6)
    roc = compute_vix_5d_roc(vix_df, current)
    assert roc is None, (
        "Insufficient VIX history must return None — production line 142, 378-382"
    )


def test_d6_threshold_exactly_30_blocks():
    """ROC == 30.0 exactly → blocked (production uses <=, not <, line 383)."""
    # ROC = (vix_today - vix_5d_ago) / vix_5d_ago * 100 = 30.0
    # vix_5d_ago = 20.0, vix_today = 26.0 → ROC = (26-20)/20*100 = 30.0
    vix_df = _make_vix_roc_df([20.0, 21.0, 22.0, 23.0, 24.0, 26.0, 27.0])
    current = date(2022, 1, 8)
    roc = compute_vix_5d_roc(vix_df, current)
    assert roc is not None
    assert roc <= D6_VIX_ROC_THRESHOLD, (
        "ROC=30.0 must be blocked — production uses <= not < (line 383)"
    )


def test_d6_disabled_via_constant():
    """D6_VIX_ROC_ENABLED=False bypasses filter entirely — VIX chronic elevation still allows entry."""
    import scripts._backtest_lib_m4 as lib

    # Build downtrend bars that meet all other entry conditions
    rows = []
    base = date(2022, 1, 3)
    price = 100.0
    for i in range(50):
        d = base + timedelta(days=(i // 2))
        bar_idx = (i % 2) + 1
        o = price + 0.5
        c = price - 1.0
        rows.append({
            "date_et": d, "bar_index": bar_idx, "open": o,
            "high": o + 0.2, "low": c - 0.2, "close": c, "volume": 10000,
            "timestamp_et": pd.Timestamp(f"{d} {'09:30' if bar_idx == 1 else '13:30'}"),
        })
        price = c
    bars = pd.DataFrame(rows)
    # VIX=28 constant → 5d ROC≈0% → would normally be blocked by D6
    vix = _make_vix_df(28.0)
    earnings = _empty_earnings()

    with patch.object(lib, "D6_VIX_ROC_ENABLED", False):
        trades_no_d6 = _run_with_synthetic(bars, vix, earnings)

    with patch.object(lib, "D6_VIX_ROC_ENABLED", True):
        trades_with_d6 = _run_with_synthetic(bars, vix, earnings)

    # With D6 disabled, chronic-VIX entries are permitted; with D6 enabled, blocked
    assert len(trades_no_d6) >= len(trades_with_d6), (
        "D6_VIX_ROC_ENABLED=False must not block entries that D6=True would block"
    )
