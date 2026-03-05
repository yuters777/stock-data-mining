"""
Variant A' — Clean re-run with ALL fixes applied:
  1. reset_index fix (ATR NaN bug)
  2. Day-change EOD flatten (no overnight holding)
  3. ATR filter OFF (ablation showed suppressive)
  4. Squeeze filter OFF (ablation showed suppressive)

Config: enable_atr_filter=False, enable_squeeze_filter=False,
        EOD flatten at 22:55 IST + day-change flatten
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

TICKERS = [
    'AAPL', 'AMD', 'AMZN', 'AVGO', 'BA', 'BABA', 'BIDU', 'C', 'COIN', 'COST',
    'GOOGL', 'GS', 'IBIT', 'JPM', 'MARA', 'META', 'MSFT', 'MU', 'NVDA',
    'PLTR', 'SNOW', 'TSLA', 'TSM', 'TXN', 'V',
]

FULL_START = '2025-02-10'
FULL_END = '2026-01-31'

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'results', 'phase3_d4_resolution')
os.makedirs(RESULTS_DIR, exist_ok=True)


def make_config(earnings_calendar=None) -> BacktestConfig:
    """Variant A' config — ATR OFF, squeeze OFF, all fixes applied."""
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
            enable_atr_filter=False,
            atr_block_threshold=0.20,
            atr_entry_threshold=0.60,
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
        name='CONFIG_A_PRIME',
    )


