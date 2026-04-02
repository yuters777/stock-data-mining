"""
RS Leader Pullback Backtest — Data Preparation + Baseline Backtest.

Part 1 (data prep):
  - 4H bars with EMA9/EMA21 for 27 equity tickers
  - Daily VIX data from FRED VIXCLS (backtester/data/vix_daily.csv)
  - Daily relative-strength rankings (20-day returns, top 30% = leaders)
  - 60-day rolling high for each ticker
  - Earnings calendar for exclusion zones

Part 2 (--baseline):
  - Signal detection: RS leaders near 60d high, EMA9>EMA21, pullback entry
  - Trade simulation with exit rules (EMA9 cross, EMA21 stop, 8-bar max)
  - Report: N, mean return, WR, PF, breakdowns by sector and RS rank

Usage:
    python backtests/rs_leader_backtest.py            # data prep only
    python backtests/rs_leader_backtest.py --baseline  # data prep + backtest
"""

import argparse
import sys
from pathlib import Path

# Ensure repo root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import pickle

import numpy as np
import pandas as pd

from utils.data_loader import load_m5_regsess

# --- Paths ---
_EARNINGS_CSV = _REPO_ROOT / "backtester" / "data" / "fmp_earnings.csv"
_VIX_CSV = _REPO_ROOT / "backtester" / "data" / "vix_daily.csv"
_OUTPUT_DIR = _REPO_ROOT / "backtest_output"
_OUTPUT_PKL = _OUTPUT_DIR / "rs_leader_prepared_data.pkl"

# --- Ticker lists ---
# 27 equity tickers = all available minus SPY, VIXY, BTC, ETH
_EXCLUDE_TICKERS = {"SPY", "VIXY", "BTC_crypto", "ETH_crypto", "BTC", "ETH"}

# Tickers that have data files (discovered dynamically)
_FETCHED_DIR = _REPO_ROOT / "Fetched_Data"


# ---------------------------------------------------------------------------
# 4H bar synthesis (reused from pead_lite_backtest.py)
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
# Step 1: Load M5 data and build 4H bars for all equity tickers
# ---------------------------------------------------------------------------

def discover_equity_tickers():
    """Discover available equity tickers from Fetched_Data/ directory."""
    available = set()
    for f in _FETCHED_DIR.glob("*_data.csv"):
        ticker = f.stem.replace("_data", "")
        available.add(ticker)
    equity = sorted(available - _EXCLUDE_TICKERS)
    return equity


def load_all_4h_bars(equity_tickers):
    """Load M5 data and synthesize 4H bars for all equity tickers."""
    print("\n--- Step 1: Loading M5 data & synthesizing 4H bars ---")
    ticker_4h = {}
    failed = []
    for ticker in equity_tickers:
        try:
            m5 = load_m5_regsess(ticker)
            bars = synthesize_4h_bars(m5)
            ticker_4h[ticker] = bars
            days = sorted(bars["trading_day"].unique())
            print(f"  {ticker}: {len(m5):>6} M5 -> {len(bars):>5} 4H bars, "
                  f"{len(days)} days ({days[0]} to {days[-1]})")
        except (FileNotFoundError, ValueError) as e:
            failed.append(ticker)
            print(f"  {ticker}: SKIPPED -- {e}")

    print(f"\n  Loaded: {len(ticker_4h)}/{len(equity_tickers)} tickers")
    if failed:
        print(f"  Failed: {failed}")
    return ticker_4h


# ---------------------------------------------------------------------------
# Step 2: Compute EMA 9 and EMA 21 on 4H close
# ---------------------------------------------------------------------------

def add_emas(ticker_4h):
    """Add EMA9 and EMA21 columns to each ticker's 4H bar DataFrame."""
    print("\n--- Step 2: Computing EMA9 / EMA21 on 4H close ---")
    total_bars = 0
    bars_after_warmup = 0

    for ticker, bars in ticker_4h.items():
        bars = bars.sort_values(["trading_day", "bar_num"]).reset_index(drop=True)
        bars["ema9"] = bars["Close"].ewm(span=9, min_periods=9).mean()
        bars["ema21"] = bars["Close"].ewm(span=21, min_periods=21).mean()
        ticker_4h[ticker] = bars
        total_bars += len(bars)
        bars_after_warmup += bars["ema21"].notna().sum()

    print(f"  Total 4H bars: {total_bars}")
    print(f"  Bars after EMA21 warmup: {bars_after_warmup}")
    return ticker_4h


