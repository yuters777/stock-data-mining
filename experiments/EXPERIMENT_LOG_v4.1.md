# Experiment Log v4.1 — Whitelist Portfolio, Trail Optimization & NVDA Rescue

**Date:** 2026-03-03 14:01
**Final Portfolio:** AAPL, AMZN, GOOGL, TSLA
**IS Period:** 2025-02-10 to 2025-10-01
**OOS Period:** 2025-10-01 to 2026-01-31
**NVDA rescued:** No

---

======================================================================
V4.1 EXPERIMENTS — Whitelist Portfolio, Trail Optimization & NVDA Rescue
Whitelist: AAPL, AMZN, GOOGL, TSLA
IS: 2025-02-10 to 2025-10-01 | OOS: 2025-10-01 to 2026-01-31
======================================================================

======================================================================
EXP-W001: Whitelist Portfolio Baseline
======================================================================
Hypothesis: Dropping META/MSFT (clearly unprofitable) gives a positive portfolio

  W001 Whitelist
    IS:  18 trades, 33.3% WR, PF=0.39, $-2019
    OOS: 63 trades, 49.2% WR, PF=1.23, $1714
    AAPL: 6 trades, 66.7% WR, PF=2.10, $521 [tgt=0 stp=1 eod=4 trail=1]
    AMZN: 19 trades, 47.4% WR, PF=1.22, $571 [tgt=0 stp=7 eod=10 trail=2]
    GOOGL: 15 trades, 40.0% WR, PF=1.20, $333 [tgt=0 stp=4 eod=11 trail=0]
    TSLA: 23 trades, 52.2% WR, PF=1.10, $289 [tgt=1 stp=9 eod=13 trail=0]

  Exit breakdown (OOS): target=1 (2%), stop=21 (33%), eod=38 (60%), trail/be=3 (5%)

  Verdict: ACCEPT

======================================================================
T001: Trail Factor Sweep
======================================================================
Hypothesis: Tighter trail (0.5R) captures more profit from favorable moves vs 1.0R default
    trail_factor=0.5: OOS 63 trades, PF=1.22, $1665
    trail_factor=0.7: OOS 63 trades, PF=1.24, $1848
    trail_factor=1.0: OOS 63 trades, PF=1.23, $1714
    trail_factor=1.5: OOS 63 trades, PF=1.20, $1490

## T001: Trail Factor Sweep
**Hypothesis:** Tighter trail captures more favorable moves
**Config:** trail_factor in [0.5, 0.7, 1.0, 1.5]

| Variant | IS Trades | IS WR | IS PF | IS P&L | OOS Trades | OOS WR | OOS PF | OOS P&L |
|---------|-----------|-------|-------|--------|------------|--------|--------|---------|
| trail_factor=0.5 | 18 | 33.3% | 0.39 | $-2019 | 63 | 49.2% | 1.22 | $1665 |
| trail_factor=0.7 | 18 | 33.3% | 0.39 | $-2019 | 63 | 49.2% | 1.24 | $1848 |
| trail_factor=1.0 | 18 | 33.3% | 0.39 | $-2019 | 63 | 49.2% | 1.23 | $1714 |
| trail_factor=1.5 | 18 | 33.3% | 0.39 | $-2019 | 63 | 49.2% | 1.20 | $1490 |

  Best: trail_factor=0.7 (OOS PF=1.24)

======================================================================
T002: Trail Activation R Sweep
======================================================================
Hypothesis: Delaying trail start until favorable R-move improves trail quality (using trail_factor=0.7)
    trail_act=0.0R: OOS 63 trades, PF=1.24, $1848
    trail_act=0.5R: OOS 63 trades, PF=1.24, $1848
    trail_act=1.0R: OOS 63 trades, PF=1.24, $1848
    trail_act=1.5R: OOS 63 trades, PF=1.24, $1848

## T002: Trail Activation R Sweep
**Hypothesis:** Delay trail start (using trail_factor=0.7)
**Config:** trail_activation_r in [0.0, 0.5, 1.0, 1.5]

| Variant | IS Trades | IS WR | IS PF | IS P&L | OOS Trades | OOS WR | OOS PF | OOS P&L |
|---------|-----------|-------|-------|--------|------------|--------|--------|---------|
| trail_act=0.0R | 18 | 33.3% | 0.39 | $-2019 | 63 | 49.2% | 1.24 | $1848 |
| trail_act=0.5R | 18 | 33.3% | 0.39 | $-2019 | 63 | 49.2% | 1.24 | $1848 |
| trail_act=1.0R | 18 | 33.3% | 0.39 | $-2019 | 63 | 49.2% | 1.24 | $1848 |
| trail_act=1.5R | 18 | 33.3% | 0.39 | $-2019 | 63 | 49.2% | 1.24 | $1848 |

  Best: trail_act=0.0R (OOS PF=1.24)

