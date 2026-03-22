#!/usr/bin/env python3
"""S28 RSI Phase Scoring — Full Calibration Pipeline.

Phases:
  2: EMA 9/21 cross detection + RSI backfill + forward returns
  3: Anchored walk-forward validation (Spearman IC)
  4: Diagnostics & reporting

Output: backtest_output/s28_rsi_phase/
"""

import os
import csv
import datetime
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from s28_rsi_phase_score import (
    rsi_phase_score, rsi_ols_slope, classify_rsi_phase,
    ema, rsi_wilder,
)

# ── Config ──
BACKTEST_DIR = "backtest_output"
OUTPUT_DIR = os.path.join(BACKTEST_DIR, "s28_rsi_phase")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# All 27 tickers with M5 data
TICKERS = sorted([
    f.replace("_m5_regsess.csv", "")
    for f in os.listdir(BACKTEST_DIR)
    if f.endswith("_m5_regsess.csv")
])

# Zone definitions (ET hours)
ZONE_MAP = {
    1: (9, 30, 10, 0),   # 09:30–10:00
    2: (10, 0, 12, 0),   # 10:00–12:00  ← PRIMARY
    3: (12, 0, 14, 0),   # 12:00–14:00
    4: (14, 0, 15, 0),   # 14:00–15:00
    5: (15, 0, 16, 0),   # 15:00–16:00
}


def get_zone(dt):
    """Return zone number (1-5) for a datetime, or 0 if outside."""
    t = dt.hour * 60 + dt.minute
    for z, (h1, m1, h2, m2) in ZONE_MAP.items():
        start = h1 * 60 + m1
        end = h2 * 60 + m2
        if start <= t < end:
            return z
    return 0


def load_m5(ticker):
    """Load M5 regular-session data for a ticker."""
    fpath = os.path.join(BACKTEST_DIR, f"{ticker}_m5_regsess.csv")
    df = pd.read_csv(fpath, parse_dates=["Datetime"])
    df = df.sort_values("Datetime").reset_index(drop=True)
    return df


# ═══════════════════════════════════════════════════════════════════
# PHASE 2: EMA Cross Detection + RSI Backfill
# ═══════════════════════════════════════════════════════════════════

def detect_crosses_for_ticker(ticker):
    """Detect EMA 9/21 crosses and compute RSI phase scores + forward returns."""
    df = load_m5(ticker)
    closes = df["Close"].values
    n = len(closes)

    # Compute indicators
    ema9 = ema(closes, 9)
    ema21 = ema(closes, 21)
    rsi14 = rsi_wilder(closes, 14)

    # Build date column for EOD lookup
    df["date"] = df["Datetime"].dt.date

    events = []

    for i in range(1, n):
        # Skip if indicators not ready
        if np.isnan(ema9[i]) or np.isnan(ema21[i]) or np.isnan(ema9[i-1]) or np.isnan(ema21[i-1]):
            continue
        if np.isnan(rsi14[i]):
            continue

        # Detect cross
        direction = None
        if ema9[i-1] <= ema21[i-1] and ema9[i] > ema21[i]:
            direction = "LONG"
        elif ema9[i-1] >= ema21[i-1] and ema9[i] < ema21[i]:
            direction = "SHORT"

        if direction is None:
            continue

        # Need 5 bars of RSI history for slope
        if i < 4 or any(np.isnan(rsi14[i-4:i+1])):
            continue

        rsi_val = rsi14[i]
        slope = rsi_ols_slope(rsi14[i-4:i+1].tolist())
        score = rsi_phase_score(rsi_val, slope, direction)
        phase = classify_rsi_phase(rsi_val, slope, direction)
        zone = get_zone(df["Datetime"].iloc[i])

        # Forward returns (signed by direction)
        dir_sign = 1.0 if direction == "LONG" else -1.0
        entry_close = closes[i]
        entry_date = df["date"].iloc[i]

        # fwd_15m (+3 bars), fwd_30m (+6 bars), fwd_60m (+12 bars)
        fwd_15m = dir_sign * (closes[i+3] / entry_close - 1) if i + 3 < n else np.nan
        fwd_30m = dir_sign * (closes[i+6] / entry_close - 1) if i + 6 < n else np.nan
        fwd_60m = dir_sign * (closes[i+12] / entry_close - 1) if i + 12 < n else np.nan

        # fwd_eod: last bar of same trading day
        day_mask = df["date"] == entry_date
        day_indices = df.index[day_mask]
        if len(day_indices) > 0:
            last_day_idx = day_indices[-1]
            fwd_eod = dir_sign * (closes[last_day_idx] / entry_close - 1)
        else:
            fwd_eod = np.nan

        events.append({
            "date": str(entry_date),
            "ticker": ticker,
            "timestamp": str(df["Datetime"].iloc[i]),
            "direction": direction,
            "rsi": round(rsi_val, 2),
            "rsi_slope": round(slope, 4),
            "rsi_phase_score": round(score, 4),
            "phase": phase,
            "zone": zone,
            "fwd_15m": round(fwd_15m, 6) if not np.isnan(fwd_15m) else np.nan,
            "fwd_30m": round(fwd_30m, 6) if not np.isnan(fwd_30m) else np.nan,
            "fwd_60m": round(fwd_60m, 6) if not np.isnan(fwd_60m) else np.nan,
            "fwd_eod": round(fwd_eod, 6) if not np.isnan(fwd_eod) else np.nan,
        })

    return events


