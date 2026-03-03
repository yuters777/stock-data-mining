"""
Phase 1 Verification: Run backtester on NVDA in-sample data.
Produces signal funnel, level audit, and trade list for manual verification.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

from backtester.backtester import Backtester, BacktestConfig
from backtester.core.level_detector import LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngineConfig
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig
from backtester.analyzer import Analyzer


def main():
    print("=" * 60)
    print("PHASE 1 VERIFICATION — In-Sample Period (NVDA)")
    print("=" * 60)

    # Load NVDA data
    data_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             'data', 'NVDA_data.csv')
    print(f"\nLoading data from: {data_path}")
    m5_df = pd.read_csv(data_path)
    m5_df['Datetime'] = pd.to_datetime(m5_df['Datetime'])
    m5_df = m5_df.sort_values(['Ticker', 'Datetime']).reset_index(drop=True)

    print(f"Total M5 bars: {len(m5_df)}")
    print(f"Date range: {m5_df['Datetime'].min()} to {m5_df['Datetime'].max()}")

    # In-sample: Feb 2025 – Oct 2025 (70%)
    start_date = '2025-02-10'
    end_date = '2025-10-01'
    print(f"In-sample period: {start_date} to {end_date}")

    # Configure backtester with baseline v3.4 parameters
    config = BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=5,
            tolerance_cents=0.05,
            tolerance_pct=0.001,
            atr_period=5,
            min_level_score=5,
        ),
        pattern_config=PatternEngineConfig(
            tail_ratio_min=0.20,
            lp2_engulfing_required=True,
            clp_min_bars=3,
            clp_max_bars=7,
        ),
        filter_config=FilterChainConfig(
            atr_block_threshold=0.30,
            atr_entry_threshold=0.75,
            enable_volume_filter=True,
            enable_time_filter=True,
            enable_squeeze_filter=True,
        ),
        risk_config=RiskManagerConfig(
            min_rr=3.0,
            max_stop_atr_pct=0.15,
            capital=100000.0,
            risk_pct=0.003,
        ),
        trade_config=TradeManagerConfig(
            slippage_per_share=0.02,
            partial_tp_at_r=2.0,
            partial_tp_pct=0.50,
        ),
        name="baseline_v3.4_IS",
    )

    # Run backtest
    print("\nRunning backtest...")
    backtester = Backtester(config)
    result = backtester.run(m5_df, start_date=start_date, end_date=end_date)

    # Add proximity events to performance dict for funnel
    result.performance['proximity_events'] = backtester.proximity_events

    # Print reports
    print("\n")
    print(Analyzer.signal_funnel_report(result))
    print("\n")
    print(Analyzer.level_audit_report(result))
    print("\n")
    print(Analyzer.performance_report(result))

    if result.trades:
        print("\n")
        print(Analyzer.trade_list_report(result))

    # Print detected levels for manual verification
    print("\n")
    print("DETECTED LEVELS (all)")
    print("=" * 100)
    for i, level in enumerate(backtester.levels):
        print(f"  {i+1:>2}. {level.date.strftime('%Y-%m-%d')} | "
              f"{level.ticker} | {level.level_type.value} | "
              f"Price={level.price:>8.2f} | Score={level.score:>2} | "
              f"Touches={level.touches:>2} | Mirror={level.is_mirror} | "
              f"ATR_D1={level.atr_d1:.2f} | {level.score_breakdown}")

    # Summary diagnostics
    print("\n")
    print("DIAGNOSTIC SUMMARY")
    print("=" * 60)
    print(f"Levels detected:        {len(backtester.levels)}")
    print(f"Proximity events:       {backtester.proximity_events}")
    print(f"Patterns found:         {backtester.patterns_found}")
    print(f"Signals blocked:        {backtester.signals_blocked}")
    print(f"Funnel entries:         {len(result.funnel_entries)}")
    print(f"Trades executed:        {len(result.trades)}")

    if len(backtester.levels) == 0:
        print("\nWARNING: Zero levels detected!")
    if backtester.proximity_events == 0:
        print("\nWARNING: Zero proximity events!")
    if backtester.patterns_found == 0 and backtester.proximity_events > 0:
        print("\nWARNING: Proximity events but zero patterns — may be too strict!")

    return result


if __name__ == '__main__':
    result = main()
