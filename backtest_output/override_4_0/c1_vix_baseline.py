#!/usr/bin/env python3
"""
Override 4.0 — C1: Data Inventory + VIX Level Baseline.

1. Inventory all volatility-related data
2. Build SPY daily returns merged with VIX
3. Run VIX level bucket analysis as baseline
"""

import csv
import os
import sys
import numpy as np
from math import erfc, sqrt
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "backtest_output" / "override_4_0"
OUT_DIR.mkdir(parents=True, exist_ok=True)


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


# ═══════════════════════════════════════════════════════════
# TASK 1: DATA INVENTORY
# ═══════════════════════════════════════════════════════════

print("=" * 70)
print("TASK 1: DATA INVENTORY")
print("=" * 70)

inventory = []


def check_file(label, path, freq, notes=""):
    p = ROOT / path
    exists = p.exists()
    lines = 0
    date_range = ""
    if exists:
        with open(p) as f:
            all_lines = f.readlines()
            lines = len(all_lines) - 1  # exclude header
            if lines > 0:
                # Try to extract date range
                first = all_lines[1].split(",")[0]
                last = all_lines[-1].split(",")[0]
                date_range = f"{first[:10]} to {last[:10]}"
    complete = "YES" if exists and lines > 200 else ("PARTIAL" if exists else "NO")
    inventory.append({
        "variable": label, "path": path, "freq": freq,
        "date_range": date_range, "rows": lines, "complete": complete,
        "notes": notes,
    })
    status = "✓" if exists else "✗"
    print(f"  {status} {label:<30} {str(path):<50} {lines:>5} rows  {complete}")


check_file("VIX daily (FRED VIXCLS)", "Fetched_Data/VIXCLS_FRED_real.csv", "Daily")
check_file("SPY daily OHLCV", "backtest_output/SPY_daily.csv", "Daily", "Full-day data")
check_file("SPY M5 FIXED", "backtest_output/SPY_m5_regsess_FIXED.csv", "M5", "TRUNCATED at 13:00 ET")
check_file("VIXY daily OHLCV", "backtest_output/VIXY_daily.csv", "Daily")
check_file("VIXY M5 FIXED", "backtest_output/VIXY_m5_regsess_FIXED.csv", "M5", "TRUNCATED at 13:00 ET")
check_file("VIXY raw M5", "Fetched_Data/VIXY_data.csv", "M5")
check_file("SPY raw M5", "Fetched_Data/SPY_data.csv", "M5", "Dual-block Alpha Vantage")

# Check for term structure data
for name, path in [
    ("VIX3M daily", "Fetched_Data/VIX3M_data.csv"),
    ("VIX3M FRED", "Fetched_Data/VIX3M_FRED.csv"),
    ("VIX9D daily", "Fetched_Data/VIX9D_data.csv"),
    ("VIX9D FRED", "Fetched_Data/VIX9D_FRED.csv"),
    ("VX1 futures", "Fetched_Data/VX1_data.csv"),
    ("VX2 futures", "Fetched_Data/VX2_data.csv"),
    ("VVIX daily", "Fetched_Data/VVIX_data.csv"),
]:
    check_file(name, path, "Daily", "Term structure")


# ═══════════════════════════════════════════════════════════
# TASK 2: BUILD SPY DAILY RETURNS + VIX MERGE
# ═══════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("TASK 2: SPY DAILY RETURNS + VIX MERGE")
print("=" * 70)

