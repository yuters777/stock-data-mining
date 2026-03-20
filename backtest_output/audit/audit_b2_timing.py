#!/usr/bin/env python3
"""Audit B2: Gap-fill timing curve.

Loads B1 output and computes: of all gaps that fill, what cumulative
fraction completed by each 30-min checkpoint (10:00, 10:30, ... 16:00)?

Claims: 51-61% by 10:00, 66-72% by 10:30, 82-86% by 13:00.
"""

import csv
import os
import statistics
from collections import defaultdict
from datetime import datetime

AUDIT_DIR = os.path.dirname(__file__)

# ── Load B1 data ────────────────────────────────────────────────────────────
b1_path = os.path.join(AUDIT_DIR, "audit_b1_gap_fill.csv")
with open(b1_path) as f:
    all_rows = list(csv.DictReader(f))

fills = [r for r in all_rows if r["filled"] == "1" and r["fill_datetime"]]
total_gaps = len(all_rows)
total_fills = len(fills)

print(f"Total gap-days: {total_gaps}")
print(f"Filled: {total_fills} ({100*total_fills/total_gaps:.1f}%)")

# ── Compute fill times ─────────────────────────────────────────────────────
# Checkpoints every 30 min from 09:30 to 16:00
checkpoints = []
for h in range(9, 16):
    for m in (0, 30):
        if h == 9 and m == 0:
            continue  # skip 09:00
        checkpoints.append(f"{h:02d}:{m:02d}")
checkpoints.append("16:00")

# For each fill, compute minutes after 09:30 and the fill time
fill_times = []  # (time_str HH:MM, minutes_after_open)
for r in fills:
    dt = datetime.strptime(r["fill_datetime"], "%Y-%m-%d %H:%M:%S")
    fill_hhmm = f"{dt.hour:02d}:{dt.minute:02d}"
    mins = (dt.hour - 9) * 60 + dt.minute - 30
    fill_times.append((fill_hhmm, mins, r))

# ── Cumulative fill at each checkpoint ──────────────────────────────────────
rows_out = []
lines = []


def p(line=""):
    print(line)
    lines.append(line)


p("=" * 72)
p("AUDIT B2: GAP-FILL TIMING CURVE")
p("=" * 72)
p(f"Total gap-days: {total_gaps} | Fills: {total_fills}")
p()

# Cumulative: how many fills completed by each checkpoint?
p("CUMULATIVE FILL TIMING (% of ALL fills completed by time):")
p(f"  {'Time':>6} {'Fills_by':>9} {'Cum%_fills':>11} {'Cum%_allgaps':>13}")
p(f"  {'-' * 44}")

cum_data = []
for cp in checkpoints:
    cp_h, cp_m = int(cp[:2]), int(cp[3:])
    cp_mins = (cp_h - 9) * 60 + cp_m - 30

    n_by = sum(1 for _, m, _ in fill_times if m <= cp_mins)
    pct_fills = 100 * n_by / total_fills if total_fills > 0 else 0
    pct_all = 100 * n_by / total_gaps if total_gaps > 0 else 0

    cum_data.append((cp, n_by, pct_fills, pct_all))
    p(f"  {cp:>6} {n_by:>9} {pct_fills:>10.1f}% {pct_all:>12.1f}%")

    rows_out.append({
        "checkpoint": cp,
        "fills_by": n_by,
        "cum_pct_of_fills": f"{pct_fills:.2f}",
        "cum_pct_of_all_gaps": f"{pct_all:.2f}",
    })

p()

# ── Compare with claims ────────────────────────────────────────────────────
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

# ── Descriptive stats on fill time ──────────────────────────────────────────
all_mins = [m for _, m, _ in fill_times]
p("FILL TIME DISTRIBUTION (minutes after 09:30 open):")
p(f"  Mean:   {statistics.mean(all_mins):>6.1f} min")
p(f"  Median: {statistics.median(all_mins):>6.1f} min")
sorted_mins = sorted(all_mins)
p(f"  10th %%: {sorted_mins[len(sorted_mins)//10]:>6.1f} min")
p(f"  25th %%: {sorted_mins[len(sorted_mins)//4]:>6.1f} min")
p(f"  75th %%: {sorted_mins[3*len(sorted_mins)//4]:>6.1f} min")
p(f"  90th %%: {sorted_mins[9*len(sorted_mins)//10]:>6.1f} min")
p()

# ── By gap-size bucket ──────────────────────────────────────────────────────
buckets = ["< 0.30%", "0.30–0.50%", "0.50–1.00%", "1.00–1.50%", "> 1.50%"]
p("CUMULATIVE % OF FILLS BY GAP-SIZE BUCKET AT KEY TIMES:")
p(f"  {'Bucket':<14} {'10:00':>7} {'10:30':>7} {'11:00':>7} {'13:00':>7} {'N_fill':>7}")
p(f"  {'-' * 50}")
for bkt in buckets:
    bkt_fills = [(hhmm, m, r) for hhmm, m, r in fill_times if r["bucket"] == bkt]
    nf = len(bkt_fills)
    if nf == 0:
        p(f"  {bkt:<14} {'—':>7} {'—':>7} {'—':>7} {'—':>7} {0:>7}")
        continue
    vals = {}
    for cp in ["10:00", "10:30", "11:00", "13:00"]:
        cp_h, cp_m = int(cp[:2]), int(cp[3:])
        cp_mins = (cp_h - 9) * 60 + cp_m - 30
        n_by = sum(1 for _, m, _ in bkt_fills if m <= cp_mins)
        vals[cp] = 100 * n_by / nf
    p(f"  {bkt:<14} {vals['10:00']:>6.1f}% {vals['10:30']:>6.1f}% "
      f"{vals['11:00']:>6.1f}% {vals['13:00']:>6.1f}% {nf:>7}")

