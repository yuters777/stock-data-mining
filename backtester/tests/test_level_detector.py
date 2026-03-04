"""Tests for the Level Detector module."""

import pytest
import pandas as pd
import numpy as np

from backtester.data_types import Level, LevelType, LevelStatus
from backtester.core.level_detector import LevelDetector, LevelDetectorConfig


def make_daily_df(prices, ticker="TEST"):
    """Helper to create a daily DataFrame from a list of (open, high, low, close) tuples."""
    rows = []
    base_date = pd.Timestamp('2025-03-01')
    for i, (o, h, l, c) in enumerate(prices):
        rows.append({
            'Ticker': ticker,
            'Date': base_date + pd.Timedelta(days=i),
            'Open': o,
            'High': h,
            'Low': l,
            'Close': c,
            'Volume': 1000000,
        })
    return pd.DataFrame(rows)


class TestLevelDetectorConfig:
    def test_default_config(self):
        cfg = LevelDetectorConfig()
        assert cfg.fractal_depth == 10  # L-005.1 default
        assert cfg.tolerance_cents == 0.05
        assert cfg.atr_period == 5

    def test_tolerance_cheap_stock(self):
        cfg = LevelDetectorConfig()
        assert cfg.get_tolerance(50.0) == 0.05

    def test_tolerance_expensive_stock(self):
        cfg = LevelDetectorConfig()
        tol = cfg.get_tolerance(200.0)
        assert abs(tol - 0.20) < 0.01  # 0.1% of 200

    def test_custom_config(self):
        cfg = LevelDetectorConfig(fractal_depth=3, tolerance_cents=0.10)
        assert cfg.fractal_depth == 3
        assert cfg.tolerance_cents == 0.10


class TestTrueRange:
    def test_basic_true_range(self):
        prices = [
            (100, 105, 95, 102),
            (102, 108, 98, 106),
            (106, 110, 100, 104),
        ]
        df = make_daily_df(prices)
        detector = LevelDetector()
        df = detector.calculate_true_range(df)

        assert 'TrueRange' in df.columns
        assert df.iloc[0]['TrueRange'] == 10.0
        assert df.iloc[1]['TrueRange'] == 10.0


class TestModifiedATR:
    def test_paranormal_excluded(self):
        """Paranormal bars should not affect ModifiedATR."""
        prices = [
            (100, 101, 99, 100.5),
            (100.5, 101.5, 99.5, 101),
            (101, 102, 100, 101.5),
            (101.5, 102.5, 100.5, 102),
            (102, 103, 101, 102.5),
            (102.5, 103.5, 101.5, 103),
            (103, 120, 100, 115),  # PARANORMAL: range = 20 >> ATR
        ]
        df = make_daily_df(prices)
        detector = LevelDetector()
        df = detector.calculate_true_range(df)
        df = detector.calculate_modified_atr(df)

        assert df.iloc[6]['IsParanormal'] == True
        mod_atr = df.iloc[6]['ModifiedATR']
        assert mod_atr < 5.0, f"ModifiedATR {mod_atr} too high (paranormal not excluded)"


