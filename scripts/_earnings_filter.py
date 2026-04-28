"""Parameterized earnings window filter."""
from __future__ import annotations

from datetime import date as Date, datetime

import pandas as pd


def is_in_earnings_window(
    ticker: str,
    date_str: str,
    buffer_days: int,
    earnings_df: pd.DataFrame,
) -> bool:
    """Return True if ticker has any earnings event within ±buffer_days of date_str.

    Args:
        ticker: Ticker symbol (uppercase).
        date_str: Date in 'YYYY-MM-DD' format.
        buffer_days: Symmetric buffer in calendar days. 0 = no filter (always returns False).
        earnings_df: DataFrame with columns [ticker, earnings_date]. earnings_date is
            datetime-coercible (str 'YYYY-MM-DD' or pandas Timestamp).

    Returns:
        True if filter should BLOCK the trade. False if trade is allowed.
    """
    if buffer_days == 0:
        return False

    if earnings_df is None or earnings_df.empty:
        return False

    base: Date = datetime.strptime(date_str, "%Y-%m-%d").date()

    relevant = earnings_df[earnings_df["ticker"] == ticker]
    if relevant.empty:
        return False

    for ed in pd.to_datetime(relevant["earnings_date"]):
        ed_date: Date = ed.date() if hasattr(ed, "date") else ed
        days_diff = abs((ed_date - base).days)
        if days_diff <= buffer_days:
            return True

    return False
