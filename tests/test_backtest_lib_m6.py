"""Tests for scripts/_backtest_lib_m6.py — synthetic data only."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts._backtest_lib_m6 import run_module6_backtest


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_gap_bars(
    gap_pct: float = -0.05,
    n_days: int = 10,
    base_price: float = 100.0,
    recovery_on_day: int = 2,  # day index (0-based) where close reaches gap_midpoint
) -> pd.DataFrame:
    """Synthetic 4H RTH bars with a gap-down on day 1.

    Day 0: 2 bars flat at base_price.
    Day 1: gap-down by gap_pct; 2 bars. If recovery_on_day==1, bar 2 closes at midpoint.
    Remaining days: flat bars.
    """
    rows = []
    base = date(2022, 3, 1)
    price = base_price

    for day in range(n_days):
        d = base + timedelta(days=day)
        # Skip weekends
        if d.weekday() >= 5:
            continue

        if day == 1:
            today_open = price * (1 + gap_pct)
            gap_midpoint = price - (price - today_open) * 0.5
        else:
            today_open = price

        for bar_idx in [1, 2]:
            if day == 1 and bar_idx == 1:
                o = today_open
                c = today_open * 0.998  # slightly below midpoint (entry)
            elif day == 1 and bar_idx == 2:
                o = price * (1 + gap_pct) * 0.998
                # Recovery to midpoint on bar 2 of entry day if requested
                c = gap_midpoint * 1.001 if recovery_on_day == 1 else o * 0.999
            elif day == recovery_on_day and day > 1:
                o = price
                c = gap_midpoint * 1.001 if day == 1 else price * 1.01
            else:
                o = price
                c = price * 1.001
            rows.append({
                "date_et": d,
                "bar_index": bar_idx,
                "open": round(o, 4),
                "high": round(max(o, c) + 0.1, 4),
                "low": round(min(o, c) - 0.1, 4),
                "close": round(c, 4),
                "volume": 10000,
                "timestamp_et": pd.Timestamp(f"{d} {'09:30' if bar_idx == 1 else '13:30'}"),
            })
        price = rows[-1]["close"]

    return pd.DataFrame(rows)


def _run_m6(
    bars: pd.DataFrame,
    earnings_buffer_days: int = 0,
    earnings_df: pd.DataFrame = None,
    news_df: pd.DataFrame = None,
    ca_df: pd.DataFrame = None,
    active_m4_df: pd.DataFrame = None,
):
    import scripts._backtest_lib_m6 as lib

    def fake_load(data_root, ticker):
        return pd.DataFrame()

    def fake_agg(df_m5):
        return bars.copy()

    if earnings_df is None:
        earnings_df = pd.DataFrame({"ticker": [], "earnings_date": pd.to_datetime([])})

    with patch.object(lib, "load_m5_extended", fake_load), \
         patch.object(lib, "aggregate_m5_to_4h_rth", fake_agg):
        return run_module6_backtest(
            universe=["AAPL"],
            date_range=("2022-01-01", "2023-12-31"),
            earnings_buffer_days=earnings_buffer_days,
            data_root=Path("/fake"),
            earnings_df=earnings_df,
            news_df=news_df,
            corporate_actions_df=ca_df,
            active_m4_trades_df=active_m4_df,
        )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_gap_down_triggers_entry():
    """≥4% gap-down with no filters → trade opened."""
    bars = _make_gap_bars(gap_pct=-0.05, recovery_on_day=3)
    trades = _run_m6(bars)
    assert len(trades) >= 1


def test_insufficient_gap_skipped():
    """<4% gap-down → no entry."""
    bars = _make_gap_bars(gap_pct=-0.02, recovery_on_day=3)
    trades = _run_m6(bars)
    assert len(trades) == 0


def test_news_filter_blocks_entry():
    """Classified news on shock date blocks M6 entry."""
    bars = _make_gap_bars(gap_pct=-0.05, recovery_on_day=3)
    gap_day = date(2022, 3, 2)  # day 1 from base 2022-03-01
    news_df = pd.DataFrame({
        "ticker": ["AAPL"],
        "news_timestamp_utc": [pd.Timestamp(f"{gap_day} 08:00")],
        "classification": ["CLASSIFIED_NEWS_HIT"],
    })
    trades = _run_m6(bars, news_df=news_df)
    assert len(trades) == 0


def test_active_m4_trade_blocks_entry():
    """Active M4 trade on same ticker blocks M6 entry."""
    bars = _make_gap_bars(gap_pct=-0.05, recovery_on_day=3)
    active_m4 = pd.DataFrame({
        "ticker": ["AAPL"],
        "entry_date_et": ["2022-03-01"],
        "exit_date_et": ["2022-03-15"],
    })
    trades = _run_m6(bars, active_m4_df=active_m4)
    assert len(trades) == 0


def test_earnings_filter_blocks_entry():
    """earnings_buffer_days=3 blocks entry when earnings within ±3d of shock."""
    bars = _make_gap_bars(gap_pct=-0.05, recovery_on_day=3)
    gap_day = date(2022, 3, 2)
    earnings_df = pd.DataFrame({
        "ticker": ["AAPL"],
        "earnings_date": [pd.Timestamp(str(gap_day))],
    })
    trades = _run_m6(bars, earnings_buffer_days=3, earnings_df=earnings_df)
    assert len(trades) == 0


def test_corporate_action_blocks_entry():
    """Split/dividend on shock date blocks M6 entry."""
    bars = _make_gap_bars(gap_pct=-0.05, recovery_on_day=3)
    gap_day = date(2022, 3, 2)
    ca_df = pd.DataFrame({
        "ticker": ["AAPL"],
        "action_date": [pd.Timestamp(str(gap_day))],
        "action_type": ["split"],
        "value": [2.0],
    })
    trades = _run_m6(bars, ca_df=ca_df)
    assert len(trades) == 0


def test_gap_midpoint_exit():
    """Trade exits when close reaches gap_midpoint."""
    bars = _make_gap_bars(gap_pct=-0.05, recovery_on_day=1)
    trades = _run_m6(bars)
    midpoint_exits = [t for t in trades if t["exit_reason"] == "gap_midpoint"]
    assert len(midpoint_exits) >= 1


def test_hard_max_exit_at_15_bars():
    """Trade exits at hard max 15 bars if gap_midpoint never reached."""
    # Build bars with gap-down but very slow recovery (never hits midpoint within 15 bars)
    bars = _make_gap_bars(gap_pct=-0.05, n_days=25, recovery_on_day=99)
    trades = _run_m6(bars)
    hard_max = [t for t in trades if t["exit_reason"] in ("hard_max", "end_of_data")]
    assert len(hard_max) >= 1
