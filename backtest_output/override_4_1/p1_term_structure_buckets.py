#!/usr/bin/env python3
"""
Override 4.1 — Part 1: VIX/VIX3M Term Structure Merge + Bucket Analysis.

1. Merge SPY daily returns with VIX3M (FRED VXVCLS)
2. Compute prior-day VIX/VIX3M ratio (NO LOOKAHEAD)
3. Bucket analysis: returns and range by term structure state
4. ANOVA F-test across buckets
"""

import csv
import os
import numpy as np
from math import erfc, sqrt
from pathlib import Path
from collections import OrderedDict

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "backtest_output" / "override_4_1"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ── Stats helpers ──────────────────────────────────────────

def p_from_t(t_stat, df):
    """Two-tailed p-value from t-stat using erfc approximation."""
    return erfc(abs(t_stat) / sqrt(2))


def t_test(arr):
    """Return (mean, std, t-stat, p-value) for one-sample t-test vs 0."""
    n = len(arr)
    if n < 2:
        return (np.mean(arr) if n else 0, 0, 0, 1.0)
    m = np.mean(arr)
    s = np.std(arr, ddof=1)
    t = m / (s / sqrt(n)) if s > 0 else 0
    p = p_from_t(t, n - 1)
    return (m, s, t, p)


def anova_f(groups):
    """One-way ANOVA F-test. Returns (F, p_approx, df_between, df_within)."""
    all_vals = np.concatenate(groups)
    grand_mean = np.mean(all_vals)
    k = len(groups)
    n_total = len(all_vals)

    ss_between = sum(len(g) * (np.mean(g) - grand_mean) ** 2 for g in groups)
    ss_within = sum(np.sum((g - np.mean(g)) ** 2) for g in groups)

    df_between = k - 1
    df_within = n_total - k

    if df_within <= 0 or ss_within == 0:
        return (0, 1.0, df_between, df_within)

    ms_between = ss_between / df_between
    ms_within = ss_within / df_within
    F = ms_between / ms_within

    # F to p approximation (using normal approx for large df)
    # More accurate: use Welch-Satterthwaite or chi-sq approx
    # Simple approximation via erfc for reporting
    if F <= 1:
        p = 1.0
    else:
        # Use the relationship between F and chi-squared for approx
        x = (F ** (1/3) * (1 - 2/(9*df_within)) - (1 - 2/(9*df_between))) / \
            sqrt(2/(9*df_between) + (F ** (2/3)) * 2/(9*df_within))
        p = erfc(abs(x) / sqrt(2))
    return (F, p, df_between, df_within)


def sharpe(arr, annual_factor=252):
    """Annualized Sharpe ratio from daily returns (%)."""
    if len(arr) < 2:
        return 0.0
    m = np.mean(arr)
    s = np.std(arr, ddof=1)
    if s == 0:
        return 0.0
    return (m / s) * sqrt(annual_factor)


def win_rate(arr):
    """Fraction of positive values."""
    if len(arr) == 0:
        return 0.0
    return np.sum(np.array(arr) > 0) / len(arr) * 100


# ═══════════════════════════════════════════════════════════
# TASK 1: MERGE SPY DAILY RETURNS WITH VIX3M
# ═══════════════════════════════════════════════════════════

print("=" * 70)
print("TASK 1: MERGE SPY DAILY RETURNS WITH VIX3M")
print("=" * 70)

# Load SPY daily returns
spy_path = ROOT / "backtest_output" / "override_4_0" / "spy_daily_returns.csv"
spy_rows = []
with open(spy_path) as f:
    reader = csv.DictReader(f)
    for row in reader:
        spy_rows.append(row)

print(f"\nSPY daily returns: {len(spy_rows)} rows")
print(f"  Date range: {spy_rows[0]['date']} to {spy_rows[-1]['date']}")
print(f"  Columns: {list(spy_rows[0].keys())}")

# Verify VIX is already prior-day in spy_daily_returns.csv
print("\n  VIX lookahead check (first 5 rows):")
print(f"  {'date':>12}  vix_prior  vix_today")
for r in spy_rows[:5]:
    print(f"  {r['date']:>12}  {float(r['vix_prior']):>8.2f}  {float(r['vix_today']):>8.2f}")
