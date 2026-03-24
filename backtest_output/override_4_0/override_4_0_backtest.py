#!/usr/bin/env python3
"""
Override 4.0 — Hazard Veto + Sizing Context Backtest
Tasks 1-4 from C3b: position sizing, hazard veto, Gap×VIX, state machine
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
            'range': float(r['intraday_range']),
            'vix_prior': float(r['vix_prior']),
            'vix_today': float(r['vix_today']),
        })

# Compute gap for each day
for i, r in enumerate(rows):
    if i >= 1:
        r['gap_pct'] = (r['open'] - rows[i-1]['close']) / rows[i-1]['close'] * 100
    else:
        r['gap_pct'] = None

print(f"Loaded {len(rows)} days ({rows[0]['date']} to {rows[-1]['date']})")

# ── Helpers ────────────────────────────────────────────────────
def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

def stats(returns):
    n = len(returns)
    if n < 2:
        return {'n': n, 'mean': 0, 'std': 0, 'sharpe': 0, 'wr': 0, 't': 0, 'p': 1.0, 'median': 0}
    mean = sum(returns) / n
    var = sum((x - mean)**2 for x in returns) / (n - 1)
    std = math.sqrt(var) if var > 0 else 0.0001
    sharpe = mean / std
    wr = sum(1 for x in returns if x > 0) / n * 100
    t = mean / (std / math.sqrt(n))
    p = 2 * (1 - norm_cdf(abs(t)))
    srt = sorted(returns)
    median = srt[n // 2]
    return {'n': n, 'mean': mean, 'std': std, 'sharpe': sharpe, 'wr': wr,
            't': t, 'p': p, 'median': median}

def vix_regime(vp):
    if vp < 16: return '<16'
    elif vp < 20: return '16-20'
    elif vp < 25: return '20-25'
    else: return '>=25'

def vix_regime_broad(vp):
    if vp < 20: return '<20'
    elif vp < 25: return '20-25'
    else: return '>=25'

VIX_ORDER_4 = ['<16', '16-20', '20-25', '>=25']
VIX_ORDER_3 = ['<20', '20-25', '>=25']

# ═══════════════════════════════════════════════════════════════
# TASK 1: VIX LEVEL → POSITION SIZING TABLE
# ═══════════════════════════════════════════════════════════════
print("=" * 75)
print("TASK 1: VIX LEVEL → POSITION SIZING TABLE")
print("=" * 75)

range_by_vix = defaultdict(list)
for r in rows:
    regime = vix_regime(r['vix_prior'])
    range_by_vix[regime].append(r['range'])

# Compute reference range (VIX 16-20 as "normal")
ref_range = sum(range_by_vix['16-20']) / len(range_by_vix['16-20'])

print(f"\nReference range (VIX 16-20): {ref_range:.3f}%")
print(f"\n{'VIX Regime':<12} {'Days':>5} {'Mean Range':>11} {'Median':>8} {'Max':>8} {'Range Ratio':>12} {'Size Mult':>10}")
print("-" * 72)
for regime in VIX_ORDER_4:
    ranges = range_by_vix[regime]
    n = len(ranges)
    mean_r = sum(ranges) / n
    srt = sorted(ranges)
    median_r = srt[n // 2]
    max_r = max(ranges)
    ratio = mean_r / ref_range
    # Size multiplier = ref / mean (keep dollar risk constant)
    size_mult = ref_range / mean_r if mean_r > 0 else 1.0
    # Cap at 1.0 (don't lever up in low-VIX)
    size_mult = min(size_mult, 1.0)
    print(f"{regime:<12} {n:>5} {mean_r:>10.3f}% {median_r:>7.3f}% {max_r:>7.3f}% {ratio:>11.2f}× {size_mult:>9.2f}×")

# Also show the broad 3-bucket version
print(f"\n\n{'VIX Regime':<12} {'Days':>5} {'Mean Range':>11} {'Median':>8} {'Max':>8} {'Size Mult':>10}")
print("-" * 55)
range_by_vix_3 = defaultdict(list)
for r in rows:
    regime = vix_regime_broad(r['vix_prior'])
    range_by_vix_3[regime].append(r['range'])

ref_range_3 = sum(range_by_vix_3['<20']) / len(range_by_vix_3['<20'])
for regime in VIX_ORDER_3:
    ranges = range_by_vix_3[regime]
    n = len(ranges)
    mean_r = sum(ranges) / n
    srt = sorted(ranges)
    median_r = srt[n // 2]
    max_r = max(ranges)
    size_mult = min(ref_range_3 / mean_r, 1.0)
    print(f"{regime:<12} {n:>5} {mean_r:>10.3f}% {median_r:>7.3f}% {max_r:>7.3f}% {size_mult:>9.2f}×")

# ═══════════════════════════════════════════════════════════════
# TASK 2: HAZARD VETO — BAD DAY PROBABILITY
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 75)
print("TASK 2: HAZARD VETO — BAD DAY PROBABILITY BY VIX REGIME")
print("=" * 75)

# Bad day = return < -1%, Very bad = return < -2%
total_days = len(rows)
total_bad = sum(1 for r in rows if r['ret'] < -1)
total_vbad = sum(1 for r in rows if r['ret'] < -2)
base_bad_rate = total_bad / total_days * 100
base_vbad_rate = total_vbad / total_days * 100

print(f"\nOverall: {total_bad} bad days ({base_bad_rate:.1f}%), {total_vbad} very bad days ({base_vbad_rate:.1f}%) out of {total_days}")

print(f"\n{'VIX Regime':<12} {'Total':>6} {'Bad(<-1%)':>10} {'Prob':>7} {'VBad(<-2%)':>11} {'Prob':>7} {'Risk Ratio':>11}")
print("-" * 68)
for regime in VIX_ORDER_4:
    days_in = [r for r in rows if vix_regime(r['vix_prior']) == regime]
    n = len(days_in)
    bad = sum(1 for r in days_in if r['ret'] < -1)
    vbad = sum(1 for r in days_in if r['ret'] < -2)
    bad_pct = bad / n * 100 if n > 0 else 0
    vbad_pct = vbad / n * 100 if n > 0 else 0
    risk_ratio = bad_pct / base_bad_rate if base_bad_rate > 0 else 0
    print(f"{regime:<12} {n:>6} {bad:>10} {bad_pct:>6.1f}% {vbad:>11} {vbad_pct:>6.1f}% {risk_ratio:>10.2f}×")

# Also broader buckets
print(f"\n{'VIX Regime':<12} {'Total':>6} {'Bad(<-1%)':>10} {'Prob':>7} {'VBad(<-2%)':>11} {'Prob':>7} {'Risk Ratio':>11}")
print("-" * 68)
for regime in VIX_ORDER_3:
    days_in = [r for r in rows if vix_regime_broad(r['vix_prior']) == regime]
    n = len(days_in)
    bad = sum(1 for r in days_in if r['ret'] < -1)
    vbad = sum(1 for r in days_in if r['ret'] < -2)
    bad_pct = bad / n * 100 if n > 0 else 0
    vbad_pct = vbad / n * 100 if n > 0 else 0
    risk_ratio = bad_pct / base_bad_rate if base_bad_rate > 0 else 0
    print(f"{regime:<12} {n:>6} {bad:>10} {bad_pct:>6.1f}% {vbad:>11} {vbad_pct:>6.1f}% {risk_ratio:>10.2f}×")

# Distribution of worst days
print("\n\nWORST 10 DAYS:")
print(f"{'Date':<12} {'Return':>10} {'VIX prior':>10} {'VIX today':>10} {'Range':>8} {'Gap':>8}")
print("-" * 60)
worst = sorted(rows, key=lambda r: r['ret'])[:10]
for r in worst:
    gap = r['gap_pct'] if r['gap_pct'] is not None else 0
    print(f"{r['date']:<12} {r['ret']:>+9.3f}% {r['vix_prior']:>10.2f} {r['vix_today']:>10.2f} {r['range']:>7.2f}% {gap:>+7.3f}%")

# ═══════════════════════════════════════════════════════════════
# TASK 3: GAP × VIX AS HAZARD (strict no-lookahead)
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 75)
print("TASK 3: GAP × VIX AS HAZARD (strict no-lookahead)")
print("=" * 75)
print("VIX regime = PRIOR-day close (no lookahead). Gap = same-day (known at open).\n")

GAP_BUCKETS = [
    ('Gap down >1%', -999, -1),
    ('Gap down 0.3-1%', -1, -0.3),
    ('Flat ±0.3%', -0.3, 0.3),
    ('Gap up 0.3-1%', 0.3, 1),
    ('Gap up >1%', 1, 999),
]

valid_gap = [r for r in rows if r['gap_pct'] is not None]

# Build cross-tabulation
print(f"{'Gap Bucket':<20} {'VIX<20 mean':>12} {'N':>4} {'VIX 20-25':>12} {'N':>4} {'VIX≥25':>12} {'N':>4} {'All':>10} {'N':>4}")
print("-" * 90)

gap_vix_data = {}
for glabel, glo, ghi in GAP_BUCKETS:
    row_data = {}
    for vix_reg in VIX_ORDER_3:
        rets = [r['ret'] for r in valid_gap
                if glo <= r['gap_pct'] < ghi and vix_regime_broad(r['vix_prior']) == vix_reg]
        row_data[vix_reg] = rets
    all_rets = [r['ret'] for r in valid_gap if glo <= r['gap_pct'] < ghi]
    row_data['all'] = all_rets
    gap_vix_data[glabel] = row_data

    parts = []
    for vix_reg in VIX_ORDER_3:
        rets = row_data[vix_reg]
        n = len(rets)
        if n >= 2:
            m = sum(rets) / n
            parts.append(f"{m:>+11.3f}% {n:>4}")
        else:
            parts.append(f"{'—':>12} {n:>4}")
    all_n = len(all_rets)
    all_m = sum(all_rets) / all_n if all_n > 0 else 0
    print(f"{glabel:<20} {parts[0]} {parts[1]} {parts[2]} {all_m:>+9.3f}% {all_n:>4}")

# Bad day probability by Gap × VIX
print(f"\n\nBAD DAY PROBABILITY (<-1%) by Gap × VIX:")
print(f"{'Gap Bucket':<20} {'VIX<20':>8} {'VIX 20-25':>10} {'VIX≥25':>8} {'All':>6}")
print("-" * 55)
for glabel, glo, ghi in GAP_BUCKETS:
    parts = []
    for vix_reg in VIX_ORDER_3:
        rets = gap_vix_data[glabel][vix_reg]
        n = len(rets)
        if n >= 3:
            bad = sum(1 for x in rets if x < -1)
            parts.append(f"{bad/n*100:>7.0f}%")
        else:
            parts.append(f"{'—':>8}")
    all_rets = gap_vix_data[glabel]['all']
    all_bad = sum(1 for x in all_rets if x < -1) / len(all_rets) * 100 if len(all_rets) > 0 else 0
    print(f"{glabel:<20} {parts[0]} {parts[1]:>10} {parts[2]:>8} {all_bad:>5.0f}%")

# Specific hazard combos
print("\n\nSPECIFIC HAZARD COMBINATIONS:")
hazard_combos = [
    ("Gap down >1% + VIX≥25", lambda r: r['gap_pct'] is not None and r['gap_pct'] < -1 and r['vix_prior'] >= 25),
    ("Gap down >1% + VIX≥20", lambda r: r['gap_pct'] is not None and r['gap_pct'] < -1 and r['vix_prior'] >= 20),
    ("Gap up >1% + VIX≥25", lambda r: r['gap_pct'] is not None and r['gap_pct'] > 1 and r['vix_prior'] >= 25),
    ("Any gap >1% + VIX≥25", lambda r: r['gap_pct'] is not None and abs(r['gap_pct']) > 1 and r['vix_prior'] >= 25),
    ("Gap down >0.5% + VIX≥25", lambda r: r['gap_pct'] is not None and r['gap_pct'] < -0.5 and r['vix_prior'] >= 25),
    ("Gap down >1% + VIX≥20 + prior VIX rose", lambda r: r['gap_pct'] is not None and r['gap_pct'] < -1 and r['vix_prior'] >= 20),
]

print(f"\n{'Combination':<38} {'N':>4} {'Mean Ret':>10} {'Bad%':>6} {'VBad%':>7} {'Mean Range':>11}")
print("-" * 80)
for label, fn in hazard_combos:
    matching = [r for r in rows if fn(r)]
    n = len(matching)
    if n >= 1:
        mean_ret = sum(r['ret'] for r in matching) / n
        bad_pct = sum(1 for r in matching if r['ret'] < -1) / n * 100
        vbad_pct = sum(1 for r in matching if r['ret'] < -2) / n * 100
        mean_range = sum(r['range'] for r in matching) / n
        print(f"{label:<38} {n:>4} {mean_ret:>+9.3f}% {bad_pct:>5.0f}% {vbad_pct:>6.0f}% {mean_range:>10.2f}%")
    else:
        print(f"{label:<38} {0:>4} {'—':>10}")

# ═══════════════════════════════════════════════════════════════
# TASK 4: OVERRIDE 4.0 STATE MACHINE BACKTEST
# ═══════════════════════════════════════════════════════════════
print("\n\n" + "=" * 75)
print("TASK 4: OVERRIDE 4.0 STATE MACHINE BACKTEST")
print("=" * 75)

def override_state(r):
    """Assign Override 4.0 state based on prior-day VIX + same-day gap."""
    vp = r['vix_prior']
    gap = r['gap_pct']  # can be None for first day

    # SUSPENDED would be GeoStress/event — we can't detect from this data
    # HIGH_RISK: VIX >= 25, OR (VIX 20-25 + gap down >1%)
    if vp >= 25:
        return 'HIGH_RISK'
    if vp >= 20 and gap is not None and gap < -1:
        return 'HIGH_RISK'
    # ELEVATED: VIX 20-25
    if vp >= 20:
        return 'ELEVATED'
    # NORMAL: VIX < 20
    return 'NORMAL'

SIZE_MULT = {'NORMAL': 1.00, 'ELEVATED': 0.75, 'HIGH_RISK': 0.50, 'SUSPENDED': 0.00}

for r in rows:
    r['state'] = override_state(r)
    r['sized_ret'] = r['ret'] * SIZE_MULT[r['state']]

STATE_ORDER = ['NORMAL', 'ELEVATED', 'HIGH_RISK']

state_buckets = defaultdict(list)
for r in rows:
    state_buckets[r['state']].append(r)

print(f"\n{'State':<12} {'Days':>5} {'Mean Ret':>10} {'Sized Ret':>10} {'Range':>8} {'Bad%':>6} {'VBad%':>7} {'WR':>6} {'Sizing':>7}")
print("-" * 80)
for state in STATE_ORDER:
    days = state_buckets[state]
    n = len(days)
    if n == 0:
        continue
    mean_ret = sum(r['ret'] for r in days) / n
    mean_sized = sum(r['sized_ret'] for r in days) / n
    mean_range = sum(r['range'] for r in days) / n
    bad_pct = sum(1 for r in days if r['ret'] < -1) / n * 100
    vbad_pct = sum(1 for r in days if r['ret'] < -2) / n * 100
    wr = sum(1 for r in days if r['ret'] > 0) / n * 100
    mult = SIZE_MULT[state]
    print(f"{state:<12} {n:>5} {mean_ret:>+9.3f}% {mean_sized:>+9.3f}% {mean_range:>7.2f}% {bad_pct:>5.1f}% {vbad_pct:>6.1f}% {wr:>5.1f}% {mult:>6.2f}×")

# Compare: full-size vs sized returns
full_mean = sum(r['ret'] for r in rows) / len(rows)
sized_mean = sum(r['sized_ret'] for r in rows) / len(rows)
full_std = math.sqrt(sum((r['ret'] - full_mean)**2 for r in rows) / (len(rows)-1))
sized_std = math.sqrt(sum((r['sized_ret'] - sized_mean)**2 for r in rows) / (len(rows)-1))
full_sharpe = full_mean / full_std if full_std > 0 else 0
sized_sharpe = sized_mean / sized_std if sized_std > 0 else 0

# Count bad days avoided/reduced
full_bad_impact = sum(r['ret'] for r in rows if r['ret'] < -1)
sized_bad_impact = sum(r['sized_ret'] for r in rows if r['ret'] < -1)

print(f"\n\nPORTFOLIO IMPACT:")
print(f"{'Metric':<30} {'Full Size':>12} {'Override 4.0':>12} {'Difference':>12}")
print("-" * 68)
print(f"{'Mean daily return':<30} {full_mean:>+11.4f}% {sized_mean:>+11.4f}% {sized_mean-full_mean:>+11.4f}%")
print(f"{'Daily std dev':<30} {full_std:>11.4f}% {sized_std:>11.4f}% {sized_std-full_std:>+11.4f}%")
print(f"{'Daily Sharpe':<30} {full_sharpe:>+11.4f} {sized_sharpe:>+11.4f} {sized_sharpe-full_sharpe:>+11.4f}")
print(f"{'Sum of bad-day returns':<30} {full_bad_impact:>+11.2f}% {sized_bad_impact:>+11.2f}% {sized_bad_impact-full_bad_impact:>+11.2f}%")
print(f"{'Bad day damage reduction':<30} {'':>12} {'':>12} {(1 - sized_bad_impact/full_bad_impact)*100 if full_bad_impact != 0 else 0:>+10.1f}%")

# Cumulative return comparison
full_cum = 1.0
sized_cum = 1.0
for r in rows:
    full_cum *= (1 + r['ret'] / 100)
    sized_cum *= (1 + r['sized_ret'] / 100)

print(f"\n{'Cumulative return (272d)':<30} {(full_cum-1)*100:>+11.2f}% {(sized_cum-1)*100:>+11.2f}%")

# Max drawdown
def max_drawdown(returns_pct):
    cum = 1.0
    peak = 1.0
    max_dd = 0
    for ret in returns_pct:
        cum *= (1 + ret / 100)
        if cum > peak:
            peak = cum
        dd = (peak - cum) / peak
        if dd > max_dd:
            max_dd = dd
    return max_dd * 100

full_dd = max_drawdown([r['ret'] for r in rows])
sized_dd = max_drawdown([r['sized_ret'] for r in rows])
print(f"{'Max drawdown':<30} {full_dd:>10.2f}% {sized_dd:>10.2f}% {sized_dd-full_dd:>+10.2f}%")

# Split-sample the state machine
print("\n\nSTATE MACHINE — SPLIT-SAMPLE:")
mid = len(rows) // 2
first_half = rows[:mid]
second_half = rows[mid:]
print(f"First half:  {len(first_half)} days ({first_half[0]['date']} to {first_half[-1]['date']})")
print(f"Second half: {len(second_half)} days ({second_half[0]['date']} to {second_half[-1]['date']})")

for label, half in [("1st Half", first_half), ("2nd Half", second_half)]:
    print(f"\n  {label}:")
    print(f"  {'State':<12} {'Days':>5} {'Mean Ret':>10} {'Range':>8} {'Bad%':>6}")
    print(f"  {'-'*45}")
    for state in STATE_ORDER:
        days = [r for r in half if r['state'] == state]
        n = len(days)
        if n == 0:
            print(f"  {state:<12} {0:>5}")
            continue
        mean_ret = sum(r['ret'] for r in days) / n
        mean_range = sum(r['range'] for r in days) / n
        bad_pct = sum(1 for r in days if r['ret'] < -1) / n * 100
        print(f"  {state:<12} {n:>5} {mean_ret:>+9.3f}% {mean_range:>7.2f}% {bad_pct:>5.1f}%")

print("\n\nDone.")
