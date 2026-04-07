# Module 4 MAE/MFE Distribution + Stop Variant Analysis

**Date:** 2026-04-07 13:27
**Tickers:** 25
**Trigger:** 3 consecutive 4H down bars (close < open) + VIX >= 25.0 + RSI < 35.0
**Entry:** 4H trigger bar close
**Exit:** first 4H close >= EMA21 (hard max 10 bars)
**Total trades:** 57 (Winners: 55, Losers: 2)

## Table 4: Stop Variant Comparison

| Variant | N | Stopped | Win_Stopped | Loss_Stopped | Mean% | WR% | PF | Max_Loss% | ES_5% | Sharpe |
|---------|---|---------|-------------|--------------|-------|-----|-----|-----------|-------|--------|
| V0 | 57 | 0 | 0 | 0 | +8.85 | 96 | 148.13 | -2.53 | -0.67 | 12.44 |
| V1 | 57 | 9 | 7 | 2 | +7.17 | 84 | 12.66 | -5.04 | -4.99 | 7.93 |
| V2 | 57 | 5 | 5 | 0 | +7.48 | 88 | 12.13 | -8.78 | -8.07 | 8.14 |
| V3 | 57 | 4 | 4 | 0 | +7.68 | 89 | 12.81 | -9.41 | -8.85 | 8.41 |
| V4 | 57 | 3 | 3 | 0 | +7.98 | 91 | 17.61 | -9.54 | -7.99 | 9.22 |
| V5 | 57 | 3 | 3 | 0 | +7.98 | 91 | 17.61 | -9.54 | -7.99 | 9.22 |
| V6 | 57 | 2 | 2 | 0 | +8.25 | 93 | 22.02 | -9.54 | -7.16 | 9.89 |
| V7 | 57 | 2 | 2 | 0 | +8.25 | 93 | 22.02 | -9.54 | -7.16 | 9.89 |
| V8 | 57 | 1 | 1 | 0 | +8.63 | 95 | 38.92 | -9.54 | -4.32 | 11.13 |
| V9 | 57 | 1 | 1 | 0 | +8.63 | 95 | 38.92 | -9.54 | -4.32 | 11.13 |
| V10 | 57 | 1 | 1 | 0 | +8.63 | 95 | 38.92 | -9.54 | -4.32 | 11.13 |

## Acceptance Criteria

- **V1**: False stop rate = 12.7% → **MARGINAL**
- **V2**: False stop rate = 9.1% → **PASS**
- **V3**: False stop rate = 7.3% → **PASS**
- **V4**: False stop rate = 5.5% → **PASS**
- **V5**: False stop rate = 5.5% → **PASS**
- **V6**: False stop rate = 3.6% → **PASS**
- **V7**: False stop rate = 3.6% → **PASS**
- **V8**: False stop rate = 1.8% → **PASS**
- **V9**: False stop rate = 1.8% → **PASS**
- **V10**: False stop rate = 1.8% → **PASS**

