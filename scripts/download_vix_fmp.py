#!/usr/bin/env python3
"""
Download full 5yr VIX daily data from FMP API and backfill into
EMA cross falsification study outputs.

Creates:
  Fetched_Data/VIX_daily_fmp_full.csv   — full 5yr VIX daily OHLCV
  Fetched_Data/VIX_prior_day_close.csv  — prior-day close lookup

Updates:
  results/ema_cross_falsification/ema_cross_events.csv  — VIX backfilled
  results/ema_cross_falsification/all_4h_bars.parquet   — VIX backfilled

Fallback: If FMP API is unreachable, builds VIX series from local files
(VIXCLS_FRED_real.csv + VXVCLS.csv with overlap-based scaling).
"""

import os
import sys
import json
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "Fetched_Data")
RESULTS = os.path.join(BASE, "results", "ema_cross_falsification")

FMP_API_KEY = "PRAtaveLKuyLOcdMUOMwg2aTvqSg2ab3"


# ── Step 1: Download / Load VIX ──────────────────────────────────────────────

def download_vix_fmp():
    """Try downloading VIX daily OHLCV from FMP. Returns DataFrame or None."""
    try:
        import requests
    except ImportError:
        print("  requests not installed, skipping FMP download")
        return None

    url = (
        f"https://financialmodelingprep.com/api/v3/historical-price-full/"
        f"%5EVIX?from=2021-01-01&to=2026-04-13&apikey={FMP_API_KEY}"
    )

    print("Downloading VIX daily data from FMP...")
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  FMP download failed: {e}")
        return None

    if "historical" not in data:
        print(f"  Unexpected API response: {list(data.keys())}")
        return None

    records = data["historical"]
    vix_df = pd.DataFrame(records)
    vix_df["date"] = pd.to_datetime(vix_df["date"])
    vix_df = vix_df.sort_values("date").reset_index(drop=True)

    # Save full OHLCV
    out_path = os.path.join(DATA, "VIX_daily_fmp_full.csv")
    vix_df.to_csv(out_path, index=False)
    print(f"  Saved FMP data to: {out_path}")

    return vix_df


def load_vix_local():
    """
    Build VIX daily series from local files.

    VIXCLS_FRED_real.csv = true VIX (CBOE 30-day), short range (~1yr)
    VXVCLS.csv           = CBOE 3-month vol index, full 5yr range

    Strategy: use FRED (VIXCLS) where available, scale VXVCLS to match
    VIXCLS on overlapping dates, then fill gaps with scaled VXVCLS.
    """
    print("Building VIX series from local files (FRED + VXVCLS)...")

    # Load FRED VIXCLS
    fred_path = os.path.join(DATA, "VIXCLS_FRED_real.csv")
    fred = None
    if os.path.exists(fred_path):
        df = pd.read_csv(fred_path)
        df.columns = ["date", "vix"]
        df = df[df["vix"] != "."]
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["vix"] = pd.to_numeric(df["vix"], errors="coerce")
        df = df.dropna().set_index("date")["vix"].sort_index()
        if not df.empty:
            fred = df
            print(f"  FRED VIXCLS: {len(fred)} rows, "
                  f"{fred.index.min().date()} to {fred.index.max().date()}")

    # Load VXVCLS
    vx_path = os.path.join(DATA, "VXVCLS.csv")
    vxvcls = None
    if os.path.exists(vx_path):
        df = pd.read_csv(vx_path)
        df.columns = ["date", "vix"]
        df = df[df["vix"] != "."]
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["vix"] = pd.to_numeric(df["vix"], errors="coerce")
        df = df.dropna().set_index("date")["vix"].sort_index()
        if not df.empty:
            vxvcls = df
            print(f"  VXVCLS:      {len(vxvcls)} rows, "
                  f"{vxvcls.index.min().date()} to {vxvcls.index.max().date()}")

    if fred is None and vxvcls is None:
        raise FileNotFoundError("No local VIX data files found")

    if fred is None:
        # Only VXVCLS available — use as-is (no scaling possible)
        print("  WARNING: No FRED data for scaling. Using VXVCLS raw values.")
        combined = vxvcls
        source_label = "VXVCLS_raw"
    elif vxvcls is None:
        # Only FRED available
        combined = fred
        source_label = "FRED_only"
    else:
        # Both available: compute scaling factor from overlap
        overlap_dates = fred.index.intersection(vxvcls.index)
        if len(overlap_dates) >= 10:
            # Linear scaling: VIXCLS ≈ a * VXVCLS + b
            # Simpler: use ratio-based scaling (multiplicative)
            fred_vals = fred.loc[overlap_dates]
            vx_vals = vxvcls.loc[overlap_dates]
            scale_factor = (fred_vals / vx_vals).median()
            print(f"  Overlap: {len(overlap_dates)} dates, "
                  f"scale factor (VIXCLS/VXVCLS median): {scale_factor:.4f}")

            # Scale VXVCLS to approximate VIXCLS
            vxvcls_scaled = vxvcls * scale_factor
        else:
            print(f"  WARNING: Only {len(overlap_dates)} overlap dates. "
                  f"Using VXVCLS raw.")
            vxvcls_scaled = vxvcls

        # Combine: FRED where available, scaled VXVCLS elsewhere
        combined = fred.copy()
        missing_dates = vxvcls_scaled.index.difference(fred.index)
        combined = pd.concat([combined, vxvcls_scaled.loc[missing_dates]])
        combined = combined.sort_index()
        source_label = "FRED+VXVCLS_scaled"

    print(f"  Combined: {len(combined)} rows, "
          f"{combined.index.min().date()} to {combined.index.max().date()}")

    # Convert to DataFrame format matching FMP output
    vix_df = pd.DataFrame({
        "date": combined.index,
        "close": combined.values,
    }).reset_index(drop=True)
    vix_df["source"] = source_label

    # Save
    out_path = os.path.join(DATA, "VIX_daily_fmp_full.csv")
    vix_df.to_csv(out_path, index=False)
    print(f"  Saved to: {out_path}")

    return vix_df


