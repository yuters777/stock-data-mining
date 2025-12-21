"""
Tests for TradingView Serializer Module.
"""

from pathlib import Path

import pandas as pd
import pytest

from level_detection.tradingview_serializer import TradingViewSerializer


class TestSerializeLevels:
    """Test level serialization."""

    @pytest.fixture
    def sample_levels_df(self):
        """Create sample levels DataFrame."""
        return pd.DataFrame({
            "Date": pd.date_range("2025-01-01", periods=5),
            "Ticker": ["AAPL"] * 5,
            "Price": [150.25, 148.10, 155.00, 152.50, 149.75],
            "Type": ["R", "S", "R", "S", "R"],
            "Score": [25, 18, 32, 15, 20],
            "IsMirror": [False, True, False, False, True],
            "IsParanormal": [False, False, True, False, False],
        })

    def test_serialize_basic(self, sample_levels_df):
        """Test basic serialization."""
        result = TradingViewSerializer.serialize_levels(sample_levels_df)

        assert isinstance(result, str)
        assert ":" in result
        assert "," in result

    def test_serialize_format(self, sample_levels_df):
        """Test serialization format Price:Type:Meta."""
        result = TradingViewSerializer.serialize_levels(sample_levels_df)
        parts = result.split(",")

        for part in parts:
            elements = part.split(":")
            assert len(elements) == 3
            assert float(elements[0])  # Price is numeric
            assert elements[1] in ("R", "S")  # Type
            assert elements[2] in ("M", "P", "N")  # Meta

    def test_serialize_mirror_levels(self, sample_levels_df):
        """Test that mirror levels get 'M' meta."""
        result = TradingViewSerializer.serialize_levels(sample_levels_df)

        # Check that mirror levels have 'M' meta
        assert ":M" in result

    def test_serialize_paranormal_levels(self, sample_levels_df):
        """Test that paranormal/high-score levels get 'P' meta."""
        result = TradingViewSerializer.serialize_levels(sample_levels_df)

        # The level with IsParanormal=True or Score>=30 should have 'P'
        assert ":P" in result

    def test_serialize_filter_by_ticker(self, sample_levels_df):
        """Test filtering by ticker."""
        # Add another ticker
        df = sample_levels_df.copy()
        df = pd.concat([df, pd.DataFrame({
            "Date": [pd.Timestamp("2025-01-06")],
            "Ticker": ["TSLA"],
            "Price": [200.00],
            "Type": ["R"],
            "Score": [20],
            "IsMirror": [False],
            "IsParanormal": [False],
        })], ignore_index=True)

        result = TradingViewSerializer.serialize_levels(df, ticker="AAPL")
        levels = TradingViewSerializer.deserialize_levels(result)

        # Should only have AAPL levels
        assert len(levels) == 5

    def test_serialize_max_levels(self, sample_levels_df):
        """Test limiting number of levels."""
        result = TradingViewSerializer.serialize_levels(
            sample_levels_df, max_levels=3
        )
        levels = TradingViewSerializer.deserialize_levels(result)

        assert len(levels) == 3

    def test_serialize_empty_df(self):
        """Test serializing empty DataFrame."""
        df = pd.DataFrame(columns=["Price", "Type", "Score", "IsMirror", "IsParanormal"])
        result = TradingViewSerializer.serialize_levels(df)

        assert result == ""

    def test_serialize_sort_by_score(self, sample_levels_df):
        """Test that levels are sorted by score descending."""
        result = TradingViewSerializer.serialize_levels(sample_levels_df)
        levels = TradingViewSerializer.deserialize_levels(result)

        # First level should be the highest score (155.00 with score 32)
        assert levels[0]["price"] == 155.00


class TestDeserializeLevels:
    """Test level deserialization."""

    def test_deserialize_basic(self):
        """Test basic deserialization."""
        input_str = "150.25:R:P,148.10:S:M,155.00:R:N"
        result = TradingViewSerializer.deserialize_levels(input_str)

        assert isinstance(result, list)
        assert len(result) == 3

    def test_deserialize_level_structure(self):
        """Test deserialized level structure."""
        input_str = "150.25:R:P"
        result = TradingViewSerializer.deserialize_levels(input_str)

        level = result[0]
        assert level["price"] == 150.25
        assert level["type"] == "Resistance"
        assert level["is_paranormal"] is True
        assert level["is_mirror"] is False

    def test_deserialize_support_level(self):
        """Test deserializing support level."""
        input_str = "148.10:S:M"
        result = TradingViewSerializer.deserialize_levels(input_str)

        level = result[0]
        assert level["type"] == "Support"
        assert level["is_mirror"] is True

    def test_deserialize_empty_string(self):
        """Test deserializing empty string."""
        result = TradingViewSerializer.deserialize_levels("")
        assert result == []

    def test_deserialize_invalid_format(self):
        """Test deserializing invalid format."""
        result = TradingViewSerializer.deserialize_levels("invalid")
        assert result == []


class TestFileSaveLoad:
    """Test file save and load operations."""

    def test_save_to_file(self, tmp_path):
        """Test saving to file."""
        output_dir = tmp_path / "output"
        tv_string = "150.25:R:P,148.10:S:M"

        filepath = TradingViewSerializer.save_to_file(
            tv_string, "AAPL", output_dir
        )

        assert filepath.exists()
        assert filepath.name == "levels_AAPL_tradingview.txt"
        assert filepath.read_text() == tv_string

    def test_load_from_file(self, tmp_path):
        """Test loading from file."""
        filepath = tmp_path / "test.txt"
        content = "150.25:R:P,148.10:S:M"
        filepath.write_text(content)

        result = TradingViewSerializer.load_from_file(filepath)
        assert result == content


class TestSummaryAndPineScript:
    """Test summary and Pine Script generation."""

    @pytest.fixture
    def sample_levels_df(self):
        """Create sample levels DataFrame."""
        return pd.DataFrame({
            "Date": pd.date_range("2025-01-01", periods=5),
            "Ticker": ["AAPL"] * 5,
            "Price": [150.25, 148.10, 155.00, 152.50, 149.75],
            "Type": ["R", "S", "R", "S", "M"],
            "Score": [25, 18, 32, 15, 20],
            "IsMirror": [False, True, False, False, True],
            "IsParanormal": [False, False, True, False, False],
        })

    def test_format_summary(self, sample_levels_df):
        """Test summary formatting."""
        summary = TradingViewSerializer.format_summary(sample_levels_df)

        assert "Level Summary" in summary
        assert "Total Levels:" in summary
        assert "Resistance:" in summary
        assert "Support:" in summary

    def test_generate_pine_script_array(self, sample_levels_df):
        """Test Pine Script array generation."""
        result = TradingViewSerializer.generate_pine_script_array(
            sample_levels_df, ticker="AAPL", array_name="my_levels"
        )

        assert "var float[] my_levels" in result
        assert "array.from(" in result
        assert "150.25" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
