# CLAUDE.md v4 — Universe Expansion & Volatility Profiles

## Context

Phases 1-3 complete. Strategy crossed breakeven on OOS (PF=1.03, +$156) using 2-tier exit (50% H1 target + trailing stop). But results are fragile: only 2 tickers, 33 OOS trades, 3/8 walk-forward windows positive. IS has only 6 trades — effectively no IS validation.

**Core finding from Phase 2-3:** Strategy works on AMZN (MED_VOL, PF=2.08) but fails on NVDA (HIGH_VOL, PF=0.13). False breakout patterns work best on moderate-volatility stocks where D1 levels hold reliably and intraday moves are contained.

**Phase 4 tests that hypothesis on 7 tickers across volatility buckets.**

## Current Best Config (v3 winner: STRUCT-002d)

```python
# Level detection
fractal_depth = 10
tolerance_cents = 0.05
tolerance_pct = 0.001
atr_period = 5
min_level_score = 5

# Pattern
tail_ratio_min = 0.10
lp2_engulfing_required = True
clp_min_bars = 3

# Filters
atr_block_threshold = 0.30
atr_entry_threshold = 0.80
enable_volume_filter = True
enable_time_filter = True
enable_squeeze_filter = True

# Risk
min_rr = 1.5
max_stop_atr_pct = 0.10
risk_pct = 0.003

# Exit: 2-tier with trail
tier1_pct = 0.50
tier2_mode = 'trail'
trail_activation = 1.0
trail_factor = 0.7

# Intraday targets
intraday_target_source = 'h1_fractal'
intraday_fractal_k = 3
```

---

## Phase 4A: Data Acquisition & Preparation

### Universe (7 tickers, 2 buckets)

| Bucket | Ticker | Notes |
|--------|--------|-------|
| MED_VOL | AMZN | Proven profitable (PF=2.08 OOS) |
| MED_VOL | AAPL | Highest liquidity, clean levels (data to 2025-11-13 only) |
| MED_VOL | GOOGL | Substitutes for AMD (unavailable in MarketPatterns-AI) |
| MED_VOL | META | Similar profile to AMZN |
| MED_VOL | MSFT | Blue chip, clean price action |
| HIGH_VOL | NVDA | Already tested, need to fix |
| HIGH_VOL | TSLA | Classic false breakout candidate |

### Volatility Classification

```python
for ticker in universe:
    # 1. Load 5-min OHLCV
    # 2. Filter RTH (14:30-21:00 UTC = 9:30-16:00 ET)
    # 3. Aggregate to D1 OHLCV + ATR(14)
    # 4. Classify:
    #    avg_relative_atr = mean(ATR_D1 / Close)
    #    MED_VOL: < 0.030
    #    HIGH_VOL: >= 0.030
    # 5. Print summary table
```

---

## Phase 4B: EXP-V001 — Uniform Baseline

Run v3 winner config (STRUCT-002d) on ALL 7 tickers unchanged.
This is the "one-size-fits-all" baseline showing which tickers the strategy naturally works on.

**Key output:** Per-ticker IS + OOS metrics, signal funnels, exit analysis.

---

## Phase 4C: EXP-V002 — Adaptive Volatility Profiles

```python
VOLATILITY_PROFILES = {
    'MED_VOL': {
        'fractal_depth': 10,
        'max_stop_atr_pct': 0.10,
        'atr_entry_threshold': 0.80,
        'tail_ratio_min': 0.10,
        'min_rr': 1.5,
        'trail_activation': 1.0,
        'trail_factor': 0.7,
    },
    'HIGH_VOL': {
        'fractal_depth': 5,
        'max_stop_atr_pct': 0.20,
        'atr_entry_threshold': 0.85,
        'tail_ratio_min': 0.15,
        'min_rr': 1.5,
        'trail_activation': 1.5,
        'trail_factor': 1.0,
    },
}
```

---

## Phase 4D: EXP-V003–V005 — HIGH_VOL Tuning

```
EXP-V003: HIGH_VOL param sweep on NVDA
EXP-V004: Validate HIGH_VOL on TSLA
EXP-V005: Combined best profiles (full portfolio)
```

---

## Phase 4E: Walk-Forward & Final Report

8-window walk-forward on full 7-ticker portfolio.
Generate `results/OPTIMIZATION_REPORT_v4.md`.

---

## Execution Order

```
1. Phase 4A: Prepare data for 7 tickers, classify volatility  <- START HERE
2. EXP-V001: Uniform config on all 7 tickers (baseline per ticker)
3. EXP-V002: Adaptive profiles (MED vs HIGH)
4. EXP-V003-V005: HIGH_VOL tuning + combined
5. Trail optimization on full portfolio
6. Walk-forward (8 windows, 7 tickers)
7. Final report
```

---

## Success Criteria v4

| Criterion | v3 Result | v4 Target |
|-----------|-----------|-----------|
| Portfolio OOS PF | 1.03 (2 tickers) | **> 1.3** (7 tickers) |
| Portfolio OOS P&L | +$156 | **> +$2,000** |
| Walk-Forward positive | 3/8 | **>= 5/8** |
| MED_VOL profitable | 1/1 (AMZN) | **>= 3/5** |
| HIGH_VOL improved | 0/1 (NVDA) | **>= 1/2 breakeven** |
| OOS trades (portfolio) | 33 | **>= 100** |
| Max single-ticker DD | ~3.5% | **< 5%** |

---

## Critical Rules

1. NEVER skip the ATR filter
2. ONE trade per ticker at a time
3. Assert everything
4. Log everything to the signal funnel
5. OOS is truth — never optimize on OOS
6. Include slippage ($0.02/share each way)
7. Intraday targets must be >= 1.0R — no micro-targets
8. **Data first.** Print summary table before any experiments
9. **EXP-V001 is most important.** Shows natural edge before tuning
10. **Don't over-optimize HIGH_VOL.** "Don't trade HIGH_VOL" is a valid conclusion
11. **Trail is the profit engine.** Protect trailing stop logic
12. **Portfolio-level metrics matter most**
13. Commit data files + experiment results after each step

## Experiment Log Format

```markdown
## EXP-V{NNN}: {Title}
**Hypothesis:** ...
**Config:** ...
**Result (IS per ticker):** ...
**Result (OOS per ticker):** ...
**Portfolio (OOS):** ...
**Verdict:** ACCEPT / REJECT / INCONCLUSIVE
**Notes:** ...
```
