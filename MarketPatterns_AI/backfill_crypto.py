#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Crypto Historical Data Backfill Script

Downloads 12 months of M5 OHLCV data for ETH and BTC.
Primary source: Alpha Vantage CRYPTO_INTRADAY with month parameter.
Fallback source: Binance public klines API (no key needed).

Output format matches existing equity CSVs:
  Datetime,Open,High,Low,Close,Volume,Ticker

Usage:
  python backfill_crypto.py                    # Auto-detect best source
  python backfill_crypto.py --source av        # Force Alpha Vantage
  python backfill_crypto.py --source binance   # Force Binance
  python backfill_crypto.py --dry-run          # Test API without saving
"""

import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
DATA_DIR = os.path.join(SCRIPT_DIR, "Fetched_Data")
BACKUP_DIR = os.path.join(DATA_DIR, "backup_crypto")

TICKERS = ["ETH", "BTC"]

# 12 months ending March 2026
MONTHS = [
    "2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09",
    "2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03",
]

# Binance symbol mapping
BINANCE_SYMBOLS = {"ETH": "ETHUSDT", "BTC": "BTCUSDT"}

# Rate limiting
AV_DELAY_SECONDS = 15        # Alpha Vantage: conservative delay between calls
BINANCE_DELAY_SECONDS = 0.5  # Binance: generous limit (1200 req/min allowed)
BINANCE_KLINE_LIMIT = 1000   # Max candles per Binance request

# Timezone for output (matching equity data — config says Asia/Jerusalem but
# equity timestamps appear to use US Eastern based on market hours)
# We detect from existing data; default to US/Eastern if undetermined.
OUTPUT_TZ = None  # Will be set after inspecting existing data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(DATA_DIR, "backfill_crypto.log"), mode="a"),
    ],
)
logger = logging.getLogger("backfill_crypto")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_api_key():
    """Load Alpha Vantage API key from config.json or environment."""
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if api_key:
        return api_key
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        api_key = config.get("alpha_vantage_api_key")
        if api_key:
            return api_key
    logger.error("No API key found. Set ALPHA_VANTAGE_API_KEY env var or add to config.json.")
    sys.exit(1)


def detect_timezone_from_existing():
    """Inspect an existing equity CSV to determine output timezone."""
    global OUTPUT_TZ
    sample_file = os.path.join(DATA_DIR, "NVDA_data.csv")
    if not os.path.exists(sample_file):
        # Try any *_data.csv
        for f in os.listdir(DATA_DIR):
            if f.endswith("_data.csv"):
                sample_file = os.path.join(DATA_DIR, f)
                break

    if os.path.exists(sample_file):
        df = pd.read_csv(sample_file, nrows=5)
        if "Datetime" in df.columns:
            # The equity data starts at 04:00 for pre-market (US Eastern) or
            # 11:00 which is Israel time for US 04:00 ET.
            # NVDA first row: 2025-02-10 11:00:00 — this is Asia/Jerusalem
            first_dt = df["Datetime"].iloc[0]
            hour = int(first_dt.split(" ")[1].split(":")[0])
            if hour >= 10:
                OUTPUT_TZ = "Asia/Jerusalem"
                logger.info(f"Detected timezone: Asia/Jerusalem (first hour={hour})")
            else:
                OUTPUT_TZ = "US/Eastern"
                logger.info(f"Detected timezone: US/Eastern (first hour={hour})")
            return

    OUTPUT_TZ = "US/Eastern"
    logger.info("No existing data found, defaulting to US/Eastern timezone.")


def backup_existing(ticker):
    """Backup existing crypto CSV before overwriting."""
    src = os.path.join(DATA_DIR, f"{ticker}_crypto_data.csv")
    if os.path.exists(src):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = os.path.join(BACKUP_DIR, f"{ticker}_crypto_data_{ts}.csv")
        import shutil
        shutil.copy2(src, dst)
        logger.info(f"Backed up {src} -> {dst}")


# ---------------------------------------------------------------------------
# Alpha Vantage source
# ---------------------------------------------------------------------------

def test_av_month_param(api_key):
    """Test if Alpha Vantage CRYPTO_INTRADAY supports the month parameter."""
    logger.info("Testing Alpha Vantage CRYPTO_INTRADAY with month parameter...")
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "CRYPTO_INTRADAY",
        "symbol": "ETH",
        "market": "USD",
        "interval": "5min",
        "outputsize": "full",
        "month": "2025-09",
        "apikey": api_key,
    }

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if "Error Message" in data or "Note" in data:
            logger.warning(f"AV returned error/note: {data.get('Error Message', data.get('Note', ''))}")
            return False, None

        # Look for time series key
        ts_key = None
        for key in data:
            if "Time Series" in key:
                ts_key = key
                break

        if ts_key and len(data[ts_key]) > 0:
            count = len(data[ts_key])
            logger.info(f"AV month parameter WORKS! Got {count} data points for ETH 2025-09.")
            return True, data
        else:
            logger.warning(f"AV month parameter returned no time series data. Keys: {list(data.keys())}")
            return False, data

    except requests.exceptions.RequestException as e:
        logger.warning(f"AV request failed: {e}")
        return False, None


def fetch_av_month(ticker, month, api_key):
    """Fetch one month of 5min crypto data from Alpha Vantage."""
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "CRYPTO_INTRADAY",
        "symbol": ticker,
        "market": "USD",
        "interval": "5min",
        "outputsize": "full",
        "month": month,
        "apikey": api_key,
    }

    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, timeout=60)
            resp.raise_for_status()
            data = resp.json()

            # Check for rate limit note
            if "Note" in data:
                logger.warning(f"Rate limited on {ticker} {month}, waiting 60s...")
                time.sleep(60)
                continue

            if "Error Message" in data:
                logger.error(f"AV error for {ticker} {month}: {data['Error Message']}")
                return pd.DataFrame()

            # Find time series key
            ts_key = None
            for key in data:
                if "Time Series" in key:
                    ts_key = key
                    break

            if not ts_key:
                logger.error(f"No time series key in response for {ticker} {month}")
                return pd.DataFrame()

            rows = []
            for dt_str, values in data[ts_key].items():
                rows.append({
                    "Datetime": dt_str,
                    "Open": float(values.get("1. open", 0)),
                    "High": float(values.get("2. high", 0)),
                    "Low": float(values.get("3. low", 0)),
                    "Close": float(values.get("4. close", 0)),
                    "Volume": float(values.get("5. volume", 0)),
                    "Ticker": ticker,
                })

            df = pd.DataFrame(rows)
            if not df.empty:
                df["Datetime"] = pd.to_datetime(df["Datetime"])
                # Convert timezone if needed
                if OUTPUT_TZ and OUTPUT_TZ != "UTC":
                    import pytz
                    utc = pytz.UTC
                    target_tz = pytz.timezone(OUTPUT_TZ)
                    df["Datetime"] = df["Datetime"].dt.tz_localize(utc).dt.tz_convert(target_tz).dt.tz_localize(None)
                df = df.sort_values("Datetime").reset_index(drop=True)

            return df

        except requests.exceptions.RequestException as e:
            logger.warning(f"Attempt {attempt + 1}/3 failed for {ticker} {month}: {e}")
            time.sleep(5 * (attempt + 1))

    return pd.DataFrame()


def backfill_av(api_key):
    """Backfill all tickers using Alpha Vantage."""
    results = {}
    for ticker in TICKERS:
        logger.info(f"\n{'='*60}")
        logger.info(f"Backfilling {ticker} via Alpha Vantage")
        logger.info(f"{'='*60}")

        all_dfs = []
        for month in MONTHS:
            logger.info(f"  Fetching {ticker} {month}...")
            df = fetch_av_month(ticker, month, api_key)
            if not df.empty:
                logger.info(f"  {ticker} {month}: {len(df)} rows "
                            f"({df['Datetime'].min()} to {df['Datetime'].max()})")
                all_dfs.append(df)
            else:
                logger.warning(f"  {ticker} {month}: NO DATA")
            time.sleep(AV_DELAY_SECONDS)

        if all_dfs:
            results[ticker] = pd.concat(all_dfs, ignore_index=True)
        else:
            results[ticker] = pd.DataFrame()

    return results


# ---------------------------------------------------------------------------
# Binance source
# ---------------------------------------------------------------------------

def fetch_binance_klines(symbol, interval, start_ms, end_ms):
    """Fetch klines from Binance public API with pagination."""
    url = "https://api.binance.com/api/v3/klines"
    all_rows = []
    current_start = start_ms

    while current_start < end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "endTime": end_ms,
            "limit": BINANCE_KLINE_LIMIT,
        }

        for attempt in range(4):
            try:
                resp = requests.get(url, params=params, timeout=30)
                resp.raise_for_status()
                klines = resp.json()
                break
            except requests.exceptions.RequestException as e:
                wait = 2 ** (attempt + 1)
                logger.warning(f"Binance request failed (attempt {attempt + 1}/4): {e}. Retrying in {wait}s...")
                time.sleep(wait)
        else:
            logger.error(f"Binance request failed after 4 attempts for {symbol} at {current_start}")
            break

        if not klines:
            break

        for k in klines:
            # k = [open_time, open, high, low, close, volume, close_time, ...]
            all_rows.append({
                "open_time_ms": int(k[0]),
                "Open": float(k[1]),
                "High": float(k[2]),
                "Low": float(k[3]),
                "Close": float(k[4]),
                "Volume": float(k[5]),
            })

        # Advance start to after the last candle
        last_close_time = int(klines[-1][6])
        current_start = last_close_time + 1

        if len(klines) < BINANCE_KLINE_LIMIT:
            break  # No more data

        time.sleep(BINANCE_DELAY_SECONDS)

    return all_rows


def backfill_binance():
    """Backfill all tickers using Binance."""
    import pytz

    # Date range: 12 months ending now
    start_dt = datetime(2025, 4, 1, tzinfo=timezone.utc)
    end_dt = datetime(2026, 3, 16, 23, 59, 59, tzinfo=timezone.utc)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    target_tz = pytz.timezone(OUTPUT_TZ) if OUTPUT_TZ else pytz.UTC

    results = {}
    for ticker in TICKERS:
        symbol = BINANCE_SYMBOLS[ticker]
        logger.info(f"\n{'='*60}")
        logger.info(f"Backfilling {ticker} ({symbol}) via Binance")
        logger.info(f"{'='*60}")

        rows = fetch_binance_klines(symbol, "5m", start_ms, end_ms)
        logger.info(f"  Downloaded {len(rows)} raw candles for {ticker}")

        if not rows:
            results[ticker] = pd.DataFrame()
            continue

        df = pd.DataFrame(rows)

        # Convert open_time_ms to datetime
        df["Datetime"] = pd.to_datetime(df["open_time_ms"], unit="ms", utc=True)

        # Convert to target timezone
        df["Datetime"] = df["Datetime"].dt.tz_convert(target_tz).dt.tz_localize(None)

        # Format to match existing CSV style
        df["Datetime"] = df["Datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
        df["Ticker"] = ticker

        df = df[["Datetime", "Open", "High", "Low", "Close", "Volume", "Ticker"]]
        df = df.sort_values("Datetime").reset_index(drop=True)

        results[ticker] = df
        logger.info(f"  {ticker}: {len(df)} rows ({df['Datetime'].iloc[0]} to {df['Datetime'].iloc[-1]})")

    return results


# ---------------------------------------------------------------------------
# Merge & save
# ---------------------------------------------------------------------------

def merge_and_save(results):
    """Merge new data with existing, deduplicate, sort, and save."""
    os.makedirs(DATA_DIR, exist_ok=True)

    for ticker, new_df in results.items():
        if new_df.empty:
            logger.warning(f"No data for {ticker}, skipping save.")
            continue

        file_path = os.path.join(DATA_DIR, f"{ticker}_crypto_data.csv")

        # Backup existing
        backup_existing(ticker)

        # Load existing data if present
        existing_df = pd.DataFrame()
        if os.path.exists(file_path):
            existing_df = pd.read_csv(file_path)
            logger.info(f"{ticker}: Existing file has {len(existing_df)} rows")

        # Ensure consistent Datetime format
        new_df["Datetime"] = pd.to_datetime(new_df["Datetime"]).dt.strftime("%Y-%m-%d %H:%M:%S")

        if not existing_df.empty:
            existing_df["Datetime"] = pd.to_datetime(existing_df["Datetime"]).dt.strftime("%Y-%m-%d %H:%M:%S")

        # Merge
        if not existing_df.empty:
            combined = pd.concat([existing_df, new_df], ignore_index=True)
        else:
            combined = new_df.copy()

        # Deduplicate by Datetime
        before_dedup = len(combined)
        combined = combined.drop_duplicates(subset=["Datetime"], keep="last")
        dupes_removed = before_dedup - len(combined)

        # Sort by Datetime ascending
        combined["Datetime"] = pd.to_datetime(combined["Datetime"])
        combined = combined.sort_values("Datetime").reset_index(drop=True)
        combined["Datetime"] = combined["Datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")

        # Ensure correct column order
        combined = combined[["Datetime", "Open", "High", "Low", "Close", "Volume", "Ticker"]]

        # Save
        combined.to_csv(file_path, index=False)

        logger.info(
            f"{ticker}: Saved {len(combined)} rows to {file_path} "
            f"(new: {len(new_df)}, dupes removed: {dupes_removed}, "
            f"range: {combined['Datetime'].iloc[0]} to {combined['Datetime'].iloc[-1]})"
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_data(results):
    """Run validation checks on backfilled data."""
    logger.info(f"\n{'='*60}")
    logger.info("VALIDATION")
    logger.info(f"{'='*60}")

    all_ok = True

    for ticker, df in results.items():
        if df.empty:
            logger.error(f"{ticker}: NO DATA — validation skipped")
            all_ok = False
            continue

        logger.info(f"\n--- {ticker} ---")
        logger.info(f"  Rows: {len(df)}")

        df_val = df.copy()
        df_val["Datetime"] = pd.to_datetime(df_val["Datetime"])
        df_val = df_val.sort_values("Datetime").reset_index(drop=True)

        # 1. Row count sanity
        expected_approx = 8640 * 12  # ~103,680 for 24/7 crypto
        ratio = len(df_val) / expected_approx
        logger.info(f"  Expected ~{expected_approx}, got {len(df_val)} ({ratio:.1%})")
        if ratio < 0.5:
            logger.warning(f"  WARNING: Row count is less than 50% of expected!")

        # 2. Date range
        logger.info(f"  Date range: {df_val['Datetime'].min()} to {df_val['Datetime'].max()}")

        # 3. Gap detection (>10 min)
        df_val["time_diff"] = df_val["Datetime"].diff()
        gaps = df_val[df_val["time_diff"] > timedelta(minutes=10)]
        if len(gaps) > 0:
            logger.info(f"  Gaps > 10min: {len(gaps)} found")
            # Show top 5 largest
            top_gaps = gaps.nlargest(5, "time_diff")
            for _, row in top_gaps.iterrows():
                logger.info(f"    {row['Datetime']} — gap of {row['time_diff']}")
        else:
            logger.info(f"  Gaps > 10min: none")

        # 4. OHLC integrity
        ohlc_issues = 0
        high_ok = (df_val["High"] >= df_val[["Open", "Close"]].max(axis=1)).all()
        low_ok = (df_val["Low"] <= df_val[["Open", "Close"]].min(axis=1)).all()
        vol_ok = (df_val["Volume"] >= 0).all()
        nan_count = df_val[["Open", "High", "Low", "Close", "Volume"]].isna().sum().sum()

        if not high_ok:
            ohlc_issues += 1
            logger.warning(f"  OHLC: High < max(Open, Close) found!")
        if not low_ok:
            ohlc_issues += 1
            logger.warning(f"  OHLC: Low > min(Open, Close) found!")
        if not vol_ok:
            ohlc_issues += 1
            logger.warning(f"  OHLC: Negative volume found!")
        if nan_count > 0:
            ohlc_issues += 1
            logger.warning(f"  OHLC: {nan_count} NaN values found!")
        if ohlc_issues == 0:
            logger.info(f"  OHLC integrity: PASS")

        # 5. Duplicate check
        dupe_count = df_val.duplicated(subset=["Datetime"]).sum()
        if dupe_count > 0:
            logger.warning(f"  Duplicates: {dupe_count} duplicate timestamps!")
            all_ok = False
        else:
            logger.info(f"  Duplicates: none")

        # 6. Format check — reload from saved file
        file_path = os.path.join(DATA_DIR, f"{ticker}_crypto_data.csv")
        if os.path.exists(file_path):
            reloaded = pd.read_csv(file_path)
            logger.info(f"  Reloaded from file: {len(reloaded)} rows")
            logger.info(f"  Columns: {list(reloaded.columns)}")
            logger.info(f"  First 3 rows:")
            for _, row in reloaded.head(3).iterrows():
                logger.info(f"    {row.to_dict()}")
            logger.info(f"  Last 3 rows:")
            for _, row in reloaded.tail(3).iterrows():
                logger.info(f"    {row.to_dict()}")

            # Compare with equity format
            equity_file = os.path.join(DATA_DIR, "NVDA_data.csv")
            if os.path.exists(equity_file):
                equity_df = pd.read_csv(equity_file, nrows=1)
                if list(equity_df.columns) == list(reloaded.columns):
                    logger.info(f"  Format match with equity data: PASS")
                else:
                    logger.warning(f"  Format mismatch! Equity: {list(equity_df.columns)}, Crypto: {list(reloaded.columns)}")
                    all_ok = False

    return all_ok


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------

def print_summary(results, source):
    """Print final summary report."""
    logger.info(f"\n{'='*60}")
    logger.info("SUMMARY REPORT")
    logger.info(f"{'='*60}")
    logger.info(f"Source: {source}")

    ready = True
    for ticker in TICKERS:
        df = results.get(ticker, pd.DataFrame())
        file_path = os.path.join(DATA_DIR, f"{ticker}_crypto_data.csv")
        file_size = os.path.getsize(file_path) / (1024 * 1024) if os.path.exists(file_path) else 0

        if df.empty:
            logger.info(f"\n{ticker}: NO DATA")
            ready = False
        else:
            df_dt = df.copy()
            df_dt["Datetime"] = pd.to_datetime(df_dt["Datetime"])
            logger.info(f"\n{ticker}:")
            logger.info(f"  Date range: {df_dt['Datetime'].min()} to {df_dt['Datetime'].max()}")
            logger.info(f"  Total rows: {len(df)}")
            logger.info(f"  File size:  {file_size:.1f} MB")

    logger.info(f"\nReady for Chandelier Exit backtest: {'YES' if ready else 'NO'}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Backfill crypto M5 OHLCV data")
    parser.add_argument("--source", choices=["av", "binance", "auto"], default="auto",
                        help="Data source (default: auto-detect)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Test API connectivity without saving")
    args = parser.parse_args()

    logger.info("Crypto Backfill Script Started")
    logger.info(f"Data directory: {DATA_DIR}")

    # Detect timezone from existing data
    detect_timezone_from_existing()
    logger.info(f"Output timezone: {OUTPUT_TZ}")

    api_key = load_api_key()
    source_used = None
    results = {}

    if args.source == "auto":
        # Test Alpha Vantage first
        av_works, _ = test_av_month_param(api_key)
        if av_works:
            logger.info("Alpha Vantage month parameter works! Using AV source.")
            source_used = "Alpha Vantage (CRYPTO_INTRADAY with month)"
            results = backfill_av(api_key)
        else:
            logger.info("Alpha Vantage month parameter not supported. Falling back to Binance.")
            source_used = "Binance (public klines API)"
            results = backfill_binance()
    elif args.source == "av":
        source_used = "Alpha Vantage (CRYPTO_INTRADAY with month)"
        results = backfill_av(api_key)
    elif args.source == "binance":
        source_used = "Binance (public klines API)"
        results = backfill_binance()

    if args.dry_run:
        logger.info("\n--- DRY RUN — Not saving ---")
        for ticker, df in results.items():
            if not df.empty:
                logger.info(f"{ticker}: {len(df)} rows, {df['Datetime'].iloc[0]} to {df['Datetime'].iloc[-1]}")
            else:
                logger.info(f"{ticker}: NO DATA")
        return

    # Save
    merge_and_save(results)

    # Validate
    validate_data(results)

    # Summary
    print_summary(results, source_used)


if __name__ == "__main__":
    main()
