# CLAUDE.md v5 — Regime Filter Phase

## Context

Phase 4.1 achieved **profitable OOS portfolio** (PF=1.27, +$2,070, 49.2% WR, 4 tickers) but **walk-forward failed: 0/8 positive windows**. IS period (Feb-Sep 2025) is deeply unprofitable while OOS (Oct-Jan 2026) works. This means the edge is regime-dependent.

**Diagnosis:** False breakout strategy works in range-bound / low-trend markets where D1 levels hold. In trending markets, "false" breakouts become true breakouts and stops get hit systematically.

**This phase adds regime filters to skip trading during unfavorable market conditions.**

**DO NOT change any existing modules.** Only ADD regime detection and filtering.

---

## Current Best Config (v4.1 winner)

```python
# Portfolio
tickers = ['AAPL', 'AMZN', 'GOOGL', 'TSLA']

# Level detection
fractal_depth = 10
tolerance_cents = 0.05, tolerance_pct = 0.001
atr_period = 5, min_level_score = 5

# Pattern + Filters  
tail_ratio_min = 0.10
atr_block = 0.30, atr_entry = 0.80
All filters ON

# Risk
min_rr = 1.5, max_stop_atr_pct = 0.10, risk_pct = 0.003

# Exit: 2-tier trail
t1_pct = 0.30, trail_factor = 0.7, trail_activation = 0.0R
intraday_target = h1_fractal k=3
```

### Walk-Forward Problem (why we're here)

| Window | Period | Trades | PF | P&L | Market Condition? |
|--------|--------|--------|----|------|-------------------|
| 1 | May→Jun 2025 | 7 | 0.34 | -$1,061 | ? |
| 2 | Jun→Jul 2025 | 11 | 0.14 | -$1,880 | ? |
| 3 | Jul→Aug 2025 | 32 | 0.77 | -$990 | ? |
| 4 | Aug→Sep 2025 | 14 | 0.48 | -$1,146 | ? |
| 5 | Sep→Oct 2025 | 21 | 0.53 | -$1,563 | ? |
| 6 | Oct→Nov 2025 | 29 | 0.72 | -$1,045 | ? |
| 7 | Nov→Dec 2025 | 13 | 1.29 | +$526 | ? |
| 8 | Dec→Jan 2026 | 21 | 0.75 | -$833 | ? |

**Step 1 of this phase: fill in the "Market Condition?" column.** Compute ADX and ATR regime for each window to understand WHEN the strategy works.

---

## Phase 5A: Regime Analysis (Diagnostic — No Trading Changes)

**Before adding any filter, understand the regime-performance correlation.**

### Step 1: Compute daily regime indicators for each ticker

```python
def compute_regime_indicators(daily_df):
    """Add regime columns to daily dataframe."""
    
    # 1. ADX (Average Directional Index) — trend strength
    #    ADX < 20: range-bound (GOOD for false breakouts)
    #    ADX 20-30: developing trend (CAUTION)
    #    ADX > 30: strong trend (BAD — breakouts are real)
    #    Use 14-period ADX
    adx_14 = compute_adx(daily_df, period=14)
    
    # 2. ATR expansion/contraction — volatility regime
    #    ATR_ratio = ATR(5) / ATR(20)
    #    < 0.8: volatility contracting (range tightening, GOOD)
    #    0.8-1.2: neutral
    #    > 1.2: volatility expanding (breakout environment, BAD)
    atr_ratio = atr_5 / atr_20
    
    # 3. Daily range position — where is price in recent range?
    #    rolling_high_20 = max(High, 20 days)
    #    rolling_low_20 = min(Low, 20 days)
    #    range_position = (Close - rolling_low) / (rolling_high - rolling_low)
    #    < 0.3 or > 0.7: near extremes (GOOD for reversal)
    #    0.3-0.7: mid-range (NEUTRAL)
    
    return daily_df  # with new columns: adx_14, atr_ratio_5_20, range_position_20
```

### Step 2: Correlate regime with trade outcomes

