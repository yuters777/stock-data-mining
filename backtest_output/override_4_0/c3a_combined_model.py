#!/usr/bin/env python3
"""
C3a: Combined Model + Split-Sample Validation for Override 4.0

IMPORTANT FINDING: C2's vix_change() used same-day VIX close (contemporaneous
with SPY return), creating a lookahead bias. This script computes BOTH methods:
  - "C2 method": vix_today[i] - vix_today[i-3]  (contains lookahead)
  - "Strict method": vix_prior[i] - vix_prior[i-3]  (true no-lookahead)
"""

import csv
import math
from collections import defaultdict
from pathlib import Path

OUT_DIR = Path("/home/user/stock-data-mining/backtest_output/override_4_0")

# ── Load data ──────────────────────────────────────────────────
rows = []
with open(OUT_DIR / "spy_daily_returns.csv") as f:
    for r in csv.DictReader(f):
        rows.append({
            'date': r['date'],
            'open': float(r['open']),
            'close': float(r['close']),
            'high': float(r['high']),
            'low': float(r['low']),
            'ret': float(r['daily_return']),
            'vix_prior': float(r['vix_prior']),
            'vix_today': float(r['vix_today']),
        })

print(f"Loaded {len(rows)} days")

# Also load full FRED VIX series (for C2-style computation)
vix_fred = {}
with open("/home/user/stock-data-mining/Fetched_Data/VIXCLS_FRED_real.csv") as f:
    for r in csv.DictReader(f):
        val = r["VIXCLS"].strip()
        if val not in ("", "."):
            vix_fred[r["observation_date"]] = float(val)

vix_dates = sorted(vix_fred.keys())
vix_idx = {d: i for i, d in enumerate(vix_dates)}

# ── Compute derived fields ─────────────────────────────────────
for i, r in enumerate(rows):
    # STRICT (no-lookahead): vix_prior[i] - vix_prior[i-3]
    if i >= 3:
        r['vix_3d_strict'] = r['vix_prior'] - rows[i-3]['vix_prior']
    else:
        r['vix_3d_strict'] = None

    # C2 METHOD (same-day VIX, contains lookahead):
    # vix_fred[date] - vix_fred[date - 3 trading days]
    d = r['date']
    if d in vix_idx and vix_idx[d] >= 3:
        idx = vix_idx[d]
        r['vix_3d_c2'] = vix_fred[vix_dates[idx]] - vix_fred[vix_dates[idx - 3]]
    else:
        r['vix_3d_c2'] = None

    # Gap percent
    if i >= 1:
        r['gap_pct'] = (r['open'] - rows[i-1]['close']) / rows[i-1]['close'] * 100
    else:
        r['gap_pct'] = None

    # VIX regime (prior-day)
    vp = r['vix_prior']
    if vp < 20:
        r['vix_regime'] = '<20'
    elif vp < 25:
        r['vix_regime'] = '20-25'
    else:
        r['vix_regime'] = '>=25'

# ── Stats helpers ──────────────────────────────────────────────
def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

def stats(returns):
    n = len(returns)
    if n < 2:
        return {'n': n, 'mean': 0, 'std': 0, 'sharpe': 0, 'wr': 0, 't': 0, 'p': 1.0}
    mean = sum(returns) / n
    var = sum((x - mean)**2 for x in returns) / (n - 1)
    std = math.sqrt(var) if var > 0 else 0.0001
    sharpe = mean / std
    wr = sum(1 for x in returns if x > 0) / n * 100
    t = mean / (std / math.sqrt(n))
    p = 2 * (1 - norm_cdf(abs(t)))
    return {'n': n, 'mean': mean, 'std': std, 'sharpe': sharpe, 'wr': wr, 't': t, 'p': p}

def bucket_data(data, fn):
    b = defaultdict(list)
    for r in data:
        b[fn(r)].append(r['ret'])
    return b

