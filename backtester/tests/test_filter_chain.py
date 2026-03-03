"""Tests for the Filter Chain module."""

import pytest
import pandas as pd
import numpy as np

from backtester.core.filter_chain import (
    FilterChain, FilterChainConfig, FilterResult
)
from backtester.core.pattern_engine import Signal, PatternType, TradeDirection
from backtester.core.level_detector import Level, LevelType


def make_level(price=100.0):
    return Level(
        date=pd.Timestamp('2025-03-01'),
        ticker='TEST',
        price=price,
        level_type=LevelType.RESISTANCE,
        score=8,
        bsu_index=0,
        atr_d1=3.0,
        is_paranormal=False,
        touches=3,
        is_round_number=True,
        is_mirror=False,
    )


def make_signal(timestamp=None, ticker='TEST', level=None, entry_price=99.5,
                direction=TradeDirection.SHORT, bar_idx=10):
    if timestamp is None:
        timestamp = pd.Timestamp('2025-03-03 15:00:00')  # 10:00 ET in UTC
    if level is None:
        level = make_level()
    return Signal(
        timestamp=timestamp,
        ticker=ticker,
        level=level,
        pattern=PatternType.LP1,
        direction=direction,
        entry_price=entry_price,
        trigger_bar_idx=bar_idx,
    )


def make_m5_bars(n=20, ticker='TEST', base_price=100.0):
    """Create n M5 bars."""
    rows = []
    base = pd.Timestamp('2025-03-03 09:30:00')
    for i in range(n):
        o = base_price + np.random.uniform(-1, 1)
        h = o + np.random.uniform(0, 1)
        l = o - np.random.uniform(0, 1)
        c = (o + h + l) / 3
        rows.append({
            'Ticker': ticker,
            'Datetime': base + pd.Timedelta(minutes=5 * i),
            'Open': o,
            'High': h,
            'Low': l,
            'Close': c,
            'Volume': 100000,
        })
    return pd.DataFrame(rows)


def make_daily_df(ticker='TEST', atr=3.0):
    """Create a minimal daily DataFrame."""
    return pd.DataFrame([{
        'Ticker': ticker,
        'Date': pd.Timestamp('2025-03-03'),
        'Open': 100.0,
        'High': 103.0,
        'Low': 97.0,
        'Close': 101.0,
        'Volume': 5000000,
        'ATR': atr,
        'ModifiedATR': atr,
    }])


class TestATRFilter:
    def test_atr_hard_block(self):
        """Signal with ATR ratio < 0.30 should be hard blocked."""
        fc = FilterChain()
        signal = make_signal(
            timestamp=pd.Timestamp('2025-03-03 10:00:00'),
            bar_idx=5,
        )

        # Create M5 data where day high is very close to level (small distance)
        m5_bars = []
        base = pd.Timestamp('2025-03-03 09:30:00')
        for i in range(10):
            m5_bars.append({
                'Ticker': 'TEST',
                'Datetime': base + pd.Timedelta(minutes=5 * i),
                'Open': 100.0,
                'High': 100.2,  # Day high barely above level at 100
                'Low': 99.8,
                'Close': 100.0,
                'Volume': 100000,
            })
        m5_df = pd.DataFrame(m5_bars)

        daily = make_daily_df(atr=10.0)  # ATR=10, distance~0.2 → ratio=0.02

        result = fc._check_atr_filter(signal, m5_df, daily)
        assert result.passed == False
        assert 'HARD BLOCK' in result.reason

    def test_atr_above_threshold_passes(self):
        """Signal with ATR ratio >= threshold should pass.
        SHORT at resistance 100: distance = level - day_low = 100 - 97 = 3, ratio = 3/3 = 1.0
        """
        fc = FilterChain(FilterChainConfig(atr_entry_threshold=0.75))
        signal = make_signal(
            timestamp=pd.Timestamp('2025-03-03 15:30:00'),
            bar_idx=12,
        )

        m5_bars = []
        base = pd.Timestamp('2025-03-03 14:30:00')
        for i in range(15):
            m5_bars.append({
                'Ticker': 'TEST',
                'Datetime': base + pd.Timedelta(minutes=5 * i),
                'Open': 99.0,
                'High': 100.5,
                'Low': 97.0,    # Day low = 97, distance to level 100 = 3
                'Close': 99.5,
                'Volume': 100000,
            })
        m5_df = pd.DataFrame(m5_bars)

        daily = make_daily_df(atr=3.0)  # ATR=3, distance=3 → ratio=1.0

        result = fc._check_atr_filter(signal, m5_df, daily)
        assert result.passed == True


