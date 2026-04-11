#!/usr/bin/env python3
"""
Download full M5 OHLCV from FMP for 27 tickers, 2021-04 to 2026-04.
Saves Fetched_Data/{TICKER}_m5_full.csv  (does NOT touch existing sparse *_data.csv files).
Resumes gracefully: months already present in the output CSV are skipped.
Checkpoints to disk every CHECKPOINT months so partial runs are not wasted.
"""

import os, json, time, calendar, csv
from urllib.request import urlopen
from datetime import date

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

START      = (2021, 4)
END        = (2026, 4)
SLEEP      = 0.3
CHECKPOINT = 12        # write CSV to disk every N months fetched (resume safety)
FIELDS     = ["date", "open", "high", "low", "close", "volume"]


# ── Helpers ────────────────────────────────────────────────────────────────

def months_range():
    """Yield (year, month) tuples from START to END inclusive."""
    y, m = START
    while (y, m) <= END:
        yield y, m
        m = m % 12 + 1
        if m == 1:
            y += 1


def load_existing(path):
    """
    Read existing CSV.
    Returns:
      rows : dict  {date_str -> field_dict}   -- deduplication by date key
      yms  : set   {'YYYY-MM', ...}            -- months already present
    """
    rows, yms = {}, set()
    if not os.path.exists(path):
        return rows, yms
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            d = row.get("date", "")
            rows[d] = row
            if len(d) >= 7:
                yms.add(d[:7])
    return rows, yms


def write_csv(path, rows):
    """Sort rows by date and write to CSV. Returns the sorted list."""
    sorted_rows = sorted(rows.values(), key=lambda r: r.get("date", ""))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted_rows)
    return sorted_rows


def fetch_month(ticker, year, month):
    """Fetch all M5 bars for one ticker/month. Returns list of dicts (may be empty)."""
    last = calendar.monthrange(year, month)[1]
    frm  = date(year, month, 1).isoformat()
    to   = date(year, month, last).isoformat()
    url  = FMP_URL.format(ticker=ticker, frm=frm, to=to)
    try:
        with urlopen(url, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        print(f"    WARN {year}-{month:02d}: {exc}")
        return []
    return data if isinstance(data, list) else []


# ── Per-ticker orchestration ───────────────────────────────────────────────

def process_ticker(ticker):
    out_path          = os.path.join(DATA, f"{ticker}_m5_full.csv")
    rows, have_yms    = load_existing(out_path)
    fetched = skipped = since_save = 0

    for year, month in months_range():
        ym = f"{year}-{month:02d}"
        if ym in have_yms:
            skipped += 1
            continue

        for rec in fetch_month(ticker, year, month):
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
          f"  ({fetched} months fetched, {skipped} skipped)")


# ── Entry point ────────────────────────────────────────────────────────────

def main():
    total_months = sum(1 for _ in months_range())
    print(f"FMP M5 full download -- {total_months} months x {len(TICKERS)} tickers")
    print(f"~{total_months * len(TICKERS) * SLEEP / 60:.0f} min at {SLEEP}s/request (no cache hits)")
    print(f"Output: {DATA}/{{TICKER}}_m5_full.csv")
    print()
    for ticker in TICKERS:
        process_ticker(ticker)
    print("\nAll done.")


if __name__ == "__main__":
    main()
