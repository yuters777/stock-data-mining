# Module 4 MAE/MFE Distribution + Stop Variant Analysis

**Date:** 2026-04-07 13:27
**Tickers:** 25
**Trigger:** 3 consecutive 4H down bars (close < open) + VIX >= 25.0 + RSI < 35.0
**Entry:** 4H trigger bar close
**Exit:** first 4H close >= EMA21 (hard max 10 bars)
**Total trades:** 57 (Winners: 55, Losers: 2)

## Regime Analysis

### MAE by VIX Level at Entry

| Group | N | MAE_close p50 | MAE_close p90 | Mean% | WR% |
|-------|---|---------------|---------------|-------|-----|
| VIX 25-30 | 17 | 0.33% | 1.20% | +5.55 | 88 |
| VIX 30-40 | 22 | -0.77% | 1.25% | +10.37 | 100 |
| VIX 40+ | 18 | 5.12% | 9.49% | +10.10 | 100 |

### MAE by RSI Tier at Entry

| Group | N | MAE_close p50 | MAE_close p90 | Mean% | WR% |
|-------|---|---------------|---------------|-------|-----|
| RSI 25-30 | 10 | 0.59% | 6.27% | +9.47 | 90 |
| RSI 30-35 | 14 | 0.69% | 8.66% | +6.92 | 100 |
| RSI <25 | 33 | -0.25% | 4.55% | +9.48 | 97 |

### MAE by Ticker Class

| Group | N | MAE_close p50 | MAE_close p90 | Mean% | WR% |
|-------|---|---------------|---------------|-------|-----|
| ADR | 1 | -3.12% | -3.12% | +8.77 | 100 |
| Crypto-proxy | 5 | 0.53% | 8.47% | +12.31 | 80 |
| Mega-cap tech | 13 | 0.33% | 6.53% | +7.37 | 100 |
| Other | 38 | 0.07% | 4.97% | +8.90 | 97 |

### MAE by Override State (VIX proxy)

| Group | N | MAE_close p50 | MAE_close p90 | Mean% | WR% |
|-------|---|---------------|---------------|-------|-----|
| ELEVATED | 45 | -0.25% | 1.19% | +7.87 | 96 |
| HIGH_RISK | 12 | 6.42% | 10.01% | +12.51 | 100 |

