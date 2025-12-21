"""
Market Data Fetcher Module.

Fetches market data from private MarketPatterns-AI GitHub repository.
Supports fetching combined data or individual ticker files.
"""

import logging
import os
from io import StringIO
from pathlib import Path
from typing import List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)


class MarketDataFetcher:
    """
    Fetch market data from private MarketPatterns-AI repository.

    Data is fetched via GitHub raw content API using a personal access token.
    Updates are available 3x daily (5 AM, 4 PM, 11:30 PM IST).
    """

    # Available tickers in MarketPatterns-AI
    AVAILABLE_TICKERS: List[str] = [
        "AAPL", "MSFT", "NVDA", "TSLA", "META",
        "COIN", "BABA", "GOOGL", "AMZN"
    ]

    def __init__(
        self,
        github_token: Optional[str] = None,
        repo: str = "yuters777/MarketPatterns-AI",
        branch: str = "main",
        cache_dir: Optional[Path] = None,
    ):
        """
        Initialize MarketDataFetcher.

        Args:
            github_token: GitHub Personal Access Token.
                          Defaults to GITHUB_TOKEN environment variable.
            repo: Repository in format 'owner/repo'.
            branch: Branch to fetch from.
            cache_dir: Directory to cache downloaded files.

        Raises:
            ValueError: If no GitHub token is provided or found.
        """
        self.token = github_token or os.getenv("GITHUB_TOKEN")
        if not self.token:
            raise ValueError(
                "GitHub token required. Set GITHUB_TOKEN environment variable "
                "or pass github_token parameter."
            )

        self.repo = repo
        self.branch = branch
        self.base_url = f"https://raw.githubusercontent.com/{repo}/{branch}"
        self.cache_dir = cache_dir or Path("level_detection/cache")

        # Create cache directory if specified
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"MarketDataFetcher initialized for {repo}/{branch}")

    def _get_headers(self) -> dict:
        """Get HTTP headers with authorization."""
        return {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3.raw",
        }

    def _fetch_csv(self, url: str, description: str = "data") -> pd.DataFrame:
        """
        Fetch CSV file from GitHub and parse as DataFrame.

        Args:
            url: Full URL to the raw CSV file.
            description: Description for logging.

        Returns:
            Parsed DataFrame.

        Raises:
            requests.HTTPError: If request fails.
        """
        logger.info(f"Fetching {description} from {url}")

        try:
            response = requests.get(url, headers=self._get_headers(), timeout=60)
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if response.status_code == 404:
                raise FileNotFoundError(f"File not found: {url}") from e
            elif response.status_code == 401:
                raise PermissionError(
                    "Invalid or expired GitHub token. Check GITHUB_TOKEN."
                ) from e
            raise

        df = pd.read_csv(StringIO(response.text), parse_dates=["Datetime"])
        logger.info(f"Fetched {len(df):,} rows")

        return df

    def fetch_combined_data(self, use_cache: bool = False) -> pd.DataFrame:
        """
        Fetch all tickers combined dataset.

        Args:
            use_cache: If True, use cached file if available.

        Returns:
            DataFrame with columns: Datetime, Open, High, Low, Close, Volume, Ticker
        """
        cache_file = self.cache_dir / "combined_sp500_all_data_5min.csv"

        if use_cache and cache_file.exists():
            logger.info(f"Loading from cache: {cache_file}")
            return pd.read_csv(cache_file, parse_dates=["Datetime"])

        url = f"{self.base_url}/Fetched_Data/combined_sp500_all_data_5min.csv"
        df = self._fetch_csv(url, "combined data")

        # Cache the result
        if self.cache_dir:
            df.to_csv(cache_file, index=False)
            logger.info(f"Cached to: {cache_file}")

        return df

    def fetch_ticker(
        self,
        ticker: str,
        use_cache: bool = False,
    ) -> pd.DataFrame:
        """
        Fetch single ticker data.

        Args:
            ticker: Stock symbol (e.g., 'AAPL', 'TSLA').
            use_cache: If True, use cached file if available.

        Returns:
            DataFrame with OHLCV data for the ticker.

        Raises:
            ValueError: If ticker is not in available list.
        """
        ticker = ticker.upper()

        if ticker not in self.AVAILABLE_TICKERS:
            raise ValueError(
                f"Ticker '{ticker}' not available. "
                f"Choose from: {', '.join(self.AVAILABLE_TICKERS)}"
            )

        cache_file = self.cache_dir / f"{ticker}_data.csv"

        if use_cache and cache_file.exists():
            logger.info(f"Loading {ticker} from cache: {cache_file}")
            return pd.read_csv(cache_file, parse_dates=["Datetime"])

        url = f"{self.base_url}/Fetched_Data/{ticker}_data.csv"
        df = self._fetch_csv(url, f"{ticker} data")

        # Add ticker column if not present
        if "Ticker" not in df.columns:
            df["Ticker"] = ticker

        # Cache the result
        if self.cache_dir:
            df.to_csv(cache_file, index=False)
            logger.info(f"Cached {ticker} to: {cache_file}")

        return df

    def fetch_summary(self) -> dict:
        """
        Fetch summary report metadata.

        Returns:
            Dictionary with summary information.
        """
        import json

        url = f"{self.base_url}/Fetched_Data/summary_report.json"
        logger.info(f"Fetching summary from {url}")

        response = requests.get(url, headers=self._get_headers(), timeout=30)
        response.raise_for_status()

        return json.loads(response.text)

    def get_available_tickers(self) -> List[str]:
        """
        Return list of available tickers.

        Returns:
            List of ticker symbols.
        """
        return self.AVAILABLE_TICKERS.copy()

    def clear_cache(self) -> None:
        """Clear all cached files."""
        if self.cache_dir and self.cache_dir.exists():
            for file in self.cache_dir.glob("*.csv"):
                file.unlink()
                logger.info(f"Removed cache file: {file}")

    def get_data_info(self, df: pd.DataFrame) -> dict:
        """
        Get information about the fetched data.

        Args:
            df: DataFrame with market data.

        Returns:
            Dictionary with data statistics.
        """
        return {
            "rows": len(df),
            "tickers": df["Ticker"].unique().tolist() if "Ticker" in df.columns else [],
            "date_range": {
                "start": df["Datetime"].min().isoformat(),
                "end": df["Datetime"].max().isoformat(),
            },
            "columns": df.columns.tolist(),
        }


def fetch_market_data(
    ticker: Optional[str] = None,
    use_cache: bool = False,
) -> pd.DataFrame:
    """
    Convenience function to fetch market data.

    Args:
        ticker: Optional ticker symbol. If None, fetches combined data.
        use_cache: If True, use cached file if available.

    Returns:
        DataFrame with market data.
    """
    fetcher = MarketDataFetcher()

    if ticker:
        return fetcher.fetch_ticker(ticker, use_cache=use_cache)
    return fetcher.fetch_combined_data(use_cache=use_cache)
