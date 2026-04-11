#!/usr/bin/env python3
"""
Download daily OHLCV from FMP REST API for 27 tickers.
Saves to Fetched_Data/{TICKER}_daily.json

Skip if file already exists and is larger than 1000 bytes.
Sleep 0.5s between requests to stay within rate limits.
"""

import os, json, time
from urllib.request import urlopen

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "Fetched_Data")
os.makedirs(DATA, exist_ok=True)

FMP_KEY = "PRAtaveLKuyLOcdMUOMwg2aTvqSg2ab3"
FMP_URL = ("https://financialmodelingprep.com/stable/historical-price-eod/full"
           "?symbol={}&apikey=" + FMP_KEY)

TICKERS = [
    "AAPL", "AMD",  "AMZN", "ARM",  "AVGO", "BA",   "BABA", "BIDU",
    "C",    "COIN", "COST", "GOOGL","GS",   "INTC", "JD",   "JPM",
    "MARA", "META", "MSFT", "MSTR", "MU",   "NVDA", "PLTR", "SMCI",
    "TSLA", "TSM",  "V",
]


def _date_range(records: list) -> tuple:
    """Return (min_date, max_date) strings from a list of FMP records."""
    dates = sorted(r.get("date", "") for r in records if r.get("date"))
    if not dates:
        return ("?", "?")
    return (dates[0], dates[-1])


def download_ticker(ticker: str) -> None:
    out_path = os.path.join(DATA, f"{ticker}_daily.json")

    # Skip if file is already present and non-trivial
    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
        try:
            with open(out_path) as f:
                data = json.load(f)
            lo, hi = _date_range(data)
            print(f"  {ticker:6s}: {len(data):5d} rows  {lo} to {hi}  [skip, exists]")
        except Exception:
            print(f"  {ticker:6s}: [skip, exists but unreadable]")
        return

    url = FMP_URL.format(ticker)
    try:
        with urlopen(url, timeout=20) as r:
            raw = r.read().decode("utf-8")
    except Exception as exc:
        print(f"  {ticker:6s}: ERROR fetching -- {exc}")
        return

    try:
        data = json.loads(raw)
    except Exception as exc:
        print(f"  {ticker:6s}: ERROR parsing JSON -- {exc}")
        return

    if not isinstance(data, list) or not data:
        print(f"  {ticker:6s}: no data returned (check API key / symbol)")
        return

    with open(out_path, "w") as f:
        json.dump(data, f)

    lo, hi = _date_range(data)
    print(f"  {ticker:6s}: {len(data):5d} rows  {lo} to {hi}  [saved]")


def main() -> None:
    print(f"FMP daily download -- output: {DATA}")
    print(f"Tickers ({len(TICKERS)}): {', '.join(TICKERS)}")
    print()

    for idx, ticker in enumerate(TICKERS):
        download_ticker(ticker)
        if idx < len(TICKERS) - 1:
            time.sleep(0.5)

    print("\nDone.")


if __name__ == "__main__":
    main()
