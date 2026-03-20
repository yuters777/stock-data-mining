#!/usr/bin/env python3
"""Audit G1: VIX level vs VIX change as predictors of SPY daily return.

Three OLS regressions:
  (a) SPY_ret ~ VIX_level
  (b) SPY_ret ~ VIX_change
  (c) SPY_ret ~ VIX_level + VIX_change
Claim: VIX change predicts returns better than VIX level.
"""

import csv
import os
import sys
import numpy as np
from datetime import datetime
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(SCRIPT_DIR, "..", "..")
OUT_PATH = os.path.join(SCRIPT_DIR, "audit_g1_vix_regression.txt")

# Redirect stdout to both console and file
class Tee:
    def __init__(self, *files):
        self.files = files
    def write(self, s):
        for f in self.files:
            f.write(s)
    def flush(self):
        for f in self.files:
            f.flush()

outfile = open(OUT_PATH, "w")
tee = Tee(sys.stdout, outfile)
_print = print
def print(*args, **kwargs):
    kwargs["file"] = tee
    _print(*args, **kwargs)


# ── Load SPY M5 → daily returns ──────────────────────────────────────────
spy_path = os.path.join(ROOT, "backtest_output", "SPY_m5_regsess.csv")
spy_by_date = defaultdict(list)
with open(spy_path) as f:
    for row in csv.DictReader(f):
        dt = datetime.strptime(row["Datetime"], "%Y-%m-%d %H:%M:%S")
        spy_by_date[dt.strftime("%Y-%m-%d")].append({
            "open": float(row["Open"]),
            "close": float(row["Close"]),
        })

spy_daily = {}
for d, bars in spy_by_date.items():
    if len(bars) >= 10:
        spy_daily[d] = (bars[-1]["close"] - bars[0]["open"]) / bars[0]["open"]

# ── Load VIX ──────────────────────────────────────────────────────────────
vix_path = os.path.join(ROOT, "Fetched_Data", "VIXCLS_FRED_real.csv")
vix_raw = {}
with open(vix_path) as f:
    for row in csv.DictReader(f):
        val = row["VIXCLS"].strip()
        if val == "." or val == "":
            continue
        vix_raw[row["observation_date"]] = float(val)

# Sort VIX dates, compute change
vix_dates = sorted(vix_raw.keys())
vix_level = {}  # VIX[d-1] (prior close)
vix_change = {} # VIX[d] - VIX[d-1]
for i in range(1, len(vix_dates)):
    d_prev = vix_dates[i - 1]
    d_curr = vix_dates[i]
    vix_level[d_curr] = vix_raw[d_prev]
    vix_change[d_curr] = vix_raw[d_curr] - vix_raw[d_prev]

# ── Align dates ───────────────────────────────────────────────────────────
common_dates = sorted(set(spy_daily.keys()) & set(vix_level.keys()) & set(vix_change.keys()))
N = len(common_dates)

y = np.array([spy_daily[d] for d in common_dates])
x_level = np.array([vix_level[d] for d in common_dates])
x_change = np.array([vix_change[d] for d in common_dates])


# ── OLS helpers ───────────────────────────────────────────────────────────
def ols(X, y):
    """OLS regression. X should include intercept column. Returns dict."""
    n, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    y_hat = X @ beta
    resid = y - y_hat
    SSR = resid @ resid
    SST = np.sum((y - np.mean(y)) ** 2)
    R2 = 1 - SSR / SST
    R2_adj = 1 - (1 - R2) * (n - 1) / (n - k)
    s2 = SSR / (n - k)
    se = np.sqrt(np.diag(s2 * XtX_inv))
    t_stat = beta / se
    # p-values from t-distribution (approximate with normal for large n)
    from math import erfc, sqrt
    p_vals = np.array([erfc(abs(t) / sqrt(2)) for t in t_stat])
    F = ((SST - SSR) / (k - 1)) / (SSR / (n - k)) if k > 1 else (SST - SSR) / (SSR / (n - 1))
    F_p = erfc(abs(F) / sqrt(2))  # rough approximation
    return {
        "beta": beta, "se": se, "t": t_stat, "p": p_vals,
        "R2": R2, "R2_adj": R2_adj, "F": F,
        "n": n, "k": k, "SSR": SSR, "SST": SST,
        "y_hat": y_hat, "resid": resid, "s2": s2,
    }


