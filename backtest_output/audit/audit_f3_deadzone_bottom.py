#!/usr/bin/env python3
"""Audit F3: Dead Zone differential + Crypto bottoms before equity on stress days.

Part A — Dead Zone (12:00-13:30) differential:
  Equity group: NVDA, AAPL, GOOGL, TSLA, META
  Crypto group: IBIT, COIN, MARA
  Compare abs_return and volume_pct in the dead zone.

Part B — Crypto bottoms before equity on stress days:
  On stress days, find intraday low time for IBIT vs SPY.
  lag = SPY_low_time - IBIT_low_time (positive = crypto bottoms first).
"""

import csv
import json
import os
import numpy as np
from datetime import datetime, time as dtime
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKTEST_DIR = os.path.join(SCRIPT_DIR, "..")


def load_m5(ticker):
    """Load M5 regsess bars, grouped by date."""
    fpath = os.path.join(BACKTEST_DIR, f"{ticker}_m5_regsess.csv")
    by_date = defaultdict(list)
    with open(fpath) as f:
        for row in csv.DictReader(f):
            dt = datetime.strptime(row["Datetime"], "%Y-%m-%d %H:%M:%S")
            by_date[dt.strftime("%Y-%m-%d")].append({
                "datetime": dt,
                "time": dt.time(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]),
            })
    return by_date


# ═══════════════════════════════════════════════════════════════════════════
# PART A: DEAD ZONE DIFFERENTIAL
# ═══════════════════════════════════════════════════════════════════════════

EQUITY_GROUP = ["NVDA", "AAPL", "GOOGL", "TSLA", "META"]
CRYPTO_GROUP = ["IBIT", "COIN", "MARA"]
ALL_TICKERS = EQUITY_GROUP + CRYPTO_GROUP

DEAD_START = dtime(12, 0)
DEAD_END = dtime(13, 30)

print("Loading M5 data for dead zone analysis...")
ticker_data = {}
for t in ALL_TICKERS:
    ticker_data[t] = load_m5(t)
    print(f"  {t}: {len(ticker_data[t])} days")

# Compute per-day metrics
dead_zone_rows = []

for t in ALL_TICKERS:
    group = "crypto" if t in CRYPTO_GROUP else "equity"
    for date, bars in ticker_data[t].items():
        if len(bars) < 10:
            continue

        # Full day metrics
        day_volume = sum(b["volume"] for b in bars)
        day_open = bars[0]["open"]
        day_close = bars[-1]["close"]

        # Dead zone bars: 12:00 <= time < 13:30
        dz_bars = [b for b in bars if DEAD_START <= b["time"] < DEAD_END]
        if not dz_bars or day_volume == 0 or day_open == 0:
            continue

        dz_volume = sum(b["volume"] for b in dz_bars)
        dz_open = dz_bars[0]["open"]
        dz_close = dz_bars[-1]["close"]
        dz_abs_return = abs(dz_close - dz_open) / dz_open
        dz_volume_pct = dz_volume / day_volume

        # Full day abs return for normalization
        day_abs_return = abs(day_close - day_open) / day_open if day_open != 0 else 0

        # Dead zone range (high-low) vs full day range
        dz_high = max(b["high"] for b in dz_bars)
        dz_low = min(b["low"] for b in dz_bars)
        day_high = max(b["high"] for b in bars)
        day_low = min(b["low"] for b in bars)
        dz_range = (dz_high - dz_low) / dz_open if dz_open != 0 else 0
        day_range = (day_high - day_low) / day_open if day_open != 0 else 0
        range_ratio = dz_range / day_range if day_range != 0 else 0

        dead_zone_rows.append({
            "date": date,
            "ticker": t,
            "group": group,
            "dz_abs_return": dz_abs_return,
            "dz_volume_pct": dz_volume_pct,
            "day_abs_return": day_abs_return,
            "dz_range": dz_range,
            "day_range": day_range,
            "range_ratio": range_ratio,
        })

# Aggregate by group
eq_rows = [r for r in dead_zone_rows if r["group"] == "equity"]
cr_rows = [r for r in dead_zone_rows if r["group"] == "crypto"]


def group_stats(rows, key):
    vals = [r[key] for r in rows]
    if not vals:
        return {"n": 0, "mean": 0, "median": 0, "std": 0}
    arr = np.array(vals)
    return {"n": len(arr), "mean": np.mean(arr), "median": np.median(arr), "std": np.std(arr)}


