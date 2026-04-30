"""EMA9 + EMA21 computation for both daily and 4H frequencies.

Standard EMA formula:
  multiplier = 2 / (period + 1)
  EMA_today = (close - EMA_yesterday) * multiplier + EMA_yesterday
  Seed: SMA of first <period> closes

Production references:
  - module7.py:539-593 (daily EMA9 from last M5 close per day)
  - module4.py:444-450 (Finding 6: warmup detection after data gap)

Warmup-after-gap rule (Finding 6):
  If a ticker has a data gap of >5 trading days, EMA needs N=21 bars to re-warm.
  During warmup, EMA21 is considered unreliable and triggers are blocked.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd

WARMUP_GAP_THRESHOLD_CALENDAR_DAYS = 7  # >5 trading days ≈ >7 calendar days
WARMUP_REQUIRED_BARS = 21


def compute_ema_series(closes: pd.Series, period: int) -> pd.Series:
    """Compute EMA series. SMA seed for first <period> values.
    Returns pd.Series same length as input; values before seed are NaN.
    """
    if len(closes) < period:
        return pd.Series([float("nan")] * len(closes), index=closes.index)

    multiplier = 2.0 / (period + 1)
    out = [float("nan")] * (period - 1)
    seed = float(closes.iloc[:period].mean())
    out.append(seed)

    ema = seed
    for c in closes.iloc[period:]:
        ema = (float(c) - ema) * multiplier + ema
        out.append(ema)

    return pd.Series(out, index=closes.index)


def compute_daily_ema_for_ticker(m5_df: pd.DataFrame, period: int) -> pd.DataFrame:
    """Compute daily EMA from M5 bars (last close of each day = daily close).

    Returns DataFrame with columns: date_et, daily_close, ema.
    Production reference: module7.py:539-593.
    """
    df = m5_df.copy()
    df["date_et"] = df["date"].dt.date
    daily = df.groupby("date_et").agg({"close": "last"}).reset_index()
    daily.columns = ["date_et", "daily_close"]
    daily = daily.sort_values("date_et").reset_index(drop=True)
    daily["ema"] = compute_ema_series(daily["daily_close"], period)
    return daily


def compute_4h_ema_for_ticker(bars_4h_df: pd.DataFrame, period: int) -> pd.DataFrame:
    """Compute 4H EMA from reconstructed 4H bars.
    bars_4h_df must be filtered to single ticker, sorted by date_et/timestamp_et.
    """
    df = bars_4h_df.sort_values(["date_et", "timestamp_et"]).reset_index(drop=True).copy()
    df["ema"] = compute_ema_series(df["close"], period)
    return df


def detect_warmup_after_gap(daily_df: pd.DataFrame, current_date: date) -> bool:
    """Return True if EMA21 is in warmup after a >5-day data gap (Finding 6).

    Production reference: module4.py:444-450.
    Logic: find the most recent gap >7 calendar days (≈>5 trading days) BEFORE
    current_date. If found, count bars since gap end. If <21, warmup is active.
    """
    if daily_df.empty:
        return True

    relevant = daily_df[daily_df["date_et"] <= current_date].copy()
    if len(relevant) < WARMUP_REQUIRED_BARS:
        return True  # insufficient history

    relevant = relevant.sort_values("date_et").reset_index(drop=True)
    date_series = pd.to_datetime(relevant["date_et"])
    gap_days = (date_series - date_series.shift(1)).dt.days

    gap_mask = gap_days > WARMUP_GAP_THRESHOLD_CALENDAR_DAYS
    if not gap_mask.any():
        return False

    last_gap_idx = int(gap_mask[gap_mask].index.max())
    bars_since_gap = len(relevant) - last_gap_idx
    return bars_since_gap < WARMUP_REQUIRED_BARS


def get_ema_at_date(daily_df: pd.DataFrame, d: date, period: int) -> Optional[float]:
    """Get EMA value for a ticker at a specific date from the daily_df
    produced by compute_daily_ema_for_ticker."""
    matches = daily_df[daily_df["date_et"] == d]
    if matches.empty:
        return None
    val = matches.iloc[0]["ema"]
    return None if pd.isna(val) else float(val)
