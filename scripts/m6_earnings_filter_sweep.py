#!/usr/bin/env python3
"""M6 earnings-filter sensitivity sweep.

Tests how M6 PF/WR/N/Sharpe/MaxDD change across earnings-exclusion buffer
sizes.  Runs both RTH (2 bars/day) and Extended (4 bars/day) modes for each
buffer value.

Output
------
results/earnings_sweep/m6_sweep.md              — comparison tables (both modes)
results/earnings_sweep/m6_trades_filter_{N}.csv — per-filter trade lists

Regression check (operator): filter_days=1 must match known baseline within ±5%
  RTH:      N=378, PF=1.68
  Extended: N=326, PF=2.12
If either diverges the script prints a warning and exits with code 1.

Usage: python scripts/m6_earnings_filter_sweep.py
"""
import sys
import os
import math

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

# ── Constants ──────────────────────────────────────────────────────────────────

TICKERS = [
    'AAPL', 'AMD', 'AMZN', 'ARM', 'AVGO', 'BA', 'BABA', 'BIDU',
    'C', 'COIN', 'COST', 'GOOGL', 'GS', 'INTC', 'JD', 'JPM',
    'MARA', 'META', 'MSFT', 'MSTR', 'MU', 'NVDA', 'PLTR',
    'SMCI', 'TSLA', 'TSM', 'V',
]  # 27 equities — identical to m6_backtest_extended.py

FILTER_VALUES = [0, 1, 3, 6, 10]
# 0 = no filter, 1 = current production value, others = sensitivity points

_BASE   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(_BASE, 'results', 'earnings_sweep')

# Known baseline for regression check (filter_days=1)
KNOWN_BASELINE = {
    'rth':      {'N': 378, 'PF': 1.68},
    'extended': {'N': 326, 'PF': 2.12},
}
REGRESSION_TOL = 0.05   # ±5 % of known baseline value

# IS ends 2024-12-31; OOS starts 2025-01-01
OOS_START = '2025-01-01'


# ── Stats helpers ──────────────────────────────────────────────────────────────

def _compute_stats(trades: list) -> dict:
    """Return N, PF, WR %, Mean %, MaxDD %, trade-level Sharpe, Avg Hold."""
    if not trades:
        return {
            'N': 0, 'PF': 0.0, 'WR': 0.0, 'Mean': 0.0,
            'MaxDD': 0.0, 'Sharpe': float('nan'), 'Avg_Hold': 0.0,
        }
    rets  = np.array([t['return_pct'] for t in trades], dtype=float)
    holds = np.array([t['hold_bars']  for t in trades], dtype=float)

    wins   = rets[rets > 0]
    losses = rets[rets <= 0]
    pf     = float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float('inf')
    wr     = float((rets > 0).mean() * 100)

    # Additive cumulative equity curve → max peak-to-trough drawdown
    cum    = np.cumsum(rets)
    peak   = np.maximum.accumulate(cum)
    max_dd = float((peak - cum).max())

    std    = float(rets.std(ddof=1)) if len(rets) > 1 else float('nan')
    sharpe = float(rets.mean() / std) if (std and not math.isnan(std) and std > 0) else float('nan')

    return {
        'N':        len(rets),
        'PF':       round(pf, 2) if not math.isinf(pf) else float('inf'),
        'WR':       round(wr, 2),
        'Mean':     round(float(rets.mean()), 4),
        'MaxDD':    round(max_dd, 2),
        'Sharpe':   round(sharpe, 3) if not math.isnan(sharpe) else float('nan'),
        'Avg_Hold': round(float(holds.mean()), 2),
    }


def _split_trades(trades: list) -> tuple:
    """Return (is_trades, oos_trades) split at OOS_START."""
    is_trades  = [t for t in trades if t['entry_date'] < OOS_START]
    oos_trades = [t for t in trades if t['entry_date'] >= OOS_START]
    return is_trades, oos_trades


# ── Per-ticker backtest ────────────────────────────────────────────────────────