# Mann-Whitney U test (manual implementation)
def mann_whitney_u(x, y):
    """Compute Mann-Whitney U statistic and approximate z-score."""
    x = np.array(x)
    y = np.array(y)
    nx, ny = len(x), len(y)
    combined = np.concatenate([x, y])
    ranks = np.empty_like(combined, dtype=float)
    order = np.argsort(combined)
    # Average ranks for ties
    i = 0
    while i < len(order):
        j = i
        while j < len(order) and combined[order[j]] == combined[order[i]]:
            j += 1
        avg_rank = (i + j + 1) / 2.0  # 1-based average
        for k in range(i, j):
            ranks[order[k]] = avg_rank
        i = j

    u1 = np.sum(ranks[:nx]) - nx * (nx + 1) / 2
    u2 = nx * ny - u1
    u = min(u1, u2)

    # Normal approximation
    mu = nx * ny / 2
    sigma = np.sqrt(nx * ny * (nx + ny + 1) / 12)
    z = (u - mu) / sigma if sigma > 0 else 0
    return u, abs(z)


print()
print("=" * 85)
print("AUDIT F3 — PART A: DEAD ZONE (12:00-13:30) DIFFERENTIAL")
print("=" * 85)
print()

metrics = [
    ("dz_abs_return", "Abs Return (dead zone)", "%"),
    ("dz_volume_pct", "Volume % (dead zone / day)", "%"),
    ("range_ratio", "Range Ratio (DZ / Day)", ""),
    ("dz_range", "DZ Range (high-low)/open", "%"),
]

print(f"  {'Metric':<30} {'Equity':>12} {'Crypto':>12} {'Diff':>12} {'M-W |z|':>8}")
print(f"  {'-'*78}")

for key, label, fmt in metrics:
    eq = group_stats(eq_rows, key)
    cr = group_stats(cr_rows, key)
    diff = cr["mean"] - eq["mean"]

    eq_vals = [r[key] for r in eq_rows]
    cr_vals = [r[key] for r in cr_rows]
    _, z = mann_whitney_u(eq_vals, cr_vals)

    mult = 100 if fmt == "%" else 1
    print(f"  {label:<30} {eq['mean']*mult:>11.3f}{'%' if fmt=='%' else ''} "
          f"{cr['mean']*mult:>11.3f}{'%' if fmt=='%' else ''} "
          f"{diff*mult:>+11.3f}{'%' if fmt=='%' else ''} {z:>8.2f}")

print()
print(f"  Equity obs: {len(eq_rows)}  |  Crypto obs: {len(cr_rows)}")
print()

# Claim assessment
eq_dz_ret = np.mean([r["dz_abs_return"] for r in eq_rows])
cr_dz_ret = np.mean([r["dz_abs_return"] for r in cr_rows])
eq_vol_pct = np.mean([r["dz_volume_pct"] for r in eq_rows])
cr_vol_pct = np.mean([r["dz_volume_pct"] for r in cr_rows])

print(f"  Claim: crypto continues through dead zone, equity compresses")
print(f"  Equity DZ abs return: {eq_dz_ret*100:.3f}%  |  Crypto DZ abs return: {cr_dz_ret*100:.3f}%")
if cr_dz_ret > eq_dz_ret:
    print(f"  → Crypto has HIGHER dead-zone absolute return (+{(cr_dz_ret-eq_dz_ret)*100:.3f}%)")
else:
    print(f"  → Crypto has LOWER dead-zone absolute return ({(cr_dz_ret-eq_dz_ret)*100:+.3f}%)")

print(f"  Equity DZ volume %: {eq_vol_pct*100:.2f}%  |  Crypto DZ volume %: {cr_vol_pct*100:.2f}%")
if cr_vol_pct > eq_vol_pct:
    print(f"  → Crypto maintains MORE relative volume in dead zone — CONFIRMED")
else:
    print(f"  → Crypto has LESS relative volume — NOT CONFIRMED on volume")

