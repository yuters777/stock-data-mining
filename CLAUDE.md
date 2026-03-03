# CLAUDE.md v7 — Direction-Specific Parameter Optimization

## Context

**v6 complete.** Direction analysis found a breakthrough:
- L-005 (TSLA=long, others=short): OOS PF=2.64, +$7,064, WF **4/8** positive (was 0/8)
- TSLA LONG: PF=4.94, +$5,209 (20 trades) — support breakouts reverse reliably
- AAPL/AMZN/GOOGL SHORT: PF=1.33-35.92 — resistance breakouts reverse reliably
- TSLA SHORT destroys value (PF=0.43, -$1,293)
- LONG on AAPL/AMZN/GOOGL destroys value (PF=0.55-0.80)

**v7 complete.** Direction-specific param optimization DEGRADED results:
- v7 optimized: OOS PF=1.41 (-47%), WF 2/8 (-50%), WF P&L +$301 (-94%)
- LP series had 0 IS trades — all picks OOS-based (overfitting)
- SP series picked from 7-11 trade IS samples (too small)
- GOOGL collapsed from PF=1.33 to PF=0.20 under SP params
- Expansion (META/MSFT/NVDA SHORT) all rejected (PF 0.37-0.79)

**VERDICT: L-005 with v4.1 baseline params is the final best config.**

## Best Config (L-005 — FINAL)

```python
direction_filter = {'TSLA': 'long', 'DEFAULT': 'short'}
fractal_depth = 10, tolerance_cents = 0.05, tolerance_pct = 0.001
atr_period = 5, min_level_score = 5
tail_ratio_min = 0.10, lp2_engulfing_required = True, clp_min_bars = 3
atr_block_threshold = 0.30, atr_entry_threshold = 0.80
min_rr = 1.5, max_stop_atr_pct = 0.10, risk_pct = 0.003
tier_config = {'mode': '2tier_trail', 't1_pct': 0.30, 'trail_factor': 0.7,
               'trail_activation_r': 0.0, 'min_rr': 1.5}
intraday: h1 fractal k=3, enable_h1=True, min_target_r=1.0
```

Portfolio: TSLA (LONG) + AAPL, AMZN, GOOGL (SHORT)

## Final Results

| Metric | v4.1 (BOTH) | L-005 (Direction) |
|--------|-------------|-------------------|
| OOS trades | 63 | 50 |
| OOS PF | 1.27 | **2.64** |
| OOS P&L | +$2,070 | **+$7,064** |
| WF positive | 0/8 | **4/8** |
| WF mean Sharpe | -6.29 | **+22.25** |
| WF total P&L | -$7,991 | **+$4,876** |

---

## Completed Phases

- Phase 7A: LP-001→LP-007 (TSLA LONG) — 0 IS trades, no reliable optimization
- Phase 7A: SP-001→SP-007 (SHORT tickers) — IS-optimized params degraded OOS
- Phase 7B: X-001→X-003 (META/MSFT/NVDA expansion) — all rejected
- Phase 7C: Combined v7 tested and rejected vs L-005 baseline

---

## Critical Rules

1. NEVER skip the ATR filter
2. ONE trade per ticker at a time
3. OOS is truth — never optimize on OOS
4. Include slippage ($0.02/share each way)
5. **Trail is the profit engine.** Protect trailing stop logic
6. **Direction filter is structural** — TSLA=long, others=short is the foundation
7. v4.1 params are robust across directions — do not over-optimize
8. Commit results after each phase
