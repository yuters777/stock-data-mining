#!/usr/bin/env python3
"""M7 Extended Backtest — Phase 1: Data pipeline skeleton.

Loads M5 extended data for all 27 equity tickers, resamples to daily
RTH bars, and computes daily indicators.  No trading logic yet.

Usage: python scripts/m7_backtest_extended.py
"""
import sys
import os

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_utils_extended import load_extended_data

# 27 equity tickers: 22-ticker M4 baseline + ARM, INTC, JD, MSTR, SMCI
TICKERS = [
    'AAPL', 'AMD', 'AMZN', 'ARM', 'AVGO', 'BA', 'BABA', 'BIDU',
    'C', 'COIN', 'COST', 'GOOGL', 'GS', 'INTC', 'JD', 'JPM',
    'MARA', 'META', 'MSFT', 'MSTR', 'MU', 'NVDA', 'PLTR',
    'SMCI', 'TSLA', 'TSM', 'V',
]  # 27 equities

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Known baseline from prior M7 backtest (all dates, 27 tickers)
KNOWN_BASELINE = {
    'N':  168,
    'PF': 1.85,
}

# RTH filter: 09:30–15:55 ET expressed as minutes-of-day
_RTH_START = 9 * 60 + 30   # 570
_RTH_END   = 15 * 60 + 55  # 955


# ── Data loading ───────────────────────────────────────────────────────────────

def load_all_tickers(data_dir: str = 'Fetched_Data') -> dict:
    """Load M5 extended data for all 27 tickers.

    Skips tickers whose _m5_extended.csv is missing (prints a notice).

    Returns
    -------
    dict : {ticker: df_m5}
    """
    result = {}
    for ticker in TICKERS:
        try:
            df = load_extended_data(ticker, data_dir=data_dir)
            result[ticker] = df
        except FileNotFoundError:
            print(f'  {ticker}: SKIP (no _m5_extended.csv)')
    return result


# ── Daily bar builder ──────────────────────────────────────────────────────────

def build_daily_from_m5(df_m5: pd.DataFrame) -> pd.DataFrame:
    """Resample M5 bars to daily RTH bars (09:30–15:55 ET).

    Per day:
      open      = first RTH bar open
      high      = max RTH high
      low       = min RTH low
      close     = last RTH close
      volume    = sum RTH volume
      bar_count = number of M5 bars contributing

    Returns
    -------
    pd.DataFrame indexed by date (date_only), sorted ascending.
    Columns: open, high, low, close, volume, bar_count.
    """
    tod = df_m5['hour'] * 60 + df_m5['minute']
    rth = df_m5[(tod >= _RTH_START) & (tod <= _RTH_END)]

    if rth.empty:
        return pd.DataFrame(
            columns=['open', 'high', 'low', 'close', 'volume', 'bar_count']
        )

    daily = rth.groupby('date_only').agg(
        open=     ('open',  'first'),
        high=     ('high',  'max'),
        low=      ('low',   'min'),
        close=    ('close', 'last'),
        volume=   ('volume','sum'),
        bar_count=('close', 'count'),
    )
    daily.index.name = 'date'
    return daily.sort_index()


# ── Daily indicators ───────────────────────────────────────────────────────────

def compute_daily_indicators(daily_df: pd.DataFrame) -> pd.DataFrame:
    """Compute EMA9, EMA21, 20-day return, and 60-day rolling high.

    Parameters
    ----------
    daily_df : output of build_daily_from_m5 — must have a 'close' column.

    Returns
    -------
    pd.DataFrame with added columns: ema9, ema21, ret_20d, high_60d.
    NaN values are preserved for warmup / insufficient history.
    """
    df = daily_df.copy()
    close = df['close']

    df['ema9']    = close.ewm(span=9,  adjust=False).mean()
    df['ema21']   = close.ewm(span=21, adjust=False).mean()
    df['ret_20d'] = close.pct_change(20) * 100   # 20-day return (%)
    df['high_60d']= close.rolling(60).max()       # 60-day rolling high

    return df


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('=' * 60)
    print('M7 BACKTEST — Phase 1: Data Pipeline Check')
    print(f'KNOWN_BASELINE: N={KNOWN_BASELINE["N"]}, PF={KNOWN_BASELINE["PF"]}')
    print('=' * 60)

    print(f'\nLoading M5 data for {len(TICKERS)} tickers...')
    ticker_data = load_all_tickers()
    print(f'Loaded {len(ticker_data)}/{len(TICKERS)} tickers.\n')

    print(f'  {"Ticker":<8} {"M5 rows":>10} {"Daily bars":>12}  Date range')
    print('  ' + '-' * 56)

    for ticker, df_m5 in ticker_data.items():
        daily = build_daily_from_m5(df_m5)
        daily = compute_daily_indicators(daily)

        if daily.empty:
            date_range = 'empty'
        else:
            date_range = f'{daily.index.min()} to {daily.index.max()}'

        print(f'  {ticker:<8} {len(df_m5):>10,} {len(daily):>12,}  {date_range}')

    print('\nPhase 1 complete — data pipeline verified.  No trading logic yet.')
