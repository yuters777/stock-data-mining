#!/usr/bin/env python3
"""
Download EXTENDED HOURS M5 OHLCV from FMP using weekly date ranges.

Extended hours = premarket 04:00 ET + postmarket to 20:00 ET.
This produces ~192 bars/day vs ~78 bars/day for RTH-only.

Strategy: iterate week-by-week from START_MONDAY to END_DATE with
&extended=true appended to every request.

Prerequisite: Run Step 1 test first to confirm extended works for old data:
  python3 - <<'EOF'
  import urllib.request, json
  FMP_KEY = "PRAtaveLKuyLOcdMUOMwg2aTvqSg2ab3"
  url = (f"https://financialmodelingprep.com/stable/historical-chart/5min"
         f"?symbol=NVDA&from=2021-05-03&to=2021-05-07&extended=true&apikey={FMP_KEY}")
  data = json.loads(urllib.request.urlopen(url, timeout=20).read())
  print(f"Bars: {len(data)}")
  if data:
      dates = sorted(set(d["date"][:10] for d in data))
      times = sorted(set(d["date"][11:16] for d in data))
      print(f"Days: {len(dates)}: {dates}")
      print(f"Time range: {times[0]} - {times[-1]}")
      print(f"Bars/day: {len(data)/len(dates):.0f}")
  EOF
  Expected: ~192 bars/day => proceed. ~78 or 0 bars => stop.

260 weeks x 28 tickers = 7,280 requests @ 0.3s = ~36 min.

Output files: Fetched_Data/{TICKER}_m5_extended.csv  (NEVER touches *_m5_full.csv)
Resumes: loads existing CSV, finds last covered date, skips completed weeks.
Checkpoints to disk every CHECKPOINT weeks (~half year).

After all tickers a verification pass flags quality issues:
  - Days with <150 bars  (possible RTH-only fallback)
  - Days with >200 bars  (possible duplicate bars)
  - Time range per ticker
  - Bar-count ratio vs RTH files (expect ~2.5x)
"""

import os, json, time, csv, collections
from urllib.request import urlopen
from datetime import date, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "Fetched_Data")
os.makedirs(DATA, exist_ok=True)

FMP_KEY = "PRAtaveLKuyLOcdMUOMwg2aTvqSg2ab3"
FMP_URL = (
    "https://financialmodelingprep.com/stable/historical-chart/5min"
    "?symbol={ticker}&from={frm}&to={to}&extended=true&apikey=" + FMP_KEY
)

