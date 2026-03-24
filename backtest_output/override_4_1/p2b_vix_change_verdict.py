#!/usr/bin/env python3
"""
Override 4.1 — Part 2b: 1d Prior VIX Change Split-Sample + Final Verdict.

1. Compute prior_vix_change = VIX(t-1) - VIX(t-2) for each day
2. Bucket analysis with split-sample validation
3. Threshold robustness at 1.5, 2.0, 2.5 pt cutoffs
4. Generate final OVERRIDE_4_1_RESULTS.md
"""

import csv
import numpy as np
from math import erfc, sqrt
from pathlib import Path
from collections import OrderedDict

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "backtest_output" / "override_4_1"
MERGED = OUT_DIR / "spy_vix3m_merged.csv"


# ── Stats helpers ──────────────────────────────────────────

def p_from_t(t_stat, df):
    return erfc(abs(t_stat) / sqrt(2))

def t_test(arr):
    n = len(arr)
    if n < 2:
        return (np.mean(arr) if n else 0, 0, 0, 1.0)
    m = np.mean(arr)
    s = np.std(arr, ddof=1)
    t = m / (s / sqrt(n)) if s > 0 else 0
    p = p_from_t(t, n - 1)
    return (m, s, t, p)

def anova_f(groups):
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
    if F <= 1:
        p = 1.0
    else:
        x = (F ** (1/3) * (1 - 2/(9*df_within)) - (1 - 2/(9*df_between))) / \
            sqrt(2/(9*df_between) + (F ** (2/3)) * 2/(9*df_within))
        p = erfc(abs(x) / sqrt(2))
    return (F, p, df_between, df_within)

def sharpe(arr):
    if len(arr) < 2: return 0.0
    m = np.mean(arr)
    s = np.std(arr, ddof=1)
    return (m / s) * sqrt(252) if s > 0 else 0.0

def win_rate(arr):
    if len(arr) == 0: return 0.0
    return np.sum(np.array(arr) > 0) / len(arr) * 100


# ═══════════════════════════════════════════════════════════
# TASK 1: 1d PRIOR VIX CHANGE SPLIT-SAMPLE
# ═══════════════════════════════════════════════════════════

print("=" * 70)
print("TASK 1: 1d PRIOR VIX CHANGE SPLIT-SAMPLE")
print("=" * 70)

# Load merged data
rows = []
with open(MERGED) as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)

print(f"Loaded {len(rows)} rows\n")

# Compute prior_vix_change = VIX(t-1) - VIX(t-2)
# vix_prior[t] = VIX close on day t-1
# vix_prior[t-1] = VIX close on day t-2
# So: prior_vix_change[t] = vix_prior[t] - vix_prior[t-1]
# First row has no prior, so drop it.

data_rows = []  # rows with valid prior_vix_change
for i in range(1, len(rows)):
    vix_t1 = float(rows[i]["vix_prior"])      # VIX(t-1)
    vix_t2 = float(rows[i-1]["vix_prior"])    # VIX(t-2)
    change = vix_t1 - vix_t2
    data_rows.append({
        "date": rows[i]["date"],
        "daily_return": float(rows[i]["daily_return"]),
        "intraday_range": float(rows[i]["intraday_range"]),
        "vix_prior": vix_t1,
        "prior_vix_change": change,
    })

print(f"Days with valid 1d VIX change: {len(data_rows)}")
changes = [r["prior_vix_change"] for r in data_rows]
print(f"  Mean change: {np.mean(changes):+.3f} pts")
print(f"  Std: {np.std(changes):.3f} pts")
print(f"  Min: {np.min(changes):+.3f}, Max: {np.max(changes):+.3f}")


def run_bucket_analysis(data, threshold, label_prefix=""):
    """Bucket by VIX change at given threshold. Return bucket results."""
    buckets = OrderedDict([
        (f"Fell >{threshold}pts", lambda c: c < -threshold),
        (f"Fell {threshold/2:.1f}-{threshold}pts", lambda c: -threshold <= c < -threshold/2),
        (f"Flat (±{threshold/2:.1f}pt)", lambda c: -threshold/2 <= c <= threshold/2),
        (f"Rose {threshold/2:.1f}-{threshold}pts", lambda c: threshold/2 < c <= threshold),
        (f"Rose >{threshold}pts", lambda c: c > threshold),
    ])

    bucket_data = OrderedDict((k, []) for k in buckets)
    for row in data:
        ch = row["prior_vix_change"]
        for bname, test in buckets.items():
            if test(ch):
                bucket_data[bname].append(row["daily_return"])
                break

    results = []
    for bname in buckets:
        arr = np.array(bucket_data[bname])
        n = len(arr)
        if n < 2:
            results.append((bname, n, 0, 0, 0, 0, 1.0))
        else:
            m, s, t, p = t_test(arr)
            wr = win_rate(arr)
            results.append((bname, n, m, wr, sharpe(arr), t, p))

    # ANOVA
    groups = [np.array(bucket_data[k]) for k in buckets if len(bucket_data[k]) >= 2]
    if len(groups) >= 2:
        F, p_a, df_b, df_w = anova_f(groups)
    else:
        F, p_a, df_b, df_w = 0, 1.0, 0, 0

    return results, F, p_a


