#!/usr/bin/env python3
"""
Validate downloaded FMP M5 data files.

Checks each ticker CSV for:
  1. Bar count per trading day (~78 for equity regular session, ~288 for crypto)
  2. Missing trading days (gaps)
  3. OHLC sanity (open > 0, high >= low, close > 0)
  4. Timestamp ordering (ascending)
  5. Duplicate timestamps
  6. Date range coverage

Usage:
    python3 scripts/validate_fmp_data.py                    # Validate all
    python3 scripts/validate_fmp_data.py --ticker NVDA      # Single ticker
    python3 scripts/validate_fmp_data.py --data-dir ./data   # Custom directory
"""

import argparse
import csv
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Ticker definitions (must match fmp_historical_fetcher.py)
# ---------------------------------------------------------------------------

EQUITY_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA",
    "TSLA", "AMD", "SMCI", "PLTR", "AVGO", "ARM", "TSM",
    "MU", "INTC", "COST",
    "COIN", "MSTR", "MARA",
    "C", "GS", "V", "BA", "JPM",
    "BABA", "JD", "BIDU",
    "SPY", "VIXY",
]

CRYPTO_TICKERS = ["BTC", "ETH"]
INDEX_TICKERS = ["VIX"]

# IST-equivalent session boundaries (ET + 7h)
# Regular session: 16:30-22:55 IST = 09:30-15:55 ET
IST_REG_START_HOUR = 16
IST_REG_START_MIN = 30
IST_REG_END_HOUR = 22
IST_REG_END_MIN = 55

# Expected bars per day
EXPECTED_EQUITY_BARS_PER_DAY = 78   # 09:30-15:55 ET, 5-min intervals
EXPECTED_CRYPTO_BARS_PER_DAY = 288  # 24h × 12 bars/hour


def get_filename(ticker: str) -> str:
    if ticker in CRYPTO_TICKERS:
        return f"{ticker}_crypto_data.csv"
    return f"{ticker}_data.csv"


def validate_ticker(ticker: str, data_dir: str) -> dict:
    """Validate a single ticker's CSV data. Returns a report dict."""
    filename = get_filename(ticker)
    filepath = os.path.join(data_dir, filename)
    is_crypto = ticker in CRYPTO_TICKERS

    report = {
        "ticker": ticker,
        "file": filename,
        "exists": False,
        "errors": [],
        "warnings": [],
        "stats": {},
    }

    if not os.path.exists(filepath):
        report["errors"].append(f"File not found: {filepath}")
        return report

    report["exists"] = True

    # Read all bars
    bars = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append(row)

    if not bars:
        report["errors"].append("File is empty (no data rows)")
        return report

    total_bars = len(bars)
    report["stats"]["total_bars"] = total_bars

    # Parse timestamps
    timestamps = []
    parse_errors = 0
    for bar in bars:
        try:
            dt = datetime.strptime(bar["Datetime"], "%Y-%m-%d %H:%M:%S")
            timestamps.append(dt)
        except (ValueError, KeyError):
            parse_errors += 1

    if parse_errors > 0:
        report["errors"].append(f"{parse_errors} timestamp parse errors")

    if not timestamps:
        report["errors"].append("No valid timestamps found")
        return report

    report["stats"]["date_range"] = f"{timestamps[0]} → {timestamps[-1]}"
    report["stats"]["first_date"] = str(timestamps[0].date())
    report["stats"]["last_date"] = str(timestamps[-1].date())

    # 1. Check timestamp ordering
    out_of_order = 0
    for i in range(1, len(timestamps)):
        if timestamps[i] < timestamps[i - 1]:
            out_of_order += 1
    if out_of_order > 0:
        report["errors"].append(f"{out_of_order} timestamps out of order")

    # 2. Check for duplicates
    ts_strings = [bar["Datetime"] for bar in bars]
    ts_counts = Counter(ts_strings)
    duplicates = {ts: count for ts, count in ts_counts.items() if count > 1}
    if duplicates:
        report["errors"].append(
            f"{len(duplicates)} duplicate timestamps "
            f"(worst: {max(duplicates.values())}x)"
        )

    # 3. OHLC sanity
    ohlc_errors = 0
    zero_price = 0
    negative_volume = 0

    for bar in bars:
        try:
            o = float(bar["Open"])
            h = float(bar["High"])
            l = float(bar["Low"])
            c = float(bar["Close"])
            v = int(float(bar["Volume"]))

            if o <= 0 or h <= 0 or l <= 0 or c <= 0:
                zero_price += 1
            if h < l:
                ohlc_errors += 1
            if v < 0:
                negative_volume += 1
        except (ValueError, KeyError):
            ohlc_errors += 1

    if ohlc_errors > 0:
        report["errors"].append(f"{ohlc_errors} OHLC consistency errors (H < L)")
    if zero_price > 0:
        report["warnings"].append(f"{zero_price} bars with zero/negative price")
    if negative_volume > 0:
        report["warnings"].append(f"{negative_volume} bars with negative volume")

    # 4. Bars per trading day (for regular session)
    if not is_crypto:
        # Count bars in IST regular session per day
        day_bar_counts = defaultdict(int)
        for dt in timestamps:
            hm = dt.hour * 60 + dt.minute
            if IST_REG_START_HOUR * 60 + IST_REG_START_MIN <= hm <= IST_REG_END_HOUR * 60 + IST_REG_END_MIN:
                day_bar_counts[dt.date()] += 1

        if day_bar_counts:
            counts = list(day_bar_counts.values())
            avg_bars = sum(counts) / len(counts)
            min_bars = min(counts)
            max_bars = max(counts)
            report["stats"]["trading_days"] = len(day_bar_counts)
            report["stats"]["avg_bars_per_day"] = round(avg_bars, 1)
            report["stats"]["min_bars_per_day"] = min_bars
            report["stats"]["max_bars_per_day"] = max_bars

            # Warn if average is significantly off from expected 78
            if avg_bars < 70:
                report["warnings"].append(
                    f"Low avg bars/day: {avg_bars:.1f} (expected ~78)"
                )
    else:
        # For crypto, count all bars per calendar day
        day_bar_counts = defaultdict(int)
        for dt in timestamps:
            day_bar_counts[dt.date()] += 1

        if day_bar_counts:
            counts = list(day_bar_counts.values())
            avg_bars = sum(counts) / len(counts)
            report["stats"]["calendar_days"] = len(day_bar_counts)
            report["stats"]["avg_bars_per_day"] = round(avg_bars, 1)

    # 5. Check for date gaps (weekday gaps for equity, any gap for crypto)
    unique_dates = sorted(set(dt.date() for dt in timestamps))
    if len(unique_dates) > 1 and not is_crypto:
        gap_days = []
        for i in range(1, len(unique_dates)):
            delta = (unique_dates[i] - unique_dates[i - 1]).days
            # Skip weekends (Sat-Mon = 2 days gap is normal)
            if delta > 3:  # More than a long weekend
                gap_days.append(
                    f"{unique_dates[i-1]} → {unique_dates[i]} ({delta}d)"
                )
        if gap_days:
            report["warnings"].append(
                f"{len(gap_days)} date gaps > 3 days: {gap_days[:5]}"
            )

    # 6. Ticker column check
    tickers_in_file = set(bar.get("Ticker", "") for bar in bars)
    if len(tickers_in_file) > 1:
        report["warnings"].append(
            f"Multiple tickers in file: {tickers_in_file}"
        )

    return report


