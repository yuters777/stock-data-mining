#!/usr/bin/env python3
"""Audit B1: Overnight gap-fill analysis.

For each ticker × each trading day:
  1. prior_close = last Close of prior day's regular-session data
  2. today_open  = Close of today's 09:30 bar (first bar)
  3. gap_pct     = (today_open - prior_close) / prior_close * 100
  4. Scan today's M5 bars: does any bar's Low-High range cross prior_close?
     If yes → gap filled. Record the fill bar's Datetime.
  5. Bucket by |gap_pct|: <0.30%, 0.30-0.50%, 0.50-1.00%, 1.00-1.50%, >1.50%

Claimed fill rates: ~75%, ~58%, ~48%, ~29%, ~20%
"""

import csv
import math
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

BUCKETS = [
    ("< 0.30%", 0.0, 0.30),
    ("0.30–0.50%", 0.30, 0.50),
    ("0.50–1.00%", 0.50, 1.00),
    ("1.00–1.50%", 1.00, 1.50),
    ("> 1.50%", 1.50, 1e6),
]

CLAIMED_RATES = [75, 58, 48, 29, 20]


def bucket_for(abs_gap):
    for i, (label, lo, hi) in enumerate(BUCKETS):
        if lo <= abs_gap < hi:
            return i
    return len(BUCKETS) - 1


# ── Collect gap-fill data ───────────────────────────────────────────────────
rows_out = []

for ticker in TICKERS:
    fpath = os.path.join(BACKTEST_DIR, f"{ticker}_m5_regsess.csv")

    # Load all bars grouped by date
    day_bars = defaultdict(list)
    with open(fpath) as f:
        for row in csv.DictReader(f):
            date_str = row["Datetime"][:10]
            day_bars[date_str].append(row)

    dates = sorted(day_bars.keys())

    for i in range(1, len(dates)):
        prev_date = dates[i - 1]
        curr_date = dates[i]

        prev_bars = day_bars[prev_date]
        curr_bars = day_bars[curr_date]

        if not prev_bars or not curr_bars:
            continue

        prior_close = float(prev_bars[-1]["Close"])
        today_open = float(curr_bars[0]["Close"])  # close of 09:30 bar

        if prior_close == 0:
            continue

        gap_pct = (today_open - prior_close) / prior_close * 100

        # Scan for fill: does any bar's range cross prior_close?
        filled = False
        fill_dt = ""
        gap_up = today_open > prior_close

        for bar in curr_bars:
            lo = float(bar["Low"])
            hi = float(bar["High"])
            if gap_up and lo <= prior_close:
                filled = True
                fill_dt = bar["Datetime"]
                break
            elif not gap_up and hi >= prior_close:
                filled = True
                fill_dt = bar["Datetime"]
                break

        abs_gap = abs(gap_pct)
        bucket_idx = bucket_for(abs_gap)

        rows_out.append({
            "date": curr_date,
            "ticker": ticker,
            "prior_close": f"{prior_close:.4f}",
            "today_open": f"{today_open:.4f}",
            "gap_pct": f"{gap_pct:.4f}",
            "abs_gap_pct": f"{abs_gap:.4f}",
            "gap_dir": "up" if gap_up else "down",
            "bucket": BUCKETS[bucket_idx][0],
            "filled": "1" if filled else "0",
            "fill_datetime": fill_dt,
        })

print(f"Tickers: {len(TICKERS)} ({', '.join(TICKERS)})")
print(f"Total gap-days: {len(rows_out)}")

