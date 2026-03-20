#!/usr/bin/env python3
"""Audit F2: COIN/IBIT divergence + Banks vs VIX analysis.

Part A — COIN divergence from IBIT:
  OLS: COIN_ret ~ IBIT_ret → beta, residual = divergence.
  On divergence days: next-day IBIT return.

Part B — Banks vs VIX:
  Bank_ret = mean(GS, C, JPM, V) daily return.
  Correlate with VIX_change vs VIX_level.
"""

import csv
import os
import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.join(SCRIPT_DIR, "..", "..")
BACKTEST_DIR = os.path.join(SCRIPT_DIR, "..")


# ── Helpers ─────────────────────────────────────────────────────────────────

def load_daily_from_m5(ticker):
    """Aggregate M5 regsess → daily: first open, last close."""
    fpath = os.path.join(BACKTEST_DIR, f"{ticker}_m5_regsess.csv")
    by_date = {}
    with open(fpath) as f:
        for row in csv.DictReader(f):
            date = row["Datetime"][:10]
            if date not in by_date:
                by_date[date] = {"open": float(row["Open"]), "close": float(row["Close"])}
            else:
                by_date[date]["close"] = float(row["Close"])
    # Compute returns
    dates = sorted(by_date.keys())
    daily = {}
    for i in range(len(dates)):
        o = by_date[dates[i]]["open"]
        c = by_date[dates[i]]["close"]
        daily[dates[i]] = {"open": o, "close": c, "ret": (c - o) / o if o != 0 else 0}
    return daily


def ols_simple(x, y):
    """Simple OLS: y = alpha + beta*x. Returns alpha, beta, r_squared."""
    x = np.array(x, dtype=float)
    y = np.array(y, dtype=float)
    n = len(x)
    x_mean = np.mean(x)
    y_mean = np.mean(y)
    ss_xy = np.sum((x - x_mean) * (y - y_mean))
    ss_xx = np.sum((x - x_mean) ** 2)
    beta = ss_xy / ss_xx if ss_xx != 0 else 0
    alpha = y_mean - beta * x_mean
    y_pred = alpha + beta * x
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - y_mean) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot != 0 else 0
    return alpha, beta, r2


# ═══════════════════════════════════════════════════════════════════════════
# PART A: COIN / IBIT DIVERGENCE
# ═══════════════════════════════════════════════════════════════════════════

print("Loading COIN and IBIT daily data from M5...")
coin_daily = load_daily_from_m5("COIN")
ibit_daily = load_daily_from_m5("IBIT")

# Align dates
common_dates = sorted(set(coin_daily.keys()) & set(ibit_daily.keys()))
print(f"  Common dates: {len(common_dates)} ({common_dates[0]} to {common_dates[-1]})")

coin_rets = [coin_daily[d]["ret"] for d in common_dates]
ibit_rets = [ibit_daily[d]["ret"] for d in common_dates]

alpha, beta, r2 = ols_simple(ibit_rets, coin_rets)
print(f"  OLS: COIN_ret = {alpha:.5f} + {beta:.3f} * IBIT_ret  (R²={r2:.3f})")

# Compute divergence
divergence = []
for i, d in enumerate(common_dates):
    div = coin_rets[i] - beta * ibit_rets[i]
    divergence.append(div)

# Next-day IBIT return for divergence buckets
div_rows = []
for i in range(len(common_dates) - 1):
    d = common_dates[i]
    d_next = common_dates[i + 1]
    # Next-day return: close-to-close using daily_returns approach
    ibit_next_ret = ibit_daily[d_next]["ret"]  # intraday return
    # Also compute close-to-close
    ibit_c2c = (ibit_daily[d_next]["close"] - ibit_daily[d]["close"]) / ibit_daily[d]["close"] \
        if ibit_daily[d]["close"] != 0 else 0

    div_rows.append({
        "date": d,
        "coin_ret": coin_rets[i],
        "ibit_ret": ibit_rets[i],
        "divergence": divergence[i],
        "ibit_next_ret": ibit_c2c,
        "next_date": d_next,
    })