```python
def analyze_regime_performance(trades_df, daily_regime_df):
    """For each trade, look up the regime on entry day. 
    Then compute WR and PF per regime bucket."""
    
    for trade in trades:
        entry_date = trade.entry_time.date()
        regime = daily_regime_df.loc[entry_date]
        trade.adx = regime.adx_14
        trade.atr_regime = regime.atr_ratio_5_20
        trade.range_pos = regime.range_position_20
    
    # Bucket ADX
    buckets = {
        'ADX < 20 (range)': trades[trades.adx < 20],
        'ADX 20-30 (transition)': trades[(trades.adx >= 20) & (trades.adx < 30)],
        'ADX > 30 (trend)': trades[trades.adx >= 30],
    }
    
    for name, bucket in buckets.items():
        print(f'{name}: {len(bucket)} trades, WR={wr}%, PF={pf}, P&L=${pnl}')
    
    # Same for ATR regime and range position
```

### Step 3: Map regimes to walk-forward windows

For each of the 8 WF windows, compute the average ADX and ATR regime during that test period. This tells us definitively: "Window 7 was profitable because ADX was 18 (range-bound)" or similar.

**Output: regime_analysis.md** with:
- Table: WF Window | Avg ADX | Avg ATR Regime | PF | Correlation
- Table: ADX Bucket | Trades | WR | PF | P&L
- Table: ATR Regime Bucket | Trades | WR | PF | P&L
- Scatter plot data: trade ADX vs trade R-multiple

---

## Phase 5B: Regime Filters (Based on 5A Findings)

**Only proceed after 5A shows clear regime-performance separation.**

### Filter 1: ADX Gate

```python
# In filter_chain.py, add:
def check_regime_filter(self, ticker, date, daily_df):
    adx = daily_df.loc[date, 'adx_14']
    
    if adx > self.config.adx_max_threshold:  # e.g., 30
        return False, f'ADX={adx:.1f} > {self.config.adx_max_threshold} (trending)'
    return True, 'OK'
```

**Test matrix:**

| Experiment | ADX Threshold | Description |
|------------|--------------|-------------|
| R-001a | ADX < 25 | Strict: only range-bound |
| R-001b | ADX < 30 | Moderate: exclude strong trends |
| R-001c | ADX < 35 | Permissive: only exclude extreme trends |
| R-001d | No filter | Baseline (current) |

### Filter 2: ATR Regime Gate

```python
def check_volatility_regime(self, ticker, date, daily_df):
    atr_5 = daily_df.loc[date, 'atr_5']
    atr_20 = daily_df.loc[date, 'atr_20']
    atr_regime = atr_5 / atr_20
    
    if atr_regime > self.config.atr_regime_max:  # e.g., 1.3
        return False, f'ATR expanding ({atr_regime:.2f}) — breakout environment'
    return True, 'OK'
```

**Test matrix:**

| Experiment | ATR Regime Max | Description |
|------------|---------------|-------------|
| R-002a | < 1.0 | Only contracting vol |
| R-002b | < 1.2 | Moderate |
| R-002c | < 1.5 | Permissive |
| R-002d | No filter | Baseline |

### Filter 3: Combined Regime Score

```python
def compute_regime_score(adx, atr_regime, range_position):
    """0 = worst for FB strategy, 100 = best."""
    
    # ADX component (lower = better, max score at ADX < 15)
    adx_score = max(0, min(100, (40 - adx) * 100 / 25))
    
    # ATR regime component (lower = better)
    atr_score = max(0, min(100, (1.5 - atr_regime) * 100 / 0.7))
    
    # Range position (extremes = better)
    range_score = max(abs(range_position - 0.5) * 2, 0) * 100
    
    return 0.5 * adx_score + 0.3 * atr_score + 0.2 * range_score

# Gate: only trade when regime_score > threshold
```

**Test matrix:**

| Experiment | Min Regime Score | Description |
|------------|-----------------|-------------|
| R-003a | > 40 | Permissive |
| R-003b | > 50 | Moderate |
| R-003c | > 60 | Strict |

---

## Phase 5C: Walk-Forward Re-validation

Run the best regime filter on the same 8 walk-forward windows:

**Key expectation:** Regime filter should:
1. **Block trades in bad windows** (1,2,4,5 → fewer trades, less loss)
2. **Allow trades in good windows** (7 → same or more trades)
3. **Improve mean PF from 0.63 to >1.0**
4. **Increase positive windows from 0/8 to ≥4/8**

