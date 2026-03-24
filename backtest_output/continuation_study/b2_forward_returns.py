#!/usr/bin/env python3
"""
B2: Forward Returns After 4H EMA 9/21 Cross.

For each cross event in cross_catalog.csv:
  1. Identify the NEXT regular session after the cross confirms
  2. Load M5 FIXED data for that session
  3. Measure forward returns at multiple time windows
  4. Split by ADX bucket
  5. Compare vs random entry

Outputs: B2_FORWARD_RETURNS.md
"""

import csv
import os
import sys
import random
import numpy as np
from collections import defaultdict
from datetime import datetime, timedelta
from math import erfc, sqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from utils.data_loader import load_m5_regsess, ALL_TICKERS

CONT_DIR = ROOT / "backtest_output" / "continuation_study"
CATALOG_PATH = CONT_DIR / "cross_catalog.csv"

# Exclude SPY and VIXY (truncated)
TICKERS = [t for t in ALL_TICKERS if t not in ("SPY", "VIXY")]

# Forward return windows (minutes after 09:30)
WINDOWS = [
    ("+30min", 30),    # 10:00
    ("+1hr", 60),      # 10:30
    ("+1.5hr", 90),    # 11:00
    ("+2hr", 120),     # 11:30
    ("+2.5hr", 150),   # 12:00
    ("+4hr", 240),     # 13:30
    ("+5hr", 300),     # 14:30
    ("Close", 385),    # 15:55
]

ADX_BUCKETS = [
    ("<15", 0, 15),
    ("15-25", 15, 25),
    (">25", 25, 999),
]

random.seed(42)


def p_from_t(t_stat, df):
    """Two-tailed p-value from t-statistic."""
    return erfc(abs(t_stat) / sqrt(2))


def t_test(arr):
    """Return (mean, std, t_stat, p_val) for one-sample t-test vs 0."""
    n = len(arr)
    if n < 2:
        return (np.mean(arr) if n else 0, 0, 0, 1.0)
    m = np.mean(arr)
    s = np.std(arr, ddof=1)
    t = m / (s / sqrt(n)) if s > 0 else 0
    p = p_from_t(t, n - 1)
    return (m, s, t, p)


# ═══════════════════════════════════════════════════════════
# LOAD DATA
# ═══════════════════════════════════════════════════════════

print("Loading cross catalog...")
crosses = []
with open(CATALOG_PATH) as f:
    for row in csv.DictReader(f):
        row["adx_14"] = float(row["adx_14"]) if row["adx_14"] else float("nan")
        row["rsi_14"] = float(row["rsi_14"]) if row["rsi_14"] else float("nan")
        crosses.append(row)

print(f"  Total crosses: {len(crosses)}")
up_crosses = [c for c in crosses if c["direction"] == "UP"]
dn_crosses = [c for c in crosses if c["direction"] == "DOWN"]
print(f"  UP: {len(up_crosses)}, DOWN: {len(dn_crosses)}")

# Pre-load all M5 data and index by ticker→date→bars
print("Loading M5 FIXED data for all tickers...")
m5_data = {}  # ticker → {date_str → list of (minutes_from_open, close)}

for ticker in TICKERS:
    try:
        df = load_m5_regsess(ticker)
    except (FileNotFoundError, ValueError):
        continue

    df["date_str"] = df["Datetime"].dt.strftime("%Y-%m-%d")
    df["minutes"] = (df["Datetime"].dt.hour - 9) * 60 + df["Datetime"].dt.minute - 30

    ticker_dates = {}
    for date_str in df["date_str"].unique():
        day = df[df["date_str"] == date_str].sort_values("minutes")
        bars = list(zip(day["minutes"].values, day["Close"].values))
        ticker_dates[date_str] = bars

    m5_data[ticker] = ticker_dates

print(f"  Loaded {len(m5_data)} tickers")


# ═══════════════════════════════════════════════════════════
# FORWARD RETURN COMPUTATION
# ═══════════════════════════════════════════════════════════

def get_next_session_date(ticker, cross_date, cross_session):
    """Get the next trading session date after a cross.

    If cross is AM → next session is same day PM, but we use NEXT DAY open for entry.
    If cross is PM → next session is next trading day.
    Either way, entry is at next day's 09:30 open.
    """
    if ticker not in m5_data:
        return None
    dates = sorted(m5_data[ticker].keys())
    try:
        idx = dates.index(cross_date)
    except ValueError:
        return None

    # Always use next day for entry (cross may confirm mid-session)
    if idx + 1 < len(dates):
        return dates[idx + 1]
    return None


