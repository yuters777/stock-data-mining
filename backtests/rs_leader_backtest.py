"""
RS Leader Pullback Backtest — Part 1: Data Preparation.

Builds the data infrastructure for the RS Leader Pullback strategy:
  1. 4H bars with EMA 9/21 for 27 equity tickers
  2. Daily VIX proxy from VIXY
  3. Daily relative-strength rankings (20-day returns, top 30% = leaders)
  4. 60-day rolling high and near-high flag
  5. Earnings calendar for exclusion zones
  6. Comprehensive data prep summary

Reads:
  - Fetched_Data/{TICKER}_data.csv  (M5 OHLCV bars, IST-encoded)
  - Fetched_Data/VIXY_data.csv      (M5 VIXY bars for VIX proxy)
  - backtester/data/fmp_earnings.csv (earnings calendar)

Produces:
  - backtest_output/rs_leader_prepared_data.pkl  (all prepared data)
  - Console output with comprehensive data prep summary

Usage:
    python backtests/rs_leader_backtest.py
"""

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
_FETCHED_DIR = _REPO_ROOT / "Fetched_Data"
_EARNINGS_CSV = _REPO_ROOT / "backtester" / "data" / "fmp_earnings.csv"
_OUTPUT_DIR = _REPO_ROOT / "backtest_output"
_OUTPUT_PKL = _OUTPUT_DIR / "rs_leader_prepared_data.pkl"

# Tickers to EXCLUDE from the equity universe
_EXCLUDE = {"SPY", "VIXY", "BTC", "ETH"}


# ---------------------------------------------------------------------------
# 1. Load and synthesize 4H bars (reused from pead_lite_backtest.py)
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
        (hm >= 570) & (hm <= 805),   # 09:30-13:25 ET
        (hm >= 810) & (hm <= 955),   # 13:30-15:55 ET
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

    bars_4h = bars_4h.sort_values(
        ["Ticker", "trading_day", "bar_num"]
    ).reset_index(drop=True)
    return bars_4h


def discover_equity_tickers() -> list:
    """Discover available equity tickers from Fetched_Data, excluding non-equity."""
    tickers = []
    for f in sorted(_FETCHED_DIR.glob("*_data.csv")):
        name = f.stem.replace("_data", "")
        if name not in _EXCLUDE and "_crypto" not in f.stem:
            tickers.append(name)
    return tickers


def load_all_4h_bars(tickers: list) -> pd.DataFrame:
    """Load M5 data for all tickers and synthesize 4H bars."""
    frames = []
    loaded = []
    for t in tickers:
        try:
            m5 = load_m5_regsess(t)
            frames.append(m5)
            loaded.append(t)
        except (FileNotFoundError, ValueError) as e:
            print(f"  WARN: skipping {t}: {e}")
    if not frames:
        raise RuntimeError("No M5 data loaded for any ticker")
    m5_all = pd.concat(frames, ignore_index=True)
    bars_4h = synthesize_4h_bars(m5_all)
    print(f"  Loaded {len(loaded)}/{len(tickers)} tickers, "
          f"{len(bars_4h)} 4H bars")
    return bars_4h, loaded


# ---------------------------------------------------------------------------
# 2. Compute EMA 9 and EMA 21 on 4H close
# ---------------------------------------------------------------------------

def add_emas(bars_4h: pd.DataFrame) -> pd.DataFrame:
    """Add EMA9 and EMA21 columns to 4H bars, computed per ticker."""
    bars = bars_4h.copy()
    bars["ema9"] = np.nan
    bars["ema21"] = np.nan

    for ticker in bars["Ticker"].unique():
        mask = bars["Ticker"] == ticker
        close = bars.loc[mask, "Close"]
        bars.loc[mask, "ema9"] = close.ewm(span=9, min_periods=9).mean()
        bars.loc[mask, "ema21"] = close.ewm(span=21, min_periods=21).mean()

    n_with_ema = bars["ema21"].notna().sum()
    print(f"  EMA warmup complete: {n_with_ema}/{len(bars)} bars have EMA21")
    return bars


# ---------------------------------------------------------------------------
# 3. Build daily VIX proxy from VIXY
# ---------------------------------------------------------------------------

