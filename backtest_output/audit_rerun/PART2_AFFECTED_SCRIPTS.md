# Part 2: Affected Scripts Identification

**Date:** 2026-03-24
**Scope:** All Python scripts in the repo that reference `_m5_regsess.csv`

---

## Critical Discovery: Daily Aggregation Is Also Broken

Scripts that only use daily Open/Close (first/last bar) were initially classified "SAFE." **This was wrong.** The buggy `_m5_regsess.csv` files have:
- **First bar (09:30):** from ET block — approximately correct (minor rounding vs IST block)
- **Last bar (15:55):** from IST block — **WRONG** (IST pre-market ≈ 08:55 ET, not 15:55 ET)

Daily Close impact: **AAPL avg $2.43 error, TSLA avg $7.81 error** per day. This means ALL scripts using these files are affected, even daily-aggregation ones.

---

## Full Scan Results

### Scripts That Read `_m5_regsess.csv`

| # | Script | Series | Timing-Sensitive | Times Used | Verdict |
|---|--------|--------|:----------------:|-----------|:-------:|
| 1 | `audit_a1_volume_jshape.py` | A1 | Yes | 13 half-hour windows | **AFFECTED** |
| 2 | `audit_a2_power_hour.py` | A2 | Yes | Zone boundaries: 12:00, 13:30, 14:45 | **AFFECTED** |
| 3 | `audit_a3_phantom_lc.py` | A3 | Yes | 10:45, 11:15, 11:45, 12:15 windows | **AFFECTED** |
| 4 | `audit_b1_gap_fill.py` | B1 | No (daily) | First/last bar → wrong Close | **AFFECTED** |
| 5 | `audit_b3_range.py` | B3 | No (daily) | First/last bar → wrong Close | **AFFECTED** |
| 6 | `audit_c1_opening_spike.py` | C1 | Yes | hour==9 (correct), but day H/L wrong | **AFFECTED** |
| 7 | `audit_d1_ce_mult.py` | D1 | Yes | 13:30, 09:30 entry; 15:50 exit | **AFFECTED** |
| 8 | `audit_d2_clock_stop.py` | D2 | Yes | 13:30, 09:30 entry; 15:50 exit | **AFFECTED** |
| 9 | `audit_d3_time_partial.py` | D3 | Yes | Entry + T min elapsed; 15:50 exit | **AFFECTED** |
| 10 | `audit_e3_adx_ema.py` | E3 | No (daily) | Daily OHLC agg → wrong Close | **AFFECTED** |
| 11 | `audit_ema_4h_crosses.py` | EMA | Yes | 13:30 split for 4H bars | **AFFECTED** |
| 12 | `audit_f2_coin_banks.py` | F2 | No (daily) | First O / last C → wrong Close | **AFFECTED** |
| 13 | `audit_f3_deadzone_bottom.py` | F3 | Yes | 12:00–13:30 DZ, 14:45–16:00 PH | **AFFECTED** |
| 14 | `audit_g1_vix_regression.py` | G1 | No (daily) | SPY first O / last C → wrong Close | **AFFECTED** |
| 15 | `audit_g2_regime.py` | G2 | Yes | 12:00–13:30 DZ, 14:45–16:00 PH | **AFFECTED** |
| 16 | `audit_h1_exit_grid.py` | H1 | Yes | 12:00 entry; 14:30–15:45 exits | **AFFECTED** |
| 17 | `audit_h2_nonstress.py` | H2 | Yes | 09:30, 12:00, 15:30 | **AFFECTED** |
| 18 | `indicators/compute_indicators.py` | — | No (all bars) | EMA/RSI/ADX on all bars | **AFFECTED** |
| 19 | `s21_p1_noon_stress.py` | S21-P1 | Yes | 09:30, 12:00 | **AFFECTED** |
| 20 | `s21_p2_executable_pnl.py` | S21-P2 | Yes | 09:30, 12:30, 15:50 | **AFFECTED** |
| 21 | `s21_p3_time_grid.py` | S21-P3 | Yes | 6×6 entry/exit grid | **AFFECTED** |
| 22 | `s21_p4_defense_interaction.py` | S21-P4 | Yes | 09:30, 12:00, 12:30 | **AFFECTED** |
| 23 | `s21_p5_placebo_test.py` | S21-P5 | Yes | 12:00 classification | **AFFECTED** |
| 24 | `s21_p8_mae_mfe.py` | S21-P8 | Yes | 09:30 entry, 15:50 exit, all bars | **AFFECTED** |
| 25 | `s21_p9_nonstress_pnl.py` | S21-P9 | Yes | 12:30 entry, 15:50 exit | **AFFECTED** |
| 26 | `s21_p10_threshold_robustness.py` | S21-P10 | Yes | 12:00 threshold | **AFFECTED** |
| 27 | `phase2_test2_3_4.py` | Phase2 | Yes | 09:30, 12:00, 12:30, 15:55 | **AFFECTED** |
| 28 | `phase3_test5_6_7_8_9.py` | Phase3 | Yes | 09:30, 12:00, 12:30, 15:55 | **AFFECTED** |

