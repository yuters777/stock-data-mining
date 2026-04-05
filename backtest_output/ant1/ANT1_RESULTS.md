# ANT-1: Earnings Recovery Ratio Backtest — Results

**Date:** 2026-04-05
**Period:** 2022-01-03 to 2026-03-31 (daily data availability)
**Earnings Data:** FMP earnings, 2024-10 to 2026-03 (~6 quarters)
**Tickers:** 22 with both price + earnings data (26 with price, 24 with earnings)
**Gap Threshold:** -5%

---

## CRITICAL LIMITATION: SMALL SAMPLE SIZE

**Total earnings events:** 130 (across 22 tickers, ~6 earnings per ticker)
**Gap-down events (gap <= -5%):** 12
**Gap-down events (gap <= -10%):** 2

The FMP earnings data available in this environment only covers approximately 6 quarters
(late 2024 to early 2026). Combined with daily price data starting 2022-01-03, this yields
a usable window of ~18 months. **ALL results below are ANECDOTAL (N < 20) and should not
be used for trading decisions.** The infrastructure is ready to re-run with full historical
data (2016-present) once the production DB or FMP API access is available.

---

## TEST 0: Universe Statistics

| Metric | Value |
|--------|-------|
| Total earnings events | 130 |
| Gap <= -5% | 12 (9.2%) |
| Gap <= -7% | 9 (6.9%) |
| Gap <= -10% | 2 (1.5%) |
| Gap <= -15% | 0 (0.0%) |
| Gap >= +5% | 21 (16.2%) |

### Gap Size Distribution

| Gap Range | Count |
|-----------|-------|
| -15% to -10% | 2 |
| -10% to -7% | 7 |
| -7% to -5% | 3 |
| -5% to -3% | 9 |
| -3% to 0% | 42 |
| 0% to +3% | 36 |
| +3% to +5% | 10 |
| +5% to +7% | 6 |
| +7% to +10% | 6 |
| +10% to +15% | 5 |
| +15% to +20% | 3 |
| > +20% | 1 |

### Timing Split
- AMC (after market close): 94 (72.3%)
- BMO (before market open): 36 (27.7%)

### Events Per Year
- 2024: 21
- 2025: 88
- 2026: 21

---

## TEST 1: Recovery Ratio vs Multi-Day Drift

**For all gap-down events with gap <= -5% (N=12):**

| Bucket | N | Mean Drift 1d | Mean Drift 3d | Mean Drift 5d | Mean Drift 10d | Median 5d | WR (5d up) | Std Dev 5d | Flag |
|--------|---|---------------|---------------|---------------|----------------|-----------|------------|------------|------|
| A (<0.20) | 7 | -1.38% | -2.03% | -1.60% | -0.71% | -1.95% | 42.9% | 3.84% | ANECDOTAL |
| B (0.20-0.30) | 1 | +0.14% | -2.54% | -4.03% | -3.54% | -4.03% | 0.0% | N/A | ANECDOTAL |
| C (0.30-0.40) | 2 | -0.00% | +0.52% | +8.89% | +1.55% | +8.89% | 100.0% | 12.42% | ANECDOTAL |
| D (0.40-0.60) | 2 | -1.21% | -2.17% | -2.87% | -0.24% | -2.87% | 0.0% | 3.69% | ANECDOTAL |
| E (>0.60) | 0 | — | — | — | — | — | — | — | — |

