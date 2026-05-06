"""Tests for m4_max_bars_bar_by_bar_sweep.py — counterfactual logic.

Synthetic trade rows exercise the bar-walk and counterfactual computation
paths without touching real M5 data.
"""
import pandas as pd
import pytest

from scripts.m4_max_bars_bar_by_bar_sweep import (
    MAX_BARS_VARIANTS,
    _compute_counterfactual_exit,
    _walk_forward_bars,
    compute_counterfactual_sweep,
    compute_per_year_sweep,
)


def _fake_enriched_trade(
    bars_held: int,
    actual_return: float,
    entry_price: float,
    bar_closes: dict,
    exit_type: str = "hard_max",
    year: int = 2025,
) -> pd.Series:
    data = {
        "ticker": "TEST",
        "entry_date": "2025-01-01",
        "exit_date": "2025-01-05",
        "bars_held": bars_held,
        "return_pct": actual_return,
        "entry_price": entry_price,
        "exit_price": entry_price * (1 + actual_return / 100.0),
        "exit_type": exit_type,
        "year": year,
        "enrich_status": "ok",
        "bars_walked": 10,
    }
    for n in range(1, 11):
        data[f"bar{n}_close"] = bar_closes.get(n, float("nan"))
    return pd.Series(data)


def test_max_bars_variants_includes_canonical_10():
    """Canonical M4 MAX_BARS=10 must be in tested variants."""
    assert 10 in MAX_BARS_VARIANTS
    assert MAX_BARS_VARIANTS == [4, 5, 6, 7, 8, 9, 10]


def test_counterfactual_passthrough_when_actual_within_cap():
    """Trade exited at bar 5 with cap=8 → keep original return."""
    trade = _fake_enriched_trade(
        bars_held=5,
        actual_return=4.50,
        entry_price=100.0,
        bar_closes={5: 104.50},
    )
    assert _compute_counterfactual_exit(trade, max_bars_cap=8) == 4.50


def test_counterfactual_synthetic_when_cap_lower_than_actual():
    """Trade held 10 bars, cap=6 → synthetic exit at bar6_close."""
    trade = _fake_enriched_trade(
        bars_held=10,
        actual_return=-3.71,
        entry_price=100.0,
        bar_closes={
            1: 99.0, 2: 98.5, 3: 99.5, 4: 100.5, 5: 101.0,
            6: 102.0,  # synthetic exit at +2%
            7: 100.0, 8: 99.0, 9: 97.0, 10: 96.29,
        },
    )
    result = _compute_counterfactual_exit(trade, max_bars_cap=6)
    assert result is not None
    assert abs(result - 2.0) < 1e-6


def test_counterfactual_returns_none_when_bar_data_missing():
    """If bar{cap}_close is NaN, return None (caller skips)."""
    trade = _fake_enriched_trade(
        bars_held=10,
        actual_return=-3.71,
        entry_price=100.0,
        bar_closes={1: 99.0, 2: 98.0},  # bar6_close is NaN
    )
    assert _compute_counterfactual_exit(trade, max_bars_cap=6) is None


def test_counterfactual_passthrough_at_exact_cap_boundary():
    """bars_held == cap is passthrough, not synthetic (boundary check)."""
    trade = _fake_enriched_trade(
        bars_held=6,
        actual_return=3.0,
        entry_price=100.0,
        bar_closes={6: 103.0},
    )
    assert _compute_counterfactual_exit(trade, max_bars_cap=6) == 3.0


def test_compute_sweep_aggregates_correctly():
    """Sweep over a tiny synthetic enriched DF returns expected metrics."""
    rows = [
        # Trade A: held 4 bars (ema21), +5% — passthrough at all caps
        _fake_enriched_trade(
            4, 5.0, 100.0,
            {1: 100.5, 2: 101.0, 3: 102.5, 4: 105.0},
            exit_type="ema21",
        ),
        # Trade B: held 10 bars (hard_max), -3% actual — synthetic varies
        _fake_enriched_trade(
            10, -3.0, 100.0,
            {1: 99.0, 2: 98.0, 3: 99.0, 4: 101.0, 5: 102.0,
             6: 102.0, 7: 100.0, 8: 99.0, 9: 97.0, 10: 97.0},
        ),
    ]
    enriched = pd.DataFrame(rows)
    sweep = compute_counterfactual_sweep(enriched)

    # cap=4: A passthrough +5%, B synthetic at bar4_close=101 → +1%. total=6, mean=3
    assert sweep[4]["N"] == 2
    assert abs(sweep[4]["total_return"] - 6.0) < 1e-6
    assert abs(sweep[4]["mean_return"] - 3.0) < 1e-6
    # cap=10: A passthrough +5%, B passthrough -3%. total=2
    assert abs(sweep[10]["total_return"] - 2.0) < 1e-6
    # WR at cap=4: both positive
    assert sweep[4]["win_rate"] == 1.0
    # WR at cap=10: 1 of 2
    assert sweep[10]["win_rate"] == 0.5


def test_walk_forward_returns_empty_when_entry_date_absent():
    """Bar walking returns [] if entry_date isn't in 4H bars."""
    bars = pd.DataFrame(
        [
            {"date_et": pd.Timestamp("2025-01-02").date(), "bar_label": "B", "close": 100.0},
            {"date_et": pd.Timestamp("2025-01-02").date(), "bar_label": "C", "close": 101.0},
        ]
    )
    walked = _walk_forward_bars(bars, pd.Timestamp("2025-01-01"), max_bars=10)
    assert walked == []


def test_walk_forward_walks_max_bars_steps_after_entry():
    """Bar walking captures bar_idx 1..max_bars after start of entry_date."""
    rows = []
    # 5 days × 2 bars = 10 forward bars after entry day's first bar
    base = pd.Timestamp("2025-01-02")
    for i in range(6):
        d = (base + pd.Timedelta(days=i)).date()
        rows.append({"date_et": d, "bar_label": "B", "close": 100.0 + i * 2})
        rows.append({"date_et": d, "bar_label": "C", "close": 101.0 + i * 2})
    bars = pd.DataFrame(rows)
    walked = _walk_forward_bars(bars, pd.Timestamp("2025-01-02"), max_bars=10)
    # bar_idx 1 is the second bar of entry_date (the C bar at 101.0)
    assert len(walked) == 10
    assert walked[0]["bar_idx"] == 1
    assert walked[0]["close"] == 101.0
    assert walked[-1]["bar_idx"] == 10


def test_per_year_sweep_keys_match_input_years():
    """Per-year sweep returns one entry per distinct year in enriched."""
    rows = [
        _fake_enriched_trade(4, 5.0, 100.0, {4: 105.0}, year=2025),
        _fake_enriched_trade(4, -2.0, 100.0, {4: 98.0}, year=2026),
    ]
    enriched = pd.DataFrame(rows)
    by_year = compute_per_year_sweep(enriched)
    assert set(by_year.keys()) == {2025, 2026}
    for yr in (2025, 2026):
        assert all(cap in by_year[yr] for cap in MAX_BARS_VARIANTS)
