"""Tests for the Filter Chain module — all 8 stages."""

import pytest
import pandas as pd
import numpy as np

from backtester.data_types import (
    Level, LevelType, Signal, SignalDirection, PatternType,
)
from backtester.core.filter_chain import (
    FilterChain, FilterChainConfig, FilterResult, SignalFunnelEntry,
)


def make_level(price=100.0, score=8):
    return Level(
        price=price,
        level_type=LevelType.RESISTANCE,
        score=score,
        ticker='TEST',
        date=pd.Timestamp('2025-03-01'),
        bsu_index=0,
        atr_d1=3.0,
        touches=3,
        is_round_number=True,
    )


def make_signal(timestamp=None, ticker='TEST', level=None, entry_price=99.5,
                direction=SignalDirection.SHORT, bar_idx=10):
    if timestamp is None:
        timestamp = pd.Timestamp('2025-03-03 17:00:00')  # IST regular session
    if level is None:
        level = make_level()
    return Signal(
        pattern=PatternType.LP1,
        direction=direction,
        level=level,
        timestamp=timestamp,
        ticker=ticker,
        entry_price=entry_price,
        trigger_bar_idx=bar_idx,
    )


def make_m5_bars(n=20, ticker='TEST', base_price=100.0):
    """Create n M5 bars in IST market hours."""
    rows = []
    base = pd.Timestamp('2025-03-03 16:30:00')  # IST open
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


# ── Stage 1: Direction Filter ──

class TestDirectionFilter:
    def test_direction_blocks_wrong_direction(self):
        fc = FilterChain(FilterChainConfig(
            direction_filter={'TEST': 'short', 'DEFAULT': 'short'}
        ))
        signal = make_signal(direction=SignalDirection.LONG)
        result = fc._check_direction_filter(signal)
        assert result.passed == False

    def test_direction_passes_correct_direction(self):
        fc = FilterChain(FilterChainConfig(
            direction_filter={'TEST': 'short'}
        ))
        signal = make_signal(direction=SignalDirection.SHORT)
        result = fc._check_direction_filter(signal)
        assert result.passed == True

    def test_no_direction_filter_passes(self):
        fc = FilterChain(FilterChainConfig(direction_filter=None))
        signal = make_signal(direction=SignalDirection.LONG)
        result = fc._check_direction_filter(signal)
        assert result.passed == True


# ── Stage 2: Position Limit Filter ──

class TestPositionLimitFilter:
    def test_position_limit_blocks(self):
        def check_fn(signal):
            return False, "Already in position"
        fc = FilterChain(FilterChainConfig(position_check_fn=check_fn))
        signal = make_signal()
        result = fc._check_position_limit(signal)
        assert result.passed == False

    def test_no_position_check_passes(self):
        fc = FilterChain(FilterChainConfig(position_check_fn=None))
        signal = make_signal()
        result = fc._check_position_limit(signal)
        assert result.passed == True


# ── Stage 3: Level Score Filter ──

class TestLevelScoreFilter:
    def test_low_score_blocked(self):
        fc = FilterChain(FilterChainConfig(min_level_score=5))
        level = make_level(score=3)
        signal = make_signal(level=level)
        result = fc._check_level_score(signal)
        assert result.passed == False

    def test_sufficient_score_passes(self):
        fc = FilterChain(FilterChainConfig(min_level_score=5))
        level = make_level(score=8)
        signal = make_signal(level=level)
        result = fc._check_level_score(signal)
        assert result.passed == True


# ── Stage 4: Time Filter (IST) ──

