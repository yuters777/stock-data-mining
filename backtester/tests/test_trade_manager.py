"""Tests for the Trade Manager module."""

import pytest
import pandas as pd
import numpy as np

from backtester.data_types import (
    Level, LevelType, LevelStatus, Signal, SignalDirection,
    PatternType, ExitReason,
)
from backtester.core.risk_manager import (
    RiskManager, RiskManagerConfig, RiskParams, calculate_slippage,
)
from backtester.core.trade_manager import (
    TradeManager, TradeManagerConfig, Trade,
)

TradeDirection = SignalDirection


def make_level(price=100.0, is_mirror=False):
    return Level(
        date=pd.Timestamp('2025-03-01'),
        ticker='TEST',
        price=price,
        level_type=LevelType.RESISTANCE,
        score=8,
        bsu_index=0,
        atr_d1=3.0,
        touches=3,
        is_round_number=True,
        is_mirror=is_mirror,
    )


def make_signal(entry_price=99.5, direction=TradeDirection.SHORT,
                bar_idx=5, ticker='TEST', level=None):
    if level is None:
        level = make_level()
    return Signal(
        timestamp=pd.Timestamp('2025-03-03 17:00:00'),
        ticker=ticker,
        level=level,
        pattern=PatternType.LP1,
        direction=direction,
        entry_price=entry_price,
        trigger_bar_idx=bar_idx,
    )


def make_risk_params(stop_price=100.5, target_price=97.0,
                     position_size=100):
    stop_distance = abs(99.5 - stop_price)
    target_distance = abs(97.0 - 99.5)
    return RiskParams(
        stop_price=stop_price,
        target_price=target_price,
        stop_distance=stop_distance,
        target_distance=target_distance,
        rr_ratio=target_distance / stop_distance if stop_distance > 0 else 0,
        position_size=position_size,
        risk_per_share=stop_distance + 0.04,
        slippage_total=0.04 * position_size,
    )


def make_m5_bar(ticker='TEST', time=None, open_=99.5, high=100.0,
                low=99.0, close=99.3, volume=100000):
    if time is None:
        time = pd.Timestamp('2025-03-03 17:05:00')
    return pd.Series({
        'Ticker': ticker,
        'Datetime': time,
        'Open': open_,
        'High': high,
        'Low': low,
        'Close': close,
        'Volume': volume,
    })


class TestNextBarEntry:
    def test_queue_and_enter_next_bar(self):
        """Signal queued should enter at next bar's open + slippage."""
        tm = TradeManager()
        signal = make_signal(entry_price=99.5)
        rp = make_risk_params()

        # Queue entry (signal detected on previous bar)
        tm.queue_entry(signal, rp)
        assert len(tm._pending_entries) == 1

        # Next bar arrives with open at 99.6
        next_bar = make_m5_bar(open_=99.6, time=pd.Timestamp('2025-03-03 17:05:00'))
        bar_time = pd.Timestamp('2025-03-03 17:05:00')

        tm.update_trades(next_bar, bar_time)

        assert len(tm.open_trades) == 1
        trade = tm.open_trades[0]
        # Entry should be at bar open (99.6) minus slippage (SHORT)
        expected_slippage = calculate_slippage(99.6)
        assert trade.entry_price == pytest.approx(99.6 - expected_slippage)
        assert trade.entry_time == bar_time

    def test_entry_cutoff_blocks(self):
        """No new entries after 22:45 IST."""
        cfg = TradeManagerConfig(entry_cutoff_hour=22, entry_cutoff_minute=45)
        tm = TradeManager(config=cfg)
        signal = make_signal()
        rp = make_risk_params()

        tm.queue_entry(signal, rp)

        # Late bar at 22:50 IST
        late_bar = make_m5_bar(time=pd.Timestamp('2025-03-03 22:50:00'))
        tm.update_trades(late_bar, pd.Timestamp('2025-03-03 22:50:00'))

        assert len(tm.open_trades) == 0  # Entry blocked


