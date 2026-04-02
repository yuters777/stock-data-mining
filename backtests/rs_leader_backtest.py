"""
RS Leader Pullback Backtest.

Prepares data infrastructure for the RS Leader Pullback strategy:
  - 4H bars with EMA9/EMA21 for 27 equity tickers
  - Daily VIX from FRED VIXCLS (vix_daily.csv)
  - Daily relative-strength rankings (20-day returns)
  - 60-day rolling high
  - Earnings calendar for exclusion

Then runs a baseline backtest and optional parameter sweeps.

Reads:
  - Fetched_Data/{TICKER}_data.csv (M5 OHLCV bars, IST-encoded)
  - backtester/data/vix_daily.csv
  - backtester/data/fmp_earnings.csv

Produces:
  - backtest_output/rs_leader_prepared_data.pkl

Usage:
    python backtests/rs_leader_backtest.py            # baseline only
    python backtests/rs_leader_backtest.py --sweep     # baseline + parameter sweeps
"""

import argparse
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
_VIX_CSV = _REPO_ROOT / "backtester" / "data" / "vix_daily.csv"
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
# Step 3: Build daily VIX from FRED VIXCLS (vix_daily.csv)
# ---------------------------------------------------------------------------

def build_vix_daily() -> dict:
    """Load VIX daily close from backtester/data/vix_daily.csv (FRED VIXCLS).

    Returns: {datetime.date: float} mapping date to VIX close.
    """
    print("\nBuilding VIX data from vix_daily.csv...")
    if not _VIX_CSV.exists():
        print(f"  ERROR: VIX CSV not found: {_VIX_CSV}")
        return {}

    df = pd.read_csv(_VIX_CSV)
    vix_data = {}
    for _, row in df.iterrows():
        try:
            d = datetime.date.fromisoformat(str(row["date"]))
            val = float(row["vix_close"])
            if not np.isnan(val):
                vix_data[d] = val
        except (ValueError, TypeError):
            continue

    print(f"  VIX days: {len(vix_data)}")
    if vix_data:
        vals = list(vix_data.values())
        print(f"  VIX range: {min(vals):.2f} to {max(vals):.2f}")

    return vix_data


# ---------------------------------------------------------------------------
# Step 4: Compute daily relative strength rankings
# ---------------------------------------------------------------------------

def compute_rs_rankings(ticker_4h: dict, equity_tickers: list,
                        rs_pct: int = 30) -> dict:
    """Compute 20-day return RS rankings for each trading day.

    For each trading day, for each ticker:
      rs_return_20d = (close_today - close_20d_ago) / close_20d_ago * 100
      (20d = 20 trading days, not calendar days)

    Top rs_pct% = RS_LEADERS

    Returns: {date: {ticker: {rs_return, rs_rank, is_leader}}}
    """
    print(f"\nComputing daily RS rankings (top {rs_pct}%)...")

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
        n_leaders = max(1, int(len(sorted_tickers) * rs_pct / 100))  # Top rs_pct%

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
    print(f"\nVIX (FRED VIXCLS daily close):")
    if vix_proxy:
        vals = list(vix_proxy.values())
        print(f"  Days with VIX data: {len(vix_proxy)}")
        print(f"  VIX range: {min(vals):.2f} to {max(vals):.2f}")
        for thresh in [20, 22, 25]:
            count = sum(1 for v in vals if v < thresh)
            pct = count / len(vals) * 100
            print(f"  Days VIX < {thresh}: {count} ({pct:.1f}%)")
            if thresh == 20 and count < 50:
                print(f"  *** NOTE: VIX<20 regime rare in this period ({count} days)")
    else:
        print("  WARNING: No VIX data available!")

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
    for vix_thresh in [18, 20, 22, 25]:
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
        min_vix = min(vix_proxy.values())
        if min_vix >= 22:
            print(f"\n  *** WARNING: VIX never drops below 22 in this period "
                  f"(min={min_vix:.2f}).")
            print(f"  *** Consider relaxing VIX threshold or removing VIX filter "
                  f"for signal detection.")

    # --- Earnings exclusions ---
    print(f"\nEarnings exclusions: {len(earnings_exclusions)} ticker-days excluded")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Backtest Engine
