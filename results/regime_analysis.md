# Phase 5A — Regime Analysis

**Date:** 2026-03-03 17:35
**Tickers:** AAPL, AMZN, GOOGL, TSLA
**Config:** v4.1 best (trail_factor=0.7, t1_pct=0.30)
**Full period:** 2025-02-10 to 2026-01-31

---

## 1. Regime Indicator Summary (per ticker)

### AAPL

| Metric | Full Period | IS (2025-02-10-2025-10-01) | OOS (2025-10-01-2026-01-31) |
|--------|-----------|-----|-----|
| Avg ADX(14) | 22.1 | 16.7 | 29.9 |
| Avg ATR(14) | $8.32 | $8.68 | $8.83 |
| Avg ATR ratio | 0.99 | 0.96 | 1.14 |
| % FAVORABLE days | 59% | 55% | 26% |
| % HOSTILE days | 12% | 2% | 55% |

### AMZN

| Metric | Full Period | IS (2025-02-10-2025-10-01) | OOS (2025-10-01-2026-01-31) |
|--------|-----------|-----|-----|
| Avg ADX(14) | 23.3 | 19.1 | 23.6 |
| Avg ATR(14) | $9.28 | $9.88 | $8.47 |
| Avg ATR ratio | 0.96 | 0.97 | 0.99 |
| % FAVORABLE days | 48% | 37% | 53% |
| % HOSTILE days | 33% | 29% | 28% |

### GOOGL

| Metric | Full Period | IS (2025-02-10-2025-10-01) | OOS (2025-10-01-2026-01-31) |
|--------|-----------|-----|-----|
| Avg ADX(14) | 22.4 | 18.8 | 21.2 |
| Avg ATR(14) | $8.66 | $7.15 | $9.80 |
| Avg ATR ratio | 1.05 | 1.00 | 1.09 |
| % FAVORABLE days | 45% | 45% | 38% |
| % HOSTILE days | 15% | 20% | 4% |

### TSLA

| Metric | Full Period | IS (2025-02-10-2025-10-01) | OOS (2025-10-01-2026-01-31) |
|--------|-----------|-----|-----|
| Avg ADX(14) | 20.5 | 15.7 | 23.5 |
| Avg ATR(14) | $22.85 | $25.37 | $21.72 |
| Avg ATR ratio | 0.96 | 0.93 | 1.02 |
| % FAVORABLE days | 73% | 65% | 57% |
| % HOSTILE days | 9% | 9% | 9% |

---

## 2. Trade Outcomes by Regime (Full Period)

### By Combined Regime

| Regime | Trades | Win Rate | PF | Total P&L | Avg P&L | Avg R |
|--------|--------|----------|-----|-----------|---------|-------|
| FAVORABLE | 14 | 28.6% | 0.21 | $-2411 | $-172 | -0.51 |
| HOSTILE | 7 | 42.9% | 1.49 | $492 | $70 | 0.17 |
| NEUTRAL | 5 | 60.0% | 2.33 | $465 | $93 | 0.31 |

### By ADX Bucket

| ADX Range | Trades | Win Rate | PF | Total P&L | Avg P&L |
|-----------|--------|----------|-----|-----------|---------|
| 15-20 | 8 | 37.5% | 0.38 | $-1028 | $-128 |
| 20-25 | 11 | 36.4% | 0.84 | $-275 | $-25 |
| 25-30 | 1 | 100.0% | inf | $476 | $476 |
| 30-40 | 6 | 33.3% | 0.38 | $-627 | $-105 |

### By ATR Ratio Bucket

| ATR Ratio | Trades | Win Rate | PF | Total P&L | Avg P&L |
|-----------|--------|----------|-----|-----------|---------|
| <0.8 | 2 | 50.0% | 0.16 | $-253 | $-126 |
| 0.8-1.0 | 8 | 25.0% | 0.30 | $-1335 | $-167 |
| 1.0-1.2 | 9 | 33.3% | 0.28 | $-1002 | $-111 |
| 1.2-1.5 | 5 | 60.0% | 2.33 | $465 | $93 |
| >1.5 | 2 | 50.0% | 2.49 | $670 | $335 |

---

## 3. IS vs OOS Regime Comparison

### IS Period Trades by Regime

| Regime | Trades | Win Rate | PF | Total P&L |
|--------|--------|----------|-----|-----------|
| FAVORABLE | 10 | 30.0% | 0.24 | $-1812 |
| HOSTILE | 4 | 25.0% | 0.64 | $-201 |
| NEUTRAL | 4 | 50.0% | 0.97 | $-11 |

