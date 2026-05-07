# Count Drift Reconciliation Table — M4 Baseline Probe S304

| N Value | Label | Source Type | Source Script | Methodology | Relationship to Canonical |
|---------|-------|-------------|---------------|-------------|--------------------------|
| 47 | N=47 Canonical | production | `market-engine/src/market_engine/module4.py (production system)` | Production M4 evaluation: live 4H bars, EMA carry-forward, override history, D6_... | IS canonical — authoritative source... |
| 57 | N=57 S44-V0 | research_backtest | `scripts/m4_backtest_5yr.py (S44 research sprint, V0 streak def)` | S44 streak sensitivity V0: streak = close<open (3 consecutive 4H bars), 25-ticke... | DIFFERENT methodology: pre-D6 filter, different streak definition, different tic... |
| ~264 (sweep input) / 28 (local mirror) | N=264/28 Counterfactual | standalone_harness | `scripts/m4_max_bars_bar_by_bar_sweep.py + scripts/_production_mirror/module4_mirror.py` | Standalone production-mirror harness on local 5yr M5 data. HARN-1.1 applies: ~6.... | DIFFERENT execution environment (HARN-1.1). Not comparable to N=47 canonical. St... |
| 4-8 (VIX sweep range) | N=4-8 VIX Threshold Sweep | standalone_harness_sweep | `scripts/m4_vix_threshold_sweep.py` | Same standalone harness as above, swept across VIX_GATE in [20,22,23,24,25,26,28... | DIFFERENT execution environment (HARN-1.1). N=7 at canonical VIX_GATE=25.0 confi... |

## Summary

4 N-values reconciled: N=47 (canonical production), N=57 (S44 V0 research), N=264/28 (standalone harness counterfactual), N=4-8 (standalone harness VIX sweep). Each attributed to distinct source and methodology. HARN-1.1 explains standalone-vs-production discrepancy.

**All sources attributed:** True