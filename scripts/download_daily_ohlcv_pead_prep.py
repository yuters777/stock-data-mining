"""
Download daily OHLCV data and build PEAD daily events table.
Tasks:
  1. Download daily OHLCV via yfinance for all tickers + SPY
     (Falls back to existing backtest_output/ CSVs if yfinance unavailable)
  2. Build PEAD daily events table with abnormal gaps, revenue confirmation, drift
  3. Print data prep summary
"""

import os
import shutil
import time
import pandas as pd
import numpy as np

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY_DIR = os.path.join(BASE_DIR, "backtester", "data", "daily")
FALLBACK_DIR = os.path.join(BASE_DIR, "backtest_output")
EARNINGS_PATH = os.path.join(BASE_DIR, "backtester", "data", "fmp_earnings.csv")
OUTPUT_DIR = os.path.join(BASE_DIR, "backtest_output")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "pead_daily_events.csv")

os.makedirs(DAILY_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# All tickers from task + earnings CSV unique tickers + SPY
TICKERS = sorted(set([
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU",
    "C", "COIN", "COST", "GOOGL", "GS", "INTC", "JPM", "MARA",
    "META", "MSFT", "MSTR", "MU", "NVDA", "PLTR", "SMCI", "TSLA",
    "TSM", "V", "SNOW", "TXN", "SPY"
]))

# ═══════════════════════════════════════════════════════════════════════════════
# TASK 1: Download daily OHLCV (with fallback to existing data)
# ═══════════════════════════════════════════════════════════════════════════════
print("=" * 60)
print("TASK 1: Downloading daily OHLCV data")
print("=" * 60)

# Try yfinance first
yf_available = False
try:
    import yfinance as yf
    # Test with a quick download
    test = yf.download("SPY", start="2025-01-01", end="2025-01-10", progress=False)
    if len(test) > 0:
        yf_available = True
        print("yfinance: AVAILABLE")
    else:
        print("yfinance: returned empty data (proxy blocked?), using fallback")
except Exception as e:
    print(f"yfinance: UNAVAILABLE ({e}), using fallback")

download_results = {}

if yf_available:
    for ticker in TICKERS:
        out_path = os.path.join(DAILY_DIR, f"{ticker}_daily.csv")
        try:
            df = yf.download(ticker, start="2016-01-01", end="2026-04-01",
                             auto_adjust=True, progress=False)
            if df.empty:
                print(f"  {ticker}: EMPTY — skipped")
                download_results[ticker] = 0
                continue

            # Flatten multi-level columns if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
            df.index.name = "Date"
            df.to_csv(out_path)

            download_results[ticker] = len(df)
            print(f"  {ticker}: {len(df)} rows, {df.index[0].date()} to {df.index[-1].date()}")
        except Exception as e:
            print(f"  {ticker}: ERROR — {e}")
            download_results[ticker] = 0
        time.sleep(0.3)
else:
    # Fallback: copy existing daily CSVs from backtest_output/
    print("\nUsing existing daily CSVs from backtest_output/")
    for ticker in TICKERS:
        src = os.path.join(FALLBACK_DIR, f"{ticker}_daily.csv")
        dst = os.path.join(DAILY_DIR, f"{ticker}_daily.csv")
        if os.path.exists(src):
            # Read, normalize columns, and save
            df = pd.read_csv(src)
            # Normalize column name: 'date' -> 'Date'
            if "date" in df.columns:
                df = df.rename(columns={"date": "Date"})
            # Ensure standard column order
            cols_needed = ["Date", "Open", "High", "Low", "Close", "Volume"]
            # Some files have columns in different order
            available_cols = [c for c in cols_needed if c in df.columns]
            df = df[available_cols]
            df.to_csv(dst, index=False)
            download_results[ticker] = len(df)
            print(f"  {ticker}: {len(df)} rows (from backtest_output/)")
        else:
            print(f"  {ticker}: NOT FOUND in backtest_output/")
            download_results[ticker] = 0

downloaded_count = sum(1 for v in download_results.values() if v > 0)
print(f"\nAvailable: {downloaded_count}/{len(TICKERS)} tickers")

# ═══════════════════════════════════════════════════════════════════════════════
# TASK 2: Build PEAD daily events table
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("TASK 2: Building PEAD daily events table")
print("=" * 60)

# Load earnings
earnings = pd.read_csv(EARNINGS_PATH)
earnings["earnings_date"] = pd.to_datetime(earnings["earnings_date"])
print(f"Loaded {len(earnings)} earnings events")

# Load SPY daily
spy_path = os.path.join(DAILY_DIR, "SPY_daily.csv")
if not os.path.exists(spy_path):
    print("ERROR: SPY daily data not available. Cannot compute abnormal gaps.")
    exit(1)

spy_df = pd.read_csv(spy_path, parse_dates=["Date"], index_col="Date").sort_index()
print(f"SPY: {len(spy_df)} rows, {spy_df.index[0].date()} to {spy_df.index[-1].date()}")

# Cache loaded ticker data
ticker_cache = {"SPY": spy_df}


def load_ticker(ticker):
    if ticker in ticker_cache:
        return ticker_cache[ticker]
    path = os.path.join(DAILY_DIR, f"{ticker}_daily.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, parse_dates=["Date"], index_col="Date").sort_index()
    ticker_cache[ticker] = df
    return df


def get_prev_trading_day(df, date):
    """Get the last trading day strictly before `date`."""
    prior = df.index[df.index < date]
    return prior[-1] if len(prior) > 0 else None


def get_on_or_next_trading_day(df, date):
    """Get `date` if it's a trading day, else the next trading day."""
    on_or_after = df.index[df.index >= date]
    return on_or_after[0] if len(on_or_after) > 0 else None


def get_nth_trading_day_after(df, date, n):
    """Get the nth trading day strictly after `date`."""
    after = df.index[df.index > date]
    if len(after) >= n:
        return after[n - 1]
    return None


events = []
skipped = 0
skip_reasons = {"no_ticker_data": 0, "no_prior_date": 0, "no_reaction_date": 0,
                "date_not_in_data": 0, "spy_missing": 0}

for _, row in earnings.iterrows():
    ticker = row["ticker"]
    edate = row["earnings_date"]
    tod = row["time_of_day"]

    tdf = load_ticker(ticker)
    if tdf is None or len(tdf) == 0:
        skipped += 1
        skip_reasons["no_ticker_data"] += 1
        continue

    # Determine prior_close date and reaction date based on AMC/BMO
    if tod == "BMO":
        # BMO: reported before market open on earnings_date
        # prior_close = close on day BEFORE earnings_date
        # reaction day = earnings_date (gap opens at earnings_date open)
        prior_date = get_prev_trading_day(tdf, edate)
        reaction_date = get_on_or_next_trading_day(tdf, edate)
    else:
        # AMC (or null): reported after market close on earnings_date
        # prior_close = close on earnings_date
        # reaction day = next trading day after earnings_date
        prior_date = get_on_or_next_trading_day(tdf, edate)
        # Reaction day is the NEXT trading day after earnings_date
        reaction_date = get_nth_trading_day_after(tdf, edate, 1)

    if prior_date is None:
        skipped += 1
        skip_reasons["no_prior_date"] += 1
        continue
    if reaction_date is None:
        skipped += 1
        skip_reasons["no_reaction_date"] += 1
        continue

    # Same logic for SPY
    if tod == "BMO":
        spy_prior_date = get_prev_trading_day(spy_df, edate)
        spy_reaction_date = get_on_or_next_trading_day(spy_df, edate)
    else:
        spy_prior_date = get_on_or_next_trading_day(spy_df, edate)
        spy_reaction_date = get_nth_trading_day_after(spy_df, edate, 1)

    if spy_prior_date is None or spy_reaction_date is None:
        skipped += 1
        skip_reasons["spy_missing"] += 1
        continue

    # Check dates exist in data
    if prior_date not in tdf.index or reaction_date not in tdf.index:
        skipped += 1
        skip_reasons["date_not_in_data"] += 1
        continue
    if spy_prior_date not in spy_df.index or spy_reaction_date not in spy_df.index:
        skipped += 1
        skip_reasons["spy_missing"] += 1
        continue

    prior_close = tdf.loc[prior_date, "Close"]
    next_open = tdf.loc[reaction_date, "Open"]
    reaction_close = tdf.loc[reaction_date, "Close"]
    reaction_high = tdf.loc[reaction_date, "High"]
    reaction_low = tdf.loc[reaction_date, "Low"]

    spy_prior_close = spy_df.loc[spy_prior_date, "Close"]
    spy_next_open = spy_df.loc[spy_reaction_date, "Open"]

    # Gap calculations
    raw_gap_pct = (next_open - prior_close) / prior_close * 100
    spy_gap_pct = (spy_next_open - spy_prior_close) / spy_prior_close * 100
    abnormal_gap_pct = raw_gap_pct - spy_gap_pct

    # Reaction day stats
    reaction_day_range = reaction_high - reaction_low
    reaction_day_midpoint = (reaction_high + reaction_low) / 2

    # First day holds
    if raw_gap_pct > 0:
        first_day_holds = (reaction_close > prior_close) and (reaction_close >= reaction_day_midpoint)
    elif raw_gap_pct < 0:
        first_day_holds = (reaction_close < prior_close) and (reaction_close <= reaction_day_midpoint)
    else:
        first_day_holds = False

    # Revenue confirmation
    eps_surprise = row["eps_surprise_pct"]
    rev_surprise = row["revenue_surprise_pct"]
    if pd.notna(eps_surprise) and pd.notna(rev_surprise):
        revenue_confirms = bool(np.sign(eps_surprise) == np.sign(rev_surprise))
    else:
        revenue_confirms = None

    # Drift calculations (1d, 3d, 5d, 10d after reaction day)
    drift = {}
    for n in [1, 3, 5, 10]:
        drift_date = get_nth_trading_day_after(tdf, reaction_date, n)
        if drift_date is not None and drift_date in tdf.index:
            drift_close = tdf.loc[drift_date, "Close"]
            drift[f"drift_{n}d_close"] = drift_close
            drift[f"drift_{n}d_pct"] = (drift_close - reaction_close) / reaction_close * 100
        else:
            drift[f"drift_{n}d_close"] = np.nan
            drift[f"drift_{n}d_pct"] = np.nan

    event = {
        "ticker": ticker,
        "earnings_date": edate.date(),
        "time_of_day": tod,
        "prior_date": prior_date.date(),
        "reaction_date": reaction_date.date(),
        "prior_close": round(prior_close, 4),
        "next_open": round(next_open, 4),
        "reaction_close": round(reaction_close, 4),
        "reaction_high": round(reaction_high, 4),
        "reaction_low": round(reaction_low, 4),
        "reaction_day_range": round(reaction_day_range, 4),
        "reaction_day_midpoint": round(reaction_day_midpoint, 4),
        "raw_gap_pct": round(raw_gap_pct, 4),
        "spy_gap_pct": round(spy_gap_pct, 4),
        "abnormal_gap_pct": round(abnormal_gap_pct, 4),
        "eps_surprise_pct": eps_surprise,
        "revenue_surprise_pct": rev_surprise,
        "revenue_confirms": revenue_confirms,
        "first_day_holds": first_day_holds,
    }
    event.update({k: round(v, 4) if pd.notna(v) else v for k, v in drift.items()})
    events.append(event)

events_df = pd.DataFrame(events)
events_df.to_csv(OUTPUT_PATH, index=False)
print(f"\nBuilt {len(events_df)} events ({skipped} skipped)")
print(f"Skip reasons: {skip_reasons}")
print(f"Saved to {OUTPUT_PATH}")

# ═══════════════════════════════════════════════════════════════════════════════
# TASK 3: Print data prep summary
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("=== Daily PEAD Data Prep Summary ===")
print("=" * 60)

# Daily OHLCV summary
print("\nDaily OHLCV:")
print(f"  Tickers downloaded: {downloaded_count}/{len(TICKERS)}")
all_min_dates = []
all_max_dates = []
for t, n in download_results.items():
    if n > 0:
        tdf = load_ticker(t)
        if tdf is not None and len(tdf) > 0:
            all_min_dates.append(tdf.index[0])
            all_max_dates.append(tdf.index[-1])
if all_min_dates:
    print(f"  Date range: {min(all_min_dates).date()} to {max(all_max_dates).date()}")
spy_rows = download_results.get("SPY", 0)
print(f"  SPY rows: {spy_rows}")

# Earnings events
print(f"\nEarnings events:")
print(f"  Total in FMP: {len(earnings)}")
print(f"  With daily data available: {len(events_df)}")
if len(events_df) > 0:
    eps_not_null = events_df["eps_surprise_pct"].notna().sum()
    print(f"  With eps_actual not null: {eps_not_null}")
    rev_not_null = events_df["revenue_surprise_pct"].notna().sum()
    print(f"  With revenue data: {rev_not_null}")

    # Gap statistics
    print(f"\nGap statistics:")
    for thresh in [1, 2, 3]:
        raw_count = (events_df["raw_gap_pct"].abs() >= thresh).sum()
        abn_count = (events_df["abnormal_gap_pct"].abs() >= thresh).sum()
        print(f"  Events with |raw_gap| >= {thresh}%: {raw_count}")
        print(f"  Events with |abnormal_gap| >= {thresh}%: {abn_count}")

    # Revenue confirmation
    print(f"\nRevenue confirmation:")
    rev_conf = events_df["revenue_confirms"]
    confirms = (rev_conf == True).sum()
    contradicts = (rev_conf == False).sum()
    total_rev = confirms + contradicts
    if total_rev > 0:
        print(f"  Events where revenue confirms EPS: {confirms} ({confirms/total_rev*100:.0f}%)")
        print(f"  Events where revenue contradicts EPS: {contradicts} ({contradicts/total_rev*100:.0f}%)")
    else:
        print(f"  Events where revenue confirms EPS: 0")
        print(f"  Events where revenue contradicts EPS: 0")

    # Direction + first day holds
    pos_gaps = (events_df["raw_gap_pct"] > 0).sum()
    neg_gaps = (events_df["raw_gap_pct"] < 0).sum()
    print(f"\nPositive gaps: {pos_gaps} | Negative gaps: {neg_gaps}")

    gap2 = events_df[events_df["raw_gap_pct"].abs() >= 2]
    holds_count = gap2["first_day_holds"].sum()
    if len(gap2) > 0:
        print(f"First day holds (raw gap >= 2%): {int(holds_count)} ({holds_count/len(gap2)*100:.0f}%)")
    else:
        print(f"First day holds (raw gap >= 2%): 0 (0%)")
else:
    print("\n  WARNING: No events could be built. Check data availability.")

print("\nDone.")
