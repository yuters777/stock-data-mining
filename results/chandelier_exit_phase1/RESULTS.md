# Chandelier Exit ATR Backtest — Phase 1 Results

## Overview
- **Tickers**: NVDA, TSLA, GOOGL, META
- **Multipliers tested**: 1.25x, 1.5x, 2.0x, 2.25x
- **Entry**: 4H EMA9/21 crossover (long only)
- **Exit**: Chandelier Exit (ATR14, HH22) with +1R activation gate
- **Max hold**: 5 trading days

## Cross-Multiplier Comparison (All Tickers Combined)

| Metric | 1.25x | 1.50x | 2.00x | 2.25x |
|--------|-------|-------|-------|-------|
| Total Trades | 44 | 44 | 44 | 44 |
| Win Rate (%) | 40.9 | 40.9 | 40.9 | 38.6 |
| Avg R-Multiple | 0.2583 | 0.1709 | 0.5259 | 0.4817 |
| Median R-Multiple | -1.0203 | -1.0203 | -1.0512 | -1.0512 |
| Profit Factor | 1.36 | 1.24 | 1.7 | 1.62 |
| Avg Winner R | 2.3941 | 2.1806 | 3.11 | 3.256 |
| Avg Loser R | -1.2204 | -1.2204 | -1.2631 | -1.2651 |
| Avg Hold (hrs) | 2.2 | 2.2 | 2.5 | 2.6 |
| Avg MFE (R) | 2.0781 | 2.1336 | 2.898 | 2.9027 |
| Give-Back Ratio | 0.5593 | 0.5719 | 0.615 | 0.655 |
| Worst Trade (R) | -2.5645 | -2.5645 | -2.5645 | -2.5645 |
| Best Trade (R) | 18.7143 | 13.5714 | 17.9091 | 17.9091 |
| % Reached +1R | 45.5 | 45.5 | 45.5 | 45.5 |
| % Reached +2R | 20.5 | 22.7 | 29.5 | 29.5 |
| % Reached +3R | 9.1 | 11.4 | 15.9 | 15.9 |

## Per-Ticker Breakdown

### NVDA

| Metric | 1.25x | 1.50x | 2.00x | 2.25x |
|--------|-------|-------|-------|-------|
| Total Trades | 14 | 14 | 14 | 14 |
| Win Rate (%) | 42.9 | 42.9 | 42.9 | 35.7 |
| Avg R-Multiple | 1.3778 | 1.1386 | 1.7701 | 1.6987 |
| Median R-Multiple | -1.0398 | -1.0398 | -1.0398 | -1.0398 |
| Profit Factor | 2.63 | 2.34 | 3.09 | 2.86 |
| Avg Winner R | 5.1919 | 4.6337 | 6.1072 | 7.3104 |
| Avg Loser R | -1.4827 | -1.4827 | -1.4827 | -1.419 |
| Avg Hold (hrs) | 1.0 | 1.1 | 1.2 | 1.2 |
| Avg MFE (R) | 4.0765 | 4.2453 | 5.9772 | 5.9772 |
| Give-Back Ratio | 0.532 | 0.5266 | 0.6414 | 0.7194 |
| Worst Trade (R) | -2.5645 | -2.5645 | -2.5645 | -2.5645 |
| Best Trade (R) | 18.7143 | 13.5714 | 17.9091 | 17.9091 |
| % Reached +1R | 42.9 | 42.9 | 42.9 | 42.9 |
| % Reached +2R | 21.4 | 28.6 | 35.7 | 35.7 |
| % Reached +3R | 21.4 | 28.6 | 28.6 | 28.6 |

### TSLA

| Metric | 1.25x | 1.50x | 2.00x | 2.25x |
|--------|-------|-------|-------|-------|
| Total Trades | 13 | 13 | 13 | 13 |
| Win Rate (%) | 46.2 | 46.2 | 46.2 | 46.2 |
| Avg R-Multiple | -0.0743 | -0.0616 | 0.4601 | 0.4591 |
| Median R-Multiple | -0.0741 | -0.0741 | -1.0317 | -1.0317 |
| Profit Factor | 0.88 | 0.9 | 1.67 | 1.64 |
| Avg Winner R | 1.1465 | 1.1739 | 2.4895 | 2.5553 |
| Avg Loser R | -1.1207 | -1.1207 | -1.2794 | -1.3376 |
| Avg Hold (hrs) | 3.6 | 3.7 | 4.4 | 4.5 |
| Avg MFE (R) | 1.4072 | 1.4133 | 2.0511 | 2.0672 |
| Give-Back Ratio | 0.5363 | 0.5259 | 0.5157 | 0.5171 |
| Worst Trade (R) | -1.6241 | -1.6241 | -1.6241 | -1.6241 |
| Best Trade (R) | 2.1949 | 2.1949 | 5.4923 | 5.4923 |
| % Reached +1R | 53.8 | 53.8 | 53.8 | 53.8 |
| % Reached +2R | 30.8 | 30.8 | 38.5 | 38.5 |
| % Reached +3R | 7.7 | 7.7 | 23.1 | 23.1 |

### GOOGL

| Metric | 1.25x | 1.50x | 2.00x | 2.25x |
|--------|-------|-------|-------|-------|
| Total Trades | 8 | 8 | 8 | 8 |
| Win Rate (%) | 50.0 | 50.0 | 50.0 | 50.0 |
| Avg R-Multiple | -0.246 | -0.3284 | -0.3529 | -0.3529 |
| Median R-Multiple | -0.033 | -0.033 | -0.033 | -0.033 |
| Profit Factor | 0.56 | 0.42 | 0.37 | 0.37 |
| Avg Winner R | 0.632 | 0.4674 | 0.4183 | 0.4183 |
| Avg Loser R | -1.1241 | -1.1241 | -1.1241 | -1.1241 |
| Avg Hold (hrs) | 3.6 | 3.6 | 3.7 | 3.7 |
| Avg MFE (R) | 0.9596 | 0.9596 | 0.9596 | 0.9596 |
| Give-Back Ratio | 0.573 | 0.6626 | 0.696 | 0.696 |
| Worst Trade (R) | -1.8 | -1.8 | -1.8 | -1.8 |
| Best Trade (R) | 1.0245 | 0.9755 | 0.7791 | 0.7791 |
| % Reached +1R | 50.0 | 50.0 | 50.0 | 50.0 |
| % Reached +2R | 0.0 | 0.0 | 0.0 | 0.0 |
| % Reached +3R | 0.0 | 0.0 | 0.0 | 0.0 |

### META

| Metric | 1.25x | 1.50x | 2.00x | 2.25x |
|--------|-------|-------|-------|-------|
| Total Trades | 9 | 9 | 9 | 9 |
| Win Rate (%) | 22.2 | 22.2 | 22.2 | 22.2 |
| Avg R-Multiple | -0.5546 | -0.5546 | -0.5332 | -0.6368 |
| Median R-Multiple | -1.0964 | -1.0964 | -1.0964 | -1.0964 |
| Profit Factor | 0.34 | 0.34 | 0.36 | 0.24 |
| Avg Winner R | 1.2676 | 1.2676 | 1.3638 | 0.8979 |
| Avg Loser R | -1.0753 | -1.0753 | -1.0753 | -1.0753 |
| Avg Hold (hrs) | 0.6 | 0.6 | 0.8 | 0.9 |
| Avg MFE (R) | 0.9328 | 0.9328 | 1.0542 | 1.0542 |
| Give-Back Ratio | 0.6494 | 0.6494 | 0.6859 | 0.7931 |
| Worst Trade (R) | -1.7917 | -1.7917 | -1.7917 | -1.7917 |
| Best Trade (R) | 1.7386 | 1.7386 | 1.7386 | 0.989 |
| % Reached +1R | 33.3 | 33.3 | 33.3 | 33.3 |
| % Reached +2R | 22.2 | 22.2 | 33.3 | 33.3 |
| % Reached +3R | 0.0 | 0.0 | 0.0 | 0.0 |

## Recommendations

1. **Best Profit Factor**: 2.0x ATR (PF = 1.7)
2. **Lowest Give-Back Ratio**: 1.25x ATR (GB = 0.5593)
3. **Best Average R**: 2.0x ATR (Avg R = 0.5259)

### Optimal Multiplier by Ticker

- **NVDA**: 2.0x ATR (PF = 3.09)
- **TSLA**: 2.0x ATR (PF = 1.67)
- **GOOGL**: 1.25x ATR (PF = 0.56)
- **META**: 2.0x ATR (PF = 0.36)

### Phase 2 Recommendation

Recommend testing **2.0x** and **2.25x** with dynamic VIX regime switching in Phase 2.

### Phase 1b Note

When crypto data (ETH, BTC) arrives, re-run this backtest with 6 tickers total to validate whether crypto's 24/7 nature changes the optimal multiplier.
