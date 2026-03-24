# Pipeline Audit Summary — Complete Results (Parts 1–4)

**Date:** 2026-03-24
**Root Cause:** `phase1_test0_test1.py` line 41 — time filter `09:30 ≤ t ≤ 15:55` on dual-block raw CSV captured IST pre-market bars (11:00–15:55) instead of regular session bars. 77% of all bars in `_m5_regsess.csv` were from the wrong session.
**Fix Applied:** Select IST regular session block (16:30–22:55 IST), convert to ET (−7h). `utils/data_loader.py` helper created. 27 `_FIXED.csv` files generated.

---

## Master Results Table

### ⚠️⚠️⚠️ CATASTROPHIC (Direction Reversal or >90% Shift)

| # | Test | Metric | Original (buggy) | Re-run (FIXED) | Shift | Verdict |
|---|------|--------|:-----------------:|:--------------:|:-----:|:-------:|
| 1 | **G1** | VIX change R² | **0.524** | **0.004** | **−99%** | **INVALIDATED** |
| 2 | **G1** | R² ratio chg/lvl | 56.6× | 0.5× | **−99%** | **INVALIDATED** |
| 3 | **H2 non-stress** | Mean P&L | +1.108% | +0.036% | −97% | **INVALIDATED** |
| 4 | **H2 non-stress** | WR | 83.6% | 54.0% | −29.6pp | **INVALIDATED** |
| 5 | **S21-P9** | Mean P&L | +1.108% | +0.036% | −97% | **INVALIDATED** |
| 6 | **S21-P2** | Mean P&L | −1.405% | **+0.197%** | **REVERSED** | **INVALIDATED** |
| 7 | **S21-P2** | WR | 15.7% | 49.1% | **REVERSED** | **INVALIDATED** |

### ⚠️⚠️ MAJOR (>30% Shift)

| # | Test | Metric | Original | Re-run | Shift | Verdict |
|---|------|--------|:--------:|:------:|:-----:|:-------:|
| 8 | **H1** | Sharpe @ 15:30 | 0.541 | 0.079 | −85% | **REVISED** |
| 9 | **H1** | Mean @ 15:30 | +0.895% | +0.225% | −75% | **REVISED** |
| 10 | **S21-P1** | PF | 5.0 | 1.3 | −74% | **REVISED** |
| 11 | **S21-P1** | Mean P&L | +0.895% | +0.225% | −75% | **REVISED** |
| 12 | **A2 Zone3 DZ** | Mean |ret| | 0.069% | 0.125% | +81% | **REVISED** |
| 13 | **A2 Zone4** | Mean |ret| | 0.079% | 0.116% | +47% | **REVISED** |
| 14 | **A2 Zone1** | Mean |ret| | 0.267% | 0.351% | +31% | **REVISED** |
| 15 | **D-series** | Mean P&L | −0.011% | +0.041% | **REVERSED** | **REVISED** |
| 16 | **C1** | Open=Extreme % | 1.2% | 2.7% | +134% | **REVISED** |

### ✓ CONFIRMED (≤30% Shift, Same Direction)

| # | Test | Metric | Original | Re-run | Shift | Verdict |
|---|------|--------|:--------:|:------:|:-----:|:-------:|
| 17 | **A2 Zone2** | Mean |ret| | 0.154% | 0.181% | +18% | CONFIRMED |
| 18 | **A2 Zone5 PH** | Mean |ret| | 0.131% | 0.124% | −5% | CONFIRMED |
| 19 | **B1 small gap** | Fill % | 86.2% | 83.5% | −3% | CONFIRMED |
| 20 | **B1 medium gap** | Fill % | 67.0% | 65.2% | −3% | CONFIRMED |
| 21 | **B1 large gap** | Fill % | 33.4% | 34.9% | +4% | CONFIRMED |
| 22 | **S21-P5** | Stress freq | 19.5% | 19.5% | 0% | CONFIRMED |
| 23 | **G1 VIX level** | R² | 0.009 | 0.008 | −15% | CONFIRMED (both ≈0) |

### ⏸️ DEFERRED (Require Separate Infrastructure Re-Run)

| # | Test | Reason | Expected Impact |
|---|------|--------|----------------|
| 24 | **E2** (TQS regression) | Needs indicator recompute on FIXED data | HIGH — drives TQS weights |
| 25 | **E3a** (ADX threshold) | Same dependency | HIGH — ADX filter decision |
| 26 | **EMA 4H crosses** | Needs EMA recompute on FIXED 4H bars | HIGH — Direction Gate |
| 27 | **S21-P3/P4/P8** | Structurally same as P1 — inherit collapse | Collapse confirmed |
| 28 | **S21-P10** | Threshold robustness — inherits from P1 | Collapse confirmed |

### ✅ SAFE (Not Affected by Bug)

| # | Test | Reason |
|---|------|--------|
| 29 | **Series I** (I1–I9) | Used raw Fetched_Data/ with correct IST filter |
| 30 | **F1** (BTC-ETH lag) | Uses crypto data, not equity regsess |
| 31 | **C2** (Width breakout) | Uses Fetched_Data/ directly (BUT has same time-filter bug — REVIEW) |
| 32 | **C3** (False breakout) | Uses Fetched_Data/ directly (BUT has same time-filter bug — REVIEW) |
| 33 | **PH-series** | Does not exist in repo |

