"""
RS Leader Pullback Backtest — Part 1: Data Preparation.

Prepares data infrastructure for the RS Leader Pullback strategy:
  - 4H bars with EMA9/EMA21 for 27 equity tickers
  - Daily VIX proxy from VIXY
  - Daily relative-strength rankings (20-day returns, top 30% = leaders)
  - 60-day rolling high
  - Earnings calendar for exclusion

Reads:
  - Fetched_Data/{TICKER}_data.csv (M5 OHLCV bars, IST-encoded)
  - backtester/data/fmp_earnings.csv

Produces:
  - backtest_output/rs_leader_prepared_data.pkl

Usage:
    python backtests/rs_leader_backtest.py
"""

import datetime
import pickle
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
_OUTPUT_PKL = _OUTPUT_DIR / "rs_leader_prepared_data.pkl"

# Tickers to exclude from equity universe
_EXCLUDE_TICKERS = {"SPY", "VIXY", "BTC", "ETH", "BTC_crypto", "ETH_crypto"}


# ---------------------------------------------------------------------------
# 4H Bar Synthesis (reused from pead_lite_backtest.py)
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
        (hm >= 570) & (hm <= 805),   # 09:30-13:25
        (hm >= 810) & (hm <= 955),   # 13:30-15:55
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


def get_trading_days(bars_4h: pd.DataFrame) -> list:
    """Get sorted list of unique trading days from 4H bars."""
    return sorted(bars_4h["trading_day"].unique())


# ---------------------------------------------------------------------------
# Step 1: Load and synthesize 4H bars for equity tickers
# ---------------------------------------------------------------------------

def load_equity_4h_bars():
    """Load M5 data for all equity tickers, synthesize 4H bars."""
    fetched_dir = _REPO_ROOT / "Fetched_Data"
    available_tickers = set()
    for f in fetched_dir.glob("*_data.csv"):
        ticker = f.stem.replace("_data", "")
        available_tickers.add(ticker)

    equity_tickers = sorted(available_tickers - _EXCLUDE_TICKERS)
    print(f"Equity tickers found: {len(equity_tickers)}")
    print(f"  {', '.join(equity_tickers)}")

    ticker_4h = {}
    ticker_trading_days = {}
    failed = []

    for ticker in equity_tickers:
        try:
            m5 = load_m5_regsess(ticker)
            bars = synthesize_4h_bars(m5)
            ticker_4h[ticker] = bars
            tdays = get_trading_days(bars)
            ticker_trading_days[ticker] = tdays
            print(f"  {ticker}: {len(m5)} M5 bars -> {len(bars)} 4H bars, "
                  f"{len(tdays)} days ({tdays[0]} to {tdays[-1]})")
        except (FileNotFoundError, ValueError) as e:
            print(f"  {ticker}: SKIPPED -- {e}")
            failed.append(ticker)

    for t in failed:
        equity_tickers.remove(t)

    return ticker_4h, ticker_trading_days, equity_tickers


# ---------------------------------------------------------------------------
# Step 2: Compute EMA 9 and EMA 21 on 4H close
# ---------------------------------------------------------------------------

def add_emas(ticker_4h: dict) -> dict:
    """Add EMA9 and EMA21 columns to each ticker's 4H bars."""
    for ticker, bars in ticker_4h.items():
        bars = bars.sort_values(["trading_day", "bar_num"]).reset_index(drop=True)
        bars["ema9"] = bars["Close"].ewm(span=9, min_periods=9).mean()
        bars["ema21"] = bars["Close"].ewm(span=21, min_periods=21).mean()
        ticker_4h[ticker] = bars
    return ticker_4h


# ---------------------------------------------------------------------------
# Step 3: Build daily VIX proxy from VIXY
# ---------------------------------------------------------------------------

def build_vix_proxy() -> dict:
    """Load VIXY, synthesize 4H bars, extract daily close (Bar 2 = last bar).

    NOTE: VIXY tracks VIX short-term futures, typically 1-3 points above VIX spot.
    We test multiple thresholds: VIXY<20, VIXY<22, VIXY<25.
    """
    print("\nBuilding VIX proxy from VIXY...")
    try:
        m5 = load_m5_regsess("VIXY")
    except (FileNotFoundError, ValueError) as e:
        print(f"  ERROR loading VIXY: {e}")
        return {}

    bars = synthesize_4h_bars(m5)
    # Daily close = last 4H bar close each day (prefer Bar 2, fall back to Bar 1)
    # NOTE: VIXY data may only cover morning session (up to ~13:00 ET),
    # so Bar 2 may not exist. Use the highest bar_num available per day.
    last_bar = bars.sort_values("bar_num").groupby("trading_day").last().reset_index()
    vix_proxy = {}
    for _, row in last_bar.iterrows():
        vix_proxy[row["trading_day"]] = row["Close"]

    print(f"  VIXY days: {len(vix_proxy)}")
    if vix_proxy:
        vals = list(vix_proxy.values())
        print(f"  VIXY range: {min(vals):.2f} to {max(vals):.2f}")

    return vix_proxy


