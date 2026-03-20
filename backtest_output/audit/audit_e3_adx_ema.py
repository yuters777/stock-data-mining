#!/usr/bin/env python3
"""Audit E3: ADX at 4H EMA crosses + forward return analysis.

Part A — ADX at cross:
  Aggregate M5→daily OHLC, compute daily ADX(14).
  Bucket crosses by ADX: <15, 15-20, 20-25, 25-30, 30+.
  Forward 1-day return per bucket.
  Claim: ADX >= 18-20 minimum for good signals.

Part B — Forward returns from 4H EMA crosses:
  1-day and 3-day forward returns for UP vs DOWN crosses.
  Compare to baseline (all-day average return).
"""

import csv
import os
import numpy as np
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKTEST_DIR = os.path.join(SCRIPT_DIR, "..")


# ── Load M5 data and aggregate to daily ─────────────────────────────────────

def load_m5(ticker):
    fpath = os.path.join(BACKTEST_DIR, f"{ticker}_m5_regsess.csv")
    bars = []
    with open(fpath) as f:
        for row in csv.DictReader(f):
            bars.append({
                "date": row["Datetime"][:10],
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
            })
    return bars


def aggregate_daily(bars):
    """M5 bars → daily OHLC."""
    daily = {}
    for b in bars:
        d = b["date"]
        if d not in daily:
            daily[d] = {"date": d, "open": b["open"], "high": b["high"],
                        "low": b["low"], "close": b["close"]}
        else:
            daily[d]["high"] = max(daily[d]["high"], b["high"])
            daily[d]["low"] = min(daily[d]["low"], b["low"])
            daily[d]["close"] = b["close"]
    dates = sorted(daily.keys())
    return [daily[d] for d in dates]


