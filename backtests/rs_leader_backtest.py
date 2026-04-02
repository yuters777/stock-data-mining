"""
RS Leader Pullback Backtest — Part 1: Data Preparation (FRESH START).

Prepares data infrastructure for the RS Leader Pullback strategy:
  - 4H bars with EMA9/EMA21 for equity tickers (excludes SPY, VIXY, BTC, ETH)
  - Daily VIX from FRED VIXCLS (backtester/data/vix_daily.csv)
  - Daily relative-strength rankings (20-day returns, top 30% = leaders)
  - 60-day rolling high proximity
  - Earnings calendar for exclusion

VIX SOURCE: backtester/data/vix_daily.csv (FRED VIXCLS spot daily close).
            DO NOT use VIXY. DO NOT derive VIX from VIXY M5 bars.

Reads:
  - Fetched_Data/{TICKER}_data.csv (M5 OHLCV bars, IST-encoded)
  - backtester/data/vix_daily.csv (284 rows, FRED VIXCLS)
  - backtester/data/fmp_earnings.csv

Produces:
  - backtest_output/rs_leader_prepared_data.pkl
  - Console output with data prep summary

Usage:
    python backtests/rs_leader_backtest.py
"""

import csv
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
_VIX_CSV = _REPO_ROOT / "backtester" / "data" / "vix_daily.csv"
_EARNINGS_CSV = _REPO_ROOT / "backtester" / "data" / "fmp_earnings.csv"
_OUTPUT_DIR = _REPO_ROOT / "backtest_output"
_OUTPUT_PKL = _OUTPUT_DIR / "rs_leader_prepared_data.pkl"

# Tickers to exclude from equity universe
_EXCLUDE_TICKERS = {"SPY", "VIXY", "BTC", "ETH", "BTC_crypto", "ETH_crypto"}

# Warmup: skip first 60 trading days
_WARMUP_DAYS = 60


# ---------------------------------------------------------------------------
# 4H Bar Synthesis (copied from pead_lite_backtest.py)
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

    all_frames = []
    failed = []

    for ticker in equity_tickers:
        try:
            m5 = load_m5_regsess(ticker)
            bars = synthesize_4h_bars(m5)
            all_frames.append(bars)
            tdays = sorted(bars["trading_day"].unique())
            print(f"  {ticker}: {len(m5)} M5 bars -> {len(bars)} 4H bars, "
                  f"{len(tdays)} days ({tdays[0]} to {tdays[-1]})")
        except (FileNotFoundError, ValueError) as e:
            print(f"  {ticker}: SKIPPED -- {e}")
            failed.append(ticker)

    for t in failed:
        equity_tickers.remove(t)

    bars_4h = pd.concat(all_frames, ignore_index=True)
    bars_4h = bars_4h.sort_values(["Ticker", "trading_day", "bar_num"]).reset_index(drop=True)

    return bars_4h, equity_tickers


# ---------------------------------------------------------------------------
# Step 2: Compute EMA 9 and EMA 21 on 4H close
# ---------------------------------------------------------------------------

def add_emas(bars_4h: pd.DataFrame) -> pd.DataFrame:
    """Add EMA9 and EMA21 columns to 4H bars, computed per ticker."""
    bars_4h = bars_4h.sort_values(["Ticker", "trading_day", "bar_num"]).reset_index(drop=True)

    ema9_list = []
    ema21_list = []
    for _, grp in bars_4h.groupby("Ticker"):
        ema9_list.append(grp["Close"].ewm(span=9, min_periods=9).mean())
        ema21_list.append(grp["Close"].ewm(span=21, min_periods=21).mean())

    bars_4h["ema9"] = pd.concat(ema9_list)
    bars_4h["ema21"] = pd.concat(ema21_list)
    return bars_4h


# ---------------------------------------------------------------------------
# Step 3: Load daily VIX from FRED VIXCLS
# ---------------------------------------------------------------------------