# ---------------------------------------------------------------------------
# Step 4: Compute daily relative strength rankings
# ---------------------------------------------------------------------------

def compute_rs_rankings(ticker_4h: dict, equity_tickers: list) -> dict:
    """Compute 20-day return RS rankings for each trading day.

    For each trading day, for each ticker:
      rs_return_20d = (close_today - close_20d_ago) / close_20d_ago * 100
      (20d = 20 trading days, not calendar days)

    Top 30% = top 8 tickers = RS_LEADERS

    Returns: {date: {ticker: {rs_return, rs_rank, is_leader}}}
    """
    print("\nComputing daily RS rankings...")

    # Build daily close series per ticker (Bar 2 close = EOD)
    daily_close = {}  # {ticker: {date: close}}
    ticker_sorted_days = {}  # {ticker: [sorted dates]}
    for ticker in equity_tickers:
        bars = ticker_4h[ticker]
        bar2 = bars[bars["bar_num"] == 2]
        dc = {}
        for _, row in bar2.iterrows():
            dc[row["trading_day"]] = row["Close"]
        daily_close[ticker] = dc
        ticker_sorted_days[ticker] = sorted(dc.keys())

    # Get all trading days across all tickers
    all_days = set()
    for dc in daily_close.values():
        all_days.update(dc.keys())
    all_days = sorted(all_days)

    rs_rankings = {}
    for day in all_days:
        # For each ticker, compute 20-trading-day return
        day_data = {}
        for ticker in equity_tickers:
            dc = daily_close[ticker]
            close_today = dc.get(day)
            if close_today is None:
                continue

            # Find close 20 trading days ago for this ticker
            sorted_days = ticker_sorted_days[ticker]
            idx = None
            # Binary search for the day
            lo, hi = 0, len(sorted_days) - 1
            while lo <= hi:
                mid = (lo + hi) // 2
                if sorted_days[mid] == day:
                    idx = mid
                    break
                elif sorted_days[mid] < day:
                    lo = mid + 1
                else:
                    hi = mid - 1

            if idx is None or idx < 20:
                continue
            day_20_ago = sorted_days[idx - 20]
            close_20_ago = dc[day_20_ago]
            if close_20_ago == 0:
                continue

            rs_return = (close_today - close_20_ago) / close_20_ago * 100
            day_data[ticker] = {"rs_return": rs_return}

        if len(day_data) < 3:
            continue

        # Rank by rs_return descending
        sorted_tickers = sorted(day_data.keys(),
                                key=lambda t: day_data[t]["rs_return"],
                                reverse=True)
        n_leaders = max(1, int(len(sorted_tickers) * 0.3))  # Top 30%

        for rank, ticker in enumerate(sorted_tickers, 1):
            day_data[ticker]["rs_rank"] = rank
            day_data[ticker]["is_leader"] = rank <= n_leaders

        rs_rankings[day] = day_data

    print(f"  Days with RS rankings: {len(rs_rankings)}")
    return rs_rankings


# ---------------------------------------------------------------------------
# Step 5: Compute 60-day rolling high
# ---------------------------------------------------------------------------

def compute_60d_high(ticker_4h: dict, equity_tickers: list) -> dict:
    """Compute 60-trading-day rolling high of daily close.

    For each ticker, for each trading day:
      high_60d = max of daily close over last 60 trading days
      near_high = close >= high_60d * 0.95

    Returns: {ticker: {date: {high_60d, near_high}}}
    """
    print("\nComputing 60-day rolling highs...")

    daily_highs = {}
    for ticker in equity_tickers:
        bars = ticker_4h[ticker]
        bar2 = bars[bars["bar_num"] == 2].sort_values("trading_day")
        closes = list(zip(bar2["trading_day"], bar2["Close"]))

        ticker_highs = {}
        for i, (day, close) in enumerate(closes):
            if i < 60:
                continue
            window = [c for _, c in closes[i - 60:i + 1]]
            high_60d = max(window)
            ticker_highs[day] = {
                "high_60d": high_60d,
                "near_high": close >= high_60d * 0.95,
            }
        daily_highs[ticker] = ticker_highs

    total_entries = sum(len(v) for v in daily_highs.values())
    print(f"  Ticker-days with 60d high data: {total_entries}")
    return daily_highs


