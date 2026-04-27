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


# ── Diagnostic helpers (crossed-earnings, per-ticker, decision rule) ──────────

def _annotate_crossed_earnings(trades: list, earnings_dict: dict) -> None:
    """Mutate `trades` in place: add 'crossed_earnings' bool to each trade.

    A trade crosses earnings if any earnings date for the ticker falls in
    [entry_date, exit_date] inclusive (string comparison on ISO YYYY-MM-DD).
    Skipped trades (exit_date is None) get crossed_earnings=False.
    """
    iso_cache: dict = {}
    for t in trades:
        ticker         = t.get('ticker')
        entry_date_str = t.get('entry_date')
        exit_date_str  = t.get('exit_date')
        if not entry_date_str or not exit_date_str:
            t['crossed_earnings'] = False
            continue
        if ticker not in iso_cache:
            iso_cache[ticker] = [
                ed.isoformat() if hasattr(ed, 'isoformat') else str(ed)[:10]
                for ed in earnings_dict.get(ticker, [])
            ]
        crossed = False
        for ed_str in iso_cache[ticker]:
            if entry_date_str <= ed_str <= exit_date_str:
                crossed = True
                break
        t['crossed_earnings'] = crossed


def _crossed_stats(trades: list) -> dict:
    """Stats over the subset of executed trades that crossed earnings.

    Returns {'count': int, 'PF': float | None}; PF is None when count < 5.
    """
    crossed = [t for t in trades
               if t.get('crossed_earnings')
               and t.get('exit_reason') != 'SKIP_MAX_CONCURRENT'
               and pd.notna(t.get('return_pct'))]
    n = len(crossed)
    if n < 5:
        return {'count': n, 'PF': None}
    rets   = np.array([t['return_pct'] for t in crossed], dtype=float)
    wins   = rets[rets > 0]
    losses = rets[rets <= 0]
    pf     = float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float('inf')
    return {'count': n, 'PF': round(pf, 2) if not math.isinf(pf) else float('inf')}


def _per_ticker_stats(trades: list) -> dict:
    """Per-ticker {N, PF} over executed trades."""
    by_ticker: dict = {}
    for t in trades:
        if t.get('exit_reason') == 'SKIP_MAX_CONCURRENT':
            continue
        if not pd.notna(t.get('return_pct')):
            continue
        by_ticker.setdefault(t['ticker'], []).append(t['return_pct'])
    result: dict = {}
    for ticker, rets in by_ticker.items():
        arr    = np.array(rets, dtype=float)
        wins   = arr[arr > 0]
        losses = arr[arr <= 0]
        pf     = float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float('inf')
        result[ticker] = {
            'N':  len(arr),
            'PF': round(pf, 2) if not math.isinf(pf) else float('inf'),
        }
    return result


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
        ' N (IS) | PF (IS) | N (OOS) | PF (OOS) | Blocked vs filter=0 |'
        ' Crossed_count | Crossed_PF |',
        '|-------------|----------|-----------|-----------|'
        '--------|---------|---------|----------|---------------------|'
        '---------------|------------|',
    ]
    for r in results:
        blocked = n0 - r['full']['N'] if (r['buffer_days'] != 0 and n0 > 0) else 0
        blocked_str = '0 (baseline)' if r['buffer_days'] == 0 else str(blocked)
        crossed       = r.get('crossed', {'count': 0, 'PF': None})
        crossed_count = crossed['count']
        crossed_pf    = '—' if crossed['PF'] is None else _fmt(crossed['PF'], '.2f')
        lines.append(
            f'| {r["buffer_days"]}'
            f' | {r["full"]["N"]}'
            f' | {_fmt(r["full"]["PF"], ".2f")}'
            f' | {_fmt(r["full"]["WR"], ".1f")}%'
            f' | {r["is"]["N"]}'
            f' | {_fmt(r["is"]["PF"], ".2f")}'
            f' | {r["oos"]["N"]}'
            f' | {_fmt(r["oos"]["PF"], ".2f")}'
            f' | {blocked_str}'
            f' | {crossed_count}'
            f' | {crossed_pf} |'
        )
    return lines


