"""
Series I6a: Executable Entry Replacement.

Replaces the lookahead DZ_low entry from I5 with 3 executable variants:
  V1: First Green Close (close > open after DZ_low)
  V2: 25% Retrace Reclaim (close > DZ_low + 0.25 * compression)
  V3: Prior Bar High Break (high > prior bar high after DZ_low)

Entry window: bar after DZ_low through 13:30 ET (20:30 IST).
Exit: close at 15:30 ET (22:30 IST).
No trade if trigger doesn't fire by 13:30 ET.
"""

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
I4_DATA = OUT_DIR / "I4_depth_zscore_data.csv"

EQUITY_TICKERS = [
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN",
    "COST", "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU",
    "NVDA", "PLTR", "SNOW", "SPY", "TSLA", "TSM", "TXN", "V",
]

# IST boundaries
Z3_END_IST = 20 * 60 + 30   # 13:30 ET = 20:30 IST
EXIT_IST = 22 * 60 + 30     # 15:30 ET = 22:30 IST


def ist_minutes(dt):
    return dt.hour * 60 + dt.minute


def load_all_m5():
    """Load and cache M5 regular-session data for all tickers, keyed by (ticker, date)."""
    print("Loading M5 data for all tickers...")
    cache = {}
    for ticker in EQUITY_TICKERS:
        path = DATA_DIR / f"{ticker}_data.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, parse_dates=["Datetime"])
        df = df.sort_values("Datetime").reset_index(drop=True)
        mins = df["Datetime"].apply(ist_minutes)
        # Regular session only (exclude first bar 16:30, keep through 22:55)
        mask = (mins >= 16 * 60 + 35) & (mins <= 22 * 60 + 55)
        df = df[mask].copy()
        df["trading_day"] = df["Datetime"].dt.date
        df["ist_min"] = df["Datetime"].apply(ist_minutes)

        for day, day_df in df.groupby("trading_day"):
            cache[(ticker, day)] = day_df.reset_index(drop=True)

    print(f"  Loaded {len(cache):,} ticker-days")
    return cache


def find_dz_low_bar_idx(day_df, dz_low_price):
    """Find the index of the bar that contains the DZ low."""
    # DZ bars: 19:00-20:25 IST (12:00-13:25 ET)
    dz_bars = day_df[(day_df["ist_min"] >= 19 * 60) & (day_df["ist_min"] < 20 * 60 + 30)]
    if dz_bars.empty:
        return None
    # Find bar where Low == dz_low (or closest)
    low_idx = dz_bars["Low"].idxmin()
    return low_idx


def get_exit_price(day_df):
    """Get close at 15:30 ET = 22:30 IST (or nearest prior bar)."""
    candidates = day_df[day_df["ist_min"] <= EXIT_IST]
    if candidates.empty:
        return None
    return candidates.iloc[-1]["Close"]


def find_entry_v1(day_df, dz_low_idx):
    """V1: First Green Close — first bar after DZ_low where close > open."""
    after = day_df.loc[dz_low_idx + 1:]
    # Only within entry window (up to 13:30 ET = 20:30 IST)
    window = after[after["ist_min"] < Z3_END_IST]
    for idx, bar in window.iterrows():
        if bar["Close"] > bar["Open"]:
            return bar["Close"], bar["Datetime"], bar["ist_min"]
    return None, None, None


def find_entry_v2(day_df, dz_low_idx, retrace_level):
    """V2: 25% Retrace Reclaim — first bar after DZ_low where close > retrace level."""
    after = day_df.loc[dz_low_idx + 1:]
    window = after[after["ist_min"] < Z3_END_IST]
    for idx, bar in window.iterrows():
        if bar["Close"] > retrace_level:
            return bar["Close"], bar["Datetime"], bar["ist_min"]
    return None, None, None


