#!/usr/bin/env python3
"""Diagnostic: compare AAPL M4 RTH trades between:
  - BASELINE : m4_backtest_5yr.py   reads AAPL_m5_full.csv
  - NEW RTH  : m4_backtest_extended.py mode='rth'  reads AAPL_m5_extended.csv

For each extra trigger in the new script that is NOT in the baseline, prints:
  • the 8 bars leading to the trigger (streak, RSI, EMA21, open, close)
  • whether the gap reset fires (gap_hours vs 30h threshold)
  • RSI / EMA21 values at the same calendar dates in both data sources

Run: python scripts/diagnose_m4_rth_aapl.py
"""

import os
import sys
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA    = os.path.join(BASE, 'Fetched_Data')
SCRIPTS = os.path.join(BASE, 'scripts')
sys.path.insert(0, SCRIPTS)

TICKER = 'AAPL'

# ── Re-implement BASELINE path exactly (mirrors backtest_ticker in m4_backtest_5yr.py)
# ──────────────────────────────────────────────────────────────────────────────

from m4_backtest_5yr import (
    build_4h, rsi14, calc_streak, _norm_m5, flag_corrupt,
    apply_ema21_warmup_mask, load_vix, prior_vix,
)

def _run_baseline(vix: pd.Series):
    """Run the original backtest_ticker() logic verbatim on AAPL.
    Returns (bars_df, trades_list) so callers can inspect the bars too.
    """
    fpath = os.path.join(DATA, f'{TICKER}_m5_full.csv')
    if not os.path.exists(fpath):
        print(f'[BASELINE] SKIP — file not found: {fpath}')
        return pd.DataFrame(), []

    raw  = _norm_m5(pd.read_csv(fpath))
    bars = build_4h(raw)
    print(f'[BASELINE] {fpath}')
    print(f'           M5 rows  : {len(raw):,}')
    print(f'           4H bars  : {len(bars)}   '
          f'({bars["ts"].min().date()} → {bars["ts"].max().date()})')

    corrupt      = flag_corrupt(bars['Close']).values
    bars['ema21'] = bars['Close'].ewm(span=21, adjust=False).mean()
    # _m5_full.csv: full-coverage, no gap-based re-masking (matches original comment)
    bars['rsi']   = rsi14(bars['Close'])
    bars['streak'] = calc_streak(bars)

    closes  = bars['Close'].values
    emas    = bars['ema21'].values
    rsis    = bars['rsi'].values
    streaks = bars['streak']
    dates   = [ts.date() for ts in bars['ts']]
    labels  = bars['session'].values   # 0 = Bar1, 1 = Bar2

    trades = []
    i = 0
    while i < len(bars):
        if corrupt[i]:
            i += 1; continue
        vix_val = prior_vix(dates[i], vix)
        if np.isnan(vix_val) or vix_val < 25:
            i += 1; continue
        rsi_val = rsis[i]
        if np.isnan(rsi_val) or rsi_val >= 35:
            i += 1; continue
        if streaks.iloc[i] < 3:
            i += 1; continue
        if np.isnan(emas[i]):
            i += 1; continue

        entry_price = closes[i]
        exit_price = exit_date = exit_type = None
        bars_held = 0
        for j in range(i + 1, min(i + 11, len(bars))):
            bars_held += 1
            if corrupt[j]:
                exit_price, exit_date, exit_type = closes[j], dates[j], 'hard_max'; break
            if closes[j] >= emas[j]:
                exit_price, exit_date, exit_type = closes[j], dates[j], 'ema21';    break
            if bars_held == 10:
                exit_price, exit_date, exit_type = closes[j], dates[j], 'hard_max'; break

        if exit_price is None:
            i += 1; continue

        ret = (exit_price - entry_price) / entry_price * 100
        trades.append({
            'entry_date':   str(dates[i]),
            'entry_bar':    f'Bar{labels[i]+1}',
            'entry_price':  round(float(entry_price), 4),
            'rsi':          round(float(rsi_val), 2),
            'vix':          round(float(vix_val), 2),
            'ema21':        round(float(emas[i]), 4),
            'streak':       int(streaks.iloc[i]),
            'return_pct':   round(float(ret), 4),
            'bars_held':    int(bars_held),
            'exit_type':    exit_type,
            'exit_date':    str(exit_date),
        })
        i += bars_held + 1

    return bars, trades


