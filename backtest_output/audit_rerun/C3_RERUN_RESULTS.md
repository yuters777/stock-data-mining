# Audit C3 Re-Run: False Breakout Rate by Zone (FIXED Data)

**Date:** 2026-03-24
**Priority:** HIGHEST — C3 Dead Zone 76.4% is a CORE zone rule
**Data Source:** `load_m5_regsess()` (IST-block extraction → correct regular session)
**Original:** Buggy naive filter on `Fetched_Data/` (`"09:30" <= hhmm < "16:00"`)

---

## Verdict: ⚠️⚠️ MATERIALLY REVISED — Zone Rankings Changed

The original C3 result (76.4% Dead Zone false breakout) was **inflated by IST pre-market
contamination**. With clean data, the Dead Zone false breakout rate drops to **53.3%**,
which actually **falls within the original framework claim of 45-55%**.

**Critical change:** Dead Zone is NO LONGER the highest false-breakout zone.

---

## Comparison Table

| Metric | Original (buggy) | Re-run (FIXED) | Delta | Verdict |
|--------|:-----------------:|:--------------:|:-----:|:-------:|
| Total breakouts | 15,468 | 10,186 | -34.2% | Fewer false signals in clean data |
| **Zone 2 (10:00-12:00)** | 41.9% | 56.3% | +14.4pp | ⚠️ REVISED |
| **Zone 3 Dead Zone** | **76.4%** | **53.3%** | **-23.1pp** | ⚠️⚠️ MAJOR REVISION |
| **Zone 4 (13:30-14:45)** | 75.1% | 57.3% | -17.8pp | ⚠️ REVISED |
| **Zone 5 (14:45-16:00)** | 70.3% | 42.3% | -28.0pp | ⚠️ REVISED |
| Zone 3 vs Claim (45-55%) | NO (76.4%) | **YES (53.3%)** | — | ✅ NOW CONFIRMED |

## Zone Ranking Change

| Rank | Original (buggy) | Re-run (FIXED) |
|:----:|:----------------:|:--------------:|
| 1st | Zone 3 Dead Zone (76.4%) | **Zone 4 (57.3%)** |
| 2nd | Zone 4 (75.1%) | **Zone 2 (56.3%)** |
| 3rd | Zone 5 (70.3%) | **Zone 3 Dead Zone (53.3%)** |
| 4th | Zone 2 (41.9%) | Zone 5 (42.3%) |

**The Dead Zone dropped from #1 to #3.** Zone 4 (13:30-14:45) is now the highest
false-breakout zone.

---

## Impact on Zone Rules

### Original Recommendation (based on buggy data):
> "Avoid ALL breakout entries 12:00-14:45 — 75-76% false breakout"

### Revised Recommendation (based on clean data):
The false breakout rates are much more uniform across zones (42-57%).
The Dead Zone is NOT dramatically worse than other zones.

- Zone 4 (57.3%) and Zone 2 (56.3%) are actually WORSE than the Dead Zone
- Zone 5 (42.3%) is the safest zone for breakouts
- The framework's original 45-55% claim for Dead Zone is now CONFIRMED
- **No blanket zone avoidance is warranted** — all zones have moderate false rates

### Implication for Core Zone Reliability Ratings:
Zone reliability ratings based on the original 76.4% figure **need revision**.
The Dead Zone is still elevated but not catastrophically so.

---

## Raw Results

```
Tickers: 27 | Total breakouts: 10,186
Lookback: 6 bars | Lookahead: 6 bars | Threshold: 0.3%

FALSE BREAKOUT RATE BY ZONE:
  Zone 2 (10:00-12:00):           56.3%  (4,897 breakouts)
  Zone 3 (12:00-13:30) DEAD ZONE: 53.3%  (2,155 breakouts)
  Zone 4 (13:30-14:45):           57.3%  (1,347 breakouts)
  Zone 5 (14:45-16:00):           42.3%  (1,787 breakouts)

BY DIRECTION (Zone 3):
  UP:   53.9% false (990 breakouts)
  DOWN: 52.7% false (1,165 breakouts)

PER-TICKER DEAD ZONE HIGHLIGHTS:
  Highest: COST 71.4%, COIN 62.5%, AVGO 62.2%
  Lowest:  SPY 0.0% (only 25 breakouts), MSFT 22.2% (9 breakouts)
  Note: SPY has very few Zone 3 breakouts due to truncated data (ends 13:00)
```
