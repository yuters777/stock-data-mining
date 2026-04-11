#!/usr/bin/env python3
"""FMP 5-Year Dataset Certification — validates Fetched_Data/ against universe."""
import os, sys, json, argparse
from datetime import datetime
import numpy as np
import pandas as pd

DATA_DIR = "Fetched_Data"
OUT_DIR = "certification_results"
OUT_FILE = os.path.join(OUT_DIR, "fmp_5yr_cert.json")
FRED_FILES = {"VIXCLS_FRED_real.csv", "VXVCLS.csv"}

UNIVERSE_EQUITY = [
    "AAPL","AMD","AMZN","ARM","AVGO","BA","BABA","BIDU","C","COIN","COST",
    "GOOGL","GS","INTC","JD","JPM","MARA","META","MSFT","MSTR","MU","NVDA",
    "PLTR","SMCI","SPY","TSLA","TSM","V","VIXY",
]
UNIVERSE_CRYPTO = ["BTC", "ETH"]
UNIVERSE_ALL = UNIVERSE_EQUITY + UNIVERSE_CRYPTO

RTH_START, RTH_END = "13:30", "19:55"   # UTC naive = 09:30–15:55 ET
RTH_FULL_THRESHOLD = 70                  # bars; full-coverage day
RTH_LOW_THRESHOLD = 60                   # bars; flag if below


def find_file(ticker):
    for suffix in ["_data.csv", "_crypto_data.csv"]:
        p = os.path.join(DATA_DIR, f"{ticker}{suffix}")
        if os.path.exists(p):
            return p
    return None


def discover_extras():
    universe_files = set()
    for t in UNIVERSE_ALL:
        for s in ["_data.csv", "_crypto_data.csv"]:
            universe_files.add(f"{t}{s}")
    return sorted(
        f for f in os.listdir(DATA_DIR)
        if f.endswith(".csv") and f not in FRED_FILES and f not in universe_files
    )


def certify(ticker):
    res = {
        "ticker": ticker, "status": "CERTIFIED", "issues": [],
        "rows": None, "dates": None, "years": None, "rth_per_day": None,
        "checks": {},
    }

    def ok(k, msg=""): res["checks"][k] = {"pass": True, "msg": str(msg)}
    def fail(k, msg):
        res["checks"][k] = {"pass": False, "msg": str(msg)}
        res["issues"].append(f"[{k}] {msg}")
        res["status"] = "FAILED"

    # 1 — file exists and loads with expected columns
    path = find_file(ticker)
    if path is None:
        fail("1_file", "file not found")
        return res
    try:
        df = pd.read_csv(path, parse_dates=["Datetime"])
    except Exception as e:
        fail("1_file", f"load error: {e}")
        return res
    missing_cols = {"Datetime","Open","High","Low","Close","Volume","Ticker"} - set(df.columns)
    if missing_cols:
        fail("1_file", f"missing columns: {missing_cols}")
        return res
    ok("1_file", os.path.basename(path))

    # 2 — row count
    res["rows"] = len(df)
    if len(df) < 10_000:
        fail("2_rows", f"{len(df):,} rows < 10,000")
    else:
        ok("2_rows", f"{len(df):,}")

    # 3 — date range
    df["_date"] = df["Datetime"].dt.date
    dates = np.sort(df["_date"].unique())
    res["dates"] = len(dates)
    years = sorted({d.year for d in dates})
    res["years"] = len(years)
    ok("3_range", f"{dates[0]} → {dates[-1]}, {len(years)} yr(s)")

    # 4 — trading days per year (flag <80 for complete years; exempt 2021 start and 2026)
    by_year = df.groupby(df["Datetime"].dt.year)["_date"].nunique()
    complete_years = {yr for yr in years if yr not in {years[0], years[-1]}}
    low_years = {yr: int(cnt) for yr, cnt in by_year.items()
                 if yr in complete_years and cnt < 80}
    if low_years:
        fail("4_dates_yr", f"<80 dates in complete year(s): {low_years}")
    else:
        ok("4_dates_yr", dict(by_year.astype(int)))

    crypto = ticker in UNIVERSE_CRYPTO

    # 5-7 — RTH checks (equity only)
    if not crypto:
        df["_t"] = df["Datetime"].dt.strftime("%H:%M")
        rth = df[(df["_t"] >= RTH_START) & (df["_t"] <= RTH_END)]
        rth_by_date = rth.groupby("_date").size()
        rth_mean = float(rth_by_date.mean())
        res["rth_per_day"] = round(rth_mean, 1)
        full_dates = rth_by_date[rth_by_date >= RTH_FULL_THRESHOLD].index
        low_rth_days = int((rth_by_date < RTH_LOW_THRESHOLD).sum())

        if low_rth_days > 5:
            fail("5_rth", f"{low_rth_days} dates with <{RTH_LOW_THRESHOLD} RTH bars; mean={rth_mean:.1f}")
        else:
            ok("5_rth", f"mean={rth_mean:.1f}/day")

        if len(full_dates):
            rth_full = rth[rth["_date"].isin(full_dates)]
            bad_first = int((rth_full.groupby("_date")["_t"].min() != RTH_START).sum())
            bad_last  = int((rth_full.groupby("_date")["_t"].max() != RTH_END).sum())
            if bad_first: fail("6_first", f"{bad_first} full days missing 13:30 bar")
            else:         ok("6_first", "13:30 ✓")
            if bad_last:  fail("7_last",  f"{bad_last} full days missing 19:55 bar")
            else:         ok("7_last",  "19:55 ✓")
        else:
            ok("6_first", "no full-coverage dates"); ok("7_last", "no full-coverage dates")
    else:
        res["rth_per_day"] = None
        ok("5_rth", "crypto-skip"); ok("6_first", "crypto-skip"); ok("7_last", "crypto-skip")

    # 8 — OHLC sanity (tolerance 1e-6 for float precision)
    o, h, l, c = df["Open"], df["High"], df["Low"], df["Close"]
    eps = 1e-6
    bad_high = int((h < np.maximum(o, c) - eps).sum())
    bad_low  = int((l > np.minimum(o, c) + eps).sum())
    bad_zero = int(((o <= 0) | (h <= 0) | (l <= 0) | (c <= 0)).sum())
    if bad_high or bad_low or bad_zero:
        fail("8_ohlc", f"bad_high={bad_high} bad_low={bad_low} zero/neg={bad_zero}")
    else:
        ok("8_ohlc")

    # 9 — no duplicate timestamps
    dupes = int(df["Datetime"].duplicated().sum())
    if dupes: fail("9_dupes", f"{dupes} duplicate timestamps")
    else:     ok("9_dupes")

    # 10 — chronological order
    if not df["Datetime"].is_monotonic_increasing:
        fail("10_order", "not sorted chronologically")
    else:
        ok("10_order")

    # 11 — no weekend bars (equity only)
    if not crypto:
        wk = int((df["Datetime"].dt.dayofweek >= 5).sum())
        if wk: fail("11_weekends", f"{wk} weekend bars")
        else:  ok("11_weekends")
    else:
        ok("11_weekends", "crypto-skip")

    # 12 — intraday price continuity: flag >15% close→next_open gaps within same date
    df_s = df.sort_values("Datetime")
    same_day = df_s["_date"] == df_s["_date"].shift(-1)
    gap = ((df_s["Open"].shift(-1) - df_s["Close"]).abs() / df_s["Close"])
    big_gaps = int((same_day & (gap > 0.15)).sum())
    if big_gaps: fail("12_continuity", f"{big_gaps} intraday gaps >15%")
    else:        ok("12_continuity")

    return res


