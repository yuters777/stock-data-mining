"""Tests for scripts/m6_transaction_cost_sweep.py — spec_2026_05_26_002."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.m6_transaction_cost_sweep import (
    BASELINE_PATH,
    COST_BPS,
    LEDGER_PATH,
    compute_row,
    ledger_digest,
    load_gross_returns,
    run_sweep,
)


def test_zero_bps_reproduces_baseline():
    """At cost_bps=0, pf/expectancy/win_rate/N match m6_rth_baseline.json within tolerance."""
    with BASELINE_PATH.open() as f:
        anchor = json.load(f)
    gross = load_gross_returns()
    row = compute_row(gross, 0)

    assert row["n"] == anchor["n"]
    pf = row["profit_factor"]
    assert isinstance(pf, float), f"Expected float PF at 0 bps, got {pf!r}"
    assert abs(pf - anchor["pf"]) <= 0.01, f"PF mismatch: {pf} vs {anchor['pf']}"
    assert abs(row["expectancy"] - anchor["mean"]) <= 0.01, (
        f"expectancy mismatch: {row['expectancy']} vs {anchor['mean']}"
    )
    assert abs(row["win_rate"] - anchor["wr"]) <= 0.1, (
        f"win_rate mismatch: {row['win_rate']} vs {anchor['wr']}"
    )


def test_cost_monotonic_non_increasing():
    """PF (where defined) and expectancy are monotonically non-increasing as cost_bps increases."""
    rows = run_sweep()
    for i in range(1, len(rows)):
        prev, curr = rows[i - 1], rows[i]

        assert curr["expectancy"] <= prev["expectancy"] + 1e-9, (
            f"expectancy increased at {curr['cost_bps']} bps: "
            f"{curr['expectancy']:.6f} > {prev['expectancy']:.6f}"
        )

        prev_pf = prev["profit_factor"]
        curr_pf = curr["profit_factor"]
        if prev_pf != "inf" and curr_pf != "inf":
            assert float(curr_pf) <= float(prev_pf) + 1e-9, (
                f"PF increased at {curr['cost_bps']} bps: "
                f"{float(curr_pf):.6f} > {float(prev_pf):.6f}"
            )


def test_input_ledger_not_mutated():
    """hashlib digest of m6_rth_trades_frozen.csv is byte-identical before and after a full sweep."""
    before = ledger_digest()
    run_sweep()
    after = ledger_digest()
    assert before == after, "Ledger file was mutated during sweep!"


def test_unit_conversion():
    """Gross return 1.00% at 10 bps yields net 0.90% (guards C5 bp->percent conversion)."""
    row = compute_row([1.00], 10)
    expected_net = 1.00 - 10 * 0.01  # = 0.90
    assert row["expectancy"] == pytest.approx(expected_net, abs=1e-9)
    assert row["win_rate"] == pytest.approx(100.0)
    assert row["n"] == 1


def test_n_constant_across_grid():
    """N == 544 at every cost level — cost changes trade sign, never trade count."""
    rows = run_sweep()
    assert [r["cost_bps"] for r in rows] == COST_BPS
    for row in rows:
        assert row["n"] == 544, f"N changed at {row['cost_bps']} bps: {row['n']}"


def test_loss_convention_includes_zero():
    """Net return of exactly 0.0 is classified as LOSS, not a win — guards C4 <= 0 convention.

    With net returns [+1.0, 0.0]:
      wins = [1.0]  (only > 0)
      losses = [0.0]  (<= 0, inclusive)
    Expected: win_rate = 50% (not 100%).
    sum(losses) = 0.0 → pf_undefined (inf), consistent with _compute_stats.
    """
    row = compute_row([1.0, 0.0], 0)
    assert row["win_rate"] == pytest.approx(50.0), (
        f"Expected WR=50% (0.0 is a loss, not a win), got {row['win_rate']}"
    )
    assert row["pf_undefined"] is True, (
        "losses=[0.0], sum=0 → should be pf_undefined (inf), not a finite PF"
    )
    assert row["profit_factor"] == "inf"


def test_pf_undefined_handled():
    """Zero net-losing trades (no net <= 0) → pf='inf', pf_undefined=True, no ZeroDivisionError."""
    all_wins = [1.0, 2.0, 3.0]
    row = compute_row(all_wins, 0)
    assert row["profit_factor"] == "inf"
    assert row["pf_undefined"] is True
    assert row["n"] == 3
    assert row["win_rate"] == pytest.approx(100.0)
