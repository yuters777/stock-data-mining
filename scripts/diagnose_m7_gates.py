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
    find_red_streaks,
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
    """Evaluate all 7 M7 gates for every trading day in *year*.

    Returns a DataFrame with one row per trading day and columns:
        date, streak_len,
        vix_val, g2_vix,
        rs_pct, g3_rs,
        pct_from_60h, g4_near_high,
        g5_ema21_rth, g5_ema21_ext,
        g6_recovery,
        g7_no_earnings
    """
    # Pre-compute streak map for the full history (warmup for older dates)
    streak_map = {
        d: (slen, sdates)
        for d, slen, sdates in find_red_streaks(daily)
    }

    rows = []
    for d in daily.index:
        if d.year != year:
            continue
        i = daily.index.get_loc(d)   # position in full daily history

        close     = float(daily.at[d, 'close'])
        high_60d  = daily.at[d, 'high_60d']

        # Gate 1: red streak 1-3
        if d in streak_map:
            slen, streak_dates = streak_map[d]
        else:
            slen, streak_dates = 0, []

        # Gate 2: prior-day VIX < 20
        vix_val = _prior_vix(d, vix_df)
        g2 = not np.isnan(vix_val) and vix_val < 20.0

        # Gate 3: RS top 30%
        rs_pct = rs_ranks.get((d, ticker), np.nan)
        g3 = not np.isnan(rs_pct) and rs_pct <= 0.30

        # Gate 4: close within 5% of 60d high
        if not pd.isna(high_60d) and high_60d > 0:
            pct_from_60h = (close / high_60d - 1) * 100
        else:
            pct_from_60h = np.nan
        g4 = not np.isnan(pct_from_60h) and pct_from_60h >= -5.0

        # Gate 5 (mode-specific): all 4H streak bars close above EMA21
        # Meaningful only when there's a streak (g1); False otherwise.
        if slen > 0:
            g5_rth = check_pullback_above_ema21(ticker, streak_dates, bars_rth)
            g5_ext = check_pullback_above_ema21(ticker, streak_dates, bars_ext)
        else:
            g5_rth = False
            g5_ext = False

        # Gate 6: today's daily close > pre-pullback close (close of bar before
        # streak started — spec §2.1 #5 "pre_pullback_close"). Mode-independent.
        if slen > 0:
            pullback_high = float(daily.iloc[i - slen]['close'])
            g6 = close > pullback_high
        else:
            g6 = False

        # Gate 7: no earnings within ±6 days
        g7 = not is_earnings_window(ticker, d, earnings)

        rows.append({
            'date':            d,
            'streak_len':      slen,
            'vix_val':         round(float(vix_val), 2) if not np.isnan(vix_val) else np.nan,
            'g2_vix':          g2,
            'rs_pct':          round(float(rs_pct), 4) if not np.isnan(rs_pct) else np.nan,
            'g3_rs':           g3,
            'pct_from_60h':    round(pct_from_60h, 2) if not np.isnan(pct_from_60h) else np.nan,
            'g4_near_high':    g4,
            'g5_ema21_rth':    g5_rth,
            'g5_ema21_ext':    g5_ext,
            'g6_recovery':     g6,
            'g7_no_earnings':  g7,
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


def print_gate_table(df: pd.DataFrame, ticker: str, year: int) -> None:
    """Print per-day gate evaluation table."""
    hdr = (f'{"Date":<12} {"Stk":>3}  {"VIX":>5} G2  {"RS%":>5} G3  '
           f'{"60H%":>6} G4  G5r G5e  G6  G7')
    sep = '-' * len(hdr)
    print(f'\n{ticker} {year} — per-day gate table')
    print(sep)
    print(hdr)
    print(sep)

    for _, r in df.iterrows():
        streak_s = f'{r["streak_len"]}' if r['streak_len'] > 0 else '-'
        line = (
            f'{str(r["date"]):<12} {streak_s:>3}  '
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
    """Print cumulative gate-passing funnel."""
    total = len(df)

    g1 = df['streak_len'].between(1, 3)
    g2 = g1 & df['g2_vix']
    g3 = g2 & df['g3_rs']
    g4 = g3 & df['g4_near_high']
    g7 = g4 & df['g7_no_earnings']   # earnings gate applied before mode-split

    g5_rth  = g7 & df['g5_ema21_rth']
    g5_ext  = g7 & df['g5_ema21_ext']
    g6_rth  = g5_rth & df['g6_recovery']
    g6_ext  = g5_ext & df['g6_recovery']

    # Also: gates 1-4+7 without mode-specific checks (shared funnel)
    print(f'\n{ticker} {year} — cumulative gate funnel  (total trading days: {total})')
    print('=' * 52)

    def row(label, mask):
        n = int(mask.sum())
        print(f'  {label:<38} {n:>4}  ({n / total * 100:.1f}%)')

    row('G1 : streak 1–3',                   g1)
    row('G1+G2 : + VIX < 20',                g2)
    row('G1-G3 : + RS top 30%',              g3)
    row('G1-G4 : + within 5% of 60d high',   g4)
    row('G1-G4+G7: + no earnings ±6d',        g7)
    print()
    row('G1-G7+G5 RTH: + pullback>EMA21',    g5_rth)
    row('G1-G7+G5 EXT: + pullback>EMA21',    g5_ext)
    print()
    row('ALL gates RTH (+ recovery bar)',     g6_rth)
    row('ALL gates EXT (+ recovery bar)',     g6_ext)
    print('=' * 52)

    # Extra: show breakdown of g1 failures to expose gate-2 behaviour
    g1_days = df[g1]
    if len(g1_days) > 0:
        print(f'\n  Breakdown of {len(g1_days)} streak days:')
        print(f'    VIX < 20      : {g1_days["g2_vix"].sum():>3} / {len(g1_days)}')
        print(f'    RS top 30%    : {g1_days["g3_rs"].sum():>3} / {len(g1_days)}')
        print(f'    Near 60d high : {g1_days["g4_near_high"].sum():>3} / {len(g1_days)}')
        print(f'    No earnings   : {g1_days["g7_no_earnings"].sum():>3} / {len(g1_days)}')
        print(f'    G5 EMA21 RTH  : {g1_days["g5_ema21_rth"].sum():>3} / {len(g1_days)}')
        print(f'    G5 EMA21 EXT  : {g1_days["g5_ema21_ext"].sum():>3} / {len(g1_days)}')
        print(f'    G6 recovery     : {g1_days["g6_recovery"].sum():>3} / {len(g1_days)}')

    # VIX distribution on streak days
    if len(g1_days) > 0:
        vix_vals = g1_days['vix_val'].dropna()
        if len(vix_vals) > 0:
            print(f'\n  VIX on {len(vix_vals)} streak days with known VIX:')
            print(f'    min={vix_vals.min():.1f}  median={vix_vals.median():.1f}'
                  f'  max={vix_vals.max():.1f}  pct<20={100*(vix_vals<20).mean():.0f}%')

    # RS distribution on streak days
    rs_vals = g1_days['rs_pct'].dropna()
    if len(rs_vals) > 0:
        print(f'\n  RS rank_pct on {len(rs_vals)} streak days with known RS:')
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
