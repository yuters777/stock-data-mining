#!/usr/bin/env python3
"""PH3: Power-hour returns on high-VIX-range ("event proxy") days.

Uses VIXY daily High − Low as a proxy for intraday VIX range.
Days in the top 25 % of VIXY daily range are flagged as "event_proxy".
Compares pooled Zone 5 vs Zone 3 absolute returns for event_proxy vs
normal days, with paired t-tests.
"""

import csv
import math
import os
import statistics
from collections import defaultdict
from datetime import datetime

BACKTEST_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
AUDIT_DIR = os.path.dirname(__file__)
EXCLUDE = {"BTC", "ETH"}

# ── Load VIXY daily OHLC → compute daily range ─────────────────────────────
vixy_daily_path = os.path.join(BACKTEST_DIR, "VIXY_daily.csv")
vixy_range_by_date = {}  # date_str -> high - low

with open(vixy_daily_path) as f:
    for row in csv.DictReader(f):
        date_str = row["date"]
        try:
            hi = float(row["High"])
            lo = float(row["Low"])
        except (ValueError, KeyError):
            continue
        vixy_range_by_date[date_str] = hi - lo

print(f"VIXY daily data: {len(vixy_range_by_date)} trading days")

# ── Determine 75th-percentile threshold ─────────────────────────────────────
all_ranges = sorted(vixy_range_by_date.values())
p75_idx = int(len(all_ranges) * 0.75)
threshold = all_ranges[p75_idx]
print(f"VIXY range 75th percentile (threshold): {threshold:.4f}")
print(f"  Min={all_ranges[0]:.4f}  Median={all_ranges[len(all_ranges)//2]:.4f}  "
      f"Max={all_ranges[-1]:.4f}")

event_dates = {d for d, r in vixy_range_by_date.items() if r >= threshold}
normal_dates = {d for d, r in vixy_range_by_date.items() if r < threshold}
print(f"Event-proxy days: {len(event_dates)}, Normal days: {len(normal_dates)}")

# ── Discover tickers ────────────────────────────────────────────────────────
tickers = sorted(
    f.replace("_m5_regsess.csv", "")
    for f in os.listdir(BACKTEST_DIR)
    if f.endswith("_m5_regsess.csv")
    and f.replace("_m5_regsess.csv", "") not in EXCLUDE
)
print(f"Tickers ({len(tickers)}): {', '.join(tickers)}")

# ── Collect zone returns per group ──────────────────────────────────────────
GROUPS = ["Event Proxy", "Normal"]
group_data = {g: {"z5": [], "z3": []} for g in GROUPS}
group_dates = {g: set() for g in GROUPS}
skipped = 0

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

        if date_str not in vixy_range_by_date:
            skipped += 1
            continue

        z5 = abs(p["15:55"] - p["14:45"]) / p["14:45"]
        z3 = abs(p["13:30"] - p["12:00"]) / p["12:00"]

        if date_str in event_dates:
            g = "Event Proxy"
        else:
            g = "Normal"

        group_data[g]["z5"].append(z5)
        group_data[g]["z3"].append(z3)
        group_dates[g].add(date_str)

print(f"Skipped ticker-days without VIXY match: {skipped}")


# ── Paired t-test helper ────────────────────────────────────────────────────
def paired_ttest(a, b):
    """Two-tailed paired t-test for a - b. Returns (t_stat, p_value)."""
    n = len(a)
    if n < 2:
        return float("nan"), float("nan")
    diffs = [x - y for x, y in zip(a, b)]
    d_mean = statistics.mean(diffs)
    d_std = statistics.stdev(diffs)
    if d_std == 0:
        return float("nan"), float("nan")
    se = d_std / math.sqrt(n)
    t_stat = d_mean / se
    df = n - 1
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


# ── Also run unpooled two-sample t-test: event Z5 vs normal Z5 ─────────────
def welch_ttest(a, b):
    """Two-sample Welch's t-test. Returns (t_stat, p_value)."""
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return float("nan"), float("nan")
    m1, m2 = statistics.mean(a), statistics.mean(b)
    v1, v2 = statistics.variance(a), statistics.variance(b)
    se = math.sqrt(v1 / n1 + v2 / n2)
    if se == 0:
        return float("nan"), float("nan")
    t_stat = (m1 - m2) / se
    # Welch-Satterthwaite df
    num = (v1 / n1 + v2 / n2) ** 2
    denom = (v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1)
    df = num / denom
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


# ── Compute stats per group ─────────────────────────────────────────────────
results = []
for g in GROUPS:
    z5_list = group_data[g]["z5"]
    z3_list = group_data[g]["z3"]
    n_obs = len(z5_list)
    n_days = len(group_dates[g])

    z5_mean = statistics.mean(z5_list) * 10000  # bps
    z3_mean = statistics.mean(z3_list) * 10000
    ratio = z5_mean / z3_mean if z3_mean > 0 else float("inf")
    t_stat, p_val = paired_ttest(z5_list, z3_list)

    results.append((g, n_days, n_obs, z5_mean, z3_mean, ratio, t_stat, p_val))

# Cross-group tests
t_z5, p_z5 = welch_ttest(group_data["Event Proxy"]["z5"],
                          group_data["Normal"]["z5"])
t_z3, p_z3 = welch_ttest(group_data["Event Proxy"]["z3"],
                          group_data["Normal"]["z3"])

