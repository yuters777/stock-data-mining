"""
Walk-Forward Validation Engine — Phase 2.3

Grid search over a reduced parameter space (32 combinations) across 6
rolling windows (3-month train, 1-month test). Total: 192 backtests.

For each window the best IS config is selected and applied to OOS.
Reports progress after each window completes.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import json
import itertools
import numpy as np
import pandas as pd
from copy import deepcopy
from dataclasses import dataclass

from backtester.backtester import Backtester, BacktestConfig
from backtester.core.level_detector import LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngineConfig
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
TICKERS = ['TSLA', 'AMZN', 'GOOGL', 'META', 'MSFT', 'NVDA']
OVERALL_START = '2025-02-10'
OVERALL_END = '2026-01-31'
TRAIN_MONTHS = 3
TEST_MONTHS = 1
MAX_WINDOWS = 6  # Limit to 6 windows → 32 × 6 = 192 IS backtests

# Baseline defaults (carried from Phase 2.2)
BASELINE = dict(
    fractal_depth=5,
    tolerance_cents=0.05,
    tolerance_pct=0.001,
    atr_period=5,
    min_level_score=5,
    cross_count_invalidate=5,
    cross_count_window=30,
    tail_ratio_min=0.15,
    lp2_engulfing_required=True,
    clp_min_bars=3,
    clp_max_bars=7,
    atr_block_threshold=0.25,
    atr_entry_threshold=0.70,
    max_stop_atr_pct=0.10,
    min_rr=3.0,
    capital=100000.0,
    risk_pct=0.003,
    tier_mode='2tier_trail',
    t1_pct=0.30,
    trail_factor=0.7,
    trail_activation_r=0.0,
    tier_min_rr=1.5,
)


# ═══════════════════════════════════════════════════════════════════════════
# REDUCED PARAMETER GRID — 32 combinations
#
# 4 key parameters, each with 2 values = 2^4 * 2 = 32
# Two "structural" levels crossed with four "signal" parameters.
# ═══════════════════════════════════════════════════════════════════════════

PARAM_GRID = {
    'atr_entry_threshold': [0.60, 0.80],
    'max_stop_atr_pct':    [0.10, 0.20],
    'min_rr':              [2.0, 3.0],
    'tail_ratio_min':      [0.10, 0.20],
    'fractal_depth':       [5, 10],
}

def build_grid():
    """Generate all parameter combinations from PARAM_GRID."""
    keys = sorted(PARAM_GRID.keys())
    values = [PARAM_GRID[k] for k in keys]
    combos = []
    for vals in itertools.product(*values):
        combo = dict(zip(keys, vals))
        combos.append(combo)
    return combos


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def build_config(name: str, overrides: dict = None) -> BacktestConfig:
    """Build BacktestConfig from baseline + overrides."""
    p = {**BASELINE, **(overrides or {})}
    return BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=p['fractal_depth'],
            tolerance_cents=p['tolerance_cents'],
            tolerance_pct=p['tolerance_pct'],
            atr_period=p['atr_period'],
            min_level_score=p['min_level_score'],
            cross_count_invalidate=p['cross_count_invalidate'],
            cross_count_window=p['cross_count_window'],
        ),
        pattern_config=PatternEngineConfig(
            tail_ratio_min=p['tail_ratio_min'],
            lp2_engulfing_required=p['lp2_engulfing_required'],
            clp_min_bars=p['clp_min_bars'],
            clp_max_bars=p['clp_max_bars'],
        ),
        filter_config=FilterChainConfig(
            atr_block_threshold=p['atr_block_threshold'],
            atr_entry_threshold=p['atr_entry_threshold'],
            enable_volume_filter=True,
            enable_time_filter=True,
            enable_squeeze_filter=True,
        ),
        risk_config=RiskManagerConfig(
            min_rr=p['min_rr'],
            max_stop_atr_pct=p['max_stop_atr_pct'],
            capital=p['capital'],
            risk_pct=p['risk_pct'],
        ),
        trade_config=TradeManagerConfig(),
        tier_config={
            'mode': p['tier_mode'],
            't1_pct': p['t1_pct'],
            'trail_factor': p['trail_factor'],
            'trail_activation_r': p['trail_activation_r'],
            'min_rr': p['tier_min_rr'],
        },
        direction_filter=None,
        name=name,
    )


def load_all_data() -> dict:
    """Load M5 data for all tickers. Returns {ticker: DataFrame}."""
    data = {}
    for ticker in TICKERS:
        path = os.path.join(DATA_DIR, f'{ticker}_data.csv')
        if not os.path.exists(path):
            print(f"  WARNING: {path} not found, skipping {ticker}")
            continue
        df = pd.read_csv(path)
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        df = df.sort_values('Datetime').reset_index(drop=True)
        data[ticker] = df
    return data


def run_backtest(config: BacktestConfig, ticker_data: dict,
                 start_date: str, end_date: str) -> dict:
    """Run backtest across all tickers for a date range. Returns metrics dict."""
    all_trades = []
    total_pnl = 0.0

    for ticker, m5_df in ticker_data.items():
        bt = Backtester(config)
        result = bt.run(m5_df, start_date=start_date, end_date=end_date)
        all_trades.extend(result.trades)
        total_pnl += result.performance.get('total_pnl', 0.0)

    n = len(all_trades)
    if n == 0:
        return {'trades': 0, 'win_rate': 0.0, 'profit_factor': 0.0,
                'avg_r': 0.0, 'total_pnl': 0.0, 'sharpe': 0.0}

    winners = [t for t in all_trades if t.pnl > 0]
    losers = [t for t in all_trades if t.pnl <= 0]
    gross_profit = sum(t.pnl for t in winners)
    gross_loss = abs(sum(t.pnl for t in losers))
    pf = gross_profit / gross_loss if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0.0)

    # Simple Sharpe approximation from daily P&L
    daily_pnl = {}
    for t in all_trades:
        day = str(t.exit_time.date()) if t.exit_time else 'unknown'
        daily_pnl[day] = daily_pnl.get(day, 0.0) + t.pnl
    daily_values = list(daily_pnl.values())
    if len(daily_values) > 1 and np.std(daily_values) > 0:
        sharpe = np.mean(daily_values) / np.std(daily_values) * np.sqrt(252)
    else:
        sharpe = 0.0

    return {
        'trades': n,
        'win_rate': len(winners) / n,
        'profit_factor': pf,
        'avg_r': np.mean([t.pnl_r for t in all_trades]),
        'total_pnl': total_pnl,
        'sharpe': sharpe,
    }


def generate_windows(overall_start: str, overall_end: str,
                     train_months: int, test_months: int) -> list:
    """Generate rolling walk-forward windows."""
    start = pd.Timestamp(overall_start)
    end = pd.Timestamp(overall_end)
    windows = []
    current = start

    while True:
        train_end = current + pd.DateOffset(months=train_months)
        test_end = train_end + pd.DateOffset(months=test_months)
        if test_end > end:
            break
        windows.append({
            'train_start': current.strftime('%Y-%m-%d'),
            'train_end': train_end.strftime('%Y-%m-%d'),
            'test_start': train_end.strftime('%Y-%m-%d'),
            'test_end': test_end.strftime('%Y-%m-%d'),
        })
        current += pd.DateOffset(months=test_months)

    return windows


# ═══════════════════════════════════════════════════════════════════════════
# SCORING — IS selection criteria
# ═══════════════════════════════════════════════════════════════════════════

def score_is(metrics: dict) -> float:
    """Score an IS result for grid selection.
    Primary: profit factor (must have >= 5 trades for significance).
    Secondary: total P&L.
    """
    if metrics['trades'] < 5:
        return -9999.0
    pf = metrics['profit_factor']
    if pf == float('inf'):
        pf = 10.0  # Cap for sorting
    return pf * 100 + metrics['total_pnl'] / 100


# ═══════════════════════════════════════════════════════════════════════════
# MAIN ENGINE
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class WindowResult:
    window_idx: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    best_params: dict
    is_metrics: dict
    oos_metrics: dict
    all_is_results: list  # [(params, metrics), ...]
    elapsed_s: float


def run_walk_forward():
    """Main walk-forward validation engine."""
    print("=" * 90)
    print("  WALK-FORWARD VALIDATION ENGINE — Phase 2.3")
    print("=" * 90)

    # Build grid
    grid = build_grid()
    print(f"\n  Parameter grid: {len(grid)} combinations")
    for k, v in sorted(PARAM_GRID.items()):
        print(f"    {k}: {v}")

    # Generate windows
    windows = generate_windows(OVERALL_START, OVERALL_END, TRAIN_MONTHS, TEST_MONTHS)
    if MAX_WINDOWS and len(windows) > MAX_WINDOWS:
        windows = windows[:MAX_WINDOWS]
    print(f"\n  Walk-forward windows: {len(windows)}")
    for i, w in enumerate(windows):
        print(f"    W{i+1}: Train {w['train_start']}→{w['train_end']}, "
              f"Test {w['test_start']}→{w['test_end']}")

    total_backtests = len(grid) * len(windows) * 2  # IS + OOS for best
    print(f"\n  Total backtests: {len(grid)} grid × {len(windows)} windows = "
          f"{len(grid) * len(windows)} IS + {len(windows)} OOS = "
          f"{len(grid) * len(windows) + len(windows)} backtests")
    print(f"  Tickers: {', '.join(TICKERS)}")

    # Load data once
    print(f"\n  Loading data...")
    ticker_data = load_all_data()
    print(f"  Loaded {sum(len(df) for df in ticker_data.values())} bars "
          f"across {len(ticker_data)} tickers")

    # Run windows
    window_results = []
    total_start = time.time()

    for wi, window in enumerate(windows):
        window_start = time.time()
        print(f"\n{'━' * 90}")
        print(f"  WINDOW {wi+1}/{len(windows)}: "
              f"Train {window['train_start']}→{window['train_end']} | "
              f"Test {window['test_start']}→{window['test_end']}")
        print(f"{'━' * 90}")

        # Phase 1: Run all grid combos on IS (training) period
        is_results = []
        for gi, params in enumerate(grid):
            combo_name = f"W{wi+1}_G{gi+1}"
            config = build_config(combo_name, params)
            metrics = run_backtest(config, ticker_data,
                                   window['train_start'], window['train_end'])
            is_results.append((params, metrics))

            # Progress dots
            if (gi + 1) % 8 == 0:
                print(f"    IS grid: {gi+1}/{len(grid)} combos done "
                      f"({(gi+1)/len(grid)*100:.0f}%)")

        # Phase 2: Select best IS config
        scored = [(score_is(m), p, m) for p, m in is_results]
        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best_params, best_is_metrics = scored[0]

        print(f"\n  Best IS config (score={best_score:.1f}):")
        for k, v in sorted(best_params.items()):
            baseline_v = BASELINE.get(k, '?')
            marker = " ← CHANGED" if v != baseline_v else ""
            print(f"    {k}: {v}{marker}")
        print(f"  IS: {best_is_metrics['trades']} trades, "
              f"PF={best_is_metrics['profit_factor']:.2f}, "
              f"WR={best_is_metrics['win_rate']*100:.1f}%, "
              f"P&L=${best_is_metrics['total_pnl']:.2f}")

        # Phase 3: Run best config on OOS (test) period
        oos_config = build_config(f"W{wi+1}_OOS", best_params)
        oos_metrics = run_backtest(oos_config, ticker_data,
                                   window['test_start'], window['test_end'])

        elapsed = time.time() - window_start

        print(f"  OOS: {oos_metrics['trades']} trades, "
              f"PF={oos_metrics['profit_factor']:.2f}, "
              f"WR={oos_metrics['win_rate']*100:.1f}%, "
              f"P&L=${oos_metrics['total_pnl']:.2f}, "
              f"Sharpe={oos_metrics['sharpe']:.2f}")
        print(f"  Window elapsed: {elapsed:.1f}s")

        wr = WindowResult(
            window_idx=wi + 1,
            train_start=window['train_start'],
            train_end=window['train_end'],
            test_start=window['test_start'],
            test_end=window['test_end'],
            best_params=best_params,
            is_metrics=best_is_metrics,
            oos_metrics=oos_metrics,
            all_is_results=[(p, m) for p, m in is_results],
            elapsed_s=elapsed,
        )
        window_results.append(wr)

        # Cumulative progress
        total_elapsed = time.time() - total_start
        completed = wi + 1
        remaining = len(windows) - completed
        eta = (total_elapsed / completed) * remaining if completed > 0 else 0
        print(f"\n  Progress: {completed}/{len(windows)} windows done | "
              f"Elapsed: {total_elapsed:.0f}s | ETA: {eta:.0f}s")

    # ═══════════════════════════════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════════════════════════════
    total_elapsed = time.time() - total_start
    print_summary(window_results, total_elapsed)
    save_report(window_results, total_elapsed)

    return window_results


def print_summary(window_results: list, total_elapsed: float):
    """Print walk-forward summary report."""
    print(f"\n\n{'=' * 90}")
    print(f"  WALK-FORWARD VALIDATION SUMMARY")
    print(f"{'=' * 90}")

    # Window-by-window table
    print(f"\n  {'Win':>4} {'Train Period':>25} {'Test Period':>25} "
          f"{'IS Tr':>5} {'IS PF':>6} {'OOS Tr':>6} {'OOS PF':>7} "
          f"{'OOS WR':>7} {'OOS P&L':>10} {'OOS Sh':>7}")
    print(f"  {'─' * 106}")

    oos_pnls = []
    oos_pfs = []
    oos_sharpes = []
    oos_trades = []
    positive_windows = 0

    for wr in window_results:
        ism = wr.is_metrics
        oom = wr.oos_metrics
        oos_pnls.append(oom['total_pnl'])
        pf = oom['profit_factor']
        if pf != float('inf'):
            oos_pfs.append(pf)
        oos_sharpes.append(oom['sharpe'])
        oos_trades.append(oom['trades'])
        if oom['total_pnl'] > 0:
            positive_windows += 1

        pf_str = f"{pf:.2f}" if pf != float('inf') else "inf"
        is_pf_str = f"{ism['profit_factor']:.2f}" if ism['profit_factor'] != float('inf') else "inf"

        print(f"  W{wr.window_idx:>2}  {wr.train_start}→{wr.train_end}  "
              f"{wr.test_start}→{wr.test_end}  "
              f"{ism['trades']:>5} {is_pf_str:>6}  "
              f"{oom['trades']:>5} {pf_str:>7} "
              f"{oom['win_rate']*100:>6.1f}% "
              f"${oom['total_pnl']:>9.2f} "
              f"{oom['sharpe']:>7.2f}")

    print(f"  {'─' * 106}")

    # Aggregate stats
    total_oos_pnl = sum(oos_pnls)
    mean_oos_pf = np.mean(oos_pfs) if oos_pfs else 0
    mean_oos_sharpe = np.mean(oos_sharpes)
    worst_sharpe = min(oos_sharpes) if oos_sharpes else 0
    total_oos_trades = sum(oos_trades)

    print(f"\n  Aggregate OOS Metrics:")
    print(f"    Total P&L:          ${total_oos_pnl:,.2f}")
    print(f"    Total OOS trades:   {total_oos_trades}")
    print(f"    Mean OOS PF:        {mean_oos_pf:.2f}")
    print(f"    Mean OOS Sharpe:    {mean_oos_sharpe:.2f}")
    print(f"    Worst OOS Sharpe:   {worst_sharpe:.2f}")
    print(f"    Positive windows:   {positive_windows}/{len(window_results)} "
          f"({positive_windows/len(window_results)*100:.0f}%)")
    print(f"    Total elapsed:      {total_elapsed:.0f}s "
          f"({total_elapsed/60:.1f}min)")

    # Parameter stability analysis
    print(f"\n  Parameter Stability Across Windows:")
    all_params = [wr.best_params for wr in window_results]
    for key in sorted(PARAM_GRID.keys()):
        values = [p[key] for p in all_params]
        unique = set(values)
        stability = f"STABLE ({values[0]})" if len(unique) == 1 else f"VARIES: {values}"
        print(f"    {key:>25}: {stability}")

    # Verdict
    print(f"\n  Verdict:")
    if positive_windows >= len(window_results) * 0.5 and total_oos_pnl > 0:
        if mean_oos_pf > 1.5:
            print(f"    ✓ ROBUST — Positive in {positive_windows}/{len(window_results)} "
                  f"windows, mean PF={mean_oos_pf:.2f}")
        else:
            print(f"    ~ MARGINAL — Positive P&L but mean PF={mean_oos_pf:.2f} < 1.5")
    else:
        print(f"    ✗ FRAGILE — Only {positive_windows}/{len(window_results)} positive, "
              f"total P&L=${total_oos_pnl:,.2f}")


def save_report(window_results: list, total_elapsed: float):
    """Save detailed JSON report."""
    results_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
    os.makedirs(results_dir, exist_ok=True)
    report_path = os.path.join(results_dir, 'walkforward_phase23.json')

    report = {
        'phase': '2.3',
        'description': 'Walk-forward validation with reduced parameter grid',
        'grid_size': len(build_grid()),
        'n_windows': len(window_results),
        'tickers': TICKERS,
        'train_months': TRAIN_MONTHS,
        'test_months': TEST_MONTHS,
        'overall_start': OVERALL_START,
        'overall_end': OVERALL_END,
        'param_grid': {k: [str(v) for v in vals] for k, vals in PARAM_GRID.items()},
        'baseline': BASELINE,
        'total_elapsed_s': total_elapsed,
        'windows': [],
    }

    for wr in window_results:
        # Serialize params/metrics (convert any numpy types)
        def clean(d):
            out = {}
            for k, v in d.items():
                if isinstance(v, (np.integer,)):
                    out[k] = int(v)
                elif isinstance(v, (np.floating,)):
                    out[k] = float(v)
                elif v == float('inf'):
                    out[k] = 'inf'
                else:
                    out[k] = v
            return out

        report['windows'].append({
            'window': wr.window_idx,
            'train_start': wr.train_start,
            'train_end': wr.train_end,
            'test_start': wr.test_start,
            'test_end': wr.test_end,
            'best_params': clean(wr.best_params),
            'is_metrics': clean(wr.is_metrics),
            'oos_metrics': clean(wr.oos_metrics),
            'elapsed_s': wr.elapsed_s,
        })

    # Aggregate
    oos_pnls = [wr.oos_metrics['total_pnl'] for wr in window_results]
    oos_pfs = [wr.oos_metrics['profit_factor'] for wr in window_results
               if wr.oos_metrics['profit_factor'] != float('inf')]
    oos_sharpes = [wr.oos_metrics['sharpe'] for wr in window_results]
    positive = sum(1 for p in oos_pnls if p > 0)

    report['aggregate'] = {
        'total_oos_pnl': float(sum(oos_pnls)),
        'mean_oos_pf': float(np.mean(oos_pfs)) if oos_pfs else 0,
        'mean_oos_sharpe': float(np.mean(oos_sharpes)),
        'worst_oos_sharpe': float(min(oos_sharpes)) if oos_sharpes else 0,
        'positive_windows': positive,
        'positive_window_pct': positive / len(window_results) if window_results else 0,
        'total_oos_trades': sum(wr.oos_metrics['trades'] for wr in window_results),
    }

    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"\n  Report saved: {report_path}")


if __name__ == '__main__':
    run_walk_forward()
