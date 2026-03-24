#!/usr/bin/env python3
"""
Part 3 — P2/P3/P4 Continuous Re-Run.

Re-runs ALL remaining affected audit tests with FIXED data.
Compares buggy vs FIXED results for each test.
"""

import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, time as dtime
import numpy as np

ROOT = "/home/user/stock-data-mining"
BACKTEST_DIR = os.path.join(ROOT, "backtest_output")
AUDIT_DIR = os.path.join(BACKTEST_DIR, "audit")
OUT_DIR = os.path.join(BACKTEST_DIR, "audit_rerun")
os.makedirs(OUT_DIR, exist_ok=True)

NOON = dtime(12, 0)
OPEN = dtime(9, 30)
N_LAGGARDS = 2

with open(os.path.join(BACKTEST_DIR, "stress_days.json")) as f:
    STRESS_SET = set(json.load(f))

EXCLUDE = {"SPY", "VIXY"}


def load_all_tickers(suffix, exclude=EXCLUDE):
    """Load ticker M5 data from backtest_output."""
    data = {}
    for fname in os.listdir(BACKTEST_DIR):
        if not fname.endswith(suffix):
            continue
        tk = fname.replace(suffix, "")
        if tk in exclude:
            continue
        by_date = defaultdict(list)
        with open(os.path.join(BACKTEST_DIR, fname)) as f:
            for row in csv.DictReader(f):
                dt = datetime.strptime(row["Datetime"], "%Y-%m-%d %H:%M:%S")
                by_date[dt.strftime("%Y-%m-%d")].append({
                    "time": dt.time(), "hhmm": f"{dt.hour:02d}:{dt.minute:02d}",
                    "open": float(row["Open"]), "high": float(row["High"]),
                    "low": float(row["Low"]), "close": float(row["Close"]),
                    "volume": int(float(row["Volume"])),
                })
        data[tk] = dict(by_date)
    return data


def load_spy(suffix):
    """Load SPY separately (may be in exclude set)."""
    fname = f"SPY{suffix}"
    fpath = os.path.join(BACKTEST_DIR, fname)
    if not os.path.exists(fpath):
        return {}
    by_date = defaultdict(list)
    with open(fpath) as f:
        for row in csv.DictReader(f):
            dt = datetime.strptime(row["Datetime"], "%Y-%m-%d %H:%M:%S")
            by_date[dt.strftime("%Y-%m-%d")].append({
                "time": dt.time(), "hhmm": f"{dt.hour:02d}:{dt.minute:02d}",
                "open": float(row["Open"]), "high": float(row["High"]),
                "low": float(row["Low"]), "close": float(row["Close"]),
                "volume": int(float(row["Volume"])),
            })
    return dict(by_date)


def get_bar(bars, t):
    for b in bars:
        if b["time"] == t:
            return b
    return None


def daily_ohlcv(bars):
    """Aggregate bars to daily: first open, max high, min low, last close, sum vol."""
    if not bars:
        return None
    return {
        "open": bars[0]["open"], "close": bars[-1]["close"],
        "high": max(b["high"] for b in bars), "low": min(b["low"] for b in bars),
        "volume": sum(b["volume"] for b in bars),
    }


def spy_daily_returns(spy_data):
    """SPY daily return from first open to last close."""
    rets = {}
    for d, bars in spy_data.items():
        if bars:
            o = bars[0]["open"]
            c = bars[-1]["close"]
            if o > 0:
                rets[d] = (c - o) / o
    return rets


# ── VIX data (FRED — not affected by bug) ──
def load_vix():
    vix_path = os.path.join(ROOT, "Fetched_Data", "VIXCLS_FRED_real.csv")
    vix_level, vix_change = {}, {}
    prev = None
    with open(vix_path) as f:
        for row in csv.DictReader(f):
            v = row.get("VIXCLS", "").strip()
            if not v or v == ".":
                continue
            val = float(v)
            d = row["observation_date"]
            vix_level[d] = val
            if prev is not None:
                vix_change[d] = val - prev
            prev = val
    return vix_level, vix_change