def compute_forward_returns(ticker, entry_date):
    """Compute forward returns from 09:30 open at each window.

    Returns dict: {window_name: return_pct} or None if data unavailable.
    """
    if ticker not in m5_data or entry_date not in m5_data[ticker]:
        return None

    bars = m5_data[ticker][entry_date]
    if not bars:
        return None

    # Entry price = 09:30 bar close (minute 0)
    open_bars = [b for b in bars if b[0] == 0]
    if not open_bars:
        return None
    entry_price = open_bars[0][1]

    if entry_price <= 0:
        return None

    returns = {}
    for wname, target_min in WINDOWS:
        # Find closest bar at or after target_min
        candidates = [b for b in bars if b[0] >= target_min]
        if candidates:
            exit_price = candidates[0][1]
            ret = (exit_price - entry_price) / entry_price * 100
            returns[wname] = ret
        # Also try exact match
        exact = [b for b in bars if b[0] == target_min]
        if exact:
            returns[wname] = (exact[0][1] - entry_price) / entry_price * 100

    return returns if returns else None


# ═══════════════════════════════════════════════════════════
# TASK 1: UP CROSS FORWARD RETURNS
# ═══════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("TASK 1: FORWARD RETURNS AFTER UP CROSS")
print("=" * 70)

up_returns = defaultdict(list)  # window → [returns]
up_adx_returns = defaultdict(lambda: defaultdict(list))  # adx_bucket → window → [returns]
up_entry_dates = []  # for random comparison

for c in up_crosses:
    ticker = c["ticker"]
    entry_date = get_next_session_date(ticker, c["date"], c["session"])
    if entry_date is None:
        continue

    fwd = compute_forward_returns(ticker, entry_date)
    if fwd is None:
        continue

    up_entry_dates.append((ticker, entry_date))
    adx = c["adx_14"]

    for wname, ret in fwd.items():
        up_returns[wname].append(ret)

        if not np.isnan(adx):
            for blabel, blo, bhi in ADX_BUCKETS:
                if blo <= adx < bhi:
                    up_adx_returns[blabel][wname].append(ret)
                    break

# Print UP results
print("\nOverall UP Cross Forward Returns:")
print(f"  {'Window':<10} {'Mean%':>8} {'Median%':>8} {'WR':>6} {'Std%':>8} {'N':>5} {'t-stat':>7} {'p-val':>8}")
print(f"  {'-' * 68}")
for wname, _ in WINDOWS:
    arr = np.array(up_returns[wname])
    if len(arr) == 0:
        continue
    m, s, t, p = t_test(arr)
    wr = 100 * np.sum(arr > 0) / len(arr)
    med = np.median(arr)
    print(f"  {wname:<10} {m:>+7.3f}% {med:>+7.3f}% {wr:>5.1f}% {s:>7.3f}% {len(arr):>5} {t:>+6.2f} {p:>8.4f}")

print("\nUP Cross by ADX Bucket:")
for blabel, _, _ in ADX_BUCKETS:
    print(f"\n  ADX {blabel}:")
    print(f"  {'Window':<10} {'Mean%':>8} {'WR':>6} {'N':>5} {'t-stat':>7} {'p-val':>8}")
    print(f"  {'-' * 50}")
    for wname, _ in WINDOWS:
        arr = np.array(up_adx_returns[blabel][wname])
        if len(arr) == 0:
            continue
        m, s, t, p = t_test(arr)
        wr = 100 * np.sum(arr > 0) / len(arr)
        print(f"  {wname:<10} {m:>+7.3f}% {wr:>5.1f}% {len(arr):>5} {t:>+6.2f} {p:>8.4f}")


# ═══════════════════════════════════════════════════════════
# TASK 2: DOWN CROSS FORWARD RETURNS
# ═══════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("TASK 2: FORWARD RETURNS AFTER DOWN CROSS")
print("=" * 70)

dn_returns = defaultdict(list)
dn_adx_returns = defaultdict(lambda: defaultdict(list))

for c in dn_crosses:
    ticker = c["ticker"]
    entry_date = get_next_session_date(ticker, c["date"], c["session"])
    if entry_date is None:
        continue

    fwd = compute_forward_returns(ticker, entry_date)
    if fwd is None:
        continue

    for wname, ret in fwd.items():
        dn_returns[wname].append(ret)

        adx = c["adx_14"]
        if not np.isnan(adx):
            for blabel, blo, bhi in ADX_BUCKETS:
                if blo <= adx < bhi:
                    dn_adx_returns[blabel][wname].append(ret)
                    break

