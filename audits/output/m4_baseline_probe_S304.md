# M4 Baseline Probe S304 — Final Report

**Generated:** 2026-05-07T12:10:47.541904Z
**Spec:** spec_2026_05_07_001_dr_probe_m4_baseline v2 FINAL

---

## 1. Executive Summary

**VERDICT: NO-GO**

### Passing Criteria

- Count drift table: all 4 sources attributed
- Look-ahead: 28/28 trades clean
- Survivorship: no material post-hoc selection bias
- N=57: source located (S44 V0 streak sensitivity)

### Failing Criteria / Open Items

- LOYO: PF < 5.0 when excluding years [2025]
- LOTO: PF < 5.0 when excluding tickers ['AMD', 'AVGO', 'BIDU', 'C', 'COIN', 'GS', 'MARA', 'MU', 'NVDA', 'PLTR', 'TSLA', 'TSM', 'V']
- LOVO: PF < 5.0 on some cluster removal
- Cost stress: PF = 4.6899 at 15bps (< 10.0)
- DB baseline: snapshot not provided (Step 0.1 prerequisite pending)

---

## 2. Authoritative Baseline

| Field | Value |
|-------|-------|
| baseline_n | 47 |
| baseline_pf | 21.38 |
| baseline_wr | 0.94 |
| baseline_mean_return | 7.52% |
| baseline_sharpe | 1.38 |
| locked_date | 2026-04-16 |
| source | module_baselines table (market-engine market.db) |

**Snapshot status:** Not provided (Step 0.1 prerequisite). Run: `scp root@market-engine.dev:/var/lib/market-system/market.db data/snapshots/market_db_snapshot_$(date +%Y%m%d).db`

---

## 3. Count Drift Reconciliation Table

| N Value | Label | Source | Relationship to Canonical |
|---------|-------|--------|--------------------------|
| 47 | N=47 Canonical | `market-engine/src/market_engine/module4.py (produc...` | IS canonical — authoritative source... |
| 57 | N=57 S44-V0 | `scripts/m4_backtest_5yr.py (S44 research sprint, V...` | DIFFERENT methodology: pre-D6 filter, different streak defin... |
| ~264 (sweep input) / 28 (local mirror) | N=264/28 Counterfactual | `scripts/m4_max_bars_bar_by_bar_sweep.py + scripts/...` | DIFFERENT execution environment (HARN-1.1). Not comparable t... |
| 4-8 (VIX sweep range) | N=4-8 VIX Threshold Sweep | `scripts/m4_vix_threshold_sweep.py...` | DIFFERENT execution environment (HARN-1.1). N=7 at canonical... |

4 N-values reconciled: N=47 (canonical production), N=57 (S44 V0 research), N=264/28 (standalone harness counterfactual), N=4-8 (standalone harness VIX sweep). Each attributed to distinct source and methodology. HARN-1.1 explains standalone-vs-production discrepancy.

---

## 4. Look-Ahead Audit Result

**N:** 28 | **Clean:** 28 | **Violations:** 0

Audit checks entry gate compliance (VIX>=25, RSI<35) on local N=28 trades. Full look-ahead audit (4H bar completion, EMA cross timing) requires raw M5 data per trade — partial coverage from trade CSV metadata.
**Verdict:** PASS

---

## 5. RTH Calendar Audit Result

**N:** 28 | **Clean:** 28 | **Violations:** 0
RTH calendar audit on local N=28 trades. NYSE calendar: unavailable — holiday checks skipped. Entry/exit timestamp hours not available in trade CSV (date-only); RTH hour check requires raw M5 data.

---

## 6. Corporate Action Audit Result

**N:** 28 | **Clean:** 28 | **Flagged:** 0
Corporate action audit: checks known splits/dividends for canonical tickers. FMP data is assumed split-adjusted (FMP default). Flagged events require manual verification that returns are not inflated. Audit is NOT exhaustive — dividend/special distribution checks require live FMP API.

---

## 7. Survivorship Audit Result

**Post-hoc risk candidates:** ['ARM']
**Material survivorship bias:** False
**Tickers missing local data:** ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA', 'AMD', 'SMCI', 'PLTR', 'AVGO', 'ARM', 'TSM', 'MU', 'INTC', 'COST', 'COIN', 'MSTR', 'MARA', 'C', 'GS', 'V', 'BA', 'JPM', 'BABA', 'JD', 'BIDU']

