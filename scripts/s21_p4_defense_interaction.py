#!/usr/bin/env python3
"""S21-P4: Does DefenseRank improve Q5 laggard selection?

Rank by AM return → Q5 (bottom 5). Within Q5, DefenseScore = -MaxDD_AM/ATR20.
Split → Q5_HiDef (top half) vs Q5_LoDef. Measure PM return 12:30→15:50.
"""

import json, pathlib
import pandas as pd
import numpy as np
from datetime import time as T
from scipy import stats

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT  = ROOT / "backtest_output"

TRADE_UNIVERSE = [
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN", "COST",
    "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU", "NVDA",
    "PLTR", "SNOW", "TSLA", "TSM", "TXN", "V",
]

stress_fp = OUT / "stress_noon_days.json"
if not stress_fp.exists():
    stress_fp = OUT / "stress_days.json"
stress_dates = set(json.loads(stress_fp.read_text()))
print(f"Using {stress_fp.name}  ({len(stress_dates)} stress days)")

# ── load daily data for ATR20 ────────────────────────────────────────────
print("Loading daily + M5 data …")
daily_hl = {}
for tkr in TRADE_UNIVERSE:
    df = pd.read_csv(OUT / f"{tkr}_daily.csv", parse_dates=["date"])
    df["range"] = df["High"] - df["Low"]
    df["atr20"] = df["range"].rolling(20).mean()
    daily_hl[tkr] = df.set_index("date")[["atr20"]]

# ── load M5 data ─────────────────────────────────────────────────────────
m5_all = {}
for tkr in TRADE_UNIVERSE:
    df = pd.read_csv(OUT / f"{tkr}_m5_regsess.csv", parse_dates=["Datetime"])
    df["date"] = df["Datetime"].dt.strftime("%Y-%m-%d")
    df["time"] = df["Datetime"].dt.time
    m5_all[tkr] = df


def max_dd_am(m5_day: pd.DataFrame) -> float:
    """Max peak-to-trough drawdown on M5 closes from 09:30-12:00."""
    prices = m5_day.loc[m5_day["time"] <= T(12, 0), "Close"].values
    if len(prices) < 2:
        return 0.0
    peak = np.maximum.accumulate(prices)
    dd = (prices - peak) / peak
    return float(dd.min())            # negative number


# ── main loop ────────────────────────────────────────────────────────────
records = []   # (date, ticker, group, pm_ret)

for date_str in sorted(stress_dates):
    date_pd = pd.Timestamp(date_str)

    # AM return and DefenseScore per ticker
    ticker_info = []
    for tkr in TRADE_UNIVERSE:
        df = m5_all[tkr]
        day = df[df["date"] == date_str]
        if day.empty:
            continue

        open_bar = day.loc[day["time"] == T(9, 30), "Close"]
        noon_bar = day.loc[day["time"] == T(12, 0), "Close"]
        entry_bar = day.loc[day["time"] == T(12, 30), "Close"]
        exit_bar  = day.loc[day["time"] == T(15, 50), "Close"]
        if open_bar.empty or noon_bar.empty or entry_bar.empty or exit_bar.empty:
            continue

        am_ret = noon_bar.iloc[0] / open_bar.iloc[0] - 1
        pm_ret = exit_bar.iloc[0] / entry_bar.iloc[0] - 1

        mdd = max_dd_am(day)

        atr_row = daily_hl[tkr]
        prior = atr_row.loc[atr_row.index < date_pd, "atr20"]
        atr20 = prior.iloc[-1] if len(prior) else np.nan
        defense = -mdd / atr20 if (atr20 and atr20 > 0) else 0.0

        ticker_info.append(dict(ticker=tkr, am_ret=am_ret, pm_ret=pm_ret,
                                mdd=mdd, atr20=atr20, defense=defense))

    if len(ticker_info) < 10:
        continue

    tdf = pd.DataFrame(ticker_info).sort_values("am_ret")
    q5 = tdf.head(5)
    q1 = tdf.tail(5)

    # split Q5 by DefenseScore
    q5s = q5.sort_values("defense", ascending=False)
    mid = len(q5s) // 2
    q5_hi = q5s.iloc[:mid + (1 if len(q5s) % 2 else 0)]   # top half (2-3)
    q5_lo = q5s.iloc[mid + (1 if len(q5s) % 2 else 0):]    # bottom half (2)

    for _, r in q5.iterrows():
        records.append((date_str, r["ticker"], "Q5_All", r["pm_ret"]))
    for _, r in q5_hi.iterrows():
        records.append((date_str, r["ticker"], "Q5_HiDef", r["pm_ret"]))
    for _, r in q5_lo.iterrows():
        records.append((date_str, r["ticker"], "Q5_LoDef", r["pm_ret"]))
    for _, r in q1.iterrows():
        records.append((date_str, r["ticker"], "Q1_Ref", r["pm_ret"]))

rdf = pd.DataFrame(records, columns=["date", "ticker", "group", "pm_ret"])

# ── report ───────────────────────────────────────────────────────────────
print(f"\n{'=' * 65}")
print("S21-P4  DefenseRank Interaction with Q5 Laggard Selection")
print(f"{'=' * 65}")
print(f"\n{'Group':<12} {'Avg PM Ret':>10} {'Hit Rate':>10} {'N':>5}")
print("-" * 42)

group_stats = {}
for grp in ["Q5_All", "Q5_HiDef", "Q5_LoDef", "Q1_Ref"]:
    sub = rdf[rdf["group"] == grp]["pm_ret"]
    avg = sub.mean() * 100
    hit = (sub > 0).mean() * 100
    n   = len(sub)
    group_stats[grp] = sub
    print(f"  {grp:<10} {avg:>+9.3f}% {hit:>9.1f}% {n:>5}")

# t-tests
hi = group_stats["Q5_HiDef"].values
lo = group_stats["Q5_LoDef"].values
t1, p1 = stats.ttest_ind(hi, lo, equal_var=False)
print(f"\n  Q5_HiDef vs Q5_LoDef:  t={t1:+.3f}, p={p1:.4f}"
      f"  {'*' if p1 < 0.05 else '(n.s.)'}")

all5 = group_stats["Q5_All"].values
t2, p2 = stats.ttest_ind(hi, all5, equal_var=False)
print(f"  Q5_HiDef vs Q5_All:    t={t2:+.3f}, p={p2:.4f}"
      f"  {'*' if p2 < 0.05 else '(n.s.)'}")

hi_avg = hi.mean() * 100
lo_avg = lo.mean() * 100
spread = hi_avg - lo_avg
print(f"\n  HiDef–LoDef spread: {spread:+.3f}%")
if spread > 0:
    print("  → 'Oversold but not broken' OUTPERFORMS 'oversold and smashed'")
else:
    print("  → No benefit from DefenseRank filtering within Q5")
print(f"{'=' * 65}")
