#!/usr/bin/env python3
"""S21-P6: Walk-forward OOS test — IS (Feb–Sep 2025) vs OOS (Oct 2025–Mar 2026).
Rank@12:00, buy bottom-2@12:30, sell@15:30. Rolling 6m/2m windows."""

import json, pathlib, pandas as pd, numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import time as T
from scipy import stats

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT  = ROOT / "backtest_output"

TICKERS = ["AAPL","AMD","AMZN","AVGO","BA","BABA","BIDU","C","COIN","COST",
           "GOOGL","GS","IBIT","JPM","MARA","META","MSFT","MU","NVDA",
           "PLTR","SNOW","TSLA","TSM","TXN","V"]
CAPITAL, SLIP, PICK_N = 10_000, 0.0005, 2
NOON_THR, IS_END, OOS_START = -0.0075, "2025-09-30", "2025-10-01"
TIMES = [T(9, 30), T(12, 0), T(12, 30), T(15, 30)]
print("Loading M5 data for 25 tickers …")
rows = []
for tkr in TICKERS:
    df = pd.read_csv(OUT / f"{tkr}_m5_regsess.csv", parse_dates=["Datetime"])
    df["date"] = df["Datetime"].dt.strftime("%Y-%m-%d")
    df["time"] = df["Datetime"].dt.time
    for _, r in df[df["time"].isin(TIMES)].iterrows():
        rows.append((r["date"], tkr, r["time"], r["Close"]))

bars = pd.DataFrame(rows, columns=["date", "ticker", "time", "close"])
piv = bars.pivot_table(index=["date", "ticker"], columns="time",
                       values="close", aggfunc="first")
piv.columns = ["open", "rank_t", "entry", "exit"]  # 09:30, 12:00, 12:30, 15:30
piv = piv.dropna().reset_index()

noon_rets = piv.copy()
noon_rets["noon_ret"] = noon_rets["rank_t"] / noon_rets["open"] - 1
median_noon = noon_rets.groupby("date")["noon_ret"].median()
stress_all = set(median_noon[median_noon < NOON_THR].index)
print(f"Total noon-stress days: {len(stress_all)}")

# ── simulate trades for a set of dates ───────────────────────────────────
def simulate(dates: set) -> pd.DataFrame:
    sub = piv[piv["date"].isin(dates)].copy()
    if sub.empty:
        return pd.DataFrame(columns=["date", "ticker", "net_ret", "pnl"])
    sub["am_ret"] = sub["rank_t"] / sub["open"] - 1
    trades = []
    for date, grp in sub.groupby("date"):
        picks = grp.nsmallest(PICK_N, "am_ret")
        for _, r in picks.iterrows():
            gross = r["exit"] / r["entry"] - 1
            net = gross - 2 * SLIP
            trades.append(dict(date=date, ticker=r["ticker"],
                               net_ret=net, pnl=CAPITAL * net))
    if not trades:
        return pd.DataFrame(columns=["date", "ticker", "net_ret", "pnl"])
    return pd.DataFrame(trades).sort_values("date").reset_index(drop=True)


