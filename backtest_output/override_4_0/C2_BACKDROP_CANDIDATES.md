# C2: Override 4.0 — Backdrop Candidates

**Date:** 2026-03-24
**Data:** 272 trading days from spy_daily_returns.csv
**Method:** All predictors use PRIOR-day data only (no lookahead)

---

## 1. Multi-Day VIX Momentum

VIX change over N prior trading days → next-day SPY open-to-close return.

### 3-Day VIX Change

| VIX 3d change | Days | Mean SPY Return | Median | Std | Sharpe | WR (>0) | t-stat | p-value |
|──────────────────|-----:|----------------:|-------:|----:|-------:|--------:|-------:|--------:|
| Falling >3pts | 27 | +0.5500% | +0.2130% | 2.0031% | +0.275 | 59.3% | +1.43 | 0.1537 |
| Falling 1-3pts | 54 | +0.1865% | +0.2874% | 0.5209% | +0.358 | 70.4% | +2.63 | 0.0085 |
| Flat (±1pt) | 117 | +0.1140% | +0.0833% | 0.4712% | +0.242 | 53.0% | +2.62 | 0.0089 |
| Rising 1-3pts | 41 | -0.2521% | -0.2268% | 0.6956% | -0.362 | 34.1% | -2.32 | 0.0203 |
| Rising >3pts | 31 | -0.6516% | -0.5515% | 1.6555% | -0.394 | 32.3% | -2.19 | 0.0284 |

**ANOVA F=7.301, p=0.0002**

### 5-Day VIX Change

| VIX 5d change | Days | Mean SPY Return | Median | Std | Sharpe | WR (>0) | t-stat | p-value |
|──────────────────|-----:|----------------:|-------:|----:|-------:|--------:|-------:|--------:|
| Falling >3pts | 38 | +0.3383% | +0.3014% | 0.6328% | +0.535 | 76.3% | +3.30 | 0.0010 |
| Falling 1-3pts | 46 | +0.0900% | +0.1169% | 0.4323% | +0.208 | 60.9% | +1.41 | 0.1580 |
| Flat (±1pt) | 96 | +0.0495% | +0.0553% | 0.6078% | +0.081 | 51.0% | +0.80 | 0.4254 |
| Rising 1-3pts | 46 | -0.0967% | -0.1365% | 0.6134% | -0.158 | 41.3% | -1.07 | 0.2849 |
| Rising >3pts | 42 | -0.2466% | -0.4168% | 2.1495% | -0.115 | 33.3% | -0.74 | 0.4573 |

**ANOVA F=1.928, p=0.1022**

### 10-Day VIX Change

| VIX 10d change | Days | Mean SPY Return | Median | Std | Sharpe | WR (>0) | t-stat | p-value |
|──────────────────|-----:|----------------:|-------:|----:|-------:|--------:|-------:|--------:|
| Falling >3pts | 49 | +0.1791% | +0.1066% | 0.5933% | +0.302 | 63.3% | +2.11 | 0.0346 |
| Falling 1-3pts | 42 | +0.0068% | -0.0423% | 0.4612% | +0.015 | 45.2% | +0.10 | 0.9243 |
| Flat (±1pt) | 74 | +0.0928% | +0.1530% | 0.4774% | +0.194 | 60.8% | +1.67 | 0.0946 |
| Rising 1-3pts | 49 | +0.1807% | +0.1526% | 0.6546% | +0.276 | 57.1% | +1.93 | 0.0533 |
| Rising >3pts | 50 | -0.3336% | -0.4844% | 2.0087% | -0.166 | 28.0% | -1.17 | 0.2403 |

**ANOVA F=2.268, p=0.0552**

## 2. VIX/VIX3M Term Structure

**SKIPPED — VIX3M data not available in repo.**

Per C1 data inventory: VIX3M_FRED.csv and VIX3M_data.csv do not exist.
This is S32's top-recommended signal. Acquiring VIX3M data should be a priority.

## 3. Variance Risk Premium (VRP)

VRP = VIX_close − Realized_Vol_5d, where RV_5d = std(daily_returns, window=5) × √252 × 100

**S32 caveat:** Academic literature finds VRP predictive at quarterly horizons. Daily may be noise.

| VRP Bucket | Days | Mean SPY Return | Median | Std | Sharpe | WR (>0) | t-stat | p-value |
|────────────────|-----:|----------------:|-------:|----:|-------:|--------:|-------:|--------:|
| High (>10) | 114 | +0.0068% | -0.0195% | 0.6232% | +0.011 | 48.2% | +0.12 | 0.9076 |
| Normal (5-10) | 109 | +0.0454% | +0.1271% | 0.8101% | +0.056 | 55.0% | +0.59 | 0.5585 |
| Low (0-5) | 26 | -0.2190% | +0.1551% | 1.2578% | -0.174 | 57.7% | -0.89 | 0.3747 |
| Negative (<0) | 18 | +0.3778% | -0.2563% | 2.5924% | +0.146 | 44.4% | +0.62 | 0.5364 |

