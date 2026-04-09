#!/usr/bin/env python3
"""
M4 Envelope Test 3: Forward OOS + Parameter Sensitivity.

Part A: Temporal split — first 70% of trades = IS, last 30% = OOS.
        Run with identical frozen parameters on each subset.
Part B: Parameter sensitivity — sweep each parameter while holding others frozen.

Output: backtest_output/m4_envelope/forward_oos_results.csv
        backtest_output/m4_envelope/param_sensitivity.csv
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backtest_output" / "m4_envelope"))

from m4_common import (
    run_baseline, calc_metrics, load_vix_daily, load_all_bars, load_4h_bars,
    compute_ema, count_down_streak, simulate_trade, get_prior_vix,
    compute_rsi_wilder,
    OUTPUT_DIR, TICKERS, VIX_THRESHOLD, STREAK_LEN, RSI_GATE,
    EMA_PERIOD, HARD_MAX_BARS, INDICATORS_4H_DIR,
    fmt_pf, fmt_sharpe,
)

SENSITIVITY = {
    "streak": [2, 3, 4],
    "vix_threshold": [24, 25, 26],
    "rsi_gate": [33, 34, 35, 36],
    "ema_exit": [13, 21, 34],
    "hard_max": [8, 10, 12, 15],
}


def run_with_custom_ema(tickers, vix_daily, ema_period, **kwargs):
    """Run baseline with a custom EMA exit period (requires recomputing EMA)."""
    all_bars = {}
    for ticker in tickers:
        path = INDICATORS_4H_DIR / f"{ticker}_4h_indicators.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, parse_dates=["timestamp"])
        bars = []
        for _, row in df.iterrows():
            bars.append({
                "timestamp": row["timestamp"],
                "date_str": row["timestamp"].strftime("%Y-%m-%d"),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]) if pd.notna(row.get("volume")) else 0,
            })
        closes = np.array([b["close"] for b in bars])
        rsi_vals = compute_rsi_wilder(closes, 14)
        ema_vals = compute_ema(closes, ema_period)
        for i, b in enumerate(bars):
            b["rsi"] = rsi_vals[i]
            b["ema21"] = ema_vals[i]  # key name stays "ema21" for simulate_trade compat
        all_bars[ticker] = bars

    return run_baseline(all_bars=all_bars, vix_daily=vix_daily,
                        ema_period=ema_period, **kwargs)


def main():
    print("=" * 80)
    print("M4 Envelope Test 3: Forward OOS + Parameter Sensitivity")
    print("=" * 80)

    vix_daily = load_vix_daily()
    all_bars = load_all_bars()
    baseline_trades = run_baseline(all_bars=all_bars, vix_daily=vix_daily)
    print(f"\nBaseline trades: N={len(baseline_trades)}")

    if not baseline_trades:
        print("ERROR: No baseline trades found.")
        return

    # Sort by trigger time
    baseline_trades.sort(key=lambda t: t["trigger_time"])

    # ── Part A: Temporal IS/OOS Split ────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Part A: Temporal IS/OOS Split (70/30)")
    print("=" * 60)

    n_total = len(baseline_trades)
    n_is = int(n_total * 0.7)
    is_trades = baseline_trades[:n_is]
    oos_trades = baseline_trades[n_is:]

    is_start = is_trades[0]["trigger_time"] if is_trades else "N/A"
    is_end = is_trades[-1]["trigger_time"] if is_trades else "N/A"
    oos_start = oos_trades[0]["trigger_time"] if oos_trades else "N/A"
    oos_end = oos_trades[-1]["trigger_time"] if oos_trades else "N/A"

    print(f"\n  IS  period: {is_start} → {is_end} (N={len(is_trades)})")
    print(f"  OOS period: {oos_start} → {oos_end} (N={len(oos_trades)})")

    print(f"\n{'Period':>8} | {'N':>4} | {'WR%':>6} | {'PF':>9} | "
          f"{'Mean%':>8} | {'Sharpe':>7} | {'Worst%':>8}")
    print("-" * 68)

    oos_rows = []
    for label, trades in [("IS", is_trades), ("OOS", oos_trades), ("ALL", baseline_trades)]:
        m = calc_metrics(trades)
        print(f"{label:>8} | {m['n']:>4} | {m['wr_pct']:>5.1f}% | "
              f"{fmt_pf(m['profit_factor']):>9} | {m['mean_pct']:>+7.2f}% | "
              f"{fmt_sharpe(m['sharpe']):>7} | {m['worst_pct']:>+7.2f}%")
        oos_rows.append({
            "period": label,
            "n": m["n"],
            "wr_pct": round(m["wr_pct"], 2),
            "profit_factor": round(m["profit_factor"], 2),
            "mean_pct": round(m["mean_pct"], 4),
            "median_pct": round(m["median_pct"], 4),
            "sharpe": round(m["sharpe"], 4),
            "worst_pct": round(m["worst_pct"], 4),
            "p_value": m["p_value"],
            "date_start": is_start if label == "IS" else (oos_start if label == "OOS" else is_start),
            "date_end": is_end if label == "IS" else (oos_end if label == "OOS" else oos_end),
        })

    is_m = calc_metrics(is_trades)
    oos_m = calc_metrics(oos_trades)
    if is_m["mean_pct"] > 0 and oos_m["n"] > 0:
        degradation = 1 - oos_m["mean_pct"] / is_m["mean_pct"]
        print(f"\nOOS degradation vs IS: {degradation:+.1%} "
              f"({'acceptable' if degradation < 0.5 else 'CONCERNING'})")

    pd.DataFrame(oos_rows).to_csv(OUTPUT_DIR / "forward_oos_results.csv", index=False)

    # ── Part B: Parameter Sensitivity ────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Part B: Parameter Sensitivity (one-at-a-time sweep)")
    print("=" * 60)

    sensitivity_rows = []

    for param_name, values in SENSITIVITY.items():
        print(f"\n── {param_name} ──")
        print(f"{'Value':>8} | {'N':>4} | {'WR%':>6} | {'PF':>9} | "
              f"{'Mean%':>8} | {'Sharpe':>7} | {'Frozen?':>7}")
        print("-" * 65)

        for val in values:
            frozen = False
            if param_name == "streak":
                trades = run_baseline(streak_len=val, all_bars=all_bars,
                                      vix_daily=vix_daily)
                frozen = (val == STREAK_LEN)
            elif param_name == "vix_threshold":
                trades = run_baseline(vix_threshold=val, all_bars=all_bars,
                                      vix_daily=vix_daily)
                frozen = (val == VIX_THRESHOLD)
            elif param_name == "rsi_gate":
                trades = run_baseline(rsi_gate=val, all_bars=all_bars,
                                      vix_daily=vix_daily)
                frozen = (val == RSI_GATE)
            elif param_name == "ema_exit":
                trades = run_with_custom_ema(TICKERS, vix_daily, ema_period=val)
                frozen = (val == EMA_PERIOD)
            elif param_name == "hard_max":
                trades = run_baseline(hard_max=val, all_bars=all_bars,
                                      vix_daily=vix_daily)
                frozen = (val == HARD_MAX_BARS)
            else:
                continue

            m = calc_metrics(trades)
            marker = "  *" if frozen else ""
            print(f"{val:>8} | {m['n']:>4} | {m['wr_pct']:>5.1f}% | "
                  f"{fmt_pf(m['profit_factor']):>9} | {m['mean_pct']:>+7.2f}% | "
                  f"{fmt_sharpe(m['sharpe']):>7} | {'FROZEN' if frozen else '':>7}{marker}")

            sensitivity_rows.append({
                "parameter": param_name,
                "value": val,
                "frozen": frozen,
                "n": m["n"],
                "wr_pct": round(m["wr_pct"], 2),
                "profit_factor": round(m["profit_factor"], 2),
                "mean_pct": round(m["mean_pct"], 4),
                "sharpe": round(m["sharpe"], 4),
                "worst_pct": round(m["worst_pct"], 4),
                "p_value": m["p_value"],
            })

    pd.DataFrame(sensitivity_rows).to_csv(OUTPUT_DIR / "param_sensitivity.csv", index=False)

    # Cliff detection
    print("\n── Cliff Detection ──")
    for param_name, values in SENSITIVITY.items():
        param_rows = [r for r in sensitivity_rows if r["parameter"] == param_name]
        pf_frozen = [r["profit_factor"] for r in param_rows if r["frozen"]]
        if not pf_frozen:
            continue
        pf_base = pf_frozen[0]
        for r in param_rows:
            if not r["frozen"]:
                if pf_base > 0:
                    change = (r["profit_factor"] - pf_base) / pf_base * 100
                else:
                    change = 0
                cliff = "CLIFF!" if abs(change) > 50 else "ok"
                print(f"  {param_name}={r['value']}: PF={r['profit_factor']:.2f} "
                      f"({change:+.0f}% vs frozen) [{cliff}]")

    print(f"\nSaved: {OUTPUT_DIR / 'forward_oos_results.csv'}")
    print(f"Saved: {OUTPUT_DIR / 'param_sensitivity.csv'}")


if __name__ == "__main__":
    main()
