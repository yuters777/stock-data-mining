# PH6: Directional Analysis — Does Power Hour Resolve Direction or Amplify Noise?

**Best subset from PH5**: High-beta tickers × Low/Normal VIX (<20)  
**Zone 5** (Power Hour): 14:45–16:00 ET  
**Zone 2** (Mid-morning): 10:00–12:00 ET (comparison zone)  
**Day direction**: sign of (close@15:55 − open@09:30)  
**High-beta tickers**: SPY, MARA, MU, TSLA, AMD, COIN, PLTR, TSM, AMZN  

## Signed Returns

Mean signed return tests whether the zone has a directional bias (t-test vs 0).

| Group | N | Mean Signed Z5 (bps) | T-stat | P-value | Mean Signed Z2 (bps) | T-stat | P-value |
|-------|--:|---------------------:|-------:|--------:|---------------------:|-------:|--------:|
| High-beta × Low/Normal VIX (best subset) | 1746 | +3.03 | 2.04 | 0.0415 | +2.92 | 0.64 | 0.5252 |
| High-beta × Elevated+ VIX | 663 | +1.04 | 0.29 | 0.7713 | +21.77 | 2.27 | 0.0229 |
| High-beta (all VIX) | 2458 | +2.48 | 1.73 | 0.0843 | +7.94 | 1.90 | 0.0575 |
| All tickers (all VIX) | 7361 | +0.90 | 1.19 | 0.2340 | +4.91 | 2.55 | 0.0106 |

## Direction Agreement with Day

% of ticker-days (with non-zero day return) where zone direction matches day direction.  
50% = random; >50% = zone predicts/resolves day direction.  
Binomial test vs 50%.

| Group | N (nonflat) | Z5 Match % | Binom P | Z2 Match % | Binom P |
|-------|------------:|-----------:|--------:|-----------:|--------:|
| High-beta × Low/Normal VIX (best subset) | 1736 | 56.3% | 0.0000 | 54.7% | 0.0001 |
| High-beta × Elevated+ VIX | 656 | 58.1% | 0.0000 | 51.8% | 0.3487 |
| High-beta (all VIX) | 2441 | 56.7% | 0.0000 | 54.0% | 0.0001 |
| All tickers (all VIX) | 7324 | 57.3% | 0.0000 | 54.4% | 0.0000 |

## Verdict: Direction Resolution vs Noise Amplification

### Signed Return Test

Zone 5 has a statistically significant directional bias (+3.03 bps, p=0.0415). This suggests a systematic drift, not just noise.

### Day-Direction Agreement Test

Zone 5 matches the day's direction 56.3% of the time (p=0.0000), significantly above 50%. **Power Hour resolves direction** — it tends to move with the day's prevailing trend.

Zone 2 comparison: matches day direction 54.7% (p=0.0001).

### Synthesis

Power Hour both **resolves direction** (aligns with day trend) and carries a **net directional drift**. This is the strongest possible signal — larger moves that systematically align with the day's prevailing direction.
