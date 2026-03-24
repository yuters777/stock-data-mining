# Override 4.0 — Final Results

**Date:** 2026-03-24
**Data:** 272 trading days (2025-02-11 to 2026-03-12)
**Source:** SPY daily OHLCV + FRED VIXCLS daily close
**Scripts:** `c1_vix_baseline.py`, `c2_backdrop_candidates.py`, `c3a_combined_model.py`, `override_4_0_backtest.py`

---

## 1. Data Availability (from C1)

| Variable | Available? | Notes |
|----------|:----------:|-------|
| SPY daily OHLCV | YES | 282 days, full-session |
| VIX daily close (FRED) | YES | 284 days |
| VIX3M / VIX9D | **NO** | Term structure untested |
| VIX futures (VX1/VX2) | **NO** | Contango/backwardation untested |
| VVIX | **NO** | Vol-of-vol untested |
| SPY M5 intraday | Partial | Truncated at 13:00 ET |

**Key gap:** VIX3M term structure (VIX/VIX3M ratio) is the academically
strongest short-term volatility signal and remains completely untested.
This is the #1 data acquisition priority.

---

## 2. VIX Level Baseline (from C1)

Prior-day VIX close → next-day SPY open-to-close return.

| VIX Regime | Days | Mean Return | Sharpe | WR | t-stat | p-value |
|------------|-----:|----------:|-------:|---:|-------:|--------:|
| <16 | 64 | −0.030% | −0.072 | 45.3% | −0.58 | 0.563 |
| 16-20 | 130 | −0.069% | −0.106 | 50.8% | −1.20 | 0.229 |
| 20-25 | 56 | +0.216% | +0.249 | 66.1% | +1.86 | 0.063 |
| ≥25 | 22 | +0.341% | +0.124 | 45.5% | +0.58 | 0.562 |

**ANOVA F = 1.861, p ≈ 0.14** — NOT significant for direction.

**But VIX predicts RANGE (strongly monotonic):**

| VIX Regime | Days | Mean Range | Median Range | Max Range | Range vs Normal |
|------------|-----:|----------:|------------:|----------:|:-:|
| <16 | 64 | 0.709% | 0.632% | 2.984% | 0.69× |
| 16-20 | 130 | 1.024% | 0.875% | 7.135% | 1.00× (ref) |
| 20-25 | 56 | 1.501% | 1.397% | 3.515% | 1.47× |
| ≥25 | 22 | 3.090% | 2.147% | 10.757% | 3.02× |

Split-sample: **4/4 VIX level buckets stable** (same sign both halves).

---

## 3. Backdrop Candidates (from C2)

| Rank | Candidate | ANOVA F | p-value | C2 Status |
|-----:|-----------|:------:|:-------:|:----------:|
| 1 | 3d VIX momentum | 7.301 | 0.0002 | WINNER → **KILLED in C3a** |
| 2 | Gap × VIX interaction | 2.954 | 0.025 | Significant for hazard |
| 3 | 10d VIX momentum | 2.268 | 0.055 | Marginal |
| 4 | 5d VIX momentum | 1.928 | 0.102 | Not significant |
| 5 | VIX level (baseline) | 1.861 | 0.137 | Range predictor |
| 6 | VRP (5d realized vol) | 1.263 | 0.273 | Noise at daily |
| 7 | Gap (marginal) | 0.951 | 0.413 | Not significant |
| 8 | VIX/VIX3M term structure | — | — | DATA UNAVAILABLE |

---

## 4. C3a — Lookahead Bug Discovery

### The bug

C2's `vix_change()` computed: `vix_fred[date] - vix_fred[date - 3 trading days]`

This uses **same-day VIX close**, which is contemporaneous with (not predictive
of) the SPY return. Same-day VIX change and SPY return have **r = −0.723**.

### Impact

| Method | ANOVA F | p-value | Monotonic? | Significant buckets |
|--------|:------:|:-------:|:----------:|:-------------------:|
| C2 (same-day VIX = lookahead) | 7.301 | 0.0002 | YES | 4 of 5 |
| Strict (prior-day VIX only) | 1.624 | ~0.17 | **NO (inverted)** | **0 of 5** |

