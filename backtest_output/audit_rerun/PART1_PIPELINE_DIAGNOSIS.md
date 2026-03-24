# Part 1: Pipeline Diagnosis & Fix

**Date:** 2026-03-24
**Discovered in:** Series I tests I8 and I9
**Severity:** CRITICAL — 77% of bars in _m5_regsess.csv files were from the wrong trading session

---

## 1.1 Bug Confirmation

### What _m5_regsess.csv Files Contain

The files appear normal — one timestamp block from 09:30 to 15:55 ET, 78 bars per day. **But bars after ~10:55 are from the wrong data source.**

The raw Alpha Vantage CSVs (`Fetched_Data/{TICKER}_data.csv`) contain two overlapping blocks per day:

| Block | Timestamp Range | Source | Content |
|-------|:--------------:|--------|---------|
| **ET block** | 04:00–10:55 | Original Alpha Vantage US/Eastern | Pre-market + first 85 min of regular session |
| **IST block** | 11:00–23:55 | Shifted +7h by `fetch_SP500_Data.py` | Full pre-market + regular + post-market in IST |

The IST block's regular session (16:30–22:55 IST) contains the **correct** 09:30–15:55 ET bars. But the old pipeline grabbed bars by raw timestamp range 09:30–15:55, capturing:
- **09:30–10:55**: from ET block → **CORRECT** (real market data)
- **11:00–15:55**: from IST block → **WRONG** (IST pre-market = ~04:00–08:55 ET)

### Proof: Side-by-Side Bar Comparison (TSLA, 2025-02-03)

| Time | regsess "12:00 ET" | Raw 12:00 IST (pre-mkt) | Raw 19:00 IST (real noon) |
|------|:------------------:|:-----------------------:|:------------------------:|
| Open | 393.78 | **393.78** ← match | 382.80 |
| Volume | 29,692 | **29,692** ← match | 810,139 |
| Session | — | Pre-market (~05:00 ET) | **Regular session (12:00 ET)** |

The regsess file's "12:00 ET" bar matches the IST pre-market bar, NOT the actual noon bar.

| Ticker | regsess noon Vol | IST pre-mkt Vol | Real noon Vol | regsess matches |
|--------|:----------------:|:---------------:|:-------------:|:---------------:|
| SPY | 634,727 | 634,727 | 5,243 | IST pre-mkt ✗ |
| NVDA | 101,237 | 101,237 | 2,481,360 | IST pre-mkt ✗ |
| TSLA | 29,692 | 29,692 | 810,139 | IST pre-mkt ✗ |

**All three confirm: regsess noon bars = IST pre-market, NOT real noon.**

---

## 1.2 IST Block Characterization

| Question | Answer |
|----------|--------|
| IST rows time range in regsess | 11:00–15:55 (displayed as "ET" but actually IST) |
| Are they OHLCV duplicates? | **No** — they are completely different bars (different session) |
| Shift | Consistent +7h (IST = ET + 7h in all Alpha Vantage files) |
| IST vs US row ratio in regsess | ~60 IST rows / 18 US rows per day (~77% IST) |
| All 27 tickers affected? | **Yes** — every single ticker |
| Date range | All dates (Feb 2025 – Mar 2026) |
| Volume signature | IST bars: 1K–100K (pre-market). Real bars: 100K–5M (regular session) |

---

## 1.3 Root Cause

### File
`phase1_test0_test1.py`, lines 35–42

### Code (BEFORE fix)
```python
# Filter to regular session: 09:30-15:55 ET (bar start times)
# Data timestamps are already in ET based on empirical check   ← WRONG ASSUMPTION
filtered = {}
for tk in TICKERS_27:
    df = raw_data[tk].copy()
    t = df["Datetime"].dt.time
    mask = (t >= pd.Timestamp("09:30").time()) & (t <= pd.Timestamp("15:55").time())
    filtered[tk] = df[mask].copy()
```

### Why It Breaks
1. The comment "timestamps are already in ET" was partially true — the ET block (04:00–10:55) IS in ET
2. But the IST block (11:00–23:55) is NOT in ET — it's IST (ET + 7h)
3. The filter `09:30 ≤ time ≤ 15:55` captures 09:30–10:55 from the ET block (correct) and 11:00–15:55 from the IST block (wrong)
4. The IST regular session bars (16:30–22:55) are OUTSIDE the filter and excluded

### Origin of the +7h Shift
`MarketPatterns_AI/fetch_SP500_Data.py` (approximately line 1350):
```python
processed_df['Datetime'] = processed_df['Datetime'] + pd.Timedelta(hours=7)
```
This appends IST-shifted bars to the CSV without removing the original ET bars, creating the dual-block structure.

---

## 2.1 Fix Applied

### Source Generator (phase1_test0_test1.py)

```python
# FIXED 2026-03-24: Select IST regular session block, convert to ET
filtered = {}
for tk in TICKERS_27:
    df = raw_data[tk].copy()
    hm = df["Datetime"].dt.hour * 60 + df["Datetime"].dt.minute
    mask = (hm >= 16 * 60 + 30) & (hm <= 22 * 60 + 55)
    filt = df[mask].copy()
    filt["Datetime"] = filt["Datetime"] - pd.Timedelta(hours=7)
    filtered[tk] = filt
```

