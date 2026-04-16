#!/usr/bin/env python3
"""Diagnose which M7 gate kills signals — single-ticker 2025 drill-down.

For every TSLA trading day in 2025, evaluates all 7 entry gates
independently and prints a per-day table.  Then prints a cumulative
funnel showing how many days survive each successive gate.

Usage: python scripts/diagnose_m7_gates.py
"""
import sys
import os

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_utils_extended import (
    build_4h_extended,
    compute_indicators,
    apply_ema21_warmup_mask,
    load_vix_daily,
    load_earnings,
    is_earnings_window,
)
from m7_backtest_extended import (
    TICKERS,
    load_all_tickers,
    build_daily_from_m5,
    compute_daily_indicators,
    compute_rs_ranks,
    check_pullback_above_ema21,
)

DIAG_TICKER = 'TSLA'
DIAG_YEAR   = 2025


# ── Helpers ────────────────────────────────────────────────────────────────────

def _prior_vix(date, vix_df: pd.DataFrame) -> float:
    """Last VIX close strictly before date."""
    mask = vix_df['date'] < date
    return float(vix_df.loc[mask, 'vix_close'].iloc[-1]) if mask.any() else np.nan



# ── Per-day gate evaluation ────────────────────────────────────────────────────

def evaluate_gates(
    ticker: str,
    daily: pd.DataFrame,
    bars_rth: pd.DataFrame,
    bars_ext: pd.DataFrame,
    vix_df: pd.DataFrame,
    earnings: dict,
    rs_ranks: dict,
    year: int,
) -> pd.DataFrame:
    """Evaluate all M7 gates for every trading day in *year*.

    Uses the same state machine as detect_m7_signals so G6 (recovery)
    correctly fires on the first up-close day after 1–3 red closes,
    not on the red closes themselves.

    day_role values:
      'idle'     — no active pullback, normal day
      'red'      — Nth red close in current pullback (streak_len = N)
      'recovery' — first up close > pre_pullback_close (G6 = True here)
      'reset'    — non-red close that failed to recover, OR 4th red bar

    G5 (4H EMA21) is only evaluated on recovery days using the
    preceding red-bar dates.  All other gates are evaluated every day.

    Columns: date, day_role, streak_len,
             vix_val, g2_vix, rs_pct, g3_rs,
             pct_from_60h, g4_near_high,
             g5_ema21_rth, g5_ema21_ext,
             g6_recovery, g7_no_earnings
    """
    dates  = daily.index.tolist()
    closes = daily['close'].values

    state    = 'IDLE'
    pb_close = np.nan
    pb_idx   = -1
    pb_dates = []

    rows = []
    for i, d in enumerate(dates):
        close      = closes[i]
        prev_close = closes[i - 1] if i > 0 else np.nan
        is_red     = not np.isnan(prev_close) and close < prev_close

        # ── Save state before advancing, then advance ─────────────────────────
        saved_pb_close = pb_close
        saved_pb_dates = list(pb_dates)
        day_role   = 'idle'
        streak_len = 0

        if state == 'IDLE':
            if is_red:
                state    = 'PULLBACK_1'
                pb_close = float(prev_close)
                pb_idx   = i - 1
                pb_dates = [d]
                day_role   = 'red'
                streak_len = 1
        else:
            streak_num = int(state[-1])
            if is_red:
                if streak_num < 3:
                    state = f'PULLBACK_{streak_num + 1}'
                    pb_dates.append(d)
                    day_role   = 'red'
                    streak_len = streak_num + 1
                else:
                    state = 'IDLE'; pb_close = np.nan; pb_idx = -1; pb_dates = []
                    day_role = 'reset'
            elif close > saved_pb_close:
                day_role   = 'recovery'
                streak_len = streak_num
                state = 'IDLE'; pb_close = np.nan; pb_idx = -1; pb_dates = []
            else:
                state = 'IDLE'; pb_close = np.nan; pb_idx = -1; pb_dates = []
                day_role = 'reset'

        if d.year != year:
            continue

        # ── Gate evaluation ───────────────────────────────────────────────────
        high_60d = daily.at[d, 'high_60d']
        vix_val  = _prior_vix(d, vix_df)
        rs_pct   = rs_ranks.get((d, ticker), np.nan)

        pct_from_60h = (
            (close / high_60d - 1) * 100
            if not pd.isna(high_60d) and high_60d > 0 else np.nan
        )

        g2 = not np.isnan(vix_val)    and vix_val    < 20.0
        g3 = not np.isnan(rs_pct)     and rs_pct     <= 0.30
        g4 = not np.isnan(pct_from_60h) and pct_from_60h >= -5.0
        g7 = not is_earnings_window(ticker, d, earnings)

        # G5: 4H EMA21 check on the streak days (not today) — recovery only
        if day_role == 'recovery':
            g5_rth = check_pullback_above_ema21(ticker, saved_pb_dates, bars_rth)
            g5_ext = check_pullback_above_ema21(ticker, saved_pb_dates, bars_ext)
        else:
            g5_rth = g5_ext = False

        g6 = (day_role == 'recovery')   # implicit in state machine output

        rows.append({
            'date':          d,
            'day_role':      day_role,
            'streak_len':    streak_len,
            'vix_val':       round(float(vix_val), 2) if not np.isnan(vix_val) else np.nan,
            'g2_vix':        g2,
            'rs_pct':        round(float(rs_pct), 4) if not np.isnan(rs_pct) else np.nan,
            'g3_rs':         g3,
            'pct_from_60h':  round(pct_from_60h, 2) if not np.isnan(pct_from_60h) else np.nan,
            'g4_near_high':  g4,
            'g5_ema21_rth':  g5_rth,
            'g5_ema21_ext':  g5_ext,
            'g6_recovery':   g6,
            'g7_no_earnings': g7,
        })

    return pd.DataFrame(rows)


