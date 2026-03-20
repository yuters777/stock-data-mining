#!/usr/bin/env python3
"""Audit H1: Optimal exit time grid for stress-day laggard entries at noon.

For each stress day, identify the bottom 2 tickers by AM return (09:30→12:00),
then compute laggard return from 12:00 entry to various PM exit times.
"""

import csv
import json
import os
from datetime import datetime, time as dtime
from collections import defaultdict
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(SCRIPT_DIR, "..", "..")
OUT = SCRIPT_DIR

# ── Config ────────────────────────────────────────────────────────────────
EXIT_TIMES = [
    dtime(14, 30), dtime(14, 45), dtime(15, 0),
    dtime(15, 15), dtime(15, 30), dtime(15, 45),
]
EXIT_LABELS = ["14:30", "14:45", "15:00", "15:15", "15:30", "15:45"]
NOON = dtime(12, 0)
OPEN = dtime(9, 30)
N_LAGGARDS = 2

# ── Load stress days ──────────────────────────────────────────────────────
with open(os.path.join(ROOT, "backtest_output", "stress_days.json")) as f:
    stress_days = set(json.load(f))

# ── Find all tickers (exclude SPY, VIXY) ─────────────────────────────────
ticker_files = {}
for fname in os.listdir(os.path.join(ROOT, "backtest_output")):
    if fname.endswith("_m5_regsess.csv"):
        ticker = fname.replace("_m5_regsess.csv", "")
        if ticker not in ("SPY", "VIXY"):
            ticker_files[ticker] = os.path.join(ROOT, "backtest_output", fname)

print(f"Tickers: {sorted(ticker_files.keys())} ({len(ticker_files)} total)")
print(f"Stress days: {len(stress_days)}")

