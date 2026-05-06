"""Canonical data loader for backtest harness.

Single source of truth for ALL static data file paths and schemas in the
production-mirror layer. Other mirror modules MUST import from here, never
read CSVs/JSONs directly.

Closes HARN-D-7/8/9 from Backtest Harness v1.0:
  - HARN-D-7: standardizes on `{TICKER}_data.csv` naming (not `_m5_extended.csv`)
  - HARN-D-8: VIX is `VIX_daily.csv` ONLY. Hard-rejects VXVCLS.csv with explicit
    error explaining VIX (30-day) vs VIX3M (3-month) semantic difference
  - HARN-D-9: earnings auto-detects CSV vs JSON format

References:
  - Operator-verified Day 47 (Notepad inspection): VIX_daily.csv schema
    `date,vix_close`, values 17.28-22.00 (canonical VIX 30-day index)
  - VXVCLS.csv schema `observation_date,VXVCLS`, values 20-24 (VIX3M, 3-month
    forward) — DIFFERENT INDEX, must NOT be silently substituted for VIX

HARN11-D-4 (deviation): VIX_daily.csv was created from VIXCLS_FRED_real.csv
  (284 rows, 2025-02-10 to 2026-03-12) since operator data verified on Day 47
  covers recent period. Full 5yr VIX fetch: see curl command in FileNotFoundError.
"""
from pathlib import Path
from typing import Optional
import json
import pandas as pd

DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "Fetched_Data"

# ── VIX ─────────────────────────────────────────────────────────────────────
VIX_CANONICAL_PATH = DATA_ROOT / "VIX_daily.csv"
VIX_REJECTED_PATHS = [
    DATA_ROOT / "VXVCLS.csv",              # VIX3M, NOT VIX
    DATA_ROOT / "VXVCLS_FRED_real.csv",    # VIX3M variant
    DATA_ROOT / "VIX_daily_fmp_full.csv",  # synthetic, marked "not canonical" in EBS-1 setup
]


def load_vix(path: Optional[Path] = None) -> pd.DataFrame:
    """Load canonical VIX (30-day, FRED VIXCLS) from VIX_daily.csv.

    Hard-rejects VXVCLS.csv and other VIX3M files even if explicitly passed
    as path argument. This is intentional to prevent silent semantic drift
    that broke harness validation Day 43-47.

    Args:
        path: Optional override path. If None, uses VIX_CANONICAL_PATH.
            If path matches a known VIX3M file, raises ValueError.

    Returns:
        DataFrame with schema: date (datetime64), vix_close (float).
        Sorted ascending by date.

    Raises:
        ValueError: if path resolves to a known VIX3M file.
        FileNotFoundError: if canonical VIX_daily.csv missing.
    """
    target = path if path else VIX_CANONICAL_PATH
    target = Path(target).resolve()

    # Hard-reject VIX3M paths even if user-supplied
    for rejected in VIX_REJECTED_PATHS:
        if target == rejected.resolve():
            raise ValueError(
                f"Refusing to load {target.name} as VIX. "
                f"This file contains VIX3M (3-month forward index, FRED VXVCLS), "
                f"NOT VIX (30-day index, FRED VIXCLS). "
                f"Loader silently substituted in Backtest Harness v1.0 Day 43, "
                f"causing M4 N=4 vs canonical N=47. "
                f"Use VIX_daily.csv (FRED VIXCLS) only. "
                f"To re-fetch: curl https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS"
            )

    if not target.exists():
        raise FileNotFoundError(
            f"VIX file not found: {target}. "
            f"Expected canonical path: {VIX_CANONICAL_PATH}. "
            f"To fetch: curl -o Fetched_Data/VIX_daily.csv "
            f"https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS"
        )

    df = pd.read_csv(target)

    # Normalize schema: accept either {date, vix_close} or raw FRED {observation_date, VIXCLS}
    if "observation_date" in df.columns and "VIXCLS" in df.columns:
        df = df.rename(columns={"observation_date": "date", "VIXCLS": "vix_close"})

    if "date" not in df.columns or "vix_close" not in df.columns:
        raise ValueError(
            f"VIX file {target.name} has unexpected schema {list(df.columns)}. "
            f"Expected: date, vix_close (or raw FRED: observation_date, VIXCLS)."
        )

    # Filter NaN/empty rows (FRED uses '.' for missing values).
    df["vix_close"] = pd.to_numeric(df["vix_close"], errors="coerce")
    df = df.dropna(subset=["vix_close"]).reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    if len(df) < 100:
        raise ValueError(
            f"VIX file {target.name} has only {len(df)} rows after parsing. "
            f"Expected >100 for usable backtest. File may be empty or malformed."
        )

    return df