p()

# ── By gap direction ────────────────────────────────────────────────────────
p("CUMULATIVE % OF FILLS BY GAP DIRECTION AT KEY TIMES:")
p(f"  {'Direction':<10} {'10:00':>7} {'10:30':>7} {'11:00':>7} {'13:00':>7} {'N_fill':>7}")
p(f"  {'-' * 44}")
for direction in ["up", "down"]:
    dir_fills = [(hhmm, m, r) for hhmm, m, r in fill_times if r["gap_dir"] == direction]
    nf = len(dir_fills)
    if nf == 0:
        continue
    vals = {}
    for cp in ["10:00", "10:30", "11:00", "13:00"]:
        cp_h, cp_m = int(cp[:2]), int(cp[3:])
        cp_mins = (cp_h - 9) * 60 + cp_m - 30
        n_by = sum(1 for _, m, _ in dir_fills if m <= cp_mins)
        vals[cp] = 100 * n_by / nf
    p(f"  {direction:<10} {vals['10:00']:>6.1f}% {vals['10:30']:>6.1f}% "
      f"{vals['11:00']:>6.1f}% {vals['13:00']:>6.1f}% {nf:>7}")

# ── Save ────────────────────────────────────────────────────────────────────
csv_path = os.path.join(AUDIT_DIR, "audit_b2_timing.csv")
with open(csv_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
    writer.writeheader()
    writer.writerows(rows_out)
print(f"\nSaved: {csv_path}")

stats_path = os.path.join(AUDIT_DIR, "audit_b2_stats.txt")
with open(stats_path, "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"Saved: {stats_path}")

# ── Chart ───────────────────────────────────────────────────────────────────
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Left: cumulative timing curve
    ax = axes[0]
    times_numeric = []
    cum_pcts = []
    for cp, _, pf, _ in cum_data:
        h, m = int(cp[:2]), int(cp[3:])
        times_numeric.append(h + m / 60)
        cum_pcts.append(pf)

    ax.plot(times_numeric, cum_pcts, "o-", color="#2196F3", linewidth=2, markersize=5, label="Actual")

    # Shade claimed ranges
    for cp_str, lo, hi in CLAIMS:
        h, m = int(cp_str[:2]), int(cp_str[3:])
        x = h + m / 60
        ax.axhspan(lo, hi, xmin=0, xmax=1, alpha=0.08, color="#FF9800")
        ax.plot([x, x], [lo, hi], "|-", color="#FF9800", linewidth=3, markersize=10)
        ax.annotate(f"Claimed\n{lo}-{hi}%", (x + 0.1, (lo + hi) / 2),
                    fontsize=7, color="#E65100", va="center")

    ax.set_xlabel("Time (ET)")
    ax.set_ylabel("Cumulative % of Fills")
    ax.set_title("Gap-Fill Timing: Cumulative Curve")
    ax.set_xlim(9.4, 16.1)
    ax.set_ylim(0, 105)
    ax.set_xticks([10, 11, 12, 13, 14, 15, 16])
    ax.set_xticklabels(["10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00"])
    ax.grid(True, alpha=0.3)
    ax.legend()

    # Right: timing curves by gap-size bucket
    ax2 = axes[1]
    colors = ["#4CAF50", "#8BC34A", "#FFC107", "#FF9800", "#F44336"]
    for idx, bkt in enumerate(buckets):
        bkt_fills = [(m, r) for _, m, r in fill_times if r["bucket"] == bkt]
        nf = len(bkt_fills)
        if nf < 10:
            continue
        bkt_cum = []
        for cp, _, _, _ in cum_data:
            cp_h, cp_m = int(cp[:2]), int(cp[3:])
            cp_mins = (cp_h - 9) * 60 + cp_m - 30
            n_by = sum(1 for m, _ in bkt_fills if m <= cp_mins)
            bkt_cum.append(100 * n_by / nf)
        ax2.plot(times_numeric, bkt_cum, "o-", color=colors[idx], linewidth=1.5,
                 markersize=3, label=f"{bkt} (N={nf})")

    ax2.set_xlabel("Time (ET)")
    ax2.set_ylabel("Cumulative % of Fills")
    ax2.set_title("Fill Timing by Gap Size")
    ax2.set_xlim(9.4, 16.1)
    ax2.set_ylim(0, 105)
    ax2.set_xticks([10, 11, 12, 13, 14, 15, 16])
    ax2.set_xticklabels(["10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00"])
    ax2.grid(True, alpha=0.3)
    ax2.legend(fontsize=8, loc="lower right")

    plt.tight_layout()
    chart_path = os.path.join(AUDIT_DIR, "audit_b2_timing_curve.png")
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    print(f"Saved: {chart_path}")

except ImportError:
    print("matplotlib not available — chart skipped")