def find_entry_v3(day_df, dz_low_idx):
    """V3: Prior Bar High Break — first bar after DZ_low where high > prior bar high."""
    after_start = dz_low_idx + 1
    after = day_df.loc[after_start:]
    window = after[after["ist_min"] < Z3_END_IST]
    for idx, bar in window.iterrows():
        if idx == 0:
            continue
        prior_idx = idx - 1
        if prior_idx not in day_df.index:
            continue
        prior_high = day_df.loc[prior_idx, "High"]
        if bar["High"] > prior_high:
            return bar["Close"], bar["Datetime"], bar["ist_min"]
    return None, None, None


def process_events(i4_df, m5_cache):
    """Process all DZ compression events and find entries for all 3 variants."""
    results = []
    n_total = len(i4_df)

    for row_i, (_, event) in enumerate(i4_df.iterrows()):
        if row_i % 1000 == 0:
            print(f"  Processing event {row_i}/{n_total}...")

        ticker = event["ticker"]
        day = event["trading_day"]
        key = (ticker, day)

        if key not in m5_cache:
            continue

        day_df = m5_cache[key]
        dz_low = event["dz_low"]
        z2_high = event["z2_high"]
        depth_z = event["depth_z"]
        zscore_bucket = event["zscore_bucket"]
        compression_pct = event["compression_pct"]
        compression_bucket = event["compression_bucket"]

        # Find DZ low bar
        dz_low_idx = find_dz_low_bar_idx(day_df, dz_low)
        if dz_low_idx is None:
            continue

        dz_low_time = day_df.loc[dz_low_idx, "Datetime"]
        dz_low_ist_min = day_df.loc[dz_low_idx, "ist_min"]

        # Exit price
        exit_price = get_exit_price(day_df)
        if exit_price is None:
            continue

        # Retrace level for V2
        retrace_level = dz_low + 0.25 * (z2_high - dz_low)

        # V1: First Green Close
        v1_entry, v1_time, v1_ist = find_entry_v1(day_df, dz_low_idx)
        # V2: 25% Retrace Reclaim
        v2_entry, v2_time, v2_ist = find_entry_v2(day_df, dz_low_idx, retrace_level)
        # V3: Prior Bar High Break
        v3_entry, v3_time, v3_ist = find_entry_v3(day_df, dz_low_idx)

        result = {
            "ticker": ticker,
            "trading_day": day,
            "z2_high": z2_high,
            "dz_low": dz_low,
            "dz_low_ist_min": dz_low_ist_min,
            "exit_price": exit_price,
            "depth_z": depth_z,
            "zscore_bucket": zscore_bucket,
            "compression_pct": compression_pct,
            "compression_bucket": compression_bucket,
            # I5 baseline
            "baseline_pl": (exit_price - dz_low) / dz_low * 100,
            # V1
            "v1_entry": v1_entry,
            "v1_ist_min": v1_ist,
            "v1_pl": (exit_price - v1_entry) / v1_entry * 100 if v1_entry else None,
            "v1_win": ((exit_price - v1_entry) / v1_entry * 100 > 0) if v1_entry else None,
            "v1_delay": (v1_ist - dz_low_ist_min) if v1_ist else None,
            # V2
            "v2_entry": v2_entry,
            "v2_ist_min": v2_ist,
            "v2_pl": (exit_price - v2_entry) / v2_entry * 100 if v2_entry else None,
            "v2_win": ((exit_price - v2_entry) / v2_entry * 100 > 0) if v2_entry else None,
            "v2_delay": (v2_ist - dz_low_ist_min) if v2_ist else None,
            # V3
            "v3_entry": v3_entry,
            "v3_ist_min": v3_ist,
            "v3_pl": (exit_price - v3_entry) / v3_entry * 100 if v3_entry else None,
            "v3_win": ((exit_price - v3_entry) / v3_entry * 100 > 0) if v3_entry else None,
            "v3_delay": (v3_ist - dz_low_ist_min) if v3_ist else None,
        }
        results.append(result)

    return pd.DataFrame(results)


