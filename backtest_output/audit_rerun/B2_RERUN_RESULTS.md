# Audit B2 Re-Run: Gap-Fill Timing Curve (FIXED Data)

**Date:** 2026-03-24
**Data Source:** `load_m5_regsess()` (IST-block extraction → correct regular session)
**Original:** B1 used `_m5_regsess.csv` (buggy), B2 computed timing from B1 output
**Note:** B1 gap detection fully recomputed from clean data in this re-run.

---

## Verdict: ⚠️⚠️ MATERIALLY REVISED — Fill Rates Higher, Timing Faster

With clean data, gap fills are **faster and more frequent**. The overall fill rate
increased from 52.9% to 60.8%, and timing shifted dramatically earlier.

---

## Comparison Table

| Metric | Original (buggy) | Re-run (FIXED) | Delta | Verdict |
|--------|:-----------------:|:--------------:|:-----:|:-------:|
| Total gap-days | 8,053 | 7,585 | -5.8% | Minor |
| Total fills | 4,258 (52.9%) | 4,615 (60.8%) | +7.9pp | ⚠️ More fills |
| Fill by 09:30 | 25.2% | **51.2%** | **+26.0pp** | ⚠️⚠️ MAJOR |
| **Fill by 10:00** | **52.3%** | **76.3%** | **+24.0pp** | ⚠️⚠️ MAJOR |
| **Fill by 10:30** | **59.7%** | **83.4%** | **+23.7pp** | ⚠️⚠️ MAJOR |
| Fill by 11:00 | 73.6% | 87.3% | +13.7pp | ⚠️ REVISED |
| **Fill by 13:00** | **78.4%** | **94.1%** | **+15.7pp** | ⚠️⚠️ MAJOR |
| Mean fill time | 99.0 min | **37.6 min** | **-62%** | ⚠️⚠️ MAJOR |
| Median fill time | 30.0 min | **0.0 min** | — | Fills at open |

## Claim Comparison

| Checkpoint | Claim | Buggy | FIXED | Buggy Match | FIXED Match |
|:----------:|:-----:|:-----:|:-----:|:-----------:|:-----------:|
| 10:00 | 51-61% | 52.3% | 76.3% | YES | NO (higher) |
| 10:30 | 66-72% | 59.7% | 83.4% | ~CLOSE | NO (higher) |
| 13:00 | 82-86% | 78.4% | 94.1% | ~CLOSE | NO (higher) |

**The buggy data was actually closer to the claims.** The clean data shows fills
happen much faster than the framework expected.

## Fill Rate by Gap Size (FIXED vs Buggy)

| Bucket | Buggy Fill Rate | FIXED Fill Rate | Delta |
|--------|:---------------:|:---------------:|:-----:|
| < 0.30% | ~75% | **95.1%** | +20pp |
| 0.30-0.50% | ~58% | **86.3%** | +28pp |
| 0.50-1.00% | ~48% | **68.6%** | +21pp |
| 1.00-1.50% | ~29% | **51.1%** | +22pp |
| > 1.50% | ~20% | **23.3%** | +3pp |

Gap fills are substantially more common with clean data, especially for small
and medium gaps. Large gaps (>1.50%) show similar fill rates.

## Key Findings

1. **Median fill time = 0 min**: Over half of fills happen at the open bar itself.
   The buggy data obscured this because pre-market IST bars created artificial gaps.

2. **Fill rates are much higher**: 95.1% of tiny gaps (<0.30%) fill vs ~75% before.

3. **Framework claims are now LOW**: The original 51-61% by 10:00 claim was based
   on buggy data. Reality is 76.3% by 10:00.

4. **Updated recommended fill rates** (of gaps that fill):
   - By 09:30: 51.2%
   - By 10:00: 76.3%
   - By 10:30: 83.4%
   - By 13:00: 94.1%

---

## Raw Results

```
Total gap-days: 7,585 | Fills: 4,615 (60.8%)

CUMULATIVE FILL TIMING:
  09:30    51.2% of fills
  10:00    76.3%
  10:30    83.4%
  11:00    87.3%
  13:00    94.1%
  16:00   100.0%

OVERALL FILL RATE BY GAP-SIZE BUCKET:
  < 0.30%:    95.1% (1,567/1,647)
  0.30-0.50%: 86.3% (802/929)
  0.50-1.00%: 68.6% (1,220/1,779)
  1.00-1.50%: 51.1% (503/985)
  > 1.50%:    23.3% (523/2,245)

BY GAP DIRECTION:
  Up:   fill by 10:30 = 82.6% (2,412 fills)
  Down: fill by 10:30 = 84.3% (2,203 fills)
```
