#!/usr/bin/env python3
"""Audit G2: VIX regime classification and SPY return/range characteristics.

Regimes by prior-day VIX close: Low(<16), Normal(16-20), Elevated(20-25), High(>=25).
Per regime: N, mean/median SPY return, intraday range, Power Hour & Dead Zone abs returns.
"""

import csv
import json
import os
import numpy as np
from datetime import datetime, time as dtime
from collections import defaultdict
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(SCRIPT_DIR, "..", "..")

# ── Load SPY M5 ──────────────────────────────────────────────────────────
spy_path = os.path.join(ROOT, "backtest_output", "SPY_m5_regsess.csv")
spy_by_date = defaultdict(list)
with open(spy_path) as f:
    for row in csv.DictReader(f):
        dt = datetime.strptime(row["Datetime"], "%Y-%m-%d %H:%M:%S")
        spy_by_date[dt.strftime("%Y-%m-%d")].append({
            "time": dt.time(),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": int(row["Volume"]),
        })

# ── Load VIX ──────────────────────────────────────────────────────────────
vix_path = os.path.join(ROOT, "Fetched_Data", "VIXCLS_FRED_real.csv")
vix_raw = {}
with open(vix_path) as f:
    for row in csv.DictReader(f):
        val = row["VIXCLS"].strip()
        if val == "." or val == "":
            continue
        vix_raw[row["observation_date"]] = float(val)

vix_dates = sorted(vix_raw.keys())
# Prior-day VIX: for date d, use VIX close from the previous trading day
prior_vix = {}
for i in range(1, len(vix_dates)):
    prior_vix[vix_dates[i]] = vix_raw[vix_dates[i - 1]]

# ── Regime classification ─────────────────────────────────────────────────
REGIMES = [
    ("Low (<16)", 0, 16),
    ("Normal (16-20)", 16, 20),
    ("Elevated (20-25)", 20, 25),
    ("High (≥25)", 25, 999),
]

def classify(vix):
    for name, lo, hi in REGIMES:
        if lo <= vix < hi:
            return name
    return "High (≥25)"

DEAD_START, DEAD_END = dtime(12, 0), dtime(13, 30)
PH_START, PH_END = dtime(14, 45), dtime(16, 0)

# ── Compute daily metrics ─────────────────────────────────────────────────
rows = []
common_dates = sorted(set(spy_by_date.keys()) & set(prior_vix.keys()))

for d in common_dates:
    bars = spy_by_date[d]
    if len(bars) < 10:
        continue

    vix_val = prior_vix[d]
    regime = classify(vix_val)

    day_open = bars[0]["open"]
    day_close = bars[-1]["close"]
    day_high = max(b["high"] for b in bars)
    day_low = min(b["low"] for b in bars)
    day_ret = (day_close - day_open) / day_open
    day_range = (day_high - day_low) / day_open

    # Dead Zone
    dz = [b for b in bars if DEAD_START <= b["time"] < DEAD_END]
    dz_abs_ret = abs(dz[-1]["close"] - dz[0]["open"]) / dz[0]["open"] if dz else 0

    # Power Hour
    ph = [b for b in bars if PH_START <= b["time"] < PH_END]
    ph_abs_ret = abs(ph[-1]["close"] - ph[0]["open"]) / ph[0]["open"] if ph else 0

    rows.append({
        "date": d,
        "vix_prior": vix_val,
        "regime": regime,
        "spy_ret": day_ret,
        "spy_range": day_range,
        "dz_abs_ret": dz_abs_ret,
        "ph_abs_ret": ph_abs_ret,
    })

# ── Aggregate by regime ───────────────────────────────────────────────────
print("=" * 90)
print("  AUDIT G2: VIX REGIME ANALYSIS — SPY RETURN & INTRADAY CHARACTERISTICS")
print("=" * 90)
print(f"\n  Date range: {common_dates[0]} to {common_dates[-1]}")
print(f"  Total trading days: {len(rows)}")
print()

header = (f"  {'Regime':<20} {'N':>5} {'MeanRet':>10} {'MedRet':>10} "
          f"{'Range':>10} {'PH AbsRet':>10} {'DZ AbsRet':>10} {'PH/DZ':>7}")
print(header)
print(f"  {'-'*85}")

