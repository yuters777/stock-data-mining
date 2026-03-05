# Claude Code Task: Backtest on 25 Tickers — Frozen Config A

## Context

The False Breakout backtester is in `yuters777/stock-data-mining/backtester/`. It was previously validated on 5 tickers (GOOGL, MSFT, META, AMZN, TSLA) with Config A producing:
- 55 OOS trades, PF 1.47, Sharpe 2.05, +$4,614, MaxDD 2.5%

We've now expanded the data universe to **25 tickers** with 13 months of 5-min data (1.45M rows) in the `yuters777/MarketPatterns-AI` private repo. The earnings filter bug has been fixed (`backtester/earnings.py`, merged).

**Goal:** Run frozen Config A on all 25 tickers. No parameter changes. This is a data expansion test — we want more OOS trades to approach the MinTRL target of 202.

## 25 Tickers

```python
TICKERS = [
    'AAPL', 'AMD', 'AMZN', 'AVGO', 'BA', 'BABA', 'BIDU', 'C', 'COIN', 'COST',
    'GOOGL', 'GS', 'IBIT', 'JPM', 'MARA', 'META', 'MSFT', 'MU', 'NVDA',
    'PLTR', 'SNOW', 'TSLA', 'TSM', 'TXN', 'V'
]
```

## Tasks

### Task 1: Data Pipeline — Load 25 Tickers

The 5-min CSV data is in `MarketPatterns-AI/Fetched_Data/{TICKER}_data.csv`.

**Steps:**
1. Clone or access `MarketPatterns-AI` repo to get the CSV files
2. Use the existing `backtester/data_loader.py` to load and process:
   - Load M5 data for all 25 tickers
   - Aggregate D1 bars from regular session M5 bars only
   - Apply session tagging (PRE_MARKET / REGULAR / POST_MARKET)
   - Saturday IST bars (00:00-02:55) → map to Friday's trading day
3. Validate: no NULLs, High >= Low, correct columns
4. Report: per-ticker row counts, date range, any issues

**Data format:** `Datetime,Open,High,Low,Close,Volume,Ticker` — IST timezone, timezone-naive.

**If the data loader already handles this (it should from Phase 2),** just point it at the 25-ticker data and verify it works. If it was hardcoded to 5 or 9 tickers, update to accept all 25.

### Task 2: Load Earnings Calendar

Use the new `backtester/earnings.py` module:
```python
from backtester.earnings import EarningsCalendar

calendar = EarningsCalendar()
calendar.load(TICKERS)  # Fetches via yfinance, caches to JSON
```

Pass the calendar into `BacktestConfig.earnings_calendar` so the filter chain gets earnings dates.

### Task 3: Run Backtest — Frozen Config A

**CRITICAL: No parameter changes. Use exactly these values:**

```python
FROZEN_CONFIG_A = {
    'FRACTAL_DEPTH_D1': 10,
    'ATR_ENTRY': 0.60,
    'ATR_BLOCK': 0.20,
    'MIN_RISK_REWARD': 2.0,
    'TAIL_RATIO_MIN': 0.15,
    'MAX_STOP_ATR_PCT': 0.15,
    'SAWING_THRESHOLD': 5,
    'SAWING_PERIOD': 30,
    'MAX_CONSECUTIVE_LOSSES_PER_LEVEL': 2,
    'REGIME_ADX_MAX': 27,
    'REGIME_ATR_RATIO_MAX': 1.3,
    # Squeeze detection: REMOVED (do not include)
    # Direction filters: NONE (no per-ticker long/short rules)
    
    # Standard risk params (unchanged from L-005.1 §9):
    'RISK_PER_TRADE': 0.003,         # 0.3%
    'HARD_CAP_20_50': 0.15,
    'HARD_CAP_50_100': 0.25,
    'HARD_CAP_100_200': 0.40,
    'BREAKEVEN_TRIGGER_MULT': 2.0,
    'SLIPPAGE_CENTS': 0.01,
    'SLIPPAGE_PCT': 0.0002,
    'INITIAL_CAPITAL': 100_000,
    
    # Portfolio constraints:
    'MAX_CONCURRENT_POSITIONS': 5,
    'MAX_PER_SECTOR': 2,
    'MAX_CORRELATED': 2,
    'MAX_TRADES_PER_DAY': 10,
    'MAX_PORTFOLIO_RISK': 0.015,
    
    # Context filters:
    'OPEN_DELAY_MINUTES': 5,
    'EARNINGS_FILTER': True,          # NOW ACTIVE (earnings.py)
    'LAST_ENTRY_TIME': '15:45',
    'EOD_FLAT_TIME': '15:55',
    
    # Circuit breakers:
    'MAX_LOSSES_SERIES': 3,
    'MAX_DAILY_LOSS': 0.01,
    'MAX_WEEKLY_LOSS': 0.02,
    'MAX_MONTHLY_LOSS': 0.08,
}
```

