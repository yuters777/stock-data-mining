# Phase 1 OOS Event Study — compression_score Validation (2025)

**Test window:** 2025-01-01 to 2025-12-31  
**Computed:** 2026-04-18T21:32:05Z  
**Baseline SHA:** SHA mismatch — local fallback baseline (not canonical 2023-2024)  
**Recommendation:** **SHELVE_M8_PHASE_B_GATE_MAY_STILL_PROCEED**

## Executive Summary

23/23 tickers had 2025 data. 5170 valid sessions (113 rejected as incomplete). Deep-compression bucket (earnings-excluded): N=47, breakout_rate=12.8% vs neutral 5.4%. Kill-switch verdict: **SHELVE_M8_PHASE_B_GATE_MAY_STILL_PROCEED**.

## Bucket Results

| Bucket | Version | N | Breakout% | MeanRet% | SPYAdj% | MFE p50 | MFE p90 | MAE p50 | MAE p90 |
|--------|---------|---|-----------|----------|---------|---------|---------|---------|---------|
| deep | full | 50 | 12.0% | -0.006 | -0.011 | 0.081 | 0.355 | -0.059 | 0.020 |
| deep | earnings_excluded | 47 | 12.8% | 0.015 | 0.006 | 0.082 | 0.362 | -0.052 | 0.022 |
| deep | earnings_and_hi_day_excluded | 40 | 15.0% | 0.016 | 0.009 | 0.073 | 0.347 | -0.051 | 0.029 |
| neutral | full | 4669 | 5.4% | 0.003 | -0.023 | 0.186 | 0.882 | -0.197 | 0.004 |
| neutral | earnings_excluded | 4035 | 5.4% | 0.001 | -0.023 | 0.184 | 0.883 | -0.194 | 0.005 |
| neutral | earnings_and_hi_day_excluded | 3556 | 5.4% | 0.004 | -0.024 | 0.182 | 0.841 | -0.190 | 0.008 |
| active | full | 451 | 5.3% | 0.052 | 0.014 | 0.328 | 1.286 | -0.300 | 0.019 |
| active | earnings_excluded | 401 | 5.0% | 0.062 | 0.023 | 0.306 | 1.286 | -0.260 | 0.019 |
| active | earnings_and_hi_day_excluded | 347 | 4.9% | 0.075 | 0.027 | 0.306 | 1.214 | -0.260 | 0.018 |

## Kill-Switch Verdict

| Criterion | Result |
|-----------|--------|
| deep_breakout_gt_neutral_breakout | **PASS** |
| deep_spy_adj_return_gt_neutral_spy_adj | **PASS** |
| deep_n_gte_40 | **PASS** |
| deep_breakout_rate_gte_20pct | FAIL |

**All-pass → SHELVE_M8_PHASE_B_GATE_MAY_STILL_PROCEED**

## Per-Ticker Session Counts

| Ticker | Deep | Neutral | Active |
|--------|------|---------|--------|
| AAPL | 0 | 80 | 0 |
| AMD | 0 | 234 | 0 |
| AMZN | 0 | 230 | 0 |
| AVGO | 0 | 233 | 0 |
| BA | 0 | 230 | 0 |
| BABA | 0 | 233 | 0 |
| BIDU | 0 | 230 | 0 |
| C | 0 | 228 | 0 |
| COIN | 0 | 231 | 0 |
| COST | 0 | 230 | 0 |
| GOOGL | 0 | 230 | 0 |
| GS | 0 | 229 | 0 |
| JPM | 0 | 230 | 0 |
| MARA | 0 | 235 | 0 |
| META | 0 | 230 | 0 |
| MSFT | 0 | 230 | 0 |
| MU | 0 | 234 | 0 |
| NVDA | 24 | 86 | 120 |
| PLTR | 0 | 237 | 0 |
| SPY | 26 | 73 | 133 |
| TSLA | 0 | 32 | 198 |
| TSM | 0 | 234 | 0 |
| V | 0 | 230 | 0 |

## Limitations

- **Baseline data:** The canonical 2023-2024 baseline (SHA `661975f5e7e5f061…`) was not available in this environment. A local fallback was used, computed from pre-2025 Z3 sessions in Fetched_Data. Tickers with fewer than 100 pre-2025 Z3 sessions received abstain score 0.50 (neutral bucket). Obtain the canonical baseline from CC-BASELINE-1 for production-grade kill-switch decisions.
- **News-based filters:** Skipped — not in local repo. Sprint 2 backtest to include.
- **Beige Book dates:** Not included in HIGH_IMPACT_DAYS_2025 (8×/year, mid-cycle).
- **SPY adjustment:** Computed when SPY data exists for same date; `mean_spy_adj_return_8bar` is None if SPY bars are missing.
- **Ticker coverage:** Tickers absent from local data/ or Fetched_Data/ are skipped.