# ── Generate markdown ───────────────────────────────────────────────────────
lines = []
lines.append("# PH3: Power Hour Returns — Event Proxy Days vs Normal Days")
lines.append("")
lines.append("**Zone 5** (Power Hour): 14:45–16:00 ET  ")
lines.append("**Zone 3** (Midday Lull): 12:00–13:30 ET  ")
lines.append("**Metric**: Mean absolute return = |close_end − close_start| / close_start  ")
lines.append(f"**Data**: M5 regular-session bars, {len(tickers)} tickers, pooled across all tickers  ")
lines.append("")
lines.append("## Event Proxy Definition")
lines.append("")
lines.append("Daily VIX range is proxied by **VIXY daily High − Low** (VIXY is a VIX-futures ETF).  ")
lines.append(f"Days with VIXY range >= **{threshold:.2f}** (75th percentile) are flagged as **event proxy** days.  ")
lines.append("")
lines.append("| Statistic | Value |")
lines.append("|-----------|------:|")
lines.append(f"| VIXY range min | {all_ranges[0]:.2f} |")
lines.append(f"| VIXY range median | {all_ranges[len(all_ranges)//2]:.2f} |")
lines.append(f"| VIXY range 75th pctl (threshold) | {threshold:.2f} |")
lines.append(f"| VIXY range max | {all_ranges[-1]:.2f} |")
lines.append(f"| Event proxy days | {len(event_dates)} |")
lines.append(f"| Normal days | {len(normal_dates)} |")
lines.append("")
lines.append("## Results: Zone 5 vs Zone 3 Within Each Group")
lines.append("")
lines.append("| Group | N days | N ticker-days | Mean \\|Ret\\| Z5 (bps) | Mean \\|Ret\\| Z3 (bps) | Ratio Z5/Z3 | T-stat | P-value | Sig |")
lines.append("|-------|-------:|--------------:|----------------------:|----------------------:|------------:|-------:|--------:|:---:|")

for g, n_days, n_obs, z5_mean, z3_mean, ratio, t_stat, p_val in results:
    if math.isnan(p_val):
        sig, p_str, t_str = "", "—", "—"
    else:
        sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else ""
        p_str = f"{p_val:.4f}"
        t_str = f"{t_stat:.2f}"
    lines.append(
        f"| {g:<12} | {n_days:>6} | {n_obs:>13} | {z5_mean:>21.1f} | {z3_mean:>21.1f} "
        f"| {ratio:>11.2f} | {t_str:>6} | {p_str:>7} | {sig:^3} |"
    )

lines.append("")
lines.append("**Significance**: \\*\\*\\* p<0.001, \\*\\* p<0.01, \\* p<0.05 (paired t-test, Zone 5 − Zone 3)")
lines.append("")

# Cross-group comparison
lines.append("## Cross-Group Comparison (Welch's t-test)")
lines.append("")
lines.append("Tests whether event-proxy days have higher absolute returns than normal days.")
lines.append("")
lines.append("| Comparison | T-stat | P-value | Sig |")
lines.append("|------------|-------:|--------:|:---:|")

for label, t_val, p_val in [("Zone 5: Event vs Normal", t_z5, p_z5),
                              ("Zone 3: Event vs Normal", t_z3, p_z3)]:
    if math.isnan(p_val):
        sig, p_str, t_str = "", "—", "—"
    else:
        sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else ""
        p_str = f"{p_val:.4f}"
        t_str = f"{t_val:.2f}"
    lines.append(f"| {label} | {t_str:>6} | {p_str:>7} | {sig:^3} |")

lines.append("")

# Summary
lines.append("## Summary")
lines.append("")

ev = results[0]  # Event Proxy
nm = results[1]  # Normal
ev_g, ev_nd, ev_no, ev_z5, ev_z3, ev_r, ev_t, ev_p = ev
nm_g, nm_nd, nm_no, nm_z5, nm_z3, nm_r, nm_t, nm_p = nm

lines.append(f"- **Event proxy days** ({ev_nd} days, {ev_no} ticker-days): "
             f"Zone 5 = {ev_z5:.1f} bps, Zone 3 = {ev_z3:.1f} bps, ratio = {ev_r:.2f}")
lines.append(f"- **Normal days** ({nm_nd} days, {nm_no} ticker-days): "
             f"Zone 5 = {nm_z5:.1f} bps, Zone 3 = {nm_z3:.1f} bps, ratio = {nm_r:.2f}")
lines.append(f"- Event-proxy days amplify both zones: "
             f"Z5 by {ev_z5 / nm_z5:.2f}x, Z3 by {ev_z3 / nm_z3:.2f}x vs normal")

if ev_r > nm_r:
    lines.append(f"- Power Hour advantage is **stronger** on event days "
                 f"(ratio {ev_r:.2f} vs {nm_r:.2f})")
else:
    lines.append(f"- Power Hour advantage is **weaker** on event days "
                 f"(ratio {ev_r:.2f} vs {nm_r:.2f})")

lines.append("")

md_text = "\n".join(lines)

out_path = os.path.join(AUDIT_DIR, "PH3_event_proxy.md")
with open(out_path, "w") as f:
    f.write(md_text)

print(f"\nSaved: {out_path}")
print()
print(md_text)