def bucket_stats(rows, key="ibit_next_ret"):
    vals = [r[key] for r in rows]
    if not vals:
        return {"n": 0, "mean": 0, "median": 0, "pct_pos": 0}
    arr = np.array(vals)
    return {
        "n": len(arr),
        "mean": np.mean(arr),
        "median": np.median(arr),
        "pct_pos": 100.0 * np.sum(arr > 0) / len(arr),
    }


# Divergence buckets
neg_big = [r for r in div_rows if r["divergence"] < -0.03]
neg_med = [r for r in div_rows if -0.03 <= r["divergence"] < -0.01]
neutral = [r for r in div_rows if -0.01 <= r["divergence"] <= 0.01]
pos_med = [r for r in div_rows if 0.01 < r["divergence"] <= 0.03]
pos_big = [r for r in div_rows if r["divergence"] > 0.03]

all_baseline = bucket_stats(div_rows)

print()
print("=" * 85)
print("AUDIT F2 — PART A: COIN / IBIT DIVERGENCE")
print("=" * 85)
print()
print(f"OLS: COIN_ret = {alpha*100:.3f}% + {beta:.3f} × IBIT_ret  (R²={r2:.3f})")
print(f"Beta={beta:.3f} → COIN moves ~{beta:.1f}x IBIT on average")
print(f"Divergence = COIN_ret − {beta:.3f} × IBIT_ret  (residual)")
print()

buckets = [
    ("div < -3%", neg_big),
    ("-3% ≤ div < -1%", neg_med),
    ("-1% ≤ div ≤ +1%", neutral),
    ("+1% < div ≤ +3%", pos_med),
    ("div > +3%", pos_big),
    ("ALL (baseline)", div_rows),
]

print(f"  {'Divergence Bucket':<22} {'N':>5} {'IBIT Next-Day Mean':>20} {'Median':>10} {'%Pos':>7}")
print(f"  {'-'*70}")
for label, rows in buckets:
    s = bucket_stats(rows)
    print(f"  {label:<22} {s['n']:>5} {s['mean']*100:>19.3f}% {s['median']*100:>9.3f}% {s['pct_pos']:>6.1f}%")

print()

# Signal interpretation
s_neg = bucket_stats(neg_big + neg_med)
s_pos = bucket_stats(pos_big + pos_med)
print(f"  COIN underperforms (div < -1%): N={s_neg['n']}, IBIT next-day={s_neg['mean']*100:+.3f}%")
print(f"  COIN outperforms   (div > +1%): N={s_pos['n']}, IBIT next-day={s_pos['mean']*100:+.3f}%")
print(f"  Baseline:                        N={all_baseline['n']}, IBIT next-day={all_baseline['mean']*100:+.3f}%")
print()
edge_neg = s_neg['mean'] - all_baseline['mean']
edge_pos = s_pos['mean'] - all_baseline['mean']
print(f"  After COIN underperformance: IBIT excess = {edge_neg*100:+.3f}%")
print(f"  After COIN outperformance:   IBIT excess = {edge_pos*100:+.3f}%")

# Save Part A CSV
csv_a_path = os.path.join(SCRIPT_DIR, "audit_f2_coin_div.csv")
with open(csv_a_path, "w", newline="") as f:
    fields = ["date", "coin_ret", "ibit_ret", "divergence", "next_date", "ibit_next_ret"]
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    for r in div_rows:
        writer.writerow({
            "date": r["date"],
            "coin_ret": f"{r['coin_ret']:.6f}",
            "ibit_ret": f"{r['ibit_ret']:.6f}",
            "divergence": f"{r['divergence']:.6f}",
            "next_date": r["next_date"],
            "ibit_next_ret": f"{r['ibit_next_ret']:.6f}",
        })
print(f"\nSaved: {csv_a_path}")


# ═══════════════════════════════════════════════════════════════════════════
# PART B: BANKS vs VIX
# ═══════════════════════════════════════════════════════════════════════════

print()
print("=" * 85)
print("AUDIT F2 — PART B: BANKS vs VIX (direction vs level)")
print("=" * 85)

