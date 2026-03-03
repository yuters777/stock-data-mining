# CLAUDE.md v3 — Structural Target Optimization

## Context

v2 optimization (13 parameter experiments) reduced OOS loss 87% but the strategy remains net negative.
The root cause is structural: **57% of trades exit at EOD because D1 targets are unreachable intraday.**
Only 1/53 OOS trades hit its D1 target. The entry edge is real (EOD exits average +$176) but targets are broken.

**v3 fixes the target system** by introducing intraday levels and tiered exits.

## Current Optimized Baseline (from v2)

```python
# "optimized_v2" — the starting point for v3 experiments
fractal_depth=10, atr_entry=0.80, max_stop_atr=0.10, tail_ratio=0.10
IS:  10 trades, 30.0% WR, PF=0.45, -$843
OOS: 53 trades, 41.5% WR, PF=0.92, -$691  (AMZN: PF=2.08, NVDA: PF=0.13)
```

## v3 New Modules

### IntradayLevelDetector (`backtester/core/intraday_levels.py`)

Detects M5 and H1 fractal support/resistance for **target placement only**.
Entry signals still use D1 levels — this module provides closer, reachable profit targets.

- M5 fractals: `H[i] > max(H[i-k]...H[i-1]) AND H[i] > max(H[i+1]...H[i+k])` on M5 bars
- H1 fractals: aggregate M5 → H1, then same fractal detection
- Configurable: `fractal_depth_m5`, `fractal_depth_h1`, `min_m5_level_age_bars`
- Returns sorted list of intraday levels between entry and D1 target

### Tiered Target System (modifications to risk_manager + trade_manager)

Replace single D1 target with multi-tier exits:

| Tier | Source | Exit % | Condition |
|------|--------|--------|-----------|
| T1 | Nearest M5/H1 fractal | configurable | Must be ≥ 1.0R from entry |
| T2 | Next intraday level or D1 | configurable | Remainder after T1 |
| T3 (optional) | D1 opposing level | remainder | Original target |

If no intraday target exists ≥ 1.0R, fall back to D1-only (current behavior).

## Experiment Plan

### STRUCT-001: M5 Intraday Targets (single-tier replacement)

Replace D1 target with nearest qualifying M5 intraday fractal level.
Tests whether closer targets improve WR and P&L.

| ID | Config | Hypothesis |
|----|--------|------------|
| STRUCT-001a | M5 fractal k=3, nearest M5 target | More M5 levels = closer targets = higher WR |
| STRUCT-001b | M5 fractal k=5, nearest M5 target | Fewer but stronger M5 levels |
| STRUCT-001c | M5 fractal k=10, nearest M5 target | Only major intraday S/R |
| STRUCT-001d | H1 fractal k=3, nearest H1 target | Hourly levels = more significant targets |

All variants: min_rr=1.5 (reduced from 3.0 since targets are closer).

### STRUCT-002: Tiered Exit System

Multi-level partial exits using best STRUCT-001 fractal config.

| ID | Config | Hypothesis |
|----|--------|------------|
| STRUCT-002a | 2-tier: 50% at M5, 50% at D1 | Lock profits early, hold for upside |
| STRUCT-002b | 2-tier: 60% at M5, 40% at D1 | Aggressive early exit |
| STRUCT-002c | 3-tier: 40%/30%/30% M5/H1/D1 | Graduated exits at each timeframe |
| STRUCT-002d | 2-tier: 50% at M5, 50% trail | Trailing stop on remainder |

### STRUCT-003: Combined + Walk-Forward

Combine best STRUCT-001 + STRUCT-002 winners. Run 8-window walk-forward.

## Experiment Log Format

```markdown
## STRUCT-{NNN}{x}: {Title}
**Hypothesis:** ...
**Change:** ...
**Baseline (v2 optimized):** ...
**Result (IS):** ...
**Result (OOS):** ...
**Verdict:** ACCEPT / REJECT / INCONCLUSIVE
**Notes:** ...
```

## Critical Rules (unchanged from v2)

1. NEVER skip the ATR filter
2. ONE trade per ticker at a time
3. Assert everything
4. Log everything to the signal funnel
5. OOS is truth — never optimize on OOS
6. Include slippage ($0.02/share each way)
7. New: **intraday targets must be ≥ 1.0R** — no micro-targets

## Success Criteria

- [ ] OOS Sharpe > 1.0
- [ ] Win Rate > 45% with Avg R > 1.0
- [ ] Profit Factor > 1.5
- [ ] Max Drawdown < 5%
- [ ] OOS Trades ≥ 20
- [ ] Walk-forward: positive Sharpe in ≥ 5 of 8 windows
- [ ] Target hit rate > 20% (vs current 2%)
