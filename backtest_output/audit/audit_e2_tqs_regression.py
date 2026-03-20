#!/usr/bin/env python3
"""Audit E2: OLS regression of TQS component scores on forward M5 returns.

Scores:
  DMI_score   = min(adx14 / 50, 1.0)
  RSI_score   = abs(rsi14 - 50) / 50
  Squeeze_score = squeeze_on (binary)

Forward return = Close[i+12] / Close[i] - 1  (12 bars = 60 min on M5)
  Skip rows with <12 bars remaining in the same trading day.

Volume excluded (single-exchange data quality issue).
Structure & CandlePA untestable on raw M5 data.

Framework weights for comparison:
  DMI=0.35, RSI=0.15, Squeeze=0.15
  (Volume=0.10, Structure=0.15, CandlePA=0.10 — not tested)
"""

import csv
import os
import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IND_DIR = os.path.join(SCRIPT_DIR, "indicators")
TICKERS = ["NVDA", "TSLA", "GOOGL", "IBIT", "GS"]
FWD_BARS = 12


def load_indicators(ticker):
    fpath = os.path.join(IND_DIR, f"indicators_{ticker}.csv")
    rows = []
    with open(fpath) as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


# ── Collect pooled data ─────────────────────────────────────────────────────

dmi_all, rsi_all, sqz_all, fret_all = [], [], [], []
ticker_counts = {}

for ticker in TICKERS:
    rows = load_indicators(ticker)
    n = len(rows)
    count = 0

    # Group by date for same-day forward return check
    for i in range(n):
        r = rows[i]
        # Skip rows with missing indicators
        if r["adx14"] == "" or r["rsi14"] == "" or r["squeeze_on"] == "":
            continue

        # Check 12 bars ahead exist and are same date
        if i + FWD_BARS >= n:
            continue
        date_i = r["Datetime"][:10]
        date_fwd = rows[i + FWD_BARS]["Datetime"][:10]
        if date_i != date_fwd:
            continue

        close_i = float(r["Close"])
        close_fwd = float(rows[i + FWD_BARS]["Close"])
        if close_i <= 0:
            continue

        adx = float(r["adx14"])
        rsi = float(r["rsi14"])
        sqz = int(r["squeeze_on"])

        dmi_score = min(adx / 50.0, 1.0)
        rsi_score = abs(rsi - 50.0) / 50.0
        sqz_score = float(sqz)
        fwd_ret = close_fwd / close_i - 1.0

        dmi_all.append(dmi_score)
        rsi_all.append(rsi_score)
        sqz_all.append(sqz_score)
        fret_all.append(fwd_ret)
        count += 1

    ticker_counts[ticker] = count

X_dmi = np.array(dmi_all)
X_rsi = np.array(rsi_all)
X_sqz = np.array(sqz_all)
Y = np.array(fret_all)
N = len(Y)

# ── OLS regression ──────────────────────────────────────────────────────────
# Y = b0 + b1*DMI + b2*RSI + b3*Squeeze + eps

X = np.column_stack([np.ones(N), X_dmi, X_rsi, X_sqz])
# Normal equations: beta = (X'X)^-1 X'Y
XtX = X.T @ X
XtY = X.T @ Y
beta = np.linalg.solve(XtX, XtY)

Y_hat = X @ beta
residuals = Y - Y_hat
SS_res = np.sum(residuals ** 2)
SS_tot = np.sum((Y - np.mean(Y)) ** 2)
R2 = 1.0 - SS_res / SS_tot
adj_R2 = 1.0 - (1.0 - R2) * (N - 1) / (N - X.shape[1])

# Standard errors
k = X.shape[1]
sigma2 = SS_res / (N - k)
cov_beta = sigma2 * np.linalg.inv(XtX)
se = np.sqrt(np.diag(cov_beta))
t_stats = beta / se

# p-values (two-tailed, using normal approx for large N)
from math import erfc, sqrt
def p_from_t(t, df):
    # For large df, use normal approximation
    return erfc(abs(t) / sqrt(2))

p_values = [p_from_t(t, N - k) for t in t_stats]

# Standardized betas (for predictors only, not intercept)
std_X = np.std(X[:, 1:], axis=0)
std_Y = np.std(Y)
std_betas = beta[1:] * std_X / std_Y if std_Y > 0 else beta[1:] * 0

