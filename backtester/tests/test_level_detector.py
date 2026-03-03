"""Tests for the Level Detector module."""

import pytest
import pandas as pd
import numpy as np

from backtester.core.level_detector import (
    LevelDetector, LevelDetectorConfig, Level, LevelType, LevelStatus
)


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


def make_m5_df(daily_prices, ticker="TEST"):
    """Helper to create M5 data from daily OHLC (simplified: 1 bar per day)."""
    rows = []
    base_date = pd.Timestamp('2025-03-01 09:30:00')
    for i, (o, h, l, c) in enumerate(daily_prices):
        rows.append({
            'Ticker': ticker,
            'Datetime': base_date + pd.Timedelta(days=i),
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
        assert cfg.fractal_depth == 5
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


class TestAggregation:
    def test_m5_to_d1(self):
        """Test M5 to D1 aggregation produces correct OHLCV."""
        m5_data = []
        base = pd.Timestamp('2025-03-03 09:30:00')
        for i in range(78):  # ~6.5 hours of 5-min bars
            m5_data.append({
                'Ticker': 'TEST',
                'Datetime': base + pd.Timedelta(minutes=5 * i),
                'Open': 100.0 + i * 0.1,
                'High': 100.5 + i * 0.1,
                'Low': 99.5 + i * 0.1,
                'Close': 100.2 + i * 0.1,
                'Volume': 1000,
            })
        m5_df = pd.DataFrame(m5_data)

        detector = LevelDetector()
        daily = detector.aggregate_m5_to_d1(m5_df)

        assert len(daily) == 1
        assert daily.iloc[0]['Open'] == 100.0  # first bar open
        assert daily.iloc[0]['High'] == 100.5 + 77 * 0.1  # max high
        assert daily.iloc[0]['Low'] == 99.5  # min low
        assert daily.iloc[0]['Volume'] == 78 * 1000


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
        # First bar: H - L = 105 - 95 = 10
        assert df.iloc[0]['TrueRange'] == 10.0
        # Second bar: max(108-98, |108-102|, |98-102|) = max(10, 6, 4) = 10
        assert df.iloc[1]['TrueRange'] == 10.0


class TestModifiedATR:
    def test_paranormal_excluded(self):
        """Paranormal bars should not affect ModifiedATR."""
        # Normal bars with range ~2, then a paranormal bar with range 20
        prices = [
            (100, 101, 99, 100.5),
            (100.5, 101.5, 99.5, 101),
            (101, 102, 100, 101.5),
            (101.5, 102.5, 100.5, 102),
            (102, 103, 101, 102.5),
            (102.5, 103.5, 101.5, 103),  # bar 5 (index 5)
            (103, 120, 100, 115),         # PARANORMAL: range = 20 >> ATR
        ]
        df = make_daily_df(prices)
        detector = LevelDetector()
        df = detector.calculate_true_range(df)
        df = detector.calculate_modified_atr(df)

        # The paranormal bar should be marked
        assert df.iloc[6]['IsParanormal'] == True
        # ModifiedATR should remain close to ~2 (not jump to ~20)
        mod_atr = df.iloc[6]['ModifiedATR']
        assert mod_atr < 5.0, f"ModifiedATR {mod_atr} too high (paranormal not excluded)"


class TestFractalDetection:
    def test_fractal_high(self):
        """With k=2, a fractal high should be detected at the peak."""
        # Create a V-shape: low, mid, HIGH, mid, low
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
        # Other bars should not be fractal highs
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

        # First 3 and last 3 should never be fractals
        for i in [0, 1, 2, 7, 8, 9]:
            assert df.iloc[i]['IsFractalHigh'] == False
            assert df.iloc[i]['IsFractalLow'] == False


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
        """Level should be invalidated if price crosses it ≥3 times in 20 bars."""
        # Create data where price oscillates around level at 100
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
            date=pd.Timestamp('2025-03-01'),
            ticker='TEST',
            price=100.0,
            level_type=LevelType.RESISTANCE,
            score=7,
            bsu_index=0,
            atr_d1=2.0,
            is_paranormal=False,
            touches=3,
            is_round_number=True,
            is_mirror=False,
        )

        # Check at date of bar 20 (base + 20 days)
        check_date = pd.Timestamp('2025-03-01') + pd.Timedelta(days=20)
        result = detector.check_anti_sawing(level, df, check_date)
        assert result == True  # Should be invalidated
        assert level.status == LevelStatus.INVALIDATED


class TestMirrorDetection:
    def test_mirror_level(self):
        """A level that acts as both support and resistance should be mirror."""
        # Level at 100: first bounces down (resistance), then bounces up (support)
        prices = [
            (98, 100.02, 97, 98),    # sets level at 100 (approx)
            (99, 100.03, 98, 99),     # approaches but doesn't break — resistance action
            (99, 100.04, 98, 99.5),   # High ≈ 100, Close < 100 → resistance
            (102, 103, 99.98, 101),   # Low ≈ 100, Close > 100 → support
            (101, 102, 100.01, 101.5), # Low ≈ 100, Close > 100 → support
        ]
        df = make_daily_df(prices)
        detector = LevelDetector()

        is_mirror = detector._check_mirror(100.0, df, 'TEST', -1)
        assert is_mirror == True

    def test_not_mirror_single_side(self):
        """A level only touched from one side should not be mirror."""
        prices = [
            (99, 100.02, 98, 99),   # resistance action
            (99, 100.03, 98, 99),   # resistance action
            (98, 99.5, 97, 98),     # doesn't reach level
        ]
        df = make_daily_df(prices)
        detector = LevelDetector()

        is_mirror = detector._check_mirror(100.0, df, 'TEST', -1)
        assert is_mirror == False


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

    def test_minimum_score(self):
        detector = LevelDetector()
        score, breakdown = detector._score_level(
            price=100.25, is_paranormal=False, touches=1,
            is_mirror=False, is_round=False, bsu_index=45, total_bars=50
        )
        # No components triggered (touches < 3, not mirror, not paranormal, not round, age < 20)
        assert score == 0