**F-stat inflated 4.5× by lookahead bias.** The entire monotonic pattern
(VIX falling → positive, VIX rising → negative) was an artifact of
contemporaneous correlation.

With strict no-lookahead, VIX rising >3pts in 3 days actually has the
**highest** next-day return (+0.424%, mean-reversion), not the lowest.

### Combined model (C3a)

| Model | FAV Mean | UNFAV Mean | Spread |
|-------|------:|-------:|------:|
| 3d momentum only (strict) | −0.005% | +0.211% | −0.216% |
| Combined (3d + Gap×VIX) | −0.035% | +0.269% | −0.305% |

Spread is **inverted** (UNFAVORABLE outperforms) and combined model is **worse**.
No multi-factor combination adds value.

---

## 5. What DOES Work: Hazard Detection

Since VIX doesn't predict direction but strongly predicts range and risk,
Override 4.0 pivots to **hazard veto + sizing context**.

### Bad-Day Probability by VIX Regime

Bad day = SPY intraday return < −1%. Baseline rate: 8.1% (22 of 272 days).

| VIX Regime | Days | Bad Days | Bad Day Prob | Risk Ratio | Very Bad (<−2%) |
|------------|-----:|---------:|:------------:|:----------:|:---------------:|
| <16 | 64 | 2 | 3.1% | 0.39× | 0.0% |
| 16-20 | 130 | 10 | 7.7% | 0.95× | 2.3% |
| 20-25 | 56 | 4 | 7.1% | 0.88× | 1.8% |
| **≥25** | **22** | **6** | **27.3%** | **3.37×** | **9.1%** |

**VIX ≥ 25 → 3.37× bad-day risk.** Over 1 in 4 days with VIX ≥ 25 had a
loss exceeding −1%. This is the strongest empirical finding in the dataset.

### Gap × VIX Hazard Combinations

| Combination | N | Mean Return | Bad Day Prob | Very Bad Prob | Mean Range |
|-------------|--:|----------:|:------------:|:-------------:|----------:|
| Gap down >1% + VIX≥25 | 4 | −0.667% | **75%** | 25% | 4.89% |
| Any gap >1% + VIX≥25 | 9 | −0.904% | **56%** | 22% | 3.79% |
| Gap down >0.5% + VIX≥25 | 6 | −0.369% | **67%** | 17% | 4.25% |
| Gap down >1% + VIX≥20 | 12 | −0.044% | 42% | 8% | 2.98% |
| Gap up >1% + VIX≥25 | 5 | −1.094% | 40% | 20% | 2.91% |

**Gap >1% (either direction) + VIX ≥ 25 = 56% bad-day probability.** These
are strong hazard veto triggers. Sample sizes are small (N=4-12) but the
signal is so extreme it's actionable as a defensive veto.

### Bad-Day Probability: Full Cross-Tabulation

| Gap Bucket | VIX<20 | VIX 20-25 | VIX≥25 |
|------------|:------:|:---------:|:------:|
| Gap down >1% | 0% | 25% | **75%** |
| Gap down 0.3-1% | 12% | 0% | 25% |
| Flat ±0.3% | 4% | 5% | 0% |
| Gap up 0.3-1% | 10% | 0% | — |
| Gap up >1% | 0% | 20% | **40%** |

---

## 6. Override 4.0 — Proposed Design

### Philosophy

**HAZARD VETO + SIZING CONTEXT**

Override 4.0 does NOT predict returns. It does NOT tell you when to be
aggressive. It tells you **when to reduce risk** and **how much to size**.

This is fundamentally different from Override 3.1, which claimed to predict
direction (and was wrong).

### Position Sizing Table

| VIX Regime | Size Multiplier | Rationale |
|------------|:-------:|-----------|
| VIX < 20 | **1.00×** | Normal conditions; mean range 0.92% |
| VIX 20-25 | **0.68×** | Range 1.47× normal; scale to equalize dollar risk |
| VIX ≥ 25 | **0.33×** | Range 3.02× normal; scale to equalize dollar risk |

