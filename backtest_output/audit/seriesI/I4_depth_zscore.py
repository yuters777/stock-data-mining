"""
Series I4: Depth Z-Score Calibration.

Tests whether normalizing DZ compression by per-ticker noon volatility (z-score)
improves recovery outcome prediction vs raw % thresholds.

Steps:
1. Compute per-ticker noon sigma (std of M5 returns in 12:00-13:30 ET window)
2. Compute depth_z = DZ_compression_pct / ticker_noon_sigma for each event
3. Re-run I2 classification with z-score buckets (<1σ, 1-2σ, >2σ)
4. Compare separation quality: chi-squared + discrimination ratio
5. VIX interaction analysis (2-way table)
6. Optimal threshold search
"""

import sys
from pathlib import Path
from datetime import timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

# ── paths ──
ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "Fetched_Data"
OUT_DIR = Path(__file__).resolve().parent
VIX_PATH = DATA_DIR / "VIXCLS_FRED_real.csv"
I2_DATA = OUT_DIR / "I2_recovery_outcome_data.csv"

EQUITY_TICKERS = [
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN",
    "COST", "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU",
    "NVDA", "PLTR", "SNOW", "SPY", "TSLA", "TSM", "TXN", "V",
]

# IST zone boundaries for Dead Zone: 12:00-13:30 ET = 19:00-20:30 IST
Z2_START = 17 * 60      # 10:00 ET = 17:00 IST
Z2_END = 19 * 60        # 12:00 ET = 19:00 IST
Z3_START = 19 * 60
Z3_END = 20 * 60 + 30


def ist_minutes(dt):
    return dt.hour * 60 + dt.minute


# ═══════════════════════════════════════════════════════════
# STEP 1: Compute per-ticker noon sigma
# ═══════════════════════════════════════════════════════════

def compute_noon_sigma():
    """Compute per-ticker normalization: std and mean of daily DZ compressions.

    For each ticker, across all trading days:
      compression = (Z2_high - DZ_low) / Z2_high * 100
    Then noon_sigma = std(compression), noon_mean = mean(compression).
    This is 'expected same-clock sigma' at the compression level,
    not per-bar returns.
    """
    results = []
    for ticker in EQUITY_TICKERS:
        path = DATA_DIR / f"{ticker}_data.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, parse_dates=["Datetime"])
        df = df.sort_values("Datetime").reset_index(drop=True)

        # Filter to IST regular session (avoid duplicate ET section)
        mins = df["Datetime"].apply(ist_minutes)
        mask = (mins >= 16 * 60 + 35) & (mins <= 22 * 60 + 55)
        df = df[mask].copy()
        df["trading_day"] = df["Datetime"].dt.date
        df["ist_min"] = df["Datetime"].apply(ist_minutes)

        daily_compressions = []
        for day, day_df in df.groupby("trading_day"):
            z2 = day_df[(day_df["ist_min"] >= Z2_START) & (day_df["ist_min"] < Z2_END)]
            z3 = day_df[(day_df["ist_min"] >= Z3_START) & (day_df["ist_min"] < Z3_END)]
            if z2.empty or z3.empty:
                continue
            z2_high = z2["High"].max()
            dz_low = z3["Low"].min()
            if z2_high <= 0:
                continue
            comp = (z2_high - dz_low) / z2_high * 100
            daily_compressions.append(comp)

        if len(daily_compressions) < 10:
            continue

        comps = np.array(daily_compressions)
        noon_sigma = comps.std()
        noon_mean = comps.mean()

        results.append({
            "ticker": ticker,
            "noon_sigma": noon_sigma,
            "noon_mean": noon_mean,
            "n_days": len(daily_compressions),
        })
        print(f"  {ticker:>5s}: mean_comp={noon_mean:.3f}%, sigma={noon_sigma:.3f}%, N_days={len(daily_compressions)}")

    return pd.DataFrame(results)


# ═══════════════════════════════════════════════════════════
# STEP 2-3: Compute depth_z and classify
# ═══════════════════════════════════════════════════════════

def zscore_bucket(z):
    if z < 1.0:
        return "<1σ"
    elif z < 2.0:
        return "1-2σ"
    return ">2σ"


