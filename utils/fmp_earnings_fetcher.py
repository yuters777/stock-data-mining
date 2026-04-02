"""
FMP (Financial Modeling Prep) earnings data fetcher for PEAD backtest.

Fetches EPS actual/estimated, revenue actual/estimated, and computes
surprise metrics. Saves to backtester/data/fmp_earnings.csv and updates
backtester/data/earnings_calendar.json with any new dates found.

CLI:
    python utils/fmp_earnings_fetcher.py backfill    # fetch all history per ticker
    python utils/fmp_earnings_fetcher.py fetch        # forward calendar + recent
    python utils/fmp_earnings_fetcher.py show AAPL    # show one ticker
"""

import csv
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# --- Paths ---
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DATA_DIR = _REPO_ROOT / "backtester" / "data"
_CSV_PATH = _DATA_DIR / "fmp_earnings.csv"
_CALENDAR_PATH = _DATA_DIR / "earnings_calendar.json"

# --- FMP endpoints ---
_BASE_URL = "https://financialmodelingprep.com/stable"
_EARNINGS_URL = _BASE_URL + "/earnings"
_CALENDAR_URL = _BASE_URL + "/earnings-calendar"

# --- Equity tickers (exclude SPY, VIXY, BTC, ETH) ---
EQUITY_TICKERS = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU",
    "C", "COIN", "COST", "GOOGL", "GS", "INTC", "JPM", "MARA",
    "META", "MSFT", "MSTR", "MU", "NVDA", "PLTR", "SMCI",
    "TSLA", "TSM", "V",
]

# --- BMO / AMC classification ---
AMC_TICKERS = {
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD",
    "COIN", "ARM", "SMCI", "PLTR", "MSTR", "MARA", "AVGO", "TSM",
    "V", "MU", "INTC", "COST",
}
BMO_TICKERS = {"JD", "BIDU", "BABA", "C", "GS", "BA", "JPM"}

CSV_COLUMNS = [
    "ticker", "earnings_date", "time_of_day", "eps_estimated", "eps_actual",
    "eps_surprise_pct", "revenue_estimated", "revenue_actual",
    "revenue_surprise_pct", "source",
]


def get_time_of_day(ticker: str) -> str:
    if ticker in AMC_TICKERS:
        return "AMC"
    if ticker in BMO_TICKERS:
        return "BMO"
    return "Unknown"


def compute_eps_surprise(actual: Optional[float], estimated: Optional[float]) -> Optional[float]:
    if actual is None or estimated is None:
        return None
    if estimated == 0:
        return None
    return round((actual - estimated) / abs(estimated) * 100, 4)


def compute_revenue_surprise(actual: Optional[float], estimated: Optional[float]) -> Optional[float]:
    if actual is None or estimated is None:
        return None
    if estimated == 0:
        return None
    return round((actual - estimated) / estimated * 100, 4)


def _get_api_key() -> str:
    key = os.getenv("FMP_API_KEY")
    if not key:
        print("ERROR: FMP_API_KEY environment variable not set.")
        print("  export FMP_API_KEY=your_key_here")
        sys.exit(1)
    return key


def _fmp_get(url: str, params: dict) -> Optional[list]:
    """GET request to FMP with retry on 429."""
    for attempt in range(2):
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 429:
                if attempt == 0:
                    logger.warning("Rate limited (429), waiting 2s...")
                    time.sleep(2)
                    continue
                logger.warning("Rate limited twice, skipping.")
                return None
            if resp.status_code == 402:
                logger.warning("FMP plan doesn't cover this endpoint (402).")
                return None
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            # Some error responses are dicts
            if isinstance(data, dict) and "error" in data:
                logger.warning("FMP error: %s", data["error"])
                return None
            return data if isinstance(data, list) else []
        except requests.RequestException as e:
            logger.warning("HTTP error: %s", e)
            return None
    return None


def fetch_ticker_earnings(ticker: str, api_key: str, limit: int = 40) -> list[dict]:
    """Fetch historical earnings for one ticker from FMP."""
    data = _fmp_get(_EARNINGS_URL, {
        "symbol": ticker,
        "apikey": api_key,
        "limit": limit,
    })
    if not data:
        return []
    return data


