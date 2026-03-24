# Override 4.1 — VIX/VIX3M Term Structure + 1d VIX Change Results

**Date:** 2026-03-24

## 1. VIX/VIX3M Term Structure (Part 1)

**Source:** FRED VXVCLS (VIX3M), merged with SPY daily returns (272 days)
**Signal:** prior-day VIX / prior-day VIX3M ratio (NO lookahead)

### Ratio Bucket → SPY Next-Day Returns

| Ratio Bucket | State | Days | Mean % | Median % | WR % | Sharpe | t-stat | p-value |
|:------------|:------|-----:|-------:|---------:|-----:|-------:|-------:|--------:|
| < 0.85 | Deep contango | 81 | -0.066 | -0.036 | 45.7 | -2.08 | -1.178 | 0.2390 |
| 0.85–0.92 | Contango | 105 | +0.034 | +0.082 | 54.3 | +0.92 | +0.596 | 0.5510 |
| 0.92–0.97 | Mild contango | 37 | +0.123 | +0.196 | 64.9 | +2.69 | +1.030 | 0.3031 |
| 0.97–1.03 | Flat | 31 | +0.037 | +0.175 | 54.8 | +0.51 | +0.180 | 0.8570 |
| 1.03–1.10 | Backwardation | 12 | -0.337 | -0.490 | 33.3 | -3.75 | -0.818 | 0.4136 |
| > 1.10 | Deep backwardation | 6 | +1.455 | +0.745 | 50.0 | +4.69 | +0.724 | 0.4693 |

**ANOVA:** F = 3.058, p = 0.0213 (significant at p < 0.05)

### Ratio → Intraday Range

| Ratio Bucket | Days | Mean Range % | Median Range % |
|:------------|-----:|-------------:|---------------:|
| < 0.85 | 81 | 0.756 | 0.639 |
| 0.85–0.92 | 105 | 1.006 | 0.875 |
| 0.92–0.97 | 37 | 1.304 | 1.226 |
| 0.97–1.03 | 31 | 1.703 | 1.547 |
| 1.03–1.10 | 12 | 2.244 | 2.094 |
| > 1.10 | 6 | 5.953 | 5.713 |

**ANOVA (Range):** F = 60.501, p < 0.0001 (extremely significant)

## 2. Cross-Tab: VIX Level × Term Structure (P2a)

| | Contango (<0.95) | Flat (0.95–1.05) | Backwardation (>1.05) |
|:---------|:-----------------|:-----------------|:----------------------|
| **VIX <20** | -0.034%, WR=50%, N=187 | -0.651%, WR=29%, N=7 | — (N=0) |
| **VIX 20-25** | +0.354%, WR=76%, N=21 | +0.133%, WR=60%, N=35 | — (N=0) |
| **VIX >=25** | — (N=0) | +0.030%, WR=50%, N=10 | +0.600%, WR=42%, N=12 |

### Key Insight
VIX level and term structure are **structurally confounded:**
- VIX <20 → almost always contango (96% of days)
- VIX >=25 → never contango (0% of days)
- 3 of 9 cells are empty — interaction test impossible
- The ratio's ANOVA significance (p=0.021) is largely because the ratio is a **proxy for VIX level**, not independent information
- **Best cell:** VIX 20-25 + Contango = +0.354%, WR=76%, t=2.83, p=0.005 (N=21)
  - But this may be a small-sample artifact

## 3. 1d Prior VIX Change — Split-Sample (P2b)

**Signal:** prior_vix_change = VIX(t-1) − VIX(t-2) (NO lookahead)

### Full Sample (2pt threshold)

