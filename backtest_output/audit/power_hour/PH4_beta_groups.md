# PH4: Power Hour Returns by Beta Group

**Zone 5** (Power Hour): 14:45–16:00 ET  
**Zone 3** (Midday Lull): 12:00–13:30 ET  
**Metric**: Mean absolute return = |close_end − close_start| / close_start  
**Beta**: 60-day trailing OLS beta of daily returns vs SPY, averaged over all rolling windows  
**Data**: M5 regular-session bars, 27 tickers, 3 groups of 9  

## Ticker Beta Rankings

| Rank | Ticker | Avg 60d Beta | Group |
|-----:|--------|-------------:|-------|
| 1 | SPY | 1.000 | High |
| 2 | MARA | 0.824 | High |
| 3 | MU | 0.705 | High |
| 4 | TSLA | 0.702 | High |
| 5 | AMD | 0.693 | High |
| 6 | COIN | 0.665 | High |
| 7 | PLTR | 0.606 | High |
| 8 | TSM | 0.512 | High |
| 9 | AMZN | 0.500 | High |
| 10 | IBIT | 0.478 | Medium |
| 11 | BA | 0.447 | Medium |
| 12 | NVDA | 0.406 | Medium |
| 13 | GOOGL | 0.384 | Medium |
| 14 | META | 0.362 | Medium |
| 15 | GS | 0.361 | Medium |
| 16 | C | 0.344 | Medium |
| 17 | BIDU | 0.333 | Medium |
| 18 | AVGO | 0.281 | Medium |
| 19 | TXN | 0.223 | Low |
| 20 | AAPL | 0.179 | Low |
| 21 | BABA | 0.177 | Low |
| 22 | MSFT | 0.177 | Low |
| 23 | SNOW | 0.145 | Low |
| 24 | JPM | 0.131 | Low |
| 25 | V | 0.100 | Low |
| 26 | COST | -0.195 | Low |
| 27 | VIXY | -3.830 | Low |

## Results: Zone 5 vs Zone 3 by Beta Group

| Group | Tickers | N ticker-days | Mean \|Ret\| Z5 (bps) | Mean \|Ret\| Z3 (bps) | Ratio Z5/Z3 | T-stat | P-value | Sig |
|-------|--------:|--------------:|----------------------:|----------------------:|------------:|-------:|--------:|:---:|
| High-beta    |       9 |          2538 |                  44.2 |                  38.2 |        1.16 |   4.48 |  0.0000 | *** |
| Medium-beta  |       9 |          2514 |                  36.5 |                  42.6 |        0.86 |  -4.19 |  0.0000 | *** |
| Low-beta     |       9 |          2509 |                  36.7 |                  43.1 |        0.85 |  -3.50 |  0.0005 | *** |

**Significance**: \*\*\* p<0.001, \*\* p<0.01, \* p<0.05 (paired t-test, Zone 5 − Zone 3)

## Summary

- **High-beta** (SPY, MARA, MU, TSLA, AMD, COIN, PLTR, TSM, AMZN): Z5 = 44.2 bps, Z3 = 38.2 bps, ratio 1.16 — Zone 5 higher (statistically significant)
- **Medium-beta** (IBIT, BA, NVDA, GOOGL, META, GS, C, BIDU, AVGO): Z5 = 36.5 bps, Z3 = 42.6 bps, ratio 0.86 — Zone 5 lower (statistically significant)
- **Low-beta** (TXN, AAPL, BABA, MSFT, SNOW, JPM, V, COST, VIXY): Z5 = 36.7 bps, Z3 = 43.1 bps, ratio 0.85 — Zone 5 lower (statistically significant)
