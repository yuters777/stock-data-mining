#!/usr/bin/env python3
"""
ANT-1: Earnings Recovery Ratio Backtest (Daily Data)
Tests whether post-earnings gap-down recovery ratio predicts multi-day drift.
"""
import os
import sys
import json
import warnings
import time
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings('ignore')

# ============================================================
# CONFIGURATION
# ============================================================
OUTPUT_DIR = Path('backtest_output/ant1')
DAILY_CACHE = OUTPUT_DIR / 'daily_cache'
EARNINGS_CACHE = OUTPUT_DIR / 'earnings_cache'

TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA",
    "TSLA", "AMD", "SMCI", "PLTR", "AVGO", "ARM", "TSM",
    "MU", "INTC", "COST",
    "COIN", "MSTR", "MARA",
    "C", "GS", "V", "BA", "JPM",
    "BABA", "JD", "BIDU",
]

START_DATE = "2016-01-01"
END_DATE = "2026-04-05"
GAP_THRESHOLD = -5.0   # minimum gap-down %
FORWARD_DAYS = 10

for d in [OUTPUT_DIR, DAILY_CACHE, EARNINGS_CACHE]:
    d.mkdir(parents=True, exist_ok=True)


# ============================================================
# PART 1: DATA LOADING (from local files)
# ============================================================
DAILY_DIR = Path('backtester/data/daily')
EARNINGS_CSV = Path('backtester/data/fmp_earnings.csv')

# BMO/AMC classification (from fmp_earnings_fetcher.py)
AMC_TICKERS = {
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD",
    "COIN", "ARM", "SMCI", "PLTR", "MSTR", "MARA", "AVGO", "TSM",
    "V", "MU", "INTC", "COST",
}
BMO_TICKERS = {"JD", "BIDU", "BABA", "C", "GS", "BA", "JPM"}


