# CLAUDE.md v7 — Directional Optimization & Universe Expansion

## Context

Phase 6 breakthrough: **TSLA=LONG, AAPL/AMZN/GOOGL=SHORT** produces OOS PF=2.64, +$7,064, walk-forward 4/8 positive with +$4,876 total WF P&L. First ever stable edge.

**This phase:** Optimize parameters for each direction profile + test META/MSFT/NVDA as SHORT-only candidates.

**DO NOT change the directional logic.** It works. Only optimize parameters within each direction and expand universe.

---

## Current Config (L-005 winner)

```python
# Direction rules
direction_map = {
    'TSLA': 'LONG',    # Support bounces, short squeeze
    'AAPL': 'SHORT',   # Resistance rejection, institutional selling
    'AMZN': 'SHORT',
    'GOOGL': 'SHORT',
}

# Shared parameters (from v4.1)
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

### L-005 Baseline Numbers

```
OOS: PF=2.64, +$7,064, 4/8 WF positive, WF P&L=+$4,876
```

---

## Phase 7A: Direction-Specific Parameter Optimization

Parameters may need different values for LONG vs SHORT entries. The dynamics are different:
- SHORT: resistance rejection, often sharp and fast → may benefit from tighter trail
- LONG: support bounce, often slower recovery → may benefit from wider stops and patience

### LONG-Profile Sweep (applied to TSLA only)

```
EXP-LP-001: fractal_depth [5, 7, 10]
EXP-LP-002: atr_entry_threshold [0.65, 0.75, 0.80, 0.85]
EXP-LP-003: max_stop_atr_pct [0.10, 0.15, 0.20]
EXP-LP-004: tail_ratio_min [0.05, 0.10, 0.15]
EXP-LP-005: trail_factor [0.5, 0.7, 1.0]
EXP-LP-006: t1_pct [0.20, 0.30, 0.40]
EXP-LP-007: min_rr [1.0, 1.5, 2.0]
```

### SHORT-Profile Sweep (applied to AAPL/AMZN/GOOGL jointly)

```
EXP-SP-001: fractal_depth [5, 7, 10]
EXP-SP-002: atr_entry_threshold [0.65, 0.75, 0.80, 0.85]
EXP-SP-003: max_stop_atr_pct [0.10, 0.15, 0.20]
EXP-SP-004: tail_ratio_min [0.05, 0.10, 0.15]
EXP-SP-005: trail_factor [0.5, 0.7, 1.0]
EXP-SP-006: t1_pct [0.20, 0.30, 0.40]
EXP-SP-007: min_rr [1.0, 1.5, 2.0]
```

### Protocol

- ONE parameter per experiment, same as before
- Run IS + OOS for the relevant ticker(s) only
- Log to EXPERIMENT_LOG_v7.md
- Pick winners from LONG and SHORT sweeps independently
- Combine LONG winners + SHORT winners → test full portfolio

### Combination

```python
optimized_config = {
    'LONG_PROFILE': {
        # Best from EXP-LP-001 through LP-007
        'fractal_depth': ???,
        'max_stop_atr_pct': ???,
        # ...
    },
    'SHORT_PROFILE': {
        # Best from EXP-SP-001 through SP-007
        'fractal_depth': ???,
        'max_stop_atr_pct': ???,
        # ...
    },
}
```

---

## Phase 7B: Universe Expansion (SHORT-only candidates)

After SHORT-profile is optimized on AAPL/AMZN/GOOGL, test new tickers:

```
EXP-UX-001: META SHORT-only (optimized SHORT params)
EXP-UX-002: MSFT SHORT-only (optimized SHORT params)
EXP-UX-003: NVDA SHORT-only (optimized SHORT params)
```

**Acceptance criteria per ticker:**
- OOS PF > 1.0
- OOS trades ≥ 5
- Does not worsen portfolio walk-forward

For each accepted ticker, also test LONG-only to confirm SHORT is the right direction:

```
EXP-UX-004: META LONG-only (compare with UX-001)
EXP-UX-005: MSFT LONG-only (compare with UX-002)
EXP-UX-006: NVDA LONG-only (compare with UX-003)
```

**The direction with higher OOS PF wins.** If both are unprofitable → exclude ticker.

### Also test: TSLA SHORT (counter-check)

```
EXP-UX-007: TSLA SHORT-only (optimized SHORT params)
```

Compare with L-005's TSLA LONG results. Confirm LONG is truly better.

---

## Phase 7C: Final Portfolio Assembly

Combine:
- Optimized LONG profile → TSLA (+ any new LONG tickers)
- Optimized SHORT profile → AAPL, AMZN, GOOGL (+ accepted new tickers)

```
EXP-FINAL-001: Full optimized portfolio
  Report: IS, OOS, per-ticker, exit breakdown, signal funnel
