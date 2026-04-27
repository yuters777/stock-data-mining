#!/usr/bin/env python3
"""M7 earnings-filter sensitivity sweep.

Tests how M7 PF/WR/N/MaxDD change across earnings-exclusion buffer sizes.
Runs both RTH and Extended modes for each buffer value.

Output
------
results/earnings_sweep/m7_sweep.md              — comparison tables (both modes)
results/earnings_sweep/m7_trades_filter_{N}.csv — per-filter trade lists

Regression check (operator): filter_days=6 must match known baseline within ±5%
  RTH:      N=188, PF=1.72
  Extended: N=169, PF=1.63

Usage: python scripts/m7_earnings_filter_sweep.py
"""
import sys
import os
import math

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from m7_backtest_extended import (
    detect_m7_signals,
    run_m7_backtest,
    load_all_tickers,
    build_daily_from_m5,
    compute_daily_indicators,
    compute_rs_ranks,
    TICKERS,
)
from backtest_utils_extended import (
    build_4h_extended,
    compute_indicators,
    apply_ema21_warmup_mask,
    load_vix_daily,
    load_earnings,
)

# ── Constants ──────────────────────────────────────────────────────────────────

FILTER_VALUES = [0, 3, 6, 10, 14]
IS_END_DATE   = '2024-12-31'
OOS_START     = '2025-01-01'   # first OOS date (day after IS_END_DATE)

_BASE   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(_BASE, 'results', 'earnings_sweep')

KNOWN_BASELINE = {
    'rth': {'N': 188, 'PF': 1.72},
    'ext': {'N': 169, 'PF': 1.63},
}
REGRESSION_TOL = 0.05   # ±5% of known baseline value


# ── Stats helpers ──────────────────────────────────────────────────────────────

def _compute_stats(trades: list) -> dict:
    """Return N, PF, WR %, Mean %, MaxDD %, Avg Hold for executed trades."""
    executed = [t for t in trades
                if t.get('exit_reason') != 'SKIP_MAX_CONCURRENT'
                and pd.notna(t.get('return_pct'))]
    if not executed:
        return {
            'N': 0, 'PF': 0.0, 'WR': 0.0, 'Mean': 0.0,
            'MaxDD': 0.0, 'Avg_Hold': 0.0,
        }
    rets  = np.array([t['return_pct'] for t in executed], dtype=float)
    holds = np.array([t['hold_days']  for t in executed], dtype=float)

    wins   = rets[rets > 0]
    losses = rets[rets <= 0]
    pf     = float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float('inf')
    wr     = float((rets > 0).mean() * 100)

    cum    = np.cumsum(rets)
    peak   = np.maximum.accumulate(cum)
    max_dd = float((peak - cum).max())

    return {
        'N':        len(rets),
        'PF':       round(pf, 2) if not math.isinf(pf) else float('inf'),
        'WR':       round(wr, 2),
        'Mean':     round(float(rets.mean()), 4),
        'MaxDD':    round(max_dd, 2),
        'Avg_Hold': round(float(holds.mean()), 2),
    }


def _split_trades(trades: list) -> tuple:
    """Return (is_trades, oos_trades) split at OOS_START."""
    is_trades  = [t for t in trades if t.get('entry_date', '') < OOS_START]
    oos_trades = [t for t in trades if t.get('entry_date', '') >= OOS_START]
    return is_trades, oos_trades


# ── Regression check ───────────────────────────────────────────────────────────

