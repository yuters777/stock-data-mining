"""
Series I6d + I6e + I6f: Time-of-Low, Split-Sample, Cost Stress Test.

Uses V1 (First Green Close) trades with MAE/MFE from I6bc.
Final validation suite before Noon Reversal v0.4 recommendation.
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ── paths ──
OUT_DIR = Path(__file__).resolve().parent
I6BC_DATA = OUT_DIR / "I6bc_trades_with_mae_mfe.csv"

# Cost tiers (round-trip)
MEGA_CAP = {"AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "SPY", "TSLA"}
HIGH_BETA = {"MARA", "PLTR", "COIN", "MSTR"}
# Everything else = mid-vol

COST_MAP = {}
for t in MEGA_CAP:
    COST_MAP[t] = 0.03
for t in HIGH_BETA:
    COST_MAP[t] = 0.08


def get_cost(ticker):
    return COST_MAP.get(ticker, 0.05)


def time_bucket(ist_min):
    """Classify DZ low time into Early/Mid/Late (ET).
    IST = ET + 7h. DZ = 12:00-13:30 ET = 19:00-20:30 IST."""
    et_min = ist_min - 7 * 60
    if et_min < 12 * 60 + 30:
        return "Early (<12:30)"
    elif et_min < 13 * 60:
        return "Mid (12:30-13:00)"
    else:
        return "Late (13:00-13:30)"


# ═══════════════════════════════════════════════════════════
# I6d: Time-of-Low Interaction
# ═══════════════════════════════════════════════════════════

def run_i6d(trades):
    print(f"\n{'='*70}")
    print("I6d: Time-of-Low Interaction")
    print("=" * 70)

    trades = trades.copy()
    trades["time_bucket"] = trades["dz_low_ist_min"].apply(time_bucket)
    trades["depth_binary"] = np.where(trades["depth_z"] >= 1.0, "deep (>=1σ)", "shallow (<1σ)")

    time_buckets = ["Early (<12:30)", "Mid (12:30-13:00)", "Late (13:00-13:30)"]
    depth_buckets = ["shallow (<1σ)", "deep (>=1σ)"]

    # 2-way table
    print(f"\n{'Time':>20s}  {'Depth':>15s}  {'Avg PL':>9s}  {'Med PL':>9s}  {'WR':>7s}  {'N':>6s}")
    print("-" * 75)

    rows = []
    for tb in time_buckets:
        for db in depth_buckets:
            sub = trades[(trades["time_bucket"] == tb) & (trades["depth_binary"] == db)]
            if sub.empty:
                continue
            avg_pl = sub["v1_pl"].mean()
            med_pl = sub["v1_pl"].median()
            wr = (sub["v1_pl"] > 0).mean() * 100
            print(f"{tb:>20s}  {db:>15s}  {avg_pl:>+8.4f}%  {med_pl:>+8.4f}%  {wr:>6.1f}%  {len(sub):>6d}")
            rows.append({"time": tb, "depth": db, "avg_pl": avg_pl, "wr": wr, "n": len(sub)})

    # Overall by time
    print(f"\n  Overall by time:")
    for tb in time_buckets:
        sub = trades[trades["time_bucket"] == tb]
        if sub.empty:
            continue
        print(f"    {tb}: avg P&L = {sub['v1_pl'].mean():+.4f}%, "
              f"WR = {(sub['v1_pl'] > 0).mean()*100:.1f}%, N = {len(sub)}")

    # Deep-shallow delta by time
    print(f"\n  'Deep - Shallow' delta by time:")
    for tb in time_buckets:
        shallow = trades[(trades["time_bucket"] == tb) & (trades["depth_binary"] == "shallow (<1σ)")]
        deep = trades[(trades["time_bucket"] == tb) & (trades["depth_binary"] == "deep (>=1σ)")]
        if shallow.empty or deep.empty:
            continue
        delta = deep["v1_pl"].mean() - shallow["v1_pl"].mean()
        print(f"    {tb}: Δ = {delta:+.4f}%")

    return pd.DataFrame(rows), trades


# ═══════════════════════════════════════════════════════════
# I6e: Split-Sample Validation
# ═══════════════════════════════════════════════════════════

def run_i6e(trades):
    print(f"\n{'='*70}")
    print("I6e: Split-Sample Validation")
    print("=" * 70)

    trades = trades.copy()
    trades["depth_binary"] = np.where(trades["depth_z"] >= 1.0, "deep (>=1σ)", "shallow (<1σ)")

    # Split by trading day chronologically
    all_days = sorted(trades["trading_day"].unique())
    mid = len(all_days) // 2
    first_half_days = set(all_days[:mid])
    second_half_days = set(all_days[mid:])

    trades["half"] = trades["trading_day"].apply(
        lambda d: "First half" if d in first_half_days else "Second half"
    )

    print(f"  First half:  {all_days[0]} to {all_days[mid-1]} ({mid} days)")
    print(f"  Second half: {all_days[mid]} to {all_days[-1]} ({len(all_days) - mid} days)")

    halves = ["First half", "Second half"]
    depth_buckets = ["shallow (<1σ)", "deep (>=1σ)"]

    print(f"\n{'Half':>14s}  {'Depth':>15s}  {'Avg PL':>9s}  {'Med PL':>9s}  {'WR':>7s}  {'N':>6s}")
    print("-" * 70)

    rows = []
    for h in halves:
        for db in depth_buckets:
            sub = trades[(trades["half"] == h) & (trades["depth_binary"] == db)]
            if sub.empty:
                continue
            avg_pl = sub["v1_pl"].mean()
            med_pl = sub["v1_pl"].median()
            wr = (sub["v1_pl"] > 0).mean() * 100
            print(f"{h:>14s}  {db:>15s}  {avg_pl:>+8.4f}%  {med_pl:>+8.4f}%  {wr:>6.1f}%  {len(sub):>6d}")
            rows.append({"half": h, "depth": db, "avg_pl": avg_pl, "wr": wr, "n": len(sub)})

    # Gradient check
    print(f"\n  Gradient check (deep - shallow):")
    for h in halves:
        shallow = trades[(trades["half"] == h) & (trades["depth_binary"] == "shallow (<1σ)")]
        deep = trades[(trades["half"] == h) & (trades["depth_binary"] == "deep (>=1σ)")]
        if shallow.empty or deep.empty:
            continue
        delta = deep["v1_pl"].mean() - shallow["v1_pl"].mean()
        direction = "DEEP > SHALLOW" if delta > 0 else "SHALLOW > DEEP"
        print(f"    {h}: Δ = {delta:+.4f}% → {direction}")

    # Also check z-score 3-bucket split
    print(f"\n  By z-score 3-bucket:")
    for h in halves:
        print(f"    {h}:")
        for zb in ["<1σ", "1-2σ", ">2σ"]:
            sub = trades[(trades["half"] == h) & (trades["zscore_bucket"] == zb)]
            if len(sub) > 0:
                print(f"      {zb}: avg P&L = {sub['v1_pl'].mean():+.4f}%, "
                      f"WR = {(sub['v1_pl'] > 0).mean()*100:.1f}%, N = {len(sub)}")

    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════
# I6f: Cost / Slippage Stress Test
# ═══════════════════════════════════════════════════════════

def run_i6f(trades):
    print(f"\n{'='*70}")
    print("I6f: Cost / Slippage Stress Test")
    print("=" * 70)

    trades = trades.copy()
    trades["cost"] = trades["ticker"].apply(get_cost)
    trades["net_pl"] = trades["v1_pl"] - trades["cost"]
    trades["depth_binary"] = np.where(trades["depth_z"] >= 1.0, "deep (>=1σ)", "shallow (<1σ)")

    depth_buckets = ["shallow (<1σ)", "deep (>=1σ)"]

    print(f"\n{'Depth':>15s}  {'Gross PL':>10s}  {'Avg Cost':>9s}  {'Net PL':>9s}  "
          f"{'Net WR':>7s}  {'Edge Left':>10s}  {'N':>6s}")
    print("-" * 75)

    rows = []
    for db in depth_buckets:
        sub = trades[trades["depth_binary"] == db]
        if sub.empty:
            continue
        gross = sub["v1_pl"].mean()
        avg_cost = sub["cost"].mean()
        net = sub["net_pl"].mean()
        net_wr = (sub["net_pl"] > 0).mean() * 100
        edge_pct = net / gross * 100 if gross > 0 else 0
        print(f"{db:>15s}  {gross:>+9.4f}%  {avg_cost:>8.3f}%  {net:>+8.4f}%  "
              f"{net_wr:>6.1f}%  {edge_pct:>9.1f}%  {len(sub):>6d}")
        rows.append({"depth": db, "gross_pl": gross, "avg_cost": avg_cost,
                      "net_pl": net, "net_wr": net_wr, "n": len(sub)})

    # By z-score 3-bucket
    print(f"\n  By z-score bucket:")
    for zb in ["<1σ", "1-2σ", ">2σ"]:
        sub = trades[trades["zscore_bucket"] == zb]
        if sub.empty:
            continue
        gross = sub["v1_pl"].mean()
        net = sub["net_pl"].mean()
        net_wr = (sub["net_pl"] > 0).mean() * 100
        print(f"    {zb}: gross = {gross:+.4f}%, net = {net:+.4f}%, net WR = {net_wr:.1f}%, N = {len(sub)}")

    # By cost tier
    print(f"\n  By cost tier:")
    for tier, tickers in [("Mega-cap (0.03%)", MEGA_CAP),
                           ("Mid-vol (0.05%)", None),
                           ("High-beta (0.08%)", HIGH_BETA)]:
        if tickers:
            sub = trades[trades["ticker"].isin(tickers)]
        else:
            sub = trades[~trades["ticker"].isin(MEGA_CAP | HIGH_BETA)]
        if sub.empty:
            continue
        gross = sub["v1_pl"].mean()
        net = sub["net_pl"].mean()
        print(f"    {tier}: gross = {gross:+.4f}%, net = {net:+.4f}%, N = {len(sub)}")

    # Breakeven analysis
    print(f"\n  Breakeven analysis (at what cost does avg P&L go to 0?):")
    for db in depth_buckets:
        sub = trades[trades["depth_binary"] == db]
        if sub.empty:
            continue
        gross = sub["v1_pl"].mean()
        print(f"    {db}: breakeven cost = {gross:+.4f}% (current avg cost = {sub['cost'].mean():.3f}%)")

    # Stress test: what if costs double?
    print(f"\n  Stress: if costs 2x:")
    trades["net_pl_2x"] = trades["v1_pl"] - trades["cost"] * 2
    for db in depth_buckets:
        sub = trades[trades["depth_binary"] == db]
        if sub.empty:
            continue
        net_2x = sub["net_pl_2x"].mean()
        print(f"    {db}: net P&L = {net_2x:+.4f}%")

    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════
# PLOTS
# ═══════════════════════════════════════════════════════════

def make_plots(trades_with_time, i6d_df, i6e_df, i6f_df):
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # 1. I6d: Time × Depth heatmap
    ax = axes[0, 0]
    time_buckets = ["Early (<12:30)", "Mid (12:30-13:00)", "Late (13:00-13:30)"]
    depth_buckets = ["shallow (<1σ)", "deep (>=1σ)"]
    data = np.zeros((len(depth_buckets), len(time_buckets)))
    for i, db in enumerate(depth_buckets):
        for j, tb in enumerate(time_buckets):
            row = i6d_df[(i6d_df["time"] == tb) & (i6d_df["depth"] == db)]
            if not row.empty:
                data[i, j] = row["avg_pl"].values[0]
    im = ax.imshow(data, cmap="RdYlGn", aspect="auto", vmin=-0.1, vmax=0.8)
    ax.set_xticks(range(len(time_buckets)))
    ax.set_xticklabels(["Early", "Mid", "Late"], fontsize=9)
    ax.set_yticks(range(len(depth_buckets)))
    ax.set_yticklabels(["Shallow", "Deep"], fontsize=9)
    for i in range(len(depth_buckets)):
        for j in range(len(time_buckets)):
            row = i6d_df[(i6d_df["time"] == time_buckets[j]) & (i6d_df["depth"] == depth_buckets[i])]
            n = int(row["n"].values[0]) if not row.empty else 0
            ax.text(j, i, f"{data[i,j]:+.3f}%\nN={n}", ha="center", va="center", fontsize=9)
    ax.set_title("I6d: Avg P&L by Time of Low × Depth")
    plt.colorbar(im, ax=ax)

    # 2. I6e: Split-sample bar chart
    ax = axes[0, 1]
    halves = ["First half", "Second half"]
    x = np.arange(len(halves))
    width = 0.35
    for i, db in enumerate(depth_buckets):
        vals = []
        for h in halves:
            row = i6e_df[(i6e_df["half"] == h) & (i6e_df["depth"] == db)]
            vals.append(row["avg_pl"].values[0] if not row.empty else 0)
        color = "#2196F3" if i == 0 else "#FF9800"
        ax.bar(x + (i - 0.5) * width, vals, width, label=db, color=color, alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(halves)
    ax.set_ylabel("Avg P&L (%)")
    ax.set_title("I6e: Split-Sample Stability")
    ax.legend(fontsize=8)
    ax.axhline(0, color="black", linewidth=0.5)

    # 3. I6f: Gross vs Net P&L
    ax = axes[1, 0]
    x = np.arange(len(depth_buckets))
    gross_vals = [i6f_df.loc[i6f_df["depth"] == db, "gross_pl"].values[0] for db in depth_buckets]
    net_vals = [i6f_df.loc[i6f_df["depth"] == db, "net_pl"].values[0] for db in depth_buckets]
    ax.bar(x - width/2, gross_vals, width, label="Gross P&L", color="#4CAF50", alpha=0.85)
    ax.bar(x + width/2, net_vals, width, label="Net P&L", color="#FF9800", alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(["Shallow", "Deep"])
    ax.set_ylabel("Avg P&L (%)")
    ax.set_title("I6f: Gross vs Net P&L")
    ax.legend()
    ax.axhline(0, color="black", linewidth=0.5)
    for i, (g, n) in enumerate(zip(gross_vals, net_vals)):
        ax.text(i - width/2, g + 0.01, f"{g:+.3f}%", ha="center", fontsize=8)
        ax.text(i + width/2, n + 0.01, f"{n:+.3f}%", ha="center", fontsize=8)

    # 4. Time-of-low distribution
    ax = axes[1, 1]
    trades_with_time = trades_with_time.copy()
    et_mins = trades_with_time["dz_low_ist_min"] - 7 * 60
    ax.hist(et_mins, bins=range(12*60, 13*60+35, 5), color="steelblue", edgecolor="white", alpha=0.85)
    ax.axvline(12*60+30, color="red", linestyle="--", alpha=0.7, label="12:30 ET")
    ax.axvline(13*60, color="orange", linestyle="--", alpha=0.7, label="13:00 ET")
    tick_pos = range(12*60, 13*60+31, 15)
    ax.set_xticks(list(tick_pos))
    ax.set_xticklabels([f"{m//60}:{m%60:02d}" for m in tick_pos], fontsize=8)
    ax.set_xlabel("DZ Low Time (ET)")
    ax.set_ylabel("Count")
    ax.set_title("I6d: Distribution of DZ Low Times")
    ax.legend(fontsize=8)

    plt.suptitle("I6d + I6e + I6f: Final Validation Suite", fontsize=14)
    plt.tight_layout()
    plt.savefig(OUT_DIR / "I6def_validation.png", dpi=150)
    plt.close()
    print("\nSaved: I6def_validation.png")


def main():
    # Load trades with MAE/MFE from I6bc
    trades = pd.read_csv(I6BC_DATA)
    trades["trading_day"] = pd.to_datetime(trades["trading_day"]).dt.date
    # Filter to V1 trades only (non-null v1_pl)
    trades = trades.dropna(subset=["v1_pl"]).copy()
    print(f"Loaded {len(trades)} V1 trades from I6bc")

    # I6d
    i6d_df, trades_with_time = run_i6d(trades)

    # I6e
    i6e_df = run_i6e(trades)

    # I6f
    i6f_df = run_i6f(trades)

    # Plots
    make_plots(trades_with_time, i6d_df, i6e_df, i6f_df)


if __name__ == "__main__":
    main()