def print_regression(title, result, var_names):
    print(f"\n{'='*75}")
    print(f"  {title}")
    print(f"{'='*75}")
    print(f"  Dep. variable: SPY_daily_return")
    print(f"  Observations:  {result['n']}")
    print(f"  R²:            {result['R2']:.6f}")
    print(f"  Adj R²:        {result['R2_adj']:.6f}")
    print(f"  F-statistic:   {result['F']:.4f}")
    print(f"  Residual SE:   {np.sqrt(result['s2']):.6f}")
    print()
    print(f"  {'Variable':<18} {'Coeff':>12} {'Std Err':>12} {'t-stat':>10} {'p-value':>12} {'Sig':>5}")
    print(f"  {'-'*72}")
    for i, name in enumerate(var_names):
        sig = ""
        if result["p"][i] < 0.001:
            sig = "***"
        elif result["p"][i] < 0.01:
            sig = "**"
        elif result["p"][i] < 0.05:
            sig = "*"
        print(f"  {name:<18} {result['beta'][i]:>12.6f} {result['se'][i]:>12.6f} "
              f"{result['t'][i]:>10.3f} {result['p'][i]:>12.6f} {sig:>5}")
    print()


def partial_corr(X_full, y, j):
    """Partial correlation of X_full[:,j] with y, controlling for other predictors."""
    # Indices of other columns
    others = [i for i in range(X_full.shape[1]) if i != j]
    X_other = X_full[:, others]
    # Residualize y on others
    XtX_inv = np.linalg.inv(X_other.T @ X_other)
    y_resid = y - X_other @ (XtX_inv @ (X_other.T @ y))
    # Residualize X_j on others
    xj = X_full[:, j]
    xj_resid = xj - X_other @ (XtX_inv @ (X_other.T @ xj))
    # Correlation of residuals
    r = np.corrcoef(y_resid, xj_resid)[0, 1]
    return r


# ── Print header ──────────────────────────────────────────────────────────
print("=" * 75)
print("  AUDIT G1: VIX REGRESSION ANALYSIS")
print("  SPY daily return ~ VIX level, VIX change")
print("=" * 75)
print(f"\n  Date range: {common_dates[0]} to {common_dates[-1]}")
print(f"  N observations: {N}")
print(f"\n  Descriptive statistics:")
print(f"  {'Variable':<18} {'Mean':>12} {'Std':>12} {'Min':>12} {'Max':>12}")
print(f"  {'-'*60}")
for name, arr in [("SPY_ret", y), ("VIX_level", x_level), ("VIX_change", x_change)]:
    print(f"  {name:<18} {np.mean(arr):>12.5f} {np.std(arr):>12.5f} "
          f"{np.min(arr):>12.5f} {np.max(arr):>12.5f}")

# Simple correlations
print(f"\n  Correlation matrix:")
corr_mat = np.corrcoef(np.vstack([y, x_level, x_change]))
labels = ["SPY_ret", "VIX_level", "VIX_change"]
print(f"  {'':>14}", end="")
for l in labels:
    print(f" {l:>12}", end="")
print()
for i, l in enumerate(labels):
    print(f"  {l:>14}", end="")
    for j in range(3):
        print(f" {corr_mat[i,j]:>12.4f}", end="")
    print()

# ── Regression (a): SPY_ret ~ VIX_level ──────────────────────────────────
ones = np.ones(N)
X_a = np.column_stack([ones, x_level])
res_a = ols(X_a, y)
print_regression("Model (a): SPY_ret ~ VIX_level", res_a, ["intercept", "VIX_level"])

# ── Regression (b): SPY_ret ~ VIX_change ─────────────────────────────────
X_b = np.column_stack([ones, x_change])
res_b = ols(X_b, y)
print_regression("Model (b): SPY_ret ~ VIX_change", res_b, ["intercept", "VIX_change"])

