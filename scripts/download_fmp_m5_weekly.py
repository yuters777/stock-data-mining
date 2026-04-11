#!/usr/bin/env python3
"""
Download full M5 OHLCV from FMP using weekly date ranges.

FMP Starter returns only ~6 trading days per monthly M5 query.
Weekly requests (Mon-Fri, 5 calendar days) return complete data
(~390 bars per full trading week).

Strategy: iterate week-by-week from START_MONDAY to END_DATE.
Each request: from=Monday, to=Friday of that week.
260 weeks x 27 tickers = 7,020 requests @ 0.3s = ~35 min.

Saves Fetched_Data/{TICKER}_m5_full.csv  (overwrites existing files).
Columns: date,open,high,low,close,volume
Resumes: loads existing CSV, finds last date, skips covered weeks.
Checkpoints to disk every CHECKPOINT weeks (~half year).
"""

import os, json, time, csv
from urllib.request import urlopen
from datetime import date, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "Fetched_Data")
os.makedirs(DATA, exist_ok=True)

FMP_KEY = "PRAtaveLKuyLOcdMUOMwg2aTvqSg2ab3"
FMP_URL = ("https://financialmodelingprep.com/stable/historical-chart/5min"
           "?symbol={ticker}&from={frm}&to={to}&apikey=" + FMP_KEY)

TICKERS = [
    "AAPL", "AMD",  "AMZN", "ARM",  "AVGO", "BA",   "BABA", "BIDU",
    "C",    "COIN", "COST", "GOOGL","GS",   "INTC", "JD",   "JPM",
    "MARA", "META", "MSFT", "MSTR", "MU",   "NVDA", "PLTR", "SMCI",
    "TSLA", "TSM",  "V",
]

START_MONDAY = date(2021, 4, 19)
END_DATE     = date(2026, 4, 11)
SLEEP        = 0.3
CHECKPOINT   = 26        # write CSV to disk every N weeks (~half year)
FIELDS       = ["date", "open", "high", "low", "close", "volume"]


# ── Helpers ────────────────────────────────────────────────────────────────

def weeks_range():
    """Yield (monday, friday) date pairs from START_MONDAY to END_DATE."""
    d = START_MONDAY
    while d <= END_DATE:
        fri = d + timedelta(days=4)
        yield d, min(fri, END_DATE)
        d += timedelta(days=7)


def load_existing(path):
    """
    Read existing CSV.
    Returns:
      rows      : dict  {date_str -> field_dict}   -- dedup by full timestamp key
      last_date : str   'YYYY-MM-DD' of latest row, or '' if empty/absent
    """
    rows = {}
    if not os.path.exists(path):
        return rows, ""
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            d = row.get("date", "")
            if d:
                rows[d] = row
    if not rows:
        return rows, ""
    # Date strings are "YYYY-MM-DD HH:MM:SS" — compare first 10 chars for calendar date
    last_date = max(d[:10] for d in rows if len(d) >= 10)
    return rows, last_date


def write_csv(path, rows):
    """Sort rows by date and write to CSV. Returns sorted list."""
    sorted_rows = sorted(rows.values(), key=lambda r: r.get("date", ""))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted_rows)
    return sorted_rows


def fetch_week(ticker, monday, friday):
    """Fetch all M5 bars for one ticker/week. Returns list of dicts (may be empty)."""
    url = FMP_URL.format(
        ticker=ticker,
        frm=monday.isoformat(),
        to=friday.isoformat(),
    )
    try:
        with urlopen(url, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        print(f"    WARN {monday}: {exc}")
        return []
    return data if isinstance(data, list) else []


# ── Per-ticker orchestration ───────────────────────────────────────────────

def process_ticker(ticker):
    out_path          = os.path.join(DATA, f"{ticker}_m5_full.csv")
    rows, last_date   = load_existing(out_path)
    fetched = skipped = since_save = 0

    for monday, friday in weeks_range():
        # Skip week if Friday is on or before the last date already in file
        if last_date and friday.isoformat() <= last_date:
            skipped += 1
            continue

        for rec in fetch_week(ticker, monday, friday):
            d = rec.get("date", "")
            if d:
                rows[d] = {k: rec.get(k, "") for k in FIELDS}

        fetched    += 1
        since_save += 1
        if since_save >= CHECKPOINT:
            write_csv(out_path, rows)
            since_save = 0

        time.sleep(SLEEP)

    if not rows:
        print(f"  {ticker:6s}: no data returned")
        return

    final = write_csv(out_path, rows)
    dates = [r["date"] for r in final if r.get("date")]
    lo    = dates[0]  if dates else "?"
    hi    = dates[-1] if dates else "?"
    print(f"  {ticker:6s}: {len(final):7d} bars  {lo} to {hi}"
          f"  ({fetched} weeks fetched, {skipped} skipped)")


# ── Entry point ────────────────────────────────────────────────────────────

def main():
    all_weeks   = list(weeks_range())
    total_weeks = len(all_weeks)
    print(f"FMP M5 weekly download -- {total_weeks} weeks x {len(TICKERS)} tickers")
    print(f"~{total_weeks * len(TICKERS) * SLEEP / 60:.0f} min at {SLEEP}s/request (no cache hits)")
    print(f"Output: {DATA}/{{TICKER}}_m5_full.csv")
    print()
    for ticker in TICKERS:
        process_ticker(ticker)
    print("\nAll done.")


if __name__ == "__main__":
    main()
