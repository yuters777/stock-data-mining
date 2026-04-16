#!/usr/bin/env python3
"""M6 Shock-Reversal backtest on extended hours 4H bars.
Compares extended (4 bars/day) vs RTH (2 bars/day).

Usage: python scripts/m6_backtest_extended.py
"""
import sys
import os

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_utils_extended import (
    load_extended_data,
    build_4h_extended,
    flag_corrupt,
    is_earnings_window,
    load_earnings,
)

# 27 tickers: 22-ticker M4 baseline + ARM, INTC, JD, MSTR, SMCI
TICKERS = [
    'AAPL', 'AMD', 'AMZN', 'ARM', 'AVGO', 'BA', 'BABA', 'BIDU',
    'C', 'COIN', 'COST', 'GOOGL', 'GS', 'INTC', 'JD', 'JPM',
    'MARA', 'META', 'MSFT', 'MSTR', 'MU', 'NVDA', 'PLTR',
    'SMCI', 'TSLA', 'TSM', 'V',
]  # 27 equities

_BASE   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(_BASE, 'results', 'extended_validation')

# Known baseline from prior backtest run
KNOWN_BASELINE = {
    'N':    378,
    'PF':   1.68,
    'WR':   69.3,
    'Mean': 1.75,
}


# ── Stats helper ───────────────────────────────────────────────────────────────

def _compute_stats(trades: list) -> dict:
    """Aggregate N, PF, WR, Mean, Avg_Hold from a list of trade dicts."""
    if not trades:
        return {'N': 0, 'PF': 0.0, 'WR': 0.0, 'Mean': 0.0, 'Avg_Hold': 0.0}
    rets  = np.array([t['return_pct'] for t in trades], dtype=float)
    holds = np.array([t['hold_bars']  for t in trades], dtype=float)
    wins   = rets[rets > 0]
    losses = rets[rets <= 0]
    pf = float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float('inf')
    wr = float((rets > 0).mean() * 100)
    return {
        'N':        len(rets),
        'PF':       round(pf, 2),
        'WR':       round(wr, 2),
        'Mean':     round(float(rets.mean()), 4),
        'Avg_Hold': round(float(holds.mean()), 2),
    }


# ── Per-ticker backtest ────────────────────────────────────────────────────────

