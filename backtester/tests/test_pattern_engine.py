"""Tests for the Pattern Engine module."""

import pytest
import pandas as pd
import numpy as np

from backtester.core.pattern_engine import (
    PatternEngine, PatternEngineConfig, PatternType, TradeDirection, Signal
)
from backtester.core.level_detector import Level, LevelType, LevelStatus


def make_level(price=100.0, level_type=LevelType.RESISTANCE, is_mirror=False):
    return Level(
        date=pd.Timestamp('2025-03-01'),
        ticker='TEST',
        price=price,
        level_type=level_type,
        score=8,
        bsu_index=0,
        atr_d1=2.0,
        is_paranormal=False,
        touches=3,
        is_round_number=True,
        is_mirror=is_mirror,
    )


def make_m5_bars(bars_data, ticker="TEST"):
    """Create M5 DataFrame from list of (open, high, low, close, volume) tuples."""
    rows = []
    base = pd.Timestamp('2025-03-03 09:30:00')
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
            (99.5, 100.5, 99.0, 99.3),  # Open < 100, High > 100, Close < 100
        ])
        engine = PatternEngine()
        signal = engine.detect_lp1(bars, 0, level, 0.05)

        assert signal is not None
        assert signal.pattern == PatternType.LP1
        assert signal.direction == TradeDirection.SHORT
        assert signal.tail_ratio > 0

    def test_lp1_long(self):
        """LP1 long: Open > Level, Low < Level, Close > Level."""
        level = make_level(100.0, LevelType.SUPPORT)
        bars = make_m5_bars([
            (100.5, 101.0, 99.5, 100.7),  # Open > 100, Low < 100, Close > 100
        ])
        engine = PatternEngine()
        signal = engine.detect_lp1(bars, 0, level, 0.05)

        assert signal is not None
        assert signal.pattern == PatternType.LP1
        assert signal.direction == TradeDirection.LONG

    def test_lp1_no_signal_when_close_beyond(self):
        """No LP1 if close is beyond the level (true breakout)."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (99.5, 101.0, 99.0, 100.5),  # Close > Level → no false breakout
        ])
        engine = PatternEngine()
        signal = engine.detect_lp1(bars, 0, level, 0.05)

        assert signal is None

    def test_lp1_tail_ratio_filter(self):
        """LP1 rejected if tail ratio below minimum."""
        level = make_level(100.0, LevelType.RESISTANCE)
        # Very small tail: high barely above level
        bars = make_m5_bars([
            (99.5, 100.1, 98.0, 99.0),  # Tail = (100.1-100)/2.1 = 0.048
        ])
        config = PatternEngineConfig(tail_ratio_min=0.20)
        engine = PatternEngine(config)
        signal = engine.detect_lp1(bars, 0, level, 0.05)

        assert signal is None  # Tail ratio too low


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
        assert signal.direction == TradeDirection.SHORT

    def test_lp2_long(self):
        """LP2 long: Bar1 closes below, Bar2 closes above."""
        level = make_level(100.0, LevelType.SUPPORT)
        bars = make_m5_bars([
            (100.3, 101.0, 99.0, 99.5),   # Bar1: closes below level, Open=100.3
            (99.5, 101.0, 99.2, 100.5),    # Bar2: closes above level (100.5>100.3), L2>=L1
        ])
        config = PatternEngineConfig(lp2_engulfing_required=True)
        engine = PatternEngine(config)
        signal = engine.detect_lp2(bars, 1, level, 0.05)

        assert signal is not None
        assert signal.direction == TradeDirection.LONG

    def test_lp2_rejected_when_bar2_high_exceeds(self):
        """LP2 short rejected if Bar2.High > Bar1.High."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (99.5, 101.0, 99.0, 100.5),   # Bar1
            (100.5, 101.5, 99.0, 99.0),   # Bar2: H2 > H1 → rejected
        ])
        engine = PatternEngine()
        signal = engine.detect_lp2(bars, 1, level, 0.05)

        assert signal is None


class TestCLPDetection:
    def test_clp_short(self):
        """CLP short: 3+ bars consolidate above level, trigger closes back below."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (99.0, 101.0, 98.5, 100.5),   # Breakout bar
            (100.5, 101.2, 100.0, 100.8),  # Consolidation 1 (above)
            (100.8, 101.0, 100.2, 100.5),  # Consolidation 2 (above)
            (100.5, 100.8, 100.1, 100.3),  # Consolidation 3 (above)
            (100.3, 100.5, 99.0, 99.5),    # Trigger: closes back below level
        ])

        engine = PatternEngine()
        atr_m5 = pd.Series([1.0] * 5)  # Constant ATR
        signal = engine.detect_clp(bars, 4, level, 0.05, atr_m5)

        assert signal is not None
        assert signal.pattern == PatternType.CLP
        assert signal.direction == TradeDirection.SHORT

    def test_clp_insufficient_bars(self):
        """CLP rejected if fewer than min_bars of consolidation."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (100.5, 101.0, 100.0, 100.8),  # Only 1 consolidation bar
            (100.3, 100.5, 99.0, 99.5),    # Trigger
        ])
        config = PatternEngineConfig(clp_min_bars=3)
        engine = PatternEngine(config)
        atr_m5 = pd.Series([1.0] * 2)
        signal = engine.detect_clp(bars, 1, level, 0.05, atr_m5)

        assert signal is None  # Not enough bars


class TestModel4:
    def test_model4_upgrade(self):
        """Signal at mirror level with paranormal bar → Model4."""
        level = make_level(100.0, LevelType.MIRROR, is_mirror=True)
        bars = make_m5_bars([
            (99.5, 104.0, 96.0, 99.0),  # Range = 8.0, ATR = 1.0 → paranormal
        ])

        engine = PatternEngine()
        signal = Signal(
            timestamp=bars.iloc[0]['Datetime'],
            ticker='TEST',
            level=level,
            pattern=PatternType.LP1,
            direction=TradeDirection.SHORT,
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
            timestamp=bars.iloc[0]['Datetime'],
            ticker='TEST',
            level=level,
            pattern=PatternType.LP1,
            direction=TradeDirection.SHORT,
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
            (99.5, 100.8, 99.0, 99.3),  # LP1 short pattern
        ])

        engine = PatternEngine()
        atr_m5 = pd.Series([0.5])
        signals = engine.scan_bar(bars, 0, [level], atr_m5,
                                  lambda p: 0.05)

        assert len(signals) >= 1
        assert signals[0].direction == TradeDirection.SHORT

    def test_scan_no_signal_when_not_near_level(self):
        """scan_bar should not find signals when bar is far from level."""
        level = make_level(100.0, LevelType.RESISTANCE)
        bars = make_m5_bars([
            (95.0, 96.0, 94.0, 95.5),  # Far from level
        ])

        engine = PatternEngine()
        atr_m5 = pd.Series([0.5])
        signals = engine.scan_bar(bars, 0, [level], atr_m5,
                                  lambda p: 0.05)

        assert len(signals) == 0
