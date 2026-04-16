#!/usr/bin/env python3
"""M9 4H Trend-Pullback backtest — first discovery run.
Phase 1: signal detection + funnel.  Phase 2: simulation.  Phase 3: output.
Usage: python scripts/m9_backtest_extended.py
"""
import bisect
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
    flag_corrupt,
)

TICKERS = [
    'AAPL', 'AMD', 'AMZN', 'ARM', 'AVGO', 'BA', 'BABA', 'BIDU',
    'C', 'COIN', 'COST', 'GOOGL', 'GS', 'INTC', 'JD', 'JPM',
    'MARA', 'META', 'MSFT', 'MSTR', 'MU', 'NVDA', 'PLTR',
    'SMCI', 'TSLA', 'TSM', 'V',
]

_BASE   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(_BASE, 'results', 'extended_validation')

# Bar start times ET — for timestamp reconstruction in Phase 2 concurrency
_BAR_TIME_ET = {
    'A': (4,  0), 'B': (8,  0), 'C': (12, 0), 'D': (16, 0),
    '1': (9, 30), '2': (13, 30),
}


def _bar_ts(date, label: str) -> pd.Timestamp:
    h, m = _BAR_TIME_ET.get(str(label), (9, 30))
    return pd.Timestamp(str(date)) + pd.Timedelta(hours=h, minutes=m)


# ── Data loading ───────────────────────────────────────────────────────────────

def load_all_tickers(data_dir: str = 'Fetched_Data') -> dict:
    """Load M5 data for all 27 tickers. No SPY needed. Skips missing files."""
    result = {}
    for ticker in TICKERS:
        try:
            result[ticker] = load_extended_data(ticker, data_dir=data_dir)
        except FileNotFoundError:
            pass
    return result


# ── Signal detection ───────────────────────────────────────────────────────────

def detect_m9_signals(
    ticker: str,
    bars: pd.DataFrame,
    vix_df: pd.DataFrame,
    earnings: dict,
    mode: str,
    funnel: dict,
) -> list:
    """Run M9 4H state machine (red bar = close < open).

    IDLE→PULLBACK_1 on RED+above EMA21; PULLBACK_1→PULLBACK_2 on 2nd RED;
    3rd RED or any pb bar ≤ EMA21 → reset.  Green bar after pb → check gates:
    EMA9>EMA21 + close>pullback_high + all pb bars>EMA21 + no earnings + VIX<20.
    Mutates `funnel` in place. Returns list of signal dicts.
    """
    if bars.empty or len(bars) < 30:
        return []

    vix_dates  = vix_df['date'].tolist()
    vix_closes = vix_df['vix_close'].tolist()

    def _prior_vix(date):
        idx = bisect.bisect_left(vix_dates, date) - 1
        return float(vix_closes[idx]) if idx >= 0 else np.nan

    closes  = bars['close'].values
    opens   = bars['open'].values
    ema9s   = bars['ema9'].values
    ema21s  = bars['ema21'].values
    dates   = bars['date'].tolist()
    labels  = bars['bar_label'].tolist()
    corrupt = flag_corrupt(bars['close']).values
    n       = len(bars)

    signals: list = []
    state  = 'IDLE'
    pb_idx = []            # indices of current pullback bars

    for i in range(n):
        funnel['total_bars'] += 1
        e9  = float(ema9s[i])  if not np.isnan(ema9s[i])  else np.nan
        e21 = float(ema21s[i]) if not np.isnan(ema21s[i]) else np.nan

        if not corrupt[i] and not np.isnan(e9) and not np.isnan(e21) and e9 > e21:
            funnel['ema_up'] += 1
        if corrupt[i]:
            state, pb_idx = 'IDLE', []; continue

        close  = float(closes[i])
        is_red = close < float(opens[i])

        if state == 'IDLE':
            if is_red and not np.isnan(e21) and close > e21:
                state, pb_idx = 'PULLBACK_1', [i]
            continue

        if is_red:
            if len(pb_idx) < 2 and not np.isnan(e21) and close > e21:
                state = 'PULLBACK_2'; pb_idx.append(i)
            else:
                state, pb_idx = 'IDLE', []
            continue

        # Green bar — recovery attempt
        funnel['red_streak'] += 1
        pb_closes = [float(closes[k]) for k in pb_idx]
        pb_high, pb_low = max(pb_closes), min(pb_closes)

        ema_ok = not np.isnan(e9) and not np.isnan(e21) and e9 > e21
        if not ema_ok or close <= pb_high:
            state, pb_idx = 'IDLE', []; continue
        funnel['recovery'] += 1

        if not all(not np.isnan(ema21s[k]) and float(closes[k]) > float(ema21s[k])
                   for k in pb_idx):
            state, pb_idx = 'IDLE', []; continue
        funnel['above_ema21'] += 1

        if is_earnings_window(ticker, dates[i], earnings, buffer_days=6):
            state, pb_idx = 'IDLE', []; continue
        funnel['no_earnings'] += 1

        vix_val = _prior_vix(dates[i])
        if np.isnan(vix_val) or vix_val >= 20.0:
            state, pb_idx = 'IDLE', []; continue
        funnel['all_gates'] += 1

        signals.append({
            'ticker':          ticker,
            'signal_date':     str(dates[i]),
            'signal_bar':      labels[i],
            'bar_ts':          _bar_ts(dates[i], labels[i]),
            'bar_idx':         i,
            'entry_price':     round(close, 4),
            'pullback_high':   round(pb_high, 4),
            'pullback_low':    round(pb_low, 4),
            'ema21_at_signal': round(e21, 4) if not np.isnan(e21) else None,
            'streak_len':      len(pb_idx),
            'vix_at_entry':    round(float(vix_val), 2),
            'mode':            mode,
        })
        state, pb_idx = 'IDLE', []

    return signals