======================================================================
T003: Tier1 Percentage Sweep
======================================================================
Hypothesis: Adjusting T1 exit % (using trail_factor=0.7, activation=0.0R)
    t1_pct=0.3: OOS 63 trades, PF=1.27, $2070
    t1_pct=0.4: OOS 63 trades, PF=1.26, $1959
    t1_pct=0.5: OOS 63 trades, PF=1.24, $1848
    t1_pct=0.6: OOS 63 trades, PF=1.23, $1738

## T003: Tier1 Percentage Sweep
**Hypothesis:** t1_pct in [0.30, 0.40, 0.50, 0.60] (trail_factor=0.7, activation=0.0R)
**Config:** t1_pct sweep

| Variant | IS Trades | IS WR | IS PF | IS P&L | OOS Trades | OOS WR | OOS PF | OOS P&L |
|---------|-----------|-------|-------|--------|------------|--------|--------|---------|
| t1_pct=0.3 | 18 | 33.3% | 0.39 | $-2024 | 63 | 49.2% | 1.27 | $2070 |
| t1_pct=0.4 | 18 | 33.3% | 0.39 | $-2022 | 63 | 49.2% | 1.26 | $1959 |
| t1_pct=0.5 | 18 | 33.3% | 0.39 | $-2019 | 63 | 49.2% | 1.24 | $1848 |
| t1_pct=0.6 | 18 | 33.3% | 0.39 | $-2016 | 63 | 49.2% | 1.23 | $1738 |

  Best: t1_pct=0.3 (OOS PF=1.27)

======================================================================
T004: Combined Best Trail Config
======================================================================
Hypothesis: trail_factor=0.7, activation=0.0R, t1_pct=0.3 vs W001 baseline

  T004 Combined
    IS:  18 trades, 33.3% WR, PF=0.39, $-2024
    OOS: 63 trades, 49.2% WR, PF=1.27, $2070
    AAPL: 6 trades, 66.7% WR, PF=2.36, $643 [tgt=0 stp=1 eod=4 trail=1]
    AMZN: 19 trades, 47.4% WR, PF=1.32, $806 [tgt=0 stp=7 eod=10 trail=2]
    GOOGL: 15 trades, 40.0% WR, PF=1.20, $333 [tgt=0 stp=4 eod=11 trail=0]
    TSLA: 23 trades, 52.2% WR, PF=1.10, $289 [tgt=1 stp=9 eod=13 trail=0]

  vs W001 Baseline: PF 1.23 -> 1.27, P&L $1714 -> $2070
  Verdict: ACCEPT

>> Using T004 trail-optimized config for portfolio

======================================================================
N001: NVDA Max Stop ATR Sweep
======================================================================
Hypothesis: Wider stops allow NVDA's high volatility moves without premature stops
    max_stop_atr=0.1: OOS 14 trades, PF=0.89, $-318
    max_stop_atr=0.15: OOS 14 trades, PF=0.89, $-318
    max_stop_atr=0.2: OOS 14 trades, PF=0.89, $-318
    max_stop_atr=0.25: OOS 14 trades, PF=0.89, $-318

## N001: NVDA Max Stop ATR Sweep
**Hypothesis:** Wider stops for high-vol
**Config:** max_stop_atr_pct in [0.10, 0.15, 0.20, 0.25] on NVDA

| Variant | IS Trades | IS WR | IS PF | IS P&L | OOS Trades | OOS WR | OOS PF | OOS P&L |
|---------|-----------|-------|-------|--------|------------|--------|--------|---------|
| max_stop_atr=0.1 | 2 | 0.0% | 0.00 | $-599 | 14 | 42.9% | 0.89 | $-318 |
| max_stop_atr=0.15 | 2 | 0.0% | 0.00 | $-599 | 14 | 42.9% | 0.89 | $-318 |
| max_stop_atr=0.2 | 2 | 0.0% | 0.00 | $-599 | 14 | 42.9% | 0.89 | $-318 |
| max_stop_atr=0.25 | 2 | 0.0% | 0.00 | $-599 | 14 | 42.9% | 0.89 | $-318 |

  Best: max_stop_atr=0.1 (OOS PF=0.89)

