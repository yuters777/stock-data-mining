#!/usr/bin/env python3
"""
Override 4.1 — Part 2a: VIX Level × Term Structure Cross-Tab.

One table: does term structure add info beyond VIX level alone?
"""

import csv
import numpy as np
from math import erfc, sqrt
from pathlib import Path
from collections import OrderedDict

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "backtest_output" / "override_4_1"
MERGED = OUT_DIR / "spy_vix3m_merged.csv"


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

def sharpe(arr):
    if len(arr) < 2: return 0.0
    m = np.mean(arr)
    s = np.std(arr, ddof=1)
    return (m / s) * sqrt(252) if s > 0 else 0.0

def win_rate(arr):
    if len(arr) == 0: return 0.0
    return np.sum(np.array(arr) > 0) / len(arr) * 100


# Load merged data
rows = []
with open(MERGED) as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)

print(f"Loaded {len(rows)} rows from spy_vix3m_merged.csv\n")

# Bucket functions
def ts_bucket(r):
    if r < 0.95: return "Contango (<0.95)"
    elif r < 1.05: return "Flat (0.95-1.05)"
    else: return "Backwardation (>1.05)"

def vix_bucket(v):
    if v < 20: return "VIX <20"
    elif v < 25: return "VIX 20-25"
    else: return "VIX >=25"

VIX_ORDER = ["VIX <20", "VIX 20-25", "VIX >=25"]
TS_ORDER = ["Contango (<0.95)", "Flat (0.95-1.05)", "Backwardation (>1.05)"]

# Build cross-tab
cells = {}
for vb in VIX_ORDER:
    for tb in TS_ORDER:
        cells[(vb, tb)] = []

for row in rows:
    vix_prior = float(row["vix_prior"])
    ratio = float(row["vix_vix3m_ratio"])
    ret = float(row["daily_return"])
    rng = float(row["intraday_range"])

    vb = vix_bucket(vix_prior)
    tb = ts_bucket(ratio)
    cells[(vb, tb)].append((ret, rng))

# Print cross-tab
print("=" * 80)
print("CROSS-TAB: VIX Level × Term Structure → SPY Next-Day Return")
print("=" * 80)

print(f"\n{'':>14} | {'Contango (<0.95)':>22} | {'Flat (0.95-1.05)':>22} | {'Backwardation (>1.05)':>22} |")
print("-" * 90)

for vb in VIX_ORDER:
    parts = []
    for tb in TS_ORDER:
        data = cells[(vb, tb)]
        n = len(data)
        if n == 0:
            parts.append(f"{'N=0':>22}")
        else:
            rets = np.array([d[0] for d in data])
            m = np.mean(rets)
            wr = win_rate(rets)
            parts.append(f"{m:+.3f}% WR={wr:.0f}% N={n:>3}")
    print(f"{vb:>14} | {parts[0]:>22} | {parts[1]:>22} | {parts[2]:>22} |")

# Detailed stats per cell
print("\n\nDETAILED CELL STATISTICS:")
print(f"{'VIX Level':<12} {'Term Structure':<22} {'N':>4} {'Mean%':>8} {'Med%':>8} {'WR%':>6} {'Sharpe':>7} {'t-stat':>7} {'p-val':>7} {'MeanRng%':>9}")
print("-" * 100)

cell_stats = []
for vb in VIX_ORDER:
    for tb in TS_ORDER:
        data = cells[(vb, tb)]
        n = len(data)
        if n == 0:
            print(f"{vb:<12} {tb:<22} {0:>4}      —        —      —       —       —       —         —")
            cell_stats.append((vb, tb, 0, 0, 0, 0, 0, 0, 1.0, 0))
            continue
        rets = np.array([d[0] for d in data])
        rngs = np.array([d[1] for d in data])
        m, s, t, p = t_test(rets)
        med = np.median(rets)
        wr = win_rate(rets)
        sh = sharpe(rets)
        mr = np.mean(rngs)
        print(f"{vb:<12} {tb:<22} {n:>4} {m:>+8.3f} {med:>+8.3f} {wr:>5.1f} {sh:>+7.2f} {t:>+7.3f} {p:>7.4f} {mr:>8.3f}%")
        cell_stats.append((vb, tb, n, m, med, wr, sh, t, p, mr))