Formula: `size_mult = min(1.0, reference_range / current_regime_range)`

### State Machine

```
NORMAL
  Condition: Prior-day VIX < 20, no extreme gap
  Sizing:    1.00×
  Entries:   All buckets allowed
  Days:      194 of 272 (71%)

ELEVATED
  Condition: Prior-day VIX 20-25 (no extreme gap)
  Sizing:    0.75×
  Entries:   A and B buckets only
  Days:      48 of 272 (18%)

HIGH_RISK
  Condition: Prior-day VIX ≥ 25
             OR (Prior-day VIX 20-25 AND gap down > 1%)
  Sizing:    0.50×
  Entries:   A-bucket only, or no new entries
  Days:      30 of 272 (11%)

SUSPENDED
  Condition: GeoStress kill-switch OR event quarantine
  Sizing:    0× (flatten)
  Entries:   None
  Update:    Event-driven (unchanged from 3.1)
```

### State Machine Transitions

```
Update: Daily at open

Inputs:
  - vix_prior = prior trading day's VIX close (from FRED or broker feed)
  - gap_pct = (today_open - yesterday_close) / yesterday_close

Rules (evaluated in order):
  1. IF GeoStress OR event quarantine active → SUSPENDED
  2. IF vix_prior ≥ 25 → HIGH_RISK
  3. IF vix_prior ≥ 20 AND |gap_pct| > 1% → HIGH_RISK
  4. IF vix_prior ≥ 20 → ELEVATED
  5. ELSE → NORMAL
```

### State Machine Backtest (272 days)

| State | Days | Mean Return | Sized Return | Range | Bad Day Prob | WR |
|-------|-----:|----------:|:-----------:|------:|:-----------:|---:|
| NORMAL | 194 | −0.056% | −0.056% | 0.92% | 6.2% | 49.0% |
| ELEVATED | 48 | +0.208% | +0.156% | 1.41% | 4.2% | 66.7% |
| HIGH_RISK | 30 | +0.321% | +0.161% | 2.81% | 26.7% | 50.0% |

**Note:** HIGH_RISK days have the highest mean return (+0.321%) due to
mean-reversion after VIX spikes. The Override does NOT try to capture this —
it deliberately reduces exposure because these days also carry 26.7% bad-day
probability and 2.81% average range. The risk/reward tradeoff favors
capital preservation.

### Portfolio Impact

| Metric | Full Size | Override 4.0 | Change |
|--------|--------:|:-----------:|------:|
| Mean daily return | +0.032% | +0.005% | −0.027% |
| Daily std dev | 1.005% | 0.689% | **−0.315%** |
| Sum of bad-day losses | −39.3% | −30.2% | **+9.1% saved** |
| Bad-day damage reduction | — | — | **+23.1%** |
| Max drawdown | 9.68% | 8.75% | **−0.93%** |
| Cumulative return (272d) | +7.59% | +0.71% | −6.88% |

The Override reduces daily volatility by 31% and bad-day damage by 23% at the
cost of mean return (because sizing down in high-VIX also cuts the bounce days).
This is a deliberate design choice: **Override 4.0 is a risk management tool,
not a return enhancer.**

### Split-Sample Stability

| State | 1st Half Mean | 1st Half Bad% | 2nd Half Mean | 2nd Half Bad% | Range Stable? |
|-------|----------:|:----:|----------:|:----:|:----:|
| NORMAL (N=85→109) | −0.041% | 8.2% | −0.069% | 4.6% | YES |
| ELEVATED (N=28→20) | +0.320% | 3.6% | +0.051% | 5.0% | YES |
| HIGH_RISK (N=23→7) | +0.203% | 34.8% | +0.709% | 0.0% | YES (range) |

Range prediction is stable. Bad-day probability for HIGH_RISK is volatile
(N=7 in second half), but range remains elevated in both halves.

---

## 7. Comparison to Override 3.1

