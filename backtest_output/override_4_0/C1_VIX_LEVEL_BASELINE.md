# C1: Override 4.0 — VIX Level Baseline

**Date:** 2026-03-24
**SPY data:** `backtest_output/SPY_daily.csv` (full-day OHLCV, NOT truncated M5)
**VIX data:** `Fetched_Data/VIXCLS_FRED_real.csv` (FRED daily close)
**Matched days:** 272
**Method:** Prior-day VIX close → next-day SPY open-to-close return (no lookahead)

---

## 1. Data Inventory

| Variable | Path | Freq | Date Range | Rows | Status | Notes |
|----------|------|------|------------|-----:|:------:|-------|
| VIX daily (FRED VIXCLS) | `Fetched_Data/VIXCLS_FRED_real.csv` | Daily | 2025-02-10 to 2026-03-12 | 284 | YES |  |
| SPY daily OHLCV | `backtest_output/SPY_daily.csv` | Daily | 2025-02-03 to 2026-03-18 | 282 | YES | Full-day data |
| SPY M5 FIXED | `backtest_output/SPY_m5_regsess_FIXED.csv` | M5 | 2025-02-03 to 2026-03-18 | 12018 | YES | TRUNCATED at 13:00 ET |
| VIXY daily OHLCV | `backtest_output/VIXY_daily.csv` | Daily | 2025-02-03 to 2026-03-18 | 282 | YES |  |
| VIXY M5 FIXED | `backtest_output/VIXY_m5_regsess_FIXED.csv` | M5 | 2025-02-03 to 2026-03-18 | 8921 | YES | TRUNCATED at 13:00 ET |
| VIXY raw M5 | `Fetched_Data/VIXY_data.csv` | M5 | 2025-02-03 to 2026-03-18 | 47216 | YES |  |
| SPY raw M5 | `Fetched_Data/SPY_data.csv` | M5 | 2025-02-03 to 2026-03-18 | 54318 | YES | Dual-block Alpha Vantage |
| VIX3M daily | `Fetched_Data/VIX3M_data.csv` | Daily |  | 0 | NO | Term structure |
| VIX3M FRED | `Fetched_Data/VIX3M_FRED.csv` | Daily |  | 0 | NO | Term structure |
| VIX9D daily | `Fetched_Data/VIX9D_data.csv` | Daily |  | 0 | NO | Term structure |
| VIX9D FRED | `Fetched_Data/VIX9D_FRED.csv` | Daily |  | 0 | NO | Term structure |
| VX1 futures | `Fetched_Data/VX1_data.csv` | Daily |  | 0 | NO | Term structure |
| VX2 futures | `Fetched_Data/VX2_data.csv` | Daily |  | 0 | NO | Term structure |
| VVIX daily | `Fetched_Data/VVIX_data.csv` | Daily |  | 0 | NO | Term structure |

### Key Findings

- **VIX3M, VIX9D, VIX futures: NOT AVAILABLE** — cannot test term structure
- **SPY daily OHLCV: AVAILABLE** — full-day open/close, suitable for regime testing
- **SPY M5 FIXED: TRUNCATED at 13:00 ET** — cannot use for full-day intraday analysis
- **VIX intraday: NOT AVAILABLE** — cannot test micro shock detection from VIX M5
- **VIXY M5: TRUNCATED** — same 13:00 ET issue as SPY

### What We CAN Test
1. VIX daily level buckets (this report)
2. Multi-day VIX momentum (3d, 5d, 10d VIX change)
3. SPY realized volatility from morning M5 bars (09:30-13:00)
4. Variance risk premium (VIX - realized vol)
5. SPY morning vol bursts from M5 data
6. Gap × VIX interaction

### What We CANNOT Test (need IB data)
1. VIX/VIX3M term structure ratio
2. VIX9D/VIX ratio (short-term fear)
3. VIX futures contango/backwardation (VX1!/VX2!)
4. VIX intraday spike detection
5. Full-session SPY afternoon vol patterns

## 2. SPY Daily Returns Summary

| Metric | Value |
|--------|------:|
| Trading days | 272 |
| Mean return | +0.0318% |
| Median return | +0.0440% |
| Std dev | 1.0029% |
| WR (>0) | 52.2% |
| Date range | 2025-02-11 to 2026-03-12 |

## 3. VIX Level Buckets (Baseline)

Prior-day VIX close → next-day SPY open-to-close return.

| VIX Regime | Days | Mean Return | Median | Std | Sharpe | WR (>0) | t-stat | p-value |
|------------|-----:|----------:|-------:|----:|-------:|--------:|-------:|--------:|
| <16 | 64 | -0.0302% | -0.0342% | 0.4180% | -0.072 | 45.3% | -0.58 | 0.5632 |
| 16-20 | 130 | -0.0694% | +0.0386% | 0.6567% | -0.106 | 50.8% | -1.20 | 0.2285 |
| 20-25 | 56 | +0.2163% | +0.2658% | 0.8687% | +0.249 | 66.1% | +1.86 | 0.0625 |
| ≥25 | 22 | +0.3409% | -0.1067% | 2.7589% | +0.124 | 45.5% | +0.58 | 0.5622 |

### Intraday Range by VIX Regime

| VIX Regime | Days | Mean Range | Median Range |
|------------|-----:|-----------:|-------------:|
| <16 | 64 | 0.709% | 0.625% |
| 16-20 | 130 | 1.024% | 0.875% |
| 20-25 | 56 | 1.501% | 1.393% |
| ≥25 | 22 | 3.090% | 2.141% |

### Fine-Grained VIX Buckets

| VIX Range | Days | Mean Return | WR | Sharpe |
|-----------|-----:|----------:|---:|-------:|
| <14 | 2 | — | — | — |
| 14-16 | 62 | -0.0290% | 46.8% | -0.068 |
| 16-18 | 89 | -0.0372% | 51.7% | -0.062 |
| 18-20 | 41 | -0.1392% | 48.8% | -0.182 |
| 20-22 | 31 | +0.4568% | 77.4% | +0.588 |
| 22-25 | 25 | -0.0820% | 52.0% | -0.091 |
| 25-30 | 10 | +0.3830% | 60.0% | +0.374 |
| ≥30 | 12 | +0.3059% | 33.3% | +0.083 |

### Monotonicity Analysis

- Mean returns by regime: <16=-0.0302%, 16-20=-0.0694%, 20-25=+0.2163%, ≥25=+0.3409%
- Monotonically decreasing (higher VIX → lower returns): NO
- Monotonically increasing (higher VIX → higher returns): NO

### VIX<20 vs VIX≥25 Comparison

| Metric | VIX<20 | VIX≥25 | Difference |
|--------|-------:|-------:|-----------:|
| N | 194 | 22 | — |
| Mean return | -0.0564% | +0.3409% | -0.3974% |
| WR | 49.0% | 45.5% | — |
| t-stat | — | — | -0.67 |
| p-value | — | — | 0.5004 |

## 4. Baseline Verdict

This VIX level analysis is the **baseline** that all other Override 4.0 candidates must beat.

**No VIX regime produces statistically significant SPY returns (p<0.05).**

**Strongest regime effect:** VIX ≥25 (mean=+0.3409%, N=22)

### Implications for Override 4.0

- If VIX level alone doesn't predict returns → Override should use it as a
  **range/volatility context** (sizing, stop distances) not as a directional signal
- Higher VIX → wider intraday ranges → adjust position sizing
- The baseline Sharpe per regime will be compared against multi-factor models in C2
