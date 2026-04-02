"""
Series I6b + I6c: Path Risk (MAE/MFE) and Per-Ticker Stability.

Uses V1 (First Green Close) from I6a as the executable entry.
Computes MAE/MFE from raw M5 bars between entry and 15:30 ET exit.
Tests per-ticker stability of "deep = better" gradient.
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ── paths ──
ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "Fetched_Data"
OUT_DIR = Path(__file__).resolve().parent
I6A_DATA = OUT_DIR / "I6a_executable_entry_data.csv"

EQUITY_TICKERS = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU", "C",
    "COIN", "COST", "GOOGL", "GS", "INTC", "JPM", "MARA", "META", "MSFT",
    "MSTR", "MU", "NVDA", "PLTR", "SMCI", "SPY", "TSLA", "TSM", "V",
]

EXIT_IST = 22 * 60 + 30  # 15:30 ET = 22:30 IST


def ist_minutes(dt):
    return dt.hour * 60 + dt.minute


def load_all_m5():
    """Load M5 regular-session data keyed by (ticker, date)."""
    print("Loading M5 data...")
    cache = {}
    for ticker in EQUITY_TICKERS:
        path = DATA_DIR / f"{ticker}_data.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, parse_dates=["Datetime"])
        df = df.sort_values("Datetime").reset_index(drop=True)
        mins = df["Datetime"].apply(ist_minutes)
        mask = (mins >= 16 * 60 + 35) & (mins <= 22 * 60 + 55)
        df = df[mask].copy()
        df["trading_day"] = df["Datetime"].dt.date
        df["ist_min"] = df["Datetime"].apply(ist_minutes)
        for day, day_df in df.groupby("trading_day"):
            cache[(ticker, day)] = day_df.reset_index(drop=True)
    print(f"  Loaded {len(cache):,} ticker-days")
    return cache


def compute_mae_mfe(m5_cache, i6a_df):
    """For each V1 trade, compute MAE and MFE from entry bar to 15:30 ET."""
    print("Computing MAE/MFE for V1 trades...")
    v1_trades = i6a_df.dropna(subset=["v1_entry"]).copy()

    mae_list, mfe_list = [], []
    for _, row in v1_trades.iterrows():
        key = (row["ticker"], row["trading_day"])
        if key not in m5_cache:
            mae_list.append(np.nan)
            mfe_list.append(np.nan)
            continue

        day_df = m5_cache[key]
        entry_price = row["v1_entry"]
        entry_ist = row["v1_ist_min"]

        # Bars from entry to exit (15:30 ET = 22:30 IST)
        path_bars = day_df[(day_df["ist_min"] >= entry_ist) & (day_df["ist_min"] <= EXIT_IST)]

        if path_bars.empty:
            mae_list.append(np.nan)
            mfe_list.append(np.nan)
            continue

        lowest_low = path_bars["Low"].min()
        highest_high = path_bars["High"].max()

        mae = (lowest_low - entry_price) / entry_price * 100  # negative = drawdown
        mfe = (highest_high - entry_price) / entry_price * 100  # positive = unrealized gain

        mae_list.append(mae)
        mfe_list.append(mfe)

    v1_trades["mae"] = mae_list
    v1_trades["mfe"] = mfe_list
    v1_trades = v1_trades.dropna(subset=["mae", "mfe"])
    print(f"  Computed MAE/MFE for {len(v1_trades)} trades")
    return v1_trades


# ═══════════════════════════════════════════════════════════
# I6b: MAE/MFE Analysis
# ═══════════════════════════════════════════════════════════

def run_i6b(trades):
    """MAE/MFE by depth bucket."""
    print(f"\n{'='*70}")
    print("I6b: MAE / MFE by Depth Bucket")
    print("=" * 70)

    z_buckets = ["<1σ", "1-2σ", ">2σ"]

    print(f"\n{'Bucket':>8s}  {'Avg MAE':>9s}  {'Med MAE':>9s}  {'Worst MAE':>10s}  "
          f"{'Avg MFE':>9s}  {'Med MFE':>9s}  {'MFE/|MAE|':>10s}  "
          f"{'%MAE>0.5':>9s}  {'%MAE>1.0':>9s}  {'N':>6s}")
    print("-" * 110)

    rows = []
    for b in z_buckets:
        sub = trades[trades["zscore_bucket"] == b]
        if sub.empty:
            continue
        avg_mae = sub["mae"].mean()
        med_mae = sub["mae"].median()
        worst_mae = sub["mae"].min()
        avg_mfe = sub["mfe"].mean()
        med_mfe = sub["mfe"].median()
        ratio = avg_mfe / abs(avg_mae) if avg_mae != 0 else float("inf")
        pct_05 = (sub["mae"] < -0.5).mean() * 100
        pct_10 = (sub["mae"] < -1.0).mean() * 100

        print(f"{b:>8s}  {avg_mae:>+8.3f}%  {med_mae:>+8.3f}%  {worst_mae:>+9.3f}%  "
              f"{avg_mfe:>+8.3f}%  {med_mfe:>+8.3f}%  {ratio:>10.2f}  "
              f"{pct_05:>8.1f}%  {pct_10:>8.1f}%  {len(sub):>6d}")

        rows.append({
            "bucket": b, "avg_mae": avg_mae, "med_mae": med_mae,
            "worst_mae": worst_mae, "avg_mfe": avg_mfe, "med_mfe": med_mfe,
            "mfe_mae_ratio": ratio, "pct_mae_05": pct_05, "pct_mae_10": pct_10,
            "n": len(sub),
        })

    # Also by raw %
    print(f"\n  By Raw % Bucket:")
    print(f"  {'Bucket':>12s}  {'Avg MAE':>9s}  {'Med MAE':>9s}  {'Avg MFE':>9s}  "
          f"{'MFE/|MAE|':>10s}  {'%MAE>0.5':>9s}  {'N':>6s}")
    for b in ["<0.5%", "0.5-1.0%", ">1.0%"]:
        sub = trades[trades["compression_bucket"] == b]
        if sub.empty:
            continue
        avg_mae = sub["mae"].mean()
        med_mae = sub["mae"].median()
        avg_mfe = sub["mfe"].mean()
        ratio = avg_mfe / abs(avg_mae) if avg_mae != 0 else float("inf")
        pct_05 = (sub["mae"] < -0.5).mean() * 100
        print(f"  {b:>12s}  {avg_mae:>+8.3f}%  {med_mae:>+8.3f}%  {avg_mfe:>+8.3f}%  "
              f"{ratio:>10.2f}  {pct_05:>8.1f}%  {len(sub):>6d}")

    # Avg P&L reminder
    print(f"\n  Avg P&L by z-score bucket (V1):")
    for b in z_buckets:
        sub = trades[trades["zscore_bucket"] == b]
        if len(sub) > 0:
            print(f"    {b}: avg P&L = {sub['v1_pl'].mean():+.4f}%, "
                  f"WR = {(sub['v1_pl'] > 0).mean()*100:.1f}%")

    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════
# I6c: Per-Ticker Stability
# ═══════════════════════════════════════════════════════════

def run_i6c(trades):
    """Per-ticker stability of 'deep = better'."""
    print(f"\n{'='*70}")
    print("I6c: Per-Ticker Stability")
    print("=" * 70)

    # Use >1σ as "deep" (combining 1-2σ and >2σ) for sufficient N
    trades = trades.copy()
    trades["depth_binary"] = np.where(trades["depth_z"] >= 1.0, "deep (>=1σ)", "shallow (<1σ)")

    results = []
    print(f"\n{'Ticker':>6s}  {'Shallow PL':>11s}  {'Sh WR':>7s}  {'Sh N':>5s}  "
          f"{'Deep PL':>9s}  {'Dp WR':>7s}  {'Dp N':>5s}  {'Delta':>8s}  {'Category':>14s}")
    print("-" * 95)

    for ticker in EQUITY_TICKERS:
        sub = trades[trades["ticker"] == ticker]
        shallow = sub[sub["depth_binary"] == "shallow (<1σ)"]
        deep = sub[sub["depth_binary"] == "deep (>=1σ)"]

        sh_pl = shallow["v1_pl"].mean() if len(shallow) > 0 else np.nan
        sh_wr = (shallow["v1_pl"] > 0).mean() * 100 if len(shallow) > 0 else np.nan
        dp_pl = deep["v1_pl"].mean() if len(deep) > 0 else np.nan
        dp_wr = (deep["v1_pl"] > 0).mean() * 100 if len(deep) > 0 else np.nan

        delta = dp_pl - sh_pl if not (np.isnan(dp_pl) or np.isnan(sh_pl)) else np.nan

        if np.isnan(delta):
            cat = "insufficient"
        elif delta > 0.2:
            cat = "deep-friendly"
        elif delta < -0.2:
            cat = "deep-hostile"
        else:
            cat = "flat"

        print(f"{ticker:>6s}  {sh_pl:>+10.4f}%  {sh_wr:>6.1f}%  {len(shallow):>5d}  "
              f"{dp_pl:>+8.4f}%  {dp_wr:>6.1f}%  {len(deep):>5d}  "
              f"{delta:>+7.3f}%  {cat:>14s}")

        results.append({
            "ticker": ticker,
            "shallow_pl": sh_pl, "shallow_wr": sh_wr, "shallow_n": len(shallow),
            "deep_pl": dp_pl, "deep_wr": dp_wr, "deep_n": len(deep),
            "delta": delta, "category": cat,
        })

    res_df = pd.DataFrame(results)

    # Summary
    cats = res_df["category"].value_counts()
    print(f"\n  Summary:")
    for c in ["deep-friendly", "flat", "deep-hostile", "insufficient"]:
        print(f"    {c}: {cats.get(c, 0)} tickers")

    # Beta proxy: use noon_sigma from I4 as volatility proxy
    sigma_path = OUT_DIR / "I4_noon_sigma.csv"
    if sigma_path.exists():
        sigma_df = pd.read_csv(sigma_path)
        res_df = res_df.merge(sigma_df[["ticker", "noon_sigma"]], on="ticker", how="left")
        valid = res_df.dropna(subset=["delta", "noon_sigma"])
        if len(valid) > 5:
            corr = valid["delta"].corr(valid["noon_sigma"])
            print(f"\n  Correlation (delta vs noon_sigma/beta proxy): r = {corr:.3f}")
            print(f"  {'Higher vol → more deep-friendly' if corr > 0.1 else 'No clear vol→deep relationship' if abs(corr) < 0.1 else 'Higher vol → less deep-friendly'}")

    return res_df


# ═══════════════════════════════════════════════════════════
# PLOTS
# ═══════════════════════════════════════════════════════════

def make_plots(trades, i6b_df, i6c_df):
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    z_buckets = ["<1σ", "1-2σ", ">2σ"]

    # 1. MAE/MFE grouped bar by z-score bucket
    ax = axes[0, 0]
    x = np.arange(len(z_buckets))
    width = 0.35
    mae_vals = [i6b_df.loc[i6b_df["bucket"] == b, "avg_mae"].values[0]
                for b in z_buckets if b in i6b_df["bucket"].values]
    mfe_vals = [i6b_df.loc[i6b_df["bucket"] == b, "avg_mfe"].values[0]
                for b in z_buckets if b in i6b_df["bucket"].values]
    ax.bar(x - width/2, [abs(v) for v in mae_vals], width, color="#F44336", alpha=0.8, label="Avg |MAE| (risk)")
    ax.bar(x + width/2, mfe_vals, width, color="#4CAF50", alpha=0.8, label="Avg MFE (opportunity)")
    ax.set_xticks(x)
    ax.set_xticklabels(z_buckets)
    ax.set_ylabel("%")
    ax.set_title("I6b: MAE vs MFE by Depth")
    ax.legend(fontsize=8)

    # 2. MFE/MAE ratio by bucket
    ax = axes[0, 1]
    ratios = [i6b_df.loc[i6b_df["bucket"] == b, "mfe_mae_ratio"].values[0]
              for b in z_buckets if b in i6b_df["bucket"].values]
    colors = ["#4CAF50" if r > 2 else "#FF9800" if r > 1.5 else "#F44336" for r in ratios]
    bars = ax.bar(z_buckets[:len(ratios)], ratios, color=colors, alpha=0.85)
    ax.axhline(2.0, color="green", linestyle="--", alpha=0.5, label="Target 2:1")
    ax.axhline(1.0, color="red", linestyle="--", alpha=0.5, label="Breakeven")
    for bar, r in zip(bars, ratios):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.05,
                f"{r:.2f}", ha="center", fontsize=10)
    ax.set_ylabel("MFE / |MAE| Ratio")
    ax.set_title("I6b: Risk/Reward Ratio by Depth")
    ax.legend(fontsize=8)

    # 3. Per-ticker delta (I6c)
    ax = axes[1, 0]
    valid = i6c_df[i6c_df["category"] != "insufficient"].sort_values("delta")
    colors_map = {"deep-friendly": "#4CAF50", "flat": "#FF9800", "deep-hostile": "#F44336"}
    bar_colors = [colors_map[c] for c in valid["category"]]
    ax.barh(range(len(valid)), valid["delta"], color=bar_colors, alpha=0.85)
    ax.set_yticks(range(len(valid)))
    ax.set_yticklabels(valid["ticker"], fontsize=7)
    ax.axvline(0, color="black", linewidth=0.5)
    ax.axvline(0.2, color="green", linestyle="--", alpha=0.3)
    ax.axvline(-0.2, color="red", linestyle="--", alpha=0.3)
    ax.set_xlabel("Delta: Deep P&L - Shallow P&L (%)")
    ax.set_title("I6c: Per-Ticker 'Deep vs Shallow' Delta")

    # 4. MAE distribution: shallow vs deep
    ax = axes[1, 1]
    shallow_mae = trades[trades["zscore_bucket"] == "<1σ"]["mae"].dropna()
    deep_mae = trades[trades["depth_z"] >= 1.0]["mae"].dropna()
    bins = np.arange(-5, 0.5, 0.1)
    ax.hist(shallow_mae, bins=bins, alpha=0.5, color="#2196F3", label=f"Shallow <1σ (N={len(shallow_mae)})", density=True)
    ax.hist(deep_mae, bins=bins, alpha=0.5, color="#F44336", label=f"Deep >=1σ (N={len(deep_mae)})", density=True)
    ax.set_xlabel("MAE (%)")
    ax.set_ylabel("Density")
    ax.set_title("I6b: MAE Distribution — Shallow vs Deep")
    ax.legend(fontsize=8)

    plt.suptitle("I6b + I6c: Path Risk & Per-Ticker Stability", fontsize=14)
    plt.tight_layout()
    plt.savefig(OUT_DIR / "I6bc_path_ticker.png", dpi=150)
    plt.close()
    print("\nSaved: I6bc_path_ticker.png")


def main():
    # Load I6a data
    i6a = pd.read_csv(I6A_DATA)
    i6a["trading_day"] = pd.to_datetime(i6a["trading_day"]).dt.date
    print(f"Loaded {len(i6a)} events from I6a")

    # Load M5 for MAE/MFE
    m5_cache = load_all_m5()

    # Compute MAE/MFE
    trades = compute_mae_mfe(m5_cache, i6a)
    trades.to_csv(OUT_DIR / "I6bc_trades_with_mae_mfe.csv", index=False)

    # I6b
    i6b_df = run_i6b(trades)

    # I6c
    i6c_df = run_i6c(trades)
    i6c_df.to_csv(OUT_DIR / "I6c_per_ticker.csv", index=False)

    # Plots
    make_plots(trades, i6b_df, i6c_df)


if __name__ == "__main__":
    main()
