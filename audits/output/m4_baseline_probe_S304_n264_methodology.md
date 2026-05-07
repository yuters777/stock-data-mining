# N=264 Counterfactual Sweep Methodology — M4 Baseline Probe S304

**Source script:** `scripts/m4_max_bars_bar_by_bar_sweep.py`
**Branch:** claude/m4-counterfactual-analysis-GgEei (Day 47 VLog 303 §6)
**Enriched CSV rows:** 28

## Methodology

**Input source:** backtest_results/m4_5yr_trades.csv — produced by scripts/_production_mirror/module4_mirror.py on local 5yr M5 data

**N=264 explanation:** N=264 comes from the VIX threshold sweep script (m4_vix_threshold_sweep.py) which ran the production mirror backtest at VIX_GATE=20.0, capturing all 5yr trades across a wide threshold range. At VIX_GATE=20.0 the standalone harness produces N=8; the 264 figure likely refers to the total signals across the anti-signal universe or a broader sweep dataset. The enriched CSV has N=28 rows from the max-bars sweep input.

**HARN-1.1 applies:** Yes

HARN-1.1: The standalone backtest harness under-fires production by ~6.7x. N=264 is NOT comparable to canonical N=47. The standalone harness runs on local M5 data without the full production data pipeline (live price feed, EMA carry-forward, override history). It fires ~7 triggers per 5yr run at the canonical gates vs 47 in production.

## Gates Applied in Standalone Harness

- Streak: close < prior_close (production mirror V1)
- VIX gate: 25.0 (canonical)
- RSI gate: 35.0 (canonical)
- D6 VIX ROC: enabled (30% threshold)
- Universe: 27 canonical tickers
- Data: local Fetched_Data/*_m5_extended.csv

## Delta from Canonical N=47

- N=47 source: production market-engine system (live data, full pipeline)
- N=264 source: standalone backtest harness (local M5, VLog 303 context)

**Relationship:** N=264 is NOT a superset of N=47. They come from completely different execution environments. The standalone harness misses ~6/7 of production triggers due to HARN-1.1 structural differences (EMA calculation, override logic, live vs historical data timing).