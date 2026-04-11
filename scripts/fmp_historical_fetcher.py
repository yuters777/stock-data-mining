#!/usr/bin/env python3
"""
FMP Historical M5 Data Fetcher for stock-data-mining project.

Downloads up to 5 years of 5-minute OHLCV bars from FMP API.
Supports equity, crypto, and VIX index tickers.

FMP returns timestamps in US/Eastern. This script converts them to
IST-equivalent format (ET + 7 hours) to match the existing Alpha Vantage
CSV convention used throughout the codebase. The backtester and analysis
scripts rely on IST session boundaries (16:30-22:55 IST = 09:30-15:55 ET)
and subtract 7 hours to recover ET.

Output format matches existing Fetched_Data CSVs:
    Columns: Datetime, Open, High, Low, Close, Volume, Ticker
    Datetime: YYYY-MM-DD HH:MM:SS (IST-equivalent = ET + 7h)
    Sorted ascending by Datetime, no index column.

Usage:
    # Test with one ticker
    python3 scripts/fmp_historical_fetcher.py --ticker NVDA --years 1

    # Download all tickers, 5 years
    python3 scripts/fmp_historical_fetcher.py --all --years 5

    # Custom date range
    python3 scripts/fmp_historical_fetcher.py --all --from-date 2021-04-01 --to-date 2026-04-10

    # Resume interrupted download (skips existing months)
    python3 scripts/fmp_historical_fetcher.py --all --years 5

    # Force re-download (overwrite existing files)
    python3 scripts/fmp_historical_fetcher.py --all --years 5 --force
"""

import argparse
import csv
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FMP_BASE_URL = "https://financialmodelingprep.com/stable/historical-chart/5min"
API_KEY = os.environ.get("FMP_API_KEY", "PRAtaveLKuyLOcdMUOMwg2aTvqSg2ab3")

# Rate limiting: 300 calls/min allowed, use 4/sec (240/min) for safety
DELAY_BETWEEN_CALLS = 0.30  # seconds

# ET → IST-equivalent offset (matches existing Alpha Vantage CSV convention)
ET_TO_IST_OFFSET_HOURS = 7

# CSV columns matching existing format
CSV_COLUMNS = ["Datetime", "Open", "High", "Low", "Close", "Volume", "Ticker"]

# ---------------------------------------------------------------------------
# Ticker definitions
# ---------------------------------------------------------------------------

EQUITY_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA",   # Mega Tech
    "TSLA", "AMD", "SMCI", "PLTR", "AVGO", "ARM", "TSM", # Growth/Semi
    "MU", "INTC", "COST",                                 # Semi/Consumer
    "COIN", "MSTR", "MARA",                               # Crypto Proxy
    "C", "GS", "V", "BA", "JPM",                          # Finance/Industrial
    "BABA", "JD", "BIDU",                                  # China ADR
    "SPY", "VIXY",                                         # Cross-asset
]

CRYPTO_TICKERS = {
    "BTC": "BTCUSD",
    "ETH": "ETHUSD",
}

INDEX_TICKERS = {
    "VIX": "^VIX",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("fmp_fetch.log"),
    ],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_all_tickers() -> dict[str, str]:
    """Build ticker map: internal_name -> FMP symbol."""
    tickers = {}
    for t in EQUITY_TICKERS:
        tickers[t] = t
    for internal, fmp_sym in CRYPTO_TICKERS.items():
        tickers[internal] = fmp_sym
    for internal, fmp_sym in INDEX_TICKERS.items():
        tickers[internal] = fmp_sym
    return tickers


def get_output_filename(ticker: str) -> str:
    """Return output filename matching existing convention."""
    if ticker in CRYPTO_TICKERS:
        return f"{ticker}_crypto_data.csv"
    return f"{ticker}_data.csv"


def month_range(from_date: datetime, to_date: datetime):
    """Yield (start_date, end_date) for each month in the range."""
    current = from_date.replace(day=1)
    while current < to_date:
        month_start = current
        # Last day of month
        if current.month == 12:
            month_end = current.replace(year=current.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            month_end = current.replace(month=current.month + 1, day=1) - timedelta(days=1)
        # Clamp to requested range
        actual_start = max(month_start, from_date)
        actual_end = min(month_end, to_date)
        yield actual_start, actual_end
        # Advance to next month
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)