Known corporate events documented: ARM IPO (2023-09), SMCI delisting risk (2024-08)

---

## 8. Robustness Audits

### Leave-One-Year-Out (LOYO)

Full sample: N=28, PF=4.9527

| Excluded Year | N | PF | Pass (PF≥5) |
|---------------|---|----|-------------|
| 2025 | 2 | 0.0000 | **FAIL** |
| 2026 | 26 | 7.2945 | YES |
**LOYO verdict:** FAIL

### Leave-One-Ticker-Out (LOTO)

Full sample: N=28, PF=4.9527

| Excluded Ticker | N | PF | Pass (PF≥5) |
|-----------------|---|----|-------------|
| AMD | 27 | 4.6485 | **FAIL** |
| AMZN | 26 | 5.1380 | YES |
| AVGO | 27 | 4.4105 | **FAIL** |
| BA | 26 | 5.4205 | YES |
| BABA | 27 | 6.5545 | YES |
| BIDU | 27 | 4.9444 | **FAIL** |
| C | 26 | 4.6535 | **FAIL** |
| COIN | 25 | 4.3014 | **FAIL** |
| COST | 27 | 5.3519 | YES |
| GOOGL | 27 | 5.6632 | YES |
| GS | 27 | 4.8108 | **FAIL** |
| MARA | 27 | 4.4656 | **FAIL** |
| META | 26 | 7.2473 | YES |
| MU | 26 | 4.3739 | **FAIL** |
| NVDA | 26 | 4.1706 | **FAIL** |
| PLTR | 27 | 4.5813 | **FAIL** |
| TSLA | 27 | 4.9195 | **FAIL** |
| TSM | 26 | 4.7799 | **FAIL** |
| V | 27 | 4.9354 | **FAIL** |
**LOTO verdict:** FAIL

### Leave-One-VIX-Cluster-Out (LOVO)

Clusters found: 2
VIX data available: True

| Cluster | Start | End | Days | PF | Pass (PF≥5) |
|---------|-------|-----|------|----|-------------|
| 1 | 2025-04-03 | 2025-04-24 | 22 | 3.6807 | **FAIL** |
| 2 | 2026-03-06 | 2026-03-09 | 4 | 4.9527 | **FAIL** |
**LOVO verdict:** FAIL

---

## 9. Cost Stress Sensitivity

**N (local):** 28 | Canonical N: 47
**PF at 15bps:** 4.6899 | Pass (≥10): False

| Slippage (bps) | PF | Pass PF≥10 |
|----------------|----|-----------| 
| 0 | 4.9527 | NO |
| 5 | 4.8630 | NO |
| 10 | 4.7754 | NO |
| 15 | 4.6899 | NO |
| 25 | 4.5247 | NO |
| 50 | 4.1239 | NO |

HARN-1.1 NOTE: Local trades N=28 (vs canonical N=47). Results are indicative; canonical PF=21.38. Cost stress at 0bps should approximate canonical PF if HARN-1.1 ratio holds.

---

## 10. Forward-OOS Context

Snapshot not provided — forward-OOS rows unavailable.

---

## 11. Phase 1 + 2 Decision

**VERDICT: NO-GO**

Phase 1 and Phase 2 BLOCKED pending resolution of failing criteria above.

**Next steps:**
- Resolve: LOYO: PF < 5.0 when excluding years [2025]
- Resolve: LOTO: PF < 5.0 when excluding tickers ['AMD', 'AVGO', 'BIDU', 'C', 'COIN', 'GS', 'MARA', 'MU', 'NVDA', 'PLTR', 'TSLA', 'TSM', 'V']
- Resolve: LOVO: PF < 5.0 on some cluster removal
- Resolve: Cost stress: PF = 4.6899 at 15bps (< 10.0)
- Resolve: DB baseline: snapshot not provided (Step 0.1 prerequisite pending)

---

## 12. Anchor

| Field | Value |
|-------|-------|
| Spec ID | spec_2026_05_07_001_dr_probe_m4_baseline |
| Spec version | v2 FINAL |
| market-engine HEAD SHA | 9a6f7e1 |
| stock-data-mining HEAD SHA | 79c1894 |
| Schema version | v90 (module_decisions PR #628) |
| Baseline locked date | 2026-04-16 |
| Report generated | 2026-05-07T12:10:47.541904Z |