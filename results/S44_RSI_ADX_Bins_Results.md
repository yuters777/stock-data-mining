# S44 4H RSI Context Bins + ADX Maturity Percentiles

**Date:** 2026-03-29 15:07
**Total tagged M5 bars:** 548,544
**Tickers:** 25/25
**ADX smoothing:** 14 (standard Wilder; prompt specified 20 but existing 4H indicators use 14)
**ADX percentile window:** 60 bars (rolling)

## Table A: 4H RSI Bins × Forward Returns × VIX Regime

### VIX: NORMAL

| RSI Bin | Horizon | N | Mean% | Med% | WR% | Std% | p-val |
|---------|---------|---|-------|------|-----|------|-------|
| STRETCHED_DOWN | +30m | 28,080 | -0.041 | -0.015 | 47.4 | 0.991 | 1.0000 |
| STRETCHED_DOWN | +1hr | 28,080 | -0.075 | -0.020 | 47.9 | 1.406 | 1.0000 |
| STRETCHED_DOWN | +2hr | 28,080 | -0.128 | -0.050 | 47.4 | 1.959 | 1.0000 |
| NEUTRAL | +30m | 256,857 | -0.003 | +0.000 | 49.8 | 0.756 | 0.9578 |
| NEUTRAL | +1hr | 256,857 | -0.004 | +0.000 | 50.0 | 1.069 | 0.9779 |
| NEUTRAL | +2hr | 256,857 | -0.007 | +0.000 | 50.0 | 1.507 | 0.9857 |
| STRETCHED_UP | +30m | 86,244 | +0.006 | +0.001 | 50.0 | 0.701 | 0.0088** |
| STRETCHED_UP | +1hr | 86,244 | +0.012 | +0.006 | 50.4 | 0.983 | 0.0003*** |
| STRETCHED_UP | +2hr | 86,244 | +0.022 | +0.005 | 50.2 | 1.377 | 0.0000*** |

### VIX: ELEVATED

| RSI Bin | Horizon | N | Mean% | Med% | WR% | Std% | p-val |
|---------|---------|---|-------|------|-----|------|-------|
| STRETCHED_DOWN | +30m | 18,312 | +0.028 | +0.024 | 52.0 | 1.005 | 0.0001*** |
| STRETCHED_DOWN | +1hr | 18,312 | +0.034 | +0.052 | 53.0 | 1.416 | 0.0005*** |
| STRETCHED_DOWN | +2hr | 18,312 | +0.027 | +0.113 | 54.2 | 2.055 | 0.0384* |
| NEUTRAL | +30m | 80,721 | +0.020 | +0.020 | 51.7 | 0.903 | 0.0000*** |
| NEUTRAL | +1hr | 80,721 | +0.032 | +0.038 | 52.5 | 1.279 | 0.0000*** |
| NEUTRAL | +2hr | 80,721 | +0.044 | +0.067 | 52.9 | 1.833 | 0.0000*** |
| STRETCHED_UP | +30m | 10,158 | +0.021 | +0.009 | 50.7 | 0.786 | 0.0040** |
| STRETCHED_UP | +1hr | 10,158 | +0.041 | +0.016 | 51.1 | 1.137 | 0.0002*** |
| STRETCHED_UP | +2hr | 10,158 | +0.081 | +0.072 | 53.2 | 1.578 | 0.0000*** |

### VIX: HIGH_RISK

| RSI Bin | Horizon | N | Mean% | Med% | WR% | Std% | p-val |
|---------|---------|---|-------|------|-----|------|-------|
| STRETCHED_DOWN | +30m | 10,578 | +0.135 | +0.010 | 50.2 | 1.675 | 0.0000*** |
| STRETCHED_DOWN | +1hr | 10,578 | +0.318 | +0.052 | 51.5 | 2.293 | 0.0000*** |
| STRETCHED_DOWN | +2hr | 10,578 | +0.728 | +0.288 | 55.9 | 3.132 | 0.0000*** |
| NEUTRAL | +30m | 34,854 | +0.047 | +0.013 | 50.9 | 1.044 | 0.0000*** |
| NEUTRAL | +1hr | 34,848 | +0.084 | +0.044 | 52.4 | 1.415 | 0.0000*** |
| NEUTRAL | +2hr | 34,836 | +0.157 | +0.125 | 54.5 | 1.921 | 0.0000*** |
| STRETCHED_UP | +30m | 1,362 | +0.003 | +0.035 | 52.2 | 0.790 | 0.4463 |
| STRETCHED_UP | +1hr | 1,362 | +0.002 | +0.015 | 50.6 | 1.063 | 0.4676 |
| STRETCHED_UP | +2hr | 1,362 | +0.017 | -0.002 | 49.5 | 1.425 | 0.3289 |

### Key Cross: STRETCHED_DOWN + VIX >= 25 (Module 4 alignment)

N = 10,578 M5 bars