# ── Re-implement NEW RTH path using the fixed backtest_utils_extended functions
# ──────────────────────────────────────────────────────────────────────────────

from backtest_utils_extended import (
    load_extended_data, build_4h_extended, compute_indicators,
    load_vix_daily, flag_corrupt as _flag_corrupt_ext,
    apply_ema21_warmup_mask as _ema_mask_ext,
)
from m4_backtest_extended import _prior_vix, _calc_streak, _bar_timestamp


def _run_new_rth(vix_df: pd.DataFrame):
    """Run the new RTH mode pipeline verbatim on AAPL.
    Returns (bars_df, trades_list).
    """
    try:
        df_m5 = load_extended_data(TICKER)
    except FileNotFoundError as exc:
        print(f'[NEW RTH ] SKIP — {exc}')
        return pd.DataFrame(), []

    fpath_ext = os.path.join(DATA, f'{TICKER}_m5_extended.csv')
    print(f'[NEW RTH ] {fpath_ext}')
    print(f'           M5 rows  : {len(df_m5):,}')

    bars = build_4h_extended(df_m5, mode='rth')
    bars = compute_indicators(bars, warmup_rows=0)
    bars['ema21'] = _ema_mask_ext(bars)

    print(f'           4H bars  : {len(bars)}   '
          f'({bars["date"].min()} → {bars["date"].max()})')

    corrupt = _flag_corrupt_ext(bars['close']).values
    streaks = _calc_streak(bars)
    dates   = bars['date'].tolist()
    labels  = bars['bar_label'].tolist()
    closes  = bars['close'].values
    emas    = bars['ema21'].values
    rsis    = bars['rsi14'].values
    n       = len(bars)

    trades = []
    i = 0
    while i < n:
        if corrupt[i]:
            i += 1; continue
        if streaks[i] < 3:
            i += 1; continue
        if np.isnan(emas[i]):
            i += 1; continue
        rsi_val = rsis[i]
        if np.isnan(rsi_val) or rsi_val >= 35.0:
            i += 1; continue
        vix_val = _prior_vix(dates[i], vix_df)
        if np.isnan(vix_val) or vix_val < 25.0:
            i += 1; continue

        entry_price = closes[i]
        exit_price = exit_date = exit_bar = exit_type = None
        bars_held = 0
        for j in range(i + 1, min(i + 11, n)):
            bars_held += 1
            if corrupt[j]:
                exit_price, exit_date, exit_bar = closes[j], dates[j], labels[j]
                exit_type = 'hard_max'; break
            if not np.isnan(emas[j]) and closes[j] >= emas[j]:
                exit_price, exit_date, exit_bar = closes[j], dates[j], labels[j]
                exit_type = 'ema21'; break
            if bars_held == 10:
                exit_price, exit_date, exit_bar = closes[j], dates[j], labels[j]
                exit_type = 'hard_max'; break

        if exit_price is None:
            i += 1; continue

        ret = (exit_price - entry_price) / entry_price * 100
        trades.append({
            'entry_date':  str(dates[i]),
            'entry_bar':   labels[i],
            'entry_price': round(float(entry_price), 4),
            'rsi':         round(float(rsi_val), 2),
            'vix':         round(float(vix_val), 2),
            'ema21':       round(float(emas[i]), 4),
            'streak':      int(streaks[i]),
            'return_pct':  round(float(ret), 4),
            'bars_held':   int(bars_held),
            'exit_type':   exit_type,
            'exit_date':   str(exit_date),
        })
        i += bars_held + 1

    return bars, trades


