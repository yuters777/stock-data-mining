#!/usr/bin/env python3
"""
Crypto Historical Data Backfill Script

Downloads 12 months of M5 OHLCV data for ETH and BTC, formatted identically
to existing equity CSV files. Supports two data sources:
  1. Alpha Vantage CRYPTO_INTRADAY (primary) - uses month parameter
  2. Binance public klines API (fallback) - no API key needed

Output format matches existing equity CSVs:
  Columns: Datetime, Open, High, Low, Close, Volume, Ticker
  Datetime format: YYYY-MM-DD HH:MM:SS (US Eastern time)
  Sorted ascending by Datetime, no index column.

Usage:
  python backfill_crypto.py                          # Auto-detect best source
  python backfill_crypto.py --source alphavantage    # Force Alpha Vantage
  python backfill_crypto.py --source binance         # Force Binance
  python backfill_crypto.py --tickers ETH            # Single ticker
  python backfill_crypto.py --data-dir ./data        # Custom output directory
"""

import os
import sys
import json
import time
import logging
import argparse
import shutil
from datetime import datetime, timedelta, timezone

import io
import zipfile

import requests
import pandas as pd
import pytz

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TICKERS = ["ETH", "BTC"]

# 12-month range: April 2025 through March 2026
MONTHS = [
    "2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09",
    "2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03",
]

AV_BASE_URL = "https://www.alphavantage.co/query"
BINANCE_BASE_URL = "https://api.binance.com/api/v3/klines"

EASTERN = pytz.timezone("America/New_York")

# CSV output format (must match equity files exactly)
CSV_COLUMNS = ["Datetime", "Open", "High", "Low", "Close", "Volume", "Ticker"]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("backfill_crypto.log"),
    ],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_api_key():
    """Get Alpha Vantage API key from environment or config.json."""
    key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if key:
        return key

    # Try config.json files in common locations
    for path in ["config.json", "MarketPatterns_AI/config.json"]:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    cfg = json.load(f)
                key = cfg.get("alpha_vantage_api_key")
                if key:
                    return key
            except (json.JSONDecodeError, KeyError):
                pass
    return None


def utc_to_eastern(dt):
    """Convert a UTC datetime to US Eastern."""
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(EASTERN).replace(tzinfo=None)


def backup_file(path):
    """Create a timestamped backup of a file if it exists."""
    if os.path.exists(path):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = f"{path}.backup_{ts}"
        shutil.copy2(path, backup)
        logger.info(f"Backed up {path} -> {backup}")
        return backup
    return None


# ---------------------------------------------------------------------------
# Alpha Vantage fetcher
# ---------------------------------------------------------------------------

def test_av_month_param(api_key):
    """Test whether AV CRYPTO_INTRADAY supports the month parameter."""
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
        resp = requests.get(AV_BASE_URL, params=params, timeout=30)
        data = resp.json()

        if "Error Message" in data or "Note" in data:
            logger.warning(f"AV month param test failed: {data.get('Error Message', data.get('Note', ''))}")
            return False

        ts_key = [k for k in data.keys() if "Time Series" in k]
        if ts_key and len(data[ts_key[0]]) > 0:
            count = len(data[ts_key[0]])
            logger.info(f"AV month param works! Got {count} bars for ETH 2025-09")
            return True

        logger.warning("AV month param returned no time series data")
        return False
    except Exception as e:
        logger.warning(f"AV month param test error: {e}")
        return False