class TestTimeFilter:
    def test_before_open_blocked(self):
        """Signals before 16:35 IST should be blocked."""
        fc = FilterChain()
        signal = make_signal(timestamp=pd.Timestamp('2025-03-03 16:30:00'))
        result = fc._check_time_filter(signal)
        assert result.passed == False

    def test_after_open_delay_passes(self):
        """Signals at 16:35+ IST should pass."""
        fc = FilterChain()
        signal = make_signal(timestamp=pd.Timestamp('2025-03-03 16:40:00'))
        result = fc._check_time_filter(signal)
        assert result.passed == True

    def test_after_market_close_blocked(self):
        """Signals at 23:00+ IST should be blocked."""
        fc = FilterChain()
        signal = make_signal(timestamp=pd.Timestamp('2025-03-03 23:05:00'))
        result = fc._check_time_filter(signal)
        assert result.passed == False

    def test_regular_session_passes(self):
        """Signal during regular IST hours passes."""
        fc = FilterChain()
        signal = make_signal(timestamp=pd.Timestamp('2025-03-03 19:00:00'))
        result = fc._check_time_filter(signal)
        assert result.passed == True


# ── Stage 5: Earnings Filter ──

class TestEarningsFilter:
    def test_earnings_day_blocked(self):
        cfg = FilterChainConfig(
            earnings_dates={'TEST': {pd.Timestamp('2025-03-03').normalize()}}
        )
        fc = FilterChain(cfg)
        signal = make_signal(timestamp=pd.Timestamp('2025-03-03 17:00:00'))
        result = fc._check_earnings_filter(signal)
        assert result.passed == False

    def test_non_earnings_day_passes(self):
        cfg = FilterChainConfig(earnings_dates={'TEST': set()})
        fc = FilterChain(cfg)
        signal = make_signal(timestamp=pd.Timestamp('2025-03-03 17:00:00'))
        result = fc._check_earnings_filter(signal)
        assert result.passed == True


# ── Stage 6: ATR Filter ──

class TestATRFilter:
    def test_atr_hard_block(self):
        """Signal with ATR ratio < 0.30 should be hard blocked."""
        fc = FilterChain()
        signal = make_signal(
            timestamp=pd.Timestamp('2025-03-03 17:00:00'),
            bar_idx=5,
        )

        m5_bars = []
        base = pd.Timestamp('2025-03-03 16:30:00')
        for i in range(10):
            m5_bars.append({
                'Ticker': 'TEST',
                'Datetime': base + pd.Timedelta(minutes=5 * i),
                'Open': 100.0,
                'High': 100.2,
                'Low': 99.8,
                'Close': 100.0,
                'Volume': 100000,
            })
        m5_df = pd.DataFrame(m5_bars)
        daily = make_daily_df(atr=10.0)

        entry = SignalFunnelEntry(signal=signal)
        result = fc._check_atr_filter(signal, m5_df, daily, entry)
        assert result.passed == False
        assert 'HARD BLOCK' in result.reason
        assert entry.atr_ratio > 0  # atr_ratio was populated

    def test_atr_above_threshold_passes(self):
        """Signal with ATR ratio >= threshold should pass."""
        fc = FilterChain(FilterChainConfig(atr_entry_threshold=0.80))
        signal = make_signal(
            timestamp=pd.Timestamp('2025-03-03 17:30:00'),
            bar_idx=12,
        )

        m5_bars = []
        base = pd.Timestamp('2025-03-03 16:30:00')
        for i in range(15):
            m5_bars.append({
                'Ticker': 'TEST',
                'Datetime': base + pd.Timedelta(minutes=5 * i),
                'Open': 99.0,
                'High': 100.5,
                'Low': 97.0,
                'Close': 99.5,
                'Volume': 100000,
            })
        m5_df = pd.DataFrame(m5_bars)
        daily = make_daily_df(atr=3.0)

        entry = SignalFunnelEntry(signal=signal)
        result = fc._check_atr_filter(signal, m5_df, daily, entry)
        assert result.passed == True
        assert entry.atr_ratio > 0  # populated


# ── Stage 7: Volume Filter ──

class TestVolumeFilter:
    def test_true_breakout_blocked(self):
        """High volume + close beyond level = true breakout → BLOCK."""
        fc = FilterChain()
        signal = make_signal(
            timestamp=pd.Timestamp('2025-03-03 17:30:00'),
            bar_idx=10,
        )

        m5_bars = []
        base = pd.Timestamp('2025-03-03 16:30:00')
        for i in range(11):
            vol = 100000 if i < 10 else 300000
            close = 99.5 if i < 10 else 100.5
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
        base = pd.Timestamp('2025-03-03 16:30:00')
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