# ---------------------------------------------------------------------------

def get_forward_4h_bars(bars_4h, ticker, entry_day, trading_days, max_bars):
    """Get up to max_bars 4H bars AFTER entry_day for a given ticker.

    Returns list of dicts with bar info, starting from Bar 1 of the
    next trading day after entry_day.
    """
    tb = bars_4h[bars_4h["Ticker"] == ticker] if "Ticker" in bars_4h.columns else bars_4h
    try:
        idx = trading_days.index(entry_day)
    except ValueError:
        return []

    fwd_days = trading_days[idx + 1:]
    fwd = []
    for d in fwd_days:
        day_bars = tb[tb["trading_day"] == d].sort_values("bar_num")
        for _, row in day_bars.iterrows():
            fwd.append({
                "trading_day": d,
                "bar_num": row["bar_num"],
                "Open": row["Open"],
                "High": row["High"],
                "Low": row["Low"],
                "Close": row["Close"],
                "ema9": row.get("ema9"),
                "ema21": row.get("ema21"),
            })
            if len(fwd) >= max_bars:
                return fwd
    return fwd


def detect_pullback(bars_4h, ticker, day, trading_days, pullback_max):
    """Check if ticker has a pullback of 1..pullback_max consecutive down 4H bars
    ending on `day`.

    A 'down bar' = Close < Open on that 4H bar.
    Returns the actual number of consecutive down bars from the end, or 0.
    Caller should check 1 <= result <= pullback_max.
    """
    tb = bars_4h
    try:
        day_idx = trading_days.index(day)
    except ValueError:
        return 0

    # Collect recent bars up to and including `day` (look back enough days)
    lookback_days = trading_days[max(0, day_idx - pullback_max - 1):day_idx + 1]
    recent_bars = []
    for d in lookback_days:
        day_bars = tb[tb["trading_day"] == d].sort_values("bar_num")
        for _, row in day_bars.iterrows():
            recent_bars.append(row)

    if not recent_bars:
        return 0

    # Count consecutive down bars from the end (no cap)
    consec_down = 0
    for bar in reversed(recent_bars):
        if bar["Close"] < bar["Open"]:
            consec_down += 1
        else:
            break

    return consec_down


def apply_exit_strategy(entry_price, fwd_bars, exit_strategy):
    """Apply an exit strategy to forward bars and return (exit_price, bars_held, exit_reason).

    Exit strategies:
      "max_only"        — hold until max_bars (pure time-based)
      "ema9_ema21_max"  — exit on EMA9 break OR EMA21 break OR max bars
      "ema21_max_only"  — exit on EMA21 break OR max bars
      "trailing_50pct"  — exit if gives back >50% of max unrealized gain
      "fixed_stop_2pct" — exit if return drops to -2% from entry
    """
    if not fwd_bars:
        return None, 0, "no_bars"

    max_unrealized = 0.0

    for i, bar in enumerate(fwd_bars):
        bar_close = bar["Close"]
        ret = (bar_close - entry_price) / entry_price * 100

        if exit_strategy == "ema9_ema21_max":
            ema9 = bar.get("ema9")
            ema21 = bar.get("ema21")
            if ema9 is not None and not np.isnan(ema9) and bar_close < ema9:
                return bar_close, i + 1, "ema9_break"
            if ema21 is not None and not np.isnan(ema21) and bar_close < ema21:
                return bar_close, i + 1, "ema21_break"

        elif exit_strategy == "ema21_max_only":
            ema21 = bar.get("ema21")
            if ema21 is not None and not np.isnan(ema21) and bar_close < ema21:
                return bar_close, i + 1, "ema21_break"

        elif exit_strategy == "trailing_50pct":
            if ret > max_unrealized:
                max_unrealized = ret
            if max_unrealized > 0 and ret < max_unrealized * 0.5:
                return bar_close, i + 1, "trailing_50pct"

        elif exit_strategy == "fixed_stop_2pct":
            if ret <= -2.0:
                return bar_close, i + 1, "fixed_stop_2pct"

        # "max_only" falls through to end

    # Max bars reached
    last = fwd_bars[-1]
    return last["Close"], len(fwd_bars), "max_bars"


