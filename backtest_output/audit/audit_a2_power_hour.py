#!/usr/bin/env python3
"""Audit A2: Power-hour (Zone 5) return analysis.

Compares absolute returns across intraday zones:
  Zone1: 09:30 → 10:30 (open drive)
  Zone2: 10:00 → 12:00 (mid-morning)
  Zone3: 12:00 → 13:30 (lunch)
  Zone5: 14:45 → 15:55 (power hour / closing drive)

Paired t-test: Zone5 vs Zone3 absolute returns.
Continuation analysis: does Zone5 direction match Zone1?
"""

import csv
import math
import os
import statistics
from collections import defaultdict
from datetime import datetime

BACKTEST_DIR = os.path.join(os.path.dirname(__file__), "..")
AUDIT_DIR = os.path.dirname(__file__)
EXCLUDE = {"BTC", "ETH"}

# Bar times for each zone boundary (using M5 bar start times)
# Bar at HH:MM has OHLC covering HH:MM to HH:MM+5
# "Price at 14:45" = close of bar starting at 14:45
# "Price at 16:00 close" = close of bar starting at 15:55 (last bar)
ZONE_BARS = {
    "09:30": (9, 30),
    "10:00": (10, 0),
    "10:30": (10, 30),
    "12:00": (12, 0),
    "13:30": (13, 30),
    "14:45": (14, 45),
    "15:55": (15, 55),
}


def hhmm_key(h, m):
    return f"{h:02d}:{m:02d}"


# ── Discover tickers ────────────────────────────────────────────────────────
tickers = sorted(
    f.replace("_m5_regsess.csv", "")
    for f in os.listdir(BACKTEST_DIR)
    if f.endswith("_m5_regsess.csv")
    and f.replace("_m5_regsess.csv", "") not in EXCLUDE
)
print(f"Tickers ({len(tickers)}): {', '.join(tickers)}")

# ── Collect zone prices per (ticker, date) ──────────────────────────────────
# For each ticker-day, store close prices at the boundary bars
rows_out = []  # list of dicts for CSV output
zone5_rets = []
zone3_rets = []
zone2_rets = []
zone1_rets = []

zone5_dirs = []  # +1 up, -1 down
zone1_dirs = []

for ticker in tickers:
    fpath = os.path.join(BACKTEST_DIR, f"{ticker}_m5_regsess.csv")

    # day → {hhmm_key: close_price}
    day_prices = defaultdict(dict)

    with open(fpath) as f:
        for row in csv.DictReader(f):
            dt = datetime.strptime(row["Datetime"], "%Y-%m-%d %H:%M:%S")
            date_str = dt.strftime("%Y-%m-%d")
            key = hhmm_key(dt.hour, dt.minute)
            # Only store bars we need
            if key in ("09:30", "10:00", "10:30", "12:00", "13:30", "14:45", "15:55"):
                day_prices[date_str][key] = float(row["Close"])

    for date_str in sorted(day_prices):
        p = day_prices[date_str]
        # Need all boundary prices
        needed = ["09:30", "10:00", "10:30", "12:00", "13:30", "14:45", "15:55"]
        if not all(k in p for k in needed):
            continue

        # Zone returns (absolute)
        z5 = abs(p["15:55"] - p["14:45"]) / p["14:45"]
        z3 = abs(p["13:30"] - p["12:00"]) / p["12:00"]
        z2 = abs(p["12:00"] - p["10:00"]) / p["10:00"]
        z1 = abs(p["10:30"] - p["09:30"]) / p["09:30"]

        # Signed returns for direction
        z5_signed = (p["15:55"] - p["14:45"]) / p["14:45"]
        z1_signed = (p["10:30"] - p["09:30"]) / p["09:30"]

        z5_dir = 1 if z5_signed > 0 else (-1 if z5_signed < 0 else 0)
        z1_dir = 1 if z1_signed > 0 else (-1 if z1_signed < 0 else 0)

        zone5_rets.append(z5)
        zone3_rets.append(z3)
        zone2_rets.append(z2)
        zone1_rets.append(z1)
        zone5_dirs.append(z5_dir)
        zone1_dirs.append(z1_dir)

        rows_out.append({
            "date": date_str,
            "ticker": ticker,
            "p_0930": f"{p['09:30']:.4f}",
            "p_1000": f"{p['10:00']:.4f}",
            "p_1030": f"{p['10:30']:.4f}",
            "p_1200": f"{p['12:00']:.4f}",
            "p_1330": f"{p['13:30']:.4f}",
            "p_1445": f"{p['14:45']:.4f}",
            "p_1555": f"{p['15:55']:.4f}",
            "zone1_abs_ret": f"{z1:.6f}",
            "zone2_abs_ret": f"{z2:.6f}",
            "zone3_abs_ret": f"{z3:.6f}",
            "zone5_abs_ret": f"{z5:.6f}",
            "zone1_dir": z1_dir,
            "zone5_dir": z5_dir,
        })

