"""
Phase 6B — Per-Ticker Direction Experiments

Based on Phase 6A findings:
  - AAPL, AMZN, GOOGL perform better SHORT
  - TSLA performs better LONG
  - SHORT-only achieves 4/8 WF positive (vs 0/8 baseline)

Tests:
  L-004: Per-ticker optimal (TSLA=both, others=short)
  L-005: Per-ticker strict (TSLA=long, others=short)
  L-006: SHORT-only ex-TSLA (TSLA excluded, others SHORT)
  L-002: SHORT only (rerun for comparison)
  L-003: BOTH baseline (rerun for comparison)

Outputs: results/direction_analysis_v6b.md
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

from backtester.backtester import BacktestConfig
from backtester.core.level_detector import LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngineConfig
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig
from backtester.core.intraday_levels import IntradayLevelConfig
from backtester.optimizer import (load_ticker_data, run_single_backtest,
                                   aggregate_metrics, WalkForwardValidator)

# ──────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────

WHITELIST = ['AAPL', 'AMZN', 'GOOGL', 'TSLA']
WHITELIST_NO_TSLA = ['AAPL', 'AMZN', 'GOOGL']
IS_START = '2025-02-10'
IS_END = '2025-10-01'
OOS_START = '2025-10-01'
OOS_END = '2026-01-31'

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')


def make_config(name, direction_filter=None) -> BacktestConfig:
    return BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=10, tolerance_cents=0.05, tolerance_pct=0.001,
            atr_period=5, min_level_score=5,
        ),
        pattern_config=PatternEngineConfig(
            tail_ratio_min=0.10, lp2_engulfing_required=True,
            clp_min_bars=3, clp_max_bars=7,
        ),
        filter_config=FilterChainConfig(
            atr_block_threshold=0.30, atr_entry_threshold=0.80,
            enable_volume_filter=True, enable_time_filter=True,
            enable_squeeze_filter=True,
        ),
        risk_config=RiskManagerConfig(
            min_rr=1.5, max_stop_atr_pct=0.10, capital=100000.0, risk_pct=0.003,
        ),
        trade_config=TradeManagerConfig(
            slippage_per_share=0.02, partial_tp_at_r=2.0, partial_tp_pct=0.50,
        ),
        intraday_config=IntradayLevelConfig(
            fractal_depth_m5=5, fractal_depth_h1=3, enable_h1=True,
            min_target_r=1.0, lookback_bars=1000,
        ),
        tier_config={
            'mode': '2tier_trail', 't1_pct': 0.30, 'min_rr': 1.5,
            'trail_factor': 0.7, 'trail_activation_r': 0.0,
        },
        direction_filter=direction_filter,
        name=name,
    )


def compute_ticker_stats(result):
    trades = result.trades
    if not trades:
        return {'trades': 0, 'wr': 0, 'pf': 0, 'pnl': 0, 'longs': 0, 'shorts': 0}
    winners = [t for t in trades if t.pnl > 0]
    losers = [t for t in trades if t.pnl <= 0]
    gp = sum(t.pnl for t in winners)
    gl = abs(sum(t.pnl for t in losers))
    return {
        'trades': len(trades),
        'wr': len(winners) / len(trades) if trades else 0,
        'pf': gp / gl if gl > 0 else float('inf'),
        'pnl': sum(t.pnl for t in trades),
        'longs': sum(1 for t in trades if t.direction.value == 'long'),
        'shorts': sum(1 for t in trades if t.direction.value == 'short'),
    }


def run_variant(exp_id, label, direction_filter, tickers=None):
    if tickers is None:
        tickers = WHITELIST
    print(f"\n{'='*60}")
    print(f"  {exp_id}: {label}")
    print(f"  Tickers: {', '.join(tickers)}")
    if isinstance(direction_filter, dict):
        print(f"  Direction map: {direction_filter}")
    else:
        print(f"  Direction: {direction_filter or 'both'}")
    print(f"{'='*60}")

    config = make_config(name=exp_id, direction_filter=direction_filter)

    is_results = {}
    oos_results = {}
    for ticker in tickers:
        m5_df = load_ticker_data(ticker)
        is_results[ticker] = run_single_backtest(config, m5_df, IS_START, IS_END)
        oos_results[ticker] = run_single_backtest(config, m5_df, OOS_START, OOS_END)

    combined_is = aggregate_metrics(is_results)
    combined_oos = aggregate_metrics(oos_results)

    is_ticker_stats = {t: compute_ticker_stats(r) for t, r in is_results.items()}
    oos_ticker_stats = {t: compute_ticker_stats(r) for t, r in oos_results.items()}

    print(f"\n  IS:  {combined_is['total_trades']} trades, "
          f"WR={combined_is['win_rate']*100:.1f}%, "
          f"PF={combined_is['profit_factor']:.2f}, "
          f"${combined_is['total_pnl']:.0f}")
    print(f"  OOS: {combined_oos['total_trades']} trades, "
          f"WR={combined_oos['win_rate']*100:.1f}%, "
          f"PF={combined_oos['profit_factor']:.2f}, "
          f"${combined_oos['total_pnl']:.0f}")

    for ticker in tickers:
        s = oos_ticker_stats[ticker]
        print(f"    {ticker} OOS: {s['trades']}t, "
              f"WR={s['wr']*100:.0f}%, PF={s['pf']:.2f}, "
              f"${s['pnl']:.0f} (L:{s['longs']}/S:{s['shorts']})")

    # Walk-forward
    print(f"\n  Walk-Forward ({exp_id}):")
    wf = WalkForwardValidator(config, tickers)
    wf_results = wf.run()
    wf_summary = WalkForwardValidator.summarize(wf_results)

    print(f"  WF: {wf_summary['positive_sharpe_windows']}/{wf_summary['n_windows']} positive, "
          f"mean Sharpe={wf_summary['mean_sharpe']:.2f}, "
          f"total P&L=${wf_summary['total_pnl']:.0f}")

    return {
        'exp_id': exp_id,
        'label': label,
        'direction_filter': direction_filter,
        'tickers': tickers,
        'combined_is': combined_is,
        'combined_oos': combined_oos,
        'is_ticker_stats': is_ticker_stats,
        'oos_ticker_stats': oos_ticker_stats,
        'wf_results': wf_results,
        'wf_summary': wf_summary,
    }


def generate_report(variants):
    lines = [
        "# Phase 6B — Per-Ticker Direction Analysis",
        "",
        "**Date:** 2026-03-03",
        "**Base config:** v4.1 best (trail_factor=0.7, t1_pct=0.30)",
        "",
        "---",
        "",
        "## 1. Portfolio Summary",
        "",
        "| Experiment | Description | Tickers | Trades (IS) | PF (IS) | P&L (IS) | Trades (OOS) | PF (OOS) | P&L (OOS) |",
        "|------------|-------------|---------|-------------|---------|----------|--------------|----------|-----------|",
    ]

    for v in variants:
        vis = v['combined_is']
        voos = v['combined_oos']
        t_str = ','.join(v['tickers'])
        lines.append(
            f"| {v['exp_id']} | {v['label']} | {t_str} | "
            f"{vis['total_trades']} | {vis['profit_factor']:.2f} | ${vis['total_pnl']:.0f} | "
            f"{voos['total_trades']} | {voos['profit_factor']:.2f} | ${voos['total_pnl']:.0f} |"
        )

    # Per-ticker OOS
    lines.extend(["", "## 2. Per-Ticker OOS Breakdown", ""])
    for v in variants:
        lines.append(f"### {v['exp_id']}: {v['label']}")
        lines.append("")
        lines.append("| Ticker | Trades | L/S | WR | PF | P&L |")
        lines.append("|--------|--------|-----|----|----|-----|")
        for ticker in v['tickers']:
            s = v['oos_ticker_stats'][ticker]
            lines.append(
                f"| {ticker} | {s['trades']} | {s['longs']}L/{s['shorts']}S | "
                f"{s['wr']*100:.0f}% | {s['pf']:.2f} | ${s['pnl']:.0f} |"
            )
        lines.append("")

    # Walk-forward
    lines.extend(["## 3. Walk-Forward Comparison", ""])
    lines.append("| Metric | " + " | ".join(v['exp_id'] for v in variants) + " |")
    lines.append("|--------|" + "|".join("---" for _ in variants) + "|")

    metric_rows = [
        ('Positive windows', lambda v: f"{v['wf_summary']['positive_sharpe_windows']}/{v['wf_summary']['n_windows']}"),
        ('Mean Sharpe', lambda v: f"{v['wf_summary']['mean_sharpe']:.2f}"),
        ('Mean PF', lambda v: f"{v['wf_summary']['mean_pf']:.2f}"),
        ('Total trades', lambda v: f"{v['wf_summary']['total_trades']}"),
        ('Total P&L', lambda v: f"${v['wf_summary']['total_pnl']:.0f}"),
        ('Mean P&L/window', lambda v: f"${v['wf_summary']['mean_pnl_per_window']:.0f}"),
    ]
    for label, fn in metric_rows:
        cells = [fn(v) for v in variants]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")

    # Per-window detail
    lines.extend(["", "### Per-Window P&L", ""])
    lines.append("| Window | Period | " + " | ".join(v['exp_id'] for v in variants) + " |")
    lines.append("|--------|--------|" + "|".join("---" for _ in variants) + "|")
    n_windows = max(len(v['wf_results']) for v in variants)
    for i in range(n_windows):
        period = ""
        cells = []
        for v in variants:
            if i < len(v['wf_results']):
                w = v['wf_results'][i]
                period = f"{w.get('test_start', '')} → {w.get('test_end', '')}"
                cells.append(f"${w['total_pnl']:.0f} ({w['total_trades']}t)")
            else:
                cells.append("-")
        lines.append(f"| {i+1} | {period} | " + " | ".join(cells) + " |")

    # Verdict
    best_wf = max(variants, key=lambda v: v['wf_summary']['positive_sharpe_windows'])
    best_oos = max(variants, key=lambda v: v['combined_oos']['profit_factor'])

    lines.extend([
        "",
        "## 4. Verdict",
        "",
        f"**Best WF stability:** {best_wf['exp_id']} ({best_wf['label']}) "
        f"— {best_wf['wf_summary']['positive_sharpe_windows']}/{best_wf['wf_summary']['n_windows']} positive, "
        f"mean Sharpe={best_wf['wf_summary']['mean_sharpe']:.2f}",
        "",
        f"**Best OOS PF:** {best_oos['exp_id']} ({best_oos['label']}) "
        f"— PF={best_oos['combined_oos']['profit_factor']:.2f}, "
        f"${best_oos['combined_oos']['total_pnl']:.0f}",
        "",
    ])

    return "\n".join(lines)


if __name__ == '__main__':
    print("Phase 6B — Per-Ticker Direction Experiments")
    print("=" * 60)

    variants = []

    # L-004: Per-ticker optimal (TSLA=both, others=short)
    variants.append(run_variant('L-004', 'TSLA=both, others=short',
                                {'TSLA': None, 'DEFAULT': 'short'}))

    # L-005: Per-ticker strict (TSLA=long only, others=short only)
    variants.append(run_variant('L-005', 'TSLA=long, others=short',
                                {'TSLA': 'long', 'DEFAULT': 'short'}))

    # L-006: SHORT-only ex-TSLA (3-ticker portfolio)
    variants.append(run_variant('L-006', 'SHORT only (ex-TSLA)',
                                'short', tickers=WHITELIST_NO_TSLA))

    # L-002 rerun: SHORT only (4 tickers) for comparison
    variants.append(run_variant('L-002', 'SHORT only (all 4)',
                                'short'))

    # L-003 rerun: BOTH baseline
    variants.append(run_variant('L-003', 'BOTH baseline',
                                None))

    # Generate report
    os.makedirs(RESULTS_DIR, exist_ok=True)
    report = generate_report(variants)
    report_path = os.path.join(RESULTS_DIR, 'direction_analysis_v6b.md')
    with open(report_path, 'w') as f:
        f.write(report)
    print(f"\nReport written to {report_path}")

    print("\n" + "=" * 60)
    print("  FINAL COMPARISON")
    print("=" * 60)
    for v in variants:
        oos = v['combined_oos']
        wfs = v['wf_summary']
        print(f"  {v['exp_id']:5} {v['label']:30s}: "
              f"OOS {oos['total_trades']}t PF={oos['profit_factor']:.2f} ${oos['total_pnl']:.0f} | "
              f"WF {wfs['positive_sharpe_windows']}/{wfs['n_windows']} pos, "
              f"Sharpe={wfs['mean_sharpe']:.2f}, ${wfs['total_pnl']:.0f}")