# ── Full sample at 2pt threshold ──
print("\n--- Full Sample (2pt threshold) ---")
full_results, full_F, full_p = run_bucket_analysis(data_rows, 2.0)
print(f"  {'Bucket':<22} {'N':>4} {'Mean%':>8} {'WR%':>6} {'Sharpe':>7} {'t-stat':>7} {'p-val':>7}")
print("  " + "-" * 66)
for (bname, n, m, wr, sh, t, p) in full_results:
    if n < 2:
        print(f"  {bname:<22} {n:>4}      —      —       —       —       —")
    else:
        print(f"  {bname:<22} {n:>4} {m:>+8.3f} {wr:>5.1f} {sh:>+7.2f} {t:>+7.3f} {p:>7.4f}")
print(f"\n  ANOVA: F = {full_F:.3f}, p = {full_p:.4f}")

# ── Split-sample ──
mid = len(data_rows) // 2
first_half = data_rows[:mid]
second_half = data_rows[mid:]
print(f"\n--- Split-Sample: First half ({len(first_half)} days: {first_half[0]['date']} to {first_half[-1]['date']}) ---")
h1_results, h1_F, h1_p = run_bucket_analysis(first_half, 2.0)
for (bname, n, m, wr, sh, t, p) in h1_results:
    if n < 2:
        print(f"  {bname:<22} {n:>4}      —")
    else:
        print(f"  {bname:<22} {n:>4} {m:>+8.3f} {wr:>5.1f}%")
print(f"  ANOVA: F = {h1_F:.3f}, p = {h1_p:.4f}")

print(f"\n--- Split-Sample: Second half ({len(second_half)} days: {second_half[0]['date']} to {second_half[-1]['date']}) ---")
h2_results, h2_F, h2_p = run_bucket_analysis(second_half, 2.0)
for (bname, n, m, wr, sh, t, p) in h2_results:
    if n < 2:
        print(f"  {bname:<22} {n:>4}      —")
    else:
        print(f"  {bname:<22} {n:>4} {m:>+8.3f} {wr:>5.1f}%")
print(f"  ANOVA: F = {h2_F:.3f}, p = {h2_p:.4f}")

# ── Stability check ──
print("\n--- Stability Comparison ---")
print(f"  {'Bucket':<22} {'Full Mean':>10} {'H1 Mean':>10} {'H2 Mean':>10} {'Sign Flip?':>12}")
for i, (bname, n, m, wr, sh, t, p) in enumerate(full_results):
    h1_m = h1_results[i][2]
    h2_m = h2_results[i][2]
    h1_n = h1_results[i][1]
    h2_n = h2_results[i][1]
    if h1_n < 2 or h2_n < 2:
        flip = "N/A"
    elif (h1_m > 0) != (h2_m > 0):
        flip = "YES"
    else:
        flip = "No"
    print(f"  {bname:<22} {m:>+9.3f}% {h1_m:>+9.3f}% {h2_m:>+9.3f}% {flip:>12}")

# ── Threshold robustness ──
print("\n--- Threshold Robustness ---")
for thresh in [1.5, 2.0, 2.5]:
    res, F, p = run_bucket_analysis(data_rows, thresh)
    # Focus on extreme buckets
    fell_big = res[0]  # Fell > threshold
    rose_big = res[-1]  # Rose > threshold
    print(f"  Threshold {thresh}pt: F={F:.3f}, p={p:.4f}")
    print(f"    Fell >{thresh}pt: N={fell_big[1]}, mean={fell_big[2]:+.3f}%")
    print(f"    Rose >{thresh}pt: N={rose_big[1]}, mean={rose_big[2]:+.3f}%")


# ═══════════════════════════════════════════════════════════
# TASK 2: FINAL VERDICT — OVERRIDE_4_1_RESULTS.md
# ═══════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("TASK 2: GENERATING FINAL VERDICT")
print("=" * 70)

