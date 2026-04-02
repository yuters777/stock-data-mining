"""
PEAD Lite Backtest — Data Preparation, Baseline Test, and Parameter Sweeps.

Tests the Post-Earnings Announcement Drift hypothesis:
stocks that gap on earnings and hold the gap tend to drift further.

Reads:
  - backtester/data/fmp_earnings.csv (993 rows, FMP earnings data)
  - Fetched_Data/{TICKER}_data.csv (M5 OHLCV bars, IST-encoded)

Produces:
  - backtest_output/pead_lite_events.csv (enriched earnings event table)
  - backtest_output/pead_lite_sweep_trades.csv (all sweep trade details)
  - Console output with data prep summary, baseline, and sweep results

Usage:
    python backtests/pead_lite_backtest.py            # baseline only
    python backtests/pead_lite_backtest.py --sweep     # full parameter sweep
"""

import argparse
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
_SWEEP_CSV = _OUTPUT_DIR / "pead_lite_sweep_trades.csv"


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
# Part C: Sweep Engine — core trade simulator used by all sweep tests
# ---------------------------------------------------------------------------

def get_subsequent_bars(bars_4h: pd.DataFrame, ticker: str,
                        entry_day, trading_days: list, max_bars: int):
    """Return list of 4H bar rows starting from bar 2 on entry_day.

    Yields up to `max_bars` bars (bar 2 of entry_day, then bar 1 & 2 of
    subsequent days).
    """
    result = []
    # bar 2 on entry day
    b2 = get_bar_row(bars_4h, ticker, entry_day, 2)
    if b2 is not None:
        result.append(b2)

    day = entry_day
    while len(result) < max_bars:
        day = next_trading_day(day, trading_days)
        if day is None:
            break
        for bn in [1, 2]:
            bar = get_bar_row(bars_4h, ticker, day, bn)
            if bar is not None:
                result.append(bar)
            if len(result) >= max_bars:
                break
    return result


def simulate_trade(ev, bars_4h, trading_days, max_bars=10,
                   exit_strategy="midpoint"):
    """Simulate a single trade and return result dict (or None if no data).

    Entry: first 4H bar close on entry_day (bar 1 close).
    Exit depends on exit_strategy:
      'midpoint'   — gap midpoint breach OR max_bars (spec default)
      'reversal'   — first 4H close against entry direction
      'ema9'       — 4H close crosses EMA9 against position
      'fixed5'     — exit at exactly bar 5 (no stop)
      'fixed10'    — exit at exactly bar 10 (no stop)
      'trailing50' — exit if any bar gives back >50% of max unrealized gain
    """
    ticker = ev["ticker"]
    entry_day = ev["entry_day"]
    gap_pct = ev["gap_pct"]
    gap_sign = 1 if gap_pct > 0 else -1
    entry_price = ev["first_4h_close"]
    gap_midpoint = ev["gap_midpoint"]

    if pd.isna(entry_price) or entry_price == 0:
        return None

    subsequent = get_subsequent_bars(bars_4h, ticker, entry_day,
                                     trading_days, max_bars)
    if not subsequent:
        return None

    # For EMA9 we need close prices including entry
    closes_for_ema = [entry_price]
    for bar in subsequent:
        closes_for_ema.append(bar["Close"])
    ema9_values = _ema(closes_for_ema, 9)

    exit_price = None
    bars_held = 0
    max_unrealized = 0.0

    for i, bar in enumerate(subsequent):
        bars_held = i + 1
        bar_close = bar["Close"]
        unrealized = (bar_close - entry_price) / entry_price * 100 * gap_sign
        if unrealized > max_unrealized:
            max_unrealized = unrealized

        if exit_strategy == "midpoint":
            # Check if close breaches gap midpoint against position
            if gap_sign == 1 and bar_close < gap_midpoint:
                exit_price = bar_close
                break
            if gap_sign == -1 and bar_close > gap_midpoint:
                exit_price = bar_close
                break
        elif exit_strategy == "reversal":
            # Close against entry direction
            move = (bar_close - entry_price) * gap_sign
            if move < 0:
                exit_price = bar_close
                break
        elif exit_strategy == "ema9":
            ema_val = ema9_values[i + 1]  # +1 because index 0 is entry
            if gap_sign == 1 and bar_close < ema_val:
                exit_price = bar_close
                break
            if gap_sign == -1 and bar_close > ema_val:
                exit_price = bar_close
                break
        elif exit_strategy == "fixed5":
            if bars_held == 5:
                exit_price = bar_close
                break
        elif exit_strategy == "fixed10":
            if bars_held == 10:
                exit_price = bar_close
                break
        elif exit_strategy == "trailing50":
            if max_unrealized > 0 and unrealized < max_unrealized * 0.5:
                exit_price = bar_close
                break

    # If no exit triggered, exit at last bar
    if exit_price is None:
        if subsequent:
            exit_price = subsequent[-1]["Close"]
        else:
            return None

    raw_return = (exit_price - entry_price) / entry_price * 100
    signed_return = raw_return * gap_sign

    return {
        "ticker": ticker,
        "entry_day": str(entry_day),
        "gap_pct": round(gap_pct, 4),
        "gap_sign": gap_sign,
        "eps_surprise_pct": ev.get("eps_surprise_pct"),
        "entry_price": round(entry_price, 4),
        "exit_price": round(exit_price, 4),
        "bars_held": bars_held,
        "raw_return_pct": round(raw_return, 4),
        "signed_return_pct": round(signed_return, 4),
        "exit_strategy": exit_strategy,
    }


