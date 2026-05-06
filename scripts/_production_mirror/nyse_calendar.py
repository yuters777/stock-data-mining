"""NYSE trading calendar loader — runtime, no external deps.

Reads Fetched_Data/nyse_calendar_2021_2026.csv (generated once via
pandas_market_calendars in _generate_nyse_calendar.py).

Production reference: market-engine market_calendar_day table schema
(columns: trading_date_et, session_mode, early_close_et — verified Day 43
via market_db_query_readonly).
"""
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

_CALENDAR_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "Fetched_Data"
    / "nyse_calendar_2021_2026.csv"
)
_CALENDAR_CACHE: Optional[pd.DataFrame] = None


def load_calendar() -> pd.DataFrame:
    """Load NYSE calendar (cached on first call). Schema:
    - trading_date_et: str YYYY-MM-DD
    - session_mode: 'standard' | 'early_close'
    - early_close_et: str HH:MM or NaN
    """
    global _CALENDAR_CACHE
    if _CALENDAR_CACHE is None:
        if not _CALENDAR_PATH.exists():
            raise FileNotFoundError(
                f"NYSE calendar not found at {_CALENDAR_PATH}. "
                f"Run scripts/_production_mirror/_generate_nyse_calendar.py first."
            )
        _CALENDAR_CACHE = pd.read_csv(_CALENDAR_PATH)
    return _CALENDAR_CACHE


def _trading_day_set() -> set:
    return set(load_calendar()["trading_date_et"])


def is_trading_day(d: date) -> bool:
    return d.strftime("%Y-%m-%d") in _trading_day_set()


def get_session_mode(d: date) -> Optional[str]:
    """Return 'standard' or 'early_close', or None if not a trading day."""
    cal = load_calendar()
    matches = cal[cal["trading_date_et"] == d.strftime("%Y-%m-%d")]
    if matches.empty:
        return None
    return str(matches.iloc[0]["session_mode"])


def get_early_close_et(d: date) -> Optional[str]:
    """Return early-close time (HH:MM ET) if early close day, else None."""
    cal = load_calendar()
    matches = cal[cal["trading_date_et"] == d.strftime("%Y-%m-%d")]
    if matches.empty:
        return None
    val = matches.iloc[0]["early_close_et"]
    if pd.isna(val):
        return None
    return str(val)


def trading_days_between(start: date, end: date) -> int:
    """Count trading days in (start, end] — exclusive of start, inclusive of end."""
    cal = load_calendar()
    mask = (cal["trading_date_et"] > start.strftime("%Y-%m-%d")) & (
        cal["trading_date_et"] <= end.strftime("%Y-%m-%d")
    )
    return int(mask.sum())