def main():
    t0 = time.time()

    print("=" * 80)
    print("  VARIANT A' — CLEAN RE-RUN WITH ALL FIXES")
    print("  ATR OFF | Squeeze OFF | Day-change EOD flatten | reset_index fix")
    print(f"  Period: {FULL_START} to {FULL_END}")
    print(f"  Tickers: {len(TICKERS)}")
    print("=" * 80)

    # Load earnings calendar
    cache_dir = os.path.join(RESULTS_DIR, 'cache')
    calendar = EarningsCalendar(cache_dir=cache_dir)
    calendar.load(TICKERS)

    config = make_config(calendar)

    all_trades = []
    all_funnel = {}
    per_ticker = {}
    overnight_count = 0

    for ticker in TICKERS:
        try:
            m5_df = load_ticker_data(ticker)
            bt = Backtester(config)
            result = bt.run(m5_df, start_date=FULL_START, end_date=FULL_END)

            ticker_trades = []
            for trade in result.trades:
                td = {
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
                    'exit_reason': trade.exit_reason.value if trade.exit_reason else '',
                }
                ticker_trades.append(td)
                all_trades.append(td)

                # Check for overnight trades
                if trade.entry_time and trade.exit_time:
                    if trade.entry_time.date() != trade.exit_time.date():
                        overnight_count += 1
                        print(f"    WARNING: overnight trade {ticker} "
                              f"{trade.entry_time} -> {trade.exit_time}")

            all_funnel[ticker] = bt.filter_chain.get_funnel_summary()

            perf = result.performance
            per_ticker[ticker] = {
                'trades': perf.get('total_trades', 0),
                'win_rate': perf.get('win_rate', 0),
                'profit_factor': perf.get('profit_factor', 0),
                'total_pnl': perf.get('total_pnl', 0),
                'eod_exits': perf.get('eod_exits', 0),
            }

            print(f"    {ticker}: {perf.get('total_trades', 0)}t, "
                  f"WR={perf.get('win_rate', 0)*100:.1f}%, "
                  f"PF={perf.get('profit_factor', 0):.2f}, "
                  f"P&L=${perf.get('total_pnl', 0):.0f}, "
                  f"EOD={perf.get('eod_exits', 0)}")

        except Exception as e:
            print(f"    {ticker}: FAILED - {e}")
            import traceback
            traceback.print_exc()

    # Aggregate metrics
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

    # Aggregate funnel
    agg_funnel = {}
    for f in all_funnel.values():
        for k, v in f.items():
            agg_funnel[k] = agg_funnel.get(k, 0) + v

    elapsed = time.time() - t0

    print(f"\n{'=' * 80}")
    print(f"  VARIANT A' AGGREGATE RESULTS")
    print(f"{'=' * 80}")
    pf_s = f"{metrics['pf']:.2f}" if metrics['pf'] != float('inf') else "inf"
    print(f"  Trades: {metrics['trades']}")
    print(f"  Win Rate: {metrics['wr']*100:.1f}%")
    print(f"  Profit Factor: {pf_s}")
    print(f"  Total P&L: ${metrics['pnl']:,.0f}")
    print(f"  Max Drawdown: ${metrics['max_dd']:,.0f}")
    print(f"  Avg R: {metrics['avg_r']:.2f}")
    print(f"  Overnight trades: {overnight_count}")
    print(f"  Signal funnel: {agg_funnel}")
    print(f"\n  Completed in {elapsed:.0f}s ({elapsed/60:.1f}min)")

    # D2: Remove-top-5 stress test
    if n >= 5:
        sorted_pnls = sorted(pnls, reverse=True)
        top5_pnl = sum(sorted_pnls[:5])
        remaining_pnl = metrics['pnl'] - top5_pnl
        print(f"\n  D2 REMOVE-TOP-5 STRESS TEST:")
        print(f"    Top 5 P&L: ${top5_pnl:,.0f}")
        print(f"    Remaining P&L: ${remaining_pnl:,.0f}")
        d2_pass = remaining_pnl > 0
        print(f"    D2 RESULT: {'PASS' if d2_pass else 'FAIL'} "
              f"(remaining {'>' if d2_pass else '<='} $0)")

    # D3: Quarterly stability
    print(f"\n  D3 QUARTERLY STABILITY:")
    quarterly = {}
    for t in all_trades:
        entry = pd.Timestamp(t['entry_time'])
        qkey = f"{entry.year}-Q{(entry.month - 1) // 3 + 1}"
        quarterly.setdefault(qkey, []).append(t['pnl'])

    profitable_qs = 0
    total_qs = 0
    for qkey in sorted(quarterly.keys()):
        q_pnls = quarterly[qkey]
        q_total = sum(q_pnls)
        q_n = len(q_pnls)
        q_winners = len([p for p in q_pnls if p > 0])
        q_wr = q_winners / q_n * 100 if q_n > 0 else 0
        is_profitable = q_total > 0
        if is_profitable:
            profitable_qs += 1
        total_qs += 1
        print(f"    {qkey}: {q_n}t WR={q_wr:.0f}% P&L=${q_total:,.0f} "
              f"{'PROFIT' if is_profitable else 'LOSS'}")

    d3_pass = profitable_qs >= total_qs * 0.5  # at least half profitable
    print(f"    D3 RESULT: {'PASS' if d3_pass else 'FAIL'} "
          f"({profitable_qs}/{total_qs} quarters profitable)")

    # D4: Overnight check
    d4_pass = overnight_count == 0
    print(f"\n  D4 OVERNIGHT CHECK:")
    print(f"    Overnight trades: {overnight_count}")
    print(f"    D4 RESULT: {'PASS' if d4_pass else 'FAIL'}")

    # Save results
    results = {
        'config': 'A_PRIME',
        'description': 'ATR OFF, Squeeze OFF, Day-change EOD flatten, reset_index fix',
        'period': f'{FULL_START} to {FULL_END}',
        'tickers': TICKERS,
        'metrics': metrics,
        'funnel': agg_funnel,
        'per_ticker': per_ticker,
        'overnight_trades': overnight_count,
        'diagnostics': {
            'd2_remove_top5': {
                'top5_pnl': top5_pnl if n >= 5 else 0,
                'remaining_pnl': remaining_pnl if n >= 5 else 0,
                'pass': d2_pass if n >= 5 else False,
            },
            'd3_quarterly': {
                'profitable_quarters': profitable_qs,
                'total_quarters': total_qs,
                'pass': d3_pass,
            },
            'd4_overnight': {
                'overnight_count': overnight_count,
                'pass': d4_pass,
            },
        },
        'elapsed_seconds': elapsed,
    }

    results_path = os.path.join(RESULTS_DIR, 'variant_a_prime_results.json')
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    # Save trade log
    if all_trades:
        trade_path = os.path.join(RESULTS_DIR, 'trades_a_prime.csv')
        keys = all_trades[0].keys()
        with open(trade_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(all_trades)

    print(f"\n  Results saved to: {RESULTS_DIR}/")


if __name__ == '__main__':
    main()
