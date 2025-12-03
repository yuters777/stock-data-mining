"""
Data Aggregator Module for BSU Detection.

Handles:
- Loading 5-minute OHLCV data
- Aggregating 5-min data to daily (D1) timeframe
- Modified ATR calculation (excludes anomalous bars)
"""

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .config import Config, DEFAULT_CONFIG


class DataAggregator:
    """
    Aggregates 5-minute data to daily and calculates Modified ATR.

    The Modified ATR excludes bars with ranges that are:
    - Greater than 2.0 × previous ATR (paranormal bars)
    - Less than 0.5 × previous ATR (insignificant bars)
    """

    def __init__(self, config: Config = DEFAULT_CONFIG):
        """
        Initialize DataAggregator with configuration.

        Args:
            config: Configuration parameters
        """
        self.config = config

    def load_data(self, file_path: Optional[Path] = None) -> pd.DataFrame:
        """
        Load 5-minute OHLCV data from CSV.

        Args:
            file_path: Path to CSV file. Uses config default if not provided.

        Returns:
            DataFrame with columns: Datetime, Open, High, Low, Close, Volume, Ticker
        """
        path = file_path or self.config.DATA_PATH

        df = pd.read_csv(path)
        df["Datetime"] = pd.to_datetime(df["Datetime"])
        df = df.sort_values(["Ticker", "Datetime"]).reset_index(drop=True)

        return df

    def aggregate_to_daily(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Aggregate 5-minute bars to daily (D1) OHLCV per ticker.

        Args:
            df: DataFrame with 5-minute OHLCV data

        Returns:
            DataFrame with daily OHLCV data per ticker
        """
        df = df.copy()
        df["Date"] = df["Datetime"].dt.date

        # Aggregate OHLCV per ticker per day
        daily = df.groupby(["Ticker", "Date"]).agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum"
        }).reset_index()

        daily["Date"] = pd.to_datetime(daily["Date"])
        daily = daily.sort_values(["Ticker", "Date"]).reset_index(drop=True)

        # Calculate True Range
        daily["TR"] = self._calculate_true_range(daily)

        return daily

    def _calculate_true_range(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate True Range for each bar.

        TR = max(High - Low, |High - Close_prev|, |Low - Close_prev|)

        Args:
            df: DataFrame with OHLCV data

        Returns:
            Series with True Range values
        """
        tr = pd.Series(index=df.index, dtype=float)

        for ticker in df["Ticker"].unique():
            mask = df["Ticker"] == ticker
            ticker_df = df[mask].copy()

            high_low = ticker_df["High"] - ticker_df["Low"]
            high_close_prev = abs(ticker_df["High"] - ticker_df["Close"].shift(1))
            low_close_prev = abs(ticker_df["Low"] - ticker_df["Close"].shift(1))

            ticker_tr = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)
            tr.loc[mask] = ticker_tr.values

        return tr

    def calculate_modified_atr(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate Modified ATR that excludes anomalous bars.

        Modified ATR excludes bars where:
        - Range > 2.0 × previous ATR (paranormal)
        - Range < 0.5 × previous ATR (insignificant)

        Args:
            df: DataFrame with daily OHLCV and TR column

        Returns:
            DataFrame with additional ATR and ModifiedATR columns
        """
        df = df.copy()
        period = self.config.ATR_PERIOD
        upper_mult = self.config.ATR_UPPER_MULT
        lower_mult = self.config.ATR_LOWER_MULT

        df["ATR"] = np.nan
        df["ModifiedATR"] = np.nan
        df["IsParanormal"] = False

        for ticker in df["Ticker"].unique():
            mask = df["Ticker"] == ticker
            ticker_idx = df[mask].index.tolist()

            if len(ticker_idx) < period:
                continue

            # Initialize with simple average for first period
            first_atr = df.loc[ticker_idx[:period], "TR"].mean()
            df.loc[ticker_idx[period - 1], "ATR"] = first_atr
            df.loc[ticker_idx[period - 1], "ModifiedATR"] = first_atr

            # Calculate Modified ATR using filtered bars
            for i in range(period, len(ticker_idx)):
                current_idx = ticker_idx[i]
                prev_idx = ticker_idx[i - 1]

                prev_atr = df.loc[prev_idx, "ModifiedATR"]
                current_tr = df.loc[current_idx, "TR"]

                # Check if bar is anomalous
                upper_threshold = prev_atr * upper_mult
                lower_threshold = prev_atr * lower_mult

                is_paranormal = current_tr >= upper_threshold
                is_insignificant = current_tr <= lower_threshold

                df.loc[current_idx, "IsParanormal"] = is_paranormal

                # For Modified ATR, exclude anomalous bars
                if is_paranormal or is_insignificant:
                    # Use previous Modified ATR value
                    df.loc[current_idx, "ModifiedATR"] = prev_atr
                else:
                    # Standard ATR calculation: EMA of TR
                    # Using Wilder's smoothing: ATR = ((period-1) * prev_ATR + TR) / period
                    new_atr = ((period - 1) * prev_atr + current_tr) / period
                    df.loc[current_idx, "ModifiedATR"] = new_atr

                # Regular ATR (includes all bars)
                prev_regular_atr = df.loc[prev_idx, "ATR"]
                if pd.notna(prev_regular_atr):
                    df.loc[current_idx, "ATR"] = ((period - 1) * prev_regular_atr + current_tr) / period

        return df

    def process_data(self, file_path: Optional[Path] = None) -> pd.DataFrame:
        """
        Complete data processing pipeline.

        Loads 5-min data, aggregates to daily, and calculates Modified ATR.

        Args:
            file_path: Optional path to input CSV file

        Returns:
            Processed DataFrame with daily OHLCV and ATR values
        """
        # Load 5-minute data
        df_5min = self.load_data(file_path)

        # Aggregate to daily
        df_daily = self.aggregate_to_daily(df_5min)

        # Calculate Modified ATR
        df_daily = self.calculate_modified_atr(df_daily)

        return df_daily

    def get_ticker_data(
        self, df: pd.DataFrame, ticker: str
    ) -> pd.DataFrame:
        """
        Extract data for a specific ticker.

        Args:
            df: DataFrame with all ticker data
            ticker: Ticker symbol to extract

        Returns:
            DataFrame with only the specified ticker's data
        """
        return df[df["Ticker"] == ticker].copy().reset_index(drop=True)
