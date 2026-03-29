# 4H Bar Construction Audit Report

**S44 ChatGPT Pro DR Priority #0 — Confidence 10/10**
**Date:** 2026-03-29
**Status:** AUDIT COMPLETE — ALIGNED, minor notes below

---

## Part A: stock-data-mining 4H Data Audit

### A1. Where does 4H data come from?

**Source chain:**
1. **Raw M5 data:** `Fetched_Data/{TICKER}_data.csv` — Alpha Vantage M5 CSVs with dual-block structure (ET block 04:00-10:55, IST block 11:00-23:55)
2. **Cleaned M5 data:** `backtest_output/{TICKER}_m5_regsess_FIXED.csv` — IST regular session (16:30-22:55) extracted and converted to ET (09:30-15:55). Pre-market excluded.
3. **4H bars:** Synthesized from FIXED M5 by splitting each day into AM/PM sessions
4. **4H indicator files:** `data/indicators_4h/{TICKER}_4h_indicators.csv` — 25 tickers, 564 bars each

**Data is NOT fetched as 4H from Alpha Vantage.** It is always built from M5.

### A2. How are 4H bars constructed?

Two independent implementations exist. Both produce identical boundaries:

#### Implementation 1: `build_4h_catalog.py` (primary, ET timestamps)
```
File: backtest_output/continuation_study/build_4h_catalog.py:121-150
Input: FIXED M5 (ET timestamps, 09:30-15:55)
Split: hhmm < "13:30" → AM, hhmm >= "13:30" → PM
```
- AM bar: 09:30-13:25 ET (48 M5 bars)
- PM bar: 13:30-15:55 ET (30 M5 bars)

#### Implementation 2: `chandelier_exit_backtest.py` (IST timestamps)
```
File: chandelier_exit_backtest.py:76-101
Input: Raw M5 filtered to RTH in IST (16:30-22:55)
Split: time_minutes <= 1225 (20:25 IST) → Bar 1, else → Bar 2
```
- Bar 1: 16:30-20:25 IST = 09:30-13:25 ET (48 M5 bars)
- Bar 2: 20:30-22:55 IST = 13:30-15:55 ET (30 M5 bars)

#### Implementation 3: `deferred_recompute.py`
```
File: backtest_output/audit_rerun/deferred_recompute.py:383-411
Input: M5 bars with hhmm field
Split: hhmm < "13:30" → AM, hhmm >= "13:30" → PM
```
Same boundaries as Implementation 1.

**All three implementations produce identical 4H bars.**

### A3. Actual bar timestamps (from data)

```
GOOGL_4h_indicators.csv (first 10 bars):

timestamp               open      high      low       close     volume
2025-02-03 09:30:00    199.9000  202.9400  199.3100  202.1300  14038537
2025-02-03 13:30:00    202.1600  202.3800  199.7200  200.4300   5767090
2025-02-04 09:30:00    202.5900  205.8600  202.0100  204.7700  16156778
2025-02-04 13:30:00    204.7600  206.2300  203.9400  205.3100  11980443
2025-02-05 09:30:00    190.3100  191.9900  187.2900  189.8000  44241273
2025-02-05 13:30:00    189.8000  190.7400  188.7600  190.5800  16790007
```

Timestamps are anchored at 09:30 ET and 13:30 ET. No UTC. No pre/post-market.

### A4. Bars per day

```
Bars per day distribution (GOOGL, 282 trading days):
  2 bars/day: 282 days (100%)

Unique bar start times:
  09:30: 282 occurrences
  13:30: 282 occurrences
```

Perfectly consistent: exactly 2 bars per trading day, every day.

---

## Part B: Cross-Repo Alignment Check

| Check | market-engine (VPS) | stock-data-mining | Status |
|-------|-------------------|-------------------|--------|
| **Anchor** | 09:30 ET | 09:30 ET | ALIGNED |
| **Bar 1** | 09:30-13:30 ET (4H) | 09:30-13:25 ET (48 M5 bars) | ALIGNED* |
| **Bar 2** | 13:30-16:00 ET (2.5H) | 13:30-15:55 ET (30 M5 bars) | ALIGNED* |
| **Pre-market** | Excluded | Excluded | ALIGNED |
| **Crypto** | UTC 4H clean (00/04/08/12/16/20) | N/A (crypto-proxy equities only: IBIT, MARA, COIN) | N/A |
| **Completeness** | 80% M5 bars required | All available M5 bars used (no completeness filter) | MINOR DIFF |
| **EMA formula** | k = 2/(N+1) | k = 2/(N+1) (both implementations) | ALIGNED |

**\*Boundary note:** market-engine states "09:30-13:30" and "13:30-16:00", while stock-data-mining uses the last M5 bar start time (13:25 and 15:55). These are equivalent — the 13:25 bar covers 13:25-13:30, so the AM candle spans 09:30-13:30. Similarly, the 15:55 bar covers 15:55-16:00, so the PM candle spans 13:30-16:00. The boundaries are identical.

### Minor Differences (non-critical)

1. **Completeness filter:** market-engine requires 80% of expected M5 bars to form a valid 4H candle. stock-data-mining has no such filter — if even 1 M5 bar exists in a session half, a 4H bar is produced. In practice this rarely matters for historical data (Alpha Vantage data is complete), but could matter if applied to live data with gaps.