# Per-ticker breakdown
print()
print("  Per-ticker dead zone stats:")
print(f"  {'Ticker':<8} {'Group':<8} {'DZ AbsRet':>12} {'DZ Vol%':>10} {'RangeRatio':>12} {'N':>5}")
print(f"  {'-'*60}")
for t in ALL_TICKERS:
    t_rows = [r for r in dead_zone_rows if r["ticker"] == t]
    if not t_rows:
        continue
    s_ret = group_stats(t_rows, "dz_abs_return")
    s_vol = group_stats(t_rows, "dz_volume_pct")
    s_rr = group_stats(t_rows, "range_ratio")
    grp = "crypto" if t in CRYPTO_GROUP else "equity"
    print(f"  {t:<8} {grp:<8} {s_ret['mean']*100:>11.3f}% {s_vol['mean']*100:>9.2f}% "
          f"{s_rr['mean']:>12.3f} {s_ret['n']:>5}")

# Save Part A
csv_a_path = os.path.join(SCRIPT_DIR, "audit_f3_dead_zone.csv")
with open(csv_a_path, "w", newline="") as f:
    fields = ["date", "ticker", "group", "dz_abs_return", "dz_volume_pct",
              "day_abs_return", "dz_range", "day_range", "range_ratio"]
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    for r in dead_zone_rows:
        writer.writerow({k: f"{v:.6f}" if isinstance(v, float) else v for k, v in r.items()})
print(f"\nSaved: {csv_a_path}")


# ═══════════════════════════════════════════════════════════════════════════
# PART B: CRYPTO BOTTOMS BEFORE EQUITY ON STRESS DAYS
# ═══════════════════════════════════════════════════════════════════════════

print()
print("=" * 85)
print("AUDIT F3 — PART B: CRYPTO BOTTOMS BEFORE EQUITY ON STRESS DAYS")
print("=" * 85)

# Load stress days
stress_path = os.path.join(BACKTEST_DIR, "stress_days.json")
with open(stress_path) as f:
    stress_days = json.load(f)
print(f"\nStress days: {len(stress_days)}")

# Load IBIT and SPY
print("Loading IBIT and SPY M5...")
ibit_data = load_m5("IBIT")
spy_data = load_m5("SPY")

# Also check COIN and MARA for broader crypto signal
coin_data = load_m5("COIN")


def find_intraday_low(bars):
    """Find the bar with the lowest low. Returns (time, low_price)."""
    if not bars:
        return None, None
    min_bar = min(bars, key=lambda b: b["low"])
    return min_bar["datetime"], min_bar["low"]


bottom_rows = []
for sd in stress_days:
    if sd not in ibit_data or sd not in spy_data:
        continue

    ibit_bars = ibit_data[sd]
    spy_bars = spy_data[sd]

    if len(ibit_bars) < 10 or len(spy_bars) < 10:
        continue

    ibit_low_dt, ibit_low_price = find_intraday_low(ibit_bars)
    spy_low_dt, spy_low_price = find_intraday_low(spy_bars)

    if ibit_low_dt is None or spy_low_dt is None:
        continue

    lag_min = (spy_low_dt - ibit_low_dt).total_seconds() / 60.0

    # Also get COIN low
    coin_low_dt = None
    coin_lag = None
    if sd in coin_data and len(coin_data[sd]) >= 10:
        coin_low_dt, _ = find_intraday_low(coin_data[sd])
        coin_lag = (spy_low_dt - coin_low_dt).total_seconds() / 60.0

    # Day severity: SPY return
    spy_ret = (spy_bars[-1]["close"] - spy_bars[0]["open"]) / spy_bars[0]["open"]

    bottom_rows.append({
        "date": sd,
        "spy_ret": spy_ret,
        "ibit_low_time": ibit_low_dt.strftime("%H:%M"),
        "spy_low_time": spy_low_dt.strftime("%H:%M"),
        "lag_min": lag_min,
        "coin_low_time": coin_low_dt.strftime("%H:%M") if coin_low_dt else "",
        "coin_lag_min": coin_lag,
    })

print(f"Stress days with both IBIT+SPY data: {len(bottom_rows)}")
print()

