# I9: Data Source Audit & Pipeline Bug Assessment

## FIRST QUESTION: What Files Did Series I Use?

### 1. File Paths

All Series I scripts (I1–I7, I8) loaded data from:
```
/home/user/stock-data-mining/Fetched_Data/{TICKER}_data.csv
```
**NOT** from `backtest_output/{TICKER}_m5_regsess.csv` (the processed files with the bug).

### 2. First 5 Lines (AAPL example)

```csv
Datetime,Open,High,Low,Close,Volume,Ticker
2025-02-03 04:00:00,231.5398,232.3455,228.2774,230.4457,36382,AAPL
2025-02-03 04:05:00,230.3661,230.4557,230.0578,230.2468,11646,AAPL
2025-02-03 04:10:00,230.207,230.3661,230.0578,230.3463,8219,AAPL
2025-02-03 04:15:00,230.3562,230.386,230.0578,230.0578,8634,AAPL
```

### 3. Timezone

The raw CSVs contain **TWO overlapping blocks** of bars per trading day:

| Block | Timestamp Range | What It Is | Example (AAPL 2025-02-03) |
|-------|:---------------:|-----------|---------------------------|
| **ET block** | 04:00–10:55 | Original Alpha Vantage US/Eastern timestamps | 09:30 → Open=228.75, Vol=4,885,170 |
| **IST block** | 11:00–23:55 | Same bars + extended hours, shifted +7h | 16:30 → Open=228.75, Vol=4,885,170 |

The IST block was created by `fetch_SP500_Data.py` line ~1350:
```python
processed_df['Datetime'] = processed_df['Datetime'] + pd.Timedelta(hours=7)
```

### 4. Duplicate Bars

**Yes — bars from 09:30–10:55 ET are duplicated at 16:30–17:55 IST** (identical OHLCV, different timestamps).

Proof (AAPL 2025-02-03):
```
09:30:00  Open=228.7548  Vol=4,885,170  ← ET block (market open)
16:30:00  Open=228.75    Vol=4,885,170  ← IST block (same bar, +7h)
```

The IST block also contains additional bars NOT in the ET block:
- 11:00–16:25 IST = pre-market bars (ET ~04:00–09:25, duplicated from ET block)
- **16:30–22:55 IST = regular session** (the CORRECT bars for 09:30–15:55 ET)
- 23:00–23:55 IST = post-market

---

## How Series I Handled This

### The Filter (used in ALL I1–I7 scripts)

```python
mins = df["Datetime"].apply(ist_minutes)  # hour*60 + minute
mask = (mins >= 16 * 60 + 35) & (mins <= 22 * 60 + 55)  # 16:35–22:55 IST
df = df[mask].copy()
```

This filter:
- **EXCLUDES** the entire ET block (04:00–10:55) ✓
- **EXCLUDES** IST pre-market (11:00–16:25) ✓
- **EXCLUDES** the first regular bar at 16:30 IST (per spec: exclude first bar) ✓
- **CAPTURES** only 16:35–22:55 IST = 09:35–15:55 ET ✓

### Zone Mapping (IST → ET)

| Zone | IST Range | ET Range | Verified Bar (AAPL 2025-02-03) |
|------|:---------:|:--------:|-------------------------------|
| Zone 2 | 17:00–18:55 | 10:00–11:55 | 17:00 IST: Open=227.58, Vol=1,472,446 ✓ |
| Zone 3 (DZ) | 19:00–20:25 | 12:00–13:25 | 19:00 IST: Open=225.15, Vol=524,833 ✓ |
| Exit (15:30) | 22:30 | 15:30 | 22:30 IST: Open=227.34, Vol=792,989 ✓ |

All volumes are 100K–5M (regular session). No pre-market bars (vol ~5K–30K) were included.

### I8 Specifically

I8 used `mins >= 16*60+30` (inclusive of 16:30, the open bar) because it needed the 09:30 ET open price for AM return calculation. The noon entry at 19:00 IST = 12:00 ET and exit at 22:30 IST = 15:30 ET are both correct regular-session bars.

---

## Impact Assessment: Series I (I1–I8)

