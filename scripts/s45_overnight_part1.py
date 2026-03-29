#!/usr/bin/env python3
"""
S45 Overnight Decomposition — Part 1: Analysis
Decomposes daily returns into overnight (close→open) and intraday (open→close).
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import time

# ── paths ──
ROOT = Path(__file__).resolve().parent.parent
REGSESS_DIR = ROOT / "backtest_output"
VIX_PATH = ROOT / "Fetched_Data" / "VIXCLS_FRED_real.csv"
EMA4H_DIR = ROOT / "data" / "indicators_4h"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

TICKERS = [
    "AAPL","AMD","AMZN","AVGO","BA","BABA","BIDU","C","COIN","COST",
    "GOOGL","GS","IBIT","JPM","MARA","META","MSFT","MU","NVDA","PLTR",
    "SNOW","SPY","TSLA","TSM","TXN","V","VIXY",
]

# ═══════════════════════════════════════════════════════════════
# 1. Load & extract daily OHLC from M5 bars
# ═══════════════════════════════════════════════════════════════

def load_daily_ohlc():
    """For each ticker, extract daily: first bar open (09:30), last bar close (15:55)."""
    rows = []
    for ticker in TICKERS:
        path = REGSESS_DIR / f"{ticker}_m5_regsess.csv"
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
            })
    daily = pd.DataFrame(rows)
    daily["date"] = pd.to_datetime(daily["date"])
    daily.sort_values(["ticker", "date"], inplace=True)
    daily.reset_index(drop=True, inplace=True)
    return daily


def compute_returns(daily):
    """Compute overnight, intraday, total returns per ticker per day."""
    records = []
    for ticker, grp in daily.groupby("ticker"):
        grp = grp.sort_values("date").reset_index(drop=True)
        for i in range(1, len(grp)):
            prior_close = grp.loc[i - 1, "close"]
            today_open = grp.loc[i, "open"]
            today_close = grp.loc[i, "close"]
            overnight = (today_open - prior_close) / prior_close * 100
            intraday = (today_close - today_open) / today_open * 100
            total = (today_close - prior_close) / prior_close * 100
            records.append({
                "ticker": ticker,
                "date": grp.loc[i, "date"],
                "prior_close": prior_close,
                "today_open": today_open,
                "today_close": today_close,
                "overnight_ret": overnight,
                "intraday_ret": intraday,
                "total_ret": total,
            })
    return pd.DataFrame(records)


# ═══════════════════════════════════════════════════════════════
# 2. Load VIX data
# ═══════════════════════════════════════════════════════════════

def load_vix():
    vix = pd.read_csv(VIX_PATH, parse_dates=["observation_date"])
    vix.rename(columns={"observation_date": "date", "VIXCLS": "vix"}, inplace=True)
    vix["vix"] = pd.to_numeric(vix["vix"], errors="coerce")
    vix.dropna(subset=["vix"], inplace=True)
    # use prior-day VIX close
    vix.sort_values("date", inplace=True)
    vix["prior_vix"] = vix["vix"].shift(1)
    return vix[["date", "prior_vix"]].dropna()


# ═══════════════════════════════════════════════════════════════
# 3. Load 4H EMA gate state at prior close
# ═══════════════════════════════════════════════════════════════

def load_ema_gates():
    """For each ticker-date, get 4H EMA gate state at last bar of prior day."""
    rows = []
    for ticker in TICKERS:
        path = EMA4H_DIR / f"{ticker}_4h_indicators.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, parse_dates=["timestamp"])
        df.dropna(subset=["ema_9", "ema_21"], inplace=True)
        if df.empty:
            continue
        df["date"] = df["timestamp"].dt.date
        # last 4H bar of each day
        eod = df.groupby("date").last().reset_index()
        eod["gate"] = np.where(eod["ema_9"] > eod["ema_21"], "UP", "DOWN")
        eod["date"] = pd.to_datetime(eod["date"])
        # shift to get prior-day gate
        eod.sort_values("date", inplace=True)
        eod["prior_gate"] = eod["gate"].shift(1)
        eod = eod.dropna(subset=["prior_gate"])
        for _, row in eod.iterrows():
            rows.append({
                "ticker": ticker,
                "date": row["date"],
                "prior_gate": row["prior_gate"],
            })
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════
# 4. Metrics helper
# ═══════════════════════════════════════════════════════════════

def calc_metrics(series, label=""):
    n = len(series)
    if n == 0:
        return {"label": label, "N": 0, "mean": np.nan, "std": np.nan, "sharpe": np.nan}
    mean = series.mean()
    std = series.std()
    sharpe = mean / std if std > 0 else np.nan
    return {"label": label, "N": n, "mean": mean, "std": std, "sharpe": sharpe}


def metrics_table(ret_df, label_prefix=""):
    on = calc_metrics(ret_df["overnight_ret"], f"{label_prefix}overnight")
    intra = calc_metrics(ret_df["intraday_ret"], f"{label_prefix}intraday")
    tot = calc_metrics(ret_df["total_ret"], f"{label_prefix}total")
    corr = ret_df["overnight_ret"].corr(ret_df["intraday_ret"])
    pct_on = on["mean"] / tot["mean"] * 100 if tot["mean"] != 0 else np.nan
    pct_intra = intra["mean"] / tot["mean"] * 100 if tot["mean"] != 0 else np.nan
    return on, intra, tot, corr, pct_on, pct_intra


# ═══════════════════════════════════════════════════════════════
# 5. Report generation
# ═══════════════════════════════════════════════════════════════

def fmt(x, decimals=4):
    if pd.isna(x):
        return "N/A"
    return f"{x:.{decimals}f}"


def generate_report(ret_df, vix_df, ema_df):
    lines = []
    lines.append("# S45 Overnight Decomposition — Part 1 Analysis")
    lines.append("")
    lines.append(f"**Generated:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Tickers:** {len(ret_df['ticker'].unique())}  |  **Obs:** {len(ret_df)}")
    lines.append(f"**Date range:** {ret_df['date'].min().date()} → {ret_df['date'].max().date()}")
    lines.append("")

    # ── Task A: Basic Decomposition ──
    lines.append("## Task A: Basic Decomposition")
    lines.append("")
    on, intra, tot, corr, pct_on, pct_intra = metrics_table(ret_df)
    lines.append("| Metric | Overnight | Intraday | Total |")
    lines.append("|--------|-----------|----------|-------|")
    lines.append(f"| Mean (%) | {fmt(on['mean'])} | {fmt(intra['mean'])} | {fmt(tot['mean'])} |")
    lines.append(f"| Std Dev (%) | {fmt(on['std'])} | {fmt(intra['std'])} | {fmt(tot['std'])} |")
    lines.append(f"| Sharpe (daily) | {fmt(on['sharpe'])} | {fmt(intra['sharpe'])} | {fmt(tot['sharpe'])} |")
    lines.append(f"| % of Total | {fmt(pct_on, 1)}% | {fmt(pct_intra, 1)}% | 100% |")
    lines.append(f"| N | {on['N']} | {intra['N']} | {tot['N']} |")
    lines.append(f"| Correlation(ON, Intra) | {fmt(corr)} | | |")
    lines.append("")

    # ── Per-ticker breakdown ──
    lines.append("### Per-Ticker Breakdown")
    lines.append("")
    lines.append("| Ticker | N | Mean ON (%) | Mean Intra (%) | Mean Total (%) | %ON | Sharpe ON | Sharpe Intra |")
    lines.append("|--------|---|-------------|----------------|----------------|-----|-----------|--------------|")
    for ticker in sorted(ret_df["ticker"].unique()):
        t = ret_df[ret_df["ticker"] == ticker]
        on_t, intra_t, tot_t, _, pct_on_t, _ = metrics_table(t)
        lines.append(f"| {ticker} | {on_t['N']} | {fmt(on_t['mean'])} | {fmt(intra_t['mean'])} | {fmt(tot_t['mean'])} | {fmt(pct_on_t, 1)}% | {fmt(on_t['sharpe'])} | {fmt(intra_t['sharpe'])} |")
    lines.append("")

    # ── Task B: VIX Regime Split ──
    lines.append("## Task B: VIX Regime Split")
    lines.append("")
    merged = ret_df.merge(vix_df, on="date", how="left")
    merged.dropna(subset=["prior_vix"], inplace=True)
    merged["vix_regime"] = pd.cut(
        merged["prior_vix"],
        bins=[-np.inf, 20, 25, np.inf],
        labels=["NORMAL (<20)", "ELEVATED (20-25)", "HIGH_RISK (≥25)"]
    )
    lines.append(f"**Obs with VIX data:** {len(merged)}")
    lines.append("")
    lines.append("| Regime | N | Mean ON (%) | Mean Intra (%) | Mean Total (%) | %ON | Sharpe ON | Sharpe Intra | Corr |")
    lines.append("|--------|---|-------------|----------------|----------------|-----|-----------|--------------|------|")
    for regime in ["NORMAL (<20)", "ELEVATED (20-25)", "HIGH_RISK (≥25)"]:
        sub = merged[merged["vix_regime"] == regime]
        if sub.empty:
            continue
        on_r, intra_r, tot_r, corr_r, pct_on_r, _ = metrics_table(sub)
        lines.append(f"| {regime} | {on_r['N']} | {fmt(on_r['mean'])} | {fmt(intra_r['mean'])} | {fmt(tot_r['mean'])} | {fmt(pct_on_r, 1)}% | {fmt(on_r['sharpe'])} | {fmt(intra_r['sharpe'])} | {fmt(corr_r)} |")
    lines.append("")

    # ── Task C: EMA Gate Conditioning ──
    lines.append("## Task C: EMA Gate Conditioning")
    lines.append("")
    ema_merged = ret_df.merge(ema_df, on=["ticker", "date"], how="inner")
    lines.append(f"**Obs with EMA gate data:** {len(ema_merged)}")
    lines.append("")
    lines.append("| Gate | N | Mean ON (%) | Mean Intra (%) | Mean Total (%) | %ON | Sharpe ON | Sharpe Intra | Corr |")
    lines.append("|------|---|-------------|----------------|----------------|-----|-----------|--------------|------|")
    for gate in ["UP", "DOWN"]:
        sub = ema_merged[ema_merged["prior_gate"] == gate]
        if sub.empty:
            continue
        on_g, intra_g, tot_g, corr_g, pct_on_g, _ = metrics_table(sub)
        lines.append(f"| {gate} | {on_g['N']} | {fmt(on_g['mean'])} | {fmt(intra_g['mean'])} | {fmt(tot_g['mean'])} | {fmt(pct_on_g, 1)}% | {fmt(on_g['sharpe'])} | {fmt(intra_g['sharpe'])} | {fmt(corr_g)} |")
    lines.append("")

    # ── Task D: Overnight Predicts Intraday? ──
    lines.append("## Task D: Overnight Predicts Intraday?")
    lines.append("")
    bins = [
        ("Big gap down (<-1%)", ret_df["overnight_ret"] < -1),
        ("Small gap down (-1% to 0)", (ret_df["overnight_ret"] >= -1) & (ret_df["overnight_ret"] < 0)),
        ("Small gap up (0 to +1%)", (ret_df["overnight_ret"] >= 0) & (ret_df["overnight_ret"] < 1)),
        ("Big gap up (>+1%)", ret_df["overnight_ret"] >= 1),
    ]
    lines.append("| Overnight Bin | N | Mean Intra (%) | Intra WR (%) | Mean ON (%) | Verdict |")
    lines.append("|---------------|---|----------------|--------------|-------------|---------|")
    for label, mask in bins:
        sub = ret_df[mask]
        n = len(sub)
        mean_intra = sub["intraday_ret"].mean()
        wr = (sub["intraday_ret"] > 0).mean() * 100
        mean_on = sub["overnight_ret"].mean()
        if "gap up" in label.lower():
            verdict = "Continuation" if mean_intra > 0 else "Reversal"
        else:
            verdict = "Continuation" if mean_intra < 0 else "Reversal"
        lines.append(f"| {label} | {n} | {fmt(mean_intra)} | {fmt(wr, 1)}% | {fmt(mean_on)} | {verdict} |")
    lines.append("")

    # ── Key Answer ──
    lines.append("## Key Answer: Where Does the Return Live?")
    lines.append("")
    on_mean = ret_df["overnight_ret"].mean()
    intra_mean = ret_df["intraday_ret"].mean()
    total_mean = ret_df["total_ret"].mean()
    if total_mean != 0:
        on_pct = on_mean / total_mean * 100
        intra_pct = intra_mean / total_mean * 100
    else:
        on_pct = intra_pct = 50.0

    if abs(on_pct) > abs(intra_pct):
        dominant = "OVERNIGHT"
        weak = "intraday"
    else:
        dominant = "INTRADAY"
        weak = "overnight"

    lines.append(f"- **Overnight mean:** {fmt(on_mean)}%  ({fmt(on_pct, 1)}% of total)")
    lines.append(f"- **Intraday mean:**  {fmt(intra_mean)}%  ({fmt(intra_pct, 1)}% of total)")
    lines.append(f"- **Total mean:**     {fmt(total_mean)}%")
    lines.append(f"- **Dominant leg:** **{dominant}** — the {weak} component is relatively weaker.")
    lines.append("")
    if dominant == "OVERNIGHT":
        lines.append("This aligns with academic literature (Cliff, Cooper, Gulen 2008; "
                      "Berkman et al. 2012): the bulk of equity returns accrue overnight. "
                      "Our Module 2 intraday signals showing weak standalone performance "
                      "is therefore **expected behavior**, not a deficiency.")
    else:
        lines.append("Contrary to the typical academic finding, intraday returns dominate in this sample. "
                      "This may reflect the specific ticker universe (high-beta tech/crypto names) "
                      "or the sample period.")
    lines.append("")
    lines.append("---")
    lines.append("*End of S45 Part 1 Analysis*")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Loading M5 data and extracting daily OHLC...")
    daily = load_daily_ohlc()
    print(f"  → {len(daily)} ticker-day rows")

    print("Computing returns...")
    ret_df = compute_returns(daily)
    print(f"  → {len(ret_df)} return observations")

    print("Loading VIX data...")
    vix_df = load_vix()
    print(f"  → {len(vix_df)} VIX rows")

    print("Loading 4H EMA gates...")
    ema_df = load_ema_gates()
    print(f"  → {len(ema_df)} EMA gate rows")

    print("Generating report...")
    report = generate_report(ret_df, vix_df, ema_df)

    out_path = RESULTS_DIR / "S45_Overnight_Part1_Analysis.md"
    out_path.write_text(report)
    print(f"Saved → {out_path}")
    print()
    print(report)