# ── Save CSV ────────────────────────────────────────────────────────────────
csv_path = os.path.join(AUDIT_DIR, "audit_b1_gap_fill.csv")
with open(csv_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
    writer.writeheader()
    writer.writerows(rows_out)
print(f"Saved: {csv_path}")

# ── Compute fill rates per bucket ──────────────────────────────────────────
bucket_counts = [0] * len(BUCKETS)
bucket_fills = [0] * len(BUCKETS)

for row in rows_out:
    idx = bucket_for(float(row["abs_gap_pct"]))
    bucket_counts[idx] += 1
    if row["filled"] == "1":
        bucket_fills[idx] += 1

lines = []


def p(line=""):
    print(line)
    lines.append(line)


p("=" * 72)
p("AUDIT B1: OVERNIGHT GAP-FILL ANALYSIS")
p("=" * 72)
p(f"Tickers: {len(TICKERS)} | Gap-days: {len(rows_out)}")
p(f"Date range: {rows_out[0]['date']} to {rows_out[-1]['date']}")
p()

# Overall stats
total_filled = sum(1 for r in rows_out if r["filled"] == "1")
overall_rate = 100 * total_filled / len(rows_out)
all_gaps = [float(r["gap_pct"]) for r in rows_out]
p(f"Overall fill rate: {total_filled}/{len(rows_out)} = {overall_rate:.1f}%")
p(f"Mean |gap|: {statistics.mean([abs(g) for g in all_gaps]):.3f}%")
p(f"Median |gap|: {statistics.median([abs(g) for g in all_gaps]):.3f}%")
p()

# Gap direction breakdown
up_gaps = [r for r in rows_out if r["gap_dir"] == "up"]
dn_gaps = [r for r in rows_out if r["gap_dir"] == "down"]
up_fill = sum(1 for r in up_gaps if r["filled"] == "1")
dn_fill = sum(1 for r in dn_gaps if r["filled"] == "1")
p(f"Gap-up:   {len(up_gaps):>5} days, fill rate {100*up_fill/len(up_gaps):.1f}%")
p(f"Gap-down: {len(dn_gaps):>5} days, fill rate {100*dn_fill/len(dn_gaps):.1f}%")
p()

# Fill rate per bucket — comparison with claimed rates
p("FILL RATE BY GAP SIZE:")
p(f"  {'Bucket':<14} {'N':>6} {'Filled':>7} {'Rate':>7} {'Claimed':>8} {'Delta':>7}")
p(f"  {'-' * 55}")
for i, (label, lo, hi) in enumerate(BUCKETS):
    n = bucket_counts[i]
    f_count = bucket_fills[i]
    rate = 100 * f_count / n if n > 0 else 0
    claimed = CLAIMED_RATES[i]
    delta = rate - claimed
    p(f"  {label:<14} {n:>6} {f_count:>7} {rate:>6.1f}% {claimed:>7}% {delta:>+6.1f}%")

p()

# Fill time analysis — how quickly do gaps fill?
fill_bars = []
for row in rows_out:
    if row["filled"] == "1" and row["fill_datetime"]:
        dt = datetime.strptime(row["fill_datetime"], "%Y-%m-%d %H:%M:%S")
        open_dt = datetime.strptime(f"{row['date']} 09:30:00", "%Y-%m-%d %H:%M:%S")
        minutes = (dt - open_dt).total_seconds() / 60
        fill_bars.append(minutes)

p("FILL TIMING (minutes after open, for filled gaps only):")
p(f"  Mean:   {statistics.mean(fill_bars):>6.1f} min")
p(f"  Median: {statistics.median(fill_bars):>6.1f} min")
p(f"  25th %%: {sorted(fill_bars)[len(fill_bars)//4]:>6.1f} min")
p(f"  75th %%: {sorted(fill_bars)[3*len(fill_bars)//4]:>6.1f} min")
p()

# Fill rate within first 30 min, 60 min, 120 min
for cutoff in [30, 60, 120, 390]:
    n_fill = sum(1 for m in fill_bars if m <= cutoff)
    label = f"≤{cutoff}min" if cutoff < 390 else "full day"
    p(f"  Filled {label}: {n_fill}/{len(rows_out)} = {100*n_fill/len(rows_out):.1f}%")
p()

# Per-ticker fill rates
p("PER-TICKER FILL RATE:")
p(f"  {'Ticker':<8} {'N':>5} {'Filled':>7} {'Rate':>7} {'Mean|Gap|':>10}")
p(f"  {'-' * 42}")
for ticker in TICKERS:
    t_rows = [r for r in rows_out if r["ticker"] == ticker]
    t_fill = sum(1 for r in t_rows if r["filled"] == "1")
    t_gaps = [abs(float(r["gap_pct"])) for r in t_rows]
    t_rate = 100 * t_fill / len(t_rows) if t_rows else 0
    t_mean = statistics.mean(t_gaps) if t_gaps else 0
    p(f"  {ticker:<8} {len(t_rows):>5} {t_fill:>7} {t_rate:>6.1f}% {t_mean:>9.3f}%")

p()
p("=" * 72)
p("COMPARISON WITH CLAIMED FILL RATES")
p("=" * 72)
p()
p(f"  {'Bucket':<14} {'Actual':>8} {'Claimed':>8} {'Match?':>8}")
p(f"  {'-' * 42}")
for i, (label, _, _) in enumerate(BUCKETS):
    n = bucket_counts[i]
    rate = 100 * bucket_fills[i] / n if n > 0 else 0
    claimed = CLAIMED_RATES[i]
    diff = abs(rate - claimed)
    match = "~YES" if diff <= 10 else "NO"
    p(f"  {label:<14} {rate:>7.1f}% {claimed:>7}% {match:>8}")

p()
# Monotonicity check: fill rate should decrease as gap size increases
rates = [100 * bucket_fills[i] / bucket_counts[i] if bucket_counts[i] > 0 else 0
         for i in range(len(BUCKETS))]
monotonic = all(rates[i] >= rates[i + 1] for i in range(len(rates) - 1))
p(f"Monotonicity (fill rate ↓ as gap ↑): {'YES' if monotonic else 'NO'}")
p(f"Rate sequence: {' > '.join(f'{r:.1f}%' for r in rates)}")

# ── Save stats ──────────────────────────────────────────────────────────────
stats_path = os.path.join(AUDIT_DIR, "audit_b1_stats.txt")
with open(stats_path, "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"\nSaved: {stats_path}")

# ── Chart ───────────────────────────────────────────────────────────────────
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Left: fill rate comparison
    ax = axes[0]
    x = np.arange(len(BUCKETS))
    width = 0.35
    actual_rates = [100 * bucket_fills[i] / bucket_counts[i] if bucket_counts[i] > 0 else 0
                    for i in range(len(BUCKETS))]
    bars1 = ax.bar(x - width / 2, actual_rates, width, label="Actual", color="#2196F3")
    bars2 = ax.bar(x + width / 2, CLAIMED_RATES, width, label="Claimed", color="#FF9800", alpha=0.7)

    ax.set_xlabel("|Gap| Bucket")
    ax.set_ylabel("Fill Rate (%)")
    ax.set_title("Gap-Fill Rate: Actual vs Claimed")
    ax.set_xticks(x)
    ax.set_xticklabels([b[0] for b in BUCKETS], rotation=15, ha="right")
    ax.legend()
    ax.set_ylim(0, 100)

    # Add N labels on bars
    for bar, n in zip(bars1, bucket_counts):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                f"N={n}", ha="center", va="bottom", fontsize=8)

    # Right: fill rate by gap direction per bucket
    ax2 = axes[1]
    up_rates = []
    dn_rates = []
    up_ns = []
    dn_ns = []
    for i in range(len(BUCKETS)):
        lo, hi = BUCKETS[i][1], BUCKETS[i][2]
        up_in = [r for r in rows_out if r["gap_dir"] == "up" and lo <= float(r["abs_gap_pct"]) < hi]
        dn_in = [r for r in rows_out if r["gap_dir"] == "down" and lo <= float(r["abs_gap_pct"]) < hi]
        up_f = sum(1 for r in up_in if r["filled"] == "1")
        dn_f = sum(1 for r in dn_in if r["filled"] == "1")
        up_rates.append(100 * up_f / len(up_in) if up_in else 0)
        dn_rates.append(100 * dn_f / len(dn_in) if dn_in else 0)
        up_ns.append(len(up_in))
        dn_ns.append(len(dn_in))

    bars_up = ax2.bar(x - width / 2, up_rates, width, label="Gap-Up", color="#4CAF50")
    bars_dn = ax2.bar(x + width / 2, dn_rates, width, label="Gap-Down", color="#F44336")
    ax2.set_xlabel("|Gap| Bucket")
    ax2.set_ylabel("Fill Rate (%)")
    ax2.set_title("Fill Rate by Gap Direction")
    ax2.set_xticks(x)
    ax2.set_xticklabels([b[0] for b in BUCKETS], rotation=15, ha="right")
    ax2.legend()
    ax2.set_ylim(0, 100)

    for bar, n in zip(bars_up, up_ns):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                 f"{n}", ha="center", va="bottom", fontsize=7)
    for bar, n in zip(bars_dn, dn_ns):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                 f"{n}", ha="center", va="bottom", fontsize=7)

    plt.tight_layout()
    chart_path = os.path.join(AUDIT_DIR, "audit_b1_gap_chart.png")
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    print(f"Saved: {chart_path}")

except ImportError:
    print("matplotlib not available — chart skipped")
