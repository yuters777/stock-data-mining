#!/usr/bin/env python3
"""Audit A3: Phantom lunch-crunch (11:30 ET sell-off) analysis.

Tests the claim that there is a systematic sell-off around 11:30 ET.
Based on N=3 live observations — this audit checks 282 days × 6 tickers.

Windows (30 min each, using Open of boundary M5 bars):
  ret_control: 10:45 → 11:15  (pre-phantom baseline)
  ret_phantom: 11:15 → 11:45  (the claimed sell-off window)
  ret_post:    11:45 → 12:15  (post-phantom)

Wilcoxon signed-rank test: is ret_phantom more negative than ret_control?
"""

import csv
import math
import os
import statistics
from collections import defaultdict
from datetime import datetime

BACKTEST_DIR = os.path.join(os.path.dirname(__file__), "..")
AUDIT_DIR = os.path.dirname(__file__)

TICKERS = ["SPY", "NVDA", "AAPL", "GOOGL", "TSLA", "META"]

# Boundary bar times — we use the OPEN of these bars as exact boundary prices
BOUNDARIES = ["10:45", "11:15", "11:45", "12:15"]


def wilcoxon_signed_rank(x, y):
    """Wilcoxon signed-rank test (two-sided). Returns (W_stat, z_approx, p_approx, n_nonzero).

    For n > 25, uses normal approximation with continuity correction.
    """
    diffs = [xi - yi for xi, yi in zip(x, y)]
    # Remove zeros
    nonzero = [(abs(d), d) for d in diffs if d != 0.0]
    n = len(nonzero)
    if n == 0:
        return 0, 0.0, 1.0, 0

    # Rank by absolute value
    nonzero.sort(key=lambda t: t[0])

    # Assign ranks (handle ties by averaging)
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n and nonzero[j][0] == nonzero[i][0]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[k] = avg_rank
        i = j

    # Sum of ranks for positive differences
    w_plus = sum(r for r, (_, d) in zip(ranks, nonzero) if d > 0)
    w_minus = sum(r for r, (_, d) in zip(ranks, nonzero) if d < 0)
    w_stat = min(w_plus, w_minus)

    # Normal approximation for n > 25
    mean_w = n * (n + 1) / 4.0
    std_w = math.sqrt(n * (n + 1) * (2 * n + 1) / 24.0)
    if std_w == 0:
        return w_stat, 0.0, 1.0, n

    # Continuity correction
    z = (w_stat - mean_w + 0.5) / std_w
    # Two-tailed p-value (normal approximation)
    p = math.erfc(abs(z) / math.sqrt(2))

    # Also return signed z: negative means first arg tends to be smaller
    # w_plus < w_minus means x tends to be < y (i.e., diffs tend negative)
    z_signed = z if w_plus <= w_minus else -z

    return w_stat, z_signed, p, n


# ── Collect data ────────────────────────────────────────────────────────────
rows_out = []
all_phantom = []
all_control = []
all_post = []
ticker_data = defaultdict(lambda: {"phantom": [], "control": [], "post": []})

for ticker in TICKERS:
    fpath = os.path.join(BACKTEST_DIR, f"{ticker}_m5_regsess.csv")

    # day → {hhmm: open_price}
    day_opens = defaultdict(dict)
    with open(fpath) as f:
        for row in csv.DictReader(f):
            dt = datetime.strptime(row["Datetime"], "%Y-%m-%d %H:%M:%S")
            hhmm = f"{dt.hour:02d}:{dt.minute:02d}"
            if hhmm in BOUNDARIES:
                day_opens[dt.strftime("%Y-%m-%d")][hhmm] = float(row["Open"])

    for date_str in sorted(day_opens):
        p = day_opens[date_str]
        if not all(b in p for b in BOUNDARIES):
            continue

        ret_control = (p["11:15"] - p["10:45"]) / p["10:45"]
        ret_phantom = (p["11:45"] - p["11:15"]) / p["11:15"]
        ret_post = (p["12:15"] - p["11:45"]) / p["11:45"]

        all_control.append(ret_control)
        all_phantom.append(ret_phantom)
        all_post.append(ret_post)
        ticker_data[ticker]["control"].append(ret_control)
        ticker_data[ticker]["phantom"].append(ret_phantom)
        ticker_data[ticker]["post"].append(ret_post)

        rows_out.append({
            "date": date_str,
            "ticker": ticker,
            "p_1045": f"{p['10:45']:.4f}",
            "p_1115": f"{p['11:15']:.4f}",
            "p_1145": f"{p['11:45']:.4f}",
            "p_1215": f"{p['12:15']:.4f}",
            "ret_control": f"{ret_control:.6f}",
            "ret_phantom": f"{ret_phantom:.6f}",
            "ret_post": f"{ret_post:.6f}",
        })