class TestFractalDetection:
    def test_fractal_high(self):
        """With k=2, a fractal high should be detected at the peak."""
        prices = [
            (98, 99, 97, 98),
            (99, 101, 98, 100),
            (101, 110, 100, 105),  # PEAK — fractal high
            (105, 103, 99, 100),
            (100, 101, 97, 98),
        ]
        df = make_daily_df(prices)
        cfg = LevelDetectorConfig(fractal_depth=2)
        detector = LevelDetector(cfg)
        df = detector.calculate_true_range(df)
        df = detector.calculate_modified_atr(df)
        df = detector.detect_fractals(df)

        assert df.iloc[2]['IsFractalHigh'] == True
        assert df.iloc[0]['IsFractalHigh'] == False
        assert df.iloc[4]['IsFractalHigh'] == False

    def test_fractal_low(self):
        """With k=2, a fractal low should be detected at the trough."""
        prices = [
            (102, 103, 101, 102),
            (101, 102, 99, 100),
            (99, 100, 90, 95),   # TROUGH — fractal low
            (96, 101, 95, 100),
            (100, 103, 99, 102),
        ]
        df = make_daily_df(prices)
        cfg = LevelDetectorConfig(fractal_depth=2)
        detector = LevelDetector(cfg)
        df = detector.calculate_true_range(df)
        df = detector.calculate_modified_atr(df)
        df = detector.detect_fractals(df)

        assert df.iloc[2]['IsFractalLow'] == True

    def test_no_fractal_at_edges(self):
        """First and last k bars should not be fractals."""
        prices = [(100 + i, 105 + i, 95 + i, 102 + i) for i in range(10)]
        df = make_daily_df(prices)
        cfg = LevelDetectorConfig(fractal_depth=3)
        detector = LevelDetector(cfg)
        df = detector.calculate_true_range(df)
        df = detector.calculate_modified_atr(df)
        df = detector.detect_fractals(df)

        for i in [0, 1, 2, 7, 8, 9]:
            assert df.iloc[i]['IsFractalHigh'] == False
            assert df.iloc[i]['IsFractalLow'] == False

    def test_confirmed_at_set(self):
        """Fractal should have confirmed_at = date of bar[i+k]."""
        prices = [
            (98, 99, 97, 98),
            (99, 101, 98, 100),
            (101, 110, 100, 105),  # fractal high at index 2
            (105, 103, 99, 100),
            (100, 101, 97, 98),
        ]
        df = make_daily_df(prices)
        cfg = LevelDetectorConfig(fractal_depth=2)
        detector = LevelDetector(cfg)
        df = detector.calculate_true_range(df)
        df = detector.calculate_modified_atr(df)
        df = detector.detect_fractals(df)

        # Fractal at index 2, k=2 → confirmed at index 4
        confirmed = df.iloc[2]['FractalConfirmedAt']
        expected = df.iloc[4]['Date']
        assert pd.Timestamp(confirmed) == pd.Timestamp(expected)

    def test_confirmed_at_enforced_in_get_active_levels(self):
        """get_active_levels should not return levels whose confirmed_at > current_date."""
        base_date = pd.Timestamp('2025-03-01')
        level = Level(
            price=100.0,
            level_type=LevelType.RESISTANCE,
            score=10,
            ticker='TEST',
            date=base_date,
            bsu_index=0,
            atr_d1=2.0,
            touches=3,
            confirmed_at=base_date + pd.Timedelta(days=10),
        )
        detector = LevelDetector()
        detector.levels = [level]

        # Before confirmed_at → should not appear
        daily_df = make_daily_df([(100, 101, 99, 100)] * 5)
        active = detector.get_active_levels('TEST', base_date + pd.Timedelta(days=5),
                                            daily_df)
        assert len(active) == 0

        # At confirmed_at → should appear
        active = detector.get_active_levels('TEST', base_date + pd.Timedelta(days=10),
                                            daily_df)
        assert len(active) == 1


class TestRoundNumber:
    def test_round_numbers(self):
        detector = LevelDetector()
        assert detector._is_round_number(100.00) == True
        assert detector._is_round_number(50.50) == True
        assert detector._is_round_number(100.50) == True
        assert detector._is_round_number(99.25) == False
        assert detector._is_round_number(100.01) == False


class TestAntiSawing:
    def test_invalidation_on_many_crosses(self):
        """Level should be invalidated if price crosses it >=3 times in 20 bars."""
        prices = []
        for i in range(25):
            if i % 2 == 0:
                prices.append((101, 103, 100.5, 102))  # above
            else:
                prices.append((99, 99.5, 97, 98))      # below
        df = make_daily_df(prices)

        cfg = LevelDetectorConfig(fractal_depth=2)
        detector = LevelDetector(cfg)

        level = Level(
            price=100.0,
            level_type=LevelType.RESISTANCE,
            score=7,
            ticker='TEST',
            date=pd.Timestamp('2025-03-01'),
            bsu_index=0,
            atr_d1=2.0,
            touches=3,
            is_round_number=True,
        )

        check_date = pd.Timestamp('2025-03-01') + pd.Timedelta(days=20)
        result = detector.check_anti_sawing(level, df, check_date)
        assert result == True
        assert level.status == LevelStatus.INVALIDATED


class TestMirrorDetection:
    def test_mirror_level(self):
        """A level that acts as both support and resistance should be mirror."""
        prices = [
            (98, 100.02, 97, 98),
            (99, 100.03, 98, 99),
            (99, 100.04, 98, 99.5),
            (102, 103, 99.98, 101),
            (101, 102, 100.01, 101.5),
        ]
        df = make_daily_df(prices)
        detector = LevelDetector()

        is_mirror = detector._check_mirror(100.0, df, 'TEST', -1)
        assert is_mirror == True

    def test_not_mirror_single_side(self):
        """A level only touched from one side should not be mirror."""
        prices = [
            (99, 100.02, 98, 99),
            (99, 100.03, 98, 99),
            (98, 99.5, 97, 98),
        ]
        df = make_daily_df(prices)
        detector = LevelDetector()

        is_mirror = detector._check_mirror(100.0, df, 'TEST', -1)
        assert is_mirror == False


