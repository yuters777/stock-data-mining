#!/usr/bin/env python3
"""PH4: Power-hour returns segmented by 60-day trailing beta group.

1. Compute daily close-to-close returns for each ticker and SPY.
2. For each ticker, compute 60-day trailing beta vs SPY (rolling OLS).
3. Average each ticker's trailing beta across all available days.
4. Rank tickers by average beta and split into 3 groups of 9:
   High-beta (top 9), Medium-beta (middle 9), Low-beta (bottom 9).
5. Pool Zone 5 and Zone 3 absolute returns within each group, run
   paired t-tests.
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
BETA_WINDOW = 60


# ── Helpers ─────────────────────────────────────────────────────────────────
def load_daily_closes(path):
    """Return sorted list of (date_str, close)."""
    rows = []
    with open(path) as f:
        for row in csv.DictReader(f):
            rows.append((row["date"], float(row["Close"])))
    rows.sort()
    return rows


def daily_returns(closes):
    """Return dict date_str -> daily return from sorted (date, close) list."""
    rets = {}
    for i in range(1, len(closes)):
        d_prev, c_prev = closes[i - 1]
        d_curr, c_curr = closes[i]
        rets[d_curr] = (c_curr - c_prev) / c_prev
    return rets


def ols_beta(x, y):
    """OLS slope (beta) of y on x, both lists of same length."""
    n = len(x)
    if n < 10:
        return float("nan")
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / n
    var = sum((xi - mx) ** 2 for xi in x) / n
    if var == 0:
        return float("nan")
    return cov / var


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


# ── Discover tickers ────────────────────────────────────────────────────────
tickers = sorted(
    f.replace("_m5_regsess.csv", "")
    for f in os.listdir(BACKTEST_DIR)
    if f.endswith("_m5_regsess.csv")
    and f.replace("_m5_regsess.csv", "") not in EXCLUDE
)
print(f"Tickers ({len(tickers)}): {', '.join(tickers)}")

# ── Load SPY daily returns ──────────────────────────────────────────────────
spy_closes = load_daily_closes(os.path.join(BACKTEST_DIR, "SPY_daily.csv"))
spy_rets = daily_returns(spy_closes)
spy_dates_sorted = sorted(spy_rets.keys())
print(f"SPY daily returns: {len(spy_rets)} days")

# ── Compute 60-day trailing beta for each ticker, then average ──────────────
ticker_avg_beta = {}

for ticker in tickers:
    daily_path = os.path.join(BACKTEST_DIR, f"{ticker}_daily.csv")
    if not os.path.exists(daily_path):
        print(f"  SKIP {ticker}: no daily file")
        continue

    tk_closes = load_daily_closes(daily_path)
    tk_rets = daily_returns(tk_closes)

    # Aligned dates
    common_dates = sorted(set(tk_rets.keys()) & set(spy_rets.keys()))
    if len(common_dates) < BETA_WINDOW:
        print(f"  SKIP {ticker}: only {len(common_dates)} common days")
        continue

    # Rolling beta
    betas = []
    for i in range(BETA_WINDOW, len(common_dates)):
        window_dates = common_dates[i - BETA_WINDOW:i]
        x = [spy_rets[d] for d in window_dates]
        y = [tk_rets[d] for d in window_dates]
        b = ols_beta(x, y)
        if not math.isnan(b):
            betas.append(b)

    if betas:
        avg_b = statistics.mean(betas)
        ticker_avg_beta[ticker] = avg_b

print(f"\nTickers with computed beta: {len(ticker_avg_beta)}")

# ── Rank and split into 3 groups of 9 ──────────────────────────────────────
ranked = sorted(ticker_avg_beta.items(), key=lambda x: x[1], reverse=True)

for tk, b in ranked:
    print(f"  {tk:<8} beta={b:.3f}")

high_beta = [tk for tk, _ in ranked[:9]]
med_beta = [tk for tk, _ in ranked[9:18]]
low_beta = [tk for tk, _ in ranked[18:27]]

print(f"\nHigh-beta ({len(high_beta)}): {', '.join(high_beta)}")
print(f"Medium-beta ({len(med_beta)}): {', '.join(med_beta)}")
print(f"Low-beta ({len(low_beta)}): {', '.join(low_beta)}")

groups = [
    ("High-beta", set(high_beta)),
    ("Medium-beta", set(med_beta)),
    ("Low-beta", set(low_beta)),
]

# ── Collect zone returns per group ──────────────────────────────────────────
group_data = {g: {"z5": [], "z3": []} for g, _ in groups}
group_ticker_days = {g: 0 for g, _ in groups}

for ticker in tickers:
    # Determine which group this ticker belongs to
    grp = None
    for g, members in groups:
        if ticker in members:
            grp = g
            break
    if grp is None:
        continue

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

        z5 = abs(p["15:55"] - p["14:45"]) / p["14:45"]
        z3 = abs(p["13:30"] - p["12:00"]) / p["12:00"]

        group_data[grp]["z5"].append(z5)
        group_data[grp]["z3"].append(z3)
    group_ticker_days[grp] += len([d for d in day_prices
                                    if all(k in day_prices[d]
                                           for k in ("12:00", "13:30", "14:45", "15:55"))])

# ── Compute stats ───────────────────────────────────────────────────────────
results = []
for g, _ in groups:
    z5 = group_data[g]["z5"]
    z3 = group_data[g]["z3"]
    n = len(z5)
    z5m = statistics.mean(z5) * 10000
    z3m = statistics.mean(z3) * 10000
    ratio = z5m / z3m if z3m > 0 else float("inf")
    t, pv = paired_ttest(z5, z3)
    results.append((g, n, z5m, z3m, ratio, t, pv))

# ── Generate markdown ───────────────────────────────────────────────────────
lines = []
lines.append("# PH4: Power Hour Returns by Beta Group")
lines.append("")
lines.append("**Zone 5** (Power Hour): 14:45–16:00 ET  ")
lines.append("**Zone 3** (Midday Lull): 12:00–13:30 ET  ")
lines.append("**Metric**: Mean absolute return = |close_end − close_start| / close_start  ")
lines.append(f"**Beta**: 60-day trailing OLS beta of daily returns vs SPY, averaged over all rolling windows  ")
lines.append(f"**Data**: M5 regular-session bars, {len(ticker_avg_beta)} tickers, 3 groups of 9  ")
lines.append("")

# Beta ranking table
lines.append("## Ticker Beta Rankings")
lines.append("")
lines.append("| Rank | Ticker | Avg 60d Beta | Group |")
lines.append("|-----:|--------|-------------:|-------|")
for i, (tk, b) in enumerate(ranked, 1):
    if tk in high_beta:
        grp_label = "High"
    elif tk in med_beta:
        grp_label = "Medium"
    else:
        grp_label = "Low"
    lines.append(f"| {i} | {tk} | {b:.3f} | {grp_label} |")

lines.append("")

# Main results
lines.append("## Results: Zone 5 vs Zone 3 by Beta Group")
lines.append("")
lines.append("| Group | Tickers | N ticker-days | Mean \\|Ret\\| Z5 (bps) | Mean \\|Ret\\| Z3 (bps) | Ratio Z5/Z3 | T-stat | P-value | Sig |")
lines.append("|-------|--------:|--------------:|----------------------:|----------------------:|------------:|-------:|--------:|:---:|")

for g, n, z5m, z3m, ratio, t, pv in results:
    if math.isnan(pv):
        sig, p_str, t_str = "", "—", "—"
    else:
        sig = "***" if pv < 0.001 else "**" if pv < 0.01 else "*" if pv < 0.05 else ""
        p_str = f"{pv:.4f}"
        t_str = f"{t:.2f}"

    n_tickers = next(len(m) for gg, m in groups if gg == g)
    lines.append(
        f"| {g:<12} | {n_tickers:>7} | {n:>13} | {z5m:>21.1f} | {z3m:>21.1f} "
        f"| {ratio:>11.2f} | {t_str:>6} | {p_str:>7} | {sig:^3} |"
    )

lines.append("")
lines.append("**Significance**: \\*\\*\\* p<0.001, \\*\\* p<0.01, \\* p<0.05 (paired t-test, Zone 5 − Zone 3)")
lines.append("")

# Summary
lines.append("## Summary")
lines.append("")

for g, n, z5m, z3m, ratio, t, pv in results:
    members = high_beta if "High" in g else med_beta if "Med" in g else low_beta
    direction = "higher" if z5m > z3m else "lower"
    sig_note = ""
    if not math.isnan(pv) and pv < 0.05:
        sig_note = " (statistically significant)"
    lines.append(
        f"- **{g}** ({', '.join(members)}): "
        f"Z5 = {z5m:.1f} bps, Z3 = {z3m:.1f} bps, "
        f"ratio {ratio:.2f} — Zone 5 {direction}{sig_note}"
    )

lines.append("")

md_text = "\n".join(lines)

out_path = os.path.join(AUDIT_DIR, "PH4_beta_groups.md")
with open(out_path, "w") as f:
    f.write(md_text)

print(f"\nSaved: {out_path}")
print()
print(md_text)
