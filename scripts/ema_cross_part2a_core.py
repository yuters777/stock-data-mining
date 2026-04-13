#!/usr/bin/env python3
"""
EMA Cross Falsification Study — Part 2a: Core Analysis

Primary verdict on Standing Rejection #22:
"4H EMA9/21 cross as return predictor — Negative, filter only."

Tests: unconditional UP cross forward returns, Config G conditional,
VIX regime split, cluster-robust bootstrap, trade simulation gate.
"""

import os
import datetime
import numpy as np
import pandas as pd
from scipy import stats

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(BASE, "results", "ema_cross_falsification")

HORIZONS = [1, 3, 5, 10, 20]


# ── Forward return computation ────────────────────────────────────────────────

def compute_forward_returns(events_df, bars_by_ticker):
    """
    For each event, compute forward returns/MFE/MAE/stop_hit at each horizon.
    bars_by_ticker: dict{ticker -> DataFrame with reset_index}.
    """
    results = []
    for _, ev in events_df.iterrows():
        ticker = ev["ticker"]
        idx = int(ev["bar_idx"])
        tb = bars_by_ticker.get(ticker)
        if tb is None:
            continue

        entry_close = ev["close"]
        cross_low = ev["low"]
        row = {"ticker": ticker, "date": ev["date"], "bar_idx": idx,
               "entry_close": entry_close}

        for h in HORIZONS:
            if idx + h >= len(tb):
                row[f"fwd_{h}"] = np.nan
                row[f"mfe_{h}"] = np.nan
                row[f"mae_{h}"] = np.nan
                row[f"stop_{h}"] = np.nan
                continue

            fwd_close = tb.loc[idx + h, "Close"]
            row[f"fwd_{h}"] = (fwd_close - entry_close) / entry_close * 100

            window = tb.loc[idx + 1: idx + h]
            row[f"mfe_{h}"] = (window["High"].max() - entry_close) / entry_close * 100
            row[f"mae_{h}"] = (window["Low"].min() - entry_close) / entry_close * 100
            row[f"stop_{h}"] = int(window["Low"].min() < cross_low)

        # EMA spread at bar+1, +3, +5 for stall analysis
        for offset in [1, 3, 5]:
            if idx + offset < len(tb):
                row[f"spread_{offset}"] = tb.loc[idx + offset, "ema_spread_pct"]
            else:
                row[f"spread_{offset}"] = np.nan

        results.append(row)

    return pd.DataFrame(results)


def print_fwd_table(df, label, horizons=None):
    """Print formatted forward return table."""
    if horizons is None:
        horizons = HORIZONS
    print(f"\n{label} (N = {len(df)})")
    header = f"{'Horizon':>8} {'N':>5} {'Mean%':>8} {'Med%':>8} {'WR%':>7} {'MFE%':>8} {'MAE%':>8} {'Stop%':>7}"
    print(header)
    print("-" * len(header))
    rows = []
    for h in horizons:
        col = f"fwd_{h}"
        valid = df[col].dropna()
        n = len(valid)
        if n == 0:
            print(f"{'+'+ str(h):>8} {'0':>5} {'---':>8} {'---':>8} {'---':>7} {'---':>8} {'---':>8} {'---':>7}")
            continue
        mean = valid.mean()
        med = valid.median()
        wr = (valid > 0).mean() * 100
        mfe = df[f"mfe_{h}"].dropna().mean()
        mae = df[f"mae_{h}"].dropna().mean()
        stop = df[f"stop_{h}"].dropna().mean() * 100
        print(f"{'+'+ str(h):>8} {n:>5} {mean:>+8.3f} {med:>+8.3f} {wr:>7.1f} {mfe:>+8.3f} {mae:>+8.3f} {stop:>7.1f}")
        rows.append({"horizon": h, "N": n, "mean_pct": round(mean, 4),
                      "median_pct": round(med, 4), "wr_pct": round(wr, 2),
                      "mfe_mean_pct": round(mfe, 4), "mae_mean_pct": round(mae, 4),
                      "stop_hit_pct": round(stop, 2)})
    return pd.DataFrame(rows)