# Load VIX
vix_data = {}
vix_path = os.path.join(BASE_DIR, "Fetched_Data", "VIXCLS_FRED_real.csv")
with open(vix_path) as f:
    for row in csv.DictReader(f):
        d = row["observation_date"]
        val = row["VIXCLS"]
        if val and val != ".":
            vix_data[d] = float(val)

vix_dates = sorted(vix_data.keys())
print(f"\nVIX data: {len(vix_dates)} observations ({vix_dates[0]} to {vix_dates[-1]})")

# Load bank tickers from M5
bank_tickers = ["GS", "C", "JPM", "V"]
bank_daily = {}
for t in bank_tickers:
    bank_daily[t] = load_daily_from_m5(t)

# Compute mean bank return per date
all_bank_dates = set(bank_daily[bank_tickers[0]].keys())
for t in bank_tickers[1:]:
    all_bank_dates &= set(bank_daily[t].keys())
all_bank_dates = sorted(all_bank_dates)

bank_ret_by_date = {}
for d in all_bank_dates:
    rets = [bank_daily[t][d]["ret"] for t in bank_tickers]
    bank_ret_by_date[d] = np.mean(rets)

# Align: need VIX[d-1] and VIX[d], and bank_ret[d]
aligned = []
for i in range(1, len(vix_dates)):
    d = vix_dates[i]
    d_prev = vix_dates[i - 1]
    if d in bank_ret_by_date:
        aligned.append({
            "date": d,
            "bank_ret": bank_ret_by_date[d],
            "vix_level": vix_data[d_prev],
            "vix_change": vix_data[d] - vix_data[d_prev],
            "vix_today": vix_data[d],
        })

print(f"Aligned dates (VIX + banks): {len(aligned)}")

bank_rets = np.array([a["bank_ret"] for a in aligned])
vix_changes = np.array([a["vix_change"] for a in aligned])
vix_levels = np.array([a["vix_level"] for a in aligned])

# Correlations
corr_change = np.corrcoef(bank_rets, vix_changes)[0, 1]
corr_level = np.corrcoef(bank_rets, vix_levels)[0, 1]

# OLS: bank_ret ~ vix_change
a1, b1, r2_1 = ols_simple(vix_changes, bank_rets)
# OLS: bank_ret ~ vix_level
a2, b2, r2_2 = ols_simple(vix_levels, bank_rets)
# OLS: bank_ret ~ vix_change + vix_level (multivariate)
X = np.column_stack([vix_changes, vix_levels, np.ones(len(aligned))])
y = bank_rets
betas_mv = np.linalg.lstsq(X, y, rcond=None)[0]
y_pred_mv = X @ betas_mv
ss_res_mv = np.sum((y - y_pred_mv) ** 2)
ss_tot = np.sum((y - np.mean(y)) ** 2)
r2_mv = 1 - ss_res_mv / ss_tot if ss_tot > 0 else 0

print()
print(f"  {'Predictor':<20} {'Corr':>8} {'Beta':>10} {'R²':>8}")
print(f"  {'-'*50}")
print(f"  {'VIX change (Δ)':<20} {corr_change:>8.4f} {b1*100:>9.4f}% {r2_1:>8.4f}")
print(f"  {'VIX level (prev)':<20} {corr_level:>8.4f} {b2*100:>9.4f}% {r2_2:>8.4f}")
print(f"  {'Both (multivar)':<20} {'':>8} {'':>10} {r2_mv:>8.4f}")
print()

# Claim assessment
print(f"  Claim: VIX direction > VIX level for explaining bank returns")
if abs(corr_change) > abs(corr_level):
    print(f"  → |corr_change|={abs(corr_change):.4f} > |corr_level|={abs(corr_level):.4f}")
    print(f"  → R²_change={r2_1:.4f} vs R²_level={r2_2:.4f}")
    print(f"  → CONFIRMED: VIX direction is a stronger predictor")
else:
    print(f"  → |corr_change|={abs(corr_change):.4f} ≤ |corr_level|={abs(corr_level):.4f}")
    print(f"  → R²_change={r2_1:.4f} vs R²_level={r2_2:.4f}")
    print(f"  → NOT CONFIRMED: VIX level is as strong or stronger")

print()

