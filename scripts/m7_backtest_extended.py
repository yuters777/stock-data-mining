#!/usr/bin/env python3
"""M7 Extended Backtest — Phase 2: Signal Detection.

Loads M5 extended data for all 27 equity tickers, resamples to daily
RTH bars and 4H bars (both modes), computes daily indicators and
cross-ticker RS ranks, then detects M7 momentum-pullback signals.
No trade simulation yet.

Usage: python scripts/m7_backtest_extended.py
"""
import sys
import os

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_utils_extended import (
    load_extended_data,
    build_4h_extended,
    compute_indicators,
    apply_ema21_warmup_mask,
    load_vix_daily,
    load_earnings,
    is_earnings_window,
)

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


# ── RS ranks ──────────────────────────────────────────────────────────────────

def compute_rs_ranks(daily_data_dict: dict) -> dict:
    """Rank all tickers by 20-day return for each date.

    Returns {(date, ticker): rank_pct} where 0.0 = best RS (highest
    20d return). Top 30% = rank_pct <= 0.30.
    Dates with fewer than 2 valid tickers are skipped.
    """
    rows = []
    for ticker, daily in daily_data_dict.items():
        if 'ret_20d' not in daily.columns:
            continue
        sub = daily[['ret_20d']].dropna().reset_index()   # cols: date, ret_20d
        sub['ticker'] = ticker
        rows.append(sub)

    if not rows:
        return {}

    df = pd.concat(rows, ignore_index=True)

    result = {}
    for date, grp in df.groupby('date'):
        n = len(grp)
        if n < 2:
            continue
        # rank ascending=False: rank 1 = highest 20d return (best RS)
        ranked = grp['ret_20d'].rank(ascending=False, method='average')
        for idx in grp.index:
            rp = (ranked.at[idx] - 1) / (n - 1)   # normalised: 0.0 = best
            result[(date, grp.at[idx, 'ticker'])] = round(float(rp), 4)

    return result


# ── Red-streak finder ─────────────────────────────────────────────────────────

def find_red_streaks(daily_df: pd.DataFrame, max_streak: int = 3) -> list:
    """Find dates that end a consecutive red-bar run of 1–max_streak days.

    A red bar is defined as close < previous day's close.

    Returns
    -------
    list of (streak_end_date, streak_len, streak_dates)
        streak_end_date : date of the last bar in the streak
        streak_len      : number of consecutive red bars (1..max_streak)
        streak_dates    : list of dates in the streak (oldest first)
    """
    closes = daily_df['close'].values
    dates  = daily_df.index.tolist()
    n      = len(daily_df)

    # streak[i] = consecutive red bars ending at bar i
    streak = np.zeros(n, dtype=int)
    for i in range(1, n):
        if closes[i] < closes[i - 1]:
            streak[i] = streak[i - 1] + 1

    results = []
    for i in range(n):
        s = int(streak[i])
        if 1 <= s <= max_streak:
            start = i - s + 1
            results.append((dates[i], s, dates[start:i + 1]))

    return results


# ── 4H pullback-above-EMA21 check ─────────────────────────────────────────────

def check_pullback_above_ema21(
    ticker: str,
    streak_dates: list,
    bars_4h: pd.DataFrame,
) -> bool:
    """Return True if every 4H bar on every streak day closes above EMA21.

    ticker is accepted for API symmetry but is not used (bars_4h is
    already scoped to the ticker by the caller).
    """
    for date in streak_dates:
        day_bars = bars_4h[bars_4h['date'] == date]
        if day_bars.empty:
            return False
        for _, bar in day_bars.iterrows():
            if pd.isna(bar['ema21']) or bar['close'] <= bar['ema21']:
                return False
    return True


# ── M7 signal detector ────────────────────────────────────────────────────────