def get_vix_data():
    """Get VIX data: try FMP first, fall back to local files."""
    vix_df = download_vix_fmp()
    if vix_df is not None and len(vix_df) > 100:
        source = "FMP API"
    else:
        vix_df = load_vix_local()
        source = "local files"

    vix_df["date"] = pd.to_datetime(vix_df["date"])
    vix_df = vix_df.sort_values("date").reset_index(drop=True)

    print(f"\nStep 1 complete: VIX data from {source}")
    print(f"  Rows:       {len(vix_df)}")
    print(f"  Date range: {vix_df['date'].min().date()} to {vix_df['date'].max().date()}")
    print(f"  Close range: {vix_df['close'].min():.2f} to {vix_df['close'].max():.2f}")

    return vix_df


# ── Step 2: Prior-day lookup ─────────────────────────────────────────────────

def build_prior_day_lookup(vix_df):
    """Build prior-trading-day VIX close lookup."""
    vix_sorted = vix_df[["date", "close"]].sort_values("date").reset_index(drop=True)

    # Prior-day close: shift so each row's value is yesterday's close
    vix_sorted["vix_prior_close"] = vix_sorted["close"].shift(1)
    vix_lookup = vix_sorted[["date", "vix_prior_close"]].dropna().copy()
    vix_lookup["date"] = vix_lookup["date"].dt.strftime("%Y-%m-%d")

    out_path = os.path.join(DATA, "VIX_prior_day_close.csv")
    vix_lookup.to_csv(out_path, index=False)

    print(f"\nStep 2: Prior-day VIX lookup built")
    print(f"  Rows:     {len(vix_lookup)}")
    print(f"  Saved to: {out_path}")

    return vix_lookup


# ── Step 3: Backfill cross events ────────────────────────────────────────────

def backfill_cross_events(vix_lookup):
    """Backfill VIX into cross events CSV."""
    events_path = os.path.join(RESULTS, "ema_cross_events.csv")
    if not os.path.exists(events_path):
        print(f"\nSkipping cross events backfill: {events_path} not found")
        return

    events = pd.read_csv(events_path)
    nan_before = events["vix_prior_close"].isna().sum()
    print(f"\nStep 3: Backfill VIX into cross events")
    print(f"  Total events:         {len(events)}")
    print(f"  Missing VIX (before): {nan_before}")

    # Normalize event dates for merge
    events["date_str"] = pd.to_datetime(events["date"]).dt.strftime("%Y-%m-%d")

    # Merge with VIX lookup
    events = events.merge(
        vix_lookup.rename(columns={"vix_prior_close": "vix_fmp"}),
        left_on="date_str", right_on="date", how="left", suffixes=("", "_fmp")
    )

    # Fill: use new VIX where existing was NaN
    mask = events["vix_prior_close"].isna() & events["vix_fmp"].notna()
    events.loc[mask, "vix_prior_close"] = events.loc[mask, "vix_fmp"]

    # Round the backfilled values
    events["vix_prior_close"] = events["vix_prior_close"].round(2)

    # Drop temp columns
    events = events.drop(columns=["date_str", "date_fmp", "vix_fmp"], errors="ignore")

    # Save
    events.to_csv(events_path, index=False)

    nan_after = events["vix_prior_close"].isna().sum()
    print(f"  Backfilled:           {mask.sum()} events")
    print(f"  Missing VIX (after):  {nan_after}")

    # VIX distribution of UP crosses
    up = events[events["direction"] == "UP"]
    vix_up = up["vix_prior_close"]
    print(f"\n  VIX distribution of UP crosses ({len(up)} total):")
    print(f"    NORMAL    (VIX<20):  {(vix_up < 20).sum()}")
    print(f"    ELEVATED  (20-25):   {((vix_up >= 20) & (vix_up < 25)).sum()}")
    print(f"    HIGH_RISK (>=25):    {(vix_up >= 25).sum()}")
    print(f"    Missing:             {vix_up.isna().sum()}")

    # VIX distribution of DOWN crosses
    dn = events[events["direction"] == "DOWN"]
    vix_dn = dn["vix_prior_close"]
    print(f"\n  VIX distribution of DOWN crosses ({len(dn)} total):")
    print(f"    NORMAL    (VIX<20):  {(vix_dn < 20).sum()}")
    print(f"    ELEVATED  (20-25):   {((vix_dn >= 20) & (vix_dn < 25)).sum()}")
    print(f"    HIGH_RISK (>=25):    {(vix_dn >= 25).sum()}")
    print(f"    Missing:             {vix_dn.isna().sum()}")


# ── Step 4: Backfill 4H bars ─────────────────────────────────────────────────

def backfill_4h_bars(vix_lookup):
    """Backfill VIX into 4H bars parquet."""
    bars_path = os.path.join(RESULTS, "all_4h_bars.parquet")
    if not os.path.exists(bars_path):
        print(f"\nSkipping 4H bars backfill: {bars_path} not found")
        return

    bars = pd.read_parquet(bars_path)
    nan_before = bars["vix_prior_close"].isna().sum()
    print(f"\nStep 4: Backfill VIX into 4H bars")
    print(f"  Total bars:           {len(bars)}")
    print(f"  Missing VIX (before): {nan_before}")

    # Normalize dates for merge
    bars["date_str"] = pd.to_datetime(bars["date"].astype(str)).dt.strftime("%Y-%m-%d")

    bars = bars.merge(
        vix_lookup.rename(columns={"vix_prior_close": "vix_fmp"}),
        left_on="date_str", right_on="date", how="left", suffixes=("", "_fmp")
    )

    mask = bars["vix_prior_close"].isna() & bars["vix_fmp"].notna()
    bars.loc[mask, "vix_prior_close"] = bars.loc[mask, "vix_fmp"]

    # Drop temp columns
    bars = bars.drop(columns=["date_str", "date_fmp", "vix_fmp"], errors="ignore")

    bars.to_parquet(bars_path, index=False)

    nan_after = bars["vix_prior_close"].isna().sum()
    print(f"  Backfilled:           {mask.sum()} bars")
    print(f"  Missing VIX (after):  {nan_after}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("VIX Daily Data Download + Backfill")
    print("=" * 60)

    # Step 1: Get VIX data (FMP or local fallback)
    vix_df = get_vix_data()

    # Step 2: Build prior-day lookup
    vix_lookup = build_prior_day_lookup(vix_df)

    # Step 3: Backfill cross events
    backfill_cross_events(vix_lookup)

    # Step 4: Backfill 4H bars
    backfill_4h_bars(vix_lookup)

    print("\n" + "=" * 60)
    print("Done.")
    print("=" * 60)


if __name__ == "__main__":
    main()
