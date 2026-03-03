# CLAUDE.md v4.1 — Whitelist Portfolio + Trail Optimization

## Context

EXP-V001 revealed that **volatility bucket classification is wrong** — all 7 tickers are HIGH_VOL (3.2-7.1% rel ATR). The MED/HIGH split hypothesis is dead. Instead, the strategy has a **ticker-specific** edge unrelated to volatility:

| Ticker | OOS PF | OOS P&L | Trades | Status |
|--------|--------|---------|--------|--------|
| AAPL | 2.10 | +$521 | 6 | ✅ WHITELIST (low sample) |
| AMZN | 1.22 | +$571 | 19 | ✅ WHITELIST (proven) |
| GOOGL | 1.20 | +$333 | 15 | ✅ WHITELIST |
| TSLA | 1.10 | +$289 | 23 | ✅ WHITELIST |
| NVDA | 0.86 | -$415 | 14 | ⚠️ PROBATION |
| META | 0.74 | -$1,548 | 33 | ❌ BLACKLIST |
| MSFT | 0.45 | -$2,289 | 22 | ❌ BLACKLIST |

**New direction:** Stop trying to fix losing tickers. Focus on maximizing the 4 profitable ones + determine if NVDA can be saved with minor tuning.

---

## Current Best Config (v3 STRUCT-002d, unchanged)

```python
fractal_depth = 10
atr_entry_threshold = 0.80
max_stop_atr_pct = 0.10
tail_ratio_min = 0.10
min_rr = 1.5
tier1_pct = 0.50  # 50% at H1 target
tier2_mode = 'trail'
trail_activation = 1.0  # R
trail_factor = 0.7
intraday_target_source = 'h1_fractal'
intraday_fractal_k = 3
```

---

## Phase 4.1A: Whitelist Portfolio Baseline

### EXP-W001: Whitelist-only backtest

Run current v3 config on **WHITELIST tickers only** (AAPL, AMZN, GOOGL, TSLA).

```python
whitelist = ['AAPL', 'AMZN', 'GOOGL', 'TSLA']
```

Report:
- Portfolio IS + OOS (combined P&L, PF, WR, Sharpe, trades)
- Per-ticker breakdown
- Signal funnel per ticker
- Walk-forward 8 windows (portfolio level)

**Expected:** Portfolio PF > 1.1, all tickers positive, walk-forward ≥ 4/8.

This is our **new baseline** for all subsequent experiments.

---

## Phase 4.1B: Trail Optimization on Whitelist Portfolio

Target hit rate is ~0%. All profit comes from trailing stop. Let's optimize it properly with 4× more data than Phase 3.

### EXP-T001: Trail Activation Sweep

When does the trailing stop engage? Test on full whitelist portfolio:

| Variant | trail_activation | Hypothesis |
|---------|-----------------|------------|
| T001a | 0.5R | Very early — locks in small gains quickly |
| T001b | 0.7R | Early — balances protection and room |
| T001c | 1.0R | Current — standard |
| T001d | 1.5R | Late — gives more room, higher avg R when trail hits |
| T001e | 2.0R | Very late — max profit per trail but many trades never activate |

### EXP-T002: Trail Factor Sweep

How tight is the trailing stop behind price?

| Variant | trail_factor | Trail distance | Hypothesis |
|---------|-------------|---------------|------------|
| T002a | 0.3 | 0.3 × stop_dist | Very tight — locks profit aggressively, exits on small pullbacks |
| T002b | 0.5 | 0.5 × stop_dist | Moderate tight |
| T002c | 0.7 | 0.7 × stop_dist | Current |
| T002d | 1.0 | 1.0 × stop_dist | Equal to original stop — wide |
| T002e | 1.5 | 1.5 × stop_dist | Very wide — lets winners run far |

### EXP-T003: Breakeven Trigger Sweep

When to move stop to breakeven (before trail activates)?

| Variant | BE trigger | Hypothesis |
|---------|-----------|------------|
| T003a | 0.5R | Very early BE — protects capital but gets shaken out |
| T003b | 0.7R | Moderate |
| T003c | 1.0R | Current (same as trail activation) |
| T003d | never | No explicit BE — go straight from original stop to trail |