# ── Print helpers ──────────────────────────────────────────────────────────────

def _b(v) -> str:
    """Format bool as Y/N, NaN as '?'."""
    if isinstance(v, float) and np.isnan(v):
        return '?'
    return 'Y' if v else 'N'


def _f(v, fmt='.2f') -> str:
    """Format float, NaN as '  ?'."""
    if isinstance(v, float) and np.isnan(v):
        return '   ?'
    return format(float(v), fmt)


_ROLE_CHAR = {'idle': '-', 'red': 'P', 'recovery': 'R', 'reset': 'X'}


def print_gate_table(df: pd.DataFrame, ticker: str, year: int) -> None:
    """Print per-day gate evaluation table.

    Type column: P=pullback/red  R=recovery(signal candidate)
                 X=reset         -=idle
    G5 and G6 are only meaningful on R (recovery) days.
    """
    hdr = (f'{"Date":<12} T {"Stk":>2}  {"VIX":>5} G2  {"RS%":>5} G3  '
           f'{"60H%":>6} G4  G5r G5e  G6  G7')
    sep = '-' * len(hdr)
    print(f'\n{ticker} {year} — per-day gate table  '
          f'(T: P=red P/back  R=Recovery  X=reset  -=idle)')
    print(sep)
    print(hdr)
    print(sep)

    for _, r in df.iterrows():
        role_c   = _ROLE_CHAR.get(r['day_role'], '?')
        streak_s = f'{r["streak_len"]}' if r['streak_len'] > 0 else '-'
        line = (
            f'{str(r["date"]):<12} {role_c} {streak_s:>2}  '
            f'{_f(r["vix_val"]):>5} {_b(r["g2_vix"])}  '
            f'{_f(r["rs_pct"]):>5} {_b(r["g3_rs"])}  '
            f'{_f(r["pct_from_60h"]):>6} {_b(r["g4_near_high"])}  '
            f'{_b(r["g5_ema21_rth"])} {_b(r["g5_ema21_ext"])}  '
            f'{_b(r["g6_recovery"])}  '
            f'{_b(r["g7_no_earnings"])}'
        )
        print(line)

    print(sep)