def variant_stats(df, pl_col, win_col, delay_col, label):
    """Compute stats for one variant."""
    valid = df.dropna(subset=[pl_col])
    if valid.empty:
        return {"variant": label, "n": 0}
    return {
        "variant": label,
        "n": len(valid),
        "avg_pl": valid[pl_col].mean(),
        "median_pl": valid[pl_col].median(),
        "wr": (valid[pl_col] > 0).mean() * 100,
        "median_delay": valid[delay_col].median() if delay_col in valid else None,
        "trigger_rate": len(valid) / len(df) * 100,
    }


def print_variant_summary(stats_list):
    """Print comparison table of variants."""
    print(f"\n{'Variant':<25s}  {'N':>6s}  {'Trigger%':>8s}  {'Avg PL':>9s}  "
          f"{'Med PL':>9s}  {'WR':>7s}  {'Med Delay':>10s}")
    print("-" * 85)
    for s in stats_list:
        if s["n"] == 0:
            print(f"{s['variant']:<25s}  {'0':>6s}  {'N/A':>8s}")
            continue
        delay_str = f"{s['median_delay']:.0f} min" if s.get("median_delay") is not None else "N/A"
        print(f"{s['variant']:<25s}  {s['n']:>6d}  {s['trigger_rate']:>7.1f}%  "
              f"{s['avg_pl']:>+8.4f}%  {s['median_pl']:>+8.4f}%  "
              f"{s['wr']:>6.1f}%  {delay_str:>10s}")


def print_depth_table(df, pl_col, win_col, bucket_col, title):
    """Print P&L by depth bucket for one variant."""
    valid = df.dropna(subset=[pl_col])
    print(f"\n  {title}")
    if bucket_col == "zscore_bucket":
        buckets = ["<1σ", "1-2σ", ">2σ"]
    else:
        buckets = ["<0.5%", "0.5-1.0%", ">1.0%"]

    print(f"  {'Bucket':>12s}  {'Avg PL':>9s}  {'Med PL':>9s}  {'WR':>7s}  {'N':>6s}")
    for b in buckets:
        sub = valid[valid[bucket_col] == b]
        if sub.empty:
            print(f"  {b:>12s}  {'N/A':>9s}")
            continue
        wr = (sub[pl_col] > 0).mean() * 100
        print(f"  {b:>12s}  {sub[pl_col].mean():>+8.4f}%  {sub[pl_col].median():>+8.4f}%  "
              f"{wr:>6.1f}%  {len(sub):>6d}")