# ── Regression (c): SPY_ret ~ VIX_level + VIX_change ─────────────────────
X_c = np.column_stack([ones, x_level, x_change])
res_c = ols(X_c, y)
print_regression("Model (c): SPY_ret ~ VIX_level + VIX_change", res_c,
                 ["intercept", "VIX_level", "VIX_change"])

# Partial correlations for model (c)
pcorr_level = partial_corr(X_c, y, 1)
pcorr_change = partial_corr(X_c, y, 2)
print(f"  Partial correlations (model c):")
print(f"    VIX_level  | controlling for VIX_change: {pcorr_level:>+.5f}")
print(f"    VIX_change | controlling for VIX_level:  {pcorr_change:>+.5f}")

# Standardized betas
std_y = np.std(y)
std_level = np.std(x_level)
std_change = np.std(x_change)
print(f"\n  Standardized betas (model c):")
print(f"    VIX_level:  {res_c['beta'][1] * std_level / std_y:>+.5f}")
print(f"    VIX_change: {res_c['beta'][2] * std_change / std_y:>+.5f}")

# ── Incremental R² ───────────────────────────────────────────────────────
print(f"\n{'='*75}")
print(f"  R² COMPARISON")
print(f"{'='*75}")
print(f"  Model (a) VIX_level only:           R² = {res_a['R2']:.6f}")
print(f"  Model (b) VIX_change only:          R² = {res_b['R2']:.6f}")
print(f"  Model (c) VIX_level + VIX_change:   R² = {res_c['R2']:.6f}")
print()
print(f"  Incremental R² of adding VIX_change to VIX_level: "
      f"{res_c['R2'] - res_a['R2']:.6f}")
print(f"  Incremental R² of adding VIX_level to VIX_change: "
      f"{res_c['R2'] - res_b['R2']:.6f}")
print()

# R² ratio
ratio = res_b["R2"] / res_a["R2"] if res_a["R2"] > 0 else float("inf")
print(f"  R² ratio (change / level): {ratio:.2f}x")

# ── Claim assessment ─────────────────────────────────────────────────────
print(f"\n{'='*75}")
print(f"  CLAIM ASSESSMENT")
print(f"{'='*75}")
print(f"\n  Claim: VIX change predicts returns better than VIX level")
print(f"         (Override philosophy: direction of change > absolute level)")
print()

if res_b["R2"] > res_a["R2"]:
    print(f"  → CONFIRMED: VIX_change R² ({res_b['R2']:.6f}) > VIX_level R² ({res_a['R2']:.6f})")
    print(f"    VIX_change explains {ratio:.1f}x more variance than VIX_level")
else:
    print(f"  → NOT CONFIRMED: VIX_level R² ({res_a['R2']:.6f}) >= VIX_change R² ({res_b['R2']:.6f})")

if abs(res_b["t"][1]) > abs(res_a["t"][1]):
    print(f"  → VIX_change t-stat ({res_b['t'][1]:.3f}) stronger than "
          f"VIX_level t-stat ({res_a['t'][1]:.3f})")

if abs(pcorr_change) > abs(pcorr_level):
    print(f"  → Partial corr of VIX_change ({pcorr_change:+.4f}) > "
          f"VIX_level ({pcorr_level:+.4f}) in combined model")

# Sign check
print(f"\n  Economic interpretation:")
print(f"    VIX_level beta (model a):  {res_a['beta'][1]:+.6f} → "
      f"{'higher VIX = lower return' if res_a['beta'][1] < 0 else 'higher VIX = higher return'}")
print(f"    VIX_change beta (model b): {res_b['beta'][1]:+.6f} → "
      f"{'VIX spike = lower return' if res_b['beta'][1] < 0 else 'VIX spike = higher return'}")
print(f"    Combined model: both effects "
      f"{'reinforce' if (res_c['beta'][1] < 0 and res_c['beta'][2] < 0) else 'differ in direction'}")

outfile.close()
_print(f"\nSaved: {OUT_PATH}")
