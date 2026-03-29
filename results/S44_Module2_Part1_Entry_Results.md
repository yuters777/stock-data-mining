# S44 Module 2 — Part 1: Entry Variants (M5 Pullback within 4H Uptrend)

**Date:** 2026-03-29 17:24
**Pre-filter:** 4H EMA gate UP + VIX < 25 + NOT Module 4 window
**Total qualifying M5 bars (BASELINE):** 210,045
**Tickers:** 25/25

## 1. Entry Variant Results

### VIX Regime: ALL

| Variant | Description | Horizon | N | Mean% | WR% | PF | Sep% | Sep p-val |
|---------|-------------|---------|---|-------|-----|----|------|-----------|
| BASELINE | Any qualifying M5 bar (no M5 filter) | +30m | 210,045 | +0.0455 | 53.4 | 1.26 | — | — |
| BASELINE | Any qualifying M5 bar (no M5 filter) | +1hr | 210,045 | +0.0869 | 54.7 | 1.35 | — | — |
| BASELINE | Any qualifying M5 bar (no M5 filter) | +2hr | 210,045 | +0.1607 | 56.0 | 1.45 | — | — |
| BASELINE | Any qualifying M5 bar (no M5 filter) | +4hr | 210,045 | +0.2809 | 57.3 | 1.54 | — | — |
| E1 | EMA9 pullback + reclaim | +30m | 20,948 | +0.0399 | 52.6 | 1.22 | -0.0055 | 0.3217 |
| E1 | EMA9 pullback + reclaim | +1hr | 20,948 | +0.0895 | 54.7 | 1.36 | +0.0026 | 0.7348 |
| E1 | EMA9 pullback + reclaim | +2hr | 20,948 | +0.1625 | 56.3 | 1.45 | +0.0018 | 0.8666 |
| E1 | EMA9 pullback + reclaim | +4hr | 20,948 | +0.2752 | 57.2 | 1.52 | -0.0057 | 0.7056 |
| E2 | RSI dip below 40 + recovery | +30m | 6,766 | +0.0562 | 54.7 | 1.30 | +0.0107 | 0.2643 |
| E2 | RSI dip below 40 + recovery | +1hr | 6,766 | +0.1306 | 57.1 | 1.54 | +0.0436 | 0.0006*** |
| E2 | RSI dip below 40 + recovery | +2hr | 6,766 | +0.2601 | 59.8 | 1.80 | +0.0994 | 0.0000*** |
| E2 | RSI dip below 40 + recovery | +4hr | 6,766 | +0.4337 | 62.3 | 1.95 | +0.1528 | 0.0000*** |
| E3 | CE flip SHORT → LONG | +30m | 11,436 | +0.0383 | 53.0 | 1.20 | -0.0072 | 0.3640 |
| E3 | CE flip SHORT → LONG | +1hr | 11,436 | +0.0937 | 55.2 | 1.36 | +0.0067 | 0.5166 |
| E3 | CE flip SHORT → LONG | +2hr | 11,436 | +0.1434 | 56.1 | 1.38 | -0.0173 | 0.2282 |
| E3 | CE flip SHORT → LONG | +4hr | 11,436 | +0.2539 | 56.8 | 1.48 | -0.0270 | 0.1709 |
| E4 | EMA21 dip + reclaim | +30m | 13,320 | +0.0335 | 52.7 | 1.17 | -0.0120 | 0.1152 |
| E4 | EMA21 dip + reclaim | +1hr | 13,320 | +0.0899 | 55.3 | 1.34 | +0.0030 | 0.7670 |
| E4 | EMA21 dip + reclaim | +2hr | 13,320 | +0.1525 | 56.4 | 1.40 | -0.0082 | 0.5471 |
| E4 | EMA21 dip + reclaim | +4hr | 13,320 | +0.2674 | 57.3 | 1.49 | -0.0135 | 0.4702 |
| E5 | Combined: RSI<50 & close<EMA9, then both flip | +30m | 9,984 | +0.0337 | 53.0 | 1.17 | -0.0118 | 0.1728 |
| E5 | Combined: RSI<50 & close<EMA9, then both flip | +1hr | 9,984 | +0.0946 | 55.4 | 1.36 | +0.0077 | 0.5030 |
| E5 | Combined: RSI<50 & close<EMA9, then both flip | +2hr | 9,984 | +0.1499 | 56.5 | 1.39 | -0.0108 | 0.4911 |
| E5 | Combined: RSI<50 & close<EMA9, then both flip | +4hr | 9,984 | +0.2674 | 57.3 | 1.50 | -0.0135 | 0.5253 |

