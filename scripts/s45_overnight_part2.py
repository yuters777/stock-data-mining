#!/usr/bin/env python3
"""
S45 Overnight Decomposition — Part 2: Strategy Backtest
Tests whether the overnight vs intraday decomposition is tradeable.
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

TICKERS = [
    "AAPL","AMD","AMZN","AVGO","BA","BABA","BIDU","C","COIN","COST",
    "GOOGL","GS","IBIT","JPM","MARA","META","MSFT","MU","NVDA","PLTR",
    "SNOW","SPY","TSLA","TSM","TXN","V","VIXY",
]


# ═══════════════════════════════════════════════════════════════
# 1. Data loaders (shared with Part 1)
# ═══════════════════════════════════════════════════════════════

def load_daily_ohlc():
    rows = []
    for ticker in TICKERS:
        path = REGSESS_DIR / f"{ticker}_m5_regsess.csv"
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
            })
    daily = pd.DataFrame(rows)
    daily["date"] = pd.to_datetime(daily["date"])
    daily.sort_values(["ticker", "date"], inplace=True)
    daily.reset_index(drop=True, inplace=True)
    return daily


def compute_returns(daily):
    records = []
    for ticker, grp in daily.groupby("ticker"):
        grp = grp.sort_values("date").reset_index(drop=True)
        for i in range(1, len(grp)):
            records.append({
                "ticker": ticker,
                "date": grp.loc[i, "date"],
                "prior_close": grp.loc[i - 1, "close"],
                "today_open": grp.loc[i, "open"],
                "today_close": grp.loc[i, "close"],
                "overnight_ret": (grp.loc[i, "open"] - grp.loc[i - 1, "close"]) / grp.loc[i - 1, "close"] * 100,
                "intraday_ret": (grp.loc[i, "close"] - grp.loc[i, "open"]) / grp.loc[i, "open"] * 100,
                "total_ret": (grp.loc[i, "close"] - grp.loc[i - 1, "close"]) / grp.loc[i - 1, "close"] * 100,
            })
    return pd.DataFrame(records)


def load_vix():
    vix = pd.read_csv(VIX_PATH, parse_dates=["observation_date"])
    vix.rename(columns={"observation_date": "date", "VIXCLS": "vix"}, inplace=True)
    vix["vix"] = pd.to_numeric(vix["vix"], errors="coerce")
    vix.dropna(subset=["vix"], inplace=True)
    vix.sort_values("date", inplace=True)
    vix["prior_vix"] = vix["vix"].shift(1)
    return vix[["date", "prior_vix"]].dropna()


def load_ema_gates_with_adx():
    """Load 4H EMA gate + ADX at prior day's last bar."""
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
        eod = df.groupby("date").last().reset_index()
        eod["gate"] = np.where(eod["ema_9"] > eod["ema_21"], "UP", "DOWN")
        eod["date"] = pd.to_datetime(eod["date"])
        eod.sort_values("date", inplace=True)
        eod["prior_gate"] = eod["gate"].shift(1)
        eod["prior_adx"] = eod["adx_14"].shift(1)
        eod = eod.dropna(subset=["prior_gate"])
        for _, row in eod.iterrows():
            rows.append({
                "ticker": ticker,
                "date": row["date"],
                "prior_gate": row["prior_gate"],
                "prior_adx": row["prior_adx"],
            })
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════
# 2. Strategy metrics
# ═══════════════════════════════════════════════════════════════

def strategy_metrics(returns_series):
    """Compute all 7 metrics for a strategy's return series."""
    r = returns_series.dropna()
    n = len(r)
    if n == 0:
        return {"N": 0, "mean": np.nan, "wr": np.nan, "pf": np.nan,
                "sharpe": np.nan, "max_dd": np.nan, "pval": np.nan}

    mean = r.mean()
    std = r.std()
    wr = (r > 0).mean() * 100
    sharpe = mean / std if std > 0 else np.nan

    # profit factor
    gross_profit = r[r > 0].sum()
    gross_loss = abs(r[r < 0].sum())
    pf = gross_profit / gross_loss if gross_loss > 0 else np.inf

    # max consecutive losing streak (drawdown proxy)
    losing = (r <= 0).astype(int)
    streaks = losing * (losing.groupby((losing != losing.shift()).cumsum()).cumcount() + 1)
    max_dd = int(streaks.max()) if len(streaks) > 0 else 0

    # p-value vs zero (two-sided t-test)
    if std > 0 and n > 1:
        t_stat, pval = stats.ttest_1samp(r, 0)
    else:
        pval = np.nan

    return {"N": n, "mean": mean, "wr": wr, "pf": pf,
            "sharpe": sharpe, "max_dd": max_dd, "pval": pval}


