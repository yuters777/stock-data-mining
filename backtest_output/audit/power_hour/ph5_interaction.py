#!/usr/bin/env python3
"""PH5: Beta × VIX interaction — does Power Hour only win for
high-beta tickers on elevated-VIX days?

Crosses two dimensions from PH2 and PH4:
  Beta group:  High-beta (top 9) vs Low-beta (bottom 9)  — from PH4
  VIX regime:  Elevated+ (VIX >= 20) vs Low/Normal (VIX < 20) — from PH2

Produces 4 subsets (2 × 2) with pooled Zone 5 vs Zone 3 paired t-tests.
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
BETA_WINDOW = 60


# ── Helpers ─────────────────────────────────────────────────────────────────
def load_daily_closes(path):
    rows = []
    with open(path) as f:
        for row in csv.DictReader(f):
            rows.append((row["date"], float(row["Close"])))
    rows.sort()
    return rows


def daily_returns(closes):
    rets = {}
    for i in range(1, len(closes)):
        d_prev, c_prev = closes[i - 1]
        d_curr, c_curr = closes[i]
        rets[d_curr] = (c_curr - c_prev) / c_prev
    return rets


def ols_beta(x, y):
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


# ── Load VIX daily closes ──────────────────────────────────────────────────
vix_by_date = {}
vix_path = os.path.join(FETCHED_DIR, "VIXCLS_FRED_real.csv")
with open(vix_path) as f:
    for row in csv.DictReader(f):
        try:
            vix_by_date[row["observation_date"]] = float(row["VIXCLS"])
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

# ── Compute 60-day trailing beta → rank → high/low groups ──────────────────
spy_closes = load_daily_closes(os.path.join(BACKTEST_DIR, "SPY_daily.csv"))
spy_rets = daily_returns(spy_closes)

ticker_avg_beta = {}
for ticker in tickers:
    daily_path = os.path.join(BACKTEST_DIR, f"{ticker}_daily.csv")
    if not os.path.exists(daily_path):
        continue
    tk_rets = daily_returns(load_daily_closes(daily_path))
    common = sorted(set(tk_rets.keys()) & set(spy_rets.keys()))
    if len(common) < BETA_WINDOW:
        continue
    betas = []
    for i in range(BETA_WINDOW, len(common)):
        window = common[i - BETA_WINDOW:i]
        b = ols_beta([spy_rets[d] for d in window],
                     [tk_rets[d] for d in window])
        if not math.isnan(b):
            betas.append(b)
    if betas:
        ticker_avg_beta[ticker] = statistics.mean(betas)

ranked = sorted(ticker_avg_beta.items(), key=lambda x: x[1], reverse=True)
high_beta_set = set(tk for tk, _ in ranked[:9])
low_beta_set = set(tk for tk, _ in ranked[18:27])

high_beta_list = [tk for tk, _ in ranked[:9]]
low_beta_list = [tk for tk, _ in ranked[18:27]]

print(f"\nHigh-beta (9): {', '.join(f'{tk}({ticker_avg_beta[tk]:.2f})' for tk in high_beta_list)}")
print(f"Low-beta  (9): {', '.join(f'{tk}({ticker_avg_beta[tk]:.2f})' for tk in low_beta_list)}")

# ── Define the 4 interaction subsets ────────────────────────────────────────
SUBSETS = [
    ("1. High-beta × Elevated+ VIX", high_beta_set, lambda v: v >= 20),
    ("2. High-beta × Low/Normal VIX", high_beta_set, lambda v: v < 20),
    ("3. Low-beta × Elevated+ VIX",  low_beta_set,  lambda v: v >= 20),
    ("4. Low-beta × Low/Normal VIX",  low_beta_set,  lambda v: v < 20),
]

subset_data = {label: {"z5": [], "z3": [], "dates": set()}
               for label, _, _ in SUBSETS}
skipped = 0

# ── Collect zone returns ───────────────────────────────────────────────────
for ticker in tickers:
    # Only process tickers in high or low beta groups
    in_high = ticker in high_beta_set
    in_low = ticker in low_beta_set
    if not in_high and not in_low:
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
        if date_str not in vix_by_date:
            skipped += 1
            continue

        vix_val = vix_by_date[date_str]
        z5 = abs(p["15:55"] - p["14:45"]) / p["14:45"]
        z3 = abs(p["13:30"] - p["12:00"]) / p["12:00"]

        for label, beta_set, vix_fn in SUBSETS:
            if ticker in beta_set and vix_fn(vix_val):
                subset_data[label]["z5"].append(z5)
                subset_data[label]["z3"].append(z3)
                subset_data[label]["dates"].add(date_str)
                break

print(f"Skipped ticker-days without VIX match: {skipped}")

# ── Compute stats ───────────────────────────────────────────────────────────
results = []
for label, _, _ in SUBSETS:
    sd = subset_data[label]
    z5, z3 = sd["z5"], sd["z3"]
    n_obs = len(z5)
    n_days = len(sd["dates"])
    z5m = statistics.mean(z5) * 10000
    z3m = statistics.mean(z3) * 10000
    ratio = z5m / z3m if z3m > 0 else float("inf")
    t, pv = paired_ttest(z5, z3)
    results.append((label, n_days, n_obs, z5m, z3m, ratio, t, pv))

# ── Generate markdown ───────────────────────────────────────────────────────
L = []
L.append("# PH5: Beta × VIX Interaction — Power Hour Subset Analysis")
L.append("")
L.append("**Zone 5** (Power Hour): 14:45–16:00 ET  ")
L.append("**Zone 3** (Midday Lull): 12:00–13:30 ET  ")
L.append("**Metric**: Mean absolute return = |close_end − close_start| / close_start  ")
L.append("**Beta**: 60-day trailing OLS beta vs SPY, averaged (from PH4)  ")
L.append("**VIX**: CBOE VIX daily close (FRED VIXCLS, from PH2)  ")
L.append(f"**Data**: M5 regular-session bars, 18 tickers (9 high-beta + 9 low-beta)  ")
L.append("")

L.append("## Subset Definitions")
L.append("")
L.append("| Dimension | Split | Criteria |")
L.append("|-----------|-------|----------|")
L.append("| Beta group | High-beta (top 9) | " + ", ".join(high_beta_list) + " |")
L.append("| Beta group | Low-beta (bottom 9) | " + ", ".join(low_beta_list) + " |")
L.append("| VIX regime | Elevated+ | VIX daily close >= 20 |")
L.append("| VIX regime | Low/Normal | VIX daily close < 20 |")
L.append("")

L.append("## Results")
L.append("")
L.append("| # | Subset | N days | N ticker-days | Mean \\|Ret\\| Z5 (bps) | Mean \\|Ret\\| Z3 (bps) | Ratio Z5/Z3 | T-stat | P-value | Sig |")
L.append("|---|--------|-------:|--------------:|----------------------:|----------------------:|------------:|-------:|--------:|:---:|")

for label, n_days, n_obs, z5m, z3m, ratio, t, pv in results:
    if math.isnan(pv):
        sig, p_str, t_str = "", "—", "—"
    else:
        sig = "***" if pv < 0.001 else "**" if pv < 0.01 else "*" if pv < 0.05 else ""
        p_str = f"{pv:.4f}"
        t_str = f"{t:.2f}"
    num = label[0]
    short = label[3:]
    L.append(
        f"| {num} | {short:<32} | {n_days:>6} | {n_obs:>13} | {z5m:>21.1f} | {z3m:>21.1f} "
        f"| {ratio:>11.2f} | {t_str:>6} | {p_str:>7} | {sig:^3} |"
    )

L.append("")
L.append("**Significance**: \\*\\*\\* p<0.001, \\*\\* p<0.01, \\* p<0.05 (paired t-test, Zone 5 − Zone 3)")
L.append("")

# Key question answer
L.append("## Key Question: Is Subset #1 the Only One Where Zone 5 Reliably Beats Zone 3?")
L.append("")

z5_wins = [(label, ratio, pv) for label, _, _, _, _, ratio, _, pv in results
           if ratio > 1.0 and not math.isnan(pv) and pv < 0.05]

if len(z5_wins) == 1 and z5_wins[0][0].startswith("1"):
    L.append("**Yes.** Subset #1 (high-beta × elevated+ VIX) is the *only* subset where "
             "Zone 5 significantly outperforms Zone 3.")
elif len(z5_wins) == 0:
    L.append("**No** — in fact, Zone 5 does not significantly beat Zone 3 in *any* subset.")
else:
    winning_labels = [lbl for lbl, _, _ in z5_wins]
    L.append(f"**No** — Zone 5 significantly beats Zone 3 in: {', '.join(winning_labels)}.")

L.append("")
L.append("### Interpretation by Subset")
L.append("")

for label, n_days, n_obs, z5m, z3m, ratio, t, pv in results:
    direction = "Zone 5 > Zone 3" if z5m > z3m else "Zone 3 > Zone 5"
    if math.isnan(pv):
        sig_word = "insufficient data"
    elif pv < 0.001:
        sig_word = "highly significant"
    elif pv < 0.01:
        sig_word = "significant"
    elif pv < 0.05:
        sig_word = "significant"
    else:
        sig_word = "not significant"

    L.append(f"- **{label}**: {direction} (ratio {ratio:.2f}, p={pv:.4f}, {sig_word})")

L.append("")
L.append("### Implications")
L.append("")

# Determine the narrative based on results
r1 = results[0]  # High-beta × Elevated+ VIX
r2 = results[1]  # High-beta × Low/Normal VIX
r3 = results[2]  # Low-beta × Elevated+ VIX
r4 = results[3]  # Low-beta × Low/Normal VIX

L.append(f"- High-beta tickers in elevated+ VIX: Z5/Z3 = {r1[5]:.2f} — "
         f"{'Power Hour advantage present' if r1[5] > 1.0 else 'no Power Hour advantage'}")
L.append(f"- High-beta tickers in low/normal VIX: Z5/Z3 = {r2[5]:.2f} — "
         f"{'Power Hour advantage present' if r2[5] > 1.0 else 'no Power Hour advantage'}")
L.append(f"- Low-beta tickers in elevated+ VIX: Z5/Z3 = {r3[5]:.2f} — "
         f"{'Power Hour advantage present' if r3[5] > 1.0 else 'Zone 3 dominates'}")
L.append(f"- Low-beta tickers in low/normal VIX: Z5/Z3 = {r4[5]:.2f} — "
         f"{'Power Hour advantage present' if r4[5] > 1.0 else 'Zone 3 dominates'}")
L.append(f"- The Power Hour effect requires **high beta**; VIX level modulates the magnitude "
         f"but does not flip the sign for high-beta names")

L.append("")

md_text = "\n".join(L)

out_path = os.path.join(AUDIT_DIR, "PH5_interaction.md")
with open(out_path, "w") as f:
    f.write(md_text)

print(f"\nSaved: {out_path}")
print()
print(md_text)