# ---------------------------------------------------------------------------
# Step 6: Load earnings calendar for exclusion
# ---------------------------------------------------------------------------

def load_earnings_calendar() -> set:
    """Load earnings dates and build exclusion set: {(ticker, date)}.

    Includes the earnings date AND the trading day before.
    """
    print("\nLoading earnings calendar...")
    if not _EARNINGS_CSV.exists():
        print(f"  WARNING: Earnings CSV not found: {_EARNINGS_CSV}")
        return set()

    df = pd.read_csv(_EARNINGS_CSV)
    exclusion_set = set()
    for _, row in df.iterrows():
        ticker = row["ticker"]
        try:
            edate = datetime.date.fromisoformat(str(row["earnings_date"]))
        except (ValueError, TypeError):
            continue
        exclusion_set.add((ticker, edate))
        # Day before earnings (calendar day)
        day_before = edate - datetime.timedelta(days=1)
        exclusion_set.add((ticker, day_before))
        # If earnings on Monday, also exclude Friday
        if edate.weekday() == 0:  # Monday
            friday_before = edate - datetime.timedelta(days=3)
            exclusion_set.add((ticker, friday_before))

    print(f"  Earnings exclusion entries: {len(exclusion_set)} ticker-days")
    return exclusion_set


# ---------------------------------------------------------------------------
# Step 7: Print comprehensive data prep summary
# ---------------------------------------------------------------------------

