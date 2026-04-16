#!/usr/bin/env python3
"""Quick test for backtest_utils_extended.py
Run: python scripts/run_quick_test.py
Expects: Fetched_Data/AAPL_m5_extended.csv to exist
"""

import sys
import os

# Ensure the scripts/ directory is on the path so the import works
# regardless of the working directory the user calls this from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest_utils_extended import (
    load_extended_data,
    build_4h_extended,
    compute_indicators,
    load_vix_daily,
    load_earnings,
    is_earnings_window,
)

# ── Test 1: Load data ──────────────────────────────────────────────────────────
print("=" * 60)
print("Test 1: load_extended_data('AAPL')")
print("=" * 60)
df = load_extended_data('AAPL')
print(f"Loaded {len(df)} M5 bars")
print(f"Date range: {df['date_only'].min()} to {df['date_only'].max()}")
print(f"Time range: {df['time_str'].min()} to {df['time_str'].max()}")
print(f"Columns: {list(df.columns)}")

# ── Test 2: Build 4H extended ──────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Test 2: build_4h_extended(df, mode='extended')")
print("=" * 60)
bars_ext = build_4h_extended(df, mode='extended')
print(f"Extended 4H: {len(bars_ext)} bars")
days = bars_ext['date'].nunique()
print(f"Trading days: {days}")
print(f"Avg bars/day: {len(bars_ext)/days:.1f}")
print(f"Bar labels seen: {sorted(bars_ext['bar_label'].unique())}")
print("\nFirst 10 bars:")
print(bars_ext.head(10).to_string(index=False))

# ── Test 3: Build 4H RTH (comparison) ─────────────────────────────────────────
print("\n" + "=" * 60)
print("Test 3: build_4h_extended(df, mode='rth')")
print("=" * 60)
bars_rth = build_4h_extended(df, mode='rth')
print(f"RTH 4H: {len(bars_rth)} bars")
rth_days = bars_rth['date'].nunique()
print(f"Avg bars/day: {len(bars_rth)/rth_days:.1f}")
print(f"Bar labels seen: {sorted(bars_rth['bar_label'].unique())}")
print(f"Ratio extended/rth: {len(bars_ext)/len(bars_rth):.2f}x")

# ── Test 4: Indicators ─────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Test 4: compute_indicators(bars_ext)")
print("=" * 60)
bars_ind = compute_indicators(bars_ext)
valid = bars_ind.dropna(subset=['ema9', 'ema21', 'rsi14'])
print(f"Indicator cols: {['ema9','ema21','rsi14','atr14','adx14','chandelier_exit']}")
print(f"Bars with valid ema9/ema21/rsi14: {len(valid)} / {len(bars_ind)}")
print("\nFirst 5 valid rows:")
print(
    valid[['date', 'bar_label', 'close', 'ema9', 'ema21',
           'rsi14', 'atr14', 'adx14', 'chandelier_exit']]
    .head(5)
    .to_string(index=False)
)

# Sanity checks
assert 'ema9' in bars_ind.columns, "ema9 missing"
assert 'chandelier_exit' in bars_ind.columns, "chandelier_exit missing"
assert bars_ind.iloc[:25][['ema9','ema21','rsi14','atr14','adx14','chandelier_exit']].isna().all().all(), \
    "Warmup rows should all be NaN"

# ── Test 5: VIX ────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Test 5: load_vix_daily()")
print("=" * 60)
try:
    vix = load_vix_daily()
    print(f"VIX: {len(vix)} days")
    print(f"Date range: {vix['date'].min()} to {vix['date'].max()}")
    print(f"VIX range: {vix['vix_close'].min():.2f} to {vix['vix_close'].max():.2f}")
except FileNotFoundError as e:
    print(f"WARNING: VIX not loaded — {e}")

# ── Test 6: Earnings ───────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Test 6: load_earnings() + is_earnings_window()")
print("=" * 60)
earn = load_earnings()
print(f"Earnings: {len(earn)} tickers")
if earn:
    sample = list(earn.items())[:3]
    for tk, dates in sample:
        print(f"  {tk}: {dates[:4]}")

    # is_earnings_window sanity check
    import datetime
    first_ticker = next(iter(earn))
    first_date   = earn[first_ticker][0] if earn[first_ticker] else None
    if first_date:
        in_win  = is_earnings_window(first_ticker, first_date, earn, buffer_days=6)
        out_win = is_earnings_window(first_ticker,
                                     first_date - datetime.timedelta(days=30),
                                     earn, buffer_days=6)
        print(f"\n  is_earnings_window({first_ticker}, {first_date}, buffer=6): {in_win}  (expect True)")
        print(f"  is_earnings_window({first_ticker}, {first_date - datetime.timedelta(days=30)}, buffer=6): {out_win}  (expect False)")
        assert in_win,  "Expected True for exact earnings date"
        assert not out_win, "Expected False 30 days before earnings"

print("\n" + "=" * 60)
print("All tests passed!")
print("=" * 60)
