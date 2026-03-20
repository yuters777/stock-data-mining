#!/usr/bin/env python3
"""Audit C1: Opening-range spike — does the first 30 min set the day's extreme?

For each ticker-day:
  - first30_high = max(High) of bars 09:30–09:55 (6 bars covering 09:30–10:00)
  - first30_low  = min(Low)  of bars 09:30–09:55
  - day_high     = max(High) of all bars
  - day_low      = min(Low)  of all bars
  - hi_match = first30_high >= day_high * 0.9995  (within 0.05%)
  - lo_match = first30_low  <= day_low  * 1.0005
  - spike = hi_match OR lo_match

Claim: ~30-34% of days.
"""

import csv
import os
import statistics
from collections import defaultdict
from datetime import datetime

BACKTEST_DIR = os.path.join(os.path.dirname(__file__), "..")
AUDIT_DIR = os.path.dirname(__file__)

TICKERS = sorted(
    f.replace("_m5_regsess.csv", "")
    for f in os.listdir(BACKTEST_DIR)
    if f.endswith("_m5_regsess.csv")
)

# ── Collect data ────────────────────────────────────────────────────────────
rows_out = []

for ticker in TICKERS:
    fpath = os.path.join(BACKTEST_DIR, f"{ticker}_m5_regsess.csv")

    day_bars = defaultdict(list)
    with open(fpath) as f:
        for row in csv.DictReader(f):
            date_str = row["Datetime"][:10]
            day_bars[date_str].append(row)

    for date_str in sorted(day_bars.keys()):
        bars = day_bars[date_str]
        if len(bars) < 6:
            continue

        # First 30 min: bars at 09:30, 09:35, 09:40, 09:45, 09:50, 09:55
        first30 = []
        for b in bars:
            dt = datetime.strptime(b["Datetime"], "%Y-%m-%d %H:%M:%S")
            if dt.hour == 9 and dt.minute < 60:
                first30.append(b)
            if dt.hour >= 10:
                break
        # Filter to only bars before 10:00
        first30 = [b for b in first30
                    if datetime.strptime(b["Datetime"], "%Y-%m-%d %H:%M:%S").hour == 9]

        if not first30:
            continue

        first30_high = max(float(b["High"]) for b in first30)
        first30_low = min(float(b["Low"]) for b in first30)
        day_high = max(float(b["High"]) for b in bars)
        day_low = min(float(b["Low"]) for b in bars)

        if day_high == 0 or day_low == 0:
            continue

        hi_match = first30_high >= day_high * 0.9995
        lo_match = first30_low <= day_low * 1.0005
        spike = hi_match or lo_match

        # Also track: both match, and exact match
        both_match = hi_match and lo_match
        hi_exact = first30_high >= day_high
        lo_exact = first30_low <= day_low

        rows_out.append({
            "date": date_str,
            "ticker": ticker,
            "first30_high": f"{first30_high:.4f}",
            "first30_low": f"{first30_low:.4f}",
            "day_high": f"{day_high:.4f}",
            "day_low": f"{day_low:.4f}",
            "hi_match": "1" if hi_match else "0",
            "lo_match": "1" if lo_match else "0",
            "spike": "1" if spike else "0",
            "both_match": "1" if both_match else "0",
            "hi_exact": "1" if hi_exact else "0",
            "lo_exact": "1" if lo_exact else "0",
        })

N = len(rows_out)
print(f"Tickers: {len(TICKERS)} | Ticker-days: {N}")

# ── Save CSV ────────────────────────────────────────────────────────────────
csv_path = os.path.join(AUDIT_DIR, "audit_c1_opening_spike.csv")
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


n_spike = sum(1 for r in rows_out if r["spike"] == "1")
n_hi = sum(1 for r in rows_out if r["hi_match"] == "1")
n_lo = sum(1 for r in rows_out if r["lo_match"] == "1")
n_both = sum(1 for r in rows_out if r["both_match"] == "1")
n_hi_exact = sum(1 for r in rows_out if r["hi_exact"] == "1")
n_lo_exact = sum(1 for r in rows_out if r["lo_exact"] == "1")

p("=" * 72)
p("AUDIT C1: OPENING-RANGE SPIKE (FIRST 30 MIN SETS DAY EXTREME)")
p("=" * 72)
p(f"Tickers: {len(TICKERS)} | Ticker-days: {N}")
p(f"Tolerance: 0.05% (hi_match if first30_high >= day_high * 0.9995)")
p()

p("AGGREGATE RESULTS:")
p(f"  hi_match (first30 ~ day high): {n_hi:>5} / {N} = {100*n_hi/N:.1f}%")
p(f"  lo_match (first30 ~ day low):  {n_lo:>5} / {N} = {100*n_lo/N:.1f}%")
p(f"  spike (hi OR lo):              {n_spike:>5} / {N} = {100*n_spike/N:.1f}%")
p(f"  both (hi AND lo):              {n_both:>5} / {N} = {100*n_both/N:.1f}%")
p()
p(f"  hi_exact (first30_high = day_high): {n_hi_exact:>5} / {N} = {100*n_hi_exact/N:.1f}%")
p(f"  lo_exact (first30_low  = day_low):  {n_lo_exact:>5} / {N} = {100*n_lo_exact/N:.1f}%")
p()

p(f"CLAIM: ~30-34%")
p(f"ACTUAL: {100*n_spike/N:.1f}%")
in_range = 30 <= 100 * n_spike / N <= 34
close = abs(100 * n_spike / N - 32) <= 10
match = "YES — within claimed range" if in_range else ("~CLOSE" if close else "NO")
p(f"MATCH: {match}")
p()

# ── Per-ticker breakdown ────────────────────────────────────────────────────
p("PER-TICKER SPIKE RATE (hi OR lo):")
p(f"  {'Ticker':<8} {'N':>5} {'Spike':>6} {'Rate':>7} {'HiOnly':>7} {'LoOnly':>7} {'Both':>6}")
p(f"  {'-' * 52}")
for ticker in TICKERS:
    t_rows = [r for r in rows_out if r["ticker"] == ticker]
    nt = len(t_rows)
    ns = sum(1 for r in t_rows if r["spike"] == "1")
    nh = sum(1 for r in t_rows if r["hi_match"] == "1" and r["lo_match"] == "0")
    nl = sum(1 for r in t_rows if r["lo_match"] == "1" and r["hi_match"] == "0")
    nb = sum(1 for r in t_rows if r["both_match"] == "1")
    p(f"  {ticker:<8} {nt:>5} {ns:>6} {100*ns/nt:>6.1f}% {100*nh/nt:>6.1f}% {100*nl/nt:>6.1f}% {100*nb/nt:>5.1f}%")

p()

# ── Day-of-week ─────────────────────────────────────────────────────────────
p("DAY-OF-WEEK SPIKE RATE:")
dow_data = defaultdict(lambda: [0, 0])
for r in rows_out:
    dt = datetime.strptime(r["date"], "%Y-%m-%d")
    dow = dt.strftime("%A")
    dow_data[dow][0] += 1
    if r["spike"] == "1":
        dow_data[dow][1] += 1

p(f"  {'Day':<12} {'N':>5} {'Spike':>6} {'Rate':>7}")
p(f"  {'-' * 34}")
for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
    if day in dow_data:
        n, s = dow_data[day]
        p(f"  {day:<12} {n:>5} {s:>6} {100*s/n:>6.1f}%")

# ── Save stats ──────────────────────────────────────────────────────────────
stats_path = os.path.join(AUDIT_DIR, "audit_c1_stats.txt")
with open(stats_path, "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"\nSaved: {stats_path}")