print("\nOverall DOWN Cross Forward Returns (negative = DOWN cross 'worked'):")
print(f"  {'Window':<10} {'Mean%':>8} {'Median%':>8} {'%Neg':>6} {'Std%':>8} {'N':>5} {'t-stat':>7} {'p-val':>8}")
print(f"  {'-' * 68}")
for wname, _ in WINDOWS:
    arr = np.array(dn_returns[wname])
    if len(arr) == 0:
        continue
    m, s, t, p = t_test(arr)
    pct_neg = 100 * np.sum(arr < 0) / len(arr)
    med = np.median(arr)
    print(f"  {wname:<10} {m:>+7.3f}% {med:>+7.3f}% {pct_neg:>5.1f}% {s:>7.3f}% {len(arr):>5} {t:>+6.2f} {p:>8.4f}")

print("\nDOWN Cross by ADX Bucket:")
for blabel, _, _ in ADX_BUCKETS:
    print(f"\n  ADX {blabel}:")
    print(f"  {'Window':<10} {'Mean%':>8} {'%Neg':>6} {'N':>5} {'t-stat':>7} {'p-val':>8}")
    print(f"  {'-' * 50}")
    for wname, _ in WINDOWS:
        arr = np.array(dn_adx_returns[blabel][wname])
        if len(arr) == 0:
            continue
        m, s, t, p = t_test(arr)
        pct_neg = 100 * np.sum(arr < 0) / len(arr)
        print(f"  {wname:<10} {m:>+7.3f}% {pct_neg:>5.1f}% {len(arr):>5} {t:>+6.2f} {p:>8.4f}")


# ═══════════════════════════════════════════════════════════
# TASK 3: RANDOM ENTRY COMPARISON
# ═══════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("TASK 3: RANDOM ENTRY COMPARISON")
print("=" * 70)

random_returns = defaultdict(list)

for ticker, entry_date in up_entry_dates:
    if ticker not in m5_data:
        continue
    dates = sorted(m5_data[ticker].keys())
    try:
        idx = dates.index(entry_date)
    except ValueError:
        continue

    # Pick random date within ±30 trading days
    lo = max(0, idx - 30)
    hi = min(len(dates) - 1, idx + 30)
    candidates = [d for d in dates[lo:hi + 1] if d != entry_date]
    if not candidates:
        continue

    rand_date = random.choice(candidates)
    fwd = compute_forward_returns(ticker, rand_date)
    if fwd is None:
        continue

    for wname, ret in fwd.items():
        random_returns[wname].append(ret)

print("\nUP Cross vs Random Entry:")
print(f"  {'Window':<10} {'Cross%':>8} {'Random%':>8} {'Spread':>8} {'t-stat':>7} {'p-val':>8}")
print(f"  {'-' * 56}")
for wname, _ in WINDOWS:
    cross_arr = np.array(up_returns[wname])
    rand_arr = np.array(random_returns[wname])
    if len(cross_arr) == 0 or len(rand_arr) == 0:
        continue
    cross_m = np.mean(cross_arr)
    rand_m = np.mean(rand_arr)
    spread = cross_m - rand_m

    # Two-sample t-test (Welch's)
    n1, n2 = len(cross_arr), len(rand_arr)
    s1, s2 = np.std(cross_arr, ddof=1), np.std(rand_arr, ddof=1)
    se = sqrt(s1**2 / n1 + s2**2 / n2) if (n1 > 1 and n2 > 1) else 1
    t_val = spread / se if se > 0 else 0
    p_val = p_from_t(t_val, min(n1, n2) - 1)
    print(f"  {wname:<10} {cross_m:>+7.3f}% {rand_m:>+7.3f}% {spread:>+7.3f}% {t_val:>+6.2f} {p_val:>8.4f}")


# ═══════════════════════════════════════════════════════════
# TASK 4: GENERATE SUMMARY REPORT
# ═══════════════════════════════════════════════════════════

lines = []


def p(line=""):
    lines.append(line)


p("# B2: Forward Returns After 4H EMA 9/21 Cross")
p()
p(f"**Date:** 2026-03-24")
p(f"**Data:** FIXED M5 data, 25 certified tickers (excl SPY/VIXY)")
p(f"**Entry:** Next session open (09:30 ET) after cross confirms")
p(f"**Cross catalog:** {len(crosses)} total ({len(up_crosses)} UP, {len(dn_crosses)} DOWN)")
p()
p("---")
p()

