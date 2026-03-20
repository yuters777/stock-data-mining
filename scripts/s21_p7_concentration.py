#!/usr/bin/env python3
"""S21-P7: Concentration risk — ticker frequency, LOTO, sector, clustering."""

import json, pathlib, pandas as pd, numpy as np
from datetime import time as T
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT  = ROOT / "backtest_output"

TICKERS = ["AAPL","AMD","AMZN","AVGO","BA","BABA","BIDU","C","COIN","COST",
           "GOOGL","GS","IBIT","JPM","MARA","META","MSFT","MU","NVDA",
           "PLTR","SNOW","TSLA","TSM","TXN","V"]
CAPITAL, SLIP, PICK_N = 10_000, 0.0005, 2
NOON_THR = -0.0075
_T = "Tech"; _F = "Financial"
SECTORS = dict(**{t:_T for t in ["AAPL","AMD","AMZN","AVGO","GOOGL","META","MSFT","MU","NVDA","PLTR","SNOW","TSM","TXN"]},
               **{t:_F for t in ["C","COIN","GS","IBIT","JPM","MARA","V"]},
               BABA="ConsDisc",TSLA="ConsDisc",BIDU="Communication",BA="Industrials",COST="ConsStaples")

# ── load data ────────────────────────────────────────────────────────────
TIMES = [T(9, 30), T(12, 0), T(12, 30), T(15, 30)]
print("Loading M5 data …")
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
piv.columns = ["open", "rank_t", "entry", "exit"]
piv = piv.dropna().reset_index()

noon_rets = piv.copy()
noon_rets["noon_ret"] = noon_rets["rank_t"] / noon_rets["open"] - 1
median_noon = noon_rets.groupby("date")["noon_ret"].median()
stress_dates = set(median_noon[median_noon < NOON_THR].index)
print(f"Stress days: {len(stress_dates)}")

def run_strategy(universe, dates):
    """Run bottom-2 strategy on given ticker universe and dates."""
    sub = piv[piv["date"].isin(dates) & piv["ticker"].isin(universe)].copy()
    if sub.empty:
        return pd.DataFrame(columns=["date", "ticker", "net_ret", "pnl"])
    sub["am_ret"] = sub["rank_t"] / sub["open"] - 1
    trades = []
    for date, grp in sub.groupby("date"):
        picks = grp.nsmallest(PICK_N, "am_ret")
        for _, r in picks.iterrows():
            net = r["exit"] / r["entry"] - 1 - 2 * SLIP
            trades.append(dict(date=date, ticker=r["ticker"], net_ret=net, pnl=CAPITAL * net))
    return pd.DataFrame(trades).sort_values("date").reset_index(drop=True) if trades else \
           pd.DataFrame(columns=["date", "ticker", "net_ret", "pnl"])

# ── baseline ─────────────────────────────────────────────────────────────
baseline = run_strategy(TICKERS, stress_dates)
base_pnl = baseline["pnl"].sum()
base_wr  = (baseline["pnl"] > 0).mean() * 100
base_avg = baseline["net_ret"].mean() * 100
N_TRADES = len(baseline)

# ══ PART A: Ticker Frequency ═════════════════════════════════════════════
print(f"\n{'=' * 65}\nPART A: Ticker Frequency Analysis\n{'=' * 65}")
freq = Counter(baseline["ticker"])
top5 = freq.most_common(5)
n_unique = len(freq)
total_sel = sum(freq.values())
top3_count = sum(c for _, c in freq.most_common(3))
top3_pct = 100 * top3_count / total_sel

print(f"\n  Top 5 most-selected tickers:")
for tkr, cnt in top5:
    print(f"    {tkr:<6} {cnt:>2}x  ({100*cnt/total_sel:.1f}%)")
print(f"\n  Unique tickers selected:  {n_unique} / 25")
print(f"  Top-3 concentration:      {top3_count}/{total_sel} = {top3_pct:.1f}%"
      f"  {'⚠ >50%' if top3_pct > 50 else '✓ diversified'}")

# per-ticker avg return (selected 2+ times)
print(f"\n  Per-ticker avg PM return (selected ≥2x):")
print(f"  {'Ticker':<8} {'Count':>5} {'Avg Ret':>9} {'Win%':>7} {'Total PnL':>10}")
print(f"  {'-'*42}")
for tkr in sorted(freq, key=lambda t: -freq[t]):
    if freq[tkr] < 2:
        continue
    sub = baseline[baseline["ticker"] == tkr]
    print(f"  {tkr:<8} {freq[tkr]:>5} {sub['net_ret'].mean()*100:>+8.3f}% "
          f"{(sub['pnl']>0).mean()*100:>6.1f}% ${sub['pnl'].sum():>+9.2f}")

# ══ PART B: Leave-One-Ticker-Out ═════════════════════════════════════════
print(f"\n{'=' * 65}\nPART B: Leave-One-Ticker-Out (LOTO)\n{'=' * 65}")
print(f"\n  Baseline: {N_TRADES} trades, WR {base_wr:.1f}%, P&L ${base_pnl:+,.2f}")
print(f"\n  {'Excluded':<10} {'P&L':>10} {'WR%':>7} {'ΔP&L':>10} {'ΔP&L%':>7}")
print(f"  {'-'*48}")

