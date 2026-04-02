"""
PEAD Lite Backtest — Data Preparation, Baseline Test (TEST 0), and Parameter Sweeps.

Tests the Post-Earnings Announcement Drift hypothesis:
stocks that gap on earnings and hold the gap tend to drift further.

Reads:
  - backtester/data/fmp_earnings.csv (993 rows, FMP earnings data)
  - Fetched_Data/{TICKER}_data.csv (M5 OHLCV bars, IST-encoded)

Produces:
  - backtest_output/pead_lite_events.csv (enriched earnings event table)
  - backtest_output/pead_lite_sweep_trades.csv (all sweep trade details)
  - Console output with data prep summary, baseline and sweep results

Usage:
    python backtests/pead_lite_backtest.py            # baseline only
    python backtests/pead_lite_backtest.py --sweep     # baseline + parameter sweeps
"""

import argparse
import sys
from pathlib import Path

# Ensure repo root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

try:
    from scipy import stats as scipy_stats
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

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
    """
    df = m5_df.copy()
    df["trading_day"] = df["Datetime"].dt.date
    hm = df["Datetime"].dt.hour * 60 + df["Datetime"].dt.minute

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
    return sorted(bars_4h["trading_day"].unique())


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


def get_forward_bars(bars_4h: pd.DataFrame, ticker: str, entry_day,
                     trading_days: list, max_bars: int):
    """Get up to max_bars 4H bars starting from bar 2 on entry_day.

    Returns list of dicts with bar info (day, bar_num, Open, High, Low, Close).
    Entry is at first bar close (bar 1), so forward bars start from bar 2.
    """
    result = []
    # Start with bar 2 on entry day
    day = entry_day
    bar_num = 2
    count = 0
    while count < max_bars:
        row = get_bar_row(bars_4h, ticker, day, bar_num)
        if row is None:
            break
        result.append({
            "day": day,
            "bar_num": bar_num,
            "Open": row["Open"],
            "High": row["High"],
            "Low": row["Low"],
            "Close": row["Close"],
        })
        count += 1
        if bar_num == 2:
            day = next_trading_day(day, trading_days)
            if day is None:
                break
            bar_num = 1
        else:
            bar_num = 2
    return result


def build_events(earnings_df: pd.DataFrame, ticker_4h: dict,
                 ticker_trading_days: dict) -> pd.DataFrame:
    """Build enriched earnings event table."""
    available_tickers = set(ticker_4h.keys())
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

        if ticker not in available_tickers:
            skipped["no_m5_data"].append(f"{ticker} {earnings_date}")
            continue

        bars_4h = ticker_4h[ticker]
        trading_days = ticker_trading_days[ticker]

        if not trading_days:
            skipped["outside_range"].append(f"{ticker} {earnings_date}: no trading days")
            continue

        min_day = trading_days[0]
        max_day = trading_days[-1]

        if min_day <= earnings_date <= max_day:
            n_in_range += 1

        if time_of_day == "BMO":
            prior_close_day = prev_trading_day(earnings_date, trading_days)
            next_open_day = earnings_date
            entry_day = earnings_date
        else:
            prior_close_day = earnings_date
            next_open_day = next_trading_day(earnings_date, trading_days)
            entry_day = next_open_day

        if prior_close_day is None:
            skipped["outside_range"].append(f"{ticker} {earnings_date}: no prior close day")
            continue
        if next_open_day is None:
            skipped["outside_range"].append(f"{ticker} {earnings_date}: no next open day")
            continue
        if entry_day is None:
            skipped["outside_range"].append(f"{ticker} {earnings_date}: no entry day")
            continue
        if prior_close_day < min_day or prior_close_day > max_day:
            skipped["outside_range"].append(f"{ticker} {earnings_date}: prior_close_day outside range")
            continue
        if next_open_day < min_day or next_open_day > max_day:
            skipped["outside_range"].append(f"{ticker} {earnings_date}: next_open_day outside range")
            continue

        prior_close = get_bar_close(bars_4h, ticker, prior_close_day, 2)
        if prior_close is None:
            prior_close = get_bar_close(bars_4h, ticker, prior_close_day, 1)
            if prior_close is None:
                skipped["missing_bars"].append(f"{ticker} {earnings_date}: no bar for prior_close")
                continue

        next_open = get_bar_open(bars_4h, ticker, next_open_day, 1)
        if next_open is None:
            skipped["missing_bars"].append(f"{ticker} {earnings_date}: no bar for next_open")
            continue

        gap_pct = (next_open - prior_close) / prior_close * 100
        gap_direction = "LONG" if gap_pct > 0 else "SHORT"

        first_bar = get_bar_row(bars_4h, ticker, entry_day, 1)
        if first_bar is None:
            skipped["missing_bars"].append(f"{ticker} {earnings_date}: no first 4H bar")
            continue

        first_4h_open = first_bar["Open"]
        first_4h_high = first_bar["High"]
        first_4h_low = first_bar["Low"]
        first_4h_close = first_bar["Close"]

        gap_midpoint = (prior_close + next_open) / 2

        if gap_pct > 0:
            first_bar_holds = first_4h_close > gap_midpoint
        else:
            first_bar_holds = first_4h_close < gap_midpoint

        # Direction filter: first bar close in gap direction
        if gap_pct > 0:
            first_bar_direction = first_4h_close > prior_close
        else:
            first_bar_direction = first_4h_close < prior_close

        # Half filter: direction + in upper/lower half of bar range
        bar_range = first_4h_high - first_4h_low
        bar_mid = (first_4h_high + first_4h_low) / 2
        if gap_pct > 0:
            first_bar_half = first_bar_direction and (first_4h_close >= bar_mid)
        else:
            first_bar_half = first_bar_direction and (first_4h_close <= bar_mid)

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
            "first_bar_direction": first_bar_direction,
            "first_bar_half": first_bar_half,
        })

    events_df = pd.DataFrame(events)

    for reason, items in skipped.items():
        if items:
            print(f"\nSkipped ({reason}): {len(items)}")
            for item in items:
                print(f"  {item}")

    return events_df, n_in_range


def print_data_prep_summary(earnings_df, events_df, n_in_range=0):
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
    gap2 = events_df[abs_gap >= 2.0]
    holds_2pct = gap2["first_bar_holds"].sum() if len(gap2) > 0 else 0
    print(f"First bar holds (2% threshold): {holds_2pct}")


# ---------------------------------------------------------------------------
# Part B: Baseline Test (TEST 0) — unchanged
# ---------------------------------------------------------------------------

def run_baseline_test(events_df, ticker_4h, ticker_trading_days):
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

    results = []
    for _, ev in test_events.iterrows():
        ticker = ev["ticker"]
        entry_day = ev["entry_day"]
        gap_pct = ev["gap_pct"]
        gap_sign = 1 if gap_pct > 0 else -1
        bars_4h = ticker_4h[ticker]
        trading_days = ticker_trading_days[ticker]
        entry_price = ev["open_price"]
        first_4h_close = ev["first_4h_close"]
        entry_day_close = get_bar_close(bars_4h, ticker, entry_day, 2)
        day_after = next_trading_day(entry_day, trading_days)
        day_after_close = get_bar_close(bars_4h, ticker, day_after, 2) if day_after else None
        day_3 = nth_trading_day_after(entry_day, 3, trading_days)
        close_3d = get_bar_close(bars_4h, ticker, day_3, 2) if day_3 else None
        day_5 = nth_trading_day_after(entry_day, 5, trading_days)
        close_5d = get_bar_close(bars_4h, ticker, day_5, 2) if day_5 else None
        exit_price_5d = close_5d

        next_day_continuation = None
        next_day_return = None
        if entry_day_close is not None and day_after_close is not None:
            move = day_after_close - entry_day_close
            next_day_continuation = (move * gap_sign) > 0
            next_day_return = (move / entry_day_close * 100) * gap_sign

        drift_3d = drift_3d_match = None
        if close_3d is not None:
            drift_3d = (close_3d - entry_price) / entry_price * 100
            drift_3d_match = (drift_3d * gap_sign) > 0

        drift_5d = drift_5d_match = None
        if close_5d is not None:
            drift_5d = (close_5d - entry_price) / entry_price * 100
            drift_5d_match = (drift_5d * gap_sign) > 0

        simple_return = None
        if first_4h_close is not None and exit_price_5d is not None:
            raw_return = (exit_price_5d - first_4h_close) / first_4h_close * 100
            simple_return = raw_return * gap_sign

        results.append({
            "ticker": ticker, "entry_day": entry_day, "gap_pct": gap_pct,
            "gap_sign": gap_sign, "eps_surprise_pct": ev["eps_surprise_pct"],
            "next_day_continuation": next_day_continuation,
            "next_day_return": next_day_return,
            "drift_3d": drift_3d, "drift_3d_match": drift_3d_match,
            "drift_5d": drift_5d, "drift_5d_match": drift_5d_match,
            "simple_return": simple_return,
        })

    res_df = pd.DataFrame(results)

    m1 = res_df.dropna(subset=["next_day_continuation"])
    if len(m1) > 0:
        print(f"\nNext-day continuation:")
        print(f"  Hit rate: {m1['next_day_continuation'].mean() * 100:.1f}%")
        print(f"  Mean return: {m1['next_day_return'].mean():.2f}%")

    m2 = res_df.dropna(subset=["drift_3d"])
    if len(m2) > 0:
        print(f"\n3-day drift:")
        print(f"  Hit rate: {m2['drift_3d_match'].mean() * 100:.1f}%")
        print(f"  Mean: {(m2['drift_3d'] * m2['gap_sign']).mean():.2f}%")

    m3 = res_df.dropna(subset=["drift_5d"])
    if len(m3) > 0:
        print(f"\n5-day drift:")
        print(f"  Hit rate: {m3['drift_5d_match'].mean() * 100:.1f}%")
        print(f"  Mean: {(m3['drift_5d'] * m3['gap_sign']).mean():.2f}%")

    m4 = res_df.dropna(subset=["simple_return"])
    if len(m4) > 0:
        n4 = len(m4)
        mean_ret_4 = m4["simple_return"].mean()
        wr = (m4["simple_return"] > 0).mean() * 100
        gp = m4.loc[m4["simple_return"] > 0, "simple_return"].sum()
        gl = abs(m4.loc[m4["simple_return"] <= 0, "simple_return"].sum())
        pf = gp / gl if gl > 0 else float("inf")
        print(f"\nSimple 4H-close entry, 5-day hold:")
        print(f"  N: {n4}, Mean: {mean_ret_4:.2f}%, WR: {wr:.1f}%, PF: {pf:.2f}")

        longs = m4[m4["gap_sign"] == 1]
        shorts = m4[m4["gap_sign"] == -1]
        if len(longs) > 0:
            lwr = (longs["simple_return"] > 0).mean() * 100
            print(f"  LONG: N={len(longs)}, mean={longs['simple_return'].mean():.2f}%, WR={lwr:.1f}%")
        if len(shorts) > 0:
            swr = (shorts["simple_return"] > 0).mean() * 100
            print(f"  SHORT: N={len(shorts)}, mean={shorts['simple_return'].mean():.2f}%, WR={swr:.1f}%")

        print(f"\n  By EPS surprise bucket:")
        eps = m4["eps_surprise_pct"]
        for label, mask in [("Beat >10%", eps > 10), ("Beat 0-10%", (eps >= 0) & (eps <= 10)),
                             ("Miss 0-10%", (eps < 0) & (eps >= -10)), ("Miss >10%", eps < -10)]:
            b = m4[mask]
            if len(b) > 0:
                print(f"    {label}: N={len(b)}, mean={b['simple_return'].mean():.2f}%")
            else:
                print(f"    {label}: N=0")

        if len(m3) > 0:
            vhr = m3["drift_5d_match"].mean() * 100
            vmean = (m3["drift_5d"] * m3["gap_sign"]).mean()
        else:
            vhr, vmean = wr, mean_ret_4

        print(f"\nVERDICT: ", end="")
        if vhr > 60 and vmean > 0.5:
            print(f"PROMISING (HR={vhr:.1f}%, mean={vmean:.2f}%)")
        elif vhr >= 55 or (0.2 <= vmean <= 0.5):
            print(f"MARGINAL (HR={vhr:.1f}%, mean={vmean:.2f}%)")
        else:
            print(f"NO_EDGE (HR={vhr:.1f}%, mean={vmean:.2f}%)")
    else:
        print("\nVERDICT: NO_EDGE (insufficient data)")


# ---------------------------------------------------------------------------
# Part C: Sweep Engine — Generic Trade Simulator
# ---------------------------------------------------------------------------

def simulate_trade(ev, ticker_4h, ticker_trading_days, max_bars=10,
                   exit_strategy="midpoint"):
    """Simulate a single trade.

    Entry: first 4H bar close on entry day.
    Exit strategies:
        "midpoint"  — gap midpoint breach OR max_bars (default)
        "reversal"  — first 4H close against entry direction
        "ema9"      — 4H close crosses EMA9 against position
        "fixed_N"   — exit at exactly bar N (no stop)
        "trailing50" — exit if bar gives back >50% of max unrealized gain

    Returns dict with trade details or None if insufficient data.
    """
    ticker = ev["ticker"]
    entry_day = ev["entry_day"]
    gap_pct = ev["gap_pct"]
    gap_sign = 1 if gap_pct > 0 else -1
    bars_4h = ticker_4h[ticker]
    trading_days = ticker_trading_days[ticker]

    entry_price = ev["first_4h_close"]
    if entry_price is None or np.isnan(entry_price):
        return None

    gap_midpoint = ev["gap_midpoint"]

    # Get forward bars
    fwd = get_forward_bars(bars_4h, ticker, entry_day, trading_days, max_bars)
    if not fwd:
        return None

    # Fixed hold strategies
    if exit_strategy.startswith("fixed_"):
        target_bar = int(exit_strategy.split("_")[1])
        # target_bar is 1-indexed: bar 5 = 5th forward bar
        if len(fwd) < target_bar:
            return None
        exit_price = fwd[target_bar - 1]["Close"]
        raw_ret = (exit_price - entry_price) / entry_price * 100
        signed_ret = raw_ret * gap_sign
        return {
            "ticker": ticker, "entry_day": entry_day, "gap_pct": gap_pct,
            "gap_sign": gap_sign, "eps_surprise_pct": ev["eps_surprise_pct"],
            "entry_price": entry_price, "exit_price": exit_price,
            "return_pct": signed_ret, "bars_held": target_bar,
            "exit_reason": f"fixed_{target_bar}",
        }

    # For EMA9, compute 9-bar EMA on close prices
    ema9_vals = None
    if exit_strategy == "ema9":
        # Build close series: entry bar + forward bars
        closes = [entry_price] + [b["Close"] for b in fwd]
        ema9_vals = _compute_ema(closes, 9)

    # Iterate forward bars
    max_unrealized = 0.0
    for i, bar in enumerate(fwd):
        bar_close = bar["Close"]
        raw_ret = (bar_close - entry_price) / entry_price * 100
        signed_ret = raw_ret * gap_sign
        unrealized = signed_ret

        if unrealized > max_unrealized:
            max_unrealized = unrealized

        # Check exit conditions
        if exit_strategy == "midpoint":
            # Midpoint breach: for LONG, bar close < midpoint; SHORT, bar close > midpoint
            if gap_sign == 1 and bar_close < gap_midpoint:
                return _trade_result(ev, entry_price, bar_close, i + 1, "midpoint_breach")
            if gap_sign == -1 and bar_close > gap_midpoint:
                return _trade_result(ev, entry_price, bar_close, i + 1, "midpoint_breach")
            # Max bars
            if i == len(fwd) - 1:
                return _trade_result(ev, entry_price, bar_close, i + 1, "max_bars")

        elif exit_strategy == "reversal":
            # Any bar close against entry direction
            if signed_ret < 0:
                return _trade_result(ev, entry_price, bar_close, i + 1, "reversal")
            if i == len(fwd) - 1:
                return _trade_result(ev, entry_price, bar_close, i + 1, "max_bars")

        elif exit_strategy == "ema9":
            # EMA9 index: i+1 because closes[0] = entry_price
            if ema9_vals is not None and (i + 1) < len(ema9_vals):
                ema_val = ema9_vals[i + 1]
                # LONG: close < ema9; SHORT: close > ema9
                if gap_sign == 1 and bar_close < ema_val:
                    return _trade_result(ev, entry_price, bar_close, i + 1, "ema9_cross")
                if gap_sign == -1 and bar_close > ema_val:
                    return _trade_result(ev, entry_price, bar_close, i + 1, "ema9_cross")
            if i == len(fwd) - 1:
                return _trade_result(ev, entry_price, bar_close, i + 1, "max_bars")

        elif exit_strategy == "trailing50":
            if max_unrealized > 0 and unrealized < max_unrealized * 0.5:
                return _trade_result(ev, entry_price, bar_close, i + 1, "trailing50")
            if i == len(fwd) - 1:
                return _trade_result(ev, entry_price, bar_close, i + 1, "max_bars")

    # Fallback (shouldn't reach here normally)
    if fwd:
        return _trade_result(ev, entry_price, fwd[-1]["Close"], len(fwd), "max_bars")
    return None


def _trade_result(ev, entry_price, exit_price, bars_held, exit_reason):
    gap_sign = 1 if ev["gap_pct"] > 0 else -1
    raw_ret = (exit_price - entry_price) / entry_price * 100
    signed_ret = raw_ret * gap_sign
    return {
        "ticker": ev["ticker"], "entry_day": ev["entry_day"],
        "gap_pct": ev["gap_pct"], "gap_sign": gap_sign,
        "eps_surprise_pct": ev["eps_surprise_pct"],
        "entry_price": entry_price, "exit_price": exit_price,
        "return_pct": signed_ret, "bars_held": bars_held,
        "exit_reason": exit_reason,
    }


def _compute_ema(values, period):
    """Compute EMA for a list of values."""
    ema = [values[0]]
    mult = 2.0 / (period + 1)
    for v in values[1:]:
        ema.append(v * mult + ema[-1] * (1 - mult))
    return ema


def run_backtest(events_df, ticker_4h, ticker_trading_days,
                 gap_threshold=2.0, first_bar_filter="holds",
                 max_bars=10, direction="both",
                 eps_surprise_threshold=None,
                 exit_strategy="midpoint",
                 exclude_ticker=None):
    """Run backtest with given parameters. Returns DataFrame of trades."""
    df = events_df.copy()

    # Gap filter
    df = df[df["gap_pct"].abs() >= gap_threshold]

    # Direction filter
    if direction == "long":
        df = df[df["gap_pct"] > 0]
    elif direction == "short":
        df = df[df["gap_pct"] < 0]

    # First bar filter
    if first_bar_filter == "holds":
        df = df[df["first_bar_holds"] == True]
    elif first_bar_filter == "direction":
        df = df[df["first_bar_direction"] == True]
    elif first_bar_filter == "half":
        df = df[df["first_bar_half"] == True]
    # "none" = no filter

    # EPS surprise filter
    if eps_surprise_threshold is not None:
        df = df[df["eps_surprise_pct"].abs() >= eps_surprise_threshold]

    # Exclude ticker (for LOTO)
    if exclude_ticker is not None:
        df = df[df["ticker"] != exclude_ticker]

    trades = []
    for _, ev in df.iterrows():
        t = simulate_trade(ev, ticker_4h, ticker_trading_days,
                          max_bars=max_bars, exit_strategy=exit_strategy)
        if t is not None:
            trades.append(t)

    return pd.DataFrame(trades) if trades else pd.DataFrame()


def compute_metrics(trades_df):
    """Compute standard metrics from trades DataFrame."""
    if trades_df.empty or len(trades_df) == 0:
        return {"N": 0, "mean_pct": 0, "wr_pct": 0, "pf": 0,
                "sharpe": 0, "max_dd": 0, "avg_bars": 0}

    rets = trades_df["return_pct"]
    n = len(rets)
    mean_r = rets.mean()
    wr = (rets > 0).mean() * 100
    gp = rets[rets > 0].sum()
    gl = abs(rets[rets <= 0].sum())
    pf = gp / gl if gl > 0 else float("inf")

    # Sharpe (annualized assuming ~2 trades/week, ~100 trades/year)
    std = rets.std()
    sharpe = (mean_r / std * np.sqrt(100)) if std > 0 else 0.0

    # Max drawdown (cumulative)
    cum = rets.cumsum()
    peak = cum.cummax()
    dd = cum - peak
    max_dd = dd.min()

    avg_bars = trades_df["bars_held"].mean() if "bars_held" in trades_df.columns else 0

    return {
        "N": n, "mean_pct": mean_r, "wr_pct": wr, "pf": pf,
        "sharpe": sharpe, "max_dd": max_dd, "avg_bars": avg_bars,
    }


def fmt_row(metrics, extra_cols=None):
    """Format a metrics dict as a table row string."""
    m = metrics
    parts = []
    if extra_cols:
        for k, v in extra_cols.items():
            parts.append(f"{v:>8}")
    parts.append(f"{m['N']:>5}")
    parts.append(f"{m['mean_pct']:>8.2f}")
    parts.append(f"{m['wr_pct']:>7.1f}")
    pf_str = f"{m['pf']:.2f}" if m['pf'] != float("inf") else "  inf"
    parts.append(f"{pf_str:>7}")
    parts.append(f"{m['sharpe']:>8.2f}")
    parts.append(f"{m['max_dd']:>8.2f}")
    parts.append(f"{m['avg_bars']:>6.1f}")
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Part D: Sweep Tests 1-6
# ---------------------------------------------------------------------------

def _table_header(first_col, first_w=8):
    hdr = f"{'':>{first_w}} | {'N':>5} | {'Mean%':>8} | {'WR%':>7} | {'PF':>7} | {'Sharpe':>8} | {'MaxDD':>8} | {'Bars':>6}"
    sep = "-" * len(hdr)
    return hdr, sep


def sweep_test1(events_df, ticker_4h, ticker_trading_days):
    """TEST 1: GAP_THRESHOLD sweep."""
    print("\n" + "=" * 60)
    print("=== TEST 1: GAP_THRESHOLD Sweep ===")
    print("=" * 60)

    thresholds = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
    hdr, sep = _table_header("Gap%")
    print(hdr)
    print(sep)

    results = {}
    for g in thresholds:
        trades = run_backtest(events_df, ticker_4h, ticker_trading_days,
                              gap_threshold=g, first_bar_filter="holds",
                              max_bars=10, exit_strategy="midpoint")
        m = compute_metrics(trades)
        results[g] = m
        row = fmt_row(m, {"Gap%": f"{g:.1f}%"})
        print(row)

    # Find best by PF (with N >= 10)
    best_gap = 2.0
    best_pf = 0
    for g, m in results.items():
        if m["N"] >= 10 and m["pf"] > best_pf:
            best_pf = m["pf"]
            best_gap = g
    print(f"\nBest gap threshold: {best_gap}% (PF={best_pf:.2f})")
    return best_gap, results


def sweep_test2(events_df, ticker_4h, ticker_trading_days):
    """TEST 2: FIRST_BAR_HOLDS filter impact."""
    print("\n" + "=" * 60)
    print("=== TEST 2: First Bar Filter Impact (gap >= 2%) ===")
    print("=" * 60)

    filters = [("none", "No filter"), ("direction", "Direction"), ("holds", "Holds (spec)"),
               ("half", "Half")]

    hdr = f"{'Filter':>14} | {'N':>5} | {'Mean%':>8} | {'WR%':>7} | {'PF':>7} | {'Lift':>8}"
    print(hdr)
    print("-" * len(hdr))

    baseline_mean = None
    for filt_key, filt_name in filters:
        trades = run_backtest(events_df, ticker_4h, ticker_trading_days,
                              gap_threshold=2.0, first_bar_filter=filt_key,
                              max_bars=10, exit_strategy="midpoint")
        m = compute_metrics(trades)
        if filt_key == "none":
            baseline_mean = m["mean_pct"]
        lift = m["mean_pct"] - baseline_mean if baseline_mean is not None else 0
        pf_str = f"{m['pf']:.2f}" if m['pf'] != float("inf") else "  inf"
        print(f"{filt_name:>14} | {m['N']:>5} | {m['mean_pct']:>8.2f} | "
              f"{m['wr_pct']:>7.1f} | {pf_str:>7} | {lift:>+8.2f}")


def sweep_test3(events_df, ticker_4h, ticker_trading_days, best_gap=2.0):
    """TEST 3: MAX_BARS sweep."""
    print("\n" + "=" * 60)
    print(f"=== TEST 3: MAX_BARS Sweep (gap >= {best_gap}%) ===")
    print("=" * 60)

    max_bars_vals = [4, 6, 8, 10, 15, 20]
    hdr, sep = _table_header("MaxBars")
    print(hdr)
    print(sep)

    results = {}
    for mb in max_bars_vals:
        trades = run_backtest(events_df, ticker_4h, ticker_trading_days,
                              gap_threshold=best_gap, first_bar_filter="holds",
                              max_bars=mb, exit_strategy="midpoint")
        m = compute_metrics(trades)
        results[mb] = m
        row = fmt_row(m, {"MaxBars": str(mb)})
        print(row)

    best_mb = 10
    best_pf = 0
    for mb, m in results.items():
        if m["N"] >= 10 and m["pf"] > best_pf:
            best_pf = m["pf"]
            best_mb = mb
    print(f"\nBest max_bars: {best_mb} (PF={best_pf:.2f})")
    return best_mb, results


def sweep_test4(events_df, ticker_4h, ticker_trading_days):
    """TEST 4: LONG-ONLY vs SHORT-ONLY vs SYMMETRIC."""
    print("\n" + "=" * 60)
    print("=== TEST 4: Direction Analysis (gap >= 2%) ===")
    print("=" * 60)

    directions = [("long", "LONG"), ("short", "SHORT"), ("both", "SYMMETRIC")]
    hdr = f"{'Direction':>10} | {'N':>5} | {'Mean%':>8} | {'WR%':>7} | {'PF':>7} | {'Sharpe':>8}"
    print(hdr)
    print("-" * len(hdr))

    for dir_key, dir_name in directions:
        trades = run_backtest(events_df, ticker_4h, ticker_trading_days,
                              gap_threshold=2.0, first_bar_filter="holds",
                              max_bars=10, direction=dir_key, exit_strategy="midpoint")
        m = compute_metrics(trades)
        pf_str = f"{m['pf']:.2f}" if m['pf'] != float("inf") else "  inf"
        print(f"{dir_name:>10} | {m['N']:>5} | {m['mean_pct']:>8.2f} | "
              f"{m['wr_pct']:>7.1f} | {pf_str:>7} | {m['sharpe']:>8.2f}")


def sweep_test5(events_df, ticker_4h, ticker_trading_days):
    """TEST 5: EPS SURPRISE as filter."""
    print("\n" + "=" * 60)
    print("=== TEST 5: EPS Surprise Filter (gap >= 2%) ===")
    print("=" * 60)

    thresholds = [0, 5, 10, 15, 20]
    hdr = f"{'|Surp|>=':>10} | {'N':>5} | {'Mean%':>8} | {'WR%':>7} | {'PF':>7}"
    print(hdr)
    print("-" * len(hdr))

    for st in thresholds:
        trades = run_backtest(events_df, ticker_4h, ticker_trading_days,
                              gap_threshold=2.0, first_bar_filter="holds",
                              max_bars=10, exit_strategy="midpoint",
                              eps_surprise_threshold=st if st > 0 else None)
        m = compute_metrics(trades)
        pf_str = f"{m['pf']:.2f}" if m['pf'] != float("inf") else "  inf"
        print(f"{st:>9}% | {m['N']:>5} | {m['mean_pct']:>8.2f} | "
              f"{m['wr_pct']:>7.1f} | {pf_str:>7}")

    # Combined filter: gap >= 2% AND |eps_surprise| >= 10%
    print(f"\nCombined: gap >= 2% AND |eps_surprise| >= 10%")
    trades = run_backtest(events_df, ticker_4h, ticker_trading_days,
                          gap_threshold=2.0, first_bar_filter="holds",
                          max_bars=10, exit_strategy="midpoint",
                          eps_surprise_threshold=10)
    if not trades.empty:
        beats = trades[trades["eps_surprise_pct"] > 0]
        misses = trades[trades["eps_surprise_pct"] <= 0]
        for label, sub in [("Beats", beats), ("Misses", misses)]:
            sm = compute_metrics(sub)
            pf_str = f"{sm['pf']:.2f}" if sm['pf'] != float("inf") else "inf"
            print(f"  {label}: N={sm['N']}, Mean={sm['mean_pct']:.2f}%, "
                  f"WR={sm['wr_pct']:.1f}%, PF={pf_str}")
    else:
        print("  No trades with combined filter.")


def sweep_test6(events_df, ticker_4h, ticker_trading_days):
    """TEST 6: Exit strategy comparison."""
    print("\n" + "=" * 60)
    print("=== TEST 6: Exit Strategy Comparison (gap >= 2%) ===")
    print("=" * 60)

    strategies = [
        ("midpoint", "Midpoint/10", 10),
        ("reversal", "Reversal", 10),
        ("ema9", "EMA9 cross", 10),
        ("fixed_5", "Fixed 5", 5),
        ("fixed_10", "Fixed 10", 10),
        ("trailing50", "Trail 50%", 10),
    ]

    hdr = f"{'Exit':>14} | {'N':>5} | {'Mean%':>8} | {'WR%':>7} | {'PF':>7} | {'AvgBars':>7}"
    print(hdr)
    print("-" * len(hdr))

    for strat, name, mb in strategies:
        trades = run_backtest(events_df, ticker_4h, ticker_trading_days,
                              gap_threshold=2.0, first_bar_filter="holds",
                              max_bars=mb, exit_strategy=strat)
        m = compute_metrics(trades)
        pf_str = f"{m['pf']:.2f}" if m['pf'] != float("inf") else "  inf"
        print(f"{name:>14} | {m['N']:>5} | {m['mean_pct']:>8.2f} | "
              f"{m['wr_pct']:>7.1f} | {pf_str:>7} | {m['avg_bars']:>7.1f}")


# ---------------------------------------------------------------------------
# Part E: Robustness Checks
# ---------------------------------------------------------------------------

SECTORS = {
    "mega_tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA"],
    "growth_semi": ["TSLA", "AMD", "SMCI", "PLTR", "AVGO", "ARM", "TSM", "MU", "INTC"],
    "crypto_proxy": ["COIN", "MSTR", "MARA"],
    "finance": ["C", "GS", "V", "BA", "JPM"],
    "china_adr": ["BABA", "JD", "BIDU"],
    "consumer": ["COST"],
}


def robustness_r1(events_df, ticker_4h, ticker_trading_days, best_config):
    """R1: Leave-one-ticker-out."""
    print("\n--- R1: Leave-One-Ticker-Out ---")

    # Baseline
    base_trades = run_backtest(events_df, ticker_4h, ticker_trading_days, **best_config)
    base_m = compute_metrics(base_trades)
    base_pf = base_m["pf"]

    tickers = sorted(events_df["ticker"].unique())
    results = []
    for t in tickers:
        trades = run_backtest(events_df, ticker_4h, ticker_trading_days,
                              exclude_ticker=t, **best_config)
        m = compute_metrics(trades)
        pf_drop = ((base_pf - m["pf"]) / base_pf * 100) if base_pf > 0 else 0
        results.append({"ticker": t, "N": m["N"], "mean_pct": m["mean_pct"],
                        "pf": m["pf"], "pf_drop_pct": pf_drop})
        print(f"  Excl {t:>6}: N={m['N']:>3}, Mean={m['mean_pct']:>+7.2f}%, PF={m['pf']:.2f}")

    if results:
        max_impact = max(results, key=lambda x: abs(x["pf_drop_pct"]))
        print(f"\n  Max impact: {max_impact['ticker']} "
              f"(PF drop {max_impact['pf_drop_pct']:.1f}%)")
        return max_impact
    return {"ticker": "N/A", "pf_drop_pct": 0}


def robustness_r2(events_df, ticker_4h, ticker_trading_days, best_config):
    """R2: Monthly returns."""
    print("\n--- R2: Monthly Returns ---")

    trades = run_backtest(events_df, ticker_4h, ticker_trading_days, **best_config)
    if trades.empty:
        print("  No trades.")
        return 0

    trades["month"] = pd.to_datetime(trades["entry_day"].astype(str)).dt.to_period("M")
    monthly = trades.groupby("month").agg(
        N=("return_pct", "count"),
        mean_pct=("return_pct", "mean"),
        total_pnl=("return_pct", "sum"),
    ).reset_index()

    total_pnl = monthly["total_pnl"].sum()
    print(f"  {'Month':>8} | {'N':>3} | {'Mean%':>7} | {'WR%':>6} | {'%PnL':>6}")
    print(f"  {'-'*42}")

    max_conc = 0
    for _, row in monthly.iterrows():
        month_trades = trades[trades["month"] == row["month"]]
        wr = (month_trades["return_pct"] > 0).mean() * 100
        pnl_pct = (row["total_pnl"] / total_pnl * 100) if total_pnl != 0 else 0
        if abs(pnl_pct) > abs(max_conc):
            max_conc = pnl_pct
        flag = " ***" if abs(pnl_pct) > 30 else ""
        print(f"  {str(row['month']):>8} | {row['N']:>3} | {row['mean_pct']:>+7.2f} | "
              f"{wr:>5.1f}% | {pnl_pct:>+5.1f}%{flag}")

    print(f"\n  Max monthly concentration: {abs(max_conc):.1f}%")
    return max_conc


def robustness_r3(events_df, ticker_4h, ticker_trading_days, best_config):
    """R3: Sector concentration."""
    print("\n--- R3: Sector Concentration ---")

    trades = run_backtest(events_df, ticker_4h, ticker_trading_days, **best_config)
    if trades.empty:
        print("  No trades.")
        return 0

    total_n = len(trades)
    print(f"  {'Sector':>14} | {'N':>4} | {'Mean%':>8} | {'% Trades':>9}")
    print(f"  {'-'*44}")

    # Build reverse lookup
    ticker_to_sector = {}
    for sector, tickers in SECTORS.items():
        for t in tickers:
            ticker_to_sector[t] = sector

    max_conc = 0
    for sector in SECTORS:
        sector_trades = trades[trades["ticker"].isin(SECTORS[sector])]
        n = len(sector_trades)
        mean_r = sector_trades["return_pct"].mean() if n > 0 else 0
        pct = n / total_n * 100
        if pct > max_conc:
            max_conc = pct
        print(f"  {sector:>14} | {n:>4} | {mean_r:>+8.2f} | {pct:>8.1f}%")

    # Unclassified
    classified = set()
    for tl in SECTORS.values():
        classified.update(tl)
    unclass = trades[~trades["ticker"].isin(classified)]
    if len(unclass) > 0:
        print(f"  {'other':>14} | {len(unclass):>4} | "
              f"{unclass['return_pct'].mean():>+8.2f} | "
              f"{len(unclass)/total_n*100:>8.1f}%")

    print(f"\n  Max sector concentration: {max_conc:.1f}%")
    return max_conc


def robustness_r4(events_df, ticker_4h, ticker_trading_days, best_config):
    """R4: Gap size vs return correlation."""
    print("\n--- R4: Gap Size vs Return Correlation ---")

    trades = run_backtest(events_df, ticker_4h, ticker_trading_days, **best_config)
    if trades.empty or len(trades) < 3:
        print("  Insufficient trades.")
        return 0

    corr = trades["gap_pct"].abs().corr(trades["return_pct"])
    print(f"  Correlation(|gap_pct|, return_pct): {corr:.4f}")
    if corr > 0.1:
        print(f"  Larger gap = larger drift (positive correlation)")
    elif corr < -0.1:
        print(f"  Larger gap = smaller drift (negative correlation)")
    else:
        print(f"  No clear relationship between gap size and return")
    return corr


def robustness_r5(events_df, ticker_4h, ticker_trading_days, best_config):
    """R5: Earnings beat vs miss."""
    print("\n--- R5: Beat vs Miss ---")

    trades = run_backtest(events_df, ticker_4h, ticker_trading_days, **best_config)
    if trades.empty:
        print("  No trades.")
        return

    beats = trades[trades["eps_surprise_pct"] > 0]
    misses = trades[trades["eps_surprise_pct"] <= 0]

    print(f"  {'Type':>8} | {'N':>5} | {'Mean%':>8} | {'WR%':>7} | {'PF':>7}")
    print(f"  {'-'*44}")

    for label, sub in [("Beat", beats), ("Miss", misses)]:
        m = compute_metrics(sub)
        pf_str = f"{m['pf']:.2f}" if m['pf'] != float("inf") else "  inf"
        print(f"  {label:>8} | {m['N']:>5} | {m['mean_pct']:>8.2f} | "
              f"{m['wr_pct']:>7.1f} | {pf_str:>7}")


# ---------------------------------------------------------------------------
# Part F: Sweep Orchestrator + Summary
# ---------------------------------------------------------------------------

def run_sweep(events_df, ticker_4h, ticker_trading_days):
    """Run all sweep tests and robustness checks."""
    print("\n" + "=" * 60)
    print("=== PEAD-lite Parameter Sweeps ===")
    print("=" * 60)

    all_sweep_trades = []

    # TEST 1: Gap threshold
    best_gap, _ = sweep_test1(events_df, ticker_4h, ticker_trading_days)

    # TEST 2: First bar filter
    sweep_test2(events_df, ticker_4h, ticker_trading_days)

    # TEST 3: Max bars
    best_mb, _ = sweep_test3(events_df, ticker_4h, ticker_trading_days, best_gap)

    # TEST 4: Direction
    sweep_test4(events_df, ticker_4h, ticker_trading_days)

    # TEST 5: EPS surprise
    sweep_test5(events_df, ticker_4h, ticker_trading_days)

    # TEST 6: Exit strategies
    sweep_test6(events_df, ticker_4h, ticker_trading_days)

    # Determine best config from sweeps
    # Try combinations of best gap + best max_bars with different filters
    configs = []
    for fb in ["holds", "direction", "half", "none"]:
        for eps_t in [None, 10]:
            for exit_s in ["midpoint", "reversal", "ema9", "trailing50"]:
                cfg = {
                    "gap_threshold": best_gap,
                    "first_bar_filter": fb,
                    "max_bars": best_mb,
                    "exit_strategy": exit_s,
                    "eps_surprise_threshold": eps_t,
                }
                trades = run_backtest(events_df, ticker_4h, ticker_trading_days, **cfg)
                m = compute_metrics(trades)
                if m["N"] >= 10:
                    configs.append((cfg, m, trades))

    # Also try best gap thresholds with default settings
    for g in [best_gap, 2.0, 3.0]:
        for mb in [best_mb, 10]:
            cfg = {
                "gap_threshold": g,
                "first_bar_filter": "holds",
                "max_bars": mb,
                "exit_strategy": "midpoint",
                "eps_surprise_threshold": None,
            }
            trades = run_backtest(events_df, ticker_4h, ticker_trading_days, **cfg)
            m = compute_metrics(trades)
            if m["N"] >= 10:
                configs.append((cfg, m, trades))

    # Pick best config by PF (with reasonable N)
    if not configs:
        print("\nNo valid configurations found with N >= 10.")
        return

    # Score: weighted combo of PF and Sharpe, penalize low N
    def score(m):
        n_bonus = min(m["N"] / 30.0, 1.0)  # full bonus at N>=30
        return (m["pf"] * 0.5 + m["sharpe"] * 0.3 + m["wr_pct"] / 100 * 0.2) * n_bonus

    configs.sort(key=lambda x: score(x[1]), reverse=True)
    best_cfg, best_m, best_trades = configs[0]

    # Save all trades from best config
    if not best_trades.empty:
        all_sweep_trades.append(best_trades)

    # Run robustness checks on best config
    print("\n" + "=" * 60)
    print("=== Robustness Checks ===")
    print("=" * 60)
    print(f"Using config: gap>={best_cfg['gap_threshold']}%, "
          f"filter={best_cfg['first_bar_filter']}, "
          f"max_bars={best_cfg['max_bars']}, "
          f"exit={best_cfg['exit_strategy']}, "
          f"eps_thresh={best_cfg['eps_surprise_threshold']}")

    rob_cfg = {k: v for k, v in best_cfg.items()}

    loto = robustness_r1(events_df, ticker_4h, ticker_trading_days, rob_cfg)
    monthly_conc = robustness_r2(events_df, ticker_4h, ticker_trading_days, rob_cfg)
    sector_conc = robustness_r3(events_df, ticker_4h, ticker_trading_days, rob_cfg)
    gap_corr = robustness_r4(events_df, ticker_4h, ticker_trading_days, rob_cfg)
    robustness_r5(events_df, ticker_4h, ticker_trading_days, rob_cfg)

    # p-value
    p_value = None
    if HAS_SCIPY and not best_trades.empty and len(best_trades) >= 2:
        _, p_value = scipy_stats.ttest_1samp(best_trades["return_pct"], 0)

    # Save sweep trades
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if all_sweep_trades:
        sweep_df = pd.concat(all_sweep_trades, ignore_index=True)
        sweep_df.to_csv(_SWEEP_CSV, index=False)
        print(f"\nSweep trades saved to: {_SWEEP_CSV}")

    # Print comprehensive summary
    print("\n" + "=" * 60)
    print("=== PEAD-lite Sweep Summary ===")
    print("=" * 60)

    eps_desc = f">={best_cfg['eps_surprise_threshold']}%" if best_cfg['eps_surprise_threshold'] else "none"
    print(f"\nBest Configuration:")
    print(f"  GAP_THRESHOLD: {best_cfg['gap_threshold']}%")
    print(f"  FIRST_BAR_FILTER: {best_cfg['first_bar_filter']}")
    print(f"  MAX_BARS: {best_cfg['max_bars']}")
    print(f"  DIRECTION: both")
    print(f"  EXIT_STRATEGY: {best_cfg['exit_strategy']}")
    print(f"  EPS_SURPRISE_FILTER: {eps_desc}")

    print(f"\nPerformance:")
    print(f"  N: {best_m['N']}")
    print(f"  Mean return: {best_m['mean_pct']:.2f}%")
    print(f"  Win rate: {best_m['wr_pct']:.1f}%")
    pf_str = f"{best_m['pf']:.2f}" if best_m['pf'] != float("inf") else "inf"
    print(f"  Profit factor: {pf_str}")
    print(f"  Sharpe: {best_m['sharpe']:.2f}")
    print(f"  Max drawdown: {best_m['max_dd']:.2f}%")
    if p_value is not None:
        print(f"  p-value: {p_value:.4f}")
    else:
        if not HAS_SCIPY:
            print(f"  p-value: scipy not available")
        else:
            print(f"  p-value: insufficient data")

    loto_impact = abs(loto.get("pf_drop_pct", 0)) if isinstance(loto, dict) else 0
    loto_ticker = loto.get("ticker", "N/A") if isinstance(loto, dict) else "N/A"
    print(f"\nRobustness:")
    print(f"  LOTO max impact: {loto_impact:.1f}% (ticker: {loto_ticker})")
    print(f"  Monthly concentration: {abs(monthly_conc):.1f}% in single month")
    print(f"  Sector concentration: {sector_conc:.1f}% in single sector")
    print(f"  Gap-return correlation: {gap_corr:.4f}")

    # Verdict
    n_ok = best_m["N"] >= 30
    wr_ok = best_m["wr_pct"] >= 60
    pf_ok = best_m["pf"] >= 2.0
    p_ok = (p_value is not None and p_value < 0.05) if HAS_SCIPY else True
    loto_ok = loto_impact < 25

    pass_count = sum([n_ok, wr_ok, pf_ok, p_ok, loto_ok])

    print(f"\nCriteria check:")
    print(f"  N >= 30: {'PASS' if n_ok else 'FAIL'} (N={best_m['N']})")
    print(f"  WR >= 60%: {'PASS' if wr_ok else 'FAIL'} (WR={best_m['wr_pct']:.1f}%)")
    print(f"  PF >= 2.0: {'PASS' if pf_ok else 'FAIL'} (PF={pf_str})")
    if p_value is not None:
        print(f"  p < 0.05: {'PASS' if p_ok else 'FAIL'} (p={p_value:.4f})")
    else:
        print(f"  p < 0.05: SKIP (scipy not available)")
    print(f"  LOTO < 25%: {'PASS' if loto_ok else 'FAIL'} ({loto_impact:.1f}%)")

    if pass_count >= 4 and n_ok:
        verdict = "VALIDATED"
    elif pass_count >= 3:
        verdict = "MARGINAL"
    else:
        verdict = "REJECTED"

    print(f"\nVERDICT: {verdict}")
    print(f"  VALIDATED = N>=30, WR>=60%, PF>=2.0, p<0.05, LOTO<25%")
    print(f"  MARGINAL = close to thresholds, needs more data")
    print(f"  REJECTED = clear failure on multiple criteria")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_data():
    """Load all data: earnings, M5, 4H bars. Returns (earnings_df, events_df, ticker_4h, ticker_trading_days)."""
    print("=" * 60)
    print("PEAD Lite Backtest — Data Prep")
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
            print(f"  {ticker}: SKIPPED -- {e}")

    print("\nBuilding earnings event table...")
    events_df, n_in_range = build_events(earnings_df, ticker_4h, ticker_trading_days)

    if len(events_df) == 0:
        print("\nNo qualifying earnings events. Exiting.")
        sys.exit(1)

    print_data_prep_summary(earnings_df, events_df, n_in_range)
    return earnings_df, events_df, ticker_4h, ticker_trading_days


def main():
    parser = argparse.ArgumentParser(description="PEAD Lite Backtest")
    parser.add_argument("--sweep", action="store_true",
                        help="Run parameter sweeps and robustness checks")
    args = parser.parse_args()

    earnings_df, events_df, ticker_4h, ticker_trading_days = load_data()

    # Always run baseline
    run_baseline_test(events_df, ticker_4h, ticker_trading_days)

    # Save events
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    events_df.to_csv(_OUTPUT_CSV, index=False)
    print(f"\nEvents table saved to: {_OUTPUT_CSV}")
    print(f"Total events: {len(events_df)}")

    # Sweep mode
    if args.sweep:
        run_sweep(events_df, ticker_4h, ticker_trading_days)


if __name__ == "__main__":
    main()