def run_phase2():
    """Phase 2: Detect all EMA crosses across 27 tickers."""
    print("=" * 70)
    print("PHASE 2: EMA 9/21 Cross Detection + RSI Backfill")
    print("=" * 70)

    all_events = []
    for ticker in TICKERS:
        events = detect_crosses_for_ticker(ticker)
        all_events.extend(events)
        print(f"  {ticker:>5}: {len(events):>4} cross events")

    # Save CSV
    df = pd.DataFrame(all_events)
    csv_path = os.path.join(OUTPUT_DIR, "s28_ema_cross_events.csv")
    df.to_csv(csv_path, index=False)

    # Summary stats
    print(f"\nTotal events: {len(df)}")
    print(f"\nEvents per direction:")
    print(df["direction"].value_counts().to_string())
    print(f"\nEvents per zone:")
    print(df["zone"].value_counts().sort_index().to_string())
    z2 = df[df["zone"] == 2]
    print(f"\nZone 2 events: {len(z2)}")
    print(f"\nEvents per ticker:")
    print(df.groupby("ticker").size().to_string())

    return df


# ═══════════════════════════════════════════════════════════════════
# PHASE 3: Anchored Walk-Forward Validation
# ═══════════════════════════════════════════════════════════════════

def run_phase3(df_all):
    """Phase 3: Walk-forward Spearman IC analysis."""
    print("\n" + "=" * 70)
    print("PHASE 3: Anchored Walk-Forward Validation")
    print("=" * 70)

    # Zone 2 only for primary analysis
    df = df_all[df_all["zone"] == 2].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna(subset=["fwd_60m"])

    if len(df) == 0:
        print("ERROR: No Zone 2 events with fwd_60m. Cannot proceed.")
        return None

    # Get sorted unique trading days
    all_dates = sorted(df["date"].unique())
    n_days = len(all_dates)
    print(f"Trading days with Zone 2 events: {n_days}")
    print(f"Zone 2 events with fwd_60m: {len(df)}")

    # Walk-forward folds
    train_len = 126
    val_len = 21
    test_len = 21
    step = 21
    fold_window = train_len + val_len + test_len

    folds = []
    fold_start = 0
    while fold_start + fold_window <= n_days:
        test_start_idx = fold_start + train_len + val_len
        test_end_idx = test_start_idx + test_len
        test_start_date = all_dates[test_start_idx]
        test_end_date = all_dates[min(test_end_idx - 1, n_days - 1)]
        folds.append((test_start_date, test_end_date))
        fold_start += step

    print(f"Walk-forward folds: {len(folds)}")

    fold_results = []
    for fold_idx, (test_start, test_end) in enumerate(folds):
        test_df = df[(df["date"] >= test_start) & (df["date"] <= test_end)]
        if len(test_df) < 10:
            continue

        scores = test_df["rsi_phase_score"].values
        returns = test_df["fwd_60m"].values

        # Spearman IC
        ic, ic_pval = stats.spearmanr(scores, returns)

        # Quintile spread
        test_df = test_df.copy()
        test_df["quintile"] = pd.qcut(test_df["rsi_phase_score"], 5, labels=False, duplicates="drop")
        q_means = test_df.groupby("quintile")["fwd_60m"].mean()
        if len(q_means) >= 2:
            q_spread = q_means.iloc[-1] - q_means.iloc[0]
        else:
            q_spread = np.nan

        # Decile monotonicity violations
        test_df["decile"] = pd.qcut(test_df["rsi_phase_score"], 10, labels=False, duplicates="drop")
        d_means = test_df.groupby("decile")["fwd_60m"].mean()
        violations = 0
        d_vals = d_means.values
        for j in range(1, len(d_vals)):
            if d_vals[j] < d_vals[j-1]:
                violations += 1

        fold_results.append({
            "fold": fold_idx + 1,
            "test_start": str(test_start.date()) if hasattr(test_start, 'date') else str(test_start)[:10],
            "test_end": str(test_end.date()) if hasattr(test_end, 'date') else str(test_end)[:10],
            "n_events": len(test_df),
            "spearman_ic": round(ic, 4),
            "ic_pval": round(ic_pval, 4),
            "quintile_spread": round(q_spread, 6) if not np.isnan(q_spread) else np.nan,
            "decile_violations": violations,
            "ic_positive": 1 if ic > 0 else 0,
            "top_gt_bottom": 1 if (not np.isnan(q_spread) and q_spread > 0) else 0,
        })

    fold_df = pd.DataFrame(fold_results)
    fold_csv = os.path.join(OUTPUT_DIR, "fold_details.csv")
    fold_df.to_csv(fold_csv, index=False)

    # Aggregate metrics
    n_folds = len(fold_df)
    mean_ic = fold_df["spearman_ic"].mean()
    std_ic = fold_df["spearman_ic"].std()
    pct_positive = fold_df["ic_positive"].mean() * 100
    mean_q_spread = fold_df["quintile_spread"].mean()
    mean_violations = fold_df["decile_violations"].mean()
    pct_top_gt_bottom = fold_df["top_gt_bottom"].mean() * 100

    print(f"\n--- Aggregate Walk-Forward Results ---")
    print(f"Folds evaluated: {n_folds}")
    print(f"Mean OOS Spearman IC: {mean_ic:.4f} ± {std_ic:.4f}")
    print(f"% folds with IC > 0: {pct_positive:.1f}%")
    print(f"Mean quintile spread: {mean_q_spread:.6f}")
    print(f"Mean decile violations: {mean_violations:.1f}")
    print(f"% folds top > bottom quintile: {pct_top_gt_bottom:.1f}%")

    # Jackknife by ticker
    print(f"\n--- Ticker Jackknife ---")
    base_ic = mean_ic
    jackknife_results = {}
    flagged_tickers = []

    for ticker in TICKERS:
        df_ex = df[df["ticker"] != ticker]
        fold_ics = []
        for test_start, test_end in folds:
            test_ex = df_ex[(df_ex["date"] >= test_start) & (df_ex["date"] <= test_end)]
            if len(test_ex) < 10:
                continue
            ic_ex, _ = stats.spearmanr(test_ex["rsi_phase_score"].values, test_ex["fwd_60m"].values)
            fold_ics.append(ic_ex)
        if fold_ics:
            jk_ic = np.mean(fold_ics)
            pct_change = abs(jk_ic - base_ic) / max(abs(base_ic), 1e-10) * 100
            jackknife_results[ticker] = jk_ic
            if pct_change > 20:
                flagged_tickers.append((ticker, jk_ic, pct_change))
                print(f"  ⚠ {ticker}: IC={jk_ic:.4f} (Δ={pct_change:.1f}%) — FLAGGED")
            else:
                print(f"  {ticker}: IC={jk_ic:.4f} (Δ={pct_change:.1f}%)")

    # Verdict
    if pct_positive >= 70 and mean_ic > 0.02:
        verdict = "CONFIRMED"
    elif pct_positive >= 70:
        verdict = "MARGINAL"
    else:
        verdict = "REJECTED"

    # Overfit controls
    oos_ic_pass = "PASS" if pct_positive >= 70 else "FAIL"
    top_bottom_pass = "PASS" if pct_top_gt_bottom >= 70 else "FAIL"

    print(f"\n--- Overfit Controls ---")
    print(f"OOS IC sign positive ≥70%: {pct_positive:.1f}% → {oos_ic_pass}")
    print(f"Top > bottom quintile ≥70%: {pct_top_gt_bottom:.1f}% → {top_bottom_pass}")
    if flagged_tickers:
        for t, ic_val, pct_chg in flagged_tickers:
            print(f"Jackknife FLAG: {t} (IC change {pct_chg:.1f}%)")
    else:
        print("Jackknife: No ticker moves IC by >20%")

    print(f"\n{'='*40}")
    print(f"VERDICT: {verdict}")
    print(f"{'='*40}")

    return {
        "n_folds": n_folds,
        "mean_ic": mean_ic,
        "std_ic": std_ic,
        "pct_positive": pct_positive,
        "mean_q_spread": mean_q_spread,
        "mean_violations": mean_violations,
        "pct_top_gt_bottom": pct_top_gt_bottom,
        "verdict": verdict,
        "oos_ic_pass": oos_ic_pass,
        "top_bottom_pass": top_bottom_pass,
        "flagged_tickers": flagged_tickers,
        "jackknife_results": jackknife_results,
        "fold_df": fold_df,
    }


