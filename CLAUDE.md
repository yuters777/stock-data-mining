# CLAUDE.md v4.1 — Whitelist Portfolio, Trail Optimization & NVDA Rescue

## Context

**EXP-V001 complete.** Ran v3 winner (STRUCT-002d) on 7 tickers uniformly.

**Key findings:**
- All 7 tickers classified HIGH_VOL (rel ATR 3.2-7.1%) — no natural MED_VOL split
- 4/7 profitable OOS: AAPL (PF=2.10), AMZN (PF=1.22), GOOGL (PF=1.20), TSLA (PF=1.10)
- 3/7 losing: MSFT (PF=0.45, -$2,289), META (PF=0.74, -$1,548), NVDA (PF=0.86, -$415)
- Portfolio OOS: 132 trades, PF=0.88, -$2,538
- Target hit rate ~0% (1 target in 132 trades)
- Trail/breakeven exits only 5/132 — trail is barely activating

**Strategic pivot:** Instead of volatility profiles, whitelist profitable tickers, optimize trail (the profit engine), then attempt NVDA rescue.

## Current Best Config (v3 winner: STRUCT-002d)

```python
fractal_depth = 10, tolerance_cents = 0.05, tolerance_pct = 0.001
atr_period = 5, min_level_score = 5
tail_ratio_min = 0.10, lp2_engulfing_required = True, clp_min_bars = 3
atr_block_threshold = 0.30, atr_entry_threshold = 0.80
enable_volume_filter = True, enable_time_filter = True, enable_squeeze_filter = True
min_rr = 1.5, max_stop_atr_pct = 0.10, risk_pct = 0.003
tier_config = {'mode': '2tier_trail', 't1_pct': 0.50, 'min_rr': 1.5}
intraday: h1 fractal k=3, enable_h1=True, min_target_r=1.0
```

---

## EXP-W001: Whitelist Portfolio Baseline

Drop META, MSFT (clearly unprofitable). Run v3 winner on AAPL, AMZN, GOOGL, TSLA.
This is the baseline for all optimization — must be positive.

---

## T001-T004: Trail Optimization

Trail is barely activating (5/132 trades). The trail starts at breakeven but uses 1R distance — too wide for intraday moves. Need to wire `trail_factor` and `trail_activation_r` into TradeManager.

```
T001: trail_factor sweep [0.5, 0.7, 1.0, 1.5] on whitelist (controls trail distance)
T002: trail_activation_r sweep [0.0, 0.5, 1.0, 1.5] using best trail_factor
T003: t1_pct sweep [0.30, 0.40, 0.50, 0.60] using best trail params
T004: Combined best trail config vs W001 baseline
```

---

## N001-N003: NVDA Rescue

NVDA is closest to breakeven (-$415, PF=0.86). Test wider stops and shallower fractals.

```
N001: max_stop_atr_pct sweep [0.10, 0.15, 0.20, 0.25] on NVDA only
N002: fractal_depth sweep [3, 5, 7, 10] on NVDA with best stop from N001
N003: Combined NVDA-tuned config — if PF >= 1.0, add to portfolio
```

---

## Walk-Forward Validation

8-window walk-forward (3-month train / 1-month test) on final portfolio.

---

## Execution Order

```
1. EXP-W001: Whitelist baseline (AAPL, AMZN, GOOGL, TSLA)      <- START HERE
2. Wire trail_factor + trail_activation_r into TradeManager
3. T001-T004: Trail optimization on whitelist
4. N001-N003: NVDA rescue attempts
5. Walk-forward on final portfolio
6. Final report
```

---

## Success Criteria v4.1

| Criterion | EXP-V001 Result | v4.1 Target |
|-----------|-----------------|-------------|
| Whitelist OOS PF | n/a | **> 1.2** |
| Whitelist OOS P&L | n/a | **> +$1,500** |
| Trail exits | 5/132 (4%) | **> 15%** |
| Walk-Forward positive | untested | **>= 5/8** |
| NVDA PF | 0.86 | **>= 1.0 or exclude** |
| Total OOS trades | 132 (7 tickers) | **>= 50** (whitelist) |
| Max single-ticker DD | 2.65% | **< 3%** |

---

## Critical Rules

1. NEVER skip the ATR filter
2. ONE trade per ticker at a time
3. Assert everything
4. Log everything to the signal funnel
5. OOS is truth — never optimize on OOS
6. Include slippage ($0.02/share each way)
7. Intraday targets must be >= 1.0R — no micro-targets
8. **Trail is the profit engine.** Protect trailing stop logic
9. **Portfolio-level metrics matter most**
10. **Don't over-optimize.** "Exclude ticker" is a valid conclusion
11. Commit experiment results after each step
