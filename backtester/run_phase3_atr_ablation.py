"""
Phase 3 ATR Exhaustion Gate Ablation — 3 variants on 25 tickers.

Variant A: ATR gate OFF (how Phase 2 actually ran — NaN bug meant it was disabled)
Variant B: ATR gate ON, strict (ATR_ENTRY=0.60, ATR_BLOCK=0.20) — same as v2
Variant C: ATR gate ON, relaxed (ATR_ENTRY=0.40, ATR_BLOCK=0.10)

Squeeze: OFF for all variants (per ablation L-005.3 §B.2).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import json
import csv
import numpy as np
import pandas as pd

from backtester.backtester import Backtester, BacktestConfig
from backtester.core.level_detector import LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngineConfig
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig
from backtester.core.intraday_levels import IntradayLevelConfig
from backtester.earnings import EarningsCalendar
from backtester.optimizer import load_ticker_data
from backtester.run_phase3_25ticker import (
    TICKERS, FULL_START, FULL_END, compute_metrics, fmt,
)

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'results', 'phase3_atr_ablation')
os.makedirs(RESULTS_DIR, exist_ok=True)


def make_config(variant, earnings_calendar=None) -> BacktestConfig:
    """Build config for a given variant (A/B/C)."""
    atr_settings = {
        'A': {'enable_atr_filter': False, 'atr_block_threshold': 0.20, 'atr_entry_threshold': 0.60},
        'B': {'enable_atr_filter': True,  'atr_block_threshold': 0.20, 'atr_entry_threshold': 0.60},
        'C': {'enable_atr_filter': True,  'atr_block_threshold': 0.10, 'atr_entry_threshold': 0.40},
    }[variant]

    return BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=10, tolerance_cents=0.05, tolerance_pct=0.001,
            atr_period=5, min_level_score=5,
        ),
        pattern_config=PatternEngineConfig(
            tail_ratio_min=0.15, lp2_engulfing_required=True,
            clp_min_bars=3, clp_max_bars=7,
        ),
        filter_config=FilterChainConfig(
            enable_atr_filter=atr_settings['enable_atr_filter'],
            atr_block_threshold=atr_settings['atr_block_threshold'],
            atr_entry_threshold=atr_settings['atr_entry_threshold'],
            enable_volume_filter=True,
            enable_time_filter=True,
            enable_squeeze_filter=False,
        ),
        risk_config=RiskManagerConfig(
            min_rr=2.0, max_stop_atr_pct=0.15, capital=100000.0, risk_pct=0.003,
        ),
        trade_config=TradeManagerConfig(
            slippage_per_share=0.02, partial_tp_at_r=2.0, partial_tp_pct=0.50,
        ),
        intraday_config=IntradayLevelConfig(
            fractal_depth_m5=5, fractal_depth_h1=3, enable_h1=True,
            min_target_r=1.0, lookback_bars=1000,
        ),
        tier_config={
            'mode': '2tier_trail', 't1_pct': 0.30, 'min_rr': 2.0,
            'trail_factor': 0.7, 'trail_activation_r': 0.0,
        },
        direction_filter=None,
        earnings_calendar=earnings_calendar,
        name=f'ConfigA_ATR_Variant_{variant}',
    )


def run_variant(variant, config, label):
    """Run one variant across all 25 tickers. Returns (metrics, funnel, trades)."""
    print(f"\n{'=' * 80}")
    print(f"  Variant {variant}: {label}")
    print(f"{'=' * 80}")

    all_trades = []
    all_funnel = {}

    for ticker in TICKERS:
        try:
            m5_df = load_ticker_data(ticker)
            bt = Backtester(config)
            result = bt.run(m5_df, start_date=FULL_START, end_date=FULL_END)

            for trade in result.trades:
                all_trades.append({
                    'ticker': ticker,
                    'direction': trade.direction.value,
                    'pattern': trade.signal.pattern.value if trade.signal else '',
                    'entry_time': str(trade.entry_time),
                    'exit_time': str(trade.exit_time),
                    'entry_price': trade.entry_price,
                    'exit_price': trade.exit_price,
                    'pnl': trade.pnl,
                    'pnl_r': trade.pnl_r,
                    'is_winner': trade.is_winner,
                })

            all_funnel[ticker] = bt.filter_chain.get_funnel_summary()

            perf = result.performance
            print(f"    {ticker}: {perf.get('total_trades', 0)}t, "
                  f"WR={perf.get('win_rate', 0)*100:.1f}%, "
                  f"PF={perf.get('profit_factor', 0):.2f}, "
                  f"P&L=${perf.get('total_pnl', 0):.0f}")

        except Exception as e:
            print(f"    {ticker}: FAILED — {e}")

    # Aggregate funnel
    agg_funnel = {}
    for f in all_funnel.values():
        for k, v in f.items():
            agg_funnel[k] = agg_funnel.get(k, 0) + v

    # Compute metrics
    trade_objs = [type('T', (), t)() for t in all_trades]  # quick objects
    pnls = [t['pnl'] for t in all_trades]
    n = len(pnls)
    if n == 0:
        metrics = {'trades': 0, 'wr': 0.0, 'pf': 0.0, 'pnl': 0.0,
                   'max_dd': 0.0, 'avg_r': 0.0}
    else:
        pnl_arr = np.array(pnls)
        winners = pnl_arr[pnl_arr > 0]
        losers = pnl_arr[pnl_arr <= 0]
        gp = winners.sum()
        gl = abs(losers.sum())
        pf = gp / gl if gl > 0 else (float('inf') if gp > 0 else 0.0)
        cum = np.cumsum(pnl_arr)
        peak = np.maximum.accumulate(cum)
        max_dd = (peak - cum).max() if len(cum) > 0 else 0.0
        pnl_r_vals = [t['pnl_r'] for t in all_trades if 'pnl_r' in t]
        metrics = {
            'trades': n,
            'wr': len(winners) / n,
            'pf': float(pf),
            'pnl': float(pnl_arr.sum()),
            'max_dd': float(max_dd),
            'avg_r': float(np.mean(pnl_r_vals)) if pnl_r_vals else 0.0,
        }

    pf_s = f"{metrics['pf']:.2f}" if metrics['pf'] != float('inf') else "inf"
    print(f"\n  AGGREGATE: {metrics['trades']}t  WR={metrics['wr']*100:.1f}%  "
          f"PF={pf_s}  P&L=${metrics['pnl']:,.0f}  MaxDD=${metrics['max_dd']:,.0f}")
    print(f"  ATR blocks: hard={agg_funnel.get('blocked_by_atr_hard', 0)}, "
          f"thresh={agg_funnel.get('blocked_by_atr_threshold', 0)}, "
          f"error={agg_funnel.get('blocked_by_atr_error', 0)}")

    return metrics, agg_funnel, all_trades


def main():
    t0 = time.time()

    print("=" * 80)
    print("  PHASE 3 ATR EXHAUSTION GATE ABLATION — 25 Tickers")
    print("=" * 80)

    # Load earnings calendar
    cache_dir = os.path.join(RESULTS_DIR, 'cache')
    calendar = EarningsCalendar(cache_dir=cache_dir)
    calendar.load(TICKERS)

    variants = {
        'A': ('ATR gate OFF (how Phase 2 ran)', make_config('A', calendar)),
        'B': ('ATR ON, strict (0.60/0.20)', make_config('B', calendar)),
        'C': ('ATR ON, relaxed (0.40/0.10)', make_config('C', calendar)),
    }

    results = {}
    for var_id, (label, config) in variants.items():
        metrics, funnel, trades = run_variant(var_id, config, label)
        results[var_id] = {
            'label': label,
            'metrics': metrics,
            'funnel': funnel,
        }

        # Save per-variant JSON
        var_path = os.path.join(RESULTS_DIR, f'variant_{var_id.lower()}.json')
        with open(var_path, 'w') as f:
            json.dump({
                'variant': var_id,
                'label': label,
                'config': {
                    'enable_atr_filter': config.filter_config.enable_atr_filter,
                    'atr_block_threshold': config.filter_config.atr_block_threshold,
                    'atr_entry_threshold': config.filter_config.atr_entry_threshold,
                },
                'metrics': metrics,
                'funnel': funnel,
            }, f, indent=2, default=str)

        # Save trade log CSV
        trade_path = os.path.join(RESULTS_DIR, f'trades_{var_id.lower()}.csv')
        if trades:
            keys = trades[0].keys()
            with open(trade_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(trades)

    # ══════════════════════════════════════════════════════════════════════
    # COMPARISON TABLE
    # ══════════════════════════════════════════════════════════════════════

    elapsed = time.time() - t0

    print(f"\n\n{'=' * 90}")
    print(f"  ATR EXHAUSTION GATE ABLATION — COMPARISON TABLE")
    print(f"{'=' * 90}")

    header = (f"  {'Variant':<4} {'ATR Config':<22} {'Trades':>7} {'PF':>7} "
              f"{'P&L':>10} {'MaxDD':>8} {'WR%':>7} {'AvgR':>6} {'ATR Blk':>8}")
    print(header)
    print(f"  {'-' * 86}")

    for var_id in ['A', 'B', 'C']:
        r = results[var_id]
        m = r['metrics']
        f = r['funnel']
        atr_blocks = (f.get('blocked_by_atr_hard', 0) +
                      f.get('blocked_by_atr_threshold', 0) +
                      f.get('blocked_by_atr_error', 0))
        pf_s = f"{m['pf']:.2f}" if m['pf'] != float('inf') else "inf"
        print(f"  {var_id:<4} {r['label']:<22} {m['trades']:>7} {pf_s:>7} "
              f"${m['pnl']:>9,.0f} ${m['max_dd']:>7,.0f} {m['wr']*100:>6.1f}% "
              f"{m['avg_r']:>6.2f} {atr_blocks:>8}")

    print(f"  {'-' * 86}")

    # Delta analysis
    a = results['A']['metrics']
    b = results['B']['metrics']
    c = results['C']['metrics']

    print(f"\n  DELTA ANALYSIS (vs Variant A — ATR OFF):")
    for var_id, m, label in [('B', b, 'Strict'), ('C', c, 'Relaxed')]:
        d_trades = m['trades'] - a['trades']
        d_pnl = m['pnl'] - a['pnl']
        d_pf = m['pf'] - a['pf']
        print(f"    {var_id} ({label}): trades {d_trades:+d}, "
              f"PF {d_pf:+.2f}, P&L ${d_pnl:+,.0f}")

    # Decision framework
    print(f"\n  RECOMMENDATION:")
    if a['pnl'] > b['pnl'] and a['pnl'] > c['pnl']:
        print(f"    A >> B and A >> C → ATR exhaustion gate is SUPPRESSIVE.")
        print(f"    Recommend: REMOVE permanently (set enable_atr_filter=False).")
    elif c['pnl'] > a['pnl'] and c['pnl'] > b['pnl']:
        print(f"    C > A and C > B → Relaxed ATR adds value.")
        print(f"    Recommend: Adopt relaxed thresholds (0.40/0.10).")
    elif b['pnl'] > a['pnl']:
        print(f"    B > A → Strict ATR is correct, Phase 2 was lucky without it.")
        print(f"    Recommend: Keep strict thresholds (0.60/0.20).")
    else:
        print(f"    Mixed results — further analysis needed.")
        if a['pf'] > 1.0 and b['pf'] < 1.0:
            print(f"    ATR gate turns profitable strategy unprofitable → likely suppressive.")

    print(f"\n  Completed in {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"  Results saved to: {RESULTS_DIR}/")

    # Save comparison JSON
    comp_path = os.path.join(RESULTS_DIR, 'comparison.json')
    with open(comp_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)


if __name__ == '__main__':
    main()