def compare(test, metric, buggy, fixed, fmt=".3f"):
    """Print comparison row and return dict."""
    delta = fixed - buggy
    shift = abs(delta / buggy * 100) if buggy != 0 else float("inf")
    flag = " ⚠️" if shift > 30 else ""
    rev = " ⚠️⚠️⚠️ REVERSED" if (buggy > 0 and fixed < 0) or (buggy < 0 and fixed > 0) else ""
    print(f"  {test:<18s} {metric:<14s} {buggy:>10{fmt}}  {fixed:>10{fmt}}  {delta:>+10{fmt}}  {shift:>7.1f}%{flag}{rev}")
    return {"test": test, "metric": metric, "buggy": buggy, "fixed": fixed, "shift_pct": shift}


# ═══════════════════════════════════════════════════════════
# ZONE ANALYSIS (A1, A2, G2)
# ═══════════════════════════════════════════════════════════

ZONE_DEFS = [
    ("Zone1", "09:30", "10:00"),
    ("Zone2", "10:00", "12:00"),
    ("Zone3_DZ", "12:00", "13:30"),
    ("Zone4", "13:30", "14:45"),
    ("Zone5_PH", "14:45", "16:00"),
]


def run_a2_zones(all_data, label):
    """A2: Absolute returns by zone."""
    zone_rets = {z[0]: [] for z in ZONE_DEFS}
    for tk, by_date in all_data.items():
        for d, bars in by_date.items():
            zone_bars = {z[0]: [] for z in ZONE_DEFS}
            for b in bars:
                for zname, zstart, zend in ZONE_DEFS:
                    if zstart <= b["hhmm"] < zend:
                        zone_bars[zname].append(b)
            for zname, zbars in zone_bars.items():
                for b in zbars:
                    if b["open"] > 0:
                        zone_rets[zname].append(abs(b["close"] - b["open"]) / b["open"] * 100)

    print(f"\n  A2 Zone Returns ({label}):")
    for zname in [z[0] for z in ZONE_DEFS]:
        arr = np.array(zone_rets[zname])
        if len(arr):
            print(f"    {zname:<12s}: mean |ret|={arr.mean():.4f}%, N={len(arr)}")
    return zone_rets


def run_a1_volume(all_data, spy_data, label):
    """A1: Volume by half-hour window (SPY only for volume)."""
    vol_by_hh = defaultdict(list)
    for d, bars in spy_data.items():
        for b in bars:
            hh = b["hhmm"][:2] + ":" + ("00" if int(b["hhmm"][3:]) < 30 else "30")
            vol_by_hh[hh].append(b["volume"])

    print(f"\n  A1 SPY Volume ({label}):")
    for hh in sorted(vol_by_hh.keys()):
        arr = np.array(vol_by_hh[hh])
        if len(arr):
            print(f"    {hh}: mean_vol={int(arr.mean()):>12,}, N={len(arr)}")
    return vol_by_hh


# ═══════════════════════════════════════════════════════════
# G1: VIX regression (SPY daily return ~ VIX change)
# ═══════════════════════════════════════════════════════════

def run_g1(spy_data, label):
    """G1: VIX level vs VIX change as SPY return predictors."""
    vix_level, vix_change = load_vix()
    spy_rets = spy_daily_returns(spy_data)

    common = sorted(set(spy_rets.keys()) & set(vix_level.keys()) & set(vix_change.keys()))
    if len(common) < 10:
        print(f"\n  G1 ({label}): insufficient data (N={len(common)})")
        return None

    y = np.array([spy_rets[d] for d in common])
    x_level = np.array([vix_level[d] for d in common])
    x_change = np.array([vix_change[d] for d in common])

    # Simple R² for each
    from numpy.polynomial.polynomial import polyfit
    # Model (a): SPY ~ VIX_level
    p_a = np.polyfit(x_level, y, 1)
    y_pred_a = np.polyval(p_a, x_level)
    ss_res_a = ((y - y_pred_a) ** 2).sum()
    ss_tot = ((y - y.mean()) ** 2).sum()
    r2_a = 1 - ss_res_a / ss_tot if ss_tot > 0 else 0

    # Model (b): SPY ~ VIX_change
    p_b = np.polyfit(x_change, y, 1)
    y_pred_b = np.polyval(p_b, x_change)
    ss_res_b = ((y - y_pred_b) ** 2).sum()
    r2_b = 1 - ss_res_b / ss_tot if ss_tot > 0 else 0

    print(f"\n  G1 VIX Regression ({label}): N={len(common)}")
    print(f"    Model (a) SPY ~ VIX_level:  R²={r2_a:.4f}, slope={p_a[0]:.6f}")
    print(f"    Model (b) SPY ~ VIX_change: R²={r2_b:.4f}, slope={p_b[0]:.6f}")
    print(f"    Ratio R²(b)/R²(a) = {r2_b/r2_a:.1f}x" if r2_a > 0 else "")
    return {"r2_level": r2_a, "r2_change": r2_b, "n": len(common)}