def run_m6_single_ticker(
    ticker: str,
    bars: pd.DataFrame,
    earnings_dict: dict,
    mode: str = 'extended',
) -> tuple:
    """Run M6 backtest on a single ticker's pre-built 4H bars.

    M6 Entry (ALL must be true):
      1. Gap ≤ -4.0% at the first bar of the trading day:
           Extended: gap = (Bar_B_open - prior_day_last_close) / prior_close
           RTH:      gap = (Bar_1_open - prior_day_last_close) / prior_close
           prior_close = last available bar's close of the prior trading day
             (typically Bar D for extended, Bar 2 for RTH; fallback to
              whatever bar was last that day on early-close sessions)
      2. Not a corporate action:
           |gap_pct| > 15% AND prior_close > 2 × entry_open → skip
      3. Not within ±1 calendar day of an earnings event

    M6 Exit (first triggered):
      1. Close ≥ gap_midpoint
           gap_midpoint = prior_close + (entry_open - prior_close) / 2
           (halfway recovery back to prior close)
      2. 15-bar hard maximum

    Rules:
      - Long only
      - Entry price = first bar close (Bar B for extended, Bar 1 for RTH)
      - Exit  price = exit bar close
      - One position per ticker at a time (no stacking)
      - No VIX filter for M6

    Returns
    -------
    (trades_list, gap_stats_dict)

    gap_stats keys:
      total             : entry bars where a valid prior close was found
      corp_action_excluded : |gap|>15% AND prior_close > 2×open
      qualified         : gap ≤ -4% AND not corp_action
                          (includes earnings_excluded subset)
      earnings_excluded : qualified bars blocked by ±1-day earnings window
    """
    if bars.empty:
        return [], {
            'total': 0, 'qualified': 0,
            'earnings_excluded': 0, 'corp_action_excluded': 0,
        }

    entry_label = 'B' if mode == 'extended' else '1'

    # Build date → last-bar-close lookup for prior-close determination.
    # "last bar" = bar with the alphabetically highest bar_label on that day
    # (D > C > B > A for extended;  2 > 1 for RTH).
    last_close_by_date: dict = {}
    for date, grp in bars.groupby('date', sort=True):
        last_close_by_date[date] = float(
            grp.sort_values('bar_label').iloc[-1]['close']
        )
    sorted_dates  = sorted(last_close_by_date.keys())
    date_to_rank  = {d: i for i, d in enumerate(sorted_dates)}

    def _prior_close(date):
        rank = date_to_rank.get(date)
        if rank is None or rank == 0:
            return None
        return last_close_by_date[sorted_dates[rank - 1]]

    closes  = bars['close'].values
    opens   = bars['open'].values
    dates   = bars['date'].tolist()
    labels  = bars['bar_label'].tolist()
    corrupt = flag_corrupt(bars['close']).values
    n       = len(bars)

    trades = []
    gap_stats = {
        'total': 0, 'qualified': 0,
        'earnings_excluded': 0, 'corp_action_excluded': 0,
    }

    i = 0
    while i < n:
        # Only check entry bars (Bar B for extended, Bar 1 for RTH)
        if labels[i] != entry_label:
            i += 1
            continue

        # Corrupt bar at potential entry → skip
        if corrupt[i]:
            i += 1
            continue

        prior_close = _prior_close(dates[i])
        if prior_close is None or prior_close <= 0:
            i += 1
            continue

        entry_open  = float(opens[i])
        entry_close = float(closes[i])
        gap_pct     = (entry_open - prior_close) / prior_close * 100

        gap_stats['total'] += 1

        # Corporate action guard: >15% gap AND prior_close > 2× open
        # Indicates a stock split or other corporate event, not a real gap.
        if abs(gap_pct) > 15.0 and prior_close > 2.0 * entry_open:
            gap_stats['corp_action_excluded'] += 1
            i += 1
            continue

        # Gap size gate: must be ≤ -4% (down gap of at least 4%)
        if gap_pct > -4.0:
            i += 1
            continue

        # This gap qualifies on size + not corp_action
        gap_stats['qualified'] += 1

        # Earnings filter: ±1 calendar day
        if is_earnings_window(ticker, dates[i], earnings_dict, buffer_days=1):
            gap_stats['earnings_excluded'] += 1
            i += 1
            continue

        # ── All gates passed — open trade ──────────────────────────────────
        entry_price  = entry_close
        entry_date   = dates[i]
        entry_bar    = labels[i]
        gap_midpoint = prior_close + (entry_open - prior_close) / 2.0

        exit_price  = None
        exit_date   = None
        exit_bar    = None
        exit_reason = None
        bars_held   = 0

        for j in range(i + 1, min(i + 16, n)):
            bars_held += 1
            # Corrupt bar during hold → hard_max exit immediately
            if corrupt[j]:
                exit_price  = float(closes[j])
                exit_date   = dates[j]
                exit_bar    = labels[j]
                exit_reason = 'hard_max'
                break
            # Midpoint exit: close has recovered to halfway between
            # entry_open and prior_close
            if closes[j] >= gap_midpoint:
                exit_price  = float(closes[j])
                exit_date   = dates[j]
                exit_bar    = labels[j]
                exit_reason = 'midpoint'
                break
            # 15-bar hard maximum
            if bars_held == 15:
                exit_price  = float(closes[j])
                exit_date   = dates[j]
                exit_bar    = labels[j]
                exit_reason = 'hard_max'
                break

        if exit_price is None:
            # Insufficient trailing bars after signal — skip
            i += 1
            continue

        ret_pct = (exit_price - entry_price) / entry_price * 100
        trades.append({
            'ticker':       ticker,
            'entry_date':   str(entry_date),
            'entry_bar':    entry_bar,
            'entry_price':  round(entry_price, 4),
            'gap_pct':      round(gap_pct, 4),
            'gap_midpoint': round(gap_midpoint, 4),
            'prior_close':  round(prior_close, 4),
            'exit_date':    str(exit_date),
            'exit_bar':     exit_bar,
            'exit_price':   round(exit_price, 4),
            'exit_reason':  exit_reason,
            'return_pct':   round(float(ret_pct), 4),
            'hold_bars':    int(bars_held),
        })

        # Advance past exit bar — one position per ticker, no stacking
        i += bars_held + 1

    return trades, gap_stats


