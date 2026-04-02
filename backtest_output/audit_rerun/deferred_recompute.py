#!/usr/bin/env python3
"""
Deferred Recompute: E2, E3a, EMA 4H on FIXED data.

1. Recompute indicators (RSI, ADX, DMI, EMA, Squeeze) on FIXED M5 bars
2. Re-run E2 TQS regression
3. Re-run E3a ADX threshold analysis
4. Validate EMA 4H crosses
"""

import csv
import os
import sys
import numpy as np
from collections import defaultdict
from datetime import datetime, time as dtime
from math import erfc, sqrt

ROOT = "/home/user/stock-data-mining"
BACKTEST_DIR = os.path.join(ROOT, "backtest_output")
OUT_DIR = os.path.join(BACKTEST_DIR, "audit_rerun")

TICKERS_5 = ["NVDA", "TSLA", "GOOGL", "IBIT", "GS"]
ALL_TICKERS = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU", "C",
    "COIN", "COST", "GOOGL", "GS", "INTC", "JPM", "MARA", "META", "MSFT",
    "MSTR", "MU", "NVDA", "PLTR", "SMCI", "SPY", "TSLA", "TSM", "V", "VIXY",
]


# ═══════════════════════════════════════════════════════════
# INDICATOR FUNCTIONS (copied from original compute_indicators.py)
# ═══════════════════════════════════════════════════════════

def ema(values, period):
    out = np.full(len(values), np.nan)
    if len(values) < period:
        return out
    out[period - 1] = np.mean(values[:period])
    k = 2.0 / (period + 1)
    for i in range(period, len(values)):
        out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out


def rsi_wilder(closes, period=14):
    n = len(closes)
    out = np.full(n, np.nan)
    if n < period + 1:
        return out
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    out[period] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i + 1] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def adx_dmi(highs, lows, closes, period=14):
    n = len(highs)
    pdi = np.full(n, np.nan)
    mdi = np.full(n, np.nan)
    adx = np.full(n, np.nan)
    if n < period + 1:
        return adx, pdi, mdi
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
    pdm = np.zeros(n)
    mdm = np.zeros(n)
    for i in range(1, n):
        up = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        pdm[i] = up if (up > down and up > 0) else 0.0
        mdm[i] = down if (down > up and down > 0) else 0.0
    atr_s = np.zeros(n)
    pdm_s = np.zeros(n)
    mdm_s = np.zeros(n)
    atr_s[period] = np.sum(tr[1:period+1])
    pdm_s[period] = np.sum(pdm[1:period+1])
    mdm_s[period] = np.sum(mdm[1:period+1])
    for i in range(period+1, n):
        atr_s[i] = atr_s[i-1] - atr_s[i-1]/period + tr[i]
        pdm_s[i] = pdm_s[i-1] - pdm_s[i-1]/period + pdm[i]
        mdm_s[i] = mdm_s[i-1] - mdm_s[i-1]/period + mdm[i]
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
    adx_start = 2 * period
    if n > adx_start:
        adx[adx_start] = np.mean(dx[period:adx_start+1])
        for i in range(adx_start+1, n):
            adx[i] = (adx[i-1] * (period-1) + dx[i]) / period
    return adx, pdi, mdi


def squeeze(closes, highs, lows, bb_period=20, atr_period=14, kc_mult=1.5):
    n = len(closes)
    squeeze_on = np.zeros(n, dtype=int)
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
    atr = np.full(n, np.nan)
    if n >= atr_period:
        atr[atr_period-1] = np.mean(tr[:atr_period])
        k = 2.0 / (atr_period + 1)
        for i in range(atr_period, n):
            atr[i] = tr[i] * k + atr[i-1] * (1 - k)
    for i in range(bb_period-1, n):
        window = closes[i-bb_period+1:i+1]
        bb_width = 2.0 * np.std(window, ddof=0)
        if not np.isnan(atr[i]):
            kc_width = 2.0 * atr[i] * kc_mult
            if bb_width < kc_width:
                squeeze_on[i] = 1
    return squeeze_on


def load_fixed_m5(ticker):
    """Load FIXED M5 data."""
    fpath = os.path.join(BACKTEST_DIR, f"{ticker}_m5_regsess_FIXED.csv")
    if not os.path.exists(fpath):
        return None
    rows = []
    with open(fpath) as f:
        for row in csv.DictReader(f):
            rows.append({
                "Datetime": row["Datetime"],
                "Open": float(row["Open"]),
                "High": float(row["High"]),
                "Low": float(row["Low"]),
                "Close": float(row["Close"]),
                "Volume": int(float(row["Volume"])),
            })
    return rows