**ANOVA F=1.263, p=0.2731**

### VRP Distribution

| Metric | Value |
|--------|------:|
| Mean VRP | 7.69 |
| Median VRP | 9.45 |
| Std VRP | 9.37 |
| Min VRP | -60.39 |
| Max VRP | 25.58 |
| Days VRP < 0 | 18 (6.7%) |

## 4. Gap × VIX Interaction

Gap = (today_open − yesterday_close) / yesterday_close × 100
Return = open-to-close return on the gap day

### Mean Intraday Return by Gap × VIX

| Gap Bucket | VIX <20 | VIX 20-25 | VIX ≥25 | All VIX |
|---|---|---|---|---|
| Gap up >1% | +0.356% (N=3) | -0.156% (N=5) | -1.094% (N=5) | -0.399% (N=13) |
| Gap up 0.3-1% | -0.182% (N=41) | +0.229% (N=12) | +0.551% (N=1) | -0.077% (N=54) |
| Flat ±0.3% | -0.045% (N=118) | +0.339% (N=22) | +1.623% (N=8) | +0.102% (N=148) |
| Gap down 0.3-1% | -0.002% (N=26) | +0.060% (N=9) | +0.526% (N=4) | +0.066% (N=39) |
| Gap down >1% | +0.095% (N=5) | +0.267% (N=8) | -0.667% (N=4) | -0.003% (N=17) |

**Cross-tabulation ANOVA F=2.954, p=0.0246**

### Detailed Gap × VIX Stats

| Gap Bucket | VIX Regime | N | Mean | Sharpe | WR | t-stat | p-value |
|------------|------------|--:|-----:|-------:|---:|-------:|--------:|
| Gap up >1% | VIX <20 | 3 | +0.3564% | +1.148 | 66.7% | +1.99 | 0.0468 |
| Gap up >1% | VIX 20-25 | 5 | -0.1560% | -0.094 | 80.0% | -0.21 | 0.8340 |
| Gap up >1% | VIX ≥25 | 5 | -1.0942% | -0.504 | 20.0% | -1.13 | 0.2600 |
| Gap up 0.3-1% | VIX <20 | 41 | -0.1822% | -0.265 | 48.8% | -1.69 | 0.0902 |
| Gap up 0.3-1% | VIX 20-25 | 12 | +0.2294% | +0.407 | 66.7% | +1.41 | 0.1587 |
| Gap up 0.3-1% | VIX ≥25 | 1 | — | — | — | — | — |
| Flat ±0.3% | VIX <20 | 118 | -0.0448% | -0.083 | 45.8% | -0.91 | 0.3651 |
| Flat ±0.3% | VIX 20-25 | 22 | +0.3392% | +0.494 | 72.7% | +2.32 | 0.0205 |
| Flat ±0.3% | VIX ≥25 | 8 | +1.6231% | +0.485 | 62.5% | +1.37 | 0.1701 |
| Gap down 0.3-1% | VIX <20 | 26 | -0.0022% | -0.003 | 57.7% | -0.02 | 0.9861 |
| Gap down 0.3-1% | VIX 20-25 | 9 | +0.0600% | +0.089 | 44.4% | +0.27 | 0.7893 |
| Gap down 0.3-1% | VIX ≥25 | 4 | +0.5263% | +0.306 | 50.0% | +0.61 | 0.5399 |
| Gap down >1% | VIX <20 | 5 | +0.0948% | +0.135 | 60.0% | +0.30 | 0.7626 |
| Gap down >1% | VIX 20-25 | 8 | +0.2669% | +0.203 | 62.5% | +0.57 | 0.5664 |
| Gap down >1% | VIX ≥25 | 4 | -0.6672% | -0.226 | 25.0% | -0.45 | 0.6507 |

### Gap Effect (marginal, all VIX levels)

| Gap Bucket | Days | Mean Return | Sharpe | WR | t-stat | p-value |
|------------|-----:|----------:|-------:|---:|-------:|--------:|
| Gap up >1% | 13 | -0.3986% | -0.235 | 53.8% | -0.85 | 0.3971 |
| Gap up 0.3-1% | 54 | -0.0772% | -0.114 | 53.7% | -0.84 | 0.4036 |
| Flat ±0.3% | 148 | +0.1024% | +0.103 | 50.7% | +1.26 | 0.2084 |
| Gap down 0.3-1% | 39 | +0.0664% | +0.084 | 53.8% | +0.52 | 0.6002 |
| Gap down >1% | 17 | -0.0035% | -0.002 | 52.9% | -0.01 | 0.9930 |

**Gap ANOVA F=0.951, p=0.4131**

## 5. Candidate Ranking