# 27 equity tickers (same as RTH scripts) + SPY = 28 total
TICKERS = [
    "AAPL", "AMD",  "AMZN", "ARM",  "AVGO", "BA",   "BABA", "BIDU",
    "C",    "COIN", "COST", "GOOGL","GS",   "INTC", "JD",   "JPM",
    "MARA", "META", "MSFT", "MSTR", "MU",   "NVDA", "PLTR", "SMCI",
    "TSLA", "TSM",  "V",    "SPY",
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
    """Fetch all extended-hours M5 bars for one ticker/week. Returns list of dicts."""
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


# ── Per-ticker download ────────────────────────────────────────────────────

def process_ticker(ticker):
    out_path        = os.path.join(DATA, f"{ticker}_m5_extended.csv")
    rows, last_date = load_existing(out_path)
    fetched = skipped = since_save = 0

    for monday, friday in weeks_range():
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

    # Bars/day average
    day_counts = collections.Counter(d[:10] for d in dates if len(d) >= 10)
    avg_bars   = sum(day_counts.values()) / len(day_counts) if day_counts else 0

    print(f"  {ticker:6s}: {len(final):7d} bars  {lo} to {hi}"
          f"  avg {avg_bars:.0f} bars/day"
          f"  ({fetched} weeks fetched, {skipped} skipped)")

    return final


# ── Verification pass ──────────────────────────────────────────────────────

def verify_all():
    """
    Post-download quality check for every extended CSV.
    - Flags days with <150 bars (RTH-only fallback?)
    - Flags days with >200 bars (duplicates?)
    - Prints time range per ticker
    - Compares bar count to RTH *_m5_full.csv (expect ~2.5x)
    """
    print("\n" + "=" * 70)
    print("VERIFICATION PASS")
    print("=" * 70)

    rth_counts = {}
    for t in TICKERS:
        p = os.path.join(DATA, f"{t}_m5_full.csv")
        if os.path.exists(p):
            with open(p, newline="") as f:
                rth_counts[t] = sum(1 for _ in csv.DictReader(f))

    summary_bars_per_day = []

    for ticker in TICKERS:
        path = os.path.join(DATA, f"{ticker}_m5_extended.csv")
        if not os.path.exists(path):
            print(f"  {ticker:6s}: MISSING — file not found")
            continue

        rows = []
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))

        if not rows:
            print(f"  {ticker:6s}: EMPTY file")
            continue

        dates_str = [r["date"] for r in rows if r.get("date")]
        day_counts = collections.Counter(d[:10] for d in dates_str if len(d) >= 10)
        times      = sorted(set(d[11:16] for d in dates_str if len(d) >= 16))
        time_lo    = times[0]  if times else "?"
        time_hi    = times[-1] if times else "?"

        low_days  = [day for day, cnt in day_counts.items() if cnt < 150]
        high_days = [day for day, cnt in day_counts.items() if cnt > 200]
        avg_bars  = sum(day_counts.values()) / len(day_counts) if day_counts else 0
        summary_bars_per_day.append(avg_bars)

        rth_n   = rth_counts.get(ticker, 0)
        ratio   = len(rows) / rth_n if rth_n else 0.0
        ratio_s = f"{ratio:.2f}x RTH" if rth_n else "no RTH file"

        flags = []
        if low_days:
            flags.append(f"LOW-BAR DAYS ({len(low_days)}): {low_days[:5]}"
                         + (" ..." if len(low_days) > 5 else ""))
        if high_days:
            flags.append(f"HIGH-BAR DAYS ({len(high_days)}): {high_days[:5]}"
                         + (" ..." if len(high_days) > 5 else ""))

        status = "OK" if not flags else "WARN"
        print(f"  {ticker:6s} [{status}]: {len(rows):7d} bars  "
              f"time {time_lo}-{time_hi}  avg {avg_bars:.0f}/day  {ratio_s}")
        for flag in flags:
            print(f"          !! {flag}")

    # Distribution summary
    if summary_bars_per_day:
        buckets = collections.Counter()
        for v in summary_bars_per_day:
            if v < 100:
                buckets["<100 (likely empty/error)"] += 1
            elif v < 150:
                buckets["100-149 (RTH-only?)"] += 1
            elif v < 185:
                buckets["150-184 (partial extended)"] += 1
            elif v <= 200:
                buckets["185-200 (full extended OK)"] += 1
            else:
                buckets[">200 (possible duplicates)"] += 1

        print("\n  Bars/day distribution across all tickers:")
        for label, cnt in sorted(buckets.items()):
            print(f"    {label}: {cnt} ticker(s)")


# ── Entry point ────────────────────────────────────────────────────────────

def main():
    all_weeks   = list(weeks_range())
    total_weeks = len(all_weeks)
    print(f"FMP M5 EXTENDED weekly download -- {total_weeks} weeks x {len(TICKERS)} tickers")
    print(f"~{total_weeks * len(TICKERS) * SLEEP / 60:.0f} min at {SLEEP}s/request (no cache hits)")
    print(f"Output: {DATA}/{{TICKER}}_m5_extended.csv")
    print(f"NOTE: RTH files (*_m5_full.csv) are NOT touched.")
    print()

    for ticker in TICKERS:
        process_ticker(ticker)

    print("\nAll tickers downloaded.")
    verify_all()
    print("\nDone.")


if __name__ == "__main__":
    main()