# ── Multi-ticker runner ────────────────────────────────────────────────────────

def run_m6_backtest(
    mode: str = 'extended',
    earnings_dict: dict = None,
) -> tuple:
    """Run M6 backtest for all 27 tickers in the given bar mode.

    Parameters
    ----------
    mode          : 'extended' (4 bars/day) or 'rth' (2 bars/day)
    earnings_dict : pre-loaded earnings dict from load_earnings()

    Returns
    -------
    (all_trades, aggregate_gap_stats)
    """
    if earnings_dict is None:
        earnings_dict = {}

    all_trades = []
    agg_stats  = {
        'total': 0, 'qualified': 0,
        'earnings_excluded': 0, 'corp_action_excluded': 0,
    }

    for ticker in TICKERS:
        print(f'  {ticker}...', end=' ', flush=True)
        try:
            df = load_extended_data(ticker)
        except FileNotFoundError:
            print('SKIP (no data)')
            continue

        bars = build_4h_extended(df, mode=mode)
        trades, gap_stats = run_m6_single_ticker(
            ticker, bars, earnings_dict, mode=mode
        )
        all_trades.extend(trades)
        for k in agg_stats:
            agg_stats[k] += gap_stats[k]

        print(
            f'{len(trades)} trades  '
            f'(gap_events={gap_stats["total"]}, '
            f'qualified={gap_stats["qualified"]}, '
            f'earnings_excl={gap_stats["earnings_excluded"]}, '
            f'corp_excl={gap_stats["corp_action_excluded"]})'
        )

    return all_trades, agg_stats


# ── Output helpers ─────────────────────────────────────────────────────────────

def _print_comparison(stats_rth: dict, stats_ext: dict) -> None:
    """Print aligned comparison table to stdout."""
    bl    = KNOWN_BASELINE
    col_w = [22, 18, 20, 16]
    header = (
        f'{"Metric":<{col_w[0]}} {"RTH (2 bars/day)":>{col_w[1]}}'
        f' {"Extended (4 bars/day)":>{col_w[2]}} {"Known Baseline":>{col_w[3]}}'
    )
    sep = '-' * sum(col_w)
    print()
    print(header)
    print(sep)

    def row(label, rth_val, ext_val, bl_val):
        print(
            f'{label:<{col_w[0]}} {rth_val:>{col_w[1]}}'
            f' {ext_val:>{col_w[2]}} {bl_val:>{col_w[3]}}'
        )

    row('N',
        str(stats_rth['N']),
        str(stats_ext['N']),
        str(bl['N']))
    row('PF',
        f'{stats_rth["PF"]:.2f}',
        f'{stats_ext["PF"]:.2f}',
        f'{bl["PF"]:.2f}')
    row('WR %',
        f'{stats_rth["WR"]:.1f}%',
        f'{stats_ext["WR"]:.1f}%',
        f'{bl["WR"]:.1f}%')
    row('Mean %',
        f'{stats_rth["Mean"]:+.2f}%',
        f'{stats_ext["Mean"]:+.2f}%',
        f'+{bl["Mean"]:.2f}%')
    row('Avg Hold (bars)',
        f'{stats_rth["Avg_Hold"]:.1f}',
        f'{stats_ext["Avg_Hold"]:.1f}',
        '?')


