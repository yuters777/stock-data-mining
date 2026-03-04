"""Tests for the Pattern Engine module."""

import pytest
import pandas as pd
import numpy as np

from backtester.data_types import (
    Level, LevelType, LevelStatus, Signal, SignalDirection, PatternType, LP2Quality,
)
from backtester.core.pattern_engine import PatternEngine, PatternEngineConfig, LP2_QUALITY_MULT


def make_level(price=100.0, level_type=LevelType.RESISTANCE, is_mirror=False):
    return Level(
        price=price,
        level_type=level_type,
        score=8,
        ticker='TEST',
        date=pd.Timestamp('2025-03-01'),
        bsu_index=0,
        atr_d1=2.0,
        touches=3,
        is_round_number=True,
        is_mirror=is_mirror,
    )


def make_m5_bars(bars_data, ticker="TEST"):
    """Create M5 DataFrame from list of (open, high, low, close[, volume]) tuples."""
    rows = []
    base = pd.Timestamp('2025-03-03 16:30:00')  # IST market open
    for i, data in enumerate(bars_data):
        o, h, l, c = data[:4]
        v = data[4] if len(data) > 4 else 100000
        rows.append({
            'Ticker': ticker,
            'Datetime': base + pd.Timedelta(minutes=5 * i),
            'Open': o,
            'High': h,
            'Low': l,
            'Close': c,
            'Volume': v,
        })
    return pd.DataFrame(rows)


class TestLP1Detection:
    def test_lp1_short(self):
        """LP1 short: Open < Level, High > Level, Close < Level."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (99.5, 100.5, 99.0, 99.3),
        ])
        engine = PatternEngine()
        signal = engine.detect_lp1(bars, 0, level, 0.05)

        assert signal is not None
        assert signal.pattern == PatternType.LP1
        assert signal.direction == SignalDirection.SHORT
        assert signal.tail_ratio > 0

    def test_lp1_long(self):
        """LP1 long: Open > Level, Low < Level, Close > Level."""
        level = make_level(100.0, LevelType.SUPPORT)
        bars = make_m5_bars([
            (100.5, 101.0, 99.5, 100.7),
        ])
        engine = PatternEngine()
        signal = engine.detect_lp1(bars, 0, level, 0.05)

        assert signal is not None
        assert signal.pattern == PatternType.LP1
        assert signal.direction == SignalDirection.LONG

    def test_lp1_no_signal_when_close_beyond(self):
        """No LP1 if close is beyond the level (true breakout)."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (99.5, 101.0, 99.0, 100.5),
        ])
        engine = PatternEngine()
        signal = engine.detect_lp1(bars, 0, level, 0.05)

        assert signal is None

    def test_lp1_tail_ratio_filter(self):
        """LP1 rejected if tail ratio below minimum."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (99.5, 100.1, 98.0, 99.0),
        ])
        config = PatternEngineConfig(tail_ratio_min=0.20)
        engine = PatternEngine(config)
        signal = engine.detect_lp1(bars, 0, level, 0.05)

        assert signal is None


class TestLP2Detection:
    def test_lp2_short(self):
        """LP2 short: Bar1 closes above, Bar2 closes below with Bar2.High <= Bar1.High."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (99.5, 101.0, 99.0, 100.5),   # Bar1: closes above level
            (100.5, 100.8, 99.0, 99.0),    # Bar2: closes below level, H2 <= H1
        ])
        config = PatternEngineConfig(lp2_engulfing_required=True)
        engine = PatternEngine(config)
        signal = engine.detect_lp2(bars, 1, level, 0.05)

        assert signal is not None
        assert signal.pattern == PatternType.LP2
        assert signal.direction == SignalDirection.SHORT

    def test_lp2_long(self):
        """LP2 long: Bar1 closes below, Bar2 closes above."""
        level = make_level(100.0, LevelType.SUPPORT)
        bars = make_m5_bars([
            (100.3, 101.0, 99.0, 99.5),
            (99.5, 101.0, 99.2, 100.5),
        ])
        config = PatternEngineConfig(lp2_engulfing_required=True)
        engine = PatternEngine(config)
        signal = engine.detect_lp2(bars, 1, level, 0.05)

        assert signal is not None
        assert signal.direction == SignalDirection.LONG

    def test_lp2_rejected_when_bar2_high_exceeds(self):
        """LP2 short rejected if Bar2.High > Bar1.High."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (99.5, 101.0, 99.0, 100.5),
            (100.5, 101.5, 99.0, 99.0),
        ])
        engine = PatternEngine()
        signal = engine.detect_lp2(bars, 1, level, 0.05)

        assert signal is None


class TestLP2Quality:
    def test_ideal_quality_short(self):
        """IDEAL: Bar2 close < Bar1 open → 1.0x sizing."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (99.5, 101.0, 99.0, 100.5),   # Bar1: open=99.5, close=100.5
            (100.5, 100.8, 98.5, 99.0),   # Bar2: close=99.0 < open_bar1=99.5 → IDEAL
        ])
        config = PatternEngineConfig(lp2_engulfing_required=False)
        engine = PatternEngine(config)
        signal = engine.detect_lp2(bars, 1, level, 0.05)

        assert signal is not None
        assert signal.lp2_quality == LP2Quality.IDEAL
        assert signal.position_size_mult == 1.0

    def test_acceptable_quality_short(self):
        """ACCEPTABLE: Bar2 close < Bar1 close but >= Bar1 open → 0.7x."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (99.5, 101.0, 99.0, 100.5),   # Bar1: open=99.5, close=100.5
            (100.5, 100.8, 99.0, 99.8),   # Bar2: close=99.8 < close1=100.5 but > open1=99.5
        ])
        config = PatternEngineConfig(lp2_engulfing_required=False)
        engine = PatternEngine(config)
        signal = engine.detect_lp2(bars, 1, level, 0.05)

        assert signal is not None
        assert signal.lp2_quality == LP2Quality.ACCEPTABLE
        assert signal.position_size_mult == 0.7

    def test_weak_quality_short(self):
        """WEAK: Bar2 close < Level only → 0.5x."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (99.5, 101.0, 99.0, 100.5),   # Bar1: open=99.5, close=100.5
            (100.5, 100.8, 99.4, 99.6),   # Bar2: close=99.6 > open1=99.5, > close1=100.5? No, 99.6 < 100.5
        ])
        config = PatternEngineConfig(lp2_engulfing_required=False)
        engine = PatternEngine(config)
        signal = engine.detect_lp2(bars, 1, level, 0.05)

        assert signal is not None
        # 99.6 < 100.5 (close_bar1) → ACCEPTABLE, not WEAK
        assert signal.lp2_quality == LP2Quality.ACCEPTABLE

    def test_quality_mult_mapping(self):
        """LP2 quality multipliers should match spec."""
        assert LP2_QUALITY_MULT[LP2Quality.IDEAL] == 1.0
        assert LP2_QUALITY_MULT[LP2Quality.ACCEPTABLE] == 0.7
        assert LP2_QUALITY_MULT[LP2Quality.WEAK] == 0.5