```

---

## Phase 7D: Walk-Forward Validation

Best final config → 8-window walk-forward:

```
| Window | Test Period | Trades | PF | P&L | Per-Ticker |
```

**Must report per-ticker P&L per window** — not just portfolio total.

---

## Phase 7E: Final Report

Generate `results/OPTIMIZATION_REPORT_v7.md`:

```markdown
# False Breakout Strategy — Final Report v7

## Strategy Summary
Direction-specific false breakout strategy:
- LONG entries at support levels: [tickers]
- SHORT entries at resistance levels: [tickers]

## Evolution Table
| Phase | Config | OOS PF | WF Positive | WF P&L |
|-------|--------|--------|-------------|--------|
| v1 | Baseline bidirectional | 0.56 | — | — |
| v2 | Param optimized | 0.92 | 1/8 | -$8,079 |
| v3 | Intraday targets | 1.03 | 3/8 | -$6,170 |
| v4 | Universe + trail | 1.27 | 0/8 | -$7,991 |
| v5 | Regime filter | — | no signal | — |
| v6 | Directional filter | 2.64 | 4/8 | +$4,876 |
| v7 | Dir + optimized + expanded | ??? | ???/8 | ??? |

## Optimized Parameters
### LONG Profile (support bounce tickers)
| Parameter | Value | Justification |

### SHORT Profile (resistance rejection tickers)
| Parameter | Value | Justification |

## Portfolio Composition
| Ticker | Direction | OOS PF | OOS P&L | Accepted |

## Walk-Forward Results
| Window | Trades | PF | P&L |

## Production Recommendations
- Watchlist
- Position sizing
- Circuit breakers
- Monitoring

## Risk Assessment
- Expected monthly P&L
- Worst walk-forward window
- Max drawdown scenario
```

---

## Execution Order

```
1. EXP-LP-001 to LP-007 — LONG profile sweep on TSLA
2. EXP-SP-001 to SP-007 — SHORT profile sweep on AAPL/AMZN/GOOGL
3. Combine LONG + SHORT winners → portfolio test
4. EXP-UX-001 to UX-007 — Universe expansion (META, MSFT, NVDA + direction check)
5. EXP-FINAL-001 — Full portfolio with all accepted tickers
6. Walk-forward validation (8 windows)
7. Final report
```

---

## Experiment Log Format

```markdown
## EXP-{PREFIX}-{NNN}: {Title}
**Profile:** LONG / SHORT
**Ticker(s):** ...
**Change:** {parameter from X to Y}
**Baseline:** L-005 (PF=2.64, WF=4/8)

### Results
| Metric | Baseline | This | Delta |

**Verdict:** ✅ ACCEPT / ❌ REJECT
```

---

## Success Criteria v7

| Criterion | v6 (L-005) | v7 Target |
|-----------|-----------|-----------|
| OOS PF | 2.64 | **≥ 2.5** (don't break it) |
| WF Positive | 4/8 | **≥ 5/8** |
| WF Total P&L | +$4,876 | **> +$5,000** |
| Portfolio tickers | 4 | **≥ 5** |
| OOS trades | ~50 | **≥ 60** |
| Max single-ticker DD | ? | **< 3%** |

---

## Critical Reminders

1. **Direction filter is the edge. Protect it.** Do not test "both directions" variants. The L-005 discovery is the foundation.

2. **LONG and SHORT profiles are independent.** Optimize them separately. What works for TSLA LONG bounces (wider stops, patience) may be wrong for AMZN SHORT rejections (tight stops, fast exit).

3. **New tickers must earn their place.** META/MSFT/NVDA are only added if they improve or maintain portfolio WF. A ticker with OOS PF=1.1 that worsens WF from 4/8 to 3/8 is REJECTED.

4. **Walk-forward per-ticker data is essential.** Show which tickers contribute in which windows. If TSLA carries all profitable windows and others drag, that's fragile.

5. **IS sample size:** TSLA LONG may have very few IS trades (fractal_depth=10 + LONG-only). Track this and flag confidence level.

6. **Commit after each experiment batch.**

**Start with EXP-LP-001 (LONG fractal depth sweep on TSLA). Go.**