# ---------------------------------------------------------------------------
# Step 3: Load daily VIX data (FRED VIXCLS)
# ---------------------------------------------------------------------------

def load_vix_daily():
    """Load daily VIX close from backtester/data/vix_daily.csv (FRED VIXCLS)."""
    print("\n--- Step 3: Loading daily VIX data (FRED VIXCLS) ---")

    if not _VIX_CSV.exists():
        print(f"  ERROR: VIX file not found: {_VIX_CSV}")
        return {}

    df = pd.read_csv(_VIX_CSV)
    df["date"] = pd.to_datetime(df["date"]).dt.date

    vix_daily = {}
    for _, row in df.iterrows():
        vix_daily[row["date"]] = row["vix_close"]

    vix_values = list(vix_daily.values())
    print(f"  Days with VIX data: {len(vix_daily)}")
    if vix_values:
        print(f"  VIX range: {min(vix_values):.2f} to {max(vix_values):.2f}")
        for thresh in [20, 22, 25]:
            count = sum(1 for v in vix_values if v < thresh)
            pct = count / len(vix_values) * 100
            print(f"  Days VIX < {thresh}: {count} ({pct:.1f}%)")
            if thresh == 20 and count < 50:
                print(f"  *** NOTE: VIX<20 regime rare in this period ({count} days)")

    return vix_daily


# ---------------------------------------------------------------------------
# Step 4: Compute daily relative strength rankings
# ---------------------------------------------------------------------------