def build_vix_proxy() -> dict:
    """Build daily VIX proxy from VIXY: last 4H bar close each day."""
    m5 = load_m5_regsess("VIXY")
    vixy_4h = synthesize_4h_bars(m5)

    # Daily VIX proxy = Bar 2 close (last bar of the day)
    # If Bar 2 missing, fall back to Bar 1
    daily = vixy_4h.sort_values(["trading_day", "bar_num"])
    daily = daily.groupby("trading_day").last().reset_index()
    vix_proxy = dict(zip(daily["trading_day"], daily["Close"]))

    print(f"  VIXY daily proxy: {len(vix_proxy)} days, "
          f"range {min(vix_proxy.values()):.2f} to {max(vix_proxy.values()):.2f}")
    return vix_proxy


# ---------------------------------------------------------------------------
# 4. Compute daily relative strength rankings
# ---------------------------------------------------------------------------

def compute_rs_rankings(bars_4h: pd.DataFrame, tickers: list) -> dict:
    """Compute daily RS rankings based on 20-day returns.

    Returns dict: {date: {ticker: {rs_return, rs_rank, is_leader}}}
    """
    # Build daily close series per ticker (last 4H bar close of each day)
    daily_close = {}
    for t in tickers:
        t_bars = bars_4h[bars_4h["Ticker"] == t].sort_values(
            ["trading_day", "bar_num"]
        )
        dc = t_bars.groupby("trading_day")["Close"].last()
        daily_close[t] = dc

    # Get union of all trading days
    all_days = sorted(
        set().union(*(dc.index for dc in daily_close.values()))
    )

    rs_data = {}
    for i, day in enumerate(all_days):
        if i < 20:
            continue  # Need 20 trading days of history

        day_20_ago = all_days[i - 20]
        ticker_returns = {}

        for t in tickers:
            dc = daily_close.get(t)
            if dc is None:
                continue
            if day not in dc.index or day_20_ago not in dc.index:
                continue
            close_today = dc[day]
            close_20d = dc[day_20_ago]
            if close_20d == 0:
                continue
            rs_ret = (close_today - close_20d) / close_20d * 100
            ticker_returns[t] = rs_ret

        if len(ticker_returns) < 3:
            continue  # Need at least a few tickers to rank

        # Rank descending (highest return = rank 1)
        sorted_tickers = sorted(
            ticker_returns.items(), key=lambda x: x[1], reverse=True
        )
        n_leaders = max(1, int(len(sorted_tickers) * 0.30))  # Top 30%

        day_data = {}
        for rank, (t, ret) in enumerate(sorted_tickers, 1):
            day_data[t] = {
                "rs_return": ret,
                "rs_rank": rank,
                "is_leader": rank <= n_leaders,
            }
        rs_data[day] = day_data

    print(f"  RS rankings: {len(rs_data)} days (after 20-day warmup)")
    return rs_data


# ---------------------------------------------------------------------------
# 5. Compute 60-day rolling high
# ---------------------------------------------------------------------------

def compute_60d_high(bars_4h: pd.DataFrame, tickers: list) -> dict:
    """Compute 60-day rolling high of daily close per ticker.

    Returns dict: {(ticker, date): {high_60d, near_high}}
    """
    # Build daily close per ticker
    daily_close = {}
    for t in tickers:
        t_bars = bars_4h[bars_4h["Ticker"] == t].sort_values(
            ["trading_day", "bar_num"]
        )
        dc = t_bars.groupby("trading_day")["Close"].last()
        daily_close[t] = dc

    high_data = {}
    for t in tickers:
        dc = daily_close.get(t)
        if dc is None or len(dc) < 60:
            continue
        days = dc.index.tolist()
        for i in range(59, len(days)):
            window = dc.iloc[i - 59 : i + 1]
            h60 = window.max()
            close = dc.iloc[i]
            high_data[(t, days[i])] = {
                "high_60d": h60,
                "near_high": close >= h60 * 0.95,
            }

    print(f"  60-day high: {len(high_data)} ticker-day records")
    return high_data


# ---------------------------------------------------------------------------
# 6. Load earnings calendar for exclusion
# ---------------------------------------------------------------------------

def load_earnings_exclusions() -> set:
    """Load earnings calendar and build exclusion set.

    Returns set of (ticker, date) tuples for earnings day and day before.
    """
    if not _EARNINGS_CSV.exists():
        print("  WARN: fmp_earnings.csv not found, no earnings exclusions")
        return set()

    df = pd.read_csv(_EARNINGS_CSV)
    df["earnings_date"] = pd.to_datetime(df["earnings_date"]).dt.date

    exclusions = set()
    for _, row in df.iterrows():
        t = row["ticker"]
        d = row["earnings_date"]
        exclusions.add((t, d))
        # Also exclude day before earnings
        day_before = d - pd.Timedelta(days=1)
        # Convert to date if needed (handles weekends approximately)
        if hasattr(day_before, "date"):
            day_before = day_before.date()
        exclusions.add((t, day_before))

    print(f"  Earnings exclusions: {len(exclusions)} ticker-day pairs "
          f"({len(df)} earnings events)")
    return exclusions


