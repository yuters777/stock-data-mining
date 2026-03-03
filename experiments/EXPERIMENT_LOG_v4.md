# Experiment Log v4 — Universe Expansion & Volatility Profiles

**Date:** 2026-03-03 13:25
**Tickers:** AAPL, AMZN, GOOGL, META, MSFT, NVDA, TSLA
**IS Period:** 2025-02-10 to 2025-10-01
**OOS Period:** 2025-10-01 to 2026-01-31
**Baseline Config:** v3 winner (STRUCT-002d: 2-tier trail, H1 k=3, min_rr=1.5)

---

## Phase 4A: Data Summary

| Ticker | Bars | Date Range | Avg Price | Avg ATR | Rel ATR | Bucket | OOS Days |
|--------|------|------------|-----------|---------|---------|--------|----------|
| AAPL | 14976 | 2025-02-10 to 2025-11-12 | $224.53 | $8.70 | 0.0392 | HIGH_VOL | 31 |
| AMZN | 18330 | 2025-02-10 to 2026-01-23 | $217.43 | $9.44 | 0.0446 | HIGH_VOL | 74 |
| GOOGL | 20202 | 2025-02-10 to 2026-02-27 | $227.71 | $8.37 | 0.0382 | HIGH_VOL | 98 |
| META | 20202 | 2025-02-10 to 2026-02-27 | $671.13 | $28.40 | 0.0438 | HIGH_VOL | 98 |
| MSFT | 20202 | 2025-02-10 to 2026-02-27 | $462.73 | $14.19 | 0.0317 | HIGH_VOL | 98 |
| NVDA | 18330 | 2025-02-10 to 2026-01-23 | $157.48 | $8.65 | 0.0588 | HIGH_VOL | 74 |
| TSLA | 20202 | 2025-02-10 to 2026-02-27 | $362.27 | $23.82 | 0.0709 | HIGH_VOL | 98 |

---

## EXP-V001: Uniform Config (v3 Winner) on All 7 Tickers

**Hypothesis:** The v3 winner config (STRUCT-002d) will be naturally profitable on MED_VOL tickers and struggle on HIGH_VOL tickers, due to stop sizing and level reliability differences.

**Config:** fractal_depth=10, atr_entry=0.80, max_stop_atr=0.10, tail=0.10, min_rr=1.5, 2-tier trail (50% H1 + trail), H1 fractal k=3

### Per-Ticker Results

| Ticker | Bucket | IS Trades | IS WR | IS PF | IS P&L | OOS Trades | OOS WR | OOS PF | OOS P&L |
|--------|--------|-----------|-------|-------|--------|------------|--------|--------|---------|
| AAPL | HIGH_VOL | 8 | 25.0% | 0.18 | $-1509 | 6 | 66.7% | 2.10 | $521 |
| AMZN | HIGH_VOL | 4 | 25.0% | 0.64 | $-201 | 19 | 47.4% | 1.22 | $571 |
| GOOGL | HIGH_VOL | 4 | 50.0% | 0.96 | $-22 | 15 | 40.0% | 1.20 | $333 |
| META | HIGH_VOL | 5 | 20.0% | 0.04 | $-833 | 33 | 30.3% | 0.74 | $-1548 |
| MSFT | HIGH_VOL | 0 | 0.0% | 0.00 | $0 | 22 | 31.8% | 0.45 | $-2289 |
| NVDA | HIGH_VOL | 2 | 0.0% | 0.00 | $-599 | 14 | 42.9% | 0.86 | $-415 |
| TSLA | HIGH_VOL | 2 | 50.0% | 0.04 | $-287 | 23 | 52.2% | 1.10 | $289 |

### OOS Exit Analysis

| Ticker | Bucket | Target | Stop | EOD | Trail/BE | Total |
|--------|--------|--------|------|-----|----------|-------|
| AAPL | HIGH_VOL | 0 | 1 | 4 | 1 | 6 |
| AMZN | HIGH_VOL | 0 | 7 | 10 | 2 | 19 |
| GOOGL | HIGH_VOL | 0 | 4 | 11 | 0 | 15 |
| META | HIGH_VOL | 0 | 18 | 14 | 1 | 33 |
| MSFT | HIGH_VOL | 0 | 12 | 10 | 0 | 22 |
| NVDA | HIGH_VOL | 0 | 8 | 5 | 1 | 14 |
| TSLA | HIGH_VOL | 1 | 9 | 13 | 0 | 23 |

### Portfolio Summary