# ── Bar-by-bar context printer ─────────────────────────────────────────────────

def _print_bar_context(bars_new: pd.DataFrame, trigger_idx: int,
                       streaks: np.ndarray, label: str = ''):
    """Print 8 bars before + trigger bar with gap_hours, streak, RSI, EMA21."""
    n = len(bars_new)
    dates  = bars_new['date'].tolist()
    lbls   = bars_new['bar_label'].tolist()
    opens  = bars_new['open'].values
    closes = bars_new['close'].values
    rsis   = bars_new['rsi14'].values
    emas   = bars_new['ema21'].values

    start = max(0, trigger_idx - 8)
    print(f'\n  {label}')
    hdr = (f'  {"Date":<12} {"Lbl":<4} {"Open":>8} {"Close":>8} '
           f'{"Down":>5} {"GapH":>7} {"Streak":>7} {"RSI14":>7} {"EMA21":>10}')
    print(hdr)
    print('  ' + '-' * (len(hdr) - 2))

    for k in range(start, trigger_idx + 1):
        if k >= n:
            break
        # gap from previous bar
        if k > 0:
            ts_prev = _bar_timestamp(dates[k - 1], lbls[k - 1])
            ts_curr = _bar_timestamp(dates[k],     lbls[k])
            gap_h   = (ts_curr - ts_prev).total_seconds() / 3600
            gap_str = f'{gap_h:>7.1f}'
        else:
            gap_str = f'{"---":>7}'

        is_down = 'YES' if closes[k] < opens[k] else 'no'
        rsi_s   = f'{rsis[k]:>7.2f}'  if not np.isnan(rsis[k]) else f'{"NaN":>7}'
        ema_s   = f'{emas[k]:>10.4f}' if not np.isnan(emas[k]) else f'{"NaN":>10}'
        marker  = '  <-- TRIGGER' if k == trigger_idx else ''

        print(f'  {str(dates[k]):<12} {str(lbls[k]):<4} '
              f'{opens[k]:>8.2f} {closes[k]:>8.2f} {is_down:>5} '
              f'{gap_str} {streaks[k]:>7} {rsi_s} {ema_s}{marker}')


# ── Indicator cross-check: same calendar date, both data sources ───────────────

