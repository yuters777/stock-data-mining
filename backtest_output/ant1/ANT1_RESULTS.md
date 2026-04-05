# ANT-1: Earnings Recovery Ratio Backtest — Results

**Date:** 2026-04-05
**Period:** 2022-01-03 to 2026-03-31 (daily data)
**Earnings Data:** 446 events from production DB (FMP backfill + quarterly extrapolation, 26 tickers)
**Gap-Down Universe (gap <= -5%):** N=30
**Gap Threshold:** -5%

---

## DATA NOTES

- Daily OHLCV from `backtester/data/daily/` (split-adjusted, 2022-01-03 to 2026-03-31)
- Earnings calendar: 446 events across 26 tickers (JD excluded — no daily data)
  - 131 events from FMP API (confirmed dates with EPS data)
  - 315 events extrapolated backward using quarterly cadence + gap validation
- BMO/AMC classification from known ticker schedules (not from DB `time_of_day` for extrapolated events)
- Some extrapolated dates may align with non-earnings gaps (tariff shocks, macro events)
  — this adds noise but doesn't systematically bias recovery ratio analysis
- **N=30 gap-down events is above the N>=20 "provisional" threshold** but still modest
  — individual bucket Ns remain small (ANECDOTAL to LOW N)

---

## TEST 0: Universe Statistics

| Metric | Value |
|--------|-------|
| Total earnings events | 444 |
| Gap <= -5% | 30 (6.8%) |
| Gap <= -7% | 16 (3.6%) |
| Gap <= -10% | 5 (1.1%) |
| Gap <= -15% | 0 (0.0%) |
| Gap >= +5% | 33 (7.4%) |

### Gap Size Distribution

| Gap Range | Count |
|-----------|-------|
| -15% to -10% | 5 |
| -10% to -7% | 11 |
| -7% to -5% | 14 |
| -5% to -3% | 26 |
| -3% to 0% | 154 |
| 0% to +3% | 176 |
| +3% to +5% | 25 |
| +5% to +7% | 11 |
| +7% to +10% | 9 |
| +10% to +15% | 8 |
| +15% to +20% | 4 |
| > +20% | 1 |

### Timing Split
- AMC: 342 (77.0%)
- BMO: 102 (23.0%)

### Events Per Year
| Year | N |
|------|---|
| 2022 | 102 |
| 2023 | 102 |
| 2024 | 109 |
| 2025 | 105 |
| 2026 | 26 |

### Top Tickers by Event Count
MSTR: 21, SMCI: 20, AVGO/COST/INTC: 18 each, most others: 17

---

## TEST 1: Recovery Ratio vs Multi-Day Drift

**For all gap-down events with gap <= -5% (N=30):**

| Bucket | N | Mean Drift 1d | Mean Drift 3d | Mean Drift 5d | Mean Drift 10d | Median 5d | WR (5d up) | Std Dev 5d | Flag |
|--------|---|---------------|---------------|---------------|----------------|-----------|------------|------------|------|
| A (<0.20) | 11 | +1.09% | +2.10% | +2.98% | +0.60% | -0.78% | 45.5% | 16.71% | LOW N |
| B (0.20-0.30) | 2 | -0.38% | -1.93% | -4.60% | -4.65% | -4.60% | 0.0% | 0.80% | ANECDOTAL |
| C (0.30-0.40) | 5 | +0.30% | +2.58% | +4.84% | +1.55% | +1.71% | 80.0% | 8.38% | ANECDOTAL |
| D (0.40-0.60) | 4 | -0.31% | +5.36% | +3.38% | +5.08% | +0.21% | 50.0% | 10.48% | ANECDOTAL |
| E (>0.60) | 8 | +3.32% | -0.20% | -1.22% | +0.87% | +0.13% | 50.0% | 12.03% | ANECDOTAL |

### Spearman Correlation
- **rho = +0.0194**, p-value = 0.9191
- **Significant at p<0.05: NO**
- Essentially zero correlation — recovery ratio does NOT predict drift direction

### Key Observations
1. **No monotonic relationship.** Bucket A (lowest recovery) has the HIGHEST mean 5d drift (+2.98%), contradicting ANT's core claim
2. **Bucket E (highest recovery) drifts NEGATIVE** at -1.22% over 5 days — opposite of "zombie reversal"
3. **Massive standard deviations** (8-17%) dwarf the mean drifts — high noise, no signal
4. **The mean vs median divergence in Bucket A** (+2.98% mean vs -0.78% median) signals outlier contamination — a few large winners pulling the mean up
5. **Bucket C (0.30-0.40) shows the best WR at 80%** but N=5 is anecdotal

---

## TEST 2: Optimal Zombie Threshold Sweep