---

## 2.2 Defensive Loader

Created: `utils/data_loader.py` with `load_m5_regsess()` function.

Features:
- Loads from raw `Fetched_Data/` CSVs (never from processed files)
- Filters to IST regular session (16:30–22:55 IST)
- Converts to ET timestamps (subtract 7h)
- Deduplicates and sorts
- Logs warning if >70% of rows filtered (expected for dual-block structure)
- Raises ValueError if no valid rows found

---

## 2.3 Validation: All 27 Tickers

| Ticker | Old Rows | New Rows | Δ | % Change | Noon Vol (sample) | Status |
|:------:|:--------:|:--------:|:---:|:--------:|:-----------------:|:------:|
| AAPL | 21,942 | 21,996 | +54 | +0.2% | 171,449 | OK |
| AMD | 21,870 | 21,996 | +126 | +0.6% | 237,860 | OK |
| AMZN | 22,176 | 21,996 | -180 | -0.8% | 210,835 | OK |
| AVGO | 21,870 | 21,996 | +126 | +0.6% | 144,491 | OK |
| BA | 21,806 | 21,996 | +190 | +0.9% | 37,305 | OK |
| BABA | 21,940 | 21,996 | +56 | +0.3% | 74,647 | OK |
| BIDU | 21,713 | 21,893 | +180 | +0.8% | 11,194 | OK* |
| C | 21,623 | 21,988 | +365 | +1.7% | 92,091 | OK |
| COIN | 21,942 | 21,996 | +54 | +0.2% | 68,161 | OK |
| COST | 21,704 | 21,996 | +292 | +1.3% | 8,787 | OK* |
| GOOGL | 22,176 | 21,996 | -180 | -0.8% | 153,649 | OK |
| GS | 21,779 | 21,987 | +208 | +1.0% | 8,579 | OK* |
| IBIT | 21,870 | 21,991 | +121 | +0.6% | 367,235 | OK |
| JPM | 21,829 | 21,996 | +167 | +0.8% | 58,965 | OK |
| MARA | 21,868 | 21,996 | +128 | +0.6% | 488,501 | OK |
| META | 22,176 | 21,996 | -180 | -0.8% | 38,648 | OK* |
| MSFT | 22,176 | 21,996 | -180 | -0.8% | 94,482 | OK |
| MU | 21,870 | 21,996 | +126 | +0.6% | 63,305 | OK |
| NVDA | 22,176 | 21,996 | -180 | -0.8% | 2,122,656 | OK |
| PLTR | 21,870 | 21,996 | +126 | +0.6% | 1,005,688 | OK |
| SNOW | 21,765 | 21,991 | +226 | +1.0% | 44,988 | OK* |
| **SPY** | **21,996** | **12,018** | **-9,978** | **-45.4%** | 4,454 | **NOTE** |
| TSLA | 22,176 | 21,996 | -180 | -0.8% | 907,581 | OK |
| TSM | 21,870 | 21,996 | +126 | +0.6% | 252,669 | OK |
| TXN | 21,631 | 21,972 | +341 | +1.6% | 17,933 | OK* |
| V | 21,791 | 21,994 | +203 | +0.9% | 58,317 | OK |
| **VIXY** | **21,955** | **8,921** | **-13,034** | **-59.4%** | 23 | **NOTE** |

**OK*** = lower noon volume due to single-exchange Alpha Vantage data (expected per A1 audit)

### SPY and VIXY Notes

SPY drops from 21,996 to 12,018 rows (−45.4%) and VIXY from 21,955 to 8,921 (−59.4%). This is because Alpha Vantage provides limited IST-block data for ETFs — SPY and VIXY have fewer bars in the 16:30–22:55 IST range. The old (buggy) pipeline filled the gap with IST pre-market bars, artificially inflating the row count. The fixed data has fewer rows but every bar is genuine regular-session data.

For SPY: 12,018 rows / 78 bars per day ≈ 154 full days out of 282. **SPY has incomplete afternoon data from Alpha Vantage.** Analysis using SPY bars after ~11:00 ET should check for missing bars.

---

## Fixed Files Created

- `backtest_output/{TICKER}_m5_regsess_FIXED.csv` — for all 27 tickers
- Original `_m5_regsess.csv` files preserved (not overwritten) for Part 2/3 comparison
- `utils/data_loader.py` — defensive loader for all future scripts
- `phase1_test0_test1.py` — source generator fixed

---

## Impact Summary

| Scope | Description |
|-------|-------------|
| **What was wrong** | 77% of bars in _m5_regsess.csv were IST pre-market data (~04:00–08:55 ET) disguised as regular session (11:00–15:55 ET) |
| **Root cause** | Naive time filter on dual-block raw CSVs |
| **Confirmed impact** | H2 Noon Reversal: +1.11%/83.6% WR → +0.07%/54% WR (I8 test) |
| **Scripts affected** | ~20 (10 audit, 8 S21 phase, 2 phase scripts) — see I9 for full list |
| **Series I (I1–I8)** | NOT affected (used raw data with correct IST filter) |
| **Fix** | Select IST regular session (16:30–22:55), convert to ET (−7h) |
