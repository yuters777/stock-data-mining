#!/usr/bin/env python3
"""Audit: EMA9/EMA21 crosses on 4H bars built from M5 regular-session data.

4H bars:
  Bar 1: 09:30–13:25 (first half of session)
  Bar 2: 13:30–15:55 (second half of session)
  OHLCV: O=first Open, H=max High, L=min Low, C=last Close, V=sum Volume

EMA crossover detection:
  Cross UP:   EMA9 > EMA21 where prior bar EMA9 <= EMA21
  Cross DOWN: EMA9 < EMA21 where prior bar EMA9 >= EMA21
"""

import csv
import os
from collections import defaultdict

BACKTEST_DIR = os.path.join(os.path.dirname(__file__), "..")
AUDIT_DIR = os.path.dirname(__file__)

# Exclude non-equity tickers
EXCLUDE = {"IBIT", "VIXY"}

TICKERS = sorted(
    f.replace("_m5_regsess.csv", "")
    for f in os.listdir(BACKTEST_DIR)
    if f.endswith("_m5_regsess.csv")
    and f.replace("_m5_regsess.csv", "") not in EXCLUDE
)

print(f"Tickers ({len(TICKERS)}): {', '.join(TICKERS)}")


def ema(values, period):
    """Compute EMA series. Returns list same length as values."""
    result = []
    k = 2 / (period + 1)
    prev = None
    for v in values:
        if prev is None:
            prev = v
        else:
            prev = v * k + prev * (1 - k)
        result.append(prev)
    return result


all_crosses = []

for ticker in TICKERS:
    fpath = os.path.join(BACKTEST_DIR, f"{ticker}_m5_regsess.csv")

    # Load M5 bars grouped by date
    day_bars = defaultdict(list)
    with open(fpath) as f:
        for row in csv.DictReader(f):
            date_str = row["Datetime"][:10]
            hhmm = row["Datetime"][11:16]
            day_bars[date_str].append({
                "hhmm": hhmm,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(float(row["Volume"])),
            })

    # Build 4H bars: two per day
    bars_4h = []
    for date_str in sorted(day_bars.keys()):
        m5 = day_bars[date_str]
        # Split: bar1 = 09:30-13:25, bar2 = 13:30-15:55
        bar1_m5 = [b for b in m5 if b["hhmm"] < "13:30"]
        bar2_m5 = [b for b in m5 if b["hhmm"] >= "13:30"]

        for half_label, half_bars in [("AM", bar1_m5), ("PM", bar2_m5)]:
            if not half_bars:
                continue
            bars_4h.append({
                "date": date_str,
                "half": half_label,
                "open": half_bars[0]["open"],
                "high": max(b["high"] for b in half_bars),
                "low": min(b["low"] for b in half_bars),
                "close": half_bars[-1]["close"],
                "volume": sum(b["volume"] for b in half_bars),
            })

    if len(bars_4h) < 22:
        print(f"  {ticker}: only {len(bars_4h)} 4H bars — skipping")
        continue

    # Compute EMAs on close series
    closes = [b["close"] for b in bars_4h]
    ema9 = ema(closes, 9)
    ema21 = ema(closes, 21)

    # Detect crosses
    for i in range(1, len(bars_4h)):
        prev_diff = ema9[i - 1] - ema21[i - 1]
        curr_diff = ema9[i] - ema21[i]

        direction = None
        if prev_diff <= 0 and curr_diff > 0:
            direction = "UP"
        elif prev_diff >= 0 and curr_diff < 0:
            direction = "DOWN"

        if direction:
            b = bars_4h[i]
            all_crosses.append({
                "date": b["date"],
                "half": b["half"],
                "ticker": ticker,
                "direction": direction,
                "close": f"{b['close']:.4f}",
                "ema9": f"{ema9[i]:.4f}",
                "ema21": f"{ema21[i]:.4f}",
            })

# ── Save CSV ────────────────────────────────────────────────────────────────
csv_path = os.path.join(AUDIT_DIR, "ema_4h_crosses.csv")
with open(csv_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(all_crosses[0].keys()))
    writer.writeheader()
    writer.writerows(all_crosses)

# ── Print results ───────────────────────────────────────────────────────────
N = len(all_crosses)
print(f"\nTotal EMA9/EMA21 4H crosses: {N}")
print(f"  UP:   {sum(1 for c in all_crosses if c['direction'] == 'UP')}")
print(f"  DOWN: {sum(1 for c in all_crosses if c['direction'] == 'DOWN')}")

print(f"\nPer-ticker count:")
print(f"  {'Ticker':<8} {'Total':>6} {'UP':>5} {'DOWN':>5}")
print(f"  {'-' * 28}")
for ticker in TICKERS:
    tc = [c for c in all_crosses if c["ticker"] == ticker]
    up = sum(1 for c in tc if c["direction"] == "UP")
    dn = sum(1 for c in tc if c["direction"] == "DOWN")
    if tc:
        print(f"  {ticker:<8} {len(tc):>6} {up:>5} {dn:>5}")

print(f"\nSample rows (first 15):")
print(f"  {'date':<12} {'half':<5} {'ticker':<7} {'dir':<5} {'close':>10} {'ema9':>10} {'ema21':>10}")
print(f"  {'-' * 62}")
for c in all_crosses[:15]:
    print(f"  {c['date']:<12} {c['half']:<5} {c['ticker']:<7} {c['direction']:<5} {c['close']:>10} {c['ema9']:>10} {c['ema21']:>10}")

print(f"\nSaved: {csv_path}")