N = len(all_phantom)
print(f"Tickers: {', '.join(TICKERS)}")
print(f"Ticker-days with complete data: {N}")

# ── Save CSV ────────────────────────────────────────────────────────────────
csv_path = os.path.join(AUDIT_DIR, "audit_a3_phantom_lc.csv")
with open(csv_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
    writer.writeheader()
    writer.writerows(rows_out)
print(f"Saved: {csv_path}")

# ── Statistics ──────────────────────────────────────────────────────────────
lines = []


def p(line=""):
    print(line)
    lines.append(line)


p("=" * 72)
p("AUDIT A3: PHANTOM LUNCH-CRUNCH (11:30 ET SELL-OFF)")
p("=" * 72)
p(f"Claim: systematic sell-off around 11:30 ET (based on N=3 live obs)")
p(f"Test: 30-min returns for {len(TICKERS)} liquid tickers × ~282 days = {N} obs")
p()
p("WINDOWS (30 min each, open-to-open of boundary M5 bars):")
p("  ret_control: 10:45 → 11:15  (pre-phantom baseline)")
p("  ret_phantom: 11:15 → 11:45  (the claimed sell-off window)")
p("  ret_post:    11:45 → 12:15  (post-phantom)")
p()

# Descriptive stats
ph_mean = statistics.mean(all_phantom) * 100
ph_med = statistics.median(all_phantom) * 100
ph_std = statistics.stdev(all_phantom) * 100
ct_mean = statistics.mean(all_control) * 100
ct_med = statistics.median(all_control) * 100
ct_std = statistics.stdev(all_control) * 100
po_mean = statistics.mean(all_post) * 100
po_med = statistics.median(all_post) * 100
po_std = statistics.stdev(all_post) * 100

p("DESCRIPTIVE STATISTICS (% return):")
p(f"  {'Window':<14} {'Mean':>9} {'Median':>9} {'Std':>9} {'N':>6}")
p(f"  {'-' * 50}")
p(f"  {'ret_control':<14} {ct_mean:>+8.4f}% {ct_med:>+8.4f}% {ct_std:>8.4f}% {N:>6}")
p(f"  {'ret_phantom':<14} {ph_mean:>+8.4f}% {ph_med:>+8.4f}% {ph_std:>8.4f}% {N:>6}")
p(f"  {'ret_post':<14} {po_mean:>+8.4f}% {po_med:>+8.4f}% {po_std:>8.4f}% {N:>6}")
p()

# Is ret_phantom negative on average?
n_neg = sum(1 for r in all_phantom if r < 0)
n_pos = sum(1 for r in all_phantom if r > 0)
n_zero = N - n_neg - n_pos
p(f"ret_phantom direction: {n_neg} negative ({100*n_neg/N:.1f}%), "
  f"{n_pos} positive ({100*n_pos/N:.1f}%), {n_zero} zero")
p(f"Mean phantom return: {ph_mean:+.4f}% — {'NEGATIVE as claimed' if ph_mean < 0 else 'NOT negative (claim fails)'}")
p()

# One-sample test: is ret_phantom mean significantly < 0?
se_ph = ph_std / math.sqrt(N)
t_onesample = ph_mean / se_ph
p_onesample = 0.5 * math.erfc(-t_onesample / math.sqrt(2))  # one-tailed P(T < t)
# For "is it negative?", we want P(mean < 0), which is the left tail
p(f"ONE-SAMPLE t-test: is mean(ret_phantom) < 0?")
p(f"  t = {t_onesample:.4f}, p (one-tailed, left) = {1 - p_onesample:.4f}")
p(f"  {'SIGNIFICANT at α=0.05: phantom return is systematically negative' if (1 - p_onesample) < 0.05 and ph_mean < 0 else 'NOT significant: no evidence of systematic negative return'}")
p()

# Wilcoxon signed-rank: ret_phantom vs ret_control
w_stat, z_val, p_val, n_nz = wilcoxon_signed_rank(all_phantom, all_control)
p("WILCOXON SIGNED-RANK TEST: ret_phantom vs ret_control")
p("  H0: ret_phantom and ret_control have the same distribution")
p("  H1: ret_phantom is more negative than ret_control")
p(f"  W = {w_stat:.0f}")
p(f"  z = {z_val:.4f} (normal approx, continuity-corrected)")
p(f"  p (two-sided) = {p_val:.4e}")
p(f"  n (nonzero diffs) = {n_nz}")
diff_mean = (statistics.mean(all_phantom) - statistics.mean(all_control)) * 100
p(f"  Mean(phantom) - Mean(control) = {diff_mean:+.4f}%")
if p_val < 0.05:
    direction = "more negative" if diff_mean < 0 else "more positive"
    p(f"  SIGNIFICANT at α=0.05: phantom window is {direction} than control")
else:
    p(f"  NOT significant at α=0.05: no difference between phantom and control")
p()

# Wilcoxon: ret_phantom vs ret_post
w2, z2, p2, n2 = wilcoxon_signed_rank(all_phantom, all_post)
diff2 = (statistics.mean(all_phantom) - statistics.mean(all_post)) * 100
p("WILCOXON SIGNED-RANK TEST: ret_phantom vs ret_post")
p(f"  W = {w2:.0f}, z = {z2:.4f}, p = {p2:.4e}, n = {n2}")
p(f"  Mean(phantom) - Mean(post) = {diff2:+.4f}%")
if p2 < 0.05:
    direction2 = "more negative" if diff2 < 0 else "more positive"
    p(f"  SIGNIFICANT: phantom is {direction2} than post-phantom")
else:
    p(f"  NOT significant")
p()

# ── Per-ticker breakdown ────────────────────────────────────────────────────
p("PER-TICKER BREAKDOWN:")
p(f"  {'Ticker':<8} {'Phantom':>10} {'Control':>10} {'Post':>10} {'%Neg':>8} {'N':>5}")
p(f"  {'-' * 55}")
for t in TICKERS:
    td = ticker_data[t]
    pm = statistics.mean(td["phantom"]) * 100
    cm = statistics.mean(td["control"]) * 100
    po_m = statistics.mean(td["post"]) * 100
    neg = sum(1 for r in td["phantom"] if r < 0)
    nt = len(td["phantom"])
    p(f"  {t:<8} {pm:>+9.4f}% {cm:>+9.4f}% {po_m:>+9.4f}% {100*neg/nt:>7.1f}% {nt:>5}")

# Per-ticker Wilcoxon
p()
p("PER-TICKER WILCOXON (phantom vs control):")
p(f"  {'Ticker':<8} {'z':>8} {'p':>10} {'Δmean':>10} {'Sig?':>6}")
p(f"  {'-' * 46}")
for t in TICKERS:
    td = ticker_data[t]
    wt, zt, pt, nt = wilcoxon_signed_rank(td["phantom"], td["control"])
    dm = (statistics.mean(td["phantom"]) - statistics.mean(td["control"])) * 100
    sig = "YES" if pt < 0.05 else "no"
    p(f"  {t:<8} {zt:>+7.3f} {pt:>10.4f} {dm:>+9.4f}% {sig:>6}")

# ── Day-of-week effect? ────────────────────────────────────────────────────
p()
p("DAY-OF-WEEK: MEAN PHANTOM RETURN (%):")
dow_rets = defaultdict(list)
for row in rows_out:
    dt = datetime.strptime(row["date"], "%Y-%m-%d")
    dow = dt.strftime("%A")
    dow_rets[dow].append(float(row["ret_phantom"]))

p(f"  {'Day':<12} {'Mean':>9} {'Median':>9} {'N':>5}")
p(f"  {'-' * 38}")
for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
    if day in dow_rets:
        m = statistics.mean(dow_rets[day]) * 100
        med = statistics.median(dow_rets[day]) * 100
        p(f"  {day:<12} {m:>+8.4f}% {med:>+8.4f}% {len(dow_rets[day]):>5}")

# ── Verdict ─────────────────────────────────────────────────────────────────
p()
p("=" * 72)
p("VERDICT")
p("=" * 72)
p(f"  Claim: systematic sell-off at 11:30 ET (N=3 live observations)")
p(f"  Data:  {N} ticker-days across {len(TICKERS)} liquid names")
p(f"  Mean phantom return (11:15→11:45): {ph_mean:+.4f}%")
p(f"  Wilcoxon phantom vs control: p = {p_val:.4e}")
if ph_mean < 0 and p_val < 0.05:
    p("  CONFIRMED: statistically significant negative bias in phantom window")
elif ph_mean < 0 and p_val >= 0.05:
    p("  WEAK: phantom return is slightly negative but NOT significantly")
    p("  different from the adjacent control window. The N=3 observation")
    p("  was likely coincidence or market-regime-specific.")
else:
    p("  REJECTED: phantom return is not negative on average.")
    p("  The N=3 live observation does not generalize.")

# ── Save stats ──────────────────────────────────────────────────────────────
stats_path = os.path.join(AUDIT_DIR, "audit_a3_stats.txt")
with open(stats_path, "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"\nSaved: {stats_path}")
