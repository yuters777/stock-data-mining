#!/usr/bin/env python3
"""Shared utilities for extended-hours 4H bar backtesting.
Used by m4/m6/m7/m9 extended backtest scripts."""

import os
import json

import numpy as np
import pandas as pd

# Project root (one level up from this file's directory)
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_dir(data_dir: str) -> str:
    """Resolve data_dir relative to project root if not absolute."""
    if os.path.isabs(data_dir):
        return data_dir
    return os.path.join(_BASE, data_dir)


# ── Data loading ───────────────────────────────────────────────────────────────

def load_extended_data(ticker: str, data_dir: str = 'Fetched_Data') -> pd.DataFrame:
    """Load {TICKER}_m5_extended.csv.

    Parse 'date' column as datetime (ET naive).
    Add columns: date_only, time_str, hour, minute.
    Return sorted DataFrame.
    """
    path = os.path.join(_resolve_dir(data_dir), f'{ticker}_m5_extended.csv')
    df = pd.read_csv(path)

    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date']).sort_values('date').reset_index(drop=True)

    df['date_only'] = df['date'].dt.date
    df['time_str']  = df['date'].dt.strftime('%H:%M')
    df['hour']      = df['date'].dt.hour
    df['minute']    = df['date'].dt.minute

    return df


# ── 4H bar builder ─────────────────────────────────────────────────────────────

def build_4h_extended(df_m5: pd.DataFrame, mode: str = 'extended') -> pd.DataFrame:
    """Build 4H OHLCV bars from M5 data.

    mode='extended': 4 bars/day
      Bar A: 04:00–07:55 ET
      Bar B: 08:00–11:55 ET
      Bar C: 12:00–15:55 ET
      Bar D: 16:00–19:55 ET

    mode='rth': 2 bars/day (legacy for comparison)
      Bar 1: 09:30–13:25 ET
      Bar 2: 13:30–15:55 ET

    Aggregation per bar:
      open      = first M5 open
      high      = max of M5 highs
      low       = min of M5 lows
      close     = last M5 close
      volume    = sum of M5 volumes
      bar_count = number of M5 bars aggregated

    Rules:
    - Group by date + time slot
    - Skip bars with bar_count < 6 (sparse data)
    - Return DataFrame: date, bar_label, open, high, low, close,
      volume, bar_count
    - Sort by date + bar_label
    """
    df = df_m5.copy()
    tod = df['hour'] * 60 + df['minute']

    bar_label = pd.Series('', index=df.index, dtype=str)

    if mode == 'extended':
        bar_label[(tod >= 240) & (tod <= 475)] = 'A'   # 04:00–07:55
        bar_label[(tod >= 480) & (tod <= 715)] = 'B'   # 08:00–11:55
        bar_label[(tod >= 720) & (tod <= 955)] = 'C'   # 12:00–15:55
        bar_label[(tod >= 960) & (tod <= 1195)] = 'D'  # 16:00–19:55
    else:  # rth
        bar_label[(tod >= 570) & (tod <= 805)] = '1'   # 09:30–13:25
        bar_label[(tod > 805)  & (tod <= 955)] = '2'   # 13:26–15:55 (matches original: > BAR1_E_ET)

    df['bar_label'] = bar_label
    df = df[df['bar_label'] != ''].copy()

    if df.empty:
        return pd.DataFrame(
            columns=['date', 'bar_label', 'open', 'high', 'low',
                     'close', 'volume', 'bar_count']
        )

    # df is already sorted by 'date' (full datetime) from load_extended_data,
    # so 'first'/'last' within each group yield the correct open/close M5 bars.
    bars = (
        df.groupby(['date_only', 'bar_label'], sort=True)
          .agg(
              open=('open',   'first'),
              high=('high',   'max'),
              low=('low',     'min'),
              close=('close', 'last'),
              volume=('volume', 'sum'),
              bar_count=('open', 'count'),
          )
          .reset_index()
          .rename(columns={'date_only': 'date'})
    )

    bars = bars[bars['bar_count'] >= 6].copy()
    bars = bars.sort_values(['date', 'bar_label']).reset_index(drop=True)

    return bars