class TestMirrorLifecycle:
    def test_broken_state(self):
        """Level should transition to BROKEN when price moves >= mirror_atr_distance * ATR."""
        base_date = pd.Timestamp('2025-03-01')
        level = Level(
            price=100.0,
            level_type=LevelType.RESISTANCE,
            status=LevelStatus.ACTIVE,
            score=7,
            ticker='TEST',
            date=base_date,
            bsu_index=0,
            atr_d1=2.0,
            touches=3,
        )

        # Price moves 7 points above level (> 3 * 2.0 ATR = 6.0)
        prices = [(100, 107.5, 99, 107)] * 5
        df = make_daily_df(prices)

        detector = LevelDetector()
        detector.update_mirror_status(level, df, base_date + pd.Timedelta(days=4))

        assert level.status == LevelStatus.BROKEN


class TestNisonInvalidation:
    def test_nison_invalidates_support_mirror(self):
        """Support mirror (breakout above): retest→bounce above→close below = invalidated."""
        base_date = pd.Timestamp('2025-03-01')
        # Mirror confirmed on day 0; bars below are AFTER confirmation
        confirmed_date = base_date
        level = Level(
            price=100.0,
            level_type=LevelType.MIRROR,
            status=LevelStatus.MIRROR_CONFIRMED,
            score=10,
            ticker='TEST',
            date=base_date - pd.Timedelta(days=30),
            bsu_index=0,
            atr_d1=2.0,
            touches=3,
            is_mirror=True,
            mirror_breakout_side='above',           # level is now support
            mirror_confirmed_date=confirmed_date,
        )

        # Bars AFTER confirmed_date (days 1, 2, 3):
        prices = [
            (101, 102, 100, 101),     # day 0 (confirmation day, excluded)
            (101, 101, 99.5, 100.03), # day 1: retest — low touches level
            (100.5, 102, 100.3, 101.5),  # day 2: bounce — close above level
            (101, 101.2, 98, 98.5),   # day 3: failure — close below level
        ]
        df = make_daily_df(prices)

        detector = LevelDetector()
        result = detector.check_nison_invalidation(level, df,
                                                    base_date + pd.Timedelta(days=3))
        assert result is True
        assert level.status == LevelStatus.INVALIDATED

    def test_nison_invalidates_resistance_mirror(self):
        """Resistance mirror (breakout below): retest→bounce below→close above = invalidated."""
        base_date = pd.Timestamp('2025-03-01')
        confirmed_date = base_date
        level = Level(
            price=100.0,
            level_type=LevelType.MIRROR,
            status=LevelStatus.MIRROR_CONFIRMED,
            score=10,
            ticker='TEST',
            date=base_date - pd.Timedelta(days=30),
            bsu_index=0,
            atr_d1=2.0,
            touches=3,
            is_mirror=True,
            mirror_breakout_side='below',           # level is now resistance
            mirror_confirmed_date=confirmed_date,
        )

        # Bars AFTER confirmed_date:
        prices = [
            (99, 100, 98, 99),         # day 0 (confirmation day, excluded)
            (99, 100.02, 98.5, 99.8),  # day 1: retest — high touches level
            (99.5, 99.8, 97, 97.5),    # day 2: bounce — close below level
            (98, 102, 97.5, 101.5),    # day 3: failure — close above level
        ]
        df = make_daily_df(prices)

        detector = LevelDetector()
        result = detector.check_nison_invalidation(level, df,
                                                    base_date + pd.Timedelta(days=3))
        assert result is True
        assert level.status == LevelStatus.INVALIDATED

    def test_nison_no_invalidation_without_bounce(self):
        """Price drifting through level without bounce is NOT Nison."""
        base_date = pd.Timestamp('2025-03-01')
        confirmed_date = base_date
        level = Level(
            price=100.0,
            level_type=LevelType.MIRROR,
            status=LevelStatus.MIRROR_CONFIRMED,
            score=10,
            ticker='TEST',
            date=base_date - pd.Timedelta(days=30),
            bsu_index=0,
            atr_d1=2.0,
            touches=3,
            is_mirror=True,
            mirror_breakout_side='above',
            mirror_confirmed_date=confirmed_date,
        )

        # Price drifts down through the level — no bounce on hold side
        prices = [
            (101, 102, 100, 101),     # day 0 (excluded)
            (101, 101, 99.5, 100.03), # day 1: retest
            (100, 100.2, 97, 97.5),   # day 2: close BELOW — no bounce above first
            (97, 98, 95, 96),         # day 3: still below
        ]
        df = make_daily_df(prices)

        detector = LevelDetector()
        result = detector.check_nison_invalidation(level, df,
                                                    base_date + pd.Timedelta(days=3))
        assert result is False
        assert level.status == LevelStatus.MIRROR_CONFIRMED

    def test_nison_no_invalidation_without_breakout_side(self):
        """Nison should not fire if breakout direction is unknown."""
        base_date = pd.Timestamp('2025-03-01')
        level = Level(
            price=100.0,
            level_type=LevelType.MIRROR,
            status=LevelStatus.MIRROR_CONFIRMED,
            score=10,
            ticker='TEST',
            date=base_date,
            bsu_index=0,
            atr_d1=2.0,
            touches=3,
            is_mirror=True,
            mirror_breakout_side='',   # no direction info
        )

        prices = [
            (99, 100.02, 98, 99),
            (99, 99.5, 97, 97.5),
            (98, 99, 97, 102),
        ]
        df = make_daily_df(prices)

        detector = LevelDetector()
        result = detector.check_nison_invalidation(level, df,
                                                    base_date + pd.Timedelta(days=2))
        assert result is False

    def test_nison_not_before_confirmation(self):
        """Bars before mirror_confirmed_date should be excluded from Nison check."""
        base_date = pd.Timestamp('2025-03-01')
        # Confirmed on day 5, only 2 bars after = too few for 3-step sequence
        confirmed_date = base_date + pd.Timedelta(days=5)
        level = Level(
            price=100.0,
            level_type=LevelType.MIRROR,
            status=LevelStatus.MIRROR_CONFIRMED,
            score=10,
            ticker='TEST',
            date=base_date - pd.Timedelta(days=30),
            bsu_index=0,
            atr_d1=2.0,
            touches=3,
            is_mirror=True,
            mirror_breakout_side='above',
            mirror_confirmed_date=confirmed_date,
        )

        # 8 bars total, but only days 6,7 are after confirmation (< 3 needed)
        prices = [
            (99, 100.02, 98, 99),     # day 0
            (101, 102, 100, 101.5),   # day 1
            (99, 100.02, 98, 97),     # day 2: touch + close below (before confirm)
            (101, 102, 100, 101.5),   # day 3
            (99, 100.02, 98, 99),     # day 4
            (101, 102, 100, 101.5),   # day 5 (confirmation day, excluded)
            (101, 101, 99.5, 100.03), # day 6: retest
            (100.5, 102, 100.3, 101), # day 7: bounce (only 2 post-confirm bars)
        ]
        df = make_daily_df(prices)

        detector = LevelDetector()
        result = detector.check_nison_invalidation(level, df,
                                                    base_date + pd.Timedelta(days=7))
        assert result is False