### VIX Regime: NORMAL

| Variant | Description | Horizon | N | Mean% | WR% | PF | Sep% | Sep p-val |
|---------|-------------|---------|---|-------|-----|----|------|-----------|
| BASELINE | Any qualifying M5 bar (no M5 filter) | +30m | 171,999 | +0.0351 | 53.0 | 1.21 | — | — |
| BASELINE | Any qualifying M5 bar (no M5 filter) | +1hr | 171,999 | +0.0672 | 54.2 | 1.27 | — | — |
| BASELINE | Any qualifying M5 bar (no M5 filter) | +2hr | 171,999 | +0.1238 | 55.1 | 1.34 | — | — |
| BASELINE | Any qualifying M5 bar (no M5 filter) | +4hr | 171,999 | +0.2104 | 56.2 | 1.39 | — | — |
| E1 | EMA9 pullback + reclaim | +30m | 17,098 | +0.0289 | 52.2 | 1.16 | -0.0063 | 0.2835 |
| E1 | EMA9 pullback + reclaim | +1hr | 17,098 | +0.0667 | 54.1 | 1.27 | -0.0005 | 0.9496 |
| E1 | EMA9 pullback + reclaim | +2hr | 17,098 | +0.1188 | 55.4 | 1.32 | -0.0050 | 0.6600 |
| E1 | EMA9 pullback + reclaim | +4hr | 17,098 | +0.1933 | 55.8 | 1.36 | -0.0172 | 0.2749 |
| E2 | RSI dip below 40 + recovery | +30m | 5,609 | +0.0456 | 53.8 | 1.25 | +0.0105 | 0.3023 |
| E2 | RSI dip below 40 + recovery | +1hr | 5,609 | +0.1116 | 55.9 | 1.46 | +0.0444 | 0.0012** |
| E2 | RSI dip below 40 + recovery | +2hr | 5,609 | +0.2244 | 58.7 | 1.67 | +0.1006 | 0.0000*** |
| E2 | RSI dip below 40 + recovery | +4hr | 5,609 | +0.3538 | 60.8 | 1.76 | +0.1434 | 0.0000*** |
| E3 | CE flip SHORT → LONG | +30m | 9,320 | +0.0232 | 52.4 | 1.12 | -0.0119 | 0.1596 |
| E3 | CE flip SHORT → LONG | +1hr | 9,320 | +0.0679 | 54.5 | 1.26 | +0.0006 | 0.9535 |
| E3 | CE flip SHORT → LONG | +2hr | 9,320 | +0.1027 | 55.2 | 1.27 | -0.0211 | 0.1721 |
| E3 | CE flip SHORT → LONG | +4hr | 9,320 | +0.1723 | 55.5 | 1.32 | -0.0381 | 0.0688 |
| E4 | EMA21 dip + reclaim | +30m | 10,787 | +0.0189 | 52.5 | 1.10 | -0.0162 | 0.0423* |
| E4 | EMA21 dip + reclaim | +1hr | 10,787 | +0.0660 | 55.0 | 1.26 | -0.0013 | 0.9033 |
| E4 | EMA21 dip + reclaim | +2hr | 10,787 | +0.1119 | 55.7 | 1.29 | -0.0119 | 0.4144 |
| E4 | EMA21 dip + reclaim | +4hr | 10,787 | +0.1746 | 55.8 | 1.31 | -0.0358 | 0.0681 |
| E5 | Combined: RSI<50 & close<EMA9, then both flip | +30m | 8,098 | +0.0228 | 52.9 | 1.12 | -0.0124 | 0.1738 |
| E5 | Combined: RSI<50 & close<EMA9, then both flip | +1hr | 8,098 | +0.0778 | 55.1 | 1.30 | +0.0105 | 0.3863 |
| E5 | Combined: RSI<50 & close<EMA9, then both flip | +2hr | 8,098 | +0.1165 | 55.8 | 1.30 | -0.0073 | 0.6626 |
| E5 | Combined: RSI<50 & close<EMA9, then both flip | +4hr | 8,098 | +0.1866 | 56.0 | 1.34 | -0.0239 | 0.2818 |

