# S20 Backtest Battery: Stress-Tested Portfolio Selection
# Prompt for Claude Code — run in stock-data-mining repo

## Context

We are validating the "Stress-Tested Portfolio Selection" methodology — a system that identifies which assets hold up best during market stress (VIX spikes) and selects them as candidates for entry during the subsequent VIX crush phase.

The core hypothesis: assets showing relative strength during stress have institutional conviction behind them and offer the best risk-adjusted entries when VIX starts falling.

## Data Location

All M5 intraday data is in the MarketPatterns-AI repo: `C:\Projects\MarketPatterns-AI\Fetched_Data\`

Files follow the pattern: `{TICKER}_data.csv` (e.g., `SPY_data.csv`, `NVDA_data.csv`)

CSV format: `Datetime, Open, High, Low, Close, Volume, Ticker` columns, IST timezone.

**27 equity/ETF tickers:**
```
AAPL, AMD, AMZN, AVGO, BA, BABA, BIDU, C, COIN, COST,
GOOGL, GS, IBIT, JPM, MARA, META, MSFT, MU, NVDA,
PLTR, SNOW, TSLA, TSM, TXN, V, SPY, VIXY
```

**VIX daily data:** `C:\Projects\MarketPatterns-AI\Fetched_Data\VIX_daily.csv`  
Format: `Date, VIX_Close` — 284 rows, Feb 2025 to Mar 2026.

If VIX_daily.csv is not in Fetched_Data, check the repo root or `C:\Projects\MarketPatterns-AI\VIXCLS_FRED_real.csv`.

**Key roles:**
- **SPY** = market benchmark (for excess return, beta calculation). NOT a trade candidate.
- **VIXY** = intraday VIX proxy (for crush timing analysis). NOT a trade candidate.
- **VIX_daily.csv** = event identification (which days are stress days).
- **25 remaining tickers** = the actual trade universe being ranked.

## Session Filtering

CRITICAL: All analysis must use REGULAR session hours only (09:30-16:00 ET).
The data contains PRE_MARKET and POST_MARKET bars — filter them out.

IST to ET conversion: IST is ET+7 (during standard time) or ET+6 (during DST mismatch Mar 8-28, 2026). For simplicity, filter M5 bars where the trading time falls within 09:30-16:00 ET. The `Datetime` column is in IST — convert accordingly or use the session tags if present.

Practical approach: Regular session bars typically fall between 16:30-23:00 IST (standard) or 15:30-22:00 IST (DST). Safest: compute the time-of-day from the Datetime column, and keep only bars that correspond to 09:30-16:00 ET.

## Test Battery (9 Tests)

### Test 0: Data Inventory & Quality Check (RUN FIRST)

Before any analysis:
1. Load all 27 CSV files, report row counts and date ranges
2. Verify SPY and VIXY loaded correctly
3. Load VIX daily, report date range
4. Count number of unique trading days per ticker
5. Identify any data gaps (missing trading days)
6. Filter to REGULAR session only — report how many bars remain per ticker
7. Compute daily returns (close-to-close) for all 25 trade universe tickers + SPY

Save the cleaned, session-filtered, daily-return dataset for use by all subsequent tests.

---

### Test 1: Stress Event Identification

**Goal:** Define which days qualify as "stress days" using VIX daily data.

**Method:**
1. Load VIX_daily.csv
2. Calculate daily VIX change %
3. Define stress events at multiple thresholds:
   - Level A: VIX daily close > 25 (elevated vol)
   - Level B: VIX daily change > +10% (spike day)
   - Level C: VIX daily change > +15% (major spike)
   - Level D: Market stress proxy — day when median return of 25 tickers < -1.0%
   - Level E: Same but < -1.5%
   - Level F: Same but < -2.0%
4. Cross-tabulate: how many days qualify at each level?
5. Identify spike→crush pairs: spike day followed by VIX drop >5% within 3 days
6. Create master event calendar with columns:
   `Date | VIX_Close | VIX_Chg% | MedianTickerReturn | StressLevel | CrushNext3D`

**Output:** Event calendar CSV + summary statistics. Print the number of events at each threshold.

**CRITICAL:** All subsequent tests depend on this event identification. Use **Level D (median return < -1.0%)** as the primary definition unless N < 15, in which case relax to -0.75%.

---

### Test 2: Cross-Sectional RS Persistence (CORE TEST)

**Hypothesis:** Tickers with better relative return in the AM window continue to outperform in the PM window on stress days.

**Method:**
1. For each stress day (Level D), split into:
   - AM window: 09:30-12:30 ET (first 3 hours)
   - PM window: 12:30-16:00 ET (last 3.5 hours)
2. For each ticker, compute AM return = (price at 12:30 / price at 09:30) - 1
3. Rank all 25 tickers by AM return (1=best, 25=worst)
4. Divide into quintiles: Q1 (top 5), Q2 (6-10), Q3 (11-15), Q4 (16-20), Q5 (bottom 5)
5. For each quintile, compute average PM return
6. Compute: spread = Q1_avg_PM - Q5_avg_PM

**Output:**
- Table: Quintile | Avg AM Return | Avg PM Return | PM Hit Rate (% positive) | N
- Average spread Q1-Q5 across all stress days
- T-test: is the spread statistically different from zero?
- Scatter plot: AM rank vs PM return (all tickers × all stress days)

---

### Test 3: RS Leader Forward Returns (Multi-Horizon)

**Hypothesis:** RS leaders at midday give better forward returns at +1h, +2h, and EOD.

**Method:**
1. On stress days, rank tickers at 12:00 ET by return since open (09:30)
2. Compute forward returns from 12:00 ET to:
   - +1 hour (13:00 ET)
   - +2 hours (14:00 ET)
   - EOD (16:00 ET close)
3. Group by quintile (same Q1-Q5 as Test 2)
4. For each horizon × quintile: average return, hit rate, std dev

**Output:**
- Table: Quintile | +1h Avg | +1h HitRate | +2h Avg | +2h HitRate | EOD Avg | EOD HitRate
- Chart: cumulative return by quintile across the 3 horizons
- Best single entry point (which hour gives best Q1 return vs Q5)

---

### Test 4: Laggard Rebound vs Leader Continuation

**Hypothesis:** Leaders outperform laggards even when the market recovers in PM. Laggards are NOT "cheap convexity."

**Method:**
1. On stress days, rank tickers at 12:00 ET
2. Split stress days into two groups:
   - Recovery days: SPY PM return > 0% (market bounced)
   - Continuation days: SPY PM return <= 0% (market kept falling)
3. For each group, compute Q1 (leaders) vs Q5 (laggards) PM returns

**Output:**
- Table: Day Type | N Days | Q1 PM Avg | Q5 PM Avg | Spread | Q5 "Rebound" Premium
- Key question answered: Do laggards snap back harder on recovery days? Or do leaders still win?
- If laggards outperform on recovery days → "cheap convexity" has some merit (contradicts S20)
- If leaders outperform even on recovery days → S20 anti-laggard rule VALIDATED

---

### Test 5: Sector-Adjusted RS

**Hypothesis:** Raw RS overstates strength when an entire sector is green on a red tape (e.g., banks in Day 9).

**Method:**
1. Define sector mapping:
   ```
   Tech: AAPL, AMD, AMZN, AVGO, GOOGL, META, MSFT, MU, NVDA, PLTR, SNOW, TSM, TXN
   Financial: C, COIN, GS, IBIT, JPM, MARA, V
   ConsumerDisc: BABA, TSLA
   Communication: BIDU
   Industrials: BA
   ConsumerStaples: COST
   ```
2. On stress days, compute:
   - RS_raw = ticker AM return
   - Sector_median = median AM return of sector peers
   - RS_adj = ticker AM return - sector_median
3. Rank by RS_raw and RS_adj separately
4. Compare: how often does sector adjustment change the Top-5?
5. Spearman rank correlation between raw and adjusted rankings

**Output:**
- Average Spearman correlation across stress days
- % of stress days where Top-5 changes between raw and adjusted
- Example days where sector adjustment makes the biggest difference
- Recommendation: is sector adjustment worth the complexity?

---

### Test 6: DefenseRank Validation (Intraday Path Quality)

**Hypothesis:** Tickers with small intraday drawdown (relative to ATR) are better candidates than tickers with good close but ugly path.

**Method:**
1. On stress days, for each ticker compute:
   - MaxDD_AM = maximum peak-to-trough drawdown during AM window (09:30-12:30)
   - ATR20 = 20-day average true range (from prior 20 days' daily data)
   - DefenseScore = -MaxDD_AM / ATR20 (higher = less drawdown = better defense)
2. Rank by DefenseScore (1=best defense, 25=worst)
3. Compare PM returns: DefenseRank Top-5 vs Close-Return-Rank Top-5
4. Which ranking method produces better PM returns?

**Output:**
- Table: Ranking Method | Top-5 Avg PM Return | Hit Rate | Sharpe
- Correlation between DefenseRank and Close-Return-Rank
- Cases where they diverge meaningfully
- Recommendation: add DefenseRank to composite score?

---

### Test 7: Stress Frequency & Sample Size (POWER ANALYSIS)

**Goal:** Determine if we have enough data for statistically meaningful results.

**Method:**
1. Count stress days at each threshold (from Test 1)
2. For the primary threshold (Level D): how many events?
3. For each test: compute minimum N needed for 80% power at 5% significance
   (use observed effect sizes from Tests 2-6)
4. Flag which tests have sufficient power and which are exploratory

**Output:**
- Table: Test | Observed Effect | Required N | Actual N | Power | Status (Sufficient/Exploratory)
- Overall assessment: is 13 months of data enough?

---

### Test 8: Beta-Adjusted Excess Return vs Raw Return

**Hypothesis:** Beta-adjusted excess return is better than raw return for RS ranking.

**Method:**
1. Compute rolling 60-day beta for each ticker vs SPY
   Beta = Cov(ticker_returns, SPY_returns) / Var(SPY_returns)
2. On stress days, compute:
   - Raw_return = ticker AM return
   - Excess_return = ticker AM return - beta × SPY AM return
3. Rank by raw vs excess
4. Compare: which ranking predicts PM returns better?

**Output:**
- Table: Method | Q1 PM Avg | Q5 PM Avg | Spread | T-stat
- Improvement (if any) from beta adjustment
- Recommendation: use raw or beta-adjusted?

---

### Test 9: VIXY Intraday Analysis (Exploratory)

**Goal:** Can VIXY M5 data identify intraday stress onset and crush timing?

**Method:**
1. On stress days, compute VIXY intraday trajectory:
   - VIXY AM high (peak stress)
   - VIXY PM low (crush trough)
   - Time of VIXY peak → time of VIXY trough = crush duration
2. Compute VIXY-based CrushConfirmed proxy:
   - VIXY has fallen >8% from intraday high
   - AND 3 of last 5 M5 bars are negative
3. At CrushConfirmed time: what are Q1 (RS leaders) forward returns to EOD?
4. Compare: entry at CrushConfirmed vs entry at fixed 12:00 vs entry at 14:00

**Output:**
- Average crush duration (peak to trough)
- Average time-of-day for CrushConfirmed
- Return comparison: CrushConfirmed entry vs fixed-time entries
- NOTE: VIXY is an imperfect VIX proxy (contango decay, tracking error). Flag this caveat.

---

## Output Requirements

1. **Create a comprehensive report** in markdown: `S20_Backtest_Battery_Results.md`
2. **Save all intermediate data** as CSVs in an output folder
3. **Include charts** where specified (save as PNG):
   - Test 2: AM rank vs PM return scatter
   - Test 3: Quintile cumulative returns by horizon
   - Test 4: Leader vs Laggard bar chart (recovery vs continuation)
   - Test 7: Power analysis summary
4. **Summary table** at the top of the report:

```
| Test | Hypothesis | Result | Statistical Significance | N Events |
|------|-----------|--------|------------------------|----------|
| 2 | RS persists AM→PM | ? | p=? | ? |
| 3 | Leaders best at all horizons | ? | ? | ? |
| 4 | Leaders > Laggards even in recovery | ? | ? | ? |
| 5 | Sector adjustment matters | ? | ? | ? |
| 6 | DefenseRank adds value | ? | ? | ? |
| 8 | Beta-adj > Raw | ? | ? | ? |
| 9 | VIXY CrushConfirmed timing works | ? | ? | ? |
```

5. **Conclusion section:** Based on results, which S20 components are VALIDATED, which need more data, and which should be REJECTED?

## Technical Notes

- Use pandas, numpy, scipy.stats for analysis
- For t-tests: scipy.stats.ttest_1samp or ttest_ind
- For rank correlation: scipy.stats.spearmanr
- For charts: matplotlib
- Handle missing data gracefully — some tickers may not trade on all days
- All times in ET for analysis (convert from IST in the raw data)
- When computing "return since open", use the first REGULAR session bar close as open price (not the literal Open of the first bar, which may gap)
