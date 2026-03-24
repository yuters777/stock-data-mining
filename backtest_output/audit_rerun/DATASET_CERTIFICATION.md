# Dataset Certification Report — All 27 FIXED Tickers

**Date:** 2026-03-24
**Tool:** `utils/dataset_certification.py`
**Data:** `backtest_output/{TICKER}_m5_regsess_FIXED.csv`
**Stage:** S32 Stage 0 — Dataset Certification

---

## Executive Summary

| Status | Count | Tickers |
|--------|:-----:|---------|
| PASS | 0 | — |
| WARN | 25 | All except SPY, VIXY |
| FAIL | 2 | **SPY**, **VIXY** |
| **Total** | **27** | |

### Critical Failures
- **SPY**: Truncated at 13:00 ET (43 bars/day vs expected 78). Alpha Vantage source data issue.
- **VIXY**: Truncated at 13:00 ET (32 bars/day). Same Alpha Vantage source data issue. Also has 37 days with wrong first bar.

### Warnings (25 tickers)
All 25 non-failing tickers pass structural tests (bar count, first/last bar, OHLC, etc.)
but trigger Test 10 (close reasonability: >5% day-over-day change). This is expected
for volatile stocks (MARA: 79 days, COIN: 58 days, MU: 52 days) and does NOT indicate
data corruption — it reflects genuine market volatility.

---

## Per-Ticker Summary

| Ticker | Overall | Rows | Days | Bars/Day | Date Range | Issues |
|--------|:-------:|-----:|:----:|:--------:|:----------:|--------|
| AAPL | WARN | 21,996 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 6 days >5% close change |
| AMD | WARN | 21,996 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 38 days >5% close change |
| AMZN | WARN | 21,996 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 8 days >5% close change |
| AVGO | WARN | 21,996 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 23 days >5% close change |
| BA | WARN | 21,996 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 9 days >5% close change |
| BABA | WARN | 21,996 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 24 days >5% close change |
| BIDU | WARN | 21,893 | 281 | 77.9 | 2025-02-03 to 2026-03-17 | 25 days >5% close change |
| C | WARN | 21,988 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 7 days >5% close change |
| COIN | WARN | 21,996 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 58 days >5% close change |
| COST | WARN | 21,996 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 3 days >5% close change |
| GOOGL | WARN | 21,996 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 6 days >5% close change |
| GS | WARN | 21,987 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 6 days >5% close change |
| IBIT | WARN | 21,991 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 24 days >5% close change |
| JPM | WARN | 21,996 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 3 days >5% close change |
| MARA | WARN | 21,996 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 79 days >5% close change |
| META | WARN | 21,996 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 9 days >5% close change |
| MSFT | WARN | 21,996 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 3 days >5% close change |
| MU | WARN | 21,996 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 52 days >5% close change |
| NVDA | WARN | 21,996 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 17 days >5% close change |
| PLTR | WARN | 21,996 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 46 days >5% close change |
| SNOW | WARN | 21,991 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 20 days >5% close change |
| **SPY** | **FAIL** | **12,018** | **282** | **42.6** | 2025-02-03 to 2026-03-18 | **TRUNCATED at 13:00 ET** |
| TSLA | WARN | 21,996 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 38 days >5% close change |
| TSM | WARN | 21,996 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 8 days >5% close change |
| TXN | WARN | 21,972 | 282 | 77.9 | 2025-02-03 to 2026-03-18 | 14 days >5% close change |
| V | WARN | 21,994 | 282 | 78.0 | 2025-02-03 to 2026-03-18 | 3 days >5% close change |
| **VIXY** | **FAIL** | **8,921** | **281** | **31.7** | 2025-02-03 to 2026-03-18 | **TRUNCATED at 13:00 ET**, wrong first bars |

---

## Test Results Matrix

| Test | Description | Pass | Fail | Notes |
|:----:|-------------|:----:|:----:|-------|
| 1 | Timezone (09:30-16:00 ET) | 27 | 0 | All bars in session |
| 2 | Bar count (70-80/day) | 25 | **2** | SPY (43/day), VIXY (32/day) |
| 3 | First bar = 09:30 | 26 | **1** | VIXY has 37 bad first-bar days |
| 4 | Last bar = 15:50/15:55 | 25 | **2** | SPY, VIXY truncated at 13:00 |
| 5 | No duplicate timestamps | 27 | 0 | Clean |
| 6 | No session spillover | 27 | 0 | Clean |
| 7 | OHLC sanity (H≥O,C,L) | 27 | 0 | Clean |
| 8 | No zero/negative prices | 27 | 0 | Clean |
| 9 | Date continuity (<5 day gaps) | 27 | 0 | Continuous coverage |
| 10 | Close reasonability (<5% DoD) | 0 | **27** | Expected for volatile stocks |

