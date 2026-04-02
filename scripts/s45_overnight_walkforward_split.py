#!/usr/bin/env python3
"""
S45 Overnight Walk-Forward Split — V5 Strategy Temporal Stability Test
Splits the full overnight V5 dataset into 3 equal time periods and reports
per-period statistics to assess temporal stability.
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
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU", "C", "COIN",
    "COST", "GOOGL", "GS", "INTC", "JPM", "MARA", "META", "MSFT", "MSTR",
    "MU", "NVDA", "PLTR", "SMCI", "TSLA", "TSM", "V",
]


# ═══════════════════════════════════════════════════════════════
# 1. Load daily bars from M5 FIXED data
# ═══════════════════════════════════════════════════════════════

def load_daily_ohlc():
    """Extract daily open (09:30) and close (15:55) from M5 regsess FIXED data."""
    rows = []
    for ticker in TICKERS:
        path = REGSESS_DIR / f"{ticker}_m5_regsess_FIXED.csv"
        if not path.exists():
            print(f"  SKIP {ticker}: file not found")
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
                "ticker": ticker,
                "date": date,
                "open": first_bar.iloc[0]["Open"],
                "close": last_bar.iloc[0]["Close"],
                "dow": pd.Timestamp(date).dayofweek,  # 0=Mon, 4=Fri
            })
    daily = pd.DataFrame(rows)
    daily["date"] = pd.to_datetime(daily["date"])
    daily.sort_values(["ticker", "date"], inplace=True)
    daily.reset_index(drop=True, inplace=True)
    return daily


# ═══════════════════════════════════════════════════════════════
# 2. Load VIX — prior-day close (no lookahead)
# ═══════════════════════════════════════════════════════════════

def load_vix():
    vix = pd.read_csv(VIX_PATH, parse_dates=["observation_date"])
    vix.rename(columns={"observation_date": "date", "VIXCLS": "vix"}, inplace=True)
    vix["vix"] = pd.to_numeric(vix["vix"], errors="coerce")
    vix.dropna(subset=["vix"], inplace=True)
    vix.sort_values("date", inplace=True)
    vix["prior_vix"] = vix["vix"].shift(1)
    return vix[["date", "prior_vix"]].dropna()


# ═══════════════════════════════════════════════════════════════
# 3. ADX(14, smoothing=20) computation on 4H bars
# ═══════════════════════════════════════════════════════════════

def compute_adx_custom(highs, lows, closes, dm_period=14, adx_smooth=20):
    """ADX with DM period=14 and ADX smoothing=20 (Wilder smoothing)."""
    n = len(highs)
    adx = np.full(n, np.nan)
    if n < dm_period + adx_smooth:
        return adx

    # True Range
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hc, lc)

    # +DM, -DM
    pdm = np.zeros(n)
    mdm = np.zeros(n)
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        pdm[i] = up if (up > down and up > 0) else 0.0
        mdm[i] = down if (down > up and down > 0) else 0.0

    # Wilder smoothing for TR, +DM, -DM (period=dm_period)
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

    # DX
    dx = np.full(n, np.nan)
    for i in range(dm_period, n):
        if atr_s[i] > 0:
            pdi = 100.0 * pdm_s[i] / atr_s[i]
            mdi = 100.0 * mdm_s[i] / atr_s[i]
        else:
            pdi = mdi = 0.0
        di_sum = pdi + mdi
        dx[i] = 100.0 * abs(pdi - mdi) / di_sum if di_sum > 0 else 0.0

    # ADX = Wilder smooth of DX with adx_smooth period
    adx_start = dm_period + adx_smooth - 1
    if n > adx_start:
        adx[adx_start] = np.nanmean(dx[dm_period:adx_start + 1])
        for i in range(adx_start + 1, n):
            if not np.isnan(dx[i]):
                adx[i] = (adx[i - 1] * (adx_smooth - 1) + dx[i]) / adx_smooth

    return adx


# ═══════════════════════════════════════════════════════════════
# 4. Load 4H bars and compute EMA gate + ADX(14, smoothing=20)
# ═══════════════════════════════════════════════════════════════

def load_4h_indicators():
    """Load 4H bars, use pre-computed EMA9/EMA21, compute ADX(14, smoothing=20).
    Return per-ticker-date: today's last 4H bar EMA gate and ADX."""
    rows = []
    for ticker in TICKERS:
        path = EMA4H_DIR / f"{ticker}_4h_indicators.csv"
        if not path.exists():
            print(f"  SKIP 4H {ticker}: file not found")
            continue
        df = pd.read_csv(path, parse_dates=["timestamp"])

        # Compute ADX(14, smoothing=20) from 4H OHLCV
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        adx_20 = compute_adx_custom(highs, lows, closes, dm_period=14, adx_smooth=20)
        df["adx_14_s20"] = adx_20

        # Use pre-computed EMA9/EMA21
        df.dropna(subset=["ema_9", "ema_21"], inplace=True)
        if df.empty:
            continue

        df["date"] = df["timestamp"].dt.date
        # Last 4H bar of each day (13:30 bar = end of day)
        eod = df.groupby("date").last().reset_index()
        eod["ema_gate_up"] = eod["ema_9"] > eod["ema_21"]
        eod["date"] = pd.to_datetime(eod["date"])
        eod.sort_values("date", inplace=True)

        for _, row in eod.iterrows():
            rows.append({
                "ticker": ticker,
                "date": row["date"],
                "ema_gate_up": row["ema_gate_up"],
                "adx_14_s20": row["adx_14_s20"],
            })
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════
# 5. Build overnight returns with V5 filter
# ═══════════════════════════════════════════════════════════════

