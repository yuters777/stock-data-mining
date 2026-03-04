"""
Phase 2.3 Actions — Fixed-params walk-forward with same-level limit & trend filter.

Runs 4 configurations across all 6 OOS windows and compares:
  A) Fixed params, no extras (baseline comparison)
  B) Fixed params + same-level limit (max_losses_per_level=2)
  C) Fixed params + trend filter (SMA20)
  D) Fixed params + same-level limit + trend filter
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from collections import defaultdict

from backtester.backtester import Backtester, BacktestConfig
from backtester.core.level_detector import LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngineConfig
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
TICKERS = ['TSLA', 'AMZN', 'GOOGL', 'META', 'MSFT', 'NVDA']

# Fixed "overall best IS" params
FIXED_PARAMS = dict(
    fractal_depth=10,
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
    atr_entry_threshold=0.60,
    max_stop_atr_pct=0.10,
    min_rr=2.0,
    capital=100000.0,
    risk_pct=0.003,
    tier_mode='2tier_trail',
    t1_pct=0.30,
    trail_factor=0.7,
    trail_activation_r=0.0,
    tier_min_rr=1.5,
)

ALL_WINDOWS = [
    {'label': 'W1', 'test_start': '2025-05-10', 'test_end': '2025-06-10'},
    {'label': 'W2', 'test_start': '2025-06-10', 'test_end': '2025-07-10'},
    {'label': 'W3', 'test_start': '2025-07-10', 'test_end': '2025-08-10'},
    {'label': 'W4', 'test_start': '2025-08-10', 'test_end': '2025-09-10'},
    {'label': 'W5', 'test_start': '2025-09-10', 'test_end': '2025-10-10'},
    {'label': 'W6', 'test_start': '2025-10-10', 'test_end': '2025-11-10'},
]


def build_config(name, max_losses_per_level=0, enable_trend=False, trend_period=20):
    p = FIXED_PARAMS
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
            enable_trend_filter=enable_trend,
            trend_sma_period=trend_period,
        ),
        risk_config=RiskManagerConfig(
            min_rr=p['min_rr'],
            max_stop_atr_pct=p['max_stop_atr_pct'],
            capital=p['capital'],
            risk_pct=p['risk_pct'],
            max_losses_per_level=max_losses_per_level,
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


def load_all_data():
    data = {}
    for ticker in TICKERS:
        path = os.path.join(DATA_DIR, f'{ticker}_data.csv')
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path)
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        df = df.sort_values('Datetime').reset_index(drop=True)
        data[ticker] = df
    return data


def run_config_all_windows(config, ticker_data, label):
    """Run a config across all windows and return per-window results."""
    results = []
    for w in ALL_WINDOWS:
        all_trades = []
        for ticker, m5_df in ticker_data.items():
            bt = Backtester(config)
            result = bt.run(m5_df, start_date=w['test_start'], end_date=w['test_end'])
            for t in result.trades:
                t.sector = ticker
            all_trades.extend(result.trades)

        n = len(all_trades)
        if n == 0:
            results.append({'window': w['label'], 'trades': 0, 'winners': 0,
                            'wr': 0, 'pf': 0, 'pnl': 0, 'sharpe': 0,
                            'blocked_trend': 0, 'blocked_level_exhaust': 0})
            continue

        winners = [t for t in all_trades if t.pnl > 0]
        losers = [t for t in all_trades if t.pnl <= 0]
        gp = sum(t.pnl for t in winners)
        gl = abs(sum(t.pnl for t in losers))
        pf = gp / gl if gl > 0 else (float('inf') if gp > 0 else 0)
        pnl = sum(t.pnl for t in all_trades)

        daily_pnl = defaultdict(float)
        for t in all_trades:
            day = str(t.exit_time.date()) if t.exit_time else 'unknown'
            daily_pnl[day] += t.pnl
        daily_vals = list(daily_pnl.values())
        if len(daily_vals) > 1 and np.std(daily_vals) > 0:
            sharpe = np.mean(daily_vals) / np.std(daily_vals) * np.sqrt(252)
        else:
            sharpe = 0.0

        results.append({
            'window': w['label'],
            'trades': n,
            'winners': len(winners),
            'wr': len(winners) / n * 100,
            'pf': pf,
            'pnl': pnl,
            'sharpe': sharpe,
        })

    return results


def print_results_table(results, label):
    """Print formatted results table."""
    print(f"\n  {label}")
    print(f"  {'Win':>4} {'Trades':>6} {'Winners':>7} {'WR':>6} {'PF':>6} "
          f"{'P&L':>10} {'Sharpe':>7}")
    print(f"  {'─' * 52}")

    total_pnl = 0
    total_trades = 0
    total_winners = 0
    positive_windows = 0

    for r in results:
        total_pnl += r['pnl']
        total_trades += r['trades']
        total_winners += r['winners']
        if r['pnl'] > 0:
            positive_windows += 1

        pf_str = f"{r['pf']:.2f}" if r['pf'] != float('inf') else "inf"
        print(f"  {r['window']:>4} {r['trades']:>6} {r['winners']:>7} "
              f"{r['wr']:>5.1f}% {pf_str:>6} "
              f"${r['pnl']:>9.2f} {r['sharpe']:>7.2f}")

    print(f"  {'─' * 52}")
    wr_total = total_winners / total_trades * 100 if total_trades > 0 else 0
    print(f"  {'TOT':>4} {total_trades:>6} {total_winners:>7} "
          f"{wr_total:>5.1f}%    — "
          f"${total_pnl:>9.2f}       —")
    print(f"  Positive windows: {positive_windows}/{len(results)}")

    return total_pnl, total_trades, positive_windows


def main():
    print("Loading data...")
    ticker_data = load_all_data()
    print(f"Loaded {len(ticker_data)} tickers")

    configs = [
        ("A) Fixed params (no extras)",
         build_config("A_fixed")),
        ("B) Fixed params + same-level limit (max=2)",
         build_config("B_level_limit", max_losses_per_level=2)),
        ("C) Fixed params + trend filter (SMA20)",
         build_config("C_trend", enable_trend=True, trend_period=20)),
        ("D) Fixed params + level limit + trend filter",
         build_config("D_both", max_losses_per_level=2, enable_trend=True, trend_period=20)),
    ]

    all_results = {}

    for label, config in configs:
        print(f"\n{'=' * 80}")
        print(f"  Running: {label}")
        print(f"{'=' * 80}")

        results = run_config_all_windows(config, ticker_data, label)
        total_pnl, total_trades, pos_wins = print_results_table(results, label)
        all_results[label] = {
            'results': results,
            'total_pnl': total_pnl,
            'total_trades': total_trades,
            'positive_windows': pos_wins,
        }

    # ── Summary comparison ──
    print(f"\n\n{'=' * 80}")
    print(f"  COMPARISON SUMMARY")
    print(f"{'=' * 80}")
    print(f"\n  {'Config':>50} {'Trades':>7} {'P&L':>11} {'Pos Win':>8}")
    print(f"  {'─' * 80}")

    for label, data in all_results.items():
        print(f"  {label:>50} {data['total_trades']:>7} "
              f"${data['total_pnl']:>10.2f} "
              f"{data['positive_windows']}/6")

    # ── W6-specific comparison ──
    print(f"\n\n  W6-SPECIFIC (Oct 10 – Nov 10):")
    print(f"  {'Config':>50} {'Trades':>7} {'P&L':>11} {'WR':>6}")
    print(f"  {'─' * 80}")

    for label, data in all_results.items():
        w6 = [r for r in data['results'] if r['window'] == 'W6'][0]
        print(f"  {label:>50} {w6['trades']:>7} "
              f"${w6['pnl']:>10.2f} {w6['wr']:>5.1f}%")

    print("\nDone.")


if __name__ == '__main__':
    main()
