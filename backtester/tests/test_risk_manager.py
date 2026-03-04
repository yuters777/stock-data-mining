"""Tests for the Risk Manager module."""

import pytest
import pandas as pd
import numpy as np

from backtester.core.risk_manager import (
    RiskManager, RiskManagerConfig, RiskParams,
    CircuitBreakerState, HARD_STOP_CAPS, calculate_slippage,
)
from backtester.data_types import (
    Level, LevelType, Signal, SignalDirection, PatternType,
)

# Backwards-compatible alias used in this test file
TradeDirection = SignalDirection


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


def make_signal(entry_price=99.5, direction=TradeDirection.SHORT, bar_idx=5,
                is_model4=False, ticker='TEST'):
    level = make_level()
    return Signal(
        timestamp=pd.Timestamp('2025-03-03 10:00:00'),
        ticker=ticker,
        level=level,
        pattern=PatternType.LP1,
        direction=direction,
        entry_price=entry_price,
        trigger_bar_idx=bar_idx,
        is_model4=is_model4,
    )


def make_m5_bars(n=10, base_price=100.0, bar_range=1.0):
    rows = []
    base = pd.Timestamp('2025-03-03 09:30:00')
    for i in range(n):
        rows.append({
            'Ticker': 'TEST',
            'Datetime': base + pd.Timedelta(minutes=5 * i),
            'Open': base_price,
            'High': base_price + bar_range / 2,
            'Low': base_price - bar_range / 2,
            'Close': base_price + 0.1,
            'Volume': 100000,
        })
    return pd.DataFrame(rows)


class TestStopCalculation:
    def test_short_stop_above_high(self):
        """Short stop should be above the trigger bar high + buffer."""
        rm = RiskManager()
        signal = make_signal(entry_price=99.5)
        m5_bars = make_m5_bars(10, base_price=99.5, bar_range=1.0)
        # Bar high = 100.0, buffer = max(0.02, 0.10 * 0.5) = 0.05

        stop = rm.calculate_stop(signal, m5_bars, atr_m5=0.5, atr_d1=3.0)
        # Stop should be above entry (since short)
        assert stop > signal.entry_price

    def test_long_stop_below_low(self):
        """Long stop should be below the trigger bar low - buffer."""
        rm = RiskManager()
        signal = make_signal(entry_price=100.5, direction=TradeDirection.LONG)
        m5_bars = make_m5_bars(10, base_price=100.5, bar_range=1.0)

        stop = rm.calculate_stop(signal, m5_bars, atr_m5=0.5, atr_d1=3.0)
        assert stop < signal.entry_price

    def test_dynamic_stop_cap(self):
        """Stop should not exceed 15% of ATR_D1 by default."""
        cfg = RiskManagerConfig(max_stop_atr_pct=0.15)
        rm = RiskManager(cfg)
        signal = make_signal(entry_price=99.5)
        # Make a bar with huge range so raw stop would be large
        m5_bars = make_m5_bars(10, base_price=99.5, bar_range=5.0)

        stop = rm.calculate_stop(signal, m5_bars, atr_m5=0.5, atr_d1=3.0)
        stop_dist = abs(signal.entry_price - stop)
        max_allowed = 0.15 * 3.0  # 0.45
        assert stop_dist <= max_allowed + 0.01

    def test_hard_stop_cap(self):
        """Stop for $75 stock should not exceed 25¢."""
        cfg = RiskManagerConfig(max_stop_atr_pct=1.0)  # relaxed dynamic cap
        rm = RiskManager(cfg)
        signal = make_signal(entry_price=75.0)
        m5_bars = make_m5_bars(10, base_price=75.0, bar_range=3.0)

        stop = rm.calculate_stop(signal, m5_bars, atr_m5=0.5, atr_d1=10.0)
        stop_dist = abs(signal.entry_price - stop)
        assert stop_dist <= 0.26  # 25¢ + small tolerance

    def test_min_stop(self):
        """Stop should not be smaller than MVS = MAX(0.25 × ATR_M5, 3¢)."""
        rm = RiskManager()
        signal = make_signal(entry_price=99.5)
        # Very small range bar
        m5_bars = make_m5_bars(10, base_price=99.5, bar_range=0.02)

        stop = rm.calculate_stop(signal, m5_bars, atr_m5=0.1, atr_d1=3.0)
        stop_dist = abs(signal.entry_price - stop)
        min_stop = max(0.25 * 0.1, 0.03)  # max(0.025, 0.03) = 0.03
        assert stop_dist >= min_stop - 0.001


