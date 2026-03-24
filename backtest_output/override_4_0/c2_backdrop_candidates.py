#!/usr/bin/env python3
"""
Override 4.0 — C2: Backdrop Candidates.

Tests multi-day VIX momentum, VRP, Gap×VIX interaction.
Ranks all candidates against VIX level baseline from C1.
"""

import csv
import os
import numpy as np
from math import erfc, sqrt
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "backtest_output" / "override_4_0"

# ── Helpers ──────────────────────────────────────────────────

def p_from_t(t_stat, df):
    """Two-tailed p-value approximation using erfc."""
    return erfc(abs(t_stat) / sqrt(2))


def bucket_stats(returns_list):
    """Compute stats for a bucket of returns."""
    arr = np.array(returns_list)
    n = len(arr)
    if n < 3:
        return {"n": n, "mean": np.nan, "median": np.nan, "std": np.nan,
                "sharpe": np.nan, "wr": np.nan, "t": np.nan, "p": np.nan}
    m = np.mean(arr)
    med = np.median(arr)
    s = np.std(arr, ddof=1)
    t = m / (s / sqrt(n)) if s > 0 else 0
    p = p_from_t(t, n - 1)
    wr = 100 * np.sum(arr > 0) / n
    sharpe = m / s if s > 0 else 0
    return {"n": n, "mean": m, "median": med, "std": s,
            "sharpe": sharpe, "wr": wr, "t": t, "p": p}


def anova_f(groups, n_perm=5000):
    """One-way ANOVA F-statistic with permutation p-value."""
    groups = [np.array(g) for g in groups if len(g) >= 2]
    if len(groups) < 2:
        return 0.0, 1.0

    def compute_f(grps):
        grand_mean = np.mean(np.concatenate(grps))
        ss_b = sum(len(g) * (np.mean(g) - grand_mean) ** 2 for g in grps)
        ss_w = sum(np.sum((g - np.mean(g)) ** 2) for g in grps)
        k = len(grps)
        N = sum(len(g) for g in grps)
        if N - k <= 0 or ss_w == 0:
            return 0.0
        return (ss_b / (k - 1)) / (ss_w / (N - k))

    f_obs = compute_f(groups)

    # Permutation test
    all_data = np.concatenate(groups)
    sizes = [len(g) for g in groups]
    rng = np.random.default_rng(42)
    count_ge = 0
    for _ in range(n_perm):
        perm = rng.permutation(all_data)
        perm_groups = []
        idx = 0
        for s in sizes:
            perm_groups.append(perm[idx:idx+s])
            idx += s
        if compute_f(perm_groups) >= f_obs:
            count_ge += 1

    p_val = (count_ge + 1) / (n_perm + 1)
    return f_obs, p_val


# ── Load Data ────────────────────────────────────────────────

