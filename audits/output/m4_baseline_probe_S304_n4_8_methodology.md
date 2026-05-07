# N=4-8 VIX Threshold Sweep Reconciliation — M4 Baseline Probe S304

**Source script:** `scripts/m4_vix_threshold_sweep.py`
**Results file:** `scripts/m4_vix_threshold_sweep_results.json`

## Key Finding

At VIX_GATE=25 standalone harness fires N=7 over 5yr. Canonical production fires N=47. Ratio: 47/7 ≈ 6.714285714285714. Expected from HARN-1.1 ratio of 6.7: 7.0. Consistent: True.

**HARN-1.1 consistency:** CONSISTENT with HARN-1.1

## Methodology

- What was swept: VIX_GATE from 20 to 30 in 8 steps
- Harness: scripts/_production_mirror/module4_mirror.py (standalone)
- Data: local Fetched_Data/*_m5_extended.csv

## All Thresholds

| VIX Gate | N | PF | WR |
|----------|---|----|----|
| 20.0 | 8 | 18.71 | 87.50% |
| 22.0 | 7 | 11.44 | 85.71% |
| 23.0 | 7 | 11.44 | 85.71% |
| 24.0 | 7 | 11.44 | 85.71% |
| 25.0 | 7 | 11.44 | 85.71% |
| 26.0 | 7 | 11.44 | 85.71% |
| 28.0 | 7 | 11.44 | 85.71% |
| 30.0 | 4 | N/A | 100.00% |

## Delta from Canonical N=47

- N=47 source: production system (canonical)
- N=4-8 source: standalone harness VIX sweep at various thresholds

**Relationship:** N=4-8 figures are HARN-1.1 artifacts. The standalone harness fires ~7 triggers per 5yr run vs 47 in production. This is a structural difference (not a bug), documented as Principle #57 candidate.