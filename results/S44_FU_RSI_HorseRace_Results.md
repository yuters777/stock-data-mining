# S44-FU: RSI<35 Horse Race + Exit Topology

**Date:** 2026-03-29 16:02
**Total triggers (3 down + VIX>=25):** 159
**Tickers with triggers:** 25/25

---
## Task A: RSI<35 Horse Race

### RSI Distribution at Trigger

| RSI Range | N | % |
|-----------|---|---|
| RSI < 25 | 33 | 20.8% |
| RSI 25-30 | 12 | 7.5% |
| RSI 30-35 | 18 | 11.3% |
| RSI 35-40 | 24 | 15.1% |
| RSI 40-50 | 45 | 28.3% |
| RSI >= 50 | 27 | 17.0% |
| **Total** | **159** | |

Mean RSI: 37.6 | Median: 38.8 | Min: 17.6 | Max: 61.5

### RSI Variant Comparison (Exit: EMA21 touch + 2-bar backstop)

| Variant | N | Mean% | Med% | WR% | PF | MAE% | Sharpe | TotalP&L% | p-val |
|---------|---|-------|------|-----|-----|------|--------|-----------|-------|
| V1: No filter | 157 | +1.73 | +1.09 | 69 | 3.94 | -2.15 | 0.429 | +272.3 | 0.0000*** |
| V2: RSI<35 gate | 63 | +3.91 | +2.37 | 86 | 14.90 | -3.10 | 0.805 | +246.3 | 0.0000*** |
| V3: RSI sizing | 157 | +2.48 | +0.96 | 69 | 5.70 | -2.55 | 0.445 | +388.9 | 0.0000*** |

### V2 Missed Trade Analysis

V2 hard gate passes: 63 | skips: 96

**Skipped trades (RSI >= 35):** N=94, Mean=+0.28%, WR=57%, PF=1.35
-> Skipped trades were positive but not significant. Hard gate may destroy value.

### Return by RSI Bin (EMA21 touch + 2-bar backstop)

| RSI Range | N | Mean% | WR% | PF | p-val |
|-----------|---|-------|-----|-----|-------|
| < 25 | 33 | +3.45 | 73 | 7.43 | 0.0013** |
| 25-30 | 12 | +4.71 | 100 | 56532.63 | 0.0000*** |
| 30-35 | 18 | +4.21 | 100 | 75809.56 | 0.0000*** |
| 35-40 | 23 | +2.04 | 83 | 6.86 | 0.0013** |
| 40-50 | 44 | +0.36 | 73 | 1.54 | 0.1443 |
| >= 50 | 27 | -1.37 | 11 | 0.01 | 1.0000 |

---
## Task B: Exit Topology

### Exit Comparison (BASELINE entry, all triggers)

| Exit | N | Mean% | Med% | WR% | PF | MAE% | Sharpe | AvgHold | p-val |
|------|---|-------|------|-----|-----|------|--------|---------|-------|
| E1: Fixed +2 bars | 157 | +2.43 | +1.31 | 71 | 5.64 | -2.28 | 0.489 | 2.0 | 0.0000*** |
| E2-pure: EMA21 only (max 10) | 158 | +3.47 | +2.05 | 75 | 9.56 | -2.51 | 0.672 | 3.8 | 0.0000*** |
| E2-backstop-2: EMA21 OR +2 bars | 157 | +1.73 | +1.09 | 69 | 3.94 | -2.15 | 0.429 | 1.7 | 0.0000*** |
| E2-backstop-3: EMA21 OR +3 bars | 155 | +1.77 | +1.14 | 70 | 4.06 | -2.22 | 0.433 | 2.2 | 0.0000*** |

### EMA21 Touch Rate

**E2-pure: EMA21 only (max 10):** 139/158 EMA21 touches (88%), 19 backstop/max exits
**E2-backstop-2: EMA21 OR +2 bars:** 75/157 EMA21 touches (48%), 82 backstop/max exits
**E2-backstop-3: EMA21 OR +3 bars:** 78/155 EMA21 touches (50%), 77 backstop/max exits

### E2-pure Non-Completion (hard max at +10 bars)

Trades needing hard max exit: 19/158
Their mean return: -1.14%, WR: 26%

### E2-backstop-2: Touch vs Backstop Split

| Exit Type | N | Mean% | WR% | PF | AvgHold |
|-----------|---|-------|-----|-----|---------|
| EMA21 touch | 75 | +2.29 | 68 | 6.00 | 1.3 |
| Backstop (+2) | 82 | +1.23 | 70 | 2.73 | 2.0 |

---
## Task C: Combined Best Spec

```
TRIGGER:    3 consecutive 4H down bars + VIX >= 25.0
RSI RULE:   RSI < 35.0 hard gate (winner: V2)
ENTRY:      4H trigger bar close
EXIT:       E2-pure: EMA21 only (max 10) (winner)

Final N:    63
Mean %:     +7.52
Median %:   +7.70
WR %:       94
PF:         126.88
MAE:        -3.51%
Sharpe:     1.382
Total P&L:  +473.6%
Avg Hold:   5.3 4H bars
p-val:      0.000000
```

### Production Implementation Rule

```python
# Module 4 — Final Research Spec
def module4_trigger(bars_4h, vix_prior_close):
    """
    Trigger: 3 consecutive 4H down bars + VIX >= 25
    Entry:   4H trigger bar close
    RSI:     RSI < 35.0 hard gate
    Exit:    E2-pure: EMA21 only (max 10)
    """
    # Check 3 consecutive down bars
    if not all(b.close < b.open for b in bars_4h[-3:]):
        return None
    if vix_prior_close < 25.0:
        return None
    if bars_4h[-1].rsi_14 >= 35.0:
        return None  # RSI hard gate
    return {'entry': bars_4h[-1].close, 'exit': 'e2_pure'}
```
