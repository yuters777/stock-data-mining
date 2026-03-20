#!/usr/bin/env python3
"""Audit C3: False breakout rate by intraday zone.

For each M5 bar in regular session (09:30–16:00):
  - rolling_high = max(High) of prior 6 bars
  - rolling_low  = min(Low)  of prior 6 bars
  - Breakout UP:   close > rolling_high * 1.003  (exceeds by >0.3%)
  - Breakout DOWN: close < rolling_low  * 0.997
  - False breakout: within NEXT 6 bars, price returns to [rolling_low, rolling_high]

Zones:
  Zone 2: 10:00–12:00 ET
  Zone 3: 12:00–13:30 ET  (Dead Zone — claim: 45–55% false breakout)
  Zone 4: 13:30–14:45 ET
  Zone 5: 14:45–16:00 ET
"""

import csv
import os
import statistics
from collections import defaultdict

FETCHED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "Fetched_Data")
AUDIT_DIR = os.path.dirname(__file__)

TICKERS = sorted(
    f.replace("_data.csv", "")
    for f in os.listdir(FETCHED_DIR)
    if f.endswith("_data.csv") and "crypto" not in f
)

ZONES = [
    ("Zone2_10-12", "10:00", "12:00"),
    ("Zone3_12-1330", "12:00", "13:30"),
    ("Zone4_1330-1445", "13:30", "14:45"),
    ("Zone5_1445-16", "14:45", "16:00"),
]

LOOKBACK = 6   # bars for rolling high/low
LOOKAHEAD = 6  # bars to check for false breakout
THRESHOLD = 0.003  # 0.3% breakout threshold


def get_zone(hhmm):
    for zname, start, end in ZONES:
        if start <= hhmm < end:
            return zname
    return None


# ── Process each ticker ─────────────────────────────────────────────────────
all_breakouts = []  # list of dicts

for ticker in TICKERS:
    fpath = os.path.join(FETCHED_DIR, f"{ticker}_data.csv")

    # Load regular-session bars grouped by day
    day_bars = defaultdict(list)
    with open(fpath) as f:
        for row in csv.DictReader(f):
            hhmm = row["Datetime"][11:16]
            if "09:30" <= hhmm < "16:00":
                date_str = row["Datetime"][:10]
                day_bars[date_str].append({
                    "datetime": row["Datetime"],
                    "hhmm": hhmm,
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                })

    for date_str in sorted(day_bars.keys()):
        bars = day_bars[date_str]
        n = len(bars)

        for i in range(LOOKBACK, n):
            bar = bars[i]
            zone = get_zone(bar["hhmm"])
            if zone is None:
                continue

            # Rolling high/low from prior 6 bars (not including current)
            window = bars[i - LOOKBACK:i]
            roll_high = max(b["high"] for b in window)
            roll_low = min(b["low"] for b in window)

            # Check breakout
            breakout_dir = None
            if bar["close"] > roll_high * (1 + THRESHOLD):
                breakout_dir = "UP"
            elif bar["close"] < roll_low * (1 - THRESHOLD):
                breakout_dir = "DOWN"

            if breakout_dir is None:
                continue

            # Check false breakout: within next 6 bars, does price return to range?
            lookahead = bars[i + 1:i + 1 + LOOKAHEAD]
            false_bo = False
            if breakout_dir == "UP":
                # False if any subsequent bar's low dips back to <= roll_high
                for fb in lookahead:
                    if fb["low"] <= roll_high:
                        false_bo = True
                        break
            else:  # DOWN
                # False if any subsequent bar's high rises back to >= roll_low
                for fb in lookahead:
                    if fb["high"] >= roll_low:
                        false_bo = True
                        break

            all_breakouts.append({
                "date": date_str,
                "ticker": ticker,
                "datetime": bar["datetime"],
                "zone": zone,
                "direction": breakout_dir,
                "close": f"{bar['close']:.4f}",
                "roll_high": f"{roll_high:.4f}",
                "roll_low": f"{roll_low:.4f}",
                "false_breakout": "1" if false_bo else "0",
            })