| Test | Data Source | Filter | Times Used | Correct? | Status |
|------|-----------|--------|-----------|:--------:|--------|
| **I1** | Fetched_Data/ raw | IST ≥16:35 | Z2 (17:00–18:55), Z3 (19:00–20:25) | **✓** | UNAFFECTED |
| **I2** | Fetched_Data/ raw | IST ≥16:35 | Z2, Z3, EOD (22:55) | **✓** | UNAFFECTED |
| **I3** | Fetched_Data/ raw | IST ≥16:35 | Z2, Z3, activity 19:00–22:55 | **✓** | UNAFFECTED |
| **I4** | Uses I2 output CSV | — | Inherits from I2 | **✓** | UNAFFECTED |
| **I5** | Fetched_Data/ raw + I4 CSV | IST ≥16:35 | Exit 22:30 IST | **✓** | UNAFFECTED |
| **I6a** | Fetched_Data/ raw + I4 CSV | IST ≥16:35 | DZ bars, exit 22:30 | **✓** | UNAFFECTED |
| **I6bc** | Fetched_Data/ raw + I6a CSV | IST ≥16:35 | MAE/MFE bars to 22:30 | **✓** | UNAFFECTED |
| **I6def** | Uses I6bc CSV | — | Inherits from I6bc | **✓** | UNAFFECTED |
| **I7a** | Fetched_Data/ raw + I4 CSV | IST ≥16:30 | DZ bars 19:00–20:30, exit 22:30 | **✓** | UNAFFECTED |
| **I7b** | Uses I7a output | — | Inherits from I7a | **✓** | UNAFFECTED |
| **I8** | Fetched_Data/ raw | IST ≥16:30 | Open 16:30, noon 19:00, exit 22:30 | **✓** | UNAFFECTED |

**ALL Series I tests used correct data.** No re-runs needed.

---

## Impact Assessment: Prior Audits & Phase Scripts

### The `_m5_regsess.csv` Bug

**Root cause:** `phase1_test0_test1.py` lines 35–42:
```python
t = df["Datetime"].dt.time
mask = (t >= pd.Timestamp("09:30").time()) & (t <= pd.Timestamp("15:55").time())
filtered[tk] = df[mask].copy()
```

This filters raw CSV by timestamp range `09:30–15:55`, which captures:
- **09:30–10:55** from the ET block → **CORRECT** regular session bars
- **11:00–15:55** from the IST block → **WRONG** (IST pre-market = ET ~04:00–08:55)

Bars at 12:00 in processed file = 12:00 IST = ~05:00 ET pre-market (Vol ~5K), NOT actual noon (Vol ~500K).

### AFFECTED Scripts (use `_m5_regsess.csv` AND access bars after 10:55 ET)

| Script | Severity | What's Wrong |
|--------|----------|-------------|
| **audit_h2_nonstress.py** | **CRITICAL** | Entry at "12:00 ET" is pre-market bar. H2 result (+1.11%) invalid. |
| **audit_h1_exit_grid.py** | **CRITICAL** | Exit times 14:30–15:45 all use wrong bars. Exit optimization invalid. |
| **audit_a2_power_hour.py** | **HIGH** | Power hour (14:45–16:00) analysis uses wrong bars. |
| **audit_f3_deadzone_bottom.py** | **HIGH** | Dead Zone analysis uses wrong noon bars. |
| **audit_d1_ce_mult.py** | **MEDIUM** | Chandelier exit may use wrong bars for afternoon. |
| **audit_d2_clock_stop.py** | **MEDIUM** | Clock-based stop uses wrong afternoon bars. |
| **audit_d3_time_partial.py** | **MEDIUM** | Time-based partial exit uses wrong afternoon bars. |
| **audit_e3_adx_ema.py** | **MEDIUM** | ADX/EMA computed on wrong afternoon data. |
| **audit_g2_regime.py** | **MEDIUM** | Regime analysis may use wrong afternoon bars. |
| **audit_a1_volume_jshape.py** | **LOW** | Volume J-shape may be distorted for afternoon. |
| **audit_c1_opening_spike.py** | **LOW** | Opening spike likely uses only early bars (may be OK). |
| **s21_p1 through s21_p10** | **CRITICAL** | All S21 Phase scripts use wrong noon/afternoon bars. |
| **phase2_test2_3_4.py** | **HIGH** | Phase 2 tests use wrong afternoon data. |
| **phase3_test5_6_7_8_9.py** | **HIGH** | Phase 3 tests use wrong afternoon data. |