# ── Technical indicators ───────────────────────────────────────────────────────

def compute_indicators(df_4h: pd.DataFrame, warmup_rows: int = 25) -> pd.DataFrame:
    """Compute technical indicators on 4H bars.

    Indicators:
    - ema9:            EMA with span=9
    - ema21:           EMA with span=21
    - rsi14:           RSI with period=14 (Wilder smoothing)
    - atr14:           ATR with period=14 (Wilder smoothing)
    - adx14:           ADX with period=14 (Wilder smoothing)
    - chandelier_exit: highest_high(22) – 3 × atr14

    Warmup: set all indicators to NaN for first warmup_rows rows (default 25).
            Pass warmup_rows=0 to skip static warmup (e.g. RTH mode when
            gap-based masking is applied separately via apply_ema21_warmup_mask).
    Return df with indicator columns added.
    """
    result = df_4h.copy()

    high  = result['high'].astype(float)
    low   = result['low'].astype(float)
    close = result['close'].astype(float)

    # EMA9 / EMA21
    ema9  = close.ewm(span=9,  adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()

    # RSI-14 — Wilder smoothing (alpha = 1/14)
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_l = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    rsi14 = 100 - 100 / (1 + rs)

    # ATR-14 — True Range then Wilder EMA
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low,
         (high - prev_close).abs(),
         (low  - prev_close).abs()],
        axis=1
    ).max(axis=1)
    atr14 = tr.ewm(alpha=1 / 14, adjust=False).mean()

    # ADX-14 — Wilder smoothing of +DM / -DM
    prev_high = high.shift(1)
    prev_low  = low.shift(1)

    up_move   = high - prev_high
    down_move = prev_low - low

    plus_dm  = np.where((up_move > down_move)   & (up_move > 0),   up_move,   0.0)
    minus_dm = np.where((down_move > up_move)   & (down_move > 0), down_move, 0.0)

    plus_dm_s  = pd.Series(plus_dm,  index=result.index)
    minus_dm_s = pd.Series(minus_dm, index=result.index)

    smooth_plus  = plus_dm_s.ewm(alpha=1 / 14, adjust=False).mean()
    smooth_minus = minus_dm_s.ewm(alpha=1 / 14, adjust=False).mean()

    safe_atr = atr14.replace(0, np.nan)
    plus_di  = 100 * smooth_plus  / safe_atr
    minus_di = 100 * smooth_minus / safe_atr

    di_sum = plus_di + minus_di
    dx     = (100 * (plus_di - minus_di).abs() / di_sum.replace(0, np.nan))
    adx14  = dx.ewm(alpha=1 / 14, adjust=False).mean()

    # Chandelier exit: rolling 22-bar highest high – 3 × ATR14
    chandelier_exit = high.rolling(22).max() - 3 * atr14

    # Assign to result
    result['ema9']            = ema9
    result['ema21']           = ema21
    result['rsi14']           = rsi14
    result['atr14']           = atr14
    result['adx14']           = adx14
    result['chandelier_exit'] = chandelier_exit

    # Warmup: blank out first warmup_rows rows for all indicator columns.
    # Pass warmup_rows=0 to skip (e.g. for RTH mode with gap-based masking).
    if warmup_rows > 0:
        indicator_cols = ['ema9', 'ema21', 'rsi14', 'atr14', 'adx14', 'chandelier_exit']
        result.loc[result.index[:warmup_rows], indicator_cols] = np.nan

    return result


# ── Corrupt bar filter ─────────────────────────────────────────────────────────

def flag_corrupt(closes: pd.Series) -> pd.Series:
    """Return boolean Series: True where adjacent-bar price ratio exceeds 6×.

    Flags stock-split artefacts and bad data (>500% jump between consecutive
    bars).  Contaminates the immediately surrounding bars as well, matching
    the logic in m4_backtest_5yr.flag_corrupt().
    """
    ratio = closes / closes.shift(1)
    bad   = (ratio > 6) | (ratio < 1 / 6)
    return bad | bad.shift(1, fill_value=False) | bad.shift(-1, fill_value=False)


