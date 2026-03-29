# S44 M5 Binary Triggers — TQS Replacement Analysis

**Date:** 2026-03-29 15:16
**Pre-filter:** 4H EMA gate = UP (EMA9 > EMA21 on completed 4H bar)
**Total qualifying M5 bars:** 291,843
**Tickers:** 25/25

## 1. Individual Binary Triggers

### T1: EMA9 reclaim (close > EMA9)

ON: 149,896 bars (51.4%) | OFF: 141,947 bars (48.6%)

| Horizon | ON Mean% | ON WR% | OFF Mean% | OFF WR% | Sep% | Sep p-val |
|---------|----------|--------|-----------|---------|------|-----------|
| +30m | +0.0061 | 49.5 | +0.0152 | 51.3 | -0.0091 | 0.0014** |
| +1hr | +0.0151 | 50.0 | +0.0279 | 51.5 | -0.0128 | 0.0014** |
| +2hr | +0.0166 | 50.1 | +0.0699 | 51.9 | -0.0532 | 0.0000*** |

### T2: RSI > 50

ON: 152,312 bars (52.2%) | OFF: 139,531 bars (47.8%)

| Horizon | ON Mean% | ON WR% | OFF Mean% | OFF WR% | Sep% | Sep p-val |
|---------|----------|--------|-----------|---------|------|-----------|
| +30m | +0.0035 | 49.6 | +0.0182 | 51.3 | -0.0147 | 0.0000*** |
| +1hr | +0.0092 | 49.9 | +0.0346 | 51.6 | -0.0253 | 0.0000*** |
| +2hr | +0.0101 | 50.0 | +0.0779 | 52.1 | -0.0679 | 0.0000*** |

### T3: CE LONG state

ON: 141,636 bars (48.5%) | OFF: 150,207 bars (51.5%)

| Horizon | ON Mean% | ON WR% | OFF Mean% | OFF WR% | Sep% | Sep p-val |
|---------|----------|--------|-----------|---------|------|-----------|
| +30m | +0.0069 | 49.7 | +0.0140 | 51.0 | -0.0071 | 0.0129* |
| +1hr | +0.0116 | 49.9 | +0.0305 | 51.6 | -0.0190 | 0.0000*** |
| +2hr | +0.0091 | 49.6 | +0.0740 | 52.3 | -0.0650 | 0.0000*** |

### T4: Higher low (5-bar)

ON: 220,152 bars (75.4%) | OFF: 71,691 bars (24.6%)

| Horizon | ON Mean% | ON WR% | OFF Mean% | OFF WR% | Sep% | Sep p-val |
|---------|----------|--------|-----------|---------|------|-----------|
| +30m | +0.0085 | 50.1 | +0.0167 | 51.4 | -0.0081 | 0.0198* |
| +1hr | +0.0182 | 50.5 | +0.0311 | 51.6 | -0.0130 | 0.0080** |
| +2hr | +0.0345 | 50.7 | +0.0671 | 51.8 | -0.0326 | 0.0000*** |

### T5: EMA trend (EMA9 > EMA21)

ON: 151,941 bars (52.1%) | OFF: 139,902 bars (47.9%)

| Horizon | ON Mean% | ON WR% | OFF Mean% | OFF WR% | Sep% | Sep p-val |
|---------|----------|--------|-----------|---------|------|-----------|
| +30m | +0.0049 | 49.7 | +0.0166 | 51.1 | -0.0117 | 0.0000*** |
| +1hr | +0.0090 | 50.0 | +0.0347 | 51.5 | -0.0257 | 0.0000*** |
| +2hr | +0.0106 | 49.9 | +0.0771 | 52.1 | -0.0665 | 0.0000*** |

## 2. Trigger Ranking (by +2hr separation)

