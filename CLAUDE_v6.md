# CLAUDE.md v6 — LONG-Only Reversal Strategy

## Context

Phases 1-5 proved that the full bidirectional False Breakout strategy has an unstable edge (OOS PF=1.27, but walk-forward 0/8). Regime filters showed no predictive signal. The strategy works sometimes but we can't predict when.

**New hypothesis:** Trading ONLY long entries from false breakouts of support levels (reversal from decline to growth) will produce a more stable edge due to:
1. **Bullish market bias** — US equities trend upward over time
2. **Short squeeze mechanics** — trapped shorts create violent upward reversals
3. **"Buy the dip" psychology** — retail and institutional demand concentrates at support levels
4. **Asymmetric moves** — downside fear triggers panic selling, creating cleaner false breakouts at support

**This is a ONE-EXPERIMENT phase.** We filter existing backtester to LONG-only and compare vs bidirectional baseline across all metrics.

---

## Current Best Config (v4.1)

```python
tickers = ['AAPL', 'AMZN', 'GOOGL', 'TSLA']
fractal_depth = 10
atr_entry_threshold = 0.80
max_stop_atr_pct = 0.10
tail_ratio_min = 0.10
min_rr = 1.5
t1_pct = 0.30
trail_factor = 0.7
trail_activation = 0.0R
intraday_target = h1_fractal k=3
```

---

## Phase 6A: LONG-Only Baseline Comparison

### Implementation

Minimal change — add one filter:

```python
# In filter_chain.py or signal generation:
def check_direction_filter(self, signal):
    if self.config.long_only and signal.direction == 'SHORT':
        return False, 'LONG-only mode: short signals blocked'
    return True, 'OK'
```

Or even simpler — in the pattern engine, only generate signals when:
- Level type = SUPPORT (Low fractal)
- Pattern = false breakout BELOW support → reversal UP
- Entry = LONG

### Experiment Matrix

| Experiment | Direction | Tickers | Description |
|------------|-----------|---------|-------------|
| L-001 | LONG only | AAPL, AMZN, GOOGL, TSLA | Core test |
| L-002 | SHORT only | Same | Counter-test (expect worse) |
| L-003 | BOTH (v4.1) | Same | Baseline reference |

**Run all three on same IS/OOS periods with same config.** Only direction changes.

### Required Output

For each experiment:

```
=== L-00X: {DIRECTION} ONLY ===
Portfolio:
  IS:  X trades, X% WR, PF=X.XX, $XXX
  OOS: X trades, X% WR, PF=X.XX, $XXX

Per-ticker OOS:
  AAPL: X trades, X% WR, PF=X.XX, $XXX
  AMZN: X trades, X% WR, PF=X.XX, $XXX
  GOOGL: X trades, X% WR, PF=X.XX, $XXX
  TSLA: X trades, X% WR, PF=X.XX, $XXX

Exit breakdown:
  Target: X (X%)
  Trail: X (X%)
  EOD: X (X%)
  Stop: X (X%)

Signal Funnel:
  Total patterns detected: X
  LONG patterns: X (X%)
  SHORT patterns: X (X%)
  → Blocked by direction filter: X
  → Valid after all filters: X
```

---

## Phase 6B: LONG-Only Parameter Re-optimization

**Only proceed if L-001 shows improvement over L-003.**

The optimal parameters for LONG-only may differ from bidirectional. Re-sweep key parameters:

```
EXP-LO-001: fractal_depth [3, 5, 7, 10] — more support levels may help
EXP-LO-002: atr_entry_threshold [0.60, 0.70, 0.80] — energy requirement for bounces
EXP-LO-003: max_stop_atr_pct [0.10, 0.15, 0.20] — stop width for support bounces
EXP-LO-004: min_rr [1.5, 2.0, 2.5] — target distance
EXP-LO-005: tail_ratio_min [0.05, 0.10, 0.15] — how much tail below support needed
```

Same protocol: one change at a time, IS + OOS, pick winners, combine.

---

## Phase 6C: Expand Universe for LONG-Only

If LONG-only works, re-test tickers that were excluded:

```
EXP-LU-001: Add NVDA (LONG only) — was unprofitable bidirectional
EXP-LU-002: Add META (LONG only) — was excluded in v4.1
EXP-LU-003: Add MSFT (LONG only) — was excluded in v4.1
```

**Hypothesis:** Tickers that failed bidirectionally may work LONG-only if their SHORT signals were the primary losers.

---

## Phase 6D: Walk-Forward Validation

Best LONG-only config → 8-window walk-forward:

```
Window 1: Train Feb-Apr 2025  → Test May 2025
...
Window 8: Train Sep-Nov 2025  → Test Dec 2025
```

**This is the critical test.** If LONG-only fixes walk-forward stability (≥4/8 positive), we have a tradeable strategy.

---

## Phase 6E: Diagnostic Deep-Dive

Regardless of walk-forward result, generate these analytics:

### 1. LONG vs SHORT trade comparison (from L-001 vs L-002)

```
| Metric | LONG trades | SHORT trades | Delta |
|--------|-------------|--------------|-------|
| Count | | | |
| Win Rate | | | |
| Avg R | | | |
| PF | | | |
| Avg holding time | | | |
| % reaching 1R | | | |
| % stopped out | | | |
```

### 2. Support level quality vs Resistance level quality

```
| Level Type | Avg Score | Avg Touches | Mirror % | Avg Level Lifetime |
|------------|-----------|-------------|----------|-------------------|
| Support | | | | |
| Resistance | | | | |
```

### 3. Time-of-day analysis for LONG entries

```
| Time Bucket | LONG Trades | WR | PF | Best Ticker |
|-------------|------------|-----|-----|-------------|
| Open (9:35-10:30) | | | | |
| Midday (10:30-14:00) | | | | |
| Close (14:00-16:00) | | | | |
```

### 4. Walk-forward windows LONG vs BOTH

```
| Window | BOTH PF | LONG PF | SHORT PF | LONG Better? |
|--------|---------|---------|----------|-------------|
| 1 | 0.34 | ??? | ??? | |
| 2 | 0.14 | ??? | ??? | |
| ... | | | | |
```

This table is THE key diagnostic. If LONG consistently outperforms in losing windows, the directional filter is the answer.

---

## Success Criteria v6

| Criterion | v4.1 Result | v6 Target |
|-----------|-------------|-----------|
| OOS PF | 1.27 | **> 1.3** (or ≥ v4.1) |
| Walk-Forward positive | 0/8 | **≥ 4/8** ← PRIMARY GOAL |
| Win Rate | 49.2% | **> 45%** |
| OOS trades | 63 | **≥ 25** (fewer trades OK) |
| Max DD | ~3% | **< 5%** |

**The #1 goal is walk-forward stability.** Even if OOS PF drops from 1.27 to 1.15, improving WF from 0/8 to 5/8 is a massive win — it means the edge is REAL and STABLE.

---

## Execution Order

```
1. L-001, L-002, L-003 — direction comparison (LONG vs SHORT vs BOTH)
2. Decision point: IF L-001 > L-003 → proceed. IF not → STOP.
3. EXP-LO-001 to LO-005 — parameter re-optimization for LONG-only
4. Combine winners
5. EXP-LU-001 to LU-003 — re-test excluded tickers
6. Walk-forward validation (8 windows)
7. Diagnostic deep-dive
8. Final report → OPTIMIZATION_REPORT_v6.md
```

---

## Critical Reminders

1. **This is a hypothesis test, not a guarantee.** If LONG-only is worse than BOTH, accept it and stop.

2. **Expect ~50% fewer trades.** We're filtering half the signals. If LONG-only has 30 OOS trades with PF=1.5, that's better than 63 trades with PF=1.27.

3. **Support levels may be different quality than resistance.** Pay attention to the level diagnostic (Phase 6E). If support levels are weaker (fewer touches, lower score), the entry quality drops.

4. **TSLA and high-vol names might flip.** TSLA shorts were actually profitable in v4.1 (PF=1.10). LONG-only might hurt TSLA. Watch per-ticker breakdown carefully.

5. **Walk-forward is truth.** Don't get excited by OOS PF alone. We've been burned by that before (v4.1 had PF=1.27 but WF=0/8).

6. **Commit after each experiment.**

**Start with L-001 (LONG only), L-002 (SHORT only), L-003 (BOTH baseline). Go.**
