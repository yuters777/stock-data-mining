"""
PEAD Daily Baseline — Data Prep & Events Table (Part 1a of 3).

Reads FMP earnings data, loads daily OHLCV + VIX,
joins earnings events with price data, computes per-event metrics,
and outputs a clean CSV for parts 1b and 1c.

Data sources (in priority order):
  1. Production DB: /var/lib/market-system/market.db  (earnings_calendar table)
  2. Local CSVs:    backtester/data/fmp_earnings.csv + backtest_output/ant1/earnings_calendar_full.csv
  3. Daily OHLCV:   backtester/data/daily/{TICKER}_daily.csv  (pre-downloaded)
  4. VIX:           Fetched_Data/VXVCLS.csv  (FRED VXVCLS series)
  5. Fallback:      yfinance download if local files missing

Produces:
  - results/pead_events_daily.csv

Usage:
    python backtests/pead_daily_baseline_prep.py
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DB_PATH = Path("/var/lib/market-system/market.db")
FMP_CSV_PRIMARY = _REPO_ROOT / "backtester" / "data" / "fmp_earnings.csv"
FMP_CSV_FULL = _REPO_ROOT / "backtest_output" / "ant1" / "earnings_calendar_full.csv"
DAILY_DIR = _REPO_ROOT / "backtester" / "data" / "daily"
VIX_CSV = _REPO_ROOT / "Fetched_Data" / "VXVCLS.csv"
VIX_CSV_ALT = _REPO_ROOT / "Fetched_Data" / "VIXCLS_FRED_real.csv"
OUTPUT_DIR = _REPO_ROOT / "results"
OUTPUT_CSV = OUTPUT_DIR / "pead_events_daily.csv"

START_DATE = "2016-01-01"
END_DATE = "2026-04-07"

TICKERS = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU",
    "C", "COIN", "COST", "GOOGL", "GS", "INTC", "JPM", "JD",
    "MARA", "META", "MSFT", "MSTR", "MU", "NVDA", "PLTR",
    "SMCI", "TSLA", "TSM", "V",
]


# ---------------------------------------------------------------------------
# 1. Load Earnings Data
# ---------------------------------------------------------------------------
def load_earnings() -> pd.DataFrame:
    """Load earnings events from production DB or fall back to CSV files."""
    df = None

    # Try production DB first
    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(str(DB_PATH))
            df = pd.read_sql_query("SELECT * FROM earnings_calendar", conn)
            conn.close()
            print(f"Loaded {len(df)} rows from production DB: {DB_PATH}")
        except Exception as e:
            print(f"DB read failed ({e}), falling back to CSV.")
            df = None

    # Fallback: merge CSV sources
    if df is None:
        frames = []
        if FMP_CSV_PRIMARY.exists():
            primary = pd.read_csv(FMP_CSV_PRIMARY)
            print(f"Loaded {len(primary)} rows from {FMP_CSV_PRIMARY.name}")
            frames.append(primary)
        if FMP_CSV_FULL.exists():
            full = pd.read_csv(FMP_CSV_FULL)
            print(f"Loaded {len(full)} rows from {FMP_CSV_FULL.name}")
            frames.append(full)
        if not frames:
            raise FileNotFoundError("No earnings data found (DB or CSV).")
        df = pd.concat(frames, ignore_index=True)

    # Normalize columns
    col_map = {"surprise_pct": "eps_surprise_pct"}
    df.rename(columns={k: v for k, v in col_map.items() if k in df.columns},
              inplace=True)

    df["earnings_date"] = pd.to_datetime(df["earnings_date"]).dt.date
    df["time_of_day"] = df["time_of_day"].str.upper().str.strip()

    # Filter to our tickers
    df = df[df["ticker"].isin(TICKERS)].copy()

    # Deduplicate: prefer rows with EPS data, keep one per (ticker, date)
    df["_has_eps"] = df["eps_actual"].notna().astype(int)
    df.sort_values("_has_eps", ascending=False, inplace=True)
    df.drop_duplicates(subset=["ticker", "earnings_date"], keep="first", inplace=True)
    df.drop(columns=["_has_eps"], inplace=True)

    # Filter only BMO/AMC
    df = df[df["time_of_day"].isin(["BMO", "AMC"])].copy()

    df.sort_values(["ticker", "earnings_date"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


# ---------------------------------------------------------------------------
# 2. Load Daily OHLCV
# ---------------------------------------------------------------------------
def _load_daily_csv(filepath: Path) -> pd.DataFrame | None:
    """Load a daily CSV written by yfinance (multi-level header)."""
    try:
        df = pd.read_csv(filepath, header=[0, 1], index_col=0)
        df.columns = df.columns.get_level_values(0)
        df.index = pd.to_datetime(df.index)
        df.index.name = "Date"
        # Ensure numeric
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df.dropna(subset=["Close"], inplace=True)
        return df
    except Exception:
        return None


def load_daily_ohlcv() -> dict[str, pd.DataFrame]:
    """Load daily OHLCV from local CSVs, fall back to yfinance if needed."""
    price_data = {}
    yf_needed = []

    print(f"\nLoading daily OHLCV for {len(TICKERS)} tickers …")
    for ticker in TICKERS:
        csv_path = DAILY_DIR / f"{ticker}_daily.csv"
        if csv_path.exists():
            df = _load_daily_csv(csv_path)
            if df is not None and not df.empty:
                price_data[ticker] = df
                print(f"  {ticker}: {len(df)} bars ({df.index[0].date()} – {df.index[-1].date()}) [local]")
                continue
        yf_needed.append(ticker)

    # Fallback: try yfinance for missing tickers
    if yf_needed:
        print(f"\n  Attempting yfinance download for {len(yf_needed)} missing tickers: {yf_needed}")
        try:
            import yfinance as yf
            for ticker in yf_needed:
                try:
                    df = yf.download(ticker, start=START_DATE, end=END_DATE,
                                     progress=False, auto_adjust=True)
                    if df.empty:
                        print(f"  {ticker}: no data (yfinance)")
                        continue
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    df.index = pd.to_datetime(df.index).tz_localize(None)
                    price_data[ticker] = df
                    print(f"  {ticker}: {len(df)} bars [yfinance]")
                except Exception as e:
                    print(f"  {ticker}: yfinance failed ({e})")
        except ImportError:
            print("  yfinance not available, skipping missing tickers")

    return price_data


def load_vix() -> pd.Series | None:
    """Load VIX close from local FRED CSV, fall back to yfinance."""
    print("\nLoading VIX …")

    # Try VXVCLS (longer history)
    for csv_path, date_col, val_col in [
        (VIX_CSV, "observation_date", "VXVCLS"),
        (VIX_CSV_ALT, "observation_date", "VIXCLS"),
    ]:
        if csv_path.exists():
            try:
                vdf = pd.read_csv(csv_path)
                vdf[date_col] = pd.to_datetime(vdf[date_col])
                vdf[val_col] = pd.to_numeric(vdf[val_col], errors="coerce")
                vdf.dropna(subset=[val_col], inplace=True)
                vix_close = vdf.set_index(date_col)[val_col]
                vix_close.index.name = "Date"
                print(f"  VIX: {len(vix_close)} bars from {csv_path.name} "
                      f"({vix_close.index[0].date()} – {vix_close.index[-1].date()})")
                return vix_close
            except Exception as e:
                print(f"  Failed to load {csv_path.name}: {e}")

    # Fallback: yfinance
    try:
        import yfinance as yf
        vix = yf.download("^VIX", start=START_DATE, end=END_DATE, progress=False)
        if isinstance(vix.columns, pd.MultiIndex):
            vix.columns = vix.columns.get_level_values(0)
        vix.index = pd.to_datetime(vix.index).tz_localize(None)
        vix_close = vix["Close"].squeeze()
        print(f"  VIX: {len(vix_close)} bars [yfinance]")
        return vix_close
    except Exception as e:
        print(f"  VIX download failed ({e}), proceeding without VIX")
        return None


# ---------------------------------------------------------------------------
# 3. Helper: trading day lookups from actual price index
# ---------------------------------------------------------------------------
def _prior_trading_day(dt, idx):
    """Return the trading day immediately before dt using the price index."""
    mask = idx < pd.Timestamp(dt)
    if mask.any():
        return idx[mask][-1]
    return None


def _next_trading_day(dt, idx):
    """Return the trading day immediately after dt using the price index."""
    mask = idx > pd.Timestamp(dt)
    if mask.any():
        return idx[mask][0]
    return None


def _offset_trading_day(dt, idx, offset):
    """Return the trading day `offset` days after dt (0-based = dt itself)."""
    try:
        pos = idx.get_loc(pd.Timestamp(dt))
    except KeyError:
        return None
    target = pos + offset
    if 0 <= target < len(idx):
        return idx[target]
    return None


# ---------------------------------------------------------------------------
# 4. Build Events Table
# ---------------------------------------------------------------------------
def build_events(earnings_df, price_data, vix_close):
    """Join earnings with price data, compute per-event metrics."""
    rows = []
    skipped = 0

    for _, ev in earnings_df.iterrows():
        ticker = ev["ticker"]
        edate = ev["earnings_date"]
        tod = ev["time_of_day"]

        if ticker not in price_data:
            skipped += 1
            continue

        px = price_data[ticker]
        idx = px.index

        # Determine event_day and prior_close
        edate_ts = pd.Timestamp(edate)

        if tod == "BMO":
            if edate_ts not in idx:
                skipped += 1
                continue
            event_day = edate_ts
            prior_day = _prior_trading_day(edate, idx)
        else:  # AMC
            next_td = _next_trading_day(edate, idx)
            if next_td is None:
                skipped += 1
                continue
            event_day = next_td
            if edate_ts in idx:
                prior_day = edate_ts
            else:
                prior_day = _prior_trading_day(edate, idx)

        if prior_day is None or event_day not in idx:
            skipped += 1
            continue

        prior_close = float(px.loc[prior_day, "Close"])
        event_open = float(px.loc[event_day, "Open"])
        event_close = float(px.loc[event_day, "Close"])
        event_high = float(px.loc[event_day, "High"])
        event_low = float(px.loc[event_day, "Low"])

        if prior_close == 0:
            skipped += 1
            continue

        # Gap percent
        gap_pct = (event_open - prior_close) / prior_close * 100

        # EPS surprise
        eps_est = ev.get("eps_estimated")
        eps_act = ev.get("eps_actual")
        if pd.notna(eps_est) and pd.notna(eps_act) and eps_est != 0:
            eps_surprise_pct = (eps_act - eps_est) / abs(eps_est) * 100
        else:
            eps_surprise_pct = np.nan

        # Revenue surprise
        rev_est = ev.get("revenue_estimated")
        rev_act = ev.get("revenue_actual")
        if pd.notna(rev_est) and pd.notna(rev_act) and rev_est != 0:
            rev_surprise_pct = (rev_act - rev_est) / abs(rev_est) * 100
        else:
            rev_surprise_pct = np.nan

        # First bar holds
        if gap_pct > 0:
            first_bar_holds = event_close > prior_close
        elif gap_pct < 0:
            first_bar_holds = event_close < prior_close
        else:
            first_bar_holds = False

        # First bar strong (closes in strong half of range)
        day_midpoint = (event_high + event_low) / 2
        if gap_pct > 0:
            first_bar_strong = event_close > day_midpoint
        elif gap_pct < 0:
            first_bar_strong = event_close < day_midpoint
        else:
            first_bar_strong = False

        # Drift calculations
        drifts = {}
        for d in [1, 2, 3, 5, 10]:
            close_d = _offset_trading_day(event_day, idx, d)
            if close_d is not None and close_d in idx:
                drifts[f"drift_{d}d"] = (float(px.loc[close_d, "Close"]) - prior_close) / prior_close * 100
            else:
                drifts[f"drift_{d}d"] = np.nan

        # VIX on event day
        vix_val = np.nan
        if vix_close is not None:
            event_day_ts = pd.Timestamp(event_day)
            if event_day_ts in vix_close.index:
                vix_val = float(vix_close.loc[event_day_ts])

        # Gap midpoint
        gap_midpoint = (prior_close + event_open) / 2

        # Direction and year
        direction = "UP" if gap_pct > 0 else ("DOWN" if gap_pct < 0 else "FLAT")
        year = event_day.year if hasattr(event_day, "year") else pd.Timestamp(event_day).year

        rows.append({
            "ticker": ticker,
            "earnings_date": edate,
            "time_of_day": tod,
            "event_day": event_day.date() if hasattr(event_day, "date") else event_day,
            "prior_close": round(prior_close, 4),
            "event_open": round(event_open, 4),
            "event_close": round(event_close, 4),
            "gap_pct": round(gap_pct, 4),
            "eps_surprise_pct": round(eps_surprise_pct, 4) if pd.notna(eps_surprise_pct) else np.nan,
            "rev_surprise_pct": round(rev_surprise_pct, 4) if pd.notna(rev_surprise_pct) else np.nan,
            "first_bar_holds": first_bar_holds,
            "first_bar_strong": first_bar_strong,
            **{k: round(v, 4) if pd.notna(v) else np.nan for k, v in drifts.items()},
            "vix_on_day": round(vix_val, 2) if pd.notna(vix_val) else np.nan,
            "gap_midpoint": round(gap_midpoint, 4),
            "year": year,
            "direction": direction,
        })

    print(f"\nSkipped {skipped} events (missing price data or trading day)")
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 5. Summary
# ---------------------------------------------------------------------------
def print_summary(earnings_df, events_df):
    """Print console summary."""
    print("\n" + "=" * 60)
    print("PEAD Daily Baseline — Data Prep Summary")
    print("=" * 60)
    print(f"Total earnings events in source:  {len(earnings_df)}")
    print(f"Events with price data:           {len(events_df)}")

    if events_df.empty:
        print("No events to summarize.")
        print("=" * 60)
        return

    valid = events_df[events_df["gap_pct"].abs() > 0.1]
    print(f"Events with valid gap (|gap|>0.1%): {len(valid)}")

    print(f"\nEvents per ticker:")
    counts = events_df["ticker"].value_counts().sort_index()
    for t, c in counts.items():
        print(f"  {t:6s}: {c}")

    print(f"\nDate range: {events_df['event_day'].min()} to {events_df['event_day'].max()}")
    g = events_df["gap_pct"]
    print(f"\nGap distribution:")
    print(f"  mean:   {g.mean():.2f}%")
    print(f"  median: {g.median():.2f}%")
    print(f"  p25:    {g.quantile(0.25):.2f}%")
    print(f"  p75:    {g.quantile(0.75):.2f}%")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # 1. Load earnings
    earnings_df = load_earnings()
    print(f"\n{len(earnings_df)} earnings events for {earnings_df['ticker'].nunique()} tickers")

    # 2. Load price data
    price_data = load_daily_ohlcv()
    vix_close = load_vix()

    # 3. Build events table
    events_df = build_events(earnings_df, price_data, vix_close)

    # 4. Print summary
    print_summary(earnings_df, events_df)

    # 5. Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    events_df.to_csv(OUTPUT_CSV, index=False)
    print(f"\nSaved {len(events_df)} events → {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
