# S44 Module 2 — Part 3: Module 4 → Module 2 Handoff Analysis

**Date:** 2026-03-29 19:04
**Module 4 triggers:** 159 (3 consecutive 4H down + VIX >= 25)
**M4 exits (EMA21 touch):** 144
**Tickers:** 25/25

## Task A: Handoff Rate

**M4 exits:** 144
**Handoffs (gate flip UP within 10 bars):** 95
**Handoff rate:** 66.0%
**Non-handoffs:** 49 (34.0%)

**Average time to handoff:** 3.4 4H bars
**Median time to handoff:** 3.0 4H bars

### Timing Distribution

| Bars after M4 exit | Count | % of handoffs |
|-------------------|-------|---------------|
| +1 | 37 | 38.9% |
| +2 | 10 | 10.5% |
| +3 | 15 | 15.8% |
| +4 | 1 | 1.1% |
| +5 | 8 | 8.4% |
| +6 | 4 | 4.2% |
| +7 | 12 | 12.6% |
| +8 | 3 | 3.2% |
| +9 | 3 | 3.2% |
| +10 | 2 | 2.1% |

## Task B: Post-Handoff Returns vs Control

### Post-Handoff (entered at gate flip UP after M4 exit)

| Horizon | N | Mean% | Median% | WR% | PF | p-val |
|---------|---|-------|---------|-----|----|-------|
| +1 4H | 95 | +0.331 | +0.026 | 51.6 | 1.67 | 0.0624 |
| +2 4H | 95 | +0.434 | +0.009 | 50.5 | 1.60 | 0.0586 |
| +3 4H | 91 | +0.317 | +0.022 | 51.6 | 1.33 | 0.1818 |
| +5 4H | 88 | +0.228 | -0.091 | 48.9 | 1.17 | 0.2951 |

### Control Group (regular gate-UP, NOT post-M4)

| Horizon | N | Mean% | Median% | WR% | PF | p-val |
|---------|---|-------|---------|-----|----|-------|
| +1 4H | 7011 | +0.069 | +0.000 | 49.9 | 1.13 | 0.0013** |
| +2 4H | 7009 | +0.135 | +0.090 | 52.2 | 1.16 | 0.0000*** |
| +3 4H | 7007 | +0.202 | +0.133 | 52.8 | 1.20 | 0.0000*** |
| +5 4H | 7002 | +0.345 | +0.280 | 53.8 | 1.26 | 0.0000*** |

### Handoff vs Control Separation

| Horizon | Handoff Mean% | Control Mean% | Delta% | Sep p-val | Significant? |
|---------|--------------|--------------|--------|-----------|--------------|
| +1 4H | +0.331 | +0.069 | +0.262 | 0.2260 | no |
| +2 4H | +0.434 | +0.135 | +0.299 | 0.2820 | no |
| +3 4H | +0.317 | +0.202 | +0.116 | 0.7418 | no |
| +5 4H | +0.228 | +0.345 | -0.117 | 0.7833 | no |

## Task C: VIX Transition Analysis

### VIX Levels Through Transition

| Stage | N | Mean VIX | Median VIX | Min | Max |
|-------|---|----------|------------|-----|-----|
| M4 Trigger | 73 | 30.7 | 29.5 | 25.3 | 47.0 |
| M4 Exit | 88 | 24.9 | 25.5 | 13.6 | 52.3 |
| M2 Handoff | 87 | 23.4 | 24.7 | 14.2 | 40.7 |

**VIX < 25 at handoff:** 48 (55.2%)
**VIX >= 25 at handoff:** 39 (44.8%)

### VIX < 25 vs VIX >= 25 at Handoff — Forward Returns

| Horizon | VIX<25 Mean% | VIX<25 N | VIX>=25 Mean% | VIX>=25 N | Delta | p-val |
|---------|-------------|----------|--------------|-----------|-------|-------|
| +1 4H | +0.057 | 48 | +0.684 | 39 | -0.627 | 0.1937 |
| +2 4H | +0.295 | 48 | +0.755 | 39 | -0.461 | 0.4330 |
| +3 4H | -0.058 | 48 | +0.777 | 39 | -0.834 | 0.2386 |
| +5 4H | -0.188 | 48 | +0.741 | 39 | -0.929 | 0.2886 |

## Verdict

**Module 4→2 handoff = SAME as regular Module 2 → no special treatment needed.**

Post-handoff returns are not significantly different from control:
- Handoff: +0.317% at +3 4H bars (N=91)
- Control: +0.202% (N=7007)
- Delta: +0.116% (p=0.7418)

Module 4 exits that transition into uptrends are just regular Module 2 territory.
No linked-trade mechanism needed — standard Module 2 rules apply.

## Summary Statistics

- M4 triggers: 159
- M4 exits: 144
- Handoffs: 95 (66.0%)
- Control group: 7012 regular gate-UP bars
- Handoff scan window: 10 4H bars
- Forward horizons: +1 4H, +2 4H, +3 4H, +5 4H
