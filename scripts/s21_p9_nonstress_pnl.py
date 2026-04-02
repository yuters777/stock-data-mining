#!/usr/bin/env python3
"""S21-P9: Q5 laggard trade on ALL days — stress vs non-stress vs combined.

Entry at 12:00 bar close, exit at 15:30 bar close.
Bottom-2 by AM return, $10k/name, 5 bps slippage/side.
"""

import json, pathlib
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import time as T

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT  = ROOT / "backtest_output"

TICKERS = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU", "C", "COIN",
    "COST", "GOOGL", "GS", "INTC", "JPM", "MARA", "META", "MSFT", "MSTR",
    "MU", "NVDA", "PLTR", "SMCI", "TSLA", "TSM", "V",
]
PICK_N = 2
CAPITAL = 10_000
SLIP    = 0.0005          # 5 bps per side
OPEN_T, ENTRY_T, EXIT_T = T(9, 30), T(12, 0), T(15, 30)
NEEDED_TIMES = [OPEN_T, ENTRY_T, EXIT_T]

stress_dates = set(json.loads((OUT / "stress_noon_days.json").read_text()))
print(f"Stress days: {len(stress_dates)}")

# ── load M5 data: 09:30 / 12:00 / 15:30 bars ──────────────────────────
print("Loading M5 bars for 25 tickers …")
rows = []
for tkr in TICKERS:
    df = pd.read_csv(OUT / f"{tkr}_m5_regsess.csv", parse_dates=["Datetime"])
    df["date"] = df["Datetime"].dt.strftime("%Y-%m-%d")
    df["time"] = df["Datetime"].dt.time
    for _, r in df[df["time"].isin(NEEDED_TIMES)].iterrows():
        rows.append((r["date"], tkr, r["time"], r["Close"]))

bars = pd.DataFrame(rows, columns=["date", "ticker", "time", "close"])
piv = bars.pivot_table(index=["date", "ticker"], columns="time",
                       values="close", aggfunc="first")
piv.columns = ["open", "entry", "exit"]
piv = piv.dropna().reset_index()
piv["am_ret"] = piv["entry"] / piv["open"] - 1

# ── filter to days with >= 20 valid tickers ────────────────────────────
day_counts = piv.groupby("date").size()
valid_days = set(day_counts[day_counts >= 20].index)
piv = piv[piv["date"].isin(valid_days)].copy()
all_days   = sorted(valid_days)
stress_set = valid_days & stress_dates
nonstress  = valid_days - stress_dates
print(f"Valid days: {len(valid_days)}  (stress: {len(stress_set)}, "
      f"non-stress: {len(nonstress)})")

# ── simulate trades ────────────────────────────────────────────────────
trade_rows = []
for date, grp in piv.groupby("date"):
    bottom = grp.nsmallest(PICK_N, "am_ret")
    for _, r in bottom.iterrows():
        gross = r["exit"] / r["entry"] - 1
        net   = gross - 2 * SLIP
        pnl   = CAPITAL * net
        trade_rows.append(dict(date=date, ticker=r["ticker"],
                               gross_ret=gross, net_ret=net, pnl=pnl,
                               is_stress=date in stress_dates))
tdf = pd.DataFrame(trade_rows).sort_values("date").reset_index(drop=True)

# ── reporting helper ───────────────────────────────────────────────────
def metrics(df, label):
    n = len(df)
    if n == 0:
        return {}
    wins   = (df["pnl"] > 0).sum()
    cum    = df.groupby("date")["pnl"].sum().sort_index().cumsum()
    dd     = (cum - cum.cummax()).min()
    gross_w = df.loc[df["pnl"] > 0, "pnl"].sum()
    gross_l = -df.loc[df["pnl"] < 0, "pnl"].sum()
    pf     = gross_w / gross_l if gross_l > 0 else float("inf")
    n_days = df["date"].nunique()
    daily  = df.groupby("date")["pnl"].sum()
    sharpe = daily.mean() / daily.std() * np.sqrt(252) if daily.std() > 0 else np.nan
    dw = (daily > 0).astype(int)
    streaks = dw.groupby((dw != dw.shift()).cumsum())
    max_cl = max((len(g) for _, g in streaks if g.iloc[0] == 0), default=0)
    mo_pnl = df.assign(mo=pd.to_datetime(df["date"]).dt.to_period("M")).groupby("mo")["pnl"].sum()
    in_dd = cum < cum.cummax()
    dd_dur = in_dd.groupby((~in_dd).cumsum()).sum().max() if in_dd.any() else 0
    best, worst = df.loc[df["pnl"].idxmax()], df.loc[df["pnl"].idxmin()]
    m = dict(label=label, n_days=n_days, n_trades=n,
             win_rate=100 * wins / n, avg_ret=df["net_ret"].mean() * 100,
             total_pnl=df["pnl"].sum(), max_dd=dd, pf=pf, sharpe=sharpe,
             max_consec_loss=max_cl, worst_month=mo_pnl.min(),
             worst_month_lbl=str(mo_pnl.idxmin()), dd_duration=int(dd_dur),
             best_tkr=best["ticker"], best_date=best["date"],
             best_pnl=best["pnl"], worst_tkr=worst["ticker"],
             worst_date=worst["date"], worst_pnl=worst["pnl"])
    return m

stress_df    = tdf[tdf["is_stress"]].copy()
nonstress_df = tdf[~tdf["is_stress"]].copy()