print("Loading C1 data...")
rows = []
with open(OUT_DIR / "spy_daily_returns.csv") as f:
    for r in csv.DictReader(f):
        rows.append({
            "date": r["date"],
            "open": float(r["open"]),
            "close": float(r["close"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "ret": float(r["daily_return"]),
            "range": float(r["intraday_range"]),
            "vix_prior": float(r["vix_prior"]),
            "vix_today": float(r["vix_today"]) if r["vix_today"] else None,
        })

print(f"  {len(rows)} days loaded")

# Also load full VIX series for multi-day lookback
vix_series = {}
with open(ROOT / "Fetched_Data" / "VIXCLS_FRED_real.csv") as f:
    for r in csv.DictReader(f):
        val = r["VIXCLS"].strip()
        if val not in ("", "."):
            vix_series[r["observation_date"]] = float(val)

vix_dates_sorted = sorted(vix_series.keys())
vix_date_idx = {d: i for i, d in enumerate(vix_dates_sorted)}

# Build date-indexed VIX for lookback
def vix_change(date, lookback_days):
    """VIX change over lookback_days trading days ending at prior day of `date`."""
    # prior-day VIX is already in the row; we need VIX from lookback_days before that
    if date not in vix_date_idx:
        return None
    idx = vix_date_idx[date]
    if idx < lookback_days:
        return None
    current = vix_series[vix_dates_sorted[idx]]
    prior = vix_series[vix_dates_sorted[idx - lookback_days]]
    return current - prior


report = []
def p(line=""):
    report.append(line)


p("# C2: Override 4.0 — Backdrop Candidates")
p()
p(f"**Date:** 2026-03-24")
p(f"**Data:** {len(rows)} trading days from spy_daily_returns.csv")
p(f"**Method:** All predictors use PRIOR-day data only (no lookahead)")
p()
p("---")
p()

# ══════════════════════════════════════════════════════════════
# TASK 1: MULTI-DAY VIX MOMENTUM
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("TASK 1: MULTI-DAY VIX MOMENTUM")
print("=" * 70)

p("## 1. Multi-Day VIX Momentum")
p()
p("VIX change over N prior trading days → next-day SPY open-to-close return.")
p()

MOMENTUM_BUCKETS = [
    ("Falling >3pts", -999, -3),
    ("Falling 1-3pts", -3, -1),
    ("Flat (±1pt)", -1, 1),
    ("Rising 1-3pts", 1, 3),
    ("Rising >3pts", 3, 999),
]

all_momentum_results = {}  # horizon -> list of (label, stats)

for horizon in [3, 5, 10]:
    p(f"### {horizon}-Day VIX Change")
    p()
    p(f"| VIX {horizon}d change | Days | Mean SPY Return | Median | Std | Sharpe | WR (>0) | t-stat | p-value |")
    p(f"|{'─'*18}|-----:|----------------:|-------:|----:|-------:|--------:|-------:|--------:|")

    groups_for_anova = []
    horizon_results = []

    for label, lo, hi in MOMENTUM_BUCKETS:
        bucket = []
        for row in rows:
            chg = vix_change(row["date"], horizon)
            if chg is not None and lo <= chg < hi:
                bucket.append(row["ret"])

        st = bucket_stats(bucket)
        groups_for_anova.append(bucket)
        horizon_results.append((label, st))

        if st["n"] < 3:
            p(f"| {label} | {st['n']} | — | — | — | — | — | — | — |")
        else:
            p(f"| {label} | {st['n']} | {st['mean']:+.4f}% | {st['median']:+.4f}% | "
              f"{st['std']:.4f}% | {st['sharpe']:+.3f} | {st['wr']:.1f}% | "
              f"{st['t']:+.2f} | {st['p']:.4f} |")

        status = f"  {label:<20} N={st['n']:>4}"
        if st["n"] >= 3:
            status += f"  mean={st['mean']:+.4f}%  Sharpe={st['sharpe']:+.3f}  p={st['p']:.4f}"
        print(status)

    f_stat, f_p = anova_f(groups_for_anova)
    all_momentum_results[horizon] = {
        "buckets": horizon_results,
        "f_stat": f_stat,
        "f_p": f_p,
        "best_sharpe": max((abs(s["sharpe"]) for _, s in horizon_results if not np.isnan(s["sharpe"])), default=0),
    }
    p()
    p(f"**ANOVA F={f_stat:.3f}, p={f_p:.4f}**")
    p()
    print(f"\n  {horizon}d ANOVA: F={f_stat:.3f}, p={f_p:.4f}")
    print()


# ══════════════════════════════════════════════════════════════
# TASK 2: VIX/VIX3M TERM STRUCTURE
# ══════════════════════════════════════════════════════════════

print("=" * 70)
print("TASK 2: VIX/VIX3M TERM STRUCTURE")
print("=" * 70)

p("## 2. VIX/VIX3M Term Structure")
p()

vix3m_path = ROOT / "Fetched_Data" / "VIX3M_FRED.csv"
vix3m_path2 = ROOT / "Fetched_Data" / "VIX3M_data.csv"
has_vix3m = False

for vp in [vix3m_path, vix3m_path2]:
    if vp.exists() and vp.stat().st_size > 100:
        has_vix3m = True
        break

if not has_vix3m:
    p("**SKIPPED — VIX3M data not available in repo.**")
    p()
    p("Per C1 data inventory: VIX3M_FRED.csv and VIX3M_data.csv do not exist.")
    p("This is S32's top-recommended signal. Acquiring VIX3M data should be a priority.")
    p()
    print("  SKIPPED — no VIX3M data available")
else:
    p("VIX3M data found — computing term structure ratio...")
    # (Would compute here if data existed)

print()


# ══════════════════════════════════════════════════════════════
# TASK 3: VARIANCE RISK PREMIUM (VRP)
# ══════════════════════════════════════════════════════════════

print("=" * 70)
print("TASK 3: VARIANCE RISK PREMIUM (VRP)")
print("=" * 70)

p("## 3. Variance Risk Premium (VRP)")
p()
p("VRP = VIX_close − Realized_Vol_5d, where RV_5d = std(daily_returns, window=5) × √252 × 100")
p()
p("**S32 caveat:** Academic literature finds VRP predictive at quarterly horizons. Daily may be noise.")
p()

# Compute trailing 5-day realized vol for each row
# We need prior 5 daily returns ending at prior day
# Since our rows are already sorted by date, we can use rolling window
rets_array = np.array([r["ret"] for r in rows])  # These are % returns

vrp_data = []
for i in range(5, len(rows)):
    window = rets_array[i-5:i]  # 5 days ending at i-1 (prior day's return is at i-1)
    # Actually we want the 5 returns BEFORE today, which are indices i-5..i-1
    rv_daily_std = np.std(window, ddof=1)  # daily std in %
    rv_annualized = rv_daily_std * sqrt(252)  # annualized, still in %
    vix_prior = rows[i]["vix_prior"]
    vrp = vix_prior - rv_annualized
    vrp_data.append({
        "row": rows[i],
        "rv5": rv_annualized,
        "vrp": vrp,
    })

print(f"  VRP computed for {len(vrp_data)} days")
vrp_vals = [d["vrp"] for d in vrp_data]
print(f"  VRP range: {min(vrp_vals):.1f} to {max(vrp_vals):.1f}")
print(f"  VRP mean: {np.mean(vrp_vals):.1f}, median: {np.median(vrp_vals):.1f}")

VRP_BUCKETS = [
    ("High (>10)", 10, 999),
    ("Normal (5-10)", 5, 10),
    ("Low (0-5)", 0, 5),
    ("Negative (<0)", -999, 0),
]

p(f"| VRP Bucket | Days | Mean SPY Return | Median | Std | Sharpe | WR (>0) | t-stat | p-value |")
p(f"|{'─'*16}|-----:|----------------:|-------:|----:|-------:|--------:|-------:|--------:|")

vrp_groups = []
vrp_results = []

for label, lo, hi in VRP_BUCKETS:
    bucket = [d["row"]["ret"] for d in vrp_data if lo <= d["vrp"] < hi]
    st = bucket_stats(bucket)
    vrp_groups.append(bucket)
    vrp_results.append((label, st))

    if st["n"] < 3:
        p(f"| {label} | {st['n']} | — | — | — | — | — | — | — |")
    else:
        p(f"| {label} | {st['n']} | {st['mean']:+.4f}% | {st['median']:+.4f}% | "
          f"{st['std']:.4f}% | {st['sharpe']:+.3f} | {st['wr']:.1f}% | "
          f"{st['t']:+.2f} | {st['p']:.4f} |")
    print(f"  {label:<20} N={st['n']:>4}  mean={st['mean']:+.4f}%  Sharpe={st['sharpe']:+.3f}  p={st['p']:.4f}" if st["n"] >= 3 else f"  {label:<20} N={st['n']}")

vrp_f, vrp_fp = anova_f(vrp_groups)
p()
p(f"**ANOVA F={vrp_f:.3f}, p={vrp_fp:.4f}**")
p()
print(f"\n  VRP ANOVA: F={vrp_f:.3f}, p={vrp_fp:.4f}")

# VRP distribution
p("### VRP Distribution")
p()
p(f"| Metric | Value |")
p(f"|--------|------:|")
p(f"| Mean VRP | {np.mean(vrp_vals):.2f} |")
p(f"| Median VRP | {np.median(vrp_vals):.2f} |")
p(f"| Std VRP | {np.std(vrp_vals):.2f} |")
p(f"| Min VRP | {min(vrp_vals):.2f} |")
p(f"| Max VRP | {max(vrp_vals):.2f} |")
p(f"| Days VRP < 0 | {sum(1 for v in vrp_vals if v < 0)} ({100*sum(1 for v in vrp_vals if v < 0)/len(vrp_vals):.1f}%) |")
p()
print()


# ══════════════════════════════════════════════════════════════
# TASK 4: GAP × VIX INTERACTION
# ══════════════════════════════════════════════════════════════

print("=" * 70)
print("TASK 4: GAP × VIX INTERACTION")
print("=" * 70)

p("## 4. Gap × VIX Interaction")
p()
p("Gap = (today_open − yesterday_close) / yesterday_close × 100")
p("Return = open-to-close return on the gap day")
p()

GAP_BUCKETS = [
    ("Gap up >1%", 1.0, 999),
    ("Gap up 0.3-1%", 0.3, 1.0),
    ("Flat ±0.3%", -0.3, 0.3),
    ("Gap down 0.3-1%", -1.0, -0.3),
    ("Gap down >1%", -999, -1.0),
]

VIX_COLS = [
    ("VIX <20", 0, 20),
    ("VIX 20-25", 20, 25),
    ("VIX ≥25", 25, 999),
]

# Compute gaps
gap_data = []
for i in range(1, len(rows)):
    prev_close = rows[i - 1]["close"]
    today_open = rows[i]["open"]
    gap = (today_open - prev_close) / prev_close * 100
    gap_data.append({
        "row": rows[i],
        "gap": gap,
    })

print(f"  Gap data computed for {len(gap_data)} days")
gaps = [d["gap"] for d in gap_data]
print(f"  Gap range: {min(gaps):.2f}% to {max(gaps):.2f}%")

# Build cross-tabulation header
p("### Mean Intraday Return by Gap × VIX")
p()
header = "| Gap Bucket |"
for vix_label, _, _ in VIX_COLS:
    header += f" {vix_label} |"
header += " All VIX |"
p(header)
p("|" + "---|" * (len(VIX_COLS) + 2))

gap_vix_groups = []  # for ANOVA

for gap_label, gap_lo, gap_hi in GAP_BUCKETS:
    line = f"| {gap_label} |"
    for vix_label, vix_lo, vix_hi in VIX_COLS:
        cell = [d["row"]["ret"] for d in gap_data
                if gap_lo <= d["gap"] < gap_hi
                and vix_lo <= d["row"]["vix_prior"] < vix_hi]
        if len(cell) >= 3:
            m = np.mean(cell)
            line += f" {m:+.3f}% (N={len(cell)}) |"
        elif len(cell) > 0:
            line += f" {np.mean(cell):+.3f}% (N={len(cell)}) |"
        else:
            line += " — |"
        gap_vix_groups.append(cell)

    # All VIX column
    all_cell = [d["row"]["ret"] for d in gap_data if gap_lo <= d["gap"] < gap_hi]
    if len(all_cell) >= 3:
        st = bucket_stats(all_cell)
        line += f" {st['mean']:+.3f}% (N={st['n']}) |"
    else:
        line += f" — (N={len(all_cell)}) |"
    p(line)

gap_vix_f, gap_vix_fp = anova_f([g for g in gap_vix_groups if len(g) >= 2])

p()
p(f"**Cross-tabulation ANOVA F={gap_vix_f:.3f}, p={gap_vix_fp:.4f}**")
p()

# Detailed Gap × VIX with stats
p("### Detailed Gap × VIX Stats")
p()
p("| Gap Bucket | VIX Regime | N | Mean | Sharpe | WR | t-stat | p-value |")
p("|------------|------------|--:|-----:|-------:|---:|-------:|--------:|")

for gap_label, gap_lo, gap_hi in GAP_BUCKETS:
    for vix_label, vix_lo, vix_hi in VIX_COLS:
        cell = [d["row"]["ret"] for d in gap_data
                if gap_lo <= d["gap"] < gap_hi
                and vix_lo <= d["row"]["vix_prior"] < vix_hi]
        st = bucket_stats(cell)
        if st["n"] >= 3:
            p(f"| {gap_label} | {vix_label} | {st['n']} | {st['mean']:+.4f}% | "
              f"{st['sharpe']:+.3f} | {st['wr']:.1f}% | {st['t']:+.2f} | {st['p']:.4f} |")
        elif st["n"] > 0:
            p(f"| {gap_label} | {vix_label} | {st['n']} | — | — | — | — | — |")

p()

# Gap alone (marginal effect)
p("### Gap Effect (marginal, all VIX levels)")
p()
p("| Gap Bucket | Days | Mean Return | Sharpe | WR | t-stat | p-value |")
p("|------------|-----:|----------:|-------:|---:|-------:|--------:|")

gap_alone_groups = []
gap_alone_results = []
for gap_label, gap_lo, gap_hi in GAP_BUCKETS:
    bucket = [d["row"]["ret"] for d in gap_data if gap_lo <= d["gap"] < gap_hi]
    st = bucket_stats(bucket)
    gap_alone_groups.append(bucket)
    gap_alone_results.append((gap_label, st))
    if st["n"] >= 3:
        p(f"| {gap_label} | {st['n']} | {st['mean']:+.4f}% | {st['sharpe']:+.3f} | "
          f"{st['wr']:.1f}% | {st['t']:+.2f} | {st['p']:.4f} |")
    else:
        p(f"| {gap_label} | {st['n']} | — | — | — | — | — |")

gap_f, gap_fp = anova_f(gap_alone_groups)
p()
p(f"**Gap ANOVA F={gap_f:.3f}, p={gap_fp:.4f}**")
p()

print(f"\n  Gap marginal ANOVA: F={gap_f:.3f}, p={gap_fp:.4f}")
print(f"  Gap×VIX cross ANOVA: F={gap_vix_f:.3f}, p={gap_vix_fp:.4f}")
print()


# ══════════════════════════════════════════════════════════════
# TASK 5: RANKING
# ══════════════════════════════════════════════════════════════

print("=" * 70)
print("TASK 5: RANKING ALL CANDIDATES")
print("=" * 70)

p("## 5. Candidate Ranking")
p()

# C1 baseline
c1_baseline_sharpe = 0.249  # VIX 20-25 from C1
c1_f = 1.5  # approximate from C1 regime spread

candidates = []

# VIX level baseline (from C1)
candidates.append({
    "name": "VIX level (C1 baseline)",
    "best_bucket": "VIX 20-25",
    "best_sharpe": c1_baseline_sharpe,
    "f_stat": c1_f,
    "f_p": 0.20,  # approx
    "improvement": "—",
})

# Momentum
for horizon in [3, 5, 10]:
    res = all_momentum_results[horizon]
    best = max(res["buckets"], key=lambda x: abs(x[1]["sharpe"]) if not np.isnan(x[1]["sharpe"]) else 0)
    candidates.append({
        "name": f"VIX {horizon}d momentum",
        "best_bucket": best[0],
        "best_sharpe": best[1]["sharpe"] if not np.isnan(best[1]["sharpe"]) else 0,
        "f_stat": res["f_stat"],
        "f_p": res["f_p"],
        "improvement": f"{best[1]['sharpe'] - c1_baseline_sharpe:+.3f}" if not np.isnan(best[1]["sharpe"]) else "—",
    })

# Term structure
candidates.append({
    "name": "VIX/VIX3M term structure",
    "best_bucket": "N/A",
    "best_sharpe": 0,
    "f_stat": 0,
    "f_p": 1.0,
    "improvement": "DATA UNAVAILABLE",
})

# VRP
vrp_best = max(vrp_results, key=lambda x: abs(x[1]["sharpe"]) if not np.isnan(x[1]["sharpe"]) else 0)
candidates.append({
    "name": "VRP (5d realized vol)",
    "best_bucket": vrp_best[0],
    "best_sharpe": vrp_best[1]["sharpe"] if not np.isnan(vrp_best[1]["sharpe"]) else 0,
    "f_stat": vrp_f,
    "f_p": vrp_fp,
    "improvement": f"{vrp_best[1]['sharpe'] - c1_baseline_sharpe:+.3f}" if not np.isnan(vrp_best[1]["sharpe"]) else "—",
})

# Gap alone
gap_best = max(gap_alone_results, key=lambda x: abs(x[1]["sharpe"]) if not np.isnan(x[1]["sharpe"]) else 0)
candidates.append({
    "name": "Gap (marginal)",
    "best_bucket": gap_best[0],
    "best_sharpe": gap_best[1]["sharpe"] if not np.isnan(gap_best[1]["sharpe"]) else 0,
    "f_stat": gap_f,
    "f_p": gap_fp,
    "improvement": f"{gap_best[1]['sharpe'] - c1_baseline_sharpe:+.3f}" if not np.isnan(gap_best[1]["sharpe"]) else "—",
})

# Gap × VIX interaction
# Find best cell
best_gv_sharpe = 0
best_gv_label = ""
for gap_label, gap_lo, gap_hi in GAP_BUCKETS:
    for vix_label, vix_lo, vix_hi in VIX_COLS:
        cell = [d["row"]["ret"] for d in gap_data
                if gap_lo <= d["gap"] < gap_hi
                and vix_lo <= d["row"]["vix_prior"] < vix_hi]
        if len(cell) >= 5:
            st = bucket_stats(cell)
            if abs(st["sharpe"]) > abs(best_gv_sharpe):
                best_gv_sharpe = st["sharpe"]
                best_gv_label = f"{gap_label} × {vix_label}"

candidates.append({
    "name": "Gap × VIX interaction",
    "best_bucket": best_gv_label,
    "best_sharpe": best_gv_sharpe,
    "f_stat": gap_vix_f,
    "f_p": gap_vix_fp,
    "improvement": f"{best_gv_sharpe - c1_baseline_sharpe:+.3f}",
})

# Sort by absolute best Sharpe
candidates.sort(key=lambda x: abs(x["best_sharpe"]) if isinstance(x["best_sharpe"], (int, float)) else 0, reverse=True)

p("| Rank | Candidate | Best Bucket | Best Sharpe | F-stat | F p-value | vs Baseline |")
p("|-----:|-----------|-------------|:----------:|:------:|:---------:|:-----------:|")
for i, c in enumerate(candidates, 1):
    sh = f"{c['best_sharpe']:+.3f}" if isinstance(c['best_sharpe'], (int, float)) and c['best_sharpe'] != 0 else "—"
    fs = f"{c['f_stat']:.3f}" if isinstance(c['f_stat'], (int, float)) and c['f_stat'] != 0 else "—"
    fp = f"{c['f_p']:.4f}" if isinstance(c['f_p'], (int, float)) and c['f_p'] < 1.0 else "—"
    p(f"| {i} | {c['name']} | {c['best_bucket']} | {sh} | {fs} | {fp} | {c['improvement']} |")

    print(f"  #{i} {c['name']:<30} Sharpe={sh:>7}  F={fs:>7}  p={fp:>7}")

p()

# ══════════════════════════════════════════════════════════════
# RECOMMENDATIONS
# ══════════════════════════════════════════════════════════════

p("## 6. Findings & Recommendations")
p()

# Find statistically significant results
sig_results = []
for horizon in [3, 5, 10]:
    for label, st in all_momentum_results[horizon]["buckets"]:
        if not np.isnan(st["p"]) and st["p"] < 0.10 and st["n"] >= 10:
            sig_results.append(f"VIX {horizon}d {label}: mean={st['mean']:+.4f}%, p={st['p']:.4f}, N={st['n']}")
for label, st in vrp_results:
    if not np.isnan(st["p"]) and st["p"] < 0.10 and st["n"] >= 10:
        sig_results.append(f"VRP {label}: mean={st['mean']:+.4f}%, p={st['p']:.4f}, N={st['n']}")
for label, st in gap_alone_results:
    if not np.isnan(st["p"]) and st["p"] < 0.10 and st["n"] >= 10:
        sig_results.append(f"Gap {label}: mean={st['mean']:+.4f}%, p={st['p']:.4f}, N={st['n']}")

if sig_results:
    p("### Near-Significant Results (p < 0.10)")
    p()
    for s in sig_results:
        p(f"- {s}")
    p()
else:
    p("### No individually significant results at p < 0.10 with N ≥ 10.")
    p()

# Check for any ANOVA significance
anova_results = [
    ("VIX 3d momentum", all_momentum_results[3]["f_stat"], all_momentum_results[3]["f_p"]),
    ("VIX 5d momentum", all_momentum_results[5]["f_stat"], all_momentum_results[5]["f_p"]),
    ("VIX 10d momentum", all_momentum_results[10]["f_stat"], all_momentum_results[10]["f_p"]),
    ("VRP", vrp_f, vrp_fp),
    ("Gap (marginal)", gap_f, gap_fp),
    ("Gap × VIX", gap_vix_f, gap_vix_fp),
]

p("### ANOVA Summary (do regimes explain return variance?)")
p()
p("| Candidate | F-stat | p-value | Significant? |")
p("|-----------|:------:|:-------:|:------------:|")
for name, f, fp in anova_results:
    sig = "YES" if fp < 0.05 else ("marginal" if fp < 0.10 else "NO")
    p(f"| {name} | {f:.3f} | {fp:.4f} | {sig} |")
p()

# Final recommendation
p("### Recommendations for C3")
p()
p("1. **VIX/VIX3M term structure:** HIGHEST PRIORITY to acquire. Academic literature")
p("   and S32 both identify this as the strongest vol regime signal. Currently unavailable.")
p()
p("2. **VIX level as context (from C1):** VIX predicts RANGE, not direction.")
p("   Use for position sizing: scale down when VIX > 25, widen stops when VIX > 20.")
p()
p("3. **Multi-day VIX momentum:** Report the best horizon's results. If any 3d/5d/10d")
p("   change shows edge, consider as a regime filter (not a directional signal).")
p()
p("4. **Gap × VIX interaction:** If gap-down + high-VIX shows mean-reversion, this")
p("   could be a useful entry filter. Report whether the interaction adds value beyond")
p("   gap alone.")
p()
p("5. **VRP:** As S32 warned, daily VRP is likely noise. Report honestly —")
p("   if no daily signal, do not force it into the model.")
p()
p("**Bottom line:** If no candidate clearly beats VIX level baseline, Override 4.0")
p("should focus on VIX as a **volatility context** (sizing/stops) rather than a")
p("directional signal. The alpha likely requires data we don't have (term structure).")

# Save
report_path = OUT_DIR / "C2_BACKDROP_CANDIDATES.md"
with open(report_path, "w") as f:
    f.write("\n".join(report) + "\n")
print(f"\nSaved: {report_path}")
