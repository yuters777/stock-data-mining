#!/usr/bin/env python3
"""
Dataset Certification — Canary tests for M5 regular-session data.

Run this BEFORE any backtest to verify data integrity.

Usage:
    from utils.dataset_certification import certify_m5_data, certify_all_tickers
    result = certify_m5_data("TSLA")
    summary = certify_all_tickers()

Or run directly:
    python -m utils.dataset_certification
"""

import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Expected regular session: 09:30–15:55 ET (78 M5 bars)
_EXPECTED_FIRST_BAR = "09:30"
_EXPECTED_LAST_BAR = "15:55"
_MIN_BARS_PER_DAY = 70
_MAX_BARS_PER_DAY = 80
_SESSION_START_MINUTES = 9 * 60 + 30   # 09:30
_SESSION_END_MINUTES = 16 * 60         # 16:00
_MAX_DAY_GAP_BUSINESS_DAYS = 3

ALL_TICKERS = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU", "BTC",
    "C", "COIN", "COST", "ETH", "GOOGL", "GS", "INTC", "JPM", "MARA",
    "META", "MSFT", "MSTR", "MU", "NVDA", "PLTR", "SMCI", "SPY", "TSLA",
    "TSM", "V", "VIXY",
]


def certify_m5_data(
    ticker: str,
    data_dir: str = "backtest_output",
    suffix: str = "_m5_regsess_FIXED.csv",
) -> dict:
    """
    Run canary tests on M5 regular session data.

    Returns dict with pass/fail per test and details.

    Tests:
    1. Timezone: all timestamps between 09:30-16:00 ET
    2. Bar count: 70-80 bars per trading day (expect ~78)
    3. First bar: 09:30 ET every day
    4. Last bar: 15:50 or 15:55 ET every day
    5. No duplicate timestamps
    6. No session spillover (no bars before 09:30 or after 16:00)
    7. OHLC sanity: High >= Open,Close,Low; Low <= Open,Close,High
    8. No zero/negative prices
    9. Date range: continuous trading days (no unexpected gaps > 3 days)
    10. Close reasonability: last bar close within ±5% of prior day's last bar
    """
    repo_root = Path(__file__).resolve().parents[1]
    filepath = repo_root / data_dir / f"{ticker}{suffix}"

    result = {
        "ticker": ticker,
        "file": str(filepath),
        "exists": False,
        "tests": {},
        "overall": "FAIL",
        "total_rows": 0,
        "trading_days": 0,
        "date_range": "",
        "mean_bars_per_day": 0.0,
        "issues": [],
    }

    if not filepath.exists():
        result["issues"].append(f"File not found: {filepath}")
        return result

    result["exists"] = True
    df = pd.read_csv(filepath, parse_dates=["Datetime"])
    result["total_rows"] = len(df)

    if df.empty:
        result["issues"].append("Empty dataframe")
        return result

    df["date"] = df["Datetime"].dt.date
    df["time_str"] = df["Datetime"].dt.strftime("%H:%M")
    df["minutes"] = df["Datetime"].dt.hour * 60 + df["Datetime"].dt.minute

    dates = sorted(df["date"].unique())
    result["trading_days"] = len(dates)
    result["date_range"] = f"{dates[0]} to {dates[-1]}"

    bar_counts = df.groupby("date").size()
    result["mean_bars_per_day"] = round(bar_counts.mean(), 1)

    # Test 1: Timezone — all timestamps between 09:30-16:00 ET
    outside = df[(df["minutes"] < _SESSION_START_MINUTES) | (df["minutes"] >= _SESSION_END_MINUTES)]
    t1_pass = len(outside) == 0
    result["tests"]["1_timezone"] = {
        "pass": t1_pass,
        "detail": f"{len(outside)} bars outside 09:30-16:00" if not t1_pass else "All bars in session",
    }

    # Test 2: Bar count 70-80 per day
    low_days = bar_counts[bar_counts < _MIN_BARS_PER_DAY]
    high_days = bar_counts[bar_counts > _MAX_BARS_PER_DAY]
    # Allow early-close days (< 70 bars is OK if it's a known half-day)
    # Flag if more than 5% of days have low bars
    pct_low = len(low_days) / len(dates) * 100
    t2_pass = pct_low < 5 and len(high_days) == 0
    detail = f"{len(low_days)} low-bar days ({pct_low:.1f}%), {len(high_days)} high-bar days"
    if not t2_pass and pct_low >= 50:
        detail += " — LIKELY TRUNCATED DATA"
    result["tests"]["2_bar_count"] = {"pass": t2_pass, "detail": detail}

    # Test 3: First bar 09:30 every day
    first_bars = df.groupby("date")["time_str"].min()
    bad_first = first_bars[first_bars != _EXPECTED_FIRST_BAR]
    t3_pass = len(bad_first) == 0
    result["tests"]["3_first_bar"] = {
        "pass": t3_pass,
        "detail": f"{len(bad_first)} days with wrong first bar" if not t3_pass else "All days start 09:30",
    }

    # Test 4: Last bar 15:50 or 15:55 every day
    last_bars = df.groupby("date")["time_str"].max()
    acceptable_last = {"15:50", "15:55"}
    bad_last = last_bars[~last_bars.isin(acceptable_last)]
    # Allow early-close days (last bar at 10:00 or 13:00 for half-days)
    known_early_close_lasts = {"10:00", "10:25", "10:30", "13:00"}
    truly_bad = bad_last[~bad_last.isin(known_early_close_lasts)]
    # If ALL days have bad last bars, it's a systemic issue
    pct_bad = len(bad_last) / len(dates) * 100
    t4_pass = pct_bad < 5
    detail = f"Last bar mode: {last_bars.mode()[0]}, {len(bad_last)} non-standard ({pct_bad:.1f}%)"
    if not t4_pass and pct_bad >= 95:
        detail += f" — SYSTEMATIC TRUNCATION at {last_bars.mode()[0]}"
    result["tests"]["4_last_bar"] = {"pass": t4_pass, "detail": detail}

    # Test 5: No duplicate timestamps
    dupes = df[df.duplicated(subset=["Datetime"], keep=False)]
    t5_pass = len(dupes) == 0
    result["tests"]["5_no_duplicates"] = {
        "pass": t5_pass,
        "detail": f"{len(dupes)} duplicate rows" if not t5_pass else "No duplicates",
    }

    # Test 6: No session spillover
    pre_market = df[df["minutes"] < _SESSION_START_MINUTES]
    post_market = df[df["minutes"] >= _SESSION_END_MINUTES]
    t6_pass = len(pre_market) == 0 and len(post_market) == 0
    result["tests"]["6_no_spillover"] = {
        "pass": t6_pass,
        "detail": f"{len(pre_market)} pre-market, {len(post_market)} post-market" if not t6_pass else "No spillover",
    }

    # Test 7: OHLC sanity
    ohlc_issues = 0
    if "High" in df.columns and "Low" in df.columns:
        bad_high = df[df["High"] < df[["Open", "Close"]].max(axis=1)]
        bad_low = df[df["Low"] > df[["Open", "Close"]].min(axis=1)]
        ohlc_issues = len(bad_high) + len(bad_low)
    t7_pass = ohlc_issues == 0
    result["tests"]["7_ohlc_sanity"] = {
        "pass": t7_pass,
        "detail": f"{ohlc_issues} OHLC violations" if not t7_pass else "OHLC consistent",
    }

    # Test 8: No zero/negative prices
    price_cols = [c for c in ["Open", "High", "Low", "Close"] if c in df.columns]
    bad_prices = 0
    for col in price_cols:
        bad_prices += (df[col] <= 0).sum()
    t8_pass = bad_prices == 0
    result["tests"]["8_no_zero_prices"] = {
        "pass": t8_pass,
        "detail": f"{bad_prices} zero/negative prices" if not t8_pass else "All prices positive",
    }

    # Test 9: Date continuity (no gaps > 3 business days)
    big_gaps = []
    for i in range(1, len(dates)):
        gap = (dates[i] - dates[i - 1]).days
        if gap > _MAX_DAY_GAP_BUSINESS_DAYS + 2:  # +2 for weekends
            big_gaps.append((dates[i - 1], dates[i], gap))
    t9_pass = len(big_gaps) == 0
    result["tests"]["9_date_continuity"] = {
        "pass": t9_pass,
        "detail": f"{len(big_gaps)} gaps > 5 calendar days" if not t9_pass else "Continuous coverage",
    }

    # Test 10: Close reasonability (day-over-day)
    last_close_per_day = df.groupby("date")["Close"].last()
    pct_changes = last_close_per_day.pct_change().abs()
    extreme = pct_changes[pct_changes > 0.05].dropna()
    t10_pass = len(extreme) == 0
    result["tests"]["10_close_reasonability"] = {
        "pass": t10_pass,
        "detail": f"{len(extreme)} days with >5% close change" if not t10_pass else "All closes reasonable",
    }

    # Overall
    all_pass = all(t["pass"] for t in result["tests"].values())
    # Critical failures
    critical_fail = not result["tests"]["2_bar_count"]["pass"] or not result["tests"]["4_last_bar"]["pass"]
    if all_pass:
        result["overall"] = "PASS"
    elif critical_fail:
        result["overall"] = "FAIL"
    else:
        result["overall"] = "WARN"

    # Collect issues
    for tname, tdata in result["tests"].items():
        if not tdata["pass"]:
            result["issues"].append(f"{tname}: {tdata['detail']}")

    return result