# ── Cluster-robust bootstrap ─────────────────────────────────────────────────

def cluster_bootstrap(df, value_col, n_boot=10000, seed=42):
    """Bootstrap resampling by ticker cluster. Returns (lo_2.5, hi_97.5)."""
    rng = np.random.RandomState(seed)
    tickers = df["ticker"].unique()
    groups = {t: df.loc[df["ticker"] == t, value_col].values for t in tickers}
    means = np.empty(n_boot)
    for i in range(n_boot):
        sample = rng.choice(tickers, size=len(tickers), replace=True)
        vals = np.concatenate([groups[t] for t in sample])
        means[i] = vals.mean()
    return np.percentile(means, [2.5, 97.5])


def stat_summary(df, value_col, label):
    """Print cluster bootstrap CI and t-test for a forward return column."""
    valid = df[[value_col, "ticker"]].dropna()
    if len(valid) < 5:
        print(f"  {label}: insufficient data (N={len(valid)})")
        return None

    vals = valid[value_col].values
    mean = vals.mean()
    t_stat, p_val = stats.ttest_1samp(vals, 0)
    ci = cluster_bootstrap(valid, value_col)

    print(f"  {label}: mean={mean:+.3f}%, 95% CI=[{ci[0]:+.3f}, {ci[1]:+.3f}], "
          f"t={t_stat:.2f}, p={p_val:.4f}")
    return {"label": label, "mean": round(mean, 4), "ci_lo": round(ci[0], 4),
            "ci_hi": round(ci[1], 4), "t_stat": round(t_stat, 3), "p_value": round(p_val, 5)}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("EMA CROSS FALSIFICATION — Part 2a: Core Analysis")
    print("Standing Rejection #22 Test on 5yr Data")
    print("=" * 70)

    # Load data
    events = pd.read_csv(os.path.join(RESULTS, "ema_cross_events.csv"))
    bars = pd.read_parquet(os.path.join(RESULTS, "all_4h_bars.parquet"))

    # Build per-ticker bar lookup (reset_index so bar_idx maps directly)
    bars_by_ticker = {}
    for t, grp in bars.groupby("ticker"):
        bars_by_ticker[t] = grp.reset_index(drop=True)

    up = events[events["direction"] == "UP"].copy()
    print(f"\nTotal crosses: {len(events)} ({len(up)} UP, {len(events) - len(up)} DOWN)")
    print(f"Tickers: {events['ticker'].nunique()}")

    # ── Compute forward returns for all UP crosses ────────────────────────────
    print("\nComputing forward returns...")
    fwd = compute_forward_returns(up, bars_by_ticker)
    # Merge event metadata
    fwd = fwd.merge(up[["ticker", "bar_idx", "vix_prior_close", "adx", "adx_slope",
                         "rsi", "bar_slot", "is_anomaly_bar", "ema_spread_pct"]],
                     on=["ticker", "bar_idx"], how="left")

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 1: Unconditional
    # ══════════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("SECTION 1: UNCONDITIONAL UP CROSS FORWARD RETURNS")
    print("=" * 70)
    tbl_uncond = print_fwd_table(fwd, "ALL UP CROSSES")

    # PRIMARY FALSIFICATION CHECK
    mean5 = fwd["fwd_5"].dropna().mean()
    mean10 = fwd["fwd_10"].dropna().mean()
    sr22_confirmed = (mean5 <= 0) and (mean10 <= 0)

    print(f"\n  ** Mean at +5 = {mean5:+.3f}%, Mean at +10 = {mean10:+.3f}% **")
    if sr22_confirmed:
        print("  >> PRIMARY FALSIFICATION: SR #22 CONFIRMED (both ≤ 0)")
    else:
        print("  >> Positive returns detected — further analysis needed")

    # Stats
    print("\nStatistics (cluster-robust bootstrap by ticker):")
    stats_uncond = []
    for h in [5, 10]:
        s = stat_summary(fwd, f"fwd_{h}", f"Unconditional +{h}")
        if s:
            stats_uncond.append(s)

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 2: Config G
    # ══════════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("SECTION 2: CONFIG G — ELEVATED VIX + FRESH ADX RISING")
    print("=" * 70)

    mask_g = ((fwd["vix_prior_close"] >= 20) & (fwd["vix_prior_close"] < 25) &
              (fwd["adx"] < 20) & (fwd["adx_slope"] > 0))
    fwd_g = fwd[mask_g]
    print(f"\nConfig G filter: VIX [20,25) AND ADX<20 AND adx_slope>0")
    print(f"  N = {len(fwd_g)} ({len(fwd_g)/len(fwd)*100:.1f}% of {len(fwd)} UP crosses)")

    stats_g = []
    if len(fwd_g) >= 15:
        tbl_g = print_fwd_table(fwd_g, "CONFIG G")
        print("\nStatistics:")
        for h in [5, 10]:
            s = stat_summary(fwd_g, f"fwd_{h}", f"Config G +{h}")
            if s:
                stats_g.append(s)
    else:
        print(f"  ** Insufficient N ({len(fwd_g)}) — cannot draw conclusions **")
        tbl_g = pd.DataFrame()

    # G-relaxed if N < 30
    if len(fwd_g) < 30:
        mask_gr = ((fwd["vix_prior_close"] >= 20) & (fwd["vix_prior_close"] < 25) &
                   (fwd["adx"] < 25))
        fwd_gr = fwd[mask_gr]
        print(f"\nConfig G-RELAXED: VIX [20,25) AND ADX<25 (any slope)")
        print(f"  N = {len(fwd_gr)} ({len(fwd_gr)/len(fwd)*100:.1f}%)")
        if len(fwd_gr) >= 15:
            tbl_gr = print_fwd_table(fwd_gr, "CONFIG G-RELAXED")
            print("\nStatistics:")
            for h in [5, 10]:
                stat_summary(fwd_gr, f"fwd_{h}", f"G-relaxed +{h}")
        else:
            print(f"  ** Insufficient N ({len(fwd_gr)}) **")

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 3: VIX Regime Split
    # ══════════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("SECTION 3: VIX REGIME SPLIT (UP CROSSES)")
    print("=" * 70)

    vix_rows = []
    for label, lo, hi in [("NORMAL (<20)", 0, 20), ("ELEVATED [20,25)", 20, 25),
                           ("HIGH_RISK (≥25)", 25, 999)]:
        mask = (fwd["vix_prior_close"] >= lo) & (fwd["vix_prior_close"] < hi)
        sub = fwd[mask]
        if len(sub) < 5:
            print(f"\n{label}: N={len(sub)} — skipped")
            continue
        tbl = print_fwd_table(sub, label, horizons=[5, 10])
        for _, r in tbl.iterrows():
            r_dict = r.to_dict()
            r_dict["vix_bucket"] = label
            vix_rows.append(r_dict)

    tbl_vix = pd.DataFrame(vix_rows) if vix_rows else pd.DataFrame()

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 4: Trade Simulation Gate
    # ══════════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("SECTION 4: TRADE SIMULATION GATE")
    print("=" * 70)

    gate_pass = False
    if len(fwd_g) >= 15:
        g_mean5 = fwd_g["fwd_5"].dropna().mean()
        g_valid5 = fwd_g["fwd_5"].dropna().values
        _, g_p5 = stats.ttest_1samp(g_valid5, 0) if len(g_valid5) >= 5 else (0, 1.0)
        print(f"\n  Config G at +5: mean={g_mean5:+.3f}%, p={g_p5:.4f}")
        gate_pass = (g_mean5 > 0.5) and (g_p5 < 0.10)

    if gate_pass:
        print("\n  >> NARROW POCKET FOUND — trade simulation warranted")
        print("     (Config G mean > 0.5% at bar+5 AND p < 0.10)")
    else:
        print("\n  >> SR #22 CONFIRMED on 5yr data. No standalone entry edge.")
        print("     Recommendation: Keep EMA cross as Module 2 permission filter only.")
        print("     Trade simulation SKIPPED (gate not met).")

    # ══════════════════════════════════════════════════════════════════════════
    # Save outputs
    # ══════════════════════════════════════════════════════════════════════════
    tbl_uncond.to_csv(os.path.join(RESULTS, "forward_returns_unconditional.csv"), index=False)
    if not tbl_g.empty:
        tbl_g.to_csv(os.path.join(RESULTS, "forward_returns_config_g.csv"), index=False)
    if not tbl_vix.empty:
        tbl_vix.to_csv(os.path.join(RESULTS, "forward_returns_by_vix.csv"), index=False)

    # Summary report
    today = datetime.date.today().isoformat()
    verdict = "NARROW POCKET FOUND" if gate_pass else "SR #22 CONFIRMED"
    recommendation = ("Trade simulation warranted for Config G pocket"
                      if gate_pass
                      else "Keep EMA cross as Module 2 permission filter only")

    report = f"""EMA CROSS FALSIFICATION — SUMMARY REPORT
Date: {today}
Data: {events['ticker'].nunique()} tickers, 5yr M5 → 4H bars
Cross events: {len(up)} UP, {len(events) - len(up)} DOWN

VERDICT: {verdict}

UNCONDITIONAL UP CROSS:
  Mean return at bar+5:  {mean5:+.4f}%
  Mean return at bar+10: {mean10:+.4f}%"""

    for s in stats_uncond:
        report += f"\n  {s['label']}: 95% CI=[{s['ci_lo']:+.4f}, {s['ci_hi']:+.4f}], p={s['p_value']:.5f}"

    if len(fwd_g) >= 15:
        g_mean5_v = fwd_g["fwd_5"].dropna().mean()
        g_mean10_v = fwd_g["fwd_10"].dropna().mean()
        report += f"""

CONFIG G (VIX [20,25) + ADX<20 + rising):
  N: {len(fwd_g)}
  Mean return at bar+5:  {g_mean5_v:+.4f}%
  Mean return at bar+10: {g_mean10_v:+.4f}%"""
        for s in stats_g:
            report += f"\n  {s['label']}: 95% CI=[{s['ci_lo']:+.4f}, {s['ci_hi']:+.4f}], p={s['p_value']:.5f}"
    else:
        report += f"\n\nCONFIG G: Insufficient N ({len(fwd_g)})"

    report += f"""

VIX REGIME SPLIT (bar+5 mean):"""
    for label, lo, hi in [("NORMAL", 0, 20), ("ELEVATED", 20, 25), ("HIGH_RISK", 25, 999)]:
        mask = (fwd["vix_prior_close"] >= lo) & (fwd["vix_prior_close"] < hi)
        sub = fwd[mask]["fwd_5"].dropna()
        if len(sub) >= 5:
            report += f"\n  {label:12s}: N={len(sub):4d}, mean={sub.mean():+.4f}%"

    report += f"""

RECOMMENDATION: {recommendation}
"""

    report_path = os.path.join(RESULTS, "summary_report.txt")
    with open(report_path, "w") as f:
        f.write(report)
    print(f"\nSaved: {report_path}")
    print(f"Saved: forward_returns_unconditional.csv")
    if not tbl_g.empty:
        print(f"Saved: forward_returns_config_g.csv")
    if not tbl_vix.empty:
        print(f"Saved: forward_returns_by_vix.csv")

    print("\n" + "=" * 70)
    print(f"FINAL VERDICT: {verdict}")
    print("=" * 70)


if __name__ == "__main__":
    main()