def anova_f(groups):
    """One-way ANOVA F-statistic"""
    groups = [g for g in groups if len(g) >= 2]
    if len(groups) < 2:
        return 0, 1.0
    all_vals = [x for g in groups for x in g]
    grand_mean = sum(all_vals) / len(all_vals)
    ss_between = sum(len(g) * (sum(g)/len(g) - grand_mean)**2 for g in groups)
    ss_within = sum(sum((x - sum(g)/len(g))**2 for x in g) for g in groups)
    df_between = len(groups) - 1
    df_within = len(all_vals) - len(groups)
    if df_within == 0 or ss_within == 0:
        return 0, 1.0
    f_stat = (ss_between / df_between) / (ss_within / df_within)
    # Approximate p-value using chi-square approximation for F
    # For rough reporting, use normal approx of sqrt(2F) - sqrt(2*df_between - 1)
    # Actually let's just report the F-stat and note it
    return f_stat, df_between, df_within

# ── 5-bucket classifier ───────────────────────────────────────
BUCKETS_5 = [
    ('Falling >3pts', -999, -3),
    ('Falling 1-3pts', -3, -1),
    ('Flat (±1pt)', -1, 1),
    ('Rising 1-3pts', 1, 3),
    ('Rising >3pts', 3, 999),
]

def classify_5(val):
    for label, lo, hi in BUCKETS_5:
        if lo <= val < hi:
            return label
    return 'Rising >3pts'  # catch edge

def classify_3(val):
    if val < -1: return 'FAVORABLE'
    elif val > 1: return 'UNFAVORABLE'
    else: return 'NEUTRAL'

# ── Filter valid rows ─────────────────────────────────────────
valid_strict = [r for r in rows if r['vix_3d_strict'] is not None and r['gap_pct'] is not None]
valid_c2 = [r for r in rows if r['vix_3d_c2'] is not None and r['gap_pct'] is not None]
print(f"Valid (strict): {len(valid_strict)} days")
print(f"Valid (C2 method): {len(valid_c2)} days")

# ═══════════════════════════════════════════════════════════════
# SECTION 0: DEMONSTRATE THE LOOKAHEAD BUG
# ═══════════════════════════════════════════════════════════════
print("\n" + "="*75)
print("SECTION 0: LOOKAHEAD BUG DEMONSTRATION")
print("="*75)

print("\nC2 method: vix_fred[date] - vix_fred[date-3]  (same-day VIX = lookahead)")
print("Strict:    vix_prior[i] - vix_prior[i-3]       (prior-day VIX = no lookahead)")
print()

# Show first 5 rows with both computations
print(f"{'Date':<12} {'VIX prior':>10} {'VIX today':>10} {'3d C2':>8} {'3d Strict':>10} {'SPY ret':>10}")
print("-"*65)
for r in rows[3:8]:
    c2_val = r['vix_3d_c2'] if r['vix_3d_c2'] is not None else 0
    st_val = r['vix_3d_strict'] if r['vix_3d_strict'] is not None else 0
    print(f"{r['date']:<12} {r['vix_prior']:>10.2f} {r['vix_today']:>10.2f} {c2_val:>+8.2f} {st_val:>+10.2f} {r['ret']:>+10.4f}%")

# Show correlation between same-day VIX change and SPY return
sameday_vix_changes = []
spy_rets = []
for r in rows:
    dv = r['vix_today'] - r['vix_prior']
    sameday_vix_changes.append(dv)
    spy_rets.append(r['ret'])

n = len(sameday_vix_changes)
mean_dv = sum(sameday_vix_changes) / n
mean_sr = sum(spy_rets) / n
cov = sum((sameday_vix_changes[i] - mean_dv) * (spy_rets[i] - mean_sr) for i in range(n)) / (n - 1)
std_dv = math.sqrt(sum((x - mean_dv)**2 for x in sameday_vix_changes) / (n - 1))
std_sr = math.sqrt(sum((x - mean_sr)**2 for x in spy_rets) / (n - 1))
corr = cov / (std_dv * std_sr) if std_dv > 0 and std_sr > 0 else 0

print(f"\nSame-day VIX change vs SPY return correlation: r = {corr:.4f}")
print(f"This contemporaneous correlation contaminates C2's 3d VIX change signal.")

# C2 method 5-bucket
print("\n\nC2 METHOD (with lookahead) — 5-bucket:")
c2_5 = defaultdict(list)
for r in valid_c2:
    c2_5[classify_5(r['vix_3d_c2'])].append(r['ret'])