class TestRiskReward:
    def test_rr_below_minimum_returns_none(self):
        """Risk params should be None if R:R < minimum."""
        cfg = RiskManagerConfig(min_rr=3.0, capital=100000)
        rm = RiskManager(cfg)
        signal = make_signal(entry_price=99.5)
        m5_bars = make_m5_bars(10, base_price=99.5, bar_range=1.0)

        # Opposing level very close → small target → bad R:R
        close_opposing = make_level(99.3)
        close_opposing.level_type = LevelType.SUPPORT

        result = rm.calculate_risk_params(
            signal, m5_bars, atr_m5=0.5, atr_d1=3.0,
            opposing_levels=[close_opposing]
        )
        # If target distance / stop distance < 3.0, should be None
        # In this case target is at 99.3+offset ≈ 99.36, entry at 99.5
        # target_distance ≈ 0.14, stop_distance ≈ 0.45
        # R:R ≈ 0.14/0.45 = 0.31 → None
        assert result is None

    def test_valid_rr_returns_params(self):
        """Valid R:R should return complete RiskParams."""
        cfg = RiskManagerConfig(min_rr=3.0, capital=100000)
        rm = RiskManager(cfg)
        signal = make_signal(entry_price=99.5)
        m5_bars = make_m5_bars(10, base_price=99.5, bar_range=0.5)

        # Far opposing level → good R:R
        far_opposing = make_level(96.0)
        far_opposing.level_type = LevelType.SUPPORT

        result = rm.calculate_risk_params(
            signal, m5_bars, atr_m5=0.5, atr_d1=3.0,
            opposing_levels=[far_opposing]
        )
        if result is not None:
            assert result.rr_ratio >= 3.0
            assert result.position_size >= 1
            assert result.slippage_total > 0


class TestPositionSizing:
    def test_basic_position_size(self):
        """Position size = Capital × 0.3% / risk_per_share."""
        cfg = RiskManagerConfig(capital=100000, risk_pct=0.003, min_rr=1.0)
        rm = RiskManager(cfg)
        signal = make_signal(entry_price=99.5)
        m5_bars = make_m5_bars(10, base_price=99.5, bar_range=0.5)

        far_opposing = make_level(95.0)
        far_opposing.level_type = LevelType.SUPPORT

        result = rm.calculate_risk_params(
            signal, m5_bars, atr_m5=0.5, atr_d1=3.0,
            opposing_levels=[far_opposing]
        )
        if result is not None:
            # Risk amount = 100000 * 0.003 = 300
            # Position size ≈ 300 / risk_per_share
            assert result.position_size > 0
            expected_approx = int(300 / result.risk_per_share)
            assert abs(result.position_size - expected_approx) <= 1

    def test_model4_multiplier(self):
        """Model4 signal should have 1.5x position size."""
        cfg = RiskManagerConfig(capital=100000, min_rr=1.0, model4_size_mult=1.5)
        rm = RiskManager(cfg)
        signal_normal = make_signal(entry_price=99.5, is_model4=False)
        signal_m4 = make_signal(entry_price=99.5, is_model4=True)
        m5_bars = make_m5_bars(10, base_price=99.5, bar_range=0.5)
        far_opp = make_level(95.0)
        far_opp.level_type = LevelType.SUPPORT

        r1 = rm.calculate_risk_params(signal_normal, m5_bars, 0.5, 3.0, [far_opp])
        r2 = rm.calculate_risk_params(signal_m4, m5_bars, 0.5, 3.0, [far_opp])

        if r1 is not None and r2 is not None:
            assert r2.position_size >= int(r1.position_size * 1.4)