N = len(zone5_rets)
print(f"Ticker-days with complete data: {N}")

# ── Save CSV ────────────────────────────────────────────────────────────────
csv_path = os.path.join(AUDIT_DIR, "audit_a2_power_hour.csv")
with open(csv_path, "w", newline="") as f:
    fieldnames = list(rows_out[0].keys())
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows_out)
print(f"Saved: {csv_path}")

# ── Paired t-test (Zone5 vs Zone3) ──────────────────────────────────────────
# d_i = zone5_i - zone3_i for each ticker-day
diffs = [z5 - z3 for z5, z3 in zip(zone5_rets, zone3_rets)]
d_mean = statistics.mean(diffs)
d_std = statistics.stdev(diffs)
se = d_std / math.sqrt(N)
t_stat = d_mean / se
# Two-tailed p-value approximation using t-distribution
# For large N, use normal approximation
# For more precise: use the regularized incomplete beta function
df = N - 1


def t_cdf_approx(t, df):
    """Approximate two-tailed p-value for t-distribution."""
    # Use the approximation: for df > 30, t ~ N(0,1)
    # For better accuracy, use the relationship with the beta function
    x = df / (df + t * t)
    # Regularized incomplete beta function approximation
    # For large df, normal approximation is fine
    if df > 100:
        # Normal approximation
        from math import erfc
        p = erfc(abs(t) / math.sqrt(2))
        return p
    else:
        # Simple numerical integration (trapezoidal) for small df
        # This is a rough approximation
        from math import gamma
        coeff = gamma((df + 1) / 2) / (math.sqrt(df * math.pi) * gamma(df / 2))
        # Integrate from |t| to infinity
        steps = 10000
        upper = max(abs(t) + 50, 100)
        dt_step = (upper - abs(t)) / steps
        integral = 0.0
        for i in range(steps):
            x_val = abs(t) + (i + 0.5) * dt_step
            integral += coeff * (1 + x_val ** 2 / df) ** (-(df + 1) / 2) * dt_step
        return 2 * integral  # two-tailed


p_value = t_cdf_approx(t_stat, df)

# Also compute Zone5 vs Zone2
diffs_52 = [z5 - z2 for z5, z2 in zip(zone5_rets, zone2_rets)]
d52_mean = statistics.mean(diffs_52)
d52_std = statistics.stdev(diffs_52)
se52 = d52_std / math.sqrt(N)
t52 = d52_mean / se52
p52 = t_cdf_approx(t52, df)

# ── Continuation analysis ───────────────────────────────────────────────────
# How often does Zone5 direction match Zone1 direction?
n_both_nonzero = sum(1 for z1d, z5d in zip(zone1_dirs, zone5_dirs) if z1d != 0 and z5d != 0)
n_continuation = sum(1 for z1d, z5d in zip(zone1_dirs, zone5_dirs) if z1d != 0 and z5d != 0 and z1d == z5d)
n_reversal = n_both_nonzero - n_continuation
cont_pct = 100.0 * n_continuation / n_both_nonzero if n_both_nonzero > 0 else 0

# Zone stats
z5_mean = statistics.mean(zone5_rets) * 100
z3_mean = statistics.mean(zone3_rets) * 100
z2_mean = statistics.mean(zone2_rets) * 100
z1_mean = statistics.mean(zone1_rets) * 100
z5_med = statistics.median(zone5_rets) * 100
z3_med = statistics.median(zone3_rets) * 100
z2_med = statistics.median(zone2_rets) * 100
z1_med = statistics.median(zone1_rets) * 100
z5_std = statistics.stdev(zone5_rets) * 100
z3_std = statistics.stdev(zone3_rets) * 100
z2_std = statistics.stdev(zone2_rets) * 100
z1_std = statistics.stdev(zone1_rets) * 100

# ── Print results ───────────────────────────────────────────────────────────
output_lines = []


def p(line=""):
    print(line)
    output_lines.append(line)


