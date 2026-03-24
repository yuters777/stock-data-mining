# Audit C2 Re-Run: First-Hour Width Ratio & Breakout (FIXED Data)

**Date:** 2026-03-24
**Data Source:** `load_m5_regsess()` (IST-block extraction → correct regular session)
**Original:** Buggy naive filter on `Fetched_Data/` (`"09:30" <= hhmm < "16:00"`)

---

## Verdict: ⚠️⚠️ MATERIALLY REVISED — Breakout Rates Dramatically Different

With clean data, wide-day double breakout drops from **30.0% to 8.7%** — much closer
to the original framework claim of ~4.8%.

---

## Comparison Table

| Metric | Original (buggy) | Re-run (FIXED) | Delta | Verdict |
|--------|:-----------------:|:--------------:|:-----:|:-------:|
| Ticker-days | 7,454 | 7,597 | +1.9% | Minor difference |
| Width ratio mean | 0.635 | 0.714 | +0.079 | ⚠️ Higher in clean data |
| Width ratio median | 0.642 | 0.726 | +0.084 | ⚠️ Higher |
| **Narrow days** | 596 (8.0%) | 266 (3.5%) | -4.5pp | REVISED |
| **Medium days** | 2,647 (35.5%) | 2,045 (26.9%) | -8.6pp | REVISED |
| **Wide days** | 4,211 (56.5%) | 5,286 (69.6%) | +13.1pp | REVISED |
| Narrow double BO | 73.7% | 48.1% | -25.6pp | ⚠️ REVISED |
| Medium double BO | 61.2% | 21.8% | -39.4pp | ⚠️⚠️ MAJOR |
| **Wide double BO** | **30.0%** | **8.7%** | **-21.3pp** | ⚠️⚠️ MAJOR |
| Wide double BO vs claim (4.8%) | NO (+25.2pp) | **~CLOSE (+3.9pp)** | REVISED toward claim |

## Key Finding

The original buggy data inflated double breakout rates across all width classes.
With clean regular-session data:

- **Wide-day double breakout = 8.7%** (was 30.0%, claim was 4.8%)
- The claim of ~4.8% is still low, but 8.7% is in the right ballpark
- The monotonic relationship holds: Narrow > Medium > Wide for double breakouts
- **Pattern is directionally correct but magnitudes changed dramatically**

## Per-Ticker Wide-Day Double Breakout Rate (Selected)

| Ticker | Buggy Rate | FIXED Rate | Delta |
|--------|:----------:|:----------:|:-----:|
| SPY | 16.1% | 3.8% | -12.3pp |
| GOOGL | 33.5% | 4.8% | -28.7pp |
| AAPL | 24.7% | 6.8% | -17.9pp |
| NVDA | 33.1% | 8.5% | -24.6pp |
| TSLA | 38.5% | 8.2% | -30.3pp |
| MARA | 20.6% | 13.9% | -6.7pp |
| VIXY | 19.7% | 21.7% | +2.0pp |

---

## Raw Results

```
Tickers: 27 | Ticker-days: 7,597

WIDTH CLASS DISTRIBUTION (FIXED):
  Narrow:    266 days (3.5%)
  Medium:  2,045 days (26.9%)
  Wide:    5,286 days (69.6%)

BREAKOUT RATES BY WIDTH CLASS (FIXED):
           None    Single   Double
  Narrow   0.0%    51.9%    48.1%
  Medium   0.0%    78.2%    21.8%
  Wide    18.4%    72.9%     8.7%

PER-TICKER WIDE-DAY DOUBLE BREAKOUT RATE (FIXED):
  AAPL: 6.8%    BA:  10.2%    GOOGL: 4.8%    NVDA:  8.5%
  AMD:  9.1%    BABA: 5.6%    GS:    8.9%    PLTR: 10.7%
  AMZN: 6.1%    BIDU: 3.9%    IBIT: 14.2%    SNOW:  7.1%
  AVGO: 8.5%    C:   10.2%    JPM:   5.5%    SPY:   3.8%
                COIN: 11.9%   MARA: 13.9%    TSLA:  8.2%
                COST:  8.0%   META:  7.8%    TSM:   8.6%
                              MSFT:  9.8%    TXN:  11.1%
                              MU:    8.0%    V:    11.3%
                                             VIXY: 21.7%
```