# Determine verdicts
# Term structure
ts_significant = True  # Part 1: F=3.058, p=0.021
ts_independent = False  # P2a showed it's confounded with VIX level

# Split-sample stability
sign_flips = 0
testable_buckets = 0
for i in range(len(full_results)):
    h1_n = h1_results[i][1]
    h2_n = h2_results[i][1]
    h1_m = h1_results[i][2]
    h2_m = h2_results[i][2]
    if h1_n >= 2 and h2_n >= 2:
        testable_buckets += 1
        if (h1_m > 0) != (h2_m > 0):
            sign_flips += 1

vix_change_stable = sign_flips <= 1  # Allow at most 1 flip

# Check "post-spike rebound" specifically
# The "Fell >2pts" bucket should show positive mean (rebound) in both halves
fell_big_full = full_results[0]
fell_big_h1 = h1_results[0]
fell_big_h2 = h2_results[0]
rebound_survives = (fell_big_h1[1] >= 3 and fell_big_h2[1] >= 3 and
                    fell_big_h1[2] > 0 and fell_big_h2[2] > 0)

# Also check "Rose >2pts" (post-VIX-spike continuation selling)
rose_big_full = full_results[-1]
rose_big_h1 = h1_results[-1]
rose_big_h2 = h2_results[-1]
spike_sell_survives = (rose_big_h1[1] >= 3 and rose_big_h2[1] >= 3 and
                       rose_big_h1[2] < 0 and rose_big_h2[2] < 0)

print(f"  Term structure significant (p<0.05): {ts_significant}")
print(f"  Term structure independent of VIX level: {ts_independent}")
print(f"  Split-sample sign flips: {sign_flips}/{testable_buckets}")
print(f"  1d VIX change stable: {vix_change_stable}")
print(f"  Post-VIX-drop rebound survives: {rebound_survives}")
print(f"  Post-VIX-spike selling survives: {spike_sell_survives}")


# ═══════════════════════════════════════════════════════════
# WRITE FINAL MARKDOWN
# ═══════════════════════════════════════════════════════════

md = []
md.append("# Override 4.1 — VIX/VIX3M Term Structure + 1d VIX Change Results\n")
md.append("**Date:** 2026-03-24\n")

# ── Section 1: Term Structure ──
md.append("## 1. VIX/VIX3M Term Structure (Part 1)\n")
md.append("**Source:** FRED VXVCLS (VIX3M), merged with SPY daily returns (272 days)")
md.append("**Signal:** prior-day VIX / prior-day VIX3M ratio (NO lookahead)\n")

md.append("### Ratio Bucket → SPY Next-Day Returns\n")
md.append("| Ratio Bucket | State | Days | Mean % | Median % | WR % | Sharpe | t-stat | p-value |")
md.append("|:------------|:------|-----:|-------:|---------:|-----:|-------:|-------:|--------:|")
md.append("| < 0.85 | Deep contango | 81 | -0.066 | -0.036 | 45.7 | -2.08 | -1.178 | 0.2390 |")
md.append("| 0.85–0.92 | Contango | 105 | +0.034 | +0.082 | 54.3 | +0.92 | +0.596 | 0.5510 |")
md.append("| 0.92–0.97 | Mild contango | 37 | +0.123 | +0.196 | 64.9 | +2.69 | +1.030 | 0.3031 |")
md.append("| 0.97–1.03 | Flat | 31 | +0.037 | +0.175 | 54.8 | +0.51 | +0.180 | 0.8570 |")
md.append("| 1.03–1.10 | Backwardation | 12 | -0.337 | -0.490 | 33.3 | -3.75 | -0.818 | 0.4136 |")
md.append("| > 1.10 | Deep backwardation | 6 | +1.455 | +0.745 | 50.0 | +4.69 | +0.724 | 0.4693 |")
md.append("\n**ANOVA:** F = 3.058, p = 0.0213 (significant at p < 0.05)\n")

md.append("### Ratio → Intraday Range\n")
md.append("| Ratio Bucket | Days | Mean Range % | Median Range % |")
md.append("|:------------|-----:|-------------:|---------------:|")
md.append("| < 0.85 | 81 | 0.756 | 0.639 |")
md.append("| 0.85–0.92 | 105 | 1.006 | 0.875 |")
md.append("| 0.92–0.97 | 37 | 1.304 | 1.226 |")
md.append("| 0.97–1.03 | 31 | 1.703 | 1.547 |")
md.append("| 1.03–1.10 | 12 | 2.244 | 2.094 |")
md.append("| > 1.10 | 6 | 5.953 | 5.713 |")
md.append("\n**ANOVA (Range):** F = 60.501, p < 0.0001 (extremely significant)\n")