### OOS Period Trades by Regime

| Regime | Trades | Win Rate | PF | Total P&L |
|--------|--------|----------|-----|-----------|
| FAVORABLE | 29 | 48.3% | 1.13 | $459 |
| HOSTILE | 8 | 62.5% | 2.16 | $1217 |
| NEUTRAL | 26 | 46.2% | 1.13 | $395 |

### IS Trades by ADX Bucket

| ADX Range | Trades | Win Rate | PF | Total P&L |
|-----------|--------|----------|-----|-----------|
| 15-20 | 5 | 40.0% | 0.55 | $-476 |
| 20-25 | 9 | 33.3% | 0.21 | $-1348 |
| 30-40 | 4 | 25.0% | 0.64 | $-201 |

### OOS Trades by ADX Bucket

| ADX Range | Trades | Win Rate | PF | Total P&L |
|-----------|--------|----------|-----|-----------|
| 15-20 | 15 | 40.0% | 0.78 | $-504 |
| 20-25 | 19 | 52.6% | 1.99 | $1895 |
| 25-30 | 22 | 50.0% | 1.25 | $581 |
| 30-40 | 7 | 57.1% | 1.09 | $97 |

---

## 4. Walk-Forward Windows Mapped to Regime

| Window | Test Period | Avg ADX | Avg ATR Ratio | % Favorable | % Hostile | Dominant |
|--------|-------------|---------|---------------|-------------|-----------|----------|
| 1 | 2025-05-10->2025-06-10 | 15.5 | 0.87 | 96% | 0% | FAVORABLE |
| 2 | 2025-06-10->2025-07-10 | 23.7 | 0.77 | 52% | 39% | FAVORABLE |
| 3 | 2025-07-10->2025-08-10 | 24.1 | 0.83 | 66% | 30% | FAVORABLE |
| 4 | 2025-08-10->2025-09-10 | 18.5 | 1.03 | 74% | 0% | FAVORABLE |
| 5 | 2025-09-10->2025-10-10 | 27.9 | 1.02 | 42% | 40% | FAVORABLE |
| 6 | 2025-10-10->2025-11-10 | 25.9 | 1.21 | 25% | 25% | NEUTRAL |
| 7 | 2025-11-10->2025-12-10 | 21.0 | 1.26 | 39% | 25% | FAVORABLE |
| 8 | 2025-12-10->2026-01-10 | 18.7 | 0.82 | 92% | 0% | FAVORABLE |

### Cross-reference with v4.1 Walk-Forward P&L

| Window | Test Period | P&L | Avg ADX | Avg ATR Ratio | Dominant Regime |
|--------|-------------|------|---------|---------------|-----------------|
| 1 | 2025-05-10->2025-06-10 | $-1061 (LOSS) | 15.5 | 0.87 | FAVORABLE |
| 2 | 2025-06-10->2025-07-10 | $-1880 (LOSS) | 23.7 | 0.77 | FAVORABLE |
| 3 | 2025-07-10->2025-08-10 | $-990 (LOSS) | 24.1 | 0.83 | FAVORABLE |
| 4 | 2025-08-10->2025-09-10 | $-1146 (LOSS) | 18.5 | 1.03 | FAVORABLE |
| 5 | 2025-09-10->2025-10-10 | $-1563 (LOSS) | 27.9 | 1.02 | FAVORABLE |
| 6 | 2025-10-10->2025-11-10 | $-1045 (LOSS) | 25.9 | 1.21 | NEUTRAL |
| 7 | 2025-11-10->2025-12-10 | $526 (PROFIT) | 21.0 | 1.26 | FAVORABLE |
| 8 | 2025-12-10->2026-01-10 | $-833 (LOSS) | 18.7 | 0.82 | FAVORABLE |

---

## 5. Verdict & Recommendations

- **FAVORABLE regime:** 14 trades, PF=0.21
- **HOSTILE regime:** 7 trades, PF=1.49

**NO CLEAR SIGNAL:** Regime classification does not clearly separate winning from losing trades. Regime filter may not help.

### ADX-specific finding
- ADX 15-20: 8 trades, PF=0.38 (UNPROFITABLE)
- ADX 20-25: 11 trades, PF=0.84 (UNPROFITABLE)
- ADX 25-30: 1 trades, PF=inf (PROFITABLE)
- ADX 30-40: 6 trades, PF=0.38 (UNPROFITABLE)