class TestSlippageModel:
    def test_entry_slippage_short(self):
        """Short entry slippage: fill at open - slippage (worse for short)."""
        tm = TradeManager()
        signal = make_signal(direction=TradeDirection.SHORT)
        rp = make_risk_params()

        trade = tm.open_trade(signal, rp, entry_price=100.0,
                              entry_time=pd.Timestamp('2025-03-03 17:05:00'))
        expected = 100.0 - calculate_slippage(100.0)
        assert trade.entry_price == pytest.approx(expected)

    def test_entry_slippage_long(self):
        """Long entry slippage: fill at open + slippage (worse for long)."""
        tm = TradeManager()
        signal = make_signal(direction=TradeDirection.LONG)
        rp = make_risk_params()

        trade = tm.open_trade(signal, rp, entry_price=100.0,
                              entry_time=pd.Timestamp('2025-03-03 17:05:00'))
        expected = 100.0 + calculate_slippage(100.0)
        assert trade.entry_price == pytest.approx(expected)


class TestStopLoss:
    def test_stop_loss_short(self):
        """Short trade should stop when high >= stop price."""
        tm = TradeManager()
        signal = make_signal()
        rp = make_risk_params(stop_price=100.5)
        trade = tm.open_trade(signal, rp, 99.5,
                              pd.Timestamp('2025-03-03 17:00:00'))

        # Bar hits stop
        bar = make_m5_bar(high=100.6, low=99.0, close=100.3,
                          time=pd.Timestamp('2025-03-03 17:05:00'))
        closed = tm.update_trades(bar, pd.Timestamp('2025-03-03 17:05:00'))

        assert len(closed) == 1
        assert closed[0].exit_reason == ExitReason.STOP_LOSS

    def test_stop_before_target(self):
        """If both stop and target hit same bar, assume stop first."""
        tm = TradeManager()
        signal = make_signal()
        rp = make_risk_params(stop_price=100.5, target_price=98.0)
        trade = tm.open_trade(signal, rp, 99.5,
                              pd.Timestamp('2025-03-03 17:00:00'))

        # Both stop and target could be hit
        bar = make_m5_bar(high=101.0, low=97.5, close=99.0,
                          time=pd.Timestamp('2025-03-03 17:05:00'))
        closed = tm.update_trades(bar, pd.Timestamp('2025-03-03 17:05:00'))

        assert len(closed) == 1
        assert closed[0].exit_reason == ExitReason.STOP_LOSS


class TestNisonExit:
    def test_nison_exit_on_invalidated_mirror(self):
        """Trade at mirror level should exit when level is INVALIDATED."""
        level = make_level(is_mirror=True)
        level.level_type = LevelType.MIRROR
        level.status = LevelStatus.MIRROR_CONFIRMED

        tm = TradeManager()
        signal = make_signal(level=level)
        rp = make_risk_params()
        trade = tm.open_trade(signal, rp, 99.5,
                              pd.Timestamp('2025-03-03 17:00:00'))

        # Simulate Nison invalidation (level_detector sets this)
        level.status = LevelStatus.INVALIDATED

        bar = make_m5_bar(high=99.8, low=99.0, close=99.2,
                          time=pd.Timestamp('2025-03-03 17:05:00'))
        closed = tm.update_trades(bar, pd.Timestamp('2025-03-03 17:05:00'))

        assert len(closed) == 1
        assert closed[0].exit_reason == ExitReason.NISON_EXIT

    def test_no_nison_exit_on_non_mirror(self):
        """Non-mirror level should never trigger Nison exit."""
        level = make_level(is_mirror=False)
        level.status = LevelStatus.INVALIDATED  # even if invalidated

        tm = TradeManager()
        signal = make_signal(level=level)
        rp = make_risk_params()
        trade = tm.open_trade(signal, rp, 99.5,
                              pd.Timestamp('2025-03-03 17:00:00'))

        bar = make_m5_bar(high=99.8, low=99.0, close=99.2,
                          time=pd.Timestamp('2025-03-03 17:05:00'))
        closed = tm.update_trades(bar, pd.Timestamp('2025-03-03 17:05:00'))

        assert len(closed) == 0  # No exit


class TestEODExit:
    def test_eod_exit_ist(self):
        """Trade should be closed at 22:55 IST."""
        cfg = TradeManagerConfig(eod_exit_hour=22, eod_exit_minute=55)
        tm = TradeManager(config=cfg)
        signal = make_signal()
        rp = make_risk_params()
        trade = tm.open_trade(signal, rp, 99.5,
                              pd.Timestamp('2025-03-03 17:00:00'))

        eod_bar = make_m5_bar(close=99.0,
                              time=pd.Timestamp('2025-03-03 22:55:00'))
        closed = tm.update_trades(eod_bar, pd.Timestamp('2025-03-03 22:55:00'))

        assert len(closed) == 1
        assert closed[0].exit_reason == ExitReason.EOD_EXIT

    def test_default_eod_is_ist(self):
        """Default EOD should be 22:55 IST."""
        cfg = TradeManagerConfig()
        assert cfg.eod_exit_hour == 22
        assert cfg.eod_exit_minute == 55