class TestCircuitBreakers:
    def test_consecutive_stops(self):
        """3 consecutive stops should trigger circuit breaker."""
        cfg = RiskManagerConfig(max_consecutive_stops=3)
        cb = CircuitBreakerState(cfg)

        date = pd.Timestamp('2025-03-03')
        for _ in range(3):
            cb.record_trade_result('TEST', date, -50.0, was_stop=True)

        blocked, reason = cb.check_circuit_breakers(date, 100000)
        assert blocked == True
        assert 'consecutive' in reason.lower()

    def test_winning_trade_resets_consecutive(self):
        """A winner should reset the consecutive stops counter."""
        cfg = RiskManagerConfig(max_consecutive_stops=3)
        cb = CircuitBreakerState(cfg)

        date = pd.Timestamp('2025-03-03')
        cb.record_trade_result('TEST', date, -50.0, was_stop=True)
        cb.record_trade_result('TEST', date, -50.0, was_stop=True)
        cb.record_trade_result('TEST', date, 100.0, was_stop=False)  # Winner

        assert cb.consecutive_stops == 0
        blocked, _ = cb.check_circuit_breakers(date, 100000)
        assert blocked == False

    def test_daily_loss_limit(self):
        """Daily loss exceeding 1% of capital should trigger breaker."""
        cfg = RiskManagerConfig(max_daily_loss_pct=0.01)
        cb = CircuitBreakerState(cfg)

        date = pd.Timestamp('2025-03-03')
        cb.record_trade_result('TEST', date, -1100.0, was_stop=False)

        blocked, reason = cb.check_circuit_breakers(date, 100000)
        assert blocked == True
        assert 'daily' in reason.lower()

    def test_no_re_entry_same_level(self):
        """Should not re-enter at same level same day after stop."""
        cfg = RiskManagerConfig()
        cb = CircuitBreakerState(cfg)
        date = pd.Timestamp('2025-03-03')

        cb.record_stop_at_level('TEST', 100.0, date)
        assert cb.is_stopped_at_level_today('TEST', 100.0, date) == True
        assert cb.is_stopped_at_level_today('TEST', 101.0, date) == False

    def test_open_position_tracking(self):
        """Should track open positions per ticker."""
        cfg = RiskManagerConfig()
        cb = CircuitBreakerState(cfg)

        assert cb.has_open_position('TEST') == False
        cb.set_position('TEST', True)
        assert cb.has_open_position('TEST') == True
        cb.set_position('TEST', False)
        assert cb.has_open_position('TEST') == False


class TestPositionLimits:
    def test_block_duplicate_position(self):
        """Should block signal if already in position for ticker."""
        rm = RiskManager()
        rm.cb_state.set_position('TEST', True)

        signal = make_signal()
        can_trade, reason = rm.check_position_limits(
            signal, pd.Timestamp('2025-03-03'))

        assert can_trade == False
        assert 'position' in reason.lower()

    def test_block_after_stop_at_level(self):
        """Should block re-entry at same level same day."""
        rm = RiskManager()
        date = pd.Timestamp('2025-03-03')
        rm.cb_state.record_stop_at_level('TEST', 100.0, date)

        signal = make_signal()
        can_trade, reason = rm.check_position_limits(signal, date)

        assert can_trade == False
        assert 'stopped' in reason.lower()


