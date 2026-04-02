"""Fetch earnings dates from Alpha Vantage EARNINGS endpoint."""
import requests
import json
import time
import sys
from pathlib import Path

API_KEY = "E4T2VQPX8FU6BI17"

TICKERS = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU", "C", "COIN",
    "COST", "GOOGL", "GS", "INTC", "JPM", "MARA", "META", "MSFT", "MSTR",
    "MU", "NVDA", "PLTR", "SMCI", "TSLA", "TSM", "V"
]

calendar = {}
failed = []

for i, ticker in enumerate(TICKERS):
    url = (f"https://www.alphavantage.co/query"
           f"?function=EARNINGS&symbol={ticker}&apikey={API_KEY}")
    try:
        resp = requests.get(url, timeout=30)
        data = resp.json()

        if "Note" in data or "Information" in data:
            msg = data.get("Note", data.get("Information", ""))
            print(f"  RATE LIMIT hit at {ticker}: {msg}")
            print("  Waiting 60s before retry...")
            time.sleep(60)
            resp = requests.get(url, timeout=30)
            data = resp.json()

        dates = []
        if "quarterlyEarnings" in data:
            for q in data["quarterlyEarnings"]:
                rd = q.get("reportedDate", "")
                if rd and "2024" <= rd[:4] <= "2026":
                    dates.append(rd)

        calendar[ticker] = sorted(dates)
        status = f"{len(dates)} dates" if dates else "NO DATES"
        print(f"  [{i+1}/{len(TICKERS)}] {ticker}: {status} -> {dates}")

        if not dates and "quarterlyEarnings" not in data:
            failed.append(ticker)
            print(f"    Response keys: {list(data.keys())}")

    except Exception as e:
        print(f"  [{i+1}/{len(TICKERS)}] {ticker}: ERROR - {e}")
        calendar[ticker] = []
        failed.append(ticker)

    if i < len(TICKERS) - 1:
        time.sleep(15)

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