def p_from_t(t, df):
    return erfc(abs(t) / sqrt(2))


# ═══════════════════════════════════════════════════════════
# TASK 1: RECOMPUTE INDICATORS
# ═══════════════════════════════════════════════════════════

def task1_indicators():
    print("=" * 70)
    print("TASK 1: RECOMPUTE INDICATORS ON FIXED DATA")
    print("=" * 70)

    ind_dir = os.path.join(OUT_DIR, "indicators_fixed")
    os.makedirs(ind_dir, exist_ok=True)

    for ticker in TICKERS_5:
        bars = load_fixed_m5(ticker)
        if not bars:
            print(f"  {ticker}: NOT FOUND")
            continue
        n = len(bars)
        closes = np.array([b["Close"] for b in bars])
        highs = np.array([b["High"] for b in bars])
        lows = np.array([b["Low"] for b in bars])

        ema9 = ema(closes, 9)
        ema21 = ema(closes, 21)
        rsi14 = rsi_wilder(closes, 14)
        adx14, pdi14, mdi14 = adx_dmi(highs, lows, closes, 14)
        sq_on = squeeze(closes, highs, lows)

        # Save
        outpath = os.path.join(ind_dir, f"indicators_{ticker}.csv")
        with open(outpath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Datetime", "Open", "High", "Low", "Close", "Volume",
                             "ema9", "ema21", "rsi14", "adx14", "pdi14", "mdi14", "squeeze_on"])
            for i in range(n):
                writer.writerow([
                    bars[i]["Datetime"],
                    f"{bars[i]['Open']:.4f}", f"{bars[i]['High']:.4f}",
                    f"{bars[i]['Low']:.4f}", f"{bars[i]['Close']:.4f}",
                    bars[i]["Volume"],
                    f"{ema9[i]:.4f}" if not np.isnan(ema9[i]) else "",
                    f"{ema21[i]:.4f}" if not np.isnan(ema21[i]) else "",
                    f"{rsi14[i]:.2f}" if not np.isnan(rsi14[i]) else "",
                    f"{adx14[i]:.2f}" if not np.isnan(adx14[i]) else "",
                    f"{pdi14[i]:.2f}" if not np.isnan(pdi14[i]) else "",
                    f"{mdi14[i]:.2f}" if not np.isnan(mdi14[i]) else "",
                    sq_on[i],
                ])

        valid = ~np.isnan(rsi14) & ~np.isnan(adx14)
        vi = np.where(valid)[0]
        rsi_med = np.nanmedian(rsi14[vi])
        adx_med = np.nanmedian(adx14[vi])
        sq_pct = 100.0 * np.sum(sq_on[vi]) / len(vi) if len(vi) > 0 else 0
        print(f"  {ticker}: {n} bars, RSI_med={rsi_med:.1f}, ADX_med={adx_med:.1f}, Squeeze%={sq_pct:.1f}%")

    return ind_dir


# ═══════════════════════════════════════════════════════════
# TASK 2: E2 TQS REGRESSION
# ═══════════════════════════════════════════════════════════

