"""
No-News Shock Reversal Backtest — Baseline Test (TEST 0).

Tests whether large idiosyncratic moves on non-earnings days tend to reverse.

Strategy:
  - Detect "shock" days: |daily return| >= SHOCK_THRESHOLD and
    |ticker return / SPY return| >= IDIOSYNCRATIC_MULTIPLIER
  - Filter out earnings days (±1 day buffer)
  - ENTRY: open of next trading day, opposite direction to shock
  - EXIT: 50% retracement, extension stop, or hard max hold

Reads:
  - backtester/data/daily/{TICKER}_daily.csv
  - backtester/data/daily/SPY_daily.csv
  - backtester/data/vix_daily.csv
  - backtester/data/fmp_earnings.csv

Produces:
  - backtest_output/nonews_shock_trades.csv
  - Console output with baseline results

Usage:
    python backtests/nonews_shock_backtest.py
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

# --- Paths ---
_DAILY_DIR = _REPO_ROOT / "backtester" / "data" / "daily"
_VIX_CSV = _REPO_ROOT / "backtester" / "data" / "vix_daily.csv"
_EARNINGS_CSV = _REPO_ROOT / "backtester" / "data" / "fmp_earnings.csv"
_OUTPUT_DIR = _REPO_ROOT / "backtest_output"
_TRADES_CSV = _OUTPUT_DIR / "nonews_shock_trades.csv"

# --- Parameters (TEST 0 baseline) ---
SHOCK_THRESHOLD = 1.5        # minimum absolute daily return %
IDIOSYNCRATIC_MULT = 1.5     # ticker move must be >= this * |SPY move|
MAX_HOLD = 5                 # max holding period in trading days
RETRACEMENT_TARGET = 0.50    # 50% retracement of shock bar range
EARNINGS_BUFFER_DAYS = 1     # exclude shocks within ±N calendar days of earnings

# --- Sector mapping ---
SECTORS = {
    "mega_tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA"],
    "growth_semi": ["TSLA", "AMD", "SMCI", "PLTR", "AVGO", "ARM", "TSM", "MU", "INTC"],
    "crypto_proxy": ["COIN", "MSTR", "MARA"],
    "finance": ["C", "GS", "V", "BA", "JPM"],
    "china_adr": ["BABA", "JD", "BIDU"],
    "consumer": ["COST"],
}

# Invert for lookup
TICKER_TO_SECTOR = {}
for sector, tickers in SECTORS.items():
    for t in tickers:
        TICKER_TO_SECTOR[t] = sector

# Universe: all tickers defined in SECTORS
UNIVERSE = sorted(set(t for tickers in SECTORS.values() for t in tickers))


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

def load_daily(ticker: str) -> pd.DataFrame:
    """Load daily OHLCV from backtester/data/daily/{TICKER}_daily.csv.

    These files have 3 header rows: row0=column labels, row1=ticker, row2='Date'.
    Actual data starts at row 3 (0-indexed).
    """
    path = _DAILY_DIR / f"{ticker}_daily.csv"
    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(path, skiprows=3, header=None,
                     names=["Date", "Close", "High", "Low", "Open", "Volume"])
    df["Date"] = pd.to_datetime(df["Date"])
    for col in ["Open", "High", "Low", "Close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0).astype(int)
    df = df.dropna(subset=["Open", "Close"]).sort_values("Date").reset_index(drop=True)
    df["Ticker"] = ticker
    return df


def load_spy_returns() -> pd.Series:
    """Load SPY daily returns as a Series indexed by date."""
    spy = load_daily("SPY")
    if spy.empty:
        raise FileNotFoundError("SPY daily data not found")
    spy["Return"] = (spy["Close"] / spy["Close"].shift(1) - 1) * 100
    return spy.set_index("Date")["Return"]


def load_vix() -> pd.Series:
    """Load VIX daily close as a Series indexed by date."""
    vix = pd.read_csv(_VIX_CSV, parse_dates=["date"])
    vix["vix_close"] = pd.to_numeric(vix["vix_close"], errors="coerce")
    return vix.set_index("date")["vix_close"]


def load_earnings_dates() -> dict:
    """Load earnings dates per ticker as a dict of sets of datetime.date."""
    earn = pd.read_csv(_EARNINGS_CSV)
    earn["earnings_date"] = pd.to_datetime(earn["earnings_date"], errors="coerce")
    earn = earn.dropna(subset=["earnings_date"])

    result = {}
    for ticker, grp in earn.groupby("ticker"):
        dates = set()
        for d in grp["earnings_date"]:
            for offset in range(-EARNINGS_BUFFER_DAYS, EARNINGS_BUFFER_DAYS + 1):
                dates.add((d + pd.Timedelta(days=offset)).date())
        result[ticker] = dates
    return result


# ---------------------------------------------------------------------------
# Shock Detection
# ---------------------------------------------------------------------------

def detect_shocks(daily_df: pd.DataFrame, spy_returns: pd.Series,
                  earnings_dates: dict) -> pd.DataFrame:
    """Detect shock events for a single ticker.

    Returns DataFrame with shock metadata.
    """
    df = daily_df.copy()
    if len(df) < 5:
        return pd.DataFrame()

    ticker = df["Ticker"].iloc[0]
    df["Return_Pct"] = (df["Close"] / df["Close"].shift(1) - 1) * 100
    df = df.dropna(subset=["Return_Pct"]).copy()

    # Merge SPY returns
    df = df.set_index("Date")
    df["SPY_Return"] = spy_returns
    df = df.dropna(subset=["SPY_Return"]).reset_index()

    # Filter: absolute return >= threshold
    df["Abs_Return"] = df["Return_Pct"].abs()
    shocks = df[df["Abs_Return"] >= SHOCK_THRESHOLD].copy()

    if shocks.empty:
        return pd.DataFrame()

    # Filter: idiosyncratic (ticker move >= MULT * SPY move)
    # Handle SPY_Return ~ 0 by using abs directly
    spy_abs = shocks["SPY_Return"].abs().clip(lower=0.01)
    shocks = shocks[shocks["Abs_Return"] >= IDIOSYNCRATIC_MULT * spy_abs].copy()

    if shocks.empty:
        return pd.DataFrame()

    # Filter: exclude earnings days
    earn_dates = earnings_dates.get(ticker, set())
    if earn_dates:
        shocks = shocks[~shocks["Date"].dt.date.isin(earn_dates)].copy()

    if shocks.empty:
        return pd.DataFrame()

    # Classify direction
    shocks["Shock_Type"] = np.where(shocks["Return_Pct"] < 0, "DOWN_SHOCK", "UP_SHOCK")

    # Keep shock bar OHLC for exit logic
    shocks = shocks.rename(columns={
        "Open": "Shock_Open", "High": "Shock_High",
        "Low": "Shock_Low", "Close": "Shock_Close",
    })
    shocks["Ticker"] = ticker

    return shocks[["Ticker", "Date", "Shock_Type", "Return_Pct", "Abs_Return",
                    "SPY_Return", "Shock_Open", "Shock_High", "Shock_Low",
                    "Shock_Close"]].copy()


# ---------------------------------------------------------------------------
# Trade Simulation
# ---------------------------------------------------------------------------

def simulate_trades(shocks: pd.DataFrame, daily_df: pd.DataFrame,
                    vix_series: pd.Series) -> list:
    """Simulate reversal trades for detected shocks of a single ticker.

    Returns list of trade dicts.
    """
    if shocks.empty:
        return []

    ticker = shocks["Ticker"].iloc[0]
    daily = daily_df.set_index("Date").sort_index()
    dates_list = daily.index.tolist()
    date_to_idx = {d: i for i, d in enumerate(dates_list)}

    trades = []
    last_exit_idx = -1  # for dedup: no overlapping trades

    for _, shock in shocks.iterrows():
        shock_date = shock["Date"]
        if shock_date not in date_to_idx:
            continue

        shock_idx = date_to_idx[shock_date]
        entry_idx = shock_idx + 1  # day after shock

        if entry_idx >= len(dates_list):
            continue

        # Dedup: skip if we're still in a previous trade
        if entry_idx <= last_exit_idx:
            continue

        entry_date = dates_list[entry_idx]
        entry_price = daily.loc[entry_date, "Open"]
        if pd.isna(entry_price) or entry_price <= 0:
            continue

        shock_open = shock["Shock_Open"]
        shock_close = shock["Shock_Close"]
        shock_type = shock["Shock_Type"]
        is_long = shock_type == "DOWN_SHOCK"

        # Compute exit thresholds
        shock_range = abs(shock_open - shock_close)
        if shock_range < 0.001:
            continue

        if is_long:
            # DOWN_SHOCK → LONG: expecting bounce
            retrace_target = shock_open - RETRACEMENT_TARGET * (shock_open - shock_close)
            extension_stop = shock_close - (shock_open - shock_close)
        else:
            # UP_SHOCK → SHORT: expecting fade
            retrace_target = shock_open + RETRACEMENT_TARGET * (shock_close - shock_open)
            extension_stop = shock_close + (shock_close - shock_open)

        # Simulate day by day
        exit_price = None
        exit_date = None
        exit_reason = None
        hold_days = 0

        for day_offset in range(1, MAX_HOLD + 1):
            check_idx = entry_idx + day_offset - 1
            if check_idx >= len(dates_list):
                # Ran out of data — exit at last available close
                check_idx = len(dates_list) - 1
                check_date = dates_list[check_idx]
                exit_price = daily.loc[check_date, "Close"]
                exit_date = check_date
                exit_reason = "DATA_END"
                hold_days = check_idx - entry_idx + 1
                break

            check_date = dates_list[check_idx]
            close = daily.loc[check_date, "Close"]
            hold_days = day_offset

            # Check retracement
            if is_long and close >= retrace_target:
                exit_price = close
                exit_date = check_date
                exit_reason = "RETRACEMENT"
                break
            elif not is_long and close <= retrace_target:
                exit_price = close
                exit_date = check_date
                exit_reason = "RETRACEMENT"
                break

            # Check extension stop
            if is_long and close < extension_stop:
                exit_price = close
                exit_date = check_date
                exit_reason = "EXTENSION_STOP"
                break
            elif not is_long and close > extension_stop:
                exit_price = close
                exit_date = check_date
                exit_reason = "EXTENSION_STOP"
                break

            # Check hard max
            if day_offset == MAX_HOLD:
                exit_price = close
                exit_date = check_date
                exit_reason = "HARD_MAX"
                break

        if exit_price is None or pd.isna(exit_price):
            continue

        # Compute return
        if is_long:
            ret_pct = (exit_price - entry_price) / entry_price * 100
        else:
            ret_pct = (entry_price - exit_price) / entry_price * 100

        # VIX on shock date
        shock_date_ts = pd.Timestamp(shock_date)
        vix_val = vix_series.get(shock_date_ts, np.nan)

        last_exit_idx = date_to_idx.get(exit_date, entry_idx)

        trades.append({
            "Ticker": ticker,
            "Sector": TICKER_TO_SECTOR.get(ticker, "unknown"),
            "Shock_Date": shock["Date"],
            "Shock_Type": shock_type,
            "Shock_Return_Pct": shock["Return_Pct"],
            "Shock_Abs_Return": shock["Abs_Return"],
            "SPY_Return": shock["SPY_Return"],
            "Shock_Open": shock_open,
            "Shock_Close": shock_close,
            "Entry_Date": entry_date,
            "Entry_Price": entry_price,
            "Exit_Date": exit_date,
            "Exit_Price": exit_price,
            "Exit_Reason": exit_reason,
            "Direction": "LONG" if is_long else "SHORT",
            "Return_Pct": ret_pct,
            "Hold_Days": hold_days,
            "VIX": vix_val,
        })

    return trades


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def classify_vix(vix_val):
    if pd.isna(vix_val):
        return "UNKNOWN"
    if vix_val < 20:
        return "NORMAL"
    elif vix_val < 25:
        return "ELEVATED"
    else:
        return "HIGH_RISK"


def classify_shock_size(abs_ret):
    if abs_ret < 3:
        return "1.5-3%"
    elif abs_ret < 5:
        return "3-5%"
    elif abs_ret < 8:
        return "5-8%"
    else:
        return ">8%"


def print_group_stats(df, label):
    """Print N, mean return, win rate for a group."""
    n = len(df)
    if n == 0:
        return f"  {label}: N=0"
    mean_ret = df["Return_Pct"].mean()
    wr = (df["Return_Pct"] > 0).mean() * 100
    return f"  {label}: N={n}, mean={mean_ret:.2f}%, WR={wr:.1f}%"


def print_results(trades_df: pd.DataFrame):
    """Print formatted TEST 0 results."""
    print("\n" + "=" * 55)
    print("=== TEST 0: No-News Shock Reversal Baseline ===")
    print("=" * 55)

    n = len(trades_df)
    print(f"N trades: {n}")

    if n == 0:
        print("\nNo trades generated. Check data availability.")
        print("\nVERDICT: NO_EDGE")
        return

    # --- Performance ---
    mean_ret = trades_df["Return_Pct"].mean()
    median_ret = trades_df["Return_Pct"].median()
    wr = (trades_df["Return_Pct"] > 0).mean() * 100
    avg_hold = trades_df["Hold_Days"].mean()

    winners = trades_df[trades_df["Return_Pct"] > 0]["Return_Pct"].sum()
    losers = abs(trades_df[trades_df["Return_Pct"] <= 0]["Return_Pct"].sum())
    pf = winners / losers if losers > 0 else float("inf")

    print(f"\nPerformance:")
    print(f"  Mean return: {mean_ret:.2f}%")
    print(f"  Median return: {median_ret:.2f}%")
    print(f"  Win rate: {wr:.1f}%")
    print(f"  Profit factor: {pf:.2f}")
    print(f"  Avg hold: {avg_hold:.1f} days")

    # --- Exit reasons ---
    print(f"\nExit reasons:")
    for reason in ["RETRACEMENT", "HARD_MAX", "EXTENSION_STOP", "DATA_END"]:
        cnt = (trades_df["Exit_Reason"] == reason).sum()
        if cnt > 0:
            pct = cnt / n * 100
            print(f"  {reason}: {cnt} ({pct:.0f}%)")

    # --- By direction ---
    print(f"\nBy direction:")
    for stype, direction_label in [("DOWN_SHOCK", "DOWN_SHOCK (long reversal)"),
                                    ("UP_SHOCK", "UP_SHOCK (short reversal)")]:
        grp = trades_df[trades_df["Shock_Type"] == stype]
        print(print_group_stats(grp, direction_label))

    # --- By shock size ---
    print(f"\nBy shock size:")
    trades_df["Size_Bucket"] = trades_df["Shock_Abs_Return"].apply(classify_shock_size)
    for bucket in ["1.5-3%", "3-5%", "5-8%", ">8%"]:
        grp = trades_df[trades_df["Size_Bucket"] == bucket]
        print(print_group_stats(grp, bucket))

    # --- By VIX regime ---
    print(f"\nBy VIX regime:")
    trades_df["VIX_Regime"] = trades_df["VIX"].apply(classify_vix)
    for regime in ["NORMAL (VIX<20)", "ELEVATED (20-25)", "HIGH_RISK (>=25)"]:
        regime_key = regime.split(" ")[0]
        grp = trades_df[trades_df["VIX_Regime"] == regime_key]
        print(print_group_stats(grp, regime))

    # --- By sector ---
    print(f"\nBy sector:")
    for sector in ["mega_tech", "growth_semi", "finance", "china_adr",
                    "crypto_proxy", "consumer"]:
        grp = trades_df[trades_df["Sector"] == sector]
        print(print_group_stats(grp, f"{sector}"))

    # --- Top 5 tickers by trade count ---
    print(f"\nTop 5 tickers by trade count:")
    ticker_counts = trades_df.groupby("Ticker").agg(
        N=("Return_Pct", "count"),
        Mean=("Return_Pct", "mean"),
    ).sort_values("N", ascending=False).head(5)
    for ticker, row in ticker_counts.iterrows():
        print(f"  {ticker}: N={int(row['N'])}, mean={row['Mean']:.2f}%")

    # --- Verdict ---
    print()
    if wr > 58 and mean_ret > 0.5 and n >= 40:
        verdict = "PROMISING"
    elif (52 <= wr <= 58) or (0.2 <= mean_ret <= 0.5):
        verdict = "MARGINAL"
    else:
        verdict = "NO_EDGE"

    print(f"VERDICT: {verdict}")
    if verdict == "PROMISING":
        print(f"  WR > 58% AND mean > 0.5% AND N >= 40")
    elif verdict == "MARGINAL":
        print(f"  WR 52-58% OR mean 0.2-0.5%")
    else:
        print(f"  WR < 52% OR mean < 0.2%")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Loading market data...")

    # Load SPY returns and VIX
    spy_returns = load_spy_returns()
    vix_series = load_vix()
    earnings_dates = load_earnings_dates()

    print(f"  SPY returns: {len(spy_returns)} days")
    print(f"  VIX data: {len(vix_series)} days")
    print(f"  Earnings tickers: {len(earnings_dates)}")

    # Process each ticker
    all_trades = []
    tickers_processed = 0
    tickers_with_shocks = 0

    for ticker in UNIVERSE:
        daily = load_daily(ticker)
        if daily.empty:
            print(f"  {ticker}: no daily data, skipping")
            continue

        tickers_processed += 1
        shocks = detect_shocks(daily, spy_returns, earnings_dates)

        if shocks.empty:
            continue

        tickers_with_shocks += 1
        trades = simulate_trades(shocks, daily, vix_series)
        all_trades.extend(trades)

    print(f"\nProcessed {tickers_processed} tickers, "
          f"{tickers_with_shocks} had shocks")

    # Build trades DataFrame
    if all_trades:
        trades_df = pd.DataFrame(all_trades)
        trades_df = trades_df.sort_values(["Shock_Date", "Ticker"]).reset_index(drop=True)

        # Save
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        trades_df.to_csv(_TRADES_CSV, index=False)
        print(f"Saved {len(trades_df)} trades to {_TRADES_CSV}")
    else:
        trades_df = pd.DataFrame()

    # Print results
    print_results(trades_df)


if __name__ == "__main__":
    main()
