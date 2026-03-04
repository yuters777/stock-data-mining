"""
Diagnostic: CLP detection — count how many are detected vs rejected by trigger gate.
Monkey-patches detect_clp to track rejection reasons.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

from backtester.backtester import Backtester, BacktestConfig
from backtester.core.level_detector import LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngine, PatternEngineConfig
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig
from backtester.data_types import LevelType, SignalDirection

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
    name="diagnose_clp",
)

# CLP tracking counters
clp_stats = {
    'detect_clp_calls': 0,
    'short_close_below_level': 0,
    'short_trigger_rejected': 0,
    'short_trigger_qualified': 0,
    'short_consol_found': 0,
    'long_close_above_level': 0,
    'long_trigger_rejected': 0,
    'long_trigger_qualified': 0,
    'long_consol_found': 0,
    'rejected_examples': [],  # Store first 5 rejected trigger bars
}


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


def patched_detect_clp(self, m5_bars, bar_idx, level, tolerance, atr_m5):
    """Instrumented detect_clp that tracks rejection reasons."""
    clp_stats['detect_clp_calls'] += 1

    min_bars = self.config.clp_min_bars
    max_bars = self.config.clp_max_bars
    max_dev_mult = self.config.clp_max_deviation_atr_mult

    if bar_idx < min_bars + 1:
        return None

    trigger_bar = m5_bars.iloc[bar_idx]
    level_price = level.price

    current_atr = atr_m5.iloc[bar_idx] if bar_idx < len(atr_m5) else None
    if current_atr is None or pd.isna(current_atr) or current_atr <= 0:
        return None

    # Short CLP
    if level.level_type in (LevelType.RESISTANCE, LevelType.MIRROR):
        if trigger_bar['Close'] < level_price:
            clp_stats['short_close_below_level'] += 1
            qualified = self._qualify_clp_trigger(
                trigger_bar, m5_bars, bar_idx, current_atr, 'short')
            if not qualified:
                clp_stats['short_trigger_rejected'] += 1
                if len(clp_stats['rejected_examples']) < 10:
                    bar_range = trigger_bar['High'] - trigger_bar['Low']
                    body = abs(trigger_bar['Close'] - trigger_bar['Open'])
                    close_pos = ((trigger_bar['Close'] - trigger_bar['Low']) / bar_range
                                 if bar_range > 0 else 999)
                    lookback = min(20, bar_idx)
                    avg_vol = (m5_bars.iloc[bar_idx - lookback:bar_idx]['Volume'].mean()
                               if lookback > 0 and 'Volume' in trigger_bar.index else 0)
                    vol_ratio = (trigger_bar['Volume'] / avg_vol
                                 if avg_vol > 0 else 0)
                    clp_stats['rejected_examples'].append({
                        'ticker': trigger_bar['Ticker'],
                        'time': str(trigger_bar['Datetime']),
                        'direction': 'short',
                        'body': body,
                        'atr': current_atr,
                        'body_ratio': body / current_atr if current_atr > 0 else 0,
                        'vol_ratio': vol_ratio,
                        'close_pos': close_pos,
                        'level_price': level_price,
                        'close': trigger_bar['Close'],
                        'OHLC': (trigger_bar['Open'], trigger_bar['High'],
                                 trigger_bar['Low'], trigger_bar['Close']),
                    })
            else:
                clp_stats['short_trigger_qualified'] += 1

    # Long CLP
    if level.level_type in (LevelType.SUPPORT, LevelType.MIRROR):
        if trigger_bar['Close'] > level_price:
            clp_stats['long_close_above_level'] += 1
            qualified = self._qualify_clp_trigger(
                trigger_bar, m5_bars, bar_idx, current_atr, 'long')
            if not qualified:
                clp_stats['long_trigger_rejected'] += 1
                if len(clp_stats['rejected_examples']) < 10:
                    bar_range = trigger_bar['High'] - trigger_bar['Low']
                    body = abs(trigger_bar['Close'] - trigger_bar['Open'])
                    close_pos = ((trigger_bar['High'] - trigger_bar['Close']) / bar_range
                                 if bar_range > 0 else 999)
                    lookback = min(20, bar_idx)
                    avg_vol = (m5_bars.iloc[bar_idx - lookback:bar_idx]['Volume'].mean()
                               if lookback > 0 and 'Volume' in trigger_bar.index else 0)
                    vol_ratio = (trigger_bar['Volume'] / avg_vol
                                 if avg_vol > 0 else 0)
                    clp_stats['rejected_examples'].append({
                        'ticker': trigger_bar['Ticker'],
                        'time': str(trigger_bar['Datetime']),
                        'direction': 'long',
                        'body': body,
                        'atr': current_atr,
                        'body_ratio': body / current_atr if current_atr > 0 else 0,
                        'vol_ratio': vol_ratio,
                        'close_pos': close_pos,
                        'level_price': level_price,
                        'close': trigger_bar['Close'],
                        'OHLC': (trigger_bar['Open'], trigger_bar['High'],
                                 trigger_bar['Low'], trigger_bar['Close']),
                    })
            else:
                clp_stats['long_trigger_qualified'] += 1

    # Call original for actual detection
    return original_detect_clp(self, m5_bars, bar_idx, level, tolerance, atr_m5)


def main():
    print("=" * 70)
    print("DIAGNOSTIC: CLP Detection Analysis")
    print("=" * 70)

    m5_df = load_all_tickers()
    print(f"Loaded {len(m5_df)} bars")

    # Monkey-patch detect_clp
    global original_detect_clp
    original_detect_clp = PatternEngine.detect_clp
    PatternEngine.detect_clp = patched_detect_clp

    backtester = Backtester(config)
    result = backtester.run(m5_df, start_date='2025-02-10', end_date='2026-02-01')

    # Restore
    PatternEngine.detect_clp = original_detect_clp

    print(f"\n  CLP Detection Stats:")
    print(f"    detect_clp called:           {clp_stats['detect_clp_calls']}")
    print(f"")
    print(f"    SHORT:")
    print(f"      Trigger close < level:     {clp_stats['short_close_below_level']}")
    print(f"      Trigger QUALIFIED:         {clp_stats['short_trigger_qualified']}")
    print(f"      Trigger REJECTED:          {clp_stats['short_trigger_rejected']}")
    print(f"    LONG:")
    print(f"      Trigger close > level:     {clp_stats['long_close_above_level']}")
    print(f"      Trigger QUALIFIED:         {clp_stats['long_trigger_qualified']}")
    print(f"      Trigger REJECTED:          {clp_stats['long_trigger_rejected']}")
    print(f"")
    total_close = (clp_stats['short_close_below_level'] +
                   clp_stats['long_close_above_level'])
    total_qual = (clp_stats['short_trigger_qualified'] +
                  clp_stats['long_trigger_qualified'])
    total_rej = (clp_stats['short_trigger_rejected'] +
                 clp_stats['long_trigger_rejected'])
    print(f"    TOTAL close triggers:        {total_close}")
    print(f"    TOTAL qualified:             {total_qual}")
    print(f"    TOTAL rejected:              {total_rej}")
    if total_close > 0:
        print(f"    Rejection rate:              {total_rej/total_close*100:.1f}%")

    print(f"\n  Rejected Trigger Bar Examples (up to 10):")
    print(f"  {'#':>3} {'Ticker':>6} {'Dir':>5} {'Time':>20} "
          f"{'Body':>6} {'ATR':>6} {'BodyR':>6} {'VolR':>6} {'CPos':>6} "
          f"{'Close':>8} {'Level':>8} {'Thresholds'}")
    print(f"  {'-'*120}")
    for i, ex in enumerate(clp_stats['rejected_examples']):
        print(f"  {i+1:>3} {ex['ticker']:>6} {ex['direction']:>5} {ex['time']:>20} "
              f"{ex['body']:>6.2f} {ex['atr']:>6.2f} {ex['body_ratio']:>6.2f} "
              f"{ex['vol_ratio']:>6.2f} {ex['close_pos']:>6.2f} "
              f"{ex['close']:>8.2f} {ex['level_price']:>8.2f} "
              f"body<{1.5*ex['atr']:.2f} vol<{2.0:.1f}x cpos>{0.25:.2f}")

    print(f"\n  CLP trades in final results: "
          f"{sum(1 for t in result.trades if t.signal.pattern.value == 'CLP')}")

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == '__main__':
    main()