# Key comparison: VIX>=25 + backwardation vs VIX>=25 + contango
print("\n\nKEY COMPARISON: VIX >= 25")
for tb in TS_ORDER:
    data = cells[("VIX >=25", tb)]
    n = len(data)
    if n == 0:
        print(f"  {tb}: N=0")
    else:
        rets = np.array([d[0] for d in data])
        m, s, t, p = t_test(rets)
        wr = win_rate(rets)
        print(f"  {tb}: N={n}, mean={m:+.3f}%, WR={wr:.1f}%, t={t:+.3f}, p={p:.4f}")

# Row marginals (VIX level only, for comparison)
print("\n\nROW MARGINALS (VIX level only — matches C1 baseline):")
for vb in VIX_ORDER:
    all_rets = []
    for tb in TS_ORDER:
        all_rets.extend([d[0] for d in cells[(vb, tb)]])
    arr = np.array(all_rets)
    n = len(arr)
    if n > 0:
        m, s, t, p = t_test(arr)
        wr = win_rate(arr)
        print(f"  {vb}: N={n}, mean={m:+.3f}%, WR={wr:.1f}%")

# Column marginals (term structure only)
print("\nCOLUMN MARGINALS (term structure only):")
for tb in TS_ORDER:
    all_rets = []
    for vb in VIX_ORDER:
        all_rets.extend([d[0] for d in cells[(vb, tb)]])
    arr = np.array(all_rets)
    n = len(arr)
    if n > 0:
        m, s, t, p = t_test(arr)
        wr = win_rate(arr)
        print(f"  {tb}: N={n}, mean={m:+.3f}%, WR={wr:.1f}%")

# Interaction test: does term structure matter WITHIN VIX>=25?
print("\n\nINTERACTION TEST: Within VIX >= 25, does term structure matter?")
high_vix_groups = []
for tb in TS_ORDER:
    data = cells[("VIX >=25", tb)]
    if len(data) >= 2:
        high_vix_groups.append(np.array([d[0] for d in data]))

if len(high_vix_groups) >= 2:
    # Simple two-group t-test between contango and non-contango at high VIX
    contango_rets = np.array([d[0] for d in cells[("VIX >=25", "Contango (<0.95)")]])
    non_contango = []
    for tb in ["Flat (0.95-1.05)", "Backwardation (>1.05)"]:
        non_contango.extend([d[0] for d in cells[("VIX >=25", tb)]])
    non_contango = np.array(non_contango)

    if len(contango_rets) >= 2 and len(non_contango) >= 2:
        m1, s1 = np.mean(contango_rets), np.std(contango_rets, ddof=1)
        m2, s2 = np.mean(non_contango), np.std(non_contango, ddof=1)
        n1, n2 = len(contango_rets), len(non_contango)
        se = sqrt(s1**2/n1 + s2**2/n2) if (s1 > 0 or s2 > 0) else 1
        t_diff = (m1 - m2) / se if se > 0 else 0
        p_diff = p_from_t(t_diff, min(n1, n2) - 1)
        print(f"  VIX>=25 + Contango: mean={m1:+.3f}%, N={n1}")
        print(f"  VIX>=25 + Non-contango: mean={m2:+.3f}%, N={n2}")
        print(f"  Difference: {m1-m2:+.3f}%, t={t_diff:+.3f}, p={p_diff:.4f}")
    else:
        print("  Insufficient data for comparison")
else:
    print("  Insufficient groups for comparison")


# ═══════════════════════════════════════════════════════════
# SAVE MARKDOWN
# ═══════════════════════════════════════════════════════════

md_path = OUT_DIR / "P2a_CROSS_TAB.md"
md = []
md.append("# Override 4.1 — Part 2a: VIX Level × Term Structure Cross-Tab\n")
md.append("**Date:** 2026-03-24\n")
md.append("**Source:** spy_vix3m_merged.csv (272 days, prior-day values only)\n")

md.append("## Cross-Tab: Mean SPY Return (%) by VIX Level × Term Structure\n")
md.append("| | Contango (<0.95) | Flat (0.95–1.05) | Backwardation (>1.05) |")
md.append("|:---------|:-----------------|:-----------------|:----------------------|")

