# PH2: Power Hour Returns by VIX Regime

**Zone 5** (Power Hour): 14:45–16:00 ET  
**Zone 3** (Midday Lull): 12:00–13:30 ET  
**Metric**: Mean absolute return = |close_end − close_start| / close_start  
**VIX Source**: CBOE VIX daily close (FRED VIXCLS)  
**Data**: M5 regular-session bars, 27 tickers, pooled across all tickers  

## VIX Regime Definitions

| Regime | VIX Range |
|--------|-----------|
| Low | < 16 |
| Normal | 16–20 |
| Elevated | 20–25 |
| High | >= 25 |

## Results

| Regime | N days | N ticker-days | Mean \|Ret\| Z5 (bps) | Mean \|Ret\| Z3 (bps) | Ratio Z5/Z3 | T-stat | P-value | Sig |
|--------|-------:|--------------:|----------------------:|----------------------:|------------:|-------:|--------:|:---:|
| Low      |     66 |          1779 |                  31.2 |                  29.3 |        1.06 |   1.25 |  0.2100 |     |
| Normal   |    128 |          3454 |                  34.9 |                  37.1 |        0.94 |  -2.08 |  0.0379 |  *  |
| Elevated |     56 |          1500 |                  46.3 |                  47.5 |        0.98 |  -0.57 |  0.5676 |     |
| High     |     23 |           609 |                  68.7 |                  87.5 |        0.78 |  -2.98 |  0.0029 | **  |

**Significance**: \*\*\* p<0.001, \*\* p<0.01, \* p<0.05

## Summary

- **Low** (VIX <16): Zone 5 mean 31.2 bps vs Zone 3 mean 29.3 bps — ratio 1.06, Zone 5 higher
- **Normal** (VIX 16–20): Zone 5 mean 34.9 bps vs Zone 3 mean 37.1 bps — ratio 0.94, Zone 5 lower (statistically significant)
- **Elevated** (VIX 20–25): Zone 5 mean 46.3 bps vs Zone 3 mean 47.5 bps — ratio 0.98, Zone 5 lower
- **High** (VIX >=25): Zone 5 mean 68.7 bps vs Zone 3 mean 87.5 bps — ratio 0.78, Zone 5 lower (statistically significant)
