"""Tests for backtester.data_types — instantiation of all dataclasses and enums."""

import pytest
import pandas as pd

from backtester.data_types import (
    # Enums
    LevelType, LevelStatus, PatternType, SignalDirection,
    LP2Quality, SignalStatus, TradeStatus, ExitReason,
    # Dataclasses
    Bar, Level, Signal, Trade, EquitySnapshot,
)


class TestEnums:
    def test_level_type_values(self):
        assert LevelType.RESISTANCE.value == "R"
        assert LevelType.SUPPORT.value == "S"
        assert LevelType.MIRROR.value == "M"

    def test_level_status_values(self):
        assert LevelStatus.ACTIVE.value == "active"
        assert LevelStatus.INVALIDATED.value == "invalidated"
        assert LevelStatus.MIRROR_CANDIDATE.value == "mirror_candidate"
        assert LevelStatus.MIRROR_CONFIRMED.value == "mirror_confirmed"

    def test_pattern_type_values(self):
        assert PatternType.LP1.value == "LP1"
        assert PatternType.LP2.value == "LP2"
        assert PatternType.CLP.value == "CLP"
        assert PatternType.MODEL4.value == "MODEL4"

    def test_signal_direction_values(self):
        assert SignalDirection.LONG.value == "long"
        assert SignalDirection.SHORT.value == "short"

    def test_lp2_quality_values(self):
        assert LP2Quality.A.value == "A"
        assert LP2Quality.B.value == "B"
        assert LP2Quality.C.value == "C"

    def test_signal_status_values(self):
        assert SignalStatus.PENDING.value == "pending"
        assert SignalStatus.PASSED.value == "passed"
        assert SignalStatus.BLOCKED.value == "blocked"
        assert SignalStatus.EXECUTED.value == "executed"

    def test_trade_status_values(self):
        assert TradeStatus.OPEN.value == "open"
        assert TradeStatus.CLOSED.value == "closed"
        assert TradeStatus.PARTIAL.value == "partial"

    def test_exit_reason_values(self):
        assert ExitReason.STOP_LOSS.value == "stop_loss"
        assert ExitReason.TRAIL_STOP.value == "trail_stop"


class TestBar:
    def test_basic_instantiation(self):
        bar = Bar(
            symbol="TSLA",
            timestamp=pd.Timestamp("2025-06-15 16:30:00"),
            timeframe="M5",
            open=250.0, high=252.0, low=249.0, close=251.0,
            volume=10000,
        )
        assert bar.symbol == "TSLA"
        assert bar.timeframe == "M5"
        assert bar.open == 250.0
        assert bar.volume == 10000

    def test_bar_properties(self):
        bar = Bar(
            symbol="AAPL",
            timestamp=pd.Timestamp("2025-06-15 16:30:00"),
            timeframe="M5",
            open=180.0, high=182.0, low=179.0, close=181.5,
        )
        assert bar.range == pytest.approx(3.0)
        assert bar.body == pytest.approx(1.5)
        assert bar.is_bullish is True
        assert bar.is_bearish is False
        assert bar.upper_wick == pytest.approx(0.5)   # 182 - 181.5
        assert bar.lower_wick == pytest.approx(1.0)    # 180 - 179

    def test_bearish_bar(self):
        bar = Bar(
            symbol="AAPL",
            timestamp=pd.Timestamp("2025-06-15 16:30:00"),
            timeframe="D1",
            open=182.0, high=183.0, low=179.0, close=180.0,
        )
        assert bar.is_bearish is True
        assert bar.is_bullish is False
        assert bar.upper_wick == pytest.approx(1.0)   # 183 - 182
        assert bar.lower_wick == pytest.approx(1.0)    # 180 - 179

    def test_default_volume(self):
        bar = Bar(
            symbol="TSLA",
            timestamp=pd.Timestamp("2025-06-15"),
            timeframe="D1",
            open=100.0, high=105.0, low=95.0, close=102.0,
        )
        assert bar.volume == 0


