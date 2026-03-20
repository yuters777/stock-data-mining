#!/usr/bin/env python3
"""Audit A1: Volume J-Shape analysis across 25+ equity/ETF tickers.

Two averaging methods:
  A) Equal-weight across tickers: average each ticker's J-shape, then average tickers
  B) Ticker-day pooled: pool all ticker-day observations (original method)
SPY is shown separately as the benchmark liquid name.
"""

import csv
import os
import statistics
from collections import defaultdict
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── Config ──────────────────────────────────────────────────────────────────
BACKTEST_DIR = os.path.join(os.path.dirname(__file__), "..")
AUDIT_DIR = os.path.dirname(__file__)

EXCLUDE = {"BTC", "ETH"}
CRYPTO_ADJACENT = {"IBIT", "COIN", "MARA"}

# 13 half-hour windows (minutes since midnight)
WINDOWS = []
for h in range(9, 16):
    for m in (0, 30):
        start_min = h * 60 + m
        if start_min < 570 or start_min >= 960:
            continue
        WINDOWS.append(start_min)

WINDOW_LABELS = [f"{w // 60:02d}:{w % 60:02d}" for w in WINDOWS]
N_WIN = len(WINDOWS)

# Framework claims to overlay
CLAIMS = {"09:30": 15.0, "12:30": 5.1, "15:30": 12.4}

# ── Discover tickers ────────────────────────────────────────────────────────
tickers = sorted(
    fname.replace("_m5_regsess.csv", "")
    for fname in os.listdir(BACKTEST_DIR)
    if fname.endswith("_m5_regsess.csv")
    and fname.replace("_m5_regsess.csv", "") not in EXCLUDE
)
print(f"Tickers ({len(tickers)}): {', '.join(tickers)}")

# ── Helper: assign bar to window index ──────────────────────────────────────
def bar_to_window(bar_min):
    for i in range(N_WIN - 1, -1, -1):
        if bar_min >= WINDOWS[i]:
            return i
    return None

# ── Process each ticker ────────────────────────────────────────────────────
ticker_avg = {}          # ticker → [13 avg pcts]
pooled_pcts = defaultdict(list)  # window_idx → list of all ticker-day pcts

for ticker in tickers:
    fpath = os.path.join(BACKTEST_DIR, f"{ticker}_m5_regsess.csv")
    day_window_vol = defaultdict(lambda: defaultdict(int))

    with open(fpath) as f:
        for row in csv.DictReader(f):
            dt = datetime.strptime(row["Datetime"], "%Y-%m-%d %H:%M:%S")
            win_idx = bar_to_window(dt.hour * 60 + dt.minute)
            if win_idx is not None:
                day_window_vol[dt.strftime("%Y-%m-%d")][win_idx] += int(row["Volume"])

    t_pcts = defaultdict(list)
    for date_str, wvol in day_window_vol.items():
        daily_total = sum(wvol.values())
        if daily_total == 0:
            continue
        for i in range(N_WIN):
            pct = 100.0 * wvol.get(i, 0) / daily_total
            t_pcts[i].append(pct)
            pooled_pcts[i].append(pct)

    ticker_avg[ticker] = [
        statistics.mean(t_pcts[i]) if t_pcts[i] else 0.0 for i in range(N_WIN)
    ]

# ── Method A: equal-weight across tickers ──────────────────────────────────
ew_means = [statistics.mean([ticker_avg[t][i] for t in tickers]) for i in range(N_WIN)]
ew_stds = [statistics.stdev([ticker_avg[t][i] for t in tickers]) if len(tickers) > 1 else 0 for i in range(N_WIN)]

# ── Method B: pooled ticker-day (original) ─────────────────────────────────
pool_means = [statistics.mean(pooled_pcts[i]) for i in range(N_WIN)]
pool_medians = [statistics.median(pooled_pcts[i]) for i in range(N_WIN)]
pool_stds = [statistics.stdev(pooled_pcts[i]) if len(pooled_pcts[i]) > 1 else 0 for i in range(N_WIN)]

# SPY alone
spy = ticker_avg.get("SPY", [0] * N_WIN)

# ── Save CSV ────────────────────────────────────────────────────────────────
csv_path = os.path.join(AUDIT_DIR, "audit_a1_volume_jshape.csv")
with open(csv_path, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["window_start", "ew_mean_pct", "ew_std", "pooled_mean_pct",
                "pooled_median_pct", "pooled_std", "spy_pct"])
    for i in range(N_WIN):
        w.writerow([WINDOW_LABELS[i],
                     f"{ew_means[i]:.3f}", f"{ew_stds[i]:.3f}",
                     f"{pool_means[i]:.3f}", f"{pool_medians[i]:.3f}", f"{pool_stds[i]:.3f}",
                     f"{spy[i]:.3f}"])
print(f"\nSaved: {csv_path}")

# ── Plot ────────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(12, 5.5))
x = list(range(N_WIN))
width = 0.3

# Equal-weight bars
ax.bar([xi - width / 2 for xi in x], ew_means, width, color="#4a90d9", alpha=0.85,
       label="Equal-weight avg (all tickers)")
ax.errorbar([xi - width / 2 for xi in x], ew_means, yerr=ew_stds,
            fmt="none", ecolor="gray", capsize=2, alpha=0.4)

# SPY line
ax.plot(x, spy, "o-", color="#2ca02c", linewidth=2, markersize=5, label="SPY alone")

