#!/usr/bin/env python3
"""S21-P2: Executable P&L simulation — laggard-long vs leader-long.

On each noon-stress day at 12:30 ET:
  Laggard strategy  — buy bottom-2 AM performers, sell 15:50
  Leader  strategy  — buy top-2    AM performers, sell 15:50
Equal weight $10k per name.  Slippage 0.05% per side.
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

TRADE_UNIVERSE = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU", "C", "COIN",
    "COST", "GOOGL", "GS", "INTC", "JPM", "MARA", "META", "MSFT", "MSTR",
    "MU", "NVDA", "PLTR", "SMCI", "TSLA", "TSM", "V",
]

CAPITAL_PER_NAME = 10_000
SLIPPAGE_BPS     = 0.0005        # 0.05 % per side
PICK_N           = 2             # bottom / top N

# ── load stress dates ────────────────────────────────────────────────────
stress_fp = OUT / "stress_noon_days.json"
if not stress_fp.exists():
    stress_fp = OUT / "stress_days.json"
stress_dates = set(json.loads(stress_fp.read_text()))
print(f"Using {stress_fp.name}  ({len(stress_dates)} stress days)")

# ── load M5 data: extract 09:30 / 12:30 / 15:50 bars per ticker ─────────
print("Loading M5 bars for 25 tickers …")
rows = []
for tkr in TRADE_UNIVERSE:
    df = pd.read_csv(OUT / f"{tkr}_m5_regsess.csv", parse_dates=["Datetime"])
    df["date"] = df["Datetime"].dt.strftime("%Y-%m-%d")
    df["time"] = df["Datetime"].dt.time
    for _, r in df[df["time"].isin([T(9, 30), T(12, 30), T(15, 50)])].iterrows():
        rows.append((r["date"], tkr, r["time"], r["Close"]))
bars = pd.DataFrame(rows, columns=["date", "ticker", "time", "close"])

# pivot: (date, ticker) → {open, entry, exit}
piv = bars.pivot_table(index=["date", "ticker"], columns="time",
                       values="close", aggfunc="first")
piv.columns = ["open", "entry", "exit"]   # 09:30, 12:30, 15:50
piv = piv.dropna().reset_index()

# filter to stress dates
piv = piv[piv["date"].isin(stress_dates)].copy()

# AM return used for ranking
piv["am_ret"] = piv["entry"] / piv["open"] - 1


# ── simulate one strategy ────────────────────────────────────────────────
def simulate(piv: pd.DataFrame, pick_bottom: bool) -> pd.DataFrame:
    """Return per-trade DataFrame with columns: date, ticker, gross_ret, pnl."""
    trades = []
    for date, grp in piv.groupby("date"):
        grp_sorted = grp.sort_values("am_ret")
        picks = grp_sorted.head(PICK_N) if pick_bottom else grp_sorted.tail(PICK_N)
        for _, row in picks.iterrows():
            gross = row["exit"] / row["entry"] - 1
            net   = gross - 2 * SLIPPAGE_BPS          # entry + exit slippage
            pnl   = CAPITAL_PER_NAME * net
            trades.append(dict(date=date, ticker=row["ticker"],
                               entry=row["entry"], exit=row["exit"],
                               gross_ret=gross, net_ret=net, pnl=pnl))
    return pd.DataFrame(trades).sort_values("date").reset_index(drop=True)


def report(trades: pd.DataFrame, label: str):
    n = len(trades)
    if n == 0:
        print(f"\n  {label}: no trades.")
        return
    wins     = (trades["pnl"] > 0).sum()
    avg_ret  = trades["net_ret"].mean()
    total    = trades["pnl"].sum()
    cum      = trades["pnl"].cumsum()
    peak     = cum.cummax()
    dd       = (cum - peak).min()
    gross_p  = trades.loc[trades["pnl"] > 0, "pnl"].sum()
    gross_l  = -trades.loc[trades["pnl"] < 0, "pnl"].sum()
    pf       = gross_p / gross_l if gross_l > 0 else float("inf")
    best     = trades.loc[trades["pnl"].idxmax()]
    worst    = trades.loc[trades["pnl"].idxmin()]
    n_events = trades["date"].nunique()

    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    print(f"  Events traded:        {n_events}")
    print(f"  Individual trades:    {n}")
    print(f"  Win rate:             {100 * wins / n:.1f}%")
    print(f"  Avg return / trade:   {100 * avg_ret:+.3f}%  (after slippage)")
    print(f"  Total P&L:            ${total:+,.2f}")
    print(f"  Max drawdown:         ${dd:+,.2f}")
    print(f"  Profit factor:        {pf:.2f}")
    print(f"  Best  trade:          ${best['pnl']:+,.2f}  "
          f"({best['ticker']} {best['date']})")
    print(f"  Worst trade:          ${worst['pnl']:+,.2f}  "
          f"({worst['ticker']} {worst['date']})")
    print(f"{'=' * 60}")


# ── run both strategies ──────────────────────────────────────────────────
lag = simulate(piv, pick_bottom=True)
lead = simulate(piv, pick_bottom=False)

report(lag,  "LAGGARD-LONG  (buy bottom 2 @ 12:30, sell 15:50)")
report(lead, "LEADER-LONG   (buy top 2 @ 12:30, sell 15:50)")

# ── equity curve chart ───────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 5))

for trades, lbl, color in [
    (lag,  "Laggard-long (Q5 bottom 2)", "#1a7f37"),
    (lead, "Leader-long  (Q1 top 2)",    "#cf222e"),
]:
    daily = trades.groupby("date")["pnl"].sum().sort_index()
    cum   = daily.cumsum()
    ax.step(range(len(cum)), cum.values, where="post", label=lbl,
            linewidth=2, color=color)

ax.axhline(0, color="grey", linewidth=0.8, linestyle="--")
ax.set_xlabel("Stress-day event #")
ax.set_ylabel("Cumulative P&L ($)")
ax.set_title("S21-P2  Noon-Stress Executable P&L\n"
             "Laggard-long vs Leader-long  |  $10k/name, 5 bps slippage/side")
ax.legend(loc="best")
ax.grid(True, alpha=0.3)
fig.tight_layout()
chart_path = OUT / "s21_p2_equity_curves.png"
fig.savefig(chart_path, dpi=150)
print(f"\nChart saved: {chart_path.relative_to(ROOT)}")
