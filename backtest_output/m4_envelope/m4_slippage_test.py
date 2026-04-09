#!/usr/bin/env python3
"""
M4 Envelope Test 1: Slippage Sensitivity.

Tests how slippage on entry degrades the M4 edge.
For each trade, adjusts entry price upward (buying higher = worse for long),
keeps exit unchanged, recalculates all metrics.

Output: backtest_output/m4_envelope/slippage_results.csv
        backtest_output/m4_envelope/slippage_summary.csv
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backtest_output" / "m4_envelope"))

from m4_common import (
    run_baseline, calc_metrics, load_vix_daily, load_all_bars,
    OUTPUT_DIR, TICKERS, fmt_pf, fmt_sharpe,
)

SLIPPAGE_BPS = [0, 10, 30, 50, 100]  # basis points


def apply_slippage(trades, slippage_bps):
    """Adjust entry prices by slippage, recalculate PnL."""
    slip_frac = slippage_bps / 10000.0
    adjusted = []
    for t in trades:
        new_entry = t["entry_price"] * (1 + slip_frac)
        new_ret = (t["exit_price"] - new_entry) / new_entry * 100
        adj = dict(t)
        adj["original_entry"] = t["entry_price"]
        adj["slipped_entry"] = new_entry
        adj["slippage_bps"] = slippage_bps
        adj["return_pct"] = new_ret
        adjusted.append(adj)
    return adjusted


def main():
    print("=" * 80)
    print("M4 Envelope Test 1: Slippage Sensitivity")
    print("=" * 80)

    # Load data once
    vix_daily = load_vix_daily()
    all_bars = load_all_bars()

    # Run baseline
    baseline_trades = run_baseline(all_bars=all_bars, vix_daily=vix_daily)
    print(f"\nBaseline trades: N={len(baseline_trades)}")

    if not baseline_trades:
        print("ERROR: No baseline trades found. Check data.")
        return

    # Stage 0: verify baseline
    bm = calc_metrics(baseline_trades)
    print(f"  WR={bm['wr_pct']:.1f}%, PF={fmt_pf(bm['profit_factor'])}, "
          f"Mean={bm['mean_pct']:+.2f}%, Sharpe={fmt_sharpe(bm['sharpe'])}")

    # Test each slippage level
    summary_rows = []
    all_detail_rows = []

    print(f"\n{'Slip BPS':>10} | {'Slip%':>6} | {'N':>4} | {'WR%':>6} | "
          f"{'PF':>9} | {'Mean%':>8} | {'Sharpe':>7} | {'Worst%':>8}")
    print("-" * 78)

    for bps in SLIPPAGE_BPS:
        adj_trades = apply_slippage(baseline_trades, bps)
        m = calc_metrics(adj_trades)

        slip_pct = bps / 100.0
        print(f"{bps:>10} | {slip_pct:>5.1f}% | {m['n']:>4} | {m['wr_pct']:>5.1f}% | "
              f"{fmt_pf(m['profit_factor']):>9} | {m['mean_pct']:>+7.2f}% | "
              f"{fmt_sharpe(m['sharpe']):>7} | {m['worst_pct']:>+7.2f}%")

        summary_rows.append({
            "slippage_bps": bps,
            "slippage_pct": slip_pct,
            "n": m["n"],
            "wr_pct": round(m["wr_pct"], 2),
            "profit_factor": round(m["profit_factor"], 2),
            "mean_pct": round(m["mean_pct"], 4),
            "median_pct": round(m["median_pct"], 4),
            "sharpe": round(m["sharpe"], 4),
            "worst_pct": round(m["worst_pct"], 4),
            "best_pct": round(m["best_pct"], 4),
            "p_value": m["p_value"],
        })

        for t in adj_trades:
            all_detail_rows.append({
                "slippage_bps": bps,
                "ticker": t["ticker"],
                "trigger_time": t["trigger_time"],
                "original_entry": round(t["original_entry"], 4),
                "slipped_entry": round(t["slipped_entry"], 4),
                "exit_price": round(t["exit_price"], 4),
                "return_pct": round(t["return_pct"], 4),
                "exit_reason": t["exit_reason"],
                "hold_bars": t["hold_bars"],
            })

    # Find critical thresholds
    print("\n── Critical Thresholds ──")
    for label, threshold in [("PF < 5", 5), ("PF < 2", 2), ("PF < 1", 1)]:
        crossed = None
        for row in summary_rows:
            if row["profit_factor"] < threshold:
                crossed = row
                break
        if crossed:
            print(f"  {label}: first crossed at {crossed['slippage_bps']} bps "
                  f"({crossed['slippage_pct']:.1f}%), PF={crossed['profit_factor']:.2f}")
        else:
            print(f"  {label}: NOT crossed even at {SLIPPAGE_BPS[-1]} bps")

    # Interpolate PF breakeven
    pfs = [(r["slippage_bps"], r["profit_factor"]) for r in summary_rows]
    for label, threshold in [("PF=5", 5), ("PF=2", 2), ("PF=1", 1)]:
        for i in range(1, len(pfs)):
            if pfs[i - 1][1] >= threshold and pfs[i][1] < threshold:
                # Linear interpolation
                x0, y0 = pfs[i - 1]
                x1, y1 = pfs[i]
                cross_bps = x0 + (threshold - y0) * (x1 - x0) / (y1 - y0)
                print(f"  {label} breakeven (interpolated): ~{cross_bps:.0f} bps ({cross_bps/100:.2f}%)")
                break

    # Save outputs
    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(OUTPUT_DIR / "slippage_summary.csv", index=False)

    detail_df = pd.DataFrame(all_detail_rows)
    detail_df.to_csv(OUTPUT_DIR / "slippage_results.csv", index=False)

    print(f"\nSaved: {OUTPUT_DIR / 'slippage_summary.csv'}")
    print(f"Saved: {OUTPUT_DIR / 'slippage_results.csv'}")


if __name__ == "__main__":
    main()
