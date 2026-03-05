# Claude Code Task: Fix Earnings Filter Bug — stock-data-mining/backtester

## Context

The False Breakout backtester has an earnings filter at Stage 1 of the filter chain (§4.5.2). The filter is currently **INERT** — it evaluated 720 signals and blocked 0. Root cause: earnings calendar data is never loaded, so `is_earnings_day` is always `False`.

This is tracked as Known Issue #1 in L-005.3 §B.5.

## What Exists

The backtester is in `stock-data-mining/backtester/`. Key files:

- `filter_chain.py` — Stage 1 context filter checks `context.is_earnings_day` and `context.is_post_earnings`
- `data_types.py` — `FilterContext` dataclass has `is_earnings_day: bool` and `is_post_earnings: bool`
- `backtester.py` — main loop populates `FilterContext` before calling filter chain
- There is NO `earnings.py` or `load_earnings_calendar()` implementation yet

## What Needs to Be Built

### 1. Create `backtester/earnings.py`

```python
"""Earnings calendar loader using yfinance.

Pre-loads ALL earnings dates before simulation starts (no per-bar API calls).
Ref: L-005.1 §4.5.2, Backtester_Architecture_v1.md §5.5
"""

def load_earnings_calendar(
    symbols: list[str],
    date_range: tuple[date, date]
) -> dict[str, set[date]]:
    """Load earnings dates for all symbols in the backtest universe.
    
    Uses yfinance to fetch historical earnings dates.
    
    Args:
        symbols: List of ticker symbols (e.g., ['AAPL', 'NVDA', ...])
        date_range: (start_date, end_date) of backtest period
        
    Returns:
        {symbol: set[date]} — set of dates when symbol has earnings
        
    Fallback: If yfinance fails for a symbol, that symbol gets an EMPTY set
              (not block-all — we'll log a warning). The spec says block-all on
              API failure, but for backtesting historical data, blocking everything
              would destroy results. We compromise: log warning, continue.
              For LIVE trading, the fallback MUST be block-all.
    """
```

**yfinance approach:**

```python
import yfinance as yf

def load_earnings_calendar(symbols, date_range):
    earnings = {}
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            # Get earnings dates from yfinance
            # yfinance provides earnings_dates or calendar
            dates = set()
            
            # Method 1: earnings_dates (most reliable for historical)
            if hasattr(ticker, 'earnings_dates') and ticker.earnings_dates is not None:
                for dt in ticker.earnings_dates.index:
                    d = dt.date()
                    if date_range[0] <= d <= date_range[1]:
                        dates.add(d)
            
            # Method 2: quarterly_earnings (fallback)
            if not dates and hasattr(ticker, 'quarterly_earnings'):
                # Parse from quarterly data
                pass
            
            earnings[symbol] = dates
            logging.info(f"{symbol}: {len(dates)} earnings dates loaded")
            
        except Exception as e:
            logging.warning(f"{symbol}: earnings load failed ({e}) — using empty set")
            earnings[symbol] = set()
    
    return earnings
```

**Important:** yfinance API can be flaky. The function must:
- Handle timeouts (set timeout=10)
- Handle missing data (some tickers may not have earnings info)
- Cache results to `backtester/data/earnings_cache.json` so subsequent runs don't re-fetch
- Load from cache if cache exists and covers the date range

### 2. Add caching

```python
CACHE_FILE = 'backtester/data/earnings_cache.json'

def _save_cache(earnings: dict[str, set[date]]):
    """Save earnings to JSON cache."""
    serializable = {sym: [d.isoformat() for d in dates] for sym, dates in earnings.items()}
    with open(CACHE_FILE, 'w') as f:
        json.dump(serializable, f, indent=2)

def _load_cache() -> dict[str, set[date]] | None:
    """Load earnings from JSON cache if it exists."""
    if not os.path.exists(CACHE_FILE):
        return None
    with open(CACHE_FILE, 'r') as f:
        data = json.load(f)
    return {sym: {date.fromisoformat(d) for d in dates} for sym, dates in data.items()}
```

### 3. Integrate into backtester.py

In the `Backtester.__init__()` or `Backtester.run()` method, **before** the simulation loop:

```python
# Pre-load earnings calendar (no per-bar API calls)
from earnings import load_earnings_calendar

self.earnings_calendar = load_earnings_calendar(
    symbols=list(d1_data.keys()),
    date_range=date_range
)
```

Then when building `FilterContext` for each bar:

```python
trading_day = bar.timestamp.date()  # or however trading_day is determined

is_earnings = trading_day in self.earnings_calendar.get(bar.symbol, set())

# Post-earnings: yesterday was earnings day, and current time < 10:30 ET
yesterday = trading_day - timedelta(days=1)
is_post_earnings = (
    yesterday in self.earnings_calendar.get(bar.symbol, set())
    and bar.timestamp.time() < time(10, 30)
)

context = FilterContext(
    ...
    is_earnings_day=is_earnings,
    is_post_earnings=is_post_earnings,
    ...
)
```

### 4. Update filter_chain.py (if needed)

Verify Stage 1 actually checks both fields. Expected logic:

```python
def _stage1_context(self, signal, ctx) -> str:
    # Earnings check
    if self.config.get('EARNINGS_FILTER', True):
        if ctx.is_earnings_day:
            return 'BLOCK'  # reason: "Earnings day"
        if ctx.is_post_earnings:
            return 'BLOCK'  # reason: "Post-earnings before 10:30"
    
    # Open delay check
    # ... existing code ...
```

### 5. Write tests

```python
# tests/test_earnings.py

def test_load_earnings_returns_dict():
    """Should return {symbol: set[date]} for all symbols."""

def test_cache_round_trip():
    """Save and load cache should return identical data."""

def test_earnings_day_blocks_signal():
    """Signal on earnings day should be BLOCKED at Stage 1."""

def test_post_earnings_before_1030_blocks():
    """Signal day after earnings, before 10:30, should be BLOCKED."""

def test_post_earnings_after_1030_passes():
    """Signal day after earnings, after 10:30, should PASS earnings check."""

def test_no_earnings_data_passes():
    """Symbol with no earnings dates should PASS (not block-all in backtest)."""
```

### 6. Add yfinance to requirements

If not already in requirements.txt or setup:
```
pip install yfinance
```

## Spec Reference

**L-005.1 §4.5.2:**
```
IF CheckEarnings(Symbol, Today) THEN Signal = BLOCKED

IF CheckEarnings(Symbol, Yesterday) AND CurrentTime < 10:30 THEN
  Signal = BLOCKED

IF EarningsAPI.is_unavailable() THEN
  Signal = BLOCKED  // Default to safety (LIVE only)
```

**L-005.3 §B.2.2 (Ablation audit finding):**
```
Earnings filter: 720 evaluated, 0 blocked, 0 unique kills
Status: INERT (bug: no data loaded)
```

## Constraints

- **Pre-load before simulation.** No yfinance API calls during bar processing.
- **Cache results.** Don't re-fetch on every backtest run.
- **25 tickers.** Must work for expanded universe (Phase 3).
- **No config changes.** Config A is frozen. `EARNINGS_FILTER: true` is already in config.
- **IST timestamps.** The backtester uses IST. Convert earnings dates to trading_day correctly (earnings date = the calendar date, check against `trading_day` which already accounts for Saturday→Friday mapping).
