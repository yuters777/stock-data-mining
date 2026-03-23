"""
Series I5: Z-Score Threshold Validation Against Noon Reversal P&L.

Uses I4 depth_z data but re-prices trades with:
  Entry = DZ_low (12:00-13:30 ET low)
  Exit  = close at 15:30 ET (nearest M5 bar)
  trade_return = (exit - entry) / entry * 100

Tests whether the z-score hard block improves trade expectancy, not just
full-recovery classification.
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

# 15:30 ET = 22:30 IST
EXIT_IST_MIN = 22 * 60 + 30


def ist_minutes(dt):
    return dt.hour * 60 + dt.minute


def get_exit_prices():
    """Extract 15:30 ET close price for every ticker × trading_day."""
    print("Extracting 15:30 ET exit prices from M5 data...")
    all_exits = {}

    for ticker in EQUITY_TICKERS:
        path = DATA_DIR / f"{ticker}_data.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, parse_dates=["Datetime"])
        df = df.sort_values("Datetime").reset_index(drop=True)

        mins = df["Datetime"].apply(ist_minutes)
        # Filter to IST regular session (avoid ET duplicate)
        mask = (mins >= 16 * 60 + 35) & (mins <= 22 * 60 + 55)
        df = df[mask].copy()
        df["trading_day"] = df["Datetime"].dt.date
        df["ist_min"] = df["Datetime"].apply(ist_minutes)

        for day, day_df in df.groupby("trading_day"):
            # Find closest bar to 22:30 IST (15:30 ET)
            # Prefer exact match, else nearest bar <= 22:30
            candidates = day_df[day_df["ist_min"] <= EXIT_IST_MIN]
            if candidates.empty:
                continue
            # Take the last bar at or before 15:30 ET
            exit_bar = candidates.iloc[-1]
            all_exits[(ticker, day)] = exit_bar["Close"]

    print(f"  Extracted {len(all_exits):,} exit prices")
    return all_exits


def main():
    # ── Load I4 data ──
    i4 = pd.read_csv(I4_DATA)
    i4["trading_day"] = pd.to_datetime(i4["trading_day"]).dt.date
    print(f"Loaded {len(i4)} events from I4")

    # ── Get exit prices ──
    exit_prices = get_exit_prices()

    # ── Compute trade returns ──
    exits = []
    for _, row in i4.iterrows():
        key = (row["ticker"], row["trading_day"])
        exit_price = exit_prices.get(key)
        exits.append(exit_price)

    i4["exit_1530"] = exits
    i4 = i4.dropna(subset=["exit_1530"]).copy()
    i4["trade_return"] = (i4["exit_1530"] - i4["dz_low"]) / i4["dz_low"] * 100
    i4["win"] = i4["trade_return"] > 0

    print(f"Events with valid exit price: {len(i4)}")
    print(f"Overall: avg P&L = {i4['trade_return'].mean():.4f}%, "
          f"WR = {i4['win'].mean()*100:.1f}%")

    i4.to_csv(OUT_DIR / "I5_trade_data.csv", index=False)

    # ═══════════════════════════════════════════════════════
    # A) Z-score cutoff sweep
    # ═══════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("A) Z-Score Cutoff Sweep — Noon Reversal P&L")
    print("=" * 70)

    cutoffs = [0.5, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
    z_results = []

    print(f"{'Cutoff':>8s}  {'Take_PL':>9s}  {'Take_WR':>8s}  {'Take_N':>7s}  "
          f"{'Block_PL':>9s}  {'Block_WR':>9s}  {'Block_N':>8s}  {'Veto_Value':>11s}")

    for c in cutoffs:
        take = i4[i4["depth_z"] < c]
        block = i4[i4["depth_z"] >= c]

        take_pl = take["trade_return"].mean() if len(take) > 0 else 0
        take_wr = take["win"].mean() * 100 if len(take) > 0 else 0
        block_pl = block["trade_return"].mean() if len(block) > 0 else 0
        block_wr = block["win"].mean() * 100 if len(block) > 0 else 0
        # Veto value = how much we avoid by blocking (negative = good veto)
        veto_value = block_pl

        print(f"{c:>7.2f}σ  {take_pl:>+8.4f}%  {take_wr:>7.1f}%  {len(take):>7d}  "
              f"{block_pl:>+8.4f}%  {block_wr:>8.1f}%  {len(block):>8d}  {veto_value:>+10.4f}%")

        z_results.append({
            "cutoff": c, "method": "z-score",
            "take_pl": take_pl, "take_wr": take_wr, "take_n": len(take),
            "block_pl": block_pl, "block_wr": block_wr, "block_n": len(block),
            "veto_value": veto_value,
        })

    # ═══════════════════════════════════════════════════════
    # B) Raw % threshold comparison
    # ═══════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("B) Raw % Threshold Comparison")
    print("=" * 70)

    raw_cutoffs = [0.5, 1.0, 1.5, 2.0]
    raw_results = []

    print(f"{'Cutoff':>8s}  {'Take_PL':>9s}  {'Take_WR':>8s}  {'Take_N':>7s}  "
          f"{'Block_PL':>9s}  {'Block_WR':>9s}  {'Block_N':>8s}  {'Veto_Value':>11s}")

    for c in raw_cutoffs:
        take = i4[i4["compression_pct"] < c]
        block = i4[i4["compression_pct"] >= c]

        take_pl = take["trade_return"].mean() if len(take) > 0 else 0
        take_wr = take["win"].mean() * 100 if len(take) > 0 else 0
        block_pl = block["trade_return"].mean() if len(block) > 0 else 0
        block_wr = block["win"].mean() * 100 if len(block) > 0 else 0

        print(f"{c:>7.1f}%  {take_pl:>+8.4f}%  {take_wr:>7.1f}%  {len(take):>7d}  "
              f"{block_pl:>+8.4f}%  {block_wr:>8.1f}%  {len(block):>8d}  {block_pl:>+10.4f}%")

        raw_results.append({
            "cutoff": c, "method": "raw_%",
            "take_pl": take_pl, "take_wr": take_wr, "take_n": len(take),
            "block_pl": block_pl, "block_wr": block_wr, "block_n": len(block),
            "veto_value": block_pl,
        })

    # ═══════════════════════════════════════════════════════
    # C) Compare optimal cutoffs
    # ═══════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("C) Optimal Cutoff Comparison")
    print("=" * 70)

    z_df = pd.DataFrame(z_results)
    raw_df = pd.DataFrame(raw_results)

    # Best z-score: maximize take_pl while veto_value is negative
    z_df["improvement"] = z_df["take_pl"] - i4["trade_return"].mean()
    best_z = z_df.loc[z_df["take_pl"].idxmax()]

    # For raw %, find best take_pl
    raw_df["improvement"] = raw_df["take_pl"] - i4["trade_return"].mean()
    best_raw = raw_df.loc[raw_df["take_pl"].idxmax()]

    baseline_pl = i4["trade_return"].mean()
    baseline_wr = i4["win"].mean() * 100

    print(f"\nBaseline (no veto): avg P&L = {baseline_pl:+.4f}%, WR = {baseline_wr:.1f}%")
    print(f"\nBest Z-Score cutoff: {best_z['cutoff']:.2f}σ")
    print(f"  Take avg P&L: {best_z['take_pl']:+.4f}% (Δ = {best_z['improvement']:+.4f}%)")
    print(f"  Take WR: {best_z['take_wr']:.1f}%")
    print(f"  Blocked avg P&L: {best_z['veto_value']:+.4f}% (veto correct = negative)")
    print(f"  N take / N block: {int(best_z['take_n'])} / {int(best_z['block_n'])}")

    print(f"\nBest Raw % cutoff: {best_raw['cutoff']:.1f}%")
    print(f"  Take avg P&L: {best_raw['take_pl']:+.4f}% (Δ = {best_raw['improvement']:+.4f}%)")
    print(f"  Take WR: {best_raw['take_wr']:.1f}%")
    print(f"  Blocked avg P&L: {best_raw['veto_value']:+.4f}%")
    print(f"  N take / N block: {int(best_raw['take_n'])} / {int(best_raw['block_n'])}")

    # ═══════════════════════════════════════════════════════
    # D) Two-tier validation: among events below 2.0σ, raw % sizing
    # ═══════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("D) Two-Tier Validation: Z-Score Veto + Raw % Sizing")
    print("=" * 70)

    passed = i4[i4["depth_z"] < 2.0].copy()
    print(f"\nEvents passing z-score < 2.0σ veto: {len(passed)}")
    print(f"  Overall avg P&L: {passed['trade_return'].mean():+.4f}%, "
          f"WR: {passed['win'].mean()*100:.1f}%")

    raw_buckets = ["<0.5%", "0.5-1.0%", ">1.0%"]
    print(f"\n{'Bucket':>12s}  {'Avg PL':>9s}  {'WR':>7s}  {'N':>6s}  {'Med PL':>9s}")
    for bucket in raw_buckets:
        sub = passed[passed["compression_bucket"] == bucket]
        if len(sub) == 0:
            continue
        avg_pl = sub["trade_return"].mean()
        wr = sub["win"].mean() * 100
        med_pl = sub["trade_return"].median()
        print(f"{bucket:>12s}  {avg_pl:>+8.4f}%  {wr:>6.1f}%  {len(sub):>6d}  {med_pl:>+8.4f}%")

    # Monotonicity check: does PL decrease with compression?
    bucket_pls = []
    for bucket in raw_buckets:
        sub = passed[passed["compression_bucket"] == bucket]
        if len(sub) > 0:
            bucket_pls.append(sub["trade_return"].mean())

    monotonic = all(bucket_pls[i] >= bucket_pls[i+1] for i in range(len(bucket_pls)-1))
    print(f"\n  Monotonic PL decrease with compression: {'YES' if monotonic else 'NO'}")
    print(f"  Two-tier system: {'VALIDATED' if monotonic else 'NOT VALIDATED'}")

    # ═══════════════════════════════════════════════════════
    # E) Additional: P&L by z-score bucket (for report)
    # ═══════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("E) P&L by Z-Score Bucket")
    print("=" * 70)

    for bucket in ["<1σ", "1-2σ", ">2σ"]:
        sub = i4[i4["zscore_bucket"] == bucket]
        if len(sub) == 0:
            continue
        avg_pl = sub["trade_return"].mean()
        wr = sub["win"].mean() * 100
        med_pl = sub["trade_return"].median()
        print(f"  {bucket:>5s}: avg P&L={avg_pl:+.4f}%, WR={wr:.1f}%, "
              f"median P&L={med_pl:+.4f}%, N={len(sub)}")

    # ═══════════════════════════════════════════════════════
    # PLOTS
    # ═══════════════════════════════════════════════════════
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # 1. Z-score cutoff sweep: take PL vs block PL
    ax = axes[0, 0]
    ax.plot(z_df["cutoff"], z_df["take_pl"], "o-", color="green", label="Take avg P&L", linewidth=2)
    ax.plot(z_df["cutoff"], z_df["block_pl"], "s-", color="red", label="Block avg P&L", linewidth=2)
    ax.axhline(baseline_pl, color="gray", linestyle="--", alpha=0.7, label=f"Baseline {baseline_pl:+.4f}%")
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_xlabel("Z-Score Cutoff (σ)")
    ax.set_ylabel("Avg P&L (%)")
    ax.set_title("Z-Score Cutoff: Take vs Block P&L")
    ax.legend(fontsize=8)

    # 2. Z-score cutoff: take WR vs block WR
    ax = axes[0, 1]
    ax.plot(z_df["cutoff"], z_df["take_wr"], "o-", color="green", label="Take WR", linewidth=2)
    ax.plot(z_df["cutoff"], z_df["block_wr"], "s-", color="red", label="Block WR", linewidth=2)
    ax.axhline(baseline_wr, color="gray", linestyle="--", alpha=0.7, label=f"Baseline {baseline_wr:.1f}%")
    ax.axhline(50, color="black", linewidth=0.5)
    ax.set_xlabel("Z-Score Cutoff (σ)")
    ax.set_ylabel("Win Rate (%)")
    ax.set_title("Z-Score Cutoff: Take vs Block Win Rate")
    ax.legend(fontsize=8)

    # 3. Two-tier: P&L by raw % bucket (among z < 2.0σ)
    ax = axes[1, 0]
    colors = ["#4CAF50", "#FF9800", "#F44336"]
    pls, labels, ns = [], [], []
    for bucket, color in zip(raw_buckets, colors):
        sub = passed[passed["compression_bucket"] == bucket]
        if len(sub) > 0:
            pls.append(sub["trade_return"].mean())
            labels.append(bucket)
            ns.append(len(sub))

    bars = ax.bar(range(len(pls)), pls, color=colors[:len(pls)], alpha=0.85, edgecolor="white")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels)
    for bar, n, pl in zip(bars, ns, pls):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.002,
                f"{pl:+.3f}%\nN={n}", ha="center", fontsize=9)
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_ylabel("Avg P&L (%)")
    ax.set_title("Two-Tier: P&L by Raw % (after z < 2.0σ veto)")

    # 4. Scatter: depth_z vs trade return
    ax = axes[1, 1]
    wins = i4[i4["win"]]
    losses = i4[~i4["win"]]
    ax.scatter(losses["depth_z"], losses["trade_return"], s=5, alpha=0.2, c="red", label="Loss")
    ax.scatter(wins["depth_z"], wins["trade_return"], s=5, alpha=0.2, c="green", label="Win")
    ax.axhline(0, color="black", linewidth=0.5)
    ax.axvline(2.0, color="blue", linestyle="--", alpha=0.7, label="2.0σ veto")
    ax.set_xlabel("Depth Z-Score (σ)")
    ax.set_ylabel("Trade Return (%)")
    ax.set_title("Depth Z-Score vs Trade Return")
    ax.set_xlim(-3, 10)
    ax.set_ylim(-10, 15)
    ax.legend(fontsize=8)

    plt.suptitle("I5: Z-Score Threshold vs Noon Reversal P&L", fontsize=14)
    plt.tight_layout()
    plt.savefig(OUT_DIR / "I5_pnl_validation.png", dpi=150)
    plt.close()
    print("\nSaved: I5_pnl_validation.png")


if __name__ == "__main__":
    main()