# ═══════════════════════════════════════════════════════════
# G2: VIX regime intraday characteristics
# ═══════════════════════════════════════════════════════════

def run_g2(all_data, spy_data, label):
    """G2: DZ and PH absolute returns by VIX regime."""
    vix_level, _ = load_vix()
    spy_rets = spy_daily_returns(spy_data)

    regime_dz_rets = {"<20": [], "20-25": [], ">=25": []}
    regime_ph_rets = {"<20": [], "20-25": [], ">=25": []}

    for d in sorted(set().union(*(by.keys() for by in all_data.values()))):
        vix = vix_level.get(d)
        if vix is None:
            continue
        regime = "<20" if vix < 20 else ("20-25" if vix < 25 else ">=25")

        for tk, by_date in all_data.items():
            bars = by_date.get(d, [])
            for b in bars:
                if b["open"] <= 0:
                    continue
                ret = abs(b["close"] - b["open"]) / b["open"] * 100
                if "12:00" <= b["hhmm"] < "13:30":
                    regime_dz_rets[regime].append(ret)
                elif "14:45" <= b["hhmm"] < "16:00":
                    regime_ph_rets[regime].append(ret)

    print(f"\n  G2 VIX Regime ({label}):")
    for reg in ["<20", "20-25", ">=25"]:
        dz = np.array(regime_dz_rets[reg])
        ph = np.array(regime_ph_rets[reg])
        if len(dz) and len(ph):
            print(f"    {reg:>5s}: DZ |ret|={dz.mean():.4f}%, PH |ret|={ph.mean():.4f}%, N_dz={len(dz)}, N_ph={len(ph)}")
    return regime_dz_rets, regime_ph_rets


# ═══════════════════════════════════════════════════════════
# D1: Chandelier Exit — simplified (PF at entry/exit)
# ═══════════════════════════════════════════════════════════

def run_d_series(all_data, label):
    """Simplified D-series: entry at 13:30 (AM cross), exit at 15:50, compute PF."""
    entry_time = dtime(13, 30)
    exit_time = dtime(15, 50)
    rets = []
    for tk, by_date in all_data.items():
        for d, bars in by_date.items():
            eb = get_bar(bars, entry_time)
            xb = get_bar(bars, exit_time)
            if eb and xb and eb["open"] > 0:
                ret = (xb["close"] - eb["open"]) / eb["open"] * 100
                rets.append(ret)

    arr = np.array(rets)
    if len(arr) == 0:
        print(f"\n  D-series ({label}): N=0")
        return None
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    print(f"\n  D-series 13:30→15:50 ({label}): mean={arr.mean():+.4f}%, WR={(arr>0).mean()*100:.1f}%, PF={pf:.2f}, N={len(arr)}")
    return {"mean": arr.mean(), "wr": (arr > 0).mean() * 100, "pf": pf, "n": len(arr)}


# ═══════════════════════════════════════════════════════════
# B1: Gap fill (daily open vs prior close)
# ═══════════════════════════════════════════════════════════