class TestLevel:
    def test_basic_instantiation(self):
        level = Level(price=150.25, level_type=LevelType.RESISTANCE)
        assert level.price == 150.25
        assert level.level_type == LevelType.RESISTANCE
        assert level.status == LevelStatus.ACTIVE
        assert level.score == 0
        assert level.is_mirror is False

    def test_full_instantiation(self):
        level = Level(
            price=200.0,
            level_type=LevelType.MIRROR,
            status=LevelStatus.MIRROR_CONFIRMED,
            score=18,
            confirmed_at=pd.Timestamp("2025-05-01"),
            ticker="TSLA",
            date=pd.Timestamp("2025-04-20"),
            bsu_index=42,
            atr_d1=5.5,
            is_paranormal=False,
            touches=3,
            is_round_number=True,
            is_mirror=True,
            mirror_breakout_date=pd.Timestamp("2025-04-25"),
            mirror_max_distance_atr=2.1,
            mirror_days_beyond=5,
        )
        assert level.score == 18
        assert level.is_mirror is True
        assert level.mirror_days_beyond == 5

    def test_default_score_breakdown(self):
        level = Level(price=100.0, level_type=LevelType.SUPPORT)
        assert level.score_breakdown == {}


class TestSignal:
    def test_basic_instantiation(self):
        level = Level(price=150.0, level_type=LevelType.RESISTANCE)
        signal = Signal(
            pattern=PatternType.LP1,
            direction=SignalDirection.SHORT,
            level=level,
        )
        assert signal.pattern == PatternType.LP1
        assert signal.direction == SignalDirection.SHORT
        assert signal.status == SignalStatus.PENDING
        assert signal.filter_results == {}
        assert signal.meta == {}

    def test_full_signal(self):
        level = Level(price=250.0, level_type=LevelType.SUPPORT)
        signal = Signal(
            pattern=PatternType.LP2,
            direction=SignalDirection.LONG,
            level=level,
            timestamp=pd.Timestamp("2025-06-15 17:00:00"),
            ticker="TSLA",
            entry_price=249.80,
            trigger_bar_idx=100,
            tail_ratio=0.35,
            stop_price=249.00,
            target_price=252.00,
            position_size=50,
            rr_ratio=2.75,
        )
        assert signal.entry_price == 249.80
        assert signal.rr_ratio == 2.75


class TestTrade:
    def test_basic_instantiation(self):
        level = Level(price=150.0, level_type=LevelType.RESISTANCE)
        signal = Signal(
            pattern=PatternType.LP1,
            direction=SignalDirection.SHORT,
            level=level,
        )
        trade = Trade(signal=signal)
        assert trade.status == TradeStatus.OPEN
        assert trade.is_closed is False
        assert trade.is_winner is False
        assert trade.pnl == 0.0

    def test_winning_trade(self):
        level = Level(price=150.0, level_type=LevelType.RESISTANCE)
        signal = Signal(
            pattern=PatternType.CLP,
            direction=SignalDirection.SHORT,
            level=level,
        )
        trade = Trade(
            signal=signal,
            entry_price=149.90,
            exit_price=148.50,
            pnl=140.0,
            pnl_r=2.5,
            status=TradeStatus.CLOSED,
            exit_reason=ExitReason.TARGET_HIT,
        )
        assert trade.is_winner is True
        assert trade.is_closed is True

    def test_partial_exits_default(self):
        level = Level(price=100.0, level_type=LevelType.SUPPORT)
        signal = Signal(
            pattern=PatternType.LP1,
            direction=SignalDirection.LONG,
            level=level,
        )
        trade = Trade(signal=signal)
        assert trade.partial_exits == []


class TestEquitySnapshot:
    def test_basic_instantiation(self):
        snap = EquitySnapshot(
            timestamp=pd.Timestamp("2025-06-15"),
            cash=100_000.0,
        )
        assert snap.total_equity == 100_000.0
        assert snap.drawdown == 0.0

    def test_with_unrealized(self):
        snap = EquitySnapshot(
            timestamp=pd.Timestamp("2025-06-15"),
            cash=99_000.0,
            unrealized_pnl=500.0,
        )
        assert snap.total_equity == 99_500.0

    def test_explicit_total_overrides(self):
        snap = EquitySnapshot(
            timestamp=pd.Timestamp("2025-06-15"),
            cash=99_000.0,
            unrealized_pnl=500.0,
            total_equity=99_800.0,  # explicitly set
        )
        # Explicit value kept (post_init only sets if 0)
        assert snap.total_equity == 99_800.0

    def test_drawdown_tracking(self):
        snap = EquitySnapshot(
            timestamp=pd.Timestamp("2025-06-15"),
            cash=95_000.0,
            peak_equity=100_000.0,
            drawdown=5_000.0,
            drawdown_pct=0.05,
        )
        assert snap.drawdown_pct == pytest.approx(0.05)
