#!/usr/bin/env python3
"""Compute technical indicators on M5 regsess data for selected tickers.

Indicators:
  - EMA9, EMA21 (on Close)
  - RSI(14) with Wilder smoothing
  - ADX(14) with +DI, -DI
  - Squeeze: BB_width vs KC_width, squeeze_on = BB < KC

Volume-based indicators excluded (Alpha Vantage single-exchange volume
is ~1000x undercount vs consolidated tape for individual tickers).
"""

import csv
import os
import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKTEST_DIR = os.path.join(SCRIPT_DIR, "..", "..")
TICKERS = ["NVDA", "TSLA", "GOOGL", "IBIT", "GS"]


def load_m5(ticker):
    fpath = os.path.join(BACKTEST_DIR, f"{ticker}_m5_regsess.csv")
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


def ema(values, period):
    """Exponential moving average."""
    out = np.full(len(values), np.nan)
    if len(values) < period:
        return out
    out[period - 1] = np.mean(values[:period])
    k = 2.0 / (period + 1)
    for i in range(period, len(values)):
        out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out


def rsi_wilder(closes, period=14):
    """RSI with Wilder (exponential) smoothing."""
    n = len(closes)
    out = np.full(n, np.nan)
    if n < period + 1:
        return out
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            out[i + 1] = 100.0
        else:
            out[i + 1] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def adx_dmi(highs, lows, closes, period=14):
    """ADX with +DI and -DI using Wilder smoothing."""
    n = len(highs)
    pdi = np.full(n, np.nan)
    mdi = np.full(n, np.nan)
    adx = np.full(n, np.nan)

    if n < period + 1:
        return adx, pdi, mdi

    # True Range
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hc, lc)

    # +DM, -DM
    pdm = np.zeros(n)
    mdm = np.zeros(n)
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        pdm[i] = up if (up > down and up > 0) else 0.0
        mdm[i] = down if (down > up and down > 0) else 0.0

    # Wilder smoothing for TR, +DM, -DM
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

    # +DI, -DI, DX
    dx = np.zeros(n)
    for i in range(period, n):
        if atr_s[i] > 0:
            pdi[i] = 100.0 * pdm_s[i] / atr_s[i]
            mdi[i] = 100.0 * mdm_s[i] / atr_s[i]
        else:
            pdi[i] = 0.0
            mdi[i] = 0.0
        di_sum = pdi[i] + mdi[i]
        if di_sum > 0:
            dx[i] = 100.0 * abs(pdi[i] - mdi[i]) / di_sum
        else:
            dx[i] = 0.0

    # ADX = Wilder smooth of DX
    adx_start = 2 * period
    if n > adx_start:
        adx[adx_start] = np.mean(dx[period:adx_start + 1])
        for i in range(adx_start + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    return adx, pdi, mdi


def squeeze(closes, highs, lows, bb_period=20, atr_period=14, kc_mult=1.5):
    """Bollinger Band width vs Keltner Channel width squeeze detection."""
    n = len(closes)
    squeeze_on = np.zeros(n, dtype=int)

    # ATR for KC
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hc, lc)

    atr = np.full(n, np.nan)
    if n >= atr_period:
        atr[atr_period - 1] = np.mean(tr[:atr_period])
        k = 2.0 / (atr_period + 1)
        for i in range(atr_period, n):
            atr[i] = tr[i] * k + atr[i - 1] * (1 - k)

    for i in range(bb_period - 1, n):
        window = closes[i - bb_period + 1:i + 1]
        bb_width = 2.0 * np.std(window, ddof=0)  # 2 * std = one-side band width
        if not np.isnan(atr[i]):
            kc_width = 2.0 * atr[i] * kc_mult
            if bb_width < kc_width:
                squeeze_on[i] = 1

    return squeeze_on


