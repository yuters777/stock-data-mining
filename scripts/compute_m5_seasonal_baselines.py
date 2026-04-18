#!/usr/bin/env python3
"""Compute M5 seasonal baselines from 5-year CSVs (offline).

Reads per-ticker M5 extended-hours CSVs via load_extended_data() from
backtest_utils_extended, filters to RTH (09:30-16:00 ET exclusive end,
78 bars/day), and emits a JSON artefact containing per-slot percentile
statistics, per-zone daily activity_raw distributions, and QA checks.

Blueprint: Seasonal_Baseline_Methodology_Spec_v1_1.md (v1.1, sections 3,
4, 7, 8, 10.1). This is offline / pure — no DB writes, no network.

Python 3.7 compatible. No walrus, no PEP 604 unions, no f-string self-
documenting expressions.
"""

import argparse
import hashlib
import json
import math
import os
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
_BASE = _SCRIPT_DIR.parent
# Ensure the repo root (so 'scripts.backtest_utils_extended' resolves) and
# the scripts dir (for the legacy bare 'backtest_utils_extended' import)
# are both on sys.path. PEP 420 namespace packages mean no __init__.py is
# required in scripts/.
for _p in (str(_BASE), str(_SCRIPT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.backtest_utils_extended import load_extended_data  # noqa: E402


# ── Universe (Sprint 1: 28 tickers, equity + SPY, per PI v39 / spec §3.1) ──

UNIVERSE_28 = [
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA',
    'TSLA', 'AMD', 'SMCI', 'PLTR', 'AVGO', 'ARM', 'TSM',
    'MU', 'INTC', 'COST',
    'COIN', 'MSTR', 'MARA',
    'C', 'GS', 'V', 'BA', 'JPM',
    'BABA', 'JD', 'BIDU',
    'SPY',
]


# ── Slot / zone configuration ────────────────────────────────────────────

RTH_START_MIN = 9 * 60 + 30       # 09:30 ET (inclusive)
RTH_END_MIN = 16 * 60             # 16:00 ET (exclusive)
SLOT_WIDTH_MIN = 5
SLOTS_PER_DAY = (RTH_END_MIN - RTH_START_MIN) // SLOT_WIDTH_MIN   # 78

# Zones: (name, slot_start_inclusive, slot_end_exclusive)
ZONES = (
    ('Z1', 0, 12),    # 09:30-10:30 Opening
    ('Z2', 12, 30),   # 10:30-12:00 Morning Trend
    ('Z3', 30, 48),   # 12:00-13:30 Dead Zone
    ('Z4', 48, 60),   # 13:30-14:30 Afternoon Setup
    ('Z5', 60, 78),   # 14:30-16:00 Power Hour
)
ZONE_NAMES = [z[0] for z in ZONES]

# Quality thresholds (spec §3.2)
MIN_TRADING_DAYS = 450
MIN_SLOT_SAMPLE = 200
EXPECTED_TRADING_DAYS_RANGE = (498, 505)

# QA check thresholds (spec §8.1)
QA_MIN_TICKERS_ACCEPTED = 26
QA_SAMPLE_UNIFORMITY_RATIO = 1.5
QA_U_SHAPE_RATIO = 1.25
QA_U_SHAPE_MIN_TICKERS = 24
QA_ZONE_SAMPLE_RANGE = (450, 510)

PERCENTILES = (10, 30, 50, 70, 90)


# ── Helpers ──────────────────────────────────────────────────────────────

def slot_zone(slot_id):
    for name, start, end in ZONES:
        if start <= slot_id < end:
            return name
    return None


def slot_et_time(slot_id):
    total_min = RTH_START_MIN + slot_id * SLOT_WIDTH_MIN
    return '{:02d}:{:02d}'.format(total_min // 60, total_min % 60)


def parse_train_window(s):
    parts = s.split('-')
    if len(parts) != 2 or not all(p.isdigit() and len(p) == 4 for p in parts):
        raise argparse.ArgumentTypeError(
            'train-window must look like YYYY-YYYY (e.g. 2023-2024)'
        )
    y1, y2 = int(parts[0]), int(parts[1])
    if y2 < y1:
        raise argparse.ArgumentTypeError(
            'train-window end year must be >= start year'
        )
    start = pd.Timestamp(year=y1, month=1, day=1)
    end = pd.Timestamp(year=y2, month=12, day=31)
    return s, start, end


def compute_source_hash(ticker_paths):
    """SHA256 of concatenated CSV bytes in alphabetical ticker order."""
    h = hashlib.sha256()
    for ticker in sorted(ticker_paths):
        path = ticker_paths[ticker]
        if path is None or not os.path.exists(path):
            continue
        with open(path, 'rb') as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
    return 'sha256:' + h.hexdigest()


def resolve_ticker_path(ticker, data_dir='Fetched_Data'):
    """Canonical path for a ticker's M5 extended CSV (may not exist)."""
    base = data_dir
    if not os.path.isabs(base):
        base = os.path.join(str(_BASE), base)
    return os.path.join(base, '{}_m5_extended.csv'.format(ticker))


# ── Pipeline primitives ──────────────────────────────────────────────────

def prepare_ticker_frame(df, start_date, end_date):
    """Filter to RTH + train window, drop incomplete days, add slot_id /
    zone / bar metrics. Returns None if frame is empty after filtering.

    Expected input columns (from load_extended_data):
        date, open, high, low, close, volume, date_only, time_str,
        hour, minute
    """
    if df is None or df.empty:
        return None

    required = ['date', 'open', 'high', 'low', 'close',
                'date_only', 'hour', 'minute']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError('Missing required columns: {}'.format(missing))

    work = df.copy()
    for col in ('open', 'high', 'low', 'close'):
        work[col] = pd.to_numeric(work[col], errors='coerce')
    work = work.dropna(
        subset=['date', 'open', 'high', 'low', 'close',
                'date_only', 'hour', 'minute']
    )
    if work.empty:
        return None

    # RTH mask — operator-confirmed explicit form.
    rth_mask = (
        ((work['hour'] == 9) & (work['minute'] >= 30))
        | ((work['hour'] >= 10) & (work['hour'] < 16))
    )
    work = work.loc[rth_mask].copy()
    if work.empty:
        return None

    # Trading-date filter on the ready-made date_only column.
    start_d = start_date.date()
    end_d = end_date.date()
    work['trading_date'] = work['date_only']
    work = work.loc[
        (work['trading_date'] >= start_d)
        & (work['trading_date'] <= end_d)
    ].copy()
    if work.empty:
        return None

    # Drop incomplete trading days (!= 78 RTH bars).
    day_counts = work.groupby('trading_date').size()
    complete_days = day_counts[day_counts == SLOTS_PER_DAY].index
    work = work.loc[work['trading_date'].isin(complete_days)].copy()
    if work.empty:
        return None

    work = work.sort_values(['trading_date', 'date']).reset_index(drop=True)

    # Slot formula — operator-confirmed: 09:30 → 0, 15:55 → 77.
    work['slot_id'] = (
        ((work['hour'] - 9) * 60 + work['minute'] - 30) // SLOT_WIDTH_MIN
    ).astype(int)
    work['zone'] = work['slot_id'].map(slot_zone)

    open_safe = work['open'].replace(0, np.nan)
    work['bar_range'] = (work['high'] - work['low']) / open_safe
    work['bar_abs_return'] = (work['close'] - work['open']).abs() / open_safe
    work = work.dropna(subset=['bar_range', 'bar_abs_return'])

    return work


def compute_per_slot_stats(work):
    """Return OrderedDict keyed by str(slot_id) in 0..77 order."""
    out = OrderedDict()
    # Pre-group once for speed.
    grouped = work.groupby('slot_id', sort=True)
    for slot_id in range(SLOTS_PER_DAY):
        key = str(slot_id)
        if slot_id not in grouped.groups:
            out[key] = {
                'et_time': slot_et_time(slot_id),
                'zone': slot_zone(slot_id),
                'sample_size': 0,
            }
            for p in PERCENTILES:
                out[key]['p{}_range'.format(p)] = None
                out[key]['p{}_abs_return'.format(p)] = None
            continue

        g = grouped.get_group(slot_id)
        rng = g['bar_range'].to_numpy(dtype=float)
        absret = g['bar_abs_return'].to_numpy(dtype=float)
        entry = OrderedDict()
        entry['et_time'] = slot_et_time(slot_id)
        entry['zone'] = slot_zone(slot_id)
        for p in PERCENTILES:
            entry['p{}_range'.format(p)] = float(np.percentile(rng, p))
        for p in PERCENTILES:
            entry['p{}_abs_return'.format(p)] = float(np.percentile(absret, p))
        entry['sample_size'] = int(len(g))
        out[key] = entry
    return out


def compute_per_zone_distribution(work):
    """For each zone, list of daily activity_raw values (sorted asc)
    plus summary stats.
    """
    out = OrderedDict()
    # Pre-index by zone for quick slicing.
    zone_bars = {name: work[work['zone'] == name] for name in ZONE_NAMES}

    for name, start, end in ZONES:
        expected = end - start
        bars = zone_bars[name]
        values = []
        if not bars.empty:
            for _, day_bars in bars.groupby('trading_date', sort=True):
                if len(day_bars) != expected:
                    continue
                day_bars = day_bars.sort_values('date')
                first_open = float(day_bars.iloc[0]['open'])
                if first_open == 0 or math.isnan(first_open):
                    continue
                day_high = float(day_bars['high'].max())
                day_low = float(day_bars['low'].min())
                zone_range = (day_high - day_low) / first_open
                zone_avg_abs = float(day_bars['bar_abs_return'].mean())
                product = zone_range * zone_avg_abs
                if product < 0 or math.isnan(product):
                    continue
                activity_raw = math.sqrt(product)
                values.append(activity_raw)

        values.sort()
        if values:
            arr = np.array(values, dtype=float)
            entry = OrderedDict()
            entry['sorted_values'] = [float(v) for v in values]
            entry['sample_size'] = int(len(values))
            entry['min_value'] = float(arr.min())
            entry['max_value'] = float(arr.max())
            entry['mean_value'] = float(arr.mean())
            entry['std_value'] = float(arr.std(ddof=0))
        else:
            entry = OrderedDict()
            entry['sorted_values'] = []
            entry['sample_size'] = 0
            entry['min_value'] = None
            entry['max_value'] = None
            entry['mean_value'] = None
            entry['std_value'] = None
        out[name] = entry
    return out


def process_ticker(ticker, start_date, end_date, data_dir, verbose):
    """Return (status_dict, per_slot, per_zone).

    status_dict is one of:
      {'accepted': True, 'ticker': T, 'trading_days': N}
      {'accepted': False, 'ticker': T, 'reason': '...'}
    """
    try:
        df = load_extended_data(ticker, data_dir=data_dir)
    except FileNotFoundError as exc:
        return (
            {'accepted': False, 'ticker': ticker,
             'reason': 'file_not_found: {}'.format(exc)},
            None, None,
        )
    except Exception as exc:
        return (
            {'accepted': False, 'ticker': ticker,
             'reason': 'load_failed: {}'.format(exc)},
            None, None,
        )

    work = prepare_ticker_frame(df, start_date, end_date)
    if work is None or work.empty:
        return (
            {'accepted': False, 'ticker': ticker,
             'reason': 'insufficient_days: 0'},
            None, None,
        )

    trading_days_count = work['trading_date'].nunique()
    if trading_days_count < MIN_TRADING_DAYS:
        return (
            {'accepted': False, 'ticker': ticker,
             'reason': 'insufficient_days: {}'.format(trading_days_count)},
            None, None,
        )

    per_slot = compute_per_slot_stats(work)

    # Slot-sample quality gate.
    for slot_id in range(SLOTS_PER_DAY):
        n = per_slot[str(slot_id)]['sample_size']
        if n < MIN_SLOT_SAMPLE:
            return (
                {'accepted': False, 'ticker': ticker,
                 'reason': 'insufficient_slot_sample: slot={}, N={}'.format(
                     slot_id, n)},
                None, None,
            )

    per_zone = compute_per_zone_distribution(work)

    if verbose:
        print('  [{}] days={} slots p50 median={:.5f}'.format(
            ticker, trading_days_count,
            float(np.median([per_slot[str(i)]['p50_range']
                             for i in range(SLOTS_PER_DAY)]))
        ))

    return (
        {'accepted': True, 'ticker': ticker,
         'trading_days': int(trading_days_count)},
        per_slot, per_zone,
    )


# ── QA checks (spec §8.1) ────────────────────────────────────────────────

def qa_check1_tickers_accepted(accepted):
    return {
        'passed': len(accepted) >= QA_MIN_TICKERS_ACCEPTED,
        'value': len(accepted),
        'threshold': QA_MIN_TICKERS_ACCEPTED,
    }


def qa_check2_sample_uniformity(per_slot_stats):
    """min(slot_samples) >= 200 AND max/min < 1.5 for each ticker."""
    details = OrderedDict()
    passed = True
    for ticker in sorted(per_slot_stats):
        samples = [per_slot_stats[ticker][str(i)]['sample_size']
                   for i in range(SLOTS_PER_DAY)]
        mn = min(samples) if samples else 0
        mx = max(samples) if samples else 0
        ratio = (mx / mn) if mn > 0 else float('inf')
        ok = (mn >= MIN_SLOT_SAMPLE) and (ratio < QA_SAMPLE_UNIFORMITY_RATIO)
        details[ticker] = {
            'min_sample': int(mn),
            'max_sample': int(mx),
            'ratio': float(ratio) if ratio != float('inf') else None,
            'passed': bool(ok),
        }
        passed = passed and ok
    return {'passed': bool(passed), 'details': details}


def qa_check3_u_shape_phase0(per_slot_stats):
    """U-shape: mean p50_range over outer session (slots 0-11 + 60-77)
    divided by mean p50_range over dead zone (slots 30-47) >= 1.25 for
    at least 24 tickers.
    """
    per_ticker = OrderedDict()
    count_ge = 0
    for ticker in sorted(per_slot_stats):
        slots = per_slot_stats[ticker]
        outer = []
        for i in list(range(0, 12)) + list(range(60, 78)):
            v = slots[str(i)].get('p50_range')
            if v is not None:
                outer.append(v)
        dead = []
        for i in range(30, 48):
            v = slots[str(i)].get('p50_range')
            if v is not None:
                dead.append(v)
        if not outer or not dead:
            per_ticker[ticker] = None
            continue
        dead_mean = float(np.mean(dead))
        if dead_mean <= 0:
            per_ticker[ticker] = None
            continue
        ratio = float(np.mean(outer)) / dead_mean
        per_ticker[ticker] = ratio
        if ratio >= QA_U_SHAPE_RATIO:
            count_ge += 1
    return {
        'passed': count_ge >= QA_U_SHAPE_MIN_TICKERS,
        'tickers_with_ratio_ge_1_25': count_ge,
        'threshold': QA_U_SHAPE_MIN_TICKERS,
        'per_ticker_ratios': per_ticker,
    }


def qa_check4_distribution_sanity(per_zone_distributions):
    """Sample size in [450, 510], min>0, max<1.0, std>0 per ticker/zone."""
    details = OrderedDict()
    passed = True
    sample_lo, sample_hi = QA_ZONE_SAMPLE_RANGE
    for ticker in sorted(per_zone_distributions):
        zones = per_zone_distributions[ticker]
        ticker_detail = OrderedDict()
        ticker_ok = True
        for name in ZONE_NAMES:
            z = zones.get(name, {})
            n = z.get('sample_size') or 0
            mn = z.get('min_value')
            mx = z.get('max_value')
            sd = z.get('std_value')
            violations = []
            if not (sample_lo <= n <= sample_hi):
                violations.append('sample_size_out_of_range:{}'.format(n))
            if mn is None or mn <= 0:
                violations.append('min_value_not_positive')
            if mx is None or mx >= 1.0:
                violations.append('max_value_ge_1')
            if sd is None or sd <= 0:
                violations.append('std_value_not_positive')
            ok = len(violations) == 0
            ticker_detail[name] = {'passed': bool(ok), 'violations': violations}
            ticker_ok = ticker_ok and ok
        details[ticker] = ticker_detail
        passed = passed and ticker_ok
    return {'passed': bool(passed), 'details': details}


def qa_check5_per_slot_monotonicity(per_slot_stats):
    """p10 < p30 < p50 < p70 < p90 for range and abs_return on every slot."""
    violations = []
    for ticker in sorted(per_slot_stats):
        for slot_id in range(SLOTS_PER_DAY):
            entry = per_slot_stats[ticker][str(slot_id)]
            for metric in ('range', 'abs_return'):
                vals = [entry.get('p{}_{}'.format(p, metric))
                        for p in PERCENTILES]
                if any(v is None for v in vals):
                    continue
                strict = all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))
                if not strict:
                    violations.append({
                        'ticker': ticker,
                        'slot_id': slot_id,
                        'metric': metric,
                        'values': [float(v) for v in vals],
                    })
    return {'passed': len(violations) == 0, 'violations': violations}


# ── Main ─────────────────────────────────────────────────────────────────

def build_output(train_window_str, start_date, end_date,
                 accepted, rejected, per_slot_stats, per_zone_distributions,
                 qa_checks, source_hash):
    out = OrderedDict()
    out['train_window'] = train_window_str
    out['computed_at'] = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    out['universe_size'] = len(UNIVERSE_28)
    out['tickers_accepted'] = sorted(accepted)
    out['tickers_rejected'] = sorted(rejected, key=lambda r: r['ticker'])
    out['per_slot_stats'] = OrderedDict(
        (t, per_slot_stats[t]) for t in sorted(per_slot_stats)
    )
    out['per_zone_distributions'] = OrderedDict(
        (t, per_zone_distributions[t]) for t in sorted(per_zone_distributions)
    )
    out['qa_checks'] = qa_checks
    out['metadata'] = OrderedDict([
        ('train_days_start', start_date.strftime('%Y-%m-%d')),
        ('train_days_end', end_date.strftime('%Y-%m-%d')),
        ('expected_trading_days_range', list(EXPECTED_TRADING_DAYS_RANGE)),
        ('python_version', '{}.{}.{}'.format(*sys.version_info[:3])),
        ('pandas_version', pd.__version__),
        ('source_hash', source_hash),
    ])
    return out


def run_pipeline(train_window_str, start_date, end_date,
                 tickers=None, data_dir='Fetched_Data', verbose=False):
    if tickers is None:
        tickers = list(UNIVERSE_28)

    accepted = []
    rejected = []
    per_slot_stats = OrderedDict()
    per_zone_distributions = OrderedDict()
    ticker_paths = {}

    for ticker in tickers:
        ticker_paths[ticker] = resolve_ticker_path(ticker, data_dir)
        status, per_slot, per_zone = process_ticker(
            ticker, start_date, end_date, data_dir, verbose
        )
        if status['accepted']:
            accepted.append(ticker)
            per_slot_stats[ticker] = per_slot
            per_zone_distributions[ticker] = per_zone
            print('ACCEPTED {} (trading_days={})'.format(
                ticker, status['trading_days']))
        else:
            rejected.append({'ticker': ticker, 'reason': status['reason']})
            print('REJECTED {} ({})'.format(ticker, status['reason']))

    qa_checks = OrderedDict()
    qa_checks['check1_tickers_accepted'] = qa_check1_tickers_accepted(accepted)
    qa_checks['check2_sample_uniformity'] = qa_check2_sample_uniformity(
        per_slot_stats)
    qa_checks['check3_u_shape_phase0'] = qa_check3_u_shape_phase0(
        per_slot_stats)
    qa_checks['check4_distribution_sanity'] = qa_check4_distribution_sanity(
        per_zone_distributions)
    qa_checks['check5_per_slot_monotonicity'] = qa_check5_per_slot_monotonicity(
        per_slot_stats)

    source_hash = compute_source_hash(ticker_paths)

    return build_output(
        train_window_str, start_date, end_date,
        accepted, rejected, per_slot_stats, per_zone_distributions,
        qa_checks, source_hash,
    )


def dump_json(obj, path):
    with open(path, 'w') as f:
        json.dump(obj, f, indent=2, sort_keys=False)


def print_summary(payload):
    qa = payload['qa_checks']
    print('')
    print('──────── QA Summary ────────')
    print('Accepted: {} / {} (check1 passed={}, threshold>={})'.format(
        len(payload['tickers_accepted']),
        payload['universe_size'],
        qa['check1_tickers_accepted']['passed'],
        qa['check1_tickers_accepted']['threshold'],
    ))
    print('Sample uniformity: passed={}'.format(
        qa['check2_sample_uniformity']['passed']))
    print('U-shape (phase 0): passed={} ({} of {} tickers have ratio>=1.25)'.format(
        qa['check3_u_shape_phase0']['passed'],
        qa['check3_u_shape_phase0']['tickers_with_ratio_ge_1_25'],
        len(payload['tickers_accepted']),
    ))
    print('Distribution sanity: passed={}'.format(
        qa['check4_distribution_sanity']['passed']))
    print('Per-slot monotonicity: passed={} (violations={})'.format(
        qa['check5_per_slot_monotonicity']['passed'],
        len(qa['check5_per_slot_monotonicity']['violations']),
    ))
    if payload['tickers_rejected']:
        print('')
        print('Rejected tickers:')
        for r in payload['tickers_rejected']:
            print('  {} — {}'.format(r['ticker'], r['reason']))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Compute M5 seasonal baselines from 5yr CSVs.'
    )
    parser.add_argument('--train-window', required=True, type=parse_train_window,
                        help='Training window, e.g. 2023-2024')
    parser.add_argument('--output', default=None,
                        help='Output JSON path (default: baselines_<window>.json)')
    parser.add_argument('--data-dir', default='Fetched_Data',
                        help='Directory containing {TICKER}_m5_extended.csv')
    parser.add_argument('--verbose', action='store_true',
                        help='Per-ticker progress prints')
    parser.add_argument('--tickers', default=None,
                        help='Comma-separated ticker list (default: UNIVERSE_28)')
    args = parser.parse_args(argv)

    window_str, start_date, end_date = args.train_window
    output = args.output or 'baselines_{}.json'.format(window_str)

    tickers = None
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(',') if t.strip()]

    payload = run_pipeline(
        window_str, start_date, end_date,
        tickers=tickers, data_dir=args.data_dir, verbose=args.verbose,
    )

    dump_json(payload, output)
    size = os.path.getsize(output)
    print('')
    print('Wrote {} ({} bytes)'.format(output, size))
    print_summary(payload)
    return 0


if __name__ == '__main__':
    sys.exit(main())