# ── Use absolute value of forward return for "magnitude of move" regression ──
Y_abs = np.abs(Y)
XtY_abs = X.T @ Y_abs
beta_abs = np.linalg.solve(XtX, XtY_abs)
Y_hat_abs = X @ beta_abs
SS_res_abs = np.sum((Y_abs - Y_hat_abs) ** 2)
SS_tot_abs = np.sum((Y_abs - np.mean(Y_abs)) ** 2)
R2_abs = 1.0 - SS_res_abs / SS_tot_abs

sigma2_abs = SS_res_abs / (N - k)
cov_beta_abs = sigma2_abs * np.linalg.inv(XtX)
se_abs = np.sqrt(np.diag(cov_beta_abs))
t_abs = beta_abs / se_abs
p_abs = [p_from_t(t, N - k) for t in t_abs]
std_betas_abs = beta_abs[1:] * std_X / np.std(Y_abs) if np.std(Y_abs) > 0 else beta_abs[1:] * 0

# ── Output ──────────────────────────────────────────────────────────────────

lines = []


def p(line=""):
    print(line)
    lines.append(line)


p("=" * 80)
p("AUDIT E2: TQS COMPONENT REGRESSION ON FORWARD M5 RETURNS")
p("=" * 80)
p(f"Forward return: Close[i+12]/Close[i] - 1  (12 bars = 60 min)")
p(f"Same-day only. Volume excluded (single-exchange data quality).")
p()
p("DATA SUMMARY:")
p(f"  Total obs:  {N:,}")
for t in TICKERS:
    p(f"    {t:<8}: {ticker_counts[t]:>8,}")
p()
p(f"  Y (fwd_ret):   mean={np.mean(Y)*1e4:.2f} bps  std={np.std(Y)*1e4:.2f} bps")
p(f"  DMI_score:     mean={np.mean(X_dmi):.3f}  std={np.std(X_dmi):.3f}")
p(f"  RSI_score:     mean={np.mean(X_rsi):.3f}  std={np.std(X_rsi):.3f}")
p(f"  Squeeze_score: mean={np.mean(X_sqz):.3f}  std={np.std(X_sqz):.3f}")
p()

# Correlation matrix
p("CORRELATION MATRIX:")
corr_labels = ["fwd_ret", "DMI", "RSI", "Squeeze"]
data_cols = [Y, X_dmi, X_rsi, X_sqz]
p(f"  {'':>10} {'fwd_ret':>10} {'DMI':>10} {'RSI':>10} {'Squeeze':>10}")
for i, lab in enumerate(corr_labels):
    row_str = f"  {lab:>10}"
    for j in range(len(corr_labels)):
        r = np.corrcoef(data_cols[i], data_cols[j])[0, 1]
        row_str += f" {r:>10.4f}"
    p(row_str)
p()

# Regression 1: signed returns
p("─" * 80)
p("REGRESSION 1: fwd_ret ~ DMI_score + RSI_score + Squeeze_score")
p("─" * 80)
p(f"  R²       = {R2:.6f}")
p(f"  Adj R²   = {adj_R2:.6f}")
p(f"  N        = {N:,}")
p(f"  σ(resid) = {np.sqrt(sigma2)*1e4:.2f} bps")
p()
p(f"  {'Variable':<14} {'Coef':>12} {'Std Err':>12} {'t-stat':>10} {'p-value':>12} {'Std Beta':>10}")
p(f"  {'-'*70}")
var_names = ["(intercept)", "DMI_score", "RSI_score", "Squeeze_score"]
for i, name in enumerate(var_names):
    sb = f"{std_betas[i-1]:.4f}" if i > 0 else "—"
    sig = ""
    if p_values[i] < 0.001:
        sig = " ***"
    elif p_values[i] < 0.01:
        sig = " **"
    elif p_values[i] < 0.05:
        sig = " *"
    p(f"  {name:<14} {beta[i]:>12.6f} {se[i]:>12.6f} {t_stats[i]:>10.2f} {p_values[i]:>12.4e} {sb:>10}{sig}")
p()

