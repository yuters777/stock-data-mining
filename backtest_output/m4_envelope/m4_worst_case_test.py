#!/usr/bin/env python3
"""
M4 Envelope Test 4: Worst Case / Drawdown / Risk Analysis.

1. Sequential equity curve + max drawdown
2. Bootstrap analysis (10,000 resamples)
3. Loss cluster analysis (by time, ticker, VIX level)
4. Hard-max exit analysis (characteristics of hard-max exits)

Output: backtest_output/m4_envelope/worst_case_equity.csv
        backtest_output/m4_envelope/worst_case_bootstrap.csv
        backtest_output/m4_envelope/worst_case_clusters.csv
        backtest_output/m4_envelope/equity_curve.png
"""

import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backtest_output" / "m4_envelope"))

from m4_common import (
    run_baseline, calc_metrics, load_vix_daily, load_all_bars,
    OUTPUT_DIR, TICKERS, fmt_pf, fmt_sharpe,
)

N_BOOTSTRAP = 10_000
RNG_SEED = 42


def compute_equity_curve(trades):
    """Walk through trades chronologically, compute running equity."""
    trades_sorted = sorted(trades, key=lambda t: t["trigger_time"])
    equity = [100.0]  # start at 100
    for t in trades_sorted:
        ret_frac = t["return_pct"] / 100.0
        equity.append(equity[-1] * (1 + ret_frac))
    return trades_sorted, equity


def compute_drawdown(equity):
    """Compute peak-to-trough drawdown series."""
    eq = np.array(equity)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak * 100  # percentage drawdown
    return dd


def max_consecutive_losses(trades):
    """Find max consecutive losing trades."""
    max_streak = 0
    current = 0
    for t in trades:
        if t["return_pct"] <= 0:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak


def bootstrap_analysis(trades, n_resamples=N_BOOTSTRAP, seed=RNG_SEED):
    """Resample trades with replacement, compute distribution of key metrics."""
    rng = np.random.RandomState(seed)
    rets = np.array([t["return_pct"] for t in trades])
    n = len(rets)

    results = {
        "max_drawdown": [],
        "total_return": [],
        "worst_single": [],
        "mean_return": [],
        "win_rate": [],
    }

    for _ in range(n_resamples):
        sample_idx = rng.choice(n, size=n, replace=True)
        sample_rets = rets[sample_idx]

        # Equity curve for this sample
        eq = [100.0]
        for r in sample_rets:
            eq.append(eq[-1] * (1 + r / 100.0))
        eq_arr = np.array(eq)
        peak = np.maximum.accumulate(eq_arr)
        dd = ((eq_arr - peak) / peak * 100)

        results["max_drawdown"].append(float(dd.min()))
        results["total_return"].append(float((eq_arr[-1] / eq_arr[0] - 1) * 100))
        results["worst_single"].append(float(sample_rets.min()))
        results["mean_return"].append(float(sample_rets.mean()))
        results["win_rate"].append(float((sample_rets > 0).sum() / n * 100))

    return results