# ── Main — Phase 1: signal counts + funnel ────────────────────────────────────

if __name__ == '__main__':
    print('=' * 65)
    print('M9 TREND-PULLBACK 4H BACKTEST — Phase 1: Signal Detection')
    print('=' * 65)

    print('\nLoading VIX...')
    vix_df = load_vix_daily()
    print(f'  {len(vix_df)} rows  {vix_df["date"].min()} → {vix_df["date"].max()}')

    print('Loading earnings...')
    try:
        earnings = load_earnings()
        print(f'  {sum(1 for v in earnings.values() if v)} tickers covered')
    except Exception as exc:
        print(f'  WARNING: {exc}')
        earnings = {}

    print(f'\nLoading M5 data for {len(TICKERS)} tickers...')
    ticker_m5 = load_all_tickers()
    missing = [t for t in TICKERS if t not in ticker_m5]
    if missing:
        print(f'  SKIP (no data): {", ".join(missing)}')
    print(f'  Loaded {len(ticker_m5)}/{len(TICKERS)}')

    def _blank_funnel():
        return {'total_bars': 0, 'ema_up': 0, 'red_streak': 0,
                'recovery': 0, 'above_ema21': 0, 'no_earnings': 0, 'all_gates': 0}

    funnel_ext, funnel_rth = _blank_funnel(), _blank_funnel()
    sigs_ext: dict = {}
    sigs_rth: dict = {}

    print('\nBuilding bars + detecting signals...')
    for ticker, df_m5 in ticker_m5.items():
        b_ext = compute_indicators(build_4h_extended(df_m5, mode='extended'))
        sigs_ext[ticker] = detect_m9_signals(
            ticker, b_ext, vix_df, earnings, 'extended', funnel_ext)

        b_rth = build_4h_extended(df_m5, mode='rth')
        b_rth = compute_indicators(b_rth, warmup_rows=0)
        b_rth['ema21'] = apply_ema21_warmup_mask(b_rth)
        sigs_rth[ticker] = detect_m9_signals(
            ticker, b_rth, vix_df, earnings, 'rth', funnel_rth)

    total_ext = sum(len(v) for v in sigs_ext.values())
    total_rth = sum(len(v) for v in sigs_rth.values())

    print(f'\nSIGNAL COUNTS  (Extended={total_ext}  RTH={total_rth})')
    print('=' * 38)
    print(f'  {"Ticker":<8} {"Extended":>10} {"RTH":>10}')
    print('  ' + '-' * 30)
    for tk in TICKERS:
        ne = len(sigs_ext.get(tk, []))
        nr = len(sigs_rth.get(tk, []))
        if ne or nr:
            print(f'  {tk:<8} {ne:>10} {nr:>10}')

    print('\nSIGNAL FUNNEL')
    print('=' * 68)
    fw = [36, 14, 14]
    print(f'  {"Gate":<{fw[0]}} {"RTH":>{fw[1]}} {"Extended":>{fw[2]}}')
    print('  ' + '-' * (sum(fw) + 2))
    for key, label in [
        ('total_bars',  'Total 4H bars'),
        ('ema_up',      'EMA UP (EMA9 > EMA21)'),
        ('red_streak',  'Recovery attempts (1–2 red + green)'),
        ('recovery',    'Recovery > pullback high + EMA UP'),
        ('above_ema21', 'Pullback bars above EMA21'),
        ('no_earnings', 'No earnings (±6d)'),
        ('all_gates',   'All gates (incl. VIX < 20)'),
    ]:
        print(f'  {label:<{fw[0]}} {funnel_rth[key]:>{fw[1]}} {funnel_ext[key]:>{fw[2]}}')
