#!/usr/bin/env python3
"""
Build 4H Indicators + Cross Catalog from FIXED M5 data.

Part 1 of the Continuation Study (Prompt B1).

For each of 25 certified equity tickers (excluding SPY, VIXY):
  1. Load FIXED M5 data
  2. Resample to 4H bars (AM: 09:30-13:25, PM: 13:30-15:55)
  3. Compute EMA 9, EMA 21, RSI 14, ADX 14 on 4H bars
  4. Save 4H indicator files
  5. Detect EMA 9/21 crosses
  6. Build cross catalog with metadata
"""

import csv
import os
import sys
import numpy as np
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from utils.data_loader import load_m5_regsess, ALL_TICKERS

# Exclude SPY and VIXY (truncated at 13:00 ET)
TICKERS = [t for t in ALL_TICKERS if t not in ("SPY", "VIXY")]

OUT_4H_DIR = ROOT / "data" / "indicators_4h"
CONT_DIR = ROOT / "backtest_output" / "continuation_study"


# ═══════════════════════════════════════════════════════════
# INDICATOR FUNCTIONS (from deferred_recompute.py)
# ═══════════════════════════════════════════════════════════

def ema(values, period):
    """Compute EMA. Returns array same length as input."""
    out = np.full(len(values), np.nan)
    if len(values) < period:
        return out
    out[period - 1] = np.mean(values[:period])
    k = 2.0 / (period + 1)
    for i in range(period, len(values)):
        out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out


def rsi_wilder(closes, period=14):
    """Compute RSI using Wilder's smoothing."""
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
    """Compute ADX, +DI, -DI."""
    n = len(highs)
    pdi = np.full(n, np.nan)
    mdi = np.full(n, np.nan)
    adx = np.full(n, np.nan)
    if n < period + 1:
        return adx, pdi, mdi
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
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
    atr_s[period] = np.sum(tr[1:period + 1])
    pdm_s[period] = np.sum(pdm[1:period + 1])
    mdm_s[period] = np.sum(mdm[1:period + 1])
    for i in range(period + 1, n):
        atr_s[i] = atr_s[i - 1] - atr_s[i - 1] / period + tr[i]
        pdm_s[i] = pdm_s[i - 1] - pdm_s[i - 1] / period + pdm[i]
        mdm_s[i] = mdm_s[i - 1] - mdm_s[i - 1] / period + mdm[i]
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
        adx[adx_start] = np.mean(dx[period:adx_start + 1])
        for i in range(adx_start + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
    return adx, pdi, mdi


# ═══════════════════════════════════════════════════════════
# TASK 1: BUILD 4H BARS + INDICATORS
# ═══════════════════════════════════════════════════════════

def build_4h_bars(df):
    """Convert M5 DataFrame to 4H bars (2 per day: AM + PM)."""
    df = df.copy()
    df["date"] = df["Datetime"].dt.strftime("%Y-%m-%d")
    df["hhmm"] = df["Datetime"].dt.strftime("%H:%M")

    bars_4h = []
    for date_str in sorted(df["date"].unique()):
        day = df[df["date"] == date_str]

        # AM: 09:30-13:25 (bars with hhmm < 13:30)
        am = day[day["hhmm"] < "13:30"]
        # PM: 13:30-15:55 (bars with hhmm >= 13:30)
        pm = day[day["hhmm"] >= "13:30"]

        for label, half in [("AM", am), ("PM", pm)]:
            if half.empty:
                continue
            bars_4h.append({
                "timestamp": f"{date_str} {half.iloc[0]['Datetime'].strftime('%H:%M:%S')}",
                "date": date_str,
                "session": label,
                "open": half.iloc[0]["Open"],
                "high": half["High"].max(),
                "low": half["Low"].min(),
                "close": half.iloc[-1]["Close"],
                "volume": int(half["Volume"].sum()),
            })

    return bars_4h


def compute_4h_indicators(bars_4h):
    """Add EMA 9, EMA 21, RSI 14, ADX 14 to 4H bars."""
    closes = np.array([b["close"] for b in bars_4h])
    highs = np.array([b["high"] for b in bars_4h])
    lows = np.array([b["low"] for b in bars_4h])

    ema9 = ema(closes, 9)
    ema21 = ema(closes, 21)
    rsi14 = rsi_wilder(closes, 14)
    adx14, pdi14, mdi14 = adx_dmi(highs, lows, closes, 14)

    for i, b in enumerate(bars_4h):
        b["ema_9"] = ema9[i]
        b["ema_21"] = ema21[i]
        b["rsi_14"] = rsi14[i]
        b["adx_14"] = adx14[i]

    return bars_4h


def save_4h_indicators(ticker, bars_4h):
    """Save 4H indicator CSV."""
    OUT_4H_DIR.mkdir(parents=True, exist_ok=True)
    outpath = OUT_4H_DIR / f"{ticker}_4h_indicators.csv"

    with open(outpath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume",
                         "ema_9", "ema_21", "rsi_14", "adx_14"])
        for b in bars_4h:
            writer.writerow([
                b["timestamp"],
                f"{b['open']:.4f}", f"{b['high']:.4f}",
                f"{b['low']:.4f}", f"{b['close']:.4f}",
                b["volume"],
                f"{b['ema_9']:.4f}" if not np.isnan(b["ema_9"]) else "",
                f"{b['ema_21']:.4f}" if not np.isnan(b["ema_21"]) else "",
                f"{b['rsi_14']:.2f}" if not np.isnan(b["rsi_14"]) else "",
                f"{b['adx_14']:.2f}" if not np.isnan(b["adx_14"]) else "",
            ])

    return outpath


