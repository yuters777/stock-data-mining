#!/usr/bin/env python3
"""Audit F1: BTC→ETH EMA cross lead-lag analysis.

Loads BTC and ETH M5 crypto data, filters to equity hours (09:30-16:00 ET),
computes EMA9/EMA21, detects crosses, matches BTC→ETH crosses within ±120 min,
and measures the lag distribution.

Claim: BTC leads ETH by ~19 minutes (N=1 from CPI Day 3).
"""

import csv
import os
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.join(SCRIPT_DIR, "..", "..")
FETCHED_DIR = os.path.join(BASE_DIR, "Fetched_Data")
OUTPUT_DIR = SCRIPT_DIR

# ── Load and filter M5 data ────────────────────────────────────────────────

def load_m5_crypto(ticker):
    """Load M5 crypto data, filter to equity regular session hours (09:30-16:00 ET)."""
    fpath = os.path.join(FETCHED_DIR, f"{ticker}_crypto_data.csv")
    bars = []
    with open(fpath) as f:
        for row in csv.DictReader(f):
            dt = datetime.strptime(row["Datetime"], "%Y-%m-%d %H:%M:%S")
            # Filter to equity hours: 09:30 <= time < 16:00
            t = dt.time()
            from datetime import time as dtime
            if dtime(9, 30) <= t < dtime(16, 0):
                bars.append({
                    "datetime": dt,
                    "date": dt.strftime("%Y-%m-%d"),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                })
    return bars


def compute_ema(values, period):
    """Compute EMA on a list of values. Returns list of same length."""
    ema = [0.0] * len(values)
    if len(values) == 0:
        return ema
    k = 2.0 / (period + 1)
    ema[0] = values[0]
    for i in range(1, len(values)):
        ema[i] = values[i] * k + ema[i - 1] * (1 - k)
    return ema


def detect_crosses(bars, ema9, ema21):
    """Detect EMA9/EMA21 crosses. Returns list of cross events."""
    crosses = []
    for i in range(1, len(bars)):
        prev_diff = ema9[i - 1] - ema21[i - 1]
        curr_diff = ema9[i] - ema21[i]
        if prev_diff <= 0 and curr_diff > 0:
            crosses.append({
                "datetime": bars[i]["datetime"],
                "date": bars[i]["date"],
                "direction": "UP",
                "close": bars[i]["close"],
                "ema9": ema9[i],
                "ema21": ema21[i],
            })
        elif prev_diff >= 0 and curr_diff < 0:
            crosses.append({
                "datetime": bars[i]["datetime"],
                "date": bars[i]["date"],
                "direction": "DOWN",
                "close": bars[i]["close"],
                "ema9": ema9[i],
                "ema21": ema21[i],
            })
    return crosses


# ── Process both tickers ───────────────────────────────────────────────────

print("Loading BTC M5 data...")
btc_bars = load_m5_crypto("BTC")
print(f"  {len(btc_bars)} bars after equity-hours filter")

print("Loading ETH M5 data...")
eth_bars = load_m5_crypto("ETH")
print(f"  {len(eth_bars)} bars after equity-hours filter")

# Compute EMAs — need to reset per day to avoid overnight gaps contaminating EMA
def process_by_day(bars):
    """Group bars by date, compute EMA per day, detect crosses per day."""
    by_date = defaultdict(list)
    for b in bars:
        by_date[b["date"]].append(b)

    all_crosses = []
    for date in sorted(by_date.keys()):
        day_bars = by_date[date]
        if len(day_bars) < 25:  # need enough bars for EMA21 to stabilize
            continue
        closes = [b["close"] for b in day_bars]
        ema9 = compute_ema(closes, 9)
        ema21 = compute_ema(closes, 21)
        # Skip first ~25 bars for EMA warmup
        warmup = 25
        day_crosses = detect_crosses(day_bars[warmup:], ema9[warmup:], ema21[warmup:])
        all_crosses.extend(day_crosses)

    return all_crosses


# Alternative: continuous EMA across all bars (more crosses, but gap effects)
# Let's do BOTH and use per-day as primary (cleaner for intraday analysis)

print("\nComputing per-day EMA9/EMA21 crosses...")
btc_crosses = process_by_day(btc_bars)
eth_crosses = process_by_day(eth_bars)

btc_up = [c for c in btc_crosses if c["direction"] == "UP"]
btc_dn = [c for c in btc_crosses if c["direction"] == "DOWN"]
eth_up = [c for c in eth_crosses if c["direction"] == "UP"]
eth_dn = [c for c in eth_crosses if c["direction"] == "DOWN"]

print(f"  BTC crosses: {len(btc_crosses)} total ({len(btc_up)} UP, {len(btc_dn)} DOWN)")
print(f"  ETH crosses: {len(eth_crosses)} total ({len(eth_up)} UP, {len(eth_dn)} DOWN)")