def run_m6_single_ticker(
    ticker: str,
    bars: pd.DataFrame,
    earnings_dict: dict,
    mode: str = 'extended',
    buffer_days: int = 1,
) -> tuple:
    """Run M6 on a single ticker's 4H bars with a configurable earnings buffer.

    When buffer_days=0 the earnings filter is skipped entirely.
    All other logic is identical to m6_backtest_extended.py.

    Returns (trades_list, gap_stats_dict).
    """
    if bars.empty:
        return [], {
            'total': 0, 'qualified': 0,
            'earnings_excluded': 0, 'corp_action_excluded': 0,
        }

    entry_label = 'B' if mode == 'extended' else '1'

    # date → last-bar close (highest bar_label alphabetically on that day)
    last_close_by_date: dict = {}
    for date, grp in bars.groupby('date', sort=True):
        last_close_by_date[date] = float(
            grp.sort_values('bar_label').iloc[-1]['close']
        )
    sorted_dates = sorted(last_close_by_date.keys())
    date_to_rank = {d: i for i, d in enumerate(sorted_dates)}

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
        if labels[i] != entry_label:
            i += 1
            continue

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

        # Corporate action guard
        if abs(gap_pct) > 15.0 and prior_close > 2.0 * entry_open:
            gap_stats['corp_action_excluded'] += 1
            i += 1
            continue

        # Gap size gate: must be ≤ -4%
        if gap_pct > -4.0:
            i += 1
            continue

        gap_stats['qualified'] += 1

        # Earnings filter — skipped entirely when buffer_days=0
        if buffer_days > 0 and is_earnings_window(
            ticker, dates[i], earnings_dict, buffer_days=buffer_days
        ):
            gap_stats['earnings_excluded'] += 1
            i += 1
            continue

        # ── All gates passed — open trade ─────────────────────────────────
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
            if corrupt[j]:
                exit_price  = float(closes[j])
                exit_date   = dates[j]
                exit_bar    = labels[j]
                exit_reason = 'hard_max'
                break
            if closes[j] >= gap_midpoint:
                exit_price  = float(closes[j])
                exit_date   = dates[j]
                exit_bar    = labels[j]
                exit_reason = 'midpoint'
                break
            if bars_held == 15:
                exit_price  = float(closes[j])
                exit_date   = dates[j]
                exit_bar    = labels[j]
                exit_reason = 'hard_max'
                break

        if exit_price is None:
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
            'mode':         mode,
            'filter_days':  buffer_days,
        })

        i += bars_held + 1

    return trades, gap_stats


def run_m6_backtest(
    mode: str = 'extended',
    earnings_dict: dict = None,
    buffer_days: int = 1,
) -> tuple:
    """Run M6 for all 27 tickers with the specified earnings buffer.

    Returns (all_trades, aggregate_gap_stats).
    """
    if earnings_dict is None:
        earnings_dict = {}

    all_trades = []
    agg_stats  = {
        'total': 0, 'qualified': 0,
        'earnings_excluded': 0, 'corp_action_excluded': 0,
    }

    for ticker in TICKERS:
        print(f'    {ticker}...', end=' ', flush=True)
        try:
            df = load_extended_data(ticker)
        except FileNotFoundError:
            print('SKIP (no data)')
            continue

        bars = build_4h_extended(df, mode=mode)
        trades, gap_stats = run_m6_single_ticker(
            ticker, bars, earnings_dict, mode=mode, buffer_days=buffer_days
        )
        all_trades.extend(trades)
        for k in agg_stats:
            agg_stats[k] += gap_stats[k]

        print(
            f'{len(trades)} trades  '
            f'(qualified={gap_stats["qualified"]}, '
            f'earnings_excl={gap_stats["earnings_excluded"]})'
        )

    return all_trades, agg_stats


# ── Regression check ───────────────────────────────────────────────────────────

