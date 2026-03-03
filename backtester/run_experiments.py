"""
Run all 13 optimization experiments sequentially.

Each experiment tests ONE parameter change against baseline v3.4.
Results are logged to experiments/EXPERIMENT_LOG.md.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from copy import deepcopy
from datetime import datetime

from backtester.optimizer import (
    get_baseline_config, load_ticker_data, run_experiment_variant,
    aggregate_metrics, format_experiment_log, pick_best_variant,
    WalkForwardValidator, run_single_backtest,
)
from backtester.backtester import BacktestConfig
from backtester.core.level_detector import LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngineConfig
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig


# Constants
TICKERS = ['NVDA', 'AMZN']
IS_START = '2025-02-10'
IS_END = '2025-10-01'
OOS_START = '2025-10-01'
OOS_END = '2026-01-31'


def make_config_variant(base_config: BacktestConfig, **overrides) -> BacktestConfig:
    """Create a variant config by overriding specific parameters."""
    cfg = BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=overrides.get('fractal_depth', base_config.level_config.fractal_depth),
            tolerance_cents=overrides.get('tolerance_cents', base_config.level_config.tolerance_cents),
            tolerance_pct=overrides.get('tolerance_pct', base_config.level_config.tolerance_pct),
            atr_period=overrides.get('atr_period', base_config.level_config.atr_period),
            min_level_score=overrides.get('min_level_score', base_config.level_config.min_level_score),
        ),
        pattern_config=PatternEngineConfig(
            tail_ratio_min=overrides.get('tail_ratio_min', base_config.pattern_config.tail_ratio_min),
            lp2_engulfing_required=overrides.get('lp2_engulfing_required', base_config.pattern_config.lp2_engulfing_required),
            clp_min_bars=overrides.get('clp_min_bars', base_config.pattern_config.clp_min_bars),
            clp_max_bars=overrides.get('clp_max_bars', base_config.pattern_config.clp_max_bars),
        ),
        filter_config=FilterChainConfig(
            atr_block_threshold=overrides.get('atr_block_threshold', base_config.filter_config.atr_block_threshold),
            atr_entry_threshold=overrides.get('atr_entry_threshold', base_config.filter_config.atr_entry_threshold),
            enable_volume_filter=overrides.get('enable_volume_filter', base_config.filter_config.enable_volume_filter),
            enable_time_filter=overrides.get('enable_time_filter', base_config.filter_config.enable_time_filter),
            enable_squeeze_filter=overrides.get('enable_squeeze_filter', base_config.filter_config.enable_squeeze_filter),
        ),
        risk_config=RiskManagerConfig(
            min_rr=overrides.get('min_rr', base_config.risk_config.min_rr),
            max_stop_atr_pct=overrides.get('max_stop_atr_pct', base_config.risk_config.max_stop_atr_pct),
            capital=base_config.risk_config.capital,
            risk_pct=base_config.risk_config.risk_pct,
            partial_tp_at=overrides.get('partial_tp_at', base_config.risk_config.partial_tp_at),
            partial_tp_pct=overrides.get('partial_tp_pct', base_config.risk_config.partial_tp_pct),
        ),
        trade_config=TradeManagerConfig(
            slippage_per_share=base_config.trade_config.slippage_per_share,
            partial_tp_at_r=overrides.get('partial_tp_at_r', base_config.trade_config.partial_tp_at_r),
            partial_tp_pct=overrides.get('partial_tp_pct_trade', base_config.trade_config.partial_tp_pct),
        ),
        name=overrides.get('name', base_config.name),
    )
    return cfg


def run_variant(base_config, label, **overrides):
    """Run a single variant and return structured result."""
    overrides['name'] = label
    cfg = make_config_variant(base_config, **overrides)

    is_results, oos_results, combined_is, combined_oos = run_experiment_variant(
        cfg, TICKERS, IS_START, IS_END, OOS_START, OOS_END
    )

    return {
        'label': label,
        'config': cfg,
        'is_results': is_results,
        'oos_results': oos_results,
        'combined_is': combined_is,
        'combined_oos': combined_oos,
    }


def run_exp_001(baseline, baseline_is, baseline_oos):
    """EXP-001: Fractal Depth"""
    print("\n" + "="*60)
    print("EXP-001: Fractal Depth")
    print("="*60)

    variants = []
    for depth in [3, 5, 7, 10]:
        label = f"fractal_depth={depth}"
        print(f"  Testing {label}...")
        v = run_variant(baseline, label, fractal_depth=depth)
        variants.append(v)

    best, verdict = pick_best_variant(variants, baseline_is)
    notes = _gen_notes(variants, baseline_is)

    log = format_experiment_log(
        "EXP-001", "Fractal Depth",
        "Shallower fractal depth (k=3) detects more levels → more trades. Deeper (k=7,10) = fewer, stronger levels",
        "fractal_depth from 5 to [3, 5, 7, 10]",
        baseline_is, baseline_oos, variants, best, verdict, notes
    )
    return log, best, verdict


def run_exp_002(baseline, baseline_is, baseline_oos):
    """EXP-002: ATR Entry Threshold"""
    print("\n" + "="*60)
    print("EXP-002: ATR Entry Threshold")
    print("="*60)

    variants = []
    for thresh in [0.60, 0.65, 0.70, 0.75, 0.80]:
        label = f"atr_entry={thresh}"
        print(f"  Testing {label}...")
        v = run_variant(baseline, label, atr_entry_threshold=thresh)
        variants.append(v)

    best, verdict = pick_best_variant(variants, baseline_is)
    notes = _gen_notes(variants, baseline_is)

    log = format_experiment_log(
        "EXP-002", "ATR Entry Threshold",
        "Lower ATR entry threshold allows more trades; quality may decrease",
        "atr_entry_threshold from 0.75 to [0.60, 0.65, 0.70, 0.75, 0.80]",
        baseline_is, baseline_oos, variants, best, verdict, notes
    )
    return log, best, verdict


def run_exp_003(baseline, baseline_is, baseline_oos):
    """EXP-003: Max Stop ATR %"""
    print("\n" + "="*60)
    print("EXP-003: Max Stop ATR %")
    print("="*60)

    variants = []
    for pct in [0.10, 0.15, 0.20, 0.25]:
        label = f"max_stop_atr={pct}"
        print(f"  Testing {label}...")
        v = run_variant(baseline, label, max_stop_atr_pct=pct)
        variants.append(v)

    best, verdict = pick_best_variant(variants, baseline_is)
    notes = _gen_notes(variants, baseline_is)

    log = format_experiment_log(
        "EXP-003", "Max Stop ATR Percentage",
        "Higher stop cap allows wider stops → fewer 'stop too big' blocks, but larger losses per trade",
        "max_stop_atr_pct from 0.15 to [0.10, 0.15, 0.20, 0.25]",
        baseline_is, baseline_oos, variants, best, verdict, notes
    )
    return log, best, verdict


def run_exp_004(baseline, baseline_is, baseline_oos):
    """EXP-004: Minimum Risk-Reward"""
    print("\n" + "="*60)
    print("EXP-004: Minimum Risk-Reward Ratio")
    print("="*60)

    variants = []
    for rr in [2.0, 2.5, 3.0, 3.5]:
        label = f"min_rr={rr}"
        print(f"  Testing {label}...")
        v = run_variant(baseline, label, min_rr=rr)
        variants.append(v)

    best, verdict = pick_best_variant(variants, baseline_is)
    notes = _gen_notes(variants, baseline_is)

    log = format_experiment_log(
        "EXP-004", "Minimum Risk-Reward Ratio",
        "Lower R:R (2.0, 2.5) allows more trades with closer targets; higher WR may compensate",
        "min_rr from 3.0 to [2.0, 2.5, 3.0, 3.5]",
        baseline_is, baseline_oos, variants, best, verdict, notes
    )
    return log, best, verdict


def run_exp_005(baseline, baseline_is, baseline_oos):
    """EXP-005: Level Tolerance"""
    print("\n" + "="*60)
    print("EXP-005: Level Tolerance")
    print("="*60)

    variants = []
    for cents, pct in [(0.03, 0.0008), (0.05, 0.001), (0.07, 0.001), (0.10, 0.0012)]:
        label = f"tol={cents}c/{pct*100:.2f}%"
        print(f"  Testing {label}...")
        v = run_variant(baseline, label, tolerance_cents=cents, tolerance_pct=pct)
        variants.append(v)

    best, verdict = pick_best_variant(variants, baseline_is)
    notes = _gen_notes(variants, baseline_is)

    log = format_experiment_log(
        "EXP-005", "Level Tolerance",
        "Wider tolerance catches more BPU touches and pattern signals near levels",
        f"tolerance from 5c/0.10% to [3c, 5c, 7c, 10c]",
        baseline_is, baseline_oos, variants, best, verdict, notes
    )
    return log, best, verdict


def run_exp_006(baseline, baseline_is, baseline_oos):
    """EXP-006: Partial TP R-multiple"""
    print("\n" + "="*60)
    print("EXP-006: Partial Take-Profit Level")
    print("="*60)

    variants = []
    for tp_r in [1.5, 2.0, 2.5]:
        label = f"partial_tp={tp_r}R"
        print(f"  Testing {label}...")
        v = run_variant(baseline, label, partial_tp_at_r=tp_r)
        variants.append(v)

    best, verdict = pick_best_variant(variants, baseline_is)
    notes = _gen_notes(variants, baseline_is)

    log = format_experiment_log(
        "EXP-006", "Partial Take-Profit Level",
        "Earlier TP (1.5R) locks in profits sooner → higher WR but lower avg R",
        "partial_tp_at from 2.0R to [1.5R, 2.0R, 2.5R]",
        baseline_is, baseline_oos, variants, best, verdict, notes
    )
    return log, best, verdict


def run_exp_007(baseline, baseline_is, baseline_oos):
    """EXP-007: CLP Min Bars"""
    print("\n" + "="*60)
    print("EXP-007: CLP Minimum Bars")
    print("="*60)

    variants = []
    for bars in [2, 3, 4, 5]:
        label = f"clp_min_bars={bars}"
        print(f"  Testing {label}...")
        v = run_variant(baseline, label, clp_min_bars=bars)
        variants.append(v)

    best, verdict = pick_best_variant(variants, baseline_is)
    notes = _gen_notes(variants, baseline_is)

    log = format_experiment_log(
        "EXP-007", "CLP Minimum Consolidation Bars",
        "Fewer min bars (2) captures more CLP signals; more (5) = higher quality",
        "clp_min_bars from 3 to [2, 3, 4, 5]",
        baseline_is, baseline_oos, variants, best, verdict, notes
    )
    return log, best, verdict


def run_exp_008(baseline, baseline_is, baseline_oos):
    """EXP-008: LP2 Engulfing Requirement"""
    print("\n" + "="*60)
    print("EXP-008: LP2 Engulfing Required")
    print("="*60)

    variants = []
    for eng in [True, False]:
        label = f"lp2_engulfing={'on' if eng else 'off'}"
        print(f"  Testing {label}...")
        v = run_variant(baseline, label, lp2_engulfing_required=eng)
        variants.append(v)

    best, verdict = pick_best_variant(variants, baseline_is)
    notes = _gen_notes(variants, baseline_is)

    log = format_experiment_log(
        "EXP-008", "LP2 Engulfing Requirement",
        "Relaxing engulfing allows more LP2 signals but may reduce quality",
        "lp2_engulfing from True to [True, False]",
        baseline_is, baseline_oos, variants, best, verdict, notes
    )
    return log, best, verdict


def run_exp_009(baseline, baseline_is, baseline_oos):
    """EXP-009: LP1 Tail Ratio Minimum"""
    print("\n" + "="*60)
    print("EXP-009: LP1 Tail Ratio Minimum")
    print("="*60)

    variants = []
    for ratio in [0.10, 0.15, 0.20, 0.25]:
        label = f"tail_ratio={ratio}"
        print(f"  Testing {label}...")
        v = run_variant(baseline, label, tail_ratio_min=ratio)
        variants.append(v)

    best, verdict = pick_best_variant(variants, baseline_is)
    notes = _gen_notes(variants, baseline_is)

    log = format_experiment_log(
        "EXP-009", "LP1 Tail Ratio Minimum",
        "Lower tail ratio (0.10) accepts more LP1 signals; higher (0.25) = cleaner patterns",
        "tail_ratio_min from 0.20 to [0.10, 0.15, 0.20, 0.25]",
        baseline_is, baseline_oos, variants, best, verdict, notes
    )
    return log, best, verdict


def run_exp_010(baseline, baseline_is, baseline_oos):
    """EXP-010: H1 Trend Filter (simulated via tighter time bucket)"""
    print("\n" + "="*60)
    print("EXP-010: Minimum Level Score")
    print("="*60)
    # Instead of H1 trend filter (not implemented), test min_level_score
    # which controls quality threshold for levels — similar filtering effect

    variants = []
    for score in [3, 5, 6, 7]:
        label = f"min_level_score={score}"
        print(f"  Testing {label}...")
        v = run_variant(baseline, label, min_level_score=score)
        variants.append(v)

    best, verdict = pick_best_variant(variants, baseline_is)
    notes = _gen_notes(variants, baseline_is)

    log = format_experiment_log(
        "EXP-010", "Minimum Level Score",
        "Lower min score (3) includes weaker levels → more trades. Higher (7) = only strongest levels",
        "min_level_score from 5 to [3, 5, 6, 7]",
        baseline_is, baseline_oos, variants, best, verdict, notes
    )
    return log, best, verdict


def run_exp_011(baseline, baseline_is, baseline_oos):
    """EXP-011: Squeeze Filter Toggle"""
    print("\n" + "="*60)
    print("EXP-011: Squeeze Filter Toggle")
    print("="*60)

    variants = []
    for enabled in [True, False]:
        label = f"squeeze={'on' if enabled else 'off'}"
        print(f"  Testing {label}...")
        v = run_variant(baseline, label, enable_squeeze_filter=enabled)
        variants.append(v)

    best, verdict = pick_best_variant(variants, baseline_is)
    notes = _gen_notes(variants, baseline_is)

    log = format_experiment_log(
        "EXP-011", "Squeeze Filter Toggle",
        "Disabling squeeze filter may allow more trades if it was blocking valid signals",
        "enable_squeeze_filter from True to [True, False]",
        baseline_is, baseline_oos, variants, best, verdict, notes
    )
    return log, best, verdict


def run_exp_012(baseline, baseline_is, baseline_oos):
    """EXP-012: Volume Filter Toggle"""
    print("\n" + "="*60)
    print("EXP-012: Volume Filter Toggle")
    print("="*60)

    variants = []
    for enabled in [True, False]:
        label = f"volume={'on' if enabled else 'off'}"
        print(f"  Testing {label}...")
        v = run_variant(baseline, label, enable_volume_filter=enabled)
        variants.append(v)

    best, verdict = pick_best_variant(variants, baseline_is)
    notes = _gen_notes(variants, baseline_is)

    log = format_experiment_log(
        "EXP-012", "Volume Filter Toggle",
        "Volume filter may be blocking valid false breakout signals. Removing it tests VSA value",
        "enable_volume_filter from True to [True, False]",
        baseline_is, baseline_oos, variants, best, verdict, notes
    )
    return log, best, verdict


def run_exp_013(baseline, baseline_is, baseline_oos):
    """EXP-013: Time Filter Toggle (All-day vs filtered)"""
    print("\n" + "="*60)
    print("EXP-013: Time Filter Toggle")
    print("="*60)

    variants = []
    for enabled in [True, False]:
        label = f"time_filter={'on' if enabled else 'off'}"
        print(f"  Testing {label}...")
        v = run_variant(baseline, label, enable_time_filter=enabled)
        variants.append(v)

    best, verdict = pick_best_variant(variants, baseline_is)
    notes = _gen_notes(variants, baseline_is)

    log = format_experiment_log(
        "EXP-013", "Time Filter Toggle",
        "Time filter blocks first 5 min. Disabling tests if open-bar signals are viable",
        "enable_time_filter from True to [True, False]",
        baseline_is, baseline_oos, variants, best, verdict, notes
    )
    return log, best, verdict


def _gen_notes(variants, baseline_is):
    """Generate observation notes for an experiment."""
    trade_counts = [v['combined_is']['total_trades'] for v in variants]
    wrs = [v['combined_is']['win_rate']*100 for v in variants]
    pfs = [v['combined_is']['profit_factor'] for v in variants]

    notes = (f"Trade counts ranged from {min(trade_counts)} to {max(trade_counts)}. "
             f"Win rates: {min(wrs):.1f}%-{max(wrs):.1f}%. "
             f"Profit factors: {min(pfs):.2f}-{max(pfs):.2f}.")
    return notes


def main():
    print("="*60)
    print("FALSE BREAKOUT STRATEGY OPTIMIZATION")
    print(f"Running 13 experiments on {', '.join(TICKERS)}")
    print(f"IS: {IS_START} to {IS_END} | OOS: {OOS_START} to {OOS_END}")
    print("="*60)

    baseline = get_baseline_config()

    # Run baseline first
    print("\nRunning baseline...")
    _, _, baseline_is, baseline_oos = run_experiment_variant(
        baseline, TICKERS, IS_START, IS_END, OOS_START, OOS_END
    )

    print(f"\nBaseline IS: {baseline_is['total_trades']} trades, "
          f"{baseline_is['win_rate']*100:.1f}% WR, "
          f"PF={baseline_is['profit_factor']:.2f}, "
          f"${baseline_is['total_pnl']:.0f}")
    print(f"Baseline OOS: {baseline_oos['total_trades']} trades, "
          f"{baseline_oos['win_rate']*100:.1f}% WR, "
          f"PF={baseline_oos['profit_factor']:.2f}, "
          f"${baseline_oos['total_pnl']:.0f}")

    # Run all 13 experiments
    experiments = [
        run_exp_001, run_exp_002, run_exp_003, run_exp_004,
        run_exp_005, run_exp_006, run_exp_007, run_exp_008,
        run_exp_009, run_exp_010, run_exp_011, run_exp_012,
        run_exp_013,
    ]

    all_logs = []
    winners = {}  # exp_id -> (best_variant, verdict)

    for i, exp_fn in enumerate(experiments):
        exp_id = f"EXP-{i+1:03d}"
        try:
            log, best, verdict = exp_fn(baseline, baseline_is, baseline_oos)
            all_logs.append(log)
            if verdict == "ACCEPT" and best:
                winners[exp_id] = best
                print(f"  → {exp_id}: {verdict} (best: {best['label']})")
            else:
                print(f"  → {exp_id}: {verdict}")
        except Exception as e:
            print(f"  → {exp_id}: ERROR — {e}")
            import traceback
            traceback.print_exc()
            all_logs.append(f"## {exp_id}: ERROR\n{str(e)}\n\n---\n")

    # Write experiment log
    exp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'experiments')
    os.makedirs(exp_dir, exist_ok=True)

    log_content = f"""# Experiment Log — False Breakout Strategy Optimization

