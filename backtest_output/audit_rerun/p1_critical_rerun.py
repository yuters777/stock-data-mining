#!/usr/bin/env python3
"""
Part 3 — P1 Critical Re-Run: H1, H2, S21-P1, S21-P2, S21-P9.

Runs each test with BOTH buggy (_m5_regsess.csv) and FIXED (_m5_regsess_FIXED.csv)
data to compare results. Only data loading changes; all analysis logic preserved.
"""

import csv
import json
import os
from collections import defaultdict
from datetime import datetime, time as dtime

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(ROOT, "phase1_test0_test1.py")):
    ROOT = os.path.dirname(ROOT)

BACKTEST_DIR = os.path.join(ROOT, "backtest_output")
OUT_DIR = os.path.join(BACKTEST_DIR, "audit_rerun")
os.makedirs(OUT_DIR, exist_ok=True)

# ── Config ────────────────────────────────────────────────────────────
NOON = dtime(12, 0)
OPEN = dtime(9, 30)
EXIT_1530 = dtime(15, 30)
EXIT_1550 = dtime(15, 50)
N_LAGGARDS = 2

EXIT_TIMES = [dtime(14,30), dtime(14,45), dtime(15,0), dtime(15,15), dtime(15,30), dtime(15,45)]
EXIT_LABELS = ["14:30", "14:45", "15:00", "15:15", "15:30", "15:45"]

with open(os.path.join(BACKTEST_DIR, "stress_days.json")) as f:
    STRESS_SET = set(json.load(f))


def load_ticker_data(suffix="_m5_regsess.csv", stress_only=False):
    """Load all tickers' M5 data from files with given suffix."""
    ticker_data = {}
    for fname in os.listdir(BACKTEST_DIR):
        if not fname.endswith(suffix):
            continue
        ticker = fname.replace(suffix, "")
        if ticker in ("SPY", "VIXY"):
            continue
        fpath = os.path.join(BACKTEST_DIR, fname)
        by_date = defaultdict(list)
        with open(fpath) as f:
            for row in csv.DictReader(f):
                dt = datetime.strptime(row["Datetime"], "%Y-%m-%d %H:%M:%S")
                d = dt.strftime("%Y-%m-%d")
                if stress_only and d not in STRESS_SET:
                    continue
                by_date[d].append({
                    "time": dt.time(),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                })
        ticker_data[ticker] = dict(by_date)
    return ticker_data


def get_bar(bars, target_time):
    """Find bar matching target time."""
    for b in bars:
        if b["time"] == target_time:
            return b
    return None


def compute_am_return(bars):
    """AM return from 09:30 open to 12:00 open."""
    ob = get_bar(bars, OPEN)
    nb = get_bar(bars, NOON)
    if ob and nb and ob["open"] > 0:
        return (nb["open"] - ob["open"]) / ob["open"]
    return None


# ═══════════════════════════════════════════════════════════════
# H1: Exit Grid (stress days only)
# ═══════════════════════════════════════════════════════════════

def run_h1(all_data, label):
    """H1: For each stress day, bottom-2 by AM return, compute exit returns."""
    results_by_exit = {l: [] for l in EXIT_LABELS}

    for day in sorted(STRESS_SET):
        am_returns = {}
        for ticker, by_date in all_data.items():
            bars = by_date.get(day, [])
            am = compute_am_return(bars)
            if am is not None:
                am_returns[ticker] = am
        if len(am_returns) < N_LAGGARDS:
            continue

        laggards = sorted(am_returns.items(), key=lambda x: x[1])[:N_LAGGARDS]
        for ticker, am in laggards:
            bars = all_data[ticker][day]
            noon_bar = get_bar(bars, NOON)
            if not noon_bar:
                continue
            entry = noon_bar["open"]
            if entry <= 0:
                continue
            bar_map = {b["time"]: b for b in bars}
            for et, el in zip(EXIT_TIMES, EXIT_LABELS):
                eb = bar_map.get(et)
                if eb:
                    ret = (eb["close"] - entry) / entry
                    results_by_exit[el].append(ret)

    print(f"\n  H1 Exit Grid ({label}):")
    print(f"  {'Exit':>8s}  {'Mean':>8s}  {'WR':>7s}  {'Sharpe':>8s}  {'N':>5s}")
    for el in EXIT_LABELS:
        rets = np.array(results_by_exit[el])
        if len(rets) == 0:
            print(f"  {el:>8s}  {'N/A':>8s}")
            continue
        mn = rets.mean() * 100
        wr = (rets > 0).mean() * 100
        sh = rets.mean() / rets.std() if rets.std() > 0 else 0
        print(f"  {el:>8s}  {mn:>+7.3f}%  {wr:>6.1f}%  {sh:>8.3f}  {len(rets):>5d}")
    return results_by_exit


# ═══════════════════════════════════════════════════════════════
# H2: Noon Reversal (all days, stress vs non-stress)
# ═══════════════════════════════════════════════════════════════