| Threshold | N_LONG | N_SHORT | Mean_LONG | Mean_SHORT | WR_LONG | WR_SHORT | Separation |
|-----------|--------|---------|-----------|------------|---------|----------|------------|
| 0.15 | 24 | 6 | +2.40% | -1.01% | 50.0% | 50.0% | **+3.41%** |
| 0.20 | 19 | 11 | +0.99% | +2.98% | 52.6% | 45.5% | -2.00% |
| 0.25 | 17 | 13 | +1.65% | +1.82% | 58.8% | 38.5% | -0.17% |
| 0.30 | 17 | 13 | +1.65% | +1.82% | 58.8% | 38.5% | -0.17% |
| 0.35 | 13 | 17 | +0.93% | +2.32% | 53.8% | 47.1% | -1.39% |
| 0.40 | 12 | 18 | +0.31% | +2.66% | 50.0% | 50.0% | -2.34% |
| 0.50 | 11 | 19 | +0.37% | +2.50% | 54.5% | 47.4% | -2.14% |
| 0.60 | 8 | 22 | -1.22% | +2.79% | 50.0% | 50.0% | -4.00% |

**Optimal threshold: 0.15** (separation = +3.41%)

**ANT claims 0.35-0.40.** Data shows the OPPOSITE pattern:
- At ANT's threshold (0.35), the LOW-recovery group actually drifts MORE positive (+2.32%) than the HIGH-recovery group (+0.93%)
- The only threshold with positive separation is 0.15, which is well below ANT's range
- **This is the strongest evidence against ANT's theory** — recovery ratio > 0.35 does NOT predict upward drift

---

## TEST 3: Gap Size Interaction

|  | Gap -5% to -10% | Gap -10% to -15% | Gap < -15% |
|---|---|---|---|
| Recovery < 0.30 | +2.63% (N=11) LOW N | -2.68% (N=2) ANECDOTAL | N/A |
| Recovery 0.30-0.50 | +3.99% (N=6) ANECDOTAL | N/A | N/A |
| Recovery > 0.50 | +1.32% (N=8) ANECDOTAL | -2.16% (N=3) ANECDOTAL | N/A |

**Observations:**
- For moderate gaps (-5% to -10%), ALL recovery groups drift positive over 5 days — mean reversion dominates regardless of recovery
- For severe gaps (-10% to -15%), both low and high recovery groups drift negative — severity matters more than recovery
- No gap < -15% events in our sample (these may require 2016-2022 data to capture)
- **The gap size itself appears more predictive than recovery ratio**

---

## TEST 4: Day-of-Minimum Distribution

### Low Recovery (<0.30) Events (N=13)

| Day | Count | % | Visual |
|-----|-------|---|--------|
| Day 0 | 2 | 15.4% | ####### |
| Day 1 | 1 | 7.7% | ### |
| Day 3 | 1 | 7.7% | ### |
| Day 5 | 1 | 7.7% | ### |
| Day 7 | 1 | 7.7% | ### |
| Day 8 | 1 | 7.7% | ### |
| Day 9 | 3 | 23.1% | ########### |
| Day 10 | 3 | 23.1% | ########### |

- **Mode: Day 9**, Mean: Day 6.2
- Distribution is bimodal: either Day 0 (bottom IS the gap day) or Day 9-10 (continued selling)
- ANT claims Day 3-5. **Day 3-5 accounts for only 15.4%** of minimums

### High Recovery (>=0.40) Events (N=12)

| Day | Count | % |
|-----|-------|---|
| Day 0 | 4 | 33.3% |
| Day 2 | 3 | 25.0% |
| Day 3 | 1 | 8.3% |
| Day 5 | 1 | 8.3% |
| Day 6 | 2 | 16.7% |
| Day 10 | 1 | 8.3% |

- **Mode: Day 0**, Mean: Day 3.0
- For "zombie" stocks (high recovery), the gap day IS the bottom 33% of the time
- This partially supports ANT's claim that zombies bottom earlier

### Average Trajectories (cumulative % from Day 1 close)

| Day | Rec < 0.20 (N=11) | Rec 0.20-0.40 (N=7) | Rec >= 0.40 (N=12) |
|-----|---|---|---|
| D0 | 0.00% | 0.00% | 0.00% |
| D1 | +1.09% | +0.11% | +2.11% |
| D3 | +2.10% | +1.29% | +1.65% |
| D5 | +2.98% | +2.14% | +0.31% |
| D7 | +2.07% | -0.38% | -1.16% |
| D10 | +0.60% | -0.22% | +2.27% |

**Surprising finding:** Low-recovery stocks (Rec < 0.20) show the BEST trajectory through Day 5,
contradicting ANT's "confirmed weakness" prediction. High-recovery stocks underperform through Day 5-7.

---

## TEST 5: EPS Surprise Interaction

Only 12 of 30 gap-down events have EPS surprise data (FMP-confirmed events only).
All cells are ANECDOTAL (N=1-3). **No meaningful interaction can be measured.**