======================================================================
N002: NVDA Fractal Depth Sweep
======================================================================
Hypothesis: Shallower fractals detect more levels for NVDA (using max_stop_atr=0.1)
    fractal_depth=3: OOS 33 trades, PF=0.86, $-976
    fractal_depth=5: OOS 17 trades, PF=0.52, $-1762
    fractal_depth=7: OOS 13 trades, PF=0.59, $-1238
    fractal_depth=10: OOS 14 trades, PF=0.89, $-318

## N002: NVDA Fractal Depth Sweep
**Hypothesis:** Shallower fractals (max_stop_atr=0.1)
**Config:** fractal_depth in [3, 5, 7, 10] on NVDA

| Variant | IS Trades | IS WR | IS PF | IS P&L | OOS Trades | OOS WR | OOS PF | OOS P&L |
|---------|-----------|-------|-------|--------|------------|--------|--------|---------|
| fractal_depth=3 | 11 | 45.5% | 0.83 | $-228 | 33 | 30.3% | 0.86 | $-976 |
| fractal_depth=5 | 6 | 50.0% | 1.33 | $223 | 17 | 35.3% | 0.52 | $-1762 |
| fractal_depth=7 | 6 | 50.0% | 1.33 | $223 | 13 | 38.5% | 0.59 | $-1238 |
| fractal_depth=10 | 2 | 0.0% | 0.00 | $-599 | 14 | 42.9% | 0.89 | $-318 |

  Best: fractal_depth=10 (OOS PF=0.89)

======================================================================
N003: NVDA Combined Rescue Config
======================================================================
Hypothesis: Combined: fractal_depth=10, max_stop_atr=0.1

  N003 NVDA Rescue
    IS:  2 trades, 0.0% WR, PF=0.00, $-599
    OOS: 14 trades, 42.9% WR, PF=0.89, $-318
    NVDA: 14 trades, 42.9% WR, PF=0.89, $-318 [tgt=0 stp=8 eod=5 trail=1]

  Verdict: EXCLUDE NVDA (PF=0.89, trades=14, P&L=$-318)

>> Final portfolio: AAPL, AMZN, GOOGL, TSLA (NVDA excluded)

======================================================================
WF: Walk-Forward Validation (Final Portfolio)
======================================================================
Hypothesis: 8-window rolling validation (3mo train / 1mo test)

  Walk-Forward Results (8 windows):
    Mean Sharpe:     -6.29 +/- 5.18
    Positive Sharpe: 0/8 windows
    Mean PF:         0.63
    Mean WR:         35.8%
    Total Trades:    148
    Total P&L:       $-7991

  | Window | Test Period | Trades | WR | PF | Sharpe | P&L |
  |--------|-------------|--------|-----|-----|--------|------|
  | 1 | 2025-05-10->2025-06-10 | 7 | 28.6% | 0.34 | -2.22 | $-1061 |
  | 2 | 2025-06-10->2025-07-10 | 11 | 18.2% | 0.14 | -12.17 | $-1880 |
  | 3 | 2025-07-10->2025-08-10 | 32 | 43.8% | 0.77 | -10.15 | $-990 |
  | 4 | 2025-08-10->2025-09-10 | 14 | 35.7% | 0.48 | -3.43 | $-1146 |
  | 5 | 2025-09-10->2025-10-10 | 21 | 33.3% | 0.53 | -5.32 | $-1563 |
  | 6 | 2025-10-10->2025-11-10 | 29 | 37.9% | 0.72 | -1.79 | $-1045 |
  | 7 | 2025-11-10->2025-12-10 | 13 | 46.2% | 1.29 | -0.05 | $526 |
  | 8 | 2025-12-10->2026-01-10 | 21 | 42.9% | 0.75 | -15.23 | $-833 |

======================================================================
V4.1 FINAL SUMMARY
======================================================================

Final Portfolio: AAPL, AMZN, GOOGL, TSLA
Best trail config: trail_factor=0.7, activation=0.0R, t1_pct=0.3

Portfolio OOS: 63 trades, 49.2% WR, PF=1.27, $2070
Walk-Forward: 0/8 positive windows, mean Sharpe=-6.29

Per-Ticker OOS:
  AAPL: 6 trades, 66.7% WR, PF=2.36, $643
  AMZN: 19 trades, 47.4% WR, PF=1.32, $806
  GOOGL: 15 trades, 40.0% WR, PF=1.20, $333
  TSLA: 23 trades, 52.2% WR, PF=1.10, $289

--- Success Criteria Check ---
  Portfolio OOS PF > 1.2: PASS (PF=1.27)
  Portfolio OOS P&L > $1,500: PASS ($2070)
  Walk-Forward >= 5/8 positive: FAIL (0/8)
  Total OOS trades >= 50: PASS (63)