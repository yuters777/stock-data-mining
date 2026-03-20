# PH5: Beta × VIX Interaction — Power Hour Subset Analysis

**Zone 5** (Power Hour): 14:45–16:00 ET  
**Zone 3** (Midday Lull): 12:00–13:30 ET  
**Metric**: Mean absolute return = |close_end − close_start| / close_start  
**Beta**: 60-day trailing OLS beta vs SPY, averaged (from PH4)  
**VIX**: CBOE VIX daily close (FRED VIXCLS, from PH2)  
**Data**: M5 regular-session bars, 18 tickers (9 high-beta + 9 low-beta)  

## Subset Definitions

| Dimension | Split | Criteria |
|-----------|-------|----------|
| Beta group | High-beta (top 9) | SPY, MARA, MU, TSLA, AMD, COIN, PLTR, TSM, AMZN |
| Beta group | Low-beta (bottom 9) | TXN, AAPL, BABA, MSFT, SNOW, JPM, V, COST, VIXY |
| VIX regime | Elevated+ | VIX daily close >= 20 |
| VIX regime | Low/Normal | VIX daily close < 20 |

## Results

| # | Subset | N days | N ticker-days | Mean \|Ret\| Z5 (bps) | Mean \|Ret\| Z3 (bps) | Ratio Z5/Z3 | T-stat | P-value | Sig |
|---|--------|-------:|--------------:|----------------------:|----------------------:|------------:|-------:|--------:|:---:|
| 1 | High-beta × Elevated+ VIX        |     79 |           711 |                  58.3 |                  53.7 |        1.09 |   1.44 |  0.1507 |     |
| 2 | High-beta × Low/Normal VIX       |    194 |          1746 |                  38.4 |                  31.9 |        1.20 |   4.49 |  0.0000 | *** |
| 3 | Low-beta × Elevated+ VIX         |     79 |           699 |                  52.9 |                  64.7 |        0.82 |  -2.31 |  0.0208 |  *  |
| 4 | Low-beta × Low/Normal VIX        |    194 |          1742 |                  30.3 |                  35.0 |        0.86 |  -2.98 |  0.0029 | **  |

**Significance**: \*\*\* p<0.001, \*\* p<0.01, \* p<0.05 (paired t-test, Zone 5 − Zone 3)

## Key Question: Is Subset #1 the Only One Where Zone 5 Reliably Beats Zone 3?

**No** — Zone 5 significantly beats Zone 3 in: 2. High-beta × Low/Normal VIX.

### Interpretation by Subset

- **1. High-beta × Elevated+ VIX**: Zone 5 > Zone 3 (ratio 1.09, p=0.1507, not significant)
- **2. High-beta × Low/Normal VIX**: Zone 5 > Zone 3 (ratio 1.20, p=0.0000, highly significant)
- **3. Low-beta × Elevated+ VIX**: Zone 3 > Zone 5 (ratio 0.82, p=0.0208, significant)
- **4. Low-beta × Low/Normal VIX**: Zone 3 > Zone 5 (ratio 0.86, p=0.0029, significant)

### Implications

- High-beta tickers in elevated+ VIX: Z5/Z3 = 1.09 — Power Hour advantage present
- High-beta tickers in low/normal VIX: Z5/Z3 = 1.20 — Power Hour advantage present
- Low-beta tickers in elevated+ VIX: Z5/Z3 = 0.82 — Zone 3 dominates
- Low-beta tickers in low/normal VIX: Z5/Z3 = 0.86 — Zone 3 dominates
- The Power Hour effect requires **high beta**; VIX level modulates the magnitude but does not flip the sign for high-beta names
