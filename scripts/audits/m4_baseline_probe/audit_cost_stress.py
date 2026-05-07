#!/usr/bin/env python3
"""Step 4.1 — Cost stress sensitivity at realistic VIX>=25 spreads.

Applies slippage assumptions to canonical trade ledger and computes PF
at 0, 5, 10, 15, 25, 50 bps round-trip. Uses best available local trades
(backtest_results/m4_5yr_trades.csv). Notes HARN-1.1 caveat.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from scripts.audits.m4_baseline_probe._constants import (
    LOCAL_TRADES_CSV,
    AUDITS_OUTPUT_DIR,
    CANONICAL_BASELINE_N,
    CANONICAL_BASELINE_PF,
    COST_STRESS_MIN_PF_AT_15BPS,
)

SLIPPAGE_BPS = [0, 5, 10, 15, 25, 50]


def _compute_pf(returns_pct: pd.Series, slippage_bps: float) -> float:
    """Compute profit factor after applying round-trip slippage (bps)."""
    adj = returns_pct - (slippage_bps / 100.0)
    gains = adj[adj > 0].sum()
    losses = adj[adj < 0].abs().sum()
    if losses == 0:
        return float("inf") if gains > 0 else float("nan")
    return float(gains / losses)


def _compute_wr(returns_pct: pd.Series, slippage_bps: float) -> float:
    adj = returns_pct - (slippage_bps / 100.0)
    if len(adj) == 0:
        return float("nan")
    return float((adj > 0).sum() / len(adj))


def audit_cost_stress(trades_path: Path | None = None) -> dict:
    path = trades_path or LOCAL_TRADES_CSV

    if not path.exists():
        return {
            "error": f"Trades CSV not found: {path}",
            "results": [],
            "breakeven_bps": None,
            "pass_at_15bps": False,
        }

    df = pd.read_csv(path)
    if "return_pct" not in df.columns:
        return {
            "error": f"'return_pct' column missing in {path}",
            "results": [],
            "breakeven_bps": None,
            "pass_at_15bps": False,
        }

    returns = df["return_pct"].astype(float)
    n = len(returns)

    results = []
    breakeven = None
    for bps in SLIPPAGE_BPS:
        pf = _compute_pf(returns, bps)
        wr = _compute_wr(returns, bps)
        pass_threshold = (pf >= COST_STRESS_MIN_PF_AT_15BPS) if np.isfinite(pf) else False
        if breakeven is None and bps > 0 and pf < COST_STRESS_MIN_PF_AT_15BPS:
            breakeven = bps
        results.append({
            "slippage_bps": bps,
            "pf": round(pf, 4) if np.isfinite(pf) else "inf",
            "wr": round(wr, 4),
            "n": n,
            "pass_10x_threshold": pass_threshold,
        })

    pf_at_15bps_entry = next((r for r in results if r["slippage_bps"] == 15), None)
    pf_at_15bps = pf_at_15bps_entry["pf"] if pf_at_15bps_entry else None
    pass_at_15bps = bool(pf_at_15bps_entry and pf_at_15bps_entry["pass_10x_threshold"])

    note = (
        f"HARN-1.1 NOTE: Local trades N={n} (vs canonical N={CANONICAL_BASELINE_N}). "
        f"Results are indicative; canonical PF={CANONICAL_BASELINE_PF:.2f}. "
        f"Cost stress at 0bps should approximate canonical PF if HARN-1.1 ratio holds."
    )

    return {
        "trades_file": str(path.relative_to(Path(__file__).parent.parent.parent.parent)),
        "n": n,
        "results": results,
        "pf_at_15bps": pf_at_15bps,
        "breakeven_bps": breakeven,
        "pass_at_15bps": pass_at_15bps,
        "harn_1_1_caveat": note,
        "canonical_pf": CANONICAL_BASELINE_PF,
        "canonical_n": CANONICAL_BASELINE_N,
    }


def _write_report(result: dict) -> Path:
    out_dir = AUDITS_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / "m4_baseline_probe_S304_cost_stress.md"

    lines = [
        "# Cost Stress Sensitivity — M4 Baseline Probe S304",
        "",
        f"**Trades file:** `{result.get('trades_file', 'N/A')}`",
        f"**N (local):** {result.get('n', 'N/A')} | **Canonical N:** {result['canonical_n']}",
        f"**Canonical PF (0bps):** {result['canonical_pf']}",
        "",
    ]

    if "error" in result:
        lines.append(f"**ERROR:** {result['error']}")
    else:
        lines += [
            "## PF vs Slippage",
            "",
            "| Slippage (bps) | PF | WR | Pass PF≥10 |",
            "|----------------|----|----|------------|",
        ]
        for r in result["results"]:
            pf_str = f"{r['pf']:.4f}" if isinstance(r["pf"], float) else str(r["pf"])
            wr_str = f"{r['wr']:.2%}"
            pass_str = "YES" if r["pass_10x_threshold"] else "NO"
            lines.append(f"| {r['slippage_bps']} | {pf_str} | {wr_str} | {pass_str} |")

        lines += [
            "",
            f"**PF at 15bps round-trip:** {result['pf_at_15bps']}",
            f"**Pass (PF≥10 at 15bps):** {result['pass_at_15bps']}",
            f"**Breakeven (PF<10 first at):** {result['breakeven_bps']} bps",
            "",
            "## HARN-1.1 Caveat",
            "",
            result["harn_1_1_caveat"],
        ]

    out_md.write_text("\n".join(lines), encoding="utf-8")
    return out_md


def main() -> int:
    result = audit_cost_stress()
    out_md = _write_report(result)
    out_json = AUDITS_OUTPUT_DIR / "m4_baseline_probe_S304_cost_stress.json"
    out_json.write_text(json.dumps(result, indent=2, default=str))

    if "error" in result:
        print(f"ERROR: {result['error']}")
        return 1

    print(f"Cost stress N={result['n']}: PF at 15bps={result['pf_at_15bps']}, pass={result['pass_at_15bps']}")
    print(f"Report: {out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