def detect_m7_signals(
    ticker: str,
    daily: pd.DataFrame,
    bars_4h_rth: pd.DataFrame,
    bars_4h_ext: pd.DataFrame,
    vix_df: pd.DataFrame,
    earnings: dict,
    rs_ranks: dict,
) -> tuple:
    """Detect M7 momentum-pullback signals for one ticker.

    Filters (ALL): red streak 1–3d | prior VIX < 20 | RS top 30% |
    within 5% of 60d high | all 4H streak bars above EMA21 (per mode) |
    today daily close > pre-pullback close (spec §2.1 #5) | no earnings ±6d.

    Returns (rth_signals, ext_signals) — each a list of signal dicts:
        ticker, signal_date, entry_day_high, pullback_low,
        vix_at_entry, rs_rank, streak_len
    """
    rth_signals: list = []
    ext_signals: list = []

    if daily.empty or len(daily) < 22:
        return rth_signals, ext_signals

    streak_map = {
        d: (slen, sdates)
        for d, slen, sdates in find_red_streaks(daily)
    }

    dates  = daily.index.tolist()
    closes = daily['close'].values

    def _prior_vix(date):
        mask = vix_df['date'] < date
        return float(vix_df.loc[mask, 'vix_close'].iloc[-1]) if mask.any() else np.nan

    for i, d in enumerate(dates):
        if d not in streak_map:
            continue
        slen, streak_dates = streak_map[d]

        # Gate 1: VIX < 20
        vix_val = _prior_vix(d)
        if np.isnan(vix_val) or vix_val >= 20.0:
            continue

        # Gate 2: RS top 30%
        rs_rank = rs_ranks.get((d, ticker), np.nan)
        if np.isnan(rs_rank) or rs_rank > 0.30:
            continue

        # Gate 3: within 5% of 60d high
        high_60d = daily.at[d, 'high_60d']
        if pd.isna(high_60d) or closes[i] < 0.95 * high_60d:
            continue

        # Gate 4: earnings block
        if is_earnings_window(ticker, d, earnings):
            continue

        entry_day_high = float(daily.at[d, 'high'])
        streak_slice   = daily.iloc[i - slen + 1:i + 1]
        pullback_low   = float(streak_slice['low'].min())
        # G6: today's daily close must exceed the close of the bar immediately
        # before the streak started (spec §2.1 #5: "pre_pullback_close").
        pullback_high  = float(daily.iloc[i - slen]['close'])
        recovery       = closes[i] > pullback_high

        base = {
            'ticker':         ticker,
            'signal_date':    str(d),
            'entry_day_high': round(entry_day_high, 4),
            'pullback_low':   round(pullback_low, 4),
            'pullback_high':  round(pullback_high, 4),
            'vix_at_entry':   round(float(vix_val), 2),
            'rs_rank':        round(float(rs_rank), 4),
            'streak_len':     slen,
        }

        # G6 is mode-independent (daily close vs pre-pullback close).
        # G5 (pullback above EMA21 on 4H bars) is still mode-specific.
        if recovery:
            if check_pullback_above_ema21(ticker, streak_dates, bars_4h_rth):
                rth_signals.append(dict(base))
            if check_pullback_above_ema21(ticker, streak_dates, bars_4h_ext):
                ext_signals.append(dict(base))

    return rth_signals, ext_signals


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('=' * 60)
    print('M7 BACKTEST — Phase 2: Signal Detection')
    print(f'KNOWN_BASELINE: N={KNOWN_BASELINE["N"]}, PF={KNOWN_BASELINE["PF"]}')
    print('=' * 60)

    print(f'\nLoading M5 data for {len(TICKERS)} tickers...')
    ticker_data = load_all_tickers()
    print(f'Loaded {len(ticker_data)}/{len(TICKERS)} tickers.')

    print('Loading VIX...')
    vix_df = load_vix_daily()
    print(f'  VIX: {len(vix_df)} rows, '
          f'{vix_df["date"].min()} to {vix_df["date"].max()}')

    print('Loading earnings...')
    earnings = load_earnings()
    print(f'  Earnings: {len(earnings)} tickers covered.')

    print('\nBuilding bars and indicators...')
    daily_data: dict = {}
    bars_rth:   dict = {}
    bars_ext:   dict = {}

    for ticker, df_m5 in ticker_data.items():
        daily = build_daily_from_m5(df_m5)
        daily_data[ticker] = compute_daily_indicators(daily)

        b_rth = build_4h_extended(df_m5, mode='rth')
        b_rth = compute_indicators(b_rth, warmup_rows=0)
        b_rth['ema21'] = apply_ema21_warmup_mask(b_rth)
        bars_rth[ticker] = b_rth

        b_ext = build_4h_extended(df_m5, mode='extended')
        bars_ext[ticker] = compute_indicators(b_ext)

    print('Computing RS ranks...')
    rs_ranks = compute_rs_ranks(daily_data)
    print(f'  RS rank entries: {len(rs_ranks):,}')

    print('\nDetecting M7 signals...\n')
    all_rth: list = []
    all_ext: list = []

    print(f'  {"Ticker":<8} {"RTH_signals":>12} {"EXT_signals":>12} {"Delta":>8}')
    print('  ' + '-' * 44)

    for ticker in TICKERS:
        if ticker not in daily_data:
            print(f'  {ticker:<8}  SKIP')
            continue
        rth_sigs, ext_sigs = detect_m7_signals(
            ticker,
            daily_data[ticker],
            bars_rth.get(ticker, pd.DataFrame()),
            bars_ext.get(ticker, pd.DataFrame()),
            vix_df,
            earnings,
            rs_ranks,
        )
        all_rth.extend(rth_sigs)
        all_ext.extend(ext_sigs)
        delta = len(ext_sigs) - len(rth_sigs)
        print(f'  {ticker:<8} {len(rth_sigs):>12} {len(ext_sigs):>12} {delta:>+8}')

    print('  ' + '-' * 44)
    total_delta = len(all_ext) - len(all_rth)
    print(f'  {"TOTAL":<8} {len(all_rth):>12} {len(all_ext):>12} {total_delta:>+8}')
    print('\nPhase 2 complete — signal detection only.  No trade simulation yet.')