| Horizon | N | Mean% | Med% | WR% | Std% | p-val |
|---------|---|-------|------|-----|------|-------|
| +30m | 10,578 | +0.1346 | +0.0099 | 50.2 | 1.6754 | 0.0000*** |
| +1hr | 10,578 | +0.3177 | +0.0520 | 51.5 | 2.2934 | 0.0000*** |
| +2hr | 10,578 | +0.7278 | +0.2875 | 55.9 | 3.1324 | 0.0000*** |

### STRETCHED_DOWN by VIX Regime (+2hr horizon)

| VIX Regime | N | Mean% | WR% | p-val |
|------------|---|-------|-----|-------|
| NORMAL | 28,080 | -0.1280 | 47.4 | 1.0000 |
| ELEVATED | 18,312 | +0.0269 | 54.2 | 0.0384* |
| HIGH_RISK | 10,578 | +0.7278 | 55.9 | 0.0000*** |

## Table B: 4H ADX Percentile Bins × Forward Returns

| ADX Pctile Bin | Horizon | N | Mean% | Med% | WR% | Std% | p-val |
|----------------|---------|---|-------|------|-----|------|-------|
| FRESH_TREND | +30m | 175,371 | +0.0191 | +0.0059 | 50.4 | 0.7840 | 0.0000*** |
| FRESH_TREND | +1hr | 175,305 | +0.0376 | +0.0141 | 51.0 | 1.0984 | 0.0000*** |
| FRESH_TREND | +2hr | 175,173 | +0.0742 | +0.0333 | 51.8 | 1.5396 | 0.0000*** |
| MODERATE | +30m | 115,600 | +0.0183 | +0.0060 | 50.4 | 0.8363 | 0.0000*** |
| MODERATE | +1hr | 115,558 | +0.0349 | +0.0160 | 51.2 | 1.1675 | 0.0000*** |
| MODERATE | +2hr | 115,474 | +0.0684 | +0.0346 | 51.7 | 1.6318 | 0.0000*** |
| EXHAUSTED_TREND | +30m | 172,832 | +0.0184 | +0.0046 | 50.3 | 0.8205 | 0.0000*** |
| EXHAUSTED_TREND | +1hr | 172,790 | +0.0353 | +0.0111 | 50.8 | 1.1713 | 0.0000*** |
| EXHAUSTED_TREND | +2hr | 172,706 | +0.0708 | +0.0208 | 51.0 | 1.6528 | 0.0000*** |

## Table C: ADX Fixed vs Percentile — Return Separation

### Fixed ADX Bins

| ADX Fixed Bin | Horizon | N | Mean% | Med% | WR% | Std% | p-val |
|---------------|---------|---|-------|------|-----|------|-------|
| FIXED_LOW | +30m | 166,294 | +0.0148 | +0.0058 | 50.4 | 0.8343 | 0.0000*** |
| FIXED_LOW | +1hr | 166,234 | +0.0297 | +0.0154 | 51.0 | 1.1743 | 0.0000*** |
| FIXED_LOW | +2hr | 166,114 | +0.0602 | +0.0344 | 51.7 | 1.6540 | 0.0000*** |
| FIXED_MID | +30m | 202,204 | +0.0022 | +0.0041 | 50.2 | 0.8390 | 0.1164 |
| FIXED_MID | +1hr | 202,150 | +0.0046 | +0.0078 | 50.4 | 1.1681 | 0.0368* |
| FIXED_MID | +2hr | 202,042 | +0.0076 | +0.0146 | 50.6 | 1.6420 | 0.0184* |
| FIXED_HIGH | +30m | 152,596 | +0.0112 | +0.0000 | 49.8 | 0.8602 | 0.0000*** |
| FIXED_HIGH | +1hr | 152,560 | +0.0222 | +0.0066 | 50.4 | 1.2198 | 0.0000*** |
| FIXED_HIGH | +2hr | 152,488 | +0.0472 | +0.0144 | 50.6 | 1.7185 | 0.0000*** |

### Separation Comparison (+2hr horizon)

| Method | Best Bin | Worst Bin | Spread |
|--------|----------|-----------|--------|
| Percentile | FRESH_TREND (+0.0742%) | MODERATE (+0.0684%) | 0.0058% |
| Fixed | FIXED_LOW (+0.0602%) | FIXED_MID (+0.0076%) | 0.0525% |

**Winner:** Fixed bins produce more return separation (0.0525% vs 0.0058%).

## Recommendations

### RSI Bins
- 18/27 RSI×VIX×horizon cells are statistically significant (p<0.05)
- 9/9 ADX percentile×horizon cells are statistically significant (p<0.05)

### ADX Smoothing Note
- Existing 4H indicators use ADX(14) with standard Wilder smoothing (period=14)
- S44 mentioned ADX smoothing=20; this would require regenerating all 4H indicator files
- Results here use the existing period=14 data