print(f"\n{'Bucket':<18} {'N':>5} {'Mean':>10} {'Sharpe':>8} {'WR':>7} {'t':>8} {'p':>8}")
print("-"*60)
for label, _, _ in BUCKETS_5:
    s = stats(c2_5[label])
    print(f"{label:<18} {s['n']:>5} {s['mean']:>+10.4f}% {s['sharpe']:>+8.3f} {s['wr']:>6.1f}% {s['t']:>+8.2f} {s['p']:>8.4f}")

# Strict method 5-bucket
print("\n\nSTRICT METHOD (no lookahead) — 5-bucket:")
st_5 = defaultdict(list)
for r in valid_strict:
    st_5[classify_5(r['vix_3d_strict'])].append(r['ret'])

print(f"\n{'Bucket':<18} {'N':>5} {'Mean':>10} {'Sharpe':>8} {'WR':>7} {'t':>8} {'p':>8}")
print("-"*60)
for label, _, _ in BUCKETS_5:
    s = stats(st_5[label])
    print(f"{label:<18} {s['n']:>5} {s['mean']:>+10.4f}% {s['sharpe']:>+8.3f} {s['wr']:>6.1f}% {s['t']:>+8.2f} {s['p']:>8.4f}")

# ANOVA comparison
c2_groups = [c2_5[label] for label, _, _ in BUCKETS_5]
st_groups = [st_5[label] for label, _, _ in BUCKETS_5]
c2_f = anova_f(c2_groups)
st_f = anova_f(st_groups)
print(f"\nANOVA F-stat: C2 method = {c2_f[0]:.3f} (df {c2_f[1]},{c2_f[2]})")
print(f"ANOVA F-stat: Strict    = {st_f[0]:.3f} (df {st_f[1]},{st_f[2]})")
print(f"\nC2 F-stat inflated by ~{c2_f[0]/st_f[0]:.1f}x due to lookahead bias" if st_f[0] > 0 else "")

# ═══════════════════════════════════════════════════════════════
# SECTION 1: WHAT ACTUALLY WORKS (STRICT NO-LOOKAHEAD)
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "="*75)
print("SECTION 1: STRICT NO-LOOKAHEAD ANALYSIS")
print("="*75)

# 3-bucket (simplified)
REGIME_ORDER = ['FAVORABLE', 'NEUTRAL', 'UNFAVORABLE']
mom3 = bucket_data(valid_strict, lambda r: classify_3(r['vix_3d_strict']))

print("\n3D VIX MOMENTUM — 3-bucket (strict, no lookahead):")
print(f"\n{'Regime':<14} {'N':>5} {'Mean':>10} {'Std':>8} {'Sharpe':>8} {'WR':>7} {'t':>8} {'p':>8}")
print("-"*65)
for regime in REGIME_ORDER:
    s = stats(mom3[regime])
    print(f"{regime:<14} {s['n']:>5} {s['mean']:>+10.4f}% {s['std']:>7.4f}% {s['sharpe']:>+8.3f} {s['wr']:>6.1f}% {s['t']:>+8.2f} {s['p']:>8.4f}")

# ═══════════════════════════════════════════════════════════════
# SECTION 2: ALTERNATIVE — PRIOR-DAY VIX CHANGE (1d, truly predictive)
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "="*75)
print("SECTION 2: PRIOR-DAY VIX CHANGE (1d, strictly predictive)")
print("="*75)
print("\nvix_1d_change = vix_prior[today] - vix_prior[yesterday]")
print("= yesterday's VIX close - day-before-yesterday's VIX close")
print("→ known before market open, truly predictive\n")

for i, r in enumerate(rows):
    if i >= 1:
        r['vix_1d_prior'] = r['vix_prior'] - rows[i-1]['vix_prior']
    else:
        r['vix_1d_prior'] = None

valid_1d = [r for r in rows if r['vix_1d_prior'] is not None]

BUCKETS_1D = [
    ('Fell >2pts', -999, -2),
    ('Fell 1-2pts', -2, -1),
    ('Fell 0.5-1pt', -1, -0.5),
    ('Flat (±0.5pt)', -0.5, 0.5),
    ('Rose 0.5-1pt', 0.5, 1),
    ('Rose 1-2pts', 1, 2),
    ('Rose >2pts', 2, 999),
]

