# C3a: Override 4.0 — Combined Model + Split-Sample Validation

**Date:** 2026-03-24
**Data:** 272 trading days from spy_daily_returns.csv (2025-02-11 to 2026-03-12)
**Script:** `c3a_combined_model.py`

---

## CRITICAL FINDING: C2 Lookahead Bug

C2's `vix_change()` function used **same-day VIX close** to compute 3-day VIX
momentum. The VIX close is contemporaneous with the SPY return being predicted.

```
C2 method:   vix_fred[date] - vix_fred[date-3]     ← uses today's VIX close
Strict:      vix_prior[i] - vix_prior[i-3]         ← uses prior-day VIX only
```

**Same-day VIX change vs SPY return: r = −0.723** (strong negative contemporaneous
correlation). This means C2's "VIX fell over 3 days → SPY rose" was partially
tautological: the VIX close on day T already reflects the same information as
SPY's return on day T.

### Example: 2025-02-21

| Method | VIX start | VIX end | 3d change | SPY return |
|--------|--------:|--------:|----------:|-----------:|
| C2 (same-day) | 15.35 | 18.21 | +2.86 | −1.58% |
| Strict (prior-day) | 15.66 | 15.37 | +0.29 | −1.58% |

C2 sees a +2.86pt VIX spike (correctly flagging a bad day). But the spike
**happened on the same day** as the −1.58% SPY drop. It's not a signal — it's
the same event measured twice. The strict method sees only +0.29 (flat), which
was the prior-day information actually available before market open.

---

## 1. Lookahead Bug Impact on 3-Day VIX Momentum

### C2 Method (with lookahead) — 5-bucket

| VIX 3d change | Days | Mean SPY Return | Sharpe | WR | t-stat | p-value |
|---|---:|---:|---:|---:|---:|---:|
| Falling >3pts | 27 | +0.5500% | +0.275 | 59.3% | +1.43 | 0.1537 |
| Falling 1-3pts | 54 | +0.1865% | +0.358 | 70.4% | +2.63 | 0.0085 |
| Flat (±1pt) | 117 | +0.1140% | +0.242 | 53.0% | +2.62 | 0.0089 |
| Rising 1-3pts | 41 | −0.2521% | −0.362 | 34.1% | −2.32 | 0.0203 |
| Rising >3pts | 31 | −0.6516% | −0.394 | 32.3% | −2.19 | 0.0284 |

**ANOVA F = 7.301 (df 4,265)**

### Strict Method (no lookahead) — 5-bucket

| VIX 3d change | Days | Mean SPY Return | Sharpe | WR | t-stat | p-value |
|---|---:|---:|---:|---:|---:|---:|
| Falling >3pts | 28 | +0.0895% | +0.119 | 57.1% | +0.63 | 0.5280 |
| Falling 1-3pts | 54 | −0.0540% | −0.091 | 46.3% | −0.67 | 0.5044 |
| Flat (±1pt) | 111 | −0.0757% | −0.114 | 51.4% | −1.20 | 0.2310 |
| Rising 1-3pts | 45 | +0.0567% | +0.077 | 46.7% | +0.52 | 0.6052 |
| Rising >3pts | 31 | +0.4235% | +0.184 | 64.5% | +1.02 | 0.3065 |

**ANOVA F = 1.624 (df 4,264)**

### Bug impact summary

| Metric | C2 (lookahead) | Strict (no lookahead) | Ratio |
|--------|:-:|:-:|:-:|
| ANOVA F-stat | 7.301 | 1.624 | **4.5x inflated** |
| ANOVA p-value | 0.0002 | ~0.17 | Insignificant |
| Monotonic pattern? | YES (VIX fall→positive) | **NO (INVERTED)** | — |
| Best bucket Sharpe | +0.358 (Falling 1-3) | +0.184 (Rising >3) | — |
| Significant buckets (p<0.05) | 4 of 5 | **0 of 5** | — |

**The C2 flagship signal (3d VIX momentum, p=0.0002) does not survive
lookahead correction.** The monotonic pattern inverts entirely — with strict
no-lookahead, VIX *rising* days have *higher* next-day SPY returns, not lower.

---

## 2. Strict No-Lookahead — 3-Bucket Simplified

| Regime | Days | Mean Return | Std | Sharpe | WR | t-stat | p-value |
|--------|-----:|----------:|----:|-------:|---:|-------:|--------:|
| FAVORABLE (VIX fell >1pt in 3d) | 82 | −0.0050% | 0.6507% | −0.008 | 50.0% | −0.07 | 0.9448 |
| NEUTRAL (VIX ±1pt) | 112 | −0.0764% | 0.6625% | −0.115 | 50.9% | −1.22 | 0.2224 |
| UNFAVORABLE (VIX rose >1pt in 3d) | 75 | +0.2111% | 1.5838% | +0.133 | 54.7% | +1.15 | 0.2483 |