def run_rs_backtest(ticker_4h, ticker_trading_days, equity_tickers,
                    vix_data, rs_rankings, daily_highs, earnings_exclusions,
                    vix_threshold=20, rs_pct=30, near_high_pct=5,
                    max_bars=8, pullback_max=2, exit_strategy="max_only",
                    verbose=False):
    """Run the RS Leader Pullback backtest with given parameters.

    Signal (LONG only):
      1. VIX < vix_threshold
      2. Ticker is RS leader (top rs_pct%)
      3. Ticker near 60-day high (within near_high_pct%)
      4. EMA9 > EMA21 (uptrend)
      5. Pullback: 1..pullback_max consecutive down 4H bars
      6. Not near earnings

    Entry: Close of the signal bar (last down bar).
    Exit: per exit_strategy, up to max_bars 4H bars.

    Returns list of trade dicts.
    """
    # Recompute RS if non-default percentile
    if rs_pct != 30:
        active_rs = compute_rs_rankings(ticker_4h, equity_tickers, rs_pct=rs_pct)
    else:
        active_rs = rs_rankings

    near_high_factor = 1.0 - (near_high_pct / 100.0)  # e.g. 5% -> 0.95

    trades = []
    rs_days = sorted(active_rs.keys())

    for day in rs_days:
        # VIX filter
        vix_val = vix_data.get(day)
        if vix_val is None or vix_val >= vix_threshold:
            continue

        day_rs = active_rs.get(day, {})

        for ticker in equity_tickers:
            # RS leader check
            rs_info = day_rs.get(ticker)
            if rs_info is None or not rs_info["is_leader"]:
                continue

            # Near 60d high check (use raw high_60d with variable threshold)
            high_info = daily_highs.get(ticker, {}).get(day)
            if high_info is None:
                continue
            high_60d = high_info["high_60d"]
            # Get today's close for near-high comparison
            bars = ticker_4h[ticker]
            tdays = ticker_trading_days[ticker]
            day_bars = bars[bars["trading_day"] == day].sort_values("bar_num")
            if day_bars.empty:
                continue
            last_bar = day_bars.iloc[-1]
            today_close = last_bar["Close"]
            if today_close < high_60d * near_high_factor:
                continue

            # Earnings exclusion
            if (ticker, day) in earnings_exclusions:
                continue

            # EMA filter: last bar of this day should have EMA9 > EMA21
            if pd.isna(last_bar["ema9"]) or pd.isna(last_bar["ema21"]):
                continue
            if last_bar["ema9"] <= last_bar["ema21"]:
                continue

            # Pullback check: need 1..pullback_max consecutive down bars
            pb_count = detect_pullback(bars, ticker, day, tdays, pullback_max)
            if pb_count < 1 or pb_count > pullback_max:
                continue

            # Entry price = close of the signal bar
            entry_price = last_bar["Close"]
            if entry_price <= 0 or np.isnan(entry_price):
                continue

            # Get forward bars for exit
            fwd_bars = get_forward_4h_bars(bars, ticker, day, tdays, max_bars)
            if not fwd_bars:
                continue

            # Apply exit strategy
            exit_price, bars_held, exit_reason = apply_exit_strategy(
                entry_price, fwd_bars, exit_strategy)
            if exit_price is None:
                continue

            ret_pct = (exit_price - entry_price) / entry_price * 100

            trades.append({
                "ticker": ticker,
                "entry_day": day,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "return_pct": ret_pct,
                "bars_held": bars_held,
                "exit_reason": exit_reason,
                "vix": vix_val,
                "rs_rank": rs_info["rs_rank"],
                "pullback_bars": pb_count,
            })

    return trades