def compute_rs_rankings(ticker_4h):
    """Compute daily RS rankings based on 20-trading-day returns."""
    print("\n--- Step 4: Computing daily relative strength rankings ---")

    # Build daily close series for each ticker (Bar 2 close = end of day)
    daily_close = {}  # {ticker: {date: close}}
    for ticker, bars in ticker_4h.items():
        bar2 = bars[bars["bar_num"] == 2].copy()
        daily_close[ticker] = {row["trading_day"]: row["Close"]
                               for _, row in bar2.iterrows()}

    # Get union of all trading days, sorted
    all_days = sorted(set(d for closes in daily_close.values() for d in closes))
    print(f"  Total unique trading days across tickers: {len(all_days)}")

    # Build day index for 20-day lookback
    day_index = {d: i for i, d in enumerate(all_days)}

    rs_data = {}  # {date: {ticker: {rs_return, rs_rank, is_leader}}}
    n_leaders_threshold = max(1, int(len(ticker_4h) * 0.30))  # top 30%

    for i, day in enumerate(all_days):
        if i < 20:
            continue  # need 20 trading days of history

        day_20_ago = all_days[i - 20]
        ticker_returns = {}

        for ticker in ticker_4h:
            close_today = daily_close[ticker].get(day)
            close_20d = daily_close[ticker].get(day_20_ago)
            if close_today is not None and close_20d is not None and close_20d > 0:
                rs_ret = (close_today - close_20d) / close_20d * 100
                ticker_returns[ticker] = rs_ret

        if not ticker_returns:
            continue

        # Rank by rs_return descending
        sorted_tickers = sorted(ticker_returns.items(), key=lambda x: x[1], reverse=True)
        day_data = {}
        for rank, (ticker, rs_ret) in enumerate(sorted_tickers, 1):
            day_data[ticker] = {
                "rs_return": rs_ret,
                "rs_rank": rank,
                "is_leader": rank <= n_leaders_threshold,
            }
        rs_data[day] = day_data

    print(f"  Days with RS rankings: {len(rs_data)} (after 20-day warmup)")
    print(f"  RS leader threshold: top {n_leaders_threshold} tickers (top 30%)")

    # Most frequent leaders
    leader_counts = {}
    for day_data in rs_data.values():
        for ticker, info in day_data.items():
            if info["is_leader"]:
                leader_counts[ticker] = leader_counts.get(ticker, 0) + 1

    if leader_counts:
        top5 = sorted(leader_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        total_rs_days = len(rs_data)
        print(f"  Most frequent leaders (top 5):")
        for ticker, count in top5:
            print(f"    {ticker}: {count} days ({count / total_rs_days * 100:.1f}%)")

    # Average RS spread (top vs bottom)
    spreads = []
    for day_data in rs_data.values():
        returns = [info["rs_return"] for info in day_data.values()]
        if len(returns) >= 2:
            top_avg = np.mean(sorted(returns, reverse=True)[:n_leaders_threshold])
            bot_avg = np.mean(sorted(returns)[:n_leaders_threshold])
            spreads.append(top_avg - bot_avg)
    if spreads:
        print(f"  Average RS spread (top vs bottom): {np.mean(spreads):.2f}%")

    return rs_data


# ---------------------------------------------------------------------------
# Step 5: Compute 60-day rolling high
# ---------------------------------------------------------------------------

def compute_60d_high(ticker_4h):
    """Compute 60-trading-day rolling high of daily close for each ticker."""
    print("\n--- Step 5: Computing 60-day rolling high ---")

    high_60d_data = {}  # {ticker: {date: {high_60d, near_high}}}

    for ticker, bars in ticker_4h.items():
        bar2 = bars[bars["bar_num"] == 2].sort_values("trading_day")
        days = bar2["trading_day"].values
        closes = bar2["Close"].values

        ticker_data = {}
        for i in range(len(days)):
            if i < 59:
                continue  # need 60 days
            window_closes = closes[i - 59:i + 1]
            h60 = float(np.max(window_closes))
            c = float(closes[i])
            ticker_data[days[i]] = {
                "high_60d": h60,
                "near_high": c >= h60 * 0.95,
            }
        high_60d_data[ticker] = ticker_data

    # Summary stats
    total_days_with_data = 0
    near_high_count = 0
    for ticker_data in high_60d_data.values():
        for info in ticker_data.values():
            total_days_with_data += 1
            if info["near_high"]:
                near_high_count += 1

    if total_days_with_data > 0:
        pct = near_high_count / total_days_with_data * 100
        print(f"  Ticker-days with 60d high data: {total_days_with_data}")
        print(f"  Ticker-days near 60d high (>=95%): {near_high_count} ({pct:.1f}%)")
    else:
        print(f"  No 60d high data computed (insufficient history)")

    return high_60d_data


# ---------------------------------------------------------------------------
# Step 6: Load earnings calendar for exclusion
# ---------------------------------------------------------------------------

def load_earnings_calendar():
    """Load earnings dates and build exclusion set (earnings day + day before)."""
    print("\n--- Step 6: Loading earnings calendar for exclusion ---")

    if not _EARNINGS_CSV.exists():
        print(f"  WARNING: Earnings file not found: {_EARNINGS_CSV}")
        return set()

    df = pd.read_csv(_EARNINGS_CSV)
    df["earnings_date"] = pd.to_datetime(df["earnings_date"]).dt.date

    exclusion_set = set()
    for _, row in df.iterrows():
        ticker = row["ticker"]
        edate = row["earnings_date"]
        exclusion_set.add((ticker, edate))
        # Also exclude day before earnings
        day_before = edate - pd.Timedelta(days=1)
        # Adjust for weekends: if day_before is Sunday, use Friday
        import datetime
        if isinstance(day_before, pd.Timestamp):
            day_before = day_before.date()
        if hasattr(day_before, 'weekday'):
            wd = day_before.weekday()
            if wd == 6:  # Sunday
                day_before = day_before - datetime.timedelta(days=2)
            elif wd == 5:  # Saturday
                day_before = day_before - datetime.timedelta(days=1)
        exclusion_set.add((ticker, day_before))

    n_tickers = len(df["ticker"].unique())
    print(f"  Earnings events loaded: {len(df)} (for {n_tickers} tickers)")
    print(f"  Exclusion set size: {len(exclusion_set)} ticker-days "
          f"(earnings day + day before)")

    return exclusion_set


# ---------------------------------------------------------------------------
# Step 7: Print comprehensive data prep summary
# ---------------------------------------------------------------------------

def print_summary(ticker_4h, vix_daily, rs_data, high_60d_data, earnings_exclusions):
    """Print comprehensive data prep summary."""
    print("\n" + "=" * 60)
    print("=== RS Leader Data Prep Summary ===")
    print("=" * 60)

    # 4H Bars
    total_bars = sum(len(bars) for bars in ticker_4h.values())
    bars_after_warmup = sum(bars["ema21"].notna().sum() for bars in ticker_4h.values())
    all_days = set()
    for bars in ticker_4h.values():
        all_days.update(bars["trading_day"].unique())
    sorted_days = sorted(all_days)

    print(f"\n4H Bars:")
    print(f"  Tickers loaded: {len(ticker_4h)}/27")
    print(f"  Trading days: {len(sorted_days)} ({sorted_days[0]} to {sorted_days[-1]})")
    print(f"  Total 4H bars: {total_bars}")
    print(f"  Bars after EMA warmup: {bars_after_warmup}")

    # VIX (FRED VIXCLS)
    print(f"\nVIX (FRED VIXCLS daily close):")
    if vix_daily:
        vix_values = list(vix_daily.values())
        print(f"  Days with VIX data: {len(vix_daily)}")
        print(f"  VIX range: {min(vix_values):.2f} to {max(vix_values):.2f}")
        for thresh in [20, 22, 25]:
            count = sum(1 for v in vix_values if v < thresh)
            pct = count / len(vix_values) * 100
            print(f"  Days VIX < {thresh}: {count} ({pct:.1f}%)")
        if sum(1 for v in vix_values if v < 20) < 50:
            print(f"  *** NOTE: VIX<20 regime rare in this period")
    else:
        print(f"  NO VIX DATA AVAILABLE")

    # Relative Strength
    print(f"\nRelative Strength:")
    print(f"  Days with RS rankings: {len(rs_data)} (after 20-day warmup)")
    if rs_data:
        # RS spread
        n_leaders = max(1, int(len(ticker_4h) * 0.30))
        spreads = []
        for day_data in rs_data.values():
            returns = [info["rs_return"] for info in day_data.values()]
            if len(returns) >= 2:
                top_avg = np.mean(sorted(returns, reverse=True)[:n_leaders])
                bot_avg = np.mean(sorted(returns)[:n_leaders])
                spreads.append(top_avg - bot_avg)
        if spreads:
            print(f"  Average RS spread (top vs bottom): {np.mean(spreads):.2f}%")

        # Most frequent leaders
        leader_counts = {}
        for day_data in rs_data.values():
            for ticker, info in day_data.items():
                if info["is_leader"]:
                    leader_counts[ticker] = leader_counts.get(ticker, 0) + 1
        if leader_counts:
            top5 = sorted(leader_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            total_rs_days = len(rs_data)
            print(f"  Most frequent leaders (top 5 by days-in-top-{n_leaders}):")
            for ticker, count in top5:
                print(f"    {ticker}: {count} days ({count / total_rs_days * 100:.1f}%)")

    # 60-Day High
    print(f"\n60-Day High:")
    total_td = 0
    near_high_count = 0
    for ticker_data in high_60d_data.values():
        for info in ticker_data.values():
            total_td += 1
            if info["near_high"]:
                near_high_count += 1
    if total_td > 0:
        pct_near = near_high_count / total_td * 100
        # Average % of tickers near 60d high per day
        day_near_pcts = {}
        for ticker, ticker_data in high_60d_data.items():
            for day, info in ticker_data.items():
                if day not in day_near_pcts:
                    day_near_pcts[day] = [0, 0]
                day_near_pcts[day][1] += 1
                if info["near_high"]:
                    day_near_pcts[day][0] += 1
        daily_pcts = [n / t * 100 for n, t in day_near_pcts.values() if t > 0]
        if daily_pcts:
            print(f"  Average % of tickers near 60d high per day: {np.mean(daily_pcts):.1f}%")
    else:
        print(f"  No 60d high data available")

    # Combined criteria — show with and without VIX filter
    # First: leader + near_high (no VIX filter)
    print(f"\nCombined (leader + near_high, no VIX filter):")
    no_vix_count = 0
    no_vix_tickers = set()
    if rs_data and high_60d_data:
        for day in rs_data:
            day_rs = rs_data[day]
            for ticker, rs_info in day_rs.items():
                if not rs_info["is_leader"]:
                    continue
                h60 = high_60d_data.get(ticker, {}).get(day)
                if h60 and h60["near_high"]:
                    no_vix_count += 1
                    no_vix_tickers.add(ticker)
    print(f"  Ticker-days meeting criteria: {no_vix_count}")
    print(f"  Unique tickers: {len(no_vix_tickers)}/{len(ticker_4h)}")

    # With VIX filter at multiple thresholds
    for vix_thresh in [20, 22, 25]:
        combined_count = 0
        combined_tickers = set()
        if vix_daily and rs_data and high_60d_data:
            for day in rs_data:
                vix_val = vix_daily.get(day)
                if vix_val is None or vix_val >= vix_thresh:
                    continue
                day_rs = rs_data[day]
                for ticker, rs_info in day_rs.items():
                    if not rs_info["is_leader"]:
                        continue
                    h60 = high_60d_data.get(ticker, {}).get(day)
                    if h60 and h60["near_high"]:
                        combined_count += 1
                        combined_tickers.add(ticker)
        print(f"\n  With VIX<{vix_thresh}: {combined_count} ticker-days, "
              f"{len(combined_tickers)} unique tickers")

    # Earnings exclusions
    print(f"\nEarnings exclusions: {len(earnings_exclusions)} ticker-days excluded")


# ---------------------------------------------------------------------------
# Step 8: Save prepared data
# ---------------------------------------------------------------------------

def save_data(ticker_4h, vix_daily, rs_data, high_60d_data, earnings_exclusions):
    """Save all prepared data to pickle for Part 2."""
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    data = {
        "ticker_4h": ticker_4h,
        "vix_daily": vix_daily,
        "rs_data": rs_data,
        "high_60d_data": high_60d_data,
        "earnings_exclusions": earnings_exclusions,
    }

    with open(_OUTPUT_PKL, "wb") as f:
        pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)

    size_mb = _OUTPUT_PKL.stat().st_size / (1024 * 1024)
    print(f"\nPrepared data saved to: {_OUTPUT_PKL} ({size_mb:.1f} MB)")


# ===========================================================================
# Part 2: Signal Detection & Baseline Backtest
# ===========================================================================

SECTORS = {
    "mega_tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA"],
    "growth_semi": ["TSLA", "AMD", "SMCI", "PLTR", "AVGO", "ARM", "TSM", "MU", "INTC"],
    "crypto_proxy": ["COIN", "MSTR", "MARA"],
    "financials": ["GS", "JPM"],
    "other": ["NFLX", "LLY", "UBER", "SNOW", "CRWD", "BA", "WMT"],
}