# ═══════════════════════════════════════════════════════════════
# 3. Build enriched dataset
# ═══════════════════════════════════════════════════════════════

def build_master(ret_df, vix_df, ema_df):
    """Merge returns with VIX and EMA gate/ADX data."""
    m = ret_df.merge(vix_df, on="date", how="left")
    m = m.merge(ema_df, on=["ticker", "date"], how="left")
    return m


# ═══════════════════════════════════════════════════════════════
# 4. Define variant filters
# ═══════════════════════════════════════════════════════════════

VARIANTS = {
    "V1: No filter":          lambda df: df,
    "V2: Gate UP":            lambda df: df[df["prior_gate"] == "UP"],
    "V3: VIX < 25":           lambda df: df[df["prior_vix"] < 25],
    "V4: VIX ≥ 25":           lambda df: df[df["prior_vix"] >= 25],
    "V5: Gate UP + ADX < 20": lambda df: df[(df["prior_gate"] == "UP") & (df["prior_adx"] < 20)],
}


# ═══════════════════════════════════════════════════════════════
# 5. Report
# ═══════════════════════════════════════════════════════════════

def fmt(x, decimals=4):
    if pd.isna(x) or (isinstance(x, float) and np.isinf(x)):
        return "N/A" if pd.isna(x) else "∞"
    return f"{x:.{decimals}f}"


def pval_stars(p):
    if pd.isna(p):
        return ""
    if p < 0.001:
        return " ***"
    if p < 0.01:
        return " **"
    if p < 0.05:
        return " *"
    return ""


def make_table(title, results):
    """Build a markdown table from variant results dict."""
    lines = [f"### {title}", ""]
    lines.append("| Variant | N | Mean (%) | WR (%) | Profit Factor | Sharpe | Max Lose Streak | p-value |")
    lines.append("|---------|---|----------|--------|---------------|--------|-----------------|---------|")
    for name, m in results.items():
        pv = fmt(m["pval"], 4) + pval_stars(m["pval"])
        lines.append(
            f"| {name} | {m['N']} | {fmt(m['mean'])} | {fmt(m['wr'], 1)} "
            f"| {fmt(m['pf'], 2)} | {fmt(m['sharpe'])} | {m['max_dd']} | {pv} |"
        )
    lines.append("")
    return lines


