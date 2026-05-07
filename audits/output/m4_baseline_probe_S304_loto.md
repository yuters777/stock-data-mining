# Leave-One-Ticker-Out Robustness — M4 Baseline Probe S304

**Full sample:** N=28, PF=4.9527, WR=0.7143
**Canonical:** N=47, PF=21.38
**Min PF threshold:** 5.0

**Tickers in canonical universe but not in local data:** ['AAPL', 'ARM', 'INTC', 'JD', 'JPM', 'MSFT', 'MSTR', 'SMCI']

## Per-Ticker Results

| Excluded Ticker | N | N Excluded | PF | WR | PF Delta | Pass (PF≥5) |
|-----------------|---|------------|----|----|----------|-------------|
| AMD | 27 | 1 | 4.6485 | 70.37% | -0.3042 | **FAIL** |
| AMZN | 26 | 2 | 5.1380 | 73.08% | +0.1852 | YES |
| AVGO | 27 | 1 | 4.4105 | 70.37% | -0.5422 | **FAIL** |
| BA | 26 | 2 | 5.4205 | 73.08% | +0.4678 | YES |
| BABA | 27 | 1 | 6.5545 | 74.07% | +1.6018 | YES |
| BIDU | 27 | 1 | 4.9444 | 70.37% | -0.0083 | **FAIL** |
| C | 26 | 2 | 4.6535 | 69.23% | -0.2992 | **FAIL** |
| COIN | 25 | 3 | 4.3014 | 72.00% | -0.6513 | **FAIL** |
| COST | 27 | 1 | 5.3519 | 74.07% | +0.3992 | YES |
| GOOGL | 27 | 1 | 5.6632 | 74.07% | +0.7105 | YES |
| GS | 27 | 1 | 4.8108 | 70.37% | -0.1420 | **FAIL** |
| MARA | 27 | 1 | 4.4656 | 70.37% | -0.4871 | **FAIL** |
| META | 26 | 2 | 7.2473 | 76.92% | +2.2945 | YES |
| MU | 26 | 2 | 4.3739 | 69.23% | -0.5788 | **FAIL** |
| NVDA | 26 | 2 | 4.1706 | 69.23% | -0.7821 | **FAIL** |
| PLTR | 27 | 1 | 4.5813 | 70.37% | -0.3714 | **FAIL** |
| TSLA | 27 | 1 | 4.9195 | 70.37% | -0.0332 | **FAIL** |
| TSM | 26 | 2 | 4.7799 | 69.23% | -0.1729 | **FAIL** |
| V | 27 | 1 | 4.9354 | 70.37% | -0.0173 | **FAIL** |

**LOTO verdict:** NO-GO

**HARN-1.1:** Local N=28 vs canonical N=47 (HARN-1.1)