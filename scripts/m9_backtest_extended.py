#!/usr/bin/env python3
"""M9 4H Trend-Pullback backtest — first discovery run.
Phase 1: signal detection + funnel.  Phase 2: simulation.  Phase 3: output.
Usage: python scripts/m9_backtest_extended.py
"""
import bisect
import datetime
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


# ── Trade simulation ───────────────────────────────────────────────────────────

_SKIP_REASONS = frozenset({'SKIP_MAX_CONCURRENT', 'SKIP_TICKER_OPEN'})


def _skip_record(sig: dict, reason: str) -> dict:
    return {
        'ticker': sig['ticker'], 'entry_date': sig['signal_date'],
        'entry_bar': sig['signal_bar'], 'entry_price': sig['entry_price'],
        'pullback_low': sig['pullback_low'], 'streak_len': sig['streak_len'],
        'vix_at_entry': sig['vix_at_entry'],
        'exit_date': None, 'exit_bar': None, 'exit_price': np.nan,
        'exit_reason': reason, 'return_pct': np.nan,
        'hold_bars': 0, 'hold_days': 0,
    }


def simulate_m9_trade(signal: dict, bars: pd.DataFrame, vix_df: pd.DataFrame):
    """Simulate M9 exit on subsequent 4H bars. Returns trade dict or None.

    Exit order (first triggered):
      1. close < EMA21            → BELOW_EMA21
      2. close < pullback_low     → STOP_PULLBACK_LOW
      3. close < chandelier_exit  → CHANDELIER_EXIT
      4. hold_bars >= 12          → MAX_HOLD_12B
      5. VIX prior-day >= 25      → OVERRIDE_SUSPENDED
    """
    entry_idx   = signal['bar_idx']
    entry_price = signal['entry_price']
    pull_low    = signal['pullback_low']

    closes  = bars['close'].values
    ema21s  = bars['ema21'].values
    chans   = bars['chandelier_exit'].values
    dates   = bars['date'].tolist()
    labels  = bars['bar_label'].tolist()
    corrupt = flag_corrupt(bars['close']).values
    n       = len(bars)

    vix_dates  = vix_df['date'].tolist()
    vix_closes = vix_df['vix_close'].tolist()

    def _prior_vix(date):
        idx = bisect.bisect_left(vix_dates, date) - 1
        return float(vix_closes[idx]) if idx >= 0 else np.nan

    exit_price = exit_date = exit_bar = exit_reason = None
    hold_bars = 0
    exit_j = -1

    for j in range(entry_idx + 1, min(entry_idx + 13, n)):
        hold_bars += 1
        if corrupt[j]:
            exit_price, exit_date, exit_bar = float(closes[j]), str(dates[j]), labels[j]
            exit_reason, exit_j = 'MAX_HOLD_12B', j
            break

        close = float(closes[j])
        e21   = float(ema21s[j]) if not np.isnan(ema21s[j]) else np.nan
        chan  = float(chans[j])  if not np.isnan(chans[j])  else np.nan
        vix_v = _prior_vix(dates[j])

        if   not np.isnan(e21) and close < e21:         trig = 'BELOW_EMA21'
        elif close < pull_low:                           trig = 'STOP_PULLBACK_LOW'
        elif not np.isnan(chan) and close < chan:        trig = 'CHANDELIER_EXIT'
        elif hold_bars >= 12:                            trig = 'MAX_HOLD_12B'
        elif not np.isnan(vix_v) and vix_v >= 25.0:     trig = 'OVERRIDE_SUSPENDED'
        else:                                            trig = None

        if trig:
            exit_price, exit_date, exit_bar = close, str(dates[j]), labels[j]
            exit_reason, exit_j = trig, j
            break

    if exit_price is None:
        return None

    entry_d = datetime.date.fromisoformat(signal['signal_date'])
    exit_d  = datetime.date.fromisoformat(exit_date)
    ret_pct = (exit_price - entry_price) / entry_price * 100

    return {
        'ticker':       signal['ticker'],
        'entry_date':   signal['signal_date'],
        'entry_bar':    signal['signal_bar'],
        'entry_price':  signal['entry_price'],
        'pullback_low': signal['pullback_low'],
        'streak_len':   signal['streak_len'],
        'vix_at_entry': signal['vix_at_entry'],
        'exit_date':    exit_date,
        'exit_bar':     exit_bar,
        'exit_price':   round(exit_price, 4),
        'exit_reason':  exit_reason,
        'return_pct':   round(float(ret_pct), 4),
        'hold_bars':    hold_bars,
        'hold_days':    (exit_d - entry_d).days,
        '_exit_ts':     _bar_ts(dates[exit_j], labels[exit_j]),
    }


# ── Concurrency runner ─────────────────────────────────────────────────────────

def run_m9_backtest(
    signals: list,
    bars_4h_data: dict,
    vix_df: pd.DataFrame,
) -> list:
    """Sort signals chronologically, enforce max-2-global + one-per-ticker.

    Skipped signals get SKIP_MAX_CONCURRENT or SKIP_TICKER_OPEN records.
    Returns list of all trade dicts (executed + skipped).
    """
    trades: list = []
    active: list = []   # open executed trades (each has '_exit_ts')

    for sig in sorted(signals, key=lambda s: s['bar_ts']):
        entry_ts = sig['bar_ts']
        ticker   = sig['ticker']

        # Expire positions whose exit bar is at or before the new entry
        active = [t for t in active if t['_exit_ts'] > entry_ts]

        if any(t['ticker'] == ticker for t in active):
            trades.append(_skip_record(sig, 'SKIP_TICKER_OPEN'))
            continue
        if len(active) >= 2:
            trades.append(_skip_record(sig, 'SKIP_MAX_CONCURRENT'))
            continue

        trade = simulate_m9_trade(sig, bars_4h_data[ticker], vix_df)
        if trade is None:
            continue    # no trailing bars — discard silently

        trades.append(trade)
        active.append(trade)

    return trades


# ── Statistics ─────────────────────────────────────────────────────────────────

def compute_stats(trades: list) -> dict:
    """N, PF, WR%, Mean%, Avg Hold (bars + calendar days) — executed trades."""
    executed = [t for t in trades
                if t.get('exit_reason') not in _SKIP_REASONS
                and pd.notna(t.get('return_pct'))]
    if not executed:
        return {'N': 0, 'PF': 0.0, 'WR': 0.0, 'Mean': 0.0,
                'Avg_Hold_Bars': 0.0, 'Avg_Hold_Days': 0.0}
    rets  = np.array([t['return_pct'] for t in executed], dtype=float)
    hbars = np.array([t['hold_bars']  for t in executed], dtype=float)
    hdays = np.array([t['hold_days']  for t in executed], dtype=float)
    wins     = rets[rets > 0]
    loss_sum = abs(rets[rets <= 0].sum())
    pf = float(wins.sum() / loss_sum) if loss_sum > 0 else float('inf')
    return {
        'N':             len(executed),
        'PF':            round(pf, 2),
        'WR':            round(float((rets > 0).mean() * 100), 2),
        'Mean':          round(float(rets.mean()), 4),
        'Avg_Hold_Bars': round(float(hbars.mean()), 2),
        'Avg_Hold_Days': round(float(hdays.mean()), 2),
    }


# ── Markdown builder ───────────────────────────────────────────────────────────