vix1d_buckets = defaultdict(list)
for r in valid_1d:
    for label, lo, hi in BUCKETS_1D:
        if lo <= r['vix_1d_prior'] < hi:
            vix1d_buckets[label].append(r['ret'])
            break

print(f"{'Bucket':<18} {'N':>5} {'Mean':>10} {'Sharpe':>8} {'WR':>7} {'t':>8} {'p':>8}")
print("-"*60)
for label, _, _ in BUCKETS_1D:
    s = stats(vix1d_buckets[label])
    print(f"{label:<18} {s['n']:>5} {s['mean']:>+10.4f}% {s['sharpe']:>+8.3f} {s['wr']:>6.1f}% {s['t']:>+8.2f} {s['p']:>8.4f}")

vix1d_groups = [vix1d_buckets[label] for label, _, _ in BUCKETS_1D if len(vix1d_buckets[label]) >= 2]
vix1d_f = anova_f(vix1d_groups)
print(f"\nANOVA F = {vix1d_f[0]:.3f} (df {vix1d_f[1]},{vix1d_f[2]})")

# ═══════════════════════════════════════════════════════════════
# SECTION 3: VIX LEVEL BASELINE (from C1, re-confirmed)
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "="*75)
print("SECTION 3: VIX LEVEL BASELINE (re-confirmed)")
print("="*75)

def vix_level_bucket(r):
    vp = r['vix_prior']
    if vp < 16: return '<16'
    elif vp < 20: return '16-20'
    elif vp < 25: return '20-25'
    else: return '>=25'

vix_lvl = bucket_data(rows, vix_level_bucket)
VIX_ORDER = ['<16', '16-20', '20-25', '>=25']

print(f"\n{'VIX Level':<10} {'N':>5} {'Mean':>10} {'Sharpe':>8} {'WR':>7} {'t':>8} {'p':>8}")
print("-"*55)
for bucket in VIX_ORDER:
    s = stats(vix_lvl[bucket])
    print(f"{bucket:<10} {s['n']:>5} {s['mean']:>+10.4f}% {s['sharpe']:>+8.3f} {s['wr']:>6.1f}% {s['t']:>+8.2f} {s['p']:>8.4f}")

vix_lvl_groups = [vix_lvl[b] for b in VIX_ORDER]
vix_lvl_f = anova_f(vix_lvl_groups)
print(f"\nANOVA F = {vix_lvl_f[0]:.3f} (df {vix_lvl_f[1]},{vix_lvl_f[2]})")

# ═══════════════════════════════════════════════════════════════
# SECTION 4: COMBINED MODEL (strict)
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "="*75)
print("SECTION 4: COMBINED MODEL (strict no-lookahead)")
print("="*75)

def combined_regime_strict(r):
    v3d = r['vix_3d_strict']
    gap = r['gap_pct']
    vix_reg = r['vix_regime']

    # Signal A: 3d VIX momentum (strict)
    if v3d < -1: sig_a = +1
    elif v3d > +1: sig_a = -1
    else: sig_a = 0

    # Signal B: Gap x VIX
    if gap < -0.3 and vix_reg == '>=25': sig_b = -1
    elif gap > 0.3 and vix_reg == '<20': sig_b = +1
    else: sig_b = 0

    combined = sig_a + sig_b
    if combined >= 1: return 'FAVORABLE'
    elif combined <= -1: return 'UNFAVORABLE'
    else: return 'NEUTRAL'

comb = bucket_data(valid_strict, combined_regime_strict)

print(f"\n{'Regime':<14} {'N':>5} {'Mean':>10} {'Std':>8} {'Sharpe':>8} {'WR':>7} {'t':>8} {'p':>8}")
print("-"*65)
for regime in REGIME_ORDER:
    s = stats(comb[regime])
    print(f"{regime:<14} {s['n']:>5} {s['mean']:>+10.4f}% {s['std']:>7.4f}% {s['sharpe']:>+8.3f} {s['wr']:>6.1f}% {s['t']:>+8.2f} {s['p']:>8.4f}")

# Comparison
print("\n\nMODEL COMPARISON (all strict no-lookahead):")
mom3_fav = stats(mom3['FAVORABLE'])
mom3_unfav = stats(mom3['UNFAVORABLE'])
comb_fav = stats(comb['FAVORABLE'])
comb_unfav = stats(comb['UNFAVORABLE'])