# Overlay claims
for j, (label, claim_val) in enumerate(CLAIMS.items()):
    idx = WINDOW_LABELS.index(label)
    ax.plot(idx, claim_val, "r*", markersize=14, zorder=5,
            label="Framework claims" if j == 0 else "")
    ax.annotate(f"{claim_val}%", (idx, claim_val), textcoords="offset points",
                xytext=(8, 6), fontsize=9, color="red", fontweight="bold")

ax.set_xticks(x)
ax.set_xticklabels(WINDOW_LABELS, rotation=45, ha="right")
ax.set_xlabel("Half-hour window start (ET)")
ax.set_ylabel("% of daily volume")
ax.set_title("Audit A1: Intraday Volume J-Shape — 27 equity/ETF tickers, 282 days")
ax.legend(loc="upper right", fontsize=9)
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()

png_path = os.path.join(AUDIT_DIR, "audit_a1_volume_jshape.png")
fig.savefig(png_path, dpi=150)
print(f"Saved: {png_path}")

# ── Print comparison ────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("VOLUME J-SHAPE: MEASURED vs FRAMEWORK CLAIMS")
print("=" * 80)
print(f"{'Window':<8} {'EW Mean':>9} {'EW Std':>8} {'SPY':>8} "
      f"{'Pool Med':>10} {'Claim':>8} {'SPYΔClm':>8}")
print("-" * 80)
for i in range(N_WIN):
    label = WINDOW_LABELS[i]
    claim = CLAIMS.get(label)
    c_str = f"{claim:.1f}%" if claim else ""
    d_str = f"{spy[i] - claim:+.1f}pp" if claim else ""
    print(f"{label:<8} {ew_means[i]:>8.2f}% {ew_stds[i]:>7.2f} {spy[i]:>7.2f}% "
          f"{pool_medians[i]:>9.2f}% {c_str:>8} {d_str:>8}")

# ── Verdict ─────────────────────────────────────────────────────────────────
print("\nVERDICT:")
for label, claim_val in CLAIMS.items():
    idx = WINDOW_LABELS.index(label)
    delta_spy = spy[idx] - claim_val
    delta_ew = ew_means[idx] - claim_val
    print(f"  {label} claim {claim_val:.1f}%: SPY={spy[idx]:.1f}% ({delta_spy:+.1f}pp), "
          f"EW-avg={ew_means[idx]:.1f}% ({delta_ew:+.1f}pp)")

print("\n  ⚠ DATA QUALITY NOTE:")
print("  Non-SPY tickers show volume from a SINGLE EXCHANGE feed, not consolidated tape.")
print("  Example: AAPL mid-day bars show ~1K vol vs ~1M real consolidated vol (1000x under).")
print("  This makes the EW-average J-shape unreliable — open is inflated, mid-day crushed.")
print("  SPY has proper consolidated volume and is the only reliable J-shape benchmark here.")
print("  Claims validation should reference SPY only.")

# ── Crypto-adjacent tickers ────────────────────────────────────────────────
print("\n" + "=" * 80)
print("CRYPTO-ADJACENT TICKERS (IBIT, COIN, MARA) vs ALL-TICKER AVG")
print("=" * 80)

for t in sorted(CRYPTO_ADJACENT):
    if t in ticker_avg:
        print(f"\n  {t}:")
        for i in range(N_WIN):
            print(f"    {WINDOW_LABELS[i]}  {ticker_avg[t][i]:6.2f}%")

ca_avg = [statistics.mean([ticker_avg[t][i] for t in sorted(CRYPTO_ADJACENT) if t in ticker_avg])
          for i in range(N_WIN)]

print(f"\n  {'Window':<8} {'Crypto3':>9} {'EW-All':>9} {'SPY':>8} {'CrΔSPY':>8}")
print(f"  {'-' * 46}")
for i in range(N_WIN):
    d = ca_avg[i] - spy[i]
    print(f"  {WINDOW_LABELS[i]:<8} {ca_avg[i]:>8.2f}% {ew_means[i]:>8.2f}% {spy[i]:>7.2f}% {d:>+7.2f}pp")

# Crypto-adjacent shape commentary
open_ca = ca_avg[0]
open_spy = spy[0]
mid_ca = ca_avg[WINDOW_LABELS.index("12:30")]
mid_spy = spy[WINDOW_LABELS.index("12:30")]
close_ca = ca_avg[-1]
close_spy = spy[-1]
print(f"\n  Crypto-adjacent shape vs SPY:")
print(f"    Open  (09:30): {open_ca:.1f}% vs {open_spy:.1f}% — {'heavier' if open_ca > open_spy else 'lighter'} open")
print(f"    Mid   (12:30): {mid_ca:.1f}% vs {mid_spy:.1f}% — {'heavier' if mid_ca > mid_spy else 'lighter'} midday")
print(f"    Close (15:30): {close_ca:.1f}% vs {close_spy:.1f}% — {'heavier' if close_ca > close_spy else 'lighter'} close")
print(f"    → Crypto-adjacent tickers have a {'more' if (open_ca - close_ca) > (open_spy - close_spy) else 'less'} front-loaded J-shape")
print(f"\n  ⚠ Same data-quality caveat applies: IBIT/COIN/MARA volume is single-exchange,")
print(f"    so the extreme front-loading may be a data artifact, not a real market feature.")
