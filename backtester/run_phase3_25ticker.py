"""
Phase 3 — Frozen Config A backtest on all available tickers.

Generates:
  1. Full results report (text + JSON)
  2. Trade log CSV
  3. Equity curve CSV
  4. Signal funnel summary
  5. Shadow log (blocked signals with reasons)

Config A params (frozen):
  FD=10, ATR_ENTRY=0.60, ATR_BLOCK=0.30, RR=2.0, TAIL=0.15, STOP=0.15
  2tier_trail: t1_pct=0.30, trail_factor=0.7
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

# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'results', 'phase3_25ticker')
os.makedirs(RESULTS_DIR, exist_ok=True)

# All 25 tickers from MarketPatterns-AI
TICKERS = [
    'AAPL', 'AMD', 'AMZN', 'AVGO', 'BA', 'BABA', 'BIDU', 'C', 'COIN',
    'COST', 'GOOGL', 'GS', 'IBIT', 'JPM', 'MARA', 'META', 'MSFT', 'MU',
    'NVDA', 'PLTR', 'SNOW', 'TSLA', 'TSM', 'TXN', 'V',
]

FULL_START = '2025-02-10'
FULL_END = '2026-01-31'

LOG = []


def log(msg=''):
    LOG.append(msg)
    print(msg)


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG A (FROZEN)
# ═══════════════════════════════════════════════════════════════════════════

def make_config_a(earnings_calendar=None) -> BacktestConfig:
    """Config A: FD=10, ATR_ENTRY=0.60, RR=2.0, TAIL=0.15, STOP=0.15"""
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
            atr_block_threshold=0.30,
            atr_entry_threshold=0.60,
            enable_volume_filter=True,
            enable_time_filter=True,
            enable_squeeze_filter=True,
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
        name='ConfigA_Phase3',
    )


# ═══════════════════════════════════════════════════════════════════════════
# HELPER: compute metrics from trade list
# ═══════════════════════════════════════════════════════════════════════════

def compute_metrics(trades):
    """Compute standard metrics from a list of Trade objects or dicts."""
    if not trades:
        return {'trades': 0, 'wr': 0.0, 'pf': 0.0, 'pnl': 0.0,
                'max_dd': 0.0, 'sharpe': 0.0, 'gross_profit': 0.0,
                'gross_loss': 0.0, 'avg_r': 0.0}

    pnls = []
    for t in trades:
        if hasattr(t, 'pnl'):
            pnls.append(t.pnl)
        else:
            pnls.append(t['pnl'])

    n = len(pnls)
    pnl_arr = np.array(pnls)
    winners = pnl_arr[pnl_arr > 0]
    losers = pnl_arr[pnl_arr <= 0]
    gp = winners.sum()
    gl = abs(losers.sum())
    pf = gp / gl if gl > 0 else (float('inf') if gp > 0 else 0.0)
    total_pnl = pnl_arr.sum()

    cum = np.cumsum(pnl_arr)
    peak = np.maximum.accumulate(cum)
    max_dd = (peak - cum).max() if len(cum) > 0 else 0.0

    if n >= 5 and np.std(pnl_arr) > 0:
        sharpe = np.mean(pnl_arr) / np.std(pnl_arr) * np.sqrt(n)
    else:
        sharpe = 0.0

    pnl_r_vals = []
    for t in trades:
        if hasattr(t, 'pnl_r'):
            pnl_r_vals.append(t.pnl_r)

    return {
        'trades': n,
        'wr': len(winners) / n,
        'pf': pf,
        'pnl': float(total_pnl),
        'max_dd': float(max_dd),
        'sharpe': float(sharpe),
        'gross_profit': float(gp),
        'gross_loss': float(gl),
        'avg_r': float(np.mean(pnl_r_vals)) if pnl_r_vals else 0.0,
    }


def fmt(m):
    pf_s = f"{m['pf']:.2f}" if m['pf'] != float('inf') else "inf"
    return (f"{m['trades']:>4}t  WR={m['wr']*100:>5.1f}%  PF={pf_s:>6}  "
            f"P&L=${m['pnl']:>8.0f}  DD=${m['max_dd']:>7.0f}  Sh={m['sharpe']:>6.2f}  "
            f"AvgR={m['avg_r']:>5.2f}")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()

    log("=" * 90)
    log("  PHASE 3 — Frozen Config A Backtest (25 Tickers)")
    log("=" * 90)
    log(f"  Config: FD=10, ATR_ENTRY=0.60, ATR_BLOCK=0.30, RR=2.0, TAIL=0.15, STOP=0.15")
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

    config = make_config_a(earnings_calendar=calendar)

    # ══════════════════════════════════════════════════════════════════════
    # RUN BACKTEST PER TICKER
    # ══════════════════════════════════════════════════════════════════════

    all_results = {}      # ticker -> BacktestResult
    all_trades = []       # flat list of trade dicts for CSV
    all_funnel = {}       # ticker -> funnel summary
    all_shadow = []       # blocked signals with reasons
    all_equity_points = []  # (timestamp, equity, ticker)

    for ticker in TICKERS:
        log(f"  Running {ticker}...")
        try:
            m5_df = load_ticker_data(ticker)
            bt = Backtester(config)
            result = bt.run(m5_df, start_date=FULL_START, end_date=FULL_END)
            all_results[ticker] = result

            # Collect trades
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

            # Collect funnel
            all_funnel[ticker] = bt.filter_chain.get_funnel_summary()

            # Collect shadow log (blocked signals)
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

            # Collect equity curve
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

    # ── Level stats ──
    log()
    log("  LEVEL DETECTION STATS")
    log(f"  {'Ticker':>8} {'Total':>7} {'Confirmed':>10} {'Mirrors':>8} {'Invalidated':>12} {'AvgScore':>9}")
    log(f"  {'-' * 60}")
    for ticker in TICKERS:
        if ticker in all_results:
            ls = all_results[ticker].level_stats
            log(f"  {ticker:>8} {ls.get('total_levels',0):>7} {ls.get('confirmed_bpu',0):>10} "
                f"{ls.get('mirrors',0):>8} {ls.get('invalidated_sawing',0):>12} "
                f"{ls.get('avg_score',0):>9.1f}")

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

    # ── Exit reason breakdown ──
    log()
    log("  EXIT REASON BREAKDOWN")
    for ticker in TICKERS:
        if ticker in all_results:
            perf = all_results[ticker].performance
            log(f"  {ticker:>8}: EOD={perf.get('eod_exits',0)}, "
                f"Nison={perf.get('nison_exits',0)}, "
                f"Trail={perf.get('trail_stop_exits',0)}, "
                f"BE={perf.get('breakeven_exits',0)}")

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

    # 3. Shadow log CSV (blocked signals)
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
        'phase': '3',
        'config': 'ConfigA_frozen',
        'tickers': TICKERS,
        'period': f'{FULL_START} to {FULL_END}',
        'note': f'{len(TICKERS)} tickers, earnings filter active',
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
    log(f"  PHASE 3 COMPLETE — {elapsed:.0f}s ({elapsed/60:.1f}min)")
    log(f"{'=' * 90}")

    report_path = os.path.join(RESULTS_DIR, 'report.txt')
    with open(report_path, 'w') as f:
        f.write('\n'.join(LOG))
    print(f"  Report saved: {report_path}")


if __name__ == '__main__':
    main()
