#!/usr/bin/env python3
"""S21-P8: MAE/MFE intraday path analysis for Stress MR Entry v0.1.

Bottom-2 laggard trade on 19 noon-stress days (38 trades total).
Entry at 12:00 bar close, exit at 15:30 bar close.
Tracks full M5 path: MAE, MFE, stop-loss & partial-profit analysis.
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
ENTRY_T, EXIT_T, OPEN_T = T(12, 0), T(15, 30), T(9, 30)

# ── load stress dates ───────────────────────────────────────────────────
stress_fp = OUT / "stress_noon_days.json"
stress_dates = set(json.loads(stress_fp.read_text()))
print(f"Stress days: {len(stress_dates)}")

# ── load ALL M5 bars 09:30-15:30 on stress days ────────────────────────
print("Loading M5 bars …")
frames = []
for tkr in TRADE_UNIVERSE:
    df = pd.read_csv(OUT / f"{tkr}_m5_regsess.csv", parse_dates=["Datetime"])
    df["date"] = df["Datetime"].dt.strftime("%Y-%m-%d")
    df["time"] = df["Datetime"].dt.time
    frames.append(df[df["date"].isin(stress_dates) & (df["time"] <= EXIT_T)])
all_bars = pd.concat(frames, ignore_index=True)

# ── identify bottom-2 tickers per day (rank by AM ret to 12:00) ────────
rank_bars = all_bars[all_bars["time"].isin([OPEN_T, ENTRY_T])].copy()
rpiv = rank_bars.pivot_table(index=["date", "Ticker"], columns="time",
                              values="Close", aggfunc="first").dropna().reset_index()
rpiv["am_ret"] = rpiv[ENTRY_T] / rpiv[OPEN_T] - 1
pick_rows = []
for date, grp in rpiv.groupby("date"):
    bottom = grp.nsmallest(PICK_N, "am_ret")
    for _, r in bottom.iterrows():
        pick_rows.append({"date": r["date"], "ticker": r["Ticker"],
                          "entry_price": r[ENTRY_T]})
picks = pd.DataFrame(pick_rows)
print(f"Trades: {len(picks)}")

# ── build intraday paths ───────────────────────────────────────────────
path_bars = all_bars[(all_bars["time"] >= ENTRY_T) & (all_bars["time"] <= EXIT_T)]
path_bars = path_bars.merge(picks, left_on=["date", "Ticker"],
                            right_on=["date", "ticker"])
path_bars["bar_ret"] = path_bars["Close"] / path_bars["entry_price"] - 1
path_bars["minutes"] = path_bars["Datetime"].dt.hour * 60 + path_bars["Datetime"].dt.minute - 720

# per-trade aggregates
trades = []
for (d, tkr), grp in path_bars.groupby(["date", "ticker"]):
    rets = grp.sort_values("time")["bar_ret"].values
    times_m = grp.sort_values("time")["minutes"].values
    mae = rets.min()
    mfe = rets.max()
    final = rets[-1]
    mae_min = times_m[np.argmin(rets)]
    mfe_min = times_m[np.argmax(rets)]
    trades.append(dict(date=d, ticker=tkr, mae=mae, mfe=mfe, final_ret=final,
                       mae_time=mae_min, mfe_time=mfe_min))
tdf = pd.DataFrame(trades)

# ── 1. Summary statistics ──────────────────────────────────────────────
print(f"\n{'='*65}")
print("MAE / MFE Summary Statistics  (N = {})".format(len(tdf)))
print(f"{'='*65}")
for metric, col in [("MAE", "mae"), ("MFE", "mfe")]:
    s = tdf[col]
    print(f"  {metric}:  median {s.median()*100:+.2f}%  mean {s.mean()*100:+.2f}%  "
          f"{'worst' if col=='mae' else 'best'} {s.min()*100 if col=='mae' else s.max()*100:+.2f}%")
print(f"  Final:  median {tdf['final_ret'].median()*100:+.2f}%  "
      f"mean {tdf['final_ret'].mean()*100:+.2f}%")
print(f"\n  % trades MAE > -0.5%  (meaningful dip):  "
      f"{(tdf['mae'] < -0.005).mean()*100:.1f}%")
print(f"  % trades MFE > +1.0%  (reached +1R):     "
      f"{(tdf['mfe'] > 0.010).mean()*100:.1f}%")
print(f"  % trades MFE > +2.0%:                     "
      f"{(tdf['mfe'] > 0.020).mean()*100:.1f}%")
print(f"\n  Time-to-MAE:  mean {tdf['mae_time'].mean():.0f} min after entry")
print(f"  Time-to-MFE:  mean {tdf['mfe_time'].mean():.0f} min after entry")

# ── 4. Stop-loss analysis ──────────────────────────────────────────────
print(f"\n{'='*65}")
print("Stop-Loss Analysis")
print(f"{'='*65}")
baseline_pnl = tdf["final_ret"].sum()
print(f"  {'Stop':>8} | {'Stopped':>7} | {'Would-Win':>9} | {'Net P&L':>10} | {'Delta':>10}")
print(f"  {'-'*8}-+-{'-'*7}-+-{'-'*9}-+-{'-'*10}-+-{'-'*10}")
for stop in [-0.0025, -0.0050, -0.0075, -0.0100, -0.0150]:
    stopped = tdf["mae"] <= stop
    n_stopped = stopped.sum()
    would_win = (stopped & (tdf["final_ret"] > 0)).sum()
    # stopped trades exit at stop level; rest keep final
    pnl_with_stop = tdf.loc[~stopped, "final_ret"].sum() + n_stopped * stop
    delta = pnl_with_stop - baseline_pnl
    print(f"  {stop*100:+7.2f}% | {n_stopped:>7} | {would_win:>9} | "
          f"{pnl_with_stop*100:+10.2f}% | {delta*100:+10.2f}%")

# ── 5. Partial profit analysis ─────────────────────────────────────────
print(f"\n{'='*65}")
print("Partial Profit Analysis  (take 50% off at target)")
print(f"{'='*65}")
print(f"  {'Target':>8} | {'Reached':>7} | {'Avg w/ partial':>14} | {'Avg w/o':>10} | {'Delta':>10}")
print(f"  {'-'*8}-+-{'-'*7}-+-{'-'*14}-+-{'-'*10}-+-{'-'*10}")
no_partial_avg = tdf["final_ret"].mean()
for tgt in [0.0050, 0.0075, 0.0100, 0.0150]:
    reached = tdf["mfe"] >= tgt
    n_reached = reached.sum()
    # reached trades: 50% exits at target, 50% rides to close
    partial_ret = tdf["final_ret"].copy()
    partial_ret[reached] = 0.5 * tgt + 0.5 * tdf.loc[reached, "final_ret"]
    avg_partial = partial_ret.mean()
    delta = avg_partial - no_partial_avg
    print(f"  {tgt*100:+7.2f}% | {n_reached:>4}/{len(tdf):<2} | "
          f"{avg_partial*100:+14.3f}% | {no_partial_avg*100:+10.3f}% | {delta*100:+10.3f}%")

# ── Charts ──────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(12, 5))

# MAE histogram
axes[0].hist(tdf["mae"] * 100, bins=15, color="#cf222e", edgecolor="white", alpha=0.85)
axes[0].axvline(tdf["mae"].median() * 100, color="black", ls="--", lw=1.5,
                label=f'Median {tdf["mae"].median()*100:.2f}%')
axes[0].set_xlabel("MAE (%)")
axes[0].set_ylabel("Count")
axes[0].set_title("Maximum Adverse Excursion")
axes[0].legend()

# MFE histogram
axes[1].hist(tdf["mfe"] * 100, bins=15, color="#1a7f37", edgecolor="white", alpha=0.85)
axes[1].axvline(tdf["mfe"].median() * 100, color="black", ls="--", lw=1.5,
                label=f'Median {tdf["mfe"].median()*100:.2f}%')
axes[1].set_xlabel("MFE (%)")
axes[1].set_ylabel("Count")
axes[1].set_title("Maximum Favorable Excursion")
axes[1].legend()

fig.suptitle("S21-P8  MAE / MFE Distributions  (38 trades, 12:00→15:30)", fontsize=13)
fig.tight_layout()
p1 = OUT / "s21_p8_mae_mfe_hist.png"
fig.savefig(p1, dpi=150)
plt.close(fig)

# ── Avg intraday path (cumulative return at M5 resolution) ─────────────
avg_path = path_bars.groupby("minutes")["bar_ret"].mean().sort_index()
fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(avg_path.index, avg_path.values * 100, color="#0969da", lw=2)
ax.fill_between(avg_path.index, avg_path.values * 100, alpha=0.15, color="#0969da")
ax.axhline(0, color="grey", lw=0.8, ls="--")

# add percentile bands
p25 = path_bars.groupby("minutes")["bar_ret"].quantile(0.25).sort_index()
p75 = path_bars.groupby("minutes")["bar_ret"].quantile(0.75).sort_index()
ax.fill_between(avg_path.index, p25.values * 100, p75.values * 100,
                alpha=0.10, color="#0969da", label="25th–75th pctl")

xticks = list(range(0, int(avg_path.index.max()) + 1, 30))
ax.set_xticks(xticks)
ax.set_xticklabels([f"{(720+m)//60}:{(720+m)%60:02d}" for m in xticks], rotation=45)
ax.set_xlabel("Time (ET)")
ax.set_ylabel("Avg Return from Entry (%)")
ax.set_title("S21-P8  Average Intraday Trade Path  (38 trades, M5 resolution)")
ax.legend(loc="upper left")
ax.grid(True, alpha=0.3)
fig.tight_layout()
p2 = OUT / "s21_p8_avg_path.png"
fig.savefig(p2, dpi=150)
plt.close(fig)

# ── Scatter: MAE/MFE vs Final Return ───────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(12, 5))
for ax, col, lbl, clr in [(axes[0], "mae", "MAE", "#cf222e"),
                           (axes[1], "mfe", "MFE", "#1a7f37")]:
    ax.scatter(tdf[col] * 100, tdf["final_ret"] * 100, c=clr, alpha=0.7, s=50)
    ax.set_xlabel(f"{lbl} (%)")
    ax.set_ylabel("Final Return (%)")
    ax.set_title(f"{lbl} vs Final Return")
    ax.axhline(0, color="grey", lw=0.8, ls="--")
    ax.axvline(0, color="grey", lw=0.8, ls="--")
    ax.grid(True, alpha=0.3)
fig.suptitle("S21-P8  MAE/MFE vs Final Return", fontsize=13)
fig.tight_layout()
p3 = OUT / "s21_p8_scatter.png"
fig.savefig(p3, dpi=150)
plt.close(fig)

print(f"\nSaved: {p1.relative_to(ROOT)}")
print(f"Saved: {p2.relative_to(ROOT)}")
print(f"Saved: {p3.relative_to(ROOT)}")
