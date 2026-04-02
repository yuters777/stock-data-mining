"""
No-News Shock Reversal — Data Preparation
CC-NONEWS-1: Detect large idiosyncratic moves on non-earnings days and measure post-shock drift.
"""

import os
import sys
import pandas as pd
import numpy as np
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = ROOT / "backtester" / "data" / "daily"
EARNINGS_PATH = ROOT / "backtester" / "data" / "fmp_earnings.csv"
VIX_PATH = ROOT / "backtester" / "data" / "vix_daily.csv"
OUTPUT_DIR = ROOT / "backtest_output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Tickers to exclude from signal generation
EXCLUDE_TICKERS = {"SPY", "VIXY", "BTC", "ETH"}

# ── 1. Load daily OHLCV ───────────────────────────────────────────────────

def load_daily(ticker: str) -> pd.DataFrame:
    """Load a yfinance-format daily CSV (3-row header)."""
    path = DAILY_DIR / f"{ticker}_daily.csv"
    df = pd.read_csv(path, header=[0, 1], index_col=0, parse_dates=True)
    # Flatten multi-level columns: keep the price-type level
    df.columns = [col[0] for col in df.columns]
    df = df.astype(float)
    df.sort_index(inplace=True)
    return df


# Discover tickers
all_files = sorted(DAILY_DIR.glob("*_daily.csv"))
all_tickers = [f.stem.replace("_daily", "") for f in all_files]
signal_tickers = [t for t in all_tickers if t not in EXCLUDE_TICKERS]

print(f"Found {len(all_tickers)} tickers total, {len(signal_tickers)} signal tickers")

# Load SPY
spy = load_daily("SPY")

# Load signal tickers
ticker_data: dict[str, pd.DataFrame] = {}
for t in signal_tickers:
    try:
        ticker_data[t] = load_daily(t)
    except Exception as e:
        print(f"  WARNING: skipping {t}: {e}")

print(f"Loaded {len(ticker_data)} signal tickers")

# ── 2. Compute daily returns ──────────────────────────────────────────────

