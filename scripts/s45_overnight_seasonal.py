#!/usr/bin/env python3
"""
S45 Overnight V5 — Seasonal Decomposition
Tests whether overnight V5 edge is concentrated in strong months (Nov-Apr)
vs weak months (May-Oct), with monthly breakdown and walk-forward stability.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import time
from scipy import stats

# ── paths ──
ROOT = Path(__file__).resolve().parent.parent
REGSESS_DIR = ROOT / "backtest_output"
VIX_PATH = ROOT / "Fetched_Data" / "VIXCLS_FRED_real.csv"
EMA4H_DIR = ROOT / "data" / "indicators_4h"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# 25 equity tickers — exclude SPY, VIXY
TICKERS = [
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN", "COST",
    "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU", "NVDA", "PLTR",
    "SNOW", "TSLA", "TSM", "TXN", "V",
]

MONTH_NAMES = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
               7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
STRONG_MONTHS = {11, 12, 1, 2, 3, 4}  # Nov-Apr
WEAK_MONTHS = {5, 6, 7, 8, 9, 10}     # May-Oct


# ═══════════════════════════════════════════════════════════════
# Data loading (same pipeline as prior S45 scripts)
# ═══════════════════════════════════════════════════════════════

def load_daily_ohlc():
    rows = []
    for ticker in TICKERS:
        path = REGSESS_DIR / f"{ticker}_m5_regsess_FIXED.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, parse_dates=["Datetime"])
        df["date"] = df["Datetime"].dt.date
        df["t"] = df["Datetime"].dt.time
        for date, grp in df.groupby("date"):
            first_bar = grp[grp["t"] == time(9, 30)]
            last_bar = grp[grp["t"] == time(15, 55)]
            if first_bar.empty or last_bar.empty:
                continue
            rows.append({
                "ticker": ticker, "date": date,
                "open": first_bar.iloc[0]["Open"],
                "close": last_bar.iloc[0]["Close"],
                "dow": pd.Timestamp(date).dayofweek,
            })
    daily = pd.DataFrame(rows)
    daily["date"] = pd.to_datetime(daily["date"])
    daily.sort_values(["ticker", "date"], inplace=True)
    daily.reset_index(drop=True, inplace=True)
    return daily


def load_vix():
    vix = pd.read_csv(VIX_PATH, parse_dates=["observation_date"])
    vix.rename(columns={"observation_date": "date", "VIXCLS": "vix"}, inplace=True)
    vix["vix"] = pd.to_numeric(vix["vix"], errors="coerce")
    vix.dropna(subset=["vix"], inplace=True)
    vix.sort_values("date", inplace=True)
    vix["prior_vix"] = vix["vix"].shift(1)
    return vix[["date", "prior_vix"]].dropna()


def compute_adx_custom(highs, lows, closes, dm_period=14, adx_smooth=20):
    n = len(highs)
    adx = np.full(n, np.nan)
    if n < dm_period + adx_smooth:
        return adx
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hc, lc)
    pdm = np.zeros(n)
    mdm = np.zeros(n)
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        pdm[i] = up if (up > down and up > 0) else 0.0
        mdm[i] = down if (down > up and down > 0) else 0.0
    atr_s = np.zeros(n)
    pdm_s = np.zeros(n)
    mdm_s = np.zeros(n)
    atr_s[dm_period] = np.sum(tr[1:dm_period + 1])
    pdm_s[dm_period] = np.sum(pdm[1:dm_period + 1])
    mdm_s[dm_period] = np.sum(mdm[1:dm_period + 1])
    for i in range(dm_period + 1, n):
        atr_s[i] = atr_s[i - 1] - atr_s[i - 1] / dm_period + tr[i]
        pdm_s[i] = pdm_s[i - 1] - pdm_s[i - 1] / dm_period + pdm[i]
        mdm_s[i] = mdm_s[i - 1] - mdm_s[i - 1] / dm_period + mdm[i]
    dx = np.full(n, np.nan)
    for i in range(dm_period, n):
        if atr_s[i] > 0:
            pdi = 100.0 * pdm_s[i] / atr_s[i]
            mdi = 100.0 * mdm_s[i] / atr_s[i]
        else:
            pdi = mdi = 0.0
        di_sum = pdi + mdi
        dx[i] = 100.0 * abs(pdi - mdi) / di_sum if di_sum > 0 else 0.0
    adx_start = dm_period + adx_smooth - 1
    if n > adx_start:
        adx[adx_start] = np.nanmean(dx[dm_period:adx_start + 1])
        for i in range(adx_start + 1, n):
            if not np.isnan(dx[i]):
                adx[i] = (adx[i - 1] * (adx_smooth - 1) + dx[i]) / adx_smooth
    return adx


def load_4h_indicators():
    rows = []
    for ticker in TICKERS:
        path = EMA4H_DIR / f"{ticker}_4h_indicators.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, parse_dates=["timestamp"])
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        adx_20 = compute_adx_custom(highs, lows, closes, dm_period=14, adx_smooth=20)
        df["adx_14_s20"] = adx_20
        df.dropna(subset=["ema_9", "ema_21"], inplace=True)
        if df.empty:
            continue
        df["date"] = df["timestamp"].dt.date
        eod = df.groupby("date").last().reset_index()
        eod["ema_gate_up"] = eod["ema_9"] > eod["ema_21"]
        eod["date"] = pd.to_datetime(eod["date"])
        eod.sort_values("date", inplace=True)
        for _, row in eod.iterrows():
            rows.append({
                "ticker": ticker, "date": row["date"],
                "ema_gate_up": row["ema_gate_up"],
                "adx_14_s20": row["adx_14_s20"],
            })
    return pd.DataFrame(rows)


def build_v5_overnight(daily, indicators_df, vix_df):
    """Apply V5 filter, skip Friday→Monday. Tag with entry month."""
    records = []
    merged = daily.merge(indicators_df, on=["ticker", "date"], how="inner")
    merged = merged.merge(vix_df, on="date", how="left")
    merged.dropna(subset=["prior_vix", "adx_14_s20"], inplace=True)

    for ticker, grp in merged.groupby("ticker"):
        grp = grp.sort_values("date").reset_index(drop=True)
        ticker_daily = daily[daily["ticker"] == ticker].sort_values("date").reset_index(drop=True)
        date_to_idx = {d: i for i, d in enumerate(ticker_daily["date"])}

        for _, row in grp.iterrows():
            if not row["ema_gate_up"]:
                continue
            if row["adx_14_s20"] >= 20:
                continue
            if row["prior_vix"] >= 25:
                continue
            if row["dow"] == 4:  # skip Friday→Monday
                continue

            idx = date_to_idx.get(row["date"])
            if idx is None or idx + 1 >= len(ticker_daily):
                continue
            next_row = ticker_daily.iloc[idx + 1]
            days_gap = (next_row["date"] - row["date"]).days
            if days_gap > 3:
                continue

            overnight_ret = (next_row["open"] / row["close"]) - 1
            entry_month = row["date"].month

            records.append({
                "ticker": ticker,
                "date": row["date"],
                "overnight_ret": overnight_ret,
                "entry_month": entry_month,
            })

    result = pd.DataFrame(records)
    result.sort_values("date", inplace=True)
    result.reset_index(drop=True, inplace=True)
    return result


# ═══════════════════════════════════════════════════════════════
# Statistics helper
# ═══════════════════════════════════════════════════════════════

def compute_stats(rets, label=""):
    n = len(rets)
    if n == 0:
        return {"label": label, "N": 0, "mean": np.nan, "std": np.nan,
                "sharpe": np.nan, "win_rate": np.nan, "t_stat": np.nan, "p_value": np.nan}
    mean_ret = np.mean(rets) * 100
    std_ret = np.std(rets, ddof=1) * 100
    sharpe = (np.mean(rets) / np.std(rets, ddof=1) * np.sqrt(252)) if np.std(rets, ddof=1) > 0 else np.nan
    win_rate = np.mean(rets > 0) * 100
    t_stat, p_value = stats.ttest_1samp(rets, 0)
    return {"label": label, "N": n, "mean": mean_ret, "std": std_ret,
            "sharpe": sharpe, "win_rate": win_rate, "t_stat": t_stat, "p_value": p_value}


# ═══════════════════════════════════════════════════════════════
# Report generation
# ═══════════════════════════════════════════════════════════════

def generate_report(v5_df):
    lines = []

    date_range = f"{v5_df['date'].min().strftime('%Y-%m-%d')} → {v5_df['date'].max().strftime('%Y-%m-%d')}"

    # ── Test A: Monthly Breakdown ──
    lines.append("MONTHLY BREAKDOWN — OVERNIGHT V5")
    lines.append("=" * 50)
    lines.append(f"Full sample: {date_range}, N={len(v5_df)}")
    lines.append("")

    for m in range(1, 13):
        rets = v5_df.loc[v5_df["entry_month"] == m, "overnight_ret"].values
        s = compute_stats(rets, MONTH_NAMES[m])
        season_tag = "S" if m in STRONG_MONTHS else "W"
        if s["N"] == 0:
            lines.append(f"{MONTH_NAMES[m]:>3s} [{season_tag}]:  N=   0 | (no data)")
        else:
            lines.append(f"{MONTH_NAMES[m]:>3s} [{season_tag}]:  N={s['N']:>4d} | Mean={s['mean']:+.4f}% | "
                         f"WR={s['win_rate']:.1f}% | t={s['t_stat']:+.3f} | p={s['p_value']:.4f}")

    lines.append("")
    lines.append("")

    # ── Test B: Strong vs Weak Season ──
    lines.append("STRONG vs WEAK SEASON")
    lines.append("=" * 50)

    strong_mask = v5_df["entry_month"].isin(STRONG_MONTHS)
    weak_mask = v5_df["entry_month"].isin(WEAK_MONTHS)
    strong_rets = v5_df.loc[strong_mask, "overnight_ret"].values
    weak_rets = v5_df.loc[weak_mask, "overnight_ret"].values

    s_strong = compute_stats(strong_rets, "STRONG (Nov-Apr)")
    s_weak = compute_stats(weak_rets, "WEAK (May-Oct)")

    for s in [s_strong, s_weak]:
        lines.append(f"{s['label']:20s}: N={s['N']:>4d} | Mean={s['mean']:+.4f}% | "
                     f"Sharpe={s['sharpe']:.2f} | WR={s['win_rate']:.1f}% | p={s['p_value']:.4f}")

    diff = s_strong["mean"] - s_weak["mean"]
    # Welch's t-test between groups
    if len(strong_rets) > 1 and len(weak_rets) > 1:
        t_between, p_between = stats.ttest_ind(strong_rets, weak_rets, equal_var=False)
        lines.append(f"Difference: {diff:+.4f}% | Welch t-test between groups: t={t_between:.3f}, p={p_between:.4f}")
    else:
        lines.append(f"Difference: {diff:+.4f}%")

    lines.append("")
    lines.append("")

    # ── Test C: Walk-Forward with Seasonal Filter (Nov-Apr only) ──
    lines.append("WALK-FORWARD WITH SEASONAL FILTER (V5 + Nov-Apr only)")
    lines.append("=" * 50)

    # Full V5 walk-forward (for comparison)
    n_full = len(v5_df)
    split_full = n_full // 3
    for label_set, df_set, split_size in [
        ("V5 unfiltered", v5_df, split_full),
    ]:
        lines.append(f"--- {label_set} (reference) ---")
        p1 = df_set.iloc[:split_size]
        p2 = df_set.iloc[split_size:2 * split_size]
        p3 = df_set.iloc[2 * split_size:]
        for p, lbl in [(p1, "Period 1 (early)"), (p2, "Period 2 (mid)"), (p3, "Period 3 (recent)")]:
            s = compute_stats(p["overnight_ret"].values, lbl)
            dr = f"{p['date'].min().strftime('%Y-%m-%d')}→{p['date'].max().strftime('%Y-%m-%d')}"
            lines.append(f"  {lbl:20s}: {dr} | N={s['N']:>4d} | Mean={s['mean']:+.4f}% | "
                         f"Sharpe={s['sharpe']:.2f} | p={s['p_value']:.4f}")
        lines.append("")

    # Seasonal-filtered walk-forward
    seasonal_df = v5_df[strong_mask].copy().reset_index(drop=True)
    n_seasonal = len(seasonal_df)

    lines.append(f"--- V5 + STRONG season (Nov-Apr only) ---")
    if n_seasonal < 3:
        lines.append("  Insufficient observations for walk-forward split.")
    else:
        split_s = n_seasonal // 3
        sp1 = seasonal_df.iloc[:split_s]
        sp2 = seasonal_df.iloc[split_s:2 * split_s]
        sp3 = seasonal_df.iloc[2 * split_s:]

        period_stats_list = []
        for p, lbl in [(sp1, "Period 1 (early)"), (sp2, "Period 2 (mid)"), (sp3, "Period 3 (recent)")]:
            s = compute_stats(p["overnight_ret"].values, lbl)
            dr = f"{p['date'].min().strftime('%Y-%m-%d')}→{p['date'].max().strftime('%Y-%m-%d')}"
            lines.append(f"  {lbl:20s}: {dr} | N={s['N']:>4d} | Mean={s['mean']:+.4f}% | "
                         f"Sharpe={s['sharpe']:.2f} | p={s['p_value']:.4f}")
            period_stats_list.append(s)

        # Stability assessment
        means = [s["mean"] for s in period_stats_list]
        sharpes = [s["sharpe"] for s in period_stats_list]
        valid_means = [m for m in means if not np.isnan(m)]
        valid_sharpes = [s for s in sharpes if not np.isnan(s)]

        all_positive = all(m > 0 for m in valid_means) if valid_means else False
        sharpe_range = max(valid_sharpes) - min(valid_sharpes) if len(valid_sharpes) >= 2 else np.nan

        if all_positive and sharpe_range < 1.0:
            stability = "STABLE"
        elif all_positive and sharpe_range < 2.0:
            stability = "DEGRADING"
        else:
            stability = "UNSTABLE"
        lines.append(f"  STABILITY: {stability}")

    lines.append("")

    # ── Overall Conclusion ──
    lines.append("")

    # Does seasonal filter help?
    seasonal_stats = compute_stats(seasonal_df["overnight_ret"].values, "seasonal")
    full_stats = compute_stats(v5_df["overnight_ret"].values, "full")

    if seasonal_stats["mean"] > full_stats["mean"] and seasonal_stats["sharpe"] > full_stats["sharpe"]:
        if n_seasonal >= 3:
            sp3_rets = seasonal_df.iloc[2 * (n_seasonal // 3):]["overnight_ret"].values
            sp3_mean = np.mean(sp3_rets) * 100 if len(sp3_rets) > 0 else np.nan
            if not np.isnan(sp3_mean) and sp3_mean > 0:
                conclusion = "SEASONAL FILTER HELPS — improves mean, Sharpe, and stabilizes Period 3"
            else:
                conclusion = "SEASONAL FILTER HELPS partially — better aggregate but Period 3 still weak"
        else:
            conclusion = "SEASONAL FILTER HELPS — better mean and Sharpe"
    elif seasonal_stats["sharpe"] > full_stats["sharpe"]:
        conclusion = "SEASONAL FILTER HELPS marginally — better Sharpe but edge still thin"
    else:
        if seasonal_stats["mean"] <= 0:
            conclusion = "EDGE STILL DEAD — seasonal filter does not rescue V5"
        else:
            conclusion = "NO IMPROVEMENT — seasonal filter does not materially help"

    lines.append(f"CONCLUSION: {conclusion}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("S45 OVERNIGHT V5 — SEASONAL DECOMPOSITION")
    print("=" * 60)

    print("\n1. Loading M5 FIXED data → daily bars...")
    daily = load_daily_ohlc()
    print(f"   → {len(daily)} ticker-day rows")

    print("\n2. Loading 4H indicators (EMA9/21 + ADX(14, smooth=20))...")
    indicators_df = load_4h_indicators()
    print(f"   → {len(indicators_df)} indicator rows")

    print("\n3. Loading VIX (prior-day close)...")
    vix_df = load_vix()
    print(f"   → {len(vix_df)} VIX rows")

    print("\n4. Applying V5 filter & computing overnight returns...")
    v5_df = build_v5_overnight(daily, indicators_df, vix_df)
    print(f"   → {len(v5_df)} V5-filtered overnight observations")

    if len(v5_df) == 0:
        print("\nERROR: No observations passed V5 filter.")
    else:
        print(f"   Date range: {v5_df['date'].min().date()} to {v5_df['date'].max().date()}")
        for m in range(1, 13):
            n = (v5_df["entry_month"] == m).sum()
            if n > 0:
                print(f"   {MONTH_NAMES[m]:>3s}: {n} obs")

        print("\n5. Generating seasonal decomposition report...\n")
        report = generate_report(v5_df)

        out_path = RESULTS_DIR / "S45_Overnight_Seasonal.txt"
        out_path.write_text(report)
        print(report)
        print(f"\nSaved → {out_path}")
