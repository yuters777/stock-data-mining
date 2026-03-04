"""
Diagnostic: Why do breakeven, trail stop, and Nison exit never trigger?
Traces the exact code paths for winning trades.
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
from backtester.core.trade_manager import TradeManagerConfig, ExitReason

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
TICKERS = ['TSLA', 'AMZN', 'GOOGL', 'META', 'MSFT', 'NVDA']

config = BacktestConfig(
    level_config=LevelDetectorConfig(
        fractal_depth=5, tolerance_cents=0.05, tolerance_pct=0.001,
        atr_period=5, min_level_score=5,
        cross_count_invalidate=5, cross_count_window=30,
    ),
    pattern_config=PatternEngineConfig(
        tail_ratio_min=0.15, lp2_engulfing_required=True,
        clp_min_bars=3, clp_max_bars=7,
    ),
    filter_config=FilterChainConfig(
        atr_block_threshold=0.25, atr_entry_threshold=0.70,
        enable_volume_filter=True, enable_time_filter=True,
        enable_squeeze_filter=True,
    ),
    risk_config=RiskManagerConfig(
        min_rr=3.0, max_stop_atr_pct=0.10,
        capital=100000.0, risk_pct=0.003,
    ),
    trade_config=TradeManagerConfig(
        slippage_per_share=0.02, partial_tp_at_r=2.0, partial_tp_pct=0.50,
    ),
    tier_config={
        'mode': '2tier_trail', 't1_pct': 0.30, 'trail_factor': 0.7,
        'trail_activation_r': 0.0, 'min_rr': 1.5,
    },
    direction_filter={'TSLA': 'long', 'DEFAULT': 'short'},
    name="diagnose_breakeven",
)


def load_all_tickers():
    frames = []
    for ticker in TICKERS:
        path = os.path.join(DATA_DIR, f'{ticker}_data.csv')
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path)
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        df = df.sort_values('Datetime').reset_index(drop=True)
        frames.append(df)
    return pd.concat(frames, ignore_index=True).sort_values(
        ['Ticker', 'Datetime']).reset_index(drop=True)


def main():
    print("=" * 70)
    print("DIAGNOSTIC: Breakeven / Trail Stop / CLP Investigation")
    print("=" * 70)

    m5_df = load_all_tickers()
    print(f"Loaded {len(m5_df)} bars")

    backtester = Backtester(config)
    result = backtester.run(m5_df, start_date='2025-02-10', end_date='2026-02-01')
    result.performance['proximity_events'] = backtester.proximity_events

    trades = result.trades
    print(f"\nTotal trades: {len(trades)}")

    # ── ISSUE 1A: Check if intraday_detector is None ──
    print("\n" + "=" * 70)
    print("ISSUE 1A: TIER CONFIG PATH CHECK")
    print("=" * 70)
    print(f"  intraday_config set:    {config.intraday_config is not None}")
    print(f"  intraday_detector:      {backtester.intraday_detector is not None}")
    print(f"  tier_config set:        {config.tier_config is not None}")
    print(f"  → Tiered path used:     {backtester.intraday_detector is not None and config.tier_config is not None}")

    # Check target_tiers on trades
    trades_with_tiers = [t for t in trades if t.risk_params.target_tiers]
    print(f"  Trades with target_tiers: {len(trades_with_tiers)} / {len(trades)}")
    print(f"  → Trail stop CANNOT activate without target_tiers containing 'trail' tier")

    # ── ISSUE 1B: Breakeven analysis on winning trades ──
    print("\n" + "=" * 70)
    print("ISSUE 1B: BREAKEVEN ANALYSIS")
    print("=" * 70)

    winners = [t for t in trades if t.is_winner]
    losers = [t for t in trades if not t.is_winner]
    print(f"  Winners: {len(winners)}, Losers: {len(losers)}")

    be_triggered = [t for t in trades if t.is_breakeven]
    print(f"  Trades with is_breakeven=True: {len(be_triggered)}")

    # For each trade, check if max_favorable would have triggered breakeven
    # Breakeven conditions use CLOSE, but max_favorable uses HIGH/LOW
    # So max_favorable >= 2×stop doesn't guarantee breakeven triggered
    print(f"\n  Breakeven conditions:")
    print(f"    Cond1: favorable_CLOSE >= 2 × stop_distance")
    print(f"    Cond2: favorable_CLOSE >= 0.5 × target_distance")
    print(f"  (Note: breakeven uses CLOSE, not HIGH/LOW)")

    print(f"\n  Max favorable excursion (HIGH/LOW based) vs thresholds:")
    print(f"  {'#':>3} {'Ticker':>6} {'Dir':>5} {'Entry':>8} {'Stop':>8} {'Target':>8} "
          f"{'StopDist':>8} {'MaxFav':>8} {'2xStop':>8} {'0.5xTP':>8} {'ExcRatio':>8} {'Exit':>12} {'BE?':>4}")
    print(f"  {'-'*110}")

    for i, t in enumerate(trades[:30]):  # Show first 30
        stop_dist = t.risk_params.stop_distance
        target_dist = t.risk_params.target_distance
        mf = t.max_favorable
        threshold_1 = 2 * stop_dist
        threshold_2 = 0.5 * target_dist
        exc_ratio = mf / stop_dist if stop_dist > 0 else 0
        direction = "SHORT" if t.direction.value == "short" else "LONG"
        exit_str = t.exit_reason.value if t.exit_reason else "?"
        be_str = "Y" if t.is_breakeven else "N"

        print(f"  {i+1:>3} {t.signal.ticker:>6} {direction:>5} {t.entry_price:>8.2f} "
              f"{t.stop_price:>8.2f} {t.target_price:>8.2f} "
              f"{stop_dist:>8.2f} {mf:>8.2f} {threshold_1:>8.2f} {threshold_2:>8.2f} "
              f"{exc_ratio:>8.2f} {exit_str:>12} {be_str:>4}")

    # Summary stats
    print(f"\n  Summary across ALL {len(trades)} trades:")
    exc_ratios = [t.max_favorable / t.risk_params.stop_distance
                  if t.risk_params.stop_distance > 0 else 0 for t in trades]
    print(f"    Mean max_favorable / stop_dist:  {np.mean(exc_ratios):.2f}")
    print(f"    Median max_favorable / stop_dist: {np.median(exc_ratios):.2f}")
    print(f"    Trades with excursion >= 2.0R:   {sum(1 for r in exc_ratios if r >= 2.0)}")
    print(f"    Trades with excursion >= 1.5R:   {sum(1 for r in exc_ratios if r >= 1.5)}")
    print(f"    Trades with excursion >= 1.0R:   {sum(1 for r in exc_ratios if r >= 1.0)}")

    # Check winners specifically
    print(f"\n  Winners ({len(winners)}) max favorable analysis:")
    w_exc = [t.max_favorable / t.risk_params.stop_distance
             if t.risk_params.stop_distance > 0 else 0 for t in winners]
    print(f"    Mean excursion ratio:  {np.mean(w_exc):.2f}R")
    print(f"    Min excursion ratio:   {np.min(w_exc):.2f}R")
    print(f"    Winners >= 2.0R:       {sum(1 for r in w_exc if r >= 2.0)}")
    print(f"    Winners >= 1.5R:       {sum(1 for r in w_exc if r >= 1.5)}")

    # ── ISSUE 1C: Deep dive on 3 winning trades ──
    print("\n" + "=" * 70)
    print("ISSUE 1C: DEEP DIVE — 3 WINNING TRADES")
    print("=" * 70)

    # Sort winners by P&L descending
    top_winners = sorted(winners, key=lambda t: t.pnl, reverse=True)[:3]

    for idx, t in enumerate(top_winners):
        stop_dist = t.risk_params.stop_distance
        target_dist = t.risk_params.target_distance
        be_thresh_1 = 2 * stop_dist
        be_thresh_2 = 0.5 * target_dist
        direction = "SHORT" if t.direction.value == "short" else "LONG"

        print(f"\n  [{idx+1}] {t.signal.ticker} {direction} | P&L=${t.pnl:.2f} | "
              f"{t.pnl_r:.2f}R | Exit: {t.exit_reason.value}")
        print(f"      Entry:  ${t.entry_price:.2f} at {t.entry_time}")
        print(f"      Stop:   ${t.stop_price:.2f} (dist=${stop_dist:.2f})")
        print(f"      Target: ${t.target_price:.2f} (dist=${target_dist:.2f})")
        print(f"      Exit:   ${t.exit_price:.2f} at {t.exit_time}")
        print(f"      Max favorable: ${t.max_favorable:.2f} ({t.max_favorable/stop_dist:.2f}R)")
        print(f"      Max adverse:   ${t.max_adverse:.2f} ({t.max_adverse/stop_dist:.2f}R)")
        print(f"      BE trigger 1 (2×stop):  ${be_thresh_1:.2f} → needed close at "
              f"${t.entry_price - be_thresh_1:.2f}" if direction == "SHORT"
              else f"      BE trigger 1 (2×stop):  ${be_thresh_1:.2f} → needed close at "
              f"${t.entry_price + be_thresh_1:.2f}")
        print(f"      BE trigger 2 (50% TP):  ${be_thresh_2:.2f} → needed close at "
              f"${t.entry_price - be_thresh_2:.2f}" if direction == "SHORT"
              else f"      BE trigger 2 (50% TP):  ${be_thresh_2:.2f} → needed close at "
              f"${t.entry_price + be_thresh_2:.2f}")
        print(f"      is_breakeven: {t.is_breakeven}")
        print(f"      trailing_stop_active: {t.trailing_stop_active}")
        print(f"      target_tiers: {t.risk_params.target_tiers}")
        print(f"      partial_exits: {t.partial_exits}")

        # Scan M5 bars during the trade to check what CLOSE values looked like
        trade_bars = m5_df[
            (m5_df['Ticker'] == t.signal.ticker) &
            (m5_df['Datetime'] >= t.entry_time) &
            (m5_df['Datetime'] <= t.exit_time)
        ].copy()
        print(f"      Trade duration: {len(trade_bars)} bars")

        if len(trade_bars) > 0:
            if direction == "SHORT":
                trade_bars['fav_close'] = t.entry_price - trade_bars['Close']
                trade_bars['fav_low'] = t.entry_price - trade_bars['Low']
            else:
                trade_bars['fav_close'] = trade_bars['Close'] - t.entry_price
                trade_bars['fav_low'] = trade_bars['High'] - t.entry_price

            max_fav_close = trade_bars['fav_close'].max()
            max_fav_low = trade_bars['fav_low'].max() if direction == "SHORT" else trade_bars['fav_low'].max()

            print(f"      Max favorable (CLOSE):  ${max_fav_close:.2f} ({max_fav_close/stop_dist:.2f}R)")
            print(f"      Max favorable (H/L):    ${max_fav_low:.2f} ({max_fav_low/stop_dist:.2f}R)")
            print(f"      BE cond1 met by CLOSE?: {max_fav_close >= be_thresh_1}")
            print(f"      BE cond2 met by CLOSE?: {max_fav_close >= be_thresh_2}")

            # Show the first few bars
            print(f"      First 5 bars:")
            for _, row in trade_bars.head(5).iterrows():
                fc = t.entry_price - row['Close'] if direction == "SHORT" else row['Close'] - t.entry_price
                fl = t.entry_price - row['Low'] if direction == "SHORT" else row['High'] - t.entry_price
                print(f"        {row['Datetime']} | O={row['Open']:.2f} H={row['High']:.2f} "
                      f"L={row['Low']:.2f} C={row['Close']:.2f} | "
                      f"FavClose={fc:.2f} ({fc/stop_dist:.2f}R) FavHL={fl:.2f} ({fl/stop_dist:.2f}R)")

    # ── ISSUE 1D: Exit reason vs is_breakeven cross-check ──
    print("\n" + "=" * 70)
    print("ISSUE 1D: EXIT REASON CLASSIFICATION BUG CHECK")
    print("=" * 70)
    print(f"  Trades with is_breakeven=True AND exit_reason=STOP_LOSS: "
          f"{sum(1 for t in trades if t.is_breakeven and t.exit_reason == ExitReason.STOP_LOSS)}")
    print(f"  Trades with exit_reason=BREAKEVEN: "
          f"{sum(1 for t in trades if t.exit_reason == ExitReason.BREAKEVEN)}")
    print(f"  → If breakeven triggers but stop_loss is still the exit reason,")
    print(f"     breakeven exits are HIDDEN in the stop_loss count.")

    # ── ISSUE 2: Trail stop analysis ──
    print("\n" + "=" * 70)
    print("ISSUE 2: TRAIL STOP ANALYSIS")
    print("=" * 70)
    trail_active = [t for t in trades if t.trailing_stop_active]
    print(f"  Trades with trailing_stop_active: {len(trail_active)}")
    print(f"  Root cause: tiered target path requires BOTH:")
    print(f"    1. intraday_config set (creates intraday_detector)")
    print(f"    2. tier_config set")
    print(f"  Current config: intraday_config={config.intraday_config}, tier_config is set")
    print(f"  → intraday_detector is None → non-tiered path always taken")
    print(f"  → target_tiers always empty → trail tier never created → trail never activates")

    # ── ISSUE 3: CLP analysis ──
    print("\n" + "=" * 70)
    print("ISSUE 3: CLP DETECTION ANALYSIS")
    print("=" * 70)

    # We need to add CLP tracking to pattern_engine. For now, check trades.
    clp_trades = [t for t in trades if t.signal.pattern.value == "CLP"]
    print(f"  CLP trades executed: {len(clp_trades)}")

    # Check patterns_found breakdown - we need to look at the pattern engine
    print(f"  Total patterns found: {backtester.patterns_found}")
    print(f"  Signals blocked: {backtester.signals_blocked}")

    # To investigate CLP detection, we need to add instrumentation
    # For now, report what we can
    print(f"\n  NOTE: To count CLP detections vs rejections, need to instrument")
    print(f"  pattern_engine._qualify_clp_trigger() with counters.")

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == '__main__':
    main()
