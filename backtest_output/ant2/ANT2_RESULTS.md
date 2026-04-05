# ANT-2: Earnings Recovery Ratio — M5 Precision Test — Results

**Date:** 2026-04-05
**M5 Data Range:** 2025-02-03 to 2026-03-18 (~13 months)
**Tickers with M5 Data:** 22 (missing: ARM, INTC, SMCI, MSTR, JD)
**Total Events:** 99 earnings events in M5 window
**Gap-Down Universe (gap <= -3%):** N=14
**Gap-Down (gap <= -5%):** N=9

---

## CRITICAL LIMITATION

**N=14 gap-down events (at -3% threshold) makes ALL results ANECDOTAL.**
Only 13 months of M5 data yields too few earnings gap-downs for statistical confidence.
All findings below are directional observations, not tradeable signals.

---

## TEST 0: M5 Data Coverage

| Threshold | N Events | Flag |
|-----------|----------|------|
| Gap <= -3% | 14 | LOW N |
| Gap <= -5% | 9 | ANECDOTAL |
| Gap <= -7% | 7 | ANECDOTAL |
| Gap <= -10% | 3 | ANECDOTAL |
| Gap >= +3% | 19 | — |

11 unique tickers contributed gap-down events. No single ticker dominated.

---

## TEST 1: 6-Point Recovery Curve by Drift Direction

**Split: Group A (drift_5d > 0, N=4) vs Group B (drift_5d <= 0, N=10)**

| Time (ET) | Group A (recovered) | Group B (continued down) | Separation |
|-----------|--------------------|-----------------------|------------|
| 10:00 | 0.190 | 0.187 | +0.003 |
| **10:30** | **0.450** | **0.212** | **+0.238** |
| 12:00 | 0.451 | 0.237 | +0.213 |
| 13:00 | 0.432 | 0.312 | +0.120 |
| 13:30 | 0.412 | 0.305 | +0.107 |
| 16:00 | 0.614 | 0.445 | +0.169 |

### Key Finding: **Separation peaks at 10:30 ET — exactly ANT's "1 hour" mark**

- At 10:00 ET (30 min): zero separation (0.003) — opening noise, no signal
- At 10:30 ET (1 hour): **maximum separation (+0.238)** — the groups diverge here
- After 10:30, separation SHRINKS — late-day price action adds noise, not signal
- **Group A stocks that recovered over 5 days showed recovery_ratio = 0.45 at 10:30**
- **Group B stocks that continued falling only recovered 0.21 at 10:30**

This is directionally consistent with ANT's claim that the 1-hour mark is the key measurement point,
even though ANT-1's daily close measurement showed zero predictive power.

---

## TEST 2: Optimal Recovery Measurement Time (Spearman Correlation)

| Time (ET) | Zone | Spearman rho | p-value | Significant |
|-----------|------|-------------|---------|-------------|
| 10:00 | Zone 1 | -0.2352 | 0.4183 | NO |
| 10:30 | Zone 2 | +0.1560 | 0.5942 | NO |
| 12:00 | Zone 2-3 | +0.0242 | 0.9346 | NO |
| 13:00 | Zone 3 | -0.2396 | 0.4094 | NO |
| **13:30** | **Bar 1** | **-0.4022** | **0.1540** | **NO (marginal)** |
| 16:00 | Close | -0.0286 | 0.9228 | NO |

### Observations
- No time point reaches p < 0.05 (N=14 is too small)
- 13:30 ET shows the strongest rho at -0.40 (p=0.15) — but this is **negative**,
  meaning higher recovery at 13:30 predicts WORSE 5-day drift (opposite of ANT)
- 10:30 ET has the only **positive** rho (+0.16) — consistent with ANT's direction
  but not statistically significant
- The contrast between 10:30 (+0.16) and 13:30 (-0.40) suggests early recovery is
  a different signal than late recovery — they may predict in opposite directions

### Comparison to ANT-1
- ANT-1 daily close: rho = +0.02, p = 0.92 (zero signal)
- ANT-2 at 10:30: rho = +0.16, p = 0.59 (right direction, not significant)
- ANT-2 at 13:30: rho = -0.40, p = 0.15 (strongest but wrong direction for ANT)
- **M5 timing does show MORE structure than daily, but N is too small to confirm**

---

## TEST 3: Recovery Trajectory Shape vs Drift

| Shape | N | Mean Drift 1d | Mean Drift 5d | Median 5d | WR (5d up) |
|-------|---|---------------|---------------|-----------|------------|
| EARLY_HOLD | 4 | -1.88% | -6.15% | -1.58% | 50.0% |
| LATE_REVERSAL | 2 | -2.35% | -3.26% | -3.26% | 0.0% |
| MIXED | 8 | -1.18% | -2.12% | -3.32% | 25.0% |
| NO_RECOVERY | 0 | — | — | — | — |
| EARLY_FADE | 0 | — | — | — | — |