def add_depth_z(i2_df, sigma_df):
    """Add depth_z column to I2 data.

    depth_z = (today's compression - ticker mean compression) / ticker sigma
    This is a proper z-score: how unusual is today's DZ compression for this ticker?
    """
    sigma_map = dict(zip(sigma_df["ticker"], sigma_df["noon_sigma"]))
    mean_map = dict(zip(sigma_df["ticker"], sigma_df["noon_mean"]))
    df = i2_df.copy()
    df["noon_sigma"] = df["ticker"].map(sigma_map)
    df["noon_mean"] = df["ticker"].map(mean_map)
    df["depth_z"] = (df["compression_pct"] - df["noon_mean"]) / df["noon_sigma"]
    df["zscore_bucket"] = df["depth_z"].apply(zscore_bucket)
    return df


# ═══════════════════════════════════════════════════════════
# STEP 4: Evaluate separation quality
# ═══════════════════════════════════════════════════════════

def print_category_table(df, group_col, group_name, cats=None):
    """Print and return category distribution."""
    if cats is None:
        cats = ["full_recovery", "partial_recovery", "weak_recovery", "failed_recovery"]
    groups = sorted(df[group_col].unique())

    print(f"\n--- Recovery Outcome by {group_name} ---")
    header = f"{'':>12s}"
    for c in cats:
        header += f"  {c:>16s}"
    header += f"  {'N':>6s}"
    print(header)

    rows = []
    for g in groups:
        sub = df[df[group_col] == g]
        n = len(sub)
        row_data = {"group": g, "N": n}
        row_str = f"{str(g):>12s}"
        for c in cats:
            cnt = (sub["category"] == c).sum()
            pct = cnt / n * 100 if n > 0 else 0
            row_str += f"  {pct:>14.1f}%"
            row_data[c] = pct
        row_str += f"  {n:>6d}"
        print(row_str)
        rows.append(row_data)

    return pd.DataFrame(rows)


def compute_discrimination_ratio(df, group_col, shallow_val, deep_val):
    """Compute full_recovery_shallow / full_recovery_deep ratio."""
    shallow = df[df[group_col] == shallow_val]
    deep = df[df[group_col] == deep_val]

    if shallow.empty or deep.empty:
        return None

    fr_shallow = (shallow["category"] == "full_recovery").mean() * 100
    fr_deep = (deep["category"] == "full_recovery").mean() * 100

    if fr_deep == 0:
        return float("inf")
    return fr_shallow / fr_deep


def compute_chi2(df, group_col):
    """Chi-squared test on contingency table of group_col vs category."""
    ct = pd.crosstab(df[group_col], df["category"])
    chi2, p, dof, expected = stats.chi2_contingency(ct)
    cramers_v = np.sqrt(chi2 / (ct.values.sum() * (min(ct.shape) - 1)))
    return chi2, p, dof, cramers_v


# ═══════════════════════════════════════════════════════════
# STEP 5: VIX interaction
# ═══════════════════════════════════════════════════════════

def vix_interaction_analysis(df):
    """2-way analysis: depth_z bucket × VIX regime → recovery outcome."""
    print("\n--- 2-Way Table: Z-Score Bucket × VIX Regime → Full Recovery % ---")
    z_buckets = ["<1σ", "1-2σ", ">2σ"]
    vix_regimes = ["<20", "20-25", ">=25"]

    header = f"{'':>8s}"
    for v in vix_regimes:
        header += f"  VIX {v:>5s}"
    header += f"  {'ALL':>8s}"
    print(header)

    for zb in z_buckets:
        row = f"{zb:>8s}"
        zb_data = df[df["zscore_bucket"] == zb]
        for vr in vix_regimes:
            sub = zb_data[zb_data["vix_regime"] == vr]
            if len(sub) == 0:
                row += f"  {'N/A':>8s}"
            else:
                fr = (sub["category"] == "full_recovery").mean() * 100
                row += f"  {fr:>6.1f}%"
        # All VIX
        fr_all = (zb_data["category"] == "full_recovery").mean() * 100
        row += f"  {fr_all:>6.1f}%"
        print(row)

    # Test: does VIX add info beyond z-score?
    # Compare chi2 of zscore_only vs zscore+vix
    df_known_vix = df[df["vix_regime"] != "unknown"]
    if len(df_known_vix) > 100:
        chi2_z, p_z, _, v_z = compute_chi2(df_known_vix, "zscore_bucket")
        # Create combined variable
        df_known_vix = df_known_vix.copy()
        df_known_vix["z_vix"] = df_known_vix["zscore_bucket"] + "_" + df_known_vix["vix_regime"]
        chi2_zv, p_zv, _, v_zv = compute_chi2(df_known_vix, "z_vix")
        print(f"\n  Z-score only:  Cramér's V = {v_z:.4f}")
        print(f"  Z-score + VIX: Cramér's V = {v_zv:.4f}")
        print(f"  VIX marginal improvement:  {(v_zv - v_z) / v_z * 100:.1f}%")
        return v_z, v_zv
    return None, None