def main():
    parser = argparse.ArgumentParser(description="Validate FMP M5 data files")
    parser.add_argument("--ticker", type=str, help="Validate single ticker")
    parser.add_argument("--data-dir", type=str, default=None,
                        help="Data directory (default: Fetched_Data/)")
    args = parser.parse_args()

    if args.data_dir:
        data_dir = args.data_dir
    else:
        repo_root = Path(__file__).resolve().parents[1]
        data_dir = str(repo_root / "Fetched_Data")

    if args.ticker:
        tickers = [args.ticker.upper()]
    else:
        tickers = EQUITY_TICKERS + CRYPTO_TICKERS + INDEX_TICKERS

    print(f"Validating {len(tickers)} tickers in {data_dir}")
    print("=" * 70)

    total_errors = 0
    total_warnings = 0
    missing = []

    for ticker in tickers:
        report = validate_ticker(ticker, data_dir)

        if not report["exists"]:
            missing.append(ticker)
            continue

        status = "OK"
        if report["errors"]:
            status = "ERRORS"
            total_errors += len(report["errors"])
        elif report["warnings"]:
            status = "WARN"
        total_warnings += len(report["warnings"])

        stats = report["stats"]
        bars = stats.get("total_bars", 0)
        date_range = stats.get("date_range", "N/A")
        trading_days = stats.get("trading_days", stats.get("calendar_days", "?"))
        avg_bars = stats.get("avg_bars_per_day", "?")

        print(f"\n{ticker:6s} [{status:6s}] {bars:>8,} bars | "
              f"{trading_days} days | avg {avg_bars}/day")
        print(f"       Range: {date_range}")

        if report["errors"]:
            for err in report["errors"]:
                print(f"       ERROR: {err}")
        if report["warnings"]:
            for warn in report["warnings"]:
                print(f"       WARN:  {warn}")

    # Summary
    print(f"\n{'=' * 70}")
    print(f"VALIDATION SUMMARY")
    print(f"{'=' * 70}")
    print(f"Tickers checked:  {len(tickers)}")
    print(f"Files found:      {len(tickers) - len(missing)}")
    print(f"Missing:          {len(missing)}")
    print(f"Total errors:     {total_errors}")
    print(f"Total warnings:   {total_warnings}")

    if missing:
        print(f"\nMissing tickers: {', '.join(missing)}")

    if total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
