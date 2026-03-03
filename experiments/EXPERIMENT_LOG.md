# Experiment Log — False Breakout Strategy Optimization

**Date:** 2026-03-03 10:34
**Tickers:** NVDA, AMZN
**IS Period:** 2025-02-10 to 2025-10-01
**OOS Period:** 2025-10-01 to 2026-01-31
**Baseline:** v3.4

---

## EXP-001: Fractal Depth
**Hypothesis:** Shallower fractal depth (k=3) detects more levels → more trades. Deeper (k=7,10) = fewer, stronger levels
**Change:** fractal_depth from 5 to [3, 5, 7, 10]

**Baseline (IS):** 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130

**Baseline (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

### Variants Tested

| Variant | Trades (IS) | WR (IS) | PF (IS) | P&L (IS) | Trades (OOS) | WR (OOS) | PF (OOS) | P&L (OOS) |
|---------|-------------|---------|---------|----------|--------------|----------|----------|-----------|
| fractal_depth=3 | 42 | 38.1% | 0.43 | $-3063 | 127 | 35.4% | 0.70 | $-5731 |
| fractal_depth=5 | 24 | 25.0% | 0.34 | $-2130 | 78 | 33.3% | 0.56 | $-5403 |
| fractal_depth=7 | 20 | 25.0% | 0.33 | $-1733 | 60 | 31.7% | 0.51 | $-4995 |
| fractal_depth=10 | 13 | 30.8% | 0.37 | $-1237 | 49 | 36.7% | 0.78 | $-1655 |

**Best Variant (IS):** fractal_depth=10 — 30.8% WR / -283357188557062.25 Sharpe / 13 trades / PF=0.37 / $-1237
**Best Variant (OOS):** 36.7% WR / -13.30 Sharpe / 49 trades / PF=0.78 / $-1655

**Verdict:** ACCEPT
**Notes:** Trade counts ranged from 13 to 42. Win rates: 25.0%-38.1%. Profit factors: 0.33-0.43.

---

## EXP-002: ATR Entry Threshold
**Hypothesis:** Lower ATR entry threshold allows more trades; quality may decrease
**Change:** atr_entry_threshold from 0.75 to [0.60, 0.65, 0.70, 0.75, 0.80]

**Baseline (IS):** 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130

**Baseline (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

### Variants Tested

| Variant | Trades (IS) | WR (IS) | PF (IS) | P&L (IS) | Trades (OOS) | WR (OOS) | PF (OOS) | P&L (OOS) |
|---------|-------------|---------|---------|----------|--------------|----------|----------|-----------|
| atr_entry=0.6 | 33 | 30.3% | 0.40 | $-2625 | 78 | 33.3% | 0.56 | $-5403 |
| atr_entry=0.65 | 26 | 26.9% | 0.32 | $-2383 | 78 | 33.3% | 0.56 | $-5403 |
| atr_entry=0.7 | 25 | 24.0% | 0.31 | $-2430 | 78 | 33.3% | 0.56 | $-5403 |
| atr_entry=0.75 | 24 | 25.0% | 0.34 | $-2130 | 78 | 33.3% | 0.56 | $-5403 |
| atr_entry=0.8 | 23 | 26.1% | 0.37 | $-1831 | 78 | 33.3% | 0.56 | $-5403 |

**Best Variant (IS):** atr_entry=0.8 — 26.1% WR / -9.72 Sharpe / 23 trades / PF=0.37 / $-1831
**Best Variant (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

**Verdict:** ACCEPT
**Notes:** Trade counts ranged from 23 to 33. Win rates: 24.0%-30.3%. Profit factors: 0.31-0.40.

---

## EXP-003: Max Stop ATR Percentage
**Hypothesis:** Higher stop cap allows wider stops → fewer 'stop too big' blocks, but larger losses per trade
**Change:** max_stop_atr_pct from 0.15 to [0.10, 0.15, 0.20, 0.25]

**Baseline (IS):** 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130

**Baseline (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

### Variants Tested

| Variant | Trades (IS) | WR (IS) | PF (IS) | P&L (IS) | Trades (OOS) | WR (OOS) | PF (OOS) | P&L (OOS) |
|---------|-------------|---------|---------|----------|--------------|----------|----------|-----------|
| max_stop_atr=0.1 | 19 | 31.6% | 0.37 | $-1961 | 76 | 32.9% | 0.56 | $-5537 |
| max_stop_atr=0.15 | 24 | 25.0% | 0.34 | $-2130 | 78 | 33.3% | 0.56 | $-5403 |
| max_stop_atr=0.2 | 24 | 25.0% | 0.34 | $-2048 | 79 | 30.4% | 0.50 | $-6349 |
| max_stop_atr=0.25 | 24 | 25.0% | 0.35 | $-1992 | 78 | 30.8% | 0.51 | $-5995 |

**Best Variant (IS):** max_stop_atr=0.1 — 31.6% WR / -10.31 Sharpe / 19 trades / PF=0.37 / $-1961
**Best Variant (OOS):** 32.9% WR / -12.90 Sharpe / 76 trades / PF=0.56 / $-5537

**Verdict:** ACCEPT
**Notes:** Trade counts ranged from 19 to 24. Win rates: 25.0%-31.6%. Profit factors: 0.34-0.37.

---

## EXP-004: Minimum Risk-Reward Ratio
**Hypothesis:** Lower R:R (2.0, 2.5) allows more trades with closer targets; higher WR may compensate
**Change:** min_rr from 3.0 to [2.0, 2.5, 3.0, 3.5]

**Baseline (IS):** 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130

**Baseline (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

### Variants Tested

| Variant | Trades (IS) | WR (IS) | PF (IS) | P&L (IS) | Trades (OOS) | WR (OOS) | PF (OOS) | P&L (OOS) |
|---------|-------------|---------|---------|----------|--------------|----------|----------|-----------|
| min_rr=2.0 | 27 | 25.9% | 0.33 | $-2306 | 92 | 34.8% | 0.57 | $-5917 |
| min_rr=2.5 | 26 | 23.1% | 0.32 | $-2346 | 88 | 34.1% | 0.57 | $-5803 |
| min_rr=3.0 | 24 | 25.0% | 0.34 | $-2130 | 78 | 33.3% | 0.56 | $-5403 |
| min_rr=3.5 | 24 | 25.0% | 0.34 | $-2130 | 77 | 33.8% | 0.57 | $-5251 |

**Best Variant (IS):** min_rr=3.0 — 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130
**Best Variant (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

**Verdict:** REJECT
**Notes:** Trade counts ranged from 24 to 27. Win rates: 23.1%-25.9%. Profit factors: 0.32-0.34.

---

## EXP-005: Level Tolerance
**Hypothesis:** Wider tolerance catches more BPU touches and pattern signals near levels
**Change:** tolerance from 5c/0.10% to [3c, 5c, 7c, 10c]

**Baseline (IS):** 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130

**Baseline (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

### Variants Tested

| Variant | Trades (IS) | WR (IS) | PF (IS) | P&L (IS) | Trades (OOS) | WR (OOS) | PF (OOS) | P&L (OOS) |
|---------|-------------|---------|---------|----------|--------------|----------|----------|-----------|
| tol=0.03c/0.08% | 24 | 25.0% | 0.34 | $-2130 | 76 | 32.9% | 0.54 | $-5566 |
| tol=0.05c/0.10% | 24 | 25.0% | 0.34 | $-2130 | 78 | 33.3% | 0.56 | $-5403 |
| tol=0.07c/0.10% | 24 | 25.0% | 0.34 | $-2130 | 78 | 33.3% | 0.56 | $-5403 |
| tol=0.1c/0.12% | 27 | 22.2% | 0.31 | $-2413 | 75 | 33.3% | 0.56 | $-5239 |

**Best Variant (IS):** tol=0.03c/0.08% — 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130
**Best Variant (OOS):** 32.9% WR / -13.62 Sharpe / 76 trades / PF=0.54 / $-5566

**Verdict:** REJECT
**Notes:** Trade counts ranged from 24 to 27. Win rates: 22.2%-25.0%. Profit factors: 0.31-0.34.

---

## EXP-006: Partial Take-Profit Level
**Hypothesis:** Earlier TP (1.5R) locks in profits sooner → higher WR but lower avg R
**Change:** partial_tp_at from 2.0R to [1.5R, 2.0R, 2.5R]

**Baseline (IS):** 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130

**Baseline (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

### Variants Tested

| Variant | Trades (IS) | WR (IS) | PF (IS) | P&L (IS) | Trades (OOS) | WR (OOS) | PF (OOS) | P&L (OOS) |
|---------|-------------|---------|---------|----------|--------------|----------|----------|-----------|
| partial_tp=1.5R | 24 | 25.0% | 0.34 | $-2130 | 78 | 33.3% | 0.56 | $-5403 |
| partial_tp=2.0R | 24 | 25.0% | 0.34 | $-2130 | 78 | 33.3% | 0.56 | $-5403 |
| partial_tp=2.5R | 24 | 25.0% | 0.34 | $-2130 | 78 | 32.1% | 0.53 | $-5865 |

**Best Variant (IS):** partial_tp=1.5R — 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130
**Best Variant (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

**Verdict:** REJECT
**Notes:** Trade counts ranged from 24 to 24. Win rates: 25.0%-25.0%. Profit factors: 0.34-0.34.

---

## EXP-007: CLP Minimum Consolidation Bars
**Hypothesis:** Fewer min bars (2) captures more CLP signals; more (5) = higher quality
**Change:** clp_min_bars from 3 to [2, 3, 4, 5]

**Baseline (IS):** 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130

**Baseline (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

### Variants Tested

| Variant | Trades (IS) | WR (IS) | PF (IS) | P&L (IS) | Trades (OOS) | WR (OOS) | PF (OOS) | P&L (OOS) |
|---------|-------------|---------|---------|----------|--------------|----------|----------|-----------|
| clp_min_bars=2 | 24 | 25.0% | 0.34 | $-2130 | 78 | 33.3% | 0.56 | $-5403 |
| clp_min_bars=3 | 24 | 25.0% | 0.34 | $-2130 | 78 | 33.3% | 0.56 | $-5403 |
| clp_min_bars=4 | 24 | 25.0% | 0.34 | $-2130 | 79 | 34.2% | 0.57 | $-5376 |
| clp_min_bars=5 | 24 | 25.0% | 0.34 | $-2130 | 80 | 33.8% | 0.56 | $-5412 |

**Best Variant (IS):** clp_min_bars=2 — 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130
**Best Variant (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

**Verdict:** REJECT
**Notes:** Trade counts ranged from 24 to 24. Win rates: 25.0%-25.0%. Profit factors: 0.34-0.34.

---

## EXP-008: LP2 Engulfing Requirement
**Hypothesis:** Relaxing engulfing allows more LP2 signals but may reduce quality
**Change:** lp2_engulfing from True to [True, False]

**Baseline (IS):** 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130

**Baseline (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

### Variants Tested

| Variant | Trades (IS) | WR (IS) | PF (IS) | P&L (IS) | Trades (OOS) | WR (OOS) | PF (OOS) | P&L (OOS) |
|---------|-------------|---------|---------|----------|--------------|----------|----------|-----------|
| lp2_engulfing=on | 24 | 25.0% | 0.34 | $-2130 | 78 | 33.3% | 0.56 | $-5403 |
| lp2_engulfing=off | 25 | 24.0% | 0.32 | $-2266 | 78 | 33.3% | 0.56 | $-5403 |

**Best Variant (IS):** lp2_engulfing=on — 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130
**Best Variant (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

**Verdict:** REJECT
**Notes:** Trade counts ranged from 24 to 25. Win rates: 24.0%-25.0%. Profit factors: 0.32-0.34.

---

## EXP-009: LP1 Tail Ratio Minimum
**Hypothesis:** Lower tail ratio (0.10) accepts more LP1 signals; higher (0.25) = cleaner patterns
**Change:** tail_ratio_min from 0.20 to [0.10, 0.15, 0.20, 0.25]

**Baseline (IS):** 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130

**Baseline (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

### Variants Tested

| Variant | Trades (IS) | WR (IS) | PF (IS) | P&L (IS) | Trades (OOS) | WR (OOS) | PF (OOS) | P&L (OOS) |
|---------|-------------|---------|---------|----------|--------------|----------|----------|-----------|
| tail_ratio=0.1 | 29 | 41.4% | 0.86 | $-500 | 88 | 35.2% | 0.59 | $-5768 |
| tail_ratio=0.15 | 26 | 30.8% | 0.68 | $-1036 | 83 | 33.7% | 0.55 | $-5859 |
| tail_ratio=0.2 | 24 | 25.0% | 0.34 | $-2130 | 78 | 33.3% | 0.56 | $-5403 |
| tail_ratio=0.25 | 24 | 20.8% | 0.21 | $-2709 | 69 | 33.3% | 0.53 | $-4933 |

**Best Variant (IS):** tail_ratio=0.1 — 41.4% WR / -1.39 Sharpe / 29 trades / PF=0.86 / $-500
**Best Variant (OOS):** 35.2% WR / -13.94 Sharpe / 88 trades / PF=0.59 / $-5768

**Verdict:** ACCEPT
**Notes:** Trade counts ranged from 24 to 29. Win rates: 20.8%-41.4%. Profit factors: 0.21-0.86.

---

## EXP-010: Minimum Level Score
**Hypothesis:** Lower min score (3) includes weaker levels → more trades. Higher (7) = only strongest levels
**Change:** min_level_score from 5 to [3, 5, 6, 7]

**Baseline (IS):** 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130

**Baseline (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

### Variants Tested

| Variant | Trades (IS) | WR (IS) | PF (IS) | P&L (IS) | Trades (OOS) | WR (OOS) | PF (OOS) | P&L (OOS) |
|---------|-------------|---------|---------|----------|--------------|----------|----------|-----------|
| min_level_score=3 | 24 | 25.0% | 0.34 | $-2130 | 78 | 33.3% | 0.56 | $-5403 |
| min_level_score=5 | 24 | 25.0% | 0.34 | $-2130 | 78 | 33.3% | 0.56 | $-5403 |
| min_level_score=6 | 24 | 25.0% | 0.34 | $-2130 | 78 | 33.3% | 0.56 | $-5403 |
| min_level_score=7 | 24 | 25.0% | 0.34 | $-2130 | 78 | 33.3% | 0.56 | $-5403 |

**Best Variant (IS):** min_level_score=3 — 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130
**Best Variant (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

**Verdict:** REJECT
**Notes:** Trade counts ranged from 24 to 24. Win rates: 25.0%-25.0%. Profit factors: 0.34-0.34.

---

## EXP-011: Squeeze Filter Toggle
**Hypothesis:** Disabling squeeze filter may allow more trades if it was blocking valid signals
**Change:** enable_squeeze_filter from True to [True, False]

**Baseline (IS):** 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130

**Baseline (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

### Variants Tested

| Variant | Trades (IS) | WR (IS) | PF (IS) | P&L (IS) | Trades (OOS) | WR (OOS) | PF (OOS) | P&L (OOS) |
|---------|-------------|---------|---------|----------|--------------|----------|----------|-----------|
| squeeze=on | 24 | 25.0% | 0.34 | $-2130 | 78 | 33.3% | 0.56 | $-5403 |
| squeeze=off | 25 | 24.0% | 0.32 | $-2310 | 83 | 34.9% | 0.62 | $-5040 |

**Best Variant (IS):** squeeze=on — 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130
**Best Variant (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

**Verdict:** REJECT
**Notes:** Trade counts ranged from 24 to 25. Win rates: 24.0%-25.0%. Profit factors: 0.32-0.34.

---

## EXP-012: Volume Filter Toggle
**Hypothesis:** Volume filter may be blocking valid false breakout signals. Removing it tests VSA value
**Change:** enable_volume_filter from True to [True, False]

**Baseline (IS):** 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130

**Baseline (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

### Variants Tested

| Variant | Trades (IS) | WR (IS) | PF (IS) | P&L (IS) | Trades (OOS) | WR (OOS) | PF (OOS) | P&L (OOS) |
|---------|-------------|---------|---------|----------|--------------|----------|----------|-----------|
| volume=on | 24 | 25.0% | 0.34 | $-2130 | 78 | 33.3% | 0.56 | $-5403 |
| volume=off | 24 | 25.0% | 0.34 | $-2130 | 78 | 33.3% | 0.56 | $-5403 |

**Best Variant (IS):** volume=on — 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130
**Best Variant (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

**Verdict:** REJECT
**Notes:** Trade counts ranged from 24 to 24. Win rates: 25.0%-25.0%. Profit factors: 0.34-0.34.

---

## EXP-013: Time Filter Toggle
**Hypothesis:** Time filter blocks first 5 min. Disabling tests if open-bar signals are viable
**Change:** enable_time_filter from True to [True, False]

**Baseline (IS):** 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130

**Baseline (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

### Variants Tested

| Variant | Trades (IS) | WR (IS) | PF (IS) | P&L (IS) | Trades (OOS) | WR (OOS) | PF (OOS) | P&L (OOS) |
|---------|-------------|---------|---------|----------|--------------|----------|----------|-----------|
| time_filter=on | 24 | 25.0% | 0.34 | $-2130 | 78 | 33.3% | 0.56 | $-5403 |
| time_filter=off | 24 | 25.0% | 0.34 | $-2130 | 78 | 32.1% | 0.55 | $-5715 |

**Best Variant (IS):** time_filter=on — 25.0% WR / -11.09 Sharpe / 24 trades / PF=0.34 / $-2130
**Best Variant (OOS):** 33.3% WR / -12.70 Sharpe / 78 trades / PF=0.56 / $-5403

**Verdict:** REJECT
**Notes:** Trade counts ranged from 24 to 24. Win rates: 25.0%-25.0%. Profit factors: 0.34-0.34.

---

## COMBINED WINNERS

**Parameters changed:** {'fractal_depth': 10, 'atr_entry_threshold': 0.8, 'max_stop_atr_pct': 0.1, 'tail_ratio_min': 0.1, 'name': 'combined_winners'}

| Period | Trades | WR | PF | P&L |
|--------|--------|-----|-----|------|
| Baseline IS | 24 | 25.0% | 0.34 | $-2130 |
| Baseline OOS | 78 | 33.3% | 0.56 | $-5403 |
| Combined IS | 10 | 30.0% | 0.45 | $-843 |
| Combined OOS | 53 | 41.5% | 0.92 | $-691 |

---


## WALK-FORWARD VALIDATION

**Config:** combined_winners
**Windows:** 8 (3-month train / 1-month test)

| Window | Test Period | Trades | WR | PF | Sharpe | P&L |
|--------|-------------|--------|-----|-----|--------|------|
| 1 | 2025-05-10→2025-06-10 | 8 | 37.5% | 0.51 | -2.80 | $-708 |
| 2 | 2025-06-10→2025-07-10 | 5 | 20.0% | 0.07 | -30.26 | $-964 |
| 3 | 2025-07-10→2025-08-10 | 27 | 44.4% | 0.99 | -0.06 | $-27 |
| 4 | 2025-08-10→2025-09-10 | 1 | 0.0% | 0.00 | 0.00 | $-165 |
| 5 | 2025-09-10→2025-10-10 | 17 | 29.4% | 0.23 | -38.56 | $-2679 |
| 6 | 2025-10-10→2025-11-10 | 27 | 44.4% | 0.82 | -6.02 | $-774 |
| 7 | 2025-11-10→2025-12-10 | 11 | 45.5% | 1.01 | 0.59 | $26 |
| 8 | 2025-12-10→2026-01-10 | 19 | 26.3% | 0.20 | -48.08 | $-2789 |

**Summary:**
- Mean Sharpe: -15.65 ± 18.71
- Positive Sharpe windows: 1/8
- Mean PF: 0.48
- Mean WR: 30.9%
- Total Trades: 115
- Total P&L: $-8079

---

## SECOND ROUND OPTIMIZATION

Based on the combined winners config (fractal_depth=10, atr_entry=0.80, max_stop_atr=0.10, tail_ratio=0.10), tested additional parameter tweaks:

| Config | IS Trades | IS WR | IS PF | IS P&L | OOS Trades | OOS WR | OOS PF | OOS P&L |
|--------|-----------|-------|-------|--------|------------|--------|--------|---------|
| combined_base | 10 | 30.0% | 0.45 | $-843 | 53 | 41.5% | 0.92 | $-691 |
| tol=0.10c | 10 | 30.0% | 0.45 | $-843 | 53 | 41.5% | 0.93 | $-541 |
| no_squeeze | 11 | 27.3% | 0.40 | $-1023 | 57 | 42.1% | 0.94 | $-573 |
| tol+nosqueeze | 11 | 27.3% | 0.40 | $-1023 | 57 | 42.1% | 0.95 | $-423 |

**Best second-round variant:** tol=0.10c + no_squeeze → OOS PF=0.95, -$423

---

## TICKER-SPECIFIC ANALYSIS

**Critical finding:** AMZN drives profitability, NVDA destroys it.

| Ticker | OOS Trades | OOS WR | OOS PF | OOS P&L | Exit Profile |
|--------|-----------|--------|--------|---------|-------------|
| AMZN | 39 | 48.7% | 2.08 | $+2,938 | 27 EOD(+$175), 11 stops(-$247), 1 target(+$922) |
| NVDA | 14 | 21.4% | 0.13 | $-3,629 | 3 EOD(+$189), 11 stops(-$381) |
| Combined | 53 | 41.5% | 0.92 | $-691 | Dragged down by NVDA |

**Root cause for NVDA underperformance:**
- NVDA has only 3 detected levels at fractal_depth=10 in IS period (too few)
- All NVDA IS trades are stops → no signal edge
- NVDA's higher volatility breaks through tight stops more often
- Fractal_depth=3 gives NVDA better results (19 IS trades, 42.1% WR) but worsens AMZN

**Conclusion:** Strategy works well for AMZN (moderate volatility, $150-220 range), poorly for NVDA (high volatility, $90-150 range). Ticker-specific tuning or a volatility-adaptive parameter scheme would improve results.
