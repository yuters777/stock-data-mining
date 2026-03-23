"""
Series I3: Volume Recovery & Price Activity Analysis.

Part A (SPY only - reliable volume):
1. Avg volume per M5 bar in Zone 2 vs Zone 3
2. Find first bar in Zone 3/4 where volume >= 1.5x DZ average
3. Histogram of volume recovery times
4. Correlation: volume recovery time vs price recovery time

Part B (All equity tickers - price only):
5. For each M5 bar 12:00-15:00 ET: average |return|
6. Plot: average absolute return per M5 bar across all days
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

EQUITY_TICKERS = [
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN",
    "COST", "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU",
    "NVDA", "PLTR", "SNOW", "SPY", "TSLA", "TSM", "TXN", "V",
]

# IST zone boundaries
Z2_START = 17 * 60
Z2_END = 19 * 60
Z3_START = 19 * 60
Z3_END = 20 * 60 + 30
Z4_START = 20 * 60 + 30
Z4_END = 21 * 60 + 45
# For price activity: 12:00-15:55 ET = 19:00-22:55 IST
ACTIVITY_START = 19 * 60
ACTIVITY_END = 22 * 60 + 55


def ist_minutes(dt):
    return dt.hour * 60 + dt.minute


def load_regular_session(ticker):
    suffix = "_crypto_data.csv" if ticker in ("BTC", "ETH") else "_data.csv"
    path = DATA_DIR / f"{ticker}{'' if suffix == '_data.csv' else ''}"
    path = DATA_DIR / f"{ticker}_data.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["Datetime"])
    df = df.sort_values("Datetime").reset_index(drop=True)
    mins = df["Datetime"].apply(ist_minutes)
    mask = (mins >= 16 * 60 + 35) & (mins <= 22 * 60 + 55)
    df = df[mask].copy()
    df["trading_day"] = df["Datetime"].dt.date
    df["ist_min"] = df["Datetime"].apply(ist_minutes)
    return df


def part_a_spy_volume():
    """SPY volume analysis - find when volume returns after Dead Zone."""
    print("\n--- Part A: SPY Volume Recovery ---")
    df = load_regular_session("SPY")
    if df is None or df.empty:
        print("  SPY data not found!")
        return None

    results = []
    for day, day_df in df.groupby("trading_day"):
        # Zone 2 volume
        z2 = day_df[(day_df["ist_min"] >= Z2_START) & (day_df["ist_min"] < Z2_END)]
        z3 = day_df[(day_df["ist_min"] >= Z3_START) & (day_df["ist_min"] < Z3_END)]

        if z2.empty or z3.empty:
            continue

        z2_avg_vol = z2["Volume"].mean()
        z3_avg_vol = z3["Volume"].mean()
        vol_ratio = z3_avg_vol / z2_avg_vol if z2_avg_vol > 0 else 0

        # Find first bar in Z3/Z4 where volume >= 1.5x DZ average
        z3z4 = day_df[
            (day_df["ist_min"] >= Z3_START) & (day_df["ist_min"] < Z4_END)
        ]
        threshold = 1.5 * z3_avg_vol
        vol_recovery = z3z4[z3z4["Volume"] >= threshold]

        vol_recovery_time_et = None
        vol_recovery_minutes = None
        if not vol_recovery.empty:
            first_bar = vol_recovery.iloc[0]
            vol_recovery_time_ist = first_bar["Datetime"]
            vol_recovery_time_et = (vol_recovery_time_ist - timedelta(hours=7))
            vol_recovery_minutes = vol_recovery_time_et.hour * 60 + vol_recovery_time_et.minute

        results.append({
            "trading_day": day,
            "z2_avg_vol": z2_avg_vol,
            "z3_avg_vol": z3_avg_vol,
            "vol_ratio_z3_z2": vol_ratio,
            "vol_recovery_time_et": (
                vol_recovery_time_et.strftime("%H:%M") if vol_recovery_time_et else None
            ),
            "vol_recovery_minutes_et": vol_recovery_minutes,
        })

    spy_df = pd.DataFrame(results)
    spy_df.to_csv(OUT_DIR / "I3_spy_volume_data.csv", index=False)

    n_total = len(spy_df)
    n_recovered = spy_df["vol_recovery_minutes_et"].notna().sum()
    print(f"  SPY trading days: {n_total}")
    print(f"  Days with volume recovery: {n_recovered}")
    print(f"  Mean Z3/Z2 volume ratio: {spy_df['vol_ratio_z3_z2'].mean():.2f}")

    recovered = spy_df.dropna(subset=["vol_recovery_minutes_et"])
    if not recovered.empty:
        med = recovered["vol_recovery_minutes_et"].median()
        avg = recovered["vol_recovery_minutes_et"].mean()
        print(f"  Median volume recovery time (ET): {int(med)//60:02d}:{int(med)%60:02d}")
        print(f"  Mean volume recovery time (ET):   {int(avg)//60:02d}:{int(avg)%60:02d}")

    return spy_df


def part_b_price_activity():
    """Average absolute return per M5 bar for all equity tickers, 12:00-15:55 ET."""
    print("\n--- Part B: Price Activity (All Equity Tickers) ---")

    all_bars = []
    for ticker in EQUITY_TICKERS:
        df = load_regular_session(ticker)
        if df is None or df.empty:
            continue

        # Filter to 12:00-15:55 ET = 19:00-22:55 IST
        sub = df[(df["ist_min"] >= ACTIVITY_START) & (df["ist_min"] <= ACTIVITY_END)].copy()
        if sub.empty:
            continue

        # Compute bar return (close-to-close within day)
        sub = sub.sort_values("Datetime")
        sub["abs_return"] = (sub["Close"] / sub["Open"] - 1).abs() * 100

        # Convert to ET minutes for grouping
        sub["et_min"] = sub["ist_min"] - 7 * 60

        for _, row in sub.iterrows():
            all_bars.append({
                "ticker": ticker,
                "trading_day": row["trading_day"],
                "et_min": row["et_min"],
                "abs_return": row["abs_return"],
            })

    bars_df = pd.DataFrame(all_bars)

    # Average absolute return per ET minute across all tickers and days
    avg_by_time = bars_df.groupby("et_min")["abs_return"].agg(["mean", "median", "count"])
    avg_by_time = avg_by_time.reset_index()

    return bars_df, avg_by_time


def main():
    # Part A: SPY volume
    spy_df = part_a_spy_volume()

    # Part B: Price activity
    bars_df, avg_by_time = part_b_price_activity()

    print(f"\n  Bars analyzed: {len(bars_df):,}")
    print(f"  Time slots: {len(avg_by_time)}")

    # ── Plots ──
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # 1. SPY volume recovery histogram
    if spy_df is not None:
        ax = axes[0, 0]
        recovered = spy_df.dropna(subset=["vol_recovery_minutes_et"])
        if not recovered.empty:
            times = recovered["vol_recovery_minutes_et"].values
            bins = np.arange(12*60, 15*60+1, 5)
            ax.hist(times, bins=bins, color="steelblue", edgecolor="white", alpha=0.85)
            med = np.median(times)
            ax.axvline(med, color="red", linestyle="--",
                       label=f"Median {int(med)//60:02d}:{int(med)%60:02d}")
            tick_pos = np.arange(12*60, 15*60+1, 15)
            ax.set_xticks(tick_pos)
            ax.set_xticklabels([f"{m//60:02d}:{m%60:02d}" for m in tick_pos],
                               rotation=45, fontsize=8)
            ax.set_xlabel("Volume Recovery Time (ET)")
            ax.set_ylabel("Count")
            ax.set_title(f"SPY: Volume Recovery Timing (N={len(recovered)})")
            ax.legend()

    # 2. SPY Z2 vs Z3 volume ratio distribution
    if spy_df is not None:
        ax = axes[0, 1]
        ax.hist(spy_df["vol_ratio_z3_z2"], bins=30, color="darkorange",
                edgecolor="white", alpha=0.85)
        ax.axvline(spy_df["vol_ratio_z3_z2"].median(), color="red", linestyle="--",
                   label=f"Median {spy_df['vol_ratio_z3_z2'].median():.2f}")
        ax.set_xlabel("Z3/Z2 Volume Ratio")
        ax.set_ylabel("Count")
        ax.set_title("SPY: Dead Zone Volume Compression Ratio")
        ax.legend()

    # 3. Average absolute return by ET time
    ax = axes[1, 0]
    et_mins = avg_by_time["et_min"].values
    ax.bar(range(len(et_mins)), avg_by_time["mean"].values * 100,
           color="purple", alpha=0.7, width=0.8)
    # Label every 6th bar (30 minutes)
    step = 6
    ax.set_xticks(range(0, len(et_mins), step))
    ax.set_xticklabels(
        [f"{int(et_mins[i])//60:02d}:{int(et_mins[i])%60:02d}"
         for i in range(0, len(et_mins), step)],
        rotation=45, fontsize=8
    )
    # Mark zone boundaries
    for zone_et, label, color in [
        (12*60, "DZ Start", "red"), (13*60+30, "Zone 4", "orange"),
        (14*60+45, "Power Hour", "green")
    ]:
        for j, m in enumerate(et_mins):
            if m == zone_et:
                ax.axvline(j, color=color, linestyle="--", alpha=0.7, label=label)
                break
    ax.set_xlabel("Time (ET)")
    ax.set_ylabel("Mean |Return| (bps)")
    ax.set_title("When Does the Market Wake Up? (All Equity Tickers)")
    ax.legend(fontsize=8)

    # 4. Correlation: volume recovery vs price recovery (SPY only)
    ax = axes[1, 1]
    # Load I1 data for SPY
    i1_path = OUT_DIR / "I1_recovery_timing_data.csv"
    if i1_path.exists() and spy_df is not None:
        i1_df = pd.read_csv(i1_path)
        i1_spy = i1_df[i1_df["ticker"] == "SPY"].copy()
        i1_spy["trading_day"] = pd.to_datetime(i1_spy["trading_day"]).dt.date

        # Merge with SPY volume data
        spy_merge = spy_df.copy()
        merged = pd.merge(
            i1_spy[["trading_day", "recovery_time_et_hhmm"]].dropna(),
            spy_merge[["trading_day", "vol_recovery_minutes_et"]].dropna(),
            on="trading_day",
            how="inner"
        )
        if not merged.empty:
            ax.scatter(
                merged["recovery_time_et_hhmm"],
                merged["vol_recovery_minutes_et"],
                alpha=0.5, s=20, c="steelblue"
            )
            # Correlation
            corr = merged["recovery_time_et_hhmm"].corr(
                merged["vol_recovery_minutes_et"]
            )
            ax.set_xlabel("Price Recovery Time (ET min)")
            ax.set_ylabel("Volume Recovery Time (ET min)")
            ax.set_title(f"SPY: Price vs Volume Recovery (r={corr:.2f}, N={len(merged)})")

            tick_pos = np.arange(12*60, 16*60+1, 30)
            tick_labels = [f"{m//60:02d}:{m%60:02d}" for m in tick_pos]
            ax.set_xticks(tick_pos)
            ax.set_xticklabels(tick_labels, rotation=45, fontsize=8)
            ax.set_yticks(tick_pos)
            ax.set_yticklabels(tick_labels, fontsize=8)
        else:
            ax.text(0.5, 0.5, "No overlapping data", ha="center", va="center",
                    transform=ax.transAxes)
    else:
        ax.text(0.5, 0.5, "Run I1 first for price recovery data",
                ha="center", va="center", transform=ax.transAxes)

    plt.suptitle("I3: Volume & Activity Recovery Analysis", fontsize=13)
    plt.tight_layout()
    plt.savefig(OUT_DIR / "I3_volume_activity.png", dpi=150)
    plt.close()
    print(f"\nSaved: I3_volume_activity.png")

    # Save average activity data
    avg_by_time.to_csv(OUT_DIR / "I3_activity_by_time.csv", index=False)
    print("Saved: I3_activity_by_time.csv")


if __name__ == "__main__":
    main()