# ── Section 2: Cross-Tab ──
md.append("## 2. Cross-Tab: VIX Level × Term Structure (P2a)\n")
md.append("| | Contango (<0.95) | Flat (0.95–1.05) | Backwardation (>1.05) |")
md.append("|:---------|:-----------------|:-----------------|:----------------------|")
md.append("| **VIX <20** | -0.034%, WR=50%, N=187 | -0.651%, WR=29%, N=7 | — (N=0) |")
md.append("| **VIX 20-25** | +0.354%, WR=76%, N=21 | +0.133%, WR=60%, N=35 | — (N=0) |")
md.append("| **VIX >=25** | — (N=0) | +0.030%, WR=50%, N=10 | +0.600%, WR=42%, N=12 |")

md.append("\n### Key Insight")
md.append("VIX level and term structure are **structurally confounded:**")
md.append("- VIX <20 → almost always contango (96% of days)")
md.append("- VIX >=25 → never contango (0% of days)")
md.append("- 3 of 9 cells are empty — interaction test impossible")
md.append("- The ratio's ANOVA significance (p=0.021) is largely because the ratio is a **proxy for VIX level**, not independent information")
md.append("- **Best cell:** VIX 20-25 + Contango = +0.354%, WR=76%, t=2.83, p=0.005 (N=21)")
md.append("  - But this may be a small-sample artifact\n")

# ── Section 3: 1d VIX Change ──
md.append("## 3. 1d Prior VIX Change — Split-Sample (P2b)\n")
md.append("**Signal:** prior_vix_change = VIX(t-1) − VIX(t-2) (NO lookahead)\n")

md.append("### Full Sample (2pt threshold)\n")
md.append("| 1d VIX Change | Days | Mean SPY % | WR % | Sharpe | t-stat | p-value |")
md.append("|:-------------|-----:|-----------:|-----:|-------:|-------:|--------:|")
for (bname, n, m, wr, sh, t, p) in full_results:
    if n < 2:
        md.append(f"| {bname} | {n} | — | — | — | — | — |")
    else:
        md.append(f"| {bname} | {n} | {m:+.3f} | {wr:.1f} | {sh:+.2f} | {t:+.3f} | {p:.4f} |")
md.append(f"\n**ANOVA:** F = {full_F:.3f}, p = {full_p:.4f}\n")

md.append("### Split-Sample Stability\n")
md.append(f"- First half: {len(first_half)} days ({first_half[0]['date']} to {first_half[-1]['date']})")
md.append(f"- Second half: {len(second_half)} days ({second_half[0]['date']} to {second_half[-1]['date']})\n")
md.append("| Bucket | Full Mean % | H1 Mean % | H2 Mean % | H1 N | H2 N | Sign Flip? |")
md.append("|:-------|----------:|---------:|---------:|----:|----:|:----------|")
for i, (bname, n, m, wr, sh, t, p) in enumerate(full_results):
    h1_m = h1_results[i][2]
    h2_m = h2_results[i][2]
    h1_n = h1_results[i][1]
    h2_n = h2_results[i][1]
    if h1_n < 2 or h2_n < 2:
        flip = "N/A (small N)"
    elif (h1_m > 0) != (h2_m > 0):
        flip = "**YES**"
    else:
        flip = "No"
    md.append(f"| {bname} | {m:+.3f} | {h1_m:+.3f} | {h2_m:+.3f} | {h1_n} | {h2_n} | {flip} |")

md.append(f"\nSign flips: **{sign_flips}/{testable_buckets}** testable buckets\n")

md.append("### Threshold Robustness\n")
md.append("| Threshold | ANOVA F | p-value | Fell>X: N, Mean | Rose>X: N, Mean |")
md.append("|----------:|--------:|--------:|:----------------|:----------------|")
for thresh in [1.5, 2.0, 2.5]:
    res, F, p = run_bucket_analysis(data_rows, thresh)
    fell = res[0]
    rose = res[-1]
    md.append(f"| {thresh}pt | {F:.3f} | {p:.4f} | N={fell[1]}, {fell[2]:+.3f}% | N={rose[1]}, {rose[2]:+.3f}% |")

# ── Section 4: Verdict ──
md.append("\n## 4. VERDICT\n")

