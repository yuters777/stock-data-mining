#!/usr/bin/env python3
"""Audit C2: First-hour width ratio and breakout classification.

For each ticker-day (regular session 09:30–16:00):
  - first_hour_range = max(High 09:30–10:25) - min(Low 09:30–10:25)
  - daily_range       = day_high - day_low
  - width_ratio       = first_hour_range / daily_range
  - Classify: Wide (>0.60), Narrow (<0.30), Medium (0.30–0.60)

For each class, compute breakout type based on bars AFTER 10:30:
  - Double breakout = price later exceeds BOTH first-hour high AND low
  - Single breakout = exceeds one but not both
  - No breakout     = stays within first-hour range

Claim: Wide days have only ~4.8% double breakout.
"""

import csv
import os
import statistics
from collections import defaultdict
from datetime import datetime

FETCHED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "Fetched_Data")
AUDIT_DIR = os.path.dirname(__file__)

TICKERS = sorted(
    f.replace("_data.csv", "")
    for f in os.listdir(FETCHED_DIR)
    if f.endswith("_data.csv") and "crypto" not in f
)


def in_regsess(hhmm):
    """Is this time in regular session [09:30, 16:00)?"""
    return "09:30" <= hhmm < "16:00"


def in_first_hour(hhmm):
    """Is this time in the first hour [09:30, 10:30)?"""
    return "09:30" <= hhmm < "10:30"


# ── Collect data ────────────────────────────────────────────────────────────
rows_out = []

for ticker in TICKERS:
    fpath = os.path.join(FETCHED_DIR, f"{ticker}_data.csv")

    day_bars = defaultdict(list)
    with open(fpath) as f:
        for row in csv.DictReader(f):
            hhmm = row["Datetime"][11:16]
            if in_regsess(hhmm):
                date_str = row["Datetime"][:10]
                day_bars[date_str].append(row)

    for date_str in sorted(day_bars.keys()):
        bars = day_bars[date_str]

        # Split into first-hour and rest-of-day
        fh_bars = [b for b in bars if in_first_hour(b["Datetime"][11:16])]
        rest_bars = [b for b in bars if b["Datetime"][11:16] >= "10:30"]

        if len(fh_bars) < 6 or len(rest_bars) < 2:
            continue

        fh_high = max(float(b["High"]) for b in fh_bars)
        fh_low = min(float(b["Low"]) for b in fh_bars)
        fh_range = fh_high - fh_low

        day_high = max(float(b["High"]) for b in bars)
        day_low = min(float(b["Low"]) for b in bars)
        day_range = day_high - day_low

        if day_range == 0:
            continue

        width_ratio = fh_range / day_range

        # Classify width
        if width_ratio > 0.60:
            width_class = "Wide"
        elif width_ratio < 0.30:
            width_class = "Narrow"
        else:
            width_class = "Medium"

        # Breakout: does rest-of-day exceed first-hour high/low?
        rest_high = max(float(b["High"]) for b in rest_bars)
        rest_low = min(float(b["Low"]) for b in rest_bars)

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
            "fh_high": f"{fh_high:.4f}",
            "fh_low": f"{fh_low:.4f}",
            "fh_range": f"{fh_range:.4f}",
            "day_high": f"{day_high:.4f}",
            "day_low": f"{day_low:.4f}",
            "day_range": f"{day_range:.4f}",
            "width_ratio": f"{width_ratio:.4f}",
            "width_class": width_class,
            "broke_high": "1" if broke_high else "0",
            "broke_low": "1" if broke_low else "0",
            "breakout": breakout,
        })

N = len(rows_out)
print(f"Tickers: {len(TICKERS)} | Ticker-days: {N}")

# ── Save CSV ────────────────────────────────────────────────────────────────
csv_path = os.path.join(AUDIT_DIR, "first_hour_width.csv")
with open(csv_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
    writer.writeheader()
    writer.writerows(rows_out)
print(f"Saved: {csv_path}")

# ── Stats ───────────────────────────────────────────────────────────────────
lines = []


def p(line=""):
    print(line)
    lines.append(line)


p("=" * 72)
p("AUDIT C2: FIRST-HOUR WIDTH RATIO & BREAKOUT CLASSIFICATION")
p("=" * 72)
p(f"Tickers: {len(TICKERS)} | Ticker-days: {N}")
p(f"First hour: 09:30–10:30 ET (12 M5 bars)")
p(f"Breakout detection: bars from 10:30 onward")
p()

# Width ratio distribution
ratios = [float(r["width_ratio"]) for r in rows_out]
p("WIDTH RATIO DISTRIBUTION:")
p(f"  Mean:   {statistics.mean(ratios):.3f}")
p(f"  Median: {statistics.median(ratios):.3f}")
p(f"  Std:    {statistics.stdev(ratios):.3f}")
p()

# Class distribution
classes = ["Narrow", "Medium", "Wide"]
class_rows = {c: [r for r in rows_out if r["width_class"] == c] for c in classes}

p("WIDTH CLASS DISTRIBUTION:")
p(f"  {'Class':<10} {'N':>6} {'%':>7} {'MeanRatio':>10}")
p(f"  {'-' * 36}")
for c in classes:
    n = len(class_rows[c])
    pct = 100 * n / N
    mr = statistics.mean([float(r["width_ratio"]) for r in class_rows[c]]) if n else 0
    p(f"  {c:<10} {n:>6} {pct:>6.1f}% {mr:>10.3f}")
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

# Claim comparison
wide_rows = class_rows["Wide"]
wide_double = sum(1 for r in wide_rows if r["breakout"] == "Double")
wide_n = len(wide_rows)
wide_double_pct = 100 * wide_double / wide_n if wide_n > 0 else 0

p("CLAIM: Wide days have ~4.8% double breakout")
p(f"ACTUAL: {wide_double}/{wide_n} = {wide_double_pct:.1f}%")
diff = abs(wide_double_pct - 4.8)
match = "YES" if diff <= 2 else ("~CLOSE" if diff <= 5 else "NO")
p(f"MATCH: {match} (Δ={wide_double_pct - 4.8:+.1f}pp)")
p()

# Detailed: breakout direction by width class
p("BREAKOUT DIRECTION DETAIL:")
p(f"  {'Class':<10} {'UpOnly':>8} {'DnOnly':>8} {'Both':>8} {'Neither':>8}")
p(f"  {'-' * 46}")
for c in classes:
    cr = class_rows[c]
    n = len(cr)
    if n == 0:
        continue
    up_only = sum(1 for r in cr if r["broke_high"] == "1" and r["broke_low"] == "0")
    dn_only = sum(1 for r in cr if r["broke_low"] == "1" and r["broke_high"] == "0")
    both = sum(1 for r in cr if r["broke_high"] == "1" and r["broke_low"] == "1")
    neither = sum(1 for r in cr if r["broke_high"] == "0" and r["broke_low"] == "0")
    p(f"  {c:<10} {100*up_only/n:>7.1f}% {100*dn_only/n:>7.1f}% "
      f"{100*both/n:>7.1f}% {100*neither/n:>7.1f}%")
p()

# Per-ticker: wide-day double breakout rate
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

# ── Save stats ──────────────────────────────────────────────────────────────
stats_path = os.path.join(AUDIT_DIR, "width_breakout_stats.txt")
with open(stats_path, "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"\nSaved: {stats_path}")