### EXP-T004: Best Combination

Combine winners from T001 + T002 + T003. Run IS + OOS on whitelist portfolio.

---

## Phase 4.1C: NVDA Rescue Attempt

NVDA is on probation (PF=0.86, -$415, 14 trades). Try 3 targeted fixes:

### EXP-N001: Wider stops for NVDA

```python
# NVDA-only override
nvda_max_stop_atr_pct = 0.20  # was 0.10
```

### EXP-N002: Shallower fractals for NVDA

```python
# NVDA-only override  
nvda_fractal_depth = 5  # was 10 — more levels
```

### EXP-N003: Combined (wider stops + shallower fractals)

If NVDA OOS PF > 1.0 with either fix → add to whitelist.
If NVDA stays < 1.0 → move to BLACKLIST. **Don't force it.**

---

## Phase 4.1D: Walk-Forward Validation

Final config (whitelist tickers + optimized trail + NVDA decision) → 8-window walk-forward.

Report per window:
- Portfolio trades, PF, P&L
- Per-ticker P&L contribution
- Worst ticker in each window

**Success = ≥ 5/8 windows with PF > 1.0 on portfolio level.**

---

## Phase 4.1E: Final Report

Generate `results/OPTIMIZATION_REPORT_v4.md`:

```markdown
# False Breakout Strategy — Final Report v4

## Strategy Evolution
| Phase | Tickers | OOS PF | P&L | Key Change |
|-------|---------|--------|------|------------|
| v1 baseline | 2 | 0.56 | -$5,403 | Raw v3.4 spec |
| v2 optimized | 2 | 0.92 | -$691 | Parameter tuning |
| v3 structural | 2 | 1.03 | +$156 | H1 targets + trail |
| v4 portfolio | 4-5 | ??? | ??? | Universe expansion + trail opt |

## Final Whitelist
| Ticker | OOS PF | Trades | Confidence |
|--------|--------|--------|------------|

## Blacklist (Do Not Trade)
| Ticker | OOS PF | Reason |

## Optimized Trail Parameters
| Parameter | Value | Justification |

## Walk-Forward Summary
| Window | Portfolio PF | P&L | Winning Tickers |

## Production Recommendations
- Watchlist
- Entry rules
- Exit rules (trail params)
- Risk per trade
- Daily/weekly limits
- Expected monthly P&L range
```

---

## Execution Order

```
1. EXP-W001: Whitelist portfolio baseline (AAPL, AMZN, GOOGL, TSLA)
2. EXP-T001: Trail activation sweep (5 variants)
3. EXP-T002: Trail factor sweep (5 variants)
4. EXP-T003: Breakeven trigger sweep (4 variants)
5. EXP-T004: Combined best trail params
6. EXP-N001-N003: NVDA rescue (3 experiments)
7. Walk-forward validation (8 windows)
8. Final report
```

---

## Success Criteria v4.1

| Criterion | v3 Result | v4.1 Target |
|-----------|-----------|-------------|
| Portfolio OOS PF | 1.03 (2 tickers) | **> 1.3** (4+ tickers) |
| Portfolio OOS P&L | +$156 | **> +$1,500** |
| Walk-Forward | 3/8 | **≥ 5/8** |
| Profitable tickers | 1/2 | **≥ 4/5** |
| OOS trades (portfolio) | 33 | **≥ 60** |
| Avg R on trail exits | unknown | **> 0.5R** |
| % trades reaching 1R | unknown | **> 30%** |

---

## Critical Reminders

1. **Whitelist = AAPL, AMZN, GOOGL, TSLA.** Do not include META or MSFT in any experiment except the baseline comparison.

2. **Trail optimization is the priority.** This is where the actual profit lives. Target hits are ~0% and that's OK — the trail IS the exit strategy.

3. **NVDA gets exactly 3 chances** (N001-N003). If none work → blacklist. No further iteration.

4. **Portfolio-level metrics only** for success criteria. Individual ticker variance is expected.

5. **AAPL has only 6 OOS trades.** Flag any AAPL-dependent conclusions as low-confidence.

6. **Commit after each experiment.**

**Start with EXP-W001. Go.**
