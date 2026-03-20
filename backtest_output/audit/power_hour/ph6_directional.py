#!/usr/bin/env python3
"""PH6: Directional analysis — does Power Hour resolve direction or just
amplify noise?

Focuses on the best-performing PH5 subset: high-beta × low/normal VIX (<20).
Computes:
  1. Mean SIGNED Zone 5 return (not absolute)
  2. % of days where Zone 5 direction matches overall day direction
     (day direction = sign of close@15:55 − open@09:30)
  3. Same metrics for Zone 2 (10:00–12:00) as a control/comparison zone

Also runs same analysis on:
  - All high-beta ticker-days (regardless of VIX) for context
  - The full universe (all 27 tickers, all days) as baseline
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
        rets[closes[i][0]] = (closes[i][1] - closes[i - 1][1]) / closes[i - 1][1]
    return rets


def ols_beta(x, y):
    n = len(x)
    if n < 10:
        return float("nan")
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / n
    var = sum((xi - mx) ** 2 for xi in x) / n
    return float("nan") if var == 0 else cov / var


def binom_p(k, n, p0=0.5):
    """Two-tailed binomial test p-value via normal approximation."""
    if n == 0:
        return float("nan")
    z = (k / n - p0) / math.sqrt(p0 * (1 - p0) / n)
    return math.erfc(abs(z) / math.sqrt(2))


def one_sample_ttest(vals):
    """Two-tailed one-sample t-test for mean != 0. Returns (t_stat, p)."""
    n = len(vals)
    if n < 2:
        return float("nan"), float("nan")
    m = statistics.mean(vals)
    s = statistics.stdev(vals)
    if s == 0:
        return float("nan"), float("nan")
    t = m / (s / math.sqrt(n))
    df = n - 1
    if df > 100:
        p = math.erfc(abs(t) / math.sqrt(2))
    else:
        from math import gamma
        coeff = gamma((df + 1) / 2) / (math.sqrt(df * math.pi) * gamma(df / 2))
        steps = 10000
        upper = abs(t) + 50
        dt_step = (upper - abs(t)) / steps
        integral = 0.0
        for i in range(steps):
            x_val = abs(t) + (i + 0.5) * dt_step
            integral += coeff * (1 + x_val ** 2 / df) ** (-(df + 1) / 2) * dt_step
        p = 2 * integral
    return t, p


# ── Load VIX ────────────────────────────────────────────────────────────────
vix_by_date = {}
with open(os.path.join(FETCHED_DIR, "VIXCLS_FRED_real.csv")) as f:
    for row in csv.DictReader(f):
        try:
            vix_by_date[row["observation_date"]] = float(row["VIXCLS"])
        except (ValueError, KeyError):
            pass

print(f"VIX daily data: {len(vix_by_date)} days")

# ── Discover tickers ────────────────────────────────────────────────────────
tickers = sorted(
    f.replace("_m5_regsess.csv", "")
    for f in os.listdir(BACKTEST_DIR)
    if f.endswith("_m5_regsess.csv")
    and f.replace("_m5_regsess.csv", "") not in EXCLUDE
)

# ── Compute beta ranking → high-beta set ────────────────────────────────────
spy_rets = daily_returns(load_daily_closes(
    os.path.join(BACKTEST_DIR, "SPY_daily.csv")))

ticker_avg_beta = {}
for tk in tickers:
    dp = os.path.join(BACKTEST_DIR, f"{tk}_daily.csv")
    if not os.path.exists(dp):
        continue
    tk_rets = daily_returns(load_daily_closes(dp))
    common = sorted(set(tk_rets) & set(spy_rets))
    if len(common) < BETA_WINDOW:
        continue
    betas = []
    for i in range(BETA_WINDOW, len(common)):
        w = common[i - BETA_WINDOW:i]
        b = ols_beta([spy_rets[d] for d in w], [tk_rets[d] for d in w])
        if not math.isnan(b):
            betas.append(b)
    if betas:
        ticker_avg_beta[tk] = statistics.mean(betas)

ranked = sorted(ticker_avg_beta.items(), key=lambda x: x[1], reverse=True)
high_beta_set = set(tk for tk, _ in ranked[:9])
high_beta_list = [tk for tk, _ in ranked[:9]]
print(f"High-beta (9): {', '.join(high_beta_list)}")

# ── Collect M5 prices for all tickers ───────────────────────────────────────
# Need: 09:30 (open of day), 10:00, 12:00, 14:45, 15:55 (close of day)
NEEDED_BARS = ("09:30", "10:00", "12:00", "14:45", "15:55")

# Each record: (ticker, date, {hhmm: close})
all_records = []

for tk in tickers:
    fpath = os.path.join(BACKTEST_DIR, f"{tk}_m5_regsess.csv")
    day_prices = defaultdict(dict)
    day_open = {}  # date -> open of 09:30 bar

    with open(fpath) as f:
        for row in csv.DictReader(f):
            dt = datetime.strptime(row["Datetime"], "%Y-%m-%d %H:%M:%S")
            ds = dt.strftime("%Y-%m-%d")
            hhmm = f"{dt.hour:02d}:{dt.minute:02d}"
            if hhmm in NEEDED_BARS:
                day_prices[ds][hhmm] = float(row["Close"])
            if hhmm == "09:30":
                day_open[ds] = float(row["Open"])

    for ds in sorted(day_prices):
        p = day_prices[ds]
        if not all(k in p for k in NEEDED_BARS) or ds not in day_open:
            continue
        all_records.append((tk, ds, p, day_open[ds]))

print(f"Total ticker-days with complete data: {len(all_records)}")


# ── Define analysis groups ──────────────────────────────────────────────────
def match_best_subset(tk, ds):
    """High-beta × Low/Normal VIX (<20)"""
    return tk in high_beta_set and ds in vix_by_date and vix_by_date[ds] < 20


def match_high_beta_all(tk, ds):
    return tk in high_beta_set


def match_all(tk, ds):
    return True


def match_high_beta_elevated(tk, ds):
    """High-beta × Elevated+ VIX (>=20) — for contrast"""
    return tk in high_beta_set and ds in vix_by_date and vix_by_date[ds] >= 20


ANALYSIS_GROUPS = [
    ("High-beta × Low/Normal VIX (best subset)", match_best_subset),
    ("High-beta × Elevated+ VIX", match_high_beta_elevated),
    ("High-beta (all VIX)", match_high_beta_all),
    ("All tickers (all VIX)", match_all),
]


# ── Compute directional stats per group ─────────────────────────────────────
class GroupStats:
    def __init__(self):
        self.z5_signed = []
        self.z2_signed = []
        self.z5_match_day = 0
        self.z2_match_day = 0
        self.n_nonflat_day = 0  # days where day return != 0
        self.n = 0


group_stats = {name: GroupStats() for name, _ in ANALYSIS_GROUPS}

for tk, ds, p, day_open_price in all_records:
    # Day direction: close@15:55 vs open@09:30
    day_close = p["15:55"]
    day_ret = (day_close - day_open_price) / day_open_price
    day_dir = 1 if day_ret > 0 else (-1 if day_ret < 0 else 0)

    # Zone 5 signed return: close@15:55 − close@14:45
    z5_ret = (p["15:55"] - p["14:45"]) / p["14:45"]
    z5_dir = 1 if z5_ret > 0 else (-1 if z5_ret < 0 else 0)

    # Zone 2 signed return: close@12:00 − close@10:00
    z2_ret = (p["12:00"] - p["10:00"]) / p["10:00"]
    z2_dir = 1 if z2_ret > 0 else (-1 if z2_ret < 0 else 0)

    for name, match_fn in ANALYSIS_GROUPS:
        if not match_fn(tk, ds):
            continue
        gs = group_stats[name]
        gs.z5_signed.append(z5_ret)
        gs.z2_signed.append(z2_ret)
        gs.n += 1

        if day_dir != 0:
            gs.n_nonflat_day += 1
            if z5_dir == day_dir:
                gs.z5_match_day += 1
            if z2_dir == day_dir:
                gs.z2_match_day += 1


# ── Generate markdown ───────────────────────────────────────────────────────
L = []
L.append("# PH6: Directional Analysis — Does Power Hour Resolve Direction or Amplify Noise?")
L.append("")
L.append("**Best subset from PH5**: High-beta tickers × Low/Normal VIX (<20)  ")
L.append("**Zone 5** (Power Hour): 14:45–16:00 ET  ")
L.append("**Zone 2** (Mid-morning): 10:00–12:00 ET (comparison zone)  ")
L.append("**Day direction**: sign of (close@15:55 − open@09:30)  ")
L.append(f"**High-beta tickers**: {', '.join(high_beta_list)}  ")
L.append("")

L.append("## Signed Returns")
L.append("")
L.append("Mean signed return tests whether the zone has a directional bias (t-test vs 0).")
L.append("")
L.append("| Group | N | Mean Signed Z5 (bps) | T-stat | P-value | Mean Signed Z2 (bps) | T-stat | P-value |")
L.append("|-------|--:|---------------------:|-------:|--------:|---------------------:|-------:|--------:|")

for name, _ in ANALYSIS_GROUPS:
    gs = group_stats[name]
    z5m = statistics.mean(gs.z5_signed) * 10000
    z2m = statistics.mean(gs.z2_signed) * 10000
    t5, p5 = one_sample_ttest(gs.z5_signed)
    t2, p2 = one_sample_ttest(gs.z2_signed)
    L.append(
        f"| {name} | {gs.n} | {z5m:+.2f} | {t5:.2f} | {p5:.4f} "
        f"| {z2m:+.2f} | {t2:.2f} | {p2:.4f} |"
    )

L.append("")

L.append("## Direction Agreement with Day")
L.append("")
L.append("% of ticker-days (with non-zero day return) where zone direction matches day direction.  ")
L.append("50% = random; >50% = zone predicts/resolves day direction.  ")
L.append("Binomial test vs 50%.")
L.append("")
L.append("| Group | N (nonflat) | Z5 Match % | Binom P | Z2 Match % | Binom P |")
L.append("|-------|------------:|-----------:|--------:|-----------:|--------:|")

for name, _ in ANALYSIS_GROUPS:
    gs = group_stats[name]
    nd = gs.n_nonflat_day
    z5_pct = 100.0 * gs.z5_match_day / nd if nd > 0 else 0
    z2_pct = 100.0 * gs.z2_match_day / nd if nd > 0 else 0
    bp5 = binom_p(gs.z5_match_day, nd)
    bp2 = binom_p(gs.z2_match_day, nd)
    L.append(
        f"| {name} | {nd} | {z5_pct:.1f}% | {bp5:.4f} "
        f"| {z2_pct:.1f}% | {bp2:.4f} |"
    )

L.append("")

# ── Verdict ─────────────────────────────────────────────────────────────────
L.append("## Verdict: Direction Resolution vs Noise Amplification")
L.append("")

best = group_stats["High-beta × Low/Normal VIX (best subset)"]
nd = best.n_nonflat_day
z5_pct = 100.0 * best.z5_match_day / nd if nd > 0 else 0
z2_pct = 100.0 * best.z2_match_day / nd if nd > 0 else 0
z5_signed_mean = statistics.mean(best.z5_signed) * 10000
z2_signed_mean = statistics.mean(best.z2_signed) * 10000
_, p_z5_signed = one_sample_ttest(best.z5_signed)
bp5 = binom_p(best.z5_match_day, nd)
bp2 = binom_p(best.z2_match_day, nd)

L.append("### Signed Return Test")
L.append("")
if p_z5_signed < 0.05:
    L.append(f"Zone 5 has a statistically significant directional bias "
             f"({z5_signed_mean:+.2f} bps, p={p_z5_signed:.4f}). "
             f"This suggests a systematic drift, not just noise.")
else:
    L.append(f"Zone 5 mean signed return ({z5_signed_mean:+.2f} bps) is **not** "
             f"significantly different from zero (p={p_z5_signed:.4f}). "
             f"The large absolute returns are bidirectional — "
             f"the Power Hour amplifies movement magnitude without a consistent direction.")

L.append("")
L.append("### Day-Direction Agreement Test")
L.append("")
if bp5 < 0.05 and z5_pct > 50:
    L.append(f"Zone 5 matches the day's direction {z5_pct:.1f}% of the time "
             f"(p={bp5:.4f}), significantly above 50%. "
             f"**Power Hour resolves direction** — it tends to move with "
             f"the day's prevailing trend.")
elif bp5 < 0.05 and z5_pct < 50:
    L.append(f"Zone 5 matches the day's direction only {z5_pct:.1f}% (p={bp5:.4f}), "
             f"significantly below 50%. Power Hour tends to *reverse* the day's direction.")
else:
    L.append(f"Zone 5 matches the day's direction {z5_pct:.1f}% of the time "
             f"(p={bp5:.4f}), not significantly different from 50%. "
             f"**Power Hour does not resolve direction** — it is directionally random "
             f"relative to the day's overall move.")

L.append("")
L.append(f"Zone 2 comparison: matches day direction {z2_pct:.1f}% (p={bp2:.4f}).")
L.append("")

# Final synthesis
L.append("### Synthesis")
L.append("")
if p_z5_signed >= 0.05 and bp5 >= 0.05:
    L.append("Power Hour in the best subset (high-beta × calm VIX) **amplifies noise, "
             "not signal**. The zone produces larger absolute returns than midday (PH1–PH5), "
             "but those returns are bidirectional with no net drift and no systematic alignment "
             "with the day's direction. A strategy relying on Power Hour directional moves "
             "would not have an edge over a coin flip.")
elif bp5 < 0.05 and z5_pct > 50 and p_z5_signed >= 0.05:
    L.append("Power Hour **resolves direction** — it aligns with the day's trend "
             "significantly more than chance, even though the mean signed return is near zero. "
             "This suggests Power Hour moves are trend-confirming, not drift-generating. "
             "A strategy could exploit this by trading Power Hour in the direction "
             "established earlier in the session.")
elif bp5 < 0.05 and z5_pct > 50 and p_z5_signed < 0.05:
    L.append("Power Hour both **resolves direction** (aligns with day trend) and carries "
             "a **net directional drift**. This is the strongest possible signal — larger "
             "moves that systematically align with the day's prevailing direction.")
else:
    L.append("Mixed results — see individual tests above for nuanced interpretation.")

L.append("")

md_text = "\n".join(L)

out_path = os.path.join(AUDIT_DIR, "PH6_directional.md")
with open(out_path, "w") as f:
    f.write(md_text)

print(f"\nSaved: {out_path}")
print()
print(md_text)
