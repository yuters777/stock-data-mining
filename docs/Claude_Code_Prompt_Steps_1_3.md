# CLAUDE CODE — Phase 2.1 Startup Prompt

## CONTEXT

You are building a backtester for the False Breakout Trading System (Gerchik methodology).

**Repository:** `stock-data-mining` (GitHub, already has `level_detection/` from Phase 1)
**Data source:** `yuters777/MarketPatterns-AI` (private GitHub repo, access via `GITHUB_TOKEN` env var)
**Specification:** L-005.1 (see KB files in project)

### Key KB Documents (read before coding):
1. **Backtester_Architecture_v1.md** — module interfaces, data contracts, build order, DEFAULT_CONFIG
2. **Data_Request_v2.md** — CSV format, session mapping, IST timezone, Saturday bars, validation checks
3. **FalseBreakout_Spec_L005_1.md** — full strategy rules (SSOT)

---

## TASK: Steps 1-3 (Foundation)

Build the first 3 modules of the backtester in order:

### Step 1: `backtester/data_types.py` + `backtester/config.py`

**data_types.py** — All dataclasses from Backtester_Architecture_v1.md §3:
- `Bar` (OHLCV + symbol + timestamp + timeframe)
- `Level` (price + type + status + score + mirror tracking + confirmed_at)
- `Signal` (pattern + direction + level + filter_results + risk sizing)
- `Trade` (entry/exit + stops + P&L + sector)
- `EquitySnapshot` (cash + unrealized + drawdown)
- All enums: `LevelType`, `LevelStatus`, `PatternType`, `SignalDirection`, `LP2Quality`, `SignalStatus`, `TradeStatus`

**config.py** — `DEFAULT_CONFIG` dict from Architecture_v1.md §7 (all ~60 parameters from L-005.1 §9). Plus `load_config(path)` and `validate_config(config)` functions.

**Tests:** Instantiation of all dataclasses, config loading, config validation (missing keys → error).

### Step 2: `backtester/data_loader.py`

Load M5 data from MarketPatterns-AI CSVs and prepare for backtester.

**Input:** Individual CSV files per ticker (`{TICKER}_data.csv`)
**Format:** `Datetime,Open,High,Low,Close,Volume,Ticker` — IST timezone, timezone-naive

**Must implement (per Data_Request_v2.md §5):**

1. `load_m5(ticker, data_dir) → DataFrame` — Read CSV, parse dates, validate
2. `assign_trading_day(dt) → date` — Saturday IST 00:00-02:55 → Friday
3. `tag_session(dt) → str` — PRE_MARKET / REGULAR / POST_MARKET based on IST hour:
   - Pre-market: 11:00–16:25 IST
   - Regular: 16:30–22:55 IST (includes 23:00 close bar)
   - Post-market: 23:05+ and 00:00–02:55 IST
4. `aggregate_d1(m5_df) → DataFrame` — Regular session bars only → daily OHLCV
5. `validate_data(df)` — NULL check, OHLC consistency, volume >= 0, chronological order, no duplicates
6. `load_all_tickers(data_dir) → dict[str, DataFrame]` — Load all 9 tickers
7. `prepare_backtester_data(data_dir, output_dir)` — Full pipeline: load → validate → tag → aggregate → save parquet + metadata.json + data_quality_report.json

**CRITICAL RULES:**
- NO timezone conversion. Data stays in IST.
- Saturday bars → Friday's trading day
- D1 aggregation = regular session ONLY
- All M5 bars kept (time filters are configurable parameters, applied later by filter_chain)

**Tests:**
- Load NVDA_data.csv, verify 49,620 rows
- Saturday bar mapping (bar at 2025-02-15 00:30 → trading_day = 2025-02-14)
- Session tagging (16:30 = REGULAR, 11:00 = PRE_MARKET, 01:00 = POST_MARKET)
- D1 aggregation produces ~260 trading days from ~315 calendar days
- Validation catches: NULL injection, High < Low, duplicate timestamp

### Step 3: `backtester/atr.py`

Modified ATR calculation per L-005.1 §4.1.

**Must implement:**

1. `true_range(bar, prev_bar) → float` — Standard TR = max(H-L, |H-Cprev|, |L-Cprev|)
2. `modified_atr(bars, period=5) → float` — SMA of TR, excluding bars where:
   - TR > 2.0 × ATR_prev (paranormal)
   - TR < 0.5 × ATR_prev (dead)
3. `calc_exhaustion(level_price, direction, session_bars, atr_d1) → float` — ATR exhaustion % at decision time:
   - SHORT from resistance: (level - low_so_far) / atr_d1
   - LONG from support: (high_so_far - level) / atr_d1
   - Uses low_so_far / high_so_far at DECISION TIME (no full-day lookahead)
4. `is_paranormal(bar, atr) → bool` — bar.range >= 2.0 × ATR

**Tests:**
- Modified ATR with known values (hand-calculated)
- Paranormal exclusion: inject a 3× ATR bar, verify it's excluded from next ATR calc
- Exhaustion: known level at $100, low_so_far = $97, ATR_D1 = $4 → exhaustion = 75%
- Edge cases: all bars excluded → fallback to unfiltered ATR

---

## FILE STRUCTURE

Create under `stock-data-mining/`:
```
backtester/
├── __init__.py
├── data_types.py      # Step 1
├── config.py          # Step 1
├── data_loader.py     # Step 2
└── atr.py             # Step 3

tests/
├── test_data_types.py
├── test_config.py
├── test_data_loader.py
├── test_atr.py
└── fixtures/
    └── (sample data for tests)
```

---

## DATA ACCESS

To fetch data from MarketPatterns-AI:
```python
import requests
from io import StringIO
import os

token = os.getenv('GITHUB_TOKEN')
repo = "yuters777/MarketPatterns-AI"
url = f"https://raw.githubusercontent.com/{repo}/main/Fetched_Data/{ticker}_data.csv"
headers = {"Authorization": f"token {token}"}
response = requests.get(url, headers=headers)
df = pd.read_csv(StringIO(response.text), parse_dates=['Datetime'])
```

**Tickers:** AAPL, MSFT, NVDA, TSLA, META, COIN, BABA, GOOGL, AMZN

---

## DESIGN PRINCIPLES

1. **No lookahead** — all data access bounded by current_bar_idx
2. **Deterministic** — same data + same params = identical results
3. **Observable** — every decision logged with reason code
4. **Test-first** — write tests before or alongside implementation
5. **Spec-driven** — reference L-005.1 sections in docstrings

---

## WHEN DONE

Report:
- Files created (with line counts)
- Tests run (pass/fail count)
- Data quality summary (if data was loaded)
- Any issues or questions for next steps (Step 4: level_detector.py)