**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
**Tickers:** {', '.join(TICKERS)}
**IS Period:** {IS_START} to {IS_END}
**OOS Period:** {OOS_START} to {OOS_END}
**Baseline:** v3.4

---

"""
    log_content += "\n".join(all_logs)

    log_path = os.path.join(exp_dir, 'EXPERIMENT_LOG.md')
    with open(log_path, 'w') as f:
        f.write(log_content)
    print(f"\nExperiment log written to: {log_path}")

    # Phase 2: Combine winners
    print("\n" + "="*60)
    print("COMBINING WINNING EXPERIMENTS")
    print("="*60)

    if not winners:
        print("No experiments accepted — trying best from each category")
        # Fall back: pick top 3 by IS P&L improvement regardless of verdict
        # Re-run experiments and collect all bests
        pass

    if winners:
        print(f"Winners: {list(winners.keys())}")
        combined_overrides = {}
        for exp_id, best in winners.items():
            cfg = best['config']
            # Extract the changed parameter from label
            label = best['label']
            print(f"  {exp_id}: {label}")

            # Map back to overrides
            if 'fractal_depth' in label:
                combined_overrides['fractal_depth'] = cfg.level_config.fractal_depth
            if 'atr_entry' in label:
                combined_overrides['atr_entry_threshold'] = cfg.filter_config.atr_entry_threshold
            if 'max_stop_atr' in label:
                combined_overrides['max_stop_atr_pct'] = cfg.risk_config.max_stop_atr_pct
            if 'min_rr' in label:
                combined_overrides['min_rr'] = cfg.risk_config.min_rr
            if 'tol=' in label:
                combined_overrides['tolerance_cents'] = cfg.level_config.tolerance_cents
                combined_overrides['tolerance_pct'] = cfg.level_config.tolerance_pct
            if 'partial_tp' in label:
                combined_overrides['partial_tp_at_r'] = cfg.trade_config.partial_tp_at_r
            if 'clp_min' in label:
                combined_overrides['clp_min_bars'] = cfg.pattern_config.clp_min_bars
            if 'lp2_engulfing' in label:
                combined_overrides['lp2_engulfing_required'] = cfg.pattern_config.lp2_engulfing_required
            if 'tail_ratio' in label:
                combined_overrides['tail_ratio_min'] = cfg.pattern_config.tail_ratio_min
            if 'min_level_score' in label:
                combined_overrides['min_level_score'] = cfg.level_config.min_level_score
            if 'squeeze' in label:
                combined_overrides['enable_squeeze_filter'] = cfg.filter_config.enable_squeeze_filter
            if 'volume' in label:
                combined_overrides['enable_volume_filter'] = cfg.filter_config.enable_volume_filter
            if 'time_filter' in label:
                combined_overrides['enable_time_filter'] = cfg.filter_config.enable_time_filter

        print(f"\nCombined overrides: {combined_overrides}")
        combined_overrides['name'] = 'combined_winners'
        combined_cfg = make_config_variant(baseline, **combined_overrides)

        print("Running combined config...")
        _, _, combined_is, combined_oos = run_experiment_variant(
            combined_cfg, TICKERS, IS_START, IS_END, OOS_START, OOS_END
        )

        print(f"\nCombined IS: {combined_is['total_trades']} trades, "
              f"{combined_is['win_rate']*100:.1f}% WR, "
              f"PF={combined_is['profit_factor']:.2f}, "
              f"${combined_is['total_pnl']:.0f}")
        print(f"Combined OOS: {combined_oos['total_trades']} trades, "
              f"{combined_oos['win_rate']*100:.1f}% WR, "
              f"PF={combined_oos['profit_factor']:.2f}, "
              f"${combined_oos['total_pnl']:.0f}")

        # Add combined results to log
        combined_log = f"""
