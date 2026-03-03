"""
Phase 6A — Direction Analysis

Runs three experiments:
  L-001: LONG only (block SHORT signals)
  L-002: SHORT only (block LONG signals)
  L-003: BOTH (no direction filter — v4.1 baseline rerun)

For each: IS/OOS per-ticker breakdown, 8-window walk-forward.
Outputs: results/direction_analysis.md
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from copy import deepcopy

from backtester.backtester import Backtester, BacktestConfig
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
IS_START = '2025-02-10'
IS_END = '2025-10-01'
OOS_START = '2025-10-01'
OOS_END = '2026-01-31'

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')


# ──────────────────────────────────────────────────────────────────
# Config builder
# ──────────────────────────────────────────────────────────────────

def make_config(name='v4.1_best', direction_filter=None) -> BacktestConfig:
    """Build v4.1 best config with optional direction filter."""
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


# ──────────────────────────────────────────────────────────────────
# Per-ticker breakdown helper
# ──────────────────────────────────────────────────────────────────

def compute_ticker_stats(result):
    """Extract stats from a single BacktestResult."""
    trades = result.trades
    if not trades:
        return {'trades': 0, 'wr': 0, 'pf': 0, 'pnl': 0, 'longs': 0, 'shorts': 0}

    winners = [t for t in trades if t.pnl > 0]
    losers = [t for t in trades if t.pnl <= 0]
    gross_profit = sum(t.pnl for t in winners)
    gross_loss = abs(sum(t.pnl for t in losers))

    longs = sum(1 for t in trades if t.direction.value == 'long')
    shorts = sum(1 for t in trades if t.direction.value == 'short')

    return {
        'trades': len(trades),
        'wr': len(winners) / len(trades) if trades else 0,
        'pf': gross_profit / gross_loss if gross_loss > 0 else float('inf'),
        'pnl': sum(t.pnl for t in trades),
        'longs': longs,
        'shorts': shorts,
    }


# ──────────────────────────────────────────────────────────────────
# Run a single experiment variant
# ──────────────────────────────────────────────────────────────────

def run_variant(exp_id, label, direction_filter):
    """Run IS/OOS + walk-forward for a direction variant."""
    print(f"\n{'='*60}")
    print(f"  {exp_id}: {label}")
    print(f"{'='*60}")

    config = make_config(name=exp_id, direction_filter=direction_filter)

    # IS + OOS per ticker
    is_results = {}
    oos_results = {}
    for ticker in WHITELIST:
        m5_df = load_ticker_data(ticker)
        is_results[ticker] = run_single_backtest(config, m5_df, IS_START, IS_END)
        oos_results[ticker] = run_single_backtest(config, m5_df, OOS_START, OOS_END)

    combined_is = aggregate_metrics(is_results)
    combined_oos = aggregate_metrics(oos_results)

    # Per-ticker stats
    is_ticker_stats = {t: compute_ticker_stats(r) for t, r in is_results.items()}
    oos_ticker_stats = {t: compute_ticker_stats(r) for t, r in oos_results.items()}

    # Print summary
    print(f"\n  IS:  {combined_is['total_trades']} trades, "
          f"WR={combined_is['win_rate']*100:.1f}%, "
          f"PF={combined_is['profit_factor']:.2f}, "
          f"${combined_is['total_pnl']:.0f}")
    print(f"  OOS: {combined_oos['total_trades']} trades, "
          f"WR={combined_oos['win_rate']*100:.1f}%, "
          f"PF={combined_oos['profit_factor']:.2f}, "
          f"${combined_oos['total_pnl']:.0f}")

    for ticker in WHITELIST:
        s = oos_ticker_stats[ticker]
        print(f"    {ticker} OOS: {s['trades']}t, "
              f"WR={s['wr']*100:.0f}%, PF={s['pf']:.2f}, "
              f"${s['pnl']:.0f} (L:{s['longs']}/S:{s['shorts']})")

    # Walk-forward
    print(f"\n  Walk-Forward ({exp_id}):")
    wf = WalkForwardValidator(config, WHITELIST)
    wf_results = wf.run()
    wf_summary = WalkForwardValidator.summarize(wf_results)

    positive = wf_summary['positive_sharpe_windows']
    total = wf_summary['n_windows']
    print(f"  WF: {positive}/{total} positive, "
          f"mean Sharpe={wf_summary['mean_sharpe']:.2f}, "
          f"total P&L=${wf_summary['total_pnl']:.0f}")

    return {
        'exp_id': exp_id,
        'label': label,
        'direction_filter': direction_filter,
        'combined_is': combined_is,
        'combined_oos': combined_oos,
        'is_ticker_stats': is_ticker_stats,
        'oos_ticker_stats': oos_ticker_stats,
        'wf_results': wf_results,
        'wf_summary': wf_summary,
    }


# ──────────────────────────────────────────────────────────────────
# Generate report
# ──────────────────────────────────────────────────────────────────

def generate_report(variants):
    """Generate results/direction_analysis.md."""

    lines = [
        "# Phase 6A — Direction Analysis",
        "",
        f"**Date:** 2026-03-03",
        f"**Tickers:** {', '.join(WHITELIST)}",
        "**Config:** v4.1 best (trail_factor=0.7, t1_pct=0.30)",
        "",
        "---",
        "",
        "## 1. Portfolio Summary (IS + OOS)",
        "",
        "| Experiment | Direction | Trades (IS) | WR (IS) | PF (IS) | P&L (IS) | Trades (OOS) | WR (OOS) | PF (OOS) | P&L (OOS) |",
        "|------------|-----------|-------------|---------|---------|----------|--------------|----------|----------|-----------|",
    ]

    for v in variants:
        vis = v['combined_is']
        voos = v['combined_oos']
        d = v['direction_filter'] or 'both'
        lines.append(
            f"| {v['exp_id']} | {d.upper()} | {vis['total_trades']} | "
            f"{vis['win_rate']*100:.1f}% | {vis['profit_factor']:.2f} | "
            f"${vis['total_pnl']:.0f} | {voos['total_trades']} | "
            f"{voos['win_rate']*100:.1f}% | {voos['profit_factor']:.2f} | "
            f"${voos['total_pnl']:.0f} |"
        )

    # Per-ticker breakdown
    for period_label, stats_key in [("IS", "is_ticker_stats"), ("OOS", "oos_ticker_stats")]:
        lines.extend([
            "",
            f"## 2{'a' if period_label == 'IS' else 'b'}. Per-Ticker Breakdown ({period_label})",
            "",
            f"| Ticker | L-001 LONG | | | L-002 SHORT | | | L-003 BOTH | | |",
            f"|--------|-----|-----|------|------|-----|------|------|-----|------|",
            f"| | Trades | PF | P&L | Trades | PF | P&L | Trades | PF | P&L |",
        ])

        for ticker in WHITELIST:
            cells = []
            for v in variants:
                s = v[stats_key][ticker]
                cells.append(f"{s['trades']} | {s['pf']:.2f} | ${s['pnl']:.0f}")
            lines.append(f"| {ticker} | {' | '.join(cells)} |")

    # Direction split in BOTH
    both_v = [v for v in variants if v['direction_filter'] is None][0]
    lines.extend([
        "",
        "## 3. Direction Split within BOTH (L-003)",
        "",
        "### OOS per-ticker direction counts",
        "",
        "| Ticker | LONG trades | SHORT trades |",
        "|--------|-------------|--------------|",
    ])
    for ticker in WHITELIST:
        s = both_v['oos_ticker_stats'][ticker]
        lines.append(f"| {ticker} | {s['longs']} | {s['shorts']} |")

    # Walk-forward comparison
    lines.extend([
        "",
        "## 4. Walk-Forward Comparison (8 windows)",
        "",
        "| Window | Period | L-001 LONG | | L-002 SHORT | | L-003 BOTH | |",
        "|--------|--------|------|------|-------|------|------|------|",
        "| | | Trades | P&L | Trades | P&L | Trades | P&L |",
    ])

    # Align windows across variants
    n_windows = max(len(v['wf_results']) for v in variants)
    for i in range(n_windows):
        cells = []
        period = ""
        for v in variants:
            if i < len(v['wf_results']):
                w = v['wf_results'][i]
                period = f"{w.get('test_start', '')} → {w.get('test_end', '')}"
                cells.append(f"{w['total_trades']} | ${w['total_pnl']:.0f}")
            else:
                cells.append("- | -")
        lines.append(f"| {i+1} | {period} | {' | '.join(cells)} |")

    # WF summary
    lines.extend([
        "",
        "### Walk-Forward Summary",
        "",
        "| Metric | L-001 LONG | L-002 SHORT | L-003 BOTH |",
        "|--------|-----------|------------|-----------|",
    ])

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
        lines.append(f"| {label} | {' | '.join(cells)} |")

    # Verdict
    # Determine best variant by OOS PF
    best_oos = max(variants, key=lambda v: v['combined_oos']['profit_factor'])
    best_wf = max(variants, key=lambda v: v['wf_summary']['positive_sharpe_windows'])

    lines.extend([
        "",
        "## 5. Verdict",
        "",
        f"**Best OOS PF:** {best_oos['exp_id']} ({best_oos['direction_filter'] or 'both'}) "
        f"— PF={best_oos['combined_oos']['profit_factor']:.2f}, "
        f"${best_oos['combined_oos']['total_pnl']:.0f}",
        "",
        f"**Best WF stability:** {best_wf['exp_id']} ({best_wf['direction_filter'] or 'both'}) "
        f"— {best_wf['wf_summary']['positive_sharpe_windows']}/{best_wf['wf_summary']['n_windows']} positive windows, "
        f"mean Sharpe={best_wf['wf_summary']['mean_sharpe']:.2f}",
        "",
    ])

    # Determine recommendation
    long_v = [v for v in variants if v['direction_filter'] == 'long'][0]
    short_v = [v for v in variants if v['direction_filter'] == 'short'][0]
    both_v = [v for v in variants if v['direction_filter'] is None][0]

    long_oos_pf = long_v['combined_oos']['profit_factor']
    short_oos_pf = short_v['combined_oos']['profit_factor']
    both_oos_pf = both_v['combined_oos']['profit_factor']
    long_wf_pos = long_v['wf_summary']['positive_sharpe_windows']
    short_wf_pos = short_v['wf_summary']['positive_sharpe_windows']
    both_wf_pos = both_v['wf_summary']['positive_sharpe_windows']

    if long_wf_pos > both_wf_pos and long_oos_pf >= both_oos_pf * 0.9:
        rec = "LONG ONLY — improves walk-forward stability without sacrificing OOS PF"
    elif short_wf_pos > both_wf_pos and short_oos_pf >= both_oos_pf * 0.9:
        rec = "SHORT ONLY — improves walk-forward stability without sacrificing OOS PF"
    elif long_oos_pf > short_oos_pf * 1.5 and long_oos_pf > both_oos_pf:
        rec = "LONG ONLY — dramatically better OOS performance"
    elif short_oos_pf > long_oos_pf * 1.5 and short_oos_pf > both_oos_pf:
        rec = "SHORT ONLY — dramatically better OOS performance"
    else:
        rec = "KEEP BOTH — no clear directional advantage"

    lines.append(f"**Recommendation:** {rec}")
    lines.append("")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("Phase 6A — Direction Analysis")
    print("=" * 60)

    variants = []

    # L-001: LONG only
    variants.append(run_variant('L-001', 'LONG only', 'long'))

    # L-002: SHORT only
    variants.append(run_variant('L-002', 'SHORT only', 'short'))

    # L-003: BOTH (baseline rerun)
    variants.append(run_variant('L-003', 'BOTH (baseline)', None))

    # Generate report
    os.makedirs(RESULTS_DIR, exist_ok=True)
    report = generate_report(variants)
    report_path = os.path.join(RESULTS_DIR, 'direction_analysis.md')
    with open(report_path, 'w') as f:
        f.write(report)
    print(f"\nReport written to {report_path}")

    # Final comparison
    print("\n" + "=" * 60)
    print("  FINAL COMPARISON")
    print("=" * 60)
    for v in variants:
        oos = v['combined_oos']
        wfs = v['wf_summary']
        print(f"  {v['exp_id']} ({v['direction_filter'] or 'both':>5}): "
              f"OOS {oos['total_trades']}t PF={oos['profit_factor']:.2f} ${oos['total_pnl']:.0f} | "
              f"WF {wfs['positive_sharpe_windows']}/{wfs['n_windows']} pos, "
              f"Sharpe={wfs['mean_sharpe']:.2f}")
