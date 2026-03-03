# CLAUDE.md v6 — Direction Analysis & Filtering

## Context

**v5 complete.** Regime analysis (Phase 5A) found:
- IS period: ALL regimes unprofitable (PF 0.24-0.97)
- OOS period: ALL regimes profitable (PF 1.13-2.16)
- Walk-forward failure is NOT regime-driven — it's a time-period issue
- ADX/ATR regime filters cannot fix walk-forward (no clear signal)

**v4.1 baseline** (still best config):
- OOS: 63 trades, PF=1.27, +$2,070
- Walk-Forward: 0/8 positive windows (mean Sharpe=-6.29)
- Portfolio: AAPL, AMZN, GOOGL, TSLA

**Phase 6 hypothesis:** LONG and SHORT trades may have very different edge profiles. False breakouts at support (LONG) vs resistance (SHORT) may perform differently. If one direction dominates losses, filtering it out could improve walk-forward stability.

## Current Best Config (v4.1 winner)

```python
fractal_depth = 10, tolerance_cents = 0.05, tolerance_pct = 0.001
atr_period = 5, min_level_score = 5
tail_ratio_min = 0.10, lp2_engulfing_required = True, clp_min_bars = 3
atr_block_threshold = 0.30, atr_entry_threshold = 0.80
min_rr = 1.5, max_stop_atr_pct = 0.10, risk_pct = 0.003
tier_config = {'mode': '2tier_trail', 't1_pct': 0.30, 'trail_factor': 0.7,
               'trail_activation_r': 0.0, 'min_rr': 1.5}
intraday: h1 fractal k=3, enable_h1=True, min_target_r=1.0
```

Portfolio: AAPL, AMZN, GOOGL, TSLA (NVDA excluded)

---

## Phase 6A: Direction Experiments

### Experiments
```
L-001: LONG only — block all SHORT signals
L-002: SHORT only — block all LONG signals
L-003: BOTH (baseline) — no direction filter (v4.1 rerun for comparison)
```

### For each experiment:
1. Run IS + OOS on 4-ticker portfolio
2. Per-ticker breakdown (trades, WR, PF, P&L)
3. 8-window walk-forward
4. Compare all three side by side

### Implementation:
- Add `direction_filter` field to `BacktestConfig` (None | "long" | "short")
- Filter signals in `Backtester.run()` after signal selection, before filter chain
- No changes to pattern engine, risk manager, or trade manager

---

## Phase 6B: Proceed Based on Results

If one direction is clearly stronger:
- Adopt direction filter into best config
- Re-run walk-forward with combined best config
- Generate final report

If both directions contribute:
- Keep BOTH, investigate other angles
- Consider per-ticker direction preferences

---

## Execution Order

```
1. Add direction_filter to BacktestConfig + Backtester.run()
2. Run L-001 (LONG), L-002 (SHORT), L-003 (BOTH)
3. Per-ticker breakdown + walk-forward for all three
4. Output results/direction_analysis.md
5. Proceed based on results
```

---

## Success Criteria v6

| Criterion | v4.1 Result | v6 Target |
|-----------|-------------|-----------|
| Portfolio OOS PF | 1.27 | **>= 1.2** (maintain or improve) |
| Walk-Forward positive | 0/8 | **>= 2/8** (any improvement) |
| Direction signal | untested | **clear split** between LONG/SHORT |

---

## Critical Rules

1. NEVER skip the ATR filter
2. ONE trade per ticker at a time
3. OOS is truth — never optimize on OOS
4. Include slippage ($0.02/share each way)
5. **Trail is the profit engine.** Protect trailing stop logic
6. **Direction filter is additive** — it only blocks signals, never changes entry/exit logic
7. Commit results after each step