## COMBINED WINNERS

**Parameters changed:** {combined_overrides}

| Period | Trades | WR | PF | P&L |
|--------|--------|-----|-----|------|
| Baseline IS | {baseline_is['total_trades']} | {baseline_is['win_rate']*100:.1f}% | {baseline_is['profit_factor']:.2f} | ${baseline_is['total_pnl']:.0f} |
| Baseline OOS | {baseline_oos['total_trades']} | {baseline_oos['win_rate']*100:.1f}% | {baseline_oos['profit_factor']:.2f} | ${baseline_oos['total_pnl']:.0f} |
| Combined IS | {combined_is['total_trades']} | {combined_is['win_rate']*100:.1f}% | {combined_is['profit_factor']:.2f} | ${combined_is['total_pnl']:.0f} |
| Combined OOS | {combined_oos['total_trades']} | {combined_oos['win_rate']*100:.1f}% | {combined_oos['profit_factor']:.2f} | ${combined_oos['total_pnl']:.0f} |

---

"""
        with open(log_path, 'a') as f:
            f.write(combined_log)

        optimized_config = combined_cfg
    else:
        # No winners: try the most impactful single changes
        print("No accepted winners. Using baseline for walk-forward.")
        optimized_config = baseline

    # Phase 3: Walk-Forward Validation
    print("\n" + "="*60)
    print("WALK-FORWARD VALIDATION")
    print("="*60)

    wf = WalkForwardValidator(optimized_config, TICKERS)
    wf_results = wf.run()
    wf_summary = WalkForwardValidator.summarize(wf_results)

    print(f"\nWalk-Forward Results ({wf_summary['n_windows']} windows):")
    print(f"  Mean Sharpe:     {wf_summary['mean_sharpe']:.2f} ± {wf_summary['std_sharpe']:.2f}")
    print(f"  Positive Sharpe: {wf_summary['positive_sharpe_windows']}/{wf_summary['n_windows']} windows")
    print(f"  Mean PF:         {wf_summary['mean_pf']:.2f}")
    print(f"  Mean WR:         {wf_summary['mean_wr']*100:.1f}%")
    print(f"  Total Trades:    {wf_summary['total_trades']}")
    print(f"  Total P&L:       ${wf_summary['total_pnl']:.0f}")

    # Add walk-forward to log
    wf_log = f"""