# ── Load all ticker M5 data ──────────────────────────────────────────────
# ticker -> date -> list of bars
all_data = {}
for ticker, fpath in ticker_files.items():
    by_date = defaultdict(list)
    with open(fpath) as f:
        for row in csv.DictReader(f):
            dt = datetime.strptime(row["Datetime"], "%Y-%m-%d %H:%M:%S")
            d = dt.strftime("%Y-%m-%d")
            if d not in stress_days:
                continue
            by_date[d].append({
                "time": dt.time(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
            })
    all_data[ticker] = dict(by_date)

# ── For each stress day: find bottom-2 AM laggards, compute PM returns ───
results = []  # list of dicts per trade
skipped = 0

for day in sorted(stress_days):
    # Compute AM return for each ticker
    am_returns = {}
    for ticker, by_date in all_data.items():
        bars = by_date.get(day, [])
        if not bars:
            continue
        # Find open bar (~09:30) and noon bar (~12:00)
        open_bar = None
        noon_bar = None
        for b in bars:
            if b["time"] == OPEN:
                open_bar = b
            if b["time"] == NOON:
                noon_bar = b
        if open_bar and noon_bar:
            am_ret = (noon_bar["open"] - open_bar["open"]) / open_bar["open"]
            am_returns[ticker] = am_ret

    if len(am_returns) < N_LAGGARDS:
        skipped += 1
        continue

    # Bottom 2 by AM return
    sorted_tickers = sorted(am_returns.items(), key=lambda x: x[1])
    laggards = sorted_tickers[:N_LAGGARDS]

    for ticker, am_ret in laggards:
        bars = all_data[ticker][day]
        # Entry price at noon
        noon_bar = None
        for b in bars:
            if b["time"] == NOON:
                noon_bar = b
                break
        if not noon_bar:
            continue
        entry_price = noon_bar["open"]

        # Find exit prices at each target time
        # Use the bar whose time matches or the closest bar before
        bar_by_time = {b["time"]: b for b in bars}
        exit_returns = {}
        for et, label in zip(EXIT_TIMES, EXIT_LABELS):
            # Find exact bar or closest preceding
            exit_bar = bar_by_time.get(et)
            if exit_bar:
                exit_price = exit_bar["close"]
                exit_returns[label] = (exit_price - entry_price) / entry_price
            else:
                # Find closest bar at or before exit time
                candidates = [b for b in bars if b["time"] <= et]
                if candidates:
                    exit_bar = max(candidates, key=lambda b: b["time"])
                    exit_price = exit_bar["close"]
                    exit_returns[label] = (exit_price - entry_price) / entry_price
                else:
                    exit_returns[label] = None

        results.append({
            "date": day,
            "ticker": ticker,
            "am_return": am_ret,
            **exit_returns,
        })

print(f"Total laggard trades: {len(results)}")
print(f"Stress days skipped (insufficient data): {skipped}")

# ── Aggregate ─────────────────────────────────────────────────────────────
print()
print("=" * 80)
print("  AUDIT H1: EXIT TIME GRID — STRESS-DAY LAGGARD MEAN REVERSION")
print("=" * 80)
print(f"\n  Entry: 12:00 ET (noon) | Bottom {N_LAGGARDS} tickers by AM return")
print(f"  Trades: {len(results)} across {len(stress_days)} stress days")
print()

header = f"  {'Exit Time':>10} {'Mean Ret':>10} {'Med Ret':>10} {'Win%':>8} {'N':>5} {'Sharpe':>8} {'Best?':>6}"
print(header)
print(f"  {'-'*60}")

stats_by_exit = {}
for label in EXIT_LABELS:
    rets = np.array([r[label] for r in results if r[label] is not None])
    if len(rets) == 0:
        continue
    mean_r = np.mean(rets)
    med_r = np.median(rets)
    win_pct = 100 * np.mean(rets > 0)
    std_r = np.std(rets)
    sharpe = mean_r / std_r if std_r > 0 else 0
    stats_by_exit[label] = {
        "mean": mean_r, "median": med_r, "win_pct": win_pct,
        "n": len(rets), "std": std_r, "sharpe": sharpe, "rets": rets,
    }

best_label = max(stats_by_exit, key=lambda k: stats_by_exit[k]["mean"])

for label in EXIT_LABELS:
    if label not in stats_by_exit:
        continue
    s = stats_by_exit[label]
    marker = "  <<<" if label == best_label else ""
    print(f"  {label:>10} {s['mean']*100:>+9.3f}% {s['median']*100:>+9.3f}% "
          f"{s['win_pct']:>7.1f}% {s['n']:>5} {s['sharpe']:>+7.3f} {marker}")

print(f"\n  Current rule exit: 15:30 ET")
print(f"  Optimal exit:     {best_label} ET")

current = stats_by_exit.get("15:30", {})
optimal = stats_by_exit.get(best_label, {})
if current and optimal:
    improvement = (optimal["mean"] - current["mean"]) * 100
    if best_label != "15:30":
        print(f"  Improvement:      {improvement:+.3f}% per trade")
    else:
        print(f"  Current rule IS optimal.")

# ── Detailed breakdown ────────────────────────────────────────────────────
print(f"\n{'='*80}")
print(f"  RETURN CURVE PROGRESSION (cumulative from noon)")
print(f"{'='*80}\n")

means = [stats_by_exit[l]["mean"] * 100 for l in EXIT_LABELS if l in stats_by_exit]
for i, label in enumerate(EXIT_LABELS):
    if label not in stats_by_exit:
        continue
    s = stats_by_exit[label]
    bar_len = int(abs(s["mean"]) * 100 * 50)  # scale for display
    direction = "+" if s["mean"] >= 0 else "-"
    bar = "█" * min(bar_len, 50)
    print(f"  {label}  {s['mean']*100:>+.3f}%  {bar}")

# ── P25/P75 by exit time ─────────────────────────────────────────────────
print(f"\n{'='*80}")
print(f"  RISK PROFILE BY EXIT TIME")
print(f"{'='*80}")
print(f"\n  {'Exit':>10} {'P10':>9} {'P25':>9} {'P50':>9} {'P75':>9} {'P90':>9} {'MaxDD':>9}")
print(f"  {'-'*60}")
for label in EXIT_LABELS:
    if label not in stats_by_exit:
        continue
    rets = stats_by_exit[label]["rets"]
    p10, p25, p50, p75, p90 = np.percentile(rets, [10, 25, 50, 75, 90])
    maxdd = np.min(rets)
    print(f"  {label:>10} {p10*100:>+8.2f}% {p25*100:>+8.2f}% {p50*100:>+8.2f}% "
          f"{p75*100:>+8.2f}% {p90*100:>+8.2f}% {maxdd*100:>+8.2f}%")

# ── Chart ─────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(14, 6))
fig.suptitle("Audit H1: Stress-Day Laggard Exit Time Optimization",
             fontsize=14, fontweight="bold")

valid_labels = [l for l in EXIT_LABELS if l in stats_by_exit]
x = np.arange(len(valid_labels))

# Left: Mean return curve
ax = axes[0]
mean_vals = [stats_by_exit[l]["mean"] * 100 for l in valid_labels]
colors = ["#F44336" if l == best_label else "#2196F3" for l in valid_labels]
bars = ax.bar(x, mean_vals, color=colors, edgecolor="black", linewidth=0.5)
ax.plot(x, mean_vals, "ko-", markersize=6, linewidth=2, zorder=5)
ax.axhline(0, color="black", linewidth=0.5)

# Mark current rule
if "15:30" in valid_labels:
    idx_1530 = valid_labels.index("15:30")
    ax.axvline(idx_1530, color="green", linewidth=2, linestyle="--", alpha=0.7,
               label="Current rule (15:30)")
if best_label in valid_labels:
    idx_best = valid_labels.index(best_label)
    ax.axvline(idx_best, color="red", linewidth=2, linestyle="--", alpha=0.7,
               label=f"Optimal ({best_label})")
ax.set_xticks(x)
ax.set_xticklabels(valid_labels)
ax.set_ylabel("Mean Return (%)")
ax.set_xlabel("Exit Time (ET)")
ax.set_title("Mean Return by Exit Time")
ax.legend(fontsize=9)
for bar, v in zip(bars, mean_vals):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
            f"{v:+.3f}%", ha="center",
            va="bottom" if v >= 0 else "top", fontsize=9)