p("=" * 72)
p("AUDIT A2: POWER HOUR (ZONE 5) RETURN ANALYSIS")
p("=" * 72)
p(f"N = {N} ticker-days, {len(tickers)} tickers, ~{N // len(tickers)} days each")
p()
p("ZONE DEFINITIONS:")
p("  Zone1: 09:30 → 10:30  (open drive, 60 min)")
p("  Zone2: 10:00 → 12:00  (mid-morning, 120 min)")
p("  Zone3: 12:00 → 13:30  (lunch, 90 min)")
p("  Zone5: 14:45 → 15:55  (closing drive / power hour, 70 min)")
p()
p("ABSOLUTE RETURN STATISTICS (%):")
p(f"  {'Zone':<8} {'Mean':>8} {'Median':>8} {'Std':>8} {'Duration':>10}")
p(f"  {'-' * 46}")
p(f"  {'Zone1':<8} {z1_mean:>7.3f}% {z1_med:>7.3f}% {z1_std:>7.3f}% {'60 min':>10}")
p(f"  {'Zone2':<8} {z2_mean:>7.3f}% {z2_med:>7.3f}% {z2_std:>7.3f}% {'120 min':>10}")
p(f"  {'Zone3':<8} {z3_mean:>7.3f}% {z3_med:>7.3f}% {z3_std:>7.3f}% {'90 min':>10}")
p(f"  {'Zone5':<8} {z5_mean:>7.3f}% {z5_med:>7.3f}% {z5_std:>7.3f}% {'70 min':>10}")
p()
p("PAIRED T-TEST: Zone5 vs Zone3 (|ret| difference)")
p(f"  Mean diff (Z5 - Z3):  {d_mean * 100:+.4f}%")
p(f"  Std of diffs:          {d_std * 100:.4f}%")
p(f"  t-statistic:           {t_stat:.4f}")
p(f"  p-value (two-tailed):  {p_value:.2e}")
p(f"  N:                     {N}")
p(f"  Result: {'Zone5 > Zone3 SIGNIFICANT' if p_value < 0.05 and d_mean > 0 else 'Zone5 < Zone3 SIGNIFICANT' if p_value < 0.05 and d_mean < 0 else 'NOT significant at α=0.05'}")
p()
p("PAIRED T-TEST: Zone5 vs Zone2 (|ret| difference)")
p(f"  Mean diff (Z5 - Z2):  {d52_mean * 100:+.4f}%")
p(f"  t-statistic:           {t52:.4f}")
p(f"  p-value (two-tailed):  {p52:.2e}")
p(f"  Result: {'Zone5 > Zone2 SIGNIFICANT' if p52 < 0.05 and d52_mean > 0 else 'Zone5 < Zone2 SIGNIFICANT' if p52 < 0.05 and d52_mean < 0 else 'NOT significant at α=0.05'}")
p()
p("ZONE1 → ZONE5 CONTINUATION ANALYSIS:")
p(f"  Ticker-days with nonzero direction in both zones: {n_both_nonzero}")
p(f"  Continuation (same dir): {n_continuation} ({cont_pct:.1f}%)")
p(f"  Reversal (opposite dir): {n_reversal} ({100 - cont_pct:.1f}%)")
p(f"  Interpretation: {'near 50% = no predictive relationship' if 45 < cont_pct < 55 else 'slight continuation bias' if cont_pct >= 55 else 'slight reversal bias'}")

# Binomial test: is continuation % significantly different from 50%?
# z = (p - 0.5) / sqrt(0.25 / n)
if n_both_nonzero > 0:
    z_binom = (cont_pct / 100 - 0.5) / math.sqrt(0.25 / n_both_nonzero)
    p_binom = math.erfc(abs(z_binom) / math.sqrt(2))
    p(f"  Binomial test vs 50%: z={z_binom:.3f}, p={p_binom:.4f}")
    p(f"  {'Statistically significant' if p_binom < 0.05 else 'NOT statistically significant'} at α=0.05")

# ── Per-ticker Zone5 vs Zone3 ──────────────────────────────────────────────
p()
p("PER-TICKER ZONE5 vs ZONE3 MEAN ABSOLUTE RETURN (%):")
p(f"  {'Ticker':<8} {'Z5 Mean':>8} {'Z3 Mean':>8} {'Z5-Z3':>8} {'Z5>Z3?':>8}")
p(f"  {'-' * 44}")

ticker_z5 = defaultdict(list)
ticker_z3 = defaultdict(list)
for row in rows_out:
    ticker_z5[row["ticker"]].append(float(row["zone5_abs_ret"]))
    ticker_z3[row["ticker"]].append(float(row["zone3_abs_ret"]))

n_z5_wins = 0
for t in tickers:
    m5 = statistics.mean(ticker_z5[t]) * 100
    m3 = statistics.mean(ticker_z3[t]) * 100
    diff = m5 - m3
    wins = "YES" if diff > 0 else "no"
    if diff > 0:
        n_z5_wins += 1
    p(f"  {t:<8} {m5:>7.3f}% {m3:>7.3f}% {diff:>+7.3f}% {wins:>8}")

p(f"\n  Zone5 > Zone3 in {n_z5_wins}/{len(tickers)} tickers")

# ── Save stats file ────────────────────────────────────────────────────────
stats_path = os.path.join(AUDIT_DIR, "audit_a2_stats.txt")
with open(stats_path, "w") as f:
    f.write("\n".join(output_lines) + "\n")
print(f"\nSaved: {stats_path}")