def _cross_check_indicators(bars_bl: pd.DataFrame, bars_new: pd.DataFrame,
                             sample_dates: list, n: int = 10):
    """For up to n sample_dates, compare RSI14 and EMA21 between the two bar sets."""
    # baseline uses columns: Close, ema21, rsi   (from m4_backtest_5yr pipeline)
    # new uses columns:       close, ema21, rsi14 (from compute_indicators)
    bl_idx  = {str(d): i for i, d in enumerate(
                   [ts.date() for ts in bars_bl['ts']])}
    new_idx = {str(d): i for i, d in enumerate(bars_new['date'].tolist())}

    printed = 0
    print(f'\n{"Date":<12} {"Lbl_BL":<8} {"RSI_BL":>8} {"EMA_BL":>10} '
          f'{"Lbl_NEW":<9} {"RSI_NEW":>9} {"EMA_NEW":>11} {"ΔRSI":>7} {"ΔEMA21":>9}')
    print('-' * 85)

    for ds in sample_dates:
        if printed >= n:
            break
        bi = bl_idx.get(ds)
        ni = new_idx.get(ds)
        if bi is None or ni is None:
            continue
        rsi_bl  = bars_bl['rsi'].iloc[bi]
        ema_bl  = bars_bl['ema21'].iloc[bi]
        lbl_bl  = f'Bar{int(bars_bl["session"].iloc[bi])+1}'
        rsi_new = bars_new['rsi14'].iloc[ni]
        ema_new = bars_new['ema21'].iloc[ni]
        lbl_new = bars_new['bar_label'].iloc[ni]

        if any(np.isnan(v) for v in [rsi_bl, ema_bl, rsi_new, ema_new]):
            continue

        d_rsi = rsi_new - rsi_bl
        d_ema = ema_new - ema_bl
        print(f'{ds:<12} {lbl_bl:<8} {rsi_bl:>8.3f} {ema_bl:>10.4f} '
              f'{lbl_new:<9} {rsi_new:>9.3f} {ema_new:>11.4f} {d_rsi:>+7.3f} {d_ema:>+9.4f}')
        printed += 1


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    SEP = '=' * 70

    print(SEP)
    print(f'M4 RTH DIAGNOSTIC  —  {TICKER} only')
    print(SEP)

    # Load VIX for both paths
    print('\nLoading VIX ...')
    vix_series = load_vix()          # baseline: pd.Series indexed by date
    vix_df     = load_vix_daily()    # new: DataFrame with 'date', 'vix_close'

    # ── 1. Run both paths ──────────────────────────────────────────────────────
    print(f'\n{SEP}')
    print('DATA SOURCES')
    print(SEP)
    bars_bl,  trades_bl  = _run_baseline(vix_series)
    bars_new, trades_new = _run_new_rth(vix_df)

    if bars_bl.empty or bars_new.empty:
        print('\nOne or both data sources missing — cannot compare.')
        return

    # ── 2. Trade-count comparison ──────────────────────────────────────────────
    print(f'\n{SEP}')
    print('TRADE COUNT COMPARISON')
    print(SEP)
    print(f'  Baseline  (m5_full.csv    RTH): {len(trades_bl):>4} trades')
    print(f'  New RTH   (m5_extended.csv RTH): {len(trades_new):>4} trades')

    bl_dates  = {t['entry_date'] for t in trades_bl}
    new_dates = {t['entry_date'] for t in trades_new}

    only_new  = sorted(new_dates - bl_dates)
    only_bl   = sorted(bl_dates  - new_dates)
    both      = sorted(bl_dates  & new_dates)

    print(f'\n  In BOTH               : {len(both)}')
    print(f'  Only in NEW (extras)  : {len(only_new)}')
    print(f'  Only in BASELINE      : {len(only_bl)}')

    # ── 3. All trades, both scripts ────────────────────────────────────────────
    print(f'\n{SEP}')
    print('ALL BASELINE TRADES')
    print(SEP)
    print(f'  {"Entry Date":<12} {"Bar":<5} {"Entry":>8} {"RSI":>6} '
          f'{"VIX":>6} {"EMA21":>10} {"Ret%":>7} {"Exit"}')
    for t in trades_bl:
        print(f'  {t["entry_date"]:<12} {t["entry_bar"]:<5} {t["entry_price"]:>8.2f} '
              f'{t["rsi"]:>6.2f} {t["vix"]:>6.2f} {t["ema21"]:>10.4f} '
              f'{t["return_pct"]:>+7.2f}% {t["exit_type"]}')

    print(f'\n{SEP}')
    print(f'ALL NEW RTH TRADES  ({len(trades_new)} total — first 40 shown)')
    print(SEP)
    print(f'  {"Entry Date":<12} {"Bar":<4} {"Entry":>8} {"RSI":>6} '
          f'{"VIX":>6} {"EMA21":>10} {"Ret%":>7} {"Exit"}')
    for t in trades_new[:40]:
        marker = '  *EXTRA*' if t['entry_date'] in only_new else ''
        print(f'  {t["entry_date"]:<12} {t["entry_bar"]:<4} {t["entry_price"]:>8.2f} '
              f'{t["rsi"]:>6.2f} {t["vix"]:>6.2f} {t["ema21"]:>10.4f} '
              f'{t["return_pct"]:>+7.2f}% {t["exit_type"]}{marker}')
    if len(trades_new) > 40:
        print(f'  ... ({len(trades_new) - 40} more trades not shown)')

    # ── 4. Bar-by-bar context for first 5 extra new trades ────────────────────
    print(f'\n{SEP}')
    print(f'BAR-BY-BAR STREAK FOR FIRST 5 EXTRA NEW TRIGGERS')
    print(SEP)

    streaks_new = _calc_streak(bars_new)
    dates_new   = bars_new['date'].tolist()
    lbls_new    = bars_new['bar_label'].tolist()

    for d_str in only_new[:5]:
        d_target = pd.to_datetime(d_str).date()

        # Find all rows on this date in new bars
        idxs = [k for k, d in enumerate(dates_new) if d == d_target]
        if not idxs:
            print(f'\n  {d_str}: bar not found in new bars')
            continue

        # The trigger bar is the one where RSI < 35 AND streak >= 3 AND EMA21 valid
        trigger_idx = None
        for k in idxs:
            if (streaks_new[k] >= 3
                    and not np.isnan(bars_new['rsi14'].iloc[k])
                    and bars_new['rsi14'].iloc[k] < 35.0
                    and not np.isnan(bars_new['ema21'].iloc[k])):
                trigger_idx = k
                break

        if trigger_idx is None:
            trigger_idx = idxs[0]  # fallback

        _print_bar_context(
            bars_new, trigger_idx, streaks_new,
            label=f'EXTRA TRIGGER  {d_str}  (RSI={bars_new["rsi14"].iloc[trigger_idx]:.2f},'
                  f' EMA={bars_new["ema21"].iloc[trigger_idx]:.4f},'
                  f' streak={streaks_new[trigger_idx]})',
        )

    # ── 5. Indicator cross-check at common trigger dates ──────────────────────
    print(f'\n{SEP}')
    print('INDICATOR CROSS-CHECK AT COMMON TRIGGER DATES (baseline vs new)')
    print(SEP)
    _cross_check_indicators(bars_bl, bars_new, [t['entry_date'] for t in trades_bl])

    # ── 6. Date-range and bar-count summary ───────────────────────────────────
    print(f'\n{SEP}')
    print('DATE RANGE / COVERAGE SUMMARY')
    print(SEP)
    bl_start  = bars_bl['ts'].min().date()
    bl_end    = bars_bl['ts'].max().date()
    new_start = bars_new['date'].min()
    new_end   = bars_new['date'].max()
    print(f'  Baseline  start: {bl_start}   end: {bl_end}   '
          f'bars: {len(bars_bl)}   trading days: ~{len(bars_bl)//2}')
    print(f'  New RTH   start: {new_start}   end: {new_end}   '
          f'bars: {len(bars_new)}   trading days: ~{len(bars_new)//2}')

    overlap_days = max(0, (min(bl_end, new_end) - max(bl_start, new_start)).days)
    total_new_days = (new_end - new_start).days
    total_bl_days  = (bl_end  - bl_start).days
    print(f'\n  Baseline spans {total_bl_days} calendar days  ({total_bl_days/365:.1f} yr)')
    print(f'  New RTH  spans {total_new_days} calendar days  ({total_new_days/365:.1f} yr)')
    print(f'  Overlap         {overlap_days} calendar days')

    # New-only date range trades: what fraction fall outside baseline window?
    extra_outside = [d for d in only_new
                     if pd.to_datetime(d).date() < bl_start
                     or pd.to_datetime(d).date() > bl_end]
    extra_inside  = [d for d in only_new
                     if bl_start <= pd.to_datetime(d).date() <= bl_end]
    print(f'\n  Extra new triggers outside baseline date range : {len(extra_outside)}')
    print(f'  Extra new triggers INSIDE  baseline date range : {len(extra_inside)}')
    if extra_inside:
        print(f'  (These {len(extra_inside)} overlap-period extras are the real discrepancy)')
        for d in extra_inside[:10]:
            nt = next(x for x in trades_new if x['entry_date'] == d)
            print(f'    {d}  RSI={nt["rsi"]:.2f}  VIX={nt["vix"]:.2f}  '
                  f'streak={nt["streak"]}  entry={nt["entry_price"]}')


if __name__ == '__main__':
    main()