ms = metrics(stress_df,    "Stress-Only (19d)")
mn = metrics(nonstress_df, "Non-Stress")
ma = metrics(tdf,          "All Days")

# ── head-to-head comparison table ──────────────────────────────────────
print(f"\n{'='*72}")
print("Head-to-Head Comparison")
print(f"{'='*72}")
hdr = f"  {'Metric':<22} {'Stress-Only':>14} {'Non-Stress':>14} {'All Days':>14}"
print(hdr)
print(f"  {'-'*22} {'-'*14} {'-'*14} {'-'*14}")
rows_fmt = [
    ("Days traded",       "n_days",          "{:>14d}"),
    ("Individual trades", "n_trades",        "{:>14d}"),
    ("Win rate",          "win_rate",        "{:>13.1f}%"),
    ("Avg return/trade",  "avg_ret",         "{:>+13.3f}%"),
    ("Total P&L",         "total_pnl",       "${:>+13,.2f}"),
    ("Sharpe (ann.)",     "sharpe",          "{:>14.2f}"),
    ("Max DD",            "max_dd",          "${:>+13,.2f}"),
    ("Profit factor",     "pf",             "{:>14.2f}"),
    ("Max consec losses", "max_consec_loss", "{:>14d}"),
    ("Worst month",       "worst_month",     "${:>+13,.2f}"),
    ("DD duration (days)","dd_duration",     "{:>14d}"),
]
for lbl, key, fmt in rows_fmt:
    vals = [fmt.format(m[key]) for m in [ms, mn, ma]]
    print(f"  {lbl:<22} {vals[0]:>14} {vals[1]:>14} {vals[2]:>14}")
for m in [ms, mn, ma]:
    print(f"\n  {m['label']}:")
    print(f"    Best:  ${m['best_pnl']:+,.2f} ({m['best_tkr']} {m['best_date']})")
    print(f"    Worst: ${m['worst_pnl']:+,.2f} ({m['worst_tkr']} {m['worst_date']})")

# ── monthly breakdown (non-stress) ────────────────────────────────────
print(f"\n{'='*62}")
print("Monthly Breakdown — Non-Stress")
print(f"{'='*62}")
nonstress_df = nonstress_df.copy()
nonstress_df["month"] = pd.to_datetime(nonstress_df["date"]).dt.to_period("M")
mo = nonstress_df.groupby("month").agg(
    n_trades=("pnl", "size"), avg_ret=("net_ret", "mean"),
    total=("pnl", "sum"), hit=("pnl", lambda x: (x > 0).mean())
)
print(f"  {'Month':<10} {'N':>4} {'AvgRet':>9} {'P&L':>12} {'Hit%':>7}")
for idx, r in mo.iterrows():
    print(f"  {str(idx):<10} {int(r['n_trades']):>4} {r['avg_ret']*100:>+8.3f}% "
          f"${r['total']:>+11,.2f} {r['hit']*100:>6.1f}%")

# ── answer: is daily viable? ──────────────────────────────────────────
ann_pnl_stress   = ms["total_pnl"] / len(all_days) * 252
ann_pnl_nonstress = mn["total_pnl"] / len(all_days) * 252
ann_pnl_all      = ma["total_pnl"] / len(all_days) * 252
print(f"\n{'='*62}")
print("Annualized Estimates (prorated to 252 trading days)")
print(f"{'='*62}")
print(f"  Stress-only:   ${ann_pnl_stress:>+12,.2f}/yr  "
      f"(~{ms['n_days']} events/yr)")
print(f"  Non-stress:    ${ann_pnl_nonstress:>+12,.2f}/yr  "
      f"(~{mn['n_days']} events/yr)")
print(f"  All days:      ${ann_pnl_all:>+12,.2f}/yr  "
      f"(~{ma['n_days']} events/yr)")
print(f"\n  Better annual Sharpe: "
      f"{'STRESS-ONLY' if ms['sharpe'] > mn['sharpe'] else 'NON-STRESS'}"
      f"  ({ms['sharpe']:.2f} vs {mn['sharpe']:.2f})")

# ── equity curve chart ─────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(12, 5.5))
for sub, lbl, clr in [
    (stress_df,    "Stress-only",  "#cf222e"),
    (nonstress_df, "Non-stress",   "#0969da"),
    (tdf,          "All days",     "#1a7f37"),
]:
    daily = sub.groupby("date")["pnl"].sum().reindex(all_days, fill_value=0)
    cum = daily.cumsum()
    ax.plot(range(len(cum)), cum.values, label=lbl, lw=1.8, color=clr,
            alpha=0.9 if lbl != "All days" else 1.0)

ax.axhline(0, color="grey", lw=0.8, ls="--")
n_ticks = 8
step = max(1, len(all_days) // n_ticks)
ax.set_xticks(range(0, len(all_days), step))
ax.set_xticklabels([all_days[i] for i in range(0, len(all_days), step)],
                   rotation=45, ha="right", fontsize=8)
ax.set_ylabel("Cumulative P&L ($)")
ax.set_title("S21-P9  Q5 Bottom-2 Laggard: Stress vs Non-Stress vs All Days\n"
             "Entry 12:00 → Exit 15:30  |  $10k/name, 5 bps slippage/side")
ax.legend(loc="upper left")
ax.grid(True, alpha=0.3)
fig.tight_layout()
chart = OUT / "s21_p9_equity_curves.png"
fig.savefig(chart, dpi=150)
plt.close(fig)
print(f"\nSaved: {chart.relative_to(ROOT)}")