print("  → vix_prior IS the prior-day VIX close (confirmed from C1 design)")

# Load VIX3M (FRED VXVCLS)
vix3m_path = ROOT / "Fetched_Data" / "VXVCLS.csv"
vix3m_by_date = {}  # date_str -> float value
vix3m_missing = 0
with open(vix3m_path) as f:
    reader = csv.DictReader(f)
    for row in reader:
        date_str = row["observation_date"].strip()
        val = row["VXVCLS"].strip()
        if val == "" or val == ".":
            vix3m_missing += 1
            continue
        vix3m_by_date[date_str] = float(val)

print(f"\nVIX3M (FRED VXVCLS): {len(vix3m_by_date)} valid rows ({vix3m_missing} missing)")
vix3m_dates = sorted(vix3m_by_date.keys())
print(f"  Date range: {vix3m_dates[0]} to {vix3m_dates[-1]}")

# Build date-sorted VIX3M list for prior-day lookup
vix3m_sorted = [(d, vix3m_by_date[d]) for d in sorted(vix3m_by_date.keys())]
# Map date -> index for fast lookup
vix3m_date_idx = {d: i for i, (d, _) in enumerate(vix3m_sorted)}

# For each SPY trading day, find PRIOR-DAY VIX3M
# prior-day = most recent VIX3M observation BEFORE the SPY date
# The spy_daily_returns already has vix_prior = prior-day VIX close
# We need prior-day VIX3M = VIX3M close from the trading day before

# Strategy: for SPY date t, find the VIX3M value for the most recent date < t
# This is equivalent to what vix_prior does for VIX

merged_rows = []
no_vix3m_prior = 0

for row in spy_rows:
    spy_date = row["date"].strip()

    # Find prior-day VIX3M: most recent VIX3M date strictly before spy_date
    # Binary search approach
    prior_vix3m = None
    prior_vix3m_date = None

    # Simple approach: iterate backwards through sorted dates
    for d, v in reversed(vix3m_sorted):
        if d < spy_date:
            prior_vix3m = v
            prior_vix3m_date = d
            break

    if prior_vix3m is None:
        no_vix3m_prior += 1
        continue

    vix_prior = float(row["vix_prior"])

    # Compute ratio using PRIOR-DAY values for both
    if prior_vix3m > 0:
        vix_vix3m_ratio = vix_prior / prior_vix3m
    else:
        no_vix3m_prior += 1
        continue

    merged_rows.append({
        "date": spy_date,
        "open": row["open"],
        "close": row["close"],
        "high": row["high"],
        "low": row["low"],
        "daily_return": row["daily_return"],
        "intraday_range": row["intraday_range"],
        "vix_prior": row["vix_prior"],
        "vix_today": row["vix_today"],
        "vix3m_prior": f"{prior_vix3m:.2f}",
        "vix3m_prior_date": prior_vix3m_date,
        "vix_vix3m_ratio": f"{vix_vix3m_ratio:.4f}",
    })

print(f"\n  Matched days: {len(merged_rows)} / {len(spy_rows)}")
print(f"  Dropped (no prior VIX3M): {no_vix3m_prior}")
print(f"  Date range: {merged_rows[0]['date']} to {merged_rows[-1]['date']}")

# Check for gaps: are there days where vix3m_prior_date is far from spy_date?
gap_days = []
for r in merged_rows:
    spy_d = r["date"]
    vix3m_d = r["vix3m_prior_date"]
    # Simple day difference (approximate)
    sy, sm, sd = map(int, spy_d.split("-"))
    vy, vm, vd = map(int, vix3m_d.split("-"))
    # Rough calendar day gap
    gap = (sy * 365 + sm * 30 + sd) - (vy * 365 + vm * 30 + vd)
    if gap > 5:  # More than 5 calendar days = suspicious
        gap_days.append((spy_d, vix3m_d, gap))

if gap_days:
    print(f"\n  WARNING: {len(gap_days)} rows with VIX3M prior-date gap > 5 calendar days:")
    for sd, vd, g in gap_days[:5]:
        print(f"    SPY date {sd}, VIX3M prior date {vd} (gap ~{g} days)")
else:
    print(f"\n  No suspicious gaps in VIX3M prior-date alignment.")

