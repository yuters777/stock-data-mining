#!/usr/bin/env python3
"""S21-P3: 6x6 entry × exit time grid for Q5 laggard trade.

For each (entry, exit) pair on noon-stress days:
  rank tickers by return-since-open at entry time,
  buy bottom 2, sell at exit time.  Report avg return & hit rate.
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
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN", "COST",
    "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU", "NVDA",
    "PLTR", "SNOW", "TSLA", "TSM", "TXN", "V",
]
PICK_N = 2

ENTRY_TIMES = [T(12, 0), T(12, 30), T(13, 0), T(13, 30), T(14, 0), T(14, 40)]
EXIT_TIMES  = [T(13, 0), T(13, 30), T(14, 0), T(15, 0), T(15, 30), T(15, 50)]
ALL_TIMES   = sorted(set([T(9, 30)] + ENTRY_TIMES + EXIT_TIMES))

# ── load stress dates ────────────────────────────────────────────────────
stress_fp = OUT / "stress_noon_days.json"
if not stress_fp.exists():
    stress_fp = OUT / "stress_days.json"
stress_dates = set(json.loads(stress_fp.read_text()))
print(f"Using {stress_fp.name}  ({len(stress_dates)} stress days)")

# ── load M5 bars at needed times ─────────────────────────────────────────
print("Loading M5 bars for 25 tickers …")
rows = []
for tkr in TRADE_UNIVERSE:
    df = pd.read_csv(OUT / f"{tkr}_m5_regsess.csv", parse_dates=["Datetime"])
    df["date"] = df["Datetime"].dt.strftime("%Y-%m-%d")
    df["time"] = df["Datetime"].dt.time
    sub = df[df["time"].isin(ALL_TIMES) & df["date"].isin(stress_dates)]
    for _, r in sub.iterrows():
        rows.append((r["date"], tkr, r["time"], r["Close"]))

bars = pd.DataFrame(rows, columns=["date", "ticker", "time", "close"])
piv = bars.pivot_table(index=["date", "ticker"], columns="time",
                       values="close", aggfunc="first")
piv = piv.dropna(axis=0, how="any").reset_index()

# ── sweep the grid ───────────────────────────────────────────────────────
avg_ret = np.full((len(ENTRY_TIMES), len(EXIT_TIMES)), np.nan)
hit_pct = np.full_like(avg_ret, np.nan)
n_trades = np.full_like(avg_ret, np.nan)

open_t = T(9, 30)

for ei, ent in enumerate(ENTRY_TIMES):
    for xi, ext in enumerate(EXIT_TIMES):
        if ext <= ent:
            continue
        trades = []
        for date, grp in piv.groupby("date"):
            grp = grp.copy()
            grp["am_ret"] = grp[ent] / grp[open_t] - 1
            picks = grp.nsmallest(PICK_N, "am_ret")
            for _, row in picks.iterrows():
                ret = row[ext] / row[ent] - 1
                trades.append(ret)
        if trades:
            arr = np.array(trades)
            avg_ret[ei, xi]  = arr.mean() * 100
            hit_pct[ei, xi]  = (arr > 0).mean() * 100
            n_trades[ei, xi] = len(arr)

# ── pretty-print labels ─────────────────────────────────────────────────
def tlbl(t): return f"{t.hour}:{t.minute:02d}"
ent_labels = [tlbl(t) for t in ENTRY_TIMES]
ext_labels = [tlbl(t) for t in EXIT_TIMES]

# ── find optimal / safest cells ──────────────────────────────────────────
mask = ~np.isnan(avg_ret)
best_idx  = np.unravel_index(np.nanargmax(avg_ret), avg_ret.shape)
safe_idx  = np.unravel_index(np.nanargmax(hit_pct), hit_pct.shape)

print(f"\n{'=' * 62}")
print("S21-P3  Entry × Exit Time Grid  (Q5 bottom-2 laggard trade)")
print(f"{'=' * 62}")

print("\nAvg return per trade (%):")
header = "          " + "  ".join(f"{l:>6}" for l in ext_labels)
print(header)
for i, el in enumerate(ent_labels):
    vals = "  ".join(f"{avg_ret[i,j]:+6.2f}" if not np.isnan(avg_ret[i,j])
                     else "     –" for j in range(len(ext_labels)))
    print(f"  {el:>5}   {vals}")

print("\nHit rate (%):")
print(header)
for i, el in enumerate(ent_labels):
    vals = "  ".join(f"{hit_pct[i,j]:6.1f}" if not np.isnan(hit_pct[i,j])
                     else "     –" for j in range(len(ext_labels)))
    print(f"  {el:>5}   {vals}")

print(f"\nOptimal cell (best avg return): entry {ent_labels[best_idx[0]]}, "
      f"exit {ext_labels[best_idx[1]]}  →  "
      f"{avg_ret[best_idx]:+.2f}%  (hit {hit_pct[best_idx]:.0f}%, "
      f"N={int(n_trades[best_idx])})")
print(f"Safest  cell (best hit rate):   entry {ent_labels[safe_idx[0]]}, "
      f"exit {ext_labels[safe_idx[1]]}  →  "
      f"{hit_pct[safe_idx]:.1f}% hit  (avg {avg_ret[safe_idx]:+.2f}%, "
      f"N={int(n_trades[safe_idx])})")

# front-loaded vs back-loaded
early_avg = np.nanmean(avg_ret[:2, :])   # 12:00, 12:30 entries
late_avg  = np.nanmean(avg_ret[4:, :])   # 14:00, 14:40 entries
bias = "FRONT-LOADED (early entry better)" if early_avg > late_avg \
       else "BACK-LOADED (late entry better)"
print(f"\nEdge timing: {bias}")
print(f"  Early entries (12:00-12:30) avg: {early_avg:+.3f}%")
print(f"  Late  entries (14:00-14:40) avg: {late_avg:+.3f}%")
print(f"{'=' * 62}")

# ── heatmaps ─────────────────────────────────────────────────────────────
def make_heatmap(data, title, cmap, fmt, fname):
    fig, ax = plt.subplots(figsize=(7, 5.5))
    masked = np.ma.array(data, mask=np.isnan(data))
    im = ax.imshow(masked, cmap=cmap, aspect="auto")
    ax.set_xticks(range(len(ext_labels)))
    ax.set_xticklabels(ext_labels)
    ax.set_yticks(range(len(ent_labels)))
    ax.set_yticklabels(ent_labels)
    ax.set_xlabel("Exit time (ET)")
    ax.set_ylabel("Entry time (ET)")
    ax.set_title(title, fontsize=11)
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            if not np.isnan(data[i, j]):
                ax.text(j, i, fmt.format(data[i, j]),
                        ha="center", va="center", fontsize=9,
                        color="white" if abs(data[i,j]) > abs(np.nanmedian(data)) else "black")
            else:
                ax.text(j, i, "–", ha="center", va="center",
                        fontsize=9, color="grey")
    fig.colorbar(im, ax=ax, shrink=0.8)
    fig.tight_layout()
    path = OUT / fname
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path

p1 = make_heatmap(avg_ret,
    "S21-P3  Avg Return per Trade (%)\nQ5 bottom-2 laggard, noon-stress days",
    "RdYlGn", "{:+.2f}", "s21_p3_avg_return_grid.png")
p2 = make_heatmap(hit_pct,
    "S21-P3  Hit Rate (%)\nQ5 bottom-2 laggard, noon-stress days",
    "RdYlGn", "{:.0f}", "s21_p3_hit_rate_grid.png")

print(f"\nSaved: {p1.relative_to(ROOT)}")
print(f"Saved: {p2.relative_to(ROOT)}")