def _build_comparison_md(
    stats_rth, stats_ext,
    stats_rth_25, stats_ext_25,
    trades_rth, trades_ext,
    funnel_rth, funnel_ext,
) -> str:
    exec_rth = [t for t in trades_rth
                if t.get('exit_reason') not in _SKIP_REASONS and pd.notna(t.get('return_pct'))]
    exec_ext = [t for t in trades_ext
                if t.get('exit_reason') not in _SKIP_REASONS and pd.notna(t.get('return_pct'))]

    def _stat_rows(sr, se):
        def r(m, rv, ev): return f'| {m} | {rv} | {ev} |'
        return [
            '| Metric | RTH (2 bars/day) | Extended (4 bars/day) |',
            '|--------|------------------|-----------------------|',
            r('N',                   sr['N'],                         se['N']),
            r('PF',                  f'{sr["PF"]:.2f}',               f'{se["PF"]:.2f}'),
            r('WR %',                f'{sr["WR"]:.1f}%',              f'{se["WR"]:.1f}%'),
            r('Mean %',              f'{sr["Mean"]:+.4f}%',           f'{se["Mean"]:+.4f}%'),
            r('Avg Hold (bars)',     f'{sr["Avg_Hold_Bars"]:.1f}',    f'{se["Avg_Hold_Bars"]:.1f}'),
            r('Avg Hold (days)',     f'{sr["Avg_Hold_Days"]:.1f}',    f'{se["Avg_Hold_Days"]:.1f}'),
        ]

    # Table 3 — per-ticker counts
    t3 = ['| Ticker | RTH | Extended |', '|--------|-----|----------|']
    for tk in TICKERS:
        t3.append(f'| {tk} | {sum(1 for t in exec_rth if t["ticker"]==tk)} '
                  f'| {sum(1 for t in exec_ext if t["ticker"]==tk)} |')

    # Table 4 — exit reasons (all trades including skips)
    all_reasons = sorted({t['exit_reason'] for t in trades_rth + trades_ext
                          if t.get('exit_reason')})
    t4 = ['| Exit Reason | RTH | Extended |', '|-------------|-----|----------|']
    for r in all_reasons:
        t4.append(f'| {r} | {sum(1 for t in trades_rth if t.get("exit_reason")==r)} '
                  f'| {sum(1 for t in trades_ext if t.get("exit_reason")==r)} |')

    # Table 5 — signal funnel
    funnel_labels = [
        ('total_bars',  'Total 4H bars'),
        ('ema_up',      'EMA UP (EMA9 > EMA21)'),
        ('red_streak',  'Recovery attempts (1–2 red + green)'),
        ('recovery',    'Recovery > pullback high + EMA UP'),
        ('above_ema21', 'Pullback bars above EMA21'),
        ('no_earnings', 'No earnings (±6d)'),
        ('all_gates',   'All gates (incl. VIX < 20)'),
    ]
    t5 = ['| Gate | RTH | Extended |', '|------|-----|----------|']
    for key, lbl in funnel_labels:
        t5.append(f'| {lbl} | {funnel_rth[key]} | {funnel_ext[key]} |')

    lines = [
        '# M9 4H Trend-Pullback — First Backtest (Discovery Run)', '',
        '## Table 1: All Dates', '',
        *_stat_rows(stats_rth, stats_ext), '',
        '## Table 2: 2025 Out-of-Sample', '',
        *_stat_rows(stats_rth_25, stats_ext_25), '',
        '## Table 3: Per-Ticker Trade Counts (Executed)', '', *t3, '',
        '## Table 4: Exit Reason Breakdown', '', *t4, '',
        '## Table 5: Signal Funnel', '', *t5, '',
        '## Entry Rules (ALL required on 4H bar close)', '',
        '1. VIX < 20 (prior day close)',
        '2. EMA gate UP: 4H EMA9 > 4H EMA21 at signal bar',
        '3. Pullback: 1–2 consecutive RED 4H bars (close < open)',
        '4. All pullback bars close strictly above 4H EMA21',
        '5. Recovery: 4H close > highest close of pullback bars',
        '6. Not within ±6 calendar days of earnings', '',
        '## Exit Rules (first triggered on subsequent 4H bars)', '',
        '1. 4H close < 4H EMA21 → BELOW_EMA21',
        '2. 4H close < pullback_low → STOP_PULLBACK_LOW',
        '3. Chandelier Exit (highest_high(22) − 3×ATR14) → CHANDELIER_EXIT',
        '4. Max hold 12 4H bars → MAX_HOLD_12B',
        '5. VIX prior-day close ≥ 25 → OVERRIDE_SUSPENDED', '',
        '## Position Rules', '',
        '- Position size: 5% per trade',
        '- Max 2 concurrent positions globally',
        '- One position per ticker at a time',
        f'- Tickers: {len(TICKERS)} equities',
        '- RTH: 2 bars/day  |  Extended: 4 bars/day',
    ]
    return '\n'.join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

def _blank_funnel() -> dict:
    return {'total_bars': 0, 'ema_up': 0, 'red_streak': 0,
            'recovery': 0, 'above_ema21': 0, 'no_earnings': 0, 'all_gates': 0}


