#!/usr/bin/env python3
"""Re-run Audit C2 (Width Ratio & Breakout) using FIXED data via load_m5_regsess().

This replaces the original naive time filter on raw Fetched_Data/ with the
correct IST-block extraction that produces genuine regular-session bars.

Changes from original:
  - Data source: load_m5_regsess() instead of raw CSV with "09:30" <= hhmm < "16:00"
  - All other logic IDENTICAL
"""

import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

# Add repo root to path for utils import
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from utils.data_loader import load_m5_regsess, ALL_TICKERS

AUDIT_RERUN_DIR = os.path.dirname(__file__)

TICKERS = ALL_TICKERS


def in_first_hour(hhmm):
    return "09:30" <= hhmm < "10:30"


# ── Collect data ────────────────────────────────────────────────────────────
rows_out = []

for ticker in TICKERS:
    try:
        df = load_m5_regsess(ticker)
    except (FileNotFoundError, ValueError) as e:
        print(f"SKIP {ticker}: {e}")
        continue

    df["date"] = df["Datetime"].dt.strftime("%Y-%m-%d")
    df["hhmm"] = df["Datetime"].dt.strftime("%H:%M")

    day_bars = defaultdict(list)
    for _, row in df.iterrows():
        day_bars[row["date"]].append(row)

    for date_str in sorted(day_bars.keys()):
        bars = day_bars[date_str]

        fh_bars = [b for b in bars if in_first_hour(b["hhmm"])]
        rest_bars = [b for b in bars if b["hhmm"] >= "10:30"]

        if len(fh_bars) < 6 or len(rest_bars) < 2:
            continue

        fh_high = max(b["High"] for b in fh_bars)
        fh_low = min(b["Low"] for b in fh_bars)
        fh_range = fh_high - fh_low

        day_high = max(b["High"] for b in bars)
        day_low = min(b["Low"] for b in bars)
        day_range = day_high - day_low

        if day_range == 0:
            continue

        width_ratio = fh_range / day_range

        if width_ratio > 0.60:
            width_class = "Wide"
        elif width_ratio < 0.30:
            width_class = "Narrow"
        else:
            width_class = "Medium"

        rest_high = max(b["High"] for b in rest_bars)
        rest_low = min(b["Low"] for b in rest_bars)

        broke_high = rest_high > fh_high
        broke_low = rest_low < fh_low

        if broke_high and broke_low:
            breakout = "Double"
        elif broke_high or broke_low:
            breakout = "Single"
        else:
            breakout = "None"

        rows_out.append({
            "date": date_str,
            "ticker": ticker,
            "width_ratio": width_ratio,
            "width_class": width_class,
            "breakout": breakout,
        })

N = len(rows_out)
print(f"Tickers: {len(TICKERS)} | Ticker-days: {N}")

# ── Stats ───────────────────────────────────────────────────────────────────
lines = []


def p(line=""):
    print(line)
    lines.append(line)


p("=" * 72)
p("AUDIT C2 RE-RUN: FIRST-HOUR WIDTH RATIO & BREAKOUT (FIXED DATA)")
p("=" * 72)
p(f"Tickers: {len(TICKERS)} | Ticker-days: {N}")
p(f"Data source: load_m5_regsess() (IST-block extraction)")
p()

# Width ratio distribution
ratios = [r["width_ratio"] for r in rows_out]
p("WIDTH RATIO DISTRIBUTION:")
p(f"  Mean:   {statistics.mean(ratios):.3f}")
p(f"  Median: {statistics.median(ratios):.3f}")
p(f"  Std:    {statistics.stdev(ratios):.3f}")
p()

# Class distribution
classes = ["Narrow", "Medium", "Wide"]
class_rows = {c: [r for r in rows_out if r["width_class"] == c] for c in classes}

p("WIDTH CLASS DISTRIBUTION:")
p(f"  {'Class':<10} {'N':>6} {'%':>7}")
p(f"  {'-' * 26}")
for c in classes:
    n = len(class_rows[c])
    pct = 100 * n / N
    p(f"  {c:<10} {n:>6} {pct:>6.1f}%")
p()

# Breakout rates per width class
breakout_types = ["None", "Single", "Double"]
p("BREAKOUT RATES BY WIDTH CLASS:")
p(f"  {'Class':<10} {'N':>6} {'None':>8} {'Single':>8} {'Double':>8}")
p(f"  {'-' * 46}")
for c in classes:
    cr = class_rows[c]
    n = len(cr)
    if n == 0:
        continue
    counts = {bt: sum(1 for r in cr if r["breakout"] == bt) for bt in breakout_types}
    p(f"  {c:<10} {n:>6} {100*counts['None']/n:>7.1f}% "
      f"{100*counts['Single']/n:>7.1f}% {100*counts['Double']/n:>7.1f}%")
p()

# Wide double breakout
wide_rows = class_rows["Wide"]
wide_double = sum(1 for r in wide_rows if r["breakout"] == "Double")
wide_n = len(wide_rows)
wide_double_pct = 100 * wide_double / wide_n if wide_n > 0 else 0

p(f"Wide-day double breakout: {wide_double}/{wide_n} = {wide_double_pct:.1f}%")

# Per-ticker
p()
p("PER-TICKER WIDE-DAY DOUBLE BREAKOUT RATE:")
p(f"  {'Ticker':<8} {'WideN':>6} {'Double':>7} {'Rate':>7}")
p(f"  {'-' * 32}")
for ticker in TICKERS:
    t_wide = [r for r in rows_out if r["ticker"] == ticker and r["width_class"] == "Wide"]
    tw = len(t_wide)
    if tw == 0:
        p(f"  {ticker:<8} {0:>6} {'—':>7} {'—':>7}")
        continue
    td = sum(1 for r in t_wide if r["breakout"] == "Double")
    p(f"  {ticker:<8} {tw:>6} {td:>7} {100*td/tw:>6.1f}%")

# Save
stats_path = os.path.join(AUDIT_RERUN_DIR, "C2_RERUN_RESULTS.md")
with open(stats_path, "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"\nSaved: {stats_path}")