def certify_all_tickers(
    tickers: Optional[list] = None,
    data_dir: str = "backtest_output",
    suffix: str = "_m5_regsess_FIXED.csv",
) -> pd.DataFrame:
    """Run certification on all tickers, return summary DataFrame."""
    if tickers is None:
        tickers = ALL_TICKERS

    rows = []
    for ticker in tickers:
        r = certify_m5_data(ticker, data_dir=data_dir, suffix=suffix)
        row = {
            "Ticker": ticker,
            "Overall": r["overall"],
            "Rows": r["total_rows"],
            "Days": r["trading_days"],
            "Bars/Day": r["mean_bars_per_day"],
            "Date Range": r["date_range"],
            "Issues": "; ".join(r["issues"]) if r["issues"] else "",
        }
        # Add individual test results
        for tname, tdata in r.get("tests", {}).items():
            row[tname] = "PASS" if tdata["pass"] else "FAIL"
        rows.append(row)

    return pd.DataFrame(rows)


def golden_day_audit(
    ticker: str,
    dates: list,
    reference_closes: dict,
    data_dir: str = "backtest_output",
    suffix: str = "_m5_regsess_FIXED.csv",
    tolerance: float = 0.50,
) -> dict:
    """
    Compare specific dates' closes against known reference prices.

    Parameters
    ----------
    ticker : str
        Stock symbol.
    dates : list
        List of date strings "YYYY-MM-DD" to check.
    reference_closes : dict
        {"YYYY-MM-DD": expected_close_price, ...}
    tolerance : float
        Maximum acceptable difference in dollars. Default $0.50.

    Returns
    -------
    dict with per-date results and overall pass/fail.
    """
    repo_root = Path(__file__).resolve().parents[1]
    filepath = repo_root / data_dir / f"{ticker}{suffix}"

    result = {
        "ticker": ticker,
        "tolerance": tolerance,
        "checks": [],
        "overall": "FAIL",
    }

    if not filepath.exists():
        result["error"] = f"File not found: {filepath}"
        return result

    df = pd.read_csv(filepath, parse_dates=["Datetime"])
    df["date_str"] = df["Datetime"].dt.strftime("%Y-%m-%d")

    all_pass = True
    for date_str in dates:
        day_data = df[df["date_str"] == date_str]
        check = {"date": date_str, "pass": False, "detail": ""}

        if day_data.empty:
            check["detail"] = "Date not found in data"
            all_pass = False
        else:
            last_close = day_data.iloc[-1]["Close"]
            check["our_close"] = round(last_close, 2)
            check["our_close_time"] = day_data.iloc[-1]["Datetime"].strftime("%H:%M")

            if date_str in reference_closes:
                ref = reference_closes[date_str]
                diff = abs(last_close - ref)
                check["reference_close"] = ref
                check["diff"] = round(diff, 2)
                check["pass"] = diff <= tolerance
                check["detail"] = f"Our={last_close:.2f} Ref={ref:.2f} Δ=${diff:.2f}"
                if not check["pass"]:
                    all_pass = False
            else:
                check["detail"] = "No reference price provided"
                check["pass"] = True  # Can't fail without reference

        result["checks"].append(check)

    result["overall"] = "PASS" if all_pass else "FAIL"
    return result


# ── CLI entrypoint ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    tickers = sys.argv[1:] if len(sys.argv) > 1 else ALL_TICKERS
    summary = certify_all_tickers(tickers)

    print("\n" + "=" * 80)
    print("DATASET CERTIFICATION RESULTS")
    print("=" * 80)

    pass_count = (summary["Overall"] == "PASS").sum()
    warn_count = (summary["Overall"] == "WARN").sum()
    fail_count = (summary["Overall"] == "FAIL").sum()
    print(f"\nPASS: {pass_count}  |  WARN: {warn_count}  |  FAIL: {fail_count}  |  Total: {len(summary)}")

    print("\n" + "-" * 80)
    for _, row in summary.iterrows():
        status = "✅" if row["Overall"] == "PASS" else ("⚠️" if row["Overall"] == "WARN" else "❌")
        print(f"{status} {row['Ticker']:<6} {row['Overall']:<5} | {row['Rows']:>6} rows | "
              f"{row['Days']:>3} days | {row['Bars/Day']:>5.1f} bars/day | {row['Date Range']}")
        if row["Issues"]:
            for issue in row["Issues"].split("; "):
                print(f"       └─ {issue}")

    print("\n" + "=" * 80)