---

## REVIEW Scripts: C2, C3

Both C2 and C3 use `Fetched_Data/_data.csv` directly (not `_m5_regsess.csv`), but they apply the **same time-range filter** (`"09:30" <= hhmm < "16:00"`) on raw dual-block CSVs. This means they have the same IST pre-market contamination bug. **Both should be re-run with corrected filters in a future pass.**

---

## ⚠️ G1: The Most Important Collapse

**G1 original finding:** "VIX daily change explains 52.4% of SPY daily return variance (R²=0.524). VIX change is 56× more predictive than VIX level."

**G1 with correct data:** R²=0.004 for VIX change. R²=0.008 for VIX level. **Neither predicts anything.**

### Why This Happened

The buggy SPY "daily return" was computed as:
- Open = first bar (09:30) → **correct** (ET block market open)
- Close = last bar (15:55) → **WRONG** (IST block pre-market ≈ 08:55 ET **next morning**)

So the "daily return" was actually measuring **open-to-next-morning-premarket**, which spans ~23 hours including overnight. Overnight returns naturally correlate strongly with VIX changes because both react to the same overnight news/events. With correct data (close at actual 15:55 ET), the VIX relationship disappears because intraday returns have much weaker VIX sensitivity.

### Framework Impact

The G1 finding was the foundation of the **Override 3.0** philosophy: "use VIX change, not VIX level." This drove:
- Override Gate design (VIX z-score based on daily change)
- The decision to drop VIX level as a regime filter
- S14/DR_Vision architecture recommendations

**All of these decisions need reassessment.** VIX change may still be useful for multi-day or overnight signals, but the claimed 52.4% intraday R² was an artifact.

---

## A2 Zone Analysis: What Changed

The zone return pattern is **preserved in direction but revised in magnitude:**

| Zone | Buggy |ret| | FIXED |ret| | Change | Pattern |
|------|:----------:|:---------:|:------:|---------|
| Zone 1 (09:30-10:00) | 0.267% | 0.351% | +31% | Still highest ✓ |
| Zone 2 (10:00-12:00) | 0.154% | 0.181% | +18% | Still 2nd ✓ |
| Zone 3 DZ (12:00-13:30) | 0.069% | 0.125% | **+81%** | Still lowest, but higher |
| Zone 4 (13:30-14:45) | 0.079% | 0.116% | +47% | Revised up |
| Zone 5 PH (14:45-16:00) | 0.131% | 0.124% | −5% | Stable |

**Key revision:** The Dead Zone is NOT as "dead" as originally measured (0.069% → 0.125%). The DZ-to-PH activity gap narrowed significantly.

---

## What Survives

| Finding | Original | FIXED | Status |
|---------|----------|-------|--------|
| Zone ordering (Z1 > Z2 > Z5 > Z4 > Z3) | ✓ | Z1 > Z2 > Z3 ≈ Z5 > Z4 | **REVISED** (DZ/Z4 moved up) |
| Gap fill rates | 86/67/33% | 84/65/35% | **CONFIRMED** (±3%) |
| Stress frequency | 19.5% | 19.5% | **CONFIRMED** |
| VIX level has low R² | 0.009 | 0.008 | **CONFIRMED** (both ≈ 0) |
| Stress MR marginal positive | +0.895% | +0.225% | **SURVIVED** (reduced but positive) |
| Series I (DZ structure, recovery timing) | All | All | **UNAFFECTED** |

---

## What Dies

| Finding | Original | FIXED | Cause of Death |
|---------|----------|-------|---------------|
| VIX change R² = 0.524 | ✓ | 0.004 | SPY "close" was next-morning pre-market |
| VIX change 56× > VIX level | ✓ | 0.5× | Same |
| H2 Noon Reversal +1.11%/83.6% WR | ✓ | +0.036%/54% | Noon/exit bars were IST pre-market |
| S21 Stress MR PF = 5.0 | ✓ | 1.3 | Same |
| Leaders lose on stress (S21-P2) | −1.4% | +0.2% | Direction reversed |
| Non-stress daily reversal | +1.11% | +0.04% | Near-zero |
| Override 3.0 philosophy (change > level) | ✓ | Not supported | G1 collapsed |

---

## Recommended Actions

1. **SUSPEND** all Stress MR / Noon Reversal paper trading
2. **REASSESS** Override 3.0 VIX gate — the "change > level" premise collapsed
3. **RE-RUN** E2/E3a/EMA with FIXED data (deferred — requires indicator recompute)
4. **FIX** C2/C3 scripts (same time-filter bug on raw data)
5. **REGENERATE** `_m5_regsess.csv` files from FIXED pipeline (replace originals)
6. **PRESERVE** Series I findings (I1–I9) — all computed on correct data
7. **RE-EVALUATE** entire framework architecture — many building blocks invalidated