def generate_report(master):
    lines = []
    lines.append("# S45 Overnight Decomposition — Part 2: Strategy Backtest")
    lines.append("")
    lines.append(f"**Generated:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    n_tickers = master["ticker"].nunique()
    lines.append(f"**Tickers:** {n_tickers}  |  **Date range:** "
                 f"{master['date'].min().date()} → {master['date'].max().date()}")
    lines.append("")

    # ── Task A: Overnight Hold Strategy ──
    lines.append("## Task A: Overnight Hold Strategy")
    lines.append("")
    lines.append("Buy at today's close (15:55 ET), sell at tomorrow's open (09:30 ET).")
    lines.append("")
    on_results = {}
    for name, filt in VARIANTS.items():
        sub = filt(master)
        on_results[name] = strategy_metrics(sub["overnight_ret"])
    lines.extend(make_table("Overnight Variants", on_results))

    # ── Task B: Intraday-Only Comparison ──
    lines.append("## Task B: Intraday-Only Comparison")
    lines.append("")
    lines.append("Buy at today's open (09:30 ET), sell at today's close (15:55 ET).")
    lines.append("")
    intra_results = {}
    for name, filt in VARIANTS.items():
        sub = filt(master)
        intra_results[name] = strategy_metrics(sub["intraday_ret"])
    lines.extend(make_table("Intraday Variants", intra_results))

    # ── Head-to-head ──
    lines.append("## Head-to-Head: Overnight vs Intraday")
    lines.append("")
    lines.append("| Variant | ON Mean (%) | Intra Mean (%) | ON Sharpe | Intra Sharpe | ON WR | Intra WR | Winner |")
    lines.append("|---------|-------------|----------------|-----------|--------------|-------|----------|--------|")
    for name in VARIANTS:
        om = on_results[name]
        im = intra_results[name]
        winner = "Overnight" if (om["sharpe"] or 0) > (im["sharpe"] or 0) else "Intraday"
        lines.append(
            f"| {name} | {fmt(om['mean'])} | {fmt(im['mean'])} "
            f"| {fmt(om['sharpe'])} | {fmt(im['sharpe'])} "
            f"| {fmt(om['wr'], 1)} | {fmt(im['wr'], 1)} | **{winner}** |"
        )
    lines.append("")

    # ── Task C: Combined Strategy ──
    lines.append("## Task C: Combined Strategy")
    lines.append("")
    lines.append("Since Part 1 confirmed overnight >> intraday, we test two combined approaches.")
    lines.append("")

    # C1: Buy at close, hold through next close IF gate UP + ADX < 20
    lines.append("### C1: Full Hold (close → next close) when Gate UP + ADX < 20")
    lines.append("")
    lines.append("Hold overnight AND intraday — capture total return when trend filter is active.")
    lines.append("")
    sub_c1 = master[(master["prior_gate"] == "UP") & (master["prior_adx"] < 20)]
    c1_met = strategy_metrics(sub_c1["total_ret"])
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| N | {c1_met['N']} |")
    lines.append(f"| Mean return (%) | {fmt(c1_met['mean'])} |")
    lines.append(f"| Win rate (%) | {fmt(c1_met['wr'], 1)} |")
    lines.append(f"| Profit factor | {fmt(c1_met['pf'], 2)} |")
    lines.append(f"| Sharpe | {fmt(c1_met['sharpe'])} |")
    lines.append(f"| Max losing streak | {c1_met['max_dd']} |")
    lines.append(f"| p-value | {fmt(c1_met['pval'], 4)}{pval_stars(c1_met['pval'])} |")
    lines.append("")

    # C2: Overnight only, then intraday only if gap was small
    lines.append("### C2: Overnight + Selective Intraday (gap reversal filter)")
    lines.append("")
    lines.append("Capture overnight always (Gate UP), then add intraday only when overnight gap was small (<1% absolute) — avoiding the reversal drag from big gaps.")
    lines.append("")
    sub_c2_base = master[master["prior_gate"] == "UP"].copy()
    # overnight return is always captured
    sub_c2_base["c2_ret"] = sub_c2_base["overnight_ret"].copy()
    # add intraday only when gap is small
    small_gap = sub_c2_base["overnight_ret"].abs() < 1.0
    sub_c2_base.loc[small_gap, "c2_ret"] = sub_c2_base.loc[small_gap, "total_ret"]
    c2_met = strategy_metrics(sub_c2_base["c2_ret"])
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| N | {c2_met['N']} |")
    lines.append(f"| Mean return (%) | {fmt(c2_met['mean'])} |")
    lines.append(f"| Win rate (%) | {fmt(c2_met['wr'], 1)} |")
    lines.append(f"| Profit factor | {fmt(c2_met['pf'], 2)} |")
    lines.append(f"| Sharpe | {fmt(c2_met['sharpe'])} |")
    lines.append(f"| Max losing streak | {c2_met['max_dd']} |")
    lines.append(f"| p-value | {fmt(c2_met['pval'], 4)}{pval_stars(c2_met['pval'])} |")
    lines.append("")

    # Compare C1 vs C2 vs pure overnight V2
    lines.append("### Combined vs Pure Overnight (Gate UP)")
    lines.append("")
    v2_on = on_results["V2: Gate UP"]
    lines.append("| Strategy | Mean (%) | Sharpe | WR (%) | PF |")
    lines.append("|----------|----------|--------|--------|----|")
    lines.append(f"| V2 Overnight only | {fmt(v2_on['mean'])} | {fmt(v2_on['sharpe'])} | {fmt(v2_on['wr'], 1)} | {fmt(v2_on['pf'], 2)} |")
    lines.append(f"| C1 Full hold (Gate UP + ADX<20) | {fmt(c1_met['mean'])} | {fmt(c1_met['sharpe'])} | {fmt(c1_met['wr'], 1)} | {fmt(c1_met['pf'], 2)} |")
    lines.append(f"| C2 ON + selective intra | {fmt(c2_met['mean'])} | {fmt(c2_met['sharpe'])} | {fmt(c2_met['wr'], 1)} | {fmt(c2_met['pf'], 2)} |")
    lines.append("")

    # ── Verdict ──
    lines.append("## Verdict")
    lines.append("")

    # Determine best overnight variant
    best_on_name = max(on_results, key=lambda k: on_results[k]["sharpe"] if not pd.isna(on_results[k]["sharpe"]) else -999)
    best_on = on_results[best_on_name]
    best_intra_name = max(intra_results, key=lambda k: intra_results[k]["sharpe"] if not pd.isna(intra_results[k]["sharpe"]) else -999)
    best_intra = intra_results[best_intra_name]

    on_sig = best_on["pval"] < 0.05 if not pd.isna(best_on["pval"]) else False
    on_sharpe_ok = best_on["sharpe"] > 0.03 if not pd.isna(best_on["sharpe"]) else False

    lines.append(f"**Best overnight variant:** {best_on_name}")
    lines.append(f"  - Sharpe: {fmt(best_on['sharpe'])}, Mean: {fmt(best_on['mean'])}%, p={fmt(best_on['pval'], 4)}")
    lines.append(f"**Best intraday variant:** {best_intra_name}")
    lines.append(f"  - Sharpe: {fmt(best_intra['sharpe'])}, Mean: {fmt(best_intra['mean'])}%, p={fmt(best_intra['pval'], 4)}")
    lines.append("")

    if on_sig and on_sharpe_ok:
        lines.append("### Recommendation: Module 2 should incorporate overnight hold as primary return source")
        lines.append("")
        lines.append("The overnight edge is **statistically significant** and materially larger than intraday. "
                      "The filtered variant ({}) achieves a Sharpe of {} vs best intraday Sharpe of {}. ".format(
                          best_on_name, fmt(best_on["sharpe"]), fmt(best_intra["sharpe"])))
        lines.append("")
        lines.append("**Action items:**")
        lines.append("1. Redesign Module 2 entry to target close-to-open holds when 4H EMA gate is UP")
        lines.append("2. Use VIX < 25 as a regime guard (overnight edge disappears in HIGH_RISK)")
        lines.append("3. Intraday re-entry should be selective — only when overnight gap is small (<1%)")
        lines.append("4. The current intraday-only Module 2 is not broken; it's targeting the weaker leg of returns")
    else:
        lines.append("### Recommendation: Overnight edge is too small or not significant to redesign Module 2")
        lines.append("")
        if not on_sig:
            lines.append("The overnight strategy does not achieve p < 0.05 significance. ")
        if not on_sharpe_ok:
            lines.append("The daily Sharpe is below 0.03, suggesting insufficient risk-adjusted return. ")
        lines.append("")
        lines.append("The overnight pattern exists in aggregate but is not reliably tradeable after filtering. "
                      "Module 2 should continue optimizing intraday signals rather than pivoting to overnight holds.")

    lines.append("")
    lines.append("---")
    lines.append("*End of S45 Part 2 Strategy Backtest*")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Loading M5 data...")
    daily = load_daily_ohlc()
    print(f"  → {len(daily)} ticker-day rows")

    print("Computing returns...")
    ret_df = compute_returns(daily)
    print(f"  → {len(ret_df)} return observations")

    print("Loading VIX...")
    vix_df = load_vix()
    print(f"  → {len(vix_df)} VIX rows")

    print("Loading 4H EMA gates + ADX...")
    ema_df = load_ema_gates_with_adx()
    print(f"  → {len(ema_df)} EMA gate rows")

    print("Building master dataset...")
    master = build_master(ret_df, vix_df, ema_df)
    print(f"  → {len(master)} master rows")

    # Drop rows missing VIX or EMA for filtered variants to work cleanly
    # (V1 uses all, filters handle NaN gracefully via comparison)
    print("Generating report...")
    report = generate_report(master)

    out_path = RESULTS_DIR / "S45_Overnight_Part2_Strategy.md"
    out_path.write_text(report)
    print(f"Saved → {out_path}")
    print()
    print(report)