def _ema(values, period):
    """Compute EMA for a list of values. Returns list of same length."""
    ema = [values[0]]
    k = 2 / (period + 1)
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def run_trades(events_df, ticker_4h, ticker_trading_days,
               gap_threshold=2.0, first_bar_filter="holds",
               max_bars=10, direction="both",
               eps_surprise_min=None, exit_strategy="midpoint"):
    """Run trades on filtered events and return list of result dicts."""
    df = events_df.copy()
    abs_gap = df["gap_pct"].abs()

    # Gap filter
    df = df[abs_gap >= gap_threshold]

    # Direction filter
    if direction == "long":
        df = df[df["gap_pct"] > 0]
    elif direction == "short":
        df = df[df["gap_pct"] < 0]

    # First bar filter
    if first_bar_filter == "holds":
        df = df[df["first_bar_holds"] == True]
    elif first_bar_filter == "direction":
        # First bar close in gap direction (above/below prior close)
        mask = ((df["gap_pct"] > 0) & (df["first_4h_close"] > df["prior_close"])) | \
               ((df["gap_pct"] < 0) & (df["first_4h_close"] < df["prior_close"]))
        df = df[mask]
    elif first_bar_filter == "half":
        # Direction filter + close in upper/lower half of bar range
        bar_range = df["first_4h_high"] - df["first_4h_low"]
        bar_mid = (df["first_4h_high"] + df["first_4h_low"]) / 2
        mask_dir = ((df["gap_pct"] > 0) & (df["first_4h_close"] > df["prior_close"])) | \
                   ((df["gap_pct"] < 0) & (df["first_4h_close"] < df["prior_close"]))
        mask_half = ((df["gap_pct"] > 0) & (df["first_4h_close"] > bar_mid)) | \
                    ((df["gap_pct"] < 0) & (df["first_4h_close"] < bar_mid))
        df = df[mask_dir & mask_half]
    # "none" = no filter

    # EPS surprise filter
    if eps_surprise_min is not None:
        df = df[df["eps_surprise_pct"].abs() >= eps_surprise_min]

    results = []
    for _, ev in df.iterrows():
        ticker = ev["ticker"]
        if ticker not in ticker_4h:
            continue
        res = simulate_trade(ev, ticker_4h[ticker],
                             ticker_trading_days[ticker],
                             max_bars=max_bars,
                             exit_strategy=exit_strategy)
        if res is not None:
            results.append(res)
    return results