def compute_metrics(trades):
    """Compute N, Mean%, WR%, PF, AvgHold from a list of trade dicts."""
    if not trades:
        return {"N": 0, "mean_pct": 0.0, "wr_pct": 0.0, "pf": 0.0, "avg_hold": 0.0}

    returns = [t["return_pct"] for t in trades]
    n = len(returns)
    mean_pct = np.mean(returns)
    wr = sum(1 for r in returns if r > 0) / n * 100
    gross_profit = sum(r for r in returns if r > 0)
    gross_loss = abs(sum(r for r in returns if r <= 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    avg_hold = np.mean([t["bars_held"] for t in trades])

    return {"N": n, "mean_pct": mean_pct, "wr_pct": wr, "pf": pf, "avg_hold": avg_hold}


def print_metrics_table(rows, columns, title):
    """Print a formatted table of sweep results.

    rows: list of dicts with metric values
    columns: list of (header, key, fmt) tuples
    """
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")

    # Header
    header = " | ".join(f"{col[0]:>{len(col[2].format(0)) if '%' not in col[2] else 6}}"
                        for col in columns)
    # Simpler approach:
    parts = []
    for hdr, key, fmt in columns:
        parts.append(f"{hdr:>8}")
    print(" | ".join(parts))
    print("-" * (len(parts) * 11))

    for row in rows:
        parts = []
        for hdr, key, fmt in columns:
            val = row.get(key, 0)
            parts.append(f"{fmt.format(val):>8}")
        print(" | ".join(parts))


# ---------------------------------------------------------------------------
# Sweep Tests
# ---------------------------------------------------------------------------

def run_sweep(ticker_4h, ticker_trading_days, equity_tickers,
              vix_data, rs_rankings, daily_highs, earnings_exclusions):
    """Run the 4 parameter sweep tests."""

    # Defaults
    DEF_VIX = 20
    DEF_RS = 30
    DEF_NEAR_HIGH = 5
    DEF_MAX_BARS = 8
    DEF_PB = 2

    sweep_winners = {}

    # --- TEST 1: VIX Threshold ---
    print("\n" + "#" * 60)
    print("# TEST 1: VIX Threshold Sweep")
    print("#" * 60)
    VIX_THRESHOLDS = [18, 19, 20, 22, 25]
    rows = []
    for vt in VIX_THRESHOLDS:
        trades = run_rs_backtest(
            ticker_4h, ticker_trading_days, equity_tickers,
            vix_data, rs_rankings, daily_highs, earnings_exclusions,
            vix_threshold=vt, rs_pct=DEF_RS, near_high_pct=DEF_NEAR_HIGH,
            max_bars=DEF_MAX_BARS, pullback_max=DEF_PB)
        m = compute_metrics(trades)
        m["param"] = f"<{vt}"
        rows.append(m)

    cols = [("VIX<", "param", "{}"), ("N", "N", "{:d}"),
            ("Mean%", "mean_pct", "{:.3f}"), ("WR%", "wr_pct", "{:.1f}"),
            ("PF", "pf", "{:.2f}")]
    print_metrics_table(rows, cols, "VIX Threshold")

    best = max([r for r in rows if r["N"] > 0], key=lambda r: r["pf"], default=None)
    if best:
        sweep_winners["vix"] = best

    # --- TEST 2: RS Percentile ---
    print("\n" + "#" * 60)
    print("# TEST 2: RS Percentile Sweep")
    print("#" * 60)
    RS_PERCENTILES = [10, 20, 30, 40, 50]
    rows = []
    for rp in RS_PERCENTILES:
        trades = run_rs_backtest(
            ticker_4h, ticker_trading_days, equity_tickers,
            vix_data, rs_rankings, daily_highs, earnings_exclusions,
            vix_threshold=DEF_VIX, rs_pct=rp, near_high_pct=DEF_NEAR_HIGH,
            max_bars=DEF_MAX_BARS, pullback_max=DEF_PB)
        m = compute_metrics(trades)
        m["param"] = f"{rp}%"
        rows.append(m)

    cols = [("RS%", "param", "{}"), ("N", "N", "{:d}"),
            ("Mean%", "mean_pct", "{:.3f}"), ("WR%", "wr_pct", "{:.1f}"),
            ("PF", "pf", "{:.2f}")]
    print_metrics_table(rows, cols, "RS Percentile")

    best = max([r for r in rows if r["N"] > 0], key=lambda r: r["pf"], default=None)
    if best:
        sweep_winners["rs"] = best

    # --- TEST 3: Max Bars ---
    print("\n" + "#" * 60)
    print("# TEST 3: Max Bars Sweep")
    print("#" * 60)
    MAX_BARS_VALUES = [4, 6, 8, 10, 12, 16, 20]
    rows = []
    for mb in MAX_BARS_VALUES:
        trades = run_rs_backtest(
            ticker_4h, ticker_trading_days, equity_tickers,
            vix_data, rs_rankings, daily_highs, earnings_exclusions,
            vix_threshold=DEF_VIX, rs_pct=DEF_RS, near_high_pct=DEF_NEAR_HIGH,
            max_bars=mb, pullback_max=DEF_PB)
        m = compute_metrics(trades)
        m["param"] = str(mb)
        rows.append(m)

    cols = [("MaxBars", "param", "{}"), ("N", "N", "{:d}"),
            ("Mean%", "mean_pct", "{:.3f}"), ("WR%", "wr_pct", "{:.1f}"),
            ("PF", "pf", "{:.2f}"), ("AvgHold", "avg_hold", "{:.1f}")]
    print_metrics_table(rows, cols, "Max Bars")

    best = max([r for r in rows if r["N"] > 0], key=lambda r: r["pf"], default=None)
    if best:
        sweep_winners["max_bars"] = best

    # --- TEST 4: Pullback Depth ---
    print("\n" + "#" * 60)
    print("# TEST 4: Pullback Depth Sweep")
    print("#" * 60)
    PULLBACK_MAX_VALUES = [1, 2, 3]
    rows = []
    for pb in PULLBACK_MAX_VALUES:
        trades = run_rs_backtest(
            ticker_4h, ticker_trading_days, equity_tickers,
            vix_data, rs_rankings, daily_highs, earnings_exclusions,
            vix_threshold=DEF_VIX, rs_pct=DEF_RS, near_high_pct=DEF_NEAR_HIGH,
            max_bars=DEF_MAX_BARS, pullback_max=pb)
        m = compute_metrics(trades)
        m["param"] = str(pb)
        rows.append(m)

    cols = [("PB_Max", "param", "{}"), ("N", "N", "{:d}"),
            ("Mean%", "mean_pct", "{:.3f}"), ("WR%", "wr_pct", "{:.1f}"),
            ("PF", "pf", "{:.2f}")]
    print_metrics_table(rows, cols, "Pullback Depth")

    best = max([r for r in rows if r["N"] > 0], key=lambda r: r["pf"], default=None)
    if best:
        sweep_winners["pullback"] = best

    # --- Part 1 Summary ---
    print("\n" + "=" * 60)
    print("=== Part 1 Sweep Winners ===")
    print("=" * 60)
    if "vix" in sweep_winners:
        w = sweep_winners["vix"]
        print(f"Best VIX threshold: {w['param']} (PF={w['pf']:.2f}, N={w['N']})")
    if "rs" in sweep_winners:
        w = sweep_winners["rs"]
        print(f"Best RS percentile: {w['param']} (PF={w['pf']:.2f}, N={w['N']})")
    if "max_bars" in sweep_winners:
        w = sweep_winners["max_bars"]
        print(f"Best max bars: {w['param']} (PF={w['pf']:.2f}, N={w['N']})")
    if "pullback" in sweep_winners:
        w = sweep_winners["pullback"]
        print(f"Best pullback depth: {w['param']} (PF={w['pf']:.2f}, N={w['N']})")

    # --- TEST 5: Exit Strategy Comparison ---
    print("\n" + "#" * 60)
    print("# TEST 5: Exit Strategy Comparison")
    print("#" * 60)
    EXIT_STRATEGIES = [
        ("max_only",        "Max bars ONLY (pure time-based)"),
        ("ema9_ema21_max",  "EMA9 break OR EMA21 break OR max bars"),
        ("ema21_max_only",  "EMA21 break OR max bars"),
        ("trailing_50pct",  "Trailing 50% giveback"),
        ("fixed_stop_2pct", "Fixed -2% stop"),
    ]
    rows = []
    for es_key, es_label in EXIT_STRATEGIES:
        trades = run_rs_backtest(
            ticker_4h, ticker_trading_days, equity_tickers,
            vix_data, rs_rankings, daily_highs, earnings_exclusions,
            vix_threshold=DEF_VIX, rs_pct=DEF_RS, near_high_pct=DEF_NEAR_HIGH,
            max_bars=DEF_MAX_BARS, pullback_max=DEF_PB, exit_strategy=es_key)
        m = compute_metrics(trades)
        m["param"] = es_key
        rows.append(m)

    cols = [("Exit", "param", "{}"), ("N", "N", "{:d}"),
            ("Mean%", "mean_pct", "{:.3f}"), ("WR%", "wr_pct", "{:.1f}"),
            ("PF", "pf", "{:.2f}"), ("AvgBars", "avg_hold", "{:.1f}")]
    print_metrics_table(rows, cols, "Exit Strategy Comparison")

    best = max([r for r in rows if r["N"] > 0], key=lambda r: r["pf"], default=None)
    if best:
        sweep_winners["exit"] = best

    # --- TEST 6: Near-High Threshold ---
    print("\n" + "#" * 60)
    print("# TEST 6: Near-High Threshold Sweep")
    print("#" * 60)
    NEAR_HIGH_VALUES = [3, 5, 7, 10, 15]
    rows = []
    for nh in NEAR_HIGH_VALUES:
        trades = run_rs_backtest(
            ticker_4h, ticker_trading_days, equity_tickers,
            vix_data, rs_rankings, daily_highs, earnings_exclusions,
            vix_threshold=DEF_VIX, rs_pct=DEF_RS, near_high_pct=nh,
            max_bars=DEF_MAX_BARS, pullback_max=DEF_PB)
        m = compute_metrics(trades)
        m["param"] = f"{nh}%"
        rows.append(m)

    cols = [("NrHigh%", "param", "{}"), ("N", "N", "{:d}"),
            ("Mean%", "mean_pct", "{:.3f}"), ("WR%", "wr_pct", "{:.1f}"),
            ("PF", "pf", "{:.2f}")]
    print_metrics_table(rows, cols, "Near-High Threshold")

    best = max([r for r in rows if r["N"] > 0], key=lambda r: r["pf"], default=None)
    if best:
        sweep_winners["near_high"] = best

    # --- TEST 7: Combined Best Configs ---
    print("\n" + "#" * 60)
    print("# TEST 7: Combined Best Configs")
    print("#" * 60)

    COMBOS = {
        "A": {"vix": 20, "rs_pct": 10, "pullback_max": 1, "max_bars": 12,
               "exit": "ema21_max_only", "near_high_pct": DEF_NEAR_HIGH},
        "B": {"vix": 20, "rs_pct": 20, "pullback_max": 2, "max_bars": 16,
               "exit": "ema21_max_only", "near_high_pct": DEF_NEAR_HIGH},
        "C": {"vix": 18, "rs_pct": 10, "pullback_max": 1, "max_bars": 20,
               "exit": "max_only", "near_high_pct": DEF_NEAR_HIGH},
    }

    rows = []
    for combo_name, cfg in COMBOS.items():
        params_str = (f"VIX<{cfg['vix']} RS{cfg['rs_pct']}% "
                      f"PB{cfg['pullback_max']} MB{cfg['max_bars']} "
                      f"{cfg['exit']}")
        trades = run_rs_backtest(
            ticker_4h, ticker_trading_days, equity_tickers,
            vix_data, rs_rankings, daily_highs, earnings_exclusions,
            vix_threshold=cfg["vix"], rs_pct=cfg["rs_pct"],
            near_high_pct=cfg["near_high_pct"],
            max_bars=cfg["max_bars"], pullback_max=cfg["pullback_max"],
            exit_strategy=cfg["exit"])
        m = compute_metrics(trades)
        m["param"] = combo_name
        m["params_str"] = params_str
        rows.append(m)

    # Print combo table
    print(f"\n{'=' * 60}")
    print(f"  Combined Best Configs")
    print(f"{'=' * 60}")
    print(f"{'Combo':>6} | {'Params':<40} | {'N':>5} | {'Mean%':>7} | {'WR%':>6} | {'PF':>6} | {'AvgBars':>7}")
    print("-" * 90)
    for row in rows:
        n = row["N"]
        mean = f"{row['mean_pct']:.3f}" if n > 0 else "N/A"
        wr = f"{row['wr_pct']:.1f}" if n > 0 else "N/A"
        pf = f"{row['pf']:.2f}" if n > 0 else "N/A"
        ah = f"{row['avg_hold']:.1f}" if n > 0 else "N/A"
        print(f"{row['param']:>6} | {row['params_str']:<40} | {n:>5} | {mean:>7} | {wr:>6} | {pf:>6} | {ah:>7}")

    best_combo = max([r for r in rows if r["N"] > 0], key=lambda r: r["pf"], default=None)
    if best_combo:
        sweep_winners["combo"] = best_combo

    # --- Part 2 Summary ---
    print("\n" + "=" * 60)
    print("=== Part 2 Sweep Winners ===")
    print("=" * 60)
    if "exit" in sweep_winners:
        w = sweep_winners["exit"]
        print(f"Best exit strategy: {w['param']} (PF={w['pf']:.2f}, N={w['N']})")
    if "near_high" in sweep_winners:
        w = sweep_winners["near_high"]
        print(f"Best near-high: {w['param']} (PF={w['pf']:.2f}, N={w['N']})")
    if "combo" in sweep_winners:
        w = sweep_winners["combo"]
        print(f"Best combined combo: {w['param']} (PF={w['pf']:.2f}, N={w['N']}, WR={w['wr_pct']:.1f}%)")


# ---------------------------------------------------------------------------
# Data Preparation (load or reuse pickle)
# ---------------------------------------------------------------------------

def load_or_prepare_data(force_prep=False):
    """Load prepared data from pickle or run full data prep."""

    if not force_prep and _OUTPUT_PKL.exists():
        print(f"Loading prepared data from {_OUTPUT_PKL}...")
        with open(_OUTPUT_PKL, "rb") as f:
            data = pickle.load(f)

        # Check if VIX data needs updating (old pkl may have VIXY data)
        vix = data.get("vix_data") or data.get("vix_proxy")
        if vix:
            # Quick check: VIXY values are typically > 10 and track futures,
            # while VIXCLS can be < 15. If max is very low or data seems like
            # FRED data, keep it. Otherwise reload.
            sample_val = next(iter(vix.values())) if vix else None
            if sample_val is not None:
                print(f"  VIX data loaded: {len(vix)} days")

        # Always refresh VIX from CSV to ensure we use FRED data
        vix_data = build_vix_daily()
        data["vix_data"] = vix_data
        # Remove old key if present
        data.pop("vix_proxy", None)

        return data

    print("=" * 60)
    print("RS Leader Pullback Backtest — Data Preparation")
    print("=" * 60)

    print("\n--- Step 1: Loading M5 data and synthesizing 4H bars ---")
    ticker_4h, ticker_trading_days, equity_tickers = load_equity_4h_bars()

    print("\n--- Step 2: Computing EMA9 and EMA21 on 4H close ---")
    ticker_4h = add_emas(ticker_4h)
    for ticker in equity_tickers[:3]:
        bars = ticker_4h[ticker]
        valid_ema9 = bars["ema9"].notna().sum()
        valid_ema21 = bars["ema21"].notna().sum()
        print(f"  {ticker}: {len(bars)} bars, EMA9 valid: {valid_ema9}, EMA21 valid: {valid_ema21}")
    print(f"  ... ({len(equity_tickers)} tickers total)")

    print("\n--- Step 3: Building VIX data ---")
    vix_data = build_vix_daily()

    print("\n--- Step 4: Computing RS rankings ---")
    rs_rankings = compute_rs_rankings(ticker_4h, equity_tickers)

    print("\n--- Step 5: Computing 60-day rolling highs ---")
    daily_highs = compute_60d_high(ticker_4h, equity_tickers)

    print("\n--- Step 6: Loading earnings calendar ---")
    earnings_exclusions = load_earnings_calendar()

    print_summary(ticker_4h, equity_tickers, vix_data, rs_rankings,
                  daily_highs, earnings_exclusions)

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    prepared_data = {
        "ticker_4h": ticker_4h,
        "ticker_trading_days": ticker_trading_days,
        "equity_tickers": equity_tickers,
        "vix_data": vix_data,
        "rs_rankings": rs_rankings,
        "daily_highs": daily_highs,
        "earnings_exclusions": earnings_exclusions,
    }

    with open(_OUTPUT_PKL, "wb") as f:
        pickle.dump(prepared_data, f)

    print(f"\nPrepared data saved to: {_OUTPUT_PKL}")
    return prepared_data


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="RS Leader Pullback Backtest")
    parser.add_argument("--sweep", action="store_true",
                        help="Run parameter sweep tests after baseline")
    parser.add_argument("--prep", action="store_true",
                        help="Force re-run data preparation")
    args = parser.parse_args()

    data = load_or_prepare_data(force_prep=args.prep)

    ticker_4h = data["ticker_4h"]
    ticker_trading_days = data["ticker_trading_days"]
    equity_tickers = data["equity_tickers"]
    vix_data = data.get("vix_data") or data.get("vix_proxy", {})
    rs_rankings = data["rs_rankings"]
    daily_highs = data["daily_highs"]
    earnings_exclusions = data["earnings_exclusions"]

    # --- Baseline ---
    print("\n" + "=" * 60)
    print("=== BASELINE: RS Leader Pullback ===")
    print("=== VIX<20, RS top 30%, near_high 5%, max_bars 8, pb_max 2 ===")
    print("=" * 60)

    trades = run_rs_backtest(
        ticker_4h, ticker_trading_days, equity_tickers,
        vix_data, rs_rankings, daily_highs, earnings_exclusions,
        vix_threshold=20, rs_pct=30, near_high_pct=5,
        max_bars=8, pullback_max=2)

    m = compute_metrics(trades)
    print(f"\nBaseline results:")
    print(f"  N={m['N']}, Mean={m['mean_pct']:.3f}%, WR={m['wr_pct']:.1f}%, "
          f"PF={m['pf']:.2f}, AvgHold={m['avg_hold']:.1f} bars")

    if trades:
        # Quick breakdown by RS rank
        ranks = {}
        for t in trades:
            r = t["rs_rank"]
            ranks.setdefault(r, []).append(t["return_pct"])
        print(f"\n  By RS rank:")
        for r in sorted(ranks.keys()):
            rets = ranks[r]
            print(f"    Rank {r}: N={len(rets)}, Mean={np.mean(rets):.3f}%")

    # --- Sweep ---
    if args.sweep:
        run_sweep(ticker_4h, ticker_trading_days, equity_tickers,
                  vix_data, rs_rankings, daily_highs, earnings_exclusions)

    print("\nDone.")


if __name__ == "__main__":
    main()