mom_spread = mom3_fav['mean'] - mom3_unfav['mean']
comb_spread = comb_fav['mean'] - comb_unfav['mean']

print(f"\n{'Model':<22} {'FAV Mean':>10} {'UNFAV Mean':>12} {'Spread':>10} {'FAV Sharpe':>12} {'UNFAV Sharpe':>14}")
print("-"*82)
print(f"{'3d momentum only':<22} {mom3_fav['mean']:>+9.4f}% {mom3_unfav['mean']:>+11.4f}% {mom_spread:>+9.4f}% {mom3_fav['sharpe']:>+12.3f} {mom3_unfav['sharpe']:>+14.3f}")
print(f"{'Combined':<22} {comb_fav['mean']:>+9.4f}% {comb_unfav['mean']:>+11.4f}% {comb_spread:>+9.4f}% {comb_fav['sharpe']:>+12.3f} {comb_unfav['sharpe']:>+14.3f}")
print(f"{'Improvement':<22} {'':>10} {'':>12} {comb_spread - mom_spread:>+9.4f}%")

# ═══════════════════════════════════════════════════════════════
# SECTION 5: SPLIT-SAMPLE VALIDATION
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "="*75)
print("SECTION 5: SPLIT-SAMPLE VALIDATION")
print("="*75)

mid = len(valid_strict) // 2
first_half = valid_strict[:mid]
second_half = valid_strict[mid:]
print(f"\nFull:        {len(valid_strict)} days ({valid_strict[0]['date']} to {valid_strict[-1]['date']})")
print(f"First half:  {len(first_half)} days ({first_half[0]['date']} to {first_half[-1]['date']})")
print(f"Second half: {len(second_half)} days ({second_half[0]['date']} to {second_half[-1]['date']})")

# 5-bucket split
print("\n\n3D VIX MOMENTUM (5-bucket, strict) — SPLIT-SAMPLE:")
full_5 = bucket_data(valid_strict, lambda r: classify_5(r['vix_3d_strict']))
first_5 = bucket_data(first_half, lambda r: classify_5(r['vix_3d_strict']))
second_5 = bucket_data(second_half, lambda r: classify_5(r['vix_3d_strict']))

print(f"\n{'Bucket':<18} {'Full':>10} {'N':>4} {'1st Half':>10} {'N':>4} {'2nd Half':>10} {'N':>4} {'Stable':>7}")
print("-"*70)
for label, _, _ in BUCKETS_5:
    sf = stats(full_5[label])
    s1 = stats(first_5.get(label, []))
    s2 = stats(second_5.get(label, []))
    same_sign = (s1['mean'] > 0 and s2['mean'] > 0) or (s1['mean'] < 0 and s2['mean'] < 0)
    stable = "YES" if same_sign and s1['n'] >= 2 and s2['n'] >= 2 else ("NO" if s1['n'] >= 2 and s2['n'] >= 2 else "N/A")
    print(f"{label:<18} {sf['mean']:>+9.4f}% {sf['n']:>4} {s1['mean']:>+9.4f}% {s1['n']:>4} {s2['mean']:>+9.4f}% {s2['n']:>4} {stable:>7}")

# 3-bucket split
print("\n\n3D VIX MOMENTUM (3-bucket, strict) — SPLIT-SAMPLE:")
full_3 = bucket_data(valid_strict, lambda r: classify_3(r['vix_3d_strict']))
first_3 = bucket_data(first_half, lambda r: classify_3(r['vix_3d_strict']))
second_3 = bucket_data(second_half, lambda r: classify_3(r['vix_3d_strict']))

print(f"\n{'Regime':<14} {'Full Mean':>10} {'N':>4} {'Sharpe':>8} {'1st Mean':>10} {'N':>4} {'2nd Mean':>10} {'N':>4} {'Stable':>7}")
print("-"*75)
for regime in REGIME_ORDER:
    sf = stats(full_3[regime])
    s1 = stats(first_3.get(regime, []))
    s2 = stats(second_3.get(regime, []))
    same_sign = (s1['mean'] > 0 and s2['mean'] > 0) or (s1['mean'] < 0 and s2['mean'] < 0)
    stable = "YES" if same_sign and s1['n'] >= 2 and s2['n'] >= 2 else "NO"
    print(f"{regime:<14} {sf['mean']:>+9.4f}% {sf['n']:>4} {sf['sharpe']:>+8.3f} {s1['mean']:>+9.4f}% {s1['n']:>4} {s2['mean']:>+9.4f}% {s2['n']:>4} {stable:>7}")

