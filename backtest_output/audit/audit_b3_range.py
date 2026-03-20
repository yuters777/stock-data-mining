#!/usr/bin/env python3
"""Audit B3: Gap-fill rate by open-vs-prior-day-range classification.

For each ticker-day:
  - prior_day_high = max(High) across all prior day's M5 bars
  - prior_day_low  = min(Low)  across all prior day's M5 bars
  - prior_close    = last bar's Close of prior day
  - today_open     = first bar's Open
  - Classify: Inside (low ≤ open ≤ high), Above (open > high), Below (open < low)
  - Fill = any of today's bars cross prior_close (same logic as B1)

Claims: Inside=70.4%, Above=47.1%, Below=44.1%
"""

import csv
import os
import statistics
from collections import defaultdict

BACKTEST_DIR = os.path.join(os.path.dirname(__file__), "..")
AUDIT_DIR = os.path.dirname(__file__)

TICKERS = sorted(
    f.replace("_m5_regsess.csv", "")
    for f in os.listdir(BACKTEST_DIR)
    if f.endswith("_m5_regsess.csv")
)

CLAIMED = {"Inside": 70.4, "Above": 47.1, "Below": 44.1}

# ── Collect data ────────────────────────────────────────────────────────────
rows_out = []

for ticker in TICKERS:
    fpath = os.path.join(BACKTEST_DIR, f"{ticker}_m5_regsess.csv")

    day_bars = defaultdict(list)
    with open(fpath) as f:
        for row in csv.DictReader(f):
            date_str = row["Datetime"][:10]
            day_bars[date_str].append(row)

    dates = sorted(day_bars.keys())

    for i in range(1, len(dates)):
        prev_date = dates[i - 1]
        curr_date = dates[i]

        prev = day_bars[prev_date]
        curr = day_bars[curr_date]
        if not prev or not curr:
            continue

        prior_high = max(float(b["High"]) for b in prev)
        prior_low = min(float(b["Low"]) for b in prev)
        prior_close = float(prev[-1]["Close"])
        today_open = float(curr[0]["Open"])

        if prior_close == 0:
            continue

        # Classify
        if today_open > prior_high:
            category = "Above"
        elif today_open < prior_low:
            category = "Below"
        else:
            category = "Inside"

        gap_pct = (today_open - prior_close) / prior_close * 100
        gap_up = today_open > prior_close

        # Fill: does any bar's range cross prior_close?
        filled = False
        fill_dt = ""
        for bar in curr:
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

        rows_out.append({
            "date": curr_date,
            "ticker": ticker,
            "prior_high": f"{prior_high:.4f}",
            "prior_low": f"{prior_low:.4f}",
            "prior_close": f"{prior_close:.4f}",
            "today_open": f"{today_open:.4f}",
            "gap_pct": f"{gap_pct:.4f}",
            "category": category,
            "filled": "1" if filled else "0",
            "fill_datetime": fill_dt,
        })

print(f"Tickers: {len(TICKERS)} | Gap-days: {len(rows_out)}")

# ── Save CSV ────────────────────────────────────────────────────────────────
csv_path = os.path.join(AUDIT_DIR, "audit_b3_range.csv")
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


cat_data = {}
for cat in ["Inside", "Above", "Below"]:
    subset = [r for r in rows_out if r["category"] == cat]
    n = len(subset)
    n_fill = sum(1 for r in subset if r["filled"] == "1")
    rate = 100 * n_fill / n if n > 0 else 0
    gaps = [abs(float(r["gap_pct"])) for r in subset]
    cat_data[cat] = {"n": n, "n_fill": n_fill, "rate": rate, "gaps": gaps}

p("=" * 72)
p("AUDIT B3: GAP-FILL RATE BY OPEN-VS-PRIOR-DAY-RANGE")
p("=" * 72)
p(f"Tickers: {len(TICKERS)} | Gap-days: {len(rows_out)}")
p(f"Date range: {rows_out[0]['date']} to {rows_out[-1]['date']}")
p()

# Distribution of categories
p("CATEGORY DISTRIBUTION:")
for cat in ["Inside", "Above", "Below"]:
    d = cat_data[cat]
    pct = 100 * d["n"] / len(rows_out)
    mean_gap = statistics.mean(d["gaps"]) if d["gaps"] else 0
    med_gap = statistics.median(d["gaps"]) if d["gaps"] else 0
    p(f"  {cat:<8} {d['n']:>5} ({pct:>5.1f}%)  mean|gap|={mean_gap:.3f}%  median|gap|={med_gap:.3f}%")
p()

# Fill rates
p("FILL RATE BY CATEGORY:")
p(f"  {'Category':<10} {'N':>6} {'Filled':>7} {'Rate':>7} {'Claimed':>8} {'Delta':>7}")
p(f"  {'-' * 50}")
for cat in ["Inside", "Above", "Below"]:
    d = cat_data[cat]
    claimed = CLAIMED[cat]
    delta = d["rate"] - claimed
    p(f"  {cat:<10} {d['n']:>6} {d['n_fill']:>7} {d['rate']:>6.1f}% {claimed:>7.1f}% {delta:>+6.1f}%")
p()

# Overall
total_fill = sum(d["n_fill"] for d in cat_data.values())
p(f"Overall fill rate: {total_fill}/{len(rows_out)} = {100*total_fill/len(rows_out):.1f}%")
p()