All regimes have p > 0.20. No regime separation. The "UNFAVORABLE" bucket
actually has the highest mean return (mean-reversion effect: after VIX rises,
the market tends to bounce).

---

## 3. Prior-Day VIX Change (1d, strictly predictive)

An alternative signal using only prior-day information (known before market open):

| Bucket | Days | Mean Return | Sharpe | WR | t-stat | p-value |
|--------|-----:|----------:|-------:|---:|-------:|--------:|
| Fell >2pts | 21 | −0.0630% | −0.076 | 38.1% | −0.35 | 0.7289 |
| Fell 1-2pts | 33 | −0.2626% | −0.330 | 45.5% | −1.89 | 0.0582 |
| Fell 0.5-1pt | 37 | +0.1345% | +0.226 | 64.9% | +1.37 | 0.1700 |
| Flat (±0.5pt) | 93 | −0.0919% | −0.129 | 52.7% | −1.25 | 0.2126 |
| Rose 0.5-1pt | 41 | −0.0224% | −0.048 | 31.7% | −0.31 | 0.7590 |
| Rose 1-2pts | 18 | +0.0527% | +0.042 | 66.7% | +0.18 | 0.8571 |
| Rose >2pts | 28 | +0.7809% | +0.364 | 71.4% | +1.92 | 0.0542 |

**ANOVA F = 3.603 (df 6,264)** — the strongest F-stat of any strict signal tested.

Interesting: VIX rose >2pts yesterday → +0.78% mean, 71.4% WR (p=0.054). This
is a **mean-reversion** pattern: big VIX spike → next-day bounce. However:
- N=28 is small
- p=0.054 is marginal
- Split-sample needed (see below)

---

## 4. Combined Model (strict no-lookahead)

Signal A: 3d VIX momentum (vix_prior[i] - vix_prior[i-3])
- < −1 → FAVORABLE (+1)
- > +1 → UNFAVORABLE (−1)
- else → NEUTRAL (0)

Signal B: Gap × VIX interaction
- Gap down >0.3% AND VIX ≥ 25 → UNFAVORABLE (−1)
- Gap up >0.3% AND VIX < 20 → FAVORABLE (+1)
- else → NEUTRAL (0)

Combined score = Signal A + Signal B → FAVORABLE (≥1) / NEUTRAL (0) / UNFAVORABLE (≤−1)

### Signal B distribution

| Signal B | Days | Pct |
|----------|-----:|----:|
| FAVORABLE (+1) | 44 | 16.4% |
| NEUTRAL (0) | 217 | 80.7% |
| UNFAVORABLE (−1) | 8 | 3.0% |

Signal B fires infrequently — only 19% of days have a non-neutral Gap×VIX signal.

### Combined model results

| Regime | Days | Mean Return | Std | Sharpe | WR | t-stat | p-value |
|--------|-----:|----------:|----:|-------:|---:|-------:|--------:|
| FAVORABLE | 99 | −0.0354% | 0.6392% | −0.055 | 53.5% | −0.55 | 0.5812 |
| NEUTRAL | 105 | −0.0678% | 0.6655% | −0.102 | 44.8% | −1.04 | 0.2963 |
| UNFAVORABLE | 65 | +0.2693% | 1.6827% | +0.160 | 60.0% | +1.29 | 0.1970 |

### Model comparison (all strict no-lookahead)

| Model | FAV Mean | UNFAV Mean | Spread | FAV Sharpe | UNFAV Sharpe |
|-------|------:|-------:|-------:|------:|-------:|
| 3d momentum only | −0.005% | +0.211% | −0.216% | −0.008 | +0.133 |
| Combined | −0.035% | +0.269% | −0.305% | −0.055 | +0.160 |
| **Improvement** | — | — | **−0.089%** | — | — |

The combined model has a **worse** spread than 3d momentum alone. Adding Gap×VIX
makes the FAVORABLE bucket slightly more negative. The spread is INVERTED in
both models (UNFAVORABLE outperforms FAVORABLE).

**Combined model does NOT beat single-factor. Not worth the complexity.**

---

## 5. Split-Sample Validation

Split: first 134 days (2025-02-14 to 2025-08-27) vs last 135 days (2025-08-28 to 2026-03-12)

### 3D VIX Momentum (5-bucket, strict) — Split-Sample

| Bucket | Full | N | 1st Half | N | 2nd Half | N | Stable? |
|--------|-----:|--:|--------:|--:|--------:|--:|:-------:|
| Falling >3pts | +0.090% | 28 | +0.111% | 18 | +0.052% | 10 | YES |
| Falling 1-3pts | −0.054% | 54 | +0.030% | 30 | −0.159% | 24 | NO |
| Flat (±1pt) | −0.076% | 111 | −0.108% | 52 | −0.047% | 59 | YES |
| Rising 1-3pts | +0.057% | 45 | +0.065% | 18 | +0.051% | 27 | YES |
| Rising >3pts | +0.424% | 31 | +0.637% | 16 | +0.196% | 15 | YES |