# Load SPY daily
spy_daily = {}
with open(ROOT / "backtest_output" / "SPY_daily.csv") as f:
    for row in csv.DictReader(f):
        spy_daily[row["date"]] = {
            "open": float(row["Open"]),
            "close": float(row["Close"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
        }

print(f"  SPY daily: {len(spy_daily)} days")

# Load VIX
vix = {}
with open(ROOT / "Fetched_Data" / "VIXCLS_FRED_real.csv") as f:
    for row in csv.DictReader(f):
        val = row["VIXCLS"].strip()
        if val in ("", "."):
            continue
        vix[row["observation_date"]] = float(val)

print(f"  VIX daily: {len(vix)} days")

# Build prior-day VIX lookup
vix_dates = sorted(vix.keys())
prior_vix = {}
for i in range(1, len(vix_dates)):
    prior_vix[vix_dates[i]] = vix[vix_dates[i - 1]]

# Merge
common_dates = sorted(set(spy_daily.keys()) & set(prior_vix.keys()))
print(f"  Matched days (SPY ∩ prior-VIX): {len(common_dates)}")

merged = []
for d in common_dates:
    s = spy_daily[d]
    ret = (s["close"] - s["open"]) / s["open"] * 100
    intraday_range = (s["high"] - s["low"]) / s["open"] * 100
    merged.append({
        "date": d,
        "open": s["open"],
        "close": s["close"],
        "high": s["high"],
        "low": s["low"],
        "daily_return": ret,
        "intraday_range": intraday_range,
        "vix_prior": prior_vix[d],
        "vix_today": vix.get(d, ""),
    })

# Save merged CSV
csv_path = OUT_DIR / "spy_daily_returns.csv"
with open(csv_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(merged[0].keys()))
    writer.writeheader()
    writer.writerows(merged)
print(f"  Saved: {csv_path} ({len(merged)} rows)")

# Validation
returns = [m["daily_return"] for m in merged]
print(f"\n  SPY daily return stats:")
print(f"    Mean:   {np.mean(returns):+.4f}%")
print(f"    Median: {np.median(returns):+.4f}%")
print(f"    Std:    {np.std(returns):.4f}%")
print(f"    Min:    {np.min(returns):+.4f}%")
print(f"    Max:    {np.max(returns):+.4f}%")
print(f"    WR>0:   {100 * np.sum(np.array(returns) > 0) / len(returns):.1f}%")


# ═══════════════════════════════════════════════════════════
# TASK 3: VIX LEVEL BUCKETS (BASELINE)
# ═══════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("TASK 3: VIX LEVEL BUCKETS (BASELINE)")
print("=" * 70)

REGIMES = [
    ("<16", 0, 16),
    ("16-20", 16, 20),
    ("20-25", 20, 25),
    ("≥25", 25, 999),
]

lines_report = []


def p(line=""):
    lines_report.append(line)


# Baseline results
p("# C1: Override 4.0 — VIX Level Baseline")
p()
p(f"**Date:** 2026-03-24")
p(f"**SPY data:** `backtest_output/SPY_daily.csv` (full-day OHLCV, NOT truncated M5)")
p(f"**VIX data:** `Fetched_Data/VIXCLS_FRED_real.csv` (FRED daily close)")
p(f"**Matched days:** {len(merged)}")
p(f"**Method:** Prior-day VIX close → next-day SPY open-to-close return (no lookahead)")
p()
p("---")
p()

# Data Inventory section
p("## 1. Data Inventory")
p()
p("| Variable | Path | Freq | Date Range | Rows | Status | Notes |")
p("|----------|------|------|------------|-----:|:------:|-------|")
for item in inventory:
    p(f"| {item['variable']} | `{item['path']}` | {item['freq']} | {item['date_range']} | "
      f"{item['rows']} | {item['complete']} | {item['notes']} |")
p()
p("### Key Findings")
p()
p("- **VIX3M, VIX9D, VIX futures: NOT AVAILABLE** — cannot test term structure")
p("- **SPY daily OHLCV: AVAILABLE** — full-day open/close, suitable for regime testing")
p("- **SPY M5 FIXED: TRUNCATED at 13:00 ET** — cannot use for full-day intraday analysis")
p("- **VIX intraday: NOT AVAILABLE** — cannot test micro shock detection from VIX M5")
p("- **VIXY M5: TRUNCATED** — same 13:00 ET issue as SPY")
p()
p("### What We CAN Test")
p("1. VIX daily level buckets (this report)")
p("2. Multi-day VIX momentum (3d, 5d, 10d VIX change)")
p("3. SPY realized volatility from morning M5 bars (09:30-13:00)")
p("4. Variance risk premium (VIX - realized vol)")
p("5. SPY morning vol bursts from M5 data")
p("6. Gap × VIX interaction")
p()
p("### What We CANNOT Test (need IB data)")
p("1. VIX/VIX3M term structure ratio")
p("2. VIX9D/VIX ratio (short-term fear)")
p("3. VIX futures contango/backwardation (VX1!/VX2!)")
p("4. VIX intraday spike detection")
p("5. Full-session SPY afternoon vol patterns")
p()

# SPY daily return summary
p("## 2. SPY Daily Returns Summary")
p()
p(f"| Metric | Value |")
p(f"|--------|------:|")
p(f"| Trading days | {len(merged)} |")
p(f"| Mean return | {np.mean(returns):+.4f}% |")
p(f"| Median return | {np.median(returns):+.4f}% |")
p(f"| Std dev | {np.std(returns):.4f}% |")
p(f"| WR (>0) | {100 * np.sum(np.array(returns) > 0) / len(returns):.1f}% |")
p(f"| Date range | {merged[0]['date']} to {merged[-1]['date']} |")
p()

# VIX Level Bucket analysis
p("## 3. VIX Level Buckets (Baseline)")
p()
p("Prior-day VIX close → next-day SPY open-to-close return.")
p()
p("| VIX Regime | Days | Mean Return | Median | Std | Sharpe | WR (>0) | t-stat | p-value |")
p("|------------|-----:|----------:|-------:|----:|-------:|--------:|-------:|--------:|")

regime_data = {}
print(f"\n  {'Regime':<10} {'N':>5} {'Mean%':>9} {'Median%':>9} {'Std%':>8} {'Sharpe':>7} {'WR':>6} {'t':>7} {'p':>8}")
print(f"  {'-' * 72}")

for label, lo, hi in REGIMES:
    bucket = [m["daily_return"] for m in merged if lo <= m["vix_prior"] < hi]
    n = len(bucket)
    if n < 3:
        continue
    arr = np.array(bucket)
    m, s, t, pv = t_test(arr)
    med = np.median(arr)
    wr = 100 * np.sum(arr > 0) / n
    sharpe = m / s if s > 0 else 0  # daily Sharpe (not annualized)
    regime_data[label] = {"n": n, "mean": m, "std": s, "sharpe": sharpe, "wr": wr, "t": t, "p": pv}

    print(f"  {label:<10} {n:>5} {m:>+8.4f}% {med:>+8.4f}% {s:>7.4f}% {sharpe:>+6.3f} {wr:>5.1f}% {t:>+6.2f} {pv:>8.4f}")
    p(f"| {label} | {n} | {m:+.4f}% | {med:+.4f}% | {s:.4f}% | {sharpe:+.3f} | {wr:.1f}% | {t:+.2f} | {pv:.4f} |")

p()

# Range analysis
p("### Intraday Range by VIX Regime")
p()
p("| VIX Regime | Days | Mean Range | Median Range |")
p("|------------|-----:|-----------:|-------------:|")
for label, lo, hi in REGIMES:
    bucket = [m["intraday_range"] for m in merged if lo <= m["vix_prior"] < hi]
    if len(bucket) < 3:
        continue
    arr = np.array(bucket)
    p(f"| {label} | {len(bucket)} | {np.mean(arr):.3f}% | {np.median(arr):.3f}% |")
p()

# Finer-grained buckets
p("### Fine-Grained VIX Buckets")
p()
p("| VIX Range | Days | Mean Return | WR | Sharpe |")
p("|-----------|-----:|----------:|---:|-------:|")
FINE_BUCKETS = [
    ("<14", 0, 14), ("14-16", 14, 16), ("16-18", 16, 18), ("18-20", 18, 20),
    ("20-22", 20, 22), ("22-25", 22, 25), ("25-30", 25, 30), ("≥30", 30, 999),
]
for label, lo, hi in FINE_BUCKETS:
    bucket = [m["daily_return"] for m in merged if lo <= m["vix_prior"] < hi]
    n = len(bucket)
    if n < 3:
        p(f"| {label} | {n} | — | — | — |")
        continue
    arr = np.array(bucket)
    m = np.mean(arr)
    s = np.std(arr, ddof=1)
    wr = 100 * np.sum(arr > 0) / n
    sharpe = m / s if s > 0 else 0
    p(f"| {label} | {n} | {m:+.4f}% | {wr:.1f}% | {sharpe:+.3f} |")
p()

# Monotonicity test
p("### Monotonicity Analysis")
p()
regime_means = [(label, regime_data[label]["mean"]) for label in regime_data]
is_monotonic = all(regime_means[i][1] >= regime_means[i + 1][1]
                    for i in range(len(regime_means) - 1))
is_inverse_monotonic = all(regime_means[i][1] <= regime_means[i + 1][1]
                           for i in range(len(regime_means) - 1))
p(f"- Mean returns by regime: {', '.join(f'{l}={m:+.4f}%' for l, m in regime_means)}")
p(f"- Monotonically decreasing (higher VIX → lower returns): {'YES' if is_monotonic else 'NO'}")
p(f"- Monotonically increasing (higher VIX → higher returns): {'YES' if is_inverse_monotonic else 'NO'}")
p()

# Statistical test: high vs low VIX
low_vix = [m["daily_return"] for m in merged if m["vix_prior"] < 20]
high_vix = [m["daily_return"] for m in merged if m["vix_prior"] >= 25]
if len(low_vix) > 5 and len(high_vix) > 5:
    low_arr, high_arr = np.array(low_vix), np.array(high_vix)
    diff = np.mean(low_arr) - np.mean(high_arr)
    se = sqrt(np.std(low_arr, ddof=1)**2 / len(low_arr) + np.std(high_arr, ddof=1)**2 / len(high_arr))
    t_diff = diff / se if se > 0 else 0
    p_diff = p_from_t(t_diff, min(len(low_arr), len(high_arr)) - 1)
    p(f"### VIX<20 vs VIX≥25 Comparison")
    p()
    p(f"| Metric | VIX<20 | VIX≥25 | Difference |")
    p(f"|--------|-------:|-------:|-----------:|")
    p(f"| N | {len(low_arr)} | {len(high_arr)} | — |")
    p(f"| Mean return | {np.mean(low_arr):+.4f}% | {np.mean(high_arr):+.4f}% | {diff:+.4f}% |")
    p(f"| WR | {100*np.sum(low_arr>0)/len(low_arr):.1f}% | {100*np.sum(high_arr>0)/len(high_arr):.1f}% | — |")
    p(f"| t-stat | — | — | {t_diff:+.2f} |")
    p(f"| p-value | — | — | {p_diff:.4f} |")
    p()

# Verdict
p("## 4. Baseline Verdict")
p()
p("This VIX level analysis is the **baseline** that all other Override 4.0 candidates must beat.")
p()
if any(d["p"] < 0.05 for d in regime_data.values()):
    significant = [(l, d) for l, d in regime_data.items() if d["p"] < 0.05]
    p("**Statistically significant regimes (p<0.05):**")
    for label, d in significant:
        p(f"- VIX {label}: mean={d['mean']:+.4f}%, t={d['t']:+.2f}, p={d['p']:.4f}")
    p()
else:
    p("**No VIX regime produces statistically significant SPY returns (p<0.05).**")
    p()

best = max(regime_data.items(), key=lambda x: abs(x[1]["mean"]))
p(f"**Strongest regime effect:** VIX {best[0]} (mean={best[1]['mean']:+.4f}%, N={best[1]['n']})")
p()
p("### Implications for Override 4.0")
p()
p("- If VIX level alone doesn't predict returns → Override should use it as a")
p("  **range/volatility context** (sizing, stop distances) not as a directional signal")
p("- Higher VIX → wider intraday ranges → adjust position sizing")
p("- The baseline Sharpe per regime will be compared against multi-factor models in C2")

# Save report
report_path = OUT_DIR / "C1_VIX_LEVEL_BASELINE.md"
with open(report_path, "w") as f:
    f.write("\n".join(lines_report) + "\n")
print(f"\nSaved: {report_path}")

# Also save data_inventory.md separately
inv_lines = ["# Override 4.0 — Data Inventory", "",
             f"**Date:** 2026-03-24", ""]
inv_lines.append("| Variable | Path | Freq | Date Range | Rows | Status | Notes |")
inv_lines.append("|----------|------|------|------------|-----:|:------:|-------|")
for item in inventory:
    inv_lines.append(
        f"| {item['variable']} | `{item['path']}` | {item['freq']} | {item['date_range']} | "
        f"{item['rows']} | {item['complete']} | {item['notes']} |")
inv_lines.append("")
inv_lines.append("## Available for Override 4.0 Testing")
inv_lines.append("")
inv_lines.append("1. VIX daily level → regime buckets (AVAILABLE)")
inv_lines.append("2. Multi-day VIX change (3d/5d/10d) → momentum (AVAILABLE)")
inv_lines.append("3. SPY morning realized vol from M5 09:30-13:00 (AVAILABLE, partial day)")
inv_lines.append("4. Variance risk premium: VIX - realized vol (AVAILABLE)")
inv_lines.append("5. VIXY daily as VIX proxy (AVAILABLE)")
inv_lines.append("6. Gap × VIX interaction from SPY daily (AVAILABLE)")
inv_lines.append("")
inv_lines.append("## NOT Available (Need IB/Alternative Data)")
inv_lines.append("")
inv_lines.append("1. VIX3M daily → VIX/VIX3M term structure ratio")
inv_lines.append("2. VIX9D daily → short-term fear gauge")
inv_lines.append("3. VIX futures (VX1!, VX2!) → contango/backwardation")
inv_lines.append("4. VIX intraday M5 → micro shock detection")
inv_lines.append("5. SPY full-session M5 → afternoon volatility patterns")

inv_path = OUT_DIR / "data_inventory.md"
with open(inv_path, "w") as f:
    f.write("\n".join(inv_lines) + "\n")
print(f"Saved: {inv_path}")
