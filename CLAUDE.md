# CLAUDE.md v8 — Confirmation Indicators & Signal Quality

## Context

**v7 complete.** Direction-specific param optimization degraded results.
L-005 (TSLA=long, others=short) with v4.1 baseline params confirmed as best.

**v8 complete.** 5 confirmation indicators tested — NONE improve walk-forward:
- **Score & Touches**: Zero variance (all trades score >= 20, touches >= 5)
- **RSI extreme**: Counter-productive (PF=0.55 when RSI confirms vs PF=4.13 when not)
- **Mirror filter**: Cosmetic (84% already mirror; removes 8 trades for +$225)
- **Volume fade**: Best diagnostic (PF 3.69) but WF degrades 4/8→3/8

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

- v4: Universe expansion (7 tickers), EXP-V001 baseline
- v4.1: Whitelist portfolio, trail optimization, NVDA rescue, walk-forward
- v5: Regime analysis (ADX/ATR) — no clear signal for filter
- v6: Direction analysis — **breakthrough** (L-005: TSLA=long, others=short)
- v7: Direction-specific param optimization — DEGRADED, rejected
- v7B: Universe expansion (META/MSFT/NVDA SHORT) — all rejected
- v8: Confirmation indicators (mirror, score, vol fade, RSI, touches) — NONE improve WF

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
