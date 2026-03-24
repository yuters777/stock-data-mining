#!/usr/bin/env python3
"""Re-run Audit B2 (Gap-Fill Timing) using FIXED data via load_m5_regsess().

B2 depends on B1 output. B1 originally used _m5_regsess.csv (buggy).
This script re-computes B1 gap-fill data from scratch using load_m5_regsess(),
then runs the B2 timing analysis on the corrected results.

Changes from original:
  - Data source: load_m5_regsess() instead of _m5_regsess.csv
  - B1 gap detection recomputed from clean data
  - B2 timing logic IDENTICAL
"""

import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from utils.data_loader import load_m5_regsess, ALL_TICKERS

AUDIT_RERUN_DIR = os.path.dirname(__file__)

TICKERS = ALL_TICKERS

BUCKETS = [
    ("< 0.30%", 0.0, 0.30),
    ("0.30-0.50%", 0.30, 0.50),
    ("0.50-1.00%", 0.50, 1.00),
    ("1.00-1.50%", 1.00, 1.50),
    ("> 1.50%", 1.50, 1e6),
]


def bucket_for(abs_gap):
    for i, (label, lo, hi) in enumerate(BUCKETS):
        if lo <= abs_gap < hi:
            return i
    return len(BUCKETS) - 1


# ── Step 1: Recompute B1 (gap-fill) from FIXED data ────────────────────────
all_gaps = []

for ticker in TICKERS:
    try:
        df = load_m5_regsess(ticker)
    except (FileNotFoundError, ValueError) as e:
        print(f"SKIP {ticker}: {e}")
        continue

    df["date"] = df["Datetime"].dt.date
    df["hhmm"] = df["Datetime"].dt.strftime("%H:%M")

    dates = sorted(df["date"].unique())

    for i in range(1, len(dates)):
        prev_date = dates[i - 1]
        curr_date = dates[i]

        prev_bars = df[df["date"] == prev_date]
        curr_bars = df[df["date"] == curr_date]

        if prev_bars.empty or curr_bars.empty:
            continue

        prior_close = prev_bars.iloc[-1]["Close"]
        today_open = curr_bars.iloc[0]["Close"]  # 09:30 bar close = open proxy

        if prior_close == 0:
            continue

        gap_pct = (today_open - prior_close) / prior_close * 100
        abs_gap = abs(gap_pct)
        gap_dir = "up" if gap_pct > 0 else "down"
        bucket_idx = bucket_for(abs_gap)
        bucket_label = BUCKETS[bucket_idx][0]

        # Scan for gap fill
        filled = False
        fill_datetime = None
        fill_minutes = None

        for _, bar in curr_bars.iterrows():
            if gap_pct > 0:
                # Gap up: filled when Low <= prior_close
                if bar["Low"] <= prior_close:
                    filled = True
                    fill_datetime = bar["Datetime"]
                    fill_minutes = (bar["Datetime"].hour - 9) * 60 + bar["Datetime"].minute - 30
                    break
            else:
                # Gap down: filled when High >= prior_close
                if bar["High"] >= prior_close:
                    filled = True
                    fill_datetime = bar["Datetime"]
                    fill_minutes = (bar["Datetime"].hour - 9) * 60 + bar["Datetime"].minute - 30
                    break

        all_gaps.append({
            "ticker": ticker,
            "date": str(curr_date),
            "gap_pct": gap_pct,
            "abs_gap": abs_gap,
            "gap_dir": gap_dir,
            "bucket": bucket_label,
            "filled": filled,
            "fill_datetime": fill_datetime,
            "fill_minutes": fill_minutes,
        })

total_gaps = len(all_gaps)
fills = [g for g in all_gaps if g["filled"]]
total_fills = len(fills)

print(f"Total gap-days: {total_gaps}")
print(f"Filled: {total_fills} ({100*total_fills/total_gaps:.1f}%)")

# ── Step 2: B2 timing analysis ─────────────────────────────────────────────
checkpoints = []
for h in range(9, 16):
    for m in (0, 30):
        if h == 9 and m == 0:
            continue
        checkpoints.append(f"{h:02d}:{m:02d}")
checkpoints.append("16:00")

fill_times = []
for g in fills:
    fill_times.append((g["fill_minutes"], g))

lines = []


def p(line=""):
    print(line)
    lines.append(line)


p("=" * 72)
p("AUDIT B2 RE-RUN: GAP-FILL TIMING CURVE (FIXED DATA)")
p("=" * 72)
p(f"Total gap-days: {total_gaps} | Fills: {total_fills}")
p(f"Data source: load_m5_regsess() (IST-block extraction)")
p()

p("CUMULATIVE FILL TIMING (% of ALL fills completed by time):")
p(f"  {'Time':>6} {'Fills_by':>9} {'Cum%_fills':>11} {'Cum%_allgaps':>13}")
p(f"  {'-' * 44}")