# UP Cross overall
p("## 1. Forward Returns After UP Cross")
p()
p("| Window | Mean % | Median % | WR | Std % | N | t-stat | p-value |")
p("|--------|-------:|--------:|---:|------:|--:|-------:|--------:|")
flagged_cells = []
for wname, _ in WINDOWS:
    arr = np.array(up_returns[wname])
    if len(arr) == 0:
        continue
    m, s, t, pv = t_test(arr)
    wr = 100 * np.sum(arr > 0) / len(arr)
    med = np.median(arr)
    flag = " **" if m > 0.20 and pv < 0.10 else ""
    if m > 0.20 and pv < 0.10:
        flagged_cells.append(("UP", "Overall", wname, m, pv))
    p(f"| {wname} | {m:+.3f} | {med:+.3f} | {wr:.1f}% | {s:.3f} | {len(arr)} | {t:+.2f} | {pv:.4f} |{flag}")
p()

# UP by ADX
p("### UP Cross by ADX Bucket")
p()
p("| ADX | Window | Mean % | WR | N | t-stat | p-value |")
p("|-----|--------|-------:|---:|--:|-------:|--------:|")
for blabel, _, _ in ADX_BUCKETS:
    for wname, _ in WINDOWS:
        arr = np.array(up_adx_returns[blabel][wname])
        if len(arr) == 0:
            continue
        m, s, t, pv = t_test(arr)
        wr = 100 * np.sum(arr > 0) / len(arr)
        flag = " **" if m > 0.20 and pv < 0.10 else ""
        if m > 0.20 and pv < 0.10:
            flagged_cells.append(("UP", blabel, wname, m, pv))
        p(f"| {blabel} | {wname} | {m:+.3f} | {wr:.1f}% | {len(arr)} | {t:+.2f} | {pv:.4f} |{flag}")
p()

# ADX heat map
p("### ADX x Window Heat Map (UP Cross Mean %)")
p()
p("| Window | " + " | ".join(b[0] for b in ADX_BUCKETS) + " |")
p("|--------| " + " | ".join("------:" for _ in ADX_BUCKETS) + " |")
for wname, _ in WINDOWS:
    cells = []
    for blabel, _, _ in ADX_BUCKETS:
        arr = np.array(up_adx_returns[blabel][wname])
        if len(arr) > 0:
            m = np.mean(arr)
            cells.append(f"{m:+.3f}")
        else:
            cells.append("—")
    p(f"| {wname} | " + " | ".join(cells) + " |")
p()

# DOWN Cross overall
p("## 2. Forward Returns After DOWN Cross")
p()
p("Negative return = DOWN cross correctly predicted decline.")
p()
p("| Window | Mean % | Median % | %Neg | Std % | N | t-stat | p-value |")
p("|--------|-------:|--------:|----:|------:|--:|-------:|--------:|")
for wname, _ in WINDOWS:
    arr = np.array(dn_returns[wname])
    if len(arr) == 0:
        continue
    m, s, t, pv = t_test(arr)
    pct_neg = 100 * np.sum(arr < 0) / len(arr)
    med = np.median(arr)
    flag = " **" if m < -0.20 and pv < 0.10 else ""
    if m < -0.20 and pv < 0.10:
        flagged_cells.append(("DOWN", "Overall", wname, m, pv))
    p(f"| {wname} | {m:+.3f} | {med:+.3f} | {pct_neg:.1f}% | {s:.3f} | {len(arr)} | {t:+.2f} | {pv:.4f} |{flag}")
p()

# DOWN by ADX
p("### DOWN Cross by ADX Bucket")
p()
p("| ADX | Window | Mean % | %Neg | N | t-stat | p-value |")
p("|-----|--------|-------:|----:|--:|-------:|--------:|")
for blabel, _, _ in ADX_BUCKETS:
    for wname, _ in WINDOWS:
        arr = np.array(dn_adx_returns[blabel][wname])
        if len(arr) == 0:
            continue
        m, s, t, pv = t_test(arr)
        pct_neg = 100 * np.sum(arr < 0) / len(arr)
        flag = " **" if m < -0.20 and pv < 0.10 else ""
        if m < -0.20 and pv < 0.10:
            flagged_cells.append(("DOWN", blabel, wname, m, pv))
        p(f"| {blabel} | {wname} | {m:+.3f} | {pct_neg:.1f}% | {len(arr)} | {t:+.2f} | {pv:.4f} |{flag}")
p()

# DOWN ADX heat map
p("### ADX x Window Heat Map (DOWN Cross Mean %)")
p()
p("| Window | " + " | ".join(b[0] for b in ADX_BUCKETS) + " |")
p("|--------| " + " | ".join("------:" for _ in ADX_BUCKETS) + " |")
for wname, _ in WINDOWS:
    cells = []
    for blabel, _, _ in ADX_BUCKETS:
        arr = np.array(dn_adx_returns[blabel][wname])
        if len(arr) > 0:
            m = np.mean(arr)
            cells.append(f"{m:+.3f}")
        else:
            cells.append("—")
    p(f"| {wname} | " + " | ".join(cells) + " |")
