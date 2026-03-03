# CLAUDE.md v5 — Regime Analysis & Adaptive Filters

## Context

**v4.1 complete.** Whitelist portfolio (AAPL, AMZN, GOOGL, TSLA) achieves:
- OOS: 63 trades, PF=1.27, +$2,070 (with trail_factor=0.7, t1_pct=0.30)
- Walk-Forward: **0/8 positive windows** (mean Sharpe=-6.29)
- NVDA rescue failed (PF=0.89 unchanged across all param variations)

**The core problem:** Strategy is profitable in Oct 2025-Jan 2026 but loses in Feb-Sep 2025. This is regime-dependent performance — the false breakout edge exists only in certain market conditions.

**Phase 5 hypothesis:** ADX (trend strength) and ATR regime (volatility expansion/contraction) explain which periods the strategy works. Low-ADX ranging markets should favor false breakouts; high-ADX trending markets should destroy them.

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

## Phase 5A: Regime Analysis (DATA FIRST)

Compute regime indicators, correlate with trade outcomes, map to WF windows.
**Output `results/regime_analysis.md` before any filter experiments.**

### Indicators
1. **ADX(14)** on D1 bars — trend strength (0-100)
   - ADX < 20: weak/no trend (ranging) — favorable for false breakouts
   - ADX 20-30: developing trend
   - ADX > 30: strong trend — unfavorable
2. **ATR regime** — ATR(14) / rolling ATR(50) ratio
   - Ratio < 0.8: low-vol contraction — levels hold better
   - Ratio 0.8-1.2: normal
   - Ratio > 1.2: vol expansion — levels break more easily
3. **Combined regime classification:**
   - FAVORABLE: ADX < 25 AND ATR_ratio < 1.2
   - NEUTRAL: everything else
   - HOSTILE: ADX > 30 OR ATR_ratio > 1.5

### Analysis Steps
1. Compute ADX(14) + ATR regime for all 4 tickers on D1 bars
2. Re-run v4.1 best config, capture per-trade entry dates
3. Map each trade to its regime at entry
4. Map each WF window (8 windows) to dominant regime
5. Correlate: WR, PF, avg P&L by regime bucket
6. Output regime_analysis.md with tables + verdict

---

## Phase 5B: Regime Filter Experiments (if 5A shows signal)

```
R001: ADX ceiling filter — block trades when ADX > threshold
R002: ATR expansion filter — block when ATR_ratio > threshold
R003: Combined regime filter
R004: Walk-forward with regime filter
```

---

## Phase 5C: Final Walk-Forward & Report

8-window walk-forward with regime filters on whitelist portfolio.
Generate `results/OPTIMIZATION_REPORT_v5.md`.

---

## Execution Order

```
1. Phase 5A: Regime analysis — compute, correlate, output regime_analysis.md  <- START HERE
2. Phase 5B: Regime filter experiments (R001-R004)
3. Phase 5C: Walk-forward with best regime filter
4. Final report
```

---

## Success Criteria v5

| Criterion | v4.1 Result | v5 Target |
|-----------|-------------|-----------|
| Portfolio OOS PF | 1.27 | **>= 1.2** (maintain) |
| Walk-Forward positive | 0/8 | **>= 4/8** |
| Regime correlation | untested | **clear signal** (p < 0.10) |
| Mean WF Sharpe | -6.29 | **> 0** |

---

## Critical Rules

1. NEVER skip the ATR filter
2. ONE trade per ticker at a time
3. OOS is truth — never optimize on OOS
4. Include slippage ($0.02/share each way)
5. **Data first.** Output regime_analysis.md BEFORE any filter experiments
6. **Regime analysis is diagnostic.** If no clear signal, don't force a filter
7. **Trail is the profit engine.** Protect trailing stop logic
8. Commit results after each step