4 of 5 buckets stable (same sign both halves). Rising >3pts is the most
consistent bucket: positive in both halves. BUT the magnitude drops from
+0.637% to +0.196% (−69%), suggesting decay or small-sample noise.

### 3D VIX Momentum (3-bucket, strict) — Split-Sample

| Regime | Full Mean | Sharpe | 1st Half | N | 2nd Half | N | Stable? |
|--------|--------:|-------:|--------:|--:|--------:|--:|:-------:|
| FAVORABLE | −0.005% | −0.008 | +0.060% | 48 | −0.097% | 34 | **NO** |
| NEUTRAL | −0.076% | −0.115 | −0.108% | 52 | −0.049% | 60 | YES |
| UNFAVORABLE | +0.211% | +0.133 | +0.334% | 34 | +0.109% | 41 | YES |

FAVORABLE is **unstable** (flips sign). UNFAVORABLE is stable but decays
from +0.334% to +0.109% (−67%).

### Combined Model (strict) — Split-Sample

| Regime | Full Mean | Sharpe | 1st Half | N | 2nd Half | N | Stable? |
|--------|--------:|-------:|--------:|--:|--------:|--:|:-------:|
| FAVORABLE | −0.035% | −0.055 | +0.008% | 53 | −0.086% | 46 | **NO** |
| NEUTRAL | −0.068% | −0.102 | −0.071% | 50 | −0.065% | 55 | YES |
| UNFAVORABLE | +0.269% | +0.160 | +0.379% | 31 | +0.169% | 34 | YES |

Same pattern: FAVORABLE unstable, UNFAVORABLE stable but decaying.

### VIX Level Baseline — Split-Sample

| VIX Level | Full Mean | Sharpe | 1st Half | N | 2nd Half | N | Stable? |
|-----------|--------:|-------:|--------:|--:|--------:|--:|:-------:|
| <16 | −0.030% | −0.072 | −0.072% | 25 | −0.003% | 39 | YES |
| 16-20 | −0.069% | −0.106 | −0.028% | 60 | −0.105% | 70 | YES |
| 20-25 | +0.216% | +0.249 | +0.272% | 33 | +0.136% | 23 | YES |
| ≥25 | +0.341% | +0.124 | +0.259% | 18 | +0.712% | 4 | YES |

**VIX level is the MOST stable signal**: all 4 buckets maintain sign in both
halves. However, none are statistically significant (best p=0.063 for VIX 20-25).

---

## 6. Summary & Verdict

### What we tested (all strict no-lookahead)

| Signal | ANOVA F | Significant? | Split-Sample Stable? | Verdict |
|--------|:-------:|:------------:|:--------------------:|---------|
| VIX level (C1 baseline) | 1.861 | NO | **4/4 buckets** | Most stable, not predictive |
| 3d VIX momentum (strict) | 1.624 | NO | 2/3 regimes | Signal inverted from C2 |
| 1d prior-day VIX change | 3.603 | marginal | — (not tested) | Interesting but thin |
| Combined (3d + Gap×VIX) | — | NO | 2/3 regimes | Worse than single-factor |
| C2's 3d momentum (lookahead) | 7.301 | YES* | — | **INVALID — lookahead bug** |

### Key conclusions

1. **C2's primary signal (3d VIX momentum, p=0.0002) was an artifact of
   lookahead bias.** Using same-day VIX close creates a tautological signal
   (VIX and SPY have r=−0.723 contemporaneously). Corrected to strict
   no-lookahead, the signal collapses (F drops 4.5x, p goes from 0.0002 to ~0.17).

2. **No daily VIX-based signal provides statistically significant regime
   separation** when properly tested with no-lookahead data.

3. **VIX level is the most stable signal** (4/4 buckets stable in split-sample)
   but predicts **range, not direction**. It is suitable for position sizing
   and stop distances, not for entry/exit decisions.

4. **The combined model makes things worse**, not better. Adding Gap×VIX
   to 3d momentum widens the spread in the wrong direction.

5. **1d prior-day VIX change shows marginal mean-reversion** (VIX spike
   yesterday → bounce today, p=0.054). This merits further investigation
   with more data but is too thin (N=28) to build a state machine on.

### Recommendation for C3b (State Machine)

**Override 4.0 should NOT include a daily VIX-momentum backdrop component.**

The state machine should be:
- **CLEAR / CAUTION / RESTRICTED**: Based on VIX level only (for range/sizing context)
- **SUSPENDED**: Event + GeoStress quarantine (unchanged from 3.1)
- No daily VIX change component — the data does not support it
- Future: acquire VIX3M data for term structure testing (untested, academically strongest)
