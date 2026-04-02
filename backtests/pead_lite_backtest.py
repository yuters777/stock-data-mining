"""
PEAD Lite Backtest — Part 1: Data Preparation + Baseline Test (TEST 0).

Tests the Post-Earnings Announcement Drift hypothesis:
stocks that gap on earnings and hold the gap tend to drift further.

Reads:
  - backtester/data/fmp_earnings.csv (993 rows, FMP earnings data)
  - Fetched_Data/{TICKER}_data.csv (M5 OHLCV bars, IST-encoded)

Produces:
  - backtest_output/pead_lite_events.csv (enriched earnings event table)
  - Console output with data prep summary and baseline test results

Usage:
    python backtests/pead_lite_backtest.py
"""

import sys
from pathlib import Path

# Ensure repo root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from utils.data_loader import load_m5_regsess

# --- Paths ---
_EARNINGS_CSV = _REPO_ROOT / "backtester" / "data" / "fmp_earnings.csv"
_OUTPUT_DIR = _REPO_ROOT / "backtest_output"
_OUTPUT_CSV = _OUTPUT_DIR / "pead_lite_events.csv"


# ---------------------------------------------------------------------------
# Part A: Data Prep Functions
# ---------------------------------------------------------------------------

def synthesize_4h_bars(m5_df: pd.DataFrame) -> pd.DataFrame:
    """Synthesize 4H bars from M5 data (already in ET).

    4H Bar 1: M5 bars from 09:30 to 13:25 ET (inclusive)
    4H Bar 2: M5 bars from 13:30 to 15:55 ET (inclusive)

    Returns DataFrame with columns:
        trading_day, bar_num (1 or 2), Open, High, Low, Close, Volume, Ticker
    """
    df = m5_df.copy()
    df["trading_day"] = df["Datetime"].dt.date
    hm = df["Datetime"].dt.hour * 60 + df["Datetime"].dt.minute

    # Bar 1: 09:30 (570) to 13:25 (805)
    # Bar 2: 13:30 (810) to 15:55 (955)
    conditions = [
        (hm >= 570) & (hm <= 805),
        (hm >= 810) & (hm <= 955),
    ]
    choices = [1, 2]
    df["bar_num"] = np.select(conditions, choices, default=0)
    df = df[df["bar_num"] > 0].copy()

    bars_4h = df.groupby(["Ticker", "trading_day", "bar_num"]).agg(
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
        Volume=("Volume", "sum"),
    ).reset_index()

    bars_4h = bars_4h.sort_values(["Ticker", "trading_day", "bar_num"]).reset_index(drop=True)
    return bars_4h


def load_earnings() -> pd.DataFrame:
    """Load and filter fmp_earnings.csv."""
    if not _EARNINGS_CSV.exists():
        print(f"ERROR: Earnings CSV not found: {_EARNINGS_CSV}")
        print("Run:  python utils/fmp_earnings_fetcher.py backfill")
        sys.exit(1)

    df = pd.read_csv(_EARNINGS_CSV)
    print(f"Total earnings in FMP CSV: {len(df)}")
    return df


def get_trading_days(bars_4h: pd.DataFrame) -> list:
    """Get sorted list of unique trading days from 4H bars."""
    days = sorted(bars_4h["trading_day"].unique())
    return days


def next_trading_day(day, trading_days: list):
    """Return the next trading day after `day`, or None."""
    for td in trading_days:
        if td > day:
            return td
    return None


def prev_trading_day(day, trading_days: list):
    """Return the trading day before `day`, or None."""
    prev = None
    for td in trading_days:
        if td >= day:
            return prev
        prev = td
    return prev


def nth_trading_day_after(day, n: int, trading_days: list):
    """Return the nth trading day after `day` (not including `day`), or None."""
    count = 0
    for td in trading_days:
        if td > day:
            count += 1
            if count == n:
                return td
    return None


