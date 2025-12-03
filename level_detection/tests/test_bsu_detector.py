"""
Tests for BSU Detector Module.

Tests fractal detection, scoring system, and level detection.
"""

import numpy as np
import pandas as pd
import pytest

from level_detection.bsu_detector import BSUDetector, Level, LevelType
from level_detection.config import Config
from level_detection.data_aggregator import DataAggregator


class TestConfig:
    """Test configuration parameters."""

    def test_default_config_values(self):
        """Test default configuration values match specification."""
        config = Config()

        assert config.FRACTAL_DEPTH_D1 == 5
        assert config.TOLERANCE_PERCENT == 0.002
        assert config.ATR_PERIOD == 5
        assert config.PARANORMAL_MULT == 2.0
        assert config.MIN_LEVEL_SCORE == 5

    def test_tolerance_calculation(self):
        """Test tolerance calculation based on price."""
        config = Config()

        # For stocks > $100, use percentage
        tolerance_high = config.get_tolerance(150.0)
        assert tolerance_high == pytest.approx(0.30, rel=0.01)  # 0.2% of 150

        # For stocks <= $100, use cents
        tolerance_low = config.get_tolerance(50.0)
        assert tolerance_low == pytest.approx(0.05, rel=0.01)


class TestDataAggregator:
    """Test data aggregation functionality."""

    @pytest.fixture
    def sample_5min_data(self) -> pd.DataFrame:
        """Create sample 5-minute data for testing."""
        dates = pd.date_range("2024-01-02 09:30", periods=78, freq="5min")
        np.random.seed(42)

        # Simulate a day of trading
        opens = [100.0]
        for _ in range(77):
            opens.append(opens[-1] + np.random.randn() * 0.5)

        highs = [o + abs(np.random.randn() * 0.3) for o in opens]
        lows = [o - abs(np.random.randn() * 0.3) for o in opens]
        closes = [l + np.random.rand() * (h - l) for l, h in zip(lows, highs)]

        return pd.DataFrame({
            "Datetime": dates,
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": np.random.randint(1000, 10000, 78),
            "Ticker": "TEST",
        })

    def test_aggregate_to_daily(self, sample_5min_data):
        """Test 5-min to daily aggregation."""
        aggregator = DataAggregator()
        daily = aggregator.aggregate_to_daily(sample_5min_data)

        # Should have 1 day of data
        assert len(daily) == 1

        # Check OHLCV aggregation
        assert daily.iloc[0]["Open"] == sample_5min_data.iloc[0]["Open"]
        assert daily.iloc[0]["High"] == sample_5min_data["High"].max()
        assert daily.iloc[0]["Low"] == sample_5min_data["Low"].min()
        assert daily.iloc[0]["Close"] == sample_5min_data.iloc[-1]["Close"]
        assert daily.iloc[0]["Volume"] == sample_5min_data["Volume"].sum()

    def test_true_range_calculation(self, sample_5min_data):
        """Test True Range calculation."""
        aggregator = DataAggregator()
        daily = aggregator.aggregate_to_daily(sample_5min_data)

        # TR should be at least High - Low
        high_low = daily.iloc[0]["High"] - daily.iloc[0]["Low"]
        assert daily.iloc[0]["TR"] >= high_low


class TestFractalDetection:
    """Test fractal detection algorithm."""

    @pytest.fixture
    def sample_daily_data(self) -> pd.DataFrame:
        """Create sample daily data with known fractals."""
        # Create 20 days of data with clear fractal patterns
        dates = pd.date_range("2024-01-01", periods=20, freq="D")

        # Design data with clear fractal at index 10 (high) and index 12 (low)
        highs = [100, 101, 102, 101, 100, 99, 100, 101, 102, 103,
                 110, 103, 102, 101, 100, 99, 100, 101, 102, 103]
        lows = [98, 99, 100, 99, 98, 97, 98, 99, 100, 101,
                105, 101, 95, 96, 97, 98, 99, 100, 101, 102]

        return pd.DataFrame({
            "Date": dates,
            "Ticker": "TEST",
            "Open": [99] * 20,
            "High": highs,
            "Low": lows,
            "Close": [99.5] * 20,
            "Volume": [1000] * 20,
            "TR": [h - l for h, l in zip(highs, lows)],
            "ATR": [2.0] * 20,
            "ModifiedATR": [2.0] * 20,
            "IsParanormal": [False] * 20,
        })

    def test_fractal_high_detection(self, sample_daily_data):
        """Test detection of fractal highs (resistance)."""
        detector = BSUDetector()
        result = detector.detect_fractals(sample_daily_data)

        # Index 10 should be detected as fractal high (110 > surrounding)
        assert bool(result.iloc[10]["IsFractalHigh"]) is True

    def test_fractal_low_detection(self, sample_daily_data):
        """Test detection of fractal lows (support)."""
        detector = BSUDetector()
        result = detector.detect_fractals(sample_daily_data)

        # Index 12 should be detected as fractal low (95 < surrounding)
        assert bool(result.iloc[12]["IsFractalLow"]) is True

    def test_edge_exclusion(self, sample_daily_data):
        """Test that first/last k bars are excluded."""
        config = Config()
        detector = BSUDetector(config)
        k = config.FRACTAL_DEPTH_D1

        result = detector.detect_fractals(sample_daily_data)

        # First k and last k bars should not be fractals
        for i in range(k):
            assert bool(result.iloc[i]["IsFractalHigh"]) is False
            assert bool(result.iloc[i]["IsFractalLow"]) is False
            assert bool(result.iloc[-(i + 1)]["IsFractalHigh"]) is False
            assert bool(result.iloc[-(i + 1)]["IsFractalLow"]) is False


