# ⚠️ P1 CRITICAL INTERIM REPORT — HALT TRIGGERED

**Date:** 2026-03-24
**Status:** HALT — Multiple P1 tests show >30% metric shift. One direction reversal.
**Action Required:** Suspend all paper trading based on Stress MR / Noon Reversal results.

---

## QC Validation

### Baseline Reproduction ✓
Buggy data reproduces original published numbers exactly:
- H2 Non-stress: +1.108%, 83.6% WR (published: +1.11%, 83.6% WR) ✓
- H1 15:30 exit: +0.895%, Sharpe 0.541 (published: +0.895%, Sharpe 0.541) ✓

### FIXED Data Sanity ✓
- 78 bars/day for all individual equities (09:30–15:55 ET) ✓
- 0 IST-contaminated bars ✓
- Closing volumes in millions (regular session confirmed) ✓
- SPY only 42.6 bars/day (IST block incomplete, stops at 13:00 ET) — not a blocker for P1 tests which exclude SPY ✓

---

## P1 Results Summary

| # | Test | Metric | Buggy | FIXED | Shift | Flag |
|---|------|--------|:-----:|:-----:|:-----:|:----:|
| 1 | **H1** | Mean % (15:30) | +0.895% | +0.225% | **−75%** | ⚠️ MAJOR |
| 1 | **H1** | WR (15:30) | 72.2% | 54.5% | −17.7pp | ⚠️ |
| 1 | **H1** | Sharpe (15:30) | 0.541 | 0.079 | **−85%** | ⚠️ MAJOR |
| 2 | **H2 Stress** | Mean % | +0.895% | +0.225% | **−75%** | ⚠️ MAJOR |
| 2 | **H2 Non-stress** | Mean % | +1.108% | +0.036% | **−97%** | ⚠️⚠️ CATASTROPHIC |
| 2 | **H2 Non-stress** | WR | 83.6% | 54.0% | −29.6pp | ⚠️⚠️ CATASTROPHIC |
| 3 | **S21-P1** | Mean % | +0.895% | +0.225% | **−75%** | ⚠️ MAJOR |
| 3 | **S21-P1** | WR | 72.2% | 54.5% | −17.7pp | ⚠️ |
| 3 | **S21-P1** | PF | 5.0 | 1.3 | **−74%** | ⚠️ MAJOR |
| 4 | **S21-P2** | Mean % | −1.405% | **+0.197%** | **REVERSED** | ⚠️⚠️⚠️ |
| 4 | **S21-P2** | WR | 15.7% | 49.1% | +33.4pp | ⚠️⚠️⚠️ |
| 5 | **S21-P9** | Mean % | +1.108% | +0.036% | **−97%** | ⚠️⚠️ CATASTROPHIC |
| 5 | **S21-P9** | WR | 83.6% | 54.0% | −29.6pp | ⚠️⚠️ CATASTROPHIC |

---

## Detailed Results

### H1: Exit Grid — ⚠️ MAJOR SHIFT (−75% at 15:30)

| Exit Time | Buggy Mean | FIXED Mean | Buggy Sharpe | FIXED Sharpe |
|:---------:|:----------:|:----------:|:------------:|:------------:|
| 14:30 | +0.761% | +0.280% | 0.483 | 0.108 |
| 14:45 | +0.757% | +0.270% | 0.482 | 0.104 |
| 15:00 | +0.879% | +0.204% | 0.550 | 0.078 |
| 15:15 | +0.804% | +0.233% | 0.487 | 0.084 |
| **15:30** | **+0.895%** | **+0.225%** | **0.541** | **0.079** |
| 15:45 | +0.839% | +0.213% | 0.519 | 0.075 |

**Verdict: REVISED.** The exit time optimization previously showed 15:30 as clear winner (Sharpe 0.541). With clean data, ALL exit times cluster at Sharpe ~0.08 with 14:30 marginally best. **The "optimal 15:30 exit" finding was an artifact.**

**FIXED finding:** The strategy is marginally positive at ALL exit times (mean +0.2–0.3%), but with Sharpe ~0.08 and WR ~55%. Not compelling for active trading.

### H2: Noon Reversal — ⚠️⚠️ CATASTROPHIC (−97%)

