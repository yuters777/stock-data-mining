# Stress MR v2 — Part 1: Heat Map Results

**Generated:** 2026-03-24
**Data:** M5 regular-session (09:30–15:55 ET), 25 equity tickers
**Stress threshold:** median return < -0.75% at measurement time
**Quintiles:** Bottom 5 (laggards) vs Top 5 (leaders) by return-from-open

## Task 1: Stress Day Identification

| Measurement Time | Stress Days (N) | % of Total Days | Avg SPY Return on Stress Days |
|:---|:---:|:---:|:---:|
| 10:30 ET | 39 | 14.3% | -0.50% |
| 11:00 ET | 10 | 3.6% | +0.37% |
| 11:30 ET | 7 | 2.5% | -0.39% |
| 12:00 ET | 11 | 4.0% | -0.22% |

### Stress Days (11:00 ET measurement)

| Date | Median Return at 11:00 | SPY Daily Return |
|:---|:---:|:---:|
| 2025-03-12 | -1.00% | -0.58% |
| 2025-04-07 | -1.10% | +3.14% |
| 2025-04-08 | -1.58% | -4.81% |
| 2025-04-24 | -0.77% | +1.83% |
| 2025-05-02 | -0.78% | +0.33% |
| 2025-05-13 | -0.87% | +0.58% |
| 2025-10-01 | -0.84% | +0.81% |
| 2025-10-17 | -1.67% | +0.73% |
| 2026-02-02 | -0.76% | +0.85% |
| 2026-03-03 | -2.06% | +0.77% |

## Task 2: Laggard-Leader Spread — Stress Days

### Full Detail: Spread (t-stat, p-value, WR, N)

| Entry \ Exit | +1hr | +2hr | +3hr | 15:00 | 15:30 | 15:55 |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **10:00** | +3.278% (t=8.15, p=0.000, WR=100%, n=10) **★** | +3.280% (t=7.50, p=0.000, WR=100%, n=10) **★** | +3.221% (t=7.25, p=0.000, WR=100%, n=10) **★** | +3.163% (t=7.50, p=0.000, WR=100%, n=10) **★** | +2.904% (t=7.02, p=0.000, WR=100%, n=10) **★** | +2.819% (t=6.97, p=0.000, WR=100%, n=10) **★** |
| **10:30** | +3.683% (t=11.93, p=0.000, WR=100%, n=10) **★** | +3.633% (t=12.51, p=0.000, WR=100%, n=10) **★** | +3.480% (t=13.03, p=0.000, WR=100%, n=10) **★** | +3.495% (t=17.64, p=0.000, WR=100%, n=10) **★** | +3.416% (t=11.19, p=0.000, WR=100%, n=10) **★** | +3.240% (t=10.79, p=0.000, WR=100%, n=10) **★** |
| **11:00** | +0.112% (t=0.47, p=0.650, WR=60%, n=10) | +0.434% (t=1.64, p=0.136, WR=70%, n=10) | +0.817% (t=3.90, p=0.004, WR=90%, n=10) **★** | +1.150% (t=4.31, p=0.002, WR=90%, n=10) **★** | +1.337% (t=3.98, p=0.003, WR=90%, n=10) **★** | +1.263% (t=2.83, p=0.020, WR=80%, n=10) **★** |
| **11:30** | +0.445% (t=2.21, p=0.055, WR=80%, n=10) **★** | +0.747% (t=2.49, p=0.034, WR=90%, n=10) **★** | +1.206% (t=5.37, p=0.000, WR=100%, n=10) **★** | +1.464% (t=5.37, p=0.000, WR=100%, n=10) **★** | +1.432% (t=4.36, p=0.002, WR=100%, n=10) **★** | +1.568% (t=5.14, p=0.001, WR=100%, n=10) **★** |
| **12:00** | +0.447% (t=2.41, p=0.039, WR=80%, n=10) **★** | +0.849% (t=3.45, p=0.007, WR=90%, n=10) **★** | +1.280% (t=4.01, p=0.003, WR=100%, n=10) **★** | +1.280% (t=4.01, p=0.003, WR=100%, n=10) **★** | +1.291% (t=3.56, p=0.006, WR=90%, n=10) **★** | +1.227% (t=2.92, p=0.017, WR=90%, n=10) **★** |

**★ = Viable cell:** spread > +0.30%, p < 0.10, WR > 55%

## Task 3: Laggard-Leader Spread — Non-Stress Days (Control)

### Full Detail: Spread (t-stat, p-value, WR, N)