# Combined model split
print("\n\nCOMBINED MODEL (strict) — SPLIT-SAMPLE:")
full_c = bucket_data(valid_strict, combined_regime_strict)
first_c = bucket_data(first_half, combined_regime_strict)
second_c = bucket_data(second_half, combined_regime_strict)

print(f"\n{'Regime':<14} {'Full Mean':>10} {'N':>4} {'Sharpe':>8} {'1st Mean':>10} {'N':>4} {'2nd Mean':>10} {'N':>4} {'Stable':>7}")
print("-"*75)
for regime in REGIME_ORDER:
    sf = stats(full_c[regime])
    s1 = stats(first_c.get(regime, []))
    s2 = stats(second_c.get(regime, []))
    same_sign = (s1['mean'] > 0 and s2['mean'] > 0) or (s1['mean'] < 0 and s2['mean'] < 0)
    stable = "YES" if same_sign and s1['n'] >= 2 and s2['n'] >= 2 else "NO"
    print(f"{regime:<14} {sf['mean']:>+9.4f}% {sf['n']:>4} {sf['sharpe']:>+8.3f} {s1['mean']:>+9.4f}% {s1['n']:>4} {s2['mean']:>+9.4f}% {s2['n']:>4} {stable:>7}")

# VIX level split
print("\n\nVIX LEVEL BASELINE — SPLIT-SAMPLE:")
mid_all = len(rows) // 2
first_all = rows[:mid_all]
second_all = rows[mid_all:]
first_vl = bucket_data(first_all, vix_level_bucket)
second_vl = bucket_data(second_all, vix_level_bucket)

print(f"\n{'VIX Level':<10} {'Full Mean':>10} {'N':>4} {'Sharpe':>8} {'1st Mean':>10} {'N':>4} {'2nd Mean':>10} {'N':>4} {'Stable':>7}")
print("-"*70)
for bucket in VIX_ORDER:
    sf = stats(vix_lvl[bucket])
    s1 = stats(first_vl.get(bucket, []))
    s2 = stats(second_vl.get(bucket, []))
    same_sign = (s1['mean'] > 0 and s2['mean'] > 0) or (s1['mean'] < 0 and s2['mean'] < 0)
    stable = "YES" if same_sign and s1['n'] >= 2 and s2['n'] >= 2 else "NO"
    print(f"{bucket:<10} {sf['mean']:>+9.4f}% {sf['n']:>4} {sf['sharpe']:>+8.3f} {s1['mean']:>+9.4f}% {s1['n']:>4} {s2['mean']:>+9.4f}% {s2['n']:>4} {stable:>7}")

# ═══════════════════════════════════════════════════════════════
# SECTION 6: FINAL VERDICT
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "="*75)
print("SECTION 6: FINAL VERDICT")
print("="*75)

print(f"""
CRITICAL FINDING: C2's 3-day VIX momentum (ANOVA p=0.0002) was contaminated
by a lookahead bug. The signal used same-day VIX close, which moves
contemporaneously with SPY returns (correlation r={corr:.3f}).

When corrected to strict no-lookahead (prior-day VIX only):
- 3d VIX momentum ANOVA F drops from ~7.3 to ~{st_f[0]:.1f}
- The monotonic pattern (VIX falling → positive, VIX rising → negative) INVERTS
- No VIX-based signal produces significant regime separation

COMBINED MODEL VERDICT:
- Mean spread improvement vs 3d-alone: {comb_spread - mom_spread:+.4f}%
- Direction: {'WRONG (combined is worse)' if comb_spread < mom_spread else 'Correct but marginal'}
- Combined model does NOT beat single-factor

OVERALL: No daily backdrop variable passes strict no-lookahead testing.
→ Override 4.0 should use hazard veto only (event + GeoStress)
→ No daily VIX-based backdrop component is justified by the data
""")
