#!/usr/bin/env python3
"""
S45 Overnight Day-of-Week Decomposition — V5 Strategy
Tests whether overnight V5 edge is concentrated in specific weekdays.
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

DOW_NAMES = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday"}
DOW_LABELS = {
    0: "Monday    (Mon close→Tue open)",
    1: "Tuesday   (Tue close→Wed open)",
    2: "Wednesday (Wed close→Thu open)",
    3: "Thursday  (Thu close→Fri open)",
    4: "Friday→Monday (weekend)",
}


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
                "dow": pd.Timestamp(date).dayofweek,
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


# ═══════════════════════════════════════════════════════════════
# 4. Load 4H bars and compute EMA gate + ADX(14, smoothing=20)
# ═══════════════════════════════════════════════════════════════

def load_4h_indicators():
    """Load 4H bars, use pre-computed EMA9/EMA21, compute ADX(14, smoothing=20)."""
    rows = []
    for ticker in TICKERS:
        path = EMA4H_DIR / f"{ticker}_4h_indicators.csv"
        if not path.exists():
            print(f"  SKIP 4H {ticker}: file not found")
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
                "ticker": ticker,
                "date": row["date"],
                "ema_gate_up": row["ema_gate_up"],
                "adx_14_s20": row["adx_14_s20"],
            })
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════
# 5. Build overnight returns with V5 filter (ALL days including Friday)
# ═══════════════════════════════════════════════════════════════

def build_v5_overnight_all_days(daily, indicators_df, vix_df):
    """Apply V5 filter and compute overnight returns for ALL entry days.
    Tags each observation by entry day of week. Includes Friday→Monday."""
    records = []

    merged = daily.merge(indicators_df, on=["ticker", "date"], how="inner")
    merged = merged.merge(vix_df, on="date", how="left")
    merged.dropna(subset=["prior_vix", "adx_14_s20"], inplace=True)

    for ticker, grp in merged.groupby("ticker"):
        grp = grp.sort_values("date").reset_index(drop=True)

        ticker_daily = daily[daily["ticker"] == ticker].sort_values("date").reset_index(drop=True)
        date_to_idx = {d: i for i, d in enumerate(ticker_daily["date"])}

        for _, row in grp.iterrows():
            # V5 filter (EMA gate UP, ADX < 20, VIX < 25)
            if not row["ema_gate_up"]:
                continue
            if row["adx_14_s20"] >= 20:
                continue
            if row["prior_vix"] >= 25:
                continue

            # Find next trading day's open
            idx = date_to_idx.get(row["date"])
            if idx is None or idx + 1 >= len(ticker_daily):
                continue
            next_row = ticker_daily.iloc[idx + 1]

            # Skip if gap > 4 calendar days (holiday week, not normal weekend)
            days_gap = (next_row["date"] - row["date"]).days
            if row["dow"] == 4:
                # Friday: expect 3-day gap (Fri→Mon)
                if days_gap > 4:
                    continue
            else:
                # Weekday: expect 1-day gap
                if days_gap > 3:
                    continue

            overnight_ret = (next_row["open"] / row["close"]) - 1

            records.append({
                "ticker": ticker,
                "date": row["date"],
                "entry_dow": row["dow"],
                "close_today": row["close"],
                "open_next": next_row["open"],
                "overnight_ret": overnight_ret,
            })

    result = pd.DataFrame(records)
    result.sort_values("date", inplace=True)
    result.reset_index(drop=True, inplace=True)
    return result


# ═══════════════════════════════════════════════════════════════
# 6. Day-of-week statistics
# ═══════════════════════════════════════════════════════════════

def dow_stats(rets, label):
    """Compute stats for a day-of-week slice."""
    n = len(rets)
    if n == 0:
        return {"label": label, "N": 0, "mean": np.nan, "std": np.nan,
                "win_rate": np.nan, "t_stat": np.nan, "p_value": np.nan}

    mean_ret = np.mean(rets) * 100
    std_ret = np.std(rets, ddof=1) * 100
    win_rate = np.mean(rets > 0) * 100
    t_stat, p_value = stats.ttest_1samp(rets, 0)

    return {
        "label": label,
        "N": n,
        "mean": mean_ret,
        "std": std_ret,
        "win_rate": win_rate,
        "t_stat": t_stat,
        "p_value": p_value,
    }


# ═══════════════════════════════════════════════════════════════
# 7. Report generation
# ═══════════════════════════════════════════════════════════════

def generate_report(v5_df):
    lines = []
    lines.append("DAY-OF-WEEK — OVERNIGHT V5")
    lines.append("=" * 50)

    date_range = f"{v5_df['date'].min().strftime('%Y-%m-%d')} → {v5_df['date'].max().strftime('%Y-%m-%d')}"
    lines.append(f"Full sample: {date_range}, N={len(v5_df)}")
    lines.append("")

    # Mon-Thu weekday overnights
    weekday_groups = {}
    for dow in range(4):  # 0=Mon, 1=Tue, 2=Wed, 3=Thu
        mask = v5_df["entry_dow"] == dow
        rets = v5_df.loc[mask, "overnight_ret"].values
        s = dow_stats(rets, DOW_LABELS[dow])
        weekday_groups[dow] = rets
        lines.append(f"{s['label']:42s}: N={s['N']:>4d} | Mean={s['mean']:+.4f}% | "
                     f"Std={s['std']:.4f}% | WR={s['win_rate']:.1f}% | "
                     f"t={s['t_stat']:+.3f} | p={s['p_value']:.4f}")

    lines.append("-" * 50)

    # Friday→Monday weekend overnight
    fri_mask = v5_df["entry_dow"] == 4
    fri_rets = v5_df.loc[fri_mask, "overnight_ret"].values
    s_fri = dow_stats(fri_rets, DOW_LABELS[4])
    lines.append(f"{s_fri['label']:42s}: N={s_fri['N']:>4d} | Mean={s_fri['mean']:+.4f}% | "
                 f"Std={s_fri['std']:.4f}% | WR={s_fri['win_rate']:.1f}% | "
                 f"t={s_fri['t_stat']:+.3f} | p={s_fri['p_value']:.4f}")
    lines.append("")

    # Kruskal-Wallis test across Mon-Thu
    kw_groups = [g for g in weekday_groups.values() if len(g) > 0]
    if len(kw_groups) >= 2:
        h_stat, kw_p = stats.kruskal(*kw_groups)
        lines.append(f"Kruskal-Wallis (Mon-Thu): H={h_stat:.3f}, p={kw_p:.4f}")
    else:
        h_stat, kw_p = np.nan, np.nan
        lines.append("Kruskal-Wallis (Mon-Thu): insufficient groups")

    # Conclusion
    lines.append("")

    # Find best/worst weekday
    weekday_means = {}
    for dow in range(4):
        rets = weekday_groups[dow]
        if len(rets) > 0:
            weekday_means[dow] = np.mean(rets) * 100

    if weekday_means:
        best_dow = max(weekday_means, key=weekday_means.get)
        worst_dow = min(weekday_means, key=weekday_means.get)
        best_name = DOW_NAMES[best_dow]
        worst_name = DOW_NAMES[worst_dow]

    # Check if Friday is an anomaly
    fri_mean = s_fri["mean"] if s_fri["N"] > 0 else np.nan
    weekday_avg = np.mean(list(weekday_means.values())) if weekday_means else np.nan

    # Determine conclusion
    if not np.isnan(kw_p) and kw_p < 0.05:
        # Significant difference among weekdays
        sig_days = []
        for dow in range(4):
            rets = weekday_groups[dow]
            if len(rets) > 0:
                _, p = stats.ttest_1samp(rets, 0)
                if p < 0.05:
                    sig_days.append(DOW_NAMES[dow])
        if sig_days:
            conclusion = f"CONCENTRATED in {', '.join(sig_days)}"
        else:
            conclusion = f"CONCENTRATED in {best_name} (Kruskal-Wallis significant)"
    elif not np.isnan(fri_mean) and not np.isnan(weekday_avg):
        fri_diff = abs(fri_mean - weekday_avg)
        if fri_diff > 0.10 and s_fri["N"] >= 20:
            conclusion = "FRIDAY ANOMALY"
        else:
            conclusion = "EVENLY DISTRIBUTED"
    else:
        conclusion = "EVENLY DISTRIBUTED"

    lines.append(f"CONCLUSION: {conclusion}")
    lines.append(f"- Best weekday:  {best_name} ({weekday_means[best_dow]:+.4f}%)")
    lines.append(f"- Worst weekday: {worst_name} ({weekday_means[worst_dow]:+.4f}%)")
    if not np.isnan(fri_mean):
        lines.append(f"- Friday→Monday: {fri_mean:+.4f}% vs weekday avg {weekday_avg:+.4f}%")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("S45 OVERNIGHT DAY-OF-WEEK DECOMPOSITION — V5 STRATEGY")
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

    print("\n4. Applying V5 filter & computing overnight returns (all days)...")
    v5_df = build_v5_overnight_all_days(daily, indicators_df, vix_df)
    print(f"   → {len(v5_df)} V5-filtered overnight observations")

    if len(v5_df) == 0:
        print("\nERROR: No observations passed V5 filter.")
    else:
        print(f"   Tickers: {v5_df['ticker'].nunique()}")
        print(f"   Date range: {v5_df['date'].min().date()} to {v5_df['date'].max().date()}")

        # Show DOW distribution
        for dow in range(5):
            n = (v5_df["entry_dow"] == dow).sum()
            print(f"   {DOW_NAMES[dow]:>10s}: {n} obs")

        print("\n5. Generating day-of-week report...\n")
        report = generate_report(v5_df)

        out_path = RESULTS_DIR / "S45_Overnight_DayOfWeek.txt"
        out_path.write_text(report)
        print(report)
        print(f"\nSaved → {out_path}")