| Feature | Override 3.1 (dead) | Override 4.0 (proposed) |
|---------|:-------------------:|:-----------------------:|
| Philosophy | dVIX/dt predicts returns | VIX = hazard/sizing context |
| Predicts direction? | Claimed yes (artifact) | **NO — explicitly not** |
| Predicts range? | Not used | **YES — strong monotonic** |
| Primary use | Entry permission | **Risk sizing + hazard veto** |
| Primary variable | Daily VIX change (1d) | VIX level + Gap×VIX |
| R² on SPY returns | 0.004 (failed) | N/A (doesn't predict) |
| ANOVA F (direction) | — | 1.6 (NS) |
| State machine | ON/OFF/WARNING/SUSPENDED | **NORMAL/ELEVATED/HIGH_RISK/SUSPENDED** |
| State update | Intraday z-score | **Daily at open** |
| Evidence base | G1 killed it | **C1-C3a: 272 days, 8 signals tested** |
| Bad-day damage reduction | Unknown | **23.1%** |
| Max DD improvement | Unknown | **−0.93%** |

### What changed philosophically

Override 3.1 asked: *"Is the market favorable or unfavorable today?"*
This is the wrong question — we cannot answer it with VIX data.

Override 4.0 asks: *"How much risk is present today?"*
This is answerable, stable, and actionable.

---

## 8. Data Gaps for Future

| Priority | Data | Signal | Potential |
|:--------:|------|--------|-----------|
| **1** | VIX3M daily (FRED or IB) | VIX/VIX3M ratio (term structure) | Academically strongest short-term vol signal. Could upgrade Override from hazard-only to partially predictive. |
| **2** | Full SPY M5 (09:30-16:00) | Afternoon vol bursts, full-day RV | Current data truncated at 13:00 ET. Full session needed for intraday hazard detection. |
| **3** | VIX9D daily | VIX9D/VIX ratio (short-term fear) | Spikes before events, may predict next-day vol. |
| **4** | VIX futures (VX1, VX2) | Contango/backwardation | Roll yield prediction, macro regime detection. |
| **5** | VVIX daily | Vol-of-vol | Extreme values may predict VIX regime shifts. |

---

## 9. VERDICT

### Best single variable
**VIX level** — for range prediction and hazard detection (bad-day probability).
Not for direction.

### Multi-factor adds value?
**NO.** Combined model (3d momentum + Gap×VIX) performed worse than
single-factor. No combination tested improved regime separation.

### Recommended design
**Hazard veto + sizing context.** No daily backdrop component predicts direction.
VIX level reliably predicts range (3× at VIX≥25) and bad-day probability
(3.37× at VIX≥25). Use for position sizing and hazard veto.

### Data gaps for future
VIX3M term structure is the #1 priority. It is the only untested signal with
strong academic support for short-horizon predictive power.

### Confidence level

| Component | Confidence | Reasoning |
|-----------|:----------:|-----------|
| VIX predicts range | **HIGH (9/10)** | Strongly monotonic, 4/4 split-sample stable |
| VIX predicts bad-day risk | **HIGH (8/10)** | 3.37× risk ratio at VIX≥25, extreme values |
| No VIX signal predicts direction | **HIGH (9/10)** | 8 signals tested, 0 survived no-lookahead |
| Gap×VIX hazard veto | **MEDIUM (6/10)** | Strong signal but N=4-12, needs more data |
| State machine thresholds | **MEDIUM (6/10)** | N=272 total, N=22-30 in high-VIX states |
| Sizing multipliers | **MEDIUM (7/10)** | Based on range ratios which are stable |

### What Override 4.0 IS

- A **risk management framework** that scales position size by volatility regime
- A **hazard detection system** that identifies extreme-risk days (VIX≥25 + large gaps)
- A **defensive tool** that reduces bad-day damage by ~23% and max drawdown by ~1%

### What Override 4.0 is NOT

- NOT a directional signal (it cannot tell you which way SPY will move)
- NOT a return enhancer (it will reduce returns from high-VIX bounce days)
- NOT a replacement for entry criteria (the strategy's bucket system does the selection)

---

*Generated by C1→C2→C3a→C3b analysis pipeline.*
*C2 lookahead bug discovered and corrected in C3a.*
*All results use strict no-lookahead methodology (prior-day VIX only).*