def _check_regression(results_rth: list, results_ext: list) -> bool:
    """Verify filter=6 results are within REGRESSION_TOL of known baselines."""
    r6_rth = next(r for r in results_rth if r['buffer_days'] == 6)
    r6_ext = next(r for r in results_ext if r['buffer_days'] == 6)

    all_ok = True
    for mode_key, stats in [('rth', r6_rth['full']), ('ext', r6_ext['full'])]:
        bl = KNOWN_BASELINE[mode_key]
        for metric in ('N', 'PF'):
            actual   = stats[metric]
            expected = bl[metric]
            if expected == 0:
                continue
            delta  = abs(actual - expected) / expected
            status = 'OK' if delta <= REGRESSION_TOL else 'FAIL'
            print(
                f'  [{mode_key.upper()} filter=6] {metric}: '
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
        ' N (IS) | PF (IS) | N (OOS) | PF (OOS) | Blocked vs filter=0 |',
        '|-------------|----------|-----------|-----------|'
        '--------|---------|---------|----------|---------------------|',
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
    """Build the extended metrics table (Mean, MaxDD, Avg Hold)."""
    lines = [
        '| filter_days | Mean % (full) | MaxDD % (full) | Avg Hold (full) | Mean % (OOS) |',
        '|-------------|---------------|----------------|-----------------|--------------|',
    ]
    for r in results:
        lines.append(
            f'| {r["buffer_days"]}'
            f' | {_fmt(r["full"]["Mean"], "+.2f")}'
            f' | {_fmt(r["full"]["MaxDD"], ".2f")}'
            f' | {_fmt(r["full"]["Avg_Hold"], ".1f")}'
            f' | {_fmt(r["oos"]["Mean"], "+.2f")} |'
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
        '# M7 Earnings Filter Sensitivity Sweep',
        '',
        f'- IS period : all entry dates before {OOS_START}',
        f'- OOS period: {OOS_START} onwards',
        f'- Tickers   : {len(TICKERS)} equities',
        f'- Filter values tested: {FILTER_VALUES}',
        '- Signal: 1–3 day pullback → recovery day | VIX < 20 | RS top 30%'
        ' | within 5% of 60d high | no earnings ±N days',
        '',
        '---',
        '',
        '## RTH mode',
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
        '## EXT mode',
        '',
    ]
    lines += _primary_table(results_ext, n0_ext)
    lines += [
        '',
        '### EXT — Extended Metrics',
        '',
    ]
    lines += _extended_metrics_table(results_ext)
    lines += [
        '',
        f'**EXT: filter_days={best_ext["buffer_days"]} maximizes OOS PF'
        f' ({_fmt(best_ext["oos"]["PF"], ".2f")})**',
        '',
        '---',
        '',
        '## Configuration',
        '',
        '- Entry: recovery day close (after 1–3 red days)',
        '- Exit: EMA9 breach | pullback low breach | 6-day max | VIX ≥ 25 override',
        '- Max concurrent positions: 2 (ranked by RS, distance-to-high, depth, ticker)',
        f'- Known baseline (filter=6):'
        f' RTH N={KNOWN_BASELINE["rth"]["N"]} PF={KNOWN_BASELINE["rth"]["PF"]},'
        f' EXT N={KNOWN_BASELINE["ext"]["N"]} PF={KNOWN_BASELINE["ext"]["PF"]}',
        '- Regression tolerance: ±5%',
    ]
    return '\n'.join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    SEP = '=' * 65

    print(SEP)
    print('M7 EARNINGS FILTER SENSITIVITY SWEEP')
    print(SEP)

    print(f'\nLoading M5 data for {len(TICKERS)} signal tickers + SPY...')
    ticker_data = load_all_tickers()
    n_sig = sum(1 for t in ticker_data if t in TICKERS)
    has_spy = 'SPY' in ticker_data
    print(f'Loaded {n_sig}/{len(TICKERS)} signal tickers'
          f'{" + SPY" if has_spy else " (SPY missing — RS dates excluded)"}.')

    print('Loading VIX...')
    vix_df = load_vix_daily()
    print(f'  VIX: {len(vix_df)} rows, '
          f'{vix_df["date"].min()} to {vix_df["date"].max()}')

    print('Loading earnings...')
    earnings = load_earnings()
    print(f'  Earnings: {len(earnings)} tickers covered.')

    print('\nBuilding bars and indicators (one-time)...')
    daily_data: dict = {}
    bars_rth:   dict = {}
    bars_ext:   dict = {}

    for ticker, df_m5 in ticker_data.items():
        daily = build_daily_from_m5(df_m5)
        daily_data[ticker] = compute_daily_indicators(daily)

        if ticker == 'SPY':
            continue  # SPY used for RS only; no 4H bars needed

        b_rth = build_4h_extended(df_m5, mode='rth')
        b_rth = compute_indicators(b_rth, warmup_rows=0)
        b_rth['ema21'] = apply_ema21_warmup_mask(b_rth)
        bars_rth[ticker] = b_rth

        b_ext = build_4h_extended(df_m5, mode='extended')
        bars_ext[ticker] = compute_indicators(b_ext)

    print('Computing RS ranks...')
    rs_ranks = compute_rs_ranks(daily_data)
    print(f'  RS rank entries: {len(rs_ranks):,}')

    os.makedirs(OUT_DIR, exist_ok=True)

    results_rth: list = []
    results_ext: list = []
    n0_rth = 0
    n0_ext = 0

    for buf in FILTER_VALUES:
        print(f'\n{SEP}')
        print(f'filter_days = {buf}')
        print(SEP)

        all_rth_sigs: list = []
        all_ext_sigs: list = []

        for ticker in TICKERS:
            if ticker not in daily_data:
                continue
            rth_sigs, ext_sigs = detect_m7_signals(
                ticker,
                daily_data[ticker],
                bars_rth.get(ticker, pd.DataFrame()),
                bars_ext.get(ticker, pd.DataFrame()),
                vix_df, earnings, rs_ranks,
                buffer_days=buf,
            )
            all_rth_sigs.extend(rth_sigs)
            all_ext_sigs.extend(ext_sigs)

        # RTH
        trades_rth = run_m7_backtest(all_rth_sigs, daily_data, bars_rth, vix_df)
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

        # EXT
        trades_ext = run_m7_backtest(all_ext_sigs, daily_data, bars_ext, vix_df)
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

        # Save per-filter CSV (RTH and EXT combined)
        combined = trades_rth + trades_ext
        if combined:
            csv_path = os.path.join(OUT_DIR, f'm7_trades_filter_{buf}.csv')
            pd.DataFrame(combined).to_csv(csv_path, index=False)
            print(f'\n  Saved {len(combined)} trades -> {csv_path}')

    # ── Regression check (filter=6 vs known baseline) ─────────────────────────
    print(f'\n{SEP}')
    print('REGRESSION CHECK  (filter=6 vs known baseline, tolerance ±5%)')
    print(SEP)
    regression_ok = _check_regression(results_rth, results_ext)
    if not regression_ok:
        print(
            '\nHALT: filter=6 result diverges >5% from known baseline.\n'
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
        return v if (isinstance(v, float) and not math.isnan(v) and not math.isinf(v)) else -1.0

    best_rth = max(results_rth, key=_oos_pf)
    best_ext = max(results_ext, key=_oos_pf)

    for r_rth, r_ext in zip(results_rth, results_ext):
        tag_rth = ' <-- max OOS PF' if r_rth['buffer_days'] == best_rth['buffer_days'] else ''
        tag_ext = ' <-- max OOS PF' if r_ext['buffer_days'] == best_ext['buffer_days'] else ''
        print(
            f'  {r_rth["buffer_days"]:>12}  '
            f'{_fmt(r_rth["oos"]["PF"], ".2f"):>14}{tag_rth}  '
            f'{_fmt(r_ext["oos"]["PF"], ".2f"):>14}{tag_ext}'
        )

    print(
        f'\n  RTH mode: filter_days={best_rth["buffer_days"]} '
        f'maximizes OOS PF ({_fmt(best_rth["oos"]["PF"], ".2f")})'
    )
    print(
        f'  EXT mode: filter_days={best_ext["buffer_days"]} '
        f'maximizes OOS PF ({_fmt(best_ext["oos"]["PF"], ".2f")})'
    )

    # ── Write markdown report ─────────────────────────────────────────────────
    md = _build_sweep_md(results_rth, results_ext, n0_rth, n0_ext, best_rth, best_ext)
    md_path = os.path.join(OUT_DIR, 'm7_sweep.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f'\nMarkdown report -> {md_path}')
    print('Done.')
