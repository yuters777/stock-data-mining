#!/usr/bin/env python3
"""PH2: Power-hour returns segmented by VIX regime.

Splits trading days into 4 VIX regimes by daily VIX close:
  Low:      < 16
  Normal:   16–20
  Elevated: 20–25
  High:     >= 25

For each regime, computes pooled (all tickers) Zone 5 and Zone 3 absolute
returns, their ratio, paired t-test, and day count.
"""

import csv
import math
import os
import statistics
from collections import defaultdict
from datetime import datetime

BACKTEST_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
AUDIT_DIR = os.path.dirname(__file__)
FETCHED_DIR = os.path.join(BACKTEST_DIR, "..", "Fetched_Data")
EXCLUDE = {"BTC", "ETH"}

VIX_REGIMES = [
    ("Low",      lambda v: v < 16),
    ("Normal",   lambda v: 16 <= v < 20),
    ("Elevated", lambda v: 20 <= v < 25),
    ("High",     lambda v: v >= 25),
]

# ── Load VIX daily closes ──────────────────────────────────────────────────
vix_by_date = {}
vix_path = os.path.join(FETCHED_DIR, "VIXCLS_FRED_real.csv")
with open(vix_path) as f:
    for row in csv.DictReader(f):
        date_str = row["observation_date"]
        try:
            vix_by_date[date_str] = float(row["VIXCLS"])
        except (ValueError, KeyError):
            continue

print(f"VIX daily data: {len(vix_by_date)} trading days")

# ── Discover tickers ────────────────────────────────────────────────────────
tickers = sorted(
    f.replace("_m5_regsess.csv", "")
    for f in os.listdir(BACKTEST_DIR)
    if f.endswith("_m5_regsess.csv")
    and f.replace("_m5_regsess.csv", "") not in EXCLUDE
)
print(f"Tickers ({len(tickers)}): {', '.join(tickers)}")

# ── Collect zone returns per (ticker, date) ─────────────────────────────────
# regime_name -> {"z5": [...], "z3": [...]}
regime_data = {name: {"z5": [], "z3": []} for name, _ in VIX_REGIMES}
regime_dates = {name: set() for name, _ in VIX_REGIMES}

skipped_no_vix = 0

for ticker in tickers:
    fpath = os.path.join(BACKTEST_DIR, f"{ticker}_m5_regsess.csv")
    day_prices = defaultdict(dict)

    with open(fpath) as f:
        for row in csv.DictReader(f):
            dt = datetime.strptime(row["Datetime"], "%Y-%m-%d %H:%M:%S")
            date_str = dt.strftime("%Y-%m-%d")
            hhmm = f"{dt.hour:02d}:{dt.minute:02d}"
            if hhmm in ("12:00", "13:30", "14:45", "15:55"):
                day_prices[date_str][hhmm] = float(row["Close"])

    for date_str in sorted(day_prices):
        p = day_prices[date_str]
        if not all(k in p for k in ("12:00", "13:30", "14:45", "15:55")):
            continue

        if date_str not in vix_by_date:
            skipped_no_vix += 1
            continue

        vix_val = vix_by_date[date_str]
        z5 = abs(p["15:55"] - p["14:45"]) / p["14:45"]
        z3 = abs(p["13:30"] - p["12:00"]) / p["12:00"]

        for regime_name, regime_fn in VIX_REGIMES:
            if regime_fn(vix_val):
                regime_data[regime_name]["z5"].append(z5)
                regime_data[regime_name]["z3"].append(z3)
                regime_dates[regime_name].add(date_str)
                break

print(f"Skipped ticker-days without VIX match: {skipped_no_vix}")


# ── Paired t-test helper ────────────────────────────────────────────────────
def paired_ttest_pvalue(a, b):
    """Two-tailed paired t-test p-value for a - b."""
    n = len(a)
    if n < 2:
        return float("nan")
    diffs = [x - y for x, y in zip(a, b)]
    d_mean = statistics.mean(diffs)
    d_std = statistics.stdev(diffs)
    if d_std == 0:
        return float("nan")
    se = d_std / math.sqrt(n)
    t_stat = d_mean / se
    df = n - 1
    # Normal approx for large n, numerical integration otherwise
    if df > 100:
        p = math.erfc(abs(t_stat) / math.sqrt(2))
    else:
        from math import gamma
        coeff = gamma((df + 1) / 2) / (math.sqrt(df * math.pi) * gamma(df / 2))
        steps = 10000
        upper = abs(t_stat) + 50
        dt_step = (upper - abs(t_stat)) / steps
        integral = 0.0
        for i in range(steps):
            x_val = abs(t_stat) + (i + 0.5) * dt_step
            integral += coeff * (1 + x_val ** 2 / df) ** (-(df + 1) / 2) * dt_step
        p = 2 * integral
    return t_stat, p