for vb in VIX_ORDER:
    parts = []
    for tb in TS_ORDER:
        data = cells[(vb, tb)]
        n = len(data)
        if n == 0:
            parts.append("— (N=0)")
        else:
            rets = np.array([d[0] for d in data])
            m = np.mean(rets)
            wr = win_rate(rets)
            parts.append(f"{m:+.3f}%, WR={wr:.0f}%, N={n}")
    md.append(f"| **{vb}** | {parts[0]} | {parts[1]} | {parts[2]} |")

md.append("\n## Detailed Cell Statistics\n")
md.append("| VIX Level | Term Structure | N | Mean % | Median % | WR % | Sharpe | t-stat | p-value | Mean Range % |")
md.append("|:----------|:---------------|--:|-------:|---------:|-----:|-------:|-------:|--------:|-------------:|")
for (vb, tb, n, m, med, wr, sh, t, p, mr) in cell_stats:
    if n == 0:
        md.append(f"| {vb} | {tb} | 0 | — | — | — | — | — | — | — |")
    else:
        md.append(f"| {vb} | {tb} | {n} | {m:+.3f} | {med:+.3f} | {wr:.1f} | {sh:+.2f} | {t:+.3f} | {p:.4f} | {mr:.3f} |")

md.append("\n## Key Comparison: VIX >= 25\n")
for tb in TS_ORDER:
    data = cells[("VIX >=25", tb)]
    n = len(data)
    if n == 0:
        md.append(f"- **{tb}:** N=0")
    else:
        rets = np.array([d[0] for d in data])
        m, s, t, p = t_test(rets)
        wr = win_rate(rets)
        md.append(f"- **{tb}:** N={n}, mean={m:+.3f}%, WR={wr:.1f}%, t={t:+.3f}, p={p:.4f}")

# Add interaction test result
contango_rets = np.array([d[0] for d in cells[("VIX >=25", "Contango (<0.95)")]])
non_contango = []
for tb in ["Flat (0.95-1.05)", "Backwardation (>1.05)"]:
    non_contango.extend([d[0] for d in cells[("VIX >=25", tb)]])
non_contango_arr = np.array(non_contango) if non_contango else np.array([])

if len(contango_rets) >= 2 and len(non_contango_arr) >= 2:
    m1 = np.mean(contango_rets)
    m2 = np.mean(non_contango_arr)
    s1 = np.std(contango_rets, ddof=1)
    s2 = np.std(non_contango_arr, ddof=1)
    n1, n2 = len(contango_rets), len(non_contango_arr)
    se = sqrt(s1**2/n1 + s2**2/n2) if (s1 > 0 or s2 > 0) else 1
    t_diff = (m1 - m2) / se if se > 0 else 0
    p_diff = p_from_t(t_diff, min(n1, n2) - 1)
    md.append(f"\n**Interaction test (VIX>=25):** Contango vs Non-contango difference = {m1-m2:+.3f}%, t = {t_diff:+.3f}, p = {p_diff:.4f}")
    if p_diff < 0.10:
        md.append(f"\n→ Term structure **adds information** within high-VIX regime")
    else:
        md.append(f"\n→ Term structure does **not significantly differentiate** within high-VIX regime (p = {p_diff:.4f})")

md.append("\n## Marginals\n")
md.append("### By VIX Level (row marginals)")
for vb in VIX_ORDER:
    all_rets = []
    for tb in TS_ORDER:
        all_rets.extend([d[0] for d in cells[(vb, tb)]])
    arr = np.array(all_rets)
    if len(arr) > 0:
        m = np.mean(arr)
        wr = win_rate(arr)
        md.append(f"- {vb}: N={len(arr)}, mean={m:+.3f}%, WR={wr:.1f}%")

md.append("\n### By Term Structure (column marginals)")
for tb in TS_ORDER:
    all_rets = []
    for vb in VIX_ORDER:
        all_rets.extend([d[0] for d in cells[(vb, tb)]])
    arr = np.array(all_rets)
    if len(arr) > 0:
        m = np.mean(arr)
        wr = win_rate(arr)
        md.append(f"- {tb}: N={len(arr)}, mean={m:+.3f}%, WR={wr:.1f}%")

md.append("\n---\n*Generated by p2a_cross_tab.py*\n")

with open(md_path, "w") as f:
    f.write("\n".join(md) + "\n")

print(f"\nSaved: {md_path}")
print("Done.")