cum_data = []
for cp in checkpoints:
    cp_h, cp_m = int(cp[:2]), int(cp[3:])
    cp_mins = (cp_h - 9) * 60 + cp_m - 30

    n_by = sum(1 for m, _ in fill_times if m <= cp_mins)
    pct_fills = 100 * n_by / total_fills if total_fills > 0 else 0
    pct_all = 100 * n_by / total_gaps if total_gaps > 0 else 0

    cum_data.append((cp, n_by, pct_fills, pct_all))
    p(f"  {cp:>6} {n_by:>9} {pct_fills:>10.1f}% {pct_all:>12.1f}%")

p()

# Claims comparison
CLAIMS = [
    ("10:00", 51, 61),
    ("10:30", 66, 72),
    ("13:00", 82, 86),
]

p("COMPARISON WITH CLAIMED RANGES:")
p(f"  {'Time':>6} {'Actual':>8} {'Claimed':>14} {'Match?':>8}")
p(f"  {'-' * 40}")
for cp, lo, hi in CLAIMS:
    actual = next(pf for t, _, pf, _ in cum_data if t == cp)
    in_range = lo <= actual <= hi
    near = abs(actual - lo) <= 10 or abs(actual - hi) <= 10
    match = "YES" if in_range else ("~CLOSE" if near else "NO")
    p(f"  {cp:>6} {actual:>7.1f}% {lo:>5}-{hi}% {match:>8}")

p()

# Fill time distribution
all_mins = [m for m, _ in fill_times]
if all_mins:
    p("FILL TIME DISTRIBUTION (minutes after 09:30 open):")
    p(f"  Mean:   {statistics.mean(all_mins):>6.1f} min")
    p(f"  Median: {statistics.median(all_mins):>6.1f} min")
    sorted_mins = sorted(all_mins)
    p(f"  75th %%: {sorted_mins[3*len(sorted_mins)//4]:>6.1f} min")
    p(f"  90th %%: {sorted_mins[9*len(sorted_mins)//10]:>6.1f} min")
    p()

# By gap-size bucket
p("CUMULATIVE % OF FILLS BY GAP-SIZE BUCKET AT KEY TIMES:")
p(f"  {'Bucket':<14} {'10:00':>7} {'10:30':>7} {'11:00':>7} {'13:00':>7} {'N_fill':>7}")
p(f"  {'-' * 50}")
for bkt_label, _, _ in BUCKETS:
    bkt_fills = [(m, g) for m, g in fill_times if g["bucket"] == bkt_label]
    nf = len(bkt_fills)
    if nf == 0:
        p(f"  {bkt_label:<14} {'--':>7} {'--':>7} {'--':>7} {'--':>7} {0:>7}")
        continue
    vals = {}
    for cp in ["10:00", "10:30", "11:00", "13:00"]:
        cp_h, cp_m = int(cp[:2]), int(cp[3:])
        cp_mins = (cp_h - 9) * 60 + cp_m - 30
        n_by = sum(1 for m, _ in bkt_fills if m <= cp_mins)
        vals[cp] = 100 * n_by / nf
    p(f"  {bkt_label:<14} {vals['10:00']:>6.1f}% {vals['10:30']:>6.1f}% "
      f"{vals['11:00']:>6.1f}% {vals['13:00']:>6.1f}% {nf:>7}")

p()

# By gap direction
p("CUMULATIVE % OF FILLS BY GAP DIRECTION AT KEY TIMES:")
p(f"  {'Direction':<10} {'10:00':>7} {'10:30':>7} {'11:00':>7} {'13:00':>7} {'N_fill':>7}")
p(f"  {'-' * 44}")
for direction in ["up", "down"]:
    dir_fills = [(m, g) for m, g in fill_times if g["gap_dir"] == direction]
    nf = len(dir_fills)
    if nf == 0:
        continue
    vals = {}
    for cp in ["10:00", "10:30", "11:00", "13:00"]:
        cp_h, cp_m = int(cp[:2]), int(cp[3:])
        cp_mins = (cp_h - 9) * 60 + cp_m - 30
        n_by = sum(1 for m, _ in dir_fills if m <= cp_mins)
        vals[cp] = 100 * n_by / nf
    p(f"  {direction:<10} {vals['10:00']:>6.1f}% {vals['10:30']:>6.1f}% "
      f"{vals['11:00']:>6.1f}% {vals['13:00']:>6.1f}% {nf:>7}")

# Overall fill rate by bucket
p()
p("OVERALL FILL RATE BY GAP-SIZE BUCKET:")
p(f"  {'Bucket':<14} {'N_gaps':>7} {'N_fills':>8} {'FillRate':>9}")
p(f"  {'-' * 42}")
for bkt_label, _, _ in BUCKETS:
    bkt_gaps = [g for g in all_gaps if g["bucket"] == bkt_label]
    bkt_fills_n = sum(1 for g in bkt_gaps if g["filled"])
    ng = len(bkt_gaps)
    fr = 100 * bkt_fills_n / ng if ng > 0 else 0
    p(f"  {bkt_label:<14} {ng:>7} {bkt_fills_n:>8} {fr:>8.1f}%")

# Save
stats_path = os.path.join(AUDIT_RERUN_DIR, "B2_RERUN_RESULTS.md")
with open(stats_path, "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"\nSaved: {stats_path}")
