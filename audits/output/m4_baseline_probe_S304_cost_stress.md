# Cost Stress Sensitivity — M4 Baseline Probe S304

**Trades file:** `backtest_results/m4_5yr_trades.csv`
**N (local):** 28 | **Canonical N:** 47
**Canonical PF (0bps):** 21.38

## PF vs Slippage

| Slippage (bps) | PF | WR | Pass PF≥10 |
|----------------|----|----|------------|
| 0 | 4.9527 | 71.43% | NO |
| 5 | 4.8630 | 71.43% | NO |
| 10 | 4.7754 | 71.43% | NO |
| 15 | 4.6899 | 71.43% | NO |
| 25 | 4.5247 | 71.43% | NO |
| 50 | 4.1239 | 67.86% | NO |

**PF at 15bps round-trip:** 4.6899
**Pass (PF≥10 at 15bps):** False
**Breakeven (PF<10 first at):** 5 bps

## HARN-1.1 Caveat

HARN-1.1 NOTE: Local trades N=28 (vs canonical N=47). Results are indicative; canonical PF=21.38. Cost stress at 0bps should approximate canonical PF if HARN-1.1 ratio holds.