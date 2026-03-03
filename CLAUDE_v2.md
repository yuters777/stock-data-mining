# CLAUDE.md v2 — Optimization Phase

## Context

Phase 1 is COMPLETE. The backtester is built, verified, and running. Baseline v3.4 is unprofitable (78 OOS trades, 32% WR, -0.25R avg, PF=0.55). Signal funnel identified the bottlenecks. Now we optimize.

**DO NOT rebuild modules.** The existing code works correctly. Focus 100% on experimentation.

---

## Phase 1 Findings (Summary)

### Signal Funnel Bottlenecks (ranked by impact)

1. **ATR filter kills 87% of IS patterns** on AMZN but 0% in OOS → regime-dependent, threshold too rigid
2. **Targets never reached** → 3R targets are unreachable intraday, most trades exit EOD at 0.2-0.7R
3. **Position limit blocks 65 OOS signals** → same-level re-entry churning after EOD exits
4. **R:R filter blocks 26-42 signals** → tied to unreachable targets
5. **Only 18-21 D1 levels** → fractal depth 5 is too selective
6. **Hard stop caps create micro-stops** → $0.15-$0.40 stops on $130-$240 stocks = noise territory

### Key Numbers

| | NVDA IS | NVDA OOS | AMZN IS | AMZN OOS |
|--|---------|----------|---------|----------|
| Trades | 8 | 19 | 16 | 59 |
| Win Rate | 25% | 26% | 25% | 36% |
| Avg R | -0.44 | -0.51 | -0.22 | -0.11 |
| PF | 0.19 | 0.23 | 0.44 | 0.75 |

### ChatGPT PRO Insights (validated, integrate)

- **Partial TP @2R (50%)** improved OOS in their test (+0.59% vs -0.31%)
- **Minimum stop distance** prevents unrealistic micro-stops
- **Volume override** at ATR < threshold needs tightening (VolRatio 2.8 too permissive → raise to 3.0+)

---

## Phase 3: Optimization Protocol

### Rule: ONE change per experiment. Always compare vs baseline.

### Experiment Priority Queue

Run these experiments **in this exact order**. Each one addresses the biggest remaining bottleneck from the funnel.

---

### EXP-001: Lower MIN_RISK_REWARD (3.0 → 2.0)

**Hypothesis:** 3R targets are unreachable intraday. Lowering to 2R will make targets achievable, converting EOD exits into actual TP hits, dramatically improving avg R.

```
Change: MIN_RISK_REWARD = 2.0
Expected: More trades pass R:R filter, winners hit TP instead of EOD exit, avg R improves
```

### EXP-002: Lower MIN_RISK_REWARD (3.0 → 2.5)

**Hypothesis:** 2.5R may be the sweet spot — reachable targets with better expectancy than 2.0.

```
Change: MIN_RISK_REWARD = 2.5
Expected: Compare with EXP-001 to find optimal R:R
```

### EXP-003: Lower ATR_MIN_ENTRY (0.75 → 0.60)

**Hypothesis:** 0.75 blocks 87% of IS patterns on AMZN. Lowering to 0.60 will unlock trades in moderate-energy conditions while still blocking low-energy entries.

```
Change: ATR_MIN_ENTRY = 0.60
Expected: 2-3x more signals pass ATR filter, WR may drop slightly but total expectancy improves
```

### EXP-004: Lower ATR_MIN_ENTRY (0.75 → 0.65)

```
Change: ATR_MIN_ENTRY = 0.65
Expected: Compare with EXP-003
```

### EXP-005: Reduce FRACTAL_DEPTH (5 → 3)

**Hypothesis:** 18-21 levels in 11 months is too few. Depth 3 finds more local extremes = more actionable levels = more trade opportunities.

```
Change: FRACTAL_DEPTH = 3
Expected: 2x more levels, more signals, possibly noisier levels (lower avg score)
```

### EXP-006: Widen MAX_STOP_ATR_PCT (0.15 → 0.20)

**Hypothesis:** Hard caps create micro-stops ($0.15-$0.40) that trigger on M5 noise. Widening to 20% ATR gives breathing room.

```
Change: MAX_STOP_ATR_PCT = 0.20
Expected: Fewer "stop too big" blocks, wider stops = lower WR but higher avg winner
```

### EXP-007: Widen MAX_STOP_ATR_PCT (0.15 → 0.25)

```
Change: MAX_STOP_ATR_PCT = 0.25
Expected: Compare with EXP-006
```

### EXP-008: Lower PARTIAL_TP level (2R → 1.5R)

**Hypothesis:** If 2R is rarely reached, try taking partial at 1.5R. Locks in profits earlier, improves WR.

```
Change: PARTIAL_TP_AT = 1.5R (50% of position)
Expected: Higher WR, lower avg R per trade, net positive impact on PF
```

### EXP-009: Add EOD Cooldown (level blocked for next day after EOD exit)

**Hypothesis:** Re-entry churning at same level wastes capital. If a trade exits EOD without hitting TP or stop, block that level for the rest of the current day AND the next day.

```
Change: Add cooldown_days = 1 after EOD exit at a level
Expected: Fewer trades but higher quality, reduces "churning" losses
```

### EXP-010: Lower TAIL_RATIO_MIN (0.20 → 0.10)

**Hypothesis:** TailRatio 0.20 may be filtering valid LP1 signals. Lower to 0.10 = more permissive.

```
Change: TAIL_RATIO_MIN = 0.10
Expected: More LP1 signals pass, marginal WR impact
```

### EXP-011: Relax LP2_ENGULFING (required → optional)

**Hypothesis:** Strict engulfing requirement (Bar2.Close < Bar1.Open) kills most LP2 candidates. Making it optional will surface more LP2 signals.

```
Change: LP2_ENGULFING = False (just require Bar2.Close < Level)
Expected: More LP2 trades, possibly lower WR but better than zero LP2s
```

### EXP-012: Disable Volume Filter

**Hypothesis:** Test if VSA filter is helping or hurting. Disable it entirely.

```
Change: VOLUME_FILTER = False
Expected: If WR drops → volume filter is valuable. If unchanged → remove complexity.
```

### EXP-013: Time Bucket Filter (Open-only mode)

**Hypothesis:** Signal funnel shows most trades are Midday/Close. Test if restricting to Open session (9:35-10:30 ET) improves WR.

```
Change: Only allow signals in Open bucket (9:35-10:30 ET = 14:35-15:30 UTC)
Expected: Fewer but higher-quality signals (open volatility = better false breakouts)
```

---

## Phase 3B: Combinations

After running all 13 single-parameter experiments, **combine the top 3-5 winners:**

```python
# Example: if EXP-001, EXP-003, EXP-005 all improved OOS
combined_params = {
    'MIN_RISK_REWARD': 2.0,      # from EXP-001
    'ATR_MIN_ENTRY': 0.60,       # from EXP-003
    'FRACTAL_DEPTH': 3,          # from EXP-005
    # ... rest = baseline
}
# Run IS + OOS
# Compare vs baseline AND vs individual experiments
```

Test 2-way and 3-way combinations. Report interaction effects.

---

## Phase 4: Walk-Forward Validation

For the final optimized parameter set, run walk-forward:

```
Window 1: Train Feb-Apr 2025  → Test May 2025
Window 2: Train Mar-May 2025  → Test Jun 2025
Window 3: Train Apr-Jun 2025  → Test Jul 2025
Window 4: Train May-Jul 2025  → Test Aug 2025
Window 5: Train Jun-Aug 2025  → Test Sep 2025
Window 6: Train Jul-Sep 2025  → Test Oct 2025
Window 7: Train Aug-Oct 2025  → Test Nov 2025
Window 8: Train Sep-Nov 2025  → Test Dec 2025
```

Report: OOS Sharpe for each window, mean, std dev, worst window.

**Success = positive Sharpe in ≥ 6 of 8 windows.**

---

## Phase 5: Final Report

Generate `results/OPTIMIZATION_REPORT.md`:

```markdown
# Optimization Report

## Baseline vs Optimized
| Metric | Baseline | Optimized | Change |
|--------|----------|-----------|--------|
| Trades (OOS) | 78 | ??? | |
| Win Rate | 32% | ??? | |
| Avg R | -0.25 | ??? | |
| Profit Factor | 0.55 | ??? | |
| Sharpe | -8.3 | ??? | |
| Max DD | 3.42% | ??? | |

## Parameter Changes
| Parameter | Baseline | Optimized | Justification |
|-----------|----------|-----------|---------------|

## Experiment Results Summary
| EXP | Change | IS Effect | OOS Effect | Verdict |
|-----|--------|-----------|------------|---------|

## Walk-Forward Results
| Window | OOS Sharpe | OOS PF | Trades |
|--------|-----------|--------|--------|

## Signal Funnel (Before/After)

## Recommendations for Production
```

---

## Experiment Log Format

For EACH experiment, append to `experiments/EXPERIMENT_LOG.md`:

```markdown
## EXP-{NNN}: {Title}
**Hypothesis:** {what we expect and why}
**Change:** {parameter from X to Y}
**Baseline ref:** 78 trades, 32% WR, -0.25R, PF=0.55

### In-Sample Results
| Metric | Baseline | This EXP | Delta |
|--------|----------|----------|-------|

### Out-of-Sample Results
| Metric | Baseline | This EXP | Delta |
|--------|----------|----------|-------|

**Verdict:** ✅ ACCEPT / ❌ REJECT / ⚠️ INCONCLUSIVE
**Keep for Phase 3B combination?** Yes/No
**Notes:** {observations, edge cases, surprises}
```

---

## Execution Commands

```bash
# Run single experiment (example)
python backtester/optimizer.py --experiment 001 --change MIN_RISK_REWARD=2.0

# Or if optimizer doesn't support this yet, modify config and run:
python backtester/backtester.py --config experiments/exp001_config.json

# Whatever method works — the KEY is: one change, run both IS and OOS, log results
```

---

## Critical Reminders

1. **ONE change per experiment.** Combining changes before testing individually = noise.
2. **Always report IS AND OOS.** If IS improves but OOS doesn't → overfitting.
3. **EOD exits are the main problem.** Any change that converts EOD→TP is high-value.
4. **ATR filter regime-dependence is real.** 87% block in IS, 0% in OOS = the filter behaves differently in different market conditions. Consider: adaptive threshold or wider fixed band.
5. **Position limit blocks are signals of level quality.** If 65 signals are blocked by "already at this level" → the level is attracting price but our entries keep failing. This might be a level quality issue, not just a position management issue.
6. **Target must be NEAREST opposing level.** Verify this — ChatGPT PRO had a bug where targets were dataset extremes. Double-check that your target calculation finds the nearest D1 level on the opposite side, not the farthest.
7. **Commit experiment results to git** after each experiment for traceability.

---

## Success Criteria (unchanged)

- [ ] Out-of-sample Sharpe > 1.0
- [ ] Win Rate > 45%
- [ ] Profit Factor > 1.5
- [ ] Max Drawdown < 5%
- [ ] ≥ 20 OOS trades
- [ ] Walk-forward: positive Sharpe in ≥ 6/8 windows
- [ ] All filter assertions pass

**Start with EXP-001. Go.**