### Spearman Correlation
- **rho = -0.2168**, p-value = 0.4986
- **Significant at p<0.05: NO**
- Direction is actually negative (opposite of ANT's prediction), but not significant

### Interpretation
With only 12 events, no meaningful pattern can be extracted. The negative Spearman rho
is contrary to ANT's prediction but statistically insignificant. Bucket C (recovery 0.30-0.40)
shows the highest drift at +8.89% but this is driven by just 2 events — one of which was a
strong outlier.

---

## TEST 2: Optimal Zombie Threshold Sweep

| Threshold | N_LONG | N_SHORT | Mean_LONG | Mean_SHORT | WR_LONG | WR_SHORT | Separation |
|-----------|--------|---------|-----------|------------|---------|----------|------------|
| 0.15 | 9 | 3 | -0.53% | +0.51% | 33.3% | 66.7% | -1.04% |
| 0.20 | 5 | 7 | +1.60% | -1.60% | 40.0% | 42.9% | +3.20% |
| 0.25 | 4 | 8 | +3.01% | -1.91% | 50.0% | 37.5% | +4.92% |
| 0.30 | 4 | 8 | +3.01% | -1.91% | 50.0% | 37.5% | +4.92% |
| 0.35 | 2 | 10 | -2.87% | +0.25% | 0.0% | 50.0% | -3.12% |
| 0.40 | 2 | 10 | -2.87% | +0.25% | 0.0% | 50.0% | -3.12% |
| 0.45 | 2 | 10 | -2.87% | +0.25% | 0.0% | 50.0% | -3.12% |
| 0.50 | 1 | 11 | -5.48% | +0.21% | 0.0% | 45.5% | -5.69% |

**Optimal threshold: 0.25** (separation = +4.92%)
**ANT claims: 0.35-0.40** — data suggests lower threshold, but with N < 20 this is unreliable.

---

## TEST 3: Gap Size Interaction

|  | Gap -5% to -10% | Gap -10% to -15% | Gap < -15% |
|---|---|---|---|
| Recovery < 0.30 | -1.65% (N=6) ANECDOTAL | -2.68% (N=2) ANECDOTAL | N/A |
| Recovery 0.30-0.50 | +5.84% (N=3) ANECDOTAL | N/A | N/A |
| Recovery > 0.50 | -5.48% (N=1) ANECDOTAL | N/A | N/A |

**Note:** No events with gap < -15% in our sample. Only 2 events with gap <= -10%, making
ANT's -10% threshold untestable with current data.

---

## TEST 4: Day-of-Minimum Distribution

### Low Recovery (<0.30) Events (N=8)

| Day | Count | % |
|-----|-------|---|
| Day 1 | 1 | 12.5% |
| Day 3 | 1 | 12.5% |
| Day 5 | 1 | 12.5% |
| Day 7 | 1 | 12.5% |
| Day 9 | 2 | 25.0% |
| Day 10 | 2 | 25.0% |

- **Mode: Day 9**, Mean: Day 6.8
- ANT claims Day 3-5. Data shows later minimum (Day 9), but N=8 is anecdotal.
- The late minimum is directionally consistent with ANT's claim that "weakness continues for
  days after the gap" — these stocks kept drifting down through the full 10-day window.

### High Recovery (>=0.40) Events (N=2)
- Mode: Day 2, Mean: Day 3.5
- Too few events to draw conclusions.

### Average Trajectories (cumulative % from Day 1 close)

| Day | Rec < 0.20 (N=7) | Rec 0.20-0.40 (N=3) | Rec >= 0.40 (N=2) |
|-----|---|---|---|
| 0 | 0.00% | 0.00% | 0.00% |
| 1 | -1.38% | +0.05% | -1.21% |
| 3 | -2.03% | -0.50% | -2.17% |
| 5 | -1.60% | +4.58% | -2.87% |
| 10 | -0.71% | -0.15% | -0.24% |

---

## TEST 5: EPS Surprise Interaction

|  | |Surprise| < 5% | |Surprise| 5-15% | |Surprise| > 15% |
|---|---|---|---|
| Rec < 0.30 | -1.37% (N=3) | -2.68% (N=2) | -1.92% (N=3) |
| Rec 0.30-0.50 | +17.67% (N=1) | -0.07% (N=2) | N/A |
| Rec > 0.50 | N/A | N/A | -5.48% (N=1) |

**All cells are ANECDOTAL (N < 10).** No meaningful interaction can be measured.

---

## TEST 6: Zombie LONG & Anti-Zombie SHORT Backtests

### Zombie LONG (gap <= -10%, recovery >= threshold, day1 green)
- **0.30 threshold:** 0 trades (no events meet gap <= -10% + recovery >= 0.30 + green day)
- **0.35 threshold:** 0 trades
- **0.40 threshold:** 0 trades

**Why no trades:** Only 2 events had gap <= -10%, and neither had high recovery + green day.

### Anti-Zombie SHORT (gap <= -10%, recovery < 0.20)

| Metric | Value |
|--------|-------|
| N trades | 2 (ANECDOTAL) |
| Mean return | +2.03% |
| Win rate | 50.0% |
| Profit factor | 3.30 |
| Max single loss | -1.77% |
| Avg holding days | 4.0 |
| Exit reasons | target: 1, max_hold: 1 |

**2 trades is meaningless.** One hit target, one expired at max hold.

---

## CHARTS

All saved to `backtest_output/ant1/`:
1. `ant1_recovery_vs_drift.png` — Recovery ratio vs 5-day drift scatter
2. `ant1_bucket_drift.png` — Mean drift by recovery bucket
3. `ant1_trajectory.png` — Average price trajectory by recovery group
4. `ant1_day_of_min.png` — Day-of-minimum histograms
5. `ant1_threshold_sweep.png` — Threshold sweep: separation & win rate

---

## VERDICT

### Can we confirm or deny ANT's theory?

**INCONCLUSIVE — insufficient data.**

| ANT Claim | Our Finding | Confidence |
|-----------|-------------|------------|
| Recovery ratio predicts drift direction | Spearman rho = -0.22, p = 0.50 (WRONG SIGN, not significant) | NONE (N=12) |
| Optimal threshold ~0.35-0.40 | Best separation at 0.25 | NONE (N=12) |
| Day-of-min is Day 3-5 | Mode = Day 9 for low-recovery | NONE (N=8) |
| Zombie LONG is tradeable | 0 trades generated | UNTESTABLE |
| Anti-Zombie SHORT works | PF=3.30 but N=2 | ANECDOTAL |

### What we need to properly test this:

1. **More earnings data:** The current FMP data covers only ~6 quarters (late 2024 to early 2026).
   We need the full production DB with 1034 rows from 2016-present, or re-run `fmp_earnings_fetcher.py backfill`
   with a valid FMP API key to get ~40 quarters per ticker.

2. **Expected N with full data:** With 27 tickers x ~40 quarters = ~1,080 earnings events.
   If ~10% gap down >= 5%, that gives ~108 gap-down events — enough for meaningful bucket analysis.
   If ~3% gap down >= 10%, that gives ~32 events — borderline for zombie backtest.

3. **The script is ready:** `ant1_earnings_recovery.py` will automatically use any expanded
   data dropped into `backtester/data/fmp_earnings.csv` and the daily price CSVs.

### Recommendations for Module 5

1. **DO NOT use recovery ratio as a filter yet** — no evidence it works with current data.
2. **Re-run with full historical data** once production DB access is restored or FMP API key is available.
3. **If re-run shows Spearman rho > 0.20 with p < 0.05**, integrate recovery ratio as a PEAD-lite
   entry filter (delay LONG entry when recovery < threshold).
4. **The day-of-minimum finding (late, not Day 1)** is directionally interesting — if confirmed with
   more data, it supports delaying LONG entry to Day 3-5.

---

## REPRODUCIBILITY

```bash
# Re-run the backtest:
cd /home/user/stock-data-mining
python3 ant1_earnings_recovery.py

# To add more earnings data:
export FMP_API_KEY=your_key
python3 utils/fmp_earnings_fetcher.py backfill

# Output files:
# backtest_output/ant1/ANT1_summary.json   (machine-readable)
# backtest_output/ant1/events.csv          (all computed events)
# backtest_output/ant1/ant1_*.png          (5 charts)
```
