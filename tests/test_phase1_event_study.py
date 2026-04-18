"""8 unit tests for scripts/phase1_event_study.py.

All tests use synthetic DataFrames — no real CSV files are opened.
Run: pytest tests/test_phase1_event_study.py -v
"""

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[1]
for _p in (str(_REPO), str(_REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.phase1_event_study import (  # noqa: E402
    compression_score_from_baseline,
    _bucket_name,
    _compute_buckets,
    _kill_switch,
    _metrics,
    _process_session,
)


# ── Fixture helpers ────────────────────────────────────────────────────────────

def _stub_baseline(ticker: str = "TEST", values: list | None = None, n: int = 200):
    """Build a minimal baseline dict with known sorted_values."""
    if values is None:
        values = sorted(np.linspace(0.001, 0.200, n).tolist())
    return {
        "tickers_accepted": [ticker],
        "per_zone_distributions": {
            ticker: {"Z3": {"sorted_values": values, "sample_size": len(values)}}
        },
    }


def _session_df(
    z3_n: int = 18,
    z3_open: float = 100.0,
    z3_high: float = 102.0,
    z4_open: float = 100.5,
    z4_close: float = 101.0,
    fwd_closes: list | None = None,
) -> pd.DataFrame:
    """Build a minimal RTH session DataFrame with explicit OHLC prices.

    Slots covered:
        Z3  : 30-47  (18 bars, 12:00-13:25 ET)
        Z4  : 48     ( 1 bar, 13:30 ET)
        fwd : 49-56  ( 8 bars, 13:35-14:10 ET)
    """
    def _ts(slot: int) -> pd.Timestamp:
        total_min = 570 + slot * 5   # 570 = 9h30 in minutes
        return pd.Timestamp(f"2025-06-10 {total_min // 60:02d}:{total_min % 60:02d}:00")

    rows = []

    # Z3 bars (slots 30-47)
    for i in range(z3_n):
        slot = 30 + i
        rows.append({
            "slot_id": slot,
            "open":    z3_open,
            "high":    z3_high if i == z3_n - 1 else z3_open * 1.003,
            "low":     z3_open * 0.997,
            "close":   z3_open * 1.001,
            "date":    _ts(slot),
        })

    # Z4 first bar (slot 48)
    rows.append({
        "slot_id": 48,
        "open":    z4_open,
        "high":    max(z4_open, z4_close) * 1.001,
        "low":     min(z4_open, z4_close) * 0.999,
        "close":   z4_close,
        "date":    _ts(48),
    })

    # Forward 8 bars (slots 49-56)
    if fwd_closes is None:
        fwd_closes = [z4_open * 1.001] * 7 + [z4_open * 1.03]
    for i, close_ in enumerate(fwd_closes[:8]):
        slot = 49 + i
        rows.append({
            "slot_id": slot,
            "open":    z4_open,
            "high":    close_ * 1.001,
            "low":     z4_open * 0.999,
            "close":   close_,
            "date":    _ts(slot),
        })

    return pd.DataFrame(rows)


def _session_record(
    cs: float,
    ticker: str,
    session_date: date,
    breakout: bool = True,
    eight_bar_ret: float = 1.0,
    spy_adj: float | None = 0.5,
    mfe: float = 1.5,
    mae: float = -0.5,
) -> dict:
    """Build a pre-processed session dict for bucketing/kill-switch tests."""
    return {
        "compression_score": cs,
        "ticker":            ticker,
        "session_date":      session_date,
        "breakout":          breakout,
        "eight_bar_ret":     eight_bar_ret,
        "spy_adj_ret":       spy_adj,
        "mfe":               mfe,
        "mae":               mae,
    }


# ── Test 1: compression_score formula ─────────────────────────────────────────

def test_compression_score_formula():
    """Known inputs produce expected searchsorted-based percentile ranks."""
    # 200 linearly spaced values: 0.001, 0.002, ..., 0.200
    n      = 200
    values = [0.001 * (i + 1) for i in range(n)]
    bl     = _stub_baseline("T", values=values)

    # Below minimum → rank 0 → score 0.0
    assert compression_score_from_baseline(bl, "T", 0.0) == pytest.approx(0.0)

    # Exactly at first element → searchsorted right → rank 1 → score 1/200
    assert compression_score_from_baseline(bl, "T", 0.001) == pytest.approx(1 / n)

    # Exactly at median element → rank 100 → score 0.5
    assert compression_score_from_baseline(bl, "T", 0.100) == pytest.approx(100 / n)

    # At maximum → rank 200 → score 1.0
    assert compression_score_from_baseline(bl, "T", 0.200) == pytest.approx(1.0)

    # Above maximum → capped at 1.0
    assert compression_score_from_baseline(bl, "T", 99.9) == pytest.approx(1.0)


def test_compression_score_abstain_for_small_n():
    """Returns 0.5 when sorted_values has fewer than 100 entries."""
    bl = _stub_baseline("T", values=[0.001 * i for i in range(50)])
    assert compression_score_from_baseline(bl, "T", 0.025) == 0.5


# ── Test 2: Z3 extraction requires exactly 18 bars ───────────────────────────

def test_z3_extraction_requires_18_bars():
    """Session with 17 Z3 bars is rejected (returns None)."""
    bl  = _stub_baseline()
    day = _session_df(z3_n=17)
    assert _process_session(day, None, bl, "TEST") is None


# ── Test 3: breakout indicator ────────────────────────────────────────────────

def test_breakout_indicator():
    """z4_close > z3_high → breakout=True; z4_close ≤ z3_high → breakout=False."""
    bl = _stub_baseline()

    # z3_high=102, z4_close=103 → breakout
    sess = _process_session(_session_df(z3_high=102.0, z4_close=103.0), None, bl, "TEST")
    assert sess is not None
    assert sess["breakout"] is True

    # z3_high=102, z4_close=101 → no breakout
    sess2 = _process_session(_session_df(z3_high=102.0, z4_close=101.0), None, bl, "TEST")
    assert sess2 is not None
    assert sess2["breakout"] is False

    # z3_high=102, z4_close=102 → no breakout (not strictly greater)
    sess3 = _process_session(_session_df(z3_high=102.0, z4_close=102.0), None, bl, "TEST")
    assert sess3 is not None
    assert sess3["breakout"] is False


# ── Test 4: eight-bar forward return ──────────────────────────────────────────

def test_eight_bar_forward_return():
    """eight_bar_ret = (last_fwd_close - signal_ref) / signal_ref × 100."""
    bl         = _stub_baseline()
    signal_ref = 100.0   # z4_open
    last_close = 102.0   # 2% above signal_ref
    fwd_closes = [signal_ref * 1.001] * 7 + [last_close]

    day  = _session_df(z4_open=signal_ref, z4_close=101.0, fwd_closes=fwd_closes)
    sess = _process_session(day, None, bl, "TEST")

    assert sess is not None
    expected = (last_close - signal_ref) / signal_ref * 100.0  # = 2.0
    assert sess["eight_bar_ret"] == pytest.approx(expected, rel=1e-9)


# ── Test 5: SPY adjustment ────────────────────────────────────────────────────

def test_spy_adjustment():
    """Ticker return 2%, SPY return 0.5% → spy_adjusted_return = 1.5%."""
    bl = _stub_baseline()

    # Ticker: signal_ref=100, last_fwd_close=102  → ticker_ret = 2.0%
    ticker_ref = 100.0
    ticker_fwd = [ticker_ref * 1.001] * 7 + [ticker_ref * 1.02]
    ticker_day = _session_df(z4_open=ticker_ref, z4_close=ticker_ref,
                             fwd_closes=ticker_fwd)

    # SPY: signal_ref=400, last_fwd_close=402  → spy_ret = 0.5%
    spy_ref = 400.0
    spy_fwd = [spy_ref * 1.001] * 7 + [spy_ref * 1.005]
    spy_day = _session_df(z4_open=spy_ref, z4_close=spy_ref,
                          fwd_closes=spy_fwd)

    sess = _process_session(ticker_day, spy_day, bl, "TEST")
    assert sess is not None
    assert sess["eight_bar_ret"] == pytest.approx(2.0, rel=1e-6)
    assert sess["spy_adj_ret"]   == pytest.approx(1.5, rel=1e-6)


# ── Test 6: exclusion filter independence ──────────────────────────────────────

def test_exclusion_filters_independence():
    """earnings_excluded ⊆ full; hi_day_excluded ⊆ earnings_excluded."""
    # Session 1: normal day (Feb 15 — far from earnings) → all three versions
    # Session 2: earnings day for T (Mar 10) → full only
    # Session 3: FOMC hi-impact day, not earnings (Jan 29) → full + earnings_excluded
    #
    # Note: is_earnings_window uses buffer_days=6, so Mar 5 (5 days before Mar 10)
    # would also be excluded.  We use Feb 15 (23 days away) as the safe normal day.
    sessions = [
        _session_record(0.15, "T", date(2025, 2, 15)),   # normal (far from earnings)
        _session_record(0.15, "T", date(2025, 3, 10)),   # earnings day for T
        _session_record(0.15, "T", date(2025, 1, 29)),   # FOMC hi-impact, no earnings
    ]
    earnings_dict = {"T": [date(2025, 3, 10)]}

    buckets  = _compute_buckets(sessions, earnings_dict)
    full_n   = buckets["deep"]["full"]["N"]
    ee_n     = buckets["deep"]["earnings_excluded"]["N"]
    hiday_n  = buckets["deep"]["earnings_and_hi_day_excluded"]["N"]

    assert full_n  == 3
    assert ee_n    == 2    # Mar-10 earnings day removed; Jan-29 FOMC kept
    assert hiday_n == 1    # Jan-29 FOMC day also removed
    assert full_n >= ee_n >= hiday_n


# ── Test 7: bucketing boundary values ─────────────────────────────────────────

def test_bucketing_boundaries():
    """score=0.30 → deep; score=0.70 → active; 0.31–0.69 → neutral."""
    assert _bucket_name(0.00)  == "deep"
    assert _bucket_name(0.30)  == "deep"    # boundary inclusive
    assert _bucket_name(0.31)  == "neutral"
    assert _bucket_name(0.50)  == "neutral"
    assert _bucket_name(0.69)  == "neutral"
    assert _bucket_name(0.70)  == "active"  # boundary inclusive
    assert _bucket_name(1.00)  == "active"


# ── Test 8: kill-switch — all four criteria must pass ─────────────────────────

def test_kill_switch_all_four_must_pass():
    """Any single criterion failure flips recommendation to SHELVE."""

    def _bkt(deep_br, neutral_br, deep_spy, neutral_spy, deep_n):
        def _m(br, spy, n):
            return {
                "N": n, "breakout_rate": br,
                "mean_spy_adj_return_8bar": spy,
                "mean_return_8bar": 0.0,
                "mfe_p50": 0.5, "mfe_p90": 1.5,
                "mae_p50": -0.3, "mae_p90": -0.8,
            }
        return {
            "deep":    {"earnings_excluded": _m(deep_br,    deep_spy,    deep_n)},
            "neutral": {"earnings_excluded": _m(neutral_br, neutral_spy, 200)},
            "active":  {"earnings_excluded": _m(0.25,       0.0,         100)},
        }

    # All four pass → PROCEED
    _, rec = _kill_switch(_bkt(0.30, 0.20, 0.50, 0.30, 50))
    assert rec == "PROCEED_TO_PHASE_2"

    # Fail C1: deep breakout ≤ neutral breakout
    _, rec = _kill_switch(_bkt(0.10, 0.20, 0.50, 0.30, 50))
    assert rec == "SHELVE_M8_PHASE_B_GATE_MAY_STILL_PROCEED"

    # Fail C2: deep SPY-adj ≤ neutral SPY-adj
    _, rec = _kill_switch(_bkt(0.30, 0.20, 0.10, 0.30, 50))
    assert rec == "SHELVE_M8_PHASE_B_GATE_MAY_STILL_PROCEED"

    # Fail C3: deep N < 40
    _, rec = _kill_switch(_bkt(0.30, 0.20, 0.50, 0.30, 39))
    assert rec == "SHELVE_M8_PHASE_B_GATE_MAY_STILL_PROCEED"

    # Fail C4: deep breakout_rate < 0.20
    _, rec = _kill_switch(_bkt(0.19, 0.10, 0.50, 0.30, 50))
    assert rec == "SHELVE_M8_PHASE_B_GATE_MAY_STILL_PROCEED"