def _check_regression(results_rth: list, results_ext: list) -> bool:
    """Verify filter=1 results are within REGRESSION_TOL of known baselines.

    Returns True if all checks pass, False if any fail.
    """
    r1_rth = next(r for r in results_rth if r['buffer_days'] == 1)
    r1_ext = next(r for r in results_ext if r['buffer_days'] == 1)

    all_ok = True
    for mode_key, stats in [('rth', r1_rth['full']), ('extended', r1_ext['full'])]:
        bl = KNOWN_BASELINE[mode_key]
        for metric in ('N', 'PF'):
            actual   = stats[metric]
            expected = bl[metric]
            if expected == 0:
                continue
            delta  = abs(actual - expected) / expected
            status = 'OK' if delta <= REGRESSION_TOL else 'FAIL'
            print(
                f'  [{mode_key.upper()} filter=1] {metric}: '
                f'got {actual}, expected {expected} '
                f'(Δ={delta:.1%})  {status}'
            )
            if delta > REGRESSION_TOL:
                all_ok = False

    return all_ok


# ── Markdown builder ───────────────────────────────────────────────────────────

def _fmt(val, fmt_str='') -> str:
    """Format a value; nan → '—', inf → '∞'."""
    if isinstance(val, float):
        if math.isnan(val):
            return '—'
        if math.isinf(val):
            return '∞'
    if fmt_str:
        return format(val, fmt_str)
    return str(val)


def _primary_table(results: list, n0: int) -> list:
    """Build the main sweep table rows."""
    lines = [
        '| filter_days | N (full) | PF (full) | WR (full) |'
        ' N (IS) | PF (IS) | N (OOS) | PF (OOS) | Trades blocked vs filter=0 |',
        '|-------------|----------|-----------|-----------|'
        '--------|---------|---------|----------|----------------------------|',
    ]
    for r in results:
        blocked = n0 - r['full']['N'] if (r['buffer_days'] != 0 and n0 > 0) else 0
        blocked_str = '0 (baseline)' if r['buffer_days'] == 0 else str(blocked)
        lines.append(
            f'| {r["buffer_days"]}'
            f' | {r["full"]["N"]}'
            f' | {_fmt(r["full"]["PF"], ".2f")}'
            f' | {_fmt(r["full"]["WR"], ".1f")}%'
            f' | {r["is"]["N"]}'
            f' | {_fmt(r["is"]["PF"], ".2f")}'
            f' | {r["oos"]["N"]}'
            f' | {_fmt(r["oos"]["PF"], ".2f")}'
            f' | {blocked_str} |'
        )
    return lines


def _extended_metrics_table(results: list) -> list:
    """Build the extended metrics table (Mean, MaxDD, Sharpe, Avg Hold)."""
    lines = [
        '| filter_days | Mean % (full) | MaxDD % (full) | Sharpe (full)'
        ' | Avg Hold (full) | Mean % (OOS) | Sharpe (OOS) |',
        '|-------------|---------------|----------------|---------------'
        '|-----------------|--------------|--------------|',
    ]
    for r in results:
        lines.append(
            f'| {r["buffer_days"]}'
            f' | {_fmt(r["full"]["Mean"], "+.2f")}'
            f' | {_fmt(r["full"]["MaxDD"], ".2f")}'
            f' | {_fmt(r["full"]["Sharpe"])}'
            f' | {_fmt(r["full"]["Avg_Hold"], ".1f")}'
            f' | {_fmt(r["oos"]["Mean"], "+.2f")}'
            f' | {_fmt(r["oos"]["Sharpe"])} |'
        )
    return lines


