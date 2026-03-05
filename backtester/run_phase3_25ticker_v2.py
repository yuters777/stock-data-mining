"""
Phase 3 v2 — Frozen Config A backtest with fixes:
  - Squeeze filter DISABLED (ablation L-005.3 §B.2 showed suppressive)
  - ATR_BLOCK corrected to 0.20 per spec

Generates same artifacts as v1, saved to results/phase3_25ticker_v2/.

Config A params (frozen, corrected):
  FD=10, ATR_ENTRY=0.60, ATR_BLOCK=0.20, RR=2.0, TAIL=0.15, STOP=0.15
  2tier_trail: t1_pct=0.30, trail_factor=0.7
  Squeeze: DISABLED
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

# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'results', 'phase3_25ticker_v2')
os.makedirs(RESULTS_DIR, exist_ok=True)

LOG = []


def log(msg=''):
    LOG.append(msg)
    print(msg)


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG A v2 (FROZEN — squeeze OFF, ATR_BLOCK=0.20)
# ═══════════════════════════════════════════════════════════════════════════

def make_config_a_v2(earnings_calendar=None) -> BacktestConfig:
    """Config A v2: FD=10, ATR_ENTRY=0.60, ATR_BLOCK=0.20, RR=2.0, TAIL=0.15
    Squeeze: DISABLED per ablation L-005.3 §B.2"""
    return BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=10,
            tolerance_cents=0.05,
            tolerance_pct=0.001,
            atr_period=5,
            min_level_score=5,
        ),
        pattern_config=PatternEngineConfig(
            tail_ratio_min=0.15,
            lp2_engulfing_required=True,
            clp_min_bars=3,
            clp_max_bars=7,
        ),
        filter_config=FilterChainConfig(
            atr_block_threshold=0.20,       # Fixed: was 0.30, spec says 0.20
            atr_entry_threshold=0.60,
            enable_volume_filter=True,
            enable_time_filter=True,
            enable_squeeze_filter=False,    # DISABLED per ablation
        ),
        risk_config=RiskManagerConfig(
            min_rr=2.0,
            max_stop_atr_pct=0.15,
            capital=100000.0,
            risk_pct=0.003,
        ),
        trade_config=TradeManagerConfig(
            slippage_per_share=0.02,
            partial_tp_at_r=2.0,
            partial_tp_pct=0.50,
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
        name='ConfigA_Phase3_v2',
    )


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()

    log("=" * 90)
    log("  PHASE 3 v2 — Frozen Config A Backtest (Squeeze OFF, ATR_BLOCK=0.20)")
    log("=" * 90)
    log(f"  Config: FD=10, ATR_ENTRY=0.60, ATR_BLOCK=0.20, RR=2.0, TAIL=0.15, STOP=0.15")
    log(f"  Squeeze filter: DISABLED")
    log(f"  Tickers ({len(TICKERS)}): {', '.join(TICKERS)}")
    log(f"  Period: {FULL_START} → {FULL_END}")
    log()

    # ── Load earnings calendar (cached to JSON) ──
    cache_dir = os.path.join(RESULTS_DIR, 'cache')
    calendar = EarningsCalendar(cache_dir=cache_dir)
    calendar.load(TICKERS)
    earnings_loaded = sum(len(calendar.get_earnings_dates(t)) for t in TICKERS)
    log(f"  Earnings calendar: {earnings_loaded} total earnings dates loaded across {len(TICKERS)} tickers")
    log()

    config = make_config_a_v2(earnings_calendar=calendar)

    # ══════════════════════════════════════════════════════════════════════
    # RUN BACKTEST PER TICKER
    # ══════════════════════════════════════════════════════════════════════

    all_results = {}
    all_trades = []
    all_funnel = {}
    all_shadow = []
    all_equity_points = []

    for ticker in TICKERS:
        log(f"  Running {ticker}...")
        try:
            m5_df = load_ticker_data(ticker)
            bt = Backtester(config)
            result = bt.run(m5_df, start_date=FULL_START, end_date=FULL_END)
            all_results[ticker] = result

            for trade in result.trades:
                all_trades.append({
                    'ticker': ticker,
                    'direction': trade.direction.value,
                    'pattern': trade.signal.pattern.value if trade.signal else '',
                    'entry_time': str(trade.entry_time),
                    'exit_time': str(trade.exit_time),
                    'entry_price': trade.entry_price,
                    'exit_price': trade.exit_price,
                    'position_size': trade.position_size,
                    'stop_price': trade.stop_price,
                    'target_price': trade.target_price,
                    'pnl': trade.pnl,
                    'pnl_r': trade.pnl_r,
                    'exit_reason': trade.exit_reason.value if trade.exit_reason else '',
                    'max_favorable': trade.max_favorable,
                    'max_adverse': trade.max_adverse,
                    'is_winner': trade.is_winner,
                })

            all_funnel[ticker] = bt.filter_chain.get_funnel_summary()

            for entry in result.funnel_entries:
                if entry.blocked_by:
                    all_shadow.append({
                        'ticker': ticker,
                        'timestamp': str(entry.signal.timestamp),
                        'pattern': entry.signal.pattern.value,
                        'direction': entry.signal.direction.value,
                        'entry_price': entry.signal.entry_price,
                        'level_price': entry.signal.level.price if entry.signal.level else 0,
                        'blocked_by': entry.blocked_by,
                        'blocked_reason': entry.blocked_reason,
                        'atr_ratio': entry.atr_ratio,
                    })

            for ts, eq in result.equity_curve:
                all_equity_points.append({
                    'timestamp': str(ts), 'equity': eq, 'ticker': ticker,
                })

            perf = result.performance
            log(f"    {ticker}: {perf.get('total_trades', 0)}t, "
                f"WR={perf.get('win_rate', 0)*100:.1f}%, "
                f"PF={perf.get('profit_factor', 0):.2f}, "
                f"P&L=${perf.get('total_pnl', 0):.0f}")

        except Exception as e:
            log(f"    {ticker}: FAILED — {e}")
            import traceback
            traceback.print_exc()

    # ══════════════════════════════════════════════════════════════════════
    # AGGREGATE METRICS
    # ══════════════════════════════════════════════════════════════════════

    all_trade_objects = []
    for r in all_results.values():
        all_trade_objects.extend(r.trades)

    agg = compute_metrics(all_trade_objects)

    log()
    log("=" * 90)
    log("  AGGREGATE RESULTS")
    log("=" * 90)
    log(f"  {fmt(agg)}")
    log()

    # ── Per-ticker breakdown ──
    log(f"  {'Ticker':>8} {'Trades':>7} {'WR':>7} {'PF':>7} {'P&L':>10} {'MaxDD':>8} {'AvgR':>6}")
    log(f"  {'-' * 60}")
    ticker_metrics = {}
    for ticker in TICKERS:
        if ticker in all_results:
            tm = compute_metrics(all_results[ticker].trades)
            ticker_metrics[ticker] = tm
            pf_s = f"{tm['pf']:.2f}" if tm['pf'] != float('inf') else "inf"
            log(f"  {ticker:>8} {tm['trades']:>7} {tm['wr']*100:>6.1f}% {pf_s:>6} "
                f"${tm['pnl']:>9.0f} ${tm['max_dd']:>7.0f} {tm['avg_r']:>6.2f}")
        else:
            log(f"  {ticker:>8}  — no data —")

    # ── Signal funnel ──
    log()
    log("  SIGNAL FUNNEL SUMMARY")
    log(f"  {'Ticker':>8} {'Total':>6} {'Passed':>7} {'Dir':>5} {'Pos':>5} {'Score':>6} "
        f"{'Time':>5} {'Earn':>5} {'ATR_H':>6} {'ATR_T':>6} {'Vol':>5} {'Sqz':>5}")
    log(f"  {'-' * 80}")
    agg_funnel = {}
    for ticker in TICKERS:
        if ticker not in all_funnel:
            continue
        f = all_funnel[ticker]
        log(f"  {ticker:>8} {f['total_signals']:>6} {f['passed']:>7} "
            f"{f['blocked_by_direction']:>5} {f['blocked_by_position']:>5} "
            f"{f['blocked_by_level_score']:>6} {f['blocked_by_time']:>5} "
            f"{f['blocked_by_earnings']:>5} {f['blocked_by_atr_hard']:>6} "
            f"{f['blocked_by_atr_threshold']:>6} {f['blocked_by_volume']:>5} "
            f"{f['blocked_by_squeeze']:>5}")
        for k, v in f.items():
            agg_funnel[k] = agg_funnel.get(k, 0) + v

    log(f"  {'-' * 80}")
    if agg_funnel:
        log(f"  {'TOTAL':>8} {agg_funnel.get('total_signals',0):>6} "
            f"{agg_funnel.get('passed',0):>7} "
            f"{agg_funnel.get('blocked_by_direction',0):>5} "
            f"{agg_funnel.get('blocked_by_position',0):>5} "
            f"{agg_funnel.get('blocked_by_level_score',0):>6} "
            f"{agg_funnel.get('blocked_by_time',0):>5} "
            f"{agg_funnel.get('blocked_by_earnings',0):>5} "
            f"{agg_funnel.get('blocked_by_atr_hard',0):>6} "
            f"{agg_funnel.get('blocked_by_atr_threshold',0):>6} "
            f"{agg_funnel.get('blocked_by_volume',0):>5} "
            f"{agg_funnel.get('blocked_by_squeeze',0):>5}")

    # ══════════════════════════════════════════════════════════════════════
    # SAVE ARTIFACTS
    # ══════════════════════════════════════════════════════════════════════

    # 1. Trade log CSV
    trade_log_path = os.path.join(RESULTS_DIR, 'trade_log.csv')
    if all_trades:
        keys = all_trades[0].keys()
        with open(trade_log_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(all_trades)
    log(f"\n  Trade log: {trade_log_path} ({len(all_trades)} trades)")

    # 2. Equity curve CSV
    equity_path = os.path.join(RESULTS_DIR, 'equity_curve.csv')
    if all_equity_points:
        keys = all_equity_points[0].keys()
        with open(equity_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(all_equity_points)
    log(f"  Equity curve: {equity_path} ({len(all_equity_points)} points)")

    # 3. Shadow log CSV
    shadow_path = os.path.join(RESULTS_DIR, 'shadow_log.csv')
    if all_shadow:
        keys = all_shadow[0].keys()
        with open(shadow_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(all_shadow)
    log(f"  Shadow log: {shadow_path} ({len(all_shadow)} blocked signals)")

    # 4. Signal funnel JSON
    funnel_path = os.path.join(RESULTS_DIR, 'signal_funnel.json')
    funnel_output = {'per_ticker': all_funnel, 'aggregate': agg_funnel}
    with open(funnel_path, 'w') as f:
        json.dump(funnel_output, f, indent=2, default=str)
    log(f"  Signal funnel: {funnel_path}")

    # 5. Full results JSON
    json_path = os.path.join(RESULTS_DIR, 'results.json')
    json_output = {
        'phase': '3v2',
        'config': 'ConfigA_frozen_v2_squeeze_off_atr_fixed',
        'tickers': TICKERS,
        'period': f'{FULL_START} to {FULL_END}',
        'note': f'{len(TICKERS)} tickers, squeeze OFF, ATR_BLOCK=0.20',
        'aggregate': agg,
        'per_ticker': {t: ticker_metrics.get(t, {}) for t in TICKERS},
        'level_stats': {t: all_results[t].level_stats for t in TICKERS if t in all_results},
        'funnel': funnel_output,
    }
    with open(json_path, 'w') as f:
        json.dump(json_output, f, indent=2, default=str)
    log(f"  Results JSON: {json_path}")

    # 6. Text report
    elapsed = time.time() - t0
    log(f"\n{'=' * 90}")
    log(f"  PHASE 3 v2 COMPLETE — {elapsed:.0f}s ({elapsed/60:.1f}min)")
    log(f"{'=' * 90}")

    report_path = os.path.join(RESULTS_DIR, 'report.txt')
    with open(report_path, 'w') as f:
        f.write('\n'.join(LOG))
    print(f"  Report saved: {report_path}")

    # ══════════════════════════════════════════════════════════════════════
    # COMPARISON: v1 vs v2
    # ══════════════════════════════════════════════════════════════════════
    v1_json_path = os.path.join(os.path.dirname(RESULTS_DIR), 'phase3_25ticker', 'results.json')
    if os.path.exists(v1_json_path):
        with open(v1_json_path) as f:
            v1 = json.load(f)
        v1a = v1['aggregate']

        print()
        print("=" * 75)
        print("  COMPARISON: v1 (squeeze ON, ATR_BLOCK=0.30) vs v2 (squeeze OFF, ATR_BLOCK=0.20)")
        print("=" * 75)
        header = f"  {'Metric':<18} {'v1 (current)':>14} {'v2 (fixed)':>14} {'Delta':>14}"
        print(header)
        print(f"  {'-' * 56}")

        def cmp(label, v1_val, v2_val, fmt_str="${:>,.0f}", is_int=False):
            delta = v2_val - v1_val
            if is_int:
                print(f"  {label:<18} {v1_val:>14} {v2_val:>14} {delta:>+14}")
            else:
                v1_s = fmt_str.format(v1_val)
                v2_s = fmt_str.format(v2_val)
                delta_s = fmt_str.format(delta)
                if delta >= 0:
                    delta_s = "+" + delta_s
                print(f"  {label:<18} {v1_s:>14} {v2_s:>14} {delta_s:>14}")

        cmp("Trades", v1a['trades'], agg['trades'], is_int=True)
        cmp("PF", v1a['pf'], agg['pf'], fmt_str="{:.2f}")
        cmp("P&L", v1a['pnl'], agg['pnl'])
        cmp("MaxDD", v1a['max_dd'], agg['max_dd'])
        cmp("WR%", v1a['wr'] * 100, agg['wr'] * 100, fmt_str="{:.1f}%")
        cmp("AvgR", v1a['avg_r'], agg['avg_r'], fmt_str="{:.2f}")

        # Funnel comparison
        v1f = v1.get('funnel', {}).get('aggregate', {})
        cmp("Squeeze blocks", v1f.get('blocked_by_squeeze', 0),
            agg_funnel.get('blocked_by_squeeze', 0), is_int=True)
        cmp("ATR hard blocks", v1f.get('blocked_by_atr_hard', 0),
            agg_funnel.get('blocked_by_atr_hard', 0), is_int=True)
        cmp("ATR thresh blocks", v1f.get('blocked_by_atr_threshold', 0),
            agg_funnel.get('blocked_by_atr_threshold', 0), is_int=True)

        print("=" * 75)


if __name__ == '__main__':
    main()
