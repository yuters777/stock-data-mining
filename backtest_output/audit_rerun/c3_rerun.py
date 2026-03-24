#!/usr/bin/env python3
"""Re-run Audit C3 (False Breakout by Zone) using FIXED data via load_m5_regsess().

This replaces the original naive time filter on raw Fetched_Data/ with the
correct IST-block extraction that produces genuine regular-session bars.

Changes from original:
  - Data source: load_m5_regsess() instead of raw CSV with "09:30" <= hhmm < "16:00"
  - All other logic IDENTICAL
"""

import os
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from utils.data_loader import load_m5_regsess, ALL_TICKERS

AUDIT_RERUN_DIR = os.path.dirname(__file__)

TICKERS = ALL_TICKERS

ZONES = [
    ("Zone2_10-12", "10:00", "12:00"),
    ("Zone3_12-1330", "12:00", "13:30"),
    ("Zone4_1330-1445", "13:30", "14:45"),
    ("Zone5_1445-16", "14:45", "16:00"),
]

LOOKBACK = 6
LOOKAHEAD = 6
THRESHOLD = 0.003


def get_zone(hhmm):
    for zname, start, end in ZONES:
        if start <= hhmm < end:
            return zname
    return None


# ── Process each ticker ─────────────────────────────────────────────────────
all_breakouts = []

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
        day_bars[row["date"]].append({
            "datetime": row["Datetime"],
            "hhmm": row["hhmm"],
            "open": row["Open"],
            "high": row["High"],
            "low": row["Low"],
            "close": row["Close"],
        })

    for date_str in sorted(day_bars.keys()):
        bars = day_bars[date_str]
        n = len(bars)

        for i in range(LOOKBACK, n):
            bar = bars[i]
            zone = get_zone(bar["hhmm"])
            if zone is None:
                continue

            window = bars[i - LOOKBACK:i]
            roll_high = max(b["high"] for b in window)
            roll_low = min(b["low"] for b in window)

            breakout_dir = None
            if bar["close"] > roll_high * (1 + THRESHOLD):
                breakout_dir = "UP"
            elif bar["close"] < roll_low * (1 - THRESHOLD):
                breakout_dir = "DOWN"

            if breakout_dir is None:
                continue

            lookahead = bars[i + 1:i + 1 + LOOKAHEAD]
            false_bo = False
            if breakout_dir == "UP":
                for fb in lookahead:
                    if fb["low"] <= roll_high:
                        false_bo = True
                        break
            else:
                for fb in lookahead:
                    if fb["high"] >= roll_low:
                        false_bo = True
                        break

            all_breakouts.append({
                "date": date_str,
                "ticker": ticker,
                "zone": zone,
                "direction": breakout_dir,
                "false_breakout": false_bo,
            })

N = len(all_breakouts)
print(f"Tickers: {len(TICKERS)} | Total breakouts detected: {N}")

# ── Stats ───────────────────────────────────────────────────────────────────
lines = []


def p(line=""):
    print(line)
    lines.append(line)


p("=" * 72)
p("AUDIT C3 RE-RUN: FALSE BREAKOUT RATE BY ZONE (FIXED DATA)")
p("=" * 72)
p(f"Tickers: {len(TICKERS)} | Total breakouts: {N}")
p(f"Lookback: {LOOKBACK} bars | Lookahead: {LOOKAHEAD} bars | Threshold: {THRESHOLD*100:.1f}%")
p(f"Data source: load_m5_regsess() (IST-block extraction)")
p()

zone_names = [z[0] for z in ZONES]
zone_labels = {
    "Zone2_10-12": "Zone 2 (10:00-12:00)",
    "Zone3_12-1330": "Zone 3 (12:00-13:30) DEAD ZONE",
    "Zone4_1330-1445": "Zone 4 (13:30-14:45)",
    "Zone5_1445-16": "Zone 5 (14:45-16:00)",
}

p("FALSE BREAKOUT RATE BY ZONE:")
p(f"  {'Zone':<36} {'N_bo':>6} {'N_false':>8} {'FalseRate':>10}")
p(f"  {'-' * 64}")

zone_data = {}
for zn in zone_names:
    z_rows = [r for r in all_breakouts if r["zone"] == zn]
    n_bo = len(z_rows)
    n_false = sum(1 for r in z_rows if r["false_breakout"])
    rate = 100 * n_false / n_bo if n_bo > 0 else 0
    zone_data[zn] = {"n": n_bo, "n_false": n_false, "rate": rate}
    label = zone_labels.get(zn, zn)
    p(f"  {label:<36} {n_bo:>6} {n_false:>8} {rate:>9.1f}%")

p()

# Dead Zone claim check
z3 = zone_data.get("Zone3_12-1330", {"rate": 0})
p(f"CLAIM: Dead Zone (Zone 3) false breakout rate = 45-55%")
p(f"ACTUAL: {z3['rate']:.1f}%")
p()

# By direction
p("FALSE BREAKOUT RATE BY ZONE x DIRECTION:")
p(f"  {'Zone':<20} {'UP_N':>6} {'UP_rate':>8} {'DN_N':>6} {'DN_rate':>8}")
p(f"  {'-' * 52}")
for zn in zone_names:
    z_rows = [r for r in all_breakouts if r["zone"] == zn]
    up = [r for r in z_rows if r["direction"] == "UP"]
    dn = [r for r in z_rows if r["direction"] == "DOWN"]
    up_f = sum(1 for r in up if r["false_breakout"])
    dn_f = sum(1 for r in dn if r["false_breakout"])
    up_r = 100 * up_f / len(up) if up else 0
    dn_r = 100 * dn_f / len(dn) if dn else 0
    short = zn.split("_")[0] + " " + zn.split("_")[1]
    p(f"  {short:<20} {len(up):>6} {up_r:>7.1f}% {len(dn):>6} {dn_r:>7.1f}%")
p()

# Per-ticker Zone 3
p("PER-TICKER DEAD ZONE (Zone 3) FALSE BREAKOUT RATE:")
p(f"  {'Ticker':<8} {'N_bo':>6} {'N_false':>8} {'Rate':>7}")
p(f"  {'-' * 32}")
for ticker in TICKERS:
    t_z3 = [r for r in all_breakouts if r["ticker"] == ticker and r["zone"] == "Zone3_12-1330"]
    tn = len(t_z3)
    tf = sum(1 for r in t_z3 if r["false_breakout"])
    tr = 100 * tf / tn if tn > 0 else 0
    p(f"  {ticker:<8} {tn:>6} {tf:>8} {tr:>6.1f}%")

p()

# Zone ranking
rates_sorted = sorted(zone_data.items(), key=lambda x: -x[1]["rate"])
p("ZONE RANKING (highest false breakout rate first):")
for i, (zn, d) in enumerate(rates_sorted, 1):
    marker = " <-- DEAD ZONE" if "Zone3" in zn else ""
    p(f"  {i}. {zone_labels.get(zn, zn):<40} {d['rate']:.1f}%{marker}")

# Save
stats_path = os.path.join(AUDIT_RERUN_DIR, "C3_RERUN_RESULTS.md")
with open(stats_path, "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"\nSaved: {stats_path}")
