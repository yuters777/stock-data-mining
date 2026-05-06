"""Reconstruct 4H bars from M5 OHLCV CSVs.

Production stores M5 raw and reconstructs 4H on-demand. Backtest mirrors this
by resampling per-day from start of session.

Bar boundaries (ET):
  Bar A: 04:00 → 09:30 (pre-market)
  Bar B: 09:30 → 13:30 (RTH morning)
  Bar C: 13:30 → 16:00 (RTH final — is_final_session_bar=True)
  Bar D: 16:00 → 20:00 (post-market — UNTRADEABLE, Standing Rejection)

Module 4 RTH-only: uses Bars B + C only.
Module 7 final-bar gate: Bar C (or early-close equivalent).

HARN-D-7: Data files are {TICKER}_data.csv with capitalized columns
(Datetime,Open,High,Low,Close,Volume,Ticker) — normalized on load.
Production reference: market-engine HEAD a673359, bars_4h_reconstructor.
"""
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "Fetched_Data"


def load_m5(ticker: str) -> pd.DataFrame:
    """Load M5 bars for ticker.

    Adapts from actual data files: {TICKER}_data.csv with columns
    Datetime,Open,High,Low,Close,Volume,Ticker → normalizes to
    date,open,high,low,close,volume (tz-naive ET).

    HARN-D-7: File naming differs from spec assumption ({TICKER}_m5_extended.csv).
    """
    path = DATA_ROOT / f"{ticker}_data.csv"
    if not path.exists():
        raise FileNotFoundError(f"M5 file not found: {path}")
    df = pd.read_csv(path)
    df = df.rename(
        columns={
            "Datetime": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    df["date"] = pd.to_datetime(df["date"])
    # Drop ticker column if present (not needed downstream)
    if "Ticker" in df.columns:
        df = df.drop(columns=["Ticker"])
    return df.sort_values("date").reset_index(drop=True)


def reconstruct_4h(m5_df: pd.DataFrame, ticker: str, rth_only: bool = True) -> pd.DataFrame:
    """Resample M5 to 4H bars per session.

    Returns DataFrame with columns:
    timestamp_et (str HH:MM), bar_label ('A'/'B'/'C'/'D'), open, high, low,
    close, volume, ticker, date_et (date), is_final_session_bar (bool).
    """
    from scripts._production_mirror.nyse_calendar import get_session_mode, get_early_close_et

    if m5_df.empty:
        return pd.DataFrame()

    out_rows = []
    m5_df = m5_df.copy()
    m5_df["date_et"] = m5_df["date"].dt.date

    for trading_day, day_bars in m5_df.groupby("date_et"):
        session_mode = get_session_mode(trading_day)
        if session_mode is None:
            continue  # non-trading day per NYSE calendar

        early_close = get_early_close_et(trading_day) if session_mode == "early_close" else None

        # Define bar boundaries (label, start_h, start_m, end_h, end_m)
        if early_close:
            ec_h, ec_m = map(int, early_close.split(":"))
            if ec_h > 13 or (ec_h == 13 and ec_m > 30):
                bars_def = [
                    ("A", 4, 0, 9, 30),
                    ("B", 9, 30, 13, 30),
                    ("C", 13, 30, ec_h, ec_m),
                ]
            else:
                bars_def = [
                    ("A", 4, 0, 9, 30),
                    ("B", 9, 30, ec_h, ec_m),
                ]
        else:
            bars_def = [
                ("A", 4, 0, 9, 30),
                ("B", 9, 30, 13, 30),
                ("C", 13, 30, 16, 0),
                ("D", 16, 0, 20, 0),
            ]

        if rth_only:
            bars_def = [b for b in bars_def if b[0] in ("B", "C")]

        if not bars_def:
            continue

        final_label = bars_def[-1][0]

        for label, sh, sm, eh, em in bars_def:
            start_ts = datetime(
                trading_day.year, trading_day.month, trading_day.day, sh, sm
            )
            end_ts = datetime(
                trading_day.year, trading_day.month, trading_day.day, eh, em
            )

            window = day_bars[
                (day_bars["date"] >= start_ts) & (day_bars["date"] < end_ts)
            ]
            if window.empty:
                continue

            out_rows.append(
                {
                    "timestamp_et": start_ts.strftime("%H:%M"),
                    "bar_label": label,
                    "ticker": ticker,
                    "date_et": trading_day,
                    "open": float(window.iloc[0]["open"]),
                    "high": float(window["high"].max()),
                    "low": float(window["low"].min()),
                    "close": float(window.iloc[-1]["close"]),
                    "volume": int(window["volume"].sum()),
                    "is_final_session_bar": (label == final_label),
                }
            )

    return pd.DataFrame(out_rows)


def get_daily_close_from_m5(m5_df: pd.DataFrame, d: date) -> Optional[float]:
    """Last M5 close of trading day (production _get_daily_close equivalent).
    Production reference: module7.py:499-513."""
    day_bars = m5_df[m5_df["date"].dt.date == d]
    if day_bars.empty:
        return None
    return float(day_bars.iloc[-1]["close"])