# ── Earnings calendar ───────────────────────────────────────────────────────
EARNINGS_CSV_PATH = DATA_ROOT / "earnings_calendar.csv"
EARNINGS_JSON_PATH = DATA_ROOT / "earnings_calendar.json"


def load_earnings() -> pd.DataFrame:
    """Load earnings calendar, auto-detecting CSV vs JSON format.

    Tries CSV first (legacy from EBS-1 setup), falls back to JSON
    (current FMP fetcher output Day 47).

    Returns:
        DataFrame with normalized schema:
            ticker (str), earnings_date (datetime64)
        Sorted ascending by earnings_date.

    Raises:
        FileNotFoundError: if neither CSV nor JSON present.
        ValueError: if file present but schema unrecognized.
    """
    if EARNINGS_CSV_PATH.exists():
        df = pd.read_csv(EARNINGS_CSV_PATH)
        # Existing EBS-1 CSV schema
        if "earnings_date" in df.columns and "ticker" in df.columns:
            df["earnings_date"] = pd.to_datetime(df["earnings_date"])
            return df.sort_values("earnings_date").reset_index(drop=True)
        # Alternate schema from raw FMP fetch (eps_estimate etc.)
        if "earnings_date" in df.columns and "symbol" in df.columns:
            df = df.rename(columns={"symbol": "ticker"})
            df["earnings_date"] = pd.to_datetime(df["earnings_date"])
            return df.sort_values("earnings_date").reset_index(drop=True)
        raise ValueError(
            f"earnings_calendar.csv has unexpected schema {list(df.columns)}. "
            f"Expected: earnings_date + (ticker OR symbol)."
        )

    if EARNINGS_JSON_PATH.exists():
        with open(EARNINGS_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError(
                f"earnings_calendar.json must be a JSON array of objects. "
                f"Got type {type(data).__name__}."
            )

        df = pd.DataFrame(data)
        # FMP JSON schema: [{"symbol": "AAPL", "date": "2020-01-28"}, ...]
        if "symbol" in df.columns and "date" in df.columns:
            df = df.rename(columns={"symbol": "ticker", "date": "earnings_date"})
        elif "ticker" in df.columns and "earnings_date" in df.columns:
            pass  # already normalized
        else:
            raise ValueError(
                f"earnings_calendar.json has unexpected schema {list(df.columns)}. "
                f"Expected: [(symbol, date)] or [(ticker, earnings_date)]."
            )

        df["earnings_date"] = pd.to_datetime(df["earnings_date"])
        return df.sort_values("earnings_date").reset_index(drop=True)

    raise FileNotFoundError(
        f"No earnings calendar found. Expected one of:\n"
        f"  {EARNINGS_CSV_PATH}\n"
        f"  {EARNINGS_JSON_PATH}\n"
        f"To regenerate JSON: python utils/fmp_earnings_fetcher.py backfill"
    )


# ── M5 OHLCV bars ───────────────────────────────────────────────────────────
def m5_bars_path(ticker: str) -> Path:
    """Resolve canonical path for M5 OHLCV bars CSV.

    Day 47 verified naming: `{TICKER}_data.csv` (HARN-D-7).
    Schema: date,open,high,low,close,volume (date is tz-naive ET).
    """
    return DATA_ROOT / f"{ticker}_data.csv"


def load_m5_bars(ticker: str) -> pd.DataFrame:
    """Load M5 bars for a ticker. Schema: date,open,high,low,close,volume.

    Normalizes from actual file schema (Datetime,Open,High,Low,Close,Volume,Ticker)
    to lowercase canonical schema per HARN-D-7.
    """
    path = m5_bars_path(ticker)
    if not path.exists():
        raise FileNotFoundError(f"M5 bars not found for {ticker}: {path}")
    df = pd.read_csv(path)
    # Normalize capitalized columns from actual data files (HARN-D-7)
    df = df.rename(columns={
        "Datetime": "date", "Open": "open", "High": "high",
        "Low": "low", "Close": "close", "Volume": "volume",
    })
    df["date"] = pd.to_datetime(df["date"])
    return df