def compute_metrics(trades):
    """Compute summary metrics from a list of trade dicts."""
    if not trades:
        return {"N": 0, "mean_pct": 0, "wr_pct": 0, "pf": 0,
                "sharpe": 0, "max_dd_pct": 0, "avg_bars": 0}
    rets = [t["signed_return_pct"] for t in trades]
    n = len(rets)
    mean_r = np.mean(rets)
    wins = sum(1 for r in rets if r > 0)
    wr = wins / n * 100
    gross_profit = sum(r for r in rets if r > 0)
    gross_loss = abs(sum(r for r in rets if r <= 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    std = np.std(rets, ddof=1) if n > 1 else 0
    sharpe = (mean_r / std) if std > 0 else 0

    # Max drawdown on cumulative equity curve
    cum = np.cumsum(rets)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = abs(dd.min()) if len(dd) > 0 else 0

    avg_bars = np.mean([t["bars_held"] for t in trades])

    return {
        "N": n,
        "mean_pct": round(mean_r, 2),
        "wr_pct": round(wr, 1),
        "pf": round(pf, 2),
        "sharpe": round(sharpe, 2),
        "max_dd_pct": round(max_dd, 2),
        "avg_bars": round(avg_bars, 1),
    }


def print_table(headers, rows, title=""):
    """Print a formatted ASCII table."""
    if title:
        print(f"\n{title}")
    col_widths = [max(len(str(h)), max((len(str(r[i])) for r in rows), default=0))
                  for i, h in enumerate(headers)]
    hdr = " | ".join(str(h).rjust(w) for h, w in zip(headers, col_widths))
    sep = "-+-".join("-" * w for w in col_widths)
    print(f"| {hdr} |")
    print(f"+-{sep}-+")
    for row in rows:
        line = " | ".join(str(row[i]).rjust(w) for i, w in enumerate(col_widths))
        print(f"| {line} |")


# ---------------------------------------------------------------------------
# Part D: Sweep Tests
# ---------------------------------------------------------------------------

def test1_gap_threshold_sweep(events_df, ticker_4h, ticker_trading_days):
    """TEST 1: GAP_THRESHOLD sweep."""
    print("\n" + "=" * 60)
    print("=== TEST 1: GAP_THRESHOLD Sweep ===")
    print("=" * 60)

    thresholds = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
    rows = []
    best_pf = 0
    best_thresh = 2.0

    for thresh in thresholds:
        trades = run_trades(events_df, ticker_4h, ticker_trading_days,
                            gap_threshold=thresh, first_bar_filter="holds",
                            max_bars=10, exit_strategy="midpoint")
        m = compute_metrics(trades)
        rows.append([f"{thresh:.1f}%", m["N"], m["mean_pct"], m["wr_pct"],
                      m["pf"], m["sharpe"], m["max_dd_pct"], m["avg_bars"]])
        if m["N"] >= 10 and m["pf"] > best_pf:
            best_pf = m["pf"]
            best_thresh = thresh

    print_table(["Gap%", "N", "Mean%", "WR%", "PF", "Sharpe", "MaxDD", "Bars"],
                rows, "Gap Threshold Sweep Results:")
    print(f"\nBest threshold (PF, N>=10): {best_thresh:.1f}%")
    return best_thresh


def test2_first_bar_filter(events_df, ticker_4h, ticker_trading_days):
    """TEST 2: FIRST_BAR_HOLDS filter impact."""
    print("\n" + "=" * 60)
    print("=== TEST 2: First Bar Filter Impact (gap >= 2%) ===")
    print("=" * 60)

    filters = [
        ("none", "No filter"),
        ("direction", "Direction"),
        ("half", "Half"),
        ("holds", "Holds (midpoint)"),
    ]
    base_mean = None
    rows = []
    for filt_key, filt_name in filters:
        trades = run_trades(events_df, ticker_4h, ticker_trading_days,
                            gap_threshold=2.0, first_bar_filter=filt_key,
                            max_bars=10, exit_strategy="midpoint")
        m = compute_metrics(trades)
        if filt_key == "none":
            base_mean = m["mean_pct"]
        lift = (m["mean_pct"] - base_mean) if base_mean is not None else 0
        rows.append([filt_name, m["N"], m["mean_pct"], m["wr_pct"],
                      m["pf"], f"{lift:+.2f}"])

    print_table(["Filter", "N", "Mean%", "WR%", "PF", "Lift vs (a)"], rows)


def test3_max_bars_sweep(events_df, ticker_4h, ticker_trading_days,
                         gap_threshold=2.0):
    """TEST 3: MAX_BARS sweep."""
    print("\n" + "=" * 60)
    print(f"=== TEST 3: MAX_BARS Sweep (gap >= {gap_threshold}%) ===")
    print("=" * 60)

    max_bars_values = [4, 6, 8, 10, 15, 20]
    rows = []
    for mb in max_bars_values:
        trades = run_trades(events_df, ticker_4h, ticker_trading_days,
                            gap_threshold=gap_threshold,
                            first_bar_filter="holds",
                            max_bars=mb, exit_strategy="midpoint")
        m = compute_metrics(trades)
        rows.append([mb, m["N"], m["mean_pct"], m["wr_pct"],
                      m["pf"], m["sharpe"], m["avg_bars"]])

    print_table(["MaxBars", "N", "Mean%", "WR%", "PF", "Sharpe", "AvgBars"],
                rows)


def test4_direction(events_df, ticker_4h, ticker_trading_days):
    """TEST 4: LONG-ONLY vs SHORT-ONLY vs SYMMETRIC."""
    print("\n" + "=" * 60)
    print("=== TEST 4: Direction Split (gap >= 2%) ===")
    print("=" * 60)

    directions = [("long", "LONG"), ("short", "SHORT"), ("both", "SYMMETRIC")]
    rows = []
    for dir_key, dir_name in directions:
        trades = run_trades(events_df, ticker_4h, ticker_trading_days,
                            gap_threshold=2.0, first_bar_filter="holds",
                            max_bars=10, direction=dir_key,
                            exit_strategy="midpoint")
        m = compute_metrics(trades)
        rows.append([dir_name, m["N"], m["mean_pct"], m["wr_pct"],
                      m["pf"], m["sharpe"]])

    print_table(["Direction", "N", "Mean%", "WR%", "PF", "Sharpe"], rows)


def test5_eps_surprise(events_df, ticker_4h, ticker_trading_days):
    """TEST 5: EPS SURPRISE as additional filter."""
    print("\n" + "=" * 60)
    print("=== TEST 5: EPS Surprise Filter (gap >= 2%) ===")
    print("=" * 60)

    thresholds = [0, 5, 10, 15, 20]
    rows = []
    for st in thresholds:
        trades = run_trades(events_df, ticker_4h, ticker_trading_days,
                            gap_threshold=2.0, first_bar_filter="holds",
                            max_bars=10, exit_strategy="midpoint",
                            eps_surprise_min=st if st > 0 else None)
        m = compute_metrics(trades)
        rows.append([f">={st}%", m["N"], m["mean_pct"], m["wr_pct"], m["pf"]])

    print_table(["EPS Thresh", "N", "Mean%", "WR%", "PF"], rows,
                "EPS Surprise Threshold Sweep:")

    # Combined: gap>=2% AND |eps_surprise|>=10%, split by beat/miss
    print("\nCombined filter: gap>=2%, first_bar_holds, |eps_surprise|>=10%")
    df = events_df.copy()
    abs_gap = df["gap_pct"].abs()
    df = df[(abs_gap >= 2.0) & (df["first_bar_holds"] == True)]
    df = df[df["eps_surprise_pct"].abs() >= 10]

    for label, sub in [("Beats (eps>0)", df[df["eps_surprise_pct"] > 0]),
                       ("Misses (eps<0)", df[df["eps_surprise_pct"] < 0])]:
        trades = []
        for _, ev in sub.iterrows():
            ticker = ev["ticker"]
            if ticker not in ticker_4h:
                continue
            res = simulate_trade(ev, ticker_4h[ticker],
                                 ticker_trading_days[ticker],
                                 max_bars=10, exit_strategy="midpoint")
            if res is not None:
                trades.append(res)
        m = compute_metrics(trades)
        print(f"  {label}: N={m['N']}, Mean={m['mean_pct']}%, "
              f"WR={m['wr_pct']}%, PF={m['pf']}")


def test6_exit_strategies(events_df, ticker_4h, ticker_trading_days):
    """TEST 6: Exit strategy comparison."""
    print("\n" + "=" * 60)
    print("=== TEST 6: Exit Strategy Comparison (gap >= 2%) ===")
    print("=" * 60)

    strategies = [
        ("midpoint", "Midpoint breach / max10"),
        ("reversal", "Any reversal bar"),
        ("ema9", "EMA9 touch"),
        ("fixed5", "Fixed 5 bars"),
        ("fixed10", "Fixed 10 bars"),
        ("trailing50", "Trailing 50% giveback"),
    ]
    rows = []
    for strat_key, strat_name in strategies:
        trades = run_trades(events_df, ticker_4h, ticker_trading_days,
                            gap_threshold=2.0, first_bar_filter="holds",
                            max_bars=10, exit_strategy=strat_key)
        m = compute_metrics(trades)
        rows.append([strat_name, m["N"], m["mean_pct"], m["wr_pct"],
                      m["pf"], m["avg_bars"]])

    print_table(["Exit", "N", "Mean%", "WR%", "PF", "AvgBars"], rows)


# ---------------------------------------------------------------------------
# Part E: Robustness Checks
# ---------------------------------------------------------------------------

def robustness_loto(events_df, ticker_4h, ticker_trading_days, **kwargs):
    """R1: Leave-one-ticker-out."""
    print("\n--- R1: Leave-One-Ticker-Out ---")
    tickers = sorted(events_df["ticker"].unique())
    base_trades = run_trades(events_df, ticker_4h, ticker_trading_days, **kwargs)
    base_m = compute_metrics(base_trades)
    base_pf = base_m["pf"]

    max_impact_ticker = None
    max_pf_drop = 0
    rows = []

    for t in tickers:
        sub = events_df[events_df["ticker"] != t]
        trades = run_trades(sub, ticker_4h, ticker_trading_days, **kwargs)
        m = compute_metrics(trades)
        pf_drop = base_pf - m["pf"] if base_pf != float("inf") else 0
        rows.append((t, m["N"], m["mean_pct"], m["pf"]))
        if abs(pf_drop) > abs(max_pf_drop):
            max_pf_drop = pf_drop
            max_impact_ticker = t

    for t, n, mean, pf in rows:
        print(f"  Without {t:6s}: N={n:3d}, Mean={mean:+.2f}%, PF={pf:.2f}")

    pf_drop_pct = (max_pf_drop / base_pf * 100) if base_pf > 0 and base_pf != float("inf") else 0
    print(f"\n  Max impact ticker: {max_impact_ticker} "
          f"(PF drop: {max_pf_drop:+.2f}, {pf_drop_pct:+.1f}%)")
    return max_impact_ticker, abs(pf_drop_pct)


def robustness_monthly(trades):
    """R2: Monthly returns."""
    print("\n--- R2: Monthly Returns ---")
    if not trades:
        print("  No trades.")
        return 0
    df = pd.DataFrame(trades)
    df["month"] = pd.to_datetime(df["entry_day"]).dt.to_period("M")
    grouped = df.groupby("month").agg(
        N=("signed_return_pct", "count"),
        mean_pct=("signed_return_pct", "mean"),
        total_pct=("signed_return_pct", "sum"),
    )
    total_pnl = grouped["total_pct"].sum()

    max_conc = 0
    for _, row in grouped.iterrows():
        wr_approx = "n/a"
        conc = abs(row["total_pct"]) / abs(total_pnl) * 100 if total_pnl != 0 else 0
        if conc > max_conc:
            max_conc = conc
        print(f"  {row.name}: N={int(row['N'])}, Mean={row['mean_pct']:.2f}%, "
              f"Total={row['total_pct']:.2f}% ({conc:.0f}% of P&L)")

    if total_pnl != 0:
        print(f"\n  Max single-month concentration: {max_conc:.1f}% of total P&L")
    return max_conc


def robustness_sector(trades):
    """R3: Sector concentration."""
    print("\n--- R3: Sector Concentration ---")
    SECTORS = {
        "mega_tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA"],
        "growth_semi": ["TSLA", "AMD", "SMCI", "PLTR", "AVGO", "ARM", "TSM",
                        "MU", "INTC"],
        "crypto_proxy": ["COIN", "MSTR", "MARA"],
        "finance": ["C", "GS", "V", "BA", "JPM"],
        "china_adr": ["BABA", "JD", "BIDU"],
        "consumer": ["COST"],
    }
    ticker_to_sector = {}
    for sector, tickers in SECTORS.items():
        for t in tickers:
            ticker_to_sector[t] = sector

    if not trades:
        print("  No trades.")
        return 0

    n_total = len(trades)
    sector_counts = {}
    sector_returns = {}
    for t in trades:
        sec = ticker_to_sector.get(t["ticker"], "other")
        sector_counts[sec] = sector_counts.get(sec, 0) + 1
        sector_returns.setdefault(sec, []).append(t["signed_return_pct"])

    max_conc = 0
    for sec in sorted(sector_counts.keys()):
        n = sector_counts[sec]
        mean_r = np.mean(sector_returns[sec])
        pct = n / n_total * 100
        if pct > max_conc:
            max_conc = pct
        print(f"  {sec:15s}: N={n:3d}, Mean={mean_r:+.2f}%, "
              f"{pct:.1f}% of trades")

    print(f"\n  Max sector concentration: {max_conc:.1f}%")
    return max_conc


def robustness_gap_corr(trades):
    """R4: Gap size vs return correlation."""
    print("\n--- R4: Gap Size vs Return Correlation ---")
    if len(trades) < 3:
        print("  Insufficient trades.")
        return 0

    gaps = [abs(t["gap_pct"]) for t in trades]
    rets = [t["signed_return_pct"] for t in trades]
    corr = np.corrcoef(gaps, rets)[0, 1]
    print(f"  Correlation(|gap_pct|, return_pct): {corr:.3f}")
    print(f"  Larger gap = larger drift: {'YES' if corr > 0.1 else 'NO' if corr < -0.1 else 'UNCLEAR'}")
    return round(corr, 3)


def robustness_beat_miss(trades):
    """R5: Earnings beat vs miss."""
    print("\n--- R5: Earnings Beat vs Miss ---")
    if not trades:
        print("  No trades.")
        return

    beats = [t for t in trades if t.get("eps_surprise_pct") is not None
             and t["eps_surprise_pct"] > 0]
    misses = [t for t in trades if t.get("eps_surprise_pct") is not None
              and t["eps_surprise_pct"] < 0]

    for label, group in [("Beats", beats), ("Misses", misses)]:
        m = compute_metrics(group)
        print(f"  {label:7s}: N={m['N']}, Mean={m['mean_pct']}%, "
              f"WR={m['wr_pct']}%, PF={m['pf']}")


# ---------------------------------------------------------------------------
# Part F: Full Sweep Orchestrator
# ---------------------------------------------------------------------------

def run_sweep(events_df, ticker_4h, ticker_trading_days):
    """Run all parameter sweeps and robustness checks."""
    print("\n" + "=" * 60)
    print("=== PEAD-lite Parameter Sweep Mode ===")
    print("=" * 60)

    all_sweep_trades = []

    # TEST 1
    best_gap = test1_gap_threshold_sweep(events_df, ticker_4h,
                                          ticker_trading_days)

    # TEST 2
    test2_first_bar_filter(events_df, ticker_4h, ticker_trading_days)

    # TEST 3
    test3_max_bars_sweep(events_df, ticker_4h, ticker_trading_days,
                         gap_threshold=best_gap)

    # TEST 4
    test4_direction(events_df, ticker_4h, ticker_trading_days)

    # TEST 5
    test5_eps_surprise(events_df, ticker_4h, ticker_trading_days)

    # TEST 6
    test6_exit_strategies(events_df, ticker_4h, ticker_trading_days)

    # --- Determine best config from sweeps ---
    # We'll search a focused grid of top candidates
    print("\n" + "=" * 60)
    print("=== Searching Best Configuration ===")
    print("=" * 60)

    best_config = {
        "gap_threshold": 2.0,
        "first_bar_filter": "holds",
        "max_bars": 10,
        "direction": "both",
        "eps_surprise_min": None,
        "exit_strategy": "midpoint",
    }
    best_score = -999

    for gt in [best_gap, 2.0, 2.5, 3.0]:
        for fbf in ["holds", "direction", "none"]:
            for mb in [8, 10, 15]:
                for es in ["midpoint", "ema9", "trailing50"]:
                    for eps_min in [None, 10]:
                        trades = run_trades(
                            events_df, ticker_4h, ticker_trading_days,
                            gap_threshold=gt, first_bar_filter=fbf,
                            max_bars=mb, exit_strategy=es,
                            eps_surprise_min=eps_min,
                        )
                        m = compute_metrics(trades)
                        if m["N"] < 10:
                            continue
                        # Score: balance PF, WR, and sample size
                        score = (m["pf"] * 0.4 + m["wr_pct"] / 100 * 0.3 +
                                 min(m["N"] / 50, 1.0) * 0.3)
                        if score > best_score:
                            best_score = score
                            best_config = {
                                "gap_threshold": gt,
                                "first_bar_filter": fbf,
                                "max_bars": mb,
                                "direction": "both",
                                "eps_surprise_min": eps_min,
                                "exit_strategy": es,
                            }

    print(f"\nBest config found:")
    for k, v in best_config.items():
        print(f"  {k}: {v}")

    # Run best config trades
    best_trades = run_trades(events_df, ticker_4h, ticker_trading_days,
                             **best_config)
    best_m = compute_metrics(best_trades)
    all_sweep_trades.extend(best_trades)

    # --- Robustness Checks ---
    print("\n" + "=" * 60)
    print("=== Robustness Checks (best config) ===")
    print("=" * 60)

    loto_ticker, loto_pct = robustness_loto(
        events_df, ticker_4h, ticker_trading_days, **best_config)
    monthly_conc = robustness_monthly(best_trades)
    sector_conc = robustness_sector(best_trades)
    gap_corr = robustness_gap_corr(best_trades)
    robustness_beat_miss(best_trades)

    # p-value
    p_val = None
    try:
        from scipy.stats import ttest_1samp
        rets = [t["signed_return_pct"] for t in best_trades]
        if len(rets) >= 2:
            _, p_val = ttest_1samp(rets, 0)
    except ImportError:
        pass

    # --- Final Summary ---
    print("\n" + "=" * 60)
    print("=== PEAD-lite Sweep Summary ===")
    print("=" * 60)

    print(f"\nBest Configuration:")
    print(f"  GAP_THRESHOLD: {best_config['gap_threshold']}%")
    print(f"  FIRST_BAR_FILTER: {best_config['first_bar_filter']}")
    print(f"  MAX_BARS: {best_config['max_bars']}")
    print(f"  DIRECTION: {best_config['direction']}")
    print(f"  EPS_SURPRISE_FILTER: >={best_config['eps_surprise_min']}%" if best_config['eps_surprise_min'] else "  EPS_SURPRISE_FILTER: none")
    print(f"  EXIT_STRATEGY: {best_config['exit_strategy']}")

    print(f"\nPerformance:")
    print(f"  N: {best_m['N']}")
    print(f"  Mean return: {best_m['mean_pct']}%")
    print(f"  Win rate: {best_m['wr_pct']}%")
    print(f"  Profit factor: {best_m['pf']}")
    print(f"  Sharpe: {best_m['sharpe']}")
    print(f"  Max drawdown: {best_m['max_dd_pct']}%")
    if p_val is not None:
        print(f"  p-value: {p_val:.4f}")
    else:
        print(f"  p-value: scipy not available")

    print(f"\nRobustness:")
    print(f"  LOTO max impact: {loto_pct:.1f}% (ticker: {loto_ticker})")
    print(f"  Monthly concentration: {monthly_conc:.1f}% in single month")
    print(f"  Sector concentration: {sector_conc:.1f}% in single sector")
    print(f"  Gap-return correlation: {gap_corr}")

    # Verdict
    validated = (best_m["N"] >= 30 and best_m["wr_pct"] >= 60 and
                 best_m["pf"] >= 2.0 and
                 (p_val is not None and p_val < 0.05) and
                 loto_pct < 25)
    marginal = not validated and (
        best_m["N"] >= 20 or best_m["wr_pct"] >= 55 or best_m["pf"] >= 1.5)

    if validated:
        verdict = "VALIDATED"
    elif marginal:
        verdict = "MARGINAL"
    else:
        verdict = "REJECTED"

    print(f"\nVERDICT: {verdict}")
    print(f"  VALIDATED = N>=30, WR>=60%, PF>=2.0, p<0.05, LOTO<25%")
    print(f"  MARGINAL = close to thresholds, needs more data")
    print(f"  REJECTED = clear failure on multiple criteria")

    # Save trade details
    if all_sweep_trades:
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        trade_df = pd.DataFrame(all_sweep_trades)
        trade_df.to_csv(_SWEEP_CSV, index=False)
        print(f"\nSweep trades saved to: {_SWEEP_CSV}")
        print(f"Total trades in best config: {len(all_sweep_trades)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_data():
    """Load earnings, M5, and 4H bar data. Returns (earnings_df, events_df, ticker_4h, ticker_trading_days)."""
    print("=" * 60)
    print("PEAD Lite Backtest — Data Loading")
    print("=" * 60)

    earnings_df = load_earnings()

    fetched_dir = _REPO_ROOT / "Fetched_Data"
    available_tickers = set()
    for f in fetched_dir.glob("*_data.csv"):
        ticker = f.stem.replace("_data", "")
        available_tickers.add(ticker)

    earnings_tickers = set(earnings_df["ticker"].unique())
    tickers_with_data = earnings_tickers & available_tickers
    print(f"Earnings tickers: {len(earnings_tickers)}")
    print(f"Tickers with M5 data: {len(available_tickers)}")
    print(f"Overlap: {len(tickers_with_data)}")

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

    print("\nBuilding earnings event table...")
    events_df, n_in_range = build_events(earnings_df, ticker_4h, ticker_trading_days)

    if len(events_df) == 0:
        print("\nNo qualifying earnings events. Exiting.")
        sys.exit(1)

    print_data_prep_summary(earnings_df, events_df, n_in_range)

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    events_df.to_csv(_OUTPUT_CSV, index=False)
    print(f"\nEvents table saved to: {_OUTPUT_CSV}")
    print(f"Total events: {len(events_df)}")

    return earnings_df, events_df, ticker_4h, ticker_trading_days


def main():
    parser = argparse.ArgumentParser(description="PEAD Lite Backtest")
    parser.add_argument("--sweep", action="store_true",
                        help="Run full parameter sweep + robustness checks")
    args = parser.parse_args()

    earnings_df, events_df, ticker_4h, ticker_trading_days = load_data()

    if args.sweep:
        run_sweep(events_df, ticker_4h, ticker_trading_days)
    else:
        run_baseline_test(events_df, ticker_4h, ticker_trading_days)


if __name__ == "__main__":
    main()