def fmt_check(res, key):
    c = res["checks"].get(key, {})
    return "OK" if c.get("pass") else "!!"


def main():
    parser = argparse.ArgumentParser(description="FMP 5-Year Dataset Certification")
    parser.add_argument("--ticker", help="Certify a single ticker (default: all)")
    args = parser.parse_args()

    tickers = [args.ticker.upper()] if args.ticker else UNIVERSE_ALL

    print("=== FMP 5-Year Dataset Certification ===\n")

    if not args.ticker:
        found   = [t for t in UNIVERSE_ALL if find_file(t)]
        missing = [t for t in UNIVERSE_ALL if not find_file(t)]
        extras  = discover_extras()
        print(f"UNIVERSE COVERAGE: Found {len(found)}/{len(UNIVERSE_ALL)}, "
              f"Missing: {missing or 'none'}, Extra: {extras or 'none'}\n")

    results = [certify(t) for t in tickers]

    # Table
    hdr = f"{'TICKER':<7} {'ROWS':>8} {'DATES':>6} {'YRS':>4} {'RTH/d':>6}  "
    hdr += "FILE ROWS RNG  DYR  RTH  1ST  LST  OHLC DUP  ORD  WKD  GAP  STATUS"
    print(hdr)
    print("─" * len(hdr))

    checks = ["1_file","2_rows","3_range","4_dates_yr","5_rth","6_first",
              "7_last","8_ohlc","9_dupes","10_order","11_weekends","12_continuity"]

    for r in results:
        rth = f"{r['rth_per_day']:.0f}" if r["rth_per_day"] is not None else "24/7"
        cols = (f"{r['ticker']:<7} {(r['rows'] or 0):>8,} {(r['dates'] or 0):>6} "
                f"{(r['years'] or 0):>4} {rth:>6}  "
                + "  ".join(fmt_check(r, k) for k in checks)
                + f"  {r['status']}")
        print(cols)
        for issue in r.get("issues", []):
            print(f"         ↳ {issue}")

    print()
    print("SPARSE DATA WARNING: ~106 dates/year = FMP Starter plan rate limit, not corruption")
    print()
    certified = sum(1 for r in results if r["status"] == "CERTIFIED")
    failed = len(results) - certified
    print(f"OVERALL: {certified} CERTIFIED | {failed} FAILED")

    # Save JSON
    os.makedirs(OUT_DIR, exist_ok=True)
    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "universe_equity": UNIVERSE_EQUITY,
        "universe_crypto": UNIVERSE_CRYPTO,
        "summary": {"total": len(results), "certified": certified, "failed": failed},
        "results": results,
    }
    with open(OUT_FILE, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"\nJSON saved → {OUT_FILE}")


if __name__ == "__main__":
    main()
