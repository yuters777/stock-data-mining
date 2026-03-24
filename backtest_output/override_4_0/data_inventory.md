# Override 4.0 — Data Inventory

**Date:** 2026-03-24

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

## Available for Override 4.0 Testing

1. VIX daily level → regime buckets (AVAILABLE)
2. Multi-day VIX change (3d/5d/10d) → momentum (AVAILABLE)
3. SPY morning realized vol from M5 09:30-13:00 (AVAILABLE, partial day)
4. Variance risk premium: VIX - realized vol (AVAILABLE)
5. VIXY daily as VIX proxy (AVAILABLE)
6. Gap × VIX interaction from SPY daily (AVAILABLE)

## NOT Available (Need IB/Alternative Data)

1. VIX3M daily → VIX/VIX3M term structure ratio
2. VIX9D daily → short-term fear gauge
3. VIX futures (VX1!, VX2!) → contango/backwardation
4. VIX intraday M5 → micro shock detection
5. SPY full-session M5 → afternoon volatility patterns