|  | |Surprise| < 5% | |Surprise| 5-15% | |Surprise| > 15% |
|---|---|---|---|
| Rec < 0.30 | -1.37% (N=3) | -2.68% (N=2) | -1.92% (N=3) |
| Rec 0.30-0.50 | +17.67% (N=1) | -0.07% (N=2) | N/A |
| Rec > 0.50 | N/A | N/A | -5.48% (N=1) |

---

## TEST 6: Zombie LONG & Anti-Zombie SHORT Backtests

### Zombie LONG (gap <= -10%, recovery >= threshold, day1 green)

| Threshold | N | Mean Return | WR | PF | Max Loss | Exit |
|-----------|---|-------------|----|----|----------|------|
| 0.30 | 1 | -13.89% | 0% | 0.00 | -13.89% | stop |
| 0.35 | 1 | -13.89% | 0% | 0.00 | -13.89% | stop |
| 0.40 | 1 | -13.89% | 0% | 0.00 | -13.89% | stop |

**Only 1 trade across all thresholds** — the entry conditions (gap <= -10% + high recovery + green day)
are too restrictive with only 5 gap-down events >= 10%. The single trade hit the stop for -13.89%.

### Anti-Zombie SHORT (gap <= -10%, recovery < 0.20)

| Metric | Value |
|--------|-------|
| N trades | 2 (ANECDOTAL) |
| Mean return | +2.03% |
| Win rate | 50.0% |
| Profit factor | 3.30 |
| Max single loss | -1.77% |
| Avg holding days | 4.0 |

---

## CHARTS

All saved to `backtest_output/ant1/`:
1. `ant1_recovery_vs_drift.png` — Scatter: recovery ratio vs 5-day drift (no visible pattern)
2. `ant1_bucket_drift.png` — Bar chart: drift by bucket (no monotonic pattern)
3. `ant1_trajectory.png` — Trajectory lines showing low-recovery stocks outperform
4. `ant1_day_of_min.png` — Day-of-min histogram (bimodal for low-recovery)
5. `ant1_threshold_sweep.png` — Threshold sweep (best separation at 0.15, not 0.35)

---

## VERDICT

### ANT's Theory: **NOT SUPPORTED by data**

| ANT Claim | Our Finding | Status |
|-----------|-------------|--------|
| Higher recovery → more positive drift | rho = +0.02, p = 0.92 (zero correlation) | **REJECTED** |
| Optimal threshold ~0.35-0.40 | Best at 0.15; ANT's range shows REVERSE separation | **REJECTED** |
| Recovery < 0.20 = "confirmed weakness" (continues down) | Mean drift_5d = +2.98% (goes UP, not down) | **REJECTED** |
| Recovery > 0.40 = "zombie" reversal (goes UP) | Mean drift_5d = +0.31% to -1.22% (flat to down) | **REJECTED** |
| Day-of-min is Day 3-5 (institutional liquidation) | Mode = Day 9 for low-recovery; bimodal Day 0/9-10 | **NOT CONFIRMED** |
| Zombie LONG is tradeable (PF > 1.5) | 1 trade, stopped out -13.89% | **UNTESTABLE** (N=1) |

### What the data actually shows:
1. **Mean reversion dominates.** Gap-down stocks tend to bounce regardless of recovery ratio
2. **Recovery ratio is noise, not signal.** Spearman rho ≈ 0 with p = 0.92
3. **Gap severity matters more than recovery.** Moderate gaps (-5% to -10%) mean-revert; severe gaps (-10%+) continue
4. **Low-recovery stocks bounce MORE** than high-recovery stocks through Day 5 — exact opposite of ANT
5. **Day-of-minimum is bimodal:** either Day 0 (immediate bottom) or Day 9-10 (extended selling) — not Day 3-5

### Caveats:
- N=30 gap-down events is above "provisional" (N>=20) but below "live-eligible" (N>=40 OOS)
- Individual recovery buckets have N=2-11, mostly ANECDOTAL
- Extrapolated earnings dates may include non-earnings gap events (adds noise)
- Only 4 years of data (2022-2026); a longer sample back to 2016 could change results
- These results apply to THIS ticker universe; ANT may trade different names

### Recommendations for Module 5 (PEAD-lite):
1. **DO NOT add recovery ratio as a filter** — no predictive value found
2. **Consider gap severity** instead: moderate gaps (-5% to -10%) show consistent mean reversion
3. **Entry timing:** the bimodal day-of-min distribution suggests either enter Day 1 (if bottom)
   or wait until Day 8+ (if extended selling) — but Day 3-5 entry is NOT optimal
4. **Re-test with pre-2022 data** if available — the 2022-2023 bear market may have different
   characteristics than the 2024-2026 bull market

---

## REPRODUCIBILITY

```bash
cd /home/user/stock-data-mining
python3 ant1_earnings_recovery.py

# Outputs:
# backtest_output/ant1/ANT1_summary.json
# backtest_output/ant1/events.csv
# backtest_output/ant1/ant1_*.png (5 charts)
# backtest_output/ant1/run_output.txt
```