def load_daily_data():
    """Load daily OHLCV for all tickers from local backtester/data/daily/ CSVs."""
    all_data = {}
    for ticker in TICKERS:
        fpath = DAILY_DIR / f"{ticker}_daily.csv"
        if not fpath.exists():
            print(f"    WARNING: No daily data file for {ticker}")
            continue
        try:
            df = pd.read_csv(fpath, header=[0, 1], index_col=0, parse_dates=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            # Ensure standard column names
            for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                if col not in df.columns:
                    print(f"    WARNING: {ticker} missing column {col}")
                    continue
            df = df.sort_index()
            all_data[ticker] = df
        except Exception as e:
            print(f"    ERROR loading {ticker}: {e}")
    return all_data


def load_earnings_data():
    """Load earnings dates from local FMP earnings CSV."""
    if not EARNINGS_CSV.exists():
        print("    ERROR: No FMP earnings CSV found")
        return pd.DataFrame()
    df = pd.read_csv(EARNINGS_CSV)
    df['earnings_date'] = pd.to_datetime(df['earnings_date'])
    return df


# ============================================================
# PART 2: BUILD EARNINGS EVENTS
# ============================================================
def get_day1_date(earnings_date, timing, daily_df):
    """
    Determine Day 1 based on BMO/AMC timing.
    BMO: Day 1 = earnings_date itself (gap appears at open)
    AMC: Day 1 = next trading day after earnings_date
    """
    idx = daily_df.index
    ed = pd.Timestamp(earnings_date).normalize()

    if timing == 'BMO':
        # Day 1 is earnings_date itself
        if ed in idx:
            return ed
        # Find nearest trading day on/after
        mask = idx >= ed
        if mask.any():
            return idx[mask][0]
        return None
    else:
        # AMC: Day 1 = next trading day
        mask = idx > ed
        if mask.any():
            return idx[mask][0]
        return None


def build_events(all_data, earnings_df):
    """Build the master events DataFrame with all computed metrics."""
    events = []
    for _, earn_row in earnings_df.iterrows():
        ticker = earn_row['ticker']
        if ticker not in all_data:
            continue

        daily = all_data[ticker]
        idx = daily.index
        earn_date = earn_row['earnings_date']
        timing = earn_row.get('time_of_day', 'Unknown')

        # Determine timing if unknown
        if timing not in ('BMO', 'AMC'):
            timing = 'AMC' if ticker in AMC_TICKERS else ('BMO' if ticker in BMO_TICKERS else 'AMC')

        day1_date = get_day1_date(earn_date, timing, daily)
        if day1_date is None:
            continue

        if day1_date not in idx:
            continue
        day1_pos = idx.get_loc(day1_date)
        if day1_pos < 1 or day1_pos + FORWARD_DAYS >= len(idx):
            continue

        prior_close = daily.iloc[day1_pos - 1]['Close']
        day1_open = daily.iloc[day1_pos]['Open']
        day1_high = daily.iloc[day1_pos]['High']
        day1_low = daily.iloc[day1_pos]['Low']
        day1_close = daily.iloc[day1_pos]['Close']

        if prior_close <= 0 or day1_open <= 0:
            continue

        # Gap calculation
        gap_pct = (day1_open - prior_close) / prior_close * 100

        # Recovery ratio
        gap_size_dollars = abs(prior_close - day1_open)
        recovery_ratio = np.nan
        if gap_size_dollars > 0:
            recovery_ratio = (day1_close - day1_low) / gap_size_dollars

        # ANT-style recovery
        day1_decline = prior_close - day1_low
        ant_recovery = np.nan
        if day1_decline > 0:
            ant_recovery = (day1_close - day1_low) / day1_decline

        # Forward drifts
        drifts = {}
        for fd in [1, 2, 3, 5, 7, 10]:
            if day1_pos + fd < len(idx):
                fwd_close = daily.iloc[day1_pos + fd]['Close']
                drifts[f'drift_{fd}d'] = (fwd_close - day1_close) / day1_close * 100
            else:
                drifts[f'drift_{fd}d'] = np.nan

        # Day of minimum (closes from Day1 through Day1+10)
        min_close = day1_close
        day_of_min = 0
        trajectory = [0.0]  # Day 0 = 0% (day1_close)
        for fd in range(1, FORWARD_DAYS + 1):
            if day1_pos + fd < len(idx):
                fwd_close = daily.iloc[day1_pos + fd]['Close']
                pct = (fwd_close - day1_close) / day1_close * 100
                trajectory.append(pct)
                if fwd_close < min_close:
                    min_close = fwd_close
                    day_of_min = fd

        # EPS surprise from FMP data
        eps_surprise = np.nan
        eps_surp_raw = earn_row.get('eps_surprise_pct', np.nan)
        if pd.notna(eps_surp_raw):
            try:
                eps_surprise = float(eps_surp_raw)
            except (ValueError, TypeError):
                pass

        event = {
            'ticker': ticker,
            'earnings_date': pd.Timestamp(earn_date).normalize(),
            'day1_date': day1_date,
            'timing': timing,
            'prior_close': prior_close,
            'day1_open': day1_open,
            'day1_high': day1_high,
            'day1_low': day1_low,
            'day1_close': day1_close,
            'gap_pct': gap_pct,
            'gap_size_dollars': gap_size_dollars,
            'recovery_ratio': recovery_ratio,
            'ant_recovery': ant_recovery,
            'day1_green': day1_close > day1_open,
            'day_of_min': day_of_min,
            'eps_surprise_pct': eps_surprise,
        }
        event.update(drifts)
        event['trajectory'] = json.dumps(trajectory)
        events.append(event)

    df = pd.DataFrame(events)
    if not df.empty:
        df = df.drop_duplicates(subset=['ticker', 'day1_date'], keep='first')
        df = df.sort_values(['ticker', 'day1_date']).reset_index(drop=True)
    return df


# ============================================================
# PART 3: TESTS
# ============================================================

def n_flag(n):
    if n < 10:
        return ' **ANECDOTAL**'
    elif n < 20:
        return ' *LOW N*'
    return ''


def test0_universe_stats(events):
    """TEST 0: Universe Statistics"""
    print('=' * 70)
    print('TEST 0: UNIVERSE STATISTICS')
    print('=' * 70)
    total = len(events)
    print(f'Total earnings events: {total}')
    print()

    # Gap-down thresholds
    for thresh in [-5, -7, -10, -15]:
        n = (events['gap_pct'] <= thresh).sum()
        print(f'  Gap <= {thresh}%: {n} ({n/total*100:.1f}%)')
    # Gap-up for symmetry
    n_up = (events['gap_pct'] >= 5).sum()
    print(f'  Gap >= +5%: {n_up} ({n_up/total*100:.1f}%)')
    print()

    # Gap size distribution
    bins = [-100, -20, -15, -10, -7, -5, -3, 0, 3, 5, 7, 10, 15, 20, 100]
    labels = [f'{bins[i]} to {bins[i+1]}%' for i in range(len(bins)-1)]
    events['gap_bucket'] = pd.cut(events['gap_pct'], bins=bins, labels=labels)
    print('Gap Size Distribution:')
    dist = events['gap_bucket'].value_counts().sort_index()
    for bucket, count in dist.items():
        if count > 0:
            print(f'  {bucket}: {count}')
    print()

    # N per ticker
    print('Events per Ticker:')
    ticker_counts = events['ticker'].value_counts().sort_values(ascending=False)
    for t, c in ticker_counts.items():
        print(f'  {t}: {c}')
    print()

    # N per year
    events['year'] = events['day1_date'].dt.year
    print('Events per Year:')
    year_counts = events['year'].value_counts().sort_index()
    for y, c in year_counts.items():
        print(f'  {y}: {c}')
    print()

    # BMO vs AMC
    print('Timing Split:')
    timing_counts = events['timing'].value_counts()
    for t, c in timing_counts.items():
        print(f'  {t}: {c} ({c/total*100:.1f}%)')
    print()

    return {
        'total_events': int(total),
        'gap_down_5pct': int((events['gap_pct'] <= -5).sum()),
        'gap_down_10pct': int((events['gap_pct'] <= -10).sum()),
        'gap_up_5pct': int(n_up),
    }


def test1_recovery_vs_drift(events):
    """TEST 1: Recovery Ratio vs Multi-Day Drift"""
    print('=' * 70)
    print('TEST 1: RECOVERY RATIO vs MULTI-DAY DRIFT')
    print('=' * 70)

    gd = events[events['gap_pct'] <= GAP_THRESHOLD].copy()
    print(f'Gap-down events (gap <= {GAP_THRESHOLD}%): N={len(gd)}')
    print()

    # Define buckets
    bucket_defs = [
        ('A (<0.20)', lambda x: x < 0.20),
        ('B (0.20-0.30)', lambda x: (x >= 0.20) & (x < 0.30)),
        ('C (0.30-0.40)', lambda x: (x >= 0.30) & (x < 0.40)),
        ('D (0.40-0.60)', lambda x: (x >= 0.40) & (x < 0.60)),
        ('E (>0.60)', lambda x: x >= 0.60),
    ]

    print(f'{"Bucket":<16} {"N":>5} {"Drift 1d":>10} {"Drift 3d":>10} {"Drift 5d":>10} {"Drift 10d":>10} {"Med 5d":>10} {"WR 5d":>8} {"Std 5d":>8}')
    print('-' * 90)

    bucket_results = {}
    for name, cond in bucket_defs:
        mask = cond(gd['recovery_ratio'])
        subset = gd[mask]
        n = len(subset)
        if n == 0:
            print(f'{name:<16} {n:>5}   (no data)')
            continue

        d1 = subset['drift_1d'].mean()
        d3 = subset['drift_3d'].mean()
        d5 = subset['drift_5d'].mean()
        d10 = subset['drift_10d'].mean()
        med5 = subset['drift_5d'].median()
        wr5 = (subset['drift_5d'] > 0).mean() * 100
        std5 = subset['drift_5d'].std()

        flag = n_flag(n)
        print(f'{name:<16} {n:>5} {d1:>+10.2f}% {d3:>+9.2f}% {d5:>+9.2f}% {d10:>+9.2f}% {med5:>+9.2f}% {wr5:>7.1f}% {std5:>7.2f}%{flag}')

        bucket_results[name] = {
            'n': int(n), 'drift_1d': round(d1, 3), 'drift_3d': round(d3, 3),
            'drift_5d': round(d5, 3), 'drift_10d': round(d10, 3),
            'median_5d': round(med5, 3), 'wr_5d': round(wr5, 1), 'std_5d': round(std5, 3)
        }

    print()

    # Spearman correlation
    valid = gd.dropna(subset=['recovery_ratio', 'drift_5d'])
    if len(valid) >= 5:
        rho, pval = stats.spearmanr(valid['recovery_ratio'], valid['drift_5d'])
        print(f'Spearman Correlation (recovery_ratio vs drift_5d):')
        print(f'  rho = {rho:.4f}, p-value = {pval:.6f}')
        sig = 'YES' if pval < 0.05 else 'NO'
        print(f'  Significant at p<0.05: {sig}')
    else:
        rho, pval = np.nan, np.nan
        print('  Insufficient data for Spearman correlation')
    print()

    return {'buckets': bucket_results, 'spearman_rho': round(rho, 4) if not np.isnan(rho) else None,
            'spearman_p': round(pval, 6) if not np.isnan(pval) else None}


def test2_threshold_sweep(events):
    """TEST 2: Optimal Zombie Threshold Sweep"""
    print('=' * 70)
    print('TEST 2: OPTIMAL ZOMBIE THRESHOLD SWEEP')
    print('=' * 70)

    gd = events[events['gap_pct'] <= GAP_THRESHOLD].dropna(subset=['recovery_ratio', 'drift_5d']).copy()
    print(f'Events for sweep: N={len(gd)}')
    print()

    thresholds = np.arange(0.15, 0.66, 0.05)
    print(f'{"Thresh":>7} {"N_LONG":>7} {"N_SHORT":>8} {"Mean_L":>9} {"Mean_S":>9} {"WR_L":>7} {"WR_S":>7} {"Sep":>9}')
    print('-' * 72)

    sweep_results = []
    best_sep = -999
    best_thresh = 0

    for t in thresholds:
        long_grp = gd[gd['recovery_ratio'] >= t]
        short_grp = gd[gd['recovery_ratio'] < t]
        n_l, n_s = len(long_grp), len(short_grp)

        if n_l == 0 or n_s == 0:
            continue

        mean_l = long_grp['drift_5d'].mean()
        mean_s = short_grp['drift_5d'].mean()
        wr_l = (long_grp['drift_5d'] > 0).mean() * 100
        wr_s = (short_grp['drift_5d'] > 0).mean() * 100
        sep = mean_l - mean_s

        print(f'{t:>7.2f} {n_l:>7} {n_s:>8} {mean_l:>+8.2f}% {mean_s:>+8.2f}% {wr_l:>6.1f}% {wr_s:>6.1f}% {sep:>+8.2f}%')

        sweep_results.append({'threshold': round(t, 2), 'n_long': int(n_l), 'n_short': int(n_s),
                               'mean_long': round(mean_l, 3), 'mean_short': round(mean_s, 3),
                               'wr_long': round(wr_l, 1), 'wr_short': round(wr_s, 1),
                               'separation': round(sep, 3)})

        if sep > best_sep:
            best_sep = sep
            best_thresh = t

    print()
    print(f'Optimal threshold: {best_thresh:.2f} (separation = {best_sep:+.2f}%)')
    print(f'ANT claims 0.35-0.40. Data says: {best_thresh:.2f}')
    print()

    return {'sweep': sweep_results, 'optimal_threshold': round(best_thresh, 2),
            'optimal_separation': round(best_sep, 3)}


def test3_gap_size_interaction(events):
    """TEST 3: Gap Size Interaction"""
    print('=' * 70)
    print('TEST 3: GAP SIZE INTERACTION')
    print('=' * 70)

    gd = events[events['gap_pct'] <= GAP_THRESHOLD].dropna(subset=['recovery_ratio', 'drift_5d']).copy()

    gap_buckets = [
        ('-5% to -10%', lambda x: (x <= -5) & (x > -10)),
        ('-10% to -15%', lambda x: (x <= -10) & (x > -15)),
        ('< -15%', lambda x: x <= -15),
    ]
    rec_buckets = [
        ('Rec < 0.30', lambda x: x < 0.30),
        ('Rec 0.30-0.50', lambda x: (x >= 0.30) & (x < 0.50)),
        ('Rec > 0.50', lambda x: x >= 0.50),
    ]

    print(f'{"":>18}', end='')
    for gn, _ in gap_buckets:
        print(f'{gn:>22}', end='')
    print()
    print('-' * 84)

    results = {}
    for rn, rc in rec_buckets:
        print(f'{rn:<18}', end='')
        for gn, gc in gap_buckets:
            mask = gc(gd['gap_pct']) & rc(gd['recovery_ratio'])
            subset = gd[mask]
            n = len(subset)
            if n > 0:
                d5 = subset['drift_5d'].mean()
                flag = n_flag(n)
                print(f'{d5:>+7.2f}% (N={n:>3}){flag:>5}', end='')
                results[f'{rn}|{gn}'] = {'drift_5d': round(d5, 3), 'n': int(n)}
            else:
                print(f'{"N/A":>22}', end='')
        print()
    print()

    return results


def test4_day_of_minimum(events):
    """TEST 4: Day-of-Minimum Distribution"""
    print('=' * 70)
    print('TEST 4: DAY-OF-MINIMUM DISTRIBUTION')
    print('=' * 70)

    gd = events[events['gap_pct'] <= GAP_THRESHOLD].copy()

    # Low recovery events
    low_rec = gd[gd['recovery_ratio'] < 0.30]
    high_rec = gd[gd['recovery_ratio'] >= 0.40]

    print(f'Low recovery (<0.30) events: N={len(low_rec)}')
    if len(low_rec) > 0:
        dom_dist = low_rec['day_of_min'].value_counts().sort_index()
        print('  Day-of-Minimum Distribution:')
        for day, count in dom_dist.items():
            pct = count / len(low_rec) * 100
            bar = '#' * int(pct / 2)
            print(f'    Day {day:>2}: {count:>4} ({pct:>5.1f}%) {bar}')
        mode_day = low_rec['day_of_min'].mode().iloc[0] if len(low_rec) > 0 else 'N/A'
        mean_day = low_rec['day_of_min'].mean()
        print(f'  Mode: Day {mode_day}, Mean: Day {mean_day:.1f}')
    print()

    print(f'High recovery (>=0.40) events: N={len(high_rec)}')
    if len(high_rec) > 0:
        dom_dist_h = high_rec['day_of_min'].value_counts().sort_index()
        print('  Day-of-Minimum Distribution:')
        for day, count in dom_dist_h.items():
            pct = count / len(high_rec) * 100
            bar = '#' * int(pct / 2)
            print(f'    Day {day:>2}: {count:>4} ({pct:>5.1f}%) {bar}')
        mode_day_h = high_rec['day_of_min'].mode().iloc[0] if len(high_rec) > 0 else 'N/A'
        mean_day_h = high_rec['day_of_min'].mean()
        print(f'  Mode: Day {mode_day_h}, Mean: Day {mean_day_h:.1f}')
    print()

    # Average trajectories by recovery bucket
    print('Average Trajectories (cumulative % from Day 1 close):')
    rec_groups = [
        ('Rec < 0.20', gd[gd['recovery_ratio'] < 0.20]),
        ('Rec 0.20-0.40', gd[(gd['recovery_ratio'] >= 0.20) & (gd['recovery_ratio'] < 0.40)]),
        ('Rec >= 0.40', gd[gd['recovery_ratio'] >= 0.40]),
    ]

    trajectories = {}
    for name, group in rec_groups:
        if len(group) == 0:
            continue
        traj_list = [json.loads(t) for t in group['trajectory']]
        max_len = max(len(t) for t in traj_list)
        padded = [t + [np.nan] * (max_len - len(t)) for t in traj_list]
        avg_traj = np.nanmean(padded, axis=0).tolist()
        trajectories[name] = avg_traj
        traj_str = ', '.join([f'{v:+.2f}%' for v in avg_traj[:11]])
        print(f'  {name} (N={len(group)}): [{traj_str}]')
    print()

    result = {
        'low_rec_n': int(len(low_rec)),
        'low_rec_mode_day': int(low_rec['day_of_min'].mode().iloc[0]) if len(low_rec) > 0 else None,
        'low_rec_mean_day': round(float(low_rec['day_of_min'].mean()), 2) if len(low_rec) > 0 else None,
        'high_rec_n': int(len(high_rec)),
        'high_rec_mode_day': int(high_rec['day_of_min'].mode().iloc[0]) if len(high_rec) > 0 else None,
        'trajectories': {k: [round(v, 3) for v in vals[:11]] for k, vals in trajectories.items()},
    }
    return result


def test5_eps_surprise(events):
    """TEST 5: EPS Surprise Interaction"""
    print('=' * 70)
    print('TEST 5: EPS SURPRISE INTERACTION')
    print('=' * 70)

    gd = events[events['gap_pct'] <= GAP_THRESHOLD].dropna(subset=['recovery_ratio', 'drift_5d']).copy()
    gd['abs_surprise'] = gd['eps_surprise_pct'].abs()

    has_surprise = gd.dropna(subset=['abs_surprise'])
    print(f'Events with EPS surprise data: {len(has_surprise)} / {len(gd)}')
    if len(has_surprise) < 10:
        print('  Insufficient data for EPS surprise analysis.')
        print()
        return {'n_with_surprise': int(len(has_surprise))}

    surp_buckets = [
        ('|Surp| < 5%', lambda x: x < 5),
        ('|Surp| 5-15%', lambda x: (x >= 5) & (x < 15)),
        ('|Surp| > 15%', lambda x: x >= 15),
    ]
    rec_buckets = [
        ('Rec < 0.30', lambda x: x < 0.30),
        ('Rec 0.30-0.50', lambda x: (x >= 0.30) & (x < 0.50)),
        ('Rec > 0.50', lambda x: x >= 0.50),
    ]

    print(f'{"":>18}', end='')
    for sn, _ in surp_buckets:
        print(f'{sn:>22}', end='')
    print()
    print('-' * 84)

    results = {}
    for rn, rc in rec_buckets:
        print(f'{rn:<18}', end='')
        for sn, sc in surp_buckets:
            mask = sc(has_surprise['abs_surprise']) & rc(has_surprise['recovery_ratio'])
            subset = has_surprise[mask]
            n = len(subset)
            if n > 0:
                d5 = subset['drift_5d'].mean()
                flag = n_flag(n)
                print(f'{d5:>+7.2f}% (N={n:>3}){flag:>5}', end='')
                results[f'{rn}|{sn}'] = {'drift_5d': round(d5, 3), 'n': int(n)}
            else:
                print(f'{"N/A":>22}', end='')
        print()
    print()

    return results


def test6_zombie_backtest(events, all_data):
    """TEST 6: Zombie LONG and Anti-Zombie SHORT Backtests"""
    print('=' * 70)
    print('TEST 6: ZOMBIE LONG & ANTI-ZOMBIE SHORT BACKTESTS')
    print('=' * 70)

    results = {}

    # Test multiple zombie thresholds
    for zombie_thresh in [0.30, 0.35, 0.40]:
        print(f'\n--- ZOMBIE LONG (recovery >= {zombie_thresh}, gap <= -10%) ---')
        gd = events[(events['gap_pct'] <= -10) &
                     (events['recovery_ratio'] >= zombie_thresh) &
                     (events['day1_green'] == True)].copy()

        trades = []
        for _, ev in gd.iterrows():
            ticker = ev['ticker']
            if ticker not in all_data:
                continue
            daily = all_data[ticker]
            idx = daily.index
            day1_date = ev['day1_date']
            if day1_date not in idx:
                continue
            day1_pos = idx.get_loc(day1_date)

            entry_price = ev['day1_close']
            prior_close = ev['prior_close']
            day1_low = ev['day1_low']
            stop_price = day1_low

            # Simulate trade
            exit_price = None
            exit_reason = None
            holding_days = 0

            for fd in range(1, 11):
                if day1_pos + fd >= len(idx):
                    break
                holding_days = fd
                bar = daily.iloc[day1_pos + fd]
                close = bar['Close']
                low = bar['Low']

                # Check stop first (intraday)
                if low < stop_price:
                    exit_price = stop_price
                    exit_reason = 'stop'
                    break
                # Check target: full gap fill
                if close >= prior_close:
                    exit_price = prior_close
                    exit_reason = 'gap_fill'
                    break
                # Check +5% target
                if close >= entry_price * 1.05:
                    exit_price = entry_price * 1.05
                    exit_reason = 'target_5pct'
                    break

            if exit_price is None and holding_days > 0:
                exit_price = daily.iloc[day1_pos + holding_days]['Close']
                exit_reason = 'max_hold'

            if exit_price is not None:
                ret = (exit_price - entry_price) / entry_price * 100
                trades.append({
                    'ticker': ticker, 'entry_date': str(day1_date.date()),
                    'entry': entry_price, 'exit': exit_price,
                    'return_pct': ret, 'reason': exit_reason,
                    'holding_days': holding_days
                })

        if trades:
            tdf = pd.DataFrame(trades)
            n_trades = len(tdf)
            mean_ret = tdf['return_pct'].mean()
            wr = (tdf['return_pct'] > 0).mean() * 100
            wins = tdf[tdf['return_pct'] > 0]['return_pct'].sum()
            losses = abs(tdf[tdf['return_pct'] <= 0]['return_pct'].sum())
            pf = wins / losses if losses > 0 else float('inf')
            max_dd = tdf['return_pct'].min()
            avg_hold = tdf['holding_days'].mean()

            print(f'  N trades: {n_trades}{n_flag(n_trades)}')
            print(f'  Mean return: {mean_ret:+.2f}%')
            print(f'  Win rate: {wr:.1f}%')
            print(f'  Profit factor: {pf:.2f}')
            print(f'  Max single loss: {max_dd:+.2f}%')
            print(f'  Avg holding days: {avg_hold:.1f}')
            print(f'  Exit reasons: {tdf["reason"].value_counts().to_dict()}')

            results[f'zombie_long_{zombie_thresh}'] = {
                'n': int(n_trades), 'mean_return': round(mean_ret, 3),
                'win_rate': round(wr, 1), 'profit_factor': round(pf, 2),
                'max_loss': round(max_dd, 3), 'avg_hold': round(avg_hold, 1),
                'exit_reasons': tdf['reason'].value_counts().to_dict()
            }
        else:
            print('  No trades generated.')
            results[f'zombie_long_{zombie_thresh}'] = {'n': 0}

    # Anti-Zombie SHORT
    print(f'\n--- ANTI-ZOMBIE SHORT (recovery < 0.20, gap <= -10%) ---')
    gd_short = events[(events['gap_pct'] <= -10) &
                       (events['recovery_ratio'] < 0.20)].copy()

    short_trades = []
    for _, ev in gd_short.iterrows():
        ticker = ev['ticker']
        if ticker not in all_data:
            continue
        daily = all_data[ticker]
        idx = daily.index
        day1_date = ev['day1_date']
        if day1_date not in idx:
            continue
        day1_pos = idx.get_loc(day1_date)

        entry_price = ev['day1_close']
        day1_low = ev['day1_low']
        prior_close = ev['prior_close']
        target_price = day1_low - 0.03 * prior_close

        exit_price = None
        exit_reason = None
        holding_days = 0

        for fd in range(1, 6):  # max 5 trading days
            if day1_pos + fd >= len(idx):
                break
            holding_days = fd
            bar = daily.iloc[day1_pos + fd]
            close = bar['Close']

            # Short target: close below target
            if close <= target_price:
                exit_price = target_price
                exit_reason = 'target'
                break

        if exit_price is None and holding_days > 0:
            exit_price = daily.iloc[day1_pos + holding_days]['Close']
            exit_reason = 'max_hold'

        if exit_price is not None:
            # SHORT: profit = entry - exit
            ret = (entry_price - exit_price) / entry_price * 100
            short_trades.append({
                'ticker': ticker, 'entry_date': str(day1_date.date()),
                'entry': entry_price, 'exit': exit_price,
                'return_pct': ret, 'reason': exit_reason,
                'holding_days': holding_days
            })

    if short_trades:
        tdf = pd.DataFrame(short_trades)
        n_trades = len(tdf)
        mean_ret = tdf['return_pct'].mean()
        wr = (tdf['return_pct'] > 0).mean() * 100
        wins = tdf[tdf['return_pct'] > 0]['return_pct'].sum()
        losses = abs(tdf[tdf['return_pct'] <= 0]['return_pct'].sum())
        pf = wins / losses if losses > 0 else float('inf')
        max_dd = tdf['return_pct'].min()
        avg_hold = tdf['holding_days'].mean()

        print(f'  N trades: {n_trades}{n_flag(n_trades)}')
        print(f'  Mean return: {mean_ret:+.2f}%')
        print(f'  Win rate: {wr:.1f}%')
        print(f'  Profit factor: {pf:.2f}')
        print(f'  Max single loss: {max_dd:+.2f}%')
        print(f'  Avg holding days: {avg_hold:.1f}')
        print(f'  Exit reasons: {tdf["reason"].value_counts().to_dict()}')

        results['anti_zombie_short'] = {
            'n': int(n_trades), 'mean_return': round(mean_ret, 3),
            'win_rate': round(wr, 1), 'profit_factor': round(pf, 2),
            'max_loss': round(max_dd, 3), 'avg_hold': round(avg_hold, 1),
            'exit_reasons': tdf['reason'].value_counts().to_dict()
        }
    else:
        print('  No short trades generated.')
        results['anti_zombie_short'] = {'n': 0}

    print()
    return results


# ============================================================
# PART 4: CHARTS
# ============================================================

def make_charts(events):
    """Generate all PNG charts."""
    gd = events[events['gap_pct'] <= GAP_THRESHOLD].dropna(subset=['recovery_ratio', 'drift_5d']).copy()

    # --- Chart 1: Recovery vs Drift Scatter ---
    fig, ax = plt.subplots(figsize=(10, 7))
    colors = np.where(gd['gap_pct'] <= -15, 'red',
             np.where(gd['gap_pct'] <= -10, 'orange', 'steelblue'))
    ax.scatter(gd['recovery_ratio'], gd['drift_5d'], c=colors, alpha=0.5, s=30)
    # Regression line
    valid = gd.dropna(subset=['recovery_ratio', 'drift_5d'])
    if len(valid) > 2:
        z = np.polyfit(valid['recovery_ratio'], valid['drift_5d'], 1)
        p = np.poly1d(z)
        x_line = np.linspace(valid['recovery_ratio'].min(), valid['recovery_ratio'].max(), 100)
        ax.plot(x_line, p(x_line), 'k--', linewidth=2, label=f'Fit: {z[0]:.1f}x + {z[1]:.1f}')
    ax.axhline(0, color='gray', linewidth=0.5)
    ax.axvline(0.35, color='green', linewidth=1, linestyle=':', label='ANT threshold (0.35)')
    ax.set_xlabel('Recovery Ratio')
    ax.set_ylabel('Drift 5d (%)')
    ax.set_title('ANT-1: Recovery Ratio vs 5-Day Drift (Gap-Down Events)')
    ax.legend(loc='upper left')
    # Color legend
    from matplotlib.patches import Patch
    legend_elements = [Patch(facecolor='steelblue', label='Gap -5% to -10%'),
                       Patch(facecolor='orange', label='Gap -10% to -15%'),
                       Patch(facecolor='red', label='Gap < -15%')]
    ax.legend(handles=legend_elements, loc='lower right')
    plt.tight_layout()
    fig.savefig(OUTPUT_DIR / 'ant1_recovery_vs_drift.png', dpi=150)
    plt.close(fig)
    print('  Saved ant1_recovery_vs_drift.png')

    # --- Chart 2: Bucket Drift Bar Chart ---
    bucket_defs = [
        ('A (<0.20)', lambda x: x < 0.20),
        ('B (0.20-0.30)', lambda x: (x >= 0.20) & (x < 0.30)),
        ('C (0.30-0.40)', lambda x: (x >= 0.30) & (x < 0.40)),
        ('D (0.40-0.60)', lambda x: (x >= 0.40) & (x < 0.60)),
        ('E (>0.60)', lambda x: x >= 0.60),
    ]

    bucket_names = []
    drift_data = {p: [] for p in ['1d', '3d', '5d', '10d']}
    for name, cond in bucket_defs:
        subset = gd[cond(gd['recovery_ratio'])]
        if len(subset) > 0:
            bucket_names.append(f'{name}\n(N={len(subset)})')
            drift_data['1d'].append(subset['drift_1d'].mean())
            drift_data['3d'].append(subset['drift_3d'].mean())
            drift_data['5d'].append(subset['drift_5d'].mean())
            drift_data['10d'].append(subset['drift_10d'].mean())

    if bucket_names:
        fig, ax = plt.subplots(figsize=(12, 7))
        x = np.arange(len(bucket_names))
        width = 0.18
        for i, (period, vals) in enumerate(drift_data.items()):
            ax.bar(x + i * width, vals, width, label=f'Drift {period}')
        ax.set_xlabel('Recovery Ratio Bucket')
        ax.set_ylabel('Mean Drift (%)')
        ax.set_title('ANT-1: Mean Forward Drift by Recovery Ratio Bucket')
        ax.set_xticks(x + 1.5 * width)
        ax.set_xticklabels(bucket_names)
        ax.legend()
        ax.axhline(0, color='gray', linewidth=0.5)
        plt.tight_layout()
        fig.savefig(OUTPUT_DIR / 'ant1_bucket_drift.png', dpi=150)
        plt.close(fig)
        print('  Saved ant1_bucket_drift.png')

    # --- Chart 3: Average Trajectory ---
    rec_groups = [
        ('Rec < 0.20', gd[gd['recovery_ratio'] < 0.20]),
        ('Rec 0.20-0.40', gd[(gd['recovery_ratio'] >= 0.20) & (gd['recovery_ratio'] < 0.40)]),
        ('Rec >= 0.40', gd[gd['recovery_ratio'] >= 0.40]),
    ]

    fig, ax = plt.subplots(figsize=(10, 7))
    colors_traj = ['red', 'orange', 'green']
    for (name, group), color in zip(rec_groups, colors_traj):
        if len(group) == 0:
            continue
        traj_list = [json.loads(t) for t in group['trajectory']]
        max_len = min(11, max(len(t) for t in traj_list))
        padded = [t[:max_len] + [np.nan] * (max_len - len(t[:max_len])) for t in traj_list]
        avg_traj = np.nanmean(padded, axis=0)
        ax.plot(range(len(avg_traj)), avg_traj, marker='o', color=color,
                label=f'{name} (N={len(group)})', linewidth=2)

    ax.axhline(0, color='gray', linewidth=0.5)
    ax.set_xlabel('Trading Days After Earnings (0 = Day 1 Close)')
    ax.set_ylabel('Cumulative Return (%)')
    ax.set_title('ANT-1: Average Price Trajectory by Recovery Bucket')
    ax.legend()
    ax.set_xticks(range(11))
    ax.set_xticklabels([f'D{i}' for i in range(11)])
    plt.tight_layout()
    fig.savefig(OUTPUT_DIR / 'ant1_trajectory.png', dpi=150)
    plt.close(fig)
    print('  Saved ant1_trajectory.png')

    # --- Chart 4: Day-of-Minimum Histogram ---
    low_rec = gd[gd['recovery_ratio'] < 0.30]
    if len(low_rec) > 0:
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))

        # Low recovery
        axes[0].hist(low_rec['day_of_min'], bins=range(12), align='left',
                     color='red', alpha=0.7, edgecolor='black')
        axes[0].set_xlabel('Day of Minimum')
        axes[0].set_ylabel('Count')
        axes[0].set_title(f'Day-of-Min: Low Recovery (<0.30, N={len(low_rec)})')
        axes[0].set_xticks(range(11))

        # High recovery
        high_rec = gd[gd['recovery_ratio'] >= 0.40]
        if len(high_rec) > 0:
            axes[1].hist(high_rec['day_of_min'], bins=range(12), align='left',
                         color='green', alpha=0.7, edgecolor='black')
            axes[1].set_xlabel('Day of Minimum')
            axes[1].set_ylabel('Count')
            axes[1].set_title(f'Day-of-Min: High Recovery (>=0.40, N={len(high_rec)})')
            axes[1].set_xticks(range(11))

        plt.tight_layout()
        fig.savefig(OUTPUT_DIR / 'ant1_day_of_min.png', dpi=150)
        plt.close(fig)
        print('  Saved ant1_day_of_min.png')

    # --- Chart 5: Threshold Sweep ---
    thresholds = np.arange(0.15, 0.66, 0.05)
    seps = []
    wr_longs = []
    for t in thresholds:
        long_grp = gd[gd['recovery_ratio'] >= t]
        short_grp = gd[gd['recovery_ratio'] < t]
        if len(long_grp) > 0 and len(short_grp) > 0:
            seps.append(long_grp['drift_5d'].mean() - short_grp['drift_5d'].mean())
            wr_longs.append((long_grp['drift_5d'] > 0).mean() * 100)
        else:
            seps.append(0)
            wr_longs.append(50)

    fig, ax1 = plt.subplots(figsize=(10, 7))
    ax1.plot(thresholds, seps, 'b-o', linewidth=2, label='Separation (L-S drift 5d)')
    ax1.set_xlabel('Recovery Ratio Threshold')
    ax1.set_ylabel('Separation (%)', color='blue')
    ax1.axhline(0, color='gray', linewidth=0.5)

    ax2 = ax1.twinx()
    ax2.plot(thresholds, wr_longs, 'g--s', linewidth=1.5, label='LONG Win Rate 5d')
    ax2.set_ylabel('Win Rate (%)', color='green')
    ax2.axhline(50, color='green', linewidth=0.5, linestyle=':')

    # Mark ANT threshold
    ax1.axvline(0.35, color='red', linewidth=1, linestyle=':', label='ANT threshold')

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
    ax1.set_title('ANT-1: Threshold Sweep — Separation & Win Rate')
    plt.tight_layout()
    fig.savefig(OUTPUT_DIR / 'ant1_threshold_sweep.png', dpi=150)
    plt.close(fig)
    print('  Saved ant1_threshold_sweep.png')


