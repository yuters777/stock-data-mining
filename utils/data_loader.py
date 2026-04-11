"""
Defensive M5 data loader for stock-data-mining.

Supports two data source formats:
  1. Alpha Vantage CSVs (legacy): dual-block structure with ET + IST blocks
  2. FMP CSVs (current): IST-equivalent timestamps (ET + 7h), single block

Both formats store timestamps as IST-equivalent (ET + 7h). The IST regular
session (16:30-22:55 IST) contains the bars for US regular session
(09:30-15:55 ET). This loader subtracts 7h to recover ET.

USAGE:
    from utils.data_loader import load_m5_regsess
    df = load_m5_regsess("TSLA")  # Returns ET timestamps, 09:30-15:55

BUG HISTORY:
    2026-03-24: Previous pipeline (phase1_test0_test1.py) filtered raw data
    by time range 09:30-15:55, which captured IST pre-market bars (11:00-15:55)
    instead of actual regular session data. This corrupted ~77% of bars in the
    _m5_regsess.csv files. See I8/I9 Series I audit for details.

DATA SOURCE MIGRATION:
    2026-04-11: Migrated from Alpha Vantage to FMP (Financial Modeling Prep).
    FMP data uses the same IST-equivalent convention (ET + 7h) for backward
    compatibility. FMP CSVs only have the IST block (no duplicate ET block).
"""

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# IST regular session boundaries (in the raw CSVs, both legacy AV and FMP)
_IST_REG_START = 16 * 60 + 30   # 16:30 IST = 09:30 ET
_IST_REG_END = 22 * 60 + 55     # 22:55 IST = 15:55 ET
_IST_TO_ET_OFFSET = pd.Timedelta(hours=7)

# Default data directory (relative to repo root)
_DEFAULT_RAW_DIR = "Fetched_Data"

# Tickers known to have valid data
ALL_TICKERS = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU", "BTC",
    "C", "COIN", "COST", "ETH", "GOOGL", "GS", "INTC", "JD", "JPM",
    "MARA", "META", "MSFT", "MSTR", "MU", "NVDA", "PLTR", "SMCI", "SPY",
    "TSLA", "TSM", "V", "VIX", "VIXY",
]


def load_m5_regsess(
    ticker: str,
    data_dir: Optional[str] = None,
    include_first_bar: bool = True,
    include_close_bar: bool = False,
) -> pd.DataFrame:
    """
    Load M5 regular-session data for a ticker from raw CSV (FMP or legacy AV).

    Selects the IST regular session block (16:30-22:55 IST) from the raw CSV
    and converts timestamps to US/Eastern. This avoids the dual-block bug
    where a naive time filter captures IST pre-market bars.

    Parameters
    ----------
    ticker : str
        Stock symbol (e.g. "TSLA", "SPY").
    data_dir : str, optional
        Path to directory containing {TICKER}_data.csv files.
        Defaults to Fetched_Data/ relative to the repo root.
    include_first_bar : bool
        If True, include the 09:30 ET bar. Default True.
    include_close_bar : bool
        If True, include the 16:00 ET close auction bar (23:00 IST).
        Default False (standard analysis excludes it).

    Returns
    -------
    pd.DataFrame
        Columns: Datetime, Open, High, Low, Close, Volume, Ticker.
        Datetime is timezone-naive in US/Eastern.
        Sorted chronologically, deduplicated.

    Raises
    ------
    FileNotFoundError
        If the raw CSV file does not exist.
    ValueError
        If no valid regular-session rows found after filtering.
    """
    if data_dir is None:
        # Auto-detect: look for Fetched_Data/ relative to this file's repo root
        repo_root = Path(__file__).resolve().parents[1]
        data_dir = repo_root / _DEFAULT_RAW_DIR

    data_dir = Path(data_dir)

    # Try standard naming, then crypto naming convention
    filepath = data_dir / f"{ticker}_data.csv"
    if not filepath.exists():
        filepath = data_dir / f"{ticker}_crypto_data.csv"
    if not filepath.exists():
        raise FileNotFoundError(
            f"Raw data file not found: {data_dir / ticker}_data.csv "
            f"(also tried _crypto_data.csv)")

    df = pd.read_csv(filepath, parse_dates=["Datetime"])
    total_raw = len(df)

    # Compute minutes since midnight for filtering
    hm = df["Datetime"].dt.hour * 60 + df["Datetime"].dt.minute

    # Select IST regular session block
    start = _IST_REG_START if include_first_bar else _IST_REG_START + 5
    end = _IST_REG_END
    mask = (hm >= start) & (hm <= end)

    # Optionally include close auction bar (23:00 IST = 16:00 ET)
    if include_close_bar:
        close_mask = (df["Datetime"].dt.hour == 23) & (df["Datetime"].dt.minute == 0)
        mask = mask | close_mask

    df = df[mask].copy()

    if df.empty:
        raise ValueError(
            f"No regular-session rows found for {ticker} in {filepath}. "
            f"Total raw rows: {total_raw}. Check data file integrity."
        )

    # Convert IST → ET
    df["Datetime"] = df["Datetime"] - _IST_TO_ET_OFFSET

    # Sort and deduplicate
    df = df.sort_values("Datetime").drop_duplicates(subset=["Datetime"]).reset_index(drop=True)

    # Validate: warn if many rows were filtered (expected for legacy AV dual-block data)
    pct_kept = len(df) / total_raw * 100
    if pct_kept < 30:
        logger.warning(
            f"{ticker}: only {pct_kept:.1f}% of raw rows kept ({len(df)}/{total_raw}). "
            f"This is expected for legacy dual-block CSV structure."
        )

    return df


def load_m5_regsess_ist(
    ticker: str,
    data_dir: Optional[str] = None,
    include_first_bar: bool = True,
) -> pd.DataFrame:
    """
    Load M5 regular-session data keeping IST timestamps (no ET conversion).

    Useful for scripts that already handle IST→ET conversion internally
    (e.g., Series I scripts I1-I7).

    Returns bars at 16:30-22:55 IST with original IST timestamps.
    """
    if data_dir is None:
        repo_root = Path(__file__).resolve().parents[1]
        data_dir = repo_root / _DEFAULT_RAW_DIR

    data_dir = Path(data_dir)

    # Try standard naming, then crypto naming convention
    filepath = data_dir / f"{ticker}_data.csv"
    if not filepath.exists():
        filepath = data_dir / f"{ticker}_crypto_data.csv"
    if not filepath.exists():
        raise FileNotFoundError(
            f"Raw data file not found: {data_dir / ticker}_data.csv "
            f"(also tried _crypto_data.csv)")

    df = pd.read_csv(filepath, parse_dates=["Datetime"])
    hm = df["Datetime"].dt.hour * 60 + df["Datetime"].dt.minute

    start = _IST_REG_START if include_first_bar else _IST_REG_START + 5
    mask = (hm >= start) & (hm <= _IST_REG_END)
    df = df[mask].copy()

    if df.empty:
        raise ValueError(f"No regular-session rows found for {ticker}")

    df = df.sort_values("Datetime").drop_duplicates(subset=["Datetime"]).reset_index(drop=True)
    return df