def print_funnel(df: pd.DataFrame, ticker: str, year: int) -> None:
    """Print cumulative gate-passing funnel.

    G1 = recovery days (day_role == 'recovery'): first up close after
    1–3 red closes where close > pre_pullback_close.  This is the
    correct entry universe — not the red closes themselves.
    """
    total = len(df)

    g1 = df['day_role'] == 'recovery'   # recovery day = G1 candidate
    g2 = g1 & df['g2_vix']
    g3 = g2 & df['g3_rs']
    g4 = g3 & df['g4_near_high']
    g7 = g4 & df['g7_no_earnings']

    g_final_rth = g7 & df['g5_ema21_rth']   # G5 RTH (G6 implicit in G1)
    g_final_ext = g7 & df['g5_ema21_ext']   # G5 EXT

    print(f'\n{ticker} {year} — cumulative gate funnel  (total trading days: {total})')
    print('=' * 52)

    def row(label, mask):
        n = int(mask.sum())
        print(f'  {label:<38} {n:>4}  ({n / total * 100:.1f}%)')

    row('G1 : recovery day (post 1–3 reds)',  g1)
    row('G1+G2 : + VIX < 20',                 g2)
    row('G1-G3 : + RS top 30%',               g3)
    row('G1-G4 : + within 5% of 60d high',    g4)
    row('G1-G4+G7 : + no earnings ±6d',        g7)
    print()
    row('ALL gates RTH (+ G5 EMA21 streak)',   g_final_rth)
    row('ALL gates EXT (+ G5 EMA21 streak)',   g_final_ext)
    print('=' * 52)

    # Breakdown: which gates kill recovery day candidates
    g1_days = df[g1]
    n_rec = len(g1_days)
    if n_rec > 0:
        print(f'\n  Breakdown of {n_rec} recovery day candidates:')
        print(f'    VIX < 20      : {int(g1_days["g2_vix"].sum()):>3} / {n_rec}')
        print(f'    RS top 30%    : {int(g1_days["g3_rs"].sum()):>3} / {n_rec}')
        print(f'    Near 60d high : {int(g1_days["g4_near_high"].sum()):>3} / {n_rec}')
        print(f'    No earnings   : {int(g1_days["g7_no_earnings"].sum()):>3} / {n_rec}')
        print(f'    G5 EMA21 RTH  : {int(g1_days["g5_ema21_rth"].sum()):>3} / {n_rec}')
        print(f'    G5 EMA21 EXT  : {int(g1_days["g5_ema21_ext"].sum()):>3} / {n_rec}')

        # streak-length breakdown among recovery days
        for slen in [1, 2, 3]:
            n_s = int((g1_days['streak_len'] == slen).sum())
            print(f'    Preceding reds={slen}  : {n_s:>3} / {n_rec}')

    # VIX distribution on recovery days
    if n_rec > 0:
        vix_vals = g1_days['vix_val'].dropna()
        if len(vix_vals) > 0:
            print(f'\n  VIX on {len(vix_vals)} recovery days:')
            print(f'    min={vix_vals.min():.1f}  median={vix_vals.median():.1f}'
                  f'  max={vix_vals.max():.1f}  pct<20={100*(vix_vals<20).mean():.0f}%')

    # RS distribution on recovery days
    if n_rec > 0:
        rs_vals = g1_days['rs_pct'].dropna()
        if len(rs_vals) > 0:
            print(f'\n  RS rank_pct on {len(rs_vals)} recovery days:')
            print(f'    min={rs_vals.min():.3f}  median={rs_vals.median():.3f}'
                  f'  max={rs_vals.max():.3f}  pct<=0.30={100*(rs_vals<=0.30).mean():.0f}%')


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('=' * 60)
    print(f'M7 GATE DIAGNOSTIC  —  {DIAG_TICKER}  {DIAG_YEAR}')
    print('=' * 60)

    # ── Load all 27 tickers for cross-sectional RS ranking ────────────────────
    print(f'\nLoading M5 data for all {len(TICKERS)} tickers (RS ranking)...')
    ticker_data = load_all_tickers()
    print(f'Loaded {len(ticker_data)}/{len(TICKERS)} tickers.')

    if DIAG_TICKER not in ticker_data:
        print(f'\nERROR: {DIAG_TICKER} data not found — '
              f'ensure {DIAG_TICKER}_m5_extended.csv is in Fetched_Data/')
        sys.exit(1)

    # ── Load reference data ───────────────────────────────────────────────────
    print('Loading VIX...')
    vix_df = load_vix_daily()
    print(f'  {len(vix_df)} rows, {vix_df["date"].min()} to {vix_df["date"].max()}')

    print('Loading earnings...')
    earnings = load_earnings()
    print(f'  {len(earnings)} tickers covered.')

    # ── Build daily bars + indicators for all tickers (RS needs all) ──────────
    print('\nBuilding daily bars and RS ranks...')
    daily_data = {}
    for ticker, df_m5 in ticker_data.items():
        daily = build_daily_from_m5(df_m5)
        daily_data[ticker] = compute_daily_indicators(daily)

    rs_ranks = compute_rs_ranks(daily_data)
    print(f'  RS rank entries: {len(rs_ranks):,}')

    # ── Build 4H bars for TSLA only ───────────────────────────────────────────
    print(f'Building 4H bars for {DIAG_TICKER}...')
    df_m5 = ticker_data[DIAG_TICKER]

    bars_rth = build_4h_extended(df_m5, mode='rth')
    bars_rth = compute_indicators(bars_rth, warmup_rows=0)
    bars_rth['ema21'] = apply_ema21_warmup_mask(bars_rth)

    bars_ext = build_4h_extended(df_m5, mode='extended')
    bars_ext = compute_indicators(bars_ext)

    # ── Evaluate gates ────────────────────────────────────────────────────────
    print(f'\nEvaluating gates for {DIAG_TICKER} {DIAG_YEAR}...')
    gate_df = evaluate_gates(
        DIAG_TICKER,
        daily_data[DIAG_TICKER],
        bars_rth,
        bars_ext,
        vix_df,
        earnings,
        rs_ranks,
        DIAG_YEAR,
    )

    print_gate_table(gate_df, DIAG_TICKER, DIAG_YEAR)
    print_funnel(gate_df, DIAG_TICKER, DIAG_YEAR)

    print(f'\nDiagnostic complete.  No fixes applied.')
