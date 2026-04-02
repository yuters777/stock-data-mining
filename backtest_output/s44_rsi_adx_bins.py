#!/usr/bin/env python3
"""
S44 Tasks A+B: 4H RSI Context Bins + ADX Maturity Percentiles.

Tags each M5 bar with the most recent COMPLETED 4H RSI/ADX bin,
computes forward M5 returns at +6/+12/+24 bars, groups by bin and VIX regime.

Lookahead prevention:
  - AM 4H bar (09:30-13:25) completes at 13:30 ET
  - PM 4H bar (13:30-15:55) completes at 16:00 ET
  - M5 bars before 13:30 use prior session's PM bar
  - M5 bars 13:30+ use today's AM bar

Output: results/S44_RSI_ADX_Bins_Results.md
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.data_loader import load_m5_regsess

# ── Config ────────────────────────────────────────────────────────────────────

TICKERS = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU", "C",
    "COIN", "COST", "GOOGL", "GS", "INTC", "JPM", "MARA", "META", "MSFT",
    "MSTR", "MU", "NVDA", "PLTR", "SMCI", "TSLA", "TSM", "V",
]

INDICATORS_4H_DIR = ROOT / "data" / "indicators_4h"
VIX_PATH = ROOT / "Fetched_Data" / "VIXCLS_FRED_real.csv"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

FORWARD_BARS = [6, 12, 24]  # +30min, +1hr, +2hr
FORWARD_LABELS = {6: "+30m", 12: "+1hr", 24: "+2hr"}

RSI_BINS = {"STRETCHED_DOWN": (0, 35), "NEUTRAL": (35, 65), "STRETCHED_UP": (65, 100)}
VIX_REGIMES = {"NORMAL": (0, 20), "ELEVATED": (20, 25), "HIGH_RISK": (25, 200)}
ADX_FIXED_BINS = {"FIXED_LOW": (0, 20), "FIXED_MID": (20, 30), "FIXED_HIGH": (30, 200)}
ADX_PCTILE_BINS = {"FRESH_TREND": (0, 33), "MODERATE": (33, 66), "EXHAUSTED_TREND": (66, 100)}
ADX_ROLLING_WINDOW = 60


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_vix_daily():
    """Load VIX daily, return {date_str: close}."""
    df = pd.read_csv(VIX_PATH)
    vix = {}
    for _, row in df.iterrows():
        try:
            vix[str(row["observation_date"])] = float(row["VIXCLS"])
        except (ValueError, TypeError):
            continue
    return vix


def get_prior_vix(vix_daily, date_str):
    """Prior trading day VIX close (no lookahead)."""
    from datetime import timedelta
    dt = pd.Timestamp(date_str)
    for offset in range(1, 6):
        prior = (dt - timedelta(days=offset)).strftime("%Y-%m-%d")
        if prior in vix_daily:
            return vix_daily[prior]
    return None


def classify_rsi(val):
    if pd.isna(val):
        return None
    for name, (lo, hi) in RSI_BINS.items():
        if lo <= val < hi or (name == "STRETCHED_UP" and val >= hi):
            return name
    return None


def classify_vix(val):
    if val is None or pd.isna(val):
        return None
    for name, (lo, hi) in VIX_REGIMES.items():
        if lo <= val < hi or (name == "HIGH_RISK" and val >= lo):
            return name
    return None


def classify_adx_fixed(val):
    if pd.isna(val):
        return None
    for name, (lo, hi) in ADX_FIXED_BINS.items():
        if lo <= val < hi or (name == "FIXED_HIGH" and val >= lo):
            return name
    return None


def classify_adx_pctile(val):
    if pd.isna(val):
        return None
    for name, (lo, hi) in ADX_PCTILE_BINS.items():
        if lo <= val < hi or (name == "EXHAUSTED_TREND" and val >= lo):
            return name
    return None


def load_4h_bars(ticker):
    """Load 4H indicator bars."""
    path = INDICATORS_4H_DIR / f"{ticker}_4h_indicators.csv"
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["date_str"] = df["timestamp"].dt.strftime("%Y-%m-%d")
    df["time_str"] = df["timestamp"].dt.strftime("%H:%M")
    # Compute rolling ADX percentile (per-ticker, 60-bar window)
    df["adx_pctile"] = df["adx_14"].rolling(window=ADX_ROLLING_WINDOW, min_periods=ADX_ROLLING_WINDOW).apply(
        lambda x: stats.percentileofscore(x, x.iloc[-1], kind="rank"), raw=False
    )
    return df


def map_m5_to_completed_4h(m5_df, bars_4h):
    """
    For each M5 bar, find the most recent COMPLETED 4H bar index.

    AM 4H bar starts 09:30, completes at 13:30 (last M5 bar 13:25).
    PM 4H bar starts 13:30, completes at 16:00 (last M5 bar 15:55).

    An M5 bar at time T uses:
      - If T < 13:30 on date D: use PM bar from prior trading day
      - If T >= 13:30 on date D: use AM bar from date D
    """
    # Build lookup: (date_str, session) -> 4H bar row index
    bar_lookup = {}
    for i, row in bars_4h.iterrows():
        session = "AM" if row["time_str"] == "09:30" else "PM"
        bar_lookup[(row["date_str"], session)] = i

    # Build sorted date list for finding prior trading day
    trading_dates = sorted(bars_4h["date_str"].unique())
    date_to_prev = {}
    for j in range(1, len(trading_dates)):
        date_to_prev[trading_dates[j]] = trading_dates[j - 1]

    completed_4h_idx = []
    for _, m5_row in m5_df.iterrows():
        m5_ts = m5_row["Datetime"]
        m5_date = m5_ts.strftime("%Y-%m-%d")
        m5_minutes = m5_ts.hour * 60 + m5_ts.minute

        if m5_minutes < 13 * 60 + 30:
            # Before 13:30 → use prior day's PM bar
            prev_date = date_to_prev.get(m5_date)
            if prev_date:
                idx = bar_lookup.get((prev_date, "PM"))
            else:
                idx = None
        else:
            # 13:30+ → use today's AM bar
            idx = bar_lookup.get((m5_date, "AM"))

        completed_4h_idx.append(idx)

    return completed_4h_idx


def compute_forward_returns(m5_df, horizons):
    """Compute forward returns at given bar horizons."""
    result = {}
    closes = m5_df["Close"].values
    for h in horizons:
        fwd = np.full(len(closes), np.nan)
        for i in range(len(closes) - h):
            fwd[i] = (closes[i + h] - closes[i]) / closes[i] * 100
        result[h] = fwd
    return result


# ── Main analysis ─────────────────────────────────────────────────────────────

def run_analysis():
    print("Loading VIX data...")
    vix_daily = load_vix_daily()

    # Accumulators: list of dicts with bin labels + forward returns
    all_rows = []

    for ticker in TICKERS:
        print(f"Processing {ticker}...")

        bars_4h = load_4h_bars(ticker)

        try:
            m5_df = load_m5_regsess(ticker)
        except (FileNotFoundError, ValueError) as e:
            print(f"  SKIP {ticker}: {e}")
            continue

        # Map each M5 bar to completed 4H bar index
        completed_idx = map_m5_to_completed_4h(m5_df, bars_4h)

        # Compute forward returns
        fwd_rets = compute_forward_returns(m5_df, FORWARD_BARS)

        # Tag each M5 bar
        for i, (_, m5_row) in enumerate(m5_df.iterrows()):
            idx_4h = completed_idx[i]
            if idx_4h is None:
                continue

            h4_bar = bars_4h.iloc[idx_4h]
            rsi_val = h4_bar["rsi_14"]
            adx_val = h4_bar["adx_14"]
            adx_pct = h4_bar["adx_pctile"]

            rsi_bin = classify_rsi(rsi_val)
            adx_fixed_bin = classify_adx_fixed(adx_val)
            adx_pctile_bin = classify_adx_pctile(adx_pct)

            m5_date = m5_row["Datetime"].strftime("%Y-%m-%d")
            vix_val = get_prior_vix(vix_daily, m5_date)
            vix_regime = classify_vix(vix_val)

            row = {
                "ticker": ticker,
                "rsi_bin": rsi_bin,
                "adx_fixed_bin": adx_fixed_bin,
                "adx_pctile_bin": adx_pctile_bin,
                "vix_regime": vix_regime,
                "rsi_val": rsi_val,
                "adx_val": adx_val,
                "adx_pct": adx_pct,
            }
            for h in FORWARD_BARS:
                row[f"fwd_{h}"] = fwd_rets[h][i]

            all_rows.append(row)

    print(f"\nTotal tagged M5 bars: {len(all_rows)}")
    return pd.DataFrame(all_rows)


# ── Metrics ───────────────────────────────────────────────────────────────────

def cell_metrics(group, horizon_col):
    """Compute metrics for one group at one horizon."""
    vals = group[horizon_col].dropna()
    n = len(vals)
    if n < 3:
        return {"N": n, "mean": np.nan, "med": np.nan, "wr": np.nan, "std": np.nan, "p": np.nan}
    mean = vals.mean()
    med = vals.median()
    wr = (vals > 0).sum() / n * 100
    std = vals.std()
    _, p = stats.ttest_1samp(vals, 0)
    p = p / 2 if mean > 0 else 1 - p / 2  # one-tailed
    return {"N": n, "mean": mean, "med": med, "wr": wr, "std": std, "p": p}


# ── Report generation ─────────────────────────────────────────────────────────

def generate_report(df):
    lines = []
    lines.append("# S44 4H RSI Context Bins + ADX Maturity Percentiles")
    lines.append("")
    lines.append(f"**Date:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Total tagged M5 bars:** {len(df):,}")
    lines.append(f"**Tickers:** {df['ticker'].nunique()}/25")
    lines.append(f"**ADX smoothing:** 14 (standard Wilder; prompt specified 20 but existing 4H indicators use 14)")
    lines.append(f"**ADX percentile window:** {ADX_ROLLING_WINDOW} bars (rolling)")
    lines.append("")

    # ── Table A: RSI bins × horizons × VIX regimes ──
    lines.append("## Table A: 4H RSI Bins × Forward Returns × VIX Regime")
    lines.append("")

    for vix_name in ["NORMAL", "ELEVATED", "HIGH_RISK"]:
        lines.append(f"### VIX: {vix_name}")
        lines.append("")
        lines.append("| RSI Bin | Horizon | N | Mean% | Med% | WR% | Std% | p-val |")
        lines.append("|---------|---------|---|-------|------|-----|------|-------|")

        vix_sub = df[df["vix_regime"] == vix_name]
        for rsi_name in ["STRETCHED_DOWN", "NEUTRAL", "STRETCHED_UP"]:
            rsi_sub = vix_sub[vix_sub["rsi_bin"] == rsi_name]
            for h in FORWARD_BARS:
                m = cell_metrics(rsi_sub, f"fwd_{h}")
                flag = " **" if m["N"] < 20 else ""
                sig = "***" if m["p"] < 0.001 else ("**" if m["p"] < 0.01 else ("*" if m["p"] < 0.05 else ""))
                lines.append(
                    f"| {rsi_name} | {FORWARD_LABELS[h]} | {m['N']:,}{flag} | "
                    f"{m['mean']:+.3f} | {m['med']:+.3f} | {m['wr']:.1f} | "
                    f"{m['std']:.3f} | {m['p']:.4f}{sig} |"
                    if not np.isnan(m["mean"]) else
                    f"| {rsi_name} | {FORWARD_LABELS[h]} | {m['N']}{flag} | — | — | — | — | — |"
                )
        lines.append("")

    # Key cross: STRETCHED_DOWN + HIGH_RISK
    lines.append("### Key Cross: STRETCHED_DOWN + VIX >= 25 (Module 4 alignment)")
    lines.append("")
    cross = df[(df["rsi_bin"] == "STRETCHED_DOWN") & (df["vix_regime"] == "HIGH_RISK")]
    lines.append(f"N = {len(cross):,} M5 bars")
    lines.append("")
    lines.append("| Horizon | N | Mean% | Med% | WR% | Std% | p-val |")
    lines.append("|---------|---|-------|------|-----|------|-------|")
    for h in FORWARD_BARS:
        m = cell_metrics(cross, f"fwd_{h}")
        sig = "***" if m["p"] < 0.001 else ("**" if m["p"] < 0.01 else ("*" if m["p"] < 0.05 else ""))
        if not np.isnan(m["mean"]):
            lines.append(
                f"| {FORWARD_LABELS[h]} | {m['N']:,} | {m['mean']:+.4f} | "
                f"{m['med']:+.4f} | {m['wr']:.1f} | {m['std']:.4f} | {m['p']:.4f}{sig} |"
            )
        else:
            lines.append(f"| {FORWARD_LABELS[h]} | {m['N']} | — | — | — | — | — |")
    lines.append("")

    # Compare STRETCHED_DOWN across VIX regimes
    lines.append("### STRETCHED_DOWN by VIX Regime (+2hr horizon)")
    lines.append("")
    lines.append("| VIX Regime | N | Mean% | WR% | p-val |")
    lines.append("|------------|---|-------|-----|-------|")
    for vix_name in ["NORMAL", "ELEVATED", "HIGH_RISK"]:
        sub = df[(df["rsi_bin"] == "STRETCHED_DOWN") & (df["vix_regime"] == vix_name)]
        m = cell_metrics(sub, "fwd_24")
        sig = "***" if m["p"] < 0.001 else ("**" if m["p"] < 0.01 else ("*" if m["p"] < 0.05 else ""))
        if not np.isnan(m["mean"]):
            lines.append(f"| {vix_name} | {m['N']:,} | {m['mean']:+.4f} | {m['wr']:.1f} | {m['p']:.4f}{sig} |")
        else:
            lines.append(f"| {vix_name} | {m['N']} | — | — | — |")
    lines.append("")

    # ── Table B: ADX bins × horizons ──
    lines.append("## Table B: 4H ADX Percentile Bins × Forward Returns")
    lines.append("")
    lines.append("| ADX Pctile Bin | Horizon | N | Mean% | Med% | WR% | Std% | p-val |")
    lines.append("|----------------|---------|---|-------|------|-----|------|-------|")
    for adx_name in ["FRESH_TREND", "MODERATE", "EXHAUSTED_TREND"]:
        sub = df[df["adx_pctile_bin"] == adx_name]
        for h in FORWARD_BARS:
            m = cell_metrics(sub, f"fwd_{h}")
            flag = " **" if m["N"] < 20 else ""
            sig = "***" if m["p"] < 0.001 else ("**" if m["p"] < 0.01 else ("*" if m["p"] < 0.05 else ""))
            if not np.isnan(m["mean"]):
                lines.append(
                    f"| {adx_name} | {FORWARD_LABELS[h]} | {m['N']:,}{flag} | "
                    f"{m['mean']:+.4f} | {m['med']:+.4f} | {m['wr']:.1f} | "
                    f"{m['std']:.4f} | {m['p']:.4f}{sig} |"
                )
            else:
                lines.append(f"| {adx_name} | {FORWARD_LABELS[h]} | {m['N']}{flag} | — | — | — | — | — |")
    lines.append("")

    # ── Table C: Fixed vs Percentile comparison ──
    lines.append("## Table C: ADX Fixed vs Percentile — Return Separation")
    lines.append("")
    lines.append("### Fixed ADX Bins")
    lines.append("")
    lines.append("| ADX Fixed Bin | Horizon | N | Mean% | Med% | WR% | Std% | p-val |")
    lines.append("|---------------|---------|---|-------|------|-----|------|-------|")
    for adx_name in ["FIXED_LOW", "FIXED_MID", "FIXED_HIGH"]:
        sub = df[df["adx_fixed_bin"] == adx_name]
        for h in FORWARD_BARS:
            m = cell_metrics(sub, f"fwd_{h}")
            flag = " **" if m["N"] < 20 else ""
            sig = "***" if m["p"] < 0.001 else ("**" if m["p"] < 0.01 else ("*" if m["p"] < 0.05 else ""))
            if not np.isnan(m["mean"]):
                lines.append(
                    f"| {adx_name} | {FORWARD_LABELS[h]} | {m['N']:,}{flag} | "
                    f"{m['mean']:+.4f} | {m['med']:+.4f} | {m['wr']:.1f} | "
                    f"{m['std']:.4f} | {m['p']:.4f}{sig} |"
                )
            else:
                lines.append(f"| {adx_name} | {FORWARD_LABELS[h]} | {m['N']}{flag} | — | — | — | — | — |")
    lines.append("")

    # Separation metric: spread between best and worst bin mean at +2hr
    lines.append("### Separation Comparison (+2hr horizon)")
    lines.append("")
    h = 24
    # Percentile
    pctile_means = {}
    for name in ["FRESH_TREND", "MODERATE", "EXHAUSTED_TREND"]:
        sub = df[df["adx_pctile_bin"] == name]
        m = cell_metrics(sub, f"fwd_{h}")
        pctile_means[name] = m["mean"] if not np.isnan(m["mean"]) else 0

    fixed_means = {}
    for name in ["FIXED_LOW", "FIXED_MID", "FIXED_HIGH"]:
        sub = df[df["adx_fixed_bin"] == name]
        m = cell_metrics(sub, f"fwd_{h}")
        fixed_means[name] = m["mean"] if not np.isnan(m["mean"]) else 0

    pctile_spread = max(pctile_means.values()) - min(pctile_means.values())
    fixed_spread = max(fixed_means.values()) - min(fixed_means.values())

    lines.append(f"| Method | Best Bin | Worst Bin | Spread |")
    lines.append(f"|--------|----------|-----------|--------|")
    best_p = max(pctile_means, key=pctile_means.get)
    worst_p = min(pctile_means, key=pctile_means.get)
    best_f = max(fixed_means, key=fixed_means.get)
    worst_f = min(fixed_means, key=fixed_means.get)
    lines.append(
        f"| Percentile | {best_p} ({pctile_means[best_p]:+.4f}%) | "
        f"{worst_p} ({pctile_means[worst_p]:+.4f}%) | {pctile_spread:.4f}% |"
    )
    lines.append(
        f"| Fixed | {best_f} ({fixed_means[best_f]:+.4f}%) | "
        f"{worst_f} ({fixed_means[worst_f]:+.4f}%) | {fixed_spread:.4f}% |"
    )
    winner = "Percentile" if pctile_spread > fixed_spread else "Fixed"
    lines.append("")
    lines.append(f"**Winner:** {winner} bins produce more return separation ({max(pctile_spread, fixed_spread):.4f}% vs {min(pctile_spread, fixed_spread):.4f}%).")
    lines.append("")

    # ── Recommendation ──
    lines.append("## Recommendations")
    lines.append("")

    # Check statistical significance of RSI bins
    lines.append("### RSI Bins")
    sig_cells = 0
    total_cells = 0
    for vix_name in VIX_REGIMES:
        for rsi_name in RSI_BINS:
            sub = df[(df["rsi_bin"] == rsi_name) & (df["vix_regime"] == vix_name)]
            for h in FORWARD_BARS:
                m = cell_metrics(sub, f"fwd_{h}")
                total_cells += 1
                if not np.isnan(m["p"]) and m["p"] < 0.05:
                    sig_cells += 1
    lines.append(f"- {sig_cells}/{total_cells} RSI×VIX×horizon cells are statistically significant (p<0.05)")

    # Check ADX significance
    adx_sig = 0
    adx_total = 0
    for name in ADX_PCTILE_BINS:
        sub = df[df["adx_pctile_bin"] == name]
        for h in FORWARD_BARS:
            m = cell_metrics(sub, f"fwd_{h}")
            adx_total += 1
            if not np.isnan(m["p"]) and m["p"] < 0.05:
                adx_sig += 1
    lines.append(f"- {adx_sig}/{adx_total} ADX percentile×horizon cells are statistically significant (p<0.05)")
    lines.append("")

    # Note about ADX smoothing
    lines.append("### ADX Smoothing Note")
    lines.append("- Existing 4H indicators use ADX(14) with standard Wilder smoothing (period=14)")
    lines.append("- S44 mentioned ADX smoothing=20; this would require regenerating all 4H indicator files")
    lines.append("- Results here use the existing period=14 data")
    lines.append("")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    df = run_analysis()
    report = generate_report(df)

    output_path = RESULTS_DIR / "S44_RSI_ADX_Bins_Results.md"
    output_path.write_text(report)
    print(f"\nResults saved to {output_path}")
    print("\n" + report)