# ═══════════════════════════════════════════════════════════
# STEP 6: Optimal threshold search
# ═══════════════════════════════════════════════════════════

def threshold_search(df):
    """Try different z-score cutoffs and find optimal discrimination."""
    print("\n--- Threshold Search ---")
    cutoffs = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]

    results = []
    print(f"{'Cutoff':>8s}  {'Shallow%':>10s}  {'Deep%':>10s}  {'Ratio':>8s}  {'N_shallow':>10s}  {'N_deep':>10s}")
    for c in cutoffs:
        shallow = df[df["depth_z"] < c]
        deep = df[df["depth_z"] >= c]

        fr_s = (shallow["category"] == "full_recovery").mean() * 100 if len(shallow) > 0 else 0
        fr_d = (deep["category"] == "full_recovery").mean() * 100 if len(deep) > 0 else 0
        ratio = fr_s / fr_d if fr_d > 0 else float("inf")

        print(f"{c:>8.2f}σ  {fr_s:>9.1f}%  {fr_d:>9.1f}%  {ratio:>8.2f}  {len(shallow):>10d}  {len(deep):>10d}")
        results.append({
            "cutoff": c,
            "fr_shallow": fr_s,
            "fr_deep": fr_d,
            "disc_ratio": ratio,
            "n_shallow": len(shallow),
            "n_deep": len(deep),
        })

    return pd.DataFrame(results)


# ═══════════════════════════════════════════════════════════
# PLOTS
# ═══════════════════════════════════════════════════════════