If the regime filter reduces total trades below 50, that's acceptable — better to trade less and be profitable than trade more and lose.

---

## Phase 5D: Final Report

Generate `results/OPTIMIZATION_REPORT_v5.md`:

```markdown
## Regime Analysis
- ADX correlation with PF: r = ???
- Best ADX bucket: ???
- ATR regime correlation: ???

## Filter Impact
| Config | Trades | WR | PF | P&L | WF Positive |
|--------|--------|-----|-----|------|-------------|
| No regime filter | 63 | 49% | 1.27 | +$2,070 | 0/8 |
| ADX < 30 | ??? | | | | ???/8 |
| Best regime | ??? | | | | ???/8 |

## Walk-Forward Comparison
| Window | No Filter PF | With Filter PF | Trades Blocked |

## Signal Funnel Addition
  Blocked by regime (ADX): ???
  Blocked by regime (ATR): ???

## Recommended Production Config
```

---

## Execution Order

```
1. Phase 5A: Compute regime indicators for all 4 tickers
2. Phase 5A: Correlate with existing v4.1 trade results (no new backtests needed!)
3. Phase 5A: Map regimes to WF windows → regime_analysis.md
4. Decision point: IF clear separation → proceed. IF no correlation → STOP.
5. Phase 5B: ADX filter sweep (R-001a-d)
6. Phase 5B: ATR regime filter sweep (R-002a-d)
7. Phase 5B: Combined regime score sweep (R-003a-c)
8. Phase 5C: Walk-forward with best regime filter
9. Phase 5D: Final report
```

---

## ADX Implementation Notes

ADX requires computing +DI, -DI, and DX first. Use standard Wilder's smoothing:

```python
import numpy as np

def compute_adx(daily_df, period=14):
    high = daily_df['High'].values
    low = daily_df['Low'].values  
    close = daily_df['Close'].values
    
    # True Range
    tr = np.maximum(high - low, 
         np.maximum(abs(high - np.roll(close, 1)), 
                    abs(low - np.roll(close, 1))))
    
    # Directional Movement
    up_move = high - np.roll(high, 1)
    down_move = np.roll(low, 1) - low
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    
    # Wilder's smoothing (EMA with alpha = 1/period)
    atr = wilder_smooth(tr, period)
    plus_di = 100 * wilder_smooth(plus_dm, period) / atr
    minus_di = 100 * wilder_smooth(minus_dm, period) / atr
    
    # DX and ADX
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = wilder_smooth(dx, period)
    
    return adx

def wilder_smooth(data, period):
    """Wilder's smoothing = EMA with alpha = 1/period."""
    result = np.zeros_like(data, dtype=float)
    result[period] = np.mean(data[1:period+1])  # Initial SMA
    for i in range(period+1, len(data)):
        result[i] = result[i-1] + (data[i] - result[i-1]) / period
    return result
```

Or use `ta` library if available: `pip install ta --break-system-packages`

```python
from ta.trend import ADXIndicator
adx_ind = ADXIndicator(high=df['High'], low=df['Low'], close=df['Close'], window=14)
df['adx_14'] = adx_ind.adx()
```

---

## Critical Reminders

1. **Phase 5A is DIAGNOSTIC.** Do not add filters until you see the correlation data. If ADX shows no correlation with trade outcomes → regime filter won't help, and we stop here.

2. **Use EXISTING v4.1 trade results** for Phase 5A. Just look up each trade's entry date in the regime data. No new backtest needed for the diagnostic.

3. **Walk-forward is THE success metric.** OOS PF doesn't matter if WF fails. Every experiment must re-run walk-forward.

4. **Fewer trades is OK.** If regime filter cuts 63 trades to 30 but makes 5/8 WF windows positive, that's a massive win.

5. **ADX is computed on D1 data.** It's a daily indicator, applied once per day. All M5 signals on the same day get the same ADX gate decision.

6. **Don't overfit the regime filter.** We only have 8 walk-forward windows. If the best ADX threshold perfectly separates good/bad windows, be suspicious — with 8 data points, even random noise can correlate.

7. **The real test:** Does the regime filter block trades in windows 1,2,4,5 (disasters) without blocking window 7 (the winner)?

**Start with Phase 5A: compute regime indicators and correlate with existing trades. Go.**