---

## Coverage Statistics

| Metric | Value |
|--------|------:|
| Total tickers | 27 |
| Total rows (all tickers) | 558,877 |
| Date range | 2025-02-03 to 2026-03-18 |
| Trading days (mode) | 282 |
| Standard bars/day | 78 (09:30-15:55) |
| Complete tickers (78 bars/day) | 25/27 |
| Truncated tickers | 2 (SPY, VIXY) |

---

## Golden-Day Audit

### Note on Reference Price Comparison
Golden-day audits require comparing our last-bar close against Yahoo Finance / TradingView
daily closes. However:

- Our "close" = last M5 bar close (15:55 ET for most tickers, 13:00 ET for SPY/VIXY)
- Yahoo/TradingView "close" = closing auction at 16:00 ET
- Expected difference: $0.01-$2.00 depending on closing auction dynamics

Since we cannot programmatically access Yahoo Finance or TradingView prices in this
environment, the golden-day audit is documented as **DEFERRED** pending manual verification.

**For manual verification, check these dates:**

#### SPY (TRUNCATED — last bar 13:00 ET, NOT comparable to daily close)
- 2025-03-03: Our 13:00 close = check against intraday chart
- 2025-06-02: Our 13:00 close = check against intraday chart
- 2025-09-15: Our 13:00 close = check against intraday chart
- 2025-12-01: Our 13:00 close = check against intraday chart
- 2026-03-02: Our 13:00 close = check against intraday chart

#### NVDA (full session data available)
- 2025-03-03: Our 15:55 close — compare to Yahoo daily close ±$0.50
- 2025-06-02: Our 15:55 close — compare to Yahoo daily close ±$0.50
- 2025-09-15: Our 15:55 close — compare to Yahoo daily close ±$0.50
- 2025-12-01: Our 15:55 close — compare to Yahoo daily close ±$0.50
- 2026-03-02: Our 15:55 close — compare to Yahoo daily close ±$0.50

#### TSLA (full session data available)
- 2025-03-03: Our 15:55 close — compare to Yahoo daily close ±$0.50
- 2025-06-02: Our 15:55 close — compare to Yahoo daily close ±$0.50
- 2025-09-15: Our 15:55 close — compare to Yahoo daily close ±$0.50
- 2025-12-01: Our 15:55 close — compare to Yahoo daily close ±$0.50
- 2026-03-02: Our 15:55 close — compare to Yahoo daily close ±$0.50

---

## SPY / VIXY Truncation — Root Cause

Both SPY and VIXY have truncated IST blocks in the raw Alpha Vantage CSVs:

| Ticker | Raw IST Block Max | Equivalent ET | Expected ET | Missing |
|--------|:-----------------:|:-------------:|:-----------:|:-------:|
| SPY | 20:00 IST | 13:00 ET | 15:55 ET | 13:05-15:55 (35 bars) |
| VIXY | 20:00 IST | 13:00 ET | 15:55 ET | 13:05-15:55 (35 bars) |
| All others | 22:55 IST | 15:55 ET | 15:55 ET | None |

**This is an Alpha Vantage data delivery issue.** The `data_loader.py` correctly
extracts what's available — there simply isn't enough data in the source.

### Action Required
1. Re-fetch SPY and VIXY data from Alpha Vantage (or alternative source)
2. Verify new data covers full regular session (09:30-15:55 ET)
3. Re-run dataset certification
4. All tests depending on SPY afternoon data should be flagged

---

## Certification Verdict

| Category | Status |
|----------|--------|
| 25 standard tickers | ✅ CERTIFIED for backtest use |
| SPY | ❌ NOT CERTIFIED — truncated at 13:00 ET |
| VIXY | ❌ NOT CERTIFIED — truncated at 13:00 ET |
| Data loader (`load_m5_regsess()`) | ✅ Correctly extracts IST block |
| OHLC integrity | ✅ All 27 tickers pass |
| Timestamp integrity | ✅ No duplicates, no spillover |
| Date coverage | ✅ 282 continuous trading days |

### Usage Guidance
- **Safe to use**: 25 tickers with full 78 bars/day for all backtests
- **Use with caution**: SPY/VIXY — only for tests that don't require data after 13:00 ET
- **Always run `certify_m5_data(ticker)` before new backtests**
