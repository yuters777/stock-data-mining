"""
Tests for Market Data Fetcher Module.

Note: Some tests require GITHUB_TOKEN environment variable.
Tests without token will be skipped.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from level_detection.market_data_fetcher import MarketDataFetcher


class TestMarketDataFetcherInit:
    """Test MarketDataFetcher initialization."""

    def test_init_with_token(self):
        """Test initialization with explicit token."""
        fetcher = MarketDataFetcher(github_token="test_token")
        assert fetcher.token == "test_token"
        assert fetcher.repo == "yuters777/MarketPatterns-AI"
        assert fetcher.branch == "main"

    def test_init_with_env_token(self):
        """Test initialization with environment variable."""
        with patch.dict(os.environ, {"GITHUB_TOKEN": "env_token"}):
            fetcher = MarketDataFetcher()
            assert fetcher.token == "env_token"

    def test_init_without_token_raises(self):
        """Test that initialization without token raises ValueError."""
        with patch.dict(os.environ, {}, clear=True):
            if "GITHUB_TOKEN" in os.environ:
                del os.environ["GITHUB_TOKEN"]
            with pytest.raises(ValueError, match="GitHub token required"):
                MarketDataFetcher(github_token=None)

    def test_custom_repo_and_branch(self):
        """Test initialization with custom repo and branch."""
        fetcher = MarketDataFetcher(
            github_token="token",
            repo="owner/repo",
            branch="develop",
        )
        assert fetcher.repo == "owner/repo"
        assert fetcher.branch == "develop"
        assert "owner/repo" in fetcher.base_url
        assert "develop" in fetcher.base_url


class TestAvailableTickers:
    """Test ticker availability."""

    def test_get_available_tickers(self):
        """Test getting list of available tickers."""
        fetcher = MarketDataFetcher(github_token="test")
        tickers = fetcher.get_available_tickers()

        assert isinstance(tickers, list)
        assert len(tickers) == 9
        assert "AAPL" in tickers
        assert "TSLA" in tickers
        assert "MSFT" in tickers

    def test_available_tickers_is_copy(self):
        """Test that returned list is a copy."""
        fetcher = MarketDataFetcher(github_token="test")
        tickers1 = fetcher.get_available_tickers()
        tickers2 = fetcher.get_available_tickers()

        tickers1.append("TEST")
        assert "TEST" not in tickers2


class TestFetchMethods:
    """Test fetch methods with mocking."""

    @pytest.fixture
    def mock_fetcher(self):
        """Create fetcher with mocked requests."""
        return MarketDataFetcher(github_token="test_token")

    @pytest.fixture
    def sample_csv_data(self):
        """Sample CSV response data."""
        return """Datetime,Open,High,Low,Close,Volume,Ticker
2025-01-02 09:30:00,150.0,151.0,149.5,150.5,1000000,AAPL
2025-01-02 09:35:00,150.5,152.0,150.0,151.5,1100000,AAPL
2025-01-02 09:40:00,151.5,153.0,151.0,152.5,1200000,AAPL"""

    def test_fetch_ticker_parses_csv(self, mock_fetcher, sample_csv_data):
        """Test that fetch_ticker correctly parses CSV data."""
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = sample_csv_data
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            df = mock_fetcher.fetch_ticker("AAPL")

            assert isinstance(df, pd.DataFrame)
            assert len(df) == 3
            assert "Datetime" in df.columns
            assert "Open" in df.columns
            assert "Ticker" in df.columns

    def test_fetch_ticker_invalid_ticker(self, mock_fetcher):
        """Test that invalid ticker raises ValueError."""
        with pytest.raises(ValueError, match="not available"):
            mock_fetcher.fetch_ticker("INVALID")

    def test_fetch_combined_data(self, mock_fetcher, sample_csv_data):
        """Test fetching combined data."""
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = sample_csv_data
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            df = mock_fetcher.fetch_combined_data()

            assert isinstance(df, pd.DataFrame)
            assert len(df) == 3


class TestDataInfo:
    """Test data info methods."""

    def test_get_data_info(self):
        """Test getting data info from DataFrame."""
        fetcher = MarketDataFetcher(github_token="test")

        df = pd.DataFrame({
            "Datetime": pd.date_range("2025-01-01", periods=10, freq="5min"),
            "Open": range(10),
            "High": range(10),
            "Low": range(10),
            "Close": range(10),
            "Volume": range(10),
            "Ticker": ["AAPL"] * 10,
        })

        info = fetcher.get_data_info(df)

        assert info["rows"] == 10
        assert "AAPL" in info["tickers"]
        assert "start" in info["date_range"]
        assert "end" in info["date_range"]


class TestCaching:
    """Test caching functionality."""

    def test_cache_dir_created(self, tmp_path):
        """Test that cache directory is created."""
        cache_dir = tmp_path / "cache"
        fetcher = MarketDataFetcher(
            github_token="test",
            cache_dir=cache_dir,
        )
        assert cache_dir.exists()

    def test_clear_cache(self, tmp_path):
        """Test clearing cache."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "test.csv").write_text("test")

        fetcher = MarketDataFetcher(
            github_token="test",
            cache_dir=cache_dir,
        )
        fetcher.clear_cache()

        assert not list(cache_dir.glob("*.csv"))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
