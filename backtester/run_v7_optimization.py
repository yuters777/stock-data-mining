"""
Phase 7A — Direction-Specific Parameter Optimization

LP-001→LP-007: TSLA LONG parameter sweeps
SP-001→SP-007: SHORT ticker (AAPL/AMZN/GOOGL) parameter sweeps
Combine winners → IS/OOS/WF on full portfolio

Phase 7B — Universe Expansion
X-001→X-003: META/MSFT/NVDA as SHORT additions

Phase 7C — Final Portfolio Walk-Forward
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from copy import deepcopy

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

TSLA_TICKERS = ['TSLA']
SHORT_TICKERS = ['AAPL', 'AMZN', 'GOOGL']
ALL_TICKERS = ['AAPL', 'AMZN', 'GOOGL', 'TSLA']
EXPANSION_TICKERS = ['META', 'MSFT', 'NVDA']

IS_START = '2025-02-10'
IS_END = '2025-10-01'
OOS_START = '2025-10-01'
OOS_END = '2026-01-31'

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

LOG_LINES = []  # accumulate full experiment log


def log(msg=''):
    LOG_LINES.append(msg)
    print(msg)


# ──────────────────────────────────────────────────────────────────
# Config builder
# ──────────────────────────────────────────────────────────────────

def make_config(name='v7', direction_filter=None, **overrides) -> BacktestConfig:
    """Build config with optional overrides for any parameter."""
    level_kw = {
        'fractal_depth': overrides.get('fractal_depth', 10),
        'tolerance_cents': 0.05, 'tolerance_pct': 0.001,
        'atr_period': 5, 'min_level_score': 5,
    }
    pattern_kw = {
        'tail_ratio_min': overrides.get('tail_ratio_min', 0.10),
        'lp2_engulfing_required': True, 'clp_min_bars': 3, 'clp_max_bars': 7,
    }
    filter_kw = {
        'atr_block_threshold': 0.30,
        'atr_entry_threshold': overrides.get('atr_entry_threshold', 0.80),
        'enable_volume_filter': True, 'enable_time_filter': True,
        'enable_squeeze_filter': True,
    }
    risk_kw = {
        'min_rr': overrides.get('min_rr', 1.5),
        'max_stop_atr_pct': overrides.get('max_stop_atr_pct', 0.10),
        'capital': 100000.0, 'risk_pct': 0.003,
    }
    tier = {
        'mode': '2tier_trail',
        't1_pct': overrides.get('t1_pct', 0.30),
        'min_rr': overrides.get('min_rr', 1.5),
        'trail_factor': overrides.get('trail_factor', 0.7),
        'trail_activation_r': 0.0,
    }

    return BacktestConfig(
        level_config=LevelDetectorConfig(**level_kw),
        pattern_config=PatternEngineConfig(**pattern_kw),
        filter_config=FilterChainConfig(**filter_kw),
        risk_config=RiskManagerConfig(**risk_kw),
        trade_config=TradeManagerConfig(
            slippage_per_share=0.02, partial_tp_at_r=2.0, partial_tp_pct=0.50,
        ),
        intraday_config=IntradayLevelConfig(
            fractal_depth_m5=5, fractal_depth_h1=3, enable_h1=True,
            min_target_r=1.0, lookback_bars=1000,
        ),
        tier_config=tier,
        direction_filter=direction_filter,
        name=name,
    )


def run_is_oos(config, tickers):
    """Run IS + OOS for given tickers, return combined metrics."""
    is_results = {}
    oos_results = {}
    for ticker in tickers:
        m5_df = load_ticker_data(ticker)
        is_results[ticker] = run_single_backtest(config, m5_df, IS_START, IS_END)
        oos_results[ticker] = run_single_backtest(config, m5_df, OOS_START, OOS_END)
    return aggregate_metrics(is_results), aggregate_metrics(oos_results), is_results, oos_results


def ticker_stats(result):
    trades = result.trades
    if not trades:
        return {'trades': 0, 'wr': 0, 'pf': 0, 'pnl': 0}
    w = [t for t in trades if t.pnl > 0]
    l = [t for t in trades if t.pnl <= 0]
    gp = sum(t.pnl for t in w)
    gl = abs(sum(t.pnl for t in l))
    return {
        'trades': len(trades),
        'wr': len(w) / len(trades),
        'pf': gp / gl if gl > 0 else float('inf'),
        'pnl': sum(t.pnl for t in trades),
    }


# ──────────────────────────────────────────────────────────────────
# Parameter sweep engine
# ──────────────────────────────────────────────────────────────────

def run_param_sweep(series_prefix, param_name, values, tickers, direction_filter,
                    baseline_overrides=None):
    """
    Sweep one parameter. Returns list of results sorted by IS PF.
    Each result: {exp_id, param_value, is_metrics, oos_metrics, ...}
    """
    baseline_overrides = baseline_overrides or {}
    results = []

    log(f"\n{'='*60}")
    log(f"  {series_prefix}: {param_name} sweep  ({', '.join(tickers)})")
    log(f"  Values: {values}")
    log(f"{'='*60}")

    for i, val in enumerate(values):
        exp_id = f"{series_prefix}-{i+1:03d}"
        overrides = dict(baseline_overrides)
        overrides[param_name] = val
        config = make_config(name=exp_id, direction_filter=direction_filter, **overrides)

        cis, coos, is_r, oos_r = run_is_oos(config, tickers)

        marker = " <-- baseline" if val == baseline_overrides.get(param_name, {
            'fractal_depth': 10, 'tail_ratio_min': 0.10, 'atr_entry_threshold': 0.80,
            'min_rr': 1.5, 'max_stop_atr_pct': 0.10, 'trail_factor': 0.7, 't1_pct': 0.30,
        }.get(param_name)) else ""

        log(f"  {param_name}={val:>5}: IS {cis['total_trades']}t PF={cis['profit_factor']:.2f} "
            f"${cis['total_pnl']:.0f} | OOS {coos['total_trades']}t PF={coos['profit_factor']:.2f} "
            f"${coos['total_pnl']:.0f}{marker}")

        results.append({
            'exp_id': exp_id,
            'param_name': param_name,
            'param_value': val,
            'is_metrics': cis,
            'oos_metrics': coos,
            'is_results': is_r,
            'oos_results': oos_r,
        })

    # Pick best by IS PF (with min trade count)
    viable = [r for r in results if r['is_metrics']['total_trades'] >= 5]
    if not viable:
        # If no variant has >=5 IS trades, use OOS PF
        viable = [r for r in results if r['oos_metrics']['total_trades'] >= 5]
        if viable:
            viable.sort(key=lambda r: r['oos_metrics']['profit_factor'], reverse=True)
            log(f"  ** No variant has >=5 IS trades. Picking by OOS PF (caution).")
        else:
            # Fall back to all results, pick by OOS trades
            viable = results
            viable.sort(key=lambda r: r['oos_metrics']['total_pnl'], reverse=True)
            log(f"  ** Very few trades. Picking by OOS P&L.")
    else:
        viable.sort(key=lambda r: r['is_metrics']['profit_factor'], reverse=True)

    best = viable[0]
    log(f"  >> BEST: {param_name}={best['param_value']} "
        f"(IS PF={best['is_metrics']['profit_factor']:.2f}, "
        f"OOS PF={best['oos_metrics']['profit_factor']:.2f})")

    return results, best


# ──────────────────────────────────────────────────────────────────
# Phase 7A: LP series (TSLA LONG)
# ──────────────────────────────────────────────────────────────────

def run_phase_7a_lp():
    """Run LP-001 through LP-007 for TSLA LONG."""
    log("\n" + "#"*60)
    log("  PHASE 7A — TSLA LONG Parameter Optimization (LP series)")
    log("#"*60)

    direction_filter = 'long'
    tickers = TSLA_TICKERS
    winners = {}

    sweeps = [
        ('LP-001', 'fractal_depth',      [5, 7, 10, 15]),
        ('LP-002', 'tail_ratio_min',     [0.05, 0.10, 0.15, 0.20]),
        ('LP-003', 'atr_entry_threshold',[0.60, 0.70, 0.80, 0.90]),
        ('LP-004', 'min_rr',             [1.0, 1.5, 2.0, 2.5]),
        ('LP-005', 'max_stop_atr_pct',   [0.05, 0.08, 0.10, 0.15]),
        ('LP-006', 'trail_factor',       [0.5, 0.7, 0.9, 1.0]),
        ('LP-007', 't1_pct',            [0.20, 0.30, 0.40, 0.50]),
    ]

    for prefix, param, values in sweeps:
        _, best = run_param_sweep(prefix, param, values, tickers, direction_filter)
        winners[param] = best['param_value']

    log(f"\n  LP WINNERS: {winners}")
    return winners


# ──────────────────────────────────────────────────────────────────
# Phase 7A: SP series (SHORT tickers)
# ──────────────────────────────────────────────────────────────────

def run_phase_7a_sp():
    """Run SP-001 through SP-007 for AAPL/AMZN/GOOGL SHORT."""
    log("\n" + "#"*60)
    log("  PHASE 7A — SHORT Ticker Parameter Optimization (SP series)")
    log("#"*60)

    direction_filter = 'short'
    tickers = SHORT_TICKERS
    winners = {}

    sweeps = [
        ('SP-001', 'fractal_depth',      [5, 7, 10, 15]),
        ('SP-002', 'tail_ratio_min',     [0.05, 0.10, 0.15, 0.20]),
        ('SP-003', 'atr_entry_threshold',[0.60, 0.70, 0.80, 0.90]),
        ('SP-004', 'min_rr',             [1.0, 1.5, 2.0, 2.5]),
        ('SP-005', 'max_stop_atr_pct',   [0.05, 0.08, 0.10, 0.15]),
        ('SP-006', 'trail_factor',       [0.5, 0.7, 0.9, 1.0]),
        ('SP-007', 't1_pct',            [0.20, 0.30, 0.40, 0.50]),
    ]

    for prefix, param, values in sweeps:
        _, best = run_param_sweep(prefix, param, values, tickers, direction_filter)
        winners[param] = best['param_value']

    log(f"\n  SP WINNERS: {winners}")
    return winners


# ──────────────────────────────────────────────────────────────────
# Combine winners
# ──────────────────────────────────────────────────────────────────

def run_combined(lp_winners, sp_winners):
    """Run combined config: TSLA with LP params, SHORT tickers with SP params.
    Since BacktestConfig is per-run and tickers are run independently,
    we run TSLA with LP config and SHORT tickers with SP config, then merge."""
    log("\n" + "#"*60)
    log("  COMBINED WINNERS — Full Portfolio Test")
    log("#"*60)

    # TSLA with LP winners
    lp_config = make_config(name='v7_LP_combined', direction_filter='long', **lp_winners)
    sp_config = make_config(name='v7_SP_combined', direction_filter='short', **sp_winners)

    # Also build L-005 baseline for comparison
    baseline_config = make_config(name='v6_L005_baseline',
                                   direction_filter={'TSLA': 'long', 'DEFAULT': 'short'})

    # --- Combined IS/OOS ---
    log("\n  Running combined IS/OOS...")

    # TSLA LONG
    tsla_data = load_ticker_data('TSLA')
    tsla_is = run_single_backtest(lp_config, tsla_data, IS_START, IS_END)
    tsla_oos = run_single_backtest(lp_config, tsla_data, OOS_START, OOS_END)

    # SHORT tickers
    short_is = {}
    short_oos = {}
    for ticker in SHORT_TICKERS:
        m5_df = load_ticker_data(ticker)
        short_is[ticker] = run_single_backtest(sp_config, m5_df, IS_START, IS_END)
        short_oos[ticker] = run_single_backtest(sp_config, m5_df, OOS_START, OOS_END)

    # Merge
    all_is = dict(short_is)
    all_is['TSLA'] = tsla_is
    all_oos = dict(short_oos)
    all_oos['TSLA'] = tsla_oos

    combined_is = aggregate_metrics(all_is)
    combined_oos = aggregate_metrics(all_oos)

    log(f"\n  COMBINED IS:  {combined_is['total_trades']}t PF={combined_is['profit_factor']:.2f} "
        f"${combined_is['total_pnl']:.0f}")
    log(f"  COMBINED OOS: {combined_oos['total_trades']}t PF={combined_oos['profit_factor']:.2f} "
        f"${combined_oos['total_pnl']:.0f}")

    for ticker in ALL_TICKERS:
        s = ticker_stats(all_oos[ticker])
        log(f"    {ticker} OOS: {s['trades']}t PF={s['pf']:.2f} ${s['pnl']:.0f}")

    # Baseline comparison
    log("\n  Running L-005 baseline IS/OOS for comparison...")
    bl_is_r = {}
    bl_oos_r = {}
    for ticker in ALL_TICKERS:
        m5_df = load_ticker_data(ticker)
        bl_is_r[ticker] = run_single_backtest(baseline_config, m5_df, IS_START, IS_END)
        bl_oos_r[ticker] = run_single_backtest(baseline_config, m5_df, OOS_START, OOS_END)
    bl_is = aggregate_metrics(bl_is_r)
    bl_oos = aggregate_metrics(bl_oos_r)
    log(f"  BASELINE IS:  {bl_is['total_trades']}t PF={bl_is['profit_factor']:.2f} "
        f"${bl_is['total_pnl']:.0f}")
    log(f"  BASELINE OOS: {bl_oos['total_trades']}t PF={bl_oos['profit_factor']:.2f} "
        f"${bl_oos['total_pnl']:.0f}")

    # --- Walk-forward ---
    log("\n  Running combined walk-forward...")
    # WF needs separate runs for TSLA (LP config) and SHORT tickers (SP config)
    wf_lp = WalkForwardValidator(lp_config, TSLA_TICKERS)
    wf_sp = WalkForwardValidator(sp_config, SHORT_TICKERS)

    lp_wf_results = wf_lp.run()
    sp_wf_results = wf_sp.run()

    # Merge window-by-window
    combined_wf = []
    for i in range(min(len(lp_wf_results), len(sp_wf_results))):
        lp_w = lp_wf_results[i]
        sp_w = sp_wf_results[i]
        merged = {
            'total_trades': lp_w['total_trades'] + sp_w['total_trades'],
            'total_pnl': lp_w['total_pnl'] + sp_w['total_pnl'],
            'win_rate': ((lp_w['win_rate'] * lp_w['total_trades'] +
                         sp_w['win_rate'] * sp_w['total_trades']) /
                        max(lp_w['total_trades'] + sp_w['total_trades'], 1)),
            'profit_factor': 0,
            'sharpe': (lp_w.get('sharpe', 0) + sp_w.get('sharpe', 0)) / 2,
            'window': i + 1,
            'test_start': lp_w.get('test_start', sp_w.get('test_start', '')),
            'test_end': lp_w.get('test_end', sp_w.get('test_end', '')),
        }
        # Recompute PF from gross
        gp = lp_w.get('gross_profit', 0) + sp_w.get('gross_profit', 0)
        gl = lp_w.get('gross_loss', 0) + sp_w.get('gross_loss', 0)
        merged['profit_factor'] = gp / gl if gl > 0 else float('inf')
        combined_wf.append(merged)

    wf_summary = WalkForwardValidator.summarize(combined_wf)

    log(f"\n  COMBINED WF: {wf_summary['positive_sharpe_windows']}/{wf_summary['n_windows']} positive, "
        f"mean Sharpe={wf_summary['mean_sharpe']:.2f}, total P&L=${wf_summary['total_pnl']:.0f}")

    for w in combined_wf:
        marker = "+" if w.get('sharpe', 0) > 0 else "-"
        log(f"    W{w['window']}: {w['test_start']}→{w['test_end']} "
            f"{w['total_trades']}t PF={w['profit_factor']:.2f} "
            f"${w['total_pnl']:.0f} [{marker}]")

    # Baseline WF
    log("\n  Running L-005 baseline walk-forward for comparison...")
    bl_wf = WalkForwardValidator(baseline_config, ALL_TICKERS)
    bl_wf_results = bl_wf.run()
    bl_wf_summary = WalkForwardValidator.summarize(bl_wf_results)
    log(f"  BASELINE WF: {bl_wf_summary['positive_sharpe_windows']}/{bl_wf_summary['n_windows']} positive, "
        f"mean Sharpe={bl_wf_summary['mean_sharpe']:.2f}, total P&L=${bl_wf_summary['total_pnl']:.0f}")

    return {
        'lp_winners': lp_winners,
        'sp_winners': sp_winners,
        'combined_is': combined_is,
        'combined_oos': combined_oos,
        'all_is': all_is,
        'all_oos': all_oos,
        'combined_wf': combined_wf,
        'wf_summary': wf_summary,
        'baseline_is': bl_is,
        'baseline_oos': bl_oos,
        'baseline_wf_summary': bl_wf_summary,
        'baseline_wf_results': bl_wf_results,
        'lp_config': lp_config,
        'sp_config': sp_config,
    }


# ──────────────────────────────────────────────────────────────────
# Phase 7B: Expansion
# ──────────────────────────────────────────────────────────────────

def run_expansion(sp_winners, combined_result):
    """Test META/MSFT/NVDA as SHORT additions."""
    log("\n" + "#"*60)
    log("  PHASE 7B — Universe Expansion (SHORT)")
    log("#"*60)

    sp_config = make_config(name='v7_expansion', direction_filter='short', **sp_winners)
    accepted = []

    for ticker in EXPANSION_TICKERS:
        try:
            m5_df = load_ticker_data(ticker)
        except FileNotFoundError:
            log(f"\n  {ticker}: DATA NOT FOUND — skipping")
            continue

        is_result = run_single_backtest(sp_config, m5_df, IS_START, IS_END)
        oos_result = run_single_backtest(sp_config, m5_df, OOS_START, OOS_END)

        is_s = ticker_stats(is_result)
        oos_s = ticker_stats(oos_result)

        accept = oos_s['pf'] >= 1.0 and oos_s['trades'] >= 5
        marker = "ACCEPT" if accept else "REJECT"

        log(f"\n  X-{EXPANSION_TICKERS.index(ticker)+1:03d}: {ticker} SHORT")
        log(f"    IS:  {is_s['trades']}t PF={is_s['pf']:.2f} ${is_s['pnl']:.0f}")
        log(f"    OOS: {oos_s['trades']}t PF={oos_s['pf']:.2f} ${oos_s['pnl']:.0f}")
        log(f"    >> {marker}")

        if accept:
            accepted.append(ticker)

    log(f"\n  EXPANSION ACCEPTED: {accepted if accepted else 'NONE'}")
    return accepted


# ──────────────────────────────────────────────────────────────────
# Phase 7C: Final portfolio WF
# ──────────────────────────────────────────────────────────────────

def run_final_portfolio(lp_winners, sp_winners, expansion_tickers, combined_result):
    """Final portfolio walk-forward with all accepted tickers."""
    final_short = SHORT_TICKERS + expansion_tickers
    final_all = final_short + TSLA_TICKERS

    log("\n" + "#"*60)
    log(f"  PHASE 7C — Final Portfolio Walk-Forward")
    log(f"  TSLA LONG + {', '.join(final_short)} SHORT")
    log("#"*60)

    lp_config = make_config(name='v7_final_LP', direction_filter='long', **lp_winners)
    sp_config = make_config(name='v7_final_SP', direction_filter='short', **sp_winners)

    # IS/OOS
    all_is = {}
    all_oos = {}

    tsla_data = load_ticker_data('TSLA')
    all_is['TSLA'] = run_single_backtest(lp_config, tsla_data, IS_START, IS_END)
    all_oos['TSLA'] = run_single_backtest(lp_config, tsla_data, OOS_START, OOS_END)

    for ticker in final_short:
        m5_df = load_ticker_data(ticker)
        all_is[ticker] = run_single_backtest(sp_config, m5_df, IS_START, IS_END)
        all_oos[ticker] = run_single_backtest(sp_config, m5_df, OOS_START, OOS_END)

    combined_is = aggregate_metrics(all_is)
    combined_oos = aggregate_metrics(all_oos)

    log(f"\n  FINAL IS:  {combined_is['total_trades']}t PF={combined_is['profit_factor']:.2f} "
        f"${combined_is['total_pnl']:.0f}")
    log(f"  FINAL OOS: {combined_oos['total_trades']}t PF={combined_oos['profit_factor']:.2f} "
        f"${combined_oos['total_pnl']:.0f}")

    for ticker in final_all:
        s = ticker_stats(all_oos[ticker])
        log(f"    {ticker} OOS: {s['trades']}t PF={s['pf']:.2f} ${s['pnl']:.0f}")

    # Walk-forward
    log("\n  Running final walk-forward...")
    wf_lp = WalkForwardValidator(lp_config, TSLA_TICKERS)
    wf_sp = WalkForwardValidator(sp_config, final_short)

    lp_wf = wf_lp.run()
    sp_wf = wf_sp.run()

    combined_wf = []
    for i in range(min(len(lp_wf), len(sp_wf))):
        lp_w = lp_wf[i]
        sp_w = sp_wf[i]
        gp = lp_w.get('gross_profit', 0) + sp_w.get('gross_profit', 0)
        gl = lp_w.get('gross_loss', 0) + sp_w.get('gross_loss', 0)
        merged = {
            'total_trades': lp_w['total_trades'] + sp_w['total_trades'],
            'total_pnl': lp_w['total_pnl'] + sp_w['total_pnl'],
            'win_rate': ((lp_w['win_rate'] * lp_w['total_trades'] +
                         sp_w['win_rate'] * sp_w['total_trades']) /
                        max(lp_w['total_trades'] + sp_w['total_trades'], 1)),
            'profit_factor': gp / gl if gl > 0 else float('inf'),
            'sharpe': (lp_w.get('sharpe', 0) + sp_w.get('sharpe', 0)) / 2,
            'window': i + 1,
            'test_start': lp_w.get('test_start', sp_w.get('test_start', '')),
            'test_end': lp_w.get('test_end', sp_w.get('test_end', '')),
        }
        combined_wf.append(merged)

    wf_summary = WalkForwardValidator.summarize(combined_wf)

    log(f"\n  FINAL WF: {wf_summary['positive_sharpe_windows']}/{wf_summary['n_windows']} positive, "
        f"mean Sharpe={wf_summary['mean_sharpe']:.2f}, total P&L=${wf_summary['total_pnl']:.0f}")

    for w in combined_wf:
        marker = "+" if w.get('sharpe', 0) > 0 else "-"
        log(f"    W{w['window']}: {w['test_start']}→{w['test_end']} "
            f"{w['total_trades']}t PF={w['profit_factor']:.2f} "
            f"${w['total_pnl']:.0f} [{marker}]")

    return {
        'final_tickers': final_all,
        'final_short': final_short,
        'combined_is': combined_is,
        'combined_oos': combined_oos,
        'all_oos': all_oos,
        'combined_wf': combined_wf,
        'wf_summary': wf_summary,
    }


# ──────────────────────────────────────────────────────────────────
# Report generation
# ──────────────────────────────────────────────────────────────────

def generate_report(lp_winners, sp_winners, combined, expansion_accepted, final):
    lines = [
        "# Phase 7 — Direction-Specific Optimization Report",
        "",
        "**Date:** 2026-03-03",
        "",
        "---",
        "",
        "## Phase 7A: Parameter Optimization",
        "",
        "### LP Winners (TSLA LONG)",
        "",
        "| Parameter | Baseline | Winner |",
        "|-----------|----------|--------|",
    ]
    defaults = {
        'fractal_depth': 10, 'tail_ratio_min': 0.10, 'atr_entry_threshold': 0.80,
        'min_rr': 1.5, 'max_stop_atr_pct': 0.10, 'trail_factor': 0.7, 't1_pct': 0.30,
    }
    for param, val in lp_winners.items():
        changed = " *" if val != defaults.get(param) else ""
        lines.append(f"| {param} | {defaults.get(param)} | {val}{changed} |")

    lines.extend([
        "",
        "### SP Winners (AAPL/AMZN/GOOGL SHORT)",
        "",
        "| Parameter | Baseline | Winner |",
        "|-----------|----------|--------|",
    ])
    for param, val in sp_winners.items():
        changed = " *" if val != defaults.get(param) else ""
        lines.append(f"| {param} | {defaults.get(param)} | {val}{changed} |")

    # Combined results
    lines.extend([
        "",
        "## Combined Winners vs Baseline (L-005)",
        "",
        "| Metric | L-005 Baseline | v7 Combined |",
        "|--------|----------------|-------------|",
        f"| IS trades | {combined['baseline_is']['total_trades']} | {combined['combined_is']['total_trades']} |",
        f"| IS PF | {combined['baseline_is']['profit_factor']:.2f} | {combined['combined_is']['profit_factor']:.2f} |",
        f"| IS P&L | ${combined['baseline_is']['total_pnl']:.0f} | ${combined['combined_is']['total_pnl']:.0f} |",
        f"| OOS trades | {combined['baseline_oos']['total_trades']} | {combined['combined_oos']['total_trades']} |",
        f"| OOS PF | {combined['baseline_oos']['profit_factor']:.2f} | {combined['combined_oos']['profit_factor']:.2f} |",
        f"| OOS P&L | ${combined['baseline_oos']['total_pnl']:.0f} | ${combined['combined_oos']['total_pnl']:.0f} |",
        f"| WF positive | {combined['baseline_wf_summary']['positive_sharpe_windows']}/{combined['baseline_wf_summary']['n_windows']} | {combined['wf_summary']['positive_sharpe_windows']}/{combined['wf_summary']['n_windows']} |",
        f"| WF mean Sharpe | {combined['baseline_wf_summary']['mean_sharpe']:.2f} | {combined['wf_summary']['mean_sharpe']:.2f} |",
        f"| WF total P&L | ${combined['baseline_wf_summary']['total_pnl']:.0f} | ${combined['wf_summary']['total_pnl']:.0f} |",
    ])

    # Per-ticker OOS
    lines.extend(["", "### Per-Ticker OOS (v7 Combined)", ""])
    lines.append("| Ticker | Direction | Trades | PF | P&L |")
    lines.append("|--------|-----------|--------|----|----|")
    for ticker in ALL_TICKERS:
        s = ticker_stats(combined['all_oos'][ticker])
        d = "LONG" if ticker == 'TSLA' else "SHORT"
        lines.append(f"| {ticker} | {d} | {s['trades']} | {s['pf']:.2f} | ${s['pnl']:.0f} |")

    # WF per-window
    lines.extend(["", "### Walk-Forward Windows (v7 Combined)", ""])
    lines.append("| Window | Period | Trades | PF | P&L | Sharpe |")
    lines.append("|--------|--------|--------|----|----|--------|")
    for w in combined['combined_wf']:
        lines.append(f"| {w['window']} | {w['test_start']}→{w['test_end']} | "
                     f"{w['total_trades']} | {w['profit_factor']:.2f} | "
                     f"${w['total_pnl']:.0f} | {w.get('sharpe', 0):.2f} |")

    # Expansion
    lines.extend([
        "",
        "## Phase 7B: Universe Expansion",
        "",
        f"**Tested:** {', '.join(EXPANSION_TICKERS)}",
        f"**Accepted:** {', '.join(expansion_accepted) if expansion_accepted else 'NONE'}",
    ])

    # Final portfolio
    if final:
        lines.extend([
            "",
            "## Phase 7C: Final Portfolio",
            "",
            f"**Tickers:** {', '.join(final['final_tickers'])}",
            f"**TSLA:** LONG | **Others:** SHORT",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| OOS trades | {final['combined_oos']['total_trades']} |",
            f"| OOS PF | {final['combined_oos']['profit_factor']:.2f} |",
            f"| OOS P&L | ${final['combined_oos']['total_pnl']:.0f} |",
            f"| WF positive | {final['wf_summary']['positive_sharpe_windows']}/{final['wf_summary']['n_windows']} |",
            f"| WF mean Sharpe | {final['wf_summary']['mean_sharpe']:.2f} |",
            f"| WF total P&L | ${final['wf_summary']['total_pnl']:.0f} |",
        ])

        lines.extend(["", "### Final Per-Ticker OOS", ""])
        lines.append("| Ticker | Direction | Trades | PF | P&L |")
        lines.append("|--------|-----------|--------|----|----|")
        for ticker in final['final_tickers']:
            s = ticker_stats(final['all_oos'][ticker])
            d = "LONG" if ticker == 'TSLA' else "SHORT"
            lines.append(f"| {ticker} | {d} | {s['trades']} | {s['pf']:.2f} | ${s['pnl']:.0f} |")

        lines.extend(["", "### Final Walk-Forward Windows", ""])
        lines.append("| Window | Period | Trades | PF | P&L |")
        lines.append("|--------|--------|--------|----|----|")
        for w in final['combined_wf']:
            lines.append(f"| {w['window']} | {w['test_start']}→{w['test_end']} | "
                         f"{w['total_trades']} | {w['profit_factor']:.2f} | ${w['total_pnl']:.0f} |")

    # Final config
    lines.extend([
        "",
        "## Final Config (v7 winner)",
        "",
        "```python",
        f"# TSLA LONG params",
        f"lp_config = {lp_winners}",
        "",
        f"# SHORT ticker params",
        f"sp_config = {sp_winners}",
        "",
        f"direction_filter = {{'TSLA': 'long', 'DEFAULT': 'short'}}",
        f"portfolio = {final['final_tickers'] if final else ALL_TICKERS}",
        "```",
        "",
    ])

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    log("Phase 7 — Direction-Specific Parameter Optimization")
    log("=" * 60)

    # Phase 7A
    lp_winners = run_phase_7a_lp()
    sp_winners = run_phase_7a_sp()

    # Combine winners
    combined = run_combined(lp_winners, sp_winners)

    # Phase 7B: Expansion
    expansion_accepted = run_expansion(sp_winners, combined)

    # Phase 7C: Final portfolio (with expansion if any)
    if expansion_accepted:
        final = run_final_portfolio(lp_winners, sp_winners, expansion_accepted, combined)
    else:
        # Just use the combined result as final
        final = {
            'final_tickers': ALL_TICKERS,
            'final_short': SHORT_TICKERS,
            'combined_is': combined['combined_is'],
            'combined_oos': combined['combined_oos'],
            'all_oos': combined['all_oos'],
            'combined_wf': combined['combined_wf'],
            'wf_summary': combined['wf_summary'],
        }

    # Generate report
    report = generate_report(lp_winners, sp_winners, combined, expansion_accepted, final)
    report_path = os.path.join(RESULTS_DIR, 'v7_optimization_report.md')
    with open(report_path, 'w') as f:
        f.write(report)
    log(f"\nReport written to {report_path}")

    # Write full experiment log
    log_path = os.path.join(RESULTS_DIR, 'v7_experiment_log.txt')
    with open(log_path, 'w') as f:
        f.write("\n".join(LOG_LINES))
    log(f"Full log written to {log_path}")

    # Summary
    log("\n" + "=" * 60)
    log("  FINAL SUMMARY")
    log("=" * 60)
    log(f"  LP Winners (TSLA LONG): {lp_winners}")
    log(f"  SP Winners (SHORT):     {sp_winners}")
    log(f"  Portfolio: {final['final_tickers']}")
    log(f"  OOS: {final['combined_oos']['total_trades']}t "
        f"PF={final['combined_oos']['profit_factor']:.2f} "
        f"${final['combined_oos']['total_pnl']:.0f}")
    log(f"  WF: {final['wf_summary']['positive_sharpe_windows']}/{final['wf_summary']['n_windows']} positive, "
        f"Sharpe={final['wf_summary']['mean_sharpe']:.2f}, "
        f"${final['wf_summary']['total_pnl']:.0f}")
