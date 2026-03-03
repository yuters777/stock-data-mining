"""
STRUCT Experiments — Structural Target System Optimization (v3)

STRUCT-001: M5 intraday targets (single-tier replacement)
STRUCT-002: Tiered exit system
STRUCT-003: Combined winner + walk-forward validation

Each experiment tests a structural change to the target/exit system.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from datetime import datetime

from backtester.backtester import Backtester, BacktestConfig
from backtester.core.level_detector import LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngineConfig
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig
from backtester.core.intraday_levels import IntradayLevelConfig
from backtester.optimizer import (
    load_ticker_data, run_single_backtest, aggregate_metrics,
    WalkForwardValidator,
)

# Constants
TICKERS = ['NVDA', 'AMZN']
IS_START = '2025-02-10'
IS_END = '2025-10-01'
OOS_START = '2025-10-01'
OOS_END = '2026-01-31'


def get_v2_optimized_config(**overrides) -> BacktestConfig:
    """Return the v2 optimized configuration (our new baseline)."""
    intraday_cfg = overrides.pop('intraday_config', None)
    tier_cfg = overrides.pop('tier_config', None)

    cfg = BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=overrides.get('fractal_depth', 10),
            tolerance_cents=0.05,
            tolerance_pct=0.001,
            atr_period=5,
            min_level_score=5,
        ),
        pattern_config=PatternEngineConfig(
            tail_ratio_min=overrides.get('tail_ratio_min', 0.10),
            lp2_engulfing_required=True,
            clp_min_bars=3,
            clp_max_bars=7,
        ),
        filter_config=FilterChainConfig(
            atr_block_threshold=0.30,
            atr_entry_threshold=overrides.get('atr_entry_threshold', 0.80),
            enable_volume_filter=True,
            enable_time_filter=True,
            enable_squeeze_filter=True,
        ),
        risk_config=RiskManagerConfig(
            min_rr=overrides.get('min_rr', 3.0),
            max_stop_atr_pct=overrides.get('max_stop_atr_pct', 0.10),
            capital=100000.0,
            risk_pct=0.003,
        ),
        trade_config=TradeManagerConfig(
            slippage_per_share=0.02,
            partial_tp_at_r=2.0,
            partial_tp_pct=0.50,
        ),
        intraday_config=intraday_cfg,
        tier_config=tier_cfg,
        name=overrides.get('name', 'v2_optimized'),
    )
    return cfg


def run_backtest_for_tickers(config, tickers, start_date, end_date):
    """Run backtest across all tickers and aggregate."""
    results = {}
    for ticker in tickers:
        m5_df = load_ticker_data(ticker)
        bt = Backtester(config)
        result = bt.run(m5_df, start_date=start_date, end_date=end_date)
        result.performance['proximity_events'] = bt.proximity_events
        result.performance['intraday_targets_found'] = bt.intraday_targets_found
        result.performance['intraday_targets_used'] = bt.intraday_targets_used
        results[ticker] = result
    combined = aggregate_metrics(results)
    # Aggregate intraday stats
    combined['intraday_targets_found'] = sum(
        r.performance.get('intraday_targets_found', 0) for r in results.values()
    )
    combined['intraday_targets_used'] = sum(
        r.performance.get('intraday_targets_used', 0) for r in results.values()
    )
    return results, combined


def run_is_oos(config, tickers):
    """Run both IS and OOS backtests."""
    is_results, is_combined = run_backtest_for_tickers(config, tickers, IS_START, IS_END)
    oos_results, oos_combined = run_backtest_for_tickers(config, tickers, OOS_START, OOS_END)
    return is_results, is_combined, oos_results, oos_combined


def fmt_metrics(m):
    """Format metrics dict for logging."""
    return (f"{m['total_trades']} trades, {m['win_rate']*100:.1f}% WR, "
            f"PF={m['profit_factor']:.2f}, ${m['total_pnl']:.0f}")


def format_variant_row(label, is_m, oos_m):
    """Format a variant row for the markdown table."""
    return (f"| {label} | {is_m['total_trades']} | {is_m['win_rate']*100:.1f}% | "
            f"{is_m['profit_factor']:.2f} | ${is_m['total_pnl']:.0f} | "
            f"{oos_m['total_trades']} | {oos_m['win_rate']*100:.1f}% | "
            f"{oos_m['profit_factor']:.2f} | ${oos_m['total_pnl']:.0f} | "
            f"{oos_m.get('intraday_targets_used', 0)} |")


def count_target_hits(results_dict):
    """Count how many trades hit their target vs EOD vs stop."""
    from backtester.core.trade_manager import ExitReason
    hits = {'target': 0, 'stop': 0, 'eod': 0, 'other': 0}
    for ticker, result in results_dict.items():
        for trade in result.trades:
            if trade.exit_reason == ExitReason.TARGET_HIT:
                hits['target'] += 1
            elif trade.exit_reason == ExitReason.STOP_LOSS:
                hits['stop'] += 1
            elif trade.exit_reason == ExitReason.EOD_EXIT:
                hits['eod'] += 1
            else:
                hits['other'] += 1
    return hits


# ──────────────────────────────────────────────────────────────────
# STRUCT-001: M5 Intraday Targets
# ──────────────────────────────────────────────────────────────────

def run_struct_001():
    """Run all STRUCT-001 variants."""
    print("\n" + "=" * 60)
    print("STRUCT-001: M5 Intraday Targets (Single-Tier Replacement)")
    print("=" * 60)

    variants = [
        {
            'id': 'STRUCT-001a',
            'label': 'M5 fractal k=3',
            'intraday_config': IntradayLevelConfig(
                fractal_depth_m5=3, enable_h1=False, min_target_r=1.0,
                lookback_bars=500,
            ),
            'tier_config': {'mode': 'single_intraday', 'min_rr': 1.5},
        },
        {
            'id': 'STRUCT-001b',
            'label': 'M5 fractal k=5',
            'intraday_config': IntradayLevelConfig(
                fractal_depth_m5=5, enable_h1=False, min_target_r=1.0,
                lookback_bars=500,
            ),
            'tier_config': {'mode': 'single_intraday', 'min_rr': 1.5},
        },
        {
            'id': 'STRUCT-001c',
            'label': 'M5 fractal k=10',
            'intraday_config': IntradayLevelConfig(
                fractal_depth_m5=10, enable_h1=False, min_target_r=1.0,
                lookback_bars=500,
            ),
            'tier_config': {'mode': 'single_intraday', 'min_rr': 1.5},
        },
        {
            'id': 'STRUCT-001d',
            'label': 'H1 fractal k=3',
            'intraday_config': IntradayLevelConfig(
                fractal_depth_m5=5, fractal_depth_h1=3, enable_h1=True,
                min_target_r=1.0, lookback_bars=1000,
            ),
            'tier_config': {'mode': 'single_intraday', 'min_rr': 1.5},
        },
    ]

    results = []
    for v in variants:
        print(f"\n  Testing {v['id']}: {v['label']}...")
        cfg = get_v2_optimized_config(
            name=v['id'],
            intraday_config=v['intraday_config'],
            tier_config=v['tier_config'],
        )
        is_r, is_m, oos_r, oos_m = run_is_oos(cfg, TICKERS)
        is_hits = count_target_hits(is_r)
        oos_hits = count_target_hits(oos_r)
        results.append({
            **v,
            'is_combined': is_m,
            'oos_combined': oos_m,
            'is_hits': is_hits,
            'oos_hits': oos_hits,
            'is_results': is_r,
            'oos_results': oos_r,
        })
        print(f"    IS:  {fmt_metrics(is_m)} | targets hit: {is_hits['target']}")
        print(f"    OOS: {fmt_metrics(oos_m)} | targets hit: {oos_hits['target']}")

    return results


# ──────────────────────────────────────────────────────────────────
# STRUCT-002: Tiered Exit System
# ──────────────────────────────────────────────────────────────────

def run_struct_002(best_001_config):
    """Run STRUCT-002 variants using best STRUCT-001 intraday config."""
    print("\n" + "=" * 60)
    print("STRUCT-002: Tiered Exit System")
    print("=" * 60)

    intraday_cfg = best_001_config['intraday_config']

    variants = [
        {
            'id': 'STRUCT-002a',
            'label': '2-tier 50/50 M5+D1',
            'tier_config': {'mode': '2tier', 't1_pct': 0.50, 'min_rr': 1.5},
        },
        {
            'id': 'STRUCT-002b',
            'label': '2-tier 60/40 M5+D1',
            'tier_config': {'mode': '2tier', 't1_pct': 0.60, 'min_rr': 1.5},
        },
        {
            'id': 'STRUCT-002c',
            'label': '3-tier 40/30/30 M5+H1+D1',
            'tier_config': {'mode': '3tier', 't1_pct': 0.40, 't2_pct': 0.30, 'min_rr': 1.5},
        },
        {
            'id': 'STRUCT-002d',
            'label': '2-tier 50% M5 + trail',
            'tier_config': {'mode': '2tier_trail', 't1_pct': 0.50, 'min_rr': 1.5},
        },
    ]

    # For 3-tier, enable H1
    h1_intraday_cfg = IntradayLevelConfig(
        fractal_depth_m5=intraday_cfg.fractal_depth_m5,
        fractal_depth_h1=3,
        enable_h1=True,
        min_target_r=intraday_cfg.min_target_r,
        lookback_bars=1000,
    )

    results = []
    for v in variants:
        print(f"\n  Testing {v['id']}: {v['label']}...")
        # Use H1-enabled config for 3-tier
        icfg = h1_intraday_cfg if v['tier_config']['mode'] == '3tier' else intraday_cfg

        cfg = get_v2_optimized_config(
            name=v['id'],
            intraday_config=icfg,
            tier_config=v['tier_config'],
        )
        is_r, is_m, oos_r, oos_m = run_is_oos(cfg, TICKERS)
        is_hits = count_target_hits(is_r)
        oos_hits = count_target_hits(oos_r)
        results.append({
            **v,
            'is_combined': is_m,
            'oos_combined': oos_m,
            'is_hits': is_hits,
            'oos_hits': oos_hits,
            'intraday_config': icfg,
            'is_results': is_r,
            'oos_results': oos_r,
        })
        print(f"    IS:  {fmt_metrics(is_m)} | targets hit: {is_hits['target']}")
        print(f"    OOS: {fmt_metrics(oos_m)} | targets hit: {oos_hits['target']}")

    return results


# ──────────────────────────────────────────────────────────────────
# Pick Best
# ──────────────────────────────────────────────────────────────────

def pick_best(results, baseline_oos):
    """Pick best variant by OOS profit factor (primary) and P&L (secondary)."""
    scored = []
    for r in results:
        oos = r['oos_combined']
        pf = oos['profit_factor']
        pnl = oos['total_pnl']
        trades = oos['total_trades']
        if trades < 3:
            score = -999
        else:
            score = pf * 100 + pnl / 100
        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0][1]

    # Determine verdict
    baseline_pf = baseline_oos['profit_factor']
    best_pf = best['oos_combined']['profit_factor']
    best_trades = best['oos_combined']['total_trades']

    if best_pf > baseline_pf and best_trades >= 5:
        verdict = "ACCEPT"
    elif best_trades < 5:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "REJECT"

    return best, verdict


# ──────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────

def write_experiment_log(baseline_is, baseline_oos, baseline_hits,
                         struct001_results, struct002_results,
                         combined_result, wf_summary, wf_results):
    """Write full experiment log to experiments/EXPERIMENT_LOG_v3.md"""
    exp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'experiments')
    os.makedirs(exp_dir, exist_ok=True)

    lines = [
        f"# Experiment Log v3 — Structural Target Optimization",
        f"",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Tickers:** {', '.join(TICKERS)}",
        f"**IS Period:** {IS_START} to {IS_END}",
        f"**OOS Period:** {OOS_START} to {OOS_END}",
        f"**Baseline:** v2 optimized (fd=10, atr=0.80, stop=0.10, tail=0.10)",
        f"",
        f"---",
        f"",
        f"## Baseline (v2 optimized, D1 targets only)",
        f"",
        f"| Period | Trades | WR | PF | P&L | Target Hits | EOD Exits | Stops |",
        f"|--------|--------|-----|-----|------|-------------|-----------|-------|",
        f"| IS | {baseline_is['total_trades']} | {baseline_is['win_rate']*100:.1f}% | "
        f"{baseline_is['profit_factor']:.2f} | ${baseline_is['total_pnl']:.0f} | "
        f"{baseline_hits['is']['target']} | {baseline_hits['is']['eod']} | {baseline_hits['is']['stop']} |",
        f"| OOS | {baseline_oos['total_trades']} | {baseline_oos['win_rate']*100:.1f}% | "
        f"{baseline_oos['profit_factor']:.2f} | ${baseline_oos['total_pnl']:.0f} | "
        f"{baseline_hits['oos']['target']} | {baseline_hits['oos']['eod']} | {baseline_hits['oos']['stop']} |",
        f"",
        f"---",
        f"",
    ]

    # STRUCT-001
    lines.extend([
        "## STRUCT-001: M5 Intraday Targets (Single-Tier Replacement)",
        "",
        "**Hypothesis:** Replacing D1 targets with M5 fractal intraday targets will increase target hit rate from ~2% to >20%, improving P&L.",
        "**Change:** Use IntradayLevelDetector to find M5/H1 fractal S/R, set as trade target. Min R:R reduced to 1.5.",
        "",
        "| Variant | Trades (IS) | WR (IS) | PF (IS) | P&L (IS) | Trades (OOS) | WR (OOS) | PF (OOS) | P&L (OOS) | Targets Used |",
        "|---------|-------------|---------|---------|----------|--------------|----------|----------|-----------|-------------|",
    ])
    for r in struct001_results:
        lines.append(format_variant_row(
            f"{r['id']}: {r['label']}", r['is_combined'], r['oos_combined']
        ))

    # Target hit comparison
    lines.extend(["", "### Target Hit Analysis (OOS)", ""])
    lines.append("| Variant | Target Hits | EOD Exits | Stops | Hit Rate |")
    lines.append("|---------|-------------|-----------|-------|----------|")
    for r in struct001_results:
        h = r['oos_hits']
        total = h['target'] + h['eod'] + h['stop'] + h['other']
        hit_rate = h['target'] / total * 100 if total > 0 else 0
        lines.append(f"| {r['id']} | {h['target']} | {h['eod']} | {h['stop']} | {hit_rate:.0f}% |")

    # Best 001
    best_001 = max(struct001_results,
                   key=lambda r: r['oos_combined']['profit_factor'] if r['oos_combined']['total_trades'] >= 3 else -999)
    lines.extend([
        f"",
        f"**Best STRUCT-001:** {best_001['id']} ({best_001['label']})",
        f"",
        f"---",
        f"",
    ])

    # STRUCT-002
    lines.extend([
        "## STRUCT-002: Tiered Exit System",
        "",
        "**Hypothesis:** Multi-level partial exits at M5/H1/D1 levels will capture more profit than single-target approach.",
        f"**Base intraday config:** {best_001['label']}",
        "",
        "| Variant | Trades (IS) | WR (IS) | PF (IS) | P&L (IS) | Trades (OOS) | WR (OOS) | PF (OOS) | P&L (OOS) | Targets Used |",
        "|---------|-------------|---------|---------|----------|--------------|----------|----------|-----------|-------------|",
    ])
    for r in struct002_results:
        lines.append(format_variant_row(
            f"{r['id']}: {r['label']}", r['is_combined'], r['oos_combined']
        ))

    lines.extend(["", "### Target Hit Analysis (OOS)", ""])
    lines.append("| Variant | Target Hits | EOD Exits | Stops | Hit Rate |")
    lines.append("|---------|-------------|-----------|-------|----------|")
    for r in struct002_results:
        h = r['oos_hits']
        total = h['target'] + h['eod'] + h['stop'] + h['other']
        hit_rate = h['target'] / total * 100 if total > 0 else 0
        lines.append(f"| {r['id']} | {h['target']} | {h['eod']} | {h['stop']} | {hit_rate:.0f}% |")

    lines.extend(["", "---", ""])

    # Combined
    if combined_result:
        cm_is = combined_result['is_combined']
        cm_oos = combined_result['oos_combined']
        lines.extend([
            "## STRUCT-003: Combined Winner",
            "",
            f"**Config:** {combined_result.get('label', 'combined')}",
            "",
            "| Period | Trades | WR | PF | P&L | Target Hits | EOD | Stops |",
            "|--------|--------|-----|-----|------|-------------|-----|-------|",
            f"| Baseline OOS | {baseline_oos['total_trades']} | {baseline_oos['win_rate']*100:.1f}% | "
            f"{baseline_oos['profit_factor']:.2f} | ${baseline_oos['total_pnl']:.0f} | "
            f"{baseline_hits['oos']['target']} | {baseline_hits['oos']['eod']} | {baseline_hits['oos']['stop']} |",
            f"| Combined IS | {cm_is['total_trades']} | {cm_is['win_rate']*100:.1f}% | "
            f"{cm_is['profit_factor']:.2f} | ${cm_is['total_pnl']:.0f} | "
            f"{combined_result.get('is_hits', {}).get('target', 0)} | "
            f"{combined_result.get('is_hits', {}).get('eod', 0)} | "
            f"{combined_result.get('is_hits', {}).get('stop', 0)} |",
            f"| Combined OOS | {cm_oos['total_trades']} | {cm_oos['win_rate']*100:.1f}% | "
            f"{cm_oos['profit_factor']:.2f} | ${cm_oos['total_pnl']:.0f} | "
            f"{combined_result.get('oos_hits', {}).get('target', 0)} | "
            f"{combined_result.get('oos_hits', {}).get('eod', 0)} | "
            f"{combined_result.get('oos_hits', {}).get('stop', 0)} |",
            "",
            "---",
            "",
        ])

    # Walk-Forward
    if wf_summary and wf_results:
        lines.extend([
            "## Walk-Forward Validation",
            "",
            f"**Config:** Combined winner",
            f"**Windows:** {wf_summary['n_windows']} (3-month train / 1-month test)",
            "",
            "| Window | Test Period | Trades | WR | PF | Sharpe | P&L |",
            "|--------|-------------|--------|-----|-----|--------|------|",
        ])
        for r in wf_results:
            lines.append(
                f"| {r['window']} | {r['test_start']}->{r['test_end']} | "
                f"{r['total_trades']} | {r['win_rate']*100:.1f}% | "
                f"{r['profit_factor']:.2f} | {r.get('sharpe', 0):.2f} | "
                f"${r['total_pnl']:.0f} |"
            )

        lines.extend([
            "",
            f"**Summary:**",
            f"- Mean Sharpe: {wf_summary['mean_sharpe']:.2f} +/- {wf_summary['std_sharpe']:.2f}",
            f"- Positive Sharpe windows: {wf_summary['positive_sharpe_windows']}/{wf_summary['n_windows']}",
            f"- Mean PF: {wf_summary['mean_pf']:.2f}",
            f"- Mean WR: {wf_summary['mean_wr']*100:.1f}%",
            f"- Total Trades: {wf_summary['total_trades']}",
            f"- Total P&L: ${wf_summary['total_pnl']:.0f}",
            "",
        ])

    log_path = os.path.join(exp_dir, 'EXPERIMENT_LOG_v3.md')
    with open(log_path, 'w') as f:
        f.write("\n".join(lines))

    print(f"\nExperiment log written to: {log_path}")
    return log_path


# ──────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("STRUCT EXPERIMENTS — v3 Target System Optimization")
    print(f"Tickers: {', '.join(TICKERS)}")
    print(f"IS: {IS_START} to {IS_END} | OOS: {OOS_START} to {OOS_END}")
    print("=" * 60)

    # ── Run v2 baseline ──
    print("\nRunning v2 optimized baseline (D1 targets only)...")
    baseline_cfg = get_v2_optimized_config(name='v2_baseline')
    is_r, baseline_is, oos_r, baseline_oos = run_is_oos(baseline_cfg, TICKERS)
    baseline_hits = {
        'is': count_target_hits(is_r),
        'oos': count_target_hits(oos_r),
    }
    print(f"  Baseline IS:  {fmt_metrics(baseline_is)} | targets: {baseline_hits['is']['target']}")
    print(f"  Baseline OOS: {fmt_metrics(baseline_oos)} | targets: {baseline_hits['oos']['target']}")

    # ── STRUCT-001 ──
    struct001_results = run_struct_001()

    # Pick best STRUCT-001
    best_001, verdict_001 = pick_best(struct001_results, baseline_oos)
    print(f"\n  STRUCT-001 best: {best_001['id']} — {verdict_001}")
    print(f"    OOS: {fmt_metrics(best_001['oos_combined'])}")

    # ── STRUCT-002 ──
    struct002_results = run_struct_002(best_001)

    # Pick best STRUCT-002
    best_002, verdict_002 = pick_best(struct002_results, baseline_oos)
    print(f"\n  STRUCT-002 best: {best_002['id']} — {verdict_002}")
    print(f"    OOS: {fmt_metrics(best_002['oos_combined'])}")

    # ── STRUCT-003: Combined winner ──
    print("\n" + "=" * 60)
    print("STRUCT-003: Combined Winner")
    print("=" * 60)

    # Use the overall best from 001 + 002
    all_results = struct001_results + struct002_results
    overall_best, overall_verdict = pick_best(all_results, baseline_oos)
    print(f"\n  Overall best: {overall_best['id']} ({overall_best['label']})")
    print(f"    OOS: {fmt_metrics(overall_best['oos_combined'])}")

    combined_result = {
        'label': f"{overall_best['id']}: {overall_best['label']}",
        'is_combined': overall_best['is_combined'],
        'oos_combined': overall_best['oos_combined'],
        'is_hits': overall_best.get('is_hits', {}),
        'oos_hits': overall_best.get('oos_hits', {}),
    }

    # ── Walk-Forward ──
    print("\n" + "=" * 60)
    print("Walk-Forward Validation")
    print("=" * 60)

    wf_cfg = get_v2_optimized_config(
        name='walk_forward',
        intraday_config=overall_best.get('intraday_config', overall_best.get('intraday_config')),
        tier_config=overall_best['tier_config'],
    )
    wf = WalkForwardValidator(wf_cfg, TICKERS)
    wf_results = wf.run()
    wf_summary = WalkForwardValidator.summarize(wf_results)

    print(f"\n  Walk-Forward ({wf_summary['n_windows']} windows):")
    print(f"    Mean Sharpe: {wf_summary['mean_sharpe']:.2f} +/- {wf_summary['std_sharpe']:.2f}")
    print(f"    Positive Sharpe: {wf_summary['positive_sharpe_windows']}/{wf_summary['n_windows']}")
    print(f"    Mean PF: {wf_summary['mean_pf']:.2f}")
    print(f"    Total P&L: ${wf_summary['total_pnl']:.0f}")

    # ── Write logs ──
    write_experiment_log(
        baseline_is, baseline_oos, baseline_hits,
        struct001_results, struct002_results,
        combined_result, wf_summary, wf_results
    )

    # ── Summary ──
    print("\n" + "=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    print(f"\nBaseline (v2): PF={baseline_oos['profit_factor']:.2f}, "
          f"${baseline_oos['total_pnl']:.0f}, "
          f"target hits={baseline_hits['oos']['target']}")
    print(f"Best v3:       PF={overall_best['oos_combined']['profit_factor']:.2f}, "
          f"${overall_best['oos_combined']['total_pnl']:.0f}, "
          f"target hits={overall_best['oos_hits']['target']}")
    print(f"Walk-Forward:  {wf_summary['positive_sharpe_windows']}/{wf_summary['n_windows']} positive Sharpe, "
          f"mean PF={wf_summary['mean_pf']:.2f}")
    print("\nDone!")


if __name__ == '__main__':
    main()