N = len(all_breakouts)
print(f"Tickers: {len(TICKERS)} | Total breakouts detected: {N}")

# ── Save CSV ────────────────────────────────────────────────────────────────
csv_path = os.path.join(AUDIT_DIR, "false_breakout_by_zone.csv")
with open(csv_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(all_breakouts[0].keys()))
    writer.writeheader()
    writer.writerows(all_breakouts)
print(f"Saved: {csv_path}")

# ── Stats ───────────────────────────────────────────────────────────────────
lines = []


def p(line=""):
    print(line)
    lines.append(line)


p("=" * 72)
p("AUDIT C3: FALSE BREAKOUT RATE BY INTRADAY ZONE")
p("=" * 72)
p(f"Tickers: {len(TICKERS)} | Total breakouts: {N}")
p(f"Lookback: {LOOKBACK} bars | Lookahead: {LOOKAHEAD} bars | Threshold: {THRESHOLD*100:.1f}%")
p()

# Zone summary
zone_names = [z[0] for z in ZONES]
zone_labels = {
    "Zone2_10-12": "Zone 2 (10:00–12:00)",
    "Zone3_12-1330": "Zone 3 (12:00–13:30) DEAD ZONE",
    "Zone4_1330-1445": "Zone 4 (13:30–14:45)",
    "Zone5_1445-16": "Zone 5 (14:45–16:00)",
}

p("FALSE BREAKOUT RATE BY ZONE:")
p(f"  {'Zone':<36} {'N_bo':>6} {'N_false':>8} {'FalseRate':>10}")
p(f"  {'-' * 64}")

zone_data = {}
for zn in zone_names:
    z_rows = [r for r in all_breakouts if r["zone"] == zn]
    n_bo = len(z_rows)
    n_false = sum(1 for r in z_rows if r["false_breakout"] == "1")
    rate = 100 * n_false / n_bo if n_bo > 0 else 0
    zone_data[zn] = {"n": n_bo, "n_false": n_false, "rate": rate}
    label = zone_labels.get(zn, zn)
    p(f"  {label:<36} {n_bo:>6} {n_false:>8} {rate:>9.1f}%")

p()

# Claim check
z3 = zone_data["Zone3_12-1330"]
p(f"CLAIM: Dead Zone (Zone 3) false breakout rate = 45–55%")
p(f"ACTUAL: {z3['rate']:.1f}%")
in_range = 45 <= z3["rate"] <= 55
close = abs(z3["rate"] - 50) <= 10
match = "YES — within claimed range" if in_range else ("~CLOSE" if close else "NO")
p(f"MATCH: {match}")
p()

# By direction
p("FALSE BREAKOUT RATE BY ZONE × DIRECTION:")
p(f"  {'Zone':<20} {'UP_N':>6} {'UP_false':>9} {'UP_rate':>8} {'DN_N':>6} {'DN_false':>9} {'DN_rate':>8}")
p(f"  {'-' * 70}")
for zn in zone_names:
    z_rows = [r for r in all_breakouts if r["zone"] == zn]
    for direction in ["UP", "DOWN"]:
        pass
    up = [r for r in z_rows if r["direction"] == "UP"]
    dn = [r for r in z_rows if r["direction"] == "DOWN"]
    up_n = len(up)
    dn_n = len(dn)
    up_f = sum(1 for r in up if r["false_breakout"] == "1")
    dn_f = sum(1 for r in dn if r["false_breakout"] == "1")
    up_r = 100 * up_f / up_n if up_n > 0 else 0
    dn_r = 100 * dn_f / dn_n if dn_n > 0 else 0
    short = zn.split("_")[0] + " " + zn.split("_")[1]
    p(f"  {short:<20} {up_n:>6} {up_f:>9} {up_r:>7.1f}% {dn_n:>6} {dn_f:>9} {dn_r:>7.1f}%")
p()