### VIX Regime: ELEVATED

| Variant | Description | Horizon | N | Mean% | WR% | PF | Sep% | Sep p-val |
|---------|-------------|---------|---|-------|-----|----|------|-----------|
| BASELINE | Any qualifying M5 bar (no M5 filter) | +30m | 38,046 | +0.0923 | 55.3 | 1.51 | — | — |
| BASELINE | Any qualifying M5 bar (no M5 filter) | +1hr | 38,046 | +0.1758 | 56.8 | 1.70 | — | — |
| BASELINE | Any qualifying M5 bar (no M5 filter) | +2hr | 38,046 | +0.3276 | 60.0 | 1.95 | — | — |
| BASELINE | Any qualifying M5 bar (no M5 filter) | +4hr | 38,046 | +0.5994 | 62.5 | 2.23 | — | — |
| E1 | EMA9 pullback + reclaim | +30m | 3,850 | +0.0892 | 54.1 | 1.46 | -0.0031 | 0.8434 |
| E1 | EMA9 pullback + reclaim | +1hr | 3,850 | +0.1908 | 57.3 | 1.73 | +0.0150 | 0.4946 |
| E1 | EMA9 pullback + reclaim | +2hr | 3,850 | +0.3567 | 60.0 | 2.01 | +0.0291 | 0.3370 |
| E1 | EMA9 pullback + reclaim | +4hr | 3,850 | +0.6391 | 63.2 | 2.31 | +0.0397 | 0.3480 |
| E2 | RSI dip below 40 + recovery | +30m | 1,157 | +0.1074 | 59.2 | 1.53 | +0.0151 | 0.5704 |
| E2 | RSI dip below 40 + recovery | +1hr | 1,157 | +0.2225 | 62.9 | 1.96 | +0.0467 | 0.1752 |
| E2 | RSI dip below 40 + recovery | +2hr | 1,157 | +0.4336 | 65.0 | 2.54 | +0.1060 | 0.0284* |
| E2 | RSI dip below 40 + recovery | +4hr | 1,157 | +0.8211 | 69.4 | 3.05 | +0.2217 | 0.0026** |
| E3 | CE flip SHORT → LONG | +30m | 2,116 | +0.1045 | 55.6 | 1.51 | +0.0122 | 0.5709 |
| E3 | CE flip SHORT → LONG | +1hr | 2,116 | +0.2071 | 58.0 | 1.80 | +0.0313 | 0.2596 |
| E3 | CE flip SHORT → LONG | +2hr | 2,116 | +0.3228 | 59.8 | 1.92 | -0.0048 | 0.8968 |
| E3 | CE flip SHORT → LONG | +4hr | 2,116 | +0.6132 | 62.6 | 2.30 | +0.0137 | 0.7945 |
| E4 | EMA21 dip + reclaim | +30m | 2,533 | +0.0956 | 53.6 | 1.45 | +0.0033 | 0.8768 |
| E4 | EMA21 dip + reclaim | +1hr | 2,533 | +0.1917 | 56.7 | 1.70 | +0.0159 | 0.5649 |
| E4 | EMA21 dip + reclaim | +2hr | 2,533 | +0.3253 | 59.5 | 1.89 | -0.0024 | 0.9480 |
| E4 | EMA21 dip + reclaim | +4hr | 2,533 | +0.6624 | 63.4 | 2.37 | +0.0630 | 0.2214 |
| E5 | Combined: RSI<50 & close<EMA9, then both flip | +30m | 1,886 | +0.0806 | 53.6 | 1.36 | -0.0117 | 0.6247 |
| E5 | Combined: RSI<50 & close<EMA9, then both flip | +1hr | 1,886 | +0.1668 | 56.6 | 1.59 | -0.0090 | 0.7710 |
| E5 | Combined: RSI<50 & close<EMA9, then both flip | +2hr | 1,886 | +0.2935 | 59.6 | 1.76 | -0.0342 | 0.4100 |
| E5 | Combined: RSI<50 & close<EMA9, then both flip | +4hr | 1,886 | +0.6146 | 63.0 | 2.19 | +0.0152 | 0.7968 |