_TICKER_TO_SECTOR = {}
for _sec, _tlist in SECTORS.items():
    for _t in _tlist:
        _TICKER_TO_SECTOR[_t] = _sec


def _is_down_bar(bar_row):
    """A 4H bar is 'down' when Close < Open."""
    return bar_row["Close"] < bar_row["Open"]


def detect_signals_and_trade(ticker_4h, vix_daily, rs_data, high_60d_data,
                             earnings_exclusions):
    """Scan every VIX<20 trading day for pullback entry signals, simulate trades.

    Returns a list of trade dicts.
    """
    print("\n" + "=" * 60)
    print("=== Part 2: Signal Detection & Baseline Backtest ===")
    print("=" * 60)

    # Build a global bar sequence per ticker for easy forward-walking
    ticker_bars = {}  # {ticker: sorted DataFrame with sequential index}
    for ticker, bars in ticker_4h.items():
        b = bars.sort_values(["trading_day", "bar_num"]).reset_index(drop=True)
        ticker_bars[ticker] = b

    # VIX<20 trading days
    vix_ok_days = {d for d, v in vix_daily.items() if v < 20}
    print(f"\n  VIX<20 days: {len(vix_ok_days)}")

    trades = []
    signals_checked = 0
    skipped_earnings = 0

    # Walk each VIX<20 day
    sorted_vix_days = sorted(vix_ok_days)

    for day in sorted_vix_days:
        day_rs = rs_data.get(day)
        if day_rs is None:
            continue

        for ticker, rs_info in day_rs.items():
            # Must be RS leader
            if not rs_info["is_leader"]:
                continue

            # Must be near 60d high
            h60 = high_60d_data.get(ticker, {}).get(day)
            if h60 is None or not h60["near_high"]:
                continue

            # Skip earnings exclusion zone
            if (ticker, day) in earnings_exclusions:
                skipped_earnings += 1
                continue

            signals_checked += 1

            bars = ticker_bars.get(ticker)
            if bars is None:
                continue

            # Find bars for this trading day
            day_mask = bars["trading_day"] == day
            day_indices = bars.index[day_mask].tolist()
            if not day_indices:
                continue

            # Gate: EMA9 > EMA21 on the last bar of this day
            last_day_idx = day_indices[-1]
            last_bar = bars.loc[last_day_idx]
            if pd.isna(last_bar["ema9"]) or pd.isna(last_bar["ema21"]):
                continue
            if last_bar["ema9"] <= last_bar["ema21"]:
                continue

            # Look for pullback: scan forward from end of this day
            # We need 1-2 consecutive down bars, all closing above EMA21
            # Then entry on first bar closing above EMA9
            scan_start = last_day_idx + 1
            if scan_start >= len(bars):
                continue

            # Scan up to 10 bars ahead for a pullback pattern
            pullback_bars = 0
            pullback_valid = False
            scan_end = min(scan_start + 10, len(bars))

            i = scan_start
            while i < scan_end:
                bar = bars.loc[i]
                if pd.isna(bar["ema21"]) or pd.isna(bar["ema9"]):
                    break

                if _is_down_bar(bar):
                    if bar["Close"] <= bar["ema21"]:
                        # Closed below EMA21 — pullback invalidated
                        break
                    pullback_bars += 1
                    if pullback_bars > 2:
                        break  # too many consecutive down bars
                    i += 1
                else:
                    # Up bar — if we had a pullback, check for entry
                    if pullback_bars >= 1:
                        pullback_valid = True
                    break

            if not pullback_valid:
                continue

            # Entry: scan from bar i for first 4H bar closing above EMA9
            entry_idx = None
            for j in range(i, min(i + 5, len(bars))):
                bar = bars.loc[j]
                if pd.isna(bar["ema9"]):
                    break
                if bar["Close"] > bar["ema9"]:
                    entry_idx = j
                    break

            if entry_idx is None:
                continue

            entry_bar = bars.loc[entry_idx]
            entry_price = entry_bar["Close"]

            # Simulate exit: walk forward up to 8 bars
            exit_idx = None
            exit_reason = "max_bars"
            exit_price = None

            for k in range(entry_idx + 1, min(entry_idx + 9, len(bars))):
                bar = bars.loc[k]
                if pd.isna(bar["ema9"]) or pd.isna(bar["ema21"]):
                    exit_reason = "data_end"
                    exit_idx = k
                    exit_price = bar["Close"]
                    break

                if bar["Close"] < bar["ema21"]:
                    exit_reason = "ema21_stop"
                    exit_idx = k
                    exit_price = bar["Close"]
                    break
                elif bar["Close"] < bar["ema9"]:
                    exit_reason = "ema9_cross"
                    exit_idx = k
                    exit_price = bar["Close"]
                    break

            if exit_idx is None:
                # 8-bar max hold — exit at bar entry_idx + 8
                max_idx = entry_idx + 8
                if max_idx < len(bars):
                    exit_idx = max_idx
                    exit_price = bars.loc[max_idx]["Close"]
                else:
                    # Not enough bars to complete the trade
                    continue

            ret_pct = (exit_price - entry_price) / entry_price * 100
            hold_bars = exit_idx - entry_idx

            trades.append({
                "ticker": ticker,
                "sector": _TICKER_TO_SECTOR.get(ticker, "unclassified"),
                "signal_day": day,
                "rs_rank": rs_info["rs_rank"],
                "rs_return": rs_info["rs_return"],
                "vix": vix_daily[day],
                "entry_day": bars.loc[entry_idx]["trading_day"],
                "entry_bar": int(bars.loc[entry_idx]["bar_num"]),
                "entry_price": entry_price,
                "exit_day": bars.loc[exit_idx]["trading_day"],
                "exit_bar": int(bars.loc[exit_idx]["bar_num"]),
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "return_pct": ret_pct,
                "hold_bars": hold_bars,
                "pullback_bars": pullback_bars,
            })

    print(f"  Candidates checked (leader + near high + VIX<20): {signals_checked}")
    print(f"  Skipped for earnings: {skipped_earnings}")
    print(f"  Trades generated: {len(trades)}")
    return trades