| Rank | Candidate | Best Bucket | Best Sharpe | F-stat | F p-value | vs Baseline |
|-----:|-----------|-------------|:----------:|:------:|:---------:|:-----------:|
| 1 | VIX 5d momentum | Falling >3pts | +0.535 | 1.928 | 0.1022 | +0.286 |
| 2 | Gap × VIX interaction | Gap up >1% × VIX ≥25 | -0.504 | 2.954 | 0.0246 | -0.753 |
| 3 | VIX 3d momentum | Rising >3pts | -0.394 | 7.301 | 0.0002 | -0.643 |
| 4 | VIX 10d momentum | Falling >3pts | +0.302 | 2.268 | 0.0552 | +0.053 |
| 5 | VIX level (C1 baseline) | VIX 20-25 | +0.249 | 1.500 | 0.2000 | — |
| 6 | Gap (marginal) | Gap up >1% | -0.235 | 0.951 | 0.4131 | -0.484 |
| 7 | VRP (5d realized vol) | Low (0-5) | -0.174 | 1.263 | 0.2731 | -0.423 |
| 8 | VIX/VIX3M term structure | N/A | — | — | — | DATA UNAVAILABLE |

## 6. Findings & Recommendations

### Near-Significant Results (p < 0.10)

- VIX 3d Falling 1-3pts: mean=+0.1865%, p=0.0085, N=54
- VIX 3d Flat (±1pt): mean=+0.1140%, p=0.0089, N=117
- VIX 3d Rising 1-3pts: mean=-0.2521%, p=0.0203, N=41
- VIX 3d Rising >3pts: mean=-0.6516%, p=0.0284, N=31
- VIX 5d Falling >3pts: mean=+0.3383%, p=0.0010, N=38
- VIX 10d Falling >3pts: mean=+0.1791%, p=0.0346, N=49
- VIX 10d Flat (±1pt): mean=+0.0928%, p=0.0946, N=74
- VIX 10d Rising 1-3pts: mean=+0.1807%, p=0.0533, N=49

### ANOVA Summary (do regimes explain return variance?)

| Candidate | F-stat | p-value | Significant? |
|-----------|:------:|:-------:|:------------:|
| VIX 3d momentum | 7.301 | 0.0002 | YES |
| VIX 5d momentum | 1.928 | 0.1022 | NO |
| VIX 10d momentum | 2.268 | 0.0552 | marginal |
| VRP | 1.263 | 0.2731 | NO |
| Gap (marginal) | 0.951 | 0.4131 | NO |
| Gap × VIX | 2.954 | 0.0246 | YES |

### Key Findings

**3-day VIX momentum is the clear winner:**
- ANOVA F=7.30, **p=0.0002** — highly significant regime separation
- Monotonic pattern: VIX falling → SPY positive, VIX rising → SPY negative
- 4 of 5 buckets individually significant (p<0.05)
- VIX rising >3pts in 3d: mean **-0.65%**, WR 32.3%, Sharpe -0.394
- VIX falling 1-3pts in 3d: mean **+0.19%**, WR 70.4%, Sharpe +0.358

**5-day VIX momentum shows strongest single bucket:**
- Falling >3pts: mean **+0.34%**, WR 76.3%, **p=0.001**, Sharpe +0.535
- But overall ANOVA only marginal (p=0.10) — spread concentrated in extremes

**Gap × VIX interaction is significant (ANOVA p=0.025)** but Gap alone is not
(p=0.41) — VIX context changes gap-day behavior.

**VRP is noise at daily frequency** (ANOVA p=0.27), confirming S32 caveat.

### Recommendations for C3

1. **PRIMARY SIGNAL: 3-day VIX momentum.** Strongest ANOVA (p=0.0002), monotonic
   pattern, multiple significant buckets. This should be the core of Override 4.0.
   - When VIX has risen >3pts in 3 days → bearish bias (or sit out)
   - When VIX has fallen 1-3pts in 3 days → bullish bias

2. **SECONDARY SIGNAL: 5-day VIX momentum.** VIX falling >3pts over 5d is the
   single best bucket (Sharpe +0.535, p=0.001). Use as confirmation for 3d signal.

3. **CONTEXT: VIX level (from C1).** VIX predicts RANGE not direction.
   Use for position sizing: scale down when VIX >25, widen stops when VIX >20.

4. **INTERACTION: Gap × VIX.** Significant as a cross-tabulation. Worth exploring
   in C3 as a filter layer on top of VIX momentum.

5. **SKIP: VRP.** Daily VRP is noise. Do not include.

6. **ACQUIRE: VIX3M data.** Term structure remains the academically strongest signal
   but is unavailable. High priority for future data acquisition.

**Bottom line:** 3-day VIX momentum **decisively beats** the VIX level baseline.
G1 killed *daily* VIX change (1-day) — but *multi-day* VIX momentum (3-day) is
a fundamentally different and much stronger signal. This is the Override 4.0 backbone.
