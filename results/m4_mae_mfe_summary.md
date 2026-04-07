# Module 4 MAE/MFE Distribution + Stop Variant Analysis

**Date:** 2026-04-07 13:27
**Tickers:** 25
**Trigger:** 3 consecutive 4H down bars (close < open) + VIX >= 25.0 + RSI < 35.0
**Entry:** 4H trigger bar close
**Exit:** first 4H close >= EMA21 (hard max 10 bars)
**Total trades:** 57 (Winners: 55, Losers: 2)

---

## Table 2: MAE/MFE Summary Statistics

| Metric | Winners (N=55) | Losers (N=2) | All (N=57) |
|--------|-------|-------|-------|
| MAE_close p50 | 0.33% | -3.47% | 0.30% |
| MAE_close p75 | 2.32% | -3.46% | 1.97% |
| MAE_close p90 | 6.84% | -3.45% | 6.77% |
| MAE_close p95 | 8.36% | -3.45% | 8.23% |
| MAE_close worst | -9.54% | -3.48% | -9.54% |
| MAE_low p50 | -2.73% | -4.09% | -2.81% |
| MAE_low p75 | -0.74% | -3.89% | -0.78% |
| MAE_low p90 | -0.13% | -3.77% | -0.14% |
| MAE_low worst | -11.41% | -4.49% | -11.41% |
| MFE p50 | 11.71% | 5.32% | 11.70% |
| MFE p75 | 15.91% | 6.82% | 15.09% |
| MFE p90 | 20.28% | 7.72% | 20.14% |
| bars_to_MAE avg | 2.4 | 5.0 | 2.5 |
| bars_to_MFE avg | 5.0 | 2.0 | 4.9 |
| bars_held avg | 6.0 | 10.0 | 6.2 |

## Table 3: ATR Context

| Metric | Value |
|--------|-------|
| ATR14 at entry mean | 7.8377 |
| ATR14 at entry p50 | 5.8853 |
| MAE/ATR ratio p50 | 0.49 |
| MAE/ATR ratio p90 | 2.04 |

---

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

---

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