def _per_ticker_table(trades_f0: list, trades_f6: list) -> list:
    """Build per-ticker breakdown rows comparing filter=0 vs filter=6."""
    s0 = _per_ticker_stats(trades_f0)
    s6 = _per_ticker_stats(trades_f6)

    rows = []
    for ticker in set(s0) | set(s6):
        n0 = s0.get(ticker, {}).get('N', 0)
        n6 = s6.get(ticker, {}).get('N', 0)
        if n0 < 5 and n6 < 5:
            continue
        pf0 = s0.get(ticker, {}).get('PF', float('nan'))
        pf6 = s6.get(ticker, {}).get('PF', float('nan'))

        d_trades = n0 - n6
        if (isinstance(pf0, float) and (math.isnan(pf0) or math.isinf(pf0))) or \
           (isinstance(pf6, float) and (math.isnan(pf6) or math.isinf(pf6))):
            d_pf = float('nan')
        else:
            d_pf = pf0 - pf6

        rows.append({
            'ticker':   ticker,
            'n0':       n0,
            'pf0':      pf0,
            'n6':       n6,
            'pf6':      pf6,
            'd_trades': d_trades,
            'd_pf':     d_pf,
        })

    rows.sort(key=lambda r: -abs(r['d_trades']))

    lines = [
        '| Ticker | N (f=0) | PF (f=0) | N (f=6) | PF (f=6) | Δ trades | Δ PF |',
        '|--------|---------|----------|---------|----------|----------|------|',
    ]
    for r in rows:
        lines.append(
            f'| {r["ticker"]}'
            f' | {r["n0"]}'
            f' | {_fmt(r["pf0"], ".2f")}'
            f' | {r["n6"]}'
            f' | {_fmt(r["pf6"], ".2f")}'
            f' | {r["d_trades"]:+d}'
            f' | {_fmt(r["d_pf"], "+.2f")} |'
        )
    return lines


def _decide_hypothesis(results: list) -> tuple:
    """Decide which pre-registered hypothesis the OOS PF data supports.

    H1 (filter justified): OOS PF(f=6) ≥ 1.15 × OOS PF(f=0) AND OOS max at f=6
    H2 (filter unnecessary): OOS PF(f=0) ≥ 0.95 × OOS PF(f=6) AND OOS max at f=0
    H3 (filter optimum elsewhere): OOS PF maximizes at filter ∉ {0, 6}

    Returns (label, rationale_str).
    """
    def _safe_pf(v):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return float(v)

    by_buf  = {r['buffer_days']: r for r in results}
    pf0_raw = by_buf.get(0, {}).get('oos', {}).get('PF', float('nan'))
    pf6_raw = by_buf.get(6, {}).get('oos', {}).get('PF', float('nan'))
    pf0     = _safe_pf(pf0_raw)
    pf6     = _safe_pf(pf6_raw)

    best     = max(results, key=_oos_pf)
    best_buf = best['buffer_days']
    best_pf  = _safe_pf(best['oos']['PF'])

    if best_buf not in (0, 6):
        return (
            'H3',
            f'OOS PF maximizes at filter={best_buf} '
            f'(PF={_fmt(best["oos"]["PF"], ".2f")}), not at 0 or 6.',
        )

    if pf0 is None or pf6 is None:
        return (
            'INDETERMINATE',
            f'OOS PF unavailable for f=0 or f=6 '
            f'(f=0={_fmt(pf0_raw, ".2f")}, f=6={_fmt(pf6_raw, ".2f")}).',
        )

    if best_buf == 6 and pf6 >= 1.15 * pf0:
        return (
            'H1',
            f'OOS PF(f=6)={pf6:.2f} ≥ 1.15 × OOS PF(f=0)={pf0:.2f} '
            f'(threshold {1.15 * pf0:.2f}); OOS max at f=6.',
        )

    if best_buf == 0 and pf0 >= 0.95 * pf6:
        return (
            'H2',
            f'OOS PF(f=0)={pf0:.2f} ≥ 0.95 × OOS PF(f=6)={pf6:.2f} '
            f'(threshold {0.95 * pf6:.2f}); OOS max at f=0.',
        )

    return (
        'NONE',
        f'No hypothesis cleanly supported '
        f'(OOS PF f=0={pf0:.2f}, f=6={pf6:.2f}, max at f={best_buf} '
        f'PF={_fmt(best_pf, ".2f") if best_pf is not None else "—"}).',
    )