def main():
    print("=" * 80)
    print("M4 Envelope Test 4: Worst Case / Drawdown Analysis")
    print("=" * 80)

    vix_daily = load_vix_daily()
    all_bars = load_all_bars()
    baseline_trades = run_baseline(all_bars=all_bars, vix_daily=vix_daily)
    print(f"\nBaseline trades: N={len(baseline_trades)}")

    if not baseline_trades:
        print("ERROR: No baseline trades found.")
        return

    bm = calc_metrics(baseline_trades)
    print(f"  WR={bm['wr_pct']:.1f}%, PF={fmt_pf(bm['profit_factor'])}, "
          f"Mean={bm['mean_pct']:+.2f}%")

    # ── 1. Sequential Equity Curve ───────────────────────────────────────────
    print("\n" + "=" * 60)
    print("1. Sequential P&L / Equity Curve")
    print("=" * 60)

    sorted_trades, equity = compute_equity_curve(baseline_trades)
    dd_series = compute_drawdown(equity)

    max_dd = float(dd_series.min())
    max_dd_idx = int(np.argmin(dd_series))
    max_consec = max_consecutive_losses(sorted_trades)

    print(f"  Starting equity: 100.00")
    print(f"  Final equity:    {equity[-1]:.2f}")
    print(f"  Total return:    {(equity[-1]/100 - 1)*100:+.2f}%")
    print(f"  Max drawdown:    {max_dd:.2f}%")
    print(f"  Max consecutive losses: {max_consec}")

    # Worst single trade
    worst_trade = min(sorted_trades, key=lambda t: t["return_pct"])
    print(f"  Worst single trade: {worst_trade['return_pct']:+.2f}% "
          f"({worst_trade['ticker']}, {worst_trade['trigger_time']})")

    best_trade = max(sorted_trades, key=lambda t: t["return_pct"])
    print(f"  Best single trade:  {best_trade['return_pct']:+.2f}% "
          f"({best_trade['ticker']}, {best_trade['trigger_time']})")

    # Save equity curve CSV
    eq_rows = []
    for i, t in enumerate(sorted_trades):
        eq_rows.append({
            "trade_num": i + 1,
            "ticker": t["ticker"],
            "trigger_time": t["trigger_time"],
            "return_pct": round(t["return_pct"], 4),
            "equity_before": round(equity[i], 4),
            "equity_after": round(equity[i + 1], 4),
            "drawdown_pct": round(dd_series[i + 1], 4),
            "exit_reason": t["exit_reason"],
        })
    pd.DataFrame(eq_rows).to_csv(OUTPUT_DIR / "worst_case_equity.csv", index=False)

    # ── 2. Bootstrap Analysis ────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"2. Bootstrap Analysis ({N_BOOTSTRAP:,} resamples)")
    print("=" * 60)

    boot = bootstrap_analysis(baseline_trades)

    print(f"\n{'Metric':>20} | {'5th':>8} | {'25th':>8} | {'50th':>8} | "
          f"{'75th':>8} | {'95th':>8}")
    print("-" * 72)

    pctiles = [5, 25, 50, 75, 95]
    boot_summary = {}
    for metric_name in ["max_drawdown", "total_return", "worst_single",
                        "mean_return", "win_rate"]:
        vals = np.array(boot[metric_name])
        ps = np.percentile(vals, pctiles)
        boot_summary[metric_name] = {f"p{p}": float(v) for p, v in zip(pctiles, ps)}
        print(f"{metric_name:>20} | {ps[0]:>+7.2f}% | {ps[1]:>+7.2f}% | "
              f"{ps[2]:>+7.2f}% | {ps[3]:>+7.2f}% | {ps[4]:>+7.2f}%")

    # Save bootstrap detail
    boot_df = pd.DataFrame({
        "max_drawdown": boot["max_drawdown"],
        "total_return": boot["total_return"],
        "worst_single": boot["worst_single"],
        "mean_return": boot["mean_return"],
        "win_rate": boot["win_rate"],
    })
    boot_df.to_csv(OUTPUT_DIR / "worst_case_bootstrap.csv", index=False)

    # ── 3. Loss Cluster Analysis ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("3. Loss Cluster Analysis")
    print("=" * 60)

    losses = [t for t in sorted_trades if t["return_pct"] <= 0]
    wins = [t for t in sorted_trades if t["return_pct"] > 0]

    print(f"\n  Total losses: {len(losses)} / {len(sorted_trades)}")

    if losses:
        # By ticker
        print("\n  Losses by ticker:")
        ticker_losses = Counter(t["ticker"] for t in losses)
        for tk, cnt in ticker_losses.most_common():
            avg_loss = np.mean([t["return_pct"] for t in losses if t["ticker"] == tk])
            print(f"    {tk}: {cnt} loss(es), avg {avg_loss:+.2f}%")

        # By month
        print("\n  Losses by month:")
        month_losses = Counter(t["trigger_time"][:7] for t in losses)
        for month, cnt in sorted(month_losses.items()):
            print(f"    {month}: {cnt} loss(es)")

        # By VIX level
        print("\n  Losses by VIX bucket:")
        for t in losses:
            bucket = "25-30" if t["vix"] < 30 else ("30-35" if t["vix"] < 35 else "35+")
            t["vix_bucket"] = bucket
        vix_losses = Counter(t["vix_bucket"] for t in losses)
        for bucket, cnt in sorted(vix_losses.items()):
            avg_loss = np.mean([t["return_pct"] for t in losses
                                if t.get("vix_bucket") == bucket])
            print(f"    VIX {bucket}: {cnt} loss(es), avg {avg_loss:+.2f}%")

        # By RSI level
        print("\n  Losses by RSI at entry:")
        for t in losses:
            print(f"    {t['ticker']:>6} {t['trigger_time']}: RSI={t['rsi']:.1f}, "
                  f"VIX={t['vix']:.1f}, ret={t['return_pct']:+.2f}%, "
                  f"hold={t['hold_bars']} bars, exit={t['exit_reason']}")

    # Save cluster CSV
    cluster_rows = []
    for t in sorted_trades:
        cluster_rows.append({
            "ticker": t["ticker"],
            "trigger_time": t["trigger_time"],
            "return_pct": round(t["return_pct"], 4),
            "is_loss": t["return_pct"] <= 0,
            "vix": round(t["vix"], 2),
            "rsi": round(t["rsi"], 2),
            "hold_bars": t["hold_bars"],
            "exit_reason": t["exit_reason"],
            "streak": t["streak"],
        })
    pd.DataFrame(cluster_rows).to_csv(OUTPUT_DIR / "worst_case_clusters.csv", index=False)

    # ── 4. Hard Max Exit Analysis ────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("4. Hard Max Exit Analysis")
    print("=" * 60)

    hard_max_trades = [t for t in sorted_trades if t["exit_reason"] == "hard_max"]
    ema_trades = [t for t in sorted_trades if t["exit_reason"] == "ema21_touch"]

    print(f"\n  Hard max exits: {len(hard_max_trades)} / {len(sorted_trades)} "
          f"({len(hard_max_trades)/len(sorted_trades)*100:.1f}%)")

    if hard_max_trades:
        hm_m = calc_metrics(hard_max_trades)
        print(f"  Hard max: N={hm_m['n']}, Mean={hm_m['mean_pct']:+.2f}%, "
              f"WR={hm_m['wr_pct']:.0f}%")

        print(f"\n  Hard max trade details:")
        print(f"  {'Ticker':>8} | {'Trigger Time':>22} | {'RSI':>6} | "
              f"{'VIX':>6} | {'Ret%':>8} | {'Streak':>6}")
        print("  " + "-" * 72)
        for t in hard_max_trades:
            print(f"  {t['ticker']:>8} | {t['trigger_time']:>22} | "
                  f"{t['rsi']:>5.1f} | {t['vix']:>5.1f} | "
                  f"{t['return_pct']:>+7.2f}% | {t['streak']:>6}")

        # Common characteristics
        avg_rsi = np.mean([t["rsi"] for t in hard_max_trades])
        avg_vix = np.mean([t["vix"] for t in hard_max_trades])
        hm_tickers = Counter(t["ticker"] for t in hard_max_trades)
        print(f"\n  Hard max avg RSI: {avg_rsi:.1f} (all trades: "
              f"{np.mean([t['rsi'] for t in sorted_trades]):.1f})")
        print(f"  Hard max avg VIX: {avg_vix:.1f} (all trades: "
              f"{np.mean([t['vix'] for t in sorted_trades]):.1f})")
        print(f"  Hard max tickers: {dict(hm_tickers.most_common())}")

    if ema_trades:
        ema_m = calc_metrics(ema_trades)
        print(f"\n  EMA21 exits: N={ema_m['n']}, Mean={ema_m['mean_pct']:+.2f}%, "
              f"WR={ema_m['wr_pct']:.0f}%")

    # ── Generate equity curve chart ──────────────────────────────────────────
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

        # Equity curve
        ax1 = axes[0]
        ax1.plot(range(len(equity)), equity, "b-", linewidth=1.5)
        ax1.set_ylabel("Equity (starting=100)")
        ax1.set_title("M4 Mean-Reversion — Sequential Equity Curve")
        ax1.axhline(y=100, color="gray", linestyle="--", alpha=0.5)
        ax1.grid(True, alpha=0.3)

        # Drawdown
        ax2 = axes[1]
        ax2.fill_between(range(len(dd_series)), dd_series, 0,
                         color="red", alpha=0.3)
        ax2.plot(range(len(dd_series)), dd_series, "r-", linewidth=1)
        ax2.set_ylabel("Drawdown (%)")
        ax2.set_xlabel("Trade #")
        ax2.set_title(f"Peak-to-Trough Drawdown (Max: {max_dd:.2f}%)")
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        chart_path = OUTPUT_DIR / "equity_curve.png"
        plt.savefig(chart_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"\nSaved chart: {chart_path}")
    except ImportError:
        print("\nmatplotlib not available — skipping chart generation")

    # ── Print Summary ────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Max peak-to-trough drawdown: {max_dd:.2f}%")
    print(f"  Max consecutive losses: {max_consec}")
    dd_5 = boot_summary["max_drawdown"]["p5"]
    dd_95 = boot_summary["max_drawdown"]["p95"]
    print(f"  Bootstrap 90% CI max drawdown: [{dd_5:.2f}%, {dd_95:.2f}%]")
    print(f"  Worst single trade: {worst_trade['return_pct']:+.2f}% "
          f"({worst_trade['ticker']}, {worst_trade['trigger_time']})")
    print(f"  Hard max exits: {len(hard_max_trades)} "
          f"(avg ret: {calc_metrics(hard_max_trades)['mean_pct']:+.2f}%)" if hard_max_trades else "")

    print(f"\nSaved: {OUTPUT_DIR / 'worst_case_equity.csv'}")
    print(f"Saved: {OUTPUT_DIR / 'worst_case_bootstrap.csv'}")
    print(f"Saved: {OUTPUT_DIR / 'worst_case_clusters.csv'}")


if __name__ == "__main__":
    main()