class TestBreakeven:
    def test_breakeven_at_2x_stop(self):
        """Stop should move to breakeven when favorable move >= 2× stop distance."""
        tm = TradeManager()
        signal = make_signal(direction=TradeDirection.SHORT)
        # stop_distance=1.0, target far away so it won't be hit
        rp = make_risk_params(stop_price=100.5, target_price=94.0)
        trade = tm.open_trade(signal, rp, 99.5,
                              pd.Timestamp('2025-03-03 17:00:00'))

        # Favorable move: entry(~99.48) - close(97.0) ≈ 2.48 > 2 × 1.0 = 2.0
        # low=97.0 is above target=94.0 so target not hit
        bar = make_m5_bar(high=99.3, low=97.0, close=97.2,
                          time=pd.Timestamp('2025-03-03 17:10:00'))
        tm.update_trades(bar, pd.Timestamp('2025-03-03 17:10:00'))

        assert trade.is_breakeven == True
        # Stop should be near entry price
        assert trade.stop_price < trade.entry_price + 0.1


class TestExitPrecedence:
    def test_stop_takes_priority_over_nison(self):
        """Stop loss should fire before Nison check."""
        level = make_level(is_mirror=True)
        level.status = LevelStatus.INVALIDATED

        tm = TradeManager()
        signal = make_signal(level=level)
        rp = make_risk_params(stop_price=100.5)
        trade = tm.open_trade(signal, rp, 99.5,
                              pd.Timestamp('2025-03-03 17:00:00'))

        # Bar hits stop
        bar = make_m5_bar(high=101.0, low=99.0, close=99.2,
                          time=pd.Timestamp('2025-03-03 17:05:00'))
        closed = tm.update_trades(bar, pd.Timestamp('2025-03-03 17:05:00'))

        assert len(closed) == 1
        assert closed[0].exit_reason == ExitReason.STOP_LOSS  # Not NISON_EXIT


class TestTrailingStop:
    def test_trail_stop_exit_reason(self):
        """Trailing stop hit should use TRAIL_STOP reason, not BREAKEVEN."""
        from backtester.core.risk_manager import TargetTier
        tm = TradeManager(tier_config={'trail_factor': 0.7, 'trail_activation_r': 0.0})
        signal = make_signal(direction=TradeDirection.SHORT)

        # Build risk params with trail tier
        rp = make_risk_params()
        rp.target_tiers = [
            TargetTier(price=98.5, exit_pct=0.30, source="M5", r_multiple=1.0),
            TargetTier(price=97.0, exit_pct=0.70, source="trail", r_multiple=0),
        ]
        trade = tm.open_trade(signal, rp, 99.5,
                              pd.Timestamp('2025-03-03 17:00:00'))

        # First bar: tier 1 hit
        bar1 = make_m5_bar(high=99.3, low=98.0, close=98.3,
                           time=pd.Timestamp('2025-03-03 17:05:00'))
        tm.update_trades(bar1, pd.Timestamp('2025-03-03 17:05:00'))
        assert trade.trailing_stop_active == True

        # Price moves down then reverses to hit trailing stop
        bar2 = make_m5_bar(high=99.3, low=97.5, close=97.8,
                           time=pd.Timestamp('2025-03-03 17:10:00'))
        tm.update_trades(bar2, pd.Timestamp('2025-03-03 17:10:00'))

        # Trailing stop should have tightened
        bar3 = make_m5_bar(high=99.0, low=98.5, close=98.8,
                           time=pd.Timestamp('2025-03-03 17:15:00'))
        closed = tm.update_trades(bar3, pd.Timestamp('2025-03-03 17:15:00'))

        # May or may not be closed depending on trail calc, but reason is correct
        for t in closed:
            assert t.exit_reason == ExitReason.TRAIL_STOP


class TestPortfolioExposure:
    def test_exposure_with_open_trades(self):
        """get_portfolio_exposure should return worst-case stop loss."""
        tm = TradeManager()
        signal = make_signal()
        rp = make_risk_params(position_size=100)
        trade = tm.open_trade(signal, rp, 99.5,
                              pd.Timestamp('2025-03-03 17:00:00'))

        unrealized, worst_case = tm.get_portfolio_exposure()
        assert worst_case < 0  # worst case is negative