def _oos_pf(r: dict) -> float:
    """Sort key: OOS PF, with nan/inf coerced to -1 so they don't win."""
    v = r['oos']['PF']
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return -1.0
    return float(v)


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
    captured_trades: dict,
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
        '## Per-ticker breakdown: filter=0 vs filter=6 (RTH mode)',
        '',
    ]
    lines += _per_ticker_table(
        captured_trades['rth'].get(0, []),
        captured_trades['rth'].get(6, []),
    )
    lines += [
        '',
        '## Per-ticker breakdown: filter=0 vs filter=6 (EXT mode)',
        '',
    ]
    lines += _per_ticker_table(
        captured_trades['ext'].get(0, []),
        captured_trades['ext'].get(6, []),
    )

    rth_label, rth_rationale = _decide_hypothesis(results_rth)
    ext_label, ext_rationale = _decide_hypothesis(results_ext)
    lines += [
        '',
        '---',
        '',
        '## Decision per pre-registered rule',
        '',
        '- H1 (filter justified): PF(f=6) ≥ 1.15 × PF(f=0) AND OOS confirms',
        '- H2 (filter unnecessary): PF(f=0) ≥ 0.95 × PF(f=6) AND OOS confirms',
        '- H3 (filter optimum elsewhere): PF maximizes at filter ≠ 6',
        '',
        f'- **RTH**: {rth_label} — {rth_rationale}',
        f'- **EXT**: {ext_label} — {ext_rationale}',
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

    # Trades captured for filter=0 and filter=6 (used for per-ticker breakdown)
    captured_trades = {
        'rth': {0: [], 6: []},
        'ext': {0: [], 6: []},
    }

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
        _annotate_crossed_earnings(trades_rth, earnings)
        is_rth, oos_rth = _split_trades(trades_rth)
        rec_rth = {
            'buffer_days': buf,
            'full':    _compute_stats(trades_rth),
            'is':      _compute_stats(is_rth),
            'oos':     _compute_stats(oos_rth),
            'crossed': _crossed_stats(trades_rth),
        }
        results_rth.append(rec_rth)
        if buf == 0:
            n0_rth = rec_rth['full']['N']
        if buf in captured_trades['rth']:
            captured_trades['rth'][buf] = list(trades_rth)
        print(
            f'  RTH  full: N={rec_rth["full"]["N"]}, '
            f'PF={_fmt(rec_rth["full"]["PF"], ".2f")}, '
            f'WR={rec_rth["full"]["WR"]:.1f}%  '
            f'| IS: N={rec_rth["is"]["N"]} PF={_fmt(rec_rth["is"]["PF"], ".2f")}'
            f'  OOS: N={rec_rth["oos"]["N"]} PF={_fmt(rec_rth["oos"]["PF"], ".2f")}'
            f'  | crossed: N={rec_rth["crossed"]["count"]} '
            f'PF={"—" if rec_rth["crossed"]["PF"] is None else _fmt(rec_rth["crossed"]["PF"], ".2f")}'
        )

        # EXT
        trades_ext = run_m7_backtest(all_ext_sigs, daily_data, bars_ext, vix_df)
        _annotate_crossed_earnings(trades_ext, earnings)
        is_ext, oos_ext = _split_trades(trades_ext)
        rec_ext = {
            'buffer_days': buf,
            'full':    _compute_stats(trades_ext),
            'is':      _compute_stats(is_ext),
            'oos':     _compute_stats(oos_ext),
            'crossed': _crossed_stats(trades_ext),
        }
        results_ext.append(rec_ext)
        if buf == 0:
            n0_ext = rec_ext['full']['N']
        if buf in captured_trades['ext']:
            captured_trades['ext'][buf] = list(trades_ext)
        print(
            f'  EXT  full: N={rec_ext["full"]["N"]}, '
            f'PF={_fmt(rec_ext["full"]["PF"], ".2f")}, '
            f'WR={rec_ext["full"]["WR"]:.1f}%  '
            f'| IS: N={rec_ext["is"]["N"]} PF={_fmt(rec_ext["is"]["PF"], ".2f")}'
            f'  OOS: N={rec_ext["oos"]["N"]} PF={_fmt(rec_ext["oos"]["PF"], ".2f")}'
            f'  | crossed: N={rec_ext["crossed"]["count"]} '
            f'PF={"—" if rec_ext["crossed"]["PF"] is None else _fmt(rec_ext["crossed"]["PF"], ".2f")}'
        )

        # Save per-filter CSV (RTH and EXT combined; includes crossed_earnings col)
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
    md = _build_sweep_md(
        results_rth, results_ext,
        n0_rth, n0_ext,
        best_rth, best_ext,
        captured_trades,
    )
    md_path = os.path.join(OUT_DIR, 'm7_sweep.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f'\nMarkdown report -> {md_path}')
    print('Done.')