class TestScoringSystem:
    """Test level scoring system."""

    @pytest.fixture
    def detector(self) -> BSUDetector:
        """Create BSU detector instance."""
        return BSUDetector()

    def test_round_number_detection(self, detector):
        """Test round number detection (.00 and .50)."""
        assert detector._is_round_number(100.0) is True
        assert detector._is_round_number(100.50) is True
        assert detector._is_round_number(100.00) is True
        assert detector._is_round_number(99.50) is True

        assert detector._is_round_number(100.25) is False
        assert detector._is_round_number(100.75) is False
        assert detector._is_round_number(100.33) is False

    def test_minimum_score_filter(self, detector):
        """Test that levels below minimum score are filtered."""
        # Create simple data that won't generate high scores
        dates = pd.date_range("2024-01-01", periods=15, freq="D")
        df = pd.DataFrame({
            "Date": dates,
            "Ticker": "TEST",
            "Open": [100] * 15,
            "High": [101 + i * 0.1 for i in range(15)],
            "Low": [99 - i * 0.1 for i in range(15)],
            "Close": [100.5] * 15,
            "Volume": [1000] * 15,
            "TR": [2.0] * 15,
            "ATR": [2.0] * 15,
            "ModifiedATR": [2.0] * 15,
            "IsParanormal": [False] * 15,
        })

        levels = detector.detect_levels(df, "TEST")

        # All detected levels should have score >= MIN_LEVEL_SCORE
        for level in levels:
            assert level.score >= detector.config.MIN_LEVEL_SCORE


class TestLevelDetection:
    """Test complete level detection pipeline."""

    @pytest.fixture
    def realistic_data(self) -> pd.DataFrame:
        """Create realistic daily data for testing."""
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=60, freq="D")

        # Create trending data with some fractals
        base_price = 100.0
        prices = []
        for i in range(60):
            # Add trend and noise
            trend = i * 0.1
            noise = np.random.randn() * 2
            prices.append(base_price + trend + noise)

        opens = prices
        highs = [p + abs(np.random.randn() * 1.5) for p in prices]
        lows = [p - abs(np.random.randn() * 1.5) for p in prices]
        closes = [l + np.random.rand() * (h - l) for l, h in zip(lows, highs)]

        tr = [h - l for h, l in zip(highs, lows)]
        atr = pd.Series(tr).rolling(5).mean().fillna(tr[0]).tolist()

        return pd.DataFrame({
            "Date": dates,
            "Ticker": "TEST",
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": np.random.randint(10000, 100000, 60).tolist(),
            "TR": tr,
            "ATR": atr,
            "ModifiedATR": atr,
            "IsParanormal": [False] * 60,
        })

    def test_detect_levels_returns_list(self, realistic_data):
        """Test that detect_levels returns a list of Level objects."""
        detector = BSUDetector()
        levels = detector.detect_levels(realistic_data, "TEST")

        assert isinstance(levels, list)
        for level in levels:
            assert isinstance(level, Level)

    def test_level_attributes(self, realistic_data):
        """Test that Level objects have correct attributes."""
        detector = BSUDetector()
        levels = detector.detect_levels(realistic_data, "TEST")

        if levels:
            level = levels[0]
            assert hasattr(level, "date")
            assert hasattr(level, "ticker")
            assert hasattr(level, "price")
            assert hasattr(level, "level_type")
            assert hasattr(level, "score")
            assert hasattr(level, "bsu_index")
            assert hasattr(level, "atr")

    def test_levels_to_dataframe(self, realistic_data):
        """Test conversion of levels to DataFrame."""
        detector = BSUDetector()
        levels = detector.detect_levels(realistic_data, "TEST")
        df = detector.levels_to_dataframe(levels)

        expected_columns = [
            "Date", "Ticker", "Price", "Type", "Score",
            "BSU_Index", "ATR", "IsParanormal", "Touches",
            "IsRoundNumber", "IsMirror"
        ]
        assert list(df.columns) == expected_columns