def build_v5_overnight(daily, indicators_df, vix_df):
    """Apply V5 filter and compute overnight returns.

    V5 filter (checked at today's close):
      - 4H EMA9 > EMA21 (gate UP) — today's last bar
      - ADX(14, smoothing=20) < 20 — today's last bar
      - VIX < 25 — prior-day close

    Entry: buy at today's close (15:55)
    Exit: sell at next session open (09:30 next trading day)
    Skip: Friday close → Monday open (weekend overnight)
    """
    records = []

    # Merge daily with indicators (same day)
    merged = daily.merge(indicators_df, on=["ticker", "date"], how="inner")
    # Merge with VIX (prior-day)
    merged = merged.merge(vix_df, on="date", how="left")
    merged.dropna(subset=["prior_vix", "adx_14_s20"], inplace=True)

    for ticker, grp in merged.groupby("ticker"):
        grp = grp.sort_values("date").reset_index(drop=True)

        # Get full daily data for this ticker to find next-day open
        ticker_daily = daily[daily["ticker"] == ticker].sort_values("date").reset_index(drop=True)
        date_to_idx = {d: i for i, d in enumerate(ticker_daily["date"])}

        for _, row in grp.iterrows():
            # V5 filter
            if not row["ema_gate_up"]:
                continue
            if row["adx_14_s20"] >= 20:
                continue
            if row["prior_vix"] >= 25:
                continue

            # Skip Friday close (weekend overnight)
            if row["dow"] == 4:  # Friday
                continue

            # Find next trading day's open
            idx = date_to_idx.get(row["date"])
            if idx is None or idx + 1 >= len(ticker_daily):
                continue
            next_row = ticker_daily.iloc[idx + 1]

            # Verify next day is actually next trading day (not gap > weekend)
            days_gap = (next_row["date"] - row["date"]).days
            if days_gap > 3:  # skip if gap > 3 calendar days (holiday week)
                continue

            overnight_ret = (next_row["open"] / row["close"]) - 1

            records.append({
                "ticker": ticker,
                "date": row["date"],
                "close_today": row["close"],
                "open_next": next_row["open"],
                "overnight_ret": overnight_ret,
                "ema9_gt_ema21": True,
                "adx_14_s20": row["adx_14_s20"],
                "prior_vix": row["prior_vix"],
            })

    result = pd.DataFrame(records)
    result.sort_values("date", inplace=True)
    result.reset_index(drop=True, inplace=True)
    return result


# ═══════════════════════════════════════════════════════════════
# 6. Period statistics
# ═══════════════════════════════════════════════════════════════