def fetch_month(fmp_symbol: str, from_date: str, to_date: str,
                api_key: str, max_retries: int = 3) -> list[dict]:
    """Fetch M5 bars for one ticker for one month from FMP.

    Returns list of bar dicts with keys: date, open, high, low, close, volume.
    """
    # URL-encode special characters (^VIX → %5EVIX)
    url_symbol = fmp_symbol.replace("^", "%5E")
    url = (f"{FMP_BASE_URL}"
           f"?symbol={url_symbol}"
           f"&from={from_date}"
           f"&to={to_date}"
           f"&apikey={api_key}")

    for attempt in range(max_retries):
        try:
            resp = requests.get(url, timeout=30)

            if resp.status_code == 429:
                wait = 60 * (attempt + 1)
                logger.warning(f"Rate limited (429), waiting {wait}s (attempt {attempt + 1})")
                time.sleep(wait)
                continue

            if resp.status_code != 200:
                logger.error(f"HTTP {resp.status_code} for {fmp_symbol} {from_date}: {resp.text[:200]}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** (attempt + 1))
                    continue
                return []

            data = resp.json()

            # FMP returns error messages as dicts sometimes
            if isinstance(data, dict):
                if "Error Message" in data or "error" in data:
                    logger.error(f"FMP error for {fmp_symbol}: {data}")
                    return []

            if not isinstance(data, list):
                logger.warning(f"Unexpected response type for {fmp_symbol}: {type(data)}")
                return []

            return data

        except requests.exceptions.Timeout:
            logger.warning(f"Timeout for {fmp_symbol} {from_date} (attempt {attempt + 1})")
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error for {fmp_symbol} {from_date}: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))

    return []


def convert_et_to_ist(et_timestamp_str: str) -> str:
    """Convert FMP Eastern Time timestamp to IST-equivalent (ET + 7h).

    This matches the existing Alpha Vantage CSV convention where timestamps
    are stored as ET + 7 hours. The data loaders subtract 7h to recover ET.
    """
    dt = datetime.strptime(et_timestamp_str, "%Y-%m-%d %H:%M:%S")
    dt_ist = dt + timedelta(hours=ET_TO_IST_OFFSET_HOURS)
    return dt_ist.strftime("%Y-%m-%d %H:%M:%S")


