# SPY FIXED Data Verification Report

**Date:** 2026-03-24
**File:** `backtest_output/SPY_m5_regsess_FIXED.csv`
**Source:** `Fetched_Data/SPY_data.csv` → `utils/data_loader.py` IST extraction

---

## 🔴 OVERALL VERDICT: FAIL — SPY DATA TRUNCATED AT 13:00 ET

S32's concern is **CONFIRMED**. SPY FIXED data is incomplete — every trading day
ends at 13:00 ET instead of the expected 15:55 ET. This is a **source data issue**
in the raw Alpha Vantage CSV, not a bug in the data loader.

---

## Check 1: First Bar = 09:30 ET ✅ PASS

| Metric | Result |
|--------|--------|
| First bar time (mode) | 09:30 |
| Days with 09:30 first bar | 282/282 (100%) |

All 282 trading days start at 09:30 ET.

## Check 2: Last Bar = 15:55 ET ❌ FAIL

| Metric | Result |
|--------|--------|
| Expected last bar | 15:55 ET |
| Actual last bar (mode) | **13:00 ET** |
| Days ending at 13:00 | 279/282 (98.9%) |
| Days ending at 10:00 | 3/282 (1.1%) |
| Days ending at 15:55 | **0/282 (0%)** |

**Every single day is truncated.** No day has data past 13:00 ET.

The 3 days ending at 10:00 correspond to early-close sessions:
- 2025-07-03 (Independence Day eve)
- 2025-11-28 (Black Friday)
- 2025-12-24 (Christmas Eve)

## Check 3: Bar Count Per Day ❌ FAIL

| Metric | Result |
|--------|--------|
| Expected bars/day | ~78 (09:30–15:55) |
| Actual bars/day (mode) | **43** (09:30–13:00) |
| Mean bars/day | 42.6 |
| Min bars/day | 7 (early-close days) |
| Max bars/day | 43 |
| Total rows | 12,018 |
| Expected rows (78 × 282) | ~22,000 |
| Coverage | **54.6%** |

## Check 4: Gap Analysis ⚠️ PARTIAL PASS

Within the available data (09:30–13:00):
- No gaps > 5 minutes detected within the covered range
- Bars are contiguous within each day's available data
- **However:** the 2h 55m gap from 13:00 to 15:55 is missing every day

## Check 5: 13:00 ET Truncation (S32 Flag) ❌ CONFIRMED

| Metric | Result |
|--------|--------|
| Days with bars after 13:00 ET | **0 / 282** |
| Days ending exactly at 13:00 | 279 / 282 |
| Data available | 09:30–13:00 only |
| Missing session | 13:05–15:55 (35 bars/day) |

### Root Cause Analysis

The raw Alpha Vantage file `SPY_data.csv` has its IST block truncated:
- Other tickers: IST block goes to **22:55 IST** (= 15:55 ET) ✅
- SPY: IST block only goes to **20:00 IST** (= 13:00 ET) ❌
- VIXY has the same issue: truncated at 20:00 IST

This is an **Alpha Vantage data delivery issue**, not a processing bug.
The `data_loader.py` correctly extracts what's available — there simply
isn't data past 20:00 IST for SPY in the source file.

## Check 6: Date Range Coverage ✅ PASS (within available range)

| Metric | Result |
|--------|--------|
| First date | 2025-02-03 |
| Last date | 2026-03-18 |
| Trading days | 282 |
| Expected (~282 for 13.5 months) | ~282 |
| Unexpected gaps > 3 business days | None |

## Check 7: OHLC Sanity ✅ PASS

Within available data, OHLC relationships are correct:
- High >= max(Open, Close) on all bars
- Low <= min(Open, Close) on all bars
- No zero or negative prices

## Check 8: Daily Close Cross-Check ⚠️ NOT POSSIBLE

Cannot cross-check against Yahoo Finance/TradingView daily closes because:
- SPY daily close = 16:00 ET closing auction
- Our last bar = 13:00 ET
- The 13:00 close is NOT comparable to the daily close
- Difference could be $1–$5+ depending on afternoon movement

---

## Impact Assessment

### Tests Directly Affected by SPY Truncation

| Test Series | SPY Dependency | Impact |
|-------------|---------------|--------|
| H1 (exit grid) | Uses SPY bars through 15:30 | ⚠️ Missing 13:05–15:30 data |
| H2 (noon reversal) | Uses noon bars (11:30–12:30) | ✅ Within available range |
| S21-P1 (stress MR) | Uses noon entry + afternoon exit | ⚠️ Exit data missing |
| B1/B2 (gap fill) | Tracks fills through 16:00 | ⚠️ Missing fills after 13:00 |
| C2 (width breakout) | Uses full-day range | ❌ Day range understated |
| C3 (false breakout) | Zones 4-5 (13:30–16:00) | ❌ Zones 4-5 completely missing |
| A2 (zone returns) | Zone 4-5 analysis | ❌ Zones 4-5 missing |

### Other Tickers with Same Issue

| Ticker | Last Bar | Bars/Day | Status |
|--------|----------|----------|--------|
| SPY | 13:00 | 43 | ❌ TRUNCATED |
| VIXY | 13:00 | 32 | ❌ TRUNCATED |
| All other 25 | 15:55 | 78 | ✅ COMPLETE |

---

## Recommendation

### Immediate Action Required
1. **Flag SPY and VIXY as INCOMPLETE** in all downstream analysis
2. **Do NOT use SPY FIXED data** for any test requiring bars after 13:00 ET
3. **Re-fetch SPY data** from Alpha Vantage with full intraday coverage
4. SPY tests using only morning data (09:30–13:00) remain valid
5. All 25 other tickers are unaffected — full 78 bars/day through 15:55 ET

### For C2/C3/B2 Re-Runs
- C2/C3 re-runs using `load_m5_regsess()` will produce SPY results based on
  truncated data. SPY results should be flagged but other 24+ tickers are valid.
- B2 re-run: SPY gap fills after 13:00 will be missed. Flag SPY gap timing results.