def _print_gap_stats(stats_rth: dict, stats_ext: dict) -> None:
    """Print gap event funnel statistics for both modes."""
    col_w = [26, 16, 16]
    header = (
        f'{"Gap Event Stat":<{col_w[0]}} {"RTH":>{col_w[1]}}'
        f' {"Extended":>{col_w[2]}}'
    )
    sep = '-' * sum(col_w)
    print()
    print(header)
    print(sep)

    def row(label, rv, ev):
        print(f'{label:<{col_w[0]}} {rv:>{col_w[1]}} {ev:>{col_w[2]}}')

    row('Total entry bars',         str(stats_rth['total']),              str(stats_ext['total']))
    row('Corp action excluded',      str(stats_rth['corp_action_excluded']), str(stats_ext['corp_action_excluded']))
    row('Qualified (gap ≤ -4%)',     str(stats_rth['qualified']),          str(stats_ext['qualified']))
    row('Earnings excluded',         str(stats_rth['earnings_excluded']),  str(stats_ext['earnings_excluded']))
    row('Trades taken',
        str(stats_rth['qualified'] - stats_rth['earnings_excluded']),
        str(stats_ext['qualified'] - stats_ext['earnings_excluded']))


def _build_comparison_md(
    stats_rth: dict,
    stats_ext: dict,
    gap_rth: dict,
    gap_ext: dict,
) -> str:
    """Build markdown comparison table string."""
    bl = KNOWN_BASELINE
    trades_rth = gap_rth['qualified'] - gap_rth['earnings_excluded']
    trades_ext = gap_ext['qualified'] - gap_ext['earnings_excluded']
    lines = [
        '# M6 Shock-Reversal: Extended Hours 4H Backtest — Comparison',
        '',
        '| Metric | RTH (2 bars/day) | Extended (4 bars/day) | Known Baseline |',
        '|--------|-------------------|----------------------|----------------|',
        f'| N | {stats_rth["N"]} | {stats_ext["N"]} | {bl["N"]} |',
        f'| PF | {stats_rth["PF"]:.2f} | {stats_ext["PF"]:.2f} | {bl["PF"]:.2f} |',
        f'| WR % | {stats_rth["WR"]:.1f}% | {stats_ext["WR"]:.1f}% | {bl["WR"]:.1f}% |',
        f'| Mean % | {stats_rth["Mean"]:+.2f}% | {stats_ext["Mean"]:+.2f}% | +{bl["Mean"]:.2f}% |',
        f'| Avg Hold (bars) | {stats_rth["Avg_Hold"]:.1f} | {stats_ext["Avg_Hold"]:.1f} | ? |',
        '',
        '## Gap Event Funnel',
        '',
        '| Stat | RTH | Extended |',
        '|------|-----|----------|',
        f'| Total entry bars | {gap_rth["total"]} | {gap_ext["total"]} |',
        f'| Corp action excluded | {gap_rth["corp_action_excluded"]} | {gap_ext["corp_action_excluded"]} |',
        f'| Qualified (gap ≤ −4%) | {gap_rth["qualified"]} | {gap_ext["qualified"]} |',
        f'| Earnings excluded | {gap_rth["earnings_excluded"]} | {gap_ext["earnings_excluded"]} |',
        f'| Trades taken | {trades_rth} | {trades_ext} |',
        '',
        '## Configuration',
        '',
        '- **RTH mode**: 2 bars/day — Bar 1 (09:30–13:25 ET), Bar 2 (13:30–15:55 ET)',
        '- **Extended mode**: 4 bars/day — Bar A (04:00–07:55 ET), Bar B (08:00–11:55 ET),'
        ' Bar C (12:00–15:55 ET), Bar D (16:00–19:55 ET)',
        '- **Known Baseline**: prior backtest run result',
        '- **Tickers**: 27 (22-ticker M4 set + ARM, INTC, JD, MSTR, SMCI)',
        '',
        '## Entry Rules (ALL required)',
        '',
        '1. Gap ≤ −4.0% at first bar of day',
        '   - Extended: `gap = (Bar_B_open − prior_day_last_close) / prior_close`',
        '   - RTH:      `gap = (Bar_1_open − prior_day_last_close) / prior_close`',
        '   - prior_close = last available bar close of the prior trading day',
        '2. Not a corporate action: |gap_pct| > 15% AND prior_close > 2 × entry_open → skip',
        '3. Not within ±1 calendar day of an earnings event',
        '',
        '## Exit Rules (first triggered)',
        '',
        '1. Close ≥ gap_midpoint  '
        '`(gap_midpoint = prior_close + (entry_open − prior_close) / 2)`',
        '2. 15-bar hard maximum',
        '',
        '## Notes',
        '',
        '- Long only; no VIX filter',
        '- Entry price = first bar close (Bar B or Bar 1)',
        '- Exit  price = exit bar close',
        '- One position per ticker at a time (no stacking)',
    ]
    return '\n'.join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('=' * 65)
    print('M6 SHOCK-REVERSAL EXTENDED HOURS BACKTEST')
    print('=' * 65)

    print('\nLoading earnings calendar...')
    try:
        earnings_dict = load_earnings()
        n_tickers_with_earnings = sum(1 for v in earnings_dict.values() if v)
        print(f'  {n_tickers_with_earnings} tickers with earnings dates loaded')
    except Exception as exc:
        print(f'  WARNING: could not load earnings — {exc}')
        earnings_dict = {}

    print('\n--- Mode: EXTENDED (4 bars/day) ---')
    trades_ext, gap_ext = run_m6_backtest('extended', earnings_dict=earnings_dict)

    print('\n--- Mode: RTH (2 bars/day) ---')
    trades_rth, gap_rth = run_m6_backtest('rth', earnings_dict=earnings_dict)

    stats_ext = _compute_stats(trades_ext)
    stats_rth = _compute_stats(trades_rth)

    # ── Overall comparison ────────────────────────────────────────────────────
    print('\n' + '=' * 65)
    print('COMPARISON TABLE  (all dates)')
    print('=' * 65)
    _print_comparison(stats_rth, stats_ext)

    # ── Gap event funnel ──────────────────────────────────────────────────────
    print('\n' + '=' * 65)
    print('GAP EVENT FUNNEL  (all dates)')
    print('=' * 65)
    _print_gap_stats(gap_rth, gap_ext)

    # ── Per-ticker breakdown ───────────────────────────────────────────────────
    print('\n' + '=' * 65)
    print('PER-TICKER TRADE COUNT  (all dates)')
    print('=' * 65)
    print(f'  {"Ticker":<8} {"RTH":>6} {"EXT":>6}')
    print('  ' + '-' * 22)
    for tk in TICKERS:
        rth_n = sum(1 for t in trades_rth if t['ticker'] == tk)
        ext_n = sum(1 for t in trades_ext if t['ticker'] == tk)
        print(f'  {tk:<8} {rth_n:>6} {ext_n:>6}')

    # ── Exit reason breakdown ──────────────────────────────────────────────────
    print('\n' + '=' * 65)
    print('EXIT REASON BREAKDOWN')
    print('=' * 65)
    for mode_label, trades in [('RTH', trades_rth), ('Extended', trades_ext)]:
        if not trades:
            print(f'  {mode_label}: no trades')
            continue
        midpoint = sum(1 for t in trades if t['exit_reason'] == 'midpoint')
        hard_max = sum(1 for t in trades if t['exit_reason'] == 'hard_max')
        total    = len(trades)
        print(f'  {mode_label}: midpoint={midpoint} ({midpoint/total*100:.1f}%)  '
              f'hard_max={hard_max} ({hard_max/total*100:.1f}%)')

    # ── Save outputs ──────────────────────────────────────────────────────────
    os.makedirs(OUT_DIR, exist_ok=True)

    if trades_ext:
        ext_path = os.path.join(OUT_DIR, 'm6_extended_trades.csv')
        pd.DataFrame(trades_ext).to_csv(ext_path, index=False)
        print(f'\nExtended trades ({stats_ext["N"]}) -> {ext_path}')

    if trades_rth:
        rth_path = os.path.join(OUT_DIR, 'm6_rth_trades.csv')
        pd.DataFrame(trades_rth).to_csv(rth_path, index=False)
        print(f'RTH trades      ({stats_rth["N"]}) -> {rth_path}')

    comp_path = os.path.join(OUT_DIR, 'm6_comparison.md')
    with open(comp_path, 'w', encoding='utf-8') as f:
        f.write(_build_comparison_md(stats_rth, stats_ext, gap_rth, gap_ext))
    print(f'Comparison      -> {comp_path}')
