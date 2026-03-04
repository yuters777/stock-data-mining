"""
Data loader for the False Breakout Strategy Backtester.

Loads M5 OHLCV CSVs (IST timezone-naive), tags sessions, assigns trading days,
aggregates D1 bars from regular session, and validates data quality.

Reference: Data_Request_v2 §5, L-005.1 spec.

CRITICAL RULES:
- NO timezone conversion. Data stays in IST.
- Saturday bars (00:00-02:55 IST) → Friday's trading day.
- D1 aggregation = regular session ONLY.
- All M5 bars kept; time filters applied later by filter_chain.
"""

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Session boundaries (IST hours)
PRE_MARKET_START_HOUR = 11    # 11:00 IST
PRE_MARKET_END_HOUR = 16     # up to 16:25 IST
REGULAR_START_HOUR = 16      # 16:30 IST
REGULAR_START_MINUTE = 30
REGULAR_END_HOUR = 22        # up to 22:55 IST
CLOSE_BAR_HOUR = 23          # 23:00 IST close bar
POST_MARKET_START_HOUR = 23  # 23:05+ IST

# All 9 tickers from the spec
ALL_TICKERS = ["AAPL", "MSFT", "NVDA", "TSLA", "META", "COIN", "BABA", "GOOGL", "AMZN"]


def load_m5(ticker: str, data_dir: str | Path) -> pd.DataFrame:
    """Load M5 data from CSV for a single ticker.

    Args:
        ticker: Stock symbol (e.g. "NVDA").
        data_dir: Directory containing {TICKER}_data.csv files.

    Returns:
        DataFrame with columns: Datetime, Open, High, Low, Close, Volume, Ticker.
        Datetime is parsed as timezone-naive (IST).

    Raises:
        FileNotFoundError: If CSV file does not exist.
    """
    data_dir = Path(data_dir)
    filepath = data_dir / f"{ticker}_data.csv"

    if not filepath.exists():
        raise FileNotFoundError(f"Data file not found: {filepath}")

    df = pd.read_csv(filepath, parse_dates=["Datetime"])

    # Ensure correct dtypes
    for col in ["Open", "High", "Low", "Close"]:
        df[col] = df[col].astype(float)
    df["Volume"] = df["Volume"].astype(int)

    # Sort by time (ensure chronological)
    df = df.sort_values("Datetime").reset_index(drop=True)

    logger.info(f"Loaded {ticker}: {len(df)} bars, "
                f"{df['Datetime'].min()} → {df['Datetime'].max()}")
    return df


def assign_trading_day(dt: pd.Timestamp) -> date:
    """Map a bar's timestamp to its logical trading day.

    Saturday IST 00:00-02:55 bars belong to Friday's trading day.
    Post-market bars after midnight (00:00-02:55) belong to the previous day.
    All other bars belong to their calendar date.

    Args:
        dt: Bar timestamp (IST, timezone-naive).

    Returns:
        The trading day (date) this bar belongs to.
    """
    # Saturday (dayofweek=5) with early morning hours → Friday
    if dt.dayofweek == 5 and dt.hour < 3:
        return (dt - timedelta(days=1)).date()

    # Weekday post-market past midnight (00:00-02:55) → previous day
    # These are bars from hours 0, 1, 2 on weekdays (Mon-Fri)
    if dt.hour < 3:
        return (dt - timedelta(days=1)).date()

    return dt.date()


def tag_session(dt: pd.Timestamp) -> str:
    """Classify a bar timestamp into its trading session.

    IST session mapping:
    - PRE_MARKET:  11:00–16:25
    - REGULAR:     16:30–22:55 (includes 23:00 close bar)
    - POST_MARKET: 23:05+ and 00:00–02:55

    Args:
        dt: Bar timestamp (IST, timezone-naive).

    Returns:
        Session label: "PRE_MARKET", "REGULAR", or "POST_MARKET".
    """
    hour = dt.hour
    minute = dt.minute

    # Post-market: 00:00–02:55
    if hour < 3:
        return "POST_MARKET"

    # Pre-market: 11:00–16:25
    if PRE_MARKET_START_HOUR <= hour < REGULAR_START_HOUR:
        return "PRE_MARKET"
    if hour == REGULAR_START_HOUR and minute < REGULAR_START_MINUTE:
        return "PRE_MARKET"

    # Regular: 16:30–22:55
    if hour == REGULAR_START_HOUR and minute >= REGULAR_START_MINUTE:
        return "REGULAR"
    if REGULAR_START_HOUR < hour <= REGULAR_END_HOUR:
        return "REGULAR"

    # 23:00 close bar is REGULAR
    if hour == CLOSE_BAR_HOUR and minute == 0:
        return "REGULAR"

    # Post-market: 23:05+
    if hour >= CLOSE_BAR_HOUR:
        return "POST_MARKET"

    # Anything else (shouldn't happen with valid data, but be safe)
    return "PRE_MARKET"