regime_data = {}
for rname, _, _ in REGIMES:
    rrows = [r for r in rows if r["regime"] == rname]
    if not rrows:
        regime_data[rname] = {"n": 0}
        continue
    rets = np.array([r["spy_ret"] for r in rrows])
    ranges = np.array([r["spy_range"] for r in rrows])
    ph = np.array([r["ph_abs_ret"] for r in rrows])
    dz = np.array([r["dz_abs_ret"] for r in rrows])

    stats = {
        "n": len(rrows),
        "mean_ret": np.mean(rets),
        "med_ret": np.median(rets),
        "mean_range": np.mean(ranges),
        "mean_ph": np.mean(ph),
        "mean_dz": np.mean(dz),
        "ph_dz_ratio": np.mean(ph) / np.mean(dz) if np.mean(dz) > 0 else 0,
        "std_ret": np.std(rets),
        "pct_positive": 100 * np.mean(rets > 0),
        "rets": rets,
        "ranges": ranges,
        "ph_arr": ph,
        "dz_arr": dz,
    }
    regime_data[rname] = stats

    print(f"  {rname:<20} {stats['n']:>5} {stats['mean_ret']*100:>+9.3f}% "
          f"{stats['med_ret']*100:>+9.3f}% {stats['mean_range']*100:>9.3f}% "
          f"{stats['mean_ph']*100:>9.3f}% {stats['mean_dz']*100:>9.3f}% "
          f"{stats['ph_dz_ratio']:>6.2f}x")

# Extended stats
print()
print(f"  {'Regime':<20} {'StdRet':>10} {'%Positive':>10} {'Sharpe*':>10}")
print(f"  {'-'*55}")
for rname, _, _ in REGIMES:
    s = regime_data[rname]
    if s["n"] == 0:
        continue
    sharpe = s["mean_ret"] / s["std_ret"] if s["std_ret"] > 0 else 0
    print(f"  {rname:<20} {s['std_ret']*100:>9.3f}% {s['pct_positive']:>9.1f}% "
          f"{sharpe:>+9.3f}")

print(f"\n  * Daily Sharpe (not annualized)")

# ── Cross-regime comparison ───────────────────────────────────────────────
print(f"\n{'='*90}")
print(f"  CROSS-REGIME PATTERNS")
print(f"{'='*90}")

# Range expansion
low_range = regime_data.get("Low (<16)", {}).get("mean_range", 0)
high_range = regime_data.get("High (≥25)", {}).get("mean_range", 0)
if low_range > 0:
    print(f"\n  Range expansion (High vs Low): {high_range/low_range:.2f}x")
    print(f"    Low regime range:  {low_range*100:.3f}%")
    print(f"    High regime range: {high_range*100:.3f}%")

# Power hour amplification
low_ph = regime_data.get("Low (<16)", {}).get("mean_ph", 0)
high_ph = regime_data.get("High (≥25)", {}).get("mean_ph", 0)
if low_ph > 0:
    print(f"\n  Power Hour amplification (High vs Low): {high_ph/low_ph:.2f}x")

# Dead zone comparison
low_dz = regime_data.get("Low (<16)", {}).get("mean_dz", 0)
high_dz = regime_data.get("High (≥25)", {}).get("mean_dz", 0)
if low_dz > 0:
    print(f"  Dead Zone amplification (High vs Low):  {high_dz/low_dz:.2f}x")

# ── Prior finding validation ─────────────────────────────────────────────
print(f"\n{'='*90}")
print(f"  VALIDATION: Exit Backtest Finding (High Vol entries = only profitable regime)")
print(f"{'='*90}")
print()
for rname, _, _ in REGIMES:
    s = regime_data[rname]
    if s["n"] == 0:
        continue
    profitable = "PROFITABLE" if s["mean_ret"] > 0 else "UNPROFITABLE"
    print(f"  {rname:<20} mean ret = {s['mean_ret']*100:>+.3f}%  → {profitable}")

high_s = regime_data.get("High (≥25)", {})
if high_s.get("n", 0) > 0:
    if high_s["mean_ret"] > 0:
        # Check if it's the MOST profitable
        best_regime = max(
            [(rname, regime_data[rname]["mean_ret"])
             for rname, _, _ in REGIMES if regime_data[rname].get("n", 0) > 0],
            key=lambda x: x[1]
        )
        if best_regime[0] == "High (≥25)":
            print(f"\n  → CONFIRMED: High VIX regime has the highest mean return")
        else:
            print(f"\n  → PARTIALLY CONFIRMED: High VIX is profitable, "
                  f"but {best_regime[0]} has higher mean return")
    else:
        print(f"\n  → NOT CONFIRMED: High VIX regime is not profitable in this sample")