### Observations
- **No NO_RECOVERY or EARLY_FADE events** in our small sample — can't test ANT's key contrasts
- EARLY_HOLD (ANT's "strongest zombie") actually shows the WORST 5d drift (-6.15%) — opposite of prediction
- ALL shape categories show negative drift — these gap-down stocks kept falling regardless of intraday pattern
- Only 25% overall WR (5d up) — heavy bear bias in this sample (includes April 2025 tariff crash period)

### Caveat
The April 2025 market-wide selloff likely contaminates these results. Several "earnings" gap-downs
were actually macro-driven, making recovery ratio meaningless for those events.

---

## TEST 4: Zone-Based Entry Timing

**Filtered to events with recovery >= 0.25 at 10:30 ET (N=4, ALL ANECDOTAL):**

| Entry Time | N | Mean Intraday | Mean 5d | WR | PF |
|------------|---|--------------|---------|----|----|
| 10:00 ET | 4 | +2.12% | -0.10% | 25% | 0.96 |
| 10:30 ET | 4 | +0.97% | -0.67% | 25% | 0.70 |
| 12:00 ET | 4 | +1.84% | -0.98% | 25% | 0.56 |
| 13:30 ET | 4 | +1.62% | -1.03% | 25% | 0.54 |

- All entries show positive INTRADAY return but negative 5-day return
- Earlier entry (10:00) shows best PF but still < 1.0
- N=4 is completely meaningless for strategy conclusions

---

## TEST 5: Gap Severity x M5 Recovery Interaction

Recovery measured at 12:00 ET (Zone 2 end):

|  | Gap -3% to -5% | Gap -5% to -10% | Gap < -10% |
|---|---|---|---|
| Rec < 0.20 | -15.39% (N=2) | +3.47% (N=4) | N/A |
| Rec 0.20-0.40 | -17.19% (N=1) | -4.06% (N=1) | -3.31% (N=3) |
| Rec > 0.40 | -0.08% (N=2) | +0.13% (N=1) | N/A |

All cells ANECDOTAL. Notable: moderate gaps (-5% to -10%) with low recovery show +3.47%
(mean reversion), consistent with ANT-1 finding that gap severity matters.

---

## TEST 6: M5 Zombie Strategy Backtest

### Entry at 12:00 ET (Zone 2 end, with sustainability filter)
- **0 trades** — no events passed: gap <= -5% + recovery >= 0.25 at 10:30 + recovery holding at 12:00

### Entry at 10:30 ET (ANT's 1-hour mark)
- **1 trade** — stopped out for -5.01%
- Entry conditions too restrictive for 13-month sample

---

## CHARTS

Saved to `backtest_output/ant2/`:
1. `ant2_recovery_curves.png` — 6-point curves: recovered vs continued (separation visible at 10:30)
2. `ant2_spearman_by_time.png` — Spearman rho bars by time point
3. `ant2_shape_drift.png` — Box plot: drift by trajectory shape
4. `ant2_entry_timing.png` — Entry timing comparison

---

## VERDICT

### Does M5 reveal what daily missed?

| Question | Answer | Confidence |
|----------|--------|------------|
| Does recovery curve separate by drift outcome? | **YES — at 10:30 ET** (sep=+0.238) | LOW (N=14) |
| Is 10:30 ET the best measurement time? | Best separation yes; best rho is 13:30 (negative) | LOW |
| Does trajectory shape predict drift? | No — EARLY_HOLD worst, all shapes negative | ANECDOTAL (N=4-8) |
| Is there an optimal entry time? | No clear winner, all PF < 1.0 | ANECDOTAL (N=4) |
| Does M5 improve on ANT-1 daily? | **Directionally yes** — more structure visible | INSUFFICIENT N |

### Key Takeaways

1. **The 10:30 ET recovery curve separation (+0.238) is the most interesting finding.**
   Stocks that will recover over 5 days show recovery_ratio ≈ 0.45 at the 1-hour mark,
   while stocks that keep falling show only 0.21. This is consistent with ANT's core
   intuition that the 1-hour mark matters.

2. **But the Spearman rho tells a different story.** The strongest correlation is at 13:30 ET
   with rho = -0.40 (negative!) — meaning higher late-day recovery predicts WORSE 5d drift.
   This could be a "dead cat bounce" effect visible only in M5.

3. **Trajectory shape is NOT predictive** with current data. EARLY_HOLD (ANT's best zombie)
   actually performs worst. This may be contaminated by the April 2025 macro selloff.

4. **We cannot draw conclusions with N=14.** The infrastructure works, the methodology is sound,
   but 13 months of M5 data produces too few earnings gap-downs.

### Comparison to ANT-1

| Metric | ANT-1 (Daily, N=30) | ANT-2 (M5, N=14) |
|--------|---------------------|-------------------|
| Recovery → drift correlation | rho=+0.02, p=0.92 | rho=+0.16 at 10:30, p=0.59 |
| Recovery direction | Low rec bounces MORE | Low rec at 10:30 shows less recovery for fallers |
| Curve separation | N/A (single point) | **+0.238 at 10:30** (most promising finding) |
| Shape predictive? | N/A | No (all shapes negative) |
| Tradeable? | No | No |

### Recommendations

1. **DO NOT deploy any recovery-ratio-based filter** — insufficient evidence at all granularities
2. **If more M5 data becomes available** (2+ years), re-run this test — the 10:30 ET separation
   is the one finding worth validating with a larger sample
3. **Close the ANT research track** for now — two tests (daily + M5) show no tradeable signal
4. **For Module 5 (PEAD-lite):** proceed with mechanical PEAD spec without recovery ratio filter

---

## REPRODUCIBILITY

```bash
cd /home/user/stock-data-mining
python3 ant2_m5_recovery.py

# Outputs in backtest_output/ant2/:
# ANT2_summary.json, events_m5.csv, ant2_*.png (4 charts)
```