| Segment | Buggy Mean | FIXED Mean | Buggy WR | FIXED WR |
|---------|:----------:|:----------:|:--------:|:--------:|
| Stress | +0.895% | +0.225% | 72.2% | 54.5% |
| Non-stress | +1.108% | +0.036% | 83.6% | 54.0% |
| All | +1.067% | +0.073% | 81.3% | 54.1% |

**Verdict: INVALIDATED.** The claimed +1.11% / 83.6% WR was entirely a data artifact. With clean data, non-stress reversal is effectively zero (+0.036%, 54% WR).

**Confirms I8 Series I finding** independently.

### S21-P1: Stress MR Core — ⚠️ MAJOR (−75%, PF 5.0→1.3)

| Metric | Buggy | FIXED |
|--------|:-----:|:-----:|
| Mean | +0.895% | +0.225% |
| WR | 72.2% | 54.5% |
| PF | 5.0 | 1.3 |
| N | 108 | 110 |

**Verdict: REVISED.** The Stress MR strategy still has a marginally positive edge (+0.225%, WR 54.5%), but the Profit Factor collapsed from 5.0 to 1.3. This is barely above breakeven and not viable for active trading after transaction costs.

### S21-P2: Leader Underperformance — ⚠️⚠️⚠️ DIRECTION REVERSAL

| Metric | Buggy | FIXED |
|--------|:-----:|:-----:|
| Mean | **−1.405%** | **+0.197%** |
| WR | 15.7% | 49.1% |
| N | 108 | 110 |

**Verdict: INVALIDATED — DIRECTION REVERSAL.** The buggy data showed leaders LOSING aggressively (−1.4%, 16% WR), which supported the "leader-chasing ban" rule. With clean data, leaders are marginally positive (+0.197%, 49% WR). **There is no leader underperformance signal.** The entire "don't chase leaders on stress days" framework rule was wrong.

### S21-P9: Non-Stress Reversal — ⚠️⚠️ CATASTROPHIC (−97%)

| Metric | Buggy | FIXED |
|--------|:-----:|:-----:|
| Mean | +1.108% | +0.036% |
| WR | 83.6% | 54.0% |
| N | 444 | 454 |

**Verdict: INVALIDATED.** Same as H2 non-stress. The "daily noon reversal" concept has essentially zero edge with clean data.

---

## GO / NO-GO Decision

### 🔴 NO-GO: Suspend ALL Noon Reversal and Stress MR Paper Trading

**Rationale:**
1. **Every P1 test shows >30% metric degradation** — far beyond the halt threshold
2. **S21-P2 reversed direction** — the leader ban was wrong
3. **The core strategy (Stress MR at noon → 15:30)** drops from PF 5.0 to PF 1.3 — not viable after costs
4. **Non-stress reversal is zero** — the daily trade concept is dead
5. **Stress reversal is marginally positive** (+0.225%) but barely profitable after costs (~0.05%)

### What Survives (Tentatively)

The Stress MR entry at noon still shows a **very small positive edge** (+0.225%, WR 54.5%). This is:
- Positive but tiny
- PF 1.3 (barely above 1.0)
- Would need lower transaction costs or position sizing adjustment to be net profitable
- Requires P2/P3 re-runs to confirm if any supporting infrastructure is still valid

### Recommended Immediate Actions

1. **HALT** all Noon Reversal / Stress MR paper trading
2. **DO NOT proceed to P2 re-runs** until this report is reviewed
3. **Mark in CONSOLIDATED_REPORT.md:** H1 REVISED, H2 INVALIDATED, S21 INVALIDATED (except marginal stress edge)
4. **Re-assess entire framework** — the strategy architecture was built on data that was 77% pre-market bars

---

## Root Cause Reminder

All original results were computed on `_m5_regsess.csv` files where:
- Bars 09:30–10:55 ET were correct (from Alpha Vantage ET block)
- Bars 11:00–15:55 ET were **IST pre-market data** (~04:00–08:55 ET)
- Entry at "12:00 noon" was actually ~05:00 ET pre-market
- Exit at "15:30" was actually ~08:30 ET pre-market
- The "reversal" measured was a pre-market price recovery, not a regular session phenomenon