def add_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Add daily_return_pct and intraday_return_pct columns."""
    df["daily_return_pct"] = df["Close"].pct_change() * 100
    df["intraday_return_pct"] = (df["Close"] - df["Open"]) / df["Open"] * 100
    return df


spy = add_returns(spy)

for t in ticker_data:
    ticker_data[t] = add_returns(ticker_data[t])

# ── 3. Detect shock events ───────────────────────────────────────────────

# Load earnings calendar and build exclusion set (earnings day + day after)
earnings_df = pd.read_csv(EARNINGS_PATH)
earnings_df["earnings_date"] = pd.to_datetime(earnings_df["earnings_date"])

# Build per-ticker set of excluded dates
earnings_exclusions: dict[str, set] = {}
for ticker, grp in earnings_df.groupby("ticker"):
    excluded = set()
    for d in grp["earnings_date"]:
        excluded.add(d.normalize())
        # Day after earnings
        next_bday = d.normalize() + pd.offsets.BDay(1)
        excluded.add(next_bday)
    earnings_exclusions[ticker] = excluded

# SPY return series for idiosyncratic filter
spy_abs_ret = spy["daily_return_pct"].abs()

SHOCK_THRESHOLD = 1.5       # minimum absolute return %
IDIO_MULTIPLIER = 1.5       # must be this many times SPY's move

shock_events = []
earnings_filtered_count = 0
pre_filter_count = 0

for ticker, df in ticker_data.items():
    abs_ret = df["daily_return_pct"].abs()
    dates = df.index

    for i in range(1, len(df)):  # skip first row (NaN return)
        date = dates[i]
        ret = df["daily_return_pct"].iloc[i]
        ar = abs(ret)

        if np.isnan(ret):
            continue

        # (a) Big enough move
        if ar < SHOCK_THRESHOLD:
            continue

        # (b) Idiosyncratic: must exceed SPY move by multiplier
        if date not in spy_abs_ret.index:
            continue
        spy_ar = spy_abs_ret.loc[date]
        if np.isnan(spy_ar) or spy_ar == 0:
            # If SPY didn't move, any move is idiosyncratic
            pass
        elif ar < IDIO_MULTIPLIER * spy_ar:
            continue

        pre_filter_count += 1

        # (c) Not earnings day or day after
        excl = earnings_exclusions.get(ticker, set())
        if date.normalize() in excl:
            earnings_filtered_count += 1
            continue

        direction = "DOWN_SHOCK" if ret < 0 else "UP_SHOCK"

        shock_events.append({
            "ticker": ticker,
            "date": date,
            "daily_return_pct": ret,
            "abs_return_pct": ar,
            "intraday_return_pct": df["intraday_return_pct"].iloc[i],
            "spy_return_pct": spy["daily_return_pct"].get(date, np.nan),
            "close": df["Close"].iloc[i],
            "direction": direction,
        })

shocks_df = pd.DataFrame(shock_events)
print(f"\nShock detection: {pre_filter_count} pre-filter, "
      f"{earnings_filtered_count} earnings-excluded, "
      f"{len(shocks_df)} final")

# ── 4. Compute post-shock drift ──────────────────────────────────────────

drift_horizons = [1, 2, 3, 5]

for h in drift_horizons:
    shocks_df[f"drift_{h}d"] = np.nan

for idx, row in shocks_df.iterrows():
    ticker = row["ticker"]
    shock_date = row["date"]
    df = ticker_data[ticker]

    # Find position of shock day in the ticker's index
    loc = df.index.get_loc(shock_date)
    shock_close = row["close"]

    for h in drift_horizons:
        future_loc = loc + h
        if future_loc < len(df):
            future_close = df["Close"].iloc[future_loc]
            drift = (future_close - shock_close) / shock_close * 100
            shocks_df.at[idx, f"drift_{h}d"] = drift

# Reversal flags
for h in drift_horizons:
    col = f"drift_{h}d"
    shocks_df[f"reversal_{h}d"] = (
        ((shocks_df["direction"] == "DOWN_SHOCK") & (shocks_df[col] > 0)) |
        ((shocks_df["direction"] == "UP_SHOCK") & (shocks_df[col] < 0))
    )

# ── 5. VIX regime tagging ────────────────────────────────────────────────

vix_df = pd.read_csv(VIX_PATH, parse_dates=["date"], index_col="date")
vix_df.sort_index(inplace=True)

def vix_regime(vix_val):
    if pd.isna(vix_val):
        return "UNKNOWN"
    if vix_val < 20:
        return "NORMAL"
    elif vix_val < 25:
        return "ELEVATED"
    else:
        return "HIGH_RISK"


shocks_df["vix_close"] = shocks_df["date"].map(
    lambda d: vix_df["vix_close"].get(d, np.nan)
)
shocks_df["vix_regime"] = shocks_df["vix_close"].apply(vix_regime)

# ── 6. Save and print summary ────────────────────────────────────────────

output_path = OUTPUT_DIR / "nonews_shock_events.csv"
shocks_df.to_csv(output_path, index=False)
print(f"\nSaved {len(shocks_df)} events to {output_path}")

# ── Summary ───────────────────────────────────────────────────────────────

# Date range across all tickers
all_dates = set()
for df in ticker_data.values():
    all_dates.update(df.index)
min_date = min(all_dates)
max_date = max(all_dates)

n_down = (shocks_df["direction"] == "DOWN_SHOCK").sum()
n_up = (shocks_df["direction"] == "UP_SHOCK").sum()
total = len(shocks_df)

# Shock size buckets
ar = shocks_df["abs_return_pct"]
size_buckets = {
    "1.5-3%": ((ar >= 1.5) & (ar < 3)).sum(),
    "3-5%":   ((ar >= 3) & (ar < 5)).sum(),
    "5-8%":   ((ar >= 5) & (ar < 8)).sum(),
    ">8%":    (ar >= 8).sum(),
}

# VIX regime counts
regime_counts = shocks_df["vix_regime"].value_counts()

# Top tickers
top_tickers = shocks_df["ticker"].value_counts().head(5)

print(f"""
=== No-News Shock Data Prep Summary ===

Daily data:
  Tickers loaded: {len(ticker_data)}
  SPY rows: {len(spy)}
  Date range: {min_date.date()} to {max_date.date()}
  Total trading days: {len(all_dates)}

Shock detection (|return| >= {SHOCK_THRESHOLD}%, >= {IDIO_MULTIPLIER}x SPY):
  Total shocks (before earnings filter): {pre_filter_count}
  Earnings-day exclusions: {earnings_filtered_count}
  Final qualifying shocks: {total}

  DOWN_SHOCK: {n_down} ({n_down/total*100:.1f}%)
  UP_SHOCK: {n_up} ({n_up/total*100:.1f}%)

Shock size distribution:""")
for label, count in size_buckets.items():
    print(f"  {label}: {count} events")

print(f"\nBy VIX regime:")
for regime in ["NORMAL", "ELEVATED", "HIGH_RISK", "UNKNOWN"]:
    cnt = regime_counts.get(regime, 0)
    if cnt > 0:
        print(f"  {regime}: {cnt} shocks")

print(f"\nTop 5 tickers by shock count:")
for ticker, cnt in top_tickers.items():
    print(f"  {ticker}: {cnt} shocks")

# Post-shock drift summary
print(f"\nMean post-shock drift (all events):")
for h in drift_horizons:
    col = f"drift_{h}d"
    rev_col = f"reversal_{h}d"
    valid = shocks_df[col].dropna()
    rev_rate = shocks_df[rev_col].sum() / shocks_df[rev_col].count() * 100 if shocks_df[rev_col].count() > 0 else 0
    print(f"  {h}-day: {valid.mean():.3f}% (reversal rate: {rev_rate:.1f}%)")