def get_bar_close(bars_4h: pd.DataFrame, ticker: str, day, bar_num: int):
    """Get the close of a specific 4H bar."""
    mask = (bars_4h["Ticker"] == ticker) & (bars_4h["trading_day"] == day) & (bars_4h["bar_num"] == bar_num)
    rows = bars_4h[mask]
    if rows.empty:
        return None
    return rows.iloc[0]["Close"]


def get_bar_open(bars_4h: pd.DataFrame, ticker: str, day, bar_num: int):
    """Get the open of a specific 4H bar."""
    mask = (bars_4h["Ticker"] == ticker) & (bars_4h["trading_day"] == day) & (bars_4h["bar_num"] == bar_num)
    rows = bars_4h[mask]
    if rows.empty:
        return None
    return rows.iloc[0]["Open"]


def get_bar_row(bars_4h: pd.DataFrame, ticker: str, day, bar_num: int):
    """Get full 4H bar row."""
    mask = (bars_4h["Ticker"] == ticker) & (bars_4h["trading_day"] == day) & (bars_4h["bar_num"] == bar_num)
    rows = bars_4h[mask]
    if rows.empty:
        return None
    return rows.iloc[0]


def build_events(earnings_df: pd.DataFrame, ticker_4h: dict, ticker_trading_days: dict) -> pd.DataFrame:
    """Build enriched earnings event table.

    Args:
        earnings_df: Filtered earnings DataFrame.
        ticker_4h: Dict mapping ticker -> 4H bars DataFrame.
        ticker_trading_days: Dict mapping ticker -> sorted list of trading days.

    Returns:
        Tuple of (events DataFrame, count of earnings within M5 range).
    """
    # Available tickers with M5 data
    available_tickers = set(ticker_4h.keys())

    # Filter: eps_actual not null
    df = earnings_df.copy()
    df = df[df["eps_actual"].notna()].copy()
    print(f"Earnings with eps_actual not null: {len(df)}")

    events = []
    n_in_range = 0
    skipped = {"no_m5_data": [], "outside_range": [], "missing_bars": [], "weekend": []}

    for _, row in df.iterrows():
        ticker = row["ticker"]
        earnings_date_str = row["earnings_date"]
        time_of_day = str(row.get("time_of_day", "")).strip().upper()
        eps_surprise_pct = row.get("eps_surprise_pct")

        try:
            earnings_date = pd.Timestamp(earnings_date_str).date()
        except Exception:
            skipped["missing_bars"].append(f"{ticker} {earnings_date_str}: invalid date")
            continue

        # Check ticker has M5 data
        if ticker not in available_tickers:
            skipped["no_m5_data"].append(f"{ticker} {earnings_date}")
            continue

        bars_4h = ticker_4h[ticker]
        trading_days = ticker_trading_days[ticker]

        # Check if earnings_date or relevant dates are within M5 range
        if not trading_days:
            skipped["outside_range"].append(f"{ticker} {earnings_date}: no trading days")
            continue

        min_day = trading_days[0]
        max_day = trading_days[-1]

        # Count earnings within M5 data range
        if min_day <= earnings_date <= max_day:
            n_in_range += 1

        # Determine prior_close day, next_open day, entry_day
        if time_of_day == "BMO":
            # BMO: prior_close = day before earnings, next_open = earnings_date
            prior_close_day = prev_trading_day(earnings_date, trading_days)
            next_open_day = earnings_date
            entry_day = earnings_date
        else:
            # AMC (or null/unknown): prior_close = earnings_date, next_open = next trading day
            prior_close_day = earnings_date
            next_open_day = next_trading_day(earnings_date, trading_days)
            entry_day = next_open_day

        # Validate days exist
        if prior_close_day is None:
            skipped["outside_range"].append(f"{ticker} {earnings_date}: no prior close day")
            continue
        if next_open_day is None:
            skipped["outside_range"].append(f"{ticker} {earnings_date}: no next open day")
            continue
        if entry_day is None:
            skipped["outside_range"].append(f"{ticker} {earnings_date}: no entry day")
            continue

        # Check if days are in our data range
        if prior_close_day < min_day or prior_close_day > max_day:
            skipped["outside_range"].append(f"{ticker} {earnings_date}: prior_close_day {prior_close_day} outside range")
            continue
        if next_open_day < min_day or next_open_day > max_day:
            skipped["outside_range"].append(f"{ticker} {earnings_date}: next_open_day {next_open_day} outside range")
            continue

        # Get prior close (last 4H bar = bar 2 close)
        prior_close = get_bar_close(bars_4h, ticker, prior_close_day, 2)
        if prior_close is None:
            # Try bar 1 if bar 2 missing (partial day)
            prior_close = get_bar_close(bars_4h, ticker, prior_close_day, 1)
            if prior_close is None:
                skipped["missing_bars"].append(f"{ticker} {earnings_date}: no bar for prior_close on {prior_close_day}")
                continue

        # Get next open (first 4H bar = bar 1 open)
        next_open = get_bar_open(bars_4h, ticker, next_open_day, 1)
        if next_open is None:
            skipped["missing_bars"].append(f"{ticker} {earnings_date}: no bar for next_open on {next_open_day}")
            continue

        # Gap calculation
        gap_pct = (next_open - prior_close) / prior_close * 100
        gap_direction = "LONG" if gap_pct > 0 else "SHORT"

        # First 4H bar on entry day (bar 1)
        first_bar = get_bar_row(bars_4h, ticker, entry_day, 1)
        if first_bar is None:
            skipped["missing_bars"].append(f"{ticker} {earnings_date}: no first 4H bar on entry {entry_day}")
            continue

        first_4h_open = first_bar["Open"]
        first_4h_high = first_bar["High"]
        first_4h_low = first_bar["Low"]
        first_4h_close = first_bar["Close"]

        # Gap midpoint
        gap_midpoint = (prior_close + next_open) / 2

        # First bar holds: close stays on gap side of midpoint
        # For positive gap: first_4h_close > gap_midpoint
        # For negative gap: first_4h_close < gap_midpoint
        if gap_pct > 0:
            first_bar_holds = first_4h_close > gap_midpoint
        else:
            first_bar_holds = first_4h_close < gap_midpoint

        events.append({
            "ticker": ticker,
            "earnings_date": earnings_date,
            "time_of_day": time_of_day if time_of_day in ("AMC", "BMO") else "AMC",
            "eps_surprise_pct": eps_surprise_pct,
            "prior_close": round(prior_close, 4),
            "open_price": round(next_open, 4),
            "gap_pct": round(gap_pct, 4),
            "gap_direction": gap_direction,
            "entry_day": entry_day,
            "first_4h_open": round(first_4h_open, 4),
            "first_4h_high": round(first_4h_high, 4),
            "first_4h_low": round(first_4h_low, 4),
            "first_4h_close": round(first_4h_close, 4),
            "gap_midpoint": round(gap_midpoint, 4),
            "first_bar_holds": first_bar_holds,
        })

    events_df = pd.DataFrame(events)

    # Print skipped events
    for reason, items in skipped.items():
        if items:
            print(f"\nSkipped ({reason}): {len(items)}")
            for item in items:
                print(f"  {item}")

    return events_df, n_in_range