| Segment | OOS Trades | OOS WR | OOS PF | OOS P&L |
|---------|------------|--------|--------|---------|
| Portfolio | 132 | 40.9% | 0.88 | $-2538 |
| HIGH_VOL | 132 | 40.9% | 0.88 | $-2538 |

### Per-Ticker Signal Funnels (OOS)

```
SIGNAL FUNNEL — AAPL (HIGH_VOL) — EXP-V001 (OOS)
==================================================
D1 levels detected:     9
  Confirmed (BPU):      9
  Mirror:               8
  Invalidated:          0

Trades executed:        6
  Target exits:         0
  Stop exits:           1
  EOD exits:            4
  Trail/breakeven:      1

Win rate:               66.7%
Profit factor:          2.10
Total P&L:              $521
Max drawdown:           0.45%
Sharpe:                 4.78
Intraday targets used:  19
```

```
SIGNAL FUNNEL — AMZN (HIGH_VOL) — EXP-V001 (OOS)
==================================================
D1 levels detected:     9
  Confirmed (BPU):      9
  Mirror:               9
  Invalidated:          6

Trades executed:        19
  Target exits:         0
  Stop exits:           7
  EOD exits:            10
  Trail/breakeven:      2

Win rate:               47.4%
Profit factor:          1.22
Total P&L:              $571
Max drawdown:           1.19%
Sharpe:                 1.65
Intraday targets used:  56
```

```
SIGNAL FUNNEL — GOOGL (HIGH_VOL) — EXP-V001 (OOS)
==================================================
D1 levels detected:     10
  Confirmed (BPU):      10
  Mirror:               3
  Invalidated:          1

Trades executed:        15
  Target exits:         0
  Stop exits:           4
  EOD exits:            11
  Trail/breakeven:      0

Win rate:               40.0%
Profit factor:          1.20
Total P&L:              $333
Max drawdown:           0.90%
Sharpe:                 1.56
Intraday targets used:  46
```

```
SIGNAL FUNNEL — META (HIGH_VOL) — EXP-V001 (OOS)
==================================================
D1 levels detected:     9
  Confirmed (BPU):      9
  Mirror:               9
  Invalidated:          2

Trades executed:        33
  Target exits:         0
  Stop exits:           18
  EOD exits:            14
  Trail/breakeven:      1

Win rate:               30.3%
Profit factor:          0.74
Total P&L:              $-1548
Max drawdown:           1.98%
Sharpe:                 -2.69
Intraday targets used:  62
```

```
SIGNAL FUNNEL — MSFT (HIGH_VOL) — EXP-V001 (OOS)
==================================================
D1 levels detected:     8
  Confirmed (BPU):      8
  Mirror:               6
  Invalidated:          6

Trades executed:        22
  Target exits:         0
  Stop exits:           12
  EOD exits:            10
  Trail/breakeven:      0

Win rate:               31.8%
Profit factor:          0.45
Total P&L:              $-2289
Max drawdown:           2.65%
Sharpe:                 -5.96
Intraday targets used:  49
```

```
SIGNAL FUNNEL — NVDA (HIGH_VOL) — EXP-V001 (OOS)
==================================================
D1 levels detected:     8
  Confirmed (BPU):      8
  Mirror:               4
  Invalidated:          4

Trades executed:        14
  Target exits:         0
  Stop exits:           8
  EOD exits:            5
  Trail/breakeven:      1

Win rate:               42.9%
Profit factor:          0.86
Total P&L:              $-415
Max drawdown:           1.19%
Sharpe:                 -1.12
Intraday targets used:  33
```

```
SIGNAL FUNNEL — TSLA (HIGH_VOL) — EXP-V001 (OOS)
==================================================
D1 levels detected:     7
  Confirmed (BPU):      7
  Mirror:               4
  Invalidated:          1

Trades executed:        23
  Target exits:         1
  Stop exits:           9
  EOD exits:            13
  Trail/breakeven:      0

Win rate:               52.2%
Profit factor:          1.10
Total P&L:              $289
Max drawdown:           1.34%
Sharpe:                 1.01
Intraday targets used:  53
```

---

## EXP-V001 Verdict

- **Profitable tickers (OOS):** 4/7
- **MED_VOL profitable:** 0/0
- **Portfolio PF:** 0.88
- **Portfolio P&L:** $-2538
- **Total OOS trades:** 132

**Verdict: NEEDS WORK** — Uniform config does not achieve portfolio profitability.

**Next steps:**
- EXP-V002: Test adaptive volatility profiles (different params per bucket)
- Focus on HIGH_VOL parameter adjustments if MED_VOL is naturally profitable