p()

# Random comparison
p("## 3. UP Cross vs Random Entry")
p()
p("| Window | Cross Mean % | Random Mean % | Spread % | t-stat | p-value |")
p("|--------|------------:|-------------:|---------:|-------:|--------:|")
for wname, _ in WINDOWS:
    cross_arr = np.array(up_returns[wname])
    rand_arr = np.array(random_returns[wname])
    if len(cross_arr) == 0 or len(rand_arr) == 0:
        continue
    cross_m = np.mean(cross_arr)
    rand_m = np.mean(rand_arr)
    spread = cross_m - rand_m
    n1, n2 = len(cross_arr), len(rand_arr)
    s1, s2 = np.std(cross_arr, ddof=1), np.std(rand_arr, ddof=1)
    se = sqrt(s1**2 / n1 + s2**2 / n2) if (n1 > 1 and n2 > 1) else 1
    t_val = spread / se if se > 0 else 0
    p_val = p_from_t(t_val, min(n1, n2) - 1)
    p(f"| {wname} | {cross_m:+.3f} | {rand_m:+.3f} | {spread:+.3f} | {t_val:+.2f} | {p_val:.4f} |")
p()

# Flagged cells
p("## 4. Flagged Cells for B3")
p()
if flagged_cells:
    p("Cells with |mean| > 0.20% AND p < 0.10:")
    p()
    p("| Direction | ADX Bucket | Window | Mean % | p-value |")
    p("|-----------|------------|--------|-------:|--------:|")
    for direction, bucket, wname, m, pv in flagged_cells:
        p(f"| {direction} | {bucket} | {wname} | {m:+.3f} | {pv:.4f} |")
    p()
    p("These cells warrant split-sample validation in B3.")
else:
    p("**No cells meet the threshold (|mean| > 0.20% AND p < 0.10).**")
    p()
    p("The 4H cross does NOT produce statistically significant continuation")
    p("returns at any window or ADX bucket. It may function purely as a")
    p("directional filter (permission gate) rather than a return predictor.")
p()

# Best combination
p("## 5. Best Window x ADX Combination")
p()
best_m = 0
best_combo = None
for blabel, _, _ in ADX_BUCKETS:
    for wname, _ in WINDOWS:
        arr = np.array(up_adx_returns[blabel][wname])
        if len(arr) >= 10:
            m = np.mean(arr)
            if m > best_m:
                best_m = m
                _, s, t, pv = t_test(arr)
                wr = 100 * np.sum(arr > 0) / len(arr)
                best_combo = (blabel, wname, m, wr, len(arr), t, pv)

if best_combo:
    bl, wn, m, wr, n, t, pv = best_combo
    p(f"**Best UP cross cell:** ADX {bl} × {wn}")
    p(f"  - Mean: {m:+.3f}%, WR: {wr:.1f}%, N={n}, t={t:+.2f}, p={pv:.4f}")
    viable = m > 0.20 and pv < 0.10
    p(f"  - Meets threshold (>0.20%, p<0.10): {'YES' if viable else 'NO'}")
else:
    p("No valid UP cross cells with N >= 10.")
p()

# Verdict
p("## 6. Verdict")
p()
up_close = np.array(up_returns.get("Close", []))
dn_close = np.array(dn_returns.get("Close", []))
if len(up_close) > 0:
    up_m = np.mean(up_close)
    up_wr = 100 * np.sum(up_close > 0) / len(up_close)
    p(f"- UP cross next-day close: mean={up_m:+.3f}%, WR={up_wr:.1f}%")
if len(dn_close) > 0:
    dn_m = np.mean(dn_close)
    dn_neg = 100 * np.sum(dn_close < 0) / len(dn_close)
    p(f"- DOWN cross next-day close: mean={dn_m:+.3f}%, %Neg={dn_neg:.1f}%")
p()

if flagged_cells:
    p("**4H cross shows some predictive continuation. Proceed to B3 for validation.**")
else:
    p("**4H cross does NOT predict meaningful continuation returns.**")
    p("It may still function as a directional FILTER (permission gate) rather than")
    p("a return PREDICTOR. The gate filters direction correctly (UP RSI ~57, DOWN RSI ~42)")
    p("but does not predict the magnitude or reliability of the next session's move.")

# Save
report_path = CONT_DIR / "B2_FORWARD_RETURNS.md"
with open(report_path, "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"\nReport saved: {report_path}")
