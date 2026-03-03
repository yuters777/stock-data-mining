# CLAUDE.md v4 — Universe Expansion & Volatility Profiles

## Context

Phases 1-3 complete. Strategy crossed breakeven on OOS (PF=1.03, +$156) using 2-tier exit (50% M5 target + trailing stop on remainder). But results are fragile: only 2 tickers, 33 OOS trades, 3/8 walk-forward windows positive. IS has only 6 trades — effectively no in-sample validation.

**Core finding from Phase 2-3:** Strategy works on AMZN (MED_VOL, PF=2.08) but fails on NVDA (HIGH_VOL, PF=0.13). The hypothesis is that false breakout patterns work best on moderate-volatility stocks where D1 levels hold reliably and intraday moves are contained.

**This phase tests that hypothesis on 7 tickers across 3 volatility buckets.**

---

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
min_rr = 1.5  # lowered from 3.0 in v3
max_stop_atr_pct = 0.10
risk_pct = 0.003

# Exit: 2-tier with trail
tier1_pct = 0.50  # 50% at nearest H1 fractal target
tier2_mode = 'trail'  # trailing stop on remainder
trail_activation = 1.0  # R to activate trail
trail_factor = 0.7  # trail distance = 0.7 × stop_dist

# Intraday targets
intraday_target_source = 'h1_fractal'
intraday_fractal_k = 3
```

---

## Phase 4A: Data Acquisition

### Step 1: Get ticker data from MarketPatterns-AI

The repo `yuters777/MarketPatterns-AI` contains auto-updated 5-min OHLCV data. Download data for these tickers:

**Target universe (7 tickers total, 3 buckets):**

| Bucket | Ticker | Expected ATR/Price | Why |
|--------|--------|-------------------|-----|
| MED_VOL | AMZN | ~2.0% | ✅ Already proven profitable |
| MED_VOL | AAPL | ~1.5% | Highest liquidity, clean levels |
| MED_VOL | META | ~2.5% | Similar profile to AMZN |
| MED_VOL | MSFT | ~1.5% | Blue chip, clean price action |
| HIGH_VOL | NVDA | ~4.0% | ✅ Already tested, need to fix |
| HIGH_VOL | TSLA | ~3.5% | Classic false breakout candidate |
| HIGH_VOL | AMD | ~3.5% | Semi sector, high retail participation |

**If any ticker is missing from MarketPatterns-AI, substitute:**
- MED: GOOG, JPM, V
- HIGH: SMCI, COIN, MARA

### Step 2: Data preparation for each ticker

```python
for ticker in universe:
    # 1. Load 5-min OHLCV from data/ folder
    # 2. Filter RTH only (14:30-21:00 UTC = 9:30-16:00 ET)
    # 3. Compute daily OHLCV + ATR
    # 4. Classify volatility bucket:
    #    avg_relative_atr = mean(ATR_D1 / Close) over full period
    #    LOW_VOL: < 0.015
    #    MED_VOL: 0.015 - 0.030
    #    HIGH_VOL: > 0.030
    # 5. Save to data/{TICKER}_data.csv
    # 6. Print: ticker, date range, bar count, avg price, avg ATR, bucket
```

---

## Phase 4B: Volatility Profile System

### Implementation

```python
VOLATILITY_PROFILES = {
    'MED_VOL': {
        # Current v3 winner — proven on AMZN
        'fractal_depth': 10,
        'max_stop_atr_pct': 0.10,
        'atr_entry_threshold': 0.80,
        'tail_ratio_min': 0.10,
        'min_rr': 1.5,
        'trail_activation': 1.0,
        'trail_factor': 0.7,
    },
    'HIGH_VOL': {
        # Hypothesis: NVDA/TSLA need wider stops and more levels
        'fractal_depth': 5,        # More levels (10 was too few for NVDA)
        'max_stop_atr_pct': 0.20,  # 2× wider stops (was 0.10)
        'atr_entry_threshold': 0.85, # Stricter energy requirement
        'tail_ratio_min': 0.15,    # Cleaner patterns only
        'min_rr': 1.5,
        'trail_activation': 1.5,   # Later trail activation (more room)
        'trail_factor': 1.0,       # Wider trail (more breathing room)
    },
}
```

### Testing Protocol

```
EXP-V001: Run UNIFORM config (current v3 winner) on ALL 7 tickers
          → This is the "one-size-fits-all" baseline for each ticker
          → Record IS + OOS per ticker
          
EXP-V002: Run ADAPTIVE config (MED_VOL params for MED tickers, HIGH_VOL for HIGH tickers)
          → Compare vs EXP-V001 per ticker
          → Key question: does HIGH_VOL profile fix NVDA?

EXP-V003: HIGH_VOL parameter sweep on NVDA only
          → fractal_depth: [3, 5, 7]
          → max_stop_atr_pct: [0.15, 0.20, 0.25]
          → trail_factor: [0.7, 1.0, 1.5]
          → Find best HIGH_VOL params

EXP-V004: Apply EXP-V003 winner to TSLA and AMD
          → Validate HIGH_VOL profile generalizes
          
EXP-V005: Final combined — best MED params on MED tickers + best HIGH params on HIGH tickers
          → Full portfolio backtest
