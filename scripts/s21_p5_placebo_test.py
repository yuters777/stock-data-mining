#!/usr/bin/env python3
"""S21-P5: Placebo test — Q5 laggard trade on stress vs non-stress days.

Same trade (bottom 2 by AM return, buy 12:30, sell 15:50) run on ALL days.
Compare stress vs non-stress, and across severity terciles.
"""

import json, pathlib
import pandas as pd
import numpy as np
from datetime import time as T
from scipy import stats

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT  = ROOT / "backtest_output"

TRADE_UNIVERSE = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU", "C", "COIN",
    "COST", "GOOGL", "GS", "INTC", "JPM", "MARA", "META", "MSFT", "MSTR",
    "MU", "NVDA", "PLTR", "SMCI", "TSLA", "TSM", "V",
]
PICK_N = 2
NEEDED_TIMES = [T(9, 30), T(12, 30), T(15, 50)]

stress_fp = OUT / "stress_noon_days.json"
if not stress_fp.exists():
    stress_fp = OUT / "stress_days.json"
stress_dates = set(json.loads(stress_fp.read_text()))
print(f"Using {stress_fp.name}  ({len(stress_dates)} stress days)")

# ── load M5 bars at needed times ─────────────────────────────────────────
print("Loading M5 data …")
rows = []
for tkr in TRADE_UNIVERSE:
    df = pd.read_csv(OUT / f"{tkr}_m5_regsess.csv", parse_dates=["Datetime"])
    df["date"] = df["Datetime"].dt.strftime("%Y-%m-%d")
    df["time"] = df["Datetime"].dt.time
    sub = df[df["time"].isin(NEEDED_TIMES)]
    for _, r in sub.iterrows():
        rows.append((r["date"], tkr, r["time"], r["Close"]))

bars = pd.DataFrame(rows, columns=["date", "ticker", "time", "close"])
piv = bars.pivot_table(index=["date", "ticker"], columns="time",
                       values="close", aggfunc="first")
piv.columns = ["open", "entry", "exit"]
piv = piv.dropna().reset_index()
piv["am_ret"] = piv["entry"] / piv["open"] - 1
piv["pm_ret"] = piv["exit"] / piv["entry"] - 1

# filter days with 20+ tickers
day_counts = piv.groupby("date")["ticker"].nunique()
valid_days = set(day_counts[day_counts >= 20].index)
piv = piv[piv["date"].isin(valid_days)].copy()

# ── run Q5 bottom-2 trade on every valid day ─────────────────────────────
trades = []
for date, grp in piv.groupby("date"):
    picks = grp.nsmallest(PICK_N, "am_ret")
    median_am = grp["am_ret"].median()
    for _, r in picks.iterrows():
        trades.append(dict(date=date, ticker=r["ticker"], pm_ret=r["pm_ret"],
                           median_am=median_am,
                           is_stress=date in stress_dates))

tdf = pd.DataFrame(trades)
print(f"Total trades: {len(tdf)} across {tdf['date'].nunique()} days  "
      f"(stress={tdf['is_stress'].sum()}, non-stress={( ~tdf['is_stress']).sum()})")


def grp_stats(sub, label):
    n = len(sub)
    if n == 0:
        return None
    avg = sub["pm_ret"].mean() * 100
    hit = (sub["pm_ret"] > 0).mean() * 100
    med = sub["pm_ret"].median() * 100
    return dict(label=label, avg=avg, hit=hit, median=med, n=n,
                vals=sub["pm_ret"].values)

# ── stress vs non-stress ─────────────────────────────────────────────────
s  = grp_stats(tdf[tdf["is_stress"]],  "Stress days")
ns = grp_stats(tdf[~tdf["is_stress"]], "Non-stress days")

print(f"\n{'=' * 65}")
print("S21-P5  Placebo Test: Q5 Laggard Trade (bottom 2, 12:30→15:50)")
print(f"{'=' * 65}")
print(f"\n{'Group':<20} {'Avg PM':>8} {'Median':>8} {'Hit%':>7} {'N':>6}")
print("-" * 52)
for g in [s, ns]:
    print(f"  {g['label']:<18} {g['avg']:>+7.3f}% {g['median']:>+7.3f}% "
          f"{g['hit']:>6.1f}% {g['n']:>5}")

t_val, p_val = stats.ttest_ind(s["vals"], ns["vals"], equal_var=False)
diff = s["avg"] - ns["avg"]
print(f"\n  Stress − Non-stress: {diff:+.3f}%   t={t_val:+.3f}, p={p_val:.4f}"
      f"  {'***' if p_val < 0.01 else '**' if p_val < 0.05 else '*' if p_val < 0.1 else '(n.s.)'}")

if p_val < 0.05:
    print("  → Effect is STRESS-SPECIFIC — belongs inside Override exception")
else:
    print("  → Effect is a GENERIC intraday reversal — not stress-specific")

# ── tercile analysis ─────────────────────────────────────────────────────
day_median = tdf.groupby("date")["median_am"].first()
t1, t2 = day_median.quantile([1/3, 2/3])
tdf["tercile"] = pd.cut(tdf["median_am"], bins=[-np.inf, t1, t2, np.inf],
                         labels=["Heavy stress", "Mild stress", "Normal/positive"])

print(f"\n── Severity Tercile Gradient ──")
print(f"  Tercile boundaries: heavy < {t1*100:.2f}% < mild < {t2*100:.2f}% < normal")
print(f"\n{'Tercile':<20} {'Avg PM':>8} {'Median':>8} {'Hit%':>7} {'N':>6}")
print("-" * 52)

terc_vals = {}
for terc in ["Heavy stress", "Mild stress", "Normal/positive"]:
    sub = tdf[tdf["tercile"] == terc]
    g = grp_stats(sub, terc)
    terc_vals[terc] = g
    print(f"  {g['label']:<18} {g['avg']:>+7.3f}% {g['median']:>+7.3f}% "
          f"{g['hit']:>6.1f}% {g['n']:>5}")

# gradient test: heavy vs normal
h = terc_vals["Heavy stress"]["vals"]
n = terc_vals["Normal/positive"]["vals"]
t3, p3 = stats.ttest_ind(h, n, equal_var=False)
spread = terc_vals["Heavy stress"]["avg"] - terc_vals["Normal/positive"]["avg"]
print(f"\n  Heavy − Normal spread: {spread:+.3f}%   t={t3:+.3f}, p={p3:.4f}"
      f"  {'***' if p3 < 0.01 else '**' if p3 < 0.05 else '*' if p3 < 0.1 else '(n.s.)'}")

mono = (terc_vals["Heavy stress"]["avg"] > terc_vals["Mild stress"]["avg"]
        > terc_vals["Normal/positive"]["avg"])
print(f"  Monotonic gradient: {'YES' if mono else 'NO'}")
print(f"{'=' * 65}")