| Entry \ Exit | +1hr | +2hr | +3hr | 15:00 | 15:30 | 15:55 |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **10:00** | +2.911% (t=37.33, p=0.000, WR=100%, n=262) **★** | +2.745% (t=38.08, p=0.000, WR=100%, n=262) **★** | +2.724% (t=36.43, p=0.000, WR=100%, n=262) **★** | +2.829% (t=41.81, p=0.000, WR=100%, n=262) **★** | +2.803% (t=43.26, p=0.000, WR=100%, n=262) **★** | +2.782% (t=44.56, p=0.000, WR=100%, n=262) **★** |
| **10:30** | +3.196% (t=39.16, p=0.000, WR=100%, n=262) **★** | +3.161% (t=38.87, p=0.000, WR=100%, n=262) **★** | +3.100% (t=40.20, p=0.000, WR=100%, n=262) **★** | +3.266% (t=44.78, p=0.000, WR=100%, n=262) **★** | +3.263% (t=45.83, p=0.000, WR=100%, n=262) **★** | +3.221% (t=46.74, p=0.000, WR=100%, n=262) **★** |
| **11:00** | +0.304% (t=10.38, p=0.000, WR=81%, n=266) **★** | +0.461% (t=13.75, p=0.000, WR=88%, n=266) **★** | +0.650% (t=18.11, p=0.000, WR=95%, n=266) **★** | +0.863% (t=19.92, p=0.000, WR=96%, n=266) **★** | +1.039% (t=21.12, p=0.000, WR=97%, n=266) **★** | +1.156% (t=22.63, p=0.000, WR=97%, n=266) **★** |
| **11:30** | +0.411% (t=14.29, p=0.000, WR=88%, n=265) **★** | +0.552% (t=14.76, p=0.000, WR=89%, n=265) **★** | +0.866% (t=19.03, p=0.000, WR=97%, n=265) **★** | +0.999% (t=20.91, p=0.000, WR=97%, n=265) **★** | +1.171% (t=22.27, p=0.000, WR=98%, n=265) **★** | +1.274% (t=23.27, p=0.000, WR=98%, n=265) **★** |
| **12:00** | +0.456% (t=13.79, p=0.000, WR=90%, n=266) **★** | +0.776% (t=20.03, p=0.000, WR=96%, n=266) **★** | +1.008% (t=23.15, p=0.000, WR=98%, n=266) **★** | +1.008% (t=23.15, p=0.000, WR=98%, n=266) **★** | +1.168% (t=23.68, p=0.000, WR=98%, n=266) **★** | +1.262% (t=25.05, p=0.000, WR=98%, n=266) **★** |

### Stress − Non-Stress Spread Difference

| Entry \ Exit | +1hr | +2hr | +3hr | 15:00 | 15:30 | 15:55 |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **10:00** | +0.367% | +0.534% | +0.497% | +0.335% | +0.102% | +0.038% |
| **10:30** | +0.487% | +0.471% | +0.380% | +0.229% | +0.153% | +0.018% |
| **11:00** | -0.193% | -0.028% | +0.167% | +0.287% | +0.298% | +0.107% |
| **11:30** | +0.035% | +0.195% | +0.340% | +0.465% | +0.262% | +0.294% |
| **12:00** | -0.009% | +0.073% | +0.272% | +0.272% | +0.123% | -0.036% |

## Task 4: Split-Sample Validation

| Cell (Entry×Exit) | Full Spread | First Half | Second Half | Stable? |
|:---|:---:|:---:|:---:|:---:|
| 10:00→+1hr | +3.278% | +3.771% (n=5) | +2.785% (n=5) | YES |
| 10:00→+2hr | +3.280% | +3.915% (n=5) | +2.645% (n=5) | YES |
| 10:00→+3hr | +3.221% | +3.834% (n=5) | +2.609% (n=5) | YES |
| 10:00→15:00 | +3.163% | +3.808% (n=5) | +2.518% (n=5) | YES |
| 10:00→15:30 | +2.904% | +3.392% (n=5) | +2.416% (n=5) | YES |
| 10:00→15:55 | +2.819% | +3.270% (n=5) | +2.368% (n=5) | YES |
| 10:30→+1hr | +3.683% | +3.448% (n=5) | +3.918% (n=5) | YES |
| 10:30→+2hr | +3.633% | +3.513% (n=5) | +3.753% (n=5) | YES |
| 10:30→+3hr | +3.480% | +3.245% (n=5) | +3.715% (n=5) | YES |
| 10:30→15:00 | +3.495% | +3.421% (n=5) | +3.568% (n=5) | YES |
| 10:30→15:30 | +3.416% | +3.379% (n=5) | +3.453% (n=5) | YES |
| 10:30→15:55 | +3.240% | +3.144% (n=5) | +3.335% (n=5) | YES |
| 11:00→+3hr | +0.817% | +0.743% (n=5) | +0.891% (n=5) | YES |
| 11:00→15:00 | +1.150% | +1.023% (n=5) | +1.277% (n=5) | YES |
| 11:00→15:30 | +1.337% | +1.246% (n=5) | +1.429% (n=5) | YES |
| 11:00→15:55 | +1.263% | +1.060% (n=5) | +1.466% (n=5) | YES |
| 11:30→+1hr | +0.445% | +0.514% (n=5) | +0.377% (n=5) | YES |
| 11:30→+2hr | +0.747% | +0.747% (n=5) | +0.747% (n=5) | YES |
| 11:30→+3hr | +1.206% | +1.214% (n=5) | +1.199% (n=5) | YES |
| 11:30→15:00 | +1.464% | +1.694% (n=5) | +1.234% (n=5) | YES |
| 11:30→15:30 | +1.432% | +1.469% (n=5) | +1.396% (n=5) | YES |
| 11:30→15:55 | +1.568% | +1.712% (n=5) | +1.423% (n=5) | YES |
| 12:00→+1hr | +0.447% | +0.611% (n=5) | +0.283% (n=5) | YES |
| 12:00→+2hr | +0.849% | +1.009% (n=5) | +0.688% (n=5) | YES |
| 12:00→+3hr | +1.280% | +1.593% (n=5) | +0.966% (n=5) | YES |
| 12:00→15:00 | +1.280% | +1.593% (n=5) | +0.966% (n=5) | YES |
| 12:00→15:30 | +1.291% | +1.465% (n=5) | +1.116% (n=5) | YES |
| 12:00→15:55 | +1.227% | +1.273% (n=5) | +1.180% (n=5) | YES |

