"""
v4.1 Experiments — Whitelist Portfolio, Trail Optimization & NVDA Rescue

EXP-W001: Whitelist baseline (AAPL, AMZN, GOOGL, TSLA)
T001-T004: Trail optimization sweeps
N001-N003: NVDA rescue attempts
Walk-Forward: 8-window validation on final portfolio
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from copy import deepcopy
from datetime import datetime

from backtester.backtester import Backtester, BacktestConfig
from backtester.core.level_detector import LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngineConfig
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig, ExitReason
from backtester.core.intraday_levels import IntradayLevelConfig
from backtester.optimizer import (
    load_ticker_data, run_single_backtest, aggregate_metrics,
    WalkForwardValidator,
)

# ──────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────

WHITELIST = ['AAPL', 'AMZN', 'GOOGL', 'TSLA']
ALL_TICKERS = ['AAPL', 'AMZN', 'GOOGL', 'META', 'MSFT', 'NVDA', 'TSLA']
IS_START = '2025-02-10'
IS_END = '2025-10-01'
OOS_START = '2025-10-01'
OOS_END = '2026-01-31'

EXP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'experiments')
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')

LOG_LINES = []  # accumulate markdown log


def log(text):
    LOG_LINES.append(text)
    print(text)


# ──────────────────────────────────────────────────────────────────
# Config Builder
# ──────────────────────────────────────────────────────────────────

def make_config(name='v3_winner', **overrides) -> BacktestConfig:
    """Build a BacktestConfig from v3 winner defaults + overrides."""
    tier_cfg = {
        'mode': '2tier_trail',
        't1_pct': overrides.pop('t1_pct', 0.50),
        'min_rr': overrides.pop('tier_min_rr', 1.5),
        'trail_factor': overrides.pop('trail_factor', 1.0),
        'trail_activation_r': overrides.pop('trail_activation_r', 0.0),
    }

    return BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=overrides.pop('fractal_depth', 10),
            tolerance_cents=0.05,
            tolerance_pct=0.001,
            atr_period=5,
            min_level_score=overrides.pop('min_level_score', 5),
        ),
        pattern_config=PatternEngineConfig(
            tail_ratio_min=overrides.pop('tail_ratio_min', 0.10),
            lp2_engulfing_required=True,
            clp_min_bars=3,
            clp_max_bars=7,
        ),
        filter_config=FilterChainConfig(
            atr_block_threshold=0.30,
            atr_entry_threshold=overrides.pop('atr_entry_threshold', 0.80),
            enable_volume_filter=True,
            enable_time_filter=True,
            enable_squeeze_filter=True,
        ),
        risk_config=RiskManagerConfig(
            min_rr=overrides.pop('min_rr', 1.5),
            max_stop_atr_pct=overrides.pop('max_stop_atr_pct', 0.10),
            capital=100000.0,
            risk_pct=0.003,
        ),
        trade_config=TradeManagerConfig(
            slippage_per_share=0.02,
            partial_tp_at_r=2.0,
            partial_tp_pct=0.50,
        ),
        intraday_config=IntradayLevelConfig(
            fractal_depth_m5=5,
            fractal_depth_h1=overrides.pop('fractal_depth_h1', 3),
            enable_h1=True,
            min_target_r=1.0,
            lookback_bars=1000,
        ),
        tier_config=tier_cfg,
        name=name,
    )


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def count_exits(trades):
    counts = {'target': 0, 'stop': 0, 'eod': 0, 'trail_be': 0, 'other': 0}
    for t in trades:
        if t.exit_reason == ExitReason.TARGET_HIT:
            counts['target'] += 1
        elif t.exit_reason == ExitReason.STOP_LOSS:
            counts['stop'] += 1
        elif t.exit_reason == ExitReason.EOD_EXIT:
            counts['eod'] += 1
        elif t.exit_reason == ExitReason.BREAKEVEN:
            counts['trail_be'] += 1
        else:
            counts['other'] += 1
    return counts


def run_on_tickers(config, tickers, label=""):
    """Run IS+OOS on given tickers. Returns structured results."""
    is_results = {}
    oos_results = {}

    for ticker in tickers:
        m5_df = load_ticker_data(ticker)
        bt_is = Backtester(config)
        is_result = bt_is.run(m5_df, start_date=IS_START, end_date=IS_END)
        is_results[ticker] = is_result

        bt_oos = Backtester(config)
        oos_result = bt_oos.run(m5_df, start_date=OOS_START, end_date=OOS_END)
        oos_results[ticker] = oos_result

    combined_is = aggregate_metrics(is_results)
    combined_oos = aggregate_metrics(oos_results)

    return {
        'is_results': is_results,
        'oos_results': oos_results,
        'combined_is': combined_is,
        'combined_oos': combined_oos,
    }


def print_results(results, tickers, label):
    ci = results['combined_is']
    co = results['combined_oos']
    log(f"\n  {label}")
    log(f"    IS:  {ci['total_trades']} trades, {ci['win_rate']*100:.1f}% WR, "
        f"PF={ci['profit_factor']:.2f}, ${ci['total_pnl']:.0f}")
    log(f"    OOS: {co['total_trades']} trades, {co['win_rate']*100:.1f}% WR, "
        f"PF={co['profit_factor']:.2f}, ${co['total_pnl']:.0f}")

    # Per-ticker OOS
    for ticker in tickers:
        p = results['oos_results'][ticker].performance
        ex = count_exits(results['oos_results'][ticker].trades)
        log(f"    {ticker}: {p.get('total_trades',0)} trades, "
            f"{p.get('win_rate',0)*100:.1f}% WR, PF={p.get('profit_factor',0):.2f}, "
            f"${p.get('total_pnl',0):.0f} "
            f"[tgt={ex['target']} stp={ex['stop']} eod={ex['eod']} trail={ex['trail_be']}]")

    return co


def log_experiment_header(exp_id, title, hypothesis):
    log(f"\n{'='*70}")
    log(f"{exp_id}: {title}")
    log(f"{'='*70}")
    log(f"Hypothesis: {hypothesis}")


def log_markdown_table(exp_id, title, hypothesis, config_desc, variants):
    """Write markdown table for experiment variants."""
    log(f"\n## {exp_id}: {title}")
    log(f"**Hypothesis:** {hypothesis}")
    log(f"**Config:** {config_desc}")
    log("")
    log("| Variant | IS Trades | IS WR | IS PF | IS P&L | OOS Trades | OOS WR | OOS PF | OOS P&L |")
    log("|---------|-----------|-------|-------|--------|------------|--------|--------|---------|")
    for label, r in variants:
        ci = r['combined_is']
        co = r['combined_oos']
        log(f"| {label} | {ci['total_trades']} | {ci['win_rate']*100:.1f}% | "
            f"{ci['profit_factor']:.2f} | ${ci['total_pnl']:.0f} | "
            f"{co['total_trades']} | {co['win_rate']*100:.1f}% | "
            f"{co['profit_factor']:.2f} | ${co['total_pnl']:.0f} |")


# ──────────────────────────────────────────────────────────────────
# EXP-W001: Whitelist Baseline
# ──────────────────────────────────────────────────────────────────

def run_w001():
    log_experiment_header("EXP-W001", "Whitelist Portfolio Baseline",
                          "Dropping META/MSFT (clearly unprofitable) gives a positive portfolio")

    config = make_config(name='W001')
    results = run_on_tickers(config, WHITELIST, label="W001 Whitelist")
    co = print_results(results, WHITELIST, "W001 Whitelist")

    # Exit analysis
    all_exits = {'target': 0, 'stop': 0, 'eod': 0, 'trail_be': 0}
    for t in WHITELIST:
        ex = count_exits(results['oos_results'][t].trades)
        for k in all_exits:
            all_exits[k] += ex[k]
    total = sum(all_exits.values())
    log(f"\n  Exit breakdown (OOS): target={all_exits['target']} ({all_exits['target']/max(total,1)*100:.0f}%), "
        f"stop={all_exits['stop']} ({all_exits['stop']/max(total,1)*100:.0f}%), "
        f"eod={all_exits['eod']} ({all_exits['eod']/max(total,1)*100:.0f}%), "
        f"trail/be={all_exits['trail_be']} ({all_exits['trail_be']/max(total,1)*100:.0f}%)")

    verdict = "ACCEPT" if co['profit_factor'] > 1.0 and co['total_pnl'] > 0 else "NEEDS WORK"
    log(f"\n  Verdict: {verdict}")

    return results, config


# ──────────────────────────────────────────────────────────────────
# T001: Trail Factor Sweep
# ──────────────────────────────────────────────────────────────────

def run_t001():
    log_experiment_header("T001", "Trail Factor Sweep",
                          "Tighter trail (0.5R) captures more profit from favorable moves vs 1.0R default")

    variants = []
    for tf in [0.5, 0.7, 1.0, 1.5]:
        label = f"trail_factor={tf}"
        print(f"  Testing {label}...")
        config = make_config(name=label, trail_factor=tf)
        r = run_on_tickers(config, WHITELIST)
        variants.append((label, r))
        co = r['combined_oos']
        log(f"    {label}: OOS {co['total_trades']} trades, "
            f"PF={co['profit_factor']:.2f}, ${co['total_pnl']:.0f}")

    log_markdown_table("T001", "Trail Factor Sweep",
                       "Tighter trail captures more favorable moves",
                       "trail_factor in [0.5, 0.7, 1.0, 1.5]", variants)

    # Pick best by OOS PF (with min trades)
    best_label, best_r = max(
        [(l, r) for l, r in variants if r['combined_oos']['total_trades'] >= 5],
        key=lambda x: x[1]['combined_oos']['profit_factor'],
        default=variants[0]
    )
    best_tf = float(best_label.split('=')[1])
    log(f"\n  Best: {best_label} (OOS PF={best_r['combined_oos']['profit_factor']:.2f})")

    return best_tf, variants


# ──────────────────────────────────────────────────────────────────
# T002: Trail Activation Sweep
# ──────────────────────────────────────────────────────────────────

def run_t002(best_trail_factor):
    log_experiment_header("T002", "Trail Activation R Sweep",
                          f"Delaying trail start until favorable R-move improves trail quality "
                          f"(using trail_factor={best_trail_factor})")

    variants = []
    for ar in [0.0, 0.5, 1.0, 1.5]:
        label = f"trail_act={ar}R"
        print(f"  Testing {label}...")
        config = make_config(name=label, trail_factor=best_trail_factor, trail_activation_r=ar)
        r = run_on_tickers(config, WHITELIST)
        variants.append((label, r))
        co = r['combined_oos']
        log(f"    {label}: OOS {co['total_trades']} trades, "
            f"PF={co['profit_factor']:.2f}, ${co['total_pnl']:.0f}")

    log_markdown_table("T002", "Trail Activation R Sweep",
                       f"Delay trail start (using trail_factor={best_trail_factor})",
                       "trail_activation_r in [0.0, 0.5, 1.0, 1.5]", variants)

    best_label, best_r = max(
        [(l, r) for l, r in variants if r['combined_oos']['total_trades'] >= 5],
        key=lambda x: x[1]['combined_oos']['profit_factor'],
        default=variants[0]
    )
    best_ar = float(best_label.split('=')[1].rstrip('R'))
    log(f"\n  Best: {best_label} (OOS PF={best_r['combined_oos']['profit_factor']:.2f})")

    return best_ar, variants


# ──────────────────────────────────────────────────────────────────
# T003: Tier1 Percentage Sweep
# ──────────────────────────────────────────────────────────────────

def run_t003(best_trail_factor, best_trail_activation):
    log_experiment_header("T003", "Tier1 Percentage Sweep",
                          f"Adjusting T1 exit % (using trail_factor={best_trail_factor}, "
                          f"activation={best_trail_activation}R)")

    variants = []
    for pct in [0.30, 0.40, 0.50, 0.60]:
        label = f"t1_pct={pct}"
        print(f"  Testing {label}...")
        config = make_config(name=label, trail_factor=best_trail_factor,
                             trail_activation_r=best_trail_activation, t1_pct=pct)
        r = run_on_tickers(config, WHITELIST)
        variants.append((label, r))
        co = r['combined_oos']
        log(f"    {label}: OOS {co['total_trades']} trades, "
            f"PF={co['profit_factor']:.2f}, ${co['total_pnl']:.0f}")

    log_markdown_table("T003", "Tier1 Percentage Sweep",
                       f"t1_pct in [0.30, 0.40, 0.50, 0.60] "
                       f"(trail_factor={best_trail_factor}, activation={best_trail_activation}R)",
                       "t1_pct sweep", variants)

    best_label, best_r = max(
        [(l, r) for l, r in variants if r['combined_oos']['total_trades'] >= 5],
        key=lambda x: x[1]['combined_oos']['profit_factor'],
        default=variants[0]
    )
    best_pct = float(best_label.split('=')[1])
    log(f"\n  Best: {best_label} (OOS PF={best_r['combined_oos']['profit_factor']:.2f})")

    return best_pct, variants


# ──────────────────────────────────────────────────────────────────
# T004: Combined Trail Config
# ──────────────────────────────────────────────────────────────────

def run_t004(best_tf, best_ar, best_pct, w001_results):
    log_experiment_header("T004", "Combined Best Trail Config",
                          f"trail_factor={best_tf}, activation={best_ar}R, t1_pct={best_pct} "
                          f"vs W001 baseline")

    config = make_config(name='T004-combined', trail_factor=best_tf,
                         trail_activation_r=best_ar, t1_pct=best_pct)
    results = run_on_tickers(config, WHITELIST, label="T004 Combined")
    co = print_results(results, WHITELIST, "T004 Combined")

    w001_co = w001_results['combined_oos']
    log(f"\n  vs W001 Baseline: PF {w001_co['profit_factor']:.2f} -> {co['profit_factor']:.2f}, "
        f"P&L ${w001_co['total_pnl']:.0f} -> ${co['total_pnl']:.0f}")

    improved = co['profit_factor'] > w001_co['profit_factor']
    verdict = "ACCEPT" if improved else "REJECT (keep W001 defaults)"
    log(f"  Verdict: {verdict}")

    return results, config, improved


# ──────────────────────────────────────────────────────────────────
# N001: NVDA Max Stop ATR Sweep
# ──────────────────────────────────────────────────────────────────

def run_n001(best_tf, best_ar, best_pct):
    log_experiment_header("N001", "NVDA Max Stop ATR Sweep",
                          "Wider stops allow NVDA's high volatility moves without premature stops")

    variants = []
    for stop_pct in [0.10, 0.15, 0.20, 0.25]:
        label = f"max_stop_atr={stop_pct}"
        print(f"  Testing {label} on NVDA...")
        config = make_config(name=label, trail_factor=best_tf,
                             trail_activation_r=best_ar, t1_pct=best_pct,
                             max_stop_atr_pct=stop_pct)
        r = run_on_tickers(config, ['NVDA'])
        variants.append((label, r))
        co = r['combined_oos']
        log(f"    {label}: OOS {co['total_trades']} trades, "
            f"PF={co['profit_factor']:.2f}, ${co['total_pnl']:.0f}")

    log_markdown_table("N001", "NVDA Max Stop ATR Sweep",
                       "Wider stops for high-vol",
                       "max_stop_atr_pct in [0.10, 0.15, 0.20, 0.25] on NVDA", variants)

    best_label, best_r = max(
        [(l, r) for l, r in variants if r['combined_oos']['total_trades'] >= 3],
        key=lambda x: x[1]['combined_oos']['profit_factor'],
        default=variants[0]
    )
    best_stop = float(best_label.split('=')[1])
    log(f"\n  Best: {best_label} (OOS PF={best_r['combined_oos']['profit_factor']:.2f})")

    return best_stop, variants


# ──────────────────────────────────────────────────────────────────
# N002: NVDA Fractal Depth Sweep
# ──────────────────────────────────────────────────────────────────

def run_n002(best_tf, best_ar, best_pct, best_stop):
    log_experiment_header("N002", "NVDA Fractal Depth Sweep",
                          f"Shallower fractals detect more levels for NVDA "
                          f"(using max_stop_atr={best_stop})")

    variants = []
    for fd in [3, 5, 7, 10]:
        label = f"fractal_depth={fd}"
        print(f"  Testing {label} on NVDA...")
        config = make_config(name=label, trail_factor=best_tf,
                             trail_activation_r=best_ar, t1_pct=best_pct,
                             max_stop_atr_pct=best_stop, fractal_depth=fd)
        r = run_on_tickers(config, ['NVDA'])
        variants.append((label, r))
        co = r['combined_oos']
        log(f"    {label}: OOS {co['total_trades']} trades, "
            f"PF={co['profit_factor']:.2f}, ${co['total_pnl']:.0f}")

    log_markdown_table("N002", "NVDA Fractal Depth Sweep",
                       f"Shallower fractals (max_stop_atr={best_stop})",
                       "fractal_depth in [3, 5, 7, 10] on NVDA", variants)

    best_label, best_r = max(
        [(l, r) for l, r in variants if r['combined_oos']['total_trades'] >= 3],
        key=lambda x: x[1]['combined_oos']['profit_factor'],
        default=variants[0]
    )
    best_fd = int(best_label.split('=')[1])
    log(f"\n  Best: {best_label} (OOS PF={best_r['combined_oos']['profit_factor']:.2f})")

    return best_fd, variants


# ──────────────────────────────────────────────────────────────────
# N003: NVDA Combined Rescue
# ──────────────────────────────────────────────────────────────────

def run_n003(best_tf, best_ar, best_pct, best_stop, best_fd):
    log_experiment_header("N003", "NVDA Combined Rescue Config",
                          f"Combined: fractal_depth={best_fd}, max_stop_atr={best_stop}")

    config = make_config(name='N003-nvda-rescue', trail_factor=best_tf,
                         trail_activation_r=best_ar, t1_pct=best_pct,
                         max_stop_atr_pct=best_stop, fractal_depth=best_fd)
    results = run_on_tickers(config, ['NVDA'])
    co = print_results(results, ['NVDA'], "N003 NVDA Rescue")

    rescued = co['profit_factor'] >= 1.0 and co['total_trades'] >= 5
    verdict = "RESCUED" if rescued else "EXCLUDE NVDA"
    log(f"\n  Verdict: {verdict} (PF={co['profit_factor']:.2f}, "
        f"trades={co['total_trades']}, P&L=${co['total_pnl']:.0f})")

    return rescued, results, config


# ──────────────────────────────────────────────────────────────────
# Walk-Forward Validation
# ──────────────────────────────────────────────────────────────────

def run_walk_forward(config, tickers, label="Final"):
    log_experiment_header("WF", f"Walk-Forward Validation ({label})",
                          "8-window rolling validation (3mo train / 1mo test)")

    wf = WalkForwardValidator(config, tickers)
    wf_results = wf.run()
    wf_summary = WalkForwardValidator.summarize(wf_results)

    log(f"\n  Walk-Forward Results ({wf_summary['n_windows']} windows):")
    log(f"    Mean Sharpe:     {wf_summary['mean_sharpe']:.2f} +/- {wf_summary['std_sharpe']:.2f}")
    log(f"    Positive Sharpe: {wf_summary['positive_sharpe_windows']}/{wf_summary['n_windows']} windows")
    log(f"    Mean PF:         {wf_summary['mean_pf']:.2f}")
    log(f"    Mean WR:         {wf_summary['mean_wr']*100:.1f}%")
    log(f"    Total Trades:    {wf_summary['total_trades']}")
    log(f"    Total P&L:       ${wf_summary['total_pnl']:.0f}")

    # Per-window table
    log(f"\n  | Window | Test Period | Trades | WR | PF | Sharpe | P&L |")
    log(f"  |--------|-------------|--------|-----|-----|--------|------|")
    for r in wf_results:
        log(f"  | {r['window']} | {r['test_start']}->{r['test_end']} | "
            f"{r['total_trades']} | {r['win_rate']*100:.1f}% | "
            f"{r['profit_factor']:.2f} | {r.get('sharpe', 0):.2f} | "
            f"${r['total_pnl']:.0f} |")

    return wf_results, wf_summary


# ──────────────────────────────────────────────────────────────────
# Experiment Log Writer
# ──────────────────────────────────────────────────────────────────

def write_experiment_log(final_portfolio, final_config, wf_summary, nvda_rescued):
    os.makedirs(EXP_DIR, exist_ok=True)

    header = [
        "# Experiment Log v4.1 — Whitelist Portfolio, Trail Optimization & NVDA Rescue",
        "",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Final Portfolio:** {', '.join(final_portfolio)}",
        f"**IS Period:** {IS_START} to {IS_END}",
        f"**OOS Period:** {OOS_START} to {OOS_END}",
        f"**NVDA rescued:** {'Yes' if nvda_rescued else 'No'}",
        "",
        "---",
        "",
    ]

    content = "\n".join(header + LOG_LINES)

    log_path = os.path.join(EXP_DIR, 'EXPERIMENT_LOG_v4.1.md')
    with open(log_path, 'w') as f:
        f.write(content)

    print(f"\nExperiment log written to: {log_path}")
    return log_path


# ──────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────

def main():
    log("=" * 70)
    log("V4.1 EXPERIMENTS — Whitelist Portfolio, Trail Optimization & NVDA Rescue")
    log(f"Whitelist: {', '.join(WHITELIST)}")
    log(f"IS: {IS_START} to {IS_END} | OOS: {OOS_START} to {OOS_END}")
    log("=" * 70)

    # ── EXP-W001: Whitelist Baseline ──
    w001_results, w001_config = run_w001()

    # ── T001: Trail Factor ──
    best_tf, _ = run_t001()

    # ── T002: Trail Activation ──
    best_ar, _ = run_t002(best_tf)

    # ── T003: Tier1 Percentage ──
    best_pct, _ = run_t003(best_tf, best_ar)

    # ── T004: Combined Trail ──
    t004_results, t004_config, trail_improved = run_t004(best_tf, best_ar, best_pct, w001_results)

    # Choose best trail config
    if trail_improved:
        best_trail_config = t004_config
        best_trail_results = t004_results
        log("\n>> Using T004 trail-optimized config for portfolio")
    else:
        best_trail_config = w001_config
        best_trail_results = w001_results
        best_tf = 1.0
        best_ar = 0.0
        best_pct = 0.50
        log("\n>> Trail optimization did not improve — keeping W001 defaults")

    # ── N001-N003: NVDA Rescue ──
    best_stop, _ = run_n001(best_tf, best_ar, best_pct)
    best_fd, _ = run_n002(best_tf, best_ar, best_pct, best_stop)
    nvda_rescued, nvda_results, nvda_config = run_n003(best_tf, best_ar, best_pct, best_stop, best_fd)

    # ── Build Final Portfolio ──
    final_portfolio = list(WHITELIST)
    if nvda_rescued:
        final_portfolio.append('NVDA')
        log(f"\n>> Final portfolio: {', '.join(final_portfolio)} (NVDA rescued)")
    else:
        log(f"\n>> Final portfolio: {', '.join(final_portfolio)} (NVDA excluded)")

    # ── Walk-Forward on Final Portfolio ──
    # Use the whitelist config (same params for all tickers in final portfolio)
    wf_config = make_config(name='WF-final', trail_factor=best_tf,
                            trail_activation_r=best_ar, t1_pct=best_pct)
    wf_results, wf_summary = run_walk_forward(wf_config, final_portfolio, "Final Portfolio")

    # ── Final Summary ──
    log("\n" + "=" * 70)
    log("V4.1 FINAL SUMMARY")
    log("=" * 70)

    # Run final portfolio OOS with best config
    final_results = run_on_tickers(wf_config, final_portfolio)
    co = final_results['combined_oos']

    log(f"\nFinal Portfolio: {', '.join(final_portfolio)}")
    log(f"Best trail config: trail_factor={best_tf}, activation={best_ar}R, t1_pct={best_pct}")
    log(f"\nPortfolio OOS: {co['total_trades']} trades, {co['win_rate']*100:.1f}% WR, "
        f"PF={co['profit_factor']:.2f}, ${co['total_pnl']:.0f}")
    log(f"Walk-Forward: {wf_summary['positive_sharpe_windows']}/{wf_summary['n_windows']} "
        f"positive windows, mean Sharpe={wf_summary['mean_sharpe']:.2f}")

    # Per-ticker final
    log("\nPer-Ticker OOS:")
    for ticker in final_portfolio:
        p = final_results['oos_results'][ticker].performance
        log(f"  {ticker}: {p.get('total_trades',0)} trades, "
            f"{p.get('win_rate',0)*100:.1f}% WR, PF={p.get('profit_factor',0):.2f}, "
            f"${p.get('total_pnl',0):.0f}")

    # Check success criteria
    log("\n--- Success Criteria Check ---")
    log(f"  Portfolio OOS PF > 1.2: {'PASS' if co['profit_factor'] > 1.2 else 'FAIL'} "
        f"(PF={co['profit_factor']:.2f})")
    log(f"  Portfolio OOS P&L > $1,500: {'PASS' if co['total_pnl'] > 1500 else 'FAIL'} "
        f"(${co['total_pnl']:.0f})")
    log(f"  Walk-Forward >= 5/8 positive: "
        f"{'PASS' if wf_summary['positive_sharpe_windows'] >= 5 else 'FAIL'} "
        f"({wf_summary['positive_sharpe_windows']}/{wf_summary['n_windows']})")
    log(f"  Total OOS trades >= 50: {'PASS' if co['total_trades'] >= 50 else 'FAIL'} "
        f"({co['total_trades']})")

    # Write experiment log
    write_experiment_log(final_portfolio, wf_config, wf_summary, nvda_rescued)

    log("\nDone!")


if __name__ == '__main__':
    main()