def tag_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Add trading_day and session columns to a DataFrame.

    Args:
        df: DataFrame with a 'Datetime' column.

    Returns:
        Same DataFrame with 'trading_day' (date) and 'session' (str) columns added.
    """
    df = df.copy()
    df["trading_day"] = df["Datetime"].apply(assign_trading_day)
    df["session"] = df["Datetime"].apply(tag_session)
    return df


def aggregate_d1(m5_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate M5 bars into daily (D1) OHLCV — regular session only.

    Uses only REGULAR session bars for aggregation.
    Groups by trading_day to produce one D1 bar per trading day.

    Args:
        m5_df: Tagged M5 DataFrame (must have 'trading_day' and 'session' columns).

    Returns:
        DataFrame with columns: trading_day, Open, High, Low, Close, Volume, Ticker.
    """
    # Filter to regular session only
    regular = m5_df[m5_df["session"] == "REGULAR"].copy()

    if regular.empty:
        return pd.DataFrame(columns=["trading_day", "Open", "High", "Low",
                                      "Close", "Volume", "Ticker"])

    # Group by trading_day, aggregate OHLCV
    d1 = regular.groupby("trading_day").agg(
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
        Volume=("Volume", "sum"),
        Ticker=("Ticker", "first"),
    ).reset_index()

    d1 = d1.sort_values("trading_day").reset_index(drop=True)

    logger.info(f"D1 aggregation: {len(d1)} trading days from "
                f"{len(m5_df)} M5 bars ({len(regular)} regular session)")
    return d1


def validate_data(df: pd.DataFrame) -> list[str]:
    """Validate data quality of an M5 DataFrame.

    Checks:
    1. No NULL values in OHLCV columns
    2. OHLC consistency: High >= Low, High >= Open/Close, Low <= Open/Close
    3. Volume >= 0
    4. Chronological order
    5. No duplicate timestamps (per ticker)

    Args:
        df: M5 DataFrame with standard columns.

    Returns:
        List of error/warning messages. Empty = clean data.

    Raises:
        ValueError: If critical data quality issues are found.
    """
    errors = []

    required_cols = ["Datetime", "Open", "High", "Low", "Close", "Volume"]
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        errors.append(f"Missing columns: {missing_cols}")
        raise ValueError("; ".join(errors))

    # 1. NULL check
    nulls = df[required_cols].isnull().sum()
    null_cols = nulls[nulls > 0]
    if len(null_cols) > 0:
        errors.append(f"NULL values found: {null_cols.to_dict()}")

    # 2. OHLC consistency
    bad_hl = df[df["High"] < df["Low"]]
    if len(bad_hl) > 0:
        errors.append(f"High < Low in {len(bad_hl)} bars")

    bad_ho = df[df["High"] < df["Open"]]
    if len(bad_ho) > 0:
        errors.append(f"High < Open in {len(bad_ho)} bars")

    bad_hc = df[df["High"] < df["Close"]]
    if len(bad_hc) > 0:
        errors.append(f"High < Close in {len(bad_hc)} bars")

    bad_lo = df[df["Low"] > df["Open"]]
    if len(bad_lo) > 0:
        errors.append(f"Low > Open in {len(bad_lo)} bars")

    bad_lc = df[df["Low"] > df["Close"]]
    if len(bad_lc) > 0:
        errors.append(f"Low > Close in {len(bad_lc)} bars")

    # 3. Volume >= 0
    neg_vol = df[df["Volume"] < 0]
    if len(neg_vol) > 0:
        errors.append(f"Negative volume in {len(neg_vol)} bars")

    # 4. Chronological order
    if not df["Datetime"].is_monotonic_increasing:
        # Check if it's just not sorted vs has actual issues
        sorted_df = df.sort_values("Datetime")
        if sorted_df["Datetime"].equals(df["Datetime"]):
            pass  # already sorted
        else:
            errors.append("Data is not in chronological order")

    # 5. No duplicate timestamps per ticker
    if "Ticker" in df.columns:
        dups = df.groupby("Ticker")["Datetime"].apply(
            lambda x: x.duplicated().sum()
        )
        dup_tickers = dups[dups > 0]
        if len(dup_tickers) > 0:
            errors.append(f"Duplicate timestamps: {dup_tickers.to_dict()}")
    else:
        dup_count = df["Datetime"].duplicated().sum()
        if dup_count > 0:
            errors.append(f"Duplicate timestamps: {dup_count}")

    if errors:
        raise ValueError("; ".join(errors))

    return errors