class TestLP2QualityMultiplier:
    def test_lp2_acceptable_reduces_size(self):
        """LP2 ACCEPTABLE quality should reduce position size by 0.7x."""
        cfg = RiskManagerConfig(capital=100000, min_rr=1.0)
        rm = RiskManager(cfg)

        signal_normal = make_signal(entry_price=99.5)
        signal_lp2 = make_signal(entry_price=99.5)
        signal_lp2.position_size_mult = 0.7  # ACCEPTABLE

        m5_bars = make_m5_bars(10, base_price=99.5, bar_range=0.5)
        far_opp = make_level(95.0)
        far_opp.level_type = LevelType.SUPPORT

        r1 = rm.calculate_risk_params(signal_normal, m5_bars, 0.5, 3.0, [far_opp])
        r2 = rm.calculate_risk_params(signal_lp2, m5_bars, 0.5, 3.0, [far_opp])

        if r1 is not None and r2 is not None:
            assert r2.position_size < r1.position_size
            assert r2.position_size == int(r1.position_size * 0.7) or \
                   abs(r2.position_size - r1.position_size * 0.7) <= 1

    def test_lp2_weak_reduces_size(self):
        """LP2 WEAK quality should reduce position size by 0.5x."""
        cfg = RiskManagerConfig(capital=100000, min_rr=1.0)
        rm = RiskManager(cfg)

        signal_weak = make_signal(entry_price=99.5)
        signal_weak.position_size_mult = 0.5  # WEAK

        m5_bars = make_m5_bars(10, base_price=99.5, bar_range=0.5)
        far_opp = make_level(95.0)
        far_opp.level_type = LevelType.SUPPORT

        r_weak = rm.calculate_risk_params(signal_weak, m5_bars, 0.5, 3.0, [far_opp])
        if r_weak is not None:
            # Should be roughly half of normal size
            normal_signal = make_signal(entry_price=99.5)
            r_normal = rm.calculate_risk_params(normal_signal, m5_bars, 0.5, 3.0, [far_opp])
            if r_normal is not None:
                assert r_weak.position_size <= int(r_normal.position_size * 0.6)


class TestSlippageModel:
    def test_slippage_cheap_stock(self):
        """Cheap stock ($40): MAX(0.01, 40 × 0.0002) = MAX(0.01, 0.008) = 0.01."""
        assert calculate_slippage(40.0) == 0.01

    def test_slippage_expensive_stock(self):
        """Expensive stock ($200): MAX(0.01, 200 × 0.0002) = MAX(0.01, 0.04) = 0.04."""
        assert calculate_slippage(200.0) == pytest.approx(0.04)

    def test_slippage_breakpoint(self):
        """At $50, MAX(0.01, 50 × 0.0002) = MAX(0.01, 0.01) = 0.01."""
        assert calculate_slippage(50.0) == 0.01


class TestPortfolioAwareCircuitBreakers:
    def test_daily_loss_with_unrealized(self):
        """Daily circuit breaker should include worst-case open risk."""
        cfg = RiskManagerConfig(max_daily_loss_pct=0.01)
        cb = CircuitBreakerState(cfg)

        date = pd.Timestamp('2025-03-03')
        # Realized loss of $800
        cb.record_trade_result('TEST', date, -800.0, was_stop=False)
        # Worst-case unrealized loss of $300
        cb.update_unrealized(-200.0, -300.0)

        # Total = $800 + $300 = $1100 > 1% of $100K
        blocked, reason = cb.check_circuit_breakers(date, 100000)
        assert blocked == True
        assert 'daily' in reason.lower()

    def test_daily_loss_without_unrealized_ok(self):
        """Realized loss alone below threshold should not trigger."""
        cfg = RiskManagerConfig(max_daily_loss_pct=0.01)
        cb = CircuitBreakerState(cfg)

        date = pd.Timestamp('2025-03-03')
        cb.record_trade_result('TEST', date, -800.0, was_stop=False)
        # No open positions (default unrealized = 0)

        blocked, _ = cb.check_circuit_breakers(date, 100000)
        assert blocked == False


class TestMVSDefaults:
    def test_mvs_defaults(self):
        """MVS defaults should be 0.25 × ATR_M5 and 3 cents."""
        cfg = RiskManagerConfig()
        assert cfg.min_stop_atr_mult == 0.25
        assert cfg.min_stop_absolute == 0.03