# ═══════════════════════════════════════════════════════════════════
# PHASE 4: Diagnostics & Reporting
# ═══════════════════════════════════════════════════════════════════

def run_phase4(df_all, results):
    """Phase 4: Generate all charts and RESULTS.md."""
    print("\n" + "=" * 70)
    print("PHASE 4: Diagnostics & Reporting")
    print("=" * 70)

    df_z2 = df_all[df_all["zone"] == 2].copy()
    fold_df = results["fold_df"]

    # 1. score_distribution.png
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.hist(df_all["rsi_phase_score"].dropna(), bins=50, edgecolor="black", alpha=0.7, color="steelblue")
    ax.set_xlabel("RSI Phase Score")
    ax.set_ylabel("Count")
    ax.set_title("S28 RSI Phase Score Distribution (All Events)")
    ax.axvline(df_all["rsi_phase_score"].median(), color="red", ls="--", label=f"Median={df_all['rsi_phase_score'].median():.3f}")
    ax.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "score_distribution.png"), dpi=150)
    plt.close()
    print("  score_distribution.png")

    # 2. quintile_returns.png
    df_z2_fwd = df_z2.dropna(subset=["fwd_60m"]).copy()
    if len(df_z2_fwd) > 0:
        df_z2_fwd["quintile"] = pd.qcut(df_z2_fwd["rsi_phase_score"], 5, labels=["Q1(Low)", "Q2", "Q3", "Q4", "Q5(High)"], duplicates="drop")
        q_stats = df_z2_fwd.groupby("quintile", observed=True)["fwd_60m"].agg(["mean", "std", "count"])

        fig, ax = plt.subplots(figsize=(10, 6))
        bars = ax.bar(q_stats.index.astype(str), q_stats["mean"] * 100, color=["#d62728", "#ff7f0e", "#bcbd22", "#2ca02c", "#1f77b4"], edgecolor="black")
        ax.set_xlabel("Score Quintile")
        ax.set_ylabel("Mean Forward 60m Return (%)")
        ax.set_title("S28: Mean fwd_60m Return by Score Quintile (Zone 2)")
        ax.axhline(0, color="black", lw=0.5)
        for bar, cnt in zip(bars, q_stats["count"]):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(), f"n={cnt}", ha="center", va="bottom", fontsize=9)
        plt.tight_layout()
        plt.savefig(os.path.join(OUTPUT_DIR, "quintile_returns.png"), dpi=150)
        plt.close()
        print("  quintile_returns.png")

    # 3. ic_by_fold.png
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(fold_df["fold"], fold_df["spearman_ic"], marker="o", color="steelblue", lw=1.5)
    ax.axhline(0, color="black", lw=0.5)
    ax.axhline(results["mean_ic"], color="red", ls="--", label=f"Mean IC={results['mean_ic']:.4f}")
    ax.fill_between(fold_df["fold"], 0, fold_df["spearman_ic"],
                     where=fold_df["spearman_ic"] > 0, alpha=0.15, color="green")
    ax.fill_between(fold_df["fold"], 0, fold_df["spearman_ic"],
                     where=fold_df["spearman_ic"] <= 0, alpha=0.15, color="red")
    ax.set_xlabel("Fold")
    ax.set_ylabel("Spearman IC")
    ax.set_title("S28: OOS Spearman IC by Walk-Forward Fold (Zone 2)")
    ax.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "ic_by_fold.png"), dpi=150)
    plt.close()
    print("  ic_by_fold.png")

    # 4. ticker_jackknife.png
    jk = results["jackknife_results"]
    if jk:
        tickers_sorted = sorted(jk.keys(), key=lambda t: jk[t])
        fig, ax = plt.subplots(figsize=(14, 6))
        colors = ["red" if any(t == ft[0] for ft in results["flagged_tickers"]) else "steelblue" for t in tickers_sorted]
        ax.bar(tickers_sorted, [jk[t] for t in tickers_sorted], color=colors, edgecolor="black")
        ax.axhline(results["mean_ic"], color="red", ls="--", label=f"Base IC={results['mean_ic']:.4f}")
        ax.set_xlabel("Ticker Removed")
        ax.set_ylabel("Aggregate IC (leave-one-out)")
        ax.set_title("S28: Ticker Jackknife — Impact on Aggregate IC")
        ax.legend()
        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()
        plt.savefig(os.path.join(OUTPUT_DIR, "ticker_jackknife.png"), dpi=150)
        plt.close()
        print("  ticker_jackknife.png")

    # 5. score_vs_return_scatter.png
    df_scatter = df_z2_fwd.copy()
    if len(df_scatter) > 500:
        df_scatter = df_scatter.sample(500, random_state=42)
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.scatter(df_scatter["rsi_phase_score"], df_scatter["fwd_60m"] * 100, alpha=0.3, s=15, color="steelblue")
    ax.set_xlabel("RSI Phase Score")
    ax.set_ylabel("Forward 60m Return (%)")
    ax.set_title("S28: Score vs Forward 60m Return (Zone 2, n≤500)")
    ax.axhline(0, color="black", lw=0.5)
    # Trend line
    z = np.polyfit(df_scatter["rsi_phase_score"], df_scatter["fwd_60m"] * 100, 1)
    x_line = np.linspace(0, 1, 100)
    ax.plot(x_line, z[0] * x_line + z[1], "r--", lw=1.5, label=f"Slope={z[0]:.3f}")
    ax.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "score_vs_return_scatter.png"), dpi=150)
    plt.close()
    print("  score_vs_return_scatter.png")

    # 6. phase_distribution.csv
    phase_counts = df_all.groupby("phase").size().reset_index(name="count")
    phase_counts.to_csv(os.path.join(OUTPUT_DIR, "phase_distribution.csv"), index=False)
    print("  phase_distribution.csv")
    print(f"\nPhase distribution:")
    print(phase_counts.to_string(index=False))

    # 7. RESULTS.md
    write_results_md(df_all, df_z2, results)
    print("  RESULTS.md")


