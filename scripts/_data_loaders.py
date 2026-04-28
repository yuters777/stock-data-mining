"""CSV data loaders for M5 extended bars, daily bars, earnings calendar, VIX daily."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)


def load_m5_extended(data_root: Path, ticker: str) -> pd.DataFrame:
    """Load extended M5 bars for a ticker.

    Expected schema: date (ET naive datetime), open, high, low, close, volume.
    Returns DataFrame indexed by the date column, sorted ascending.
    """
    f = data_root / f"{ticker}_m5_extended.csv"
    if not f.exists():
        raise FileNotFoundError(f"M5 file not found: {f}")
    df = pd.read_csv(f, parse_dates=["date"])
    df = df.set_index("date").sort_index()
    return df


def aggregate_m5_to_4h_rth(df_m5: pd.DataFrame) -> pd.DataFrame:
    """Aggregate M5 bars to 4H RTH-only bars.

    4H bar boundaries (production reference module4.py):
      Bar 1: 09:30-13:30 ET
      Bar 2: 13:30-16:00 ET

    Returns DataFrame with columns: date_et, bar_index (1 or 2), open, high, low, close, volume,
    timestamp_et.
    """
    df = df_m5.copy()
    # Index may be tz-naive ET (as loaded from CSV with 'date' column)
    idx = df.index
    if hasattr(idx, "tz") and idx.tz is not None:
        idx_et = idx.tz_convert("America/New_York")
    else:
        idx_et = idx

    rth_mask = (idx_et.time >= pd.Timestamp("09:30").time()) & (
        idx_et.time < pd.Timestamp("16:00").time()
    )
    weekday_mask = idx_et.weekday < 5
    df = df[rth_mask & weekday_mask].copy()
    idx_et = idx_et[rth_mask & weekday_mask]

    def _bar_index(t):
        return 1 if t < pd.Timestamp("13:30").time() else 2

    df["bar_index"] = [_bar_index(t) for t in idx_et.time]
    df["date_et"] = idx_et.date

    bars_4h = df.groupby(["date_et", "bar_index"]).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).reset_index()

    def _ts(row):
        t = "09:30" if row["bar_index"] == 1 else "13:30"
        return pd.Timestamp(f"{row['date_et']} {t}")

    bars_4h["timestamp_et"] = bars_4h.apply(_ts, axis=1)
    return bars_4h.sort_values("timestamp_et").reset_index(drop=True)


def aggregate_m5_to_daily(df_m5: pd.DataFrame) -> pd.DataFrame:
    """Aggregate M5 bars to daily RTH-only bars."""
    df = df_m5.copy()
    idx = df.index
    if hasattr(idx, "tz") and idx.tz is not None:
        idx_et = idx.tz_convert("America/New_York")
    else:
        idx_et = idx

    rth_mask = (idx_et.time >= pd.Timestamp("09:30").time()) & (
        idx_et.time < pd.Timestamp("16:00").time()
    )
    weekday_mask = idx_et.weekday < 5
    df = df[rth_mask & weekday_mask].copy()
    idx_et = idx_et[rth_mask & weekday_mask]

    df["date_et"] = idx_et.date
    daily = df.groupby("date_et").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).reset_index()
    return daily.sort_values("date_et").reset_index(drop=True)


def load_vix_daily(data_root: Path) -> pd.DataFrame:
    """Load FRED VIX daily series. Schema: date (YYYY-MM-DD), vix_close."""
    f = data_root / "VIX_daily.csv"
    if not f.exists():
        raise FileNotFoundError(f"VIX file not found: {f}")
    df = pd.read_csv(f, parse_dates=["date"])
    return df.sort_values("date").reset_index(drop=True)


def load_earnings_calendar(data_root: Path) -> pd.DataFrame:
    """Load earnings calendar. Schema: ticker, earnings_date, [optional columns]."""
    f = data_root / "earnings_calendar.csv"
    if not f.exists():
        raise FileNotFoundError(f"Earnings calendar not found: {f}")
    df = pd.read_csv(f, parse_dates=["earnings_date"])
    return df


def load_news_index(data_root: Path) -> Optional[pd.DataFrame]:
    """Load news index for M6 no-news filter. Optional.

    Schema: ticker, news_timestamp_utc, classification.
    Returns None if file not present (M6 assumes NO_CLASSIFIED_NEWS).
    """
    f = data_root / "news_index.csv"
    if not f.exists():
        log.warning(f"News index not found: {f} — M6 filter will assume NEWS_DATA_UNKNOWN")
        return None
    df = pd.read_csv(f, parse_dates=["news_timestamp_utc"])
    return df


def load_corporate_actions(data_root: Path) -> Optional[pd.DataFrame]:
    """Load corporate actions for M6 split/dividend guard. Optional.

    Schema: ticker, action_date, action_type, value.
    Returns None if file not present (M6 skips CA guard).
    """
    f = data_root / "corporate_actions.csv"
    if not f.exists():
        log.warning(f"Corporate actions not found: {f} — M6 will skip CA guard")
        return None
    df = pd.read_csv(f, parse_dates=["action_date"])
    return df