def print_baseline_report(trades):
    """Print detailed baseline backtest report."""
    print("\n" + "=" * 60)
    print("=== Baseline Backtest Report ===")
    print("=" * 60)

    if not trades:
        print("\n  NO TRADES FOUND.")
        return

    df = pd.DataFrame(trades)
    n = len(df)
    wins = df[df["return_pct"] > 0]
    losses = df[df["return_pct"] <= 0]
    wr = len(wins) / n * 100

    gross_profit = wins["return_pct"].sum() if len(wins) > 0 else 0
    gross_loss = abs(losses["return_pct"].sum()) if len(losses) > 0 else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    print(f"\n  N trades:       {n}")
    print(f"  Mean return:    {df['return_pct'].mean():.3f}%")
    print(f"  Median return:  {df['return_pct'].median():.3f}%")
    print(f"  Std dev:        {df['return_pct'].std():.3f}%")
    print(f"  Win rate:       {wr:.1f}% ({len(wins)}W / {len(losses)}L)")
    print(f"  Profit factor:  {pf:.2f}")
    print(f"  Best trade:     {df['return_pct'].max():.3f}%")
    print(f"  Worst trade:    {df['return_pct'].min():.3f}%")
    print(f"  Avg hold (bars):{df['hold_bars'].mean():.1f}")

    # Exit reason breakdown
    print(f"\n  Exit reasons:")
    for reason, grp in df.groupby("exit_reason"):
        print(f"    {reason:15s}: {len(grp):>3} trades, "
              f"mean {grp['return_pct'].mean():+.3f}%, "
              f"WR {(grp['return_pct'] > 0).mean() * 100:.0f}%")

    # Sector breakdown
    print(f"\n  By sector:")
    print(f"  {'Sector':<16s} {'N':>4s} {'Mean%':>8s} {'WR%':>6s} {'PF':>6s}")
    print(f"  {'-'*42}")
    for sector in sorted(df["sector"].unique()):
        s = df[df["sector"] == sector]
        s_n = len(s)
        s_mean = s["return_pct"].mean()
        s_wr = (s["return_pct"] > 0).mean() * 100
        s_gp = s.loc[s["return_pct"] > 0, "return_pct"].sum() if (s["return_pct"] > 0).any() else 0
        s_gl = abs(s.loc[s["return_pct"] <= 0, "return_pct"].sum()) if (s["return_pct"] <= 0).any() else 0
        s_pf = s_gp / s_gl if s_gl > 0 else float("inf")
        print(f"  {sector:<16s} {s_n:>4d} {s_mean:>+8.3f} {s_wr:>6.1f} {s_pf:>6.2f}")

    # RS rank breakdown
    print(f"\n  By RS rank bucket:")
    print(f"  {'Rank':<12s} {'N':>4s} {'Mean%':>8s} {'WR%':>6s} {'PF':>6s}")
    print(f"  {'-'*38}")
    rank_bins = [(1, 3, "Top 1-3"), (4, 6, "Rank 4-6"), (7, 99, "Rank 7+")]
    for lo, hi, label in rank_bins:
        rb = df[(df["rs_rank"] >= lo) & (df["rs_rank"] <= hi)]
        if len(rb) == 0:
            continue
        rb_n = len(rb)
        rb_mean = rb["return_pct"].mean()
        rb_wr = (rb["return_pct"] > 0).mean() * 100
        rb_gp = rb.loc[rb["return_pct"] > 0, "return_pct"].sum() if (rb["return_pct"] > 0).any() else 0
        rb_gl = abs(rb.loc[rb["return_pct"] <= 0, "return_pct"].sum()) if (rb["return_pct"] <= 0).any() else 0
        rb_pf = rb_gp / rb_gl if rb_gl > 0 else float("inf")
        print(f"  {label:<12s} {rb_n:>4d} {rb_mean:>+8.3f} {rb_wr:>6.1f} {rb_pf:>6.2f}")

    # Top tickers by trade count
    print(f"\n  Top tickers by trade count:")
    ticker_counts = df.groupby("ticker").agg(
        N=("return_pct", "count"),
        mean_ret=("return_pct", "mean"),
        wr=("return_pct", lambda x: (x > 0).mean() * 100),
    ).sort_values("N", ascending=False).head(10)
    for ticker, row in ticker_counts.iterrows():
        print(f"    {ticker:<6s}: {int(row['N']):>3} trades, "
              f"mean {row['mean_ret']:+.3f}%, WR {row['wr']:.0f}%")

    # Pullback length breakdown
    print(f"\n  By pullback length:")
    for pb in sorted(df["pullback_bars"].unique()):
        pb_df = df[df["pullback_bars"] == pb]
        print(f"    {pb}-bar pullback: {len(pb_df)} trades, "
              f"mean {pb_df['return_pct'].mean():+.3f}%, "
              f"WR {(pb_df['return_pct'] > 0).mean() * 100:.0f}%")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="RS Leader Pullback Backtest")
    parser.add_argument("--baseline", action="store_true",
                        help="Run Part 2: signal detection + baseline backtest")
    args = parser.parse_args()

    print("=" * 60)
    print("RS Leader Pullback Backtest — Data Preparation")
    print("=" * 60)

    # Step 1: Discover tickers and build 4H bars
    equity_tickers = discover_equity_tickers()
    print(f"\nEquity tickers discovered: {len(equity_tickers)}")
    print(f"  {equity_tickers}")
    ticker_4h = load_all_4h_bars(equity_tickers)

    # Step 2: Add EMAs
    ticker_4h = add_emas(ticker_4h)

    # Step 3: VIX daily (FRED VIXCLS)
    vix_daily = load_vix_daily()

    # Step 4: RS rankings
    rs_data = compute_rs_rankings(ticker_4h)

    # Step 5: 60-day rolling high
    high_60d_data = compute_60d_high(ticker_4h)

    # Step 6: Earnings exclusions
    earnings_exclusions = load_earnings_calendar()

    # Step 7: Print summary
    print_summary(ticker_4h, vix_daily, rs_data, high_60d_data, earnings_exclusions)

    # Step 8: Save
    save_data(ticker_4h, vix_daily, rs_data, high_60d_data, earnings_exclusions)

    print("\n--- Data preparation complete. ---")

    # Part 2: Baseline backtest
    if args.baseline:
        trades = detect_signals_and_trade(
            ticker_4h, vix_daily, rs_data, high_60d_data, earnings_exclusions,
        )
        print_baseline_report(trades)

        # Save trades
        if trades:
            trades_df = pd.DataFrame(trades)
            trades_csv = _OUTPUT_DIR / "rs_leader_baseline_trades.csv"
            trades_df.to_csv(trades_csv, index=False)
            print(f"\n  Trades saved to: {trades_csv}")
    else:
        print("  Run with --baseline to execute Part 2 (signal detection + backtest).")


if __name__ == "__main__":
    main()