# Per-ticker Zone 3 false breakout rate
p("PER-TICKER DEAD ZONE (Zone 3) FALSE BREAKOUT RATE:")
p(f"  {'Ticker':<8} {'N_bo':>6} {'N_false':>8} {'Rate':>7}")
p(f"  {'-' * 32}")
for ticker in TICKERS:
    t_z3 = [r for r in all_breakouts if r["ticker"] == ticker and r["zone"] == "Zone3_12-1330"]
    tn = len(t_z3)
    tf = sum(1 for r in t_z3 if r["false_breakout"] == "1")
    tr = 100 * tf / tn if tn > 0 else 0
    p(f"  {ticker:<8} {tn:>6} {tf:>8} {tr:>6.1f}%")

p()

# Is Zone 3 the highest false breakout zone?
rates_sorted = sorted(zone_data.items(), key=lambda x: -x[1]["rate"])
p("ZONE RANKING (highest false breakout rate first):")
for i, (zn, d) in enumerate(rates_sorted, 1):
    marker = " ← DEAD ZONE" if "Zone3" in zn else ""
    p(f"  {i}. {zone_labels.get(zn, zn):<40} {d['rate']:.1f}%{marker}")

# ── Save stats ──────────────────────────────────────────────────────────────
stats_path = os.path.join(AUDIT_DIR, "false_breakout_stats.txt")
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

    # Left: false breakout rate by zone
    ax = axes[0]
    zone_short = ["Zone 2\n10-12", "Zone 3\n12-13:30\n(Dead Zone)", "Zone 4\n13:30-14:45", "Zone 5\n14:45-16"]
    rates = [zone_data[zn]["rate"] for zn in zone_names]
    ns = [zone_data[zn]["n"] for zn in zone_names]
    colors = ["#2196F3", "#F44336", "#FF9800", "#4CAF50"]

    bars = ax.bar(range(len(zone_names)), rates, color=colors, alpha=0.85, edgecolor="white")
    ax.set_xticks(range(len(zone_names)))
    ax.set_xticklabels(zone_short, fontsize=9)
    ax.set_ylabel("False Breakout Rate (%)")
    ax.set_title("False Breakout Rate by Intraday Zone")

    for bar, n, r in zip(bars, ns, rates):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                f"{r:.1f}%\nN={n}", ha="center", va="bottom", fontsize=9)

    # Shade claimed range for Zone 3
    ax.axhspan(45, 55, xmin=0.15, xmax=0.5, alpha=0.15, color="#F44336",
               label="Claimed 45–55%")
    ax.legend(fontsize=8)
    ax.set_ylim(0, max(rates) + 12)

    # Right: by zone × direction
    ax2 = axes[1]
    x = np.arange(len(zone_names))
    width = 0.35

    up_rates = []
    dn_rates = []
    for zn in zone_names:
        z_rows = [r for r in all_breakouts if r["zone"] == zn]
        up = [r for r in z_rows if r["direction"] == "UP"]
        dn = [r for r in z_rows if r["direction"] == "DOWN"]
        up_f = sum(1 for r in up if r["false_breakout"] == "1")
        dn_f = sum(1 for r in dn if r["false_breakout"] == "1")
        up_rates.append(100 * up_f / len(up) if up else 0)
        dn_rates.append(100 * dn_f / len(dn) if dn else 0)

    ax2.bar(x - width / 2, up_rates, width, label="Breakout UP", color="#4CAF50", alpha=0.8)
    ax2.bar(x + width / 2, dn_rates, width, label="Breakout DOWN", color="#F44336", alpha=0.8)
    ax2.set_xticks(x)
    ax2.set_xticklabels(zone_short, fontsize=9)
    ax2.set_ylabel("False Breakout Rate (%)")
    ax2.set_title("False Breakout Rate by Zone × Direction")
    ax2.legend(fontsize=9)
    ax2.set_ylim(0, max(max(up_rates), max(dn_rates)) + 10)

    plt.tight_layout()
    chart_path = os.path.join(AUDIT_DIR, "false_breakout_chart.png")
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    print(f"Saved: {chart_path}")

except ImportError:
    print("matplotlib not available — chart skipped")