def load_existing_months(filepath: str) -> set[str]:
    """Load set of YYYY-MM months already present in a CSV file."""
    months = set()
    if not os.path.exists(filepath):
        return months
    try:
        with open(filepath, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                dt_str = row.get("Datetime", "")
                if len(dt_str) >= 7:
                    months.add(dt_str[:7])
    except Exception as e:
        logger.warning(f"Error reading existing file {filepath}: {e}")
    return months


def load_existing_bars(filepath: str) -> list[dict]:
    """Load existing bars from CSV file for merging."""
    bars = []
    if not os.path.exists(filepath):
        return bars
    try:
        with open(filepath, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                bars.append(row)
    except Exception as e:
        logger.warning(f"Error reading existing file {filepath}: {e}")
    return bars


def write_csv(filepath: str, bars: list[dict], ticker: str):
    """Write bars to CSV in the standard format.

    Bars are sorted chronologically and deduplicated by timestamp.
    """
    # Deduplicate by Datetime
    seen = set()
    unique_bars = []
    for bar in bars:
        dt = bar["Datetime"]
        if dt not in seen:
            seen.add(dt)
            unique_bars.append(bar)

    # Sort chronologically
    unique_bars.sort(key=lambda b: b["Datetime"])

    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for bar in unique_bars:
            writer.writerow({
                "Datetime": bar["Datetime"],
                "Open": bar["Open"],
                "High": bar["High"],
                "Low": bar["Low"],
                "Close": bar["Close"],
                "Volume": bar["Volume"],
                "Ticker": ticker,
            })

    return len(unique_bars)


# ---------------------------------------------------------------------------
# Main download logic
# ---------------------------------------------------------------------------


def download_ticker(ticker: str, fmp_symbol: str,
                    from_date: datetime, to_date: datetime,
                    output_dir: str, api_key: str,
                    force: bool = False) -> int:
    """Download M5 bars for a single ticker, month by month.

    Returns total number of new bars downloaded.
    """
    filename = get_output_filename(ticker)
    filepath = os.path.join(output_dir, filename)

    # Resume support: check what months already exist
    existing_months = set()
    existing_bars = []
    if not force and os.path.exists(filepath):
        existing_months = load_existing_months(filepath)
        existing_bars = load_existing_bars(filepath)
        if existing_months:
            logger.info(f"  {ticker}: found {len(existing_months)} existing months, "
                        f"{len(existing_bars)} existing bars")

    new_bars = []
    api_calls = 0

    for month_start, month_end in month_range(from_date, to_date):
        month_key = month_start.strftime("%Y-%m")

        # For IST-equivalent timestamps, the month key in the file
        # is shifted. E.g., ET 2021-04-30 20:00 → IST 2021-05-01 03:00.
        # So we check the ET month key AND the next month key.
        ist_month_key = (month_start + timedelta(hours=ET_TO_IST_OFFSET_HOURS)).strftime("%Y-%m")

        if not force and month_key in existing_months and ist_month_key in existing_months:
            logger.info(f"  {ticker} {month_key}: SKIP (exists)")
            continue

        from_str = month_start.strftime("%Y-%m-%d")
        to_str = month_end.strftime("%Y-%m-%d")

        raw_bars = fetch_month(fmp_symbol, from_str, to_str, api_key)
        api_calls += 1

        if raw_bars:
            for bar in raw_bars:
                ist_dt = convert_et_to_ist(bar["date"])
                new_bars.append({
                    "Datetime": ist_dt,
                    "Open": bar["open"],
                    "High": bar["high"],
                    "Low": bar["low"],
                    "Close": bar["close"],
                    "Volume": bar["volume"],
                    "Ticker": ticker,
                })
            logger.info(f"  {ticker} {month_key}: {len(raw_bars)} bars")
        else:
            logger.info(f"  {ticker} {month_key}: 0 bars")

        time.sleep(DELAY_BETWEEN_CALLS)

    # Merge with existing bars and write
    if new_bars:
        all_bars = existing_bars + new_bars
        total = write_csv(filepath, all_bars, ticker)
        logger.info(f"  {ticker}: TOTAL {total} bars saved "
                    f"({len(new_bars)} new, {api_calls} API calls)")
        return len(new_bars)
    elif not existing_bars:
        logger.warning(f"  {ticker}: No data downloaded")
        return 0
    else:
        logger.info(f"  {ticker}: No new data (already up to date)")
        return 0


def download_all(tickers: dict[str, str],
                 from_date: datetime, to_date: datetime,
                 output_dir: str, api_key: str,
                 force: bool = False) -> dict:
    """Download M5 bars for all tickers.

    Returns summary dict with per-ticker stats.
    """
    os.makedirs(output_dir, exist_ok=True)

    summary = {}
    total_new = 0
    total_tickers = len(tickers)

    for i, (ticker, fmp_symbol) in enumerate(tickers.items(), 1):
        logger.info(f"[{i}/{total_tickers}] Downloading {ticker} ({fmp_symbol})...")

        try:
            new_bars = download_ticker(
                ticker, fmp_symbol, from_date, to_date,
                output_dir, api_key, force=force,
            )
            summary[ticker] = {"status": "ok", "new_bars": new_bars}
            total_new += new_bars
        except Exception as e:
            logger.error(f"  {ticker}: FAILED - {e}")
            summary[ticker] = {"status": "error", "error": str(e)}

    logger.info(f"\nDownload complete: {total_new} new bars across {total_tickers} tickers")
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download M5 historical data from FMP API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true",
                       help="Download all tickers (equity + crypto + VIX)")
    group.add_argument("--ticker", type=str,
                       help="Download a single ticker (e.g., NVDA, BTC, VIX)")
    group.add_argument("--equity-only", action="store_true",
                       help="Download equity tickers only")
    group.add_argument("--crypto-only", action="store_true",
                       help="Download crypto tickers only")

    parser.add_argument("--years", type=int, default=5,
                        help="Number of years of history to download (default: 5)")
    parser.add_argument("--from-date", type=str,
                        help="Start date YYYY-MM-DD (overrides --years)")
    parser.add_argument("--to-date", type=str,
                        help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Output directory (default: Fetched_Data/)")
    parser.add_argument("--force", action="store_true",
                        help="Force re-download, overwriting existing files")
    parser.add_argument("--api-key", type=str, default=None,
                        help="FMP API key (default: env FMP_API_KEY or built-in)")

    return parser.parse_args()


def main():
    args = parse_args()

    # Resolve output directory
    if args.output_dir:
        output_dir = args.output_dir
    else:
        repo_root = Path(__file__).resolve().parents[1]
        output_dir = str(repo_root / "Fetched_Data")

    # Resolve API key
    api_key = args.api_key or API_KEY
    if not api_key:
        logger.error("No FMP API key. Set FMP_API_KEY env var or use --api-key")
        sys.exit(1)

    # Resolve date range
    if args.to_date:
        to_date = datetime.strptime(args.to_date, "%Y-%m-%d")
    else:
        to_date = datetime.now()

    if args.from_date:
        from_date = datetime.strptime(args.from_date, "%Y-%m-%d")
    else:
        from_date = to_date.replace(year=to_date.year - args.years)

    logger.info(f"Date range: {from_date.strftime('%Y-%m-%d')} → {to_date.strftime('%Y-%m-%d')}")
    logger.info(f"Output directory: {output_dir}")

    # Build ticker list
    all_tickers = get_all_tickers()

    if args.all:
        tickers = all_tickers
    elif args.ticker:
        t = args.ticker.upper()
        if t in all_tickers:
            tickers = {t: all_tickers[t]}
        elif t in CRYPTO_TICKERS:
            tickers = {t: CRYPTO_TICKERS[t]}
        elif t in INDEX_TICKERS:
            tickers = {t: INDEX_TICKERS[t]}
        else:
            # Assume it's a direct FMP symbol
            tickers = {t: t}
    elif args.equity_only:
        tickers = {t: t for t in EQUITY_TICKERS}
    elif args.crypto_only:
        tickers = {k: v for k, v in CRYPTO_TICKERS.items()}

    logger.info(f"Tickers ({len(tickers)}): {', '.join(tickers.keys())}")

    # Calculate estimated API calls
    from dateutil.relativedelta import relativedelta
    months = 0
    current = from_date.replace(day=1)
    while current < to_date:
        months += 1
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    est_calls = len(tickers) * months
    est_minutes = est_calls * DELAY_BETWEEN_CALLS / 60
    logger.info(f"Estimated API calls: {est_calls} (~{est_minutes:.1f} min)")

    # Download
    start_time = time.time()
    summary = download_all(tickers, from_date, to_date, output_dir, api_key,
                           force=args.force)
    elapsed = time.time() - start_time

    # Print summary
    logger.info(f"\n{'=' * 60}")
    logger.info(f"DOWNLOAD SUMMARY (elapsed: {elapsed:.0f}s)")
    logger.info(f"{'=' * 60}")

    ok_count = sum(1 for v in summary.values() if v["status"] == "ok")
    err_count = sum(1 for v in summary.values() if v["status"] == "error")
    total_bars = sum(v.get("new_bars", 0) for v in summary.values())

    logger.info(f"Tickers OK: {ok_count}, Errors: {err_count}")
    logger.info(f"Total new bars: {total_bars:,}")

    if err_count > 0:
        logger.info("\nFailed tickers:")
        for ticker, info in summary.items():
            if info["status"] == "error":
                logger.info(f"  {ticker}: {info['error']}")

    # Per-ticker summary
    logger.info(f"\nPer-ticker breakdown:")
    for ticker, info in sorted(summary.items()):
        status = info["status"].upper()
        bars = info.get("new_bars", 0)
        logger.info(f"  {ticker:6s}: {status} ({bars:,} new bars)")


if __name__ == "__main__":
    main()