## 2. Ranking by Separation from BASELINE

Ranked by absolute separation at +2hr horizon (ALL regimes).

| Rank | Variant | Sep% (+2hr) | p-val | Significant? |
|------|---------|-------------|-------|--------------|
| 1 | E2 | +0.0994 | 0.0000 | YES |
| 2 | E3 | -0.0173 | 0.2282 | no |
| 3 | E5 | -0.0108 | 0.4911 | no |
| 4 | E4 | -0.0082 | 0.5471 | no |
| 5 | E1 | +0.0018 | 0.8666 | no |

## 3. Best Horizon per Variant

| Variant | Best Horizon | Mean% | Sep% from BASELINE | p-val |
|---------|-------------|-------|-------------------|-------|
| BASELINE | +4hr | +0.2809 | +0.0000 | — |
| E1 | +4hr | +0.2752 | -0.0057 | 0.7056 |
| E2 | +4hr | +0.4337 | +0.1528 | 0.0000 |
| E3 | +4hr | +0.2539 | -0.0270 | 0.1709 |
| E4 | +4hr | +0.2674 | -0.0135 | 0.4702 |
| E5 | +4hr | +0.2674 | -0.0135 | 0.5253 |

## 4. Winner Identification

**Winner: E2** — RSI dip below 40 + recovery
- Separation from BASELINE at +2hr: +0.0994% (p=0.0000)

Significant variants:
- **E2**: RSI dip below 40 + recovery — sep=+0.0994%, p=0.0000

## 5. VIX Regime Comparison

| Regime | BASELINE N | BASELINE Mean% (+2hr) | Best Variant | Best Sep% | p-val |
|--------|-----------|----------------------|-------------|----------|-------|
| NORMAL | 171,999 | +0.1238 | E2 | +0.1006 | 0.0000 |
| ELEVATED | 38,046 | +0.3276 | E2 | +0.1060 | 0.0284 |

## 6. Signal Count Summary

| Variant | Total Signals | % of BASELINE | Avg Signals/Ticker |
|---------|--------------|--------------|-------------------|
| BASELINE | 210,045 | 100.0% | 8,402 |
| E1 | 20,948 | 10.0% | 838 |
| E2 | 6,766 | 3.2% | 271 |
| E3 | 11,436 | 5.4% | 457 |
| E4 | 13,320 | 6.3% | 533 |
| E5 | 9,984 | 4.8% | 399 |

## 7. Configuration

```
RSI period:    14 (Wilder smoothing)
ADX period:    20 (Wilder smoothing)
EMA periods:   9, 21
CE params:     period=14, lookback=22, mult=2.0
RSI threshold: 40 (E2), 50 (E5)
Horizons:      +30m, +1hr, +2hr, +4hr
VIX regimes:   NORMAL (<20), ELEVATED (20-25)
```