| 1d VIX Change | Days | Mean SPY % | WR % | Sharpe | t-stat | p-value |
|:-------------|-----:|-----------:|-----:|-------:|-------:|--------:|
| Fell >2.0pts | 21 | -0.063 | 38.1 | -1.20 | -0.347 | 0.7289 |
| Fell 1.0-2.0pts | 33 | -0.263 | 45.5 | -5.24 | -1.895 | 0.0582 |
| Flat (±1.0pt) | 171 | -0.026 | 50.3 | -0.65 | -0.537 | 0.5915 |
| Rose 1.0-2.0pts | 18 | +0.053 | 66.7 | +0.67 | +0.180 | 0.8571 |
| Rose >2.0pts | 28 | +0.781 | 71.4 | +5.77 | +1.925 | 0.0542 |

**ANOVA:** F = 5.062, p = 0.0014

### Split-Sample Stability

- First half: 135 days (2025-02-12 to 2025-08-26)
- Second half: 136 days (2025-08-27 to 2026-03-12)

| Bucket | Full Mean % | H1 Mean % | H2 Mean % | H1 N | H2 N | Sign Flip? |
|:-------|----------:|---------:|---------:|----:|----:|:----------|
| Fell >2.0pts | -0.063 | -0.335 | +0.299 | 12 | 9 | **YES** |
| Fell 1.0-2.0pts | -0.263 | -0.249 | -0.281 | 19 | 14 | No |
| Flat (±1.0pt) | -0.026 | +0.062 | -0.108 | 82 | 89 | **YES** |
| Rose 1.0-2.0pts | +0.053 | -0.564 | +0.361 | 6 | 12 | **YES** |
| Rose >2.0pts | +0.781 | +1.054 | +0.416 | 16 | 12 | No |

Sign flips: **3/5** testable buckets

### Threshold Robustness

| Threshold | ANOVA F | p-value | Fell>X: N, Mean | Rose>X: N, Mean |
|----------:|--------:|--------:|:----------------|:----------------|
| 1.5pt | 3.244 | 0.0256 | N=35, -0.025% | N=35, +0.556% |
| 2.0pt | 5.062 | 0.0014 | N=21, -0.063% | N=28, +0.781% |
| 2.5pt | 3.933 | 0.0084 | N=17, -0.145% | N=23, +0.794% |

## 4. VERDICT

### VIX/VIX3M Term Structure
- ANOVA significant? **Yes** (F=3.058, p=0.021)
- Independent of VIX level? **No** — ratio is confounded with VIX level
  - VIX <20 ≈ contango, VIX >=25 ≈ backwardation (structural link)
  - Cross-tab has 3 empty cells; interaction test impossible
- Range prediction? **Yes** (F=60.5, p<0.0001) — but VIX level alone does this too
- **Adds value beyond VIX level? NO** — the ratio is a redundant proxy at daily frequency
  - May have intraday value (contango slope changes intraday) — test when IB data available

### 1d Prior VIX Change
- ANOVA significant? **Yes** (F=5.062, p=0.0014)
- Split-sample stable? **No** (3/5 sign flips)
- Post-VIX-drop rebound survives? **No**
- Post-VIX-spike selling survives? **No**
- **Verdict: Unstable across halves — discard as unreliable**

### Override Recommendation

**Keep Override 4.0 unchanged**

Neither term structure (confounded) nor 1d VIX change (insufficient evidence) justify modifying the existing Override 4.0 design. The VIX level hazard veto + context sizing remains the best available model.

| Option | Status |
|:-------|:-------|
| Keep 4.0 unchanged (hazard veto + sizing only) | **SELECTED** |
| Upgrade to 4.1 (add term structure layer) | Rejected — confounded with VIX level |
| Upgrade to 4.1 (add 1d VIX rebound flag) | Pending further data |
| Both additions | Rejected |

**Confidence:** high

### What Would Change Our Mind
- **Term structure:** Intraday VIX/VIX3M data from IB could reveal intraday slope changes that matter for entry timing
- **1d VIX change:** More data (>500 days) with consistent split-sample results would promote this to a hard signal
- **VIX futures term structure (VX1/VX2):** More granular than VIX/VIX3M — acquire from IB when available

---
*Generated by p2b_vix_change_verdict.py*