class TestTimeFilter:
    def test_before_open_blocked(self):
        """Signals before 14:35 UTC (09:35 ET) should be blocked."""
        fc = FilterChain()
        signal = make_signal(timestamp=pd.Timestamp('2025-03-03 14:30:00'))
        result = fc._check_time_filter(signal)
        assert result.passed == False

    def test_after_open_delay_passes(self):
        """Signals at 14:35+ UTC (09:35+ ET) should pass."""
        fc = FilterChain()
        signal = make_signal(timestamp=pd.Timestamp('2025-03-03 14:40:00'))
        result = fc._check_time_filter(signal)
        assert result.passed == True

    def test_after_market_close_blocked(self):
        """Signals at 21:00+ UTC (16:00+ ET) should be blocked."""
        fc = FilterChain()
        signal = make_signal(timestamp=pd.Timestamp('2025-03-03 21:05:00'))
        result = fc._check_time_filter(signal)
        assert result.passed == False


class TestEarningsFilter:
    def test_earnings_day_blocked(self):
        cfg = FilterChainConfig(
            earnings_dates={'TEST': {pd.Timestamp('2025-03-03').normalize()}}
        )
        fc = FilterChain(cfg)
        signal = make_signal(timestamp=pd.Timestamp('2025-03-03 10:00:00'))
        result = fc._check_earnings_filter(signal)
        assert result.passed == False

    def test_non_earnings_day_passes(self):
        cfg = FilterChainConfig(earnings_dates={'TEST': set()})
        fc = FilterChain(cfg)
        signal = make_signal(timestamp=pd.Timestamp('2025-03-03 10:00:00'))
        result = fc._check_earnings_filter(signal)
        assert result.passed == True


class TestVolumeFilter:
    def test_true_breakout_blocked(self):
        """High volume + close beyond level = true breakout → BLOCK."""
        fc = FilterChain()
        # Short signal: V > 2x AND Close > Level → block
        signal = make_signal(
            timestamp=pd.Timestamp('2025-03-03 10:30:00'),
            bar_idx=10,
        )

        m5_bars = []
        base = pd.Timestamp('2025-03-03 09:30:00')
        for i in range(11):
            vol = 100000 if i < 10 else 300000  # Signal bar: 3x average
            close = 99.5 if i < 10 else 100.5   # Signal bar: close above level
            m5_bars.append({
                'Ticker': 'TEST',
                'Datetime': base + pd.Timedelta(minutes=5 * i),
                'Open': 99.5,
                'High': 101.0,
                'Low': 99.0,
                'Close': close,
                'Volume': vol,
            })
        m5_df = pd.DataFrame(m5_bars)

        result = fc._check_volume_filter(signal, m5_df)
        assert result.passed == False

    def test_low_volume_passes(self):
        """Normal volume should pass the filter."""
        fc = FilterChain()
        signal = make_signal(bar_idx=10)

        m5_bars = []
        base = pd.Timestamp('2025-03-03 09:30:00')
        for i in range(11):
            m5_bars.append({
                'Ticker': 'TEST',
                'Datetime': base + pd.Timedelta(minutes=5 * i),
                'Open': 99.5,
                'High': 100.5,
                'Low': 99.0,
                'Close': 99.3,
                'Volume': 100000,
            })
        m5_df = pd.DataFrame(m5_bars)

        result = fc._check_volume_filter(signal, m5_df)
        assert result.passed == True


class TestTimeBucket:
    def test_open_bucket(self):
        fc = FilterChain()
        assert fc.get_time_bucket(pd.Timestamp('2025-03-03 09:35:00')) == "Open"
        assert fc.get_time_bucket(pd.Timestamp('2025-03-03 10:25:00')) == "Open"

    def test_midday_bucket(self):
        fc = FilterChain()
        assert fc.get_time_bucket(pd.Timestamp('2025-03-03 11:00:00')) == "Midday"
        assert fc.get_time_bucket(pd.Timestamp('2025-03-03 13:55:00')) == "Midday"

    def test_close_bucket(self):
        fc = FilterChain()
        assert fc.get_time_bucket(pd.Timestamp('2025-03-03 14:00:00')) == "Close"
        assert fc.get_time_bucket(pd.Timestamp('2025-03-03 15:55:00')) == "Close"


class TestFunnelSummary:
    def test_empty_funnel(self):
        fc = FilterChain()
        summary = fc.get_funnel_summary()
        assert summary['total_signals'] == 0
        assert summary['passed'] == 0