loto_results, critical = [], []
for tkr in sorted(TICKERS):
    tr = run_strategy([t for t in TICKERS if t != tkr], stress_dates)
    pnl = tr["pnl"].sum() if len(tr) else 0
    wr = (tr["pnl"] > 0).mean() * 100 if len(tr) else 0
    delta = pnl - base_pnl
    delta_pct = 100 * delta / base_pnl if base_pnl else 0
    flag = " ← UNPROFITABLE" if pnl <= 0 else (" ← >30% impact" if abs(delta) > 0.3 * abs(base_pnl) else "")
    if pnl <= 0: critical.append(tkr)
    loto_results.append(dict(ticker=tkr, pnl=round(pnl, 2), wr=round(wr, 1),
                             delta=round(delta, 2), delta_pct=round(delta_pct, 1)))
    print(f"  {tkr:<10} ${pnl:>+9,.2f} {wr:>6.1f}% ${delta:>+9,.2f} {delta_pct:>+6.1f}%{flag}")

any_dominant = any(abs(r["delta"]) > 0.3 * abs(base_pnl) for r in loto_results)
print(f"\n  Single ticker >30% of P&L? {'YES ⚠' if any_dominant else 'NO ✓'}")
print(f"  Critical dependencies:     {', '.join(critical) if critical else 'None ✓'}")

# ══ PART C: Sector Concentration ═════════════════════════════════════════
print(f"\n{'=' * 65}\nPART C: Sector Concentration\n{'=' * 65}")
baseline["sector"] = baseline["ticker"].map(SECTORS)
sec_freq = Counter(baseline["sector"])
print(f"\n  Sector breakdown of all {total_sel} selections:")
for sec in sorted(sec_freq, key=lambda s: -sec_freq[s]):
    pct = 100 * sec_freq[sec] / total_sel
    print(f"    {sec:<15} {sec_freq[sec]:>3}  ({pct:.1f}%)")

max_sec_pct = max(sec_freq.values()) / total_sel * 100
print(f"\n  Max sector concentration: {max_sec_pct:.1f}%"
      f"  {'⚠ >70%' if max_sec_pct > 70 else '✓ <70%'}")

# same-sector days
same_sec_days = []
for date, grp in baseline.groupby("date"):
    secs = grp["sector"].tolist()
    if len(set(secs)) == 1:
        same_sec_days.append((date, secs[0]))
print(f"  Both picks same sector:   {len(same_sec_days)}/{len(stress_dates)} days"
      f"  ({100*len(same_sec_days)/len(stress_dates):.0f}%)")
for d, s in same_sec_days:
    tks = baseline[baseline["date"] == d]["ticker"].tolist()
    print(f"    {d}: {', '.join(tks)} ({s})")

# ══ PART D: Stress Episode Clustering ════════════════════════════════════
print(f"\n{'=' * 65}\nPART D: Stress Episode Clustering\n{'=' * 65}")
sorted_dates = sorted(stress_dates)
ts = [pd.Timestamp(d) for d in sorted_dates]

# group into episodes (within 3 calendar days)
episodes, cur = [], [ts[0]]
for i in range(1, len(ts)):
    if (ts[i] - cur[-1]).days <= 3:
        cur.append(ts[i])
    else:
        episodes.append(cur)
        cur = [ts[i]]
episodes.append(cur)

# label each date
date_labels = {}
for ep in episodes:
    if len(ep) == 1:
        date_labels[ep[0].strftime("%Y-%m-%d")] = "isolated"
    else:
        for j, d in enumerate(ep):
            date_labels[d.strftime("%Y-%m-%d")] = "day1" if j == 0 else "day2+"

baseline["cluster"] = baseline["date"].map(date_labels)
n_iso = sum(1 for v in date_labels.values() if v == "isolated")
n_clust = len(date_labels) - n_iso

print(f"\n  Episodes: {len(episodes)} ({n_iso} isolated, "
      f"{len([e for e in episodes if len(e)>1])} clusters with {n_clust} days)")
print(f"\n  {'Type':<12} {'Avg Ret':>9} {'Hit%':>7} {'N trades':>9}")
print(f"  {'-'*40}")
for lbl in ["isolated", "day1", "day2+"]:
    sub = baseline[baseline["cluster"] == lbl]
    if sub.empty:
        continue
    avg = sub["net_ret"].mean() * 100
    hit = (sub["pnl"] > 0).mean() * 100
    print(f"  {lbl:<12} {avg:>+8.3f}% {hit:>6.1f}% {len(sub):>9}")

d1 = baseline.loc[baseline["cluster"]=="day1", "net_ret"]
d2 = baseline.loc[baseline["cluster"]=="day2+", "net_ret"]
d1_avg, d2_avg = (d1.mean()*100 if len(d1) else 0), (d2.mean()*100 if len(d2) else 0)
decay = d2_avg < d1_avg and len(d2) > 0
print(f"\n  Edge decay: {'YES' if decay else 'NO'} (day1 {d1_avg:+.3f}%, day2+ {d2_avg:+.3f}%)")
print(f"{'=' * 65}")

# ── save JSON ────────────────────────────────────────────────────────────
(OUT / "s21_p7_concentration.json").write_text(json.dumps(dict(
    ticker_freq=dict(freq), n_unique=n_unique, top3_pct=round(top3_pct, 1),
    loto=loto_results, critical_deps=critical,
    sector_freq=dict(sec_freq), max_sector_pct=round(max_sec_pct, 1),
    same_sector_days=len(same_sec_days),
    n_isolated=n_iso, n_clustered=n_clust,
    edge_decay=bool(decay),
), indent=2) + "\n")
print(f"Saved: backtest_output/s21_p7_concentration.json")