if __name__ == '__main__':
    print('=' * 65)
    print('M9 TREND-PULLBACK 4H BACKTEST — FIRST DISCOVERY RUN')
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

    funnel_ext, funnel_rth = _blank_funnel(), _blank_funnel()
    all_sigs_ext: list = []
    all_sigs_rth: list = []
    bars_ext: dict = {}
    bars_rth: dict = {}

    print('\nBuilding 4H bars + detecting signals...')
    for ticker, df_m5 in ticker_m5.items():
        b_ext = compute_indicators(build_4h_extended(df_m5, mode='extended'))
        bars_ext[ticker] = b_ext
        all_sigs_ext += detect_m9_signals(
            ticker, b_ext, vix_df, earnings, 'extended', funnel_ext)

        b_rth = build_4h_extended(df_m5, mode='rth')
        b_rth = compute_indicators(b_rth, warmup_rows=0)
        b_rth['ema21'] = apply_ema21_warmup_mask(b_rth)
        bars_rth[ticker] = b_rth
        all_sigs_rth += detect_m9_signals(
            ticker, b_rth, vix_df, earnings, 'rth', funnel_rth)

    print(f'  Signals detected — Extended: {len(all_sigs_ext)}  RTH: {len(all_sigs_rth)}')

    print('\nRunning trade simulation...')
    trades_ext = run_m9_backtest(all_sigs_ext, bars_ext, vix_df)
    trades_rth = run_m9_backtest(all_sigs_rth, bars_rth, vix_df)

    stats_ext = compute_stats(trades_ext)
    stats_rth = compute_stats(trades_rth)

    def _oos(trades):
        return [t for t in trades
                if t.get('exit_reason') not in _SKIP_REASONS
                and str(t.get('entry_date', ''))[:4] == '2025'
                and pd.notna(t.get('return_pct'))]

    stats_ext_25 = compute_stats(_oos(trades_ext))
    stats_rth_25 = compute_stats(_oos(trades_rth))

    # ── Print comparison tables ───────────────────────────────────────────────
    cw = [22, 20, 22]

    def _print_stat_table(title, sr, se):
        print(f'\n{title}')
        print('=' * sum(cw))
        print(f'  {"Metric":<{cw[0]}} {"RTH":>{cw[1]}} {"Extended":>{cw[2]}}')
        print('  ' + '-' * (sum(cw) - 2))
        for metric, rv, ev in [
            ('N',               str(sr['N']),                        str(se['N'])),
            ('PF',              f'{sr["PF"]:.2f}',                   f'{se["PF"]:.2f}'),
            ('WR %',            f'{sr["WR"]:.1f}%',                  f'{se["WR"]:.1f}%'),
            ('Mean %',          f'{sr["Mean"]:+.4f}%',               f'{se["Mean"]:+.4f}%'),
            ('Avg Hold (bars)', f'{sr["Avg_Hold_Bars"]:.1f}',        f'{se["Avg_Hold_Bars"]:.1f}'),
            ('Avg Hold (days)', f'{sr["Avg_Hold_Days"]:.1f}',        f'{se["Avg_Hold_Days"]:.1f}'),
        ]:
            print(f'  {metric:<{cw[0]}} {rv:>{cw[1]}} {ev:>{cw[2]}}')

    _print_stat_table('ALL DATES', stats_rth, stats_ext)
    _print_stat_table('2025 OOS',  stats_rth_25, stats_ext_25)

    exec_ext = [t for t in trades_ext
                if t.get('exit_reason') not in _SKIP_REASONS and pd.notna(t.get('return_pct'))]
    exec_rth = [t for t in trades_rth
                if t.get('exit_reason') not in _SKIP_REASONS and pd.notna(t.get('return_pct'))]

    print('\nPER-TICKER TRADE COUNTS  (executed)')
    print('=' * 36)
    print(f'  {"Ticker":<8} {"RTH":>8} {"EXT":>8}')
    print('  ' + '-' * 26)
    for tk in TICKERS:
        nr = sum(1 for t in exec_rth if t['ticker'] == tk)
        ne = sum(1 for t in exec_ext if t['ticker'] == tk)
        if nr or ne:
            print(f'  {tk:<8} {nr:>8} {ne:>8}')

    all_reasons = sorted({t['exit_reason'] for t in trades_rth + trades_ext
                          if t.get('exit_reason')})
    print('\nEXIT REASON BREAKDOWN  (all trades incl. skips)')
    print('=' * 54)
    print(f'  {"Reason":<30} {"RTH":>8} {"EXT":>8}')
    print('  ' + '-' * 50)
    for reason in all_reasons:
        nr = sum(1 for t in trades_rth if t.get('exit_reason') == reason)
        ne = sum(1 for t in trades_ext if t.get('exit_reason') == reason)
        print(f'  {reason:<30} {nr:>8} {ne:>8}')

    fw = [36, 14, 14]
    print('\nSIGNAL FUNNEL')
    print('=' * (sum(fw) + 4))
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

    # ── Save outputs ──────────────────────────────────────────────────────────
    os.makedirs(OUT_DIR, exist_ok=True)

    _CSV_COLS = [
        'ticker', 'entry_date', 'entry_bar', 'entry_price',
        'pullback_low', 'streak_len', 'vix_at_entry',
        'exit_date', 'exit_bar', 'exit_price', 'exit_reason',
        'return_pct', 'hold_bars', 'hold_days',
    ]

    for label, trades, stats in [('extended', trades_ext, stats_ext),
                                   ('rth',      trades_rth, stats_rth)]:
        path = os.path.join(OUT_DIR, f'm9_{label}_trades.csv')
        pd.DataFrame(trades)[_CSV_COLS].to_csv(path, index=False)
        print(f'\n{label.upper()} trades ({stats["N"]} executed) → {path}')

    md_path = os.path.join(OUT_DIR, 'm9_comparison.md')
    with open(md_path, 'w', encoding='utf-8') as fh:
        fh.write(_build_comparison_md(
            stats_rth, stats_ext,
            stats_rth_25, stats_ext_25,
            trades_rth, trades_ext,
            funnel_rth, funnel_ext,
        ))
    print(f'Comparison      → {md_path}')