class TestGapBoundary:
    def test_gap_detected(self):
        """Gap boundary should be detected when gap >= gap_min_pct."""
        # Day 1 closes at 100, Day 2 opens at 101 → 1% gap
        prices = [
            (99, 101, 98, 100),    # close at 100
            (101, 103, 100.5, 102),  # open at 101 → gap
        ]
        df = make_daily_df(prices)
        detector = LevelDetector(LevelDetectorConfig(gap_min_pct=0.005))

        # 100.0 is the gap boundary (prev close)
        assert detector._detect_gap_boundary(100.0, df, 'TEST', -1) == True

    def test_no_gap(self):
        """No gap boundary when gap is tiny."""
        prices = [
            (99, 101, 98, 100),
            (100.1, 102, 99, 101),  # 0.1% gap — below threshold
        ]
        df = make_daily_df(prices)
        detector = LevelDetector(LevelDetectorConfig(gap_min_pct=0.005))

        assert detector._detect_gap_boundary(100.0, df, 'TEST', -1) == False


class TestLevelScoring:
    def test_score_with_mirror_and_touches(self):
        detector = LevelDetector()
        score, breakdown = detector._score_level(
            price=100.0, is_paranormal=False, touches=5,
            is_mirror=True, is_round=True, bsu_index=0, total_bars=50
        )
        assert breakdown.get('mirror') == 10
        assert breakdown.get('penny_touches') == 9
        assert breakdown.get('round_number') == 6
        assert breakdown.get('age') == 7
        assert score == 10 + 9 + 6 + 7

    def test_score_with_gap_boundary(self):
        detector = LevelDetector()
        score, breakdown = detector._score_level(
            price=100.0, is_paranormal=False, touches=1,
            is_mirror=False, is_round=False, bsu_index=0, total_bars=50,
            is_gap_boundary=True
        )
        assert breakdown.get('gap_boundary') == 8
        assert breakdown.get('age') == 7
        assert score == 8 + 7

    def test_minimum_score(self):
        detector = LevelDetector()
        score, breakdown = detector._score_level(
            price=100.25, is_paranormal=False, touches=1,
            is_mirror=False, is_round=False, bsu_index=45, total_bars=50
        )
        assert score == 0
