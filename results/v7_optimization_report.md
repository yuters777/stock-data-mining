# Phase 7 — Direction-Specific Optimization Report

**Date:** 2026-03-03

---

## Phase 7A: Parameter Optimization

### LP Winners (TSLA LONG)

| Parameter | Baseline | Winner |
|-----------|----------|--------|
| fractal_depth | 10 | 10 |
| tail_ratio_min | 0.1 | 0.15 * |
| atr_entry_threshold | 0.8 | 0.6 * |
| min_rr | 1.5 | 1.5 |
| max_stop_atr_pct | 0.1 | 0.1 |
| trail_factor | 0.7 | 0.5 * |
| t1_pct | 0.3 | 0.2 * |

### SP Winners (AAPL/AMZN/GOOGL SHORT)

| Parameter | Baseline | Winner |
|-----------|----------|--------|
| fractal_depth | 10 | 7 * |
| tail_ratio_min | 0.1 | 0.2 * |
| atr_entry_threshold | 0.8 | 0.9 * |
| min_rr | 1.5 | 1.5 |
| max_stop_atr_pct | 0.1 | 0.08 * |
| trail_factor | 0.7 | 0.5 * |
| t1_pct | 0.3 | 0.5 * |

## Combined Winners vs Baseline (L-005)

| Metric | L-005 Baseline | v7 Combined |
|--------|----------------|-------------|
| IS trades | 11 | 15 |
| IS PF | 0.56 | 1.38 |
| IS P&L | $-856 | $717 |
| OOS trades | 50 | 50 |
| OOS PF | 2.64 | 1.41 |
| OOS P&L | $7064 | $2731 |
| WF positive | 4/8 | 2/8 |
| WF mean Sharpe | 22.25 | -831.60 |
| WF total P&L | $4876 | $301 |

### Per-Ticker OOS (v7 Combined)

| Ticker | Direction | Trades | PF | P&L |
|--------|-----------|--------|----|----|
| AAPL | SHORT | 3 | 2.52 | $455 |
| AMZN | SHORT | 14 | 0.68 | $-778 |
| GOOGL | SHORT | 16 | 0.20 | $-2298 |
| TSLA | LONG | 17 | 6.24 | $5352 |

### Walk-Forward Windows (v7 Combined)

| Window | Period | Trades | PF | P&L | Sharpe |
|--------|--------|--------|----|----|--------|
| 1 | 2025-05-10→2025-06-10 | 6 | 0.41 | $-665 | -0.52 |
| 2 | 2025-06-10→2025-07-10 | 18 | 1.13 | $277 | -3.31 |
| 3 | 2025-07-10→2025-08-10 | 21 | 0.86 | $-332 | -1.12 |
| 4 | 2025-08-10→2025-09-10 | 14 | 0.47 | $-1073 | -1.87 |
| 5 | 2025-09-10→2025-10-10 | 20 | 0.66 | $-962 | -3.99 |
| 6 | 2025-10-10→2025-11-10 | 24 | 0.59 | $-1289 | 1.82 |
| 7 | 2025-11-10→2025-12-10 | 12 | 0.83 | $-347 | -6647.76 |
| 8 | 2025-12-10→2026-01-10 | 16 | 4.24 | $4692 | 3.92 |

## Phase 7B: Universe Expansion

**Tested:** META, MSFT, NVDA
**Accepted:** NONE

## Phase 7C: Final Portfolio

**Tickers:** AAPL, AMZN, GOOGL, TSLA
**TSLA:** LONG | **Others:** SHORT

| Metric | Value |
|--------|-------|
| OOS trades | 50 |
| OOS PF | 1.41 |
| OOS P&L | $2731 |
| WF positive | 2/8 |
| WF mean Sharpe | -831.60 |
| WF total P&L | $301 |

### Final Per-Ticker OOS

| Ticker | Direction | Trades | PF | P&L |
|--------|-----------|--------|----|----|
| AAPL | SHORT | 3 | 2.52 | $455 |
| AMZN | SHORT | 14 | 0.68 | $-778 |
| GOOGL | SHORT | 16 | 0.20 | $-2298 |
| TSLA | LONG | 17 | 6.24 | $5352 |

### Final Walk-Forward Windows

| Window | Period | Trades | PF | P&L |
|--------|--------|--------|----|----|
| 1 | 2025-05-10→2025-06-10 | 6 | 0.41 | $-665 |
| 2 | 2025-06-10→2025-07-10 | 18 | 1.13 | $277 |
| 3 | 2025-07-10→2025-08-10 | 21 | 0.86 | $-332 |
| 4 | 2025-08-10→2025-09-10 | 14 | 0.47 | $-1073 |
| 5 | 2025-09-10→2025-10-10 | 20 | 0.66 | $-962 |
| 6 | 2025-10-10→2025-11-10 | 24 | 0.59 | $-1289 |
| 7 | 2025-11-10→2025-12-10 | 12 | 0.83 | $-347 |
| 8 | 2025-12-10→2026-01-10 | 16 | 4.24 | $4692 |

## Final Config (v7 winner)

**VERDICT: REJECT v7 optimized params. Keep L-005 with v4.1 baseline params.**

The direction-specific parameter optimization DEGRADED performance:

| Metric | L-005 (v4.1 params) | v7 Optimized | Change |
|--------|---------------------|--------------|--------|
| OOS PF | 2.64 | 1.41 | -47% |
| OOS P&L | +$7,064 | +$2,731 | -61% |
| WF positive | 4/8 | 2/8 | -50% |
| WF P&L | +$4,876 | +$301 | -94% |

**Root cause:** LP series had 0 IS trades for TSLA LONG — all picks were OOS-based (overfitting risk).
SP series picked IS "winners" from 7-11 trade samples — too small for reliable optimization.
GOOGL collapsed from PF=1.33 to PF=0.20 under SP params (fractal_depth 10→7 generated too many bad signals).

**Expansion (Phase 7B):** META, MSFT, NVDA all rejected as SHORT additions (PF 0.37-0.79).

**Best config remains L-005 (v6):**

```python
# L-005: TSLA=long, others=short, v4.1 baseline params
direction_filter = {'TSLA': 'long', 'DEFAULT': 'short'}
fractal_depth = 10, tolerance_cents = 0.05, tolerance_pct = 0.001
atr_period = 5, min_level_score = 5
tail_ratio_min = 0.10, lp2_engulfing_required = True, clp_min_bars = 3
atr_block_threshold = 0.30, atr_entry_threshold = 0.80
min_rr = 1.5, max_stop_atr_pct = 0.10, risk_pct = 0.003
tier_config = {'mode': '2tier_trail', 't1_pct': 0.30, 'trail_factor': 0.7,
               'trail_activation_r': 0.0, 'min_rr': 1.5}
intraday: h1 fractal k=3, enable_h1=True, min_target_r=1.0

# L-005 results:
# OOS: 50 trades, PF=2.64, +$7,064
# WF: 4/8 positive, mean Sharpe=+22.25, total P&L=+$4,876
# Portfolio: AAPL(SHORT), AMZN(SHORT), GOOGL(SHORT), TSLA(LONG)
```
