# PH3: Power Hour Returns — Event Proxy Days vs Normal Days

**Zone 5** (Power Hour): 14:45–16:00 ET  
**Zone 3** (Midday Lull): 12:00–13:30 ET  
**Metric**: Mean absolute return = |close_end − close_start| / close_start  
**Data**: M5 regular-session bars, 27 tickers, pooled across all tickers  

## Event Proxy Definition

Daily VIX range is proxied by **VIXY daily High − Low** (VIXY is a VIX-futures ETF).  
Days with VIXY range >= **2.33** (75th percentile) are flagged as **event proxy** days.  

| Statistic | Value |
|-----------|------:|
| VIXY range min | 0.27 |
| VIXY range median | 1.38 |
| VIXY range 75th pctl (threshold) | 2.33 |
| VIXY range max | 25.35 |
| Event proxy days | 71 |
| Normal days | 211 |

## Results: Zone 5 vs Zone 3 Within Each Group

| Group | N days | N ticker-days | Mean \|Ret\| Z5 (bps) | Mean \|Ret\| Z3 (bps) | Ratio Z5/Z3 | T-stat | P-value | Sig |
|-------|-------:|--------------:|----------------------:|----------------------:|------------:|-------:|--------:|:---:|
| Event Proxy  |     71 |          1902 |                  53.8 |                  60.3 |        0.89 |  -2.60 |  0.0092 | **  |
| Normal       |    211 |          5659 |                  34.2 |                  34.8 |        0.98 |  -0.71 |  0.4797 |     |

**Significance**: \*\*\* p<0.001, \*\* p<0.01, \* p<0.05 (paired t-test, Zone 5 − Zone 3)

## Cross-Group Comparison (Welch's t-test)

Tests whether event-proxy days have higher absolute returns than normal days.

| Comparison | T-stat | P-value | Sig |
|------------|-------:|--------:|:---:|
| Zone 5: Event vs Normal |  12.00 |  0.0000 | *** |
| Zone 3: Event vs Normal |  10.33 |  0.0000 | *** |

## Summary

- **Event proxy days** (71 days, 1902 ticker-days): Zone 5 = 53.8 bps, Zone 3 = 60.3 bps, ratio = 0.89
- **Normal days** (211 days, 5659 ticker-days): Zone 5 = 34.2 bps, Zone 3 = 34.8 bps, ratio = 0.98
- Event-proxy days amplify both zones: Z5 by 1.57x, Z3 by 1.73x vs normal
- Power Hour advantage is **weaker** on event days (ratio 0.89 vs 0.98)