def make_plots(df, raw_table, zscore_table, threshold_df):
    """Generate comparison plots."""

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # 1. Raw % vs Z-score: side-by-side full recovery rates
    ax = axes[0, 0]
    x = np.arange(3)
    width = 0.35

    raw_groups = ["<0.5%", "0.5-1.0%", ">1.0%"]
    z_groups = ["<1σ", "1-2σ", ">2σ"]

    raw_fr = [raw_table.loc[raw_table["group"] == g, "full_recovery"].values[0]
              for g in raw_groups]
    z_fr = [zscore_table.loc[zscore_table["group"] == g, "full_recovery"].values[0]
            for g in z_groups]

    bars1 = ax.bar(x - width / 2, raw_fr, width, label="Raw %", color="#2196F3", alpha=0.8)
    bars2 = ax.bar(x + width / 2, z_fr, width, label="Z-Score", color="#FF9800", alpha=0.8)

    ax.set_xticks(x)
    ax.set_xticklabels(["Shallow", "Medium", "Deep"])
    ax.set_ylabel("Full Recovery %")
    ax.set_title("Full Recovery Rate: Raw % vs Z-Score Buckets")
    ax.legend()
    for bar in bars1:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                f"{bar.get_height():.1f}", ha="center", fontsize=8)
    for bar in bars2:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                f"{bar.get_height():.1f}", ha="center", fontsize=8)

    # 2. Raw % vs Z-score: failed recovery rates
    ax = axes[0, 1]
    raw_fail = [raw_table.loc[raw_table["group"] == g, "failed_recovery"].values[0]
                for g in raw_groups]
    z_fail = [zscore_table.loc[zscore_table["group"] == g, "failed_recovery"].values[0]
              for g in z_groups]

    bars1 = ax.bar(x - width / 2, raw_fail, width, label="Raw %", color="#2196F3", alpha=0.8)
    bars2 = ax.bar(x + width / 2, z_fail, width, label="Z-Score", color="#FF9800", alpha=0.8)

    ax.set_xticks(x)
    ax.set_xticklabels(["Shallow", "Medium", "Deep"])
    ax.set_ylabel("Failed Recovery %")
    ax.set_title("Failed Recovery Rate: Raw % vs Z-Score Buckets")
    ax.legend()
    for bar in bars1:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                f"{bar.get_height():.1f}", ha="center", fontsize=8)
    for bar in bars2:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                f"{bar.get_height():.1f}", ha="center", fontsize=8)

    # 3. Depth_z distribution by category
    ax = axes[1, 0]
    cats = ["full_recovery", "failed_recovery"]
    colors = ["#4CAF50", "#F44336"]
    for cat, color in zip(cats, colors):
        sub = df[df["category"] == cat]["depth_z"]
        ax.hist(sub, bins=50, alpha=0.5, color=color, label=cat, density=True)
    ax.set_xlabel("Depth Z-Score (σ)")
    ax.set_ylabel("Density")
    ax.set_title("Depth Z-Score Distribution: Full vs Failed Recovery")
    ax.legend()
    ax.set_xlim(0, 15)

    # 4. Threshold search: discrimination ratio
    ax = axes[1, 1]
    ax.plot(threshold_df["cutoff"], threshold_df["disc_ratio"],
            "o-", color="steelblue", linewidth=2, markersize=6)
    best_idx = threshold_df["disc_ratio"].idxmax()
    best = threshold_df.loc[best_idx]
    ax.axvline(best["cutoff"], color="red", linestyle="--", alpha=0.7,
               label=f"Best: {best['cutoff']:.2f}σ (ratio={best['disc_ratio']:.2f})")
    ax.set_xlabel("Z-Score Cutoff (σ)")
    ax.set_ylabel("Discrimination Ratio (Shallow/Deep Full Recovery)")
    ax.set_title("Optimal Z-Score Threshold Search")
    ax.legend()

    plt.suptitle("I4: Depth Z-Score Calibration", fontsize=14)
    plt.tight_layout()
    plt.savefig(OUT_DIR / "I4_depth_zscore_comparison.png", dpi=150)
    plt.close()
    print("\nSaved: I4_depth_zscore_comparison.png")

    # Heatmap: z-score × VIX → full recovery %
    fig, ax = plt.subplots(figsize=(8, 5))
    z_buckets = ["<1σ", "1-2σ", ">2σ"]
    vix_regimes = ["<20", "20-25", ">=25"]

    heatmap_data = np.zeros((len(z_buckets), len(vix_regimes)))
    for i, zb in enumerate(z_buckets):
        for j, vr in enumerate(vix_regimes):
            sub = df[(df["zscore_bucket"] == zb) & (df["vix_regime"] == vr)]
            if len(sub) > 0:
                heatmap_data[i, j] = (sub["category"] == "full_recovery").mean() * 100
            else:
                heatmap_data[i, j] = np.nan

    im = ax.imshow(heatmap_data, cmap="RdYlGn", aspect="auto", vmin=0, vmax=50)
    ax.set_xticks(range(len(vix_regimes)))
    ax.set_xticklabels(vix_regimes)
    ax.set_yticks(range(len(z_buckets)))
    ax.set_yticklabels(z_buckets)
    ax.set_xlabel("VIX Regime")
    ax.set_ylabel("Depth Z-Score")
    ax.set_title("Full Recovery % by Z-Score × VIX Regime")

    for i in range(len(z_buckets)):
        for j in range(len(vix_regimes)):
            val = heatmap_data[i, j]
            if not np.isnan(val):
                sub = df[(df["zscore_bucket"] == z_buckets[i]) & (df["vix_regime"] == vix_regimes[j])]
                ax.text(j, i, f"{val:.1f}%\nN={len(sub)}",
                        ha="center", va="center", fontsize=9,
                        color="black" if val > 20 else "white")

    plt.colorbar(im, ax=ax, label="Full Recovery %")
    plt.tight_layout()
    plt.savefig(OUT_DIR / "I4_zscore_vix_heatmap.png", dpi=150)
    plt.close()
    print("Saved: I4_zscore_vix_heatmap.png")


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def main():
    # ── STEP 1: Compute noon sigma ──
    print("=" * 60)
    print("STEP 1: Computing per-ticker noon sigma")
    print("=" * 60)
    sigma_df = compute_noon_sigma()
    sigma_df.to_csv(OUT_DIR / "I4_noon_sigma.csv", index=False)
    print(f"\nMean noon sigma across tickers: {sigma_df['noon_sigma'].mean():.4f}%")
    print(f"Range: {sigma_df['noon_sigma'].min():.4f}% ({sigma_df.loc[sigma_df['noon_sigma'].idxmin(), 'ticker']}) "
          f"to {sigma_df['noon_sigma'].max():.4f}% ({sigma_df.loc[sigma_df['noon_sigma'].idxmax(), 'ticker']})")

    # ── STEP 2-3: Add depth_z to I2 data ──
    print(f"\n{'=' * 60}")
    print("STEP 2-3: Computing depth_z and classifying")
    print("=" * 60)
    i2_df = pd.read_csv(I2_DATA)
    df = add_depth_z(i2_df, sigma_df)
    df.to_csv(OUT_DIR / "I4_depth_zscore_data.csv", index=False)

    print(f"Total events: {len(df)}")
    print(f"Depth_z stats: mean={df['depth_z'].mean():.2f}σ, "
          f"median={df['depth_z'].median():.2f}σ, "
          f"max={df['depth_z'].max():.1f}σ")

    for b in ["<1σ", "1-2σ", ">2σ"]:
        n = (df["zscore_bucket"] == b).sum()
        print(f"  {b}: {n} ({n / len(df) * 100:.1f}%)")

    # ── Raw % table (from I2) ──
    print(f"\n{'=' * 60}")
    print("STEP 3: Recovery outcome comparison")
    print("=" * 60)
    raw_table = print_category_table(df, "compression_bucket", "Raw % Buckets")
    zscore_table = print_category_table(df, "zscore_bucket", "Z-Score Buckets")

    # ── STEP 4: Separation quality ──
    print(f"\n{'=' * 60}")
    print("STEP 4: Separation quality")
    print("=" * 60)

    dr_raw = compute_discrimination_ratio(df, "compression_bucket", "<0.5%", ">1.0%")
    dr_z = compute_discrimination_ratio(df, "zscore_bucket", "<1σ", ">2σ")
    print(f"\nDiscrimination ratio (Full Recovery: Shallow/Deep):")
    print(f"  Raw %:   {dr_raw:.2f}x" if dr_raw else "  Raw %:   N/A (empty bucket)")
    print(f"  Z-Score: {dr_z:.2f}x" if dr_z else "  Z-Score: N/A (empty bucket)")
    if dr_raw and dr_z:
        print(f"  Winner:  {'Z-Score' if dr_z > dr_raw else 'Raw %'} "
              f"({'better' if dr_z > dr_raw else 'worse'} by "
              f"{abs(dr_z - dr_raw) / max(dr_raw, dr_z) * 100:.1f}%)")
    else:
        print("  (Cannot compare — one or both buckets empty)")

    chi2_raw, p_raw, dof_raw, v_raw = compute_chi2(df, "compression_bucket")
    chi2_z, p_z, dof_z, v_z = compute_chi2(df, "zscore_bucket")
    print(f"\nChi-squared test:")
    print(f"  Raw %:   χ²={chi2_raw:.1f}, p={p_raw:.2e}, Cramér's V={v_raw:.4f}")
    print(f"  Z-Score: χ²={chi2_z:.1f}, p={p_z:.2e}, Cramér's V={v_z:.4f}")
    print(f"  Winner:  {'Z-Score' if v_z > v_raw else 'Raw %'} "
          f"(Cramér's V {'higher' if v_z > v_raw else 'lower'} by "
          f"{abs(v_z - v_raw) / max(v_raw, v_z) * 100:.1f}%)")

    # ── STEP 5: VIX interaction ──
    print(f"\n{'=' * 60}")
    print("STEP 5: VIX interaction")
    print("=" * 60)
    v_z_only, v_z_vix = vix_interaction_analysis(df)

    # ── STEP 6: Threshold search ──
    print(f"\n{'=' * 60}")
    print("STEP 6: Optimal threshold search")
    print("=" * 60)
    threshold_df = threshold_search(df)

    best = threshold_df.loc[threshold_df["disc_ratio"].idxmax()]
    print(f"\nOptimal cutoff: {best['cutoff']:.2f}σ "
          f"(discrimination ratio = {best['disc_ratio']:.2f}x)")

    # ── PLOTS ──
    print(f"\n{'=' * 60}")
    print("Generating plots...")
    print("=" * 60)
    make_plots(df, raw_table, zscore_table, threshold_df)

    # ── FINAL VERDICT ──
    print(f"\n{'=' * 60}")
    print("FINAL VERDICT")
    print("=" * 60)
    if v_z > v_raw * 1.05:
        verdict = "Z-SCORE BETTER"
    elif v_raw > v_z * 1.05:
        verdict = "RAW % BETTER"
    else:
        verdict = "NO SIGNIFICANT DIFFERENCE"
    print(f"  Verdict: {verdict}")
    print(f"  Raw Cramér's V:     {v_raw:.4f}")
    print(f"  Z-Score Cramér's V: {v_z:.4f}")
    print(f"  Raw Disc Ratio:     {dr_raw:.2f}x" if dr_raw else "  Raw Disc Ratio:     N/A")
    print(f"  Z-Score Disc Ratio: {dr_z:.2f}x" if dr_z else "  Z-Score Disc Ratio: N/A")


if __name__ == "__main__":
    main()