**Run the backtest on the full date range available** (approximately Feb 2025 — Mar 2026).

### Task 4: Generate Results Report

After the backtest completes, generate a comprehensive report with:

**4a. Summary Metrics:**
```
Total trades, Win rate, Profit Factor, Sharpe (daily equity, annualized),
Max Drawdown ($ and %), Total P&L, Avg R-multiple, Max consecutive losses
```

**4b. Comparison vs Previous (5-ticker) Results:**

| Metric | 5-Ticker (Phase 2.5) | 25-Ticker (Phase 3) | Delta |
|--------|---------------------|---------------------|-------|
| Trades | 55 | ? | |
| PF | 1.47 | ? | |
| Sharpe | 2.05 | ? | |
| MaxDD | 2.5% | ? | |
| P&L | +$4,614 | ? | |

**4c. Per-Ticker Breakdown:**
- Trades, PF, P&L for each of the 25 tickers
- Identify which tickers contribute most/least
- Flag any ticker with 0 trades (possible data or level detection issue)

**4d. Per-Pattern Breakdown:**
- LP1, LP2, CLP, Model #4 — trade count, win rate, PF for each

**4e. Signal Funnel:**
```
Levels detected → Patterns detected → Blocked by [each filter stage] → Approved → Executed
```
With the earnings filter now active, report how many signals it blocks.

**4f. Equity Curve:**
Save daily equity values to CSV for plotting.

**4g. Trade Log:**
Save complete trade log to CSV: trade_id, ticker, direction, pattern, entry_time, entry_price, exit_time, exit_price, exit_reason, pnl_dollars, pnl_r.

### Task 5: Statistical Diagnostics (if scipy available)

**5a. DSR / MinTRL:**
```python
# Deflated Sharpe Ratio (López de Prado)
# Given: N trials = 1 (frozen config, no optimization on this data)
# Calculate: PSR, DSR, MinTRL
# Question: With 25-ticker trade count, are we closer to MinTRL=202?
```

**5b. CSCV/PBO:**
If the walk-forward infrastructure exists, re-run CSCV with the expanded dataset. Otherwise defer — just running the flat backtest is the priority.

**5c. P&L Concentration:**
- Herfindahl index on per-trade P&L contributions
- What % of total P&L comes from top 5 trades?
- What % comes from top 3 tickers?

### Task 6: Shadow Log

Save ALL unfiltered signals (pre-filter) to a separate CSV:
```
signal_id, ticker, timestamp, direction, pattern, level_price, level_score,
filter_result (APPROVED/BLOCKED), blocked_by (stage name), blocked_reason
```

This is for future analysis — understanding what the filter chain kills.

## Output Files

Save all results to `results/phase3_25ticker/`:

```
results/phase3_25ticker/
├── backtest_summary.json          # All metrics in JSON
├── backtest_summary.md            # Human-readable report
├── trade_log.csv                  # All executed trades
├── equity_curve.csv               # Daily equity values
├── signal_funnel.json             # Signal attrition data
├── shadow_log.csv                 # ALL signals (pre-filter)
├── per_ticker_metrics.csv         # Per-ticker breakdown
├── per_pattern_metrics.csv        # Per-pattern breakdown
├── diagnostics/
│   ├── dsr_mintrl.json            # DSR results (if calculated)
│   └── pnl_concentration.json    # Herfindahl, top-N analysis
```

## Constraints

1. **Config A is FROZEN.** Do not modify any parameters. If something looks wrong, report it but don't fix by tweaking params.
2. **No per-ticker customization.** Same config for all 25 tickers. No direction filters.
3. **Earnings filter is now active.** Use the new `earnings.py` module. Report how many signals it blocks.
4. **Chronological bar processing.** Bars across all symbols must be processed in timestamp order (not ticker-by-ticker). This is critical for portfolio constraint enforcement.
5. **Data is in IST timezone.** Session times (09:30 ET open, 15:55 ET flatten) must account for IST→ET conversion.

## What We're Looking For

The key question this backtest answers: **Does the edge survive universe expansion?**

- If PF > 1.25 and trade count > 100 → edge likely real, proceed to forward test
- If PF < 1.0 → edge was ticker-specific, need to investigate
- If trade count < 80 → still insufficient, may need more history or tickers
- Earnings filter impact: how many signals blocked? Does it improve or hurt PF?

**Report honestly. Bad results are more valuable than false positives at this stage.**