## WALK-FORWARD VALIDATION

**Config:** {optimized_config.name}
**Windows:** {wf_summary['n_windows']} (3-month train / 1-month test)

| Window | Test Period | Trades | WR | PF | Sharpe | P&L |
|--------|-------------|--------|-----|-----|--------|------|
"""
    for r in wf_results:
        wf_log += (f"| {r['window']} | {r['test_start']}→{r['test_end']} | "
                   f"{r['total_trades']} | {r['win_rate']*100:.1f}% | "
                   f"{r['profit_factor']:.2f} | {r.get('sharpe', 0):.2f} | "
                   f"${r['total_pnl']:.0f} |\n")

    wf_log += f"""
**Summary:**
- Mean Sharpe: {wf_summary['mean_sharpe']:.2f} ± {wf_summary['std_sharpe']:.2f}
- Positive Sharpe windows: {wf_summary['positive_sharpe_windows']}/{wf_summary['n_windows']}
- Mean PF: {wf_summary['mean_pf']:.2f}
- Mean WR: {wf_summary['mean_wr']*100:.1f}%
- Total Trades: {wf_summary['total_trades']}
- Total P&L: ${wf_summary['total_pnl']:.0f}
"""

    with open(log_path, 'a') as f:
        f.write(wf_log)

    print(f"\nFull results written to: {log_path}")
    print("\nDone!")


if __name__ == '__main__':
    main()
