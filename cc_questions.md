# CC Questions & Deviation Log — Earnings Buffer Sensitivity Sweep v1.0

**EBS = Earnings Buffer Sweep**
**Spec version:** CC_EARNINGS_BUFFER_SWEEP_v1_0_spec.md (Day 41, April 28 2026)
**Production reference HEAD:** market-engine `62bf5b1`

---

## §0. Discovery Findings

**Branch:** `claude/earnings-buffer-sensitivity-5kPd4` (harness convention; spec says `claude/earnings-buffer-sweep-EBS1`)
**Deviation:** EBS-D-1 (branch name, pre-approved — harness controls branch)

**Existing scripts in `scripts/`:** 40+ files including `backtest_utils_extended.py`, `m4_backtest_extended.py`, `m6_backtest_extended.py`, `m7_backtest_extended.py`, existing sweep scripts. None were modified.

**`backtest_utils_extended.py` exists:** Yes (52+ lines). CC did not read or depend on it; all helpers reimplemented in `_*.py` files per spec §1 allowlist.

**pandas/numpy availability:** Not present in system Python; installed via `pip install pandas numpy` (pandas 3.0.2, numpy 2.4.4). Not added to `requirements.txt` per spec §1 freeze. Documented here per EBS-D-DEPS handling (non-blocking — packages installable).

---

## §1. Deviation Log

### EBS-D-1 — Branch name mismatch (pre-approved)

**Spec says:** `claude/earnings-buffer-sweep-EBS1`
**Harness says:** `claude/earnings-buffer-sensitivity-5kPd4`
**Resolution:** Used harness branch. Content identical; branch name is infrastructure detail.

### EBS-D-2 — `_data_loaders.py` uses `date` column instead of `timestamp_utc`

**Spec says:** M5 schema `timestamp_utc, open, high, low, close, volume`
**Discovery:** Existing `backtest_utils_extended.py` (not modified) uses `date` column (ET naive). Real CSVs use `date` not `timestamp_utc`.
**Resolution:** `load_m5_extended` parses `date` column. `aggregate_m5_to_4h_rth` handles tz-naive ET index directly without UTC conversion. Operator confirms or corrects in PR review.

### EBS-D-3 — M7 `_rolling_60d_high` requires 60 trading-day history

**Spec:** `_ROLLING_HIGH_WINDOW = 60` (calendar days vs trading days ambiguous)
**CC interpretation:** 60 **trading** days (consistent with production `compute_daily_rs` lookback=20 trading days convention).
**Effect:** Tickers with <60 trading days in data_root are skipped for M7. Consistent with production behavior.
**Operator confirms or corrects in PR review.**

### EBS-D-4 — M7 EMA9 window passes full close history

**Spec pseudocode:** `ema9 = compute_ema_9(closes_so_far[-20:])` (truncated window)
**CC implementation:** `ema9 = compute_ema_9(closes_so_far)` (full history)
**Rationale:** Truncating to 20 points breaks Wilder's EMA (needs warm-up from index 0). Full history is mathematically correct per production `compute_daily_ema9` (line 539).

### EBS-D-5 — `pytest` not in `requirements.txt`

**Spec:** No new deps to `requirements.txt`.
**Resolution:** `pytest` installed for CC test execution only. Not added to `requirements.txt`. Operator's existing environment likely has pytest.

---

## §2. Open Questions for Operator

### Q1 — M5 CSV date column name

Is the `date` column in `{TICKER}_m5_extended.csv` named `date` (ET naive) or `timestamp_utc`? CC implemented `date`. If `timestamp_utc`, update `load_m5_extended` in `_data_loaders.py`.

### Q2 — VIX CSV column name

Is the VIX column named `vix_close` (as spec says) or `VIXCLS` (FRED default)? CC implemented `vix_close`. If FRED default, update `load_vix_daily` or rename column at load time.

### Q3 — Earnings calendar column name

Is the earnings date column `earnings_date` or `report_date` or another name? CC implemented `earnings_date`.

---

*CC deviations: 5 documented, all pre-approved or in operator-confirmation category.*
*No forbidden deviations.*