def fetch_earnings_calendar(api_key: str, from_date: str, to_date: str) -> list[dict]:
    """Fetch forward earnings calendar from FMP."""
    data = _fmp_get(_CALENDAR_URL, {
        "from": from_date,
        "to": to_date,
        "apikey": api_key,
    })
    if not data:
        return []
    return data


def _parse_fmp_row(row: dict) -> dict:
    """Convert FMP JSON row to our CSV format."""
    ticker = row.get("symbol", "")
    earnings_date = row.get("date", "")
    eps_actual = row.get("epsActual")
    eps_estimated = row.get("epsEstimated")
    rev_actual = row.get("revenueActual")
    rev_estimated = row.get("revenueEstimated")

    return {
        "ticker": ticker,
        "earnings_date": earnings_date,
        "time_of_day": get_time_of_day(ticker),
        "eps_estimated": eps_estimated,
        "eps_actual": eps_actual,
        "eps_surprise_pct": compute_eps_surprise(eps_actual, eps_estimated),
        "revenue_estimated": rev_estimated,
        "revenue_actual": rev_actual,
        "revenue_surprise_pct": compute_revenue_surprise(rev_actual, rev_estimated),
        "source": "fmp",
    }


def _load_existing_csv() -> list[dict]:
    """Load existing CSV rows as list of dicts."""
    if not _CSV_PATH.exists():
        return []
    rows = []
    with open(_CSV_PATH, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def _save_csv(rows: list[dict]):
    """Save rows to CSV, sorted by ticker then date."""
    rows.sort(key=lambda r: (r.get("ticker", ""), r.get("earnings_date", "")))
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(_CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _update_earnings_calendar(new_dates: dict[str, set[str]]):
    """Merge new earnings dates into earnings_calendar.json."""
    if _CALENDAR_PATH.exists():
        with open(_CALENDAR_PATH, "r") as f:
            calendar = json.load(f)
    else:
        calendar = {}

    updated = 0
    for ticker, dates in new_dates.items():
        existing = set(calendar.get(ticker, []))
        merged = existing | dates
        if len(merged) > len(existing):
            calendar[ticker] = sorted(merged)
            updated += len(merged) - len(existing)

    with open(_CALENDAR_PATH, "w") as f:
        json.dump(calendar, f, indent=2)
        f.write("\n")

    if updated:
        logger.info("Updated earnings_calendar.json: %d new dates added", updated)


def cmd_backfill():
    """Fetch full earnings history for all equity tickers."""
    api_key = _get_api_key()
    all_rows = []
    new_dates: dict[str, set[str]] = {}
    skipped = []

    print(f"Backfilling earnings for {len(EQUITY_TICKERS)} tickers...")
    for i, ticker in enumerate(EQUITY_TICKERS):
        print(f"  [{i+1}/{len(EQUITY_TICKERS)}] {ticker}...", end=" ", flush=True)
        data = fetch_ticker_earnings(ticker, api_key, limit=40)
        if not data:
            print("no data")
            skipped.append(ticker)
            continue

        ticker_dates = set()
        for row in data:
            parsed = _parse_fmp_row(row)
            all_rows.append(parsed)
            if parsed["earnings_date"]:
                ticker_dates.add(parsed["earnings_date"])

        new_dates[ticker] = ticker_dates
        print(f"{len(data)} rows")

        # Respect rate limits: brief pause between tickers
        if i < len(EQUITY_TICKERS) - 1:
            time.sleep(0.3)

    # Merge with existing data
    existing = _load_existing_csv()
    existing_keys = {(r["ticker"], r["earnings_date"]) for r in existing}
    added = 0
    for row in all_rows:
        key = (row["ticker"], row["earnings_date"])
        if key not in existing_keys:
            existing.append(row)
            existing_keys.add(key)
            added += 1
        else:
            # Update existing row with fresh data
            for i_ex, ex in enumerate(existing):
                if (ex["ticker"], ex["earnings_date"]) == key:
                    existing[i_ex] = row
                    break

    _save_csv(existing)
    _update_earnings_calendar(new_dates)

    # Report
    print(f"\n--- Backfill Complete ---")
    print(f"CSV: {_CSV_PATH}")
    print(f"Total rows: {len(existing)}")
    print(f"New rows added: {added}")
    print(f"Tickers with data: {len(new_dates)}")
    if skipped:
        print(f"Skipped (no data): {skipped}")

    # Stats
    has_eps = sum(1 for r in existing if r.get("eps_actual") not in (None, "", "None"))
    dates_list = [r["earnings_date"] for r in existing if r.get("earnings_date")]
    if dates_list:
        print(f"Date range: {min(dates_list)} to {max(dates_list)}")
    print(f"Rows with EPS actual: {has_eps}/{len(existing)}")


def cmd_fetch():
    """Fetch forward earnings calendar + recent updates."""
    api_key = _get_api_key()
    today = date.today()
    from_date = (today - timedelta(days=7)).isoformat()
    to_date = (today + timedelta(days=90)).isoformat()

    print(f"Fetching earnings calendar: {from_date} to {to_date}...")
    data = fetch_earnings_calendar(api_key, from_date, to_date)
    if not data:
        print("No calendar data returned.")
        return

    # Filter to our tickers
    our_tickers = set(EQUITY_TICKERS)
    relevant = [r for r in data if r.get("symbol") in our_tickers]
    print(f"Found {len(relevant)} entries for our tickers (out of {len(data)} total)")

    all_rows = []
    new_dates: dict[str, set[str]] = {}
    for row in relevant:
        parsed = _parse_fmp_row(row)
        all_rows.append(parsed)
        ticker = parsed["ticker"]
        if parsed["earnings_date"]:
            new_dates.setdefault(ticker, set()).add(parsed["earnings_date"])

    # Merge
    existing = _load_existing_csv()
    existing_keys = {(r["ticker"], r["earnings_date"]) for r in existing}
    added = 0
    for row in all_rows:
        key = (row["ticker"], row["earnings_date"])
        if key not in existing_keys:
            existing.append(row)
            existing_keys.add(key)
            added += 1

    _save_csv(existing)
    _update_earnings_calendar(new_dates)

    print(f"Added {added} new rows. Total: {len(existing)}")


def cmd_show(ticker: str):
    """Show earnings data for one ticker."""
    if not _CSV_PATH.exists():
        print(f"No data file found. Run 'backfill' first.")
        return

    rows = _load_existing_csv()
    ticker_rows = [r for r in rows if r["ticker"] == ticker.upper()]
    if not ticker_rows:
        print(f"No earnings data for {ticker.upper()}")
        return

    ticker_rows.sort(key=lambda r: r["earnings_date"])
    print(f"\n{'Date':<12} {'ToD':<5} {'EPS Est':>9} {'EPS Act':>9} {'EPS Surp%':>10} "
          f"{'Rev Est':>14} {'Rev Act':>14} {'Rev Surp%':>10}")
    print("-" * 95)
    for r in ticker_rows:
        eps_est = r.get("eps_estimated", "")
        eps_act = r.get("eps_actual", "")
        eps_surp = r.get("eps_surprise_pct", "")
        rev_est = r.get("revenue_estimated", "")
        rev_act = r.get("revenue_actual", "")
        rev_surp = r.get("revenue_surprise_pct", "")

        # Format revenue as M/B
        def fmt_rev(v):
            if not v or v in ("None", ""):
                return ""
            try:
                v = float(v)
                if abs(v) >= 1e9:
                    return f"{v/1e9:.1f}B"
                if abs(v) >= 1e6:
                    return f"{v/1e6:.0f}M"
                return f"{v:.0f}"
            except (ValueError, TypeError):
                return str(v)

        def fmt_val(v):
            if not v or v in ("None", ""):
                return ""
            return str(v)

        print(f"{r['earnings_date']:<12} {r.get('time_of_day',''):<5} "
              f"{fmt_val(eps_est):>9} {fmt_val(eps_act):>9} {fmt_val(eps_surp):>10} "
              f"{fmt_rev(rev_est):>14} {fmt_rev(rev_act):>14} {fmt_val(rev_surp):>10}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python utils/fmp_earnings_fetcher.py backfill   # fetch all history")
        print("  python utils/fmp_earnings_fetcher.py fetch      # forward calendar")
        print("  python utils/fmp_earnings_fetcher.py show AAPL  # show one ticker")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    if cmd == "backfill":
        cmd_backfill()
    elif cmd == "fetch":
        cmd_fetch()
    elif cmd == "show":
        if len(sys.argv) < 3:
            print("Usage: python utils/fmp_earnings_fetcher.py show TICKER")
            sys.exit(1)
        cmd_show(sys.argv[2])
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