# ── Chart ─────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle("Audit G2: VIX Regime Analysis — SPY Intraday Characteristics",
             fontsize=14, fontweight="bold", y=0.98)

regime_names = [r[0] for r in REGIMES if regime_data.get(r[0], {}).get("n", 0) > 0]
regime_colors = {"Low (<16)": "#2196F3", "Normal (16-20)": "#4CAF50",
                 "Elevated (20-25)": "#FF9800", "High (≥25)": "#F44336"}
colors = [regime_colors[r] for r in regime_names]

# (a) Mean return by regime
ax = axes[0, 0]
vals = [regime_data[r]["mean_ret"] * 100 for r in regime_names]
bars = ax.bar(regime_names, vals, color=colors, edgecolor="black", linewidth=0.5)
ax.axhline(0, color="black", linewidth=0.5)
ax.set_ylabel("Mean Daily Return (%)")
ax.set_title("(a) Mean SPY Return by VIX Regime")
for bar, v in zip(bars, vals):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
            f"{v:+.3f}%", ha="center", va="bottom" if v >= 0 else "top", fontsize=9)

# (b) Intraday range
ax = axes[0, 1]
vals = [regime_data[r]["mean_range"] * 100 for r in regime_names]
bars = ax.bar(regime_names, vals, color=colors, edgecolor="black", linewidth=0.5)
ax.set_ylabel("Mean Intraday Range (%)")
ax.set_title("(b) SPY Intraday Range by VIX Regime")
for bar, v in zip(bars, vals):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
            f"{v:.3f}%", ha="center", va="bottom", fontsize=9)

# (c) Power Hour vs Dead Zone
ax = axes[1, 0]
x = np.arange(len(regime_names))
w = 0.35
ph_vals = [regime_data[r]["mean_ph"] * 100 for r in regime_names]
dz_vals = [regime_data[r]["mean_dz"] * 100 for r in regime_names]
ax.bar(x - w/2, ph_vals, w, label="Power Hour (14:45-16:00)", color="#E91E63", edgecolor="black", linewidth=0.5)
ax.bar(x + w/2, dz_vals, w, label="Dead Zone (12:00-13:30)", color="#9E9E9E", edgecolor="black", linewidth=0.5)
ax.set_xticks(x)
ax.set_xticklabels(regime_names, fontsize=8)
ax.set_ylabel("Abs Return (%)")
ax.set_title("(c) Power Hour vs Dead Zone Abs Return")
ax.legend(fontsize=8)

# (d) Return distribution box plots
ax = axes[1, 1]
data_for_box = [regime_data[r]["rets"] * 100 for r in regime_names]
bp = ax.boxplot(data_for_box, labels=regime_names, patch_artist=True,
                showfliers=True, flierprops={"markersize": 3, "alpha": 0.5})
for patch, c in zip(bp["boxes"], colors):
    patch.set_facecolor(c)
    patch.set_alpha(0.6)
ax.axhline(0, color="black", linewidth=0.5, linestyle="--")
ax.set_ylabel("Daily Return (%)")
ax.set_title("(d) Return Distribution by VIX Regime")

for ax in axes.flat:
    ax.tick_params(axis="x", labelsize=8)

plt.tight_layout(rect=[0, 0, 1, 0.96])
chart_path = os.path.join(SCRIPT_DIR, "audit_g2_chart.png")
plt.savefig(chart_path, dpi=150, bbox_inches="tight")
print(f"\nSaved chart: {chart_path}")

# ── Save CSV ──────────────────────────────────────────────────────────────
csv_path = os.path.join(SCRIPT_DIR, "audit_g2_regime.csv")
with open(csv_path, "w", newline="") as f:
    fields = ["date", "vix_prior", "regime", "spy_ret", "spy_range",
              "dz_abs_ret", "ph_abs_ret"]
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: f"{v:.6f}" if isinstance(v, float) else v
                         for k, v in r.items()})
print(f"Saved CSV: {csv_path}")