# ---------------------------------------------------------------------------
# 7. Print comprehensive data prep summary
# ---------------------------------------------------------------------------

def print_summary(
    bars_4h: pd.DataFrame,
    loaded_tickers: list,
    target_tickers: list,
    vix_proxy: dict,
    rs_data: dict,
    high_data: dict,
    earnings_excl: set,
):
    """Print comprehensive data prep summary."""
    print("\n" + "=" * 55)
    print("=== RS Leader Data Prep Summary ===")
    print("=" * 55)

    # --- 4H Bars ---
    trading_days = sorted(bars_4h["trading_day"].unique())
    n_with_ema21 = bars_4h["ema21"].notna().sum()
    print(f"\n4H Bars:")
    print(f"  Tickers loaded: {len(loaded_tickers)}/{len(target_tickers)}")
    print(f"  Trading days: {len(trading_days)} "
          f"({trading_days[0]} to {trading_days[-1]})")
    print(f"  Total 4H bars: {len(bars_4h)}")
    print(f"  Bars after EMA warmup: {n_with_ema21}")

    # --- VIX Proxy ---
    vix_vals = list(vix_proxy.values())
    days_lt20 = sum(1 for v in vix_vals if v < 20)
    days_lt22 = sum(1 for v in vix_vals if v < 22)
    days_lt25 = sum(1 for v in vix_vals if v < 25)
    n_vix = len(vix_vals)
    print(f"\nVIX Proxy (VIXY daily close):")
    print(f"  Days with VIXY data: {n_vix}")
    print(f"  VIXY range: {min(vix_vals):.2f} to {max(vix_vals):.2f}")
    days_lt28 = sum(1 for v in vix_vals if v < 28)
    days_lt30 = sum(1 for v in vix_vals if v < 30)
    print(f"  Days VIXY < 20: {days_lt20} ({days_lt20/n_vix*100:.1f}%)")
    print(f"  Days VIXY < 22: {days_lt22} ({days_lt22/n_vix*100:.1f}%)")
    print(f"  Days VIXY < 25: {days_lt25} ({days_lt25/n_vix*100:.1f}%)")
    print(f"  Days VIXY < 28: {days_lt28} ({days_lt28/n_vix*100:.1f}%)")
    print(f"  Days VIXY < 30: {days_lt30} ({days_lt30/n_vix*100:.1f}%)")
    if days_lt20 < 50:
        print(f"  *** NOTE: VIX<20 regime rare in this period "
              f"({days_lt20} days)")
    if days_lt20 < 30:
        print(f"  *** WARNING: VIXY<20 gives <30 days — "
              f"limited but proceeding")
    if days_lt25 < 30:
        print(f"  *** NOTE: VIXY tracks VIX futures (typically 1-5 pts above "
              f"spot). Consider higher thresholds (28-30) for VIXY.")

    # --- Relative Strength ---
    rs_days = sorted(rs_data.keys())
    if rs_days:
        # Most frequent leaders
        leader_counts = {}
        for day, tdata in rs_data.items():
            for t, info in tdata.items():
                if info["is_leader"]:
                    leader_counts[t] = leader_counts.get(t, 0) + 1

        # Average spread
        spreads = []
        for day, tdata in rs_data.items():
            returns = [info["rs_return"] for info in tdata.values()]
            if len(returns) >= 4:
                sorted_r = sorted(returns, reverse=True)
                n_top = max(1, int(len(sorted_r) * 0.30))
                n_bot = max(1, int(len(sorted_r) * 0.30))
                top_avg = np.mean(sorted_r[:n_top])
                bot_avg = np.mean(sorted_r[-n_bot:])
                spreads.append(top_avg - bot_avg)

        print(f"\nRelative Strength:")
        print(f"  Days with RS rankings: {len(rs_days)} "
              f"(after 20-day warmup)")
        if spreads:
            print(f"  Average RS spread (top vs bottom): "
                  f"{np.mean(spreads):.2f}%")
        top5 = sorted(leader_counts.items(), key=lambda x: x[1],
                       reverse=True)[:5]
        print(f"  Most frequent leaders (top 5 tickers by days-in-top-8):")
        for t, cnt in top5:
            print(f"    {t}: {cnt} days ({cnt/len(rs_days)*100:.1f}%)")

    # --- 60-Day High ---
    if high_data:
        near_high_by_day = {}
        total_by_day = {}
        for (t, d), info in high_data.items():
            total_by_day[d] = total_by_day.get(d, 0) + 1
            if info["near_high"]:
                near_high_by_day[d] = near_high_by_day.get(d, 0) + 1
        pcts = []
        for d in total_by_day:
            nh = near_high_by_day.get(d, 0)
            pcts.append(nh / total_by_day[d] * 100)
        print(f"\n60-Day High:")
        print(f"  Average % of tickers near 60d high per day: "
              f"{np.mean(pcts):.1f}%")

    # --- Combined filter estimate (multiple VIXY thresholds) ---
    if rs_days and high_data and vix_proxy:
        for vix_thresh in [20, 22, 25, 28, 30]:
            combined = 0
            combined_tickers = set()
            for day in rs_days:
                vix_val = vix_proxy.get(day)
                if vix_val is None or vix_val >= vix_thresh:
                    continue
                tdata = rs_data[day]
                for t, info in tdata.items():
                    if not info["is_leader"]:
                        continue
                    hinfo = high_data.get((t, day))
                    if hinfo is None or not hinfo["near_high"]:
                        continue
                    combined += 1
                    combined_tickers.add(t)
            print(f"\nCombined (VIXY<{vix_thresh} + leader + near_high):")
            print(f"  Ticker-days meeting ALL criteria: {combined}")
            print(f"  Unique tickers: "
                  f"{len(combined_tickers)}/{len(loaded_tickers)}")

    # --- Earnings exclusions ---
    # Count how many exclusions overlap with our tickers/days
    relevant_excl = sum(
        1 for (t, d) in earnings_excl
        if t in loaded_tickers and d in set(trading_days)
    )
    print(f"\nEarnings exclusions: {relevant_excl} ticker-days excluded")

    print("=" * 55)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 55)
    print("RS Leader Pullback — Data Preparation")
    print("=" * 55)

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Discover tickers and load 4H bars
    print("\n[1/6] Loading M5 data and synthesizing 4H bars...")
    target_tickers = discover_equity_tickers()
    print(f"  Target equity tickers ({len(target_tickers)}): "
          f"{', '.join(target_tickers)}")
    bars_4h, loaded_tickers = load_all_4h_bars(target_tickers)

    # Step 2: Compute EMAs
    print("\n[2/6] Computing EMA 9 and EMA 21 on 4H close...")
    bars_4h = add_emas(bars_4h)

    # Step 3: Build VIX proxy
    print("\n[3/6] Building daily VIX proxy from VIXY...")
    vix_proxy = build_vix_proxy()

    # Step 4: Compute RS rankings
    print("\n[4/6] Computing daily relative-strength rankings...")
    rs_data = compute_rs_rankings(bars_4h, loaded_tickers)

    # Step 5: Compute 60-day rolling high
    print("\n[5/6] Computing 60-day rolling high...")
    high_data = compute_60d_high(bars_4h, loaded_tickers)

    # Step 6: Load earnings exclusions
    print("\n[6/6] Loading earnings calendar for exclusion zones...")
    earnings_excl = load_earnings_exclusions()

    # Print comprehensive summary
    print_summary(
        bars_4h, loaded_tickers, target_tickers,
        vix_proxy, rs_data, high_data, earnings_excl,
    )

    # Save prepared data to pickle
    prepared = {
        "bars_4h": bars_4h,
        "loaded_tickers": loaded_tickers,
        "vix_proxy": vix_proxy,
        "rs_data": rs_data,
        "high_data": high_data,
        "earnings_excl": earnings_excl,
    }
    with open(_OUTPUT_PKL, "wb") as f:
        pickle.dump(prepared, f, protocol=pickle.HIGHEST_PROTOCOL)
    size_mb = _OUTPUT_PKL.stat().st_size / (1024 * 1024)
    print(f"\nSaved prepared data to {_OUTPUT_PKL.name} ({size_mb:.1f} MB)")
    print("Data prep complete. Ready for Part 2 (signal detection).")


if __name__ == "__main__":
    main()
