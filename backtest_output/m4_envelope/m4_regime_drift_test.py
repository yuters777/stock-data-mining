#!/usr/bin/env python3
"""
M4 Envelope Test 2: Regime Drift.

Part A: Classifies trades by whether VIX stayed >= 25 during the hold period
        vs softened below 25. Compares performance.
Part B: VIX threshold sensitivity — sweeps VIX gate from 22-28.

Output: backtest_output/m4_envelope/regime_drift_results.csv
        backtest_output/m4_envelope/vix_threshold_sweep.csv
"""

import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backtest_output" / "m4_envelope"))

from m4_common import (
    run_baseline, calc_metrics, load_vix_daily, load_all_bars,
    OUTPUT_DIR, TICKERS, VIX_THRESHOLD, fmt_pf, fmt_sharpe,
)

VIX_THRESHOLDS = [22, 23, 24, 25, 26, 27, 28]


def get_vix_during_hold(vix_daily, trade):
    """Get daily VIX values during the trade's hold period."""
    entry_date = pd.Timestamp(trade["trigger_time"]).normalize()
    hold_days = (trade["hold_bars"] + 1) // 2 + 1  # ~2 bars per day, +1 buffer
    vix_values = []
    for d in range(hold_days + 1):
        dt = entry_date + timedelta(days=d)
        ds = dt.strftime("%Y-%m-%d")
        if ds in vix_daily:
            vix_values.append({"date": ds, "vix": vix_daily[ds]})
    return vix_values


def classify_regime_drift(trades, vix_daily):
    """Classify each trade as VIX_STAYED_HIGH or VIX_SOFTENED during hold."""
    classified = []
    for t in trades:
        vix_during = get_vix_during_hold(vix_daily, t)
        min_vix = min(v["vix"] for v in vix_during) if vix_during else t["vix"]
        stayed_high = all(v["vix"] >= VIX_THRESHOLD for v in vix_during)
        tc = dict(t)
        tc["vix_during_hold"] = vix_during
        tc["min_vix_during_hold"] = min_vix
        tc["regime_class"] = "VIX_STAYED_HIGH" if stayed_high else "VIX_SOFTENED"
        classified.append(tc)
    return classified


def main():
    print("=" * 80)
    print("M4 Envelope Test 2: Regime Drift Analysis")
    print("=" * 80)

    vix_daily = load_vix_daily()
    all_bars = load_all_bars()
    baseline_trades = run_baseline(all_bars=all_bars, vix_daily=vix_daily)
    print(f"\nBaseline trades: N={len(baseline_trades)}")

    if not baseline_trades:
        print("ERROR: No baseline trades found.")
        return

    # ── Part A: VIX drift during hold ────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Part A: VIX Behavior During Hold Period")
    print("=" * 60)

    classified = classify_regime_drift(baseline_trades, vix_daily)

    stayed = [t for t in classified if t["regime_class"] == "VIX_STAYED_HIGH"]
    softened = [t for t in classified if t["regime_class"] == "VIX_SOFTENED"]

    print(f"\n{'Category':>18} | {'N':>4} | {'WR%':>6} | {'PF':>9} | "
          f"{'Mean%':>8} | {'Sharpe':>7} | {'MinVIX':>7}")
    print("-" * 72)

    for label, group in [("VIX_STAYED_HIGH", stayed), ("VIX_SOFTENED", softened)]:
        m = calc_metrics(group)
        min_vix_avg = np.mean([t["min_vix_during_hold"] for t in group]) if group else 0
        print(f"{label:>18} | {m['n']:>4} | {m['wr_pct']:>5.1f}% | "
              f"{fmt_pf(m['profit_factor']):>9} | {m['mean_pct']:>+7.2f}% | "
              f"{fmt_sharpe(m['sharpe']):>7} | {min_vix_avg:>6.1f}")

    # All baseline for comparison
    bm = calc_metrics(baseline_trades)
    print(f"{'ALL':>18} | {bm['n']:>4} | {bm['wr_pct']:>5.1f}% | "
          f"{fmt_pf(bm['profit_factor']):>9} | {bm['mean_pct']:>+7.2f}% | "
          f"{fmt_sharpe(bm['sharpe']):>7} |")

    if stayed and softened:
        stayed_rets = [t["return_pct"] for t in stayed]
        softened_rets = [t["return_pct"] for t in softened]
        diff = np.mean(stayed_rets) - np.mean(softened_rets)
        print(f"\nDifference (stayed - softened): {diff:+.2f}%")

    # Save detail CSV
    drift_rows = []
    for t in classified:
        drift_rows.append({
            "ticker": t["ticker"],
            "trigger_time": t["trigger_time"],
            "entry_vix": t["vix"],
            "min_vix_during_hold": round(t["min_vix_during_hold"], 2),
            "regime_class": t["regime_class"],
            "return_pct": round(t["return_pct"], 4),
            "hold_bars": t["hold_bars"],
            "exit_reason": t["exit_reason"],
        })
    pd.DataFrame(drift_rows).to_csv(OUTPUT_DIR / "regime_drift_results.csv", index=False)

    # ── Part B: VIX Threshold Sensitivity ────────────────────────────────────
    print("\n" + "=" * 60)
    print("Part B: VIX Threshold Sensitivity Sweep")
    print("=" * 60)

    print(f"\n{'VIX Gate':>10} | {'N':>4} | {'WR%':>6} | {'PF':>9} | "
          f"{'Mean%':>8} | {'Sharpe':>7} | {'Worst%':>8}")
    print("-" * 70)

    sweep_rows = []
    for vix_thresh in VIX_THRESHOLDS:
        trades = run_baseline(vix_threshold=vix_thresh, all_bars=all_bars,
                              vix_daily=vix_daily)
        m = calc_metrics(trades)
        marker = " *" if vix_thresh == VIX_THRESHOLD else ""
        print(f"{'>=' + str(vix_thresh) + marker:>10} | {m['n']:>4} | "
              f"{m['wr_pct']:>5.1f}% | {fmt_pf(m['profit_factor']):>9} | "
              f"{m['mean_pct']:>+7.2f}% | {fmt_sharpe(m['sharpe']):>7} | "
              f"{m['worst_pct']:>+7.2f}%")

        sweep_rows.append({
            "vix_threshold": vix_thresh,
            "n": m["n"],
            "wr_pct": round(m["wr_pct"], 2),
            "profit_factor": round(m["profit_factor"], 2),
            "mean_pct": round(m["mean_pct"], 4),
            "median_pct": round(m["median_pct"], 4),
            "sharpe": round(m["sharpe"], 4),
            "worst_pct": round(m["worst_pct"], 4),
            "p_value": m["p_value"],
        })

    pd.DataFrame(sweep_rows).to_csv(OUTPUT_DIR / "vix_threshold_sweep.csv", index=False)

    print(f"\nSaved: {OUTPUT_DIR / 'regime_drift_results.csv'}")
    print(f"Saved: {OUTPUT_DIR / 'vix_threshold_sweep.csv'}")


if __name__ == "__main__":
    main()