def period_stats(df, label):
    """Compute stats for a period slice."""
    n = len(df)
    if n == 0:
        return {"label": label, "N": 0, "date_range": "N/A",
                "mean": np.nan, "std": np.nan, "sharpe": np.nan,
                "win_rate": np.nan, "t_stat": np.nan, "p_value": np.nan}

    rets = df["overnight_ret"].values
    mean_ret = np.mean(rets)
    std_ret = np.std(rets, ddof=1)
    sharpe = (mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else np.nan
    win_rate = np.mean(rets > 0) * 100
    t_stat, p_value = stats.ttest_1samp(rets, 0)
    date_min = df["date"].min().strftime("%Y-%m-%d")
    date_max = df["date"].max().strftime("%Y-%m-%d")

    return {
        "label": label,
        "N": n,
        "date_range": f"{date_min} → {date_max}",
        "mean": mean_ret * 100,  # as percentage
        "std": std_ret * 100,
        "sharpe": sharpe,
        "win_rate": win_rate,
        "t_stat": t_stat,
        "p_value": p_value,
    }


# ═══════════════════════════════════════════════════════════════
# 7. Report generation
# ═══════════════════════════════════════════════════════════════

def generate_report(v5_df):
    """Split into 3 equal periods by observation count and report."""
    n_total = len(v5_df)
    split_size = n_total // 3

    p1 = v5_df.iloc[:split_size]
    p2 = v5_df.iloc[split_size:2 * split_size]
    p3 = v5_df.iloc[2 * split_size:]

    full_stats = period_stats(v5_df, "Full sample")
    s1 = period_stats(p1, "Period 1 (early)")
    s2 = period_stats(p2, "Period 2 (mid)")
    s3 = period_stats(p3, "Period 3 (recent)")

    # Stability assessment
    means = [s1["mean"], s2["mean"], s3["mean"]]
    sharpes = [s1["sharpe"], s2["sharpe"], s3["sharpe"]]
    valid_means = [m for m in means if not np.isnan(m)]
    valid_sharpes = [s for s in sharpes if not np.isnan(s)]

    all_positive = all(m > 0 for m in valid_means)
    all_negative = all(m < 0 for m in valid_means)
    sign_consistent = all_positive or all_negative
    sign_label = "all positive" if all_positive else ("all negative" if all_negative else "mixed")

    # Find max drawdown period (worst mean)
    period_labels = ["Period 1 (early)", "Period 2 (mid)", "Period 3 (recent)"]
    worst_idx = np.argmin(means)
    worst_period = period_labels[worst_idx]

    sharpe_min = min(valid_sharpes) if valid_sharpes else np.nan
    sharpe_max = max(valid_sharpes) if valid_sharpes else np.nan
    sharpe_range = sharpe_max - sharpe_min if valid_sharpes else np.nan

    # Stability verdict
    if sign_consistent and sharpe_range < 1.0:
        stability = "STABLE"
    elif sign_consistent and sharpe_range < 2.0:
        stability = "DEGRADING"
    else:
        stability = "UNSTABLE"

    lines = []
    lines.append("WALK-FORWARD SPLIT — OVERNIGHT V5")
    lines.append("=" * 50)
    lines.append(f"Full sample: {full_stats['date_range']}, N={full_stats['N']}")
    lines.append(f"  Mean={full_stats['mean']:.4f}% | Std={full_stats['std']:.4f}% | "
                 f"Sharpe={full_stats['sharpe']:.2f} | WR={full_stats['win_rate']:.1f}% | "
                 f"t={full_stats['t_stat']:.3f} | p={full_stats['p_value']:.4f}")
    lines.append("")

    for s in [s1, s2, s3]:
        lines.append(f"{s['label']:20s}: {s['date_range']} | N={s['N']} | "
                     f"Mean={s['mean']:.4f}% | Sharpe={s['sharpe']:.2f} | "
                     f"WR={s['win_rate']:.1f}% | t={s['t_stat']:.3f} | p={s['p_value']:.4f}")

    lines.append("")
    lines.append(f"STABILITY: {stability}")
    lines.append(f"- Period-to-period sign consistency: {sign_label}")
    lines.append(f"- Max drawdown period: {worst_period}")
    lines.append(f"- Sharpe range: {sharpe_min:.2f} to {sharpe_max:.2f}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("S45 OVERNIGHT WALK-FORWARD SPLIT — V5 STRATEGY")
    print("=" * 60)

    print("\n1. Loading M5 FIXED data → daily bars...")
    daily = load_daily_ohlc()
    print(f"   → {len(daily)} ticker-day rows, "
          f"{daily['ticker'].nunique()} tickers, "
          f"{daily['date'].min().date()} to {daily['date'].max().date()}")

    print("\n2. Loading 4H indicators (EMA9/21 + computing ADX(14, smooth=20))...")
    indicators_df = load_4h_indicators()
    print(f"   → {len(indicators_df)} indicator rows")

    print("\n3. Loading VIX (prior-day close)...")
    vix_df = load_vix()
    print(f"   → {len(vix_df)} VIX rows")

    print("\n4. Applying V5 filter & computing overnight returns...")
    v5_df = build_v5_overnight(daily, indicators_df, vix_df)
    print(f"   → {len(v5_df)} V5-filtered overnight observations")

    if len(v5_df) == 0:
        print("\nERROR: No observations passed V5 filter. Check data/filters.")
    else:
        print(f"   Tickers with signals: {v5_df['ticker'].nunique()}")
        print(f"   Date range: {v5_df['date'].min().date()} to {v5_df['date'].max().date()}")

        print("\n5. Generating walk-forward split report...\n")
        report = generate_report(v5_df)

        out_path = RESULTS_DIR / "S45_Overnight_WalkForward_Split.txt"
        out_path.write_text(report)
        print(report)
        print(f"\nSaved → {out_path}")