md.append("### VIX/VIX3M Term Structure")
md.append(f"- ANOVA significant? **Yes** (F=3.058, p=0.021)")
md.append(f"- Independent of VIX level? **No** — ratio is confounded with VIX level")
md.append(f"  - VIX <20 ≈ contango, VIX >=25 ≈ backwardation (structural link)")
md.append(f"  - Cross-tab has 3 empty cells; interaction test impossible")
md.append(f"- Range prediction? **Yes** (F=60.5, p<0.0001) — but VIX level alone does this too")
md.append(f"- **Adds value beyond VIX level? NO** — the ratio is a redundant proxy at daily frequency")
md.append(f"  - May have intraday value (contango slope changes intraday) — test when IB data available\n")

md.append("### 1d Prior VIX Change")
if full_p < 0.10:
    md.append(f"- ANOVA significant? **Yes** (F={full_F:.3f}, p={full_p:.4f})")
else:
    md.append(f"- ANOVA significant? **No** (F={full_F:.3f}, p={full_p:.4f})")
md.append(f"- Split-sample stable? **{'Yes' if vix_change_stable else 'No'}** ({sign_flips}/{testable_buckets} sign flips)")
md.append(f"- Post-VIX-drop rebound survives? **{'Yes' if rebound_survives else 'No'}**")
md.append(f"- Post-VIX-spike selling survives? **{'Yes' if spike_sell_survives else 'No'}**")

if vix_change_stable and full_p < 0.10:
    md.append(f"- **Verdict: 1d VIX change is a viable signal**\n")
elif vix_change_stable:
    md.append(f"- **Verdict: Stable pattern but not statistically significant — marginal signal**\n")
else:
    md.append(f"- **Verdict: Unstable across halves — discard as unreliable**\n")

md.append("### Override Recommendation\n")

# Determine recommendation
if not ts_independent:
    if vix_change_stable and (rebound_survives or spike_sell_survives) and full_p < 0.15:
        recommendation = "4.0 + 1d VIX change rebound flag"
        rec_detail = ("Keep Override 4.0 (VIX level hazard veto + sizing) unchanged. "
                      "Add a supplementary 1d VIX change flag for post-shock context, "
                      "but only as a monitoring indicator, not a hard override.")
        confidence = "medium"
    elif vix_change_stable and full_p < 0.10:
        recommendation = "4.1 with 1d VIX rebound flag"
        rec_detail = ("Upgrade to Override 4.1 by adding a post-VIX-spike rebound flag. "
                      "Term structure dropped (redundant with VIX level).")
        confidence = "medium"
    else:
        recommendation = "Keep Override 4.0 unchanged"
        rec_detail = ("Neither term structure (confounded) nor 1d VIX change "
                      "(insufficient evidence) justify modifying the existing Override 4.0 design. "
                      "The VIX level hazard veto + context sizing remains the best available model.")
        confidence = "high"
else:
    recommendation = "4.1 with term structure layer"
    rec_detail = "Add VIX/VIX3M term structure as an independent signal layer."
    confidence = "medium"

md.append(f"**{recommendation}**\n")
md.append(f"{rec_detail}\n")

md.append("| Option | Status |")
md.append("|:-------|:-------|")
md.append(f"| Keep 4.0 unchanged (hazard veto + sizing only) | {'**SELECTED**' if 'Keep' in recommendation else 'Rejected'} |")
md.append(f"| Upgrade to 4.1 (add term structure layer) | Rejected — confounded with VIX level |")
if 'rebound' in recommendation.lower():
    md.append(f"| Upgrade to 4.1 (add 1d VIX rebound flag) | **SELECTED** (monitoring only) |")
else:
    md.append(f"| Upgrade to 4.1 (add 1d VIX rebound flag) | {'Pending further data' if not vix_change_stable else 'Optional — marginal evidence'} |")
md.append(f"| Both additions | Rejected |")

md.append(f"\n**Confidence:** {confidence}\n")

md.append("### What Would Change Our Mind")
md.append("- **Term structure:** Intraday VIX/VIX3M data from IB could reveal intraday slope changes that matter for entry timing")
md.append("- **1d VIX change:** More data (>500 days) with consistent split-sample results would promote this to a hard signal")
md.append("- **VIX futures term structure (VX1/VX2):** More granular than VIX/VIX3M — acquire from IB when available\n")

md.append("---\n*Generated by p2b_vix_change_verdict.py*\n")

md_path = OUT_DIR / "OVERRIDE_4_1_RESULTS.md"
with open(md_path, "w") as f:
    f.write("\n".join(md) + "\n")

print(f"\nSaved: {md_path}")
print("Done.")