# ── Match BTC → ETH crosses ────────────────────────────────────────────────

def match_crosses(btc_list, eth_list, max_lag_min=120):
    """For each BTC cross, find nearest ETH cross in same direction within ±max_lag_min.
    Returns list of (btc_cross, eth_cross, lag_minutes) tuples.
    lag > 0 means ETH lags BTC (BTC leads).
    """
    matches = []
    used_eth = set()  # avoid double-matching

    for bc in btc_list:
        best = None
        best_abs_lag = max_lag_min + 1

        for j, ec in enumerate(eth_list):
            if j in used_eth:
                continue
            if bc["direction"] != ec["direction"]:
                continue

            lag = (ec["datetime"] - bc["datetime"]).total_seconds() / 60.0

            if abs(lag) <= max_lag_min and abs(lag) < best_abs_lag:
                best = (j, ec, lag)
                best_abs_lag = abs(lag)

        if best is not None:
            j, ec, lag = best
            used_eth.add(j)
            matches.append({
                "btc_datetime": bc["datetime"],
                "eth_datetime": ec["datetime"],
                "direction": bc["direction"],
                "lag_min": lag,
                "btc_close": bc["close"],
                "eth_close": ec["close"],
            })

    return matches


print("\nMatching BTC→ETH crosses (±120 min window)...")
matches_120 = match_crosses(btc_crosses, eth_crosses, max_lag_min=120)
matches_60 = [m for m in matches_120 if abs(m["lag_min"]) <= 60]

print(f"  Matched within ±120 min: {len(matches_120)}")
print(f"  Matched within ±60 min:  {len(matches_60)}")

pct_matched_120 = 100.0 * len(matches_120) / len(btc_crosses) if btc_crosses else 0
pct_matched_60 = 100.0 * len(matches_60) / len(btc_crosses) if btc_crosses else 0

# ── Lag statistics ──────────────────────────────────────────────────────────

if matches_120:
    lags_120 = np.array([m["lag_min"] for m in matches_120])
    lags_60 = np.array([m["lag_min"] for m in matches_60]) if matches_60 else np.array([])

    mean_lag = np.mean(lags_120)
    median_lag = np.median(lags_120)
    std_lag = np.std(lags_120)
    pct_btc_leads = 100.0 * np.sum(lags_120 > 0) / len(lags_120)
    pct_same = 100.0 * np.sum(lags_120 == 0) / len(lags_120)
    pct_eth_leads = 100.0 * np.sum(lags_120 < 0) / len(lags_120)

# ── Print results ───────────────────────────────────────────────────────────

print()
print("=" * 80)
print("AUDIT F1: BTC → ETH EMA CROSS LEAD-LAG ANALYSIS")
print("=" * 80)
print()
print(f"Data: BTC & ETH M5, filtered to equity hours (09:30-16:00 ET)")
print(f"EMA: 9/21 computed per-day with 25-bar warmup")
print(f"BTC crosses: {len(btc_crosses)}  |  ETH crosses: {len(eth_crosses)}")
print()

print("─" * 80)
print("CROSS MATCHING")
print("─" * 80)
print(f"  BTC crosses with ETH match within ±120 min: {len(matches_120)}/{len(btc_crosses)} "
      f"({pct_matched_120:.1f}%)")
print(f"  BTC crosses with ETH match within ±60 min:  {len(matches_60)}/{len(btc_crosses)} "
      f"({pct_matched_60:.1f}%)")
print()