def task2_e2(ind_dir, label):
    """Run E2 regression on indicators from ind_dir."""
    FWD_BARS = 12
    dmi_all, rsi_all, sqz_all, fret_all = [], [], [], []
    ticker_counts = {}

    for ticker in TICKERS_5:
        fpath = os.path.join(ind_dir, f"indicators_{ticker}.csv")
        if not os.path.exists(fpath):
            continue
        rows = []
        with open(fpath) as f:
            for row in csv.DictReader(f):
                rows.append(row)
        n = len(rows)
        count = 0
        for i in range(n):
            r = rows[i]
            if r["adx14"] == "" or r["rsi14"] == "" or r["squeeze_on"] == "":
                continue
            if i + FWD_BARS >= n:
                continue
            date_i = r["Datetime"][:10]
            date_fwd = rows[i + FWD_BARS]["Datetime"][:10]
            if date_i != date_fwd:
                continue
            close_i = float(r["Close"])
            close_fwd = float(rows[i + FWD_BARS]["Close"])
            if close_i <= 0:
                continue
            adx = float(r["adx14"])
            rsi = float(r["rsi14"])
            sqz = int(r["squeeze_on"])
            dmi_all.append(min(adx / 50.0, 1.0))
            rsi_all.append(abs(rsi - 50.0) / 50.0)
            sqz_all.append(float(sqz))
            fret_all.append(close_fwd / close_i - 1.0)
            count += 1
        ticker_counts[ticker] = count

    X_dmi = np.array(dmi_all)
    X_rsi = np.array(rsi_all)
    X_sqz = np.array(sqz_all)
    Y = np.array(fret_all)
    N = len(Y)

    if N == 0:
        print(f"\n  E2 ({label}): NO DATA")
        return None

    # OLS: Y = b0 + b1*DMI + b2*RSI + b3*Squeeze
    X = np.column_stack([np.ones(N), X_dmi, X_rsi, X_sqz])
    beta = np.linalg.solve(X.T @ X, X.T @ Y)
    Y_hat = X @ beta
    SS_res = np.sum((Y - Y_hat) ** 2)
    SS_tot = np.sum((Y - np.mean(Y)) ** 2)
    R2 = 1.0 - SS_res / SS_tot if SS_tot > 0 else 0

    # |fwd_ret| regression
    Y_abs = np.abs(Y)
    beta_abs = np.linalg.solve(X.T @ X, X.T @ Y_abs)
    Y_hat_abs = X @ beta_abs
    SS_res_abs = np.sum((Y_abs - Y_hat_abs) ** 2)
    SS_tot_abs = np.sum((Y_abs - np.mean(Y_abs)) ** 2)
    R2_abs = 1.0 - SS_res_abs / SS_tot_abs if SS_tot_abs > 0 else 0

    # Std betas for |fwd_ret|
    std_X = np.std(X[:, 1:], axis=0)
    std_Y_abs = np.std(Y_abs)
    std_betas = beta_abs[1:] * std_X / std_Y_abs if std_Y_abs > 0 else beta_abs[1:] * 0

    # Standard errors for |fwd_ret|
    k = X.shape[1]
    sigma2_abs = SS_res_abs / (N - k)
    cov_abs = sigma2_abs * np.linalg.inv(X.T @ X)
    se_abs = np.sqrt(np.diag(cov_abs))
    t_abs = beta_abs / se_abs
    p_abs = [p_from_t(t, N - k) for t in t_abs]

    print(f"\n  E2 TQS Regression ({label}): N={N:,}")
    for tk, cnt in ticker_counts.items():
        print(f"    {tk}: {cnt:,}")

    print(f"\n  Regression on |fwd_ret|: R²={R2_abs:.6f}")
    names = ["(intercept)", "DMI_score", "RSI_score", "Squeeze_score"]
    print(f"  {'Variable':<14s} {'Coef':>10s} {'Std Beta':>10s} {'t-stat':>8s} {'p-value':>10s}")
    for i, name in enumerate(names):
        sb = f"{std_betas[i-1]:.4f}" if i > 0 else "—"
        sig = " ***" if p_abs[i] < 0.001 else (" **" if p_abs[i] < 0.01 else (" *" if p_abs[i] < 0.05 else ""))
        print(f"  {name:<14s} {beta_abs[i]:>10.6f} {sb:>10s} {t_abs[i]:>8.2f} {p_abs[i]:>10.4e}{sig}")

    # Rank
    abs_std = {"DMI": abs(std_betas[0]), "RSI": abs(std_betas[1]), "Squeeze": abs(std_betas[2])}
    rank = sorted(abs_std.keys(), key=lambda k: abs_std[k], reverse=True)
    print(f"  Empirical rank: {' > '.join(rank)}")
    if abs_std[rank[1]] > 0:
        print(f"  {rank[0]} / {rank[1]} ratio: {abs_std[rank[0]]/abs_std[rank[1]]:.2f}x")

    return {"R2_abs": R2_abs, "std_betas": std_betas, "N": N, "rank": rank,
            "beta_abs": beta_abs, "abs_std": abs_std}


# ═══════════════════════════════════════════════════════════
# TASK 3: E3a ADX THRESHOLD
# ═══════════════════════════════════════════════════════════