def make_plots(df):
    """Generate I6a comparison plots."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    variants = [
        ("baseline_pl", "I5 Baseline (DZ_low)", "gray"),
        ("v1_pl", "V1: First Green Close", "#4CAF50"),
        ("v2_pl", "V2: 25% Retrace", "#2196F3"),
        ("v3_pl", "V3: Prior Bar High Break", "#FF9800"),
    ]

    # 1. Avg P&L by variant × z-score bucket
    ax = axes[0, 0]
    z_buckets = ["<1σ", "1-2σ", ">2σ"]
    x = np.arange(len(z_buckets))
    width = 0.2
    for i, (col, label, color) in enumerate(variants):
        vals = []
        for b in z_buckets:
            sub = df[df["zscore_bucket"] == b].dropna(subset=[col])
            vals.append(sub[col].mean() if len(sub) > 0 else 0)
        ax.bar(x + i * width - 1.5 * width, vals, width, label=label, color=color, alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(z_buckets)
    ax.set_ylabel("Avg P&L (%)")
    ax.set_title("Avg P&L by Z-Score Bucket")
    ax.legend(fontsize=7)
    ax.axhline(0, color="black", linewidth=0.5)

    # 2. Avg P&L by variant × raw % bucket
    ax = axes[0, 1]
    raw_buckets = ["<0.5%", "0.5-1.0%", ">1.0%"]
    x = np.arange(len(raw_buckets))
    for i, (col, label, color) in enumerate(variants):
        vals = []
        for b in raw_buckets:
            sub = df[df["compression_bucket"] == b].dropna(subset=[col])
            vals.append(sub[col].mean() if len(sub) > 0 else 0)
        ax.bar(x + i * width - 1.5 * width, vals, width, label=label, color=color, alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(raw_buckets)
    ax.set_ylabel("Avg P&L (%)")
    ax.set_title("Avg P&L by Raw % Bucket")
    ax.legend(fontsize=7)
    ax.axhline(0, color="black", linewidth=0.5)

    # 3. Entry delay distribution for best variant (V1)
    ax = axes[1, 0]
    for col, label, color in [("v1_delay", "V1", "#4CAF50"),
                               ("v2_delay", "V2", "#2196F3"),
                               ("v3_delay", "V3", "#FF9800")]:
        valid = df[col].dropna()
        if len(valid) > 0:
            ax.hist(valid, bins=range(0, 100, 5), alpha=0.5, color=color, label=label)
    ax.set_xlabel("Entry Delay After DZ Low (minutes)")
    ax.set_ylabel("Count")
    ax.set_title("Entry Delay Distribution")
    ax.legend()

    # 4. Win rate by variant × z-score bucket
    ax = axes[1, 1]
    z_buckets = ["<1σ", "1-2σ", ">2σ"]
    x = np.arange(len(z_buckets))
    win_cols = [
        ("baseline_pl", "I5 Baseline", "gray"),
        ("v1_pl", "V1", "#4CAF50"),
        ("v2_pl", "V2", "#2196F3"),
        ("v3_pl", "V3", "#FF9800"),
    ]
    for i, (pcol, label, color) in enumerate(win_cols):
        vals = []
        for b in z_buckets:
            sub = df[df["zscore_bucket"] == b].dropna(subset=[pcol])
            if len(sub) > 0:
                vals.append((sub[pcol] > 0).mean() * 100)
            else:
                vals.append(0)
        ax.bar(x + i * width - 1.5 * width, vals, width, label=label, color=color, alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(z_buckets)
    ax.set_ylabel("Win Rate (%)")
    ax.set_title("Win Rate by Z-Score Bucket")
    ax.legend(fontsize=7)
    ax.axhline(50, color="black", linewidth=0.5, linestyle="--")

    plt.suptitle("I6a: Executable Entry Variants vs Baseline", fontsize=14)
    plt.tight_layout()
    plt.savefig(OUT_DIR / "I6a_executable_entry.png", dpi=150)
    plt.close()
    print("\nSaved: I6a_executable_entry.png")


def main():
    # Load I4 data
    i4 = pd.read_csv(I4_DATA)
    i4["trading_day"] = pd.to_datetime(i4["trading_day"]).dt.date
    print(f"Loaded {len(i4)} DZ compression events from I4")

    # Load M5 data
    m5_cache = load_all_m5()

    # Process all events
    print("\nProcessing executable entries...")
    df = process_events(i4, m5_cache)
    df.to_csv(OUT_DIR / "I6a_executable_entry_data.csv", index=False)
    print(f"Processed {len(df)} events")

    # ═══════════════════════════════════════════════════════
    # Overall variant comparison
    # ═══════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("VARIANT COMPARISON")
    print("=" * 70)

    baseline = {
        "variant": "I5 Baseline (DZ_low)",
        "n": len(df),
        "avg_pl": df["baseline_pl"].mean(),
        "median_pl": df["baseline_pl"].median(),
        "wr": (df["baseline_pl"] > 0).mean() * 100,
        "median_delay": 0,
        "trigger_rate": 100.0,
    }
    v1_stats = variant_stats(df, "v1_pl", "v1_win", "v1_delay", "V1: First Green Close")
    v2_stats = variant_stats(df, "v2_pl", "v2_win", "v2_delay", "V2: 25% Retrace Reclaim")
    v3_stats = variant_stats(df, "v3_pl", "v3_win", "v3_delay", "V3: Prior Bar High Break")

    all_stats = [baseline, v1_stats, v2_stats, v3_stats]
    print_variant_summary(all_stats)

    # ═══════════════════════════════════════════════════════
    # Depth analysis for each variant
    # ═══════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("DEPTH ANALYSIS BY VARIANT")
    print("=" * 70)

    for pl_col, win_col, label in [
        ("baseline_pl", None, "I5 Baseline"),
        ("v1_pl", "v1_win", "V1: First Green Close"),
        ("v2_pl", "v2_win", "V2: 25% Retrace Reclaim"),
        ("v3_pl", "v3_win", "V3: Prior Bar High Break"),
    ]:
        if win_col is None:
            # Baseline: derive win from P&L
            df["_tmp_win"] = df[pl_col] > 0
            wc = "_tmp_win"
        else:
            wc = win_col
        print(f"\n--- {label} ---")
        print_depth_table(df, pl_col, wc, "zscore_bucket", "By Z-Score Bucket:")
        print_depth_table(df, pl_col, wc, "compression_bucket", "By Raw % Bucket:")

    # ═══════════════════════════════════════════════════════
    # "Deep = better" test for each variant
    # ═══════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("DEEP = BETTER TEST (z-score)")
    print("=" * 70)

    for pl_col, label in [
        ("baseline_pl", "Baseline"),
        ("v1_pl", "V1"),
        ("v2_pl", "V2"),
        ("v3_pl", "V3"),
    ]:
        valid = df.dropna(subset=[pl_col])
        shallow = valid[valid["zscore_bucket"] == "<1σ"][pl_col].mean()
        deep_data = valid[valid["zscore_bucket"] == ">2σ"]
        deep = deep_data[pl_col].mean() if len(deep_data) > 0 else float("nan")
        direction = "DEEP > SHALLOW" if deep > shallow else "SHALLOW > DEEP"
        diff = deep - shallow
        print(f"  {label:>10s}: shallow={shallow:+.4f}%, deep={deep:+.4f}%, "
              f"Δ={diff:+.4f}% → {direction}")

    print(f"\n{'='*70}")
    print("DEEP = BETTER TEST (raw %)")
    print("=" * 70)

    for pl_col, label in [
        ("baseline_pl", "Baseline"),
        ("v1_pl", "V1"),
        ("v2_pl", "V2"),
        ("v3_pl", "V3"),
    ]:
        valid = df.dropna(subset=[pl_col])
        shallow = valid[valid["compression_bucket"] == "<0.5%"][pl_col].mean()
        deep = valid[valid["compression_bucket"] == ">1.0%"][pl_col].mean()
        direction = "DEEP > SHALLOW" if deep > shallow else "SHALLOW > DEEP"
        diff = deep - shallow
        print(f"  {label:>10s}: shallow={shallow:+.4f}%, deep={deep:+.4f}%, "
              f"Δ={diff:+.4f}% → {direction}")

    # ═══════════════════════════════════════════════════════
    # Entry time analysis
    # ═══════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("ENTRY TIME ANALYSIS")
    print("=" * 70)

    for delay_col, pl_col, label in [
        ("v1_delay", "v1_pl", "V1"),
        ("v2_delay", "v2_pl", "V2"),
        ("v3_delay", "v3_pl", "V3"),
    ]:
        valid = df.dropna(subset=[delay_col])
        if valid.empty:
            continue
        # Convert IST entry time to ET
        entry_times = valid["dz_low_ist_min"] + valid[delay_col] - 7 * 60
        print(f"\n  {label}:")
        print(f"    Median entry time (ET): {int(entry_times.median())//60:02d}:{int(entry_times.median())%60:02d}")
        print(f"    Median delay from DZ low: {valid[delay_col].median():.0f} min")
        print(f"    Mean delay from DZ low: {valid[delay_col].mean():.1f} min")

        # By depth
        for b in ["<1σ", "1-2σ", ">2σ"]:
            sub = valid[valid["zscore_bucket"] == b]
            if len(sub) > 0:
                et = sub["dz_low_ist_min"] + sub[delay_col] - 7 * 60
                print(f"    {b}: median entry {int(et.median())//60:02d}:{int(et.median())%60:02d}, "
                      f"delay {sub[delay_col].median():.0f} min, N={len(sub)}")

    # Plots
    make_plots(df)


if __name__ == "__main__":
    main()
