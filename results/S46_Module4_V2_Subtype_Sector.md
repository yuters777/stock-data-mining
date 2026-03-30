# S46 Module 4 V2 — Part 2: Subtype Attribution + Sector Check

**Date:** 2026-03-30 06:50
**Tickers:** 25 equity (excl SPY, VIXY)
**Filters:** prior-day VIX >= 25.0, 4H RSI(14) < 35.0
**Entry:** 4H trigger bar close
**Exit:** first 4H close >= EMA21 (hard max 10 bars)
**V0:** close < open, 3 consecutive
**V2:** close < prior_bar_close, 3 consecutive

---

## Test A: V2-Only Trigger Subtypes

```
V2-ONLY SUBTYPE ATTRIBUTION
==================================================

Total V2 trades: 74
V2-only trades (not in V0): 29

GAP_DOWN_GREEN      : N= 11 ( 37.9%) | Mean=+7.67% | WR=100%
FLAT_OPEN_DRIFT     : N=  7 ( 24.1%) | Mean=+9.85% | WR=100%
TINY_LOWER          : N=  0 (  0.0%) | Mean=+0.00% | WR=0%
OTHER               : N= 11 ( 37.9%) | Mean=+7.42% | WR=91%

Dominant: GAP_DOWN_GREEN (38% of V2-only trades)

V2-only trade details:
| Ticker | Date | Subtype | Open | Close | PriorCl | Ret% | Win |
|--------|------|---------|------|-------|---------|------|-----|
| AMZN | 2025-04-04 | FLAT_OPEN_DRIFT   | 174.78 | 170.98 | 174.80 | +11.68% | Y |
| META | 2025-04-04 | FLAT_OPEN_DRIFT   | 507.00 | 503.62 | 507.02 | +15.84% | Y |
| MSFT | 2025-04-04 | FLAT_OPEN_DRIFT   | 361.76 | 356.98 | 361.72 | +5.38% | Y |
| AMD | 2025-04-07 | FLAT_OPEN_DRIFT   | 83.84 | 83.63 | 83.83 | +15.65% | Y |
| GS | 2025-04-07 | FLAT_OPEN_DRIFT   | 456.75 | 455.44 | 456.57 | +11.20% | Y |
| MSFT | 2025-04-07 | FLAT_OPEN_DRIFT   | 356.39 | 355.02 | 356.39 | +5.96% | Y |
| MARA | 2025-12-26 | FLAT_OPEN_DRIFT   | 9.60 | 9.59 | 9.60 | +3.23% | Y |
| TXN | 2025-03-11 | GAP_DOWN_GREEN    | 171.72 | 171.80 | 171.81 | +1.26% | Y |
| AMZN | 2025-04-04 | GAP_DOWN_GREEN    | 167.14 | 174.80 | 178.36 | +9.24% | Y |
| META | 2025-04-04 | GAP_DOWN_GREEN    | 505.48 | 507.02 | 530.41 | +15.06% | Y |
| MSFT | 2025-04-04 | GAP_DOWN_GREEN    | 361.35 | 361.72 | 370.27 | +3.99% | Y |
| AAPL | 2025-04-07 | GAP_DOWN_GREEN    | 176.44 | 180.76 | 187.57 | +12.30% | Y |
| AMD | 2025-04-07 | GAP_DOWN_GREEN    | 80.68 | 83.83 | 85.74 | +15.38% | Y |
| GS | 2025-04-07 | GAP_DOWN_GREEN    | 437.86 | 456.57 | 460.70 | +10.92% | Y |
| MSFT | 2025-04-07 | GAP_DOWN_GREEN    | 348.20 | 356.39 | 356.98 | +5.55% | Y |
| IBIT | 2025-10-17 | GAP_DOWN_GREEN    | 59.89 | 60.28 | 61.42 | +4.11% | Y |
| BABA | 2025-11-21 | GAP_DOWN_GREEN    | 151.98 | 152.85 | 153.28 | +5.03% | Y |
| IBIT | 2025-11-21 | GAP_DOWN_GREEN    | 47.49 | 47.70 | 48.98 | +1.51% | Y |
| TXN | 2025-03-11 | OTHER             | 182.32 | 171.81 | 180.83 | +0.97% | Y |
| V | 2025-03-11 | OTHER             | 335.91 | 327.49 | 339.11 | +1.21% | Y |
| BIDU | 2025-04-04 | OTHER             | 82.80 | 80.43 | 89.79 | +0.25% | Y |
| GOOGL | 2025-04-04 | OTHER             | 147.60 | 147.33 | 150.30 | +7.40% | Y |
| PLTR | 2025-04-04 | OTHER             | 80.07 | 73.91 | 83.65 | +14.91% | Y |
| V | 2025-04-04 | OTHER             | 327.56 | 316.87 | 336.78 | +4.07% | Y |
| AMD | 2025-04-08 | OTHER             | 86.14 | 81.47 | 83.63 | +18.72% | Y |
| BIDU | 2025-04-08 | OTHER             | 81.72 | 76.62 | 79.76 | +11.98% | Y |
| COIN | 2025-04-08 | OTHER             | 165.20 | 152.40 | 157.27 | +16.23% | Y |
| IBIT | 2025-04-08 | OTHER             | 45.54 | 43.46 | 44.29 | +7.64% | Y |
| GS | 2026-03-09 | OTHER             | 810.00 | 808.87 | 820.57 | -1.79% | N |

```

---

## Test B: Sector Concentration

```
SECTOR CONCENTRATION (all V2 triggers)
==================================================

Total V2 trades: 74

Tech           : N= 33 ( 44.6%) | Mean=+10.26% | WR=100% | Tickers: AAPL, AMD, AMZN, AVGO, GOOGL, META, MSFT, NVDA, PLTR
Crypto-proxy   : N=  8 ( 10.8%) | Mean=+10.07% | WR=100% | Tickers: COIN, IBIT, MARA
China ADR      : N=  3 (  4.1%) | Mean=+5.75% | WR=100% | Tickers: BABA, BIDU
Finance        : N= 13 ( 17.6%) | Mean=+6.77% | WR=92% | Tickers: C, GS, JPM, V
Semi           : N=  9 ( 12.2%) | Mean=+7.66% | WR=100% | Tickers: MU, TSM, TXN
Industrial     : N=  2 (  2.7%) | Mean=+17.21% | WR=100% | Tickers: BA
Consumer       : N=  1 (  1.4%) | Mean=-2.53% | WR=0% | Tickers: COST
Cloud/SaaS     : N=  3 (  4.1%) | Mean=+9.85% | WR=100% | Tickers: SNOW
Consumer Disc. : N=  2 (  2.7%) | Mean=+4.30% | WR=100% | Tickers: TSLA

VERDICT: DIVERSIFIED (largest sector: Tech at 45%)

Top sector breakdown (Tech):
  AAPL: N=3 | Mean=+6.83% | WR=100%
  AMD: N=8 | Mean=+14.03% | WR=100%
  AMZN: N=3 | Mean=+10.26% | WR=100%
  AVGO: N=1 | Mean=+20.28% | WR=100%
  GOOGL: N=3 | Mean=+8.70% | WR=100%
  META: N=3 | Mean=+15.13% | WR=100%
  MSFT: N=8 | Mean=+4.46% | WR=100%
  NVDA: N=1 | Mean=+13.14% | WR=100%
  PLTR: N=3 | Mean=+11.46% | WR=100%

```
