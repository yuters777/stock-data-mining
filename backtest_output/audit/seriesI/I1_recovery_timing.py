"""
Series I1: Dead Zone Recovery Timing Analysis.

For each trading day and equity ticker:
1. Find HIGH in Zone 2 (10:00-12:00 ET)
2. Find LOW in Zone 3 / Dead Zone (12:00-13:30 ET)
3. Compute DZ compression = (Z2_high - DZ_low) / Z2_high * 100
4. Filter: compression >= 0.3%
5. Find first bar AFTER DZ_low where price recovers >= 50% of compression
6. Record recovery start time (ET)
7. Histogram + stats by VIX regime
"""

import sys
from pathlib import Path
from datetime import timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ── paths ──
ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "Fetched_Data"
OUT_DIR = Path(__file__).resolve().parent
VIX_PATH = DATA_DIR / "VIXCLS_FRED_real.csv"

# ── tickers (equity only, no crypto) ──
EQUITY_TICKERS = [
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN",
    "COST", "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU",
    "NVDA", "PLTR", "SNOW", "SPY", "TSLA", "TSM", "TXN", "V",
]

# ── IST zone boundaries (data timestamps = ET + 7h) ──
# Zone 2: 10:00-12:00 ET = 17:00-19:00 IST
# Zone 3: 12:00-13:30 ET = 19:00-20:30 IST
Z2_START = 17 * 60  # 17:00
Z2_END = 19 * 60    # 19:00 (exclusive)
Z3_START = 19 * 60  # 19:00
Z3_END = 20 * 60 + 30  # 20:30 (exclusive)

MIN_COMPRESSION_PCT = 0.3


def ist_minutes(dt):
    """Convert datetime to minutes since midnight (IST timestamp)."""
    return dt.hour * 60 + dt.minute


def load_vix():
    """Load VIX daily data."""
    vix = pd.read_csv(VIX_PATH)
    vix.columns = ["date", "vix"]
    vix["date"] = pd.to_datetime(vix["date"]).dt.date
    vix["vix"] = pd.to_numeric(vix["vix"], errors="coerce")
    vix = vix.dropna(subset=["vix"])
    return dict(zip(vix["date"], vix["vix"]))


def vix_regime(vix_val):
    if vix_val is None or np.isnan(vix_val):
        return "unknown"
    if vix_val < 20:
        return "<20"
    elif vix_val < 25:
        return "20-25"
    else:
        return ">=25"


def load_regular_session(ticker):
    """Load M5 data, filter to regular session (16:35-22:55 IST, excluding
    first bar 16:30 and close auction 23:00)."""
    path = DATA_DIR / f"{ticker}_data.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["Datetime"])
    df = df.sort_values("Datetime").reset_index(drop=True)

    # Filter to IST regular session range, exclude duplicated ET section
    mins = df["Datetime"].apply(ist_minutes)
    # Regular session: 16:30-22:55. Exclude first bar (16:30) and close (23:00)
    mask = (mins >= 16 * 60 + 35) & (mins <= 22 * 60 + 55)
    df = df[mask].copy()

    # Assign trading day (IST date = trading day for regular session bars)
    df["trading_day"] = df["Datetime"].dt.date
    # Add ET time for display
    df["et_time"] = df["Datetime"] - timedelta(hours=7)
    df["et_minutes"] = df["et_time"].apply(ist_minutes)

    return df


def analyze_ticker(ticker, vix_map):
    """Analyze DZ recovery timing for one ticker."""
    df = load_regular_session(ticker)
    if df is None or df.empty:
        return []

    results = []
    for day, day_df in df.groupby("trading_day"):
        mins = day_df["Datetime"].apply(ist_minutes)

        # Zone 2 bars
        z2 = day_df[(mins >= Z2_START) & (mins < Z2_END)]
        if z2.empty:
            continue
        z2_high = z2["High"].max()
        z2_high_idx = z2["High"].idxmax()
        z2_high_time = day_df.loc[z2_high_idx, "Datetime"]

        # Zone 3 bars
        z3 = day_df[(mins >= Z3_START) & (mins < Z3_END)]
        if z3.empty:
            continue
        dz_low = z3["Low"].min()
        dz_low_idx = z3["Low"].idxmin()
        dz_low_time = day_df.loc[dz_low_idx, "Datetime"]

        # DZ compression
        if z2_high <= 0:
            continue
        compression_pct = (z2_high - dz_low) / z2_high * 100

        if compression_pct < MIN_COMPRESSION_PCT:
            continue

        # Recovery threshold: DZ_low + 50% of compression
        recovery_threshold = dz_low + 0.5 * (z2_high - dz_low)

        # Find first bar AFTER dz_low_time where High >= recovery_threshold
        after_low = day_df[day_df["Datetime"] > dz_low_time]
        recovery_bar = after_low[after_low["High"] >= recovery_threshold]

        recovery_time_et = None
        recovery_minutes_after_dz_low = None
        if not recovery_bar.empty:
            first_recovery = recovery_bar.iloc[0]
            recovery_time_ist = first_recovery["Datetime"]
            recovery_time_et = recovery_time_ist - timedelta(hours=7)
            recovery_minutes_after_dz_low = (
                (recovery_time_ist - dz_low_time).total_seconds() / 60
            )

        vix_val = vix_map.get(day)
        regime = vix_regime(vix_val)

        results.append({
            "ticker": ticker,
            "trading_day": day,
            "z2_high": z2_high,
            "dz_low": dz_low,
            "compression_pct": compression_pct,
            "dz_low_time_et": (dz_low_time - timedelta(hours=7)).strftime("%H:%M"),
            "recovery_time_et": recovery_time_et.strftime("%H:%M") if recovery_time_et else None,
            "recovery_time_et_hhmm": (
                recovery_time_et.hour * 60 + recovery_time_et.minute
                if recovery_time_et else None
            ),
            "recovery_minutes_after_dz_low": recovery_minutes_after_dz_low,
            "vix": vix_val,
            "vix_regime": regime,
            "recovered": recovery_time_et is not None,
        })

    return results


