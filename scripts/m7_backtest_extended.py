#!/usr/bin/env python3
"""M7 Extended Backtest — Phase 3: Full Backtest with Trade Simulation.

Loads M5 extended data for all 27 equity tickers, resamples to daily
RTH bars and 4H bars (both modes), computes daily indicators and
cross-ticker RS ranks, detects M7 momentum-pullback signals via a
state machine, simulates trades, and saves comparison results.

Usage: python scripts/m7_backtest_extended.py
"""
import sys
import os
import datetime

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

_BASE   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(_BASE, 'results', 'extended_validation')

# Known baseline from prior M7 backtest
KNOWN_BASELINE = {
    'N':      168,
    'PF':     1.85,
    'PF_OOS': 1.11,   # 2025 out-of-sample reference
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

    State machine fires on the first recovery day after 1–3 red closes:
      IDLE → PULLBACK_1 on red close (record pre_pullback_close)
      PULLBACK_N → PULLBACK_N+1 on another red close (max N=3)
      PULLBACK_N → ENTRY if today close > pre_pullback_close
      PULLBACK_N → RESET if today is non-red but close ≤ pre_pullback_close
      PULLBACK_3 → RESET on 4th red close

    Remaining gates checked on the recovery (entry) day:
      VIX < 20 | RS top 30% | within 5% of 60d high | no earnings ±6d |
      all 4H bars during streak close above EMA21 (per mode)

    Returns (rth_signals, ext_signals) — each a list of signal dicts:
        ticker, signal_date, entry_day_high, pullback_low, pullback_high,
        vix_at_entry, rs_rank, streak_len
    """
    rth_signals: list = []
    ext_signals: list = []

    if daily.empty or len(daily) < 22:
        return rth_signals, ext_signals

    dates  = daily.index.tolist()
    closes = daily['close'].values

    def _prior_vix(date):
        mask = vix_df['date'] < date
        return float(vix_df.loc[mask, 'vix_close'].iloc[-1]) if mask.any() else np.nan

    state    = 'IDLE'
    pb_close = np.nan   # close of bar immediately before streak started
    pb_idx   = -1       # index of that bar
    pb_dates = []       # red-bar dates in the current pullback

    for i, d in enumerate(dates):
        close      = closes[i]
        prev_close = closes[i - 1] if i > 0 else np.nan
        is_red     = not np.isnan(prev_close) and close < prev_close

        if state == 'IDLE':
            if is_red:
                state    = 'PULLBACK_1'
                pb_close = float(prev_close)
                pb_idx   = i - 1
                pb_dates = [d]
            continue

        # ── In PULLBACK_1 / PULLBACK_2 / PULLBACK_3 ──────────────────────────
        streak_num      = int(state[-1])
        saved_pb_close  = pb_close
        saved_pb_idx    = pb_idx
        saved_pb_dates  = list(pb_dates)

        if is_red:
            if streak_num < 3:
                state = f'PULLBACK_{streak_num + 1}'
                pb_dates.append(d)
            else:                           # 4th red bar → reset without signal
                state = 'IDLE'; pb_close = np.nan; pb_idx = -1; pb_dates = []
            continue

        # Non-red day: recovery attempt or reset
        if close > saved_pb_close:
            # ── Recovery day: evaluate remaining gates ────────────────────────
            vix_val  = _prior_vix(d)
            rs_rank  = rs_ranks.get((d, ticker), np.nan)
            high_60d = daily.at[d, 'high_60d']

            if (not np.isnan(vix_val)  and vix_val  < 20.0
                    and not np.isnan(rs_rank) and rs_rank  <= 0.30
                    and not pd.isna(high_60d) and close    >= 0.95 * float(high_60d)
                    and not is_earnings_window(ticker, d, earnings)):

                pullback_slice = daily.iloc[saved_pb_idx + 1:i]  # red bars only
                base = {
                    'ticker':         ticker,
                    'signal_date':    str(d),
                    'entry_day_high': round(float(daily.at[d, 'high']), 4),
                    'pullback_low':   round(float(pullback_slice['low'].min()), 4),
                    'pullback_high':  round(saved_pb_close, 4),
                    'vix_at_entry':   round(float(vix_val), 2),
                    'rs_rank':        round(float(rs_rank), 4),
                    'streak_len':     streak_num,
                }
                if check_pullback_above_ema21(ticker, saved_pb_dates, bars_4h_rth):
                    rth_signals.append(dict(base))
                if check_pullback_above_ema21(ticker, saved_pb_dates, bars_4h_ext):
                    ext_signals.append(dict(base))

        # Reset after any non-red day (one recovery attempt per pullback)
        state = 'IDLE'; pb_close = np.nan; pb_idx = -1; pb_dates = []

    return rth_signals, ext_signals


# ── Trade simulation ──────────────────────────────────────────────────────────

def simulate_m7_trade(
    signal: dict,
    daily_df: pd.DataFrame,
    bars_4h: pd.DataFrame,
    vix_df: pd.DataFrame,
) -> dict:
    """Simulate one M7 trade from a signal dict.

    Entry : open of the first trading day after signal_date.
    Exit  : first triggered at end-of-day daily close:
              1. close < EMA9            → BELOW_EMA9
              2. close < pullback_low    → STOP_PULLBACK_LOW
              3. hold_days >= 6          → MAX_HOLD_6D
              4. VIX close >= 25         → OVERRIDE_SUSPENDED

    Returns None if insufficient bars remain after the signal day.
    bars_4h is accepted for API symmetry; exits are daily-level only.
    """
    sig_date  = datetime.date.fromisoformat(signal['signal_date'])
    pull_low  = float(signal['pullback_low'])
    dates     = daily_df.index.tolist()

    try:
        sig_idx = dates.index(sig_date)
    except ValueError:
        return None
    if sig_idx + 1 >= len(dates):
        return None

    entry_idx   = sig_idx + 1
    entry_date  = dates[entry_idx]
    entry_price = float(daily_df.iloc[entry_idx]['open'])

    def _vix_on(d):
        row = vix_df[vix_df['date'] == d]
        return float(row['vix_close'].iloc[0]) if not row.empty else np.nan

    exit_price = exit_date = exit_reason = None
    hold_days  = 0

    for j in range(entry_idx, min(entry_idx + 6, len(dates))):
        hold_days += 1
        d     = dates[j]
        row   = daily_df.iloc[j]
        close = float(row['close'])
        ema9  = float(row['ema9']) if not pd.isna(row['ema9']) else np.nan
        vix_c = _vix_on(d)

        if not np.isnan(ema9) and close < ema9:
            triggered = 'BELOW_EMA9'
        elif close < pull_low:
            triggered = 'STOP_PULLBACK_LOW'
        elif hold_days >= 6:
            triggered = 'MAX_HOLD_6D'
        elif not np.isnan(vix_c) and vix_c >= 25.0:
            triggered = 'OVERRIDE_SUSPENDED'
        else:
            triggered = None

        if triggered:
            exit_price, exit_date, exit_reason = close, d, triggered
            break

    if exit_price is None:
        return None

    return {
        'ticker':       signal['ticker'],
        'signal_date':  signal['signal_date'],
        'entry_date':   str(entry_date),
        'entry_price':  round(entry_price, 4),
        'exit_date':    str(exit_date),
        'exit_price':   round(exit_price, 4),
        'return_pct':   round((exit_price - entry_price) / entry_price * 100, 4),
        'hold_days':    hold_days,
        'exit_reason':  exit_reason,
        'streak_len':   signal['streak_len'],
        'vix_at_entry': signal['vix_at_entry'],
        'rs_rank':      signal['rs_rank'],
    }


# ── Multi-ticker backtest runner ───────────────────────────────────────────────

def run_m7_backtest(
    signals_list: list,
    daily_data: dict,
    bars_4h_data: dict,
    vix_df: pd.DataFrame,
) -> list:
    """Simulate M7 trades with a global max-2-concurrent-positions cap.

    Signals are processed chronologically.  When 2 positions are already
    open at a new entry date the signal is recorded as SKIP_MAX_CONCURRENT.

    Returns list of trade dicts (executed + skipped).
    """
    sorted_sigs = sorted(signals_list, key=lambda s: s['signal_date'])
    trades: list = []
    active: list = []   # trade dicts for currently open positions

    for signal in sorted_sigs:
        ticker = signal['ticker']
        if ticker not in daily_data:
            continue

        daily_df = daily_data[ticker]
        sig_date = datetime.date.fromisoformat(signal['signal_date'])
        dates    = daily_df.index.tolist()

        try:
            sig_idx = dates.index(sig_date)
        except ValueError:
            continue
        if sig_idx + 1 >= len(dates):
            continue

        entry_date_str = str(dates[sig_idx + 1])

        # Drop positions that have already closed before this entry date
        active = [t for t in active if t['exit_date'] >= entry_date_str]

        if len(active) >= 2:
            trades.append({
                'ticker':       ticker,
                'signal_date':  signal['signal_date'],
                'entry_date':   entry_date_str,
                'entry_price':  np.nan,
                'exit_date':    None,
                'exit_price':   np.nan,
                'return_pct':   np.nan,
                'hold_days':    0,
                'exit_reason':  'SKIP_MAX_CONCURRENT',
                'streak_len':   signal['streak_len'],
                'vix_at_entry': signal['vix_at_entry'],
                'rs_rank':      signal['rs_rank'],
            })
            continue

        trade = simulate_m7_trade(
            signal, daily_df,
            bars_4h_data.get(ticker, pd.DataFrame()),
            vix_df,
        )
        if trade is not None:
            trades.append(trade)
            active.append(trade)

    return trades


# ── Statistics ─────────────────────────────────────────────────────────────────

def compute_stats(trades: list) -> dict:
    """Aggregate N, PF, WR, Mean, Avg_Hold from executed trades."""
    executed = [t for t in trades
                if t.get('exit_reason') != 'SKIP_MAX_CONCURRENT'
                and pd.notna(t.get('return_pct'))]
    if not executed:
        return {'N': 0, 'PF': 0.0, 'WR': 0.0, 'Mean': 0.0, 'Avg_Hold': 0.0}
    rets  = np.array([t['return_pct'] for t in executed], dtype=float)
    holds = np.array([t['hold_days']  for t in executed], dtype=float)
    wins  = rets[rets > 0]
    loss_sum = abs(rets[rets <= 0].sum())
    pf   = float(wins.sum() / loss_sum) if loss_sum > 0 else float('inf')
    return {
        'N':        len(executed),
        'PF':       round(pf, 2),
        'WR':       round(float((rets > 0).mean() * 100), 2),
        'Mean':     round(float(rets.mean()), 4),
        'Avg_Hold': round(float(holds.mean()), 2),
    }


# ── Markdown builder ───────────────────────────────────────────────────────────

def _build_comparison_md(stats_rth, stats_ext, stats_rth_25, stats_ext_25):
    bl = KNOWN_BASELINE
    lines = [
        '# M7 RS-Leader Pullback Backtest — Extended Hours Comparison',
        '',
        '## All Dates',
        '',
        '| Metric | RTH | Extended | Baseline |',
        '|--------|-----|----------|----------|',
        f'| N | {stats_rth["N"]} | {stats_ext["N"]} | {bl["N"]} |',
        f'| PF | {stats_rth["PF"]:.2f} | {stats_ext["PF"]:.2f} | {bl["PF"]:.2f} |',
        f'| WR % | {stats_rth["WR"]:.1f}% | {stats_ext["WR"]:.1f}% | — |',
        f'| Mean % | {stats_rth["Mean"]:+.2f}% | {stats_ext["Mean"]:+.2f}% | — |',
        f'| Avg Hold (d) | {stats_rth["Avg_Hold"]:.1f} | {stats_ext["Avg_Hold"]:.1f} | — |',
        '',
        '## 2025 Out-of-Sample',
        '',
        '| Metric | RTH | Extended | Baseline OOS |',
        '|--------|-----|----------|--------------|',
        f'| N | {stats_rth_25["N"]} | {stats_ext_25["N"]} | — |',
        f'| PF | {stats_rth_25["PF"]:.2f} | {stats_ext_25["PF"]:.2f} | {bl["PF_OOS"]:.2f} |',
        f'| WR % | {stats_rth_25["WR"]:.1f}% | {stats_ext_25["WR"]:.1f}% | — |',
        f'| Mean % | {stats_rth_25["Mean"]:+.2f}% | {stats_ext_25["Mean"]:+.2f}% | — |',
        f'| Avg Hold (d) | {stats_rth_25["Avg_Hold"]:.1f} | {stats_ext_25["Avg_Hold"]:.1f} | — |',
        '',
        '## Entry Rules',
        '',
        '1. 1–3 day daily pullback (state machine)',
        '2. Prior-day VIX close < 20',
        '3. RS rank top 30% (20d return cross-sectional)',
        '4. Daily close within 5% of 60-day high',
        '5. All 4H streak bars close above EMA21 (mode-specific)',
        '6. Recovery day: daily close > pre-pullback close',
        '7. No earnings ±6 days',
        '',
        '## Exit Rules (first triggered, end-of-day)',
        '',
        '1. Daily close < EMA9  → BELOW_EMA9',
        '2. Daily close < pullback_low  → STOP_PULLBACK_LOW',
        '3. Hold >= 6 days  → MAX_HOLD_6D',
        '4. VIX close >= 25  → OVERRIDE_SUSPENDED',
    ]
    return '\n'.join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('=' * 60)
    print('M7 BACKTEST — Phase 3: Full Backtest')
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

    # ── Signal detection ──────────────────────────────────────────────────────
    print('\nDetecting signals...')
    all_rth: list = []
    all_ext: list = []

    for ticker in TICKERS:
        if ticker not in daily_data:
            continue
        rth_sigs, ext_sigs = detect_m7_signals(
            ticker,
            daily_data[ticker],
            bars_rth.get(ticker, pd.DataFrame()),
            bars_ext.get(ticker, pd.DataFrame()),
            vix_df, earnings, rs_ranks,
        )
        all_rth.extend(rth_sigs)
        all_ext.extend(ext_sigs)

    print(f'  Signals: {len(all_rth)} RTH | {len(all_ext)} EXT')

    # ── Trade simulation ──────────────────────────────────────────────────────
    print('\nRunning trade simulation...')
    trades_rth = run_m7_backtest(all_rth, daily_data, bars_rth, vix_df)
    trades_ext = run_m7_backtest(all_ext, daily_data, bars_ext, vix_df)
    stats_rth  = compute_stats(trades_rth)
    stats_ext  = compute_stats(trades_ext)
    print(f'  RTH: {stats_rth["N"]} trades | EXT: {stats_ext["N"]} trades')

    # ── Print comparison tables ───────────────────────────────────────────────
    bl  = KNOWN_BASELINE
    cw  = [22, 14, 16, 14]

    def _tbl(title, sr, se, bl_stats):
        print(f'\n{title}')
        print('=' * sum(cw))
        print(f'{"Metric":<{cw[0]}} {"RTH":>{cw[1]}} {"Extended":>{cw[2]}} {"Baseline":>{cw[3]}}')
        print('-' * sum(cw))
        def r(lbl, rv, ev, bv):
            print(f'{lbl:<{cw[0]}} {rv:>{cw[1]}} {ev:>{cw[2]}} {bv:>{cw[3]}}')
        r('N',            str(sr['N']),             str(se['N']),             str(bl_stats.get('N', '—')))
        r('PF',           f'{sr["PF"]:.2f}',         f'{se["PF"]:.2f}',         f'{bl_stats["PF"]:.2f}')
        r('WR %',         f'{sr["WR"]:.1f}%',        f'{se["WR"]:.1f}%',        '—')
        r('Mean %',       f'{sr["Mean"]:+.2f}%',     f'{se["Mean"]:+.2f}%',     '—')
        r('Avg Hold (d)', f'{sr["Avg_Hold"]:.1f}',   f'{se["Avg_Hold"]:.1f}',   '—')

    _tbl('ALL DATES', stats_rth, stats_ext, bl)

    def _oos(trades, year=2025):
        return [t for t in trades if t.get('entry_date', '')[:4] == str(year)]

    stats_rth_25 = compute_stats(_oos(trades_rth))
    stats_ext_25 = compute_stats(_oos(trades_ext))
    _tbl('2025 OOS', stats_rth_25, stats_ext_25, {'N': '—', 'PF': bl['PF_OOS']})

    # Per-ticker counts
    print('\nPER-TICKER TRADE COUNTS  (executed only)')
    print('=' * 36)
    print(f'  {"Ticker":<8} {"RTH":>8} {"EXT":>8}')
    print('  ' + '-' * 26)
    for tk in TICKERS:
        nr = sum(1 for t in trades_rth if t['ticker'] == tk
                 and t.get('exit_reason') != 'SKIP_MAX_CONCURRENT')
        ne = sum(1 for t in trades_ext if t['ticker'] == tk
                 and t.get('exit_reason') != 'SKIP_MAX_CONCURRENT')
        if nr or ne:
            print(f'  {tk:<8} {nr:>8} {ne:>8}')

    # Exit reason breakdown
    print('\nEXIT REASON BREAKDOWN')
    print('=' * 46)
    print(f'  {"Reason":<26} {"RTH":>8} {"EXT":>8}')
    print('  ' + '-' * 44)
    all_reasons = sorted({t['exit_reason'] for t in trades_rth + trades_ext
                          if t['exit_reason'] is not None})
    for reason in all_reasons:
        nr = sum(1 for t in trades_rth if t['exit_reason'] == reason)
        ne = sum(1 for t in trades_ext if t['exit_reason'] == reason)
        print(f'  {reason:<26} {nr:>8} {ne:>8}')

    # ── Save outputs ──────────────────────────────────────────────────────────
    os.makedirs(OUT_DIR, exist_ok=True)

    if trades_rth:
        rth_path = os.path.join(OUT_DIR, 'm7_rth_trades.csv')
        pd.DataFrame(trades_rth).to_csv(rth_path, index=False)
        print(f'\nRTH trades ({stats_rth["N"]}) → {rth_path}')

    if trades_ext:
        ext_path = os.path.join(OUT_DIR, 'm7_extended_trades.csv')
        pd.DataFrame(trades_ext).to_csv(ext_path, index=False)
        print(f'EXT trades ({stats_ext["N"]}) → {ext_path}')

    md_path = os.path.join(OUT_DIR, 'm7_comparison.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(_build_comparison_md(stats_rth, stats_ext, stats_rth_25, stats_ext_25))
    print(f'Comparison   → {md_path}')