def process_ticker(ticker):
    bars = load_m5(ticker)
    n = len(bars)
    closes = np.array([b["Close"] for b in bars])
    highs = np.array([b["High"] for b in bars])
    lows = np.array([b["Low"] for b in bars])

    ema9 = ema(closes, 9)
    ema21 = ema(closes, 21)
    rsi14 = rsi_wilder(closes, 14)
    adx14, pdi14, mdi14 = adx_dmi(highs, lows, closes, 14)
    sq_on = squeeze(closes, highs, lows)

    # Write CSV
    outpath = os.path.join(SCRIPT_DIR, f"indicators_{ticker}.csv")
    with open(outpath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Datetime", "Open", "High", "Low", "Close", "Volume",
                          "ema9", "ema21", "rsi14", "adx14", "pdi14", "mdi14", "squeeze_on"])
        for i in range(n):
            writer.writerow([
                bars[i]["Datetime"],
                f"{bars[i]['Open']:.4f}",
                f"{bars[i]['High']:.4f}",
                f"{bars[i]['Low']:.4f}",
                f"{bars[i]['Close']:.4f}",
                bars[i]["Volume"],
                f"{ema9[i]:.4f}" if not np.isnan(ema9[i]) else "",
                f"{ema21[i]:.4f}" if not np.isnan(ema21[i]) else "",
                f"{rsi14[i]:.2f}" if not np.isnan(rsi14[i]) else "",
                f"{adx14[i]:.2f}" if not np.isnan(adx14[i]) else "",
                f"{pdi14[i]:.2f}" if not np.isnan(pdi14[i]) else "",
                f"{mdi14[i]:.2f}" if not np.isnan(mdi14[i]) else "",
                sq_on[i],
            ])

    # Verification stats
    valid_mask = ~np.isnan(ema9) & ~np.isnan(rsi14) & ~np.isnan(adx14)
    valid_idx = np.where(valid_mask)[0]
    if len(valid_idx) == 0:
        print(f"  {ticker}: {n} rows — NO valid indicator rows")
        return

    # Sample from middle
    mid = valid_idx[len(valid_idx) // 2]
    ema9_diff_pct = np.nanmean(np.abs(ema9[valid_idx] - closes[valid_idx]) / closes[valid_idx]) * 100
    rsi_median = np.nanmedian(rsi14[valid_idx])
    adx_median = np.nanmedian(adx14[valid_idx])
    sq_pct = 100.0 * np.sum(sq_on[valid_idx]) / len(valid_idx)

    print(f"  {ticker}: {n:>6} rows | EMA9 avg diff from Close: {ema9_diff_pct:.3f}% | "
          f"RSI median: {rsi_median:.1f} | ADX median: {adx_median:.1f} | "
          f"Squeeze%: {sq_pct:.1f}%")

    # Sanity checks
    warnings = []
    if ema9_diff_pct > 1.0:
        warnings.append(f"EMA9 drift {ema9_diff_pct:.2f}% > 1%")
    if rsi_median < 30 or rsi_median > 70:
        warnings.append(f"RSI median {rsi_median:.1f} outside 30-70")
    if adx_median < 5 or adx_median > 60:
        warnings.append(f"ADX median {adx_median:.1f} outside 10-50 range")
    if warnings:
        print(f"    ⚠ WARNINGS: {'; '.join(warnings)}")
    else:
        print(f"    ✓ All sanity checks passed")

    # Sample row
    print(f"    Sample row [{mid}]: Close={closes[mid]:.2f} EMA9={ema9[mid]:.2f} "
          f"EMA21={ema21[mid]:.2f} RSI={rsi14[mid]:.1f} ADX={adx14[mid]:.1f} "
          f"+DI={pdi14[mid]:.1f} -DI={mdi14[mid]:.1f} Sq={sq_on[mid]}")

    return outpath


print("=" * 80)
print("INDICATOR COMPUTATION: M5 REGSESS DATA")
print("=" * 80)
print(f"Tickers: {', '.join(TICKERS)}")
print(f"Indicators: EMA9, EMA21, RSI(14), ADX(14), +DI(14), -DI(14), Squeeze")
print(f"Note: Volume-based indicators excluded (single-exchange data)")
print()

for ticker in TICKERS:
    try:
        process_ticker(ticker)
    except FileNotFoundError:
        print(f"  {ticker}: FILE NOT FOUND — skipped")

print()
print("Done.")