class TestModifiedATR:
    """Test Modified ATR calculation."""

    @pytest.fixture
    def data_with_anomalies(self) -> pd.DataFrame:
        """Create data with anomalous bars for ATR testing."""
        dates = pd.date_range("2024-01-01", periods=20, freq="D")

        # Normal bars with some anomalies
        tr_values = [2.0, 2.1, 1.9, 2.0, 2.2,  # Normal
                     10.0,  # Paranormal (> 2x ATR)
                     2.0, 1.8, 2.1, 2.0,
                     0.2,  # Insignificant (< 0.5x ATR)
                     2.0, 2.1, 1.9, 2.0, 2.2, 2.1, 1.8, 2.0, 2.1]

        highs = [100 + tr for tr in tr_values]
        lows = [100] * 20

        return pd.DataFrame({
            "Date": dates,
            "Ticker": "TEST",
            "Open": [100] * 20,
            "High": highs,
            "Low": lows,
            "Close": [100.5] * 20,
            "Volume": [1000] * 20,
            "TR": tr_values,
        })

    def test_paranormal_detection(self, data_with_anomalies):
        """Test that paranormal bars are detected."""
        aggregator = DataAggregator()
        result = aggregator.calculate_modified_atr(data_with_anomalies)

        # Bar at index 5 (TR=10.0) should be marked as paranormal
        assert bool(result.iloc[5]["IsParanormal"]) is True

    def test_modified_atr_excludes_anomalies(self, data_with_anomalies):
        """Test that Modified ATR excludes anomalous bars."""
        aggregator = DataAggregator()
        result = aggregator.calculate_modified_atr(data_with_anomalies)

        # Modified ATR should be more stable than regular ATR
        # after anomalous bars
        if pd.notna(result.iloc[6]["ModifiedATR"]) and pd.notna(result.iloc[6]["ATR"]):
            # Modified ATR should not spike as much after paranormal bar
            assert result.iloc[6]["ModifiedATR"] < result.iloc[6]["ATR"]


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_dataframe(self):
        """Test handling of empty DataFrame."""
        detector = BSUDetector()
        df = pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume"])

        result = detector.detect_fractals(df)
        assert len(result) == 0

    def test_insufficient_data(self):
        """Test handling when data is shorter than fractal depth."""
        detector = BSUDetector()
        dates = pd.date_range("2024-01-01", periods=5, freq="D")

        df = pd.DataFrame({
            "Date": dates,
            "Ticker": "TEST",
            "Open": [100] * 5,
            "High": [101] * 5,
            "Low": [99] * 5,
            "Close": [100.5] * 5,
            "Volume": [1000] * 5,
        })

        result = detector.detect_fractals(df)

        # Should return DataFrame without any fractals detected
        assert result["IsFractalHigh"].sum() == 0
        assert result["IsFractalLow"].sum() == 0

    def test_single_ticker_processing(self):
        """Test processing a single ticker."""
        aggregator = DataAggregator()
        detector = BSUDetector()

        # Create minimal valid data
        np.random.seed(42)
        dates = pd.date_range("2024-01-01 09:30", periods=156, freq="5min")

        df = pd.DataFrame({
            "Datetime": dates,
            "Open": np.random.randn(156).cumsum() + 100,
            "High": np.random.randn(156).cumsum() + 101,
            "Low": np.random.randn(156).cumsum() + 99,
            "Close": np.random.randn(156).cumsum() + 100,
            "Volume": np.random.randint(1000, 10000, 156),
            "Ticker": "AAPL",
        })

        # Ensure High >= max(Open, Close) and Low <= min(Open, Close)
        df["High"] = df[["Open", "High", "Close"]].max(axis=1)
        df["Low"] = df[["Open", "Low", "Close"]].min(axis=1)

        daily = aggregator.aggregate_to_daily(df)
        daily = aggregator.calculate_modified_atr(daily)

        ticker_data = aggregator.get_ticker_data(daily, "AAPL")
        assert len(ticker_data) > 0
        assert ticker_data["Ticker"].unique()[0] == "AAPL"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