# Show ratio distribution
ratios = [float(r["vix_vix3m_ratio"]) for r in merged_rows]
print(f"\n  VIX/VIX3M ratio stats:")
print(f"    Mean:   {np.mean(ratios):.4f}")
print(f"    Median: {np.median(ratios):.4f}")
print(f"    Std:    {np.std(ratios):.4f}")
print(f"    Min:    {np.min(ratios):.4f}")
print(f"    Max:    {np.max(ratios):.4f}")
print(f"    < 1.0 (contango): {sum(1 for r in ratios if r < 1.0)} days ({sum(1 for r in ratios if r < 1.0)/len(ratios)*100:.1f}%)")
print(f"    > 1.0 (backwardation): {sum(1 for r in ratios if r > 1.0)} days ({sum(1 for r in ratios if r > 1.0)/len(ratios)*100:.1f}%)")

# Save merged CSV
merged_path = OUT_DIR / "spy_vix3m_merged.csv"
fieldnames = ["date", "open", "close", "high", "low", "daily_return", "intraday_range",
              "vix_prior", "vix_today", "vix3m_prior", "vix3m_prior_date", "vix_vix3m_ratio"]
with open(merged_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(merged_rows)
print(f"\n  Saved: {merged_path} ({len(merged_rows)} rows)")


# ═══════════════════════════════════════════════════════════
# TASK 2: VIX/VIX3M RATIO BUCKET ANALYSIS
# ═══════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("TASK 2: VIX/VIX3M RATIO BUCKET ANALYSIS")
print("=" * 70)

# Define buckets
RATIO_BUCKETS = OrderedDict([
    ("< 0.85",       ("Deep contango",      lambda r: r < 0.85)),
    ("0.85–0.92",    ("Contango",           lambda r: 0.85 <= r < 0.92)),
    ("0.92–0.97",    ("Mild contango",      lambda r: 0.92 <= r < 0.97)),
    ("0.97–1.03",    ("Flat",               lambda r: 0.97 <= r < 1.03)),
    ("1.03–1.10",    ("Backwardation",      lambda r: 1.03 <= r < 1.10)),
    ("> 1.10",       ("Deep backwardation", lambda r: r >= 1.10)),
])

# Assign each day to a bucket
bucket_returns = OrderedDict()
bucket_ranges = OrderedDict()
for label in RATIO_BUCKETS:
    bucket_returns[label] = []
    bucket_ranges[label] = []

for row in merged_rows:
    ratio = float(row["vix_vix3m_ratio"])
    ret = float(row["daily_return"])
    rng = float(row["intraday_range"])

    for label, (state, test) in RATIO_BUCKETS.items():
        if test(ratio):
            bucket_returns[label].append(ret)
            bucket_ranges[label].append(rng)
            break

# ── Return Bucket Table ──
print("\n  VIX/VIX3M Ratio → SPY Next-Day Returns:")
print(f"  {'Ratio':<12} {'State':<20} {'Days':>5} {'Mean%':>8} {'Med%':>8} {'WR%':>6} {'Sharpe':>7} {'t-stat':>7} {'p-val':>7}")
print("  " + "-" * 88)

report_lines = []  # For markdown
for label, (state, _) in RATIO_BUCKETS.items():
    arr = np.array(bucket_returns[label])
    n = len(arr)
    if n == 0:
        print(f"  {label:<12} {state:<20} {n:>5}      —        —      —       —       —       —")
        report_lines.append((label, state, n, 0, 0, 0, 0, 0, 1.0))
        continue
    m, s, t, p = t_test(arr)
    med = np.median(arr)
    wr = win_rate(arr)
    sh = sharpe(arr)
    print(f"  {label:<12} {state:<20} {n:>5} {m:>+8.3f} {med:>+8.3f} {wr:>5.1f} {sh:>+7.2f} {t:>+7.3f} {p:>7.4f}")
    report_lines.append((label, state, n, m, med, wr, sh, t, p))

# ANOVA
groups = [np.array(bucket_returns[label]) for label in RATIO_BUCKETS if len(bucket_returns[label]) >= 2]
if len(groups) >= 2:
    F, p_anova, df_b, df_w = anova_f(groups)
    print(f"\n  ANOVA F-test: F = {F:.3f}, p = {p_anova:.4f} (df_between={df_b}, df_within={df_w})")
else:
    F, p_anova = 0, 1.0
    print("\n  ANOVA: insufficient groups")

# ── Range Bucket Table ──
print(f"\n  VIX/VIX3M Ratio → Intraday Range:")
print(f"  {'Ratio':<12} {'State':<20} {'Days':>5} {'Mean Range%':>12} {'Med Range%':>12}")
print("  " + "-" * 65)

range_report = []
for label, (state, _) in RATIO_BUCKETS.items():
    arr = np.array(bucket_ranges[label])
    n = len(arr)
    if n == 0:
        print(f"  {label:<12} {state:<20} {n:>5}          —            —")
        range_report.append((label, state, n, 0, 0))
        continue
    m = np.mean(arr)
    med = np.median(arr)
    print(f"  {label:<12} {state:<20} {n:>5} {m:>11.3f}% {med:>11.3f}%")
    range_report.append((label, state, n, m, med))

# ANOVA on range
range_groups = [np.array(bucket_ranges[label]) for label in RATIO_BUCKETS if len(bucket_ranges[label]) >= 2]
if len(range_groups) >= 2:
    F_range, p_range, df_b_r, df_w_r = anova_f(range_groups)
    print(f"\n  ANOVA (Range): F = {F_range:.3f}, p = {p_range:.4f} (df_between={df_b_r}, df_within={df_w_r})")
else:
    F_range, p_range = 0, 1.0

# ── Comparison with C1 VIX Level Baseline ──
print(f"\n  Comparison with C1 VIX Level Baseline:")
print(f"    VIX level ANOVA:      F = 1.861, p ≈ 0.14 (from C1)")
print(f"    VIX/VIX3M ratio ANOVA: F = {F:.3f}, p = {p_anova:.4f}")
if p_anova < 0.10:
    print(f"    → Term structure ADDS predictive value (p < 0.10)")
elif p_anova < 0.20:
    print(f"    → Term structure is MARGINAL (0.10 < p < 0.20)")
else:
    print(f"    → Term structure does NOT add value for daily returns (p > 0.20)")

# Range comparison
print(f"\n    VIX level → Range:      Strong predictor (from C1)")
print(f"    VIX/VIX3M → Range:      F = {F_range:.3f}, p = {p_range:.4f}")
if p_range < 0.05:
    print(f"    → Term structure ALSO predicts range")
else:
    print(f"    → Range prediction: {'marginal' if p_range < 0.15 else 'weak/none'}")


# ═══════════════════════════════════════════════════════════
# SAVE MARKDOWN REPORT
# ═══════════════════════════════════════════════════════════

md_path = OUT_DIR / "P1_TERM_STRUCTURE_BUCKETS.md"

md = []
md.append("# Override 4.1 — Part 1: VIX/VIX3M Term Structure Buckets\n")
md.append(f"**Date:** 2026-03-24\n")

md.append("## Data Merge\n")
md.append(f"- SPY daily returns: {len(spy_rows)} rows ({spy_rows[0]['date']} to {spy_rows[-1]['date']})")
md.append(f"- VIX3M (FRED VXVCLS): {len(vix3m_by_date)} valid rows ({vix3m_dates[0]} to {vix3m_dates[-1]})")
md.append(f"- **Matched days: {len(merged_rows)}** (inner join on date)")
md.append(f"- Dropped (no prior VIX3M): {no_vix3m_prior}")
if gap_days:
    md.append(f"- WARNING: {len(gap_days)} rows with VIX3M prior-date gap > 5 calendar days")
else:
    md.append(f"- No suspicious gaps in VIX3M prior-date alignment")

md.append(f"\n### VIX/VIX3M Ratio Distribution")
md.append(f"- Mean: {np.mean(ratios):.4f}")
md.append(f"- Median: {np.median(ratios):.4f}")
md.append(f"- Std: {np.std(ratios):.4f}")
md.append(f"- Range: {np.min(ratios):.4f} – {np.max(ratios):.4f}")
ct = sum(1 for r in ratios if r < 1.0)
bt = sum(1 for r in ratios if r > 1.0)
md.append(f"- Contango (ratio < 1.0): {ct} days ({ct/len(ratios)*100:.1f}%)")
md.append(f"- Backwardation (ratio > 1.0): {bt} days ({bt/len(ratios)*100:.1f}%)")

md.append(f"\n### Lookahead Prevention")
md.append(f"- VIX: uses `vix_prior` column from C1 (prior-day VIX close)")
md.append(f"- VIX3M: uses most recent VXVCLS observation strictly BEFORE SPY date")
md.append(f"- Ratio = prior_day_VIX / prior_day_VIX3M")

md.append(f"\n## VIX/VIX3M Ratio → SPY Next-Day Returns\n")
md.append(f"| Ratio Bucket | State | Days | Mean Return % | Median % | WR % | Sharpe | t-stat | p-value |")
md.append(f"|:------------|:------|-----:|--------------:|---------:|-----:|-------:|-------:|--------:|")
for (label, state, n, m, med, wr, sh, t, p) in report_lines:
    if n == 0:
        md.append(f"| {label} | {state} | {n} | — | — | — | — | — | — |")
    else:
        md.append(f"| {label} | {state} | {n} | {m:+.3f} | {med:+.3f} | {wr:.1f} | {sh:+.2f} | {t:+.3f} | {p:.4f} |")

md.append(f"\n**ANOVA F-test:** F = {F:.3f}, p = {p_anova:.4f} (df_between={df_b if len(groups) >= 2 else '—'}, df_within={df_w if len(groups) >= 2 else '—'})")

if p_anova < 0.05:
    md.append(f"\n**VERDICT:** VIX/VIX3M ratio is **statistically significant** at p < 0.05.")
elif p_anova < 0.10:
    md.append(f"\n**VERDICT:** VIX/VIX3M ratio is **marginally significant** (p < 0.10). Worth investigating further.")
elif p_anova < 0.20:
    md.append(f"\n**VERDICT:** VIX/VIX3M ratio is **weak** (p = {p_anova:.4f}). Not significant at conventional levels.")
else:
    md.append(f"\n**VERDICT:** VIX/VIX3M ratio shows **no significant relationship** with next-day SPY returns (p = {p_anova:.4f}).")

md.append(f"\n## VIX/VIX3M Ratio → Intraday Range\n")
md.append(f"| Ratio Bucket | State | Days | Mean Range % | Median Range % |")
md.append(f"|:------------|:------|-----:|-------------:|---------------:|")
for (label, state, n, m, med) in range_report:
    if n == 0:
        md.append(f"| {label} | {state} | {n} | — | — |")
    else:
        md.append(f"| {label} | {state} | {n} | {m:.3f} | {med:.3f} |")

md.append(f"\n**ANOVA (Range):** F = {F_range:.3f}, p = {p_range:.4f}")
if p_range < 0.05:
    md.append(f"\n→ Term structure **predicts intraday range** (p < 0.05)")
elif p_range < 0.10:
    md.append(f"\n→ Term structure has **marginal range prediction** (p < 0.10)")
else:
    md.append(f"\n→ Term structure has **weak/no range prediction** (p = {p_range:.4f})")

md.append(f"\n## Comparison with C1 VIX Level Baseline\n")
md.append(f"| Test | ANOVA F | p-value | Significant? |")
md.append(f"|:-----|--------:|--------:|:------------|")
md.append(f"| VIX level → returns (C1) | 1.861 | ~0.14 | No |")
md.append(f"| VIX/VIX3M ratio → returns | {F:.3f} | {p_anova:.4f} | {'Yes' if p_anova < 0.10 else 'No'} |")
md.append(f"| VIX/VIX3M ratio → range | {F_range:.3f} | {p_range:.4f} | {'Yes' if p_range < 0.10 else 'No'} |")

md.append(f"\n## Next Steps\n")
if p_anova < 0.10:
    md.append(f"- Proceed to Part 2: Cross-tab VIX level × term structure")
    md.append(f"- Test combined Override 4.1 model")
else:
    md.append(f"- Term structure alone does not predict daily returns significantly")
    md.append(f"- Part 2 should still cross-tab to check for interaction effects")
    md.append(f"- If cross-tab also null → report 'term structure = no daily edge, wait for intraday data from IB'")

md.append(f"\n---\n*Generated by p1_term_structure_buckets.py*\n")

with open(md_path, "w") as f:
    f.write("\n".join(md) + "\n")

print(f"\n  Saved: {md_path}")
print("\nDone.")