### Scripts That Do NOT Read `_m5_regsess.csv`

| # | Script | Series | Data Source | Verdict |
|---|--------|--------|-----------|:-------:|
| 29 | `audit_c2_width_breakout.py` | C2 | `Fetched_Data/_data.csv` with explicit `in_regsess()` filter | **REVIEW** |
| 30 | `audit_c3_false_breakout.py` | C3 | `Fetched_Data/_data.csv` | **REVIEW** |
| 31 | `audit_b2_timing.py` | B2 | Needs confirmation | **REVIEW** |
| 32 | `audit_f1_btc_eth_lag.py` | F1 | Crypto data | **SAFE** |
| 33 | Series I (I1–I9) | I-series | `Fetched_Data/` with IST≥16:35 | **SAFE** |

---

## Summary Counts

| Verdict | Count | Scripts |
|---------|:-----:|---------|
| **AFFECTED** | **28** | All 28 scripts reading _m5_regsess.csv |
| **REVIEW** | **3** | C2, C3, B2 (different data source, need manual check) |
| **SAFE** | **2** | F1 (crypto), Series I (correct IST filter) |

---

## Prioritized Re-Run List

### Priority 1: CRITICAL — Active Trading Decisions

| Script | Test | Impact | Why Critical |
|--------|------|--------|-------------|
| `audit_h1_exit_grid.py` | H1 | Exit time optimization | Drives 15:30 vs other exit times |
| `audit_h2_nonstress.py` | H2 | Noon reversal P&L | Already confirmed wrong by I8 |
| `s21_p1_noon_stress.py` | S21-P1 | Stress identification | Foundation for all S21 |
| `s21_p2_executable_pnl.py` | S21-P2 | Executable P&L | Actual paper-trade expectations |
| `s21_p9_nonstress_pnl.py` | S21-P9 | Non-stress P&L | Key S21 result |
| `phase2_test2_3_4.py` | Phase2 | Forward returns | Drives strategy design |
| `phase3_test5_6_7_8_9.py` | Phase3 | Full backtest | Drives strategy parameters |

### Priority 2: HIGH — Architecture Decisions

| Script | Test | Impact | Why High |
|--------|------|--------|---------|
| `audit_ema_4h_crosses.py` | EMA | 4H bar construction | EMA9/21 gate depends on this |
| `audit_e3_adx_ema.py` | E3 | ADX daily values | Drives TQS scoring if used |
| `indicators/compute_indicators.py` | — | All indicators | Foundation for E-series |
| `s21_p3_time_grid.py` | S21-P3 | Entry/exit time grid | Drives optimal timing |
| `s21_p4_defense_interaction.py` | S21-P4 | Defense rank | Drives filtering rules |
| `s21_p8_mae_mfe.py` | S21-P8 | MAE/MFE risk | Drives stop-loss sizing |

### Priority 3: MEDIUM — Zone & Pattern Analysis

| Script | Test | Impact |
|--------|------|--------|
| `audit_a2_power_hour.py` | A2 | Zone absolute return profiles |
| `audit_a1_volume_jshape.py` | A1 | Intraday volume shape |
| `audit_f3_deadzone_bottom.py` | F3 | Dead zone analysis |
| `audit_g2_regime.py` | G2 | VIX regime intraday characteristics |
| `audit_d1_ce_mult.py` | D1 | Chandelier exit optimization |
| `audit_d2_clock_stop.py` | D2 | Clock stop timing |
| `audit_d3_time_partial.py` | D3 | Partial exit timing |

### Priority 4: LOWER — Supporting Analysis

| Script | Test | Impact |
|--------|------|--------|
| `audit_a3_phantom_lc.py` | A3 | Phantom London Close |
| `audit_b1_gap_fill.py` | B1 | Gap fill rates (daily agg wrong) |
| `audit_b3_range.py` | B3 | Range classification (daily agg wrong) |
| `audit_c1_opening_spike.py` | C1 | Opening extreme (09:30 OK, day H/L wrong) |
| `audit_f2_coin_banks.py` | F2 | COIN/banks correlation (daily agg wrong) |
| `audit_g1_vix_regression.py` | G1 | VIX regression (SPY daily wrong) |
| `s21_p5_placebo_test.py` | S21-P5 | Placebo/null test |
| `s21_p10_threshold_robustness.py` | S21-P10 | Threshold robustness |

---

## What Part 3 Needs To Do

For each AFFECTED script:
1. Replace `_m5_regsess.csv` reads with `load_m5_regsess()` from `utils/data_loader.py` (or read `_FIXED.csv`)
2. Re-run and capture new results
3. Compare old vs new: `| Test | Old Result | New Result | Changed? |`
4. Update CONSOLIDATED_REPORT.md with corrected verdicts

**Estimated re-run effort:** ~28 scripts, ~2–4 hours of compute time, manual comparison for each.