def main():
    print("Loading VIX data...")
    vix_map = load_vix()
    print(f"  VIX: {len(vix_map)} trading days")

    all_results = []
    for ticker in EQUITY_TICKERS:
        results = analyze_ticker(ticker, vix_map)
        all_results.extend(results)
        if results:
            sig = sum(1 for r in results if r["compression_pct"] >= MIN_COMPRESSION_PCT)
            rec = sum(1 for r in results if r["recovered"])
            print(f"  {ticker}: {sig} significant DZ days, {rec} recovered")

    df = pd.DataFrame(all_results)
    df.to_csv(OUT_DIR / "I1_recovery_timing_data.csv", index=False)

    # ── Stats ──
    n_total = len(df)
    n_recovered = df["recovered"].sum()
    recovered = df[df["recovered"]].copy()

    print(f"\n{'='*60}")
    print(f"I1: Dead Zone Recovery Timing")
    print(f"{'='*60}")
    print(f"Total ticker-days with DZ compression >= {MIN_COMPRESSION_PCT}%: {n_total}")
    print(f"Days with recovery (50% retrace): {n_recovered} ({n_recovered/n_total*100:.1f}%)")

    if recovered.empty:
        print("No recoveries found. Exiting.")
        return

    # Recovery time stats
    median_time = recovered["recovery_time_et_hhmm"].median()
    mean_time = recovered["recovery_time_et_hhmm"].mean()
    median_min_after = recovered["recovery_minutes_after_dz_low"].median()
    mean_min_after = recovered["recovery_minutes_after_dz_low"].mean()

    print(f"\nMedian recovery start time (ET): {int(median_time)//60:02d}:{int(median_time)%60:02d}")
    print(f"Mean recovery start time (ET):   {int(mean_time)//60:02d}:{int(mean_time)%60:02d}")
    print(f"Median minutes after DZ low:     {median_min_after:.0f} min")
    print(f"Mean minutes after DZ low:       {mean_min_after:.0f} min")

    # By VIX regime
    print(f"\n--- Recovery Time by VIX Regime ---")
    for regime in ["<20", "20-25", ">=25"]:
        sub = recovered[recovered["vix_regime"] == regime]
        if sub.empty:
            print(f"  {regime:>5s}: N=0")
            continue
        med = sub["recovery_time_et_hhmm"].median()
        avg = sub["recovery_time_et_hhmm"].mean()
        med_after = sub["recovery_minutes_after_dz_low"].median()
        print(
            f"  {regime:>5s}: N={len(sub):4d}  "
            f"median={int(med)//60:02d}:{int(med)%60:02d}  "
            f"mean={int(avg)//60:02d}:{int(avg)%60:02d}  "
            f"median_min_after_low={med_after:.0f}"
        )

    # ── Plots ──
    # 1. Histogram of recovery start times (ET)
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    ax = axes[0]
    times = recovered["recovery_time_et_hhmm"].values
    bins = np.arange(12*60, 16*60+1, 5)  # 5-min bins from 12:00 to 16:00 ET
    ax.hist(times, bins=bins, color="steelblue", edgecolor="white", alpha=0.85)
    tick_positions = np.arange(12*60, 16*60+1, 30)
    tick_labels = [f"{m//60:02d}:{m%60:02d}" for m in tick_positions]
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels, rotation=45, fontsize=8)
    ax.axvline(median_time, color="red", linestyle="--", label=f"Median {int(median_time)//60:02d}:{int(median_time)%60:02d}")
    ax.set_xlabel("Recovery Start Time (ET)")
    ax.set_ylabel("Count")
    ax.set_title(f"I1: DZ Recovery Start Time Distribution (N={len(recovered)})")
    ax.legend()

    # 2. Histogram of minutes after DZ low
    ax = axes[1]
    mins_after = recovered["recovery_minutes_after_dz_low"].values
    ax.hist(mins_after, bins=30, color="darkorange", edgecolor="white", alpha=0.85)
    ax.axvline(median_min_after, color="red", linestyle="--",
               label=f"Median {median_min_after:.0f} min")
    ax.set_xlabel("Minutes After DZ Low")
    ax.set_ylabel("Count")
    ax.set_title("Time From DZ Low to Recovery Start")
    ax.legend()

    plt.tight_layout()
    plt.savefig(OUT_DIR / "I1_recovery_timing_histogram.png", dpi=150)
    plt.close()
    print(f"\nSaved: I1_recovery_timing_histogram.png")

    # 3. By VIX regime boxplot
    fig, ax = plt.subplots(figsize=(8, 5))
    regimes = ["<20", "20-25", ">=25"]
    data_by_regime = [
        recovered[recovered["vix_regime"] == r]["recovery_minutes_after_dz_low"].dropna().values
        for r in regimes
    ]
    # Filter out empty arrays
    valid = [(r, d) for r, d in zip(regimes, data_by_regime) if len(d) > 0]
    if valid:
        bp = ax.boxplot([d for _, d in valid], labels=[r for r, _ in valid], patch_artist=True)
        colors = ["#4CAF50", "#FF9800", "#F44336"]
        for patch, color in zip(bp["boxes"], colors[:len(valid)]):
            patch.set_facecolor(color)
            patch.set_alpha(0.6)
        ax.set_xlabel("VIX Regime")
        ax.set_ylabel("Minutes After DZ Low")
        ax.set_title("Recovery Timing by VIX Regime")
        plt.tight_layout()
        plt.savefig(OUT_DIR / "I1_recovery_by_vix.png", dpi=150)
        plt.close()
        print("Saved: I1_recovery_by_vix.png")


if __name__ == "__main__":
    main()