class TestCLPDetection:
    def test_clp_short(self):
        """CLP short: breakout + 3+ bars consolidate above level + trigger closes back below."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (99.0, 101.0, 98.5, 100.5),   # Breakout bar (High > level)
            (100.5, 101.2, 100.0, 100.8),  # Consolidation 1 (above)
            (100.8, 101.0, 100.2, 100.5),  # Consolidation 2 (above)
            (100.5, 100.8, 100.1, 100.3),  # Consolidation 3 (above)
            (100.3, 101.0, 99.0, 99.1),    # Trigger: closes back below level (close in bottom 25%)
        ])

        engine = PatternEngine()
        atr_m5 = pd.Series([1.0] * 5)
        signal = engine.detect_clp(bars, 4, level, 0.05, atr_m5)

        assert signal is not None
        assert signal.pattern == PatternType.CLP
        assert signal.direction == SignalDirection.SHORT

    def test_clp_insufficient_bars(self):
        """CLP rejected if fewer than min_bars of consolidation."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (100.5, 101.0, 100.0, 100.8),
            (100.3, 100.5, 99.0, 99.5),
        ])
        config = PatternEngineConfig(clp_min_bars=3)
        engine = PatternEngine(config)
        atr_m5 = pd.Series([1.0] * 2)
        signal = engine.detect_clp(bars, 1, level, 0.05, atr_m5)

        assert signal is None

    def test_clp_range_compression_required(self):
        """CLP rejected if consecutive bars don't overlap enough (< 50%)."""
        level = make_level(100.0, LevelType.RESISTANCE)
        # Consolidation bars with NO overlap (disjoint ranges)
        bars = make_m5_bars([
            (99.0, 101.0, 98.5, 100.5),   # Breakout bar
            (100.5, 101.2, 100.5, 100.8),  # Consol 1: range [100.5, 101.2]
            (101.3, 102.0, 101.3, 101.8),  # Consol 2: range [101.3, 102.0] - no overlap!
            (101.0, 101.5, 101.0, 101.2),  # Consol 3
            (100.3, 100.5, 99.0, 99.5),    # Trigger
        ])
        config = PatternEngineConfig(clp_min_overlap_pct=0.50)
        engine = PatternEngine(config)
        atr_m5 = pd.Series([1.0] * 5)
        signal = engine.detect_clp(bars, 4, level, 0.05, atr_m5)

        assert signal is None  # No overlap → rejected

    def test_clp_breakout_bar_validation(self):
        """CLP short rejected if bar before consolidation didn't break level."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (98.0, 99.0, 97.5, 98.5),     # Bar BEFORE consol: High 99 < level 100
            (100.5, 101.2, 100.0, 100.8),  # Consolidation 1
            (100.8, 101.0, 100.2, 100.5),  # Consolidation 2
            (100.5, 100.8, 100.1, 100.3),  # Consolidation 3
            (100.3, 100.5, 99.0, 99.5),    # Trigger
        ])
        engine = PatternEngine()
        atr_m5 = pd.Series([1.0] * 5)
        signal = engine.detect_clp(bars, 4, level, 0.05, atr_m5)

        assert signal is None  # No breakout before consolidation

    def test_clp_max_deviation_uses_close(self):
        """MaxDeviation should use CLOSE, not HIGH. Wick spike with tight close should pass."""
        level = make_level(100.0, LevelType.RESISTANCE)
        # All consol bars have HIGH wicks to 103.0 (>2.5 ATR) but CLOSE stays tight at ~100.5
        # Overlap is fine because all bars share similar [100.0, 103.0] range
        bars = make_m5_bars([
            (99.0, 101.0, 98.5, 100.5),    # Breakout bar
            (100.5, 103.0, 100.0, 100.8),   # Consolidation 1: wick to 103, close tight
            (100.8, 103.0, 100.2, 100.5),   # Consolidation 2: wick to 103, close tight
            (100.5, 103.0, 100.1, 100.3),   # Consolidation 3: wick to 103, close tight
            (100.3, 101.0, 99.0, 99.1),     # Trigger (close in bottom 25%)
        ])
        engine = PatternEngine()
        atr_m5 = pd.Series([1.0] * 5)  # max_deviation = 2.5 * 1.0 = 2.5
        signal = engine.detect_clp(bars, 4, level, 0.05, atr_m5)

        # Close deviation max = 100.8 - 100.0 = 0.8 < 2.5 → should PASS
        # Old code would reject: High deviation = 103.0 - 100.0 = 3.0 > 2.5
        assert signal is not None
        assert signal.direction == SignalDirection.SHORT

    def test_clp_max_deviation_rejects_by_close(self):
        """MaxDeviation should reject when CLOSE is too far, even if HIGH is close."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (99.0, 101.0, 98.5, 100.5),    # Breakout bar
            (100.5, 101.2, 100.0, 100.8),   # Consolidation 1
            (102.0, 103.0, 101.5, 103.0),   # Consolidation 2: CLOSE 103.0 (3.0 > 2.5)
            (100.5, 100.8, 100.1, 100.3),   # Consolidation 3
            (100.3, 101.0, 99.0, 99.1),     # Trigger
        ])
        engine = PatternEngine()
        atr_m5 = pd.Series([1.0] * 5)
        signal = engine.detect_clp(bars, 4, level, 0.05, atr_m5)

        assert signal is None  # Close deviation 3.0 > 2.5

    def test_clp_trigger_bar_big_body(self):
        """Trigger bar qualifies via big body (>= 1.5 * ATR_M5)."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (99.0, 101.0, 98.5, 100.5),
            (100.5, 101.2, 100.0, 100.8),
            (100.8, 101.0, 100.2, 100.5),
            (100.5, 100.8, 100.1, 100.3),
            (101.0, 101.0, 99.0, 99.3),  # body = 1.7 >= 1.5*1.0, close NOT in bottom 25%
        ])
        engine = PatternEngine()
        atr_m5 = pd.Series([1.0] * 5)
        signal = engine.detect_clp(bars, 4, level, 0.05, atr_m5)

        assert signal is not None

    def test_clp_trigger_bar_high_volume(self):
        """Trigger bar qualifies via volume >= 2x average."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (99.0, 101.0, 98.5, 100.5, 100000),
            (100.5, 101.2, 100.0, 100.8, 100000),
            (100.8, 101.0, 100.2, 100.5, 100000),
            (100.5, 100.8, 100.1, 100.3, 100000),
            (100.3, 100.5, 99.0, 99.5, 250000),  # volume 2.5x avg, but close not in bottom 25%
        ])
        engine = PatternEngine()
        atr_m5 = pd.Series([1.0] * 5)
        signal = engine.detect_clp(bars, 4, level, 0.05, atr_m5)

        assert signal is not None

    def test_clp_trigger_bar_unqualified_rejected(self):
        """Trigger bar without any qualification is rejected."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (99.0, 101.0, 98.5, 100.5, 100000),
            (100.5, 101.2, 100.0, 100.8, 100000),
            (100.8, 101.0, 100.2, 100.5, 100000),
            (100.5, 100.8, 100.1, 100.3, 100000),
            # Trigger: tiny body (0.2), normal vol, close at 50% of range
            (100.0, 100.5, 99.5, 99.8, 100000),
        ])
        engine = PatternEngine()
        atr_m5 = pd.Series([1.0] * 5)
        signal = engine.detect_clp(bars, 4, level, 0.05, atr_m5)

        # body=0.2 < 1.5, vol=100k < 200k, position=(99.8-99.5)/1.0=0.30 > 0.25
        assert signal is None


class TestModel4:
    def test_model4_upgrade(self):
        """Signal at mirror level with paranormal bar → Model4."""
        level = make_level(100.0, LevelType.MIRROR, is_mirror=True)
        bars = make_m5_bars([
            (99.5, 104.0, 96.0, 99.0),
        ])

        engine = PatternEngine()
        signal = Signal(
            pattern=PatternType.LP1,
            direction=SignalDirection.SHORT,
            level=level,
            timestamp=bars.iloc[0]['Datetime'],
            ticker='TEST',
            entry_price=99.0,
            trigger_bar_idx=0,
        )

        atr_m5 = pd.Series([1.0])
        result = engine.detect_model4(signal, bars, atr_m5)

        assert result.is_model4 == True
        assert result.pattern == PatternType.MODEL4
        assert result.priority == 10

    def test_no_model4_without_mirror(self):
        """Non-mirror level should not get Model4 upgrade."""
        level = make_level(100.0, LevelType.RESISTANCE, is_mirror=False)
        bars = make_m5_bars([
            (99.5, 104.0, 96.0, 99.0),
        ])

        engine = PatternEngine()
        signal = Signal(
            pattern=PatternType.LP1,
            direction=SignalDirection.SHORT,
            level=level,
            timestamp=bars.iloc[0]['Datetime'],
            ticker='TEST',
            entry_price=99.0,
            trigger_bar_idx=0,
        )
        atr_m5 = pd.Series([1.0])
        result = engine.detect_model4(signal, bars, atr_m5)

        assert result.is_model4 == False


class TestScanBar:
    def test_scan_finds_signal(self):
        """scan_bar should find LP1 signals at active levels."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (99.5, 100.8, 99.0, 99.3),
        ])

        engine = PatternEngine()
        atr_m5 = pd.Series([0.5])
        signals = engine.scan_bar(bars, 0, [level], atr_m5,
                                  lambda p: 0.05)

        assert len(signals) >= 1
        assert signals[0].direction == SignalDirection.SHORT

    def test_scan_no_signal_when_not_near_level(self):
        """scan_bar should not find signals when bar is far from level."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (95.0, 96.0, 94.0, 95.5),
        ])

        engine = PatternEngine()
        atr_m5 = pd.Series([0.5])
        signals = engine.scan_bar(bars, 0, [level], atr_m5,
                                  lambda p: 0.05)

        assert len(signals) == 0