def load_vix_daily() -> dict:
    """Load VIX spot daily close from backtester/data/vix_daily.csv (FRED VIXCLS).

    This is the ONLY source of VIX data. Not VIXY. Not synthesized.
    Just read the CSV.
    """
    print("\nLoading VIX from FRED VIXCLS (backtester/data/vix_daily.csv)...")
    if not _VIX_CSV.exists():
        print(f"  ERROR: VIX CSV not found: {_VIX_CSV}")
        return {}

    vix_daily = {}
    with open(_VIX_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            val = row["vix_close"].strip()
            if val == "" or val == ".":
                continue
            vix_daily[row["date"]] = float(val)

    print(f"  Days with VIX data: {len(vix_daily)}")
    if vix_daily:
        vals = list(vix_daily.values())
        print(f"  VIX range: {min(vals):.2f} to {max(vals):.2f}")

    return vix_daily


# ---------------------------------------------------------------------------
# Step 4: Compute daily relative strength rankings
# ---------------------------------------------------------------------------

def compute_rs_rankings(bars_4h: pd.DataFrame, equity_tickers: list) -> dict:
    """Compute 20-day return RS rankings for each trading day.

    For each trading day, for each ticker:
      rs_return = (close_today - close_20d_ago) / close_20d_ago * 100
    Top 30% = RS leaders.

    Returns: {date: {ticker: {rs_return, rs_rank, is_leader}}}
    """
    print("\nComputing daily RS rankings...")

    # Build daily close series per ticker (Bar 2 close = EOD)
    bar2 = bars_4h[bars_4h["bar_num"] == 2].copy()
    daily_close = {}  # {ticker: pd.Series indexed by date}
    for ticker in equity_tickers:
        t_bars = bar2[bar2["Ticker"] == ticker].sort_values("trading_day")
        daily_close[ticker] = dict(zip(t_bars["trading_day"], t_bars["Close"]))

    # Build sorted days per ticker for 20-day lookback
    ticker_sorted_days = {t: sorted(dc.keys()) for t, dc in daily_close.items()}

    # All trading days
    all_days = sorted(set().union(*[set(dc.keys()) for dc in daily_close.values()]))

    rs_rankings = {}
    for day in all_days:
        day_data = {}
        for ticker in equity_tickers:
            dc = daily_close[ticker]
            close_today = dc.get(day)
            if close_today is None:
                continue

            sorted_days = ticker_sorted_days[ticker]
            # Binary search for the day index
            lo, hi = 0, len(sorted_days) - 1
            idx = None
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
            close_20_ago = dc[sorted_days[idx - 20]]
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
        n_leaders = max(1, int(len(sorted_tickers) * 0.3))

        for rank, ticker in enumerate(sorted_tickers, 1):
            day_data[ticker]["rs_rank"] = rank
            day_data[ticker]["is_leader"] = rank <= n_leaders

        rs_rankings[day] = day_data

    print(f"  Days with RS rankings: {len(rs_rankings)}")
    return rs_rankings


# ---------------------------------------------------------------------------
# Step 5: Compute 60-day rolling high
# ---------------------------------------------------------------------------

def compute_60d_high(bars_4h: pd.DataFrame, equity_tickers: list) -> dict:
    """Compute 60-trading-day rolling high of daily close.

    For each ticker, for each trading day:
      high_60d = max of daily close over last 60 trading days (inclusive)
      near_high = close >= high_60d * 0.95

    Returns: {ticker: {date: {high_60d, near_high}}}
    """
    print("\nComputing 60-day rolling highs...")

    bar2 = bars_4h[bars_4h["bar_num"] == 2].copy()
    daily_highs = {}

    for ticker in equity_tickers:
        t_bars = bar2[bar2["Ticker"] == ticker].sort_values("trading_day")
        closes = list(zip(t_bars["trading_day"], t_bars["Close"]))

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
# Step 7: Determine gate_UP per ticker per day (EMA9 > EMA21 on last bar)
# ---------------------------------------------------------------------------

def compute_gate_up(bars_4h: pd.DataFrame, equity_tickers: list) -> dict:
    """Compute gate_UP: EMA9 > EMA21 on the last 4H bar of each trading day.

    Returns: {ticker: {date: bool}}
    """
    print("\nComputing gate_UP (EMA9 > EMA21)...")

    gate_up = {}
    for ticker in equity_tickers:
        t_bars = bars_4h[bars_4h["Ticker"] == ticker].copy()
        # Last bar per day
        last_bar = t_bars.sort_values("bar_num").groupby("trading_day").last()
        ticker_gate = {}
        for day, row in last_bar.iterrows():
            if pd.notna(row["ema9"]) and pd.notna(row["ema21"]):
                ticker_gate[day] = row["ema9"] > row["ema21"]
        gate_up[ticker] = ticker_gate

    total = sum(len(v) for v in gate_up.values())
    up_count = sum(sum(1 for x in v.values() if x) for v in gate_up.values())
    print(f"  Ticker-days with gate data: {total}")
    print(f"  Ticker-days gate_UP: {up_count} ({up_count / total * 100:.1f}%)" if total > 0 else "")
    return gate_up


# ---------------------------------------------------------------------------
# Step 8: Print comprehensive data prep summary
# ---------------------------------------------------------------------------

def print_summary(bars_4h, equity_tickers, vix_daily, rs_rankings,
                  daily_highs, gate_up, earnings_exclusions):
    """Print the comprehensive data prep summary."""
    print("\n" + "=" * 60)
    print("=== RS Leader Data Prep Summary ===")
    print("=" * 60)

    # --- 4H Bars ---
    total_bars = len(bars_4h)
    all_days = sorted(bars_4h["trading_day"].unique())
    bars_after_warmup = bars_4h["ema21"].notna().sum()

    print(f"\n4H Bars:")
    print(f"  Tickers loaded: {len(equity_tickers)}")
    print(f"  Trading days: {len(all_days)} ({all_days[0]} to {all_days[-1]})")
    print(f"  Total 4H bars: {total_bars}")
    print(f"  Bars after EMA warmup: {bars_after_warmup}")

    # --- VIX (FRED VIXCLS) ---
    print(f"\nVIX (FRED VIXCLS — backtester/data/vix_daily.csv):")
    if vix_daily:
        vals = list(vix_daily.values())
        print(f"  Days with data: {len(vix_daily)}")
        print(f"  VIX range: {min(vals):.2f} to {max(vals):.2f}")
        for thresh in [18, 20, 22, 25]:
            count = sum(1 for v in vals if v < thresh)
            pct = count / len(vals) * 100
            print(f"  Days VIX < {thresh}: {count} ({pct:.1f}%)")
    else:
        print("  WARNING: No VIX data available!")

    # --- Relative Strength ---
    print(f"\nRelative Strength:")
    rs_days = sorted(rs_rankings.keys())
    print(f"  Days with RS rankings: {len(rs_days)}")
    if rs_days:
        leader_counts = {}
        for day, data in rs_rankings.items():
            for ticker, info in data.items():
                if info["is_leader"]:
                    leader_counts[ticker] = leader_counts.get(ticker, 0) + 1
        top_leaders = sorted(leader_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        print(f"  Most frequent leaders (top 5):")
        for ticker, count in top_leaders:
            pct = count / len(rs_days) * 100
            print(f"    {ticker}: {count} days ({pct:.1f}%)")

    # --- 60-Day High ---
    print(f"\n60-Day High:")
    total_near = 0
    total_entries = 0
    for ticker_data in daily_highs.values():
        for info in ticker_data.values():
            total_entries += 1
            if info["near_high"]:
                total_near += 1
    if total_entries > 0:
        print(f"  Ticker-days near 60d high: {total_near} ({total_near / total_entries * 100:.1f}%)")

    # --- Combined filter: VIX<20 + leader + near_high + gate_UP ---
    # Convert VIX keys (strings) to date objects for matching
    vix_by_date = {}
    for k, v in vix_daily.items():
        if isinstance(k, str):
            vix_by_date[datetime.date.fromisoformat(k)] = v
        else:
            vix_by_date[k] = v

    print(f"\nCombined (VIX<20 + leader + near_high + gate_UP):")
    combined_count = 0
    combined_tickers = set()
    for day in rs_days:
        vix_val = vix_by_date.get(day)
        if vix_val is None or vix_val >= 20:
            continue
        day_rs = rs_rankings.get(day, {})
        for ticker, info in day_rs.items():
            if not info["is_leader"]:
                continue
            high_info = daily_highs.get(ticker, {}).get(day)
            if high_info is None or not high_info["near_high"]:
                continue
            ticker_gate = gate_up.get(ticker, {}).get(day)
            if not ticker_gate:
                continue
            combined_count += 1
            combined_tickers.add(ticker)

    print(f"  Ticker-days: {combined_count}")

    # --- Earnings exclusions ---
    print(f"\nEarnings exclusions: {len(earnings_exclusions)} ticker-days")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("RS Leader Pullback Backtest — Data Preparation (FRESH START)")
    print("=" * 60)

    # Step 1: Load and synthesize 4H bars
    print("\n--- Step 1: Loading M5 data and synthesizing 4H bars ---")
    bars_4h, equity_tickers = load_equity_4h_bars()

    # Step 2: Compute EMAs
    print("\n--- Step 2: Computing EMA9 and EMA21 on 4H close ---")
    bars_4h = add_emas(bars_4h)
    for ticker in equity_tickers[:3]:
        t_bars = bars_4h[bars_4h["Ticker"] == ticker]
        valid_ema9 = t_bars["ema9"].notna().sum()
        valid_ema21 = t_bars["ema21"].notna().sum()
        print(f"  {ticker}: {len(t_bars)} bars, EMA9 valid: {valid_ema9}, EMA21 valid: {valid_ema21}")
    print(f"  ... ({len(equity_tickers)} tickers total)")

    # Step 3: Load daily VIX from FRED VIXCLS
    print("\n--- Step 3: Loading VIX from FRED VIXCLS ---")
    vix_daily = load_vix_daily()

    # Step 4: RS rankings
    print("\n--- Step 4: Computing RS rankings ---")
    rs_rankings = compute_rs_rankings(bars_4h, equity_tickers)

    # Step 5: 60-day rolling high
    print("\n--- Step 5: Computing 60-day rolling highs ---")
    daily_highs = compute_60d_high(bars_4h, equity_tickers)

    # Step 6: Earnings calendar
    print("\n--- Step 6: Loading earnings calendar ---")
    earnings_exclusions = load_earnings_calendar()

    # Step 7: gate_UP
    print("\n--- Step 7: Computing gate_UP ---")
    gate_up = compute_gate_up(bars_4h, equity_tickers)

    # Step 8: Summary
    print_summary(bars_4h, equity_tickers, vix_daily, rs_rankings,
                  daily_highs, gate_up, earnings_exclusions)

    # Save prepared data
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    prepared_data = {
        "bars_4h": bars_4h,
        "equity_tickers": equity_tickers,
        "vix_daily": vix_daily,
        "rs_rankings": rs_rankings,
        "daily_highs": daily_highs,
        "gate_up": gate_up,
        "earnings_exclusions": earnings_exclusions,
    }

    with open(_OUTPUT_PKL, "wb") as f:
        pickle.dump(prepared_data, f)

    print(f"\nPrepared data saved to: {_OUTPUT_PKL}")
    print("Data prep complete. Ready for Part 2 (signal detection).")


if __name__ == "__main__":
    main()