# ── Compute stats per regime ────────────────────────────────────────────────
results = []
for regime_name, _ in VIX_REGIMES:
    z5_list = regime_data[regime_name]["z5"]
    z3_list = regime_data[regime_name]["z3"]
    n_obs = len(z5_list)
    n_days = len(regime_dates[regime_name])

    if n_obs < 2:
        results.append((regime_name, n_days, n_obs, 0, 0, 0, float("nan"), float("nan")))
        continue

    z5_mean = statistics.mean(z5_list) * 10000  # bps
    z3_mean = statistics.mean(z3_list) * 10000
    ratio = z5_mean / z3_mean if z3_mean > 0 else float("inf")
    t_stat, p_val = paired_ttest_pvalue(z5_list, z3_list)

    results.append((regime_name, n_days, n_obs, z5_mean, z3_mean, ratio, t_stat, p_val))

# ── Generate markdown ───────────────────────────────────────────────────────
lines = []
lines.append("# PH2: Power Hour Returns by VIX Regime")
lines.append("")
lines.append("**Zone 5** (Power Hour): 14:45–16:00 ET  ")
lines.append("**Zone 3** (Midday Lull): 12:00–13:30 ET  ")
lines.append("**Metric**: Mean absolute return = |close_end − close_start| / close_start  ")
lines.append("**VIX Source**: CBOE VIX daily close (FRED VIXCLS)  ")
lines.append(f"**Data**: M5 regular-session bars, {len(tickers)} tickers, pooled across all tickers  ")
lines.append("")
lines.append("## VIX Regime Definitions")
lines.append("")
lines.append("| Regime | VIX Range |")
lines.append("|--------|-----------|")
lines.append("| Low | < 16 |")
lines.append("| Normal | 16–20 |")
lines.append("| Elevated | 20–25 |")
lines.append("| High | >= 25 |")
lines.append("")
lines.append("## Results")
lines.append("")
lines.append("| Regime | N days | N ticker-days | Mean \\|Ret\\| Z5 (bps) | Mean \\|Ret\\| Z3 (bps) | Ratio Z5/Z3 | T-stat | P-value | Sig |")
lines.append("|--------|-------:|--------------:|----------------------:|----------------------:|------------:|-------:|--------:|:---:|")

for regime_name, n_days, n_obs, z5_mean, z3_mean, ratio, t_stat, p_val in results:
    if math.isnan(p_val):
        sig = ""
        p_str = "—"
        t_str = "—"
    else:
        if p_val < 0.001:
            sig = "***"
        elif p_val < 0.01:
            sig = "**"
        elif p_val < 0.05:
            sig = "*"
        else:
            sig = ""
        p_str = f"{p_val:.4f}"
        t_str = f"{t_stat:.2f}"

    lines.append(
        f"| {regime_name:<8} | {n_days:>6} | {n_obs:>13} | {z5_mean:>21.1f} | {z3_mean:>21.1f} "
        f"| {ratio:>11.2f} | {t_str:>6} | {p_str:>7} | {sig:^3} |"
    )

lines.append("")
lines.append("**Significance**: \\*\\*\\* p<0.001, \\*\\* p<0.01, \\* p<0.05")
lines.append("")

# Summary
lines.append("## Summary")
lines.append("")
for regime_name, n_days, n_obs, z5_mean, z3_mean, ratio, t_stat, p_val in results:
    if n_obs < 2:
        lines.append(f"- **{regime_name}**: insufficient data")
        continue
    direction = "higher" if z5_mean > z3_mean else "lower"
    sig_note = ""
    if not math.isnan(p_val) and p_val < 0.05:
        sig_note = " (statistically significant)"
    lines.append(
        f"- **{regime_name}** (VIX {'<16' if regime_name == 'Low' else '16–20' if regime_name == 'Normal' else '20–25' if regime_name == 'Elevated' else '>=25'}): "
        f"Zone 5 mean {z5_mean:.1f} bps vs Zone 3 mean {z3_mean:.1f} bps — "
        f"ratio {ratio:.2f}, Zone 5 {direction}{sig_note}"
    )

lines.append("")

md_text = "\n".join(lines)

out_path = os.path.join(AUDIT_DIR, "PH2_vix_regime.md")
with open(out_path, "w") as f:
    f.write(md_text)

print(f"\nSaved: {out_path}")
print()
print(md_text)
