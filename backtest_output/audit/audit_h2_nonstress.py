#!/usr/bin/env python3
"""Audit H2 Part A: Non-stress noon reversal — is it significant?

For ALL trading days, pick bottom-2 tickers at noon by AM return,
compute return 12:00→15:30, separate stress vs non-stress.
t-test: is non-stress reversal significantly > 0?
S21 claim: stress +1.51%, non-stress +0.78%.
"""

import csv
import json
import os
from datetime import datetime, time as dtime
from collections import defaultdict
import numpy as np
from scipy import stats as sp_stats

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(SCRIPT_DIR, "..", "..")

NOON = dtime(12, 0)
OPEN = dtime(9, 30)
EXIT = dtime(15, 30)
N_LAGGARDS = 2

# ── Load stress days ──────────────────────────────────────────────────────
with open(os.path.join(ROOT, "backtest_output", "stress_days.json")) as f:
    stress_set = set(json.load(f))

# ── Find tickers (exclude SPY, VIXY) ─────────────────────────────────────
ticker_files = {}
for fname in os.listdir(os.path.join(ROOT, "backtest_output")):
    if fname.endswith("_m5_regsess.csv"):
        ticker = fname.replace("_m5_regsess.csv", "")
        if ticker not in ("SPY", "VIXY"):
            ticker_files[ticker] = os.path.join(ROOT, "backtest_output", fname)

# ── Load all ticker M5 data ──────────────────────────────────────────────
all_data = {}  # ticker -> date -> list of bars
all_dates = set()
for ticker, fpath in ticker_files.items():
    by_date = defaultdict(list)
    with open(fpath) as f:
        for row in csv.DictReader(f):
            dt = datetime.strptime(row["Datetime"], "%Y-%m-%d %H:%M:%S")
            d = dt.strftime("%Y-%m-%d")
            by_date[d].append({
                "time": dt.time(),
                "open": float(row["Open"]),
                "close": float(row["Close"]),
            })
    all_data[ticker] = dict(by_date)
    all_dates.update(by_date.keys())

print(f"Tickers: {len(ticker_files)} | Trading days: {len(all_dates)}")
print(f"Stress days in data: {len(stress_set & all_dates)}")

# ── For each day: find bottom-2, compute noon→15:30 return ────────────────
results = []

for day in sorted(all_dates):
    am_returns = {}
    for ticker, by_date in all_data.items():
        bars = by_date.get(day, [])
        if not bars:
            continue
        bar_by_time = {b["time"]: b for b in bars}
        open_bar = bar_by_time.get(OPEN)
        noon_bar = bar_by_time.get(NOON)
        if open_bar and noon_bar:
            am_returns[ticker] = (noon_bar["open"] - open_bar["open"]) / open_bar["open"]

    if len(am_returns) < N_LAGGARDS:
        continue

    sorted_tickers = sorted(am_returns.items(), key=lambda x: x[1])
    laggards = sorted_tickers[:N_LAGGARDS]

    for ticker, am_ret in laggards:
        bars = all_data[ticker][day]
        bar_by_time = {b["time"]: b for b in bars}
        noon_bar = bar_by_time.get(NOON)
        exit_bar = bar_by_time.get(EXIT)
        if not noon_bar or not exit_bar:
            continue
        entry_price = noon_bar["open"]
        exit_price = exit_bar["close"]
        pm_ret = (exit_price - entry_price) / entry_price
        is_stress = day in stress_set

        results.append({
            "date": day,
            "ticker": ticker,
            "am_return": am_ret,
            "pm_return": pm_ret,
            "is_stress": is_stress,
        })

stress_rets = np.array([r["pm_return"] for r in results if r["is_stress"]])
nonstress_rets = np.array([r["pm_return"] for r in results if not r["is_stress"]])

print(f"\nTotal trades: {len(results)}")
print(f"  Stress:     {len(stress_rets)}")
print(f"  Non-stress: {len(nonstress_rets)}")

print()
print("=" * 80)
print("  AUDIT H2: STRESS vs NON-STRESS NOON REVERSAL")
print("=" * 80)

# Stress stats
print(f"\n  STRESS DAYS (N={len(stress_rets)}):")
print(f"    Mean return:   {np.mean(stress_rets)*100:+.3f}%")
print(f"    Median return: {np.median(stress_rets)*100:+.3f}%")
print(f"    Std:           {np.std(stress_rets)*100:.3f}%")
print(f"    Win rate:      {100*np.mean(stress_rets > 0):.1f}%")
t_s, p_s = sp_stats.ttest_1samp(stress_rets, 0)
print(f"    t-test vs 0:   t={t_s:.3f}, p={p_s:.4f} {'***' if p_s<0.001 else '**' if p_s<0.01 else '*' if p_s<0.05 else 'ns'}")

# Non-stress stats
print(f"\n  NON-STRESS DAYS (N={len(nonstress_rets)}):")
print(f"    Mean return:   {np.mean(nonstress_rets)*100:+.3f}%")
print(f"    Median return: {np.median(nonstress_rets)*100:+.3f}%")
print(f"    Std:           {np.std(nonstress_rets)*100:.3f}%")
print(f"    Win rate:      {100*np.mean(nonstress_rets > 0):.1f}%")
t_ns, p_ns = sp_stats.ttest_1samp(nonstress_rets, 0)
print(f"    t-test vs 0:   t={t_ns:.3f}, p={p_ns:.4f} {'***' if p_ns<0.001 else '**' if p_ns<0.01 else '*' if p_ns<0.05 else 'ns'}")

# Two-sample test
t_2, p_2 = sp_stats.ttest_ind(stress_rets, nonstress_rets)
print(f"\n  TWO-SAMPLE t-test (stress vs non-stress):")
print(f"    t={t_2:.3f}, p={p_2:.4f} {'***' if p_2<0.001 else '**' if p_2<0.01 else '*' if p_2<0.05 else 'ns'}")

# S21 claim comparison
print(f"\n  S21 CLAIM COMPARISON:")
print(f"    {'':>20} {'Claimed':>10} {'Actual':>10} {'Match':>8}")
print(f"    {'-'*50}")
print(f"    {'Stress':>20} {'+1.51%':>10} {np.mean(stress_rets)*100:>+9.3f}% {'~' if abs(np.mean(stress_rets)*100 - 1.51) < 0.5 else 'NO':>8}")
print(f"    {'Non-stress':>20} {'+0.78%':>10} {np.mean(nonstress_rets)*100:>+9.3f}% {'~' if abs(np.mean(nonstress_rets)*100 - 0.78) < 0.3 else 'NO':>8}")

# ── Save CSV ──────────────────────────────────────────────────────────────
csv_path = os.path.join(SCRIPT_DIR, "audit_h2_nonstress.csv")
with open(csv_path, "w", newline="") as f:
    fields = ["date", "ticker", "am_return", "pm_return", "is_stress"]
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    for r in results:
        out = {k: (f"{v:.6f}" if isinstance(v, float) else v) for k, v in r.items()}
        writer.writerow(out)
print(f"\nSaved: {csv_path}")
