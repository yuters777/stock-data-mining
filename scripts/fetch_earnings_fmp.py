#!/usr/bin/env python3
"""
Fetch earnings dates from FMP (Financial Modeling Prep) API.

Replaces the legacy fetch_earnings_av.py which used Alpha Vantage.

Usage:
    python3 scripts/fetch_earnings_fmp.py
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

API_KEY = os.environ.get("FMP_API_KEY", "PRAtaveLKuyLOcdMUOMwg2aTvqSg2ab3")
FMP_EARNINGS_URL = "https://financialmodelingprep.com/stable/earning-calendar"

TICKERS = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU",
    "C", "COIN", "COST", "GOOGL", "GS", "INTC", "JD", "JPM",
    "MARA", "META", "MSFT", "MSTR", "MU", "NVDA", "PLTR", "SMCI",
    "SPY", "TSLA", "TSM", "V", "VIXY",
]

calendar = {}
failed = []

for i, ticker in enumerate(TICKERS):
    url = (f"{FMP_EARNINGS_URL}"
           f"?symbol={ticker}"
           f"&apikey={API_KEY}")
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code == 429:
            print(f"  RATE LIMIT hit at {ticker}, waiting 60s...")
            time.sleep(60)
            resp = requests.get(url, timeout=30)

        data = resp.json()

        dates = []
        if isinstance(data, list):
            for entry in data:
                rd = entry.get("date", "")
                if rd and "2024" <= rd[:4] <= "2026":
                    dates.append(rd)

        calendar[ticker] = sorted(set(dates))
        status = f"{len(dates)} dates" if dates else "NO DATES"
        print(f"  [{i+1}/{len(TICKERS)}] {ticker}: {status} -> {dates[:5]}")

    except Exception as e:
        print(f"  [{i+1}/{len(TICKERS)}] {ticker}: ERROR - {e}")
        calendar[ticker] = []
        failed.append(ticker)

    if i < len(TICKERS) - 1:
        time.sleep(0.3)

# Save
out_dir = Path(__file__).resolve().parent.parent / "backtester" / "data"
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / "earnings_calendar.json"

with open(out_path, "w") as f:
    json.dump(calendar, f, indent=2)

total = sum(len(v) for v in calendar.values())
print(f"\nSaved {total} total earnings dates for {len(calendar)} tickers to {out_path}")
if failed:
    print(f"Failed tickers: {failed}")
