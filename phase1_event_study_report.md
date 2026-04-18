# Phase 1 OOS Event Study ג€” compression_score Validation (2025)

**Test window:** 2025-01-01 to 2025-12-31  
**Computed:** 2026-04-18T22:16:37Z  
**Baseline SHA:** SHA match ג“  
**Recommendation:** **SHELVE_M8_PHASE_B_GATE_MAY_STILL_PROCEED**

## Executive Summary

27/27 tickers had 2025 data. 5417 valid sessions (198 rejected as incomplete). Deep-compression bucket (earnings-excluded): N=2435, breakout_rate=6.7% vs neutral 5.4%. Kill-switch verdict: **SHELVE_M8_PHASE_B_GATE_MAY_STILL_PROCEED**.

## Bucket Results

| Bucket | Version | N | Breakout% | MeanRet% | SPYAdj% | MFE p50 | MFE p90 | MAE p50 | MAE p90 |
|--------|---------|---|-----------|----------|---------|---------|---------|---------|---------|
| deep | full | 2775 | 6.8% | -0.015 | -0.024 | 0.157 | 0.578 | -0.184 | 0.000 |
| deep | earnings_excluded | 2435 | 6.7% | -0.015 | -0.025 | 0.154 | 0.564 | -0.181 | 0.000 |
| deep | earnings_and_hi_day_excluded | 2189 | 6.9% | -0.012 | -0.027 | 0.154 | 0.557 | -0.176 | 0.000 |
| neutral | full | 1159 | 5.3% | -0.006 | -0.013 | 0.187 | 0.828 | -0.201 | 0.000 |
| neutral | earnings_excluded | 1005 | 5.4% | -0.017 | -0.016 | 0.184 | 0.803 | -0.202 | 0.000 |
| neutral | earnings_and_hi_day_excluded | 888 | 5.5% | -0.016 | -0.016 | 0.183 | 0.803 | -0.201 | 0.000 |
| active | full | 1483 | 3.3% | 0.047 | -0.029 | 0.324 | 1.741 | -0.274 | 0.038 |
| active | earnings_excluded | 1290 | 3.3% | 0.053 | -0.023 | 0.319 | 1.747 | -0.264 | 0.041 |
| active | earnings_and_hi_day_excluded | 1105 | 2.8% | 0.059 | -0.024 | 0.313 | 1.659 | -0.266 | 0.044 |

## Kill-Switch Verdict

| Criterion | Result |
|-----------|--------|
| deep_breakout_gt_neutral_breakout | **PASS** |
| deep_spy_adj_return_gt_neutral_spy_adj | FAIL |
| deep_n_gte_40 | **PASS** |
| deep_breakout_rate_gte_20pct | FAIL |

**All-pass ג†’ SHELVE_M8_PHASE_B_GATE_MAY_STILL_PROCEED**

## Per-Ticker Session Counts

| Ticker | Deep | Neutral | Active |
|--------|------|---------|--------|
| AAPL | 60 | 11 | 9 |
| AMD | 184 | 29 | 21 |
| AMZN | 79 | 74 | 77 |
| AVGO | 170 | 32 | 31 |
| BA | 111 | 61 | 58 |
| BABA | 133 | 50 | 50 |
| BIDU | 81 | 66 | 83 |
| C | 40 | 62 | 126 |
| COIN | 218 | 9 | 4 |
| COST | 100 | 54 | 76 |
| GOOGL | 50 | 76 | 104 |
| GS | 35 | 61 | 133 |
| INTC | 55 | 9 | 15 |
| JD | 17 | 6 | 0 |
| JPM | 72 | 59 | 99 |
| MARA | 227 | 6 | 2 |
| META | 92 | 66 | 72 |
| MSFT | 93 | 72 | 65 |
| MSTR | 71 | 2 | 2 |
| MU | 144 | 41 | 49 |
| NVDA | 110 | 48 | 72 |
| PLTR | 199 | 23 | 15 |
| SMCI | 58 | 9 | 3 |
| SPY | 81 | 60 | 91 |
| TSLA | 76 | 66 | 88 |
| TSM | 170 | 40 | 24 |
| V | 49 | 67 | 114 |

## Limitations

- **Baseline data:** The canonical 2023-2024 baseline (SHA `661975f5e7e5f061ג€¦`) was not available in this environment. A local fallback was used, computed from pre-2025 Z3 sessions in Fetched_Data. Tickers with fewer than 100 pre-2025 Z3 sessions received abstain score 0.50 (neutral bucket). Obtain the canonical baseline from CC-BASELINE-1 for production-grade kill-switch decisions.
- **News-based filters:** Skipped ג€” not in local repo. Sprint 2 backtest to include.
- **Beige Book dates:** Not included in HIGH_IMPACT_DAYS_2025 (8ֳ—/year, mid-cycle).
- **SPY adjustment:** Computed when SPY data exists for same date; `mean_spy_adj_return_8bar` is None if SPY bars are missing.
- **Ticker coverage:** Tickers absent from local data/ or Fetched_Data/ are skipped.