def fetch_av_month(ticker, month, api_key, delay=15):
    """Fetch one month of M5 crypto data from Alpha Vantage."""
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
            resp = requests.get(AV_BASE_URL, params=params, timeout=60)
            data = resp.json()

            # Rate-limit / error handling
            if "Note" in data:
                logger.warning(f"AV rate limit hit for {ticker} {month}, waiting 60s...")
                time.sleep(60)
                continue
            if "Error Message" in data:
                logger.error(f"AV error for {ticker} {month}: {data['Error Message']}")
                return pd.DataFrame()

            # Parse time series
            ts_key = [k for k in data.keys() if "Time Series" in k]
            if not ts_key:
                logger.error(f"No time series key in AV response for {ticker} {month}")
                return pd.DataFrame()

            records = []
            for ts_str, bar in data[ts_key[0]].items():
                records.append({
                    "Datetime": ts_str,
                    "Open": float(bar.get("1. open", 0)),
                    "High": float(bar.get("2. high", 0)),
                    "Low": float(bar.get("3. low", 0)),
                    "Close": float(bar.get("4. close", 0)),
                    "Volume": float(bar.get("5. volume", 0)),
                    "Ticker": ticker,
                })

            df = pd.DataFrame(records)
            if not df.empty:
                df["Datetime"] = pd.to_datetime(df["Datetime"])
                df = df.sort_values("Datetime").reset_index(drop=True)

            logger.info(f"AV: {ticker} {month} -> {len(df)} bars")
            time.sleep(delay)
            return df

        except Exception as e:
            logger.error(f"AV fetch error for {ticker} {month} (attempt {attempt+1}): {e}")
            time.sleep(15 * (attempt + 1))

    return pd.DataFrame()


def fetch_all_av(tickers, months, api_key):
    """Fetch all months for all tickers via Alpha Vantage."""
    results = {}
    for ticker in tickers:
        all_dfs = []
        for month in months:
            df = fetch_av_month(ticker, month, api_key)
            if not df.empty:
                all_dfs.append(df)

        if all_dfs:
            results[ticker] = pd.concat(all_dfs, ignore_index=True)
            logger.info(f"AV total for {ticker}: {len(results[ticker])} bars")
        else:
            results[ticker] = pd.DataFrame()

    return results


# ---------------------------------------------------------------------------
# Binance fetcher
# ---------------------------------------------------------------------------

BINANCE_SYMBOL_MAP = {"ETH": "ETHUSDT", "BTC": "BTCUSDT"}


def fetch_binance_chunk(symbol, start_ms, end_ms, limit=1000):
    """Fetch a single chunk of klines from Binance."""
    params = {
        "symbol": symbol,
        "interval": "5m",
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": limit,
    }
    for attempt in range(3):
        try:
            resp = requests.get(BINANCE_BASE_URL, params=params, timeout=30)
            if resp.status_code == 429:
                logger.warning("Binance rate limit, waiting 10s...")
                time.sleep(10)
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Binance fetch error (attempt {attempt+1}): {e}")
            time.sleep(2 * (attempt + 1))
    return []


def fetch_binance_ticker(ticker, start_dt, end_dt):
    """Fetch full date range for one ticker from Binance, handling pagination."""
    symbol = BINANCE_SYMBOL_MAP.get(ticker)
    if not symbol:
        logger.error(f"No Binance symbol mapping for {ticker}")
        return pd.DataFrame()

    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    all_records = []
    current_start = start_ms
    chunk_step_ms = 1000 * 5 * 60 * 1000  # 1000 bars * 5 min in ms

    call_count = 0
    while current_start < end_ms:
        chunk_end = min(current_start + chunk_step_ms, end_ms)
        klines = fetch_binance_chunk(symbol, current_start, chunk_end)

        if not klines:
            # Move forward anyway to avoid infinite loop
            current_start = chunk_end + 1
            continue

        for k in klines:
            # k[0]=open_time, k[1]=open, k[2]=high, k[3]=low, k[4]=close, k[5]=volume
            open_time_utc = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
            et_time = utc_to_eastern(open_time_utc)
            all_records.append({
                "Datetime": et_time.strftime("%Y-%m-%d %H:%M:%S"),
                "Open": float(k[1]),
                "High": float(k[2]),
                "Low": float(k[3]),
                "Close": float(k[4]),
                "Volume": float(k[5]),
                "Ticker": ticker,
            })

        # Advance past the last kline we received
        last_open_ms = klines[-1][0]
        current_start = last_open_ms + (5 * 60 * 1000)  # next 5-min bar

        call_count += 1
        if call_count % 50 == 0:
            logger.info(f"Binance {ticker}: {call_count} API calls, {len(all_records)} bars so far...")
            time.sleep(1)  # gentle throttle

    df = pd.DataFrame(all_records)
    if not df.empty:
        df["Datetime"] = pd.to_datetime(df["Datetime"])
        df = df.sort_values("Datetime").reset_index(drop=True)

    logger.info(f"Binance total for {ticker}: {len(df)} bars from {call_count} API calls")
    return df


def fetch_all_binance(tickers, start_dt, end_dt):
    """Fetch all tickers via Binance API."""
    results = {}
    for ticker in tickers:
        df = fetch_binance_ticker(ticker, start_dt, end_dt)
        results[ticker] = df
    return results


# ---------------------------------------------------------------------------
# Binance Vision bulk download (geo-unrestricted)
# ---------------------------------------------------------------------------

VISION_BASE = "https://data.binance.vision/data/spot/monthly/klines"


def fetch_vision_month(symbol, year_month):
    """Download a single monthly klines ZIP from data.binance.vision."""
    url = f"{VISION_BASE}/{symbol}/5m/{symbol}-5m-{year_month}.zip"
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=60)
            if resp.status_code == 404:
                logger.warning(f"Vision: {url} not found (month may not be available yet)")
                return pd.DataFrame()
            resp.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                csv_name = zf.namelist()[0]
                with zf.open(csv_name) as f:
                    df = pd.read_csv(f, header=None, names=[
                        "open_time", "Open", "High", "Low", "Close", "Volume",
                        "close_time", "quote_volume", "count",
                        "taker_buy_volume", "taker_buy_quote_volume", "ignore"
                    ])
            logger.info(f"Vision: {symbol} {year_month} -> {len(df)} bars")
            return df
        except Exception as e:
            logger.error(f"Vision fetch error {symbol} {year_month} (attempt {attempt+1}): {e}")
            time.sleep(2 * (attempt + 1))
    return pd.DataFrame()


def fetch_all_vision(tickers, months):
    """Fetch all tickers using Binance Vision bulk downloads."""
    results = {}
    for ticker in tickers:
        symbol = BINANCE_SYMBOL_MAP.get(ticker)
        if not symbol:
            logger.error(f"No Binance symbol mapping for {ticker}")
            results[ticker] = pd.DataFrame()
            continue

        all_records = []
        for month in months:
            df = fetch_vision_month(symbol, month)
            if df.empty:
                continue
            # Auto-detect timestamp unit: ms (13 digits) vs us (16 digits)
            sample_ts = df["open_time"].iloc[0]
            if sample_ts > 1e15:  # microseconds
                ts_unit = "us"
            elif sample_ts > 1e12:  # milliseconds
                ts_unit = "ms"
            else:  # seconds
                ts_unit = "s"
            logger.info(f"Vision {symbol} {month}: open_time sample={sample_ts}, unit={ts_unit}")
            df["Datetime_utc"] = pd.to_datetime(df["open_time"], unit=ts_unit, utc=True)
            df["Datetime_et"] = df["Datetime_utc"].dt.tz_convert("America/New_York")
            for _, row in df.iterrows():
                all_records.append({
                    "Datetime": row["Datetime_et"].strftime("%Y-%m-%d %H:%M:%S"),
                    "Open": float(row["Open"]),
                    "High": float(row["High"]),
                    "Low": float(row["Low"]),
                    "Close": float(row["Close"]),
                    "Volume": float(row["Volume"]),
                    "Ticker": ticker,
                })

        result_df = pd.DataFrame(all_records)
        if not result_df.empty:
            result_df["Datetime"] = pd.to_datetime(result_df["Datetime"])
            result_df = result_df.sort_values("Datetime").reset_index(drop=True)

        logger.info(f"Vision total for {ticker}: {len(result_df)} bars from {len(months)} months")
        results[ticker] = result_df
    return results


# ---------------------------------------------------------------------------
# CryptoCompare fetcher (US-accessible, no API key for basic usage)
# ---------------------------------------------------------------------------

CRYPTOCOMPARE_BASE = "https://min-api.cryptocompare.com/data/v2/histominute"


def fetch_cryptocompare_chunk(fsym, toTs, limit=2000):
    """Fetch a chunk of minute-level OHLCV from CryptoCompare."""
    params = {"fsym": fsym, "tsym": "USDT", "limit": limit, "toTs": toTs}
    for attempt in range(3):
        try:
            resp = requests.get(CRYPTOCOMPARE_BASE, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("Response") == "Error":
                logger.error(f"CryptoCompare error: {data.get('Message', 'unknown')}")
                return []
            return data.get("Data", {}).get("Data", [])
        except Exception as e:
            logger.error(f"CryptoCompare fetch error (attempt {attempt+1}): {e}")
            time.sleep(2 * (attempt + 1))
    return []


def fetch_all_cryptocompare(tickers, months):
    """Fetch all tickers using CryptoCompare histominute API.

    CryptoCompare provides 1-minute data. We resample to 5-minute bars.
    Each call returns up to 2000 minutes (~33 hours). For 12 months we need ~265 calls per ticker.
    """
    results = {}
    for ticker in tickers:
        logger.info(f"CryptoCompare: fetching {ticker}...")

        # Parse month range to get timestamps
        start_dt = datetime(int(months[0][:4]), int(months[0][5:]), 1, tzinfo=timezone.utc)
        end_year, end_month_num = int(months[-1][:4]), int(months[-1][5:])
        if end_month_num == 12:
            end_dt = datetime(end_year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end_dt = datetime(end_year, end_month_num + 1, 1, tzinfo=timezone.utc)
        now_utc = datetime.now(timezone.utc)
        if end_dt > now_utc:
            end_dt = now_utc

        start_ts = int(start_dt.timestamp())
        end_ts = int(end_dt.timestamp())
        current_to = end_ts

        all_records = []
        call_count = 0

        while current_to > start_ts:
            data = fetch_cryptocompare_chunk(ticker, current_to, limit=2000)
            call_count += 1

            if not data:
                logger.warning(f"CryptoCompare: no data for {ticker} at ts={current_to}")
                break

            for bar in data:
                ts = bar.get("time", 0)
                if ts < start_ts or ts > end_ts:
                    continue
                if bar.get("volumeto", 0) == 0 and bar.get("close", 0) == 0:
                    continue
                open_time_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
                et_time = utc_to_eastern(open_time_utc)
                all_records.append({
                    "Datetime": et_time,
                    "Open": float(bar["open"]),
                    "High": float(bar["high"]),
                    "Low": float(bar["low"]),
                    "Close": float(bar["close"]),
                    "Volume": float(bar.get("volumeto", 0)),
                    "Ticker": ticker,
                })

            # Move backward
            earliest_ts = min(bar.get("time", current_to) for bar in data)
            if earliest_ts >= current_to:
                break
            current_to = earliest_ts - 1

            if call_count % 20 == 0:
                logger.info(f"CryptoCompare {ticker}: {call_count} calls, {len(all_records)} bars")
                time.sleep(1)

        # Resample 1-min bars to 5-min
        if all_records:
            df_1m = pd.DataFrame(all_records)
            df_1m["Datetime"] = pd.to_datetime(df_1m["Datetime"])
            df_1m = df_1m.set_index("Datetime").sort_index()

            df_5m = df_1m.resample("5min").agg({
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
                "Ticker": "first",
            }).dropna(subset=["Open"])

            df_5m = df_5m.reset_index()
            logger.info(f"CryptoCompare {ticker}: {len(df_1m)} 1m bars -> {len(df_5m)} 5m bars "
                        f"from {call_count} API calls")
            results[ticker] = df_5m
        else:
            logger.warning(f"CryptoCompare: no data for {ticker}")
            results[ticker] = pd.DataFrame()

    return results


# ---------------------------------------------------------------------------
# Merge, deduplicate, validate
# ---------------------------------------------------------------------------

def merge_with_existing(new_df, existing_path, ticker):
    """Merge new data with existing CSV, deduplicate, sort."""
    if os.path.exists(existing_path):
        existing_df = pd.read_csv(existing_path)
        existing_df["Datetime"] = pd.to_datetime(existing_df["Datetime"])
        rows_before = len(existing_df)
        logger.info(f"Existing {ticker} data: {rows_before} rows, "
                     f"range {existing_df['Datetime'].min()} to {existing_df['Datetime'].max()}")

        combined = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        rows_before = 0
        combined = new_df.copy()

    # Deduplicate by Datetime
    combined = combined.drop_duplicates(subset=["Datetime"], keep="last")
    combined = combined.sort_values("Datetime").reset_index(drop=True)

    new_rows = len(combined) - rows_before
    logger.info(f"{ticker}: {rows_before} existing + {new_rows} new = {len(combined)} total rows")
    logger.info(f"{ticker} date range: {combined['Datetime'].min()} to {combined['Datetime'].max()}")

    return combined


def validate_data(df, ticker):
    """Validate OHLCV data quality. Returns (passed, report_dict)."""
    report = {"ticker": ticker, "issues": []}

    if df.empty:
        report["issues"].append("DataFrame is empty")
        return False, report

    report["total_rows"] = len(df)
    report["date_range"] = f"{df['Datetime'].min()} to {df['Datetime'].max()}"

    # 1. OHLC integrity
    ohlc_issues = 0
    high_violations = (df["High"] < df[["Open", "Close"]].max(axis=1)).sum()
    low_violations = (df["Low"] > df[["Open", "Close"]].min(axis=1)).sum()
    if high_violations > 0:
        report["issues"].append(f"High < max(Open,Close) in {high_violations} bars")
        ohlc_issues += high_violations
    if low_violations > 0:
        report["issues"].append(f"Low > min(Open,Close) in {low_violations} bars")
        ohlc_issues += low_violations

    # 2. Volume >= 0
    neg_vol = (df["Volume"] < 0).sum()
    if neg_vol > 0:
        report["issues"].append(f"Negative volume in {neg_vol} bars")

    # 3. No NaN/null
    nulls = df[CSV_COLUMNS].isnull().sum()
    null_cols = {k: v for k, v in nulls.items() if v > 0}
    if null_cols:
        report["issues"].append(f"Null values: {null_cols}")

    # 4. Duplicate timestamps
    dupes = df["Datetime"].duplicated().sum()
    if dupes > 0:
        report["issues"].append(f"{dupes} duplicate timestamps")

    # 5. Gap analysis (gaps > 10 minutes, accounting for crypto 24/7)
    df_sorted = df.sort_values("Datetime")
    time_diffs = df_sorted["Datetime"].diff()
    gap_threshold = pd.Timedelta(minutes=10)
    gaps = time_diffs[time_diffs > gap_threshold]
    if len(gaps) > 0:
        # Only report significant gaps (>1 hour) individually
        big_gaps = gaps[gaps > pd.Timedelta(hours=1)]
        report["total_gaps_over_10min"] = len(gaps)
        report["total_gaps_over_1hr"] = len(big_gaps)
        if len(big_gaps) <= 10:
            gap_details = []
            for idx in big_gaps.index:
                gap_start = df_sorted.loc[idx - 1, "Datetime"] if idx > 0 else "N/A"
                gap_end = df_sorted.loc[idx, "Datetime"]
                gap_details.append(f"{gap_start} -> {gap_end} ({big_gaps[idx]})")
            report["large_gaps"] = gap_details
        else:
            report["large_gaps"] = f"{len(big_gaps)} gaps > 1 hour (too many to list)"

    # 6. Expected row count sanity (crypto 24/7: ~8640 bars/month * 12 months ≈ 103,680)
    report["expected_approx"] = "~103,680 (288 bars/day × 360 days)"

    passed = len(report["issues"]) == 0
    report["passed"] = passed
    return passed, report


def save_csv(df, path):
    """Save DataFrame to CSV in exact equity format."""
    df_out = df[CSV_COLUMNS].copy()
    df_out["Datetime"] = df_out["Datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
    df_out["Volume"] = df_out["Volume"].astype(int)
    df_out.to_csv(path, index=False)
    size_mb = os.path.getsize(path) / (1024 * 1024)
    logger.info(f"Saved {path} ({len(df_out)} rows, {size_mb:.1f} MB)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Backfill crypto M5 OHLCV data")
    parser.add_argument("--source", choices=["alphavantage", "binance", "auto"],
                        default="auto", help="Data source (default: auto-detect)")
    parser.add_argument("--tickers", nargs="+", default=TICKERS,
                        help="Tickers to backfill (default: ETH BTC)")
    parser.add_argument("--data-dir", default="data",
                        help="Output directory for CSV files (default: data)")
    parser.add_argument("--also-update-fetched-data", action="store_true",
                        help="Also save to MarketPatterns_AI/Fetched_Data/")
    parser.add_argument("--av-delay", type=int, default=15,
                        help="Delay between Alpha Vantage calls in seconds (default: 15)")
    parser.add_argument("--start-month", default="2025-04",
                        help="Start month YYYY-MM (default: 2025-04)")
    parser.add_argument("--end-month", default="2026-03",
                        help="End month YYYY-MM (default: 2026-03)")
    args = parser.parse_args()

    # Build month list from args
    months = []
    current = datetime.strptime(args.start_month, "%Y-%m")
    end = datetime.strptime(args.end_month, "%Y-%m")
    while current <= end:
        months.append(current.strftime("%Y-%m"))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    logger.info(f"Backfill plan: tickers={args.tickers}, months={months[0]}..{months[-1]} ({len(months)} months)")
    logger.info(f"Output directory: {args.data_dir}")

    os.makedirs(args.data_dir, exist_ok=True)

    # Determine source
    source = args.source
    api_key = get_api_key()

    if source == "auto":
        if api_key:
            logger.info("Testing Alpha Vantage CRYPTO_INTRADAY month parameter...")
            if test_av_month_param(api_key):
                source = "alphavantage"
            else:
                logger.info("AV month param not supported, falling back to Binance")
                source = "binance"
        else:
            logger.info("No Alpha Vantage API key found, using Binance")
            source = "binance"
    elif source == "alphavantage" and not api_key:
        logger.error("Alpha Vantage selected but no API key found. "
                      "Set ALPHA_VANTAGE_API_KEY env var or add to config.json")
        sys.exit(1)

    logger.info(f"Using data source: {source}")

    # Fetch data
    if source == "alphavantage":
        results = fetch_all_av(args.tickers, months, api_key)
    else:
        # Binance: compute start/end datetime range
        start_dt = datetime(int(months[0][:4]), int(months[0][5:]), 1, tzinfo=timezone.utc)
        # End at the last day of the end month
        end_year, end_month_num = int(months[-1][:4]), int(months[-1][5:])
        if end_month_num == 12:
            end_dt = datetime(end_year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end_dt = datetime(end_year, end_month_num + 1, 1, tzinfo=timezone.utc)
        # Cap at current time
        now_utc = datetime.now(timezone.utc)
        if end_dt > now_utc:
            end_dt = now_utc

        # Quick connectivity test: try a single API call before committing to full fetch
        logger.info("Testing Binance API connectivity with a single request...")
        test_data = fetch_binance_chunk("BTCUSDT", int(start_dt.timestamp() * 1000),
                                         int(start_dt.timestamp() * 1000) + 300000)
        if test_data:
            logger.info(f"Binance API accessible ({len(test_data)} bars from test). Using API.")
            results = fetch_all_binance(args.tickers, start_dt, end_dt)
        else:
            logger.warning("Binance API not accessible (likely geo-blocked). "
                           "Trying data.binance.vision bulk downloads...")
            results = fetch_all_vision(args.tickers, months)

            # If Vision also fails, try CryptoCompare as last resort
            empty_count = sum(1 for df in results.values() if df.empty)
            if empty_count == len(args.tickers):
                logger.warning("Vision also returned no data. "
                               "Trying CryptoCompare API as final fallback...")
                results = fetch_all_cryptocompare(args.tickers, months)

    # Process each ticker: merge, validate, save
    output_dirs = [args.data_dir]
    if args.also_update_fetched_data:
        fetched_dir = os.path.join("MarketPatterns_AI", "Fetched_Data")
        os.makedirs(fetched_dir, exist_ok=True)
        output_dirs.append(fetched_dir)

    summary = {}

    for ticker in args.tickers:
        new_df = results.get(ticker, pd.DataFrame())
        if new_df.empty:
            logger.warning(f"No data fetched for {ticker}, skipping")
            summary[ticker] = {"status": "NO DATA"}
            continue

        # Ensure Datetime is datetime type
        new_df["Datetime"] = pd.to_datetime(new_df["Datetime"])

        for out_dir in output_dirs:
            # Determine filename: crypto files use {TICKER}_crypto_data.csv
            csv_name = f"{ticker}_crypto_data.csv"
            csv_path = os.path.join(out_dir, csv_name)

            # Backup existing file
            backup_file(csv_path)

            # Merge with existing
            merged = merge_with_existing(new_df, csv_path, ticker)

            # Validate
            passed, report = validate_data(merged, ticker)
            if passed:
                logger.info(f"Validation PASSED for {ticker}")
            else:
                logger.warning(f"Validation issues for {ticker}: {report['issues']}")

            # Save
            save_csv(merged, csv_path)

            # Store summary for first output dir
            if out_dir == output_dirs[0]:
                summary[ticker] = report

    # Print summary report
    print("\n" + "=" * 70)
    print("BACKFILL SUMMARY REPORT")
    print("=" * 70)
    print(f"Data source: {source}")
    print(f"Months: {months[0]} through {months[-1]} ({len(months)} months)")
    print()

    for ticker, report in summary.items():
        print(f"--- {ticker} ---")
        if isinstance(report, dict) and "status" in report:
            print(f"  Status: {report['status']}")
            continue
        print(f"  Total rows:    {report.get('total_rows', 'N/A')}")
        print(f"  Date range:    {report.get('date_range', 'N/A')}")
        print(f"  Expected:      {report.get('expected_approx', 'N/A')}")
        print(f"  Gaps > 10min:  {report.get('total_gaps_over_10min', 0)}")
        print(f"  Gaps > 1hr:    {report.get('total_gaps_over_1hr', 0)}")
        if report.get("issues"):
            print(f"  Issues:        {report['issues']}")
        else:
            print(f"  Validation:    PASSED")
        csv_path = os.path.join(args.data_dir, f"{ticker}_crypto_data.csv")
        if os.path.exists(csv_path):
            size_mb = os.path.getsize(csv_path) / (1024 * 1024)
            print(f"  File size:     {size_mb:.1f} MB")
        print()

    # Verify format matches equity
    print("--- FORMAT CHECK ---")
    for ticker in args.tickers:
        csv_path = os.path.join(args.data_dir, f"{ticker}_crypto_data.csv")
        if os.path.exists(csv_path):
            df_check = pd.read_csv(csv_path, nrows=5)
            print(f"\n{ticker} first 5 rows:")
            print(df_check.to_string(index=False))
            df_tail = pd.read_csv(csv_path).tail(5)
            print(f"\n{ticker} last 5 rows:")
            print(df_tail.to_string(index=False))

    print("\n" + "=" * 70)
    ready = all(
        isinstance(r, dict) and r.get("passed", False)
        for r in summary.values()
    )
    print(f"Ready for Chandelier Exit backtest? {'YES' if ready else 'NO - check issues above'}")
    print("=" * 70)

    # Exit with error if no data was generated at all
    all_empty = all(
        isinstance(r, dict) and r.get("status") == "NO DATA"
        for r in summary.values()
    )
    if all_empty:
        logger.error("FATAL: No data was generated for any ticker!")
        sys.exit(1)


if __name__ == "__main__":
    main()