def run_h2(all_data, label):
    """H2: bottom-2 at noon, exit 15:30, stress vs non-stress."""
    stress_rets, nonstress_rets = [], []

    all_dates = set()
    for by_date in all_data.values():
        all_dates.update(by_date.keys())

    for day in sorted(all_dates):
        am_returns = {}
        for ticker, by_date in all_data.items():
            bars = by_date.get(day, [])
            am = compute_am_return(bars)
            if am is not None:
                am_returns[ticker] = am
        if len(am_returns) < N_LAGGARDS:
            continue

        laggards = sorted(am_returns.items(), key=lambda x: x[1])[:N_LAGGARDS]
        is_stress = day in STRESS_SET

        for ticker, am in laggards:
            bars = all_data[ticker][day]
            noon_bar = get_bar(bars, NOON)
            exit_bar = get_bar(bars, EXIT_1530)
            if not noon_bar or not exit_bar:
                continue
            entry = noon_bar["open"]
            if entry <= 0:
                continue
            ret = (exit_bar["close"] - entry) / entry
            if is_stress:
                stress_rets.append(ret)
            else:
                nonstress_rets.append(ret)

    sr = np.array(stress_rets) * 100
    nr = np.array(nonstress_rets) * 100

    print(f"\n  H2 Noon Reversal ({label}):")
    for name, arr in [("Stress", sr), ("Non-stress", nr), ("All", np.concatenate([sr, nr]))]:
        if len(arr) == 0:
            print(f"  {name:>12s}: N=0")
            continue
        print(f"  {name:>12s}: mean={arr.mean():+.3f}%, WR={100*(arr>0).mean():.1f}%, N={len(arr)}")

    return {"stress": sr, "nonstress": nr}


# ═══════════════════════════════════════════════════════════════
# S21-P1: Stress MR Core (laggard reversal on stress days)
# ═══════════════════════════════════════════════════════════════

def run_s21_p1(all_data, label):
    """S21 P1: Bottom-2 at noon on stress days, exit 15:30."""
    rets = []
    for day in sorted(STRESS_SET):
        am_returns = {}
        for ticker, by_date in all_data.items():
            bars = by_date.get(day, [])
            am = compute_am_return(bars)
            if am is not None:
                am_returns[ticker] = am
        if len(am_returns) < N_LAGGARDS:
            continue
        laggards = sorted(am_returns.items(), key=lambda x: x[1])[:N_LAGGARDS]
        for ticker, am in laggards:
            bars = all_data[ticker][day]
            noon_bar = get_bar(bars, NOON)
            exit_bar = get_bar(bars, EXIT_1530)
            if not noon_bar or not exit_bar:
                continue
            entry = noon_bar["open"]
            if entry <= 0:
                continue
            ret = (exit_bar["close"] - entry) / entry
            rets.append(ret)

    arr = np.array(rets) * 100
    print(f"\n  S21-P1 Stress MR ({label}):")
    if len(arr):
        pf = arr[arr > 0].sum() / abs(arr[arr < 0].sum()) if (arr < 0).any() else float("inf")
        print(f"    Mean={arr.mean():+.3f}%, WR={100*(arr>0).mean():.1f}%, PF={pf:.1f}, N={len(arr)}")
    return arr


# ═══════════════════════════════════════════════════════════════
# S21-P2: Leader underperformance (top-2 on stress days)
# ═══════════════════════════════════════════════════════════════

def run_s21_p2(all_data, label):
    """S21 P2: TOP-2 at noon on stress days, exit 15:30."""
    rets = []
    for day in sorted(STRESS_SET):
        am_returns = {}
        for ticker, by_date in all_data.items():
            bars = by_date.get(day, [])
            am = compute_am_return(bars)
            if am is not None:
                am_returns[ticker] = am
        if len(am_returns) < N_LAGGARDS:
            continue
        leaders = sorted(am_returns.items(), key=lambda x: x[1], reverse=True)[:N_LAGGARDS]
        for ticker, am in leaders:
            bars = all_data[ticker][day]
            noon_bar = get_bar(bars, NOON)
            exit_bar = get_bar(bars, EXIT_1530)
            if not noon_bar or not exit_bar:
                continue
            entry = noon_bar["open"]
            if entry <= 0:
                continue
            ret = (exit_bar["close"] - entry) / entry
            rets.append(ret)

    arr = np.array(rets) * 100
    print(f"\n  S21-P2 Leader PM ({label}):")
    if len(arr):
        wr = 100 * (arr > 0).mean()
        print(f"    Mean={arr.mean():+.3f}%, WR={wr:.1f}%, N={len(arr)}")
    return arr


# ═══════════════════════════════════════════════════════════════
# S21-P9: Non-stress generic reversal
# ═══════════════════════════════════════════════════════════════