# Right: Box plot of return distributions
ax = axes[1]
data_for_box = [stats_by_exit[l]["rets"] * 100 for l in valid_labels]
bp = ax.boxplot(data_for_box, tick_labels=valid_labels, patch_artist=True,
                showfliers=True, flierprops={"markersize": 3, "alpha": 0.5})
box_colors = ["#FFCDD2" if l == best_label else "#BBDEFB" for l in valid_labels]
for patch, c in zip(bp["boxes"], box_colors):
    patch.set_facecolor(c)
ax.axhline(0, color="black", linewidth=0.5, linestyle="--")
ax.set_ylabel("Return (%)")
ax.set_xlabel("Exit Time (ET)")
ax.set_title("Return Distribution by Exit Time")

plt.tight_layout()
chart_path = os.path.join(OUT, "audit_h1_curve.png")
plt.savefig(chart_path, dpi=150, bbox_inches="tight")
print(f"\nSaved chart: {chart_path}")

# ── Save CSV ──────────────────────────────────────────────────────────────
csv_path = os.path.join(OUT, "audit_h1_exit_grid.csv")
with open(csv_path, "w", newline="") as f:
    fields = ["date", "ticker", "am_return"] + EXIT_LABELS
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    for r in results:
        out = {k: (f"{v:.6f}" if isinstance(v, float) and v is not None else v)
               for k, v in r.items()}
        writer.writerow(out)
print(f"Saved CSV: {csv_path}")