def _build_sweep_md(
    results_rth: list,
    results_ext: list,
    n0_rth: int,
    n0_ext: int,
    best_rth: dict,
    best_ext: dict,
) -> str:
    lines = [
        '# M6 Earnings Filter Sensitivity Sweep',
        '',
        f'- IS period : all entry dates before {OOS_START}',
        f'- OOS period: {OOS_START} onwards',
        f'- Tickers   : {len(TICKERS)} equities',
        f'- Filter values tested: {FILTER_VALUES}',
        f'- Gap threshold: ≤ −4.0%  |  Exit: midpoint OR 15-bar hard max  |  Long only',
        '',
        '---',
        '',
        '## RTH mode (2 bars/day)',
        '',
    ]
    lines += _primary_table(results_rth, n0_rth)
    lines += [
        '',
        '### RTH — Extended Metrics',
        '',
    ]
    lines += _extended_metrics_table(results_rth)
    lines += [
        '',
        f'**RTH: filter_days={best_rth["buffer_days"]} maximizes OOS PF'
        f' ({_fmt(best_rth["oos"]["PF"], ".2f")})**',
        '',
        '---',
        '',
        '## Extended mode (4 bars/day)',
        '',
    ]
    lines += _primary_table(results_ext, n0_ext)
    lines += [
        '',
        '### Extended — Extended Metrics',
        '',
    ]
    lines += _extended_metrics_table(results_ext)
    lines += [
        '',
        f'**Extended: filter_days={best_ext["buffer_days"]} maximizes OOS PF'
        f' ({_fmt(best_ext["oos"]["PF"], ".2f")})**',
        '',
        '---',
        '',
        '## Configuration',
        '',
        '- RTH bars   : Bar 1 (09:30–13:25 ET), Bar 2 (13:30–15:55 ET)',
        '- Extended bars: Bar A (04:00–07:55 ET), Bar B (08:00–11:55 ET),'
        ' Bar C (12:00–15:55 ET), Bar D (16:00–19:55 ET)',
        f'- Known baseline (filter=1):'
        f' RTH N={KNOWN_BASELINE["rth"]["N"]} PF={KNOWN_BASELINE["rth"]["PF"]},'
        f' Extended N={KNOWN_BASELINE["extended"]["N"]} PF={KNOWN_BASELINE["extended"]["PF"]}',
        '- Regression tolerance: ±5%',
        '- Entry price: first bar close (Bar 1 for RTH, Bar B for Extended)',
        '- No VIX filter; one position per ticker at a time',
    ]
    return '\n'.join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    SEP = '=' * 65

    print(SEP)
    print('M6 EARNINGS FILTER SENSITIVITY SWEEP')
    print(SEP)

    print('\nLoading earnings calendar...')
    try:
        earnings_dict = load_earnings()
        n_tickers_with_earnings = sum(1 for v in earnings_dict.values() if v)
        print(f'  {n_tickers_with_earnings} tickers with earnings dates loaded')
    except Exception as exc:
        print(f'  WARNING: could not load earnings — {exc}')
        earnings_dict = {}

    os.makedirs(OUT_DIR, exist_ok=True)

    results_rth: list = []
    results_ext: list = []
    n0_rth = 0
    n0_ext = 0

    for buf in FILTER_VALUES:
        print(f'\n{SEP}')
        print(f'filter_days = {buf}')
        print(SEP)

        # --- RTH ---
        print(f'\n  [RTH] buffer_days={buf}')
        trades_rth, gap_rth = run_m6_backtest('rth', earnings_dict=earnings_dict, buffer_days=buf)
        is_rth, oos_rth = _split_trades(trades_rth)
        rec_rth = {
            'buffer_days': buf,
            'full': _compute_stats(trades_rth),
            'is':   _compute_stats(is_rth),
            'oos':  _compute_stats(oos_rth),
        }
        results_rth.append(rec_rth)
        if buf == 0:
            n0_rth = rec_rth['full']['N']
        print(
            f'  RTH  full: N={rec_rth["full"]["N"]}, '
            f'PF={_fmt(rec_rth["full"]["PF"], ".2f")}, '
            f'WR={rec_rth["full"]["WR"]:.1f}%  '
            f'| IS: N={rec_rth["is"]["N"]} PF={_fmt(rec_rth["is"]["PF"], ".2f")}'
            f'  OOS: N={rec_rth["oos"]["N"]} PF={_fmt(rec_rth["oos"]["PF"], ".2f")}'
        )

        # --- Extended ---
        print(f'\n  [EXT] buffer_days={buf}')
        trades_ext, gap_ext = run_m6_backtest('extended', earnings_dict=earnings_dict, buffer_days=buf)
        is_ext, oos_ext = _split_trades(trades_ext)
        rec_ext = {
            'buffer_days': buf,
            'full': _compute_stats(trades_ext),
            'is':   _compute_stats(is_ext),
            'oos':  _compute_stats(oos_ext),
        }
        results_ext.append(rec_ext)
        if buf == 0:
            n0_ext = rec_ext['full']['N']
        print(
            f'  EXT  full: N={rec_ext["full"]["N"]}, '
            f'PF={_fmt(rec_ext["full"]["PF"], ".2f")}, '
            f'WR={rec_ext["full"]["WR"]:.1f}%  '
            f'| IS: N={rec_ext["is"]["N"]} PF={_fmt(rec_ext["is"]["PF"], ".2f")}'
            f'  OOS: N={rec_ext["oos"]["N"]} PF={_fmt(rec_ext["oos"]["PF"], ".2f")}'
        )

        # Save per-filter CSV (both modes in one file, distinguished by 'mode' column)
        combined = trades_rth + trades_ext
        if combined:
            csv_path = os.path.join(OUT_DIR, f'm6_trades_filter_{buf}.csv')
            pd.DataFrame(combined).to_csv(csv_path, index=False)
            print(f'\n  Saved {len(combined)} trades -> {csv_path}')

    # ── Regression check (filter=1 vs known baseline) ─────────────────────────
    print(f'\n{SEP}')
    print('REGRESSION CHECK  (filter=1 vs known baseline, tolerance ±5%)')
    print(SEP)
    regression_ok = _check_regression(results_rth, results_ext)
    if not regression_ok:
        print(
            '\nHALT: filter=1 result diverges >5% from known baseline.\n'
            'Investigate data source / bar construction before proceeding.'
        )
        sys.exit(1)

    # ── OOS PF summary ────────────────────────────────────────────────────────
    print(f'\n{SEP}')
    print('OOS PF BY FILTER VALUE')
    print(SEP)
    print(f'\n  {"filter_days":>12}  {"OOS PF (RTH)":>14}  {"OOS PF (EXT)":>14}')
    print('  ' + '-' * 46)

    def _oos_pf(r):
        v = r['oos']['PF']
        return v if (not math.isnan(v) and not math.isinf(v)) else -1.0

    best_rth = max(results_rth, key=_oos_pf)
    best_ext = max(results_ext, key=_oos_pf)

    for r_rth, r_ext in zip(results_rth, results_ext):
        tag_rth = ' <-- max OOS PF' if r_rth['buffer_days'] == best_rth['buffer_days'] else ''
        tag_ext = ' <-- max OOS PF' if r_ext['buffer_days'] == best_ext['buffer_days'] else ''
        print(
            f'  {r_rth["buffer_days"]:>12}  '
            f'{_fmt(r_rth["oos"]["PF"], ".2f"):>14}{tag_rth}'
        )
        if tag_ext:
            print(
                f'  {"":>12}  {"":>14}  '
                f'{_fmt(r_ext["oos"]["PF"], ".2f"):>14}{tag_ext}'
            )

    print(
        f'\n  RTH      mode: filter_days={best_rth["buffer_days"]} '
        f'maximizes OOS PF ({_fmt(best_rth["oos"]["PF"], ".2f")})'
    )
    print(
        f'  Extended mode: filter_days={best_ext["buffer_days"]} '
        f'maximizes OOS PF ({_fmt(best_ext["oos"]["PF"], ".2f")})'
    )

    # ── Write markdown report ─────────────────────────────────────────────────
    md = _build_sweep_md(results_rth, results_ext, n0_rth, n0_ext, best_rth, best_ext)
    md_path = os.path.join(OUT_DIR, 'm6_sweep.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f'\nMarkdown report -> {md_path}')
    print('Done.')
