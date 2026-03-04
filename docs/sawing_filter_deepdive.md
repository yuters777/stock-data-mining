# Sawing Filter Deep-Dive Report

## Executive Summary

**Initial hypothesis:** Sawing kills 95% of levels (124/131 with FD=5).
**Actual finding:** Only 22% killed by sawing. **Nison invalidation kills 97%.**

The 95% figure was a measurement error — the earlier experiment counted ALL invalidated levels (sawing + Nison) as "sawed". After proper attribution:

| Kill Source | Levels | % |
|---|---|---|
| Nison invalidation | 114 | 77.6% |
| Sawing (cross-count) | 32 | 21.8% |
| Still active | 1 | 0.7% |
| **Total** | **147** | |

However, a real **bug** was found and fixed in the sawing logic.

---

## Bug Found: Pre-Creation Crosses

### The Problem

`check_anti_sawing()` used a sliding window of the last N D1 bars before `current_date`, **without filtering out bars before the level was created**. This meant:

- A level confirmed at bar N with `cross_count_window=20` would examine bars N-20 through N
- Bars N-20 through N-1 are **before the level existed**
- Price oscillating around a fractal pivot is **inherent to fractal formation** — that's what MAKES it a fractal
- These natural pre-creation oscillations were being counted as "sawing"

### Evidence

**9 out of 147 levels (6.1%) were killed immediately at confirmation (day 0)**, all by pre-creation crosses:

| Level | Ticker | Price | Pre-Creation Crosses | Post-Creation Crosses |
|---|---|---|---|---|
| 1 | AMZN | $246.77 | 4 | 0 |
| 2 | GOOGL | $165.08 | 3 | 0 |
| 3 | MSFT | $531.82 | 4 | 0 |
| 4 | NVDA | $122.89 | 3 | 0 |
| 5 | GOOGL | $187.82 | 3 | 0 |

Every one killed **entirely** by pre-creation crosses. Zero post-creation crosses.

### The Fix

Changed `check_anti_sawing()` in `level_detector.py:351` to only count bars **after** `level.confirmed_at`:

```python
# Before (bug):
date_mask = idx['dates'] <= np.datetime64(current_date)

# After (fix):
level_start = level.confirmed_at if level.confirmed_at else level.date
date_mask = (idx['dates'] >= level_start_np) & (idx['dates'] <= np.datetime64(current_date))
```

### Impact of Fix

| Config | Metric | Before Fix | After Fix |
|---|---|---|---|
| FD=10, ATR=0.80/0.30 (baseline) | Trades | 8 | 8 (unchanged) |
| FD=10, ATR=0.70/0.25 | Trades | 12 | 12 (unchanged) |
| FD=5, ATR=0.70/0.25 | Trades | 17 | 18 (+1) |
| FD=5, day-0 kills | Count | 9 | 0 |

The fix has minimal impact on FD=10 (levels are confirmed later, so fewer pre-creation bars in window) but correctly eliminates all false day-0 kills.

---

## Cross-Counting Logic Review

### What the code does correctly:
1. **CLOSE-only crosses** — only `Close` price is checked, not wicks (High/Low) ✓
2. **Side-change detection** — tracks `prev_side` / `current_side`, counts transitions ✓
3. **Tolerance neutral zone** — closes within `[price-tol, price+tol]` are skipped, `prev_side` unchanged ✓
4. **Edge case: $150.05 approaching $150.00 level** — within $0.05 tolerance → NEUTRAL, not a cross ✓

### What was wrong (now fixed):
- Pre-creation bars in the window counted as crosses ✗ → Fixed ✓

### Spec compliance (L-005.1 §2.5):
> "CrossCount = COUNT(bars WHERE Close crosses Level, period=20)"
> "Crosses" means close was on one side, now close is on the other side.

- Close-only: ✓
- Side-change (not proximity): ✓
- Window period: ✓
- Post-creation only: ✓ (after fix)

---

## The Real Bottleneck: Nison Invalidation

With sawing disabled entirely (`cross_count_invalidate=999`):
- 143 of 147 levels (97.3%) are killed by Nison invalidation
- Only 4 levels survive to end of data

This means Nison invalidation is far more aggressive than sawing. If trade count is the goal, Nison parameters (or logic) deserve investigation next.