```

---

## Phase 4C: Trail Optimization (on expanded universe)

With more data, re-optimize trailing stop parameters:

```
EXP-T001: trail_activation sweep [0.5, 0.7, 1.0, 1.5, 2.0] R
EXP-T002: trail_factor sweep [0.3, 0.5, 0.7, 1.0, 1.5]
EXP-T003: breakeven_trigger sweep [0.5, 0.7, 1.0, never]
EXP-T004: Best combo from T001-T003
```

Run these on the **full 7-ticker portfolio** (not per-ticker). Trail params should be universal.

---

## Phase 4D: Walk-Forward on Full Portfolio

Final config → 8-window walk-forward across all 7 tickers simultaneously.

```
Window 1: Train Feb-Apr 2025  → Test May 2025
Window 2: Train Mar-May 2025  → Test Jun 2025
...
Window 8: Train Sep-Nov 2025  → Test Dec 2025
```

**Report per window:**
- Total trades (all tickers)
- P&L per ticker
- Portfolio P&L
- PF, WR, Sharpe

---

## Phase 4E: Final Report

Generate `results/OPTIMIZATION_REPORT_v4.md`:

```markdown
# False Breakout Strategy — Optimization Report v4

## Universe Performance Summary
| Ticker | Bucket | OOS Trades | WR | PF | P&L | Profile |
|--------|--------|-----------|-----|-----|------|---------|

## Volatility Profile Comparison
| Config | Portfolio OOS PF | Portfolio P&L | Best Ticker | Worst Ticker |
|--------|-----------------|---------------|-------------|--------------|

## Trail Parameter Analysis
| Config | OOS PF | Avg R on trail exits | % trades reaching 1R |

## Walk-Forward Results
| Window | Trades | PF | P&L | Tickers in Profit |

## Per-Ticker Signal Funnels

## Recommended Production Config
- MED_VOL tickers: [params]
- HIGH_VOL tickers: [params]
- Watchlist: [which tickers to trade]
- Blacklist: [which tickers to skip]

## Risk Assessment
- Expected monthly P&L range
- Worst-case scenario (worst walk-forward window)
- Recommended starting capital
```

---

## Execution Order

```
1. Phase 4A: Download + prepare data for 5 new tickers
2. EXP-V001: Uniform config on all 7 tickers (baseline per ticker)
3. EXP-V002: Adaptive profiles (MED vs HIGH)
4. EXP-V003: HIGH_VOL param sweep on NVDA
5. EXP-V004: Validate HIGH_VOL on TSLA + AMD
6. EXP-V005: Combined best profiles
7. EXP-T001-T004: Trail optimization on full portfolio
8. Walk-forward validation (8 windows, 7 tickers)
9. Final report
```

---

## Signal Funnel Template (Per Ticker)

```
SIGNAL FUNNEL — {ticker} ({bucket}) — {config}
════════════════════════════════════════════════
D1 levels:              ??? (target: 10-25 per ticker)
  Confirmed:            ???
  Mirror:               ???
  
Patterns:               ???
  Blocked ATR:          ???
  Blocked R:R:          ???
  Blocked other:        ???
  
VALID SIGNALS:          ???
  Trail exits:          ???  (avg R: ???)
  Target hits:          ???  (avg R: ???)
  EOD exits:            ???  (avg R: ???)
  Stop exits:           ???  (avg R: ???)
  
% reaching 1R:          ???  ← entry quality metric
% reaching 2R:          ???
```

---

## Success Criteria v4

| Criterion | v3 Result | v4 Target |
|-----------|-----------|-----------|
| Portfolio OOS PF | 1.03 (2 tickers) | **> 1.3** (7 tickers) |
| Portfolio OOS P&L | +$156 | **> +$2,000** |
| Walk-Forward positive | 3/8 | **≥ 5/8** |
| MED_VOL tickers profitable | 1/1 (AMZN) | **≥ 3/4** |
| HIGH_VOL tickers improved | 0/1 (NVDA) | **≥ 1/3 breakeven** |
| OOS trades (portfolio) | 33 | **≥ 100** |
| Max single-ticker DD | ~3.5% | **< 5%** |

---

## Critical Reminders

1. **Data first.** Do NOT start experiments until all 7 tickers are loaded, RTH-filtered, and ATR-calculated. Print summary table showing ticker/dates/bars/ATR/bucket.

2. **EXP-V001 is the most important experiment.** It shows us which tickers the strategy naturally works on BEFORE any tuning. Expect MED_VOL tickers to be profitable and HIGH_VOL to struggle.

3. **Don't over-optimize HIGH_VOL.** If NVDA/TSLA/AMD all fail with reasonable params, the answer is "don't trade HIGH_VOL" — that's a valid and valuable conclusion.

4. **Trail is the profit engine.** Any change that breaks trailing stop logic is catastrophic. Protect it.

5. **Portfolio-level metrics matter most.** Individual ticker PF can vary; what matters is that the portfolio as a whole makes money across walk-forward windows.

6. **IS sample size problem persists.** With fractal_depth=10, IS periods may still have too few trades. If IS trades < 10 for any ticker, note it as a reliability concern — don't discard the ticker but flag the confidence level.

7. **Commit data files + experiment results to git after each step.**

**Start with Phase 4A: data acquisition. Go.**