# Regression 2: absolute returns
p("─" * 80)
p("REGRESSION 2: |fwd_ret| ~ DMI_score + RSI_score + Squeeze_score")
p("  (Tests whether scores predict MAGNITUDE of move, not direction)")
p("─" * 80)
p(f"  R²       = {R2_abs:.6f}")
p(f"  Adj R²   = {1.0 - (1.0 - R2_abs) * (N - 1) / (N - k):.6f}")
p()
p(f"  {'Variable':<14} {'Coef':>12} {'Std Err':>12} {'t-stat':>10} {'p-value':>12} {'Std Beta':>10}")
p(f"  {'-'*70}")
for i, name in enumerate(var_names):
    sb = f"{std_betas_abs[i-1]:.4f}" if i > 0 else "—"
    sig = ""
    if p_abs[i] < 0.001:
        sig = " ***"
    elif p_abs[i] < 0.01:
        sig = " **"
    elif p_abs[i] < 0.05:
        sig = " *"
    p(f"  {name:<14} {beta_abs[i]:>12.6f} {se_abs[i]:>12.6f} {t_abs[i]:>10.2f} {p_abs[i]:>12.4e} {sb:>10}{sig}")
p()

# ── Framework comparison ────────────────────────────────────────────────────
p("=" * 80)
p("FRAMEWORK WEIGHT COMPARISON")
p("=" * 80)
p()
fw = {"DMI": 0.35, "RSI": 0.15, "Squeeze": 0.15}
# Normalize framework weights to sum to 1 across testable components
fw_total = sum(fw.values())
fw_norm = {k: v / fw_total for k, v in fw.items()}

# Rank by |std_beta| from regression 2 (magnitude prediction)
abs_std = {
    "DMI": abs(std_betas_abs[0]),
    "RSI": abs(std_betas_abs[1]),
    "Squeeze": abs(std_betas_abs[2]),
}
empirical_total = sum(abs_std.values())
emp_norm = {k: v / empirical_total if empirical_total > 0 else 0 for k, v in abs_std.items()}

rank_fw = sorted(fw_norm.keys(), key=lambda k: fw_norm[k], reverse=True)
rank_emp = sorted(emp_norm.keys(), key=lambda k: emp_norm[k], reverse=True)

p(f"  {'Component':<12} {'FW Weight':>10} {'FW Norm':>9} {'FW Rank':>8}   "
  f"{'|Std β|':>10} {'Emp Norm':>9} {'Emp Rank':>9}")
p(f"  {'-'*75}")
for comp in ["DMI", "RSI", "Squeeze"]:
    fw_r = rank_fw.index(comp) + 1
    emp_r = rank_emp.index(comp) + 1
    p(f"  {comp:<12} {fw[comp]:>10.2f} {fw_norm[comp]:>9.3f} {'#'+str(fw_r):>8}   "
      f"{abs_std[comp]:>10.4f} {emp_norm[comp]:>9.3f} {'#'+str(emp_r):>9}")

p()
rank_match = rank_fw == rank_emp
p(f"  Rank order match: {'YES' if rank_match else 'NO'}")
p(f"    Framework rank: {' > '.join(rank_fw)}")
p(f"    Empirical rank: {' > '.join(rank_emp)}")
p()

# DMI dominance check
dmi_is_dominant = rank_emp[0] == "DMI"
p(f"  Is DMI dominant (highest |std β|)? {'YES' if dmi_is_dominant else 'NO'}")
if dmi_is_dominant:
    ratio_2nd = abs_std["DMI"] / abs_std[rank_emp[1]] if abs_std[rank_emp[1]] > 0 else float('inf')
    p(f"  DMI / 2nd-place ratio: {ratio_2nd:.2f}x")
p()

# Significance summary
p("SIGNIFICANCE SUMMARY (|fwd_ret| regression):")
for i, comp in enumerate(["DMI", "RSI", "Squeeze"]):
    pv = p_abs[i + 1]
    if pv < 0.001:
        sig_str = "*** (p < 0.001)"
    elif pv < 0.01:
        sig_str = "**  (p < 0.01)"
    elif pv < 0.05:
        sig_str = "*   (p < 0.05)"
    else:
        sig_str = "ns  (not significant)"
    p(f"  {comp:<12}: {sig_str}")
p()

p("NOTE: R² is expected to be very low for M5 return prediction.")
p("The key question is RELATIVE importance (rank order), not absolute fit.")
p("Volume (0.10 weight), Structure (0.15), CandlePA (0.10) are not testable")
p("on raw M5 data — they account for 0.35 of framework weight.")

# ── Save ────────────────────────────────────────────────────────────────────
out_path = os.path.join(SCRIPT_DIR, "audit_e2_tqs_regression.txt")
with open(out_path, "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"\nSaved: {out_path}")