def print_data_prep_summary(earnings_df: pd.DataFrame, events_df: pd.DataFrame,
                            n_in_range: int = 0):
    """Print the data prep summary."""
    print("\n" + "=" * 50)
    print("=== PEAD Data Prep Summary ===")
    print("=" * 50)

    total = len(earnings_df)
    n_events = len(events_df)

    print(f"Total earnings in FMP CSV: {total}")
    print(f"Earnings within M5 range: {n_in_range}")
    print(f"Earnings with M5 data available: {n_events}")

    if n_events == 0:
        print("No qualifying events found.")
        return

    abs_gap = events_df["gap_pct"].abs()
    print(f"Gap >= 1%: {(abs_gap >= 1.0).sum()}")
    print(f"Gap >= 2%: {(abs_gap >= 2.0).sum()}")
    print(f"Gap >= 3%: {(abs_gap >= 3.0).sum()}")

    pos_gaps = (events_df["gap_pct"] > 0).sum()
    neg_gaps = (events_df["gap_pct"] < 0).sum()
    print(f"Positive gaps: {pos_gaps} | Negative gaps: {neg_gaps}")

    holds = events_df["first_bar_holds"].sum()
    # First bar holds with 2% gap threshold
    gap2 = events_df[abs_gap >= 2.0]
    holds_2pct = gap2["first_bar_holds"].sum() if len(gap2) > 0 else 0
    print(f"First bar holds (2% threshold): {holds_2pct}")


