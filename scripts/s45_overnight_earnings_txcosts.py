#!/usr/bin/env python3
"""
S45 Overnight Earnings Filter + Transaction Costs — V5 Strategy
Test A: Strip earnings-adjacent overnights and retest V5
Test B: Apply realistic transaction costs and find break-even
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import time, timedelta
from scipy import stats

# ── paths ──
ROOT = Path(__file__).resolve().parent.parent
REGSESS_DIR = ROOT / "backtest_output"
VIX_PATH = ROOT / "Fetched_Data" / "VIXCLS_FRED_real.csv"
EMA4H_DIR = ROOT / "data" / "indicators_4h"
EARNINGS_PATH = ROOT / "backtester" / "data" / "earnings_calendar.json"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# 25 equity tickers — exclude SPY, VIXY
TICKERS = [
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN", "COST",
    "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU", "NVDA", "PLTR",
    "SNOW", "TSLA", "TSM", "TXN", "V",
]


# ═══════════════════════════════════════════════════════════════
# 1. Load daily bars from M5 FIXED data
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


# ═══════════════════════════════════════════════════════════════
# 2. Load VIX — prior-day close
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
# 3. ADX(14, smoothing=20) on 4H bars
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
# 4. Load 4H indicators
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
# 5. Load earnings calendar
# ═══════════════════════════════════════════════════════════════

def load_earnings_calendar():
    """Load static earnings calendar. Returns dict: ticker → set of earnings dates."""
    with open(EARNINGS_PATH) as f:
        raw = json.load(f)
    cal = {}
    for ticker, dates in raw.items():
        cal[ticker] = set(pd.to_datetime(d).date() for d in dates)
    return cal


# ═══════════════════════════════════════════════════════════════
# 6. Build V5 overnight returns (all weekdays, no Friday skip)
# ═══════════════════════════════════════════════════════════════

def build_v5_overnight(daily, indicators_df, vix_df):
    """Apply V5 filter, compute overnight returns. Skip Friday→Monday."""
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
            if row["dow"] == 4:  # skip Friday
                continue

            idx = date_to_idx.get(row["date"])
            if idx is None or idx + 1 >= len(ticker_daily):
                continue
            next_row = ticker_daily.iloc[idx + 1]
            days_gap = (next_row["date"] - row["date"]).days
            if days_gap > 3:
                continue

            overnight_ret = (next_row["open"] / row["close"]) - 1
            entry_date = row["date"].date() if hasattr(row["date"], "date") else row["date"]
            exit_date = next_row["date"].date() if hasattr(next_row["date"], "date") else next_row["date"]

            records.append({
                "ticker": ticker,
                "date": row["date"],
                "entry_date": entry_date,
                "exit_date": exit_date,
                "close_today": row["close"],
                "open_next": next_row["open"],
                "overnight_ret": overnight_ret,
            })

    result = pd.DataFrame(records)
    result.sort_values("date", inplace=True)
    result.reset_index(drop=True, inplace=True)
    return result


# ═══════════════════════════════════════════════════════════════
# 7. Statistics helper
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
# 8. Test A: Earnings filter
# ═══════════════════════════════════════════════════════════════

def test_earnings_filter(v5_df, earnings_cal):
    """Remove earnings-adjacent overnights and compare."""
    # Flag earnings-adjacent: entry_date or exit_date is an earnings date for that ticker
    def is_earnings_adjacent(row):
        ticker_dates = earnings_cal.get(row["ticker"], set())
        if not ticker_dates:
            return False
        return row["entry_date"] in ticker_dates or row["exit_date"] in ticker_dates

    v5_df = v5_df.copy()
    v5_df["is_earnings"] = v5_df.apply(is_earnings_adjacent, axis=1)

    earnings_df = v5_df[v5_df["is_earnings"]]
    ex_earnings_df = v5_df[~v5_df["is_earnings"]]

    # Also flag >3% overnight as proxy check
    v5_df["big_move"] = v5_df["overnight_ret"].abs() > 0.03

    full_stats = compute_stats(v5_df["overnight_ret"].values, "V5 full sample")
    ex_stats = compute_stats(ex_earnings_df["overnight_ret"].values, "V5 ex-earnings")
    earn_stats = compute_stats(earnings_df["overnight_ret"].values, "Earnings-only nights")

    # Also compute proxy-based (remove |ret| > 3%)
    proxy_df = v5_df[~v5_df["big_move"]]
    proxy_stats = compute_stats(proxy_df["overnight_ret"].values, "V5 ex-big-moves (|ret|>3%)")

    # Overlap check: how many big moves are earnings?
    n_big = v5_df["big_move"].sum()
    n_big_and_earn = (v5_df["big_move"] & v5_df["is_earnings"]).sum()

    # Conclusion
    if earn_stats["N"] > 0 and not np.isnan(earn_stats["mean"]):
        earn_mean = earn_stats["mean"]
        ex_mean = ex_stats["mean"]
        if earn_mean > ex_mean + 0.05:
            conclusion = "Earnings DRIVE the edge (higher mean on earnings nights)"
        elif earn_mean < ex_mean - 0.05:
            conclusion = "Earnings HURT the edge (lower/negative mean on earnings nights)"
        else:
            conclusion = "Earnings NEUTRAL (similar means with/without)"
    else:
        conclusion = "Insufficient earnings observations"

    return full_stats, ex_stats, earn_stats, proxy_stats, n_big, n_big_and_earn, conclusion


# ═══════════════════════════════════════════════════════════════
# 9. Test B: Transaction costs
# ═══════════════════════════════════════════════════════════════

def test_transaction_costs(v5_df):
    """Apply transaction costs and find break-even."""
    gross_rets = v5_df["overnight_ret"].values
    gross_stats = compute_stats(gross_rets, "Gross")

    cost_levels = [5, 10]  # bps
    cost_results = {}
    for bps in cost_levels:
        cost = bps / 10000.0  # convert bps to decimal
        net_rets = gross_rets - cost
        s = compute_stats(net_rets, f"Net ({bps} bps)")
        cost_results[bps] = s

    # Break-even: mean gross return in bps
    gross_mean_decimal = np.mean(gross_rets)
    break_even_bps = gross_mean_decimal * 10000  # convert to bps

    # Conclusion
    if cost_results[10]["mean"] > 0 and cost_results[10]["p_value"] < 0.10:
        conclusion = "SURVIVES costs (positive and marginally significant at 10 bps)"
    elif cost_results[5]["mean"] > 0 and cost_results[5]["p_value"] < 0.10:
        conclusion = "MARGINAL (survives 5 bps but not 10 bps)"
    elif cost_results[5]["mean"] > 0:
        conclusion = "MARGINAL (positive at 5 bps but not significant)"
    else:
        conclusion = "KILLED by costs (negative even at 5 bps)"

    return gross_stats, cost_results, break_even_bps, conclusion


# ═══════════════════════════════════════════════════════════════
# 10. Report
# ═══════════════════════════════════════════════════════════════

def generate_report(v5_df, earnings_cal):
    lines = []

    # ── Test A ──
    full_s, ex_s, earn_s, proxy_s, n_big, n_big_earn, earn_conclusion = test_earnings_filter(v5_df, earnings_cal)

    lines.append("EARNINGS FILTER — OVERNIGHT V5")
    lines.append("=" * 50)
    lines.append(f"Earnings calendar: {EARNINGS_PATH.name} ({sum(len(v) for v in earnings_cal.values())} dates across {len(earnings_cal)} tickers)")
    lines.append("")

    for s in [full_s, ex_s, earn_s]:
        mean_str = f"Mean={s['mean']:+.4f}%" if not np.isnan(s['mean']) else "Mean=N/A"
        sharpe_str = f"Sharpe={s['sharpe']:.2f}" if not np.isnan(s['sharpe']) else "Sharpe=N/A"
        p_str = f"p={s['p_value']:.4f}" if not np.isnan(s['p_value']) else "p=N/A"
        wr_str = f"WR={s['win_rate']:.1f}%" if not np.isnan(s['win_rate']) else "WR=N/A"
        lines.append(f"{s['label']:25s}: N={s['N']:>4d} | {mean_str} | {sharpe_str} | {wr_str} | {p_str}")

    lines.append("")
    lines.append(f"Proxy check (|ret| > 3%): {n_big} big moves, {n_big_earn} overlap with earnings")
    s = proxy_s
    lines.append(f"{s['label']:25s}: N={s['N']:>4d} | Mean={s['mean']:+.4f}% | Sharpe={s['sharpe']:.2f} | p={s['p_value']:.4f}")
    lines.append("")
    lines.append(f"CONCLUSION: {earn_conclusion}")

    lines.append("")
    lines.append("")

    # ── Test B ──
    gross_s, cost_results, break_even, cost_conclusion = test_transaction_costs(v5_df)

    lines.append("TRANSACTION COSTS — OVERNIGHT V5")
    lines.append("=" * 50)
    lines.append(f"{'Gross':25s}: Mean={gross_s['mean']:+.4f}% | Sharpe={gross_s['sharpe']:.2f} | "
                 f"WR={gross_s['win_rate']:.1f}% | p={gross_s['p_value']:.4f}")

    for bps in [5, 10]:
        s = cost_results[bps]
        lines.append(f"{'Net (' + str(bps) + ' bps)':25s}: Mean={s['mean']:+.4f}% | Sharpe={s['sharpe']:.2f} | "
                     f"WR={s['win_rate']:.1f}% | p={s['p_value']:.4f}")

    lines.append("")
    lines.append(f"Break-even cost: {break_even:.1f} bps")
    lines.append("")
    lines.append(f"CONCLUSION: {cost_conclusion}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("S45 OVERNIGHT EARNINGS FILTER + TRANSACTION COSTS — V5")
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

    print("\n4. Loading earnings calendar...")
    earnings_cal = load_earnings_calendar()
    n_dates = sum(len(v) for v in earnings_cal.values())
    print(f"   → {len(earnings_cal)} tickers, {n_dates} total earnings dates")

    print("\n5. Applying V5 filter & computing overnight returns...")
    v5_df = build_v5_overnight(daily, indicators_df, vix_df)
    print(f"   → {len(v5_df)} V5-filtered overnight observations")

    if len(v5_df) == 0:
        print("\nERROR: No observations passed V5 filter.")
    else:
        print(f"\n6. Running earnings filter + transaction cost tests...\n")
        report = generate_report(v5_df, earnings_cal)

        out_path = RESULTS_DIR / "S45_Overnight_Earnings_TxCosts.txt"
        out_path.write_text(report)
        print(report)
        print(f"\nSaved → {out_path}")