def run_s21_p9(all_data, label):
    """S21 P9: Bottom-2 at noon on NON-stress days, exit 15:30."""
    rets = []
    all_dates = set()
    for by_date in all_data.values():
        all_dates.update(by_date.keys())

    non_stress = sorted(all_dates - STRESS_SET)
    for day in non_stress:
        am_returns = {}
        for ticker, by_date in all_data.items():
            bars = by_date.get(day, [])
            am = compute_am_return(bars)
            if am is not None:
                am_returns[ticker] = am
        if len(am_returns) < N_LAGGARDS:
            continue
        laggards = sorted(am_returns.items(), key=lambda x: x[1])[:N_LAGGARDS]
        for ticker, am in laggards:
            bars = all_data[ticker][day]
            noon_bar = get_bar(bars, NOON)
            exit_bar = get_bar(bars, EXIT_1530)
            if not noon_bar or not exit_bar:
                continue
            entry = noon_bar["open"]
            if entry <= 0:
                continue
            ret = (exit_bar["close"] - entry) / entry
            rets.append(ret)

    arr = np.array(rets) * 100
    print(f"\n  S21-P9 Non-stress ({label}):")
    if len(arr):
        wr = 100 * (arr > 0).mean()
        print(f"    Mean={arr.mean():+.3f}%, WR={wr:.1f}%, N={len(arr)}")
    return arr


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("P1 CRITICAL RE-RUN: Buggy vs FIXED data comparison")
    print("=" * 70)

    # Load both datasets
    print("\nLoading BUGGY data (_m5_regsess.csv)...")
    buggy_all = load_ticker_data("_m5_regsess.csv", stress_only=False)
    print(f"  {len(buggy_all)} tickers loaded")

    print("Loading FIXED data (_m5_regsess_FIXED.csv)...")
    fixed_all = load_ticker_data("_m5_regsess_FIXED.csv", stress_only=False)
    print(f"  {len(fixed_all)} tickers loaded")

    # ── H1 ──
    print("\n" + "=" * 70)
    print("H1: EXIT GRID")
    print("=" * 70)
    h1_buggy = run_h1(buggy_all, "BUGGY")
    h1_fixed = run_h1(fixed_all, "FIXED")

    # ── H2 ──
    print("\n" + "=" * 70)
    print("H2: NOON REVERSAL")
    print("=" * 70)
    h2_buggy = run_h2(buggy_all, "BUGGY")
    h2_fixed = run_h2(fixed_all, "FIXED")

    # ── S21-P1 ──
    print("\n" + "=" * 70)
    print("S21-P1: STRESS MR CORE")
    print("=" * 70)
    p1_buggy = run_s21_p1(buggy_all, "BUGGY")
    p1_fixed = run_s21_p1(fixed_all, "FIXED")

    # ── S21-P2 ──
    print("\n" + "=" * 70)
    print("S21-P2: LEADER UNDERPERFORMANCE")
    print("=" * 70)
    p2_buggy = run_s21_p2(buggy_all, "BUGGY")
    p2_fixed = run_s21_p2(fixed_all, "FIXED")

    # ── S21-P9 ──
    print("\n" + "=" * 70)
    print("S21-P9: NON-STRESS REVERSAL")
    print("=" * 70)
    p9_buggy = run_s21_p9(buggy_all, "BUGGY")
    p9_fixed = run_s21_p9(fixed_all, "FIXED")

    # ── SUMMARY ──
    print("\n" + "=" * 70)
    print("SUMMARY: P1 CRITICAL TESTS")
    print("=" * 70)
    print(f"\n{'Test':<15s}  {'Metric':<12s}  {'Buggy':>10s}  {'Fixed':>10s}  {'Delta':>10s}  {'Shift':>8s}")
    print("-" * 70)

    def row(test, metric, buggy_val, fixed_val, fmt="+.3f"):
        delta = fixed_val - buggy_val
        shift = abs(delta / buggy_val * 100) if buggy_val != 0 else float("inf")
        flag = " ⚠️" if shift > 30 else ""
        print(f"{test:<15s}  {metric:<12s}  {buggy_val:>10{fmt}}  {fixed_val:>10{fmt}}  "
              f"{delta:>10{fmt}}  {shift:>7.1f}%{flag}")

    # H1 at 15:30
    if h1_buggy["15:30"] and h1_fixed["15:30"]:
        b = np.array(h1_buggy["15:30"])
        f = np.array(h1_fixed["15:30"])
        row("H1 (15:30)", "Mean%", b.mean()*100, f.mean()*100)
        row("H1 (15:30)", "WR%", (b>0).mean()*100, (f>0).mean()*100, ".1f")

    # H2
    for seg, key in [("H2 Stress", "stress"), ("H2 NonStr", "nonstress")]:
        b, f = h2_buggy[key], h2_fixed[key]
        if len(b) and len(f):
            row(seg, "Mean%", b.mean(), f.mean())
            row(seg, "WR%", (b>0).mean()*100, (f>0).mean()*100, ".1f")

    # S21
    for name, b, f in [("S21-P1", p1_buggy, p1_fixed),
                         ("S21-P2", p2_buggy, p2_fixed),
                         ("S21-P9", p9_buggy, p9_fixed)]:
        if len(b) and len(f):
            row(name, "Mean%", b.mean(), f.mean())
            row(name, "WR%", (b>0).mean()*100, (f>0).mean()*100, ".1f")
            row(name, "N", len(b), len(f), "d")


if __name__ == "__main__":
    main()