if bottom_rows:
    lags = np.array([r["lag_min"] for r in bottom_rows])
    coin_lags = np.array([r["coin_lag_min"] for r in bottom_rows if r["coin_lag_min"] is not None])

    mean_lag = np.mean(lags)
    median_lag = np.median(lags)
    pct_crypto_first = 100.0 * np.sum(lags > 0) / len(lags)
    pct_simultaneous = 100.0 * np.sum(lags == 0) / len(lags)
    pct_equity_first = 100.0 * np.sum(lags < 0) / len(lags)

    print(f"  IBIT→SPY bottom lag (positive = IBIT bottoms first):")
    print(f"    N stress days:       {len(lags)}")
    print(f"    Mean lag:            {mean_lag:+.1f} min")
    print(f"    Median lag:          {median_lag:+.1f} min")
    print(f"    Std dev:             {np.std(lags):.1f} min")
    print(f"    IBIT bottoms first:  {pct_crypto_first:.1f}%")
    print(f"    Simultaneous (±0):   {pct_simultaneous:.1f}%")
    print(f"    SPY bottoms first:   {pct_equity_first:.1f}%")
    print()

    if len(coin_lags) > 0:
        print(f"  COIN→SPY bottom lag:")
        print(f"    Mean lag:            {np.mean(coin_lags):+.1f} min")
        print(f"    Median lag:          {np.median(coin_lags):+.1f} min")
        print(f"    COIN bottoms first:  {100*np.sum(coin_lags>0)/len(coin_lags):.1f}%")
        print()

    # Claim
    print(f"  Claim: crypto bottoms before equity on stress days (N=3 live)")
    if mean_lag > 0 and pct_crypto_first > 50:
        print(f"  → CONFIRMED: IBIT bottoms {mean_lag:+.1f} min before SPY on average")
        print(f"  → {pct_crypto_first:.0f}% of stress days, crypto bottoms first")
    elif median_lag > 0:
        print(f"  → PARTIALLY CONFIRMED: median lag is positive ({median_lag:+.1f} min)")
        print(f"    but mean ({mean_lag:+.1f} min) is weak or negative")
    else:
        print(f"  → NOT CONFIRMED: mean lag = {mean_lag:+.1f} min, "
              f"crypto first only {pct_crypto_first:.0f}%")

    print()

    # Detail table — most severe stress days
    sorted_rows = sorted(bottom_rows, key=lambda r: r["spy_ret"])
    print("  Detail (sorted by SPY return, worst first):")
    print(f"  {'Date':<12} {'SPY Ret':>9} {'IBIT Low':>10} {'SPY Low':>10} "
          f"{'Lag(min)':>10} {'COIN Low':>10} {'COIN Lag':>10}")
    print(f"  {'-'*78}")
    for r in sorted_rows[:30]:  # Show worst 30
        print(f"  {r['date']:<12} {r['spy_ret']*100:>8.2f}% {r['ibit_low_time']:>10} "
              f"{r['spy_low_time']:>10} {r['lag_min']:>+10.0f} "
              f"{r['coin_low_time']:>10} "
              f"{r['coin_lag_min']:>+10.0f}" if r['coin_lag_min'] is not None
              else f"  {r['date']:<12} {r['spy_ret']*100:>8.2f}% {r['ibit_low_time']:>10} "
              f"{r['spy_low_time']:>10} {r['lag_min']:>+10.0f} {'':>10} {'':>10}")

    # Bucketed by severity
    print()
    print("  By stress severity:")
    severe = [r for r in bottom_rows if r["spy_ret"] < -0.015]
    moderate = [r for r in bottom_rows if -0.015 <= r["spy_ret"] < -0.005]
    mild = [r for r in bottom_rows if r["spy_ret"] >= -0.005]

    for label, subset in [("Severe (<-1.5%)", severe), ("Moderate (-1.5% to -0.5%)", moderate),
                          ("Mild (>-0.5%)", mild)]:
        if subset:
            sub_lags = np.array([r["lag_min"] for r in subset])
            print(f"  {label:<30} N={len(sub_lags):>3}, mean lag={np.mean(sub_lags):>+7.1f} min, "
                  f"crypto first={100*np.sum(sub_lags>0)/len(sub_lags):.0f}%")

# Save Part B
csv_b_path = os.path.join(SCRIPT_DIR, "audit_f3_crypto_bottom.csv")
with open(csv_b_path, "w", newline="") as f:
    fields = ["date", "spy_ret", "ibit_low_time", "spy_low_time", "lag_min",
              "coin_low_time", "coin_lag_min"]
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    for r in bottom_rows:
        writer.writerow({
            "date": r["date"],
            "spy_ret": f"{r['spy_ret']:.6f}",
            "ibit_low_time": r["ibit_low_time"],
            "spy_low_time": r["spy_low_time"],
            "lag_min": f"{r['lag_min']:.1f}",
            "coin_low_time": r["coin_low_time"],
            "coin_lag_min": f"{r['coin_lag_min']:.1f}" if r["coin_lag_min"] is not None else "",
        })
print(f"\nSaved: {csv_b_path}")
