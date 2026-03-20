#!/usr/bin/env python3
"""S21-P10: Stress threshold robustness — sweep 6 noon-median cutoffs.

For each threshold, count stress days, run bottom-2 laggard trade
(entry 12:00, exit 15:30, $10k/name, 5 bps slippage/side), and compare.
"""

import pathlib
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import time as T

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT  = ROOT / "backtest_output"

TICKERS = [
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN", "COST",
    "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU", "NVDA",
    "PLTR", "SNOW", "TSLA", "TSM", "TXN", "V",
]
PICK_N = 2
CAPITAL = 10_000
SLIP = 0.0005
OPEN_T, ENTRY_T, EXIT_T = T(9, 30), T(12, 0), T(15, 30)
THRESHOLDS = [-0.0025, -0.0050, -0.0075, -0.0100, -0.0125, -0.0150]
LABELS = ["< -0.25%", "< -0.50%", "< -0.75%", "< -1.00%", "< -1.25%", "< -1.50%"]

# ── load M5 data ────────────────────────────────────────────────────────
print("Loading M5 bars for 25 tickers …")
rows = []
for tkr in TICKERS:
    df = pd.read_csv(OUT / f"{tkr}_m5_regsess.csv", parse_dates=["Datetime"])
    df["date"] = df["Datetime"].dt.strftime("%Y-%m-%d")
    df["time"] = df["Datetime"].dt.time
    for _, r in df[df["time"].isin([OPEN_T, ENTRY_T, EXIT_T])].iterrows():
        rows.append((r["date"], tkr, r["time"], r["Close"]))

bars = pd.DataFrame(rows, columns=["date", "ticker", "time", "close"])
piv = bars.pivot_table(index=["date", "ticker"], columns="time",
                       values="close", aggfunc="first")
piv.columns = ["open", "entry", "exit"]
piv = piv.dropna().reset_index()
piv["am_ret"] = piv["entry"] / piv["open"] - 1

# filter to days with >= 20 tickers
day_counts = piv.groupby("date").size()
valid_days = set(day_counts[day_counts >= 20].index)
piv = piv[piv["date"].isin(valid_days)].copy()
total_days = len(valid_days)

# ── compute daily median noon return ────────────────────────────────────
daily_median = piv.groupby("date")["am_ret"].median()

# ── sweep thresholds ────────────────────────────────────────────────────
results = []
for thresh, lbl in zip(THRESHOLDS, LABELS):
    stress_set = set(daily_median[daily_median < thresh].index)
    sub = piv[piv["date"].isin(stress_set)]
    trades = []
    for date, grp in sub.groupby("date"):
        bottom = grp.nsmallest(PICK_N, "am_ret")
        for _, r in bottom.iterrows():
            net = r["exit"] / r["entry"] - 1 - 2 * SLIP
            trades.append(net)
    arr = np.array(trades) if trades else np.array([0.0])
    n_days = len(stress_set)
    n_trades = len(trades)
    wins = (arr > 0).sum()
    gross_w = arr[arr > 0].sum() if (arr > 0).any() else 0
    gross_l = -arr[arr < 0].sum() if (arr < 0).any() else 0
    pf = gross_w / gross_l if gross_l > 0 else float("inf")
    total_pnl = arr.sum() * CAPITAL
    results.append(dict(label=lbl, thresh=thresh, n_days=n_days, n_trades=n_trades,
                        win_rate=100 * wins / max(n_trades, 1),
                        avg_ret=arr.mean() * 100, total_pnl=total_pnl, pf=pf,
                        sharpe_proxy=arr.mean() * np.sqrt(n_days) if n_days > 0 else 0))
rdf = pd.DataFrame(results)

# ── comparison table ────────────────────────────────────────────────────
print(f"\n{'='*82}")
print(f"Stress Threshold Robustness  ({total_days} valid trading days)")
print(f"{'='*82}")
print(f"  {'Threshold':<11} {'N Days':>7} {'Trades':>7} {'Win%':>7} "
      f"{'AvgRet':>9} {'Total P&L':>12} {'PF':>7}")
print(f"  {'-'*11} {'-'*7} {'-'*7} {'-'*7} {'-'*9} {'-'*12} {'-'*7}")
for _, r in rdf.iterrows():
    pf_s = f"{r['pf']:.2f}" if np.isfinite(r['pf']) else "inf"
    print(f"  {r['label']:<11} {r['n_days']:>7} {r['n_trades']:>7} "
          f"{r['win_rate']:>6.1f}% {r['avg_ret']:>+8.3f}% "
          f"${r['total_pnl']:>+11,.2f} {pf_s:>7}")

# ── annual expected P&L ─────────────────────────────────────────────────
months_in_data = total_days / 21  # approx trading months
annual_factor = 12 / months_in_data
print(f"\n{'='*82}")
print("Annual Expected P&L  (extrapolated from {:.1f} months)".format(months_in_data))
print(f"{'='*82}")
for _, r in rdf.iterrows():
    ann = r["total_pnl"] * annual_factor
    print(f"  {r['label']:<11}  ${ann:>+12,.2f}/yr  "
          f"(~{r['n_days'] * annual_factor:.0f} days/yr)")

# ── optimal threshold ───────────────────────────────────────────────────
best_idx = rdf["sharpe_proxy"].idxmax()
best = rdf.loc[best_idx]
print(f"\n  Optimal (best avg_ret × sqrt(N)): {best['label']}  "
      f"(proxy = {best['sharpe_proxy']:.4f})")

# ── monotonicity check ──────────────────────────────────────────────────
avg_rets = rdf["avg_ret"].values
diffs = np.diff(avg_rets)
is_mono = all(d >= 0 for d in diffs)
print(f"\n  Monotonicity (stricter → higher avg return): "
      f"{'YES — effect is threshold-robust' if is_mono else 'NO — possible overfitting/small-N noise'}")
if not is_mono:
    breaks = [f"    {LABELS[i]} ({avg_rets[i]:+.3f}%) → {LABELS[i+1]} ({avg_rets[i+1]:+.3f}%)"
              for i, d in enumerate(diffs) if d < 0]
    print("  Breaks at:\n" + "\n".join(breaks))

# ── chart: avg return + N days dual axis ────────────────────────────────
fig, ax1 = plt.subplots(figsize=(10, 5.5))
x = range(len(rdf))
ax1.bar(x, rdf["avg_ret"], color="#1a7f37", alpha=0.7, width=0.5, label="Avg Return/Trade")
ax1.set_xticks(x)
ax1.set_xticklabels(LABELS)
ax1.set_xlabel("Stress Threshold (median noon return)")
ax1.set_ylabel("Avg Return per Trade (%)", color="#1a7f37")
ax1.tick_params(axis="y", labelcolor="#1a7f37")

ax2 = ax1.twinx()
ax2.plot(x, rdf["n_days"], "o-", color="#cf222e", lw=2, ms=8, label="N Stress Days")
ax2.set_ylabel("N Stress Days", color="#cf222e")
ax2.tick_params(axis="y", labelcolor="#cf222e")

# highlight optimal
ax1.axvline(best_idx, color="gold", ls="--", lw=1.5, alpha=0.7, label=f"Optimal: {best['label']}")
lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")
ax1.set_title("S21-P10  Stress Threshold Robustness\n"
              "Bottom-2 laggard, 12:00→15:30, $10k/name")
ax1.grid(True, alpha=0.3, axis="y")
fig.tight_layout()
chart = OUT / "s21_p10_threshold_sweep.png"
fig.savefig(chart, dpi=150)
plt.close(fig)
print(f"\nSaved: {chart.relative_to(ROOT)}")