def print_summary(ticker_4h, equity_tickers, vix_proxy, rs_rankings,
                  daily_highs, earnings_exclusions):
    """Print the comprehensive data prep summary."""
    print("\n" + "=" * 60)
    print("=== RS Leader Data Prep Summary ===")
    print("=" * 60)

    # --- 4H Bars ---
    total_bars = sum(len(bars) for bars in ticker_4h.values())
    all_days = set()
    for bars in ticker_4h.values():
        all_days.update(bars["trading_day"].unique())
    all_days = sorted(all_days)

    bars_after_warmup = 0
    for bars in ticker_4h.values():
        bars_after_warmup += bars["ema21"].notna().sum()

    print(f"\n4H Bars:")
    print(f"  Tickers loaded: {len(equity_tickers)}/27")
    print(f"  Trading days: {len(all_days)} ({all_days[0]} to {all_days[-1]})")
    print(f"  Total 4H bars: {total_bars}")
    print(f"  Bars with valid EMA21: {bars_after_warmup}")

    # --- VIX Proxy ---
    print(f"\nVIX Proxy (VIXY daily close):")
    if vix_proxy:
        vals = list(vix_proxy.values())
        print(f"  Days with VIXY data: {len(vix_proxy)}")
        print(f"  VIXY range: {min(vals):.2f} to {max(vals):.2f}")
        for thresh in [20, 22, 25]:
            count = sum(1 for v in vals if v < thresh)
            pct = count / len(vals) * 100
            print(f"  Days VIXY < {thresh}: {count} ({pct:.1f}%)")
            if thresh == 20 and count < 50:
                print(f"  *** NOTE: VIX<20 regime rare in this period ({count} days)")
    else:
        print("  WARNING: No VIXY data available!")

    # --- Relative Strength ---
    print(f"\nRelative Strength:")
    rs_days = sorted(rs_rankings.keys())
    print(f"  Days with RS rankings: {len(rs_days)}")
    if rs_days:
        # Average RS spread (top vs bottom)
        spreads = []
        for day, data in rs_rankings.items():
            returns = [d["rs_return"] for d in data.values()]
            if len(returns) >= 2:
                sorted_r = sorted(returns, reverse=True)
                n_top = max(1, int(len(sorted_r) * 0.3))
                top_avg = np.mean(sorted_r[:n_top])
                bot_avg = np.mean(sorted_r[-n_top:])
                spreads.append(top_avg - bot_avg)
        if spreads:
            print(f"  Average RS spread (top vs bottom): {np.mean(spreads):.2f}%")

        # Most frequent leaders
        leader_counts = {}
        for day, data in rs_rankings.items():
            for ticker, info in data.items():
                if info["is_leader"]:
                    leader_counts[ticker] = leader_counts.get(ticker, 0) + 1
        top_leaders = sorted(leader_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        print(f"  Most frequent leaders (top 5 tickers by days-in-top-8):")
        for ticker, count in top_leaders:
            pct = count / len(rs_days) * 100
            print(f"    {ticker}: {count} days ({pct:.1f}%)")

    # --- 60-Day High ---
    print(f"\n60-Day High:")
    if daily_highs:
        total_near = 0
        total_entries = 0
        for ticker_data in daily_highs.values():
            for info in ticker_data.values():
                total_entries += 1
                if info["near_high"]:
                    total_near += 1
        if total_entries > 0:
            print(f"  Average % of tickers near 60d high per day: "
                  f"{total_near / total_entries * 100:.1f}%")

    # --- Combined filter check at multiple VIX thresholds ---
    for vix_thresh in [22, 25, 30]:
        print(f"\nCombined (VIX<{vix_thresh} + leader + near_high):")
        combined_count = 0
        combined_tickers = set()
        for day in rs_days:
            vixy_val = vix_proxy.get(day)
            if vixy_val is None or vixy_val >= vix_thresh:
                continue
            day_rs = rs_rankings.get(day, {})
            for ticker, info in day_rs.items():
                if not info["is_leader"]:
                    continue
                high_info = daily_highs.get(ticker, {}).get(day)
                if high_info is None or not high_info["near_high"]:
                    continue
                combined_count += 1
                combined_tickers.add(ticker)

        print(f"  Ticker-days meeting ALL criteria: {combined_count}")
        print(f"  Unique tickers: {len(combined_tickers)}/{len(equity_tickers)}")

    if vix_proxy:
        min_vixy = min(vix_proxy.values())
        if min_vixy >= 22:
            print(f"\n  *** WARNING: VIXY never drops below 22 in this period "
                  f"(min={min_vixy:.2f}).")
            print(f"  *** Consider relaxing VIX threshold or removing VIX filter "
                  f"for signal detection.")

    # --- Earnings exclusions ---
    print(f"\nEarnings exclusions: {len(earnings_exclusions)} ticker-days excluded")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("RS Leader Pullback Backtest — Data Preparation")
    print("=" * 60)

    # Step 1: Load and synthesize 4H bars
    print("\n--- Step 1: Loading M5 data and synthesizing 4H bars ---")
    ticker_4h, ticker_trading_days, equity_tickers = load_equity_4h_bars()

    # Step 2: Compute EMAs
    print("\n--- Step 2: Computing EMA9 and EMA21 on 4H close ---")
    ticker_4h = add_emas(ticker_4h)
    for ticker in equity_tickers[:3]:
        bars = ticker_4h[ticker]
        valid_ema9 = bars["ema9"].notna().sum()
        valid_ema21 = bars["ema21"].notna().sum()
        print(f"  {ticker}: {len(bars)} bars, EMA9 valid: {valid_ema9}, EMA21 valid: {valid_ema21}")
    print(f"  ... ({len(equity_tickers)} tickers total)")

    # Step 3: VIX proxy
    print("\n--- Step 3: Building VIX proxy ---")
    vix_proxy = build_vix_proxy()

    # Step 4: RS rankings
    print("\n--- Step 4: Computing RS rankings ---")
    rs_rankings = compute_rs_rankings(ticker_4h, equity_tickers)

    # Step 5: 60-day rolling high
    print("\n--- Step 5: Computing 60-day rolling highs ---")
    daily_highs = compute_60d_high(ticker_4h, equity_tickers)

    # Step 6: Earnings calendar
    print("\n--- Step 6: Loading earnings calendar ---")
    earnings_exclusions = load_earnings_calendar()

    # Step 7: Summary
    print_summary(ticker_4h, equity_tickers, vix_proxy, rs_rankings,
                  daily_highs, earnings_exclusions)

    # Save prepared data
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    prepared_data = {
        "ticker_4h": ticker_4h,
        "ticker_trading_days": ticker_trading_days,
        "equity_tickers": equity_tickers,
        "vix_proxy": vix_proxy,
        "rs_rankings": rs_rankings,
        "daily_highs": daily_highs,
        "earnings_exclusions": earnings_exclusions,
    }

    with open(_OUTPUT_PKL, "wb") as f:
        pickle.dump(prepared_data, f)

    print(f"\nPrepared data saved to: {_OUTPUT_PKL}")
    print("Data prep complete. Ready for Part 2 (signal detection).")


if __name__ == "__main__":
    main()