def task3_e3a(suffix, label):
    """E3a: ADX threshold at EMA crosses. Aggregates M5→daily, computes ADX, cross detection."""
    # We need to: 1) aggregate FIXED M5 to daily, 2) compute daily ADX, 3) detect 4H EMA crosses,
    # 4) bucket crosses by ADX, 5) compute fwd returns.

    tickers = TICKERS_5

    daily_cache = {}
    adx_cache = {}
    close_by_date = {}
    dates_by_ticker = {}

    for ticker in tickers:
        fpath = os.path.join(BACKTEST_DIR, f"{ticker}{suffix}")
        if not os.path.exists(fpath):
            continue
        bars = []
        with open(fpath) as f:
            for row in csv.DictReader(f):
                bars.append({
                    "date": row["Datetime"][:10],
                    "hhmm": row["Datetime"][11:16],
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                })

        # Aggregate to daily
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
        sorted_dates = sorted(daily.keys())
        daily_list = [daily[d] for d in sorted_dates]
        daily_cache[ticker] = daily_list

        # ADX on daily
        if len(daily_list) < 30:
            continue
        highs = np.array([d["high"] for d in daily_list])
        lows = np.array([d["low"] for d in daily_list])
        closes = np.array([d["close"] for d in daily_list])
        adx14, pdi14, mdi14 = adx_dmi(highs, lows, closes, 14)
        adx_dict = {}
        for i in range(len(daily_list)):
            if not np.isnan(adx14[i]):
                adx_dict[daily_list[i]["date"]] = (adx14[i], pdi14[i], mdi14[i])
        adx_cache[ticker] = adx_dict
        close_by_date[ticker] = {d["date"]: d["close"] for d in daily_list}
        dates_by_ticker[ticker] = sorted_dates

        # Build 4H bars: AM (09:30-13:25) and PM (13:30-15:55)
        bars_by_date = defaultdict(list)
        for b in bars:
            bars_by_date[b["date"]].append(b)

        # Detect EMA 9/21 crosses on 4H bars
        four_h_bars = []
        for d in sorted_dates:
            day_bars = bars_by_date[d]
            am = [b for b in day_bars if b["hhmm"] < "13:30"]
            pm = [b for b in day_bars if b["hhmm"] >= "13:30"]
            if am:
                four_h_bars.append({
                    "date": d, "session": "AM",
                    "open": am[0]["open"], "high": max(b["high"] for b in am),
                    "low": min(b["low"] for b in am), "close": am[-1]["close"],
                })
            if pm:
                four_h_bars.append({
                    "date": d, "session": "PM",
                    "open": pm[0]["open"], "high": max(b["high"] for b in pm),
                    "low": min(b["low"] for b in pm), "close": pm[-1]["close"],
                })

        if len(four_h_bars) < 22:
            continue
        closes_4h = np.array([b["close"] for b in four_h_bars])
        ema9_4h = ema(closes_4h, 9)
        ema21_4h = ema(closes_4h, 21)

        # Detect crosses
        if ticker not in adx_cache:
            continue
        for i in range(1, len(four_h_bars)):
            if np.isnan(ema9_4h[i]) or np.isnan(ema21_4h[i]):
                continue
            if np.isnan(ema9_4h[i-1]) or np.isnan(ema21_4h[i-1]):
                continue
            prev_diff = ema9_4h[i-1] - ema21_4h[i-1]
            curr_diff = ema9_4h[i] - ema21_4h[i]
            if prev_diff <= 0 and curr_diff > 0:
                direction = "UP"
            elif prev_diff >= 0 and curr_diff < 0:
                direction = "DOWN"
            else:
                continue

            d = four_h_bars[i]["date"]
            if d not in adx_cache[ticker]:
                continue
            adx_val = adx_cache[ticker][d][0]
            dates = dates_by_ticker[ticker]
            if d not in dates:
                continue
            idx = dates.index(d)

            fwd1 = None
            if idx + 1 < len(dates):
                c0 = close_by_date[ticker][d]
                c1 = close_by_date[ticker][dates[idx+1]]
                if c0 > 0:
                    fwd1 = (c1 - c0) / c0

            if fwd1 is not None:
                if ticker not in daily_cache:
                    continue
                # Bucket by ADX
                for lo, hi, lbl in [(0,15,"<15"),(15,20,"15-20"),(20,25,"20-25"),(25,30,"25-30"),(30,999,"30+")]:
                    if lo <= adx_val < hi:
                        if lbl not in task3_e3a.buckets:
                            task3_e3a.buckets[lbl] = {"UP": [], "DOWN": [], "ALL": []}
                        task3_e3a.buckets[lbl][direction].append(fwd1)
                        task3_e3a.buckets[lbl]["ALL"].append(fwd1)
                        break
                task3_e3a.all_crosses.append({"direction": direction, "adx": adx_val, "fwd1": fwd1, "ticker": ticker})

    # Print results
    print(f"\n  E3a ADX Threshold ({label}): {len(task3_e3a.all_crosses)} crosses")
    print(f"  {'Bucket':<8s} {'N':>5s} {'Mean 1d%':>10s} {'%Pos':>7s}")
    for lbl in ["<15", "15-20", "20-25", "25-30", "30+"]:
        if lbl in task3_e3a.buckets:
            arr = np.array(task3_e3a.buckets[lbl]["ALL"])
            if len(arr):
                print(f"  {lbl:<8s} {len(arr):>5d} {arr.mean()*100:>+9.3f}% {(arr>0).mean()*100:>6.1f}%")

    # UP crosses: low vs high ADX
    up_crosses = [c for c in task3_e3a.all_crosses if c["direction"] == "UP" and c["fwd1"] is not None]
    lo = [c["fwd1"] for c in up_crosses if c["adx"] < 18]
    hi = [c["fwd1"] for c in up_crosses if c["adx"] >= 18]
    if lo and hi:
        lo_m = np.mean(lo) * 100
        hi_m = np.mean(hi) * 100
        print(f"\n  UP crosses: ADX<18 mean={lo_m:+.3f}% (N={len(lo)}), ADX>=18 mean={hi_m:+.3f}% (N={len(hi)})")
        print(f"  Inversion test: {'LOW BETTER' if lo_m > hi_m else 'HIGH BETTER'} (diff={lo_m-hi_m:+.3f}%)")

    return task3_e3a.all_crosses