def run_b1(all_data, label):
    """B1: Gap fill rates using daily agg."""
    gap_fills = {"small": [0, 0], "medium": [0, 0], "large": [0, 0]}  # [fills, total]
    for tk, by_date in all_data.items():
        sorted_days = sorted(by_date.keys())
        for i in range(1, len(sorted_days)):
            prev_d, curr_d = sorted_days[i - 1], sorted_days[i]
            prev_agg = daily_ohlcv(by_date[prev_d])
            curr_agg = daily_ohlcv(by_date[curr_d])
            if not prev_agg or not curr_agg:
                continue
            prev_close = prev_agg["close"]
            curr_open = curr_agg["open"]
            if prev_close <= 0:
                continue
            gap_pct = abs(curr_open - prev_close) / prev_close * 100
            if gap_pct < 0.1:
                continue
            # Check if gap filled (price crossed prev_close during the day)
            filled = False
            if curr_open > prev_close:  # gap up
                filled = curr_agg["low"] <= prev_close
            else:  # gap down
                filled = curr_agg["high"] >= prev_close

            bucket = "small" if gap_pct < 0.5 else ("medium" if gap_pct < 1.0 else "large")
            gap_fills[bucket][1] += 1
            if filled:
                gap_fills[bucket][0] += 1

    print(f"\n  B1 Gap Fill ({label}):")
    for bucket in ["small", "medium", "large"]:
        fills, total = gap_fills[bucket]
        rate = fills / total * 100 if total > 0 else 0
        print(f"    {bucket:<8s}: {rate:.1f}% ({fills}/{total})")
    return gap_fills


# ═══════════════════════════════════════════════════════════
# C1: Opening extreme
# ═══════════════════════════════════════════════════════════

def run_c1(all_data, label):
    """C1: % of days where open = day high or day low."""
    open_is_extreme = 0
    total = 0
    for tk, by_date in all_data.items():
        for d, bars in by_date.items():
            agg = daily_ohlcv(bars)
            if not agg:
                continue
            total += 1
            if agg["open"] >= agg["high"] - 0.001 or agg["open"] <= agg["low"] + 0.001:
                open_is_extreme += 1

    pct = open_is_extreme / total * 100 if total > 0 else 0
    print(f"\n  C1 Opening Extreme ({label}): {pct:.1f}% ({open_is_extreme}/{total})")
    return pct


# ═══════════════════════════════════════════════════════════
# S21-P5: Stress frequency
# ═══════════════════════════════════════════════════════════