# VIX change buckets
print("  Bank returns by VIX change bucket:")
vix_buckets = [
    ("VIX drop > 2", lambda a: a["vix_change"] < -2),
    ("VIX drop 1-2", lambda a: -2 <= a["vix_change"] < -1),
    ("VIX drop 0-1", lambda a: -1 <= a["vix_change"] < 0),
    ("VIX rise 0-1", lambda a: 0 <= a["vix_change"] < 1),
    ("VIX rise 1-2", lambda a: 1 <= a["vix_change"] < 2),
    ("VIX rise > 2", lambda a: a["vix_change"] >= 2),
]

print(f"  {'Bucket':<16} {'N':>5} {'Bank Ret Mean':>15} {'Median':>10} {'%Pos':>7}")
print(f"  {'-'*58}")
for label, filt in vix_buckets:
    subset = [a for a in aligned if filt(a)]
    if subset:
        rets = np.array([a["bank_ret"] for a in subset])
        print(f"  {label:<16} {len(rets):>5} {np.mean(rets)*100:>14.3f}% "
              f"{np.median(rets)*100:>9.3f}% {100*np.sum(rets>0)/len(rets):>6.1f}%")
    else:
        print(f"  {label:<16}     0")

print()

# VIX level buckets
print("  Bank returns by VIX level bucket (prior day):")
level_buckets = [
    ("VIX < 15", lambda a: a["vix_level"] < 15),
    ("VIX 15-20", lambda a: 15 <= a["vix_level"] < 20),
    ("VIX 20-25", lambda a: 20 <= a["vix_level"] < 25),
    ("VIX 25-30", lambda a: 25 <= a["vix_level"] < 30),
    ("VIX 30+", lambda a: a["vix_level"] >= 30),
]

print(f"  {'Bucket':<16} {'N':>5} {'Bank Ret Mean':>15} {'Median':>10} {'%Pos':>7}")
print(f"  {'-'*58}")
for label, filt in level_buckets:
    subset = [a for a in aligned if filt(a)]
    if subset:
        rets = np.array([a["bank_ret"] for a in subset])
        print(f"  {label:<16} {len(rets):>5} {np.mean(rets)*100:>14.3f}% "
              f"{np.median(rets)*100:>9.3f}% {100*np.sum(rets>0)/len(rets):>6.1f}%")
    else:
        print(f"  {label:<16}     0")

print()

# Per-bank detail
print("  Per-bank correlation with VIX change:")
print(f"  {'Ticker':<8} {'Corr(Δ)':>10} {'Corr(Lvl)':>12}")
print(f"  {'-'*35}")
for t in bank_tickers:
    t_rets = []
    t_vchg = []
    t_vlvl = []
    for a in aligned:
        if a["date"] in bank_daily[t]:
            t_rets.append(bank_daily[t][a["date"]]["ret"])
            t_vchg.append(a["vix_change"])
            t_vlvl.append(a["vix_level"])
    if len(t_rets) > 2:
        c1 = np.corrcoef(t_rets, t_vchg)[0, 1]
        c2 = np.corrcoef(t_rets, t_vlvl)[0, 1]
        print(f"  {t:<8} {c1:>10.4f} {c2:>12.4f}")

# Save Part B CSV
csv_b_path = os.path.join(SCRIPT_DIR, "audit_f2_banks_vix.csv")
with open(csv_b_path, "w", newline="") as f:
    fields = ["date", "bank_ret", "vix_level", "vix_change", "vix_today",
              "gs_ret", "c_ret", "jpm_ret", "v_ret"]
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    for a in aligned:
        row = {
            "date": a["date"],
            "bank_ret": f"{a['bank_ret']:.6f}",
            "vix_level": f"{a['vix_level']:.2f}",
            "vix_change": f"{a['vix_change']:.2f}",
            "vix_today": f"{a['vix_today']:.2f}",
        }
        for t, col in zip(bank_tickers, ["gs_ret", "c_ret", "jpm_ret", "v_ret"]):
            row[col] = f"{bank_daily[t][a['date']]['ret']:.6f}" if a["date"] in bank_daily[t] else ""
        writer.writerow(row)
print(f"\nSaved: {csv_b_path}")