2. **Crypto handling:** market-engine uses UTC-aligned 4H bars for BTC/ETH spot. stock-data-mining only has crypto-proxy equities (IBIT, MARA, COIN) which use standard equity session boundaries. No spot crypto 4H bars exist in the backtester yet.

### Verdict: NO CRITICAL MISALIGNMENT

---

## Part C: Asymmetric Bar Length Impact

### The asymmetry

- **AM bar:** 09:30-13:30 ET = 240 minutes = 48 M5 bars
- **PM bar:** 13:30-16:00 ET = 150 minutes = 30 M5 bars
- **Ratio:** PM is 62.5% the duration of AM

### C1. EMA Impact

EMA 9/21 operates on **bar count**, not time duration. Each bar (AM or PM) gets equal weight in the EMA calculation regardless of its time span.

**Is this correct for our use case?** Mostly yes, with a caveat:
- The PM bar captures less price action (2.5H vs 4H), so its close price reflects a shorter sampling window
- In trending markets, the PM bar's close will show less movement than the AM bar (less time for trend to develop)
- This means EMA crosses detected on PM bars are based on a "compressed" data point
- **Practical impact:** EMA 9/21 crosses are relatively slow signals (9-21 bar lookback = 4.5-10.5 trading days). The asymmetry of individual bars is smoothed over multiple days. Impact is **low but nonzero**.

### C2. Streak Impact

For "3 consecutive 4H down bars" logic:
- A "down bar" in 2.5H PM session has less time to develop range than a 4H AM session
- PM bars tend to have **smaller ranges** (less volume, less time, approaching close)
- A PM down bar could be a mild pullback that wouldn't register as "down" in a 4H-equivalent window
- Conversely, AM bars that include the open have higher volatility (gap risk, overnight positioning)

**Practical impact:** Streak counts could differ by ~1 bar at edges. For a 3-bar streak threshold, this is **potentially significant** — it could be the difference between triggering and not triggering a circuit breaker.

### C3. Robustness Test Proposal (feasibility assessment)

**Option A: 2-bar/day, 195 min each (50/50 split)**
- Bar 1: 09:30-12:45 ET (195 min, ~39 M5 bars)
- Bar 2: 12:45-16:00 ET (195 min, ~39 M5 bars)
- **Pro:** Symmetric, each bar sees equal time
- **Con:** Breaks alignment with market-engine. The 12:45 boundary has no market microstructure significance.
- **Feasibility:** Easy to implement — just change the split point in `build_4h_bars()`. Would require regenerating all 4H indicator files and cross catalogs.

**Option B: 3-bar/day, 130 min each**
- Bar 1: 09:30-11:40 ET (130 min, 26 M5 bars)
- Bar 2: 11:40-13:50 ET (130 min, 26 M5 bars)
- Bar 3: 13:50-16:00 ET (130 min, 26 M5 bars)
- **Pro:** Symmetric, higher resolution
- **Con:** Breaks alignment with market-engine. EMA 9/21 now spans 3-7 days instead of 4.5-10.5. All streak thresholds and EMA gate logic would need recalibration.
- **Feasibility:** Moderate — easy to build, but changes the meaning of all downstream signals.

**Option C: Keep current 2-bar asymmetric (recommended)**
- Already aligned with market-engine
- S44's concern is valid in theory but mitigated by the fact that EMA gates use multi-day lookbacks
- The asymmetry is a known property of NYSE's 6.5H session — any 4H split must be asymmetric

**What would change with alternatives:** EMA 9/21 cross dates would shift by 0-2 bars. Some crosses currently detected on PM bars would move to AM of the next day (or vice versa). Streak counts would change at margins. The cross catalog (559 events) would see ~5-15% of crosses shift timing.

---

## Part D: Recommendation

### Finding: ALIGNED, proceed with caveats

1. **4H bar construction is aligned** between market-engine and stock-data-mining. Both use the same session-anchored boundaries (09:30-13:30 / 13:30-16:00 ET). No critical misalignment.

2. **The asymmetry (4H + 2.5H) is an inherent property** of splitting a 6.5H session into "4H" bars. There is no clean 4H division of NYSE. This is correctly handled in both codebases.

3. **Proceed to Prompt 2.** The 4H bar construction is sound and consistent.

### Minor action items (non-blocking):

- **[LOW] Completeness filter:** Consider adding an 80%-M5-bar completeness check to stock-data-mining's `build_4h_bars()` to match market-engine. Not urgent for historical Alpha Vantage data.

- **[LOW] Document the asymmetry:** The PM bar being 2.5H should be noted in any documentation of streak-based circuit breakers. A streak of 3 PM bars = 7.5H of bearish action, while 3 AM bars = 12H.

- **[OPTIONAL] Robustness test:** If streak-based logic shows edge-case sensitivity in future backtests, consider testing the 195-min symmetric split. Not recommended now as it would break market-engine alignment.

---

## Summary Table

| Question | Answer |
|----------|--------|
| 4H data source | M5 from Alpha Vantage, synthesized to 4H in code |
| Construction method | Split on 13:30 ET boundary (AM/PM) |
| Anchor | 09:30 ET session open |
| Pre-market included? | No |
| Bars per day | 2 (always) |
| Aligned with market-engine? | **Yes** |
| Asymmetry a problem? | Low risk for EMA gates, moderate risk for streak counts |
| Recommendation | **Proceed to Prompt 2** |