# Expected pattern: Inside should have highest fill rate
rates_ordered = [(cat, cat_data[cat]["rate"]) for cat in ["Inside", "Above", "Below"]]
p("Expected pattern: Inside > Above ≈ Below")
p(f"Actual:  {' > '.join(f'{cat}={r:.1f}%' for cat, r in sorted(rates_ordered, key=lambda x: -x[1]))}")
inside_highest = cat_data["Inside"]["rate"] > max(cat_data["Above"]["rate"], cat_data["Below"]["rate"])
p(f"Inside highest? {'YES' if inside_highest else 'NO'}")
p()

# Per-ticker breakdown
p("PER-TICKER FILL RATE BY CATEGORY:")
p(f"  {'Ticker':<8} {'Inside':>10} {'N_i':>5} {'Above':>10} {'N_a':>5} {'Below':>10} {'N_b':>5}")
p(f"  {'-' * 58}")
for ticker in TICKERS:
    t_rows = [r for r in rows_out if r["ticker"] == ticker]
    vals = {}
    for cat in ["Inside", "Above", "Below"]:
        sub = [r for r in t_rows if r["category"] == cat]
        n = len(sub)
        nf = sum(1 for r in sub if r["filled"] == "1")
        vals[cat] = (100 * nf / n if n > 0 else 0, n)
    p(f"  {ticker:<8} {vals['Inside'][0]:>9.1f}% {vals['Inside'][1]:>5} "
      f"{vals['Above'][0]:>9.1f}% {vals['Above'][1]:>5} "
      f"{vals['Below'][0]:>9.1f}% {vals['Below'][1]:>5}")

p()
p("=" * 72)
p("COMPARISON WITH CLAIMED FILL RATES")
p("=" * 72)
p()
for cat in ["Inside", "Above", "Below"]:
    d = cat_data[cat]
    claimed = CLAIMED[cat]
    diff = abs(d["rate"] - claimed)
    match = "~MATCH" if diff <= 10 else "DIFFERS"
    p(f"  {cat:<8} actual={d['rate']:.1f}%  claimed={claimed:.1f}%  Δ={d['rate']-claimed:+.1f}%  {match}")

# ── Save stats ──────────────────────────────────────────────────────────────
stats_path = os.path.join(AUDIT_DIR, "audit_b3_stats.txt")
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

    cats = ["Inside", "Above", "Below"]
    actual = [cat_data[c]["rate"] for c in cats]
    claimed = [CLAIMED[c] for c in cats]
    ns = [cat_data[c]["n"] for c in cats]
    colors_actual = ["#2196F3", "#4CAF50", "#F44336"]
    color_claimed = "#FF9800"

    # Left panel: actual vs claimed
    ax = axes[0]
    x = np.arange(len(cats))
    width = 0.35
    bars1 = ax.bar(x - width / 2, actual, width, label="Actual", color=colors_actual)
    bars2 = ax.bar(x + width / 2, claimed, width, label="Claimed", color=color_claimed, alpha=0.7)
    ax.set_ylabel("Fill Rate (%)")
    ax.set_title("Gap-Fill Rate by Open Position vs Prior Day Range")
    ax.set_xticks(x)
    ax.set_xticklabels(cats)
    ax.legend()
    ax.set_ylim(0, 100)
    for bar, n in zip(bars1, ns):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                f"N={n}", ha="center", va="bottom", fontsize=9)

    # Right panel: per-ticker heatmap-style grouped bars (top 10 by volume of data)
    ax2 = axes[1]
    # Show category distribution as stacked bar
    n_inside = cat_data["Inside"]["n"]
    n_above = cat_data["Above"]["n"]
    n_below = cat_data["Below"]["n"]
    total = len(rows_out)

    # Per-ticker category distribution
    ticker_cats = {}
    for ticker in TICKERS:
        t_rows = [r for r in rows_out if r["ticker"] == ticker]
        nt = len(t_rows)
        if nt == 0:
            continue
        ni = sum(1 for r in t_rows if r["category"] == "Inside")
        na = sum(1 for r in t_rows if r["category"] == "Above")
        nb = sum(1 for r in t_rows if r["category"] == "Below")
        ticker_cats[ticker] = (100 * ni / nt, 100 * na / nt, 100 * nb / nt)

    tickers_sorted = sorted(ticker_cats.keys(), key=lambda t: ticker_cats[t][0], reverse=True)
    y_pos = np.arange(len(tickers_sorted))

    inside_pcts = [ticker_cats[t][0] for t in tickers_sorted]
    above_pcts = [ticker_cats[t][1] for t in tickers_sorted]
    below_pcts = [ticker_cats[t][2] for t in tickers_sorted]

    ax2.barh(y_pos, inside_pcts, 0.7, label="Inside", color="#2196F3", alpha=0.8)
    ax2.barh(y_pos, above_pcts, 0.7, left=inside_pcts, label="Above", color="#4CAF50", alpha=0.8)
    lefts = [i + a for i, a in zip(inside_pcts, above_pcts)]
    ax2.barh(y_pos, below_pcts, 0.7, left=lefts, label="Below", color="#F44336", alpha=0.8)

    ax2.set_yticks(y_pos)
    ax2.set_yticklabels(tickers_sorted, fontsize=8)
    ax2.set_xlabel("% of Days")
    ax2.set_title("Category Distribution by Ticker")
    ax2.legend(loc="lower right", fontsize=8)
    ax2.set_xlim(0, 100)
    ax2.invert_yaxis()

    plt.tight_layout()
    chart_path = os.path.join(AUDIT_DIR, "audit_b3_chart.png")
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    print(f"Saved: {chart_path}")

except ImportError:
    print("matplotlib not available — chart skipped")