def run_s21_p5(all_data, label):
    """S21-P5: Count stress days."""
    all_dates = set()
    for by_date in all_data.values():
        all_dates.update(by_date.keys())
    n_days = len(all_dates)
    n_stress = len(STRESS_SET & all_dates)
    print(f"\n  S21-P5 Stress Freq ({label}): {n_stress} stress / {n_days} total = {n_stress/n_days*100:.1f}%")
    return n_stress, n_days


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def main():
    results = []

    print("=" * 70)
    print("P2-P4 CONTINUOUS RE-RUN")
    print("=" * 70)

    # Load both datasets
    print("\nLoading data...")
    buggy = load_all_tickers("_m5_regsess.csv")
    fixed = load_all_tickers("_m5_regsess_FIXED.csv")
    spy_buggy = load_spy("_m5_regsess.csv")
    spy_fixed = load_spy("_m5_regsess_FIXED.csv")
    print(f"  Buggy: {len(buggy)} tickers, SPY {len(spy_buggy)} days")
    print(f"  Fixed: {len(fixed)} tickers, SPY {len(spy_fixed)} days")

    # ── P2: SCORING ARCHITECTURE ──
    print("\n" + "=" * 70)
    print("P2: SCORING ARCHITECTURE")
    print("=" * 70)

    # E2/E3a depend on indicators computed from regsess — would need full indicator recompute
    # For now: flag as AFFECTED, estimate impact from daily agg change
    print("\n  E2 (TQS regression): AFFECTED — uses indicators from compute_indicators.py")
    print("    Requires full indicator recompute on FIXED data. Flagged for separate re-run.")
    print("\n  E3a (ADX threshold): AFFECTED — same dependency on compute_indicators.py")
    print("    Flagged for separate re-run.")

    # EMA 4H crosses: split at 13:30
    print("\n  EMA 4H crosses: AFFECTED — 4H bars split at 13:30, PM bar uses wrong data")
    print("    Flagged for separate re-run (requires EMA recompute).")

    # S21-P3, P4, P8: use noon ranking + various features
    # These are structurally identical to P1 tests, already shown to collapse
    print("\n  S21-P3 (DefenseRank): Structurally same as P1 — uses noon ranking on buggy data")
    print("  S21-P4 (Beta-weighted): Same dependency")
    print("  S21-P8 (Sector concentration): Same dependency")
    print("  → All S21 tests inherit the P1 collapse. No separate re-run needed.")

    # ── P3: ZONE & PATTERN ANALYSIS ──
    print("\n" + "=" * 70)
    print("P3: ZONE & PATTERN ANALYSIS")
    print("=" * 70)

    # A2: Zone returns
    a2_b = run_a2_zones(buggy, "BUGGY")
    a2_f = run_a2_zones(fixed, "FIXED")

    # A1: Volume (SPY only)
    a1_b = run_a1_volume(buggy, spy_buggy, "BUGGY")
    a1_f = run_a1_volume(fixed, spy_fixed, "FIXED")

    # G2: VIX regime
    g2_b = run_g2(buggy, spy_buggy, "BUGGY")
    g2_f = run_g2(fixed, spy_fixed, "FIXED")

    # D-series simplified
    d_b = run_d_series(buggy, "BUGGY")
    d_f = run_d_series(fixed, "FIXED")

    # C1: Opening extreme
    c1_b = run_c1(buggy, "BUGGY")
    c1_f = run_c1(fixed, "FIXED")

    # B1: Gap fill
    b1_b = run_b1(buggy, "BUGGY")
    b1_f = run_b1(fixed, "FIXED")

    # ── P4: SUPPORTING ──
    print("\n" + "=" * 70)
    print("P4: SUPPORTING ANALYSIS")
    print("=" * 70)

    # G1: VIX regression — THE CRITICAL ONE
    g1_b = run_g1(spy_buggy, "BUGGY")
    g1_f = run_g1(spy_fixed, "FIXED")

    # S21-P5: Stress frequency
    p5_b = run_s21_p5(buggy, "BUGGY")
    p5_f = run_s21_p5(fixed, "FIXED")

    # ── SUMMARY TABLE ──
    print("\n" + "=" * 70)
    print("COMPARISON SUMMARY (all tests)")
    print("=" * 70)
    print(f"\n  {'Test':<18s} {'Metric':<14s} {'Buggy':>10s}  {'Fixed':>10s}  {'Delta':>10s}  {'Shift%':>8s}")
    print("  " + "-" * 70)

    # Zone means
    for zname in [z[0] for z in ZONE_DEFS]:
        if a2_b[zname] and a2_f[zname]:
            compare(f"A2 {zname}", "|ret| %",
                    np.mean(a2_b[zname]), np.mean(a2_f[zname]))

    # D-series
    if d_b and d_f:
        compare("D1-3 13:30→15:50", "Mean %", d_b["mean"], d_f["mean"])
        compare("D1-3 13:30→15:50", "PF", d_b["pf"], d_f["pf"])

    # C1
    compare("C1 Open=Extreme", "% days", c1_b, c1_f)

    # B1
    for bucket in ["small", "medium", "large"]:
        b_rate = b1_b[bucket][0] / b1_b[bucket][1] * 100 if b1_b[bucket][1] > 0 else 0
        f_rate = b1_f[bucket][0] / b1_f[bucket][1] * 100 if b1_f[bucket][1] > 0 else 0
        compare(f"B1 Gap {bucket}", "Fill %", b_rate, f_rate)

    # G1
    if g1_b and g1_f:
        compare("G1 VIX chg", "R²", g1_b["r2_change"], g1_f["r2_change"])
        compare("G1 VIX lvl", "R²", g1_b["r2_level"], g1_f["r2_level"])
        if g1_b["r2_level"] > 0 and g1_f["r2_level"] > 0:
            compare("G1 ratio", "chg/lvl", g1_b["r2_change"]/g1_b["r2_level"],
                    g1_f["r2_change"]/g1_f["r2_level"])


if __name__ == "__main__":
    main()
