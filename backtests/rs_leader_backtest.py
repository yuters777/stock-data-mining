"""
RS Leader Pullback Backtest — Data Preparation + Signal Detection + Baseline.

Strategy: Buy RS leaders pulling back to EMA support in low-VIX regimes.

Data prep:
  - 4H bars with EMA9/EMA21 for equity tickers (excludes SPY, VIXY, BTC, ETH)
  - Daily VIX from FRED VIXCLS (backtester/data/vix_daily.csv)
  - Daily relative-strength rankings (20-day returns, top 30% = leaders)
  - 60-day rolling high proximity
  - Earnings calendar for exclusion

Signal detection:
  - Filters: VIX<20, RS leader, near 60d high, EMA9>EMA21, no earnings
  - Pullback: 1-2 consecutive 4H bars with close<open, all above EMA21
  - Bounce entry: next 4H bar closes above EMA9
  - Exit: EMA9 break, EMA21 break (stop), or hard max 8 bars

VIX SOURCE: backtester/data/vix_daily.csv (FRED VIXCLS spot daily close).
            DO NOT use VIXY. DO NOT derive VIX from VIXY M5 bars.

Reads:
  - Fetched_Data/{TICKER}_data.csv (M5 OHLCV bars, IST-encoded)
  - backtester/data/vix_daily.csv (284 rows, FRED VIXCLS)
  - backtester/data/fmp_earnings.csv

Produces:
  - backtest_output/rs_leader_prepared_data.pkl
  - backtest_output/rs_leader_trades.csv
  - Console output with data prep summary and baseline results

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
_TRADES_CSV = _OUTPUT_DIR / "rs_leader_trades.csv"

# Tickers to exclude from equity universe
_EXCLUDE_TICKERS = {"SPY", "VIXY", "BTC", "ETH", "BTC_crypto", "ETH_crypto"}

# Warmup: skip first 60 trading days
_WARMUP_DAYS = 60

# --- Default baseline parameters ---
_VIX_THRESHOLD = 20        # FRED VIXCLS, NOT VIXY
_RS_PERCENTILE = 0.30      # top 30%
_RS_LOOKBACK = 20          # trading days
_NEAR_HIGH_PCT = 0.05      # within 5% of 60d high
_MAX_BARS = 8              # hard max hold (8 4H bars ≈ 4 trading days)
_PULLBACK_MAX = 2          # max consecutive pullback bars

# --- Sector mapping ---
SECTORS = {
    "mega_tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA"],
    "growth_semi": ["TSLA", "AMD", "SMCI", "PLTR", "AVGO", "ARM", "TSM", "MU", "INTC"],
    "crypto_proxy": ["COIN", "MSTR", "MARA"],
    "finance": ["C", "GS", "V", "BA", "JPM"],
    "china_adr": ["BABA", "JD", "BIDU"],
    "consumer": ["COST"],
}

def _ticker_to_sector(ticker: str) -> str:
    for sector, tickers in SECTORS.items():
        if ticker in tickers:
            return sector
    return "other"


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
# Part B: Signal Detection + Trade Simulation
# ---------------------------------------------------------------------------

def _build_vix_by_date(vix_daily: dict) -> dict:
    """Convert VIX dict keys from string to datetime.date."""
    vix_by_date = {}
    for k, v in vix_daily.items():
        if isinstance(k, str):
            vix_by_date[datetime.date.fromisoformat(k)] = v
        else:
            vix_by_date[k] = v
    return vix_by_date


def _get_prior_day_vix(day, trading_days: list, vix_by_date: dict):
    """Get VIX close for the trading day before `day`."""
    idx = None
    for i, td in enumerate(trading_days):
        if td == day:
            idx = i
            break
    if idx is None or idx == 0:
        return None
    prev_day = trading_days[idx - 1]
    return vix_by_date.get(prev_day)


def detect_signals_and_trade(bars_4h, equity_tickers, vix_daily, rs_rankings,
                             daily_highs, gate_up, earnings_exclusions):
    """Detect pullback signals and simulate trades.

    Signal conditions (ALL must be true on the pullback day):
      1. Prior-day VIX < 20 (FRED VIXCLS)
      2. Ticker is RS leader (top 30%)
      3. Close within 5% of 60d high
      4. EMA9 > EMA21 (gate_UP)
      5. No earnings today or tomorrow

    Pullback: 1-2 consecutive 4H bars with close < open, all closing above EMA21.
    Bounce entry: next 4H bar closes above EMA9 → ENTRY at that close.

    Exit (first to trigger):
      1. EMA9 break: 4H close < EMA9
      2. EMA21 break: 4H close < EMA21 (stop)
      3. Hard max: 8 4H bars

    Returns list of trade dicts.
    """
    vix_by_date = _build_vix_by_date(vix_daily)

    # Build per-ticker bar sequences (sorted chronologically)
    ticker_bars = {}
    for ticker in equity_tickers:
        t = bars_4h[bars_4h["Ticker"] == ticker].sort_values(
            ["trading_day", "bar_num"]).reset_index(drop=True)
        ticker_bars[ticker] = t

    # All trading days (sorted)
    all_trading_days = sorted(bars_4h["trading_day"].unique())

    # Build earnings exclusion set with next-day logic:
    # Exclude earnings day + day before (already in earnings_exclusions).
    # We also need to check "no earnings tomorrow" — add (ticker, day_before_earnings).
    # The existing set already has day_before, so we just check membership.
    # For "no earnings today or tomorrow", we check both (ticker, day) and
    # look for (ticker, next_day) in the raw earnings dates.
    raw_earnings_dates = set()
    if _EARNINGS_CSV.exists():
        edf = pd.read_csv(_EARNINGS_CSV)
        for _, row in edf.iterrows():
            try:
                edate = datetime.date.fromisoformat(str(row["earnings_date"]))
                raw_earnings_dates.add((row["ticker"], edate))
            except (ValueError, TypeError):
                continue

    trades = []
    # Track active trade end bar index per ticker to prevent overlaps
    ticker_trade_end = {}  # {ticker: last_bar_index_of_active_trade}

    for ticker in equity_tickers:
        t_bars = ticker_bars[ticker]
        n_bars = len(t_bars)
        if n_bars < _WARMUP_DAYS * 2 + 5:
            continue

        for i in range(1, n_bars):
            # Skip if still in an active trade for this ticker
            if ticker in ticker_trade_end and i <= ticker_trade_end[ticker]:
                continue

            bar = t_bars.iloc[i]
            day = bar["trading_day"]

            # Need valid EMAs
            if pd.isna(bar["ema9"]) or pd.isna(bar["ema21"]):
                continue

            # --- Filter 1: Prior-day VIX < threshold ---
            prior_vix = _get_prior_day_vix(day, all_trading_days, vix_by_date)
            if prior_vix is None or prior_vix >= _VIX_THRESHOLD:
                continue

            # --- Filter 2: RS leader ---
            rs_info = rs_rankings.get(day, {}).get(ticker)
            if rs_info is None or not rs_info["is_leader"]:
                continue

            # --- Filter 3: Near 60d high ---
            high_info = daily_highs.get(ticker, {}).get(day)
            if high_info is None or not high_info["near_high"]:
                continue

            # --- Filter 4: gate_UP (EMA9 > EMA21) ---
            if not gate_up.get(ticker, {}).get(day, False):
                continue

            # --- Filter 5: No earnings today or tomorrow ---
            if (ticker, day) in earnings_exclusions:
                continue
            # Check if tomorrow has earnings
            day_idx_in_all = None
            for j, td in enumerate(all_trading_days):
                if td == day:
                    day_idx_in_all = j
                    break
            if day_idx_in_all is not None and day_idx_in_all + 1 < len(all_trading_days):
                next_day = all_trading_days[day_idx_in_all + 1]
                if (ticker, next_day) in raw_earnings_dates:
                    continue

            # --- Pullback detection: close < open, close > EMA21 ---
            if bar["Close"] >= bar["Open"]:
                continue
            if bar["Close"] <= bar["ema21"]:
                continue

            # Check for 1-2 bar pullback
            pullback_bars = [i]
            # Check if prior bar was also a pullback bar
            if i >= 2:
                prev_bar = t_bars.iloc[i - 1]
                if (pd.notna(prev_bar["ema21"]) and
                        prev_bar["Close"] < prev_bar["Open"] and
                        prev_bar["Close"] > prev_bar["ema21"]):
                    pullback_bars = [i - 1, i]

            # The bar before the pullback should NOT be a pullback bar
            # (otherwise we'd be in a longer downtrend, not a brief pullback)
            first_pb = pullback_bars[0]
            if first_pb >= 1:
                pre_pb = t_bars.iloc[first_pb - 1]
                if (pd.notna(pre_pb["ema21"]) and
                        pre_pb["Close"] < pre_pb["Open"] and
                        pre_pb["Close"] > pre_pb["ema21"]):
                    # This is bar 3+ of a pullback; skip
                    if len(pullback_bars) >= _PULLBACK_MAX:
                        continue

            # --- Bounce detection: next bar closes above EMA9 ---
            bounce_idx = i + 1
            if bounce_idx >= n_bars:
                continue
            bounce_bar = t_bars.iloc[bounce_idx]
            if pd.isna(bounce_bar["ema9"]):
                continue
            if bounce_bar["Close"] <= bounce_bar["ema9"]:
                continue

            # ENTRY
            entry_price = bounce_bar["Close"]
            entry_day = bounce_bar["trading_day"]
            entry_bar_num = bounce_bar["bar_num"]
            pullback_depth = len(pullback_bars)

            # --- Trade management: exit logic ---
            exit_price = None
            exit_reason = None
            exit_day = None
            exit_bar_num = None
            bars_held = 0

            for k in range(bounce_idx + 1, min(bounce_idx + 1 + _MAX_BARS, n_bars)):
                hold_bar = t_bars.iloc[k]
                bars_held += 1

                if pd.isna(hold_bar["ema9"]) or pd.isna(hold_bar["ema21"]):
                    continue

                # Exit check: EMA21 break (stop) — check first (worse)
                if hold_bar["Close"] < hold_bar["ema21"]:
                    exit_price = hold_bar["Close"]
                    exit_reason = "EMA21_BREAK"
                    exit_day = hold_bar["trading_day"]
                    exit_bar_num = hold_bar["bar_num"]
                    ticker_trade_end[ticker] = k
                    break

                # Exit check: EMA9 break
                if hold_bar["Close"] < hold_bar["ema9"]:
                    exit_price = hold_bar["Close"]
                    exit_reason = "EMA9_BREAK"
                    exit_day = hold_bar["trading_day"]
                    exit_bar_num = hold_bar["bar_num"]
                    ticker_trade_end[ticker] = k
                    break

            # Hard max exit
            if exit_price is None and bars_held > 0:
                last_k = min(bounce_idx + _MAX_BARS, n_bars - 1)
                last_bar = t_bars.iloc[last_k]
                exit_price = last_bar["Close"]
                exit_reason = "HARD_MAX"
                exit_day = last_bar["trading_day"]
                exit_bar_num = last_bar["bar_num"]
                ticker_trade_end[ticker] = last_k

            if exit_price is None:
                continue

            return_pct = (exit_price - entry_price) / entry_price * 100
            rs_rank = rs_info["rs_rank"]

            trades.append({
                "ticker": ticker,
                "sector": _ticker_to_sector(ticker),
                "entry_day": entry_day,
                "entry_bar": entry_bar_num,
                "entry_price": round(entry_price, 4),
                "exit_day": exit_day,
                "exit_bar": exit_bar_num,
                "exit_price": round(exit_price, 4),
                "return_pct": round(return_pct, 4),
                "bars_held": bars_held,
                "exit_reason": exit_reason,
                "pullback_depth": pullback_depth,
                "rs_rank": rs_rank,
                "vix_at_entry": round(prior_vix, 2),
            })

            # Mark trade end to prevent overlap
            ticker_trade_end[ticker] = max(
                ticker_trade_end.get(ticker, 0),
                bounce_idx + bars_held
            )

    return trades


def print_baseline_results(trades: list):
    """Print TEST 0 baseline results."""
    print("\n" + "=" * 60)
    print(f"=== TEST 0: RS Leader Baseline (VIX<{_VIX_THRESHOLD}, FRED VIXCLS) ===")
    print("=" * 60)

    n = len(trades)
    if n == 0:
        print("N trades: 0")
        print("VERDICT: NO_EDGE (no trades generated)")
        return

    returns = [t["return_pct"] for t in trades]
    mean_ret = np.mean(returns)
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    win_rate = len(wins) / n * 100
    avg_hold = np.mean([t["bars_held"] for t in trades])

    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0.001
    profit_factor = gross_profit / gross_loss

    print(f"N trades: {n}")
    print(f"Mean return: {mean_ret:.2f}%")
    print(f"Win rate: {win_rate:.1f}%")
    print(f"Profit factor: {profit_factor:.2f}")
    print(f"Avg hold: {avg_hold:.1f} bars")

    # Exit reasons
    print(f"\nExit reasons:")
    exit_counts = {}
    for t in trades:
        exit_counts[t["exit_reason"]] = exit_counts.get(t["exit_reason"], 0) + 1
    for reason in ["EMA9_BREAK", "EMA21_BREAK", "HARD_MAX"]:
        cnt = exit_counts.get(reason, 0)
        pct = cnt / n * 100
        print(f"  {reason}: {cnt} ({pct:.1f}%)")

    # By sector
    print(f"\nBy sector:")
    sector_trades = {}
    for t in trades:
        sector_trades.setdefault(t["sector"], []).append(t)
    for sector in ["mega_tech", "growth_semi", "finance", "china_adr",
                    "crypto_proxy", "consumer", "other"]:
        st = sector_trades.get(sector, [])
        if not st:
            continue
        sr = [t["return_pct"] for t in st]
        sw = sum(1 for r in sr if r > 0) / len(sr) * 100
        print(f"  {sector}: N={len(st)}, mean={np.mean(sr):.2f}%, WR={sw:.1f}%")

    # By RS rank
    print(f"\nBy RS rank:")
    top3 = [t for t in trades if t["rs_rank"] <= 3]
    top4p = [t for t in trades if t["rs_rank"] > 3]
    if top3:
        r3 = [t["return_pct"] for t in top3]
        w3 = sum(1 for r in r3 if r > 0) / len(r3) * 100
        print(f"  Top 3: N={len(top3)}, mean={np.mean(r3):.2f}%, WR={w3:.1f}%")
    if top4p:
        r4 = [t["return_pct"] for t in top4p]
        w4 = sum(1 for r in r4 if r > 0) / len(r4) * 100
        print(f"  Top 4+: N={len(top4p)}, mean={np.mean(r4):.2f}%, WR={w4:.1f}%")

    # By pullback depth
    print(f"\nBy pullback depth:")
    for depth in [1, 2]:
        dt = [t for t in trades if t["pullback_depth"] == depth]
        if not dt:
            continue
        dr = [t["return_pct"] for t in dt]
        dw = sum(1 for r in dr if r > 0) / len(dr) * 100
        print(f"  {depth} bar{'s' if depth > 1 else ''}: N={len(dt)}, "
              f"mean={np.mean(dr):.2f}%, WR={dw:.1f}%")

    # Verdict
    if mean_ret > 0.3 and win_rate > 55 and profit_factor > 1.3:
        verdict = "PROMISING"
    elif mean_ret > 0 and win_rate > 50:
        verdict = "MARGINAL"
    else:
        verdict = "NO_EDGE"
    print(f"\nVERDICT: {verdict}")
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

    # ---------------------------------------------------------------
    # Part B: Signal Detection + Baseline
    # ---------------------------------------------------------------
    print("\n" + "=" * 60)
    print("Part B: Signal Detection + Trade Simulation")
    print("=" * 60)

    trades = detect_signals_and_trade(
        bars_4h, equity_tickers, vix_daily, rs_rankings,
        daily_highs, gate_up, earnings_exclusions,
    )
    print(f"\nTotal trades detected: {len(trades)}")

    # Save trades CSV
    if trades:
        trades_df = pd.DataFrame(trades)
        trades_df = trades_df.sort_values(["entry_day", "ticker"]).reset_index(drop=True)
        trades_df.to_csv(_TRADES_CSV, index=False)
        print(f"Trades saved to: {_TRADES_CSV}")

    # Print baseline results
    print_baseline_results(trades)


if __name__ == "__main__":
    main()