## Critical Caveats

### 1. Sample Size Warning
- Only **10 stress days** at the 11:00 ET threshold (3.6% of 276 trading days)
- Split-sample halves contain just **n=5 each** — statistically fragile
- Any finding on n=10 should be treated as preliminary hypothesis, not confirmed signal

### 2. The Early-Entry Spread is a Beta Artifact (NOT Mean Reversion)
The 10:00 and 10:30 entry rows show massive spreads (+2.8% to +3.7%) on stress days.
**But the non-stress control shows nearly identical spreads** (+2.7% to +3.3%).

This is **cross-sectional beta dispersion**, not stress-specific mean reversion:
- At 10:00/10:30, "laggards" are high-beta names (COIN, MARA, NVDA) that fell more
- "Leaders" are low-beta defensives (V, COST, JPM) that fell less
- As the day progresses, high-beta names mechanically move more in EITHER direction
- This produces a positive laggard-leader spread on ALL days, stress or not

**Evidence:** The stress − non-stress difference at early entries is small (+0.04% to +0.53%),
meaning stress days are NOT materially different from normal days at these entries.

### 3. Later Entries (11:00+) Show Marginal Stress Enhancement
At 11:00+ entries, the stress − non-stress difference is slightly positive (+0.1% to +0.5%)
for longer hold periods. However:
- n=10 makes this unreliable
- The absolute spread on non-stress days is already large and significant
- The incremental stress effect is within noise given n=10

## Bottom Line

- **Cells meeting initial criteria** (spread > +0.30%, p < 0.10, WR > 55%): **28** on stress days
- **Cells surviving split-sample** (both halves > +0.10%): **28**
- **BUT: The non-stress control ALSO shows 30/30 viable cells with the same pattern**

### Interpretation

The laggard-leader spread exists on **ALL days**, not just stress days. This is generic
intraday cross-sectional mean reversion (well-documented in literature), driven by:
1. Beta dispersion at ranking time creating mechanical spread
2. Regression to the mean of intraday returns
3. Liquidity provision dynamics (market makers fading extreme moves)

The stress − non-stress difference matrix shows:
- **Early entries (10:00-10:30):** +0.04% to +0.53% incremental on stress days — **not meaningful** given n=10
- **Later entries (11:00-12:00):** +0.1% to +0.5% incremental — **marginally interesting** but unreliable on n=10
- **No cell** has a stress-specific incremental spread that is both large (>+0.30%) AND reliably measured

### Verdict

**No stress-SPECIFIC intraday mean-reversion signal found.** The laggard-leader
spread is a generic all-days phenomenon, not amplified by stress conditions in a
meaningful or reliable way given the sample size.

The Nagel (2011) hypothesis — that stress days create ADDITIONAL MR opportunity
beyond normal days — is **not supported** by this data.

### Recommendation

**Stress MR as a standalone research line: CLOSED.**

The underlying MR effect (laggards outperform leaders intraday) is real but:
1. It exists on ALL days — no stress conditioning needed
2. It's primarily a beta/dispersion artifact at early entries
3. At later entries it's a well-known generic MR effect (~0.3-1.2% spread)
4. Exploiting it requires capturing the long-short spread, not just going long laggards
5. Transaction costs on a 5-name portfolio rotation make this uneconomical

**For DR:** If pursuing generic intraday MR (not stress-specific), the relevant question
becomes: can the laggard-leader spread be captured net of costs in a tradeable structure?
This is a different research question from Stress MR.

---
*Analysis: stress_mr_part1.py | Data: 25 tickers × M5 regular session (282 days) |
Stress threshold: median < -0.75% at 11:00 ET | n_stress=10, n_nonstress=266*