| Rank | Trigger | Description | Sep% | p-val | Significant? |
|------|---------|-------------|------|-------|--------------|
| 1 | T2 | RSI > 50 | -0.0679 | 0.0000 | YES |
| 2 | T5 | EMA trend (EMA9 > EMA21) | -0.0665 | 0.0000 | YES |
| 3 | T3 | CE LONG state | -0.0650 | 0.0000 | YES |
| 4 | T1 | EMA9 reclaim (close > EMA9) | -0.0532 | 0.0000 | YES |
| 5 | T4 | Higher low (5-bar) | -0.0326 | 0.0000 | YES |

## 3. Combination Test (Top Significant Triggers)

**Combined triggers:** T2 + T5 + T3

ALL ON: 112,773 bars | Any OFF: 179,070 bars

| Horizon | ALL ON Mean% | ALL ON WR% | Any OFF Mean% | Any OFF WR% | Sep% | Sep p-val |
|---------|-------------|------------|--------------|-------------|------|-----------|
| +30m | +0.0050 | 49.5 | +0.0140 | 50.9 | -0.0090 | 0.0016** |
| +1hr | +0.0089 | 49.6 | +0.0292 | 51.4 | -0.0203 | 0.0000*** |
| +2hr | +0.0082 | 49.4 | +0.0641 | 52.0 | -0.0560 | 0.0000*** |

## 4. Head-to-Head: Binary Triggers vs TQS A/B/C

TQS formula: `TQS_quant = 0.76 * RSI_phase + 0.24 * DMI_alignment`
- RSI_phase = |RSI(14) - 50| / 50
- DMI_alignment = min(ADX(14) / 50, 1.0)
- Grades: A (top tercile), B (middle), C (bottom tercile)

### TQS Grades

| Grade | Horizon | N | Mean% | WR% | Std% | p-val |
|-------|---------|---|-------|-----|------|-------|
| A | +30m | 97,461 | +0.0238 | 50.8 | 0.7636 | 0.0000*** |
| A | +1hr | 97,454 | +0.0415 | 51.1 | 1.0486 | 0.0000*** |
| A | +2hr | 97,432 | +0.0882 | 51.5 | 1.4681 | 0.0000*** |
| B | +30m | 97,162 | +0.0045 | 50.3 | 0.7974 | 0.0391* |
| B | +1hr | 97,151 | +0.0123 | 50.3 | 1.1094 | 0.0003*** |
| B | +2hr | 97,107 | +0.0251 | 50.6 | 1.5399 | 0.0000*** |
| C | +30m | 97,172 | +0.0033 | 50.0 | 0.7424 | 0.0838 |
| C | +1hr | 97,142 | +0.0101 | 50.8 | 1.0814 | 0.0018** |
| C | +2hr | 97,112 | +0.0141 | 50.8 | 1.5552 | 0.0024** |

**TQS A-vs-C separation at +2hr:** +0.0741% (p=0.0000)

**Best binary trigger (T2) separation at +2hr:** -0.0679% (p=0.0000)

## 5. Verdict

**TQS still wins marginally.**

TQS separation (0.0741%) exceeds best binary trigger (0.0679%).

## 6. Implementation Rule

```python
# Replace TQS with binary gate(s)
# T2: RSI > 50
# T5: EMA trend (EMA9 > EMA21)
# T3: CE LONG state

def m5_entry_gate(m5_bar, m5_ema9, m5_ema21, m5_rsi, m5_ce_long, m5_low_prev5):
    """Returns True if M5 binary gate passes (all significant triggers ON)."""
    if m5_rsi <= 50: return False  # T2: RSI above 50
    if m5_ema9 <= m5_ema21: return False  # T5: EMA trend
    if not m5_ce_long: return False  # T3: CE LONG
    return True
```

## 7. Integration with Prompt 3 (4H RSI/ADX Bins)

From Prompt 3: 4H RSI bins × VIX regime dominate forward returns.
STRETCHED_DOWN + VIX>=25 = +0.73% at +2hr (p<0.0001).

The M5 binary triggers operate WITHIN a given 4H context.
If both layers show edge, a Multi-TF Intelligence Module should:
1. **Outer gate:** 4H RSI bin + VIX regime (decides WHETHER to trade)
2. **Inner gate:** M5 binary triggers (decides HOW to enter)