# ============================================================
# MAIN
# ============================================================
def main():
    print('=' * 70)
    print('ANT-1: EARNINGS RECOVERY RATIO BACKTEST')
    print(f'Date: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print(f'Tickers: {len(TICKERS)}')
    print(f'Period: {START_DATE} to {END_DATE}')
    print('=' * 70)
    print()

    # --- LOAD DATA ---
    print('PHASE 1: Loading daily OHLCV data from local files...')
    all_data = load_daily_data()
    print(f'  Loaded {len(all_data)} tickers with daily data')
    for t, df in sorted(all_data.items()):
        print(f'    {t}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})')
    print()

    print('PHASE 2: Loading earnings calendar from FMP data...')
    earnings_df = load_earnings_data()
    n_tickers_earn = earnings_df['ticker'].nunique() if not earnings_df.empty else 0
    print(f'  Loaded {len(earnings_df)} earnings events for {n_tickers_earn} tickers')
    if not earnings_df.empty:
        for t in sorted(earnings_df['ticker'].unique()):
            sub = earnings_df[earnings_df['ticker'] == t]
            print(f'    {t}: {len(sub)} dates ({sub["earnings_date"].min().date()} to {sub["earnings_date"].max().date()})')
    print()

    print('PHASE 3: Building events...')
    events = build_events(all_data, earnings_df)
    print(f'  Total events built: {len(events)}')
    if events.empty:
        print('ERROR: No events built. Check data availability.')
        sys.exit(1)

    # Save events
    events.to_csv(OUTPUT_DIR / 'events.csv', index=False)
    print(f'  Saved events.csv')
    print()

    # --- RUN TESTS ---
    all_results = {}

    print('PHASE 4: Running tests...')
    print()

    all_results['test0'] = test0_universe_stats(events)
    all_results['test1'] = test1_recovery_vs_drift(events)
    all_results['test2'] = test2_threshold_sweep(events)
    all_results['test3'] = test3_gap_size_interaction(events)
    all_results['test4'] = test4_day_of_minimum(events)
    all_results['test5'] = test5_eps_surprise(events)
    all_results['test6'] = test6_zombie_backtest(events, all_data)

    # --- CHARTS ---
    print('PHASE 5: Generating charts...')
    make_charts(events)
    print()

    # --- SAVE SUMMARY ---
    print('PHASE 6: Saving summary...')
    # Add meta info
    all_results['meta'] = {
        'date_run': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'n_tickers': len(all_data),
        'n_earnings_tickers': n_tickers_earn,
        'n_events': int(len(events)),
        'period': f'{START_DATE} to {END_DATE}',
        'gap_threshold': GAP_THRESHOLD,
    }

    with open(OUTPUT_DIR / 'ANT1_summary.json', 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f'  Saved ANT1_summary.json')

    # --- FINAL VERDICT ---
    print()
    print('=' * 70)
    print('VERDICT SUMMARY')
    print('=' * 70)
    t1 = all_results.get('test1', {})
    rho = t1.get('spearman_rho')
    p = t1.get('spearman_p')
    t2 = all_results.get('test2', {})
    opt_thresh = t2.get('optimal_threshold')
    opt_sep = t2.get('optimal_separation')
    t4 = all_results.get('test4', {})
    dom_mode = t4.get('low_rec_mode_day')
    t6 = all_results.get('test6', {})
    zombie_35 = t6.get('zombie_long_0.35', {})

    print(f'Spearman rho: {rho} (p={p})')
    if rho is not None and p is not None:
        if p < 0.05 and rho > 0.15:
            print('  -> Recovery ratio IS a significant predictor of drift direction')
        elif p < 0.10:
            print('  -> Marginal evidence for predictive power')
        else:
            print('  -> No significant predictive power found')

    print(f'Optimal threshold: {opt_thresh} (separation: {opt_sep}%)')
    if opt_thresh is not None:
        if 0.30 <= opt_thresh <= 0.45:
            print('  -> Consistent with ANT claim (0.35-0.40)')
        else:
            print(f'  -> Diverges from ANT claim (0.35-0.40)')

    print(f'Day-of-minimum mode (low recovery): Day {dom_mode}')
    if dom_mode is not None:
        if 3 <= dom_mode <= 5:
            print('  -> Consistent with ANT claim (Day 3-5)')
        elif dom_mode == 0:
            print('  -> Day 1 IS the bottom (contradicts ANT)')
        else:
            print(f'  -> Inconclusive (Day {dom_mode})')

    if zombie_35.get('n', 0) > 0:
        pf = zombie_35.get('profit_factor', 0)
        print(f'Zombie LONG (0.35) PF: {pf}, WR: {zombie_35.get("win_rate")}%, N: {zombie_35.get("n")}')
        if pf >= 1.5 and zombie_35.get('n', 0) >= 20:
            print('  -> Tradeable signal')
        elif pf >= 1.2:
            print('  -> Marginal signal, needs more data')
        else:
            print('  -> Not tradeable')
    else:
        print('Zombie LONG (0.35): No trades')

    print()
    print('Done. All outputs saved to backtest_output/ant1/')


if __name__ == '__main__':
    main()