def metrics(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return dict(n_days=0, n_trades=0, win_rate=0, avg_ret=0, total_pnl=0,
                    max_dd=0, pf=0, best="", worst="")
    n = len(trades)
    wins = (trades["pnl"] > 0).sum()
    total = trades["pnl"].sum()
    cum = trades["pnl"].cumsum()
    dd = (cum - cum.cummax()).min()
    gp = trades.loc[trades["pnl"] > 0, "pnl"].sum()
    gl = -trades.loc[trades["pnl"] < 0, "pnl"].sum()
    pf = gp / gl if gl > 0 else float("inf")
    best = trades.loc[trades["pnl"].idxmax()]
    worst = trades.loc[trades["pnl"].idxmin()]
    return dict(
        n_days=trades["date"].nunique(), n_trades=n,
        win_rate=round(100 * wins / n, 1),
        avg_ret=round(100 * trades["net_ret"].mean(), 3),
        total_pnl=round(total, 2), max_dd=round(dd, 2),
        pf=round(pf, 2),
        best=f"${best['pnl']:+,.2f} ({best['ticker']} {best['date']})",
        worst=f"${worst['pnl']:+,.2f} ({worst['ticker']} {worst['date']})",
    )


# ── IS / OOS split ──────────────────────────────────────────────────────
is_dates  = {d for d in stress_all if d <= IS_END}
oos_dates = {d for d in stress_all if d >= OOS_START}

is_trades  = simulate(is_dates)
oos_trades = simulate(oos_dates)
is_m  = metrics(is_trades)
oos_m = metrics(oos_trades)

print(f"\n{'=' * 65}\nS21-P6  Walk-Forward Out-of-Sample Test\n{'=' * 65}")
FIELDS = [("n_days","Stress days: {}"),("n_trades","Trades: {}"),
          ("win_rate","Win rate: {}%"),("avg_ret","Avg ret/trade: {:+.3f}%"),
          ("total_pnl","Total P&L: ${:+,.2f}"),("max_dd","Max drawdown: ${:+,.2f}"),
          ("pf","Profit factor: {}"),("best","Best: {}"),("worst","Worst: {}")]
for label, m in [("IN-SAMPLE (Feb–Sep 2025)", is_m),
                 ("OUT-OF-SAMPLE (Oct 2025–Mar 2026)", oos_m)]:
    print(f"\n  {label}")
    for k, fmt in FIELDS:
        print(f"    {fmt.format(m[k])}")

# t-test IS vs OOS
if len(is_trades) and len(oos_trades):
    t_val, p_val = stats.ttest_ind(is_trades["net_ret"].values,
                                   oos_trades["net_ret"].values, equal_var=False)
    diff = oos_m["avg_ret"] - is_m["avg_ret"]
    verdict = ("PERSISTS" if p_val > 0.10
               else "DECAYS" if diff < 0 else "IMPROVES")
    print(f"\n  IS vs OOS:  diff={diff:+.3f}%  t={t_val:+.3f}  p={p_val:.4f}")
    print(f"  Edge verdict: {verdict}")
else:
    t_val, p_val, verdict = 0, 1, "INSUFFICIENT DATA"
    print(f"\n  Edge verdict: {verdict}")

# ── rolling walk-forward (6m train / 2m test) ───────────────────────────
all_dates_sorted = sorted(piv["date"].unique())
first = pd.Timestamp(all_dates_sorted[0])
last  = pd.Timestamp(all_dates_sorted[-1])

windows, wstart = [], first
while wstart + pd.DateOffset(months=8) <= last + pd.DateOffset(days=1):
    train_end  = wstart + pd.DateOffset(months=6) - pd.DateOffset(days=1)
    test_start = train_end + pd.DateOffset(days=1)
    test_end   = wstart + pd.DateOffset(months=8) - pd.DateOffset(days=1)
    te_s, te_e = test_start.strftime("%Y-%m-%d"), test_end.strftime("%Y-%m-%d")
    test_stress = {d for d in stress_all if te_s <= d <= te_e}
    tr = simulate(test_stress)
    avg = round(100 * tr["net_ret"].mean(), 3) if len(tr) else 0
    windows.append(dict(
        train=f"{wstart.strftime('%Y-%m')}→{train_end.strftime('%Y-%m')}",
        test=f"{test_start.strftime('%Y-%m')}→{test_end.strftime('%Y-%m')}",
        stress_days=len(test_stress), trades=len(tr), avg_ret=avg,
        total_pnl=round(tr["pnl"].sum(), 2) if len(tr) else 0))
    wstart += pd.DateOffset(months=2)

print(f"\n── Rolling Walk-Forward (6m train / 2m test) ──")
print(f"  {'Window':<22} {'Test':<18} {'#Str':>4} {'#Tr':>4} {'Avg%':>7} {'P&L':>9}")
print("  " + "-" * 68)
any_neg = any(w["avg_ret"] < 0 and w["trades"] > 0 for w in windows)
for w in windows:
    flag = " ***" if w["avg_ret"] < 0 and w["trades"] > 0 else ""
    print(f"  {w['train']:<22} {w['test']:<18} {w['stress_days']:>4} "
          f"{w['trades']:>4} {w['avg_ret']:>+6.3f} ${w['total_pnl']:>+8,.2f}{flag}")
print(f"\n  Any negative test window? {'YES' if any_neg else 'NO'}")

# ── save JSON ────────────────────────────────────────────────────────────
result = dict(in_sample=is_m, out_of_sample=oos_m,
              t_test=dict(t=round(t_val, 3), p=round(p_val, 4), verdict=verdict),
              rolling_windows=windows, any_negative_window=any_neg)
(OUT / "s21_p6_walkforward.json").write_text(json.dumps(result, indent=2) + "\n")

# ── chart: IS vs OOS equity curves ──────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
for ax, trades, label, color in [
    (axes[0], is_trades,  "IN-SAMPLE (Feb–Sep 2025)", "#1a7f37"),
    (axes[1], oos_trades, "OUT-OF-SAMPLE (Oct 2025–Mar 2026)", "#0969da"),
]:
    if trades.empty:
        ax.set_title(f"{label}\n(no trades)")
        continue
    daily = trades.groupby("date")["pnl"].sum().sort_index()
    cum = daily.cumsum()
    ax.step(range(len(cum)), cum.values, where="post", lw=2, color=color)
    ax.axhline(0, color="grey", lw=0.8, ls="--")
    m = metrics(trades)
    ax.set_title(f"{label}\n{m['n_days']} days, WR {m['win_rate']}%, "
                 f"P&L ${m['total_pnl']:+,.0f}")
    ax.set_xlabel("Stress-day event #")
    ax.grid(True, alpha=0.3)
axes[0].set_ylabel("Cumulative P&L ($)")
fig.suptitle("S21-P6  Walk-Forward: IS vs OOS Equity Curves\n"
             "Q5 bottom-2, rank@12:00, buy@12:30, sell@15:30, $10k/name", fontsize=11, y=1.02)
fig.tight_layout()
chart = OUT / "s21_p6_walkforward.png"
fig.savefig(chart, dpi=150, bbox_inches="tight")
print(f"\nSaved: {chart.relative_to(ROOT)}")
print(f"Saved: backtest_output/s21_p6_walkforward.json\n{'=' * 65}")