### LIKELY UNAFFECTED (use `_m5_regsess.csv` but only early bars)

| Script | Reason |
|--------|--------|
| audit_b1_gap_fill.py | Gap fill analysis uses opening bars (09:30–10:00). |
| audit_b3_range.py | Range analysis likely uses first-hour bars. |
| audit_f2_coin_banks.py | Cross-asset correlation likely uses daily data. |
| audit_g1_vix_regression.py | VIX regression uses daily returns, not intraday bars. |
| audit_a3_phantom_lc.py | Phantom level detection likely uses early bars. |

### NOT AFFECTED (use raw data or daily data)

| Script | Reason |
|--------|--------|
| **All Series I (I1–I8)** | Use `Fetched_Data/` raw with IST ≥16:30 filter. |
| audit_f1_btc_eth_lag.py | Uses crypto data directly. |
| audit_ema_4h_crosses.py | Uses raw Fetched_Data. |
| backtester/ scripts | Use `data_loader.py` with IST session tagging. |

---

## Pipeline Bug: Root Cause & Fix

### Root Cause

The Alpha Vantage fetcher (`MarketPatterns_AI/fetch_SP500_Data.py`) appends IST-shifted bars to the same CSV without removing the original ET bars. This creates a file with **two copies of each bar** (ET and IST timestamps) for the overlap period.

The `_m5_regsess.csv` generator (`phase1_test0_test1.py`) then filters by `09:30 ≤ time ≤ 15:55`, which accidentally captures IST pre-market bars (11:00–15:55 IST) instead of the IST regular session bars (16:30–22:55 IST).

### Fix (for `phase1_test0_test1.py`)

Replace:
```python
t = df["Datetime"].dt.time
mask = (t >= pd.Timestamp("09:30").time()) & (t <= pd.Timestamp("15:55").time())
```

With:
```python
# Use IST regular session block (16:30-22:55), then convert to ET
t_min = df["Datetime"].dt.hour * 60 + df["Datetime"].dt.minute
mask = (t_min >= 16*60+30) & (t_min <= 22*60+55)
df_reg = df[mask].copy()
df_reg["Datetime"] = df_reg["Datetime"] - pd.Timedelta(hours=7)  # IST → ET
```

Or alternatively, deduplicate the raw CSV first by keeping only bars where volume matches regular session levels.

---

## Tests Needing Re-Run

### NONE for Series I — all I1–I8 results stand as published.

### For prior audits (outside Series I scope but flagged):

**CRITICAL re-runs needed:**
1. `audit_h1_exit_grid.py` — exit time optimization
2. `audit_h2_nonstress.py` — noon reversal P&L (confirmed invalid in I8)
3. All `s21_p*.py` scripts — S21 Phase results
4. `phase2_test2_3_4.py` and `phase3_test5_6_7_8_9.py`

**HIGH priority re-runs:**
5. `audit_a2_power_hour.py` — power hour analysis
6. `audit_f3_deadzone_bottom.py` — dead zone bottom
7. `audit_d1_ce_mult.py`, `audit_d3_time_partial.py` — exit mechanics

---

## Summary

| Question | Answer |
|----------|--------|
| **Series I data correct?** | **YES** — all I1–I8 used raw `Fetched_Data/` with correct IST→ET filter |
| **Duplicate bars in analysis?** | **NO** — filter `≥16:35 IST` excludes entire ET block and IST pre-market |
| **`_m5_regsess.csv` bug real?** | **YES** — bars after 10:55 ET are IST pre-market, not regular session |
| **How many prior scripts affected?** | **~20 scripts** (10 audit, 8 s21, 2 phase) |
| **Series I re-runs needed?** | **NONE** |
| **I8 H2 finding confirmed?** | **YES** — H2's +1.11% was computed on wrong data. Correct result: +0.073% |