def load_all_tickers(data_dir: str | Path) -> dict[str, pd.DataFrame]:
    """Load M5 data for all available tickers in the data directory.

    Args:
        data_dir: Directory containing {TICKER}_data.csv files.

    Returns:
        Dict mapping ticker symbol to its M5 DataFrame.
    """
    data_dir = Path(data_dir)
    result = {}

    for ticker in ALL_TICKERS:
        filepath = data_dir / f"{ticker}_data.csv"
        if filepath.exists():
            try:
                df = load_m5(ticker, data_dir)
                result[ticker] = df
                logger.info(f"Loaded {ticker}: {len(df)} bars")
            except Exception as e:
                logger.warning(f"Failed to load {ticker}: {e}")
        else:
            logger.info(f"Skipping {ticker}: file not found")

    logger.info(f"Loaded {len(result)} tickers: {sorted(result.keys())}")
    return result


def prepare_backtester_data(
    data_dir: str | Path,
    output_dir: str | Path,
    tickers: Optional[list[str]] = None,
) -> dict:
    """Full data preparation pipeline: load → validate → tag → aggregate → save.

    Produces:
    - {output_dir}/{ticker}_m5.parquet — tagged M5 data
    - {output_dir}/{ticker}_d1.parquet — D1 aggregated data
    - {output_dir}/metadata.json — summary of processed data
    - {output_dir}/data_quality_report.json — validation results

    Args:
        data_dir: Directory containing raw CSV files.
        output_dir: Directory to write processed data.
        tickers: Optional list of tickers to process. None = all available.

    Returns:
        Dict with metadata about processed data.
    """
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load all tickers
    all_data = load_all_tickers(data_dir)
    if tickers:
        all_data = {t: df for t, df in all_data.items() if t in tickers}

    metadata = {"tickers": {}, "processed_at": pd.Timestamp.now().isoformat()}
    quality_report = {}

    for ticker, df in all_data.items():
        logger.info(f"Processing {ticker}...")

        # Validate
        try:
            validate_data(df)
            quality_report[ticker] = {"status": "clean", "errors": []}
        except ValueError as e:
            quality_report[ticker] = {"status": "issues", "errors": str(e).split("; ")}
            logger.warning(f"{ticker} validation issues: {e}")

        # Tag sessions and trading days
        tagged = tag_dataframe(df)

        # Aggregate D1
        d1 = aggregate_d1(tagged)

        # Save parquet
        tagged.to_parquet(output_dir / f"{ticker}_m5.parquet", index=False)
        d1.to_parquet(output_dir / f"{ticker}_d1.parquet", index=False)

        metadata["tickers"][ticker] = {
            "m5_bars": len(tagged),
            "d1_days": len(d1),
            "date_range": f"{df['Datetime'].min()} → {df['Datetime'].max()}",
            "sessions": tagged["session"].value_counts().to_dict(),
        }

    # Save metadata
    with open(output_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    with open(output_dir / "data_quality_report.json", "w") as f:
        json.dump(quality_report, f, indent=2)

    logger.info(f"Prepared data for {len(all_data)} tickers → {output_dir}")
    return metadata
