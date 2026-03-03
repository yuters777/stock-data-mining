# Phase 8 — Confirmation Indicator Report

**Date:** 2026-03-03

## M-001: Diagnostic Signal Count

| Indicator | OOS Pass | OOS PF | OOS P&L | Notes |
|-----------|----------|--------|---------|-------|
| Mirror level | 42/50 (84%) | 3.14 | +$7,289 | 8 non-mirror trades lose -$224 |
| Score >= 10/15/20 | 50/50 (100%) | 2.64 | +$7,064 | ALL trades already above all thresholds |
| Volume fade | 33/50 (66%) | 3.69 | +$6,933 | Strong diagnostic; 17 surge trades PF=1.08 |
| RSI confirms | 13/50 (26%) | 0.55 | -$813 | **COUNTER-PRODUCTIVE** — blocks winners |
| Touches >= 2/3/5 | 50/50 (100%) | 2.64 | +$7,064 | ALL trades already above all thresholds |

## Filter Comparison (OOS)

| Experiment | Label | Trades | WR | PF | P&L |
|------------|-------|--------|----|----|-----|
| L-005 | **Baseline (no filter)** | **50** | **56%** | **2.64** | **$7,064** |
| M-002 | Mirror levels only | 42 | 60% | 3.14 | $7,289 |
| M-003-10 | Level score >= 10 | 50 | 56% | 2.64 | $7,064 |
| M-003-15 | Level score >= 15 | 50 | 56% | 2.64 | $7,064 |
| M-003-20 | Level score >= 20 | 50 | 56% | 2.64 | $7,064 |
| M-004 | Volume fade (vol < 1.0x) | 33 | 61% | 3.69 | $6,933 |
| M-005-55/45 | RSI S>55/L<45 | 20 | 40% | 0.84 | -$386 |
| M-005-60/40 | RSI S>60/L<40 | 13 | 38% | 0.55 | -$813 |
| M-005-65/35 | RSI S>65/L<35 | 8 | 25% | 0.39 | -$729 |
| M-005-70/30 | RSI S>70/L<30 | 6 | 33% | 0.78 | -$130 |
| M-006-2 | Touches >= 2 | 50 | 56% | 2.64 | $7,064 |
| M-006-3 | Touches >= 3 | 50 | 56% | 2.64 | $7,064 |
| M-006-5 | Touches >= 5 | 50 | 56% | 2.64 | $7,064 |

## M-007: Walk-Forward Comparison

| Window | Period | Baseline (L-005) | | Vol Fade (M-004) | |
|--------|--------|---------|------|---------|------|
| | | Trades | P&L | Trades | P&L |
| 1 | 2025-05-10→06-10 | 5 | -$162 | 4 | -$613 |
| 2 | 2025-06-10→07-10 | 12 | +$1,086 | 9 | +$1,835 |
| 3 | 2025-07-10→08-10 | 18 | -$349 | 14 | -$320 |
| 4 | 2025-08-10→09-10 | 7 | -$1,159 | 3 | -$337 |
| 5 | 2025-09-10→10-10 | 20 | -$440 | 15 | +$393 |
| 6 | 2025-10-10→11-10 | 26 | +$895 | 13 | -$210 |
| 7 | 2025-11-10→12-10 | 13 | +$1,559 | 5 | +$325 |
| 8 | 2025-12-10→01-10 | 15 | +$3,447 | 10 | -$464 |
| **Total** | | **116** | **+$4,876** | **73** | **+$609** |
| **Positive** | | **4/8** | | **3/8** | |

## Verdict

**REJECT all confirmation indicators. L-005 baseline remains best.**

Key findings:
1. **Score and Touches have ZERO variance** — all trades already score >= 20 and have >= 5 touches. These can't be used as filters.
2. **RSI is COUNTER-PRODUCTIVE** — trading WITH RSI extremes (overbought SHORT, oversold LONG) selects the worst trades (PF=0.55). The strategy works best when RSI is NOT extreme.
3. **Mirror filter is cosmetic** — 84% of trades are already on mirror levels. Removing 8 non-mirror trades adds +$225 but doesn't help WF.
4. **Volume fade has best diagnostic power** — PF goes from 2.64→3.69 on OOS. But WF degrades from 4/8→3/8, losing window 8 (the biggest winner $3,447→-$464). Filtering on volume removes winning trades in crucial windows.

**Why indicators don't help:** The existing filter chain (ATR ratio, volume, squeeze, time) already filters out low-quality signals. With direction filtering (TSLA=long, others=short), the remaining 50 OOS trades are already high-quality. Adding more filters just reduces sample size and harms WF stability.

**Final config: L-005 with v4.1 baseline params, no confirmation filters.**