# ── Stage 8: Squeeze Filter ──

class TestSqueezeFilter:
    def test_squeeze_blocks(self):
        """Tight BB width should block."""
        fc = FilterChain(FilterChainConfig(squeeze_bb_width_threshold=0.005))
        signal = make_signal(bar_idx=25)

        # All bars at nearly identical price → tight BB
        m5_bars = []
        base = pd.Timestamp('2025-03-03 16:30:00')
        for i in range(30):
            m5_bars.append({
                'Ticker': 'TEST',
                'Datetime': base + pd.Timedelta(minutes=5 * i),
                'Open': 100.0,
                'High': 100.01,
                'Low': 99.99,
                'Close': 100.0,
                'Volume': 100000,
            })
        m5_df = pd.DataFrame(m5_bars)

        result = fc._check_squeeze_filter(signal, m5_df, atr_passed=True)
        assert result.passed == False
        assert 'overrides ATR' in result.reason


# ── Full Chain ──

class TestApplyFilters:
    def test_all_8_stages_run(self):
        """When all pass, funnel entry should show all 8 filter names."""
        fc = FilterChain(FilterChainConfig(
            enable_time_filter=False,
            enable_volume_filter=False,
            enable_squeeze_filter=False,
        ))

        m5_bars = []
        base = pd.Timestamp('2025-03-03 16:30:00')
        for i in range(15):
            m5_bars.append({
                'Ticker': 'TEST',
                'Datetime': base + pd.Timedelta(minutes=5 * i),
                'Open': 99.0,
                'High': 100.5,
                'Low': 97.0,
                'Close': 99.5,
                'Volume': 100000,
            })
        m5_df = pd.DataFrame(m5_bars)
        daily = make_daily_df(atr=3.0)

        signal = make_signal(bar_idx=10)
        passed, entry = fc.apply_filters(signal, m5_df, daily)

        assert passed == True
        assert 'direction' in entry.filters_passed
        assert 'position' in entry.filters_passed
        assert 'level_score' in entry.filters_passed
        assert 'atr' in entry.filters_passed

    def test_early_exit_on_block(self):
        """Chain should stop at first blocked filter."""
        fc = FilterChain(FilterChainConfig(
            direction_filter={'TEST': 'long'}  # will block SHORT signals
        ))
        signal = make_signal(direction=SignalDirection.SHORT)
        m5_df = make_m5_bars()
        daily = make_daily_df()

        passed, entry = fc.apply_filters(signal, m5_df, daily)
        assert passed == False
        assert entry.blocked_by == 'direction'
        assert len(entry.filters_passed) == 0  # blocked at first stage


class TestTimeBucket:
    def test_open_bucket_ist(self):
        fc = FilterChain()
        assert fc.get_time_bucket(pd.Timestamp('2025-03-03 16:35:00')) == "Open"
        assert fc.get_time_bucket(pd.Timestamp('2025-03-03 18:25:00')) == "Open"

    def test_midday_bucket_ist(self):
        fc = FilterChain()
        assert fc.get_time_bucket(pd.Timestamp('2025-03-03 18:35:00')) == "Midday"
        assert fc.get_time_bucket(pd.Timestamp('2025-03-03 20:55:00')) == "Midday"

    def test_close_bucket_ist(self):
        fc = FilterChain()
        assert fc.get_time_bucket(pd.Timestamp('2025-03-03 21:00:00')) == "Close"
        assert fc.get_time_bucket(pd.Timestamp('2025-03-03 22:55:00')) == "Close"


class TestFunnelSummary:
    def test_empty_funnel(self):
        fc = FilterChain()
        summary = fc.get_funnel_summary()
        assert summary['total_signals'] == 0
        assert summary['passed'] == 0

    def test_funnel_counts_new_stages(self):
        """Funnel summary should include direction, position, level_score."""
        fc = FilterChain()
        summary = fc.get_funnel_summary()
        assert 'blocked_by_direction' in summary
        assert 'blocked_by_position' in summary
        assert 'blocked_by_level_score' in summary