# ── EMA21 gap-based warmup mask ────────────────────────────────────────────────

# Canonical bar start times (ET) for timestamp reconstruction.
# Used by apply_ema21_warmup_mask; matches _BAR_TIME in m4_backtest_extended.py.
_BAR_TIME_ET = {
    'A': (4, 0), 'B': (8, 0), 'C': (12, 0), 'D': (16, 0),
    '1': (9, 30), '2': (13, 30),
}


def apply_ema21_warmup_mask(bars: pd.DataFrame) -> pd.Series:
    """Re-NaN EMA21 for 21 bars after any data gap > 7 calendar days.

    After a multi-day gap the EMA has been carrying forward stale values.
    This function reconstructs bar timestamps from (date, bar_label) and
    NaNs bars i … i+20 whenever the gap to bar i-1 exceeds 7 days —
    matching m4_backtest_5yr.apply_ema21_warmup_mask() behaviour.

    bars must contain columns: 'date', 'bar_label', 'ema21'.
    Returns a new pd.Series (same index) with the masked EMA21 values.
    """
    ema    = bars['ema21'].copy()
    dates  = bars['date'].tolist()
    labels = bars['bar_label'].tolist()
    n      = len(bars)

    def _ts(date, label):
        h, m = _BAR_TIME_ET.get(str(label), (9, 30))
        return pd.Timestamp(str(date)) + pd.Timedelta(hours=h, minutes=m)

    warmup_end = -1
    for i in range(1, n):
        gap_days = (_ts(dates[i], labels[i]) - _ts(dates[i - 1], labels[i - 1])
                    ).total_seconds() / 86400
        if gap_days > 7:
            warmup_end = min(n - 1, i + 20)   # bars i … i+20 inclusive
        if i <= warmup_end:
            ema.iloc[i] = np.nan
    return ema


# ── VIX loader ─────────────────────────────────────────────────────────────────

def load_vix_daily(data_dir: str = 'Fetched_Data') -> pd.DataFrame:
    """Load VIX daily data.

    Try in order:
    1. {data_dir}/VIX_daily_fmp.json       — FMP JSON array (date + close)
    2. {data_dir}/VIX_daily_fmp_full.csv   — FMP full CSV  (date + close cols)
    3. {data_dir}/VIXCLS_FRED_real.csv     — FRED two-column CSV

    Return DataFrame with columns: date (datetime.date), vix_close.
    """
    d = _resolve_dir(data_dir)

    # 1. VIX_daily_fmp.json
    p = os.path.join(d, 'VIX_daily_fmp.json')
    if os.path.exists(p):
        try:
            with open(p) as f:
                records = json.load(f)
            rows = [
                {'date': r['date'], 'vix_close': r['close']}
                for r in records
                if r.get('date') and r.get('close') is not None
            ]
            if rows:
                df = pd.DataFrame(rows)
                df['date']      = pd.to_datetime(df['date'], errors='coerce').dt.date
                df['vix_close'] = pd.to_numeric(df['vix_close'], errors='coerce')
                df = df.dropna().sort_values('date').reset_index(drop=True)
                if not df.empty:
                    return df
        except Exception:
            pass

    # 2. VIX_daily_fmp_full.csv
    p = os.path.join(d, 'VIX_daily_fmp_full.csv')
    if os.path.exists(p):
        try:
            df = pd.read_csv(p)
            # Normalize column names: look for date + close regardless of case
            lc = {c.lower(): c for c in df.columns}
            date_col  = lc.get('date')
            close_col = lc.get('close') or lc.get('adjclose') or lc.get('adj close')
            if date_col and close_col:
                df = df[[date_col, close_col]].copy()
                df.columns = ['date', 'vix_close']
                df['date']      = pd.to_datetime(df['date'], errors='coerce').dt.date
                df['vix_close'] = pd.to_numeric(df['vix_close'], errors='coerce')
                df = df.dropna().sort_values('date').reset_index(drop=True)
                if not df.empty:
                    return df
        except Exception:
            pass

    # 3. VIXCLS_FRED_real.csv
    p = os.path.join(d, 'VIXCLS_FRED_real.csv')
    if os.path.exists(p):
        df = pd.read_csv(p)
        # FRED format: two columns (DATE, VIXCLS) — or (date, vix)
        df.columns = ['date', 'vix_close']
        df = df[df['vix_close'] != '.'].copy()   # FRED uses '.' for missing
        df['date']      = pd.to_datetime(df['date'], errors='coerce').dt.date
        df['vix_close'] = pd.to_numeric(df['vix_close'], errors='coerce')
        df = df.dropna().sort_values('date').reset_index(drop=True)
        if not df.empty:
            return df

    raise FileNotFoundError(
        f'No VIX daily data file found in {d}. '
        'Expected VIX_daily_fmp.json, VIX_daily_fmp_full.csv, '
        'or VIXCLS_FRED_real.csv.'
    )