# ---------------------------------------------------------------------------
# Part B: Baseline Test (TEST 0)
# ---------------------------------------------------------------------------

def run_baseline_test(events_df: pd.DataFrame, ticker_4h: dict, ticker_trading_days: dict):
    """Run TEST 0: PEAD Baseline for events with |gap_pct| >= 2%."""
    abs_gap = events_df["gap_pct"].abs()
    test_events = events_df[abs_gap >= 2.0].copy()

    print("\n" + "=" * 50)
    print("=== TEST 0: PEAD Baseline (gap >= 2%) ===")
    print("=" * 50)
    print(f"N events: {len(test_events)}")

    if len(test_events) == 0:
        print("No events with |gap| >= 2%. Cannot run baseline.")
        return

    # Collect metrics for each event
    results = []
    for _, ev in test_events.iterrows():
        ticker = ev["ticker"]
        entry_day = ev["entry_day"]
        gap_pct = ev["gap_pct"]
        gap_sign = 1 if gap_pct > 0 else -1
        bars_4h = ticker_4h[ticker]
        trading_days = ticker_trading_days[ticker]

        entry_price = ev["open_price"]  # gap open price
        first_4h_close = ev["first_4h_close"]

        # Entry day close (bar 2 close on entry_day)
        entry_day_close = get_bar_close(bars_4h, ticker, entry_day, 2)

        # Day after entry
        day_after = next_trading_day(entry_day, trading_days)
        day_after_close = get_bar_close(bars_4h, ticker, day_after, 2) if day_after else None

        # 3 trading days after entry
        day_3 = nth_trading_day_after(entry_day, 3, trading_days)
        close_3d = get_bar_close(bars_4h, ticker, day_3, 2) if day_3 else None

        # 5 trading days after entry
        day_5 = nth_trading_day_after(entry_day, 5, trading_days)
        close_5d = get_bar_close(bars_4h, ticker, day_5, 2) if day_5 else None

        # 5th trading day close for simple strategy (10th 4H bar = bar 2 on day 5)
        exit_price_5d = close_5d

        # Metric 1: Next-day continuation
        next_day_continuation = None
        next_day_return = None
        if entry_day_close is not None and day_after_close is not None:
            move = day_after_close - entry_day_close
            next_day_continuation = (move * gap_sign) > 0
            next_day_return = (move / entry_day_close * 100) * gap_sign

        # Metric 2: 3-day drift
        drift_3d = None
        drift_3d_match = None
        if close_3d is not None:
            drift_3d = (close_3d - entry_price) / entry_price * 100
            drift_3d_match = (drift_3d * gap_sign) > 0

        # Metric 3: 5-day drift
        drift_5d = None
        drift_5d_match = None
        if close_5d is not None:
            drift_5d = (close_5d - entry_price) / entry_price * 100
            drift_5d_match = (drift_5d * gap_sign) > 0

        # Metric 4: Simple 4H-close entry, 5-day hold
        simple_return = None
        if first_4h_close is not None and exit_price_5d is not None:
            raw_return = (exit_price_5d - first_4h_close) / first_4h_close * 100
            simple_return = raw_return * gap_sign  # adjust sign for SHORT

        results.append({
            "ticker": ticker,
            "entry_day": entry_day,
            "gap_pct": gap_pct,
            "gap_sign": gap_sign,
            "eps_surprise_pct": ev["eps_surprise_pct"],
            "next_day_continuation": next_day_continuation,
            "next_day_return": next_day_return,
            "drift_3d": drift_3d,
            "drift_3d_match": drift_3d_match,
            "drift_5d": drift_5d,
            "drift_5d_match": drift_5d_match,
            "simple_return": simple_return,
        })

    res_df = pd.DataFrame(results)

    # --- Metric 1: Next-day continuation ---
    m1 = res_df.dropna(subset=["next_day_continuation"])
    if len(m1) > 0:
        hit_rate_1 = m1["next_day_continuation"].mean() * 100
        mean_ret_1 = m1["next_day_return"].mean()
        print(f"\nNext-day continuation:")
        print(f"  Hit rate: {hit_rate_1:.1f}%")
        print(f"  Mean next-day return in gap direction: {mean_ret_1:.2f}%")
    else:
        print("\nNext-day continuation: insufficient data")

    # --- Metric 2: 3-day drift ---
    m2 = res_df.dropna(subset=["drift_3d"])
    if len(m2) > 0:
        hit_rate_2 = m2["drift_3d_match"].mean() * 100
        mean_drift_2 = (m2["drift_3d"] * m2["gap_sign"]).mean()
        print(f"\n3-day drift:")
        print(f"  Hit rate: {hit_rate_2:.1f}%")
        print(f"  Mean 3-day drift: {mean_drift_2:.2f}%")
    else:
        print("\n3-day drift: insufficient data")

    # --- Metric 3: 5-day drift ---
    m3 = res_df.dropna(subset=["drift_5d"])
    if len(m3) > 0:
        hit_rate_3 = m3["drift_5d_match"].mean() * 100
        mean_drift_3 = (m3["drift_5d"] * m3["gap_sign"]).mean()
        print(f"\n5-day drift:")
        print(f"  Hit rate: {hit_rate_3:.1f}%")
        print(f"  Mean 5-day drift: {mean_drift_3:.2f}%")
    else:
        print("\n5-day drift: insufficient data")

    # --- Metric 4: Simple 4H-close entry, 5-day hold ---
    m4 = res_df.dropna(subset=["simple_return"])
    if len(m4) > 0:
        n4 = len(m4)
        mean_ret_4 = m4["simple_return"].mean()
        wins = (m4["simple_return"] > 0).sum()
        losses = (m4["simple_return"] <= 0).sum()
        wr = wins / n4 * 100

        gross_profit = m4.loc[m4["simple_return"] > 0, "simple_return"].sum()
        gross_loss = abs(m4.loc[m4["simple_return"] <= 0, "simple_return"].sum())
        pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        print(f"\nSimple 4H-close entry, 5-day hold:")
        print(f"  N: {n4}")
        print(f"  Mean return: {mean_ret_4:.2f}%")
        print(f"  Win rate: {wr:.1f}%")
        print(f"  Profit factor: {pf:.2f}")

        # Split by direction
        longs = m4[m4["gap_sign"] == 1]
        shorts = m4[m4["gap_sign"] == -1]

        if len(longs) > 0:
            l_wr = (longs["simple_return"] > 0).mean() * 100
            print(f"\n  Positive gaps (LONG): N={len(longs)}, mean={longs['simple_return'].mean():.2f}%, WR={l_wr:.1f}%")
        if len(shorts) > 0:
            s_wr = (shorts["simple_return"] > 0).mean() * 100
            print(f"  Negative gaps (SHORT): N={len(shorts)}, mean={shorts['simple_return'].mean():.2f}%, WR={s_wr:.1f}%")

        # By EPS surprise bucket
        print(f"\n  By EPS surprise bucket:")
        eps_col = m4["eps_surprise_pct"]
        # Use signed drift (drift in gap direction)
        m4_drift = m4.copy()
        m4_drift["signed_drift"] = m4_drift["simple_return"]

        beat_gt10 = m4_drift[eps_col > 10]
        beat_0_10 = m4_drift[(eps_col >= 0) & (eps_col <= 10)]
        miss_0_10 = m4_drift[(eps_col < 0) & (eps_col >= -10)]
        miss_gt10 = m4_drift[eps_col < -10]

        for label, bucket in [("Beat >10%", beat_gt10), ("Beat 0-10%", beat_0_10),
                               ("Miss 0-10%", miss_0_10), ("Miss >10%", miss_gt10)]:
            if len(bucket) > 0:
                print(f"    {label}:  N={len(bucket)}, mean drift={bucket['signed_drift'].mean():.2f}%")
            else:
                print(f"    {label}:  N=0")

        # Verdict
        # Use 5-day drift metrics for verdict (most representative)
        if len(m3) > 0:
            verdict_hr = m3["drift_5d_match"].mean() * 100
            verdict_mean = (m3["drift_5d"] * m3["gap_sign"]).mean()
        else:
            verdict_hr = wr
            verdict_mean = mean_ret_4

        print(f"\nVERDICT: ", end="")
        if verdict_hr > 60 and verdict_mean > 0.5:
            print("PROMISING")
            print(f"  PROMISING = hit rate > 60% AND mean > 0.5%")
        elif verdict_hr >= 55 or (0.2 <= verdict_mean <= 0.5):
            print("MARGINAL")
            print(f"  MARGINAL = hit rate 55-60% OR mean 0.2-0.5%")
        else:
            print("NO_EDGE")
            print(f"  NO_EDGE = hit rate < 55% AND mean < 0.2%")

        print(f"  (5-day hit rate: {verdict_hr:.1f}%, mean drift: {verdict_mean:.2f}%)")
    else:
        print("\nSimple 4H-close entry, 5-day hold: insufficient data")
        print("\nVERDICT: NO_EDGE (insufficient data)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("PEAD Lite Backtest — Part 1: Data Prep + Baseline")
    print("=" * 60)

    # Step 1: Load earnings data
    earnings_df = load_earnings()

    # Step 2: Identify tickers that have M5 data
    fetched_dir = _REPO_ROOT / "Fetched_Data"
    available_tickers = set()
    for f in fetched_dir.glob("*_data.csv"):
        ticker = f.stem.replace("_data", "")
        available_tickers.add(ticker)

    # Filter earnings to tickers with M5 data
    earnings_tickers = set(earnings_df["ticker"].unique())
    tickers_with_data = earnings_tickers & available_tickers
    print(f"Earnings tickers: {len(earnings_tickers)}")
    print(f"Tickers with M5 data: {len(available_tickers)}")
    print(f"Overlap: {len(tickers_with_data)}")

    # Step 3: Load M5 data and synthesize 4H bars per ticker
    print("\nLoading M5 data and synthesizing 4H bars...")
    ticker_4h = {}
    ticker_trading_days = {}
    for ticker in sorted(tickers_with_data):
        try:
            m5 = load_m5_regsess(ticker)
            bars_4h = synthesize_4h_bars(m5)
            ticker_4h[ticker] = bars_4h
            trading_days = get_trading_days(bars_4h)
            ticker_trading_days[ticker] = trading_days
            print(f"  {ticker}: {len(m5)} M5 bars -> {len(bars_4h)} 4H bars, "
                  f"{len(trading_days)} trading days "
                  f"({trading_days[0]} to {trading_days[-1]})")
        except (FileNotFoundError, ValueError) as e:
            print(f"  {ticker}: SKIPPED — {e}")

    # Step 4: Build earnings event table
    print("\nBuilding earnings event table...")
    events_df, n_in_range = build_events(earnings_df, ticker_4h, ticker_trading_days)

    if len(events_df) == 0:
        print("\nNo qualifying earnings events. Exiting.")
        return

    # Step 5: Print data prep summary
    print_data_prep_summary(earnings_df, events_df, n_in_range)

    # Step 6: Run baseline test
    run_baseline_test(events_df, ticker_4h, ticker_trading_days)

    # Step 7: Save events table
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    events_df.to_csv(_OUTPUT_CSV, index=False)
    print(f"\nEvents table saved to: {_OUTPUT_CSV}")
    print(f"Total events: {len(events_df)}")


if __name__ == "__main__":
    main()