if matches_120:
    print("─" * 80)
    print("LAG STATISTICS (positive = ETH lags BTC, i.e. BTC leads)")
    print("─" * 80)
    print(f"  N matched pairs:   {len(matches_120)}")
    print(f"  Mean lag:          {mean_lag:+.1f} min")
    print(f"  Median lag:        {median_lag:+.1f} min")
    print(f"  Std dev:           {std_lag:.1f} min")
    print(f"  BTC leads (lag>0): {pct_btc_leads:.1f}%")
    print(f"  Simultaneous (=0): {pct_same:.1f}%")
    print(f"  ETH leads (lag<0): {pct_eth_leads:.1f}%")
    print()

    # By direction
    for direction in ["UP", "DOWN"]:
        subset = [m for m in matches_120 if m["direction"] == direction]
        if subset:
            sub_lags = np.array([m["lag_min"] for m in subset])
            print(f"  {direction} crosses: N={len(subset)}, "
                  f"mean lag={np.mean(sub_lags):+.1f} min, "
                  f"median={np.median(sub_lags):+.1f} min, "
                  f"BTC leads={100*np.sum(sub_lags>0)/len(sub_lags):.1f}%")

    print()

    # Claim assessment
    print("─" * 80)
    print("CLAIM: BTC leads ETH by ~19 minutes (N=1 from CPI Day 3)")
    print("─" * 80)
    print(f"  Observed mean lag:   {mean_lag:+.1f} min")
    print(f"  Observed median lag: {median_lag:+.1f} min")
    if mean_lag > 0:
        print(f"  → BTC does tend to lead ETH on average.")
        if 10 <= mean_lag <= 30:
            print(f"  → ~19 min claim is PLAUSIBLE (observed mean in 10-30 min range)")
        else:
            print(f"  → ~19 min specific value {'CLOSE' if abs(mean_lag - 19) < 10 else 'NOT CLOSE'} "
                  f"to observed mean")
    else:
        print(f"  → BTC does NOT lead ETH on average. Claim NOT CONFIRMED.")

    print()

    # Histogram bins
    bins = [(-120, -60), (-60, -30), (-30, -10), (-10, -5), (-5, 0),
            (0, 5), (5, 10), (10, 30), (30, 60), (60, 120)]
    print("LAG HISTOGRAM (minutes):")
    print(f"  {'Bin':>14} {'N':>5} {'%':>7} {'Bar'}")
    print(f"  {'-'*50}")
    max_n = max(np.sum((lags_120 >= lo) & (lags_120 < hi)) for lo, hi in bins) if len(lags_120) > 0 else 1
    for lo, hi in bins:
        n = int(np.sum((lags_120 >= lo) & (lags_120 < hi)))
        pct = 100.0 * n / len(lags_120)
        bar_len = int(30 * n / max_n) if max_n > 0 else 0
        print(f"  [{lo:+4d},{hi:+4d})  {n:>5} {pct:>6.1f}% {'█' * bar_len}")

print()

# ── Save CSV ────────────────────────────────────────────────────────────────

csv_path = os.path.join(OUTPUT_DIR, "audit_f1_btc_eth_lag.csv")
with open(csv_path, "w", newline="") as f:
    fields = ["btc_datetime", "eth_datetime", "direction", "lag_min",
              "btc_close", "eth_close"]
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    for m in matches_120:
        writer.writerow({
            "btc_datetime": m["btc_datetime"].strftime("%Y-%m-%d %H:%M:%S"),
            "eth_datetime": m["eth_datetime"].strftime("%Y-%m-%d %H:%M:%S"),
            "direction": m["direction"],
            "lag_min": f"{m['lag_min']:.1f}",
            "btc_close": f"{m['btc_close']:.2f}",
            "eth_close": f"{m['eth_close']:.2f}",
        })
print(f"Saved: {csv_path}")

# ── Save histogram PNG ─────────────────────────────────────────────────────

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Left: full histogram
    ax = axes[0]
    ax.hist(lags_120, bins=30, color="steelblue", edgecolor="white", alpha=0.8)
    ax.axvline(0, color="red", linestyle="--", linewidth=1.5, label="Simultaneous")
    ax.axvline(mean_lag, color="orange", linestyle="-", linewidth=2,
               label=f"Mean={mean_lag:+.1f}m")
    ax.axvline(median_lag, color="green", linestyle="-", linewidth=2,
               label=f"Median={median_lag:+.1f}m")
    ax.axvline(19, color="purple", linestyle=":", linewidth=1.5,
               label="Claimed ~19m")
    ax.set_xlabel("Lag (minutes): ETH_time − BTC_time")
    ax.set_ylabel("Count")
    ax.set_title(f"BTC→ETH EMA Cross Lag (±120m, N={len(matches_120)})")
    ax.legend(fontsize=8)

    # Right: zoomed ±60 min
    ax = axes[1]
    if len(lags_60) > 0:
        ax.hist(lags_60, bins=24, color="coral", edgecolor="white", alpha=0.8)
        ax.axvline(0, color="red", linestyle="--", linewidth=1.5)
        m60 = np.mean(lags_60)
        ax.axvline(m60, color="orange", linestyle="-", linewidth=2,
                   label=f"Mean={m60:+.1f}m")
        ax.axvline(np.median(lags_60), color="green", linestyle="-", linewidth=2,
                   label=f"Median={np.median(lags_60):+.1f}m")
    ax.set_xlabel("Lag (minutes): ETH_time − BTC_time")
    ax.set_ylabel("Count")
    ax.set_title(f"Zoomed ±60m (N={len(matches_60)})")
    ax.legend(fontsize=8)

    plt.tight_layout()
    png_path = os.path.join(OUTPUT_DIR, "audit_f1_lag_hist.png")
    plt.savefig(png_path, dpi=150)
    plt.close()
    print(f"Saved: {png_path}")

except ImportError:
    print("matplotlib not available — skipping histogram PNG")