# ── Earnings loader ────────────────────────────────────────────────────────────

def load_earnings(data_dir: str = 'backtester/data') -> dict:
    """Load earnings calendar.

    Try: {data_dir}/fmp_earnings.csv  (ticker, earnings_date, ...)
    Fallback: {data_dir}/earnings_calendar.json  ({ticker: [dates]})

    Return dict: {ticker: [list of datetime.date objects]}
    """
    import datetime

    d = _resolve_dir(data_dir)

    # 1. fmp_earnings.csv
    p = os.path.join(d, 'fmp_earnings.csv')
    if os.path.exists(p):
        try:
            df = pd.read_csv(p)
            lc = {c.lower(): c for c in df.columns}
            ticker_col = lc.get('ticker') or lc.get('symbol')
            date_col   = lc.get('earnings_date') or lc.get('date')
            if ticker_col and date_col:
                df = df[[ticker_col, date_col]].copy()
                df.columns = ['ticker', 'date']
                df['date'] = pd.to_datetime(df['date'], errors='coerce').dt.date
                df = df.dropna()
                result = {}
                for ticker, grp in df.groupby('ticker'):
                    result[ticker] = sorted(grp['date'].tolist())
                return result
        except Exception:
            pass

    # 2. earnings_calendar.json
    p = os.path.join(d, 'earnings_calendar.json')
    if os.path.exists(p):
        try:
            with open(p) as f:
                raw = json.load(f)
            result = {}
            for ticker, dates in raw.items():
                parsed = []
                for d_str in dates:
                    try:
                        parsed.append(
                            datetime.date.fromisoformat(str(d_str)[:10])
                        )
                    except ValueError:
                        pass
                result[ticker] = sorted(parsed)
            return result
        except Exception:
            pass

    # Nothing found — return empty dict rather than raising
    return {}


# ── Earnings proximity check ───────────────────────────────────────────────────

def is_earnings_window(
    ticker: str,
    date,
    earnings_dict: dict,
    buffer_days: int = 6,
) -> bool:
    """Check if date is within ±buffer_days of any earnings date for ticker.

    Parameters
    ----------
    ticker        : equity symbol (e.g. 'AAPL')
    date          : datetime.date or anything coercible to one
    earnings_dict : returned by load_earnings()
    buffer_days   : symmetric window radius in calendar days (default 6)

    Returns
    -------
    True if the date falls within [earnings_date - buffer_days,
                                    earnings_date + buffer_days]
    for any earnings date in the ticker's list, else False.
    """
    import datetime

    dates = earnings_dict.get(ticker, [])
    if not dates:
        return False

    if not isinstance(date, datetime.date):
        date = pd.to_datetime(date).date()

    delta = datetime.timedelta(days=buffer_days)
    for ed in dates:
        if not isinstance(ed, datetime.date):
            try:
                ed = datetime.date.fromisoformat(str(ed)[:10])
            except ValueError:
                continue
        if (ed - delta) <= date <= (ed + delta):
            return True
    return False