task3_e3a.buckets = {}
task3_e3a.all_crosses = []


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def main():
    # Task 1: Recompute indicators
    ind_dir = task1_indicators()

    # Task 2: E2 — run on BOTH buggy and FIXED indicators
    print("\n" + "=" * 70)
    print("TASK 2: E2 TQS REGRESSION")
    print("=" * 70)
    buggy_ind = os.path.join(BACKTEST_DIR, "audit", "indicators")
    e2_buggy = task2_e2(buggy_ind, "BUGGY")

    e2_fixed = task2_e2(ind_dir, "FIXED")

    if e2_buggy and e2_fixed:
        print(f"\n  E2 COMPARISON:")
        print(f"  {'Component':<12s} {'Buggy |β|':>12s} {'FIXED |β|':>12s} {'Shift':>8s}")
        for comp, i in [("DMI", 0), ("RSI", 1), ("Squeeze", 2)]:
            b = e2_buggy["abs_std"][comp]
            f = e2_fixed["abs_std"][comp]
            shift = abs(f - b) / b * 100 if b > 0 else float("inf")
            print(f"  {comp:<12s} {b:>12.4f} {f:>12.4f} {shift:>7.1f}%")
        print(f"  Buggy rank: {' > '.join(e2_buggy['rank'])}")
        print(f"  FIXED rank: {' > '.join(e2_fixed['rank'])}")
        print(f"  Rank changed: {'YES ⚠️' if e2_buggy['rank'] != e2_fixed['rank'] else 'NO'}")

    # Task 3: E3a — BUGGY vs FIXED
    print("\n" + "=" * 70)
    print("TASK 3: E3a ADX THRESHOLD")
    print("=" * 70)

    task3_e3a.buckets = {}
    task3_e3a.all_crosses = []
    e3_buggy = task3_e3a("_m5_regsess.csv", "BUGGY")
    buggy_crosses = list(task3_e3a.all_crosses)

    task3_e3a.buckets = {}
    task3_e3a.all_crosses = []
    e3_fixed = task3_e3a("_m5_regsess_FIXED.csv", "FIXED")

    # Task 4: EMA 4H validation (already done within E3a)
    print("\n" + "=" * 70)
    print("TASK 4: EMA 4H CROSS VALIDATION")
    print("=" * 70)
    print(f"  Buggy: {len(buggy_crosses)} total crosses")
    print(f"  FIXED: {len(task3_e3a.all_crosses)} total crosses")

    # Per-ticker cross counts
    for dataset, name in [(buggy_crosses, "BUGGY"), (task3_e3a.all_crosses, "FIXED")]:
        by_tk = defaultdict(int)
        for c in dataset:
            by_tk[c["ticker"]] += 1
        print(f"  {name} per-ticker: {dict(by_tk)}")


if __name__ == "__main__":
    main()