# ═══════════════════════════════════════════════════════════
# TASK 2: DETECT CROSSES + BUILD CATALOG
# ═══════════════════════════════════════════════════════════

def detect_crosses(ticker, bars_4h):
    """Detect EMA 9/21 crosses. Returns list of cross events."""
    crosses = []

    for i in range(1, len(bars_4h)):
        b = bars_4h[i]
        bp = bars_4h[i - 1]

        if np.isnan(b["ema_9"]) or np.isnan(b["ema_21"]):
            continue
        if np.isnan(bp["ema_9"]) or np.isnan(bp["ema_21"]):
            continue

        prev_diff = bp["ema_9"] - bp["ema_21"]
        curr_diff = b["ema_9"] - b["ema_21"]

        direction = None
        if prev_diff <= 0 and curr_diff > 0:
            direction = "UP"
        elif prev_diff >= 0 and curr_diff < 0:
            direction = "DOWN"

        if direction is None:
            continue

        crosses.append({
            "ticker": ticker,
            "date": b["date"],
            "session": b["session"],
            "timestamp": b["timestamp"],
            "direction": direction,
            "close": b["close"],
            "ema_9": b["ema_9"],
            "ema_21": b["ema_21"],
            "ema_spread": b["ema_9"] - b["ema_21"],
            "rsi_14": b["rsi_14"],
            "adx_14": b["adx_14"],
        })

    return crosses


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("BUILD 4H INDICATORS + CROSS CATALOG (FIXED DATA)")
    print("=" * 70)
    print(f"Tickers: {len(TICKERS)}")
    print()

    all_crosses = []
    ticker_stats = {}

    for ticker in TICKERS:
        try:
            df = load_m5_regsess(ticker)
        except (FileNotFoundError, ValueError) as e:
            print(f"  SKIP {ticker}: {e}")
            continue

        # Build 4H bars
        bars_4h = build_4h_bars(df)

        # Compute indicators
        bars_4h = compute_4h_indicators(bars_4h)

        # Save 4H indicator file
        outpath = save_4h_indicators(ticker, bars_4h)

        # Detect crosses
        crosses = detect_crosses(ticker, bars_4h)
        all_crosses.extend(crosses)

        up = sum(1 for c in crosses if c["direction"] == "UP")
        dn = sum(1 for c in crosses if c["direction"] == "DOWN")
        ticker_stats[ticker] = {"bars_4h": len(bars_4h), "up": up, "down": dn, "total": up + dn}

        print(f"  {ticker}: {len(bars_4h)} 4H bars, {up} UP + {dn} DOWN = {up + dn} crosses → {outpath.name}")

    # Save cross catalog
    CONT_DIR.mkdir(parents=True, exist_ok=True)
    catalog_path = CONT_DIR / "cross_catalog.csv"
    with open(catalog_path, "w", newline="") as f:
        fields = ["ticker", "date", "session", "timestamp", "direction", "close",
                  "ema_9", "ema_21", "ema_spread", "rsi_14", "adx_14"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for c in all_crosses:
            row = {}
            for k in fields:
                v = c[k]
                if isinstance(v, float) and not np.isnan(v):
                    if k in ("rsi_14", "adx_14"):
                        row[k] = f"{v:.2f}"
                    else:
                        row[k] = f"{v:.4f}"
                elif isinstance(v, float) and np.isnan(v):
                    row[k] = ""
                else:
                    row[k] = v
            writer.writerow(row)
    print(f"\nCross catalog saved: {catalog_path}")
    print(f"Total crosses: {len(all_crosses)}")

    # ── Task 3: Catalog Statistics ──────────────────────────
    total_up = sum(1 for c in all_crosses if c["direction"] == "UP")
    total_dn = sum(1 for c in all_crosses if c["direction"] == "DOWN")

    lines = []

    def p(line=""):
        lines.append(line)

    p("# 4H EMA 9/21 Cross Catalog — Statistics")
    p()
    p(f"**Date:** 2026-03-24")
    p(f"**Data:** FIXED M5 → 4H bars (AM: 09:30-13:25, PM: 13:30-15:55)")
    p(f"**Tickers:** {len(TICKERS)} (25 certified equities, excluding SPY/VIXY)")
    p()
    p("---")
    p()
    p("## Summary")
    p()
    p(f"| Metric | Value |")
    p(f"|--------|------:|")
    p(f"| Total crosses | {len(all_crosses)} |")
    p(f"| UP crosses (EMA9 > EMA21) | {total_up} |")
    p(f"| DOWN crosses (EMA9 < EMA21) | {total_dn} |")
    p(f"| UP/DOWN ratio | {total_up / total_dn:.2f} |" if total_dn > 0 else "| UP/DOWN ratio | N/A |")
    p(f"| Mean crosses per ticker | {len(all_crosses) / len(TICKERS):.1f} |")
    p()

    # Per-ticker distribution
    p("## Per-Ticker Distribution")
    p()
    p("| Ticker | 4H Bars | UP | DOWN | Total | Avg days between |")
    p("|--------|--------:|---:|-----:|------:|-----------------:|")
    for ticker in TICKERS:
        if ticker not in ticker_stats:
            continue
        s = ticker_stats[ticker]
        tk_crosses = [c for c in all_crosses if c["ticker"] == ticker]
        if len(tk_crosses) >= 2:
            dates = sorted(set(c["date"] for c in tk_crosses))
            if len(dates) >= 2:
                from datetime import datetime
                d0 = datetime.strptime(dates[0], "%Y-%m-%d")
                d1 = datetime.strptime(dates[-1], "%Y-%m-%d")
                avg_gap = (d1 - d0).days / (len(dates) - 1)
            else:
                avg_gap = 0
        else:
            avg_gap = 0
        p(f"| {ticker} | {s['bars_4h']} | {s['up']} | {s['down']} | {s['total']} | {avg_gap:.1f} |")
    p()

    # ADX distribution at cross
    adx_values = [c["adx_14"] for c in all_crosses if not np.isnan(c["adx_14"])]
    p("## ADX Distribution at Cross")
    p()
    if adx_values:
        adx_arr = np.array(adx_values)
        low = np.sum(adx_arr < 15)
        med = np.sum((adx_arr >= 15) & (adx_arr <= 25))
        high = np.sum(adx_arr > 25)
        p(f"| ADX Bucket | Count | % | Mean ADX |")
        p(f"|------------|------:|--:|---------:|")
        for label, mask_fn in [("< 15 (low trend)", lambda x: x < 15),
                               ("15-25 (moderate)", lambda x: (x >= 15) & (x <= 25)),
                               ("> 25 (strong trend)", lambda x: x > 25)]:
            mask = mask_fn(adx_arr)
            n = int(np.sum(mask))
            pct = 100 * n / len(adx_arr) if len(adx_arr) > 0 else 0
            mean_v = np.mean(adx_arr[mask]) if n > 0 else 0
            p(f"| {label} | {n} | {pct:.1f}% | {mean_v:.1f} |")
        p()
        p(f"Overall: mean={np.mean(adx_arr):.1f}, median={np.median(adx_arr):.1f}, "
          f"std={np.std(adx_arr):.1f}")
        p()

        # ADX by direction
        p("### ADX by Cross Direction")
        p()
        p("| Direction | Mean ADX | Median ADX | % Low (<15) | % High (>25) |")
        p("|-----------|:--------:|:----------:|:-----------:|:------------:|")
        for d in ["UP", "DOWN"]:
            d_adx = np.array([c["adx_14"] for c in all_crosses
                              if c["direction"] == d and not np.isnan(c["adx_14"])])
            if len(d_adx) > 0:
                p(f"| {d} | {np.mean(d_adx):.1f} | {np.median(d_adx):.1f} | "
                  f"{100 * np.sum(d_adx < 15) / len(d_adx):.1f}% | "
                  f"{100 * np.sum(d_adx > 25) / len(d_adx):.1f}% |")
        p()

    # RSI distribution at cross
    rsi_values = [c["rsi_14"] for c in all_crosses if not np.isnan(c["rsi_14"])]
    p("## RSI Distribution at Cross")
    p()
    if rsi_values:
        rsi_arr = np.array(rsi_values)
        p("| RSI Bucket | Count | % |")
        p("|------------|------:|--:|")
        for label, lo, hi in [("< 30 (oversold)", 0, 30), ("30-40", 30, 40),
                              ("40-50", 40, 50), ("50-60", 50, 60),
                              ("60-70", 60, 70), ("> 70 (overbought)", 70, 101)]:
            n = int(np.sum((rsi_arr >= lo) & (rsi_arr < hi)))
            pct = 100 * n / len(rsi_arr)
            p(f"| {label} | {n} | {pct:.1f}% |")
        p()
        p(f"Overall: mean={np.mean(rsi_arr):.1f}, median={np.median(rsi_arr):.1f}")
        p()

        # RSI by direction
        p("### RSI by Cross Direction")
        p()
        p("| Direction | Mean RSI | Median RSI |")
        p("|-----------|:--------:|:----------:|")
        for d in ["UP", "DOWN"]:
            d_rsi = np.array([c["rsi_14"] for c in all_crosses
                              if c["direction"] == d and not np.isnan(c["rsi_14"])])
            if len(d_rsi) > 0:
                p(f"| {d} | {np.mean(d_rsi):.1f} | {np.median(d_rsi):.1f} |")
        p()

    # Time-of-day distribution (AM vs PM)
    p("## Time-of-Day Distribution")
    p()
    am_count = sum(1 for c in all_crosses if c["session"] == "AM")
    pm_count = sum(1 for c in all_crosses if c["session"] == "PM")
    p("| Session | Count | % |")
    p("|---------|------:|--:|")
    p(f"| AM (09:30-13:25) | {am_count} | {100 * am_count / len(all_crosses):.1f}% |")
    p(f"| PM (13:30-15:55) | {pm_count} | {100 * pm_count / len(all_crosses):.1f}% |")
    p()
    p("### By Direction x Session")
    p()
    p("| Direction | AM | PM |")
    p("|-----------|---:|---:|")
    for d in ["UP", "DOWN"]:
        am = sum(1 for c in all_crosses if c["direction"] == d and c["session"] == "AM")
        pm = sum(1 for c in all_crosses if c["direction"] == d and c["session"] == "PM")
        p(f"| {d} | {am} | {pm} |")
    p()

    # Save stats
    stats_path = CONT_DIR / "CROSS_CATALOG_STATS.md"
    with open(stats_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Stats saved: {stats_path}")


if __name__ == "__main__":
    main()
