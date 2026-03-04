"""
Post-Nison-Fix Backtest: 6-ticker portfolio with Phase 2.2 optimized params.
Compare against previous run (16 trades, PF 2.92).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

from backtester.backtester import Backtester, BacktestConfig
from backtester.core.level_detector import LevelDetector, LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngineConfig
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig
from backtester.data_types import LevelStatus
from backtester.analyzer import Analyzer


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
TICKERS = ['TSLA', 'AMZN', 'GOOGL', 'META', 'MSFT', 'NVDA']

# Phase 2.2 optimized params
config = BacktestConfig(
    level_config=LevelDetectorConfig(
        fractal_depth=5,             # Phase 2.2
        tolerance_cents=0.05,
        tolerance_pct=0.001,
        atr_period=5,
        min_level_score=5,
        cross_count_invalidate=5,    # SAWING_THRESHOLD=5
        cross_count_window=30,       # SAWING_PERIOD=30
    ),
    pattern_config=PatternEngineConfig(
        tail_ratio_min=0.15,         # Phase 2.2
        lp2_engulfing_required=True,
        clp_min_bars=3,
        clp_max_bars=7,
    ),
    filter_config=FilterChainConfig(
        atr_block_threshold=0.25,    # Phase 2.2
        atr_entry_threshold=0.70,    # Phase 2.2
        enable_volume_filter=True,
        enable_time_filter=True,
        enable_squeeze_filter=True,
    ),
    risk_config=RiskManagerConfig(
        min_rr=3.0,                  # Phase 2.2
        max_stop_atr_pct=0.10,
        capital=100000.0,
        risk_pct=0.003,
    ),
    trade_config=TradeManagerConfig(
        slippage_per_share=0.02,
        partial_tp_at_r=2.0,
        partial_tp_pct=0.50,
    ),
    tier_config={
        'mode': '2tier_trail',
        't1_pct': 0.30,
        'trail_factor': 0.7,
        'trail_activation_r': 0.0,
        'min_rr': 1.5,
    },
    direction_filter={'TSLA': 'long', 'DEFAULT': 'short'},
    name="nison_fix_p2.2",
)


def load_all_tickers():
    """Load and concatenate all ticker data."""
    frames = []
    for ticker in TICKERS:
        path = os.path.join(DATA_DIR, f'{ticker}_data.csv')
        if not os.path.exists(path):
            print(f"  SKIP: {path} not found")
            continue
        df = pd.read_csv(path)
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        df = df.sort_values('Datetime').reset_index(drop=True)
        frames.append(df)
        print(f"  Loaded {ticker}: {len(df)} bars")
    return pd.concat(frames, ignore_index=True).sort_values(
        ['Ticker', 'Datetime']).reset_index(drop=True)


def count_level_invalidations(backtester):
    """Detailed breakdown of level invalidation reasons."""
    total = len(backtester.levels)
    active = 0
    broken = 0
    mirror_candidate = 0
    mirror_confirmed = 0
    invalidated_sawing = 0
    invalidated_nison = 0
    invalidated_other = 0

    for lvl in backtester.levels:
        if lvl.status == LevelStatus.ACTIVE:
            active += 1
        elif lvl.status == LevelStatus.BROKEN:
            broken += 1
        elif lvl.status == LevelStatus.MIRROR_CANDIDATE:
            mirror_candidate += 1
        elif lvl.status == LevelStatus.MIRROR_CONFIRMED:
            mirror_confirmed += 1
        elif lvl.status == LevelStatus.INVALIDATED:
            # Distinguish sawing vs nison: sawing has cross_count >= threshold
            if lvl.cross_count >= backtester.config.level_config.cross_count_invalidate:
                invalidated_sawing += 1
            elif lvl.mirror_breakout_side:
                # Had mirror info → likely Nison
                invalidated_nison += 1
            else:
                invalidated_other += 1

    return {
        'total': total,
        'active': active,
        'broken': broken,
        'mirror_candidate': mirror_candidate,
        'mirror_confirmed': mirror_confirmed,
        'invalidated_sawing': invalidated_sawing,
        'invalidated_nison': invalidated_nison,
        'invalidated_other': invalidated_other,
        'surviving': active + broken + mirror_candidate + mirror_confirmed,
    }


def main():
    print("=" * 70)
    print("POST-NISON-FIX BACKTEST — Phase 2.2 Params — 6 Tickers")
    print("=" * 70)
    print(f"\nParams: FRACTAL_DEPTH=5, ATR_ENTRY=0.70, ATR_BLOCK=0.25")
    print(f"        SAWING_THRESH=5, SAWING_PERIOD=30, TAIL_RATIO=0.15, MIN_RR=3.0")
    print(f"        Direction: TSLA=long, others=short")
    print(f"\nTickers: {', '.join(TICKERS)}")

    # Full date range
    start_date = '2025-02-10'
    end_date = '2026-02-01'
    print(f"Period: {start_date} to {end_date}")

    print(f"\nLoading data...")
    m5_df = load_all_tickers()
    print(f"Total M5 bars: {len(m5_df)}")

    print(f"\nRunning backtest...")
    backtester = Backtester(config)
    result = backtester.run(m5_df, start_date=start_date, end_date=end_date)
    result.performance['proximity_events'] = backtester.proximity_events

    # ── 1. LEVEL BREAKDOWN ──
    print("\n")
    print("=" * 70)
    print("1. LEVEL BREAKDOWN")
    print("=" * 70)

    lvl_stats = count_level_invalidations(backtester)
    print(f"\n  Total levels detected:     {lvl_stats['total']}")
    print(f"  ├─ Active:                 {lvl_stats['active']}")
    print(f"  ├─ Broken:                 {lvl_stats['broken']}")
    print(f"  ├─ Mirror Candidate:       {lvl_stats['mirror_candidate']}")
    print(f"  ├─ Mirror Confirmed:       {lvl_stats['mirror_confirmed']}")
    print(f"  ├─ Invalidated (sawing):   {lvl_stats['invalidated_sawing']}")
    print(f"  ├─ Invalidated (Nison):    {lvl_stats['invalidated_nison']}")
    print(f"  └─ Invalidated (other):    {lvl_stats['invalidated_other']}")
    print(f"")
    total_inv = lvl_stats['invalidated_sawing'] + lvl_stats['invalidated_nison'] + lvl_stats['invalidated_other']
    print(f"  Surviving levels:          {lvl_stats['surviving']} "
          f"({lvl_stats['surviving']/max(lvl_stats['total'],1)*100:.1f}%)")
    print(f"  Total invalidated:         {total_inv} "
          f"({total_inv/max(lvl_stats['total'],1)*100:.1f}%)")
    if lvl_stats['invalidated_nison'] > 0:
        nison_pct = lvl_stats['invalidated_nison'] / max(lvl_stats['total'], 1) * 100
        print(f"  Nison kill rate:           {nison_pct:.1f}%")

    # Per-ticker breakdown
    print(f"\n  Per-ticker level counts:")
    for ticker in TICKERS:
        t_levels = [l for l in backtester.levels if l.ticker == ticker]
        t_inv = sum(1 for l in t_levels if l.status == LevelStatus.INVALIDATED)
        t_mirror = sum(1 for l in t_levels if l.is_mirror)
        print(f"    {ticker:>5}: {len(t_levels):>4} total, {t_mirror:>3} mirrors, {t_inv:>3} invalidated")

    # ── 2. SIGNAL FUNNEL ──
    print("\n")
    print("=" * 70)
    print("2. SIGNAL FUNNEL")
    print("=" * 70)
    print(Analyzer.signal_funnel_report(result))

    # ── 3. PERFORMANCE ──
    print("\n")
    print("=" * 70)
    print("3. PERFORMANCE")
    print("=" * 70)
    print(Analyzer.performance_report(result))

    # ── 4. TRADE LIST ──
    if result.trades:
        print("\n")
        print("=" * 70)
        print("4. TRADE LIST")
        print("=" * 70)
        print(Analyzer.trade_list_report(result))

    # ── 5. COMPARISON ──
    print("\n")
    print("=" * 70)
    print("5. COMPARISON vs PREVIOUS (16 trades, PF 2.92)")
    print("=" * 70)
    p = result.performance
    prev = {'trades': 16, 'pf': 2.92}
    curr_trades = p.get('total_trades', 0)
    curr_pf = p.get('profit_factor', 0)
    print(f"\n  {'Metric':>20} {'Previous':>12} {'Current':>12} {'Delta':>12}")
    print(f"  {'-'*56}")
    print(f"  {'Trades':>20} {prev['trades']:>12} {curr_trades:>12} {curr_trades - prev['trades']:>+12}")
    print(f"  {'Profit Factor':>20} {prev['pf']:>12.2f} {curr_pf:>12.2f} {curr_pf - prev['pf']:>+12.2f}")
    print(f"  {'Win Rate':>20} {'N/A':>12} {p.get('win_rate',0)*100:>11.1f}%")
    print(f"  {'Total P&L':>20} {'N/A':>12} ${p.get('total_pnl',0):>11.2f}")
    print(f"  {'Sharpe':>20} {'N/A':>12} {p.get('sharpe',0):>12.2f}")
    print(f"  {'Max DD':>20} {'N/A':>12} {p.get('max_drawdown_pct',0):>11.2f}%")

    # ── 6. NISON SAMPLE ──
    print("\n")
    print("=" * 70)
    print("6. NISON-INVALIDATED LEVELS (sample up to 5)")
    print("=" * 70)
    nison_levels = [l for l in backtester.levels
                    if l.status == LevelStatus.INVALIDATED
                    and l.mirror_breakout_side
                    and l.cross_count < backtester.config.level_config.cross_count_invalidate]
    for i, lvl in enumerate(nison_levels[:5]):
        print(f"\n  [{i+1}] {lvl.ticker} @ ${lvl.price:.2f} | "
              f"Breakout: {lvl.mirror_breakout_side} | "
              f"Confirmed: {lvl.mirror_confirmed_date} | "
              f"Date: {lvl.date.strftime('%Y-%m-%d')}")
        hold_side = "above" if lvl.mirror_breakout_side == 'above' else "below"
        fail_side = "below" if lvl.mirror_breakout_side == 'above' else "above"
        print(f"       Mirror type: {'support' if lvl.mirror_breakout_side == 'above' else 'resistance'}")
        print(f"       Hold side: close {hold_side} level | Fail side: close {fail_side} level")
        print(f"       3-step Nison: retest → bounce {hold_side} → close {fail_side} = INVALIDATED")

    if not nison_levels:
        print("\n  No Nison-invalidated levels found (fix is working as expected).")

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)

    return result


if __name__ == '__main__':
    result = main()