def compute_adx(daily_bars, period=14):
    """Compute ADX(14) with +DI, -DI on daily bars. Returns dict date→(adx, pdi, mdi)."""
    n = len(daily_bars)
    highs = np.array([b["high"] for b in daily_bars])
    lows = np.array([b["low"] for b in daily_bars])
    closes = np.array([b["close"] for b in daily_bars])

    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i - 1]),
                     abs(lows[i] - closes[i - 1]))

    pdm = np.zeros(n)
    mdm = np.zeros(n)
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        pdm[i] = up if (up > down and up > 0) else 0.0
        mdm[i] = down if (down > up and down > 0) else 0.0

    atr_s = np.zeros(n)
    pdm_s = np.zeros(n)
    mdm_s = np.zeros(n)

    if n <= period:
        return {}

    atr_s[period] = np.sum(tr[1:period + 1])
    pdm_s[period] = np.sum(pdm[1:period + 1])
    mdm_s[period] = np.sum(mdm[1:period + 1])

    for i in range(period + 1, n):
        atr_s[i] = atr_s[i - 1] - atr_s[i - 1] / period + tr[i]
        pdm_s[i] = pdm_s[i - 1] - pdm_s[i - 1] / period + pdm[i]
        mdm_s[i] = mdm_s[i - 1] - mdm_s[i - 1] / period + mdm[i]

    pdi = np.full(n, np.nan)
    mdi = np.full(n, np.nan)
    dx = np.zeros(n)
    for i in range(period, n):
        if atr_s[i] > 0:
            pdi[i] = 100.0 * pdm_s[i] / atr_s[i]
            mdi[i] = 100.0 * mdm_s[i] / atr_s[i]
        else:
            pdi[i] = 0.0
            mdi[i] = 0.0
        di_sum = pdi[i] + mdi[i]
        dx[i] = 100.0 * abs(pdi[i] - mdi[i]) / di_sum if di_sum > 0 else 0.0

    adx = np.full(n, np.nan)
    adx_start = 2 * period
    if n > adx_start:
        adx[adx_start] = np.mean(dx[period:adx_start + 1])
        for i in range(adx_start + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    result = {}
    for i in range(n):
        if not np.isnan(adx[i]):
            result[daily_bars[i]["date"]] = (adx[i], pdi[i], mdi[i])
    return result


# ── Load crosses ────────────────────────────────────────────────────────────

def load_crosses():
    crosses = []
    fpath = os.path.join(SCRIPT_DIR, "ema_4h_crosses.csv")
    with open(fpath) as f:
        for row in csv.DictReader(f):
            crosses.append(row)
    return crosses


# ── Main ────────────────────────────────────────────────────────────────────

crosses = load_crosses()
tickers = sorted(set(c["ticker"] for c in crosses))

# Build daily bars + ADX + close lookup per ticker
daily_cache = {}
adx_cache = {}
close_by_date = {}  # ticker → {date: close}
dates_by_ticker = {}  # ticker → sorted list of dates

for ticker in tickers:
    m5 = load_m5(ticker)
    daily = aggregate_daily(m5)
    daily_cache[ticker] = daily
    adx_cache[ticker] = compute_adx(daily)
    close_by_date[ticker] = {d["date"]: d["close"] for d in daily}
    dates_by_ticker[ticker] = sorted(close_by_date[ticker].keys())

print(f"Loaded {len(tickers)} tickers, {len(crosses)} crosses total")

# ── Part A: ADX at cross, bucketed forward returns ──────────────────────────

ADX_BUCKETS = [
    ("<15", 0, 15),
    ("15-20", 15, 20),
    ("20-25", 20, 25),
    ("25-30", 25, 30),
    ("30+", 30, 999),
]

bucket_data = {b[0]: [] for b in ADX_BUCKETS}
cross_details = []

for c in crosses:
    ticker = c["ticker"]
    date = c["date"]
    direction = c["direction"]

    if ticker not in adx_cache or date not in adx_cache[ticker]:
        continue

    adx_val, pdi_val, mdi_val = adx_cache[ticker][date]
    dates = dates_by_ticker[ticker]
    if date not in dates:
        continue
    idx = dates.index(date)

    # Forward 1-day return
    fwd1_ret = None
    if idx + 1 < len(dates):
        c0 = close_by_date[ticker][date]
        c1 = close_by_date[ticker][dates[idx + 1]]
        if c0 > 0:
            fwd1_ret = (c1 - c0) / c0

    # Forward 3-day return
    fwd3_ret = None
    if idx + 3 < len(dates):
        c0 = close_by_date[ticker][date]
        c3 = close_by_date[ticker][dates[idx + 3]]
        if c0 > 0:
            fwd3_ret = (c3 - c0) / c0

    detail = {
        "ticker": ticker,
        "date": date,
        "direction": direction,
        "adx": adx_val,
        "pdi": pdi_val,
        "mdi": mdi_val,
        "fwd1_ret": fwd1_ret,
        "fwd3_ret": fwd3_ret,
    }
    cross_details.append(detail)

    if fwd1_ret is not None:
        for label, lo, hi in ADX_BUCKETS:
            if lo <= adx_val < hi:
                bucket_data[label].append(detail)
                break

# ── Part B: UP vs DOWN forward returns ──────────────────────────────────────

up_crosses = [d for d in cross_details if d["direction"] == "UP"]
down_crosses = [d for d in cross_details if d["direction"] == "DOWN"]

# Baseline: average daily return across all tickers and all dates
all_daily_rets = []
for ticker in tickers:
    dates = dates_by_ticker[ticker]
    for i in range(1, len(dates)):
        c0 = close_by_date[ticker][dates[i - 1]]
        c1 = close_by_date[ticker][dates[i]]
        if c0 > 0:
            all_daily_rets.append((c1 - c0) / c0)

baseline_1d = np.mean(all_daily_rets) if all_daily_rets else 0

# 3-day baseline
all_3d_rets = []
for ticker in tickers:
    dates = dates_by_ticker[ticker]
    for i in range(len(dates) - 3):
        c0 = close_by_date[ticker][dates[i]]
        c3 = close_by_date[ticker][dates[i + 3]]
        if c0 > 0:
            all_3d_rets.append((c3 - c0) / c0)

baseline_3d = np.mean(all_3d_rets) if all_3d_rets else 0


def ret_stats(details, key):
    vals = [d[key] for d in details if d[key] is not None]
    if not vals:
        return {"mean": 0, "median": 0, "std": 0, "n": 0, "pct_pos": 0}
    arr = np.array(vals)
    return {
        "mean": np.mean(arr),
        "median": np.median(arr),
        "std": np.std(arr),
        "n": len(arr),
        "pct_pos": 100.0 * np.sum(arr > 0) / len(arr),
    }


# ── Print ───────────────────────────────────────────────────────────────────

lines = []


def p(line=""):
    print(line)
    lines.append(line)


p("=" * 85)
p("AUDIT E3: ADX AT 4H EMA CROSSES + FORWARD RETURN ANALYSIS")
p("=" * 85)
p()

# Part A
p("PART A: ADX BUCKET ANALYSIS (all crosses, fwd 1-day return)")
p(f"  {'Bucket':<8} {'N':>5} {'MeanRet':>10} {'MedRet':>10} {'StdRet':>10} {'%Pos':>7}")
p(f"  {'-'*55}")
for label, lo, hi in ADX_BUCKETS:
    data = bucket_data[label]
    s = ret_stats(data, "fwd1_ret")
    p(f"  {label:<8} {s['n']:>5} {s['mean']*100:>9.3f}% {s['median']*100:>9.3f}% "
      f"{s['std']*100:>9.3f}% {s['pct_pos']:>6.1f}%")

p()

# UP-only ADX buckets
p("PART A (UP crosses only): ADX BUCKET → fwd 1-day return")
p(f"  {'Bucket':<8} {'N':>5} {'MeanRet':>10} {'MedRet':>10} {'%Pos':>7}")
p(f"  {'-'*45}")
for label, lo, hi in ADX_BUCKETS:
    data = [d for d in bucket_data[label] if d["direction"] == "UP"]
    s = ret_stats(data, "fwd1_ret")
    p(f"  {label:<8} {s['n']:>5} {s['mean']*100:>9.3f}% {s['median']*100:>9.3f}% {s['pct_pos']:>6.1f}%")

p()

# ADX threshold scan
p("ADX THRESHOLD SCAN (UP crosses only, fwd 1-day):")
up_with_adx = [d for d in up_crosses if d["fwd1_ret"] is not None]
p(f"  {'Thresh':>8} {'N>=':>5} {'MeanRet':>10} {'MedRet':>10} {'%Pos':>7}  {'N<':>5} {'MeanRet<':>10}")
p(f"  {'-'*65}")
for thresh in [12, 15, 18, 20, 22, 25, 30]:
    above = [d for d in up_with_adx if d["adx"] >= thresh]
    below = [d for d in up_with_adx if d["adx"] < thresh]
    sa = ret_stats(above, "fwd1_ret")
    sb = ret_stats(below, "fwd1_ret")
    p(f"  ADX>={thresh:<3} {sa['n']:>5} {sa['mean']*100:>9.3f}% {sa['median']*100:>9.3f}% "
      f"{sa['pct_pos']:>6.1f}%  {sb['n']:>5} {sb['mean']*100:>9.3f}%")

p()
p(f"  Claim: ADX >= 18-20 minimum for good signals")
# Assess
for thresh in [18, 20]:
    above = [d for d in up_with_adx if d["adx"] >= thresh]
    below = [d for d in up_with_adx if d["adx"] < thresh]
    sa = ret_stats(above, "fwd1_ret")
    sb = ret_stats(below, "fwd1_ret")
    diff = sa["mean"] - sb["mean"]
    p(f"  ADX>={thresh}: mean={sa['mean']*100:.3f}% vs ADX<{thresh}: mean={sb['mean']*100:.3f}% → "
      f"diff={diff*100:+.3f}%  {'CONFIRMED' if diff > 0 else 'NOT CONFIRMED'}")

p()

# Part B
p("─" * 85)
p("PART B: FORWARD RETURNS — UP vs DOWN CROSSES vs BASELINE")
p("─" * 85)
p()

su1 = ret_stats(up_crosses, "fwd1_ret")
sd1 = ret_stats(down_crosses, "fwd1_ret")
su3 = ret_stats(up_crosses, "fwd3_ret")
sd3 = ret_stats(down_crosses, "fwd3_ret")

p(f"  {'Group':<14} {'N':>5} {'Fwd1d Mean':>12} {'Fwd1d Med':>12} {'%Pos':>7}  "
  f"{'Fwd3d Mean':>12} {'Fwd3d Med':>12} {'%Pos':>7}")
p(f"  {'-'*85}")
p(f"  {'UP crosses':<14} {su1['n']:>5} {su1['mean']*100:>11.3f}% {su1['median']*100:>11.3f}% "
  f"{su1['pct_pos']:>6.1f}%  {su3['mean']*100:>11.3f}% {su3['median']*100:>11.3f}% {su3['pct_pos']:>6.1f}%")
p(f"  {'DOWN crosses':<14} {sd1['n']:>5} {sd1['mean']*100:>11.3f}% {sd1['median']*100:>11.3f}% "
  f"{sd1['pct_pos']:>6.1f}%  {sd3['mean']*100:>11.3f}% {sd3['median']*100:>11.3f}% {sd3['pct_pos']:>6.1f}%")
p(f"  {'Baseline':<14} {'':>5} {baseline_1d*100:>11.3f}% {'':>12} {'':>7}  "
  f"{baseline_3d*100:>11.3f}%")

p()

# UP crosses excess return
excess_1d = su1["mean"] - baseline_1d
excess_3d = su3["mean"] - baseline_3d
p(f"  UP crosses excess over baseline:")
p(f"    1-day: {excess_1d*100:+.3f}%  {'(positive edge)' if excess_1d > 0 else '(no edge)'}")
p(f"    3-day: {excess_3d*100:+.3f}%  {'(positive edge)' if excess_3d > 0 else '(no edge)'}")

# DOWN crosses: do they predict negative returns?
p(f"  DOWN crosses vs baseline:")
p(f"    1-day: {sd1['mean']*100:+.3f}% vs baseline {baseline_1d*100:+.3f}%  "
  f"diff={((sd1['mean']-baseline_1d)*100):+.3f}%")
p(f"    3-day: {sd3['mean']*100:+.3f}% vs baseline {baseline_3d*100:+.3f}%  "
  f"diff={((sd3['mean']-baseline_3d)*100):+.3f}%")

p()

# UP vs DOWN spread
spread_1d = su1["mean"] - sd1["mean"]
spread_3d = su3["mean"] - sd3["mean"]
p(f"  UP - DOWN spread:")
p(f"    1-day: {spread_1d*100:+.3f}%")
p(f"    3-day: {spread_3d*100:+.3f}%")
p(f"    Are UP crosses predictive? {'YES (positive spread)' if spread_1d > 0 else 'WEAK/NO'}")

p()

# Per-ticker Part B
p("PER-TICKER: UP cross fwd 1-day mean return")
p(f"  {'Ticker':<8} {'N_UP':>5} {'Fwd1d':>10} {'N_DN':>5} {'Fwd1d':>10} {'Spread':>10}")
p(f"  {'-'*55}")
for ticker in tickers:
    up_t = [d for d in up_crosses if d["ticker"] == ticker]
    dn_t = [d for d in down_crosses if d["ticker"] == ticker]
    su = ret_stats(up_t, "fwd1_ret")
    sd = ret_stats(dn_t, "fwd1_ret")
    spread = su["mean"] - sd["mean"] if su["n"] > 0 and sd["n"] > 0 else 0
    p(f"  {ticker:<8} {su['n']:>5} {su['mean']*100:>9.3f}% {sd['n']:>5} {sd['mean']*100:>9.3f}% "
      f"{spread*100:>9.3f}%")

# ── Save CSVs ───────────────────────────────────────────────────────────────

# E3 ADX CSV
adx_path = os.path.join(SCRIPT_DIR, "audit_e3_adx.csv")
adx_rows = []
for d in cross_details:
    adx_rows.append({
        "ticker": d["ticker"],
        "date": d["date"],
        "direction": d["direction"],
        "adx": f"{d['adx']:.2f}",
        "pdi": f"{d['pdi']:.2f}",
        "mdi": f"{d['mdi']:.2f}",
        "fwd1_ret": f"{d['fwd1_ret']:.6f}" if d["fwd1_ret"] is not None else "",
        "fwd3_ret": f"{d['fwd3_ret']:.6f}" if d["fwd3_ret"] is not None else "",
    })
with open(adx_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(adx_rows[0].keys()))
    writer.writeheader()
    writer.writerows(adx_rows)
p(f"\nSaved: {adx_path}")

# E3 EMA forward CSV (summary)
ema_path = os.path.join(SCRIPT_DIR, "audit_e3_ema_forward.csv")
summary_rows = []
for label, lo, hi in ADX_BUCKETS:
    for direction in ["UP", "DOWN", "ALL"]:
        if direction == "ALL":
            data = bucket_data[label]
        else:
            data = [d for d in bucket_data[label] if d["direction"] == direction]
        s1 = ret_stats(data, "fwd1_ret")
        s3 = ret_stats(data, "fwd3_ret")
        summary_rows.append({
            "adx_bucket": label,
            "direction": direction,
            "n": s1["n"],
            "fwd1d_mean": f"{s1['mean']*100:.4f}",
            "fwd1d_median": f"{s1['median']*100:.4f}",
            "fwd1d_pct_pos": f"{s1['pct_pos']:.1f}",
            "fwd3d_mean": f"{s3['mean']*100:.4f}",
            "fwd3d_median": f"{s3['median']*100:.4f}",
            "fwd3d_pct_pos": f"{s3['pct_pos']:.1f}",
        })

# Add overall rows
for direction in ["UP", "DOWN", "ALL"]:
    if direction == "UP":
        data = up_crosses
    elif direction == "DOWN":
        data = down_crosses
    else:
        data = cross_details
    s1 = ret_stats(data, "fwd1_ret")
    s3 = ret_stats(data, "fwd3_ret")
    summary_rows.append({
        "adx_bucket": "ALL",
        "direction": direction,
        "n": s1["n"],
        "fwd1d_mean": f"{s1['mean']*100:.4f}",
        "fwd1d_median": f"{s1['median']*100:.4f}",
        "fwd1d_pct_pos": f"{s1['pct_pos']:.1f}",
        "fwd3d_mean": f"{s3['mean']*100:.4f}",
        "fwd3d_median": f"{s3['median']*100:.4f}",
        "fwd3d_pct_pos": f"{s3['pct_pos']:.1f}",
    })

with open(ema_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
    writer.writeheader()
    writer.writerows(summary_rows)
p(f"Saved: {ema_path}")