def write_results_md(df_all, df_z2, results):
    """Write the final RESULTS.md summary."""
    md_path = os.path.join(OUTPUT_DIR, "RESULTS.md")

    df_z2_fwd = df_z2.dropna(subset=["fwd_60m"])

    # Supplementary zone stats
    zone_stats = []
    for z in [1, 3, 4, 5]:
        dz = df_all[(df_all["zone"] == z)].dropna(subset=["fwd_60m"])
        if len(dz) >= 20:
            ic, _ = stats.spearmanr(dz["rsi_phase_score"], dz["fwd_60m"])
            zone_stats.append((z, len(dz), round(ic, 4)))

    # Quintile table for Zone 2
    q_table = ""
    if len(df_z2_fwd) > 0:
        df_z2_fwd = df_z2_fwd.copy()
        df_z2_fwd["quintile"] = pd.qcut(df_z2_fwd["rsi_phase_score"], 5, labels=["Q1(Low)", "Q2", "Q3", "Q4", "Q5(High)"], duplicates="drop")
        q_agg = df_z2_fwd.groupby("quintile", observed=True)["fwd_60m"].agg(["mean", "std", "count"])
        q_table = "| Quintile | Mean fwd_60m | Std | Count |\n|----------|-------------|-----|-------|\n"
        for idx, row in q_agg.iterrows():
            q_table += f"| {idx} | {row['mean']*100:.4f}% | {row['std']*100:.4f}% | {int(row['count'])} |\n"

    flagged_str = "None"
    if results["flagged_tickers"]:
        flagged_str = ", ".join(f"{t} (Δ={p:.1f}%)" for t, _, p in results["flagged_tickers"])

    content = f"""# S28 RSI Phase Scoring — Calibration Results

**Date**: {datetime.date.today()}
**Repo**: yuters77/stock-data-mining
**Tag**: s28-rsi-phase-v1

## Verdict: **{results['verdict']}**

## Summary

| Metric | Value |
|--------|-------|
| Total cross events | {len(df_all)} |
| Zone 2 events | {len(df_z2)} |
| Zone 2 events with fwd_60m | {len(df_z2_fwd)} |
| Walk-forward folds | {results['n_folds']} |
| Mean OOS Spearman IC | {results['mean_ic']:.4f} ± {results['std_ic']:.4f} |
| % folds IC > 0 | {results['pct_positive']:.1f}% |
| Mean quintile spread | {results['mean_q_spread']*100:.4f}% |
| Mean decile violations | {results['mean_violations']:.1f} |
| % folds top > bottom | {results['pct_top_gt_bottom']:.1f}% |

## Overfit Controls

| Check | Result |
|-------|--------|
| OOS IC positive ≥70% folds | {results['pct_positive']:.1f}% → {results['oos_ic_pass']} |
| Top > bottom quintile ≥70% folds | {results['pct_top_gt_bottom']:.1f}% → {results['top_bottom_pass']} |
| Jackknife flagged tickers | {flagged_str} |

## Quintile Returns (Zone 2, fwd_60m)

{q_table}

## Supplementary Zone Analysis

| Zone | Events | Spearman IC |
|------|--------|-------------|
"""
    for z, n, ic in zone_stats:
        content += f"| {z} | {n} | {ic} |\n"

    content += f"""
## Events by Direction

| Direction | Count |
|-----------|-------|
| LONG | {len(df_all[df_all['direction']=='LONG'])} |
| SHORT | {len(df_all[df_all['direction']=='SHORT'])} |

## Events by Ticker (Top 10)

| Ticker | Count |
|--------|-------|
"""
    ticker_counts = df_all.groupby("ticker").size().sort_values(ascending=False).head(10)
    for t, c in ticker_counts.items():
        content += f"| {t} | {c} |\n"

    content += f"""
## Files Generated

- `s28_ema_cross_events.csv` — All cross events with scores and forward returns
- `fold_details.csv` — Per-fold walk-forward metrics
- `phase_distribution.csv` — Event counts by RSI phase
- `score_distribution.png` — Score histogram
- `quintile_returns.png` — Mean returns by score quintile
- `ic_by_fold.png` — Spearman IC over time
- `ticker_jackknife.png` — Leave-one-out IC stability
- `score_vs_return_scatter.png` — Score vs return scatter

## Interpretation

"""
    if results["verdict"] == "CONFIRMED":
        content += """The RSI Phase Scoring curve shows statistically meaningful rank-ordering ability
for forward 60-minute returns on EMA 9/21 cross entries. The designed sigmoid
parameters from S28 DR produce a score that positively correlates with
directional returns in the majority of out-of-sample folds.

**Recommendation**: Deploy to shadow portfolio for live monitoring. Monitor for
20+ sessions before trusting for position sizing.
"""
    elif results["verdict"] == "MARGINAL":
        content += """The RSI Phase Scoring curve shows weak but consistent rank-ordering ability.
The IC is positive in the majority of folds but the magnitude is below the
0.02 threshold for high confidence.

**Recommendation**: Deploy to shadow portfolio with reduced weight. Consider
empirical calibration of sigmoid parameters (±15% perturbation grid on each
of the 7 constants) if IC doesn't improve over 20 live sessions.
"""
    else:
        content += """The RSI Phase Scoring curve does NOT show reliable rank-ordering ability in
walk-forward validation. The designed sigmoid parameters may not capture the
true relationship between RSI dynamics and forward returns on this data.

**Recommendation**: Do NOT deploy. Design perturbation grid (±15% on each of
7 constants: 28, 4.5, 68, 5.0, 0.9710, 0.10, 0.65) and re-test. Consider
whether M5 timeframe is appropriate or if 4H aggregation would be better.
"""

    content += f"""
## Constants Used (S28 DR — NOT optimized)

- Level sigmoid center low: 28.0
- Level sigmoid width low: 4.5
- Level sigmoid center high: 68.0
- Level sigmoid width high: 5.0
- Level normalization: 0.9710
- Slope sigmoid center: 0.10
- Slope sigmoid width: 0.65
"""

    with open(md_path, "w") as f:
        f.write(content)


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"S28 RSI Phase Scoring — Calibration Pipeline")
    print(f"Tickers: {len(TICKERS)} — {', '.join(TICKERS)}")
    print()

    # Phase 2
    df_all = run_phase2()

    # Phase 3
    results = run_phase3(df_all)

    if results is None:
        print("\nPhase 3 failed — insufficient data. Aborting.")
        exit(1)

    # Phase 4
    run_phase4(df_all, results)

    print("\n" + "=" * 70)
    print("S28 RSI Phase Calibration COMPLETE")
    print(f"Output: {OUTPUT_DIR}/")
    print("=" * 70)
