# Phase 6A — Direction Analysis

**Date:** 2026-03-03
**Tickers:** AAPL, AMZN, GOOGL, TSLA
**Config:** v4.1 best (trail_factor=0.7, t1_pct=0.30)

---

## 1. Portfolio Summary (IS + OOS)

| Experiment | Direction | Trades (IS) | WR (IS) | PF (IS) | P&L (IS) | Trades (OOS) | WR (OOS) | PF (OOS) | P&L (OOS) |
|------------|-----------|-------------|---------|---------|----------|--------------|----------|----------|-----------|
| L-001 | LONG | 7 | 28.6% | 0.14 | $-1202 | 36 | 52.8% | 2.19 | $4546 |
| L-002 | SHORT | 13 | 30.8% | 0.49 | $-1144 | 43 | 46.5% | 1.11 | $563 |
| L-003 | BOTH | 18 | 33.3% | 0.39 | $-2024 | 63 | 49.2% | 1.27 | $2070 |

## 2a. Per-Ticker Breakdown (IS)

| Ticker | L-001 LONG | | | L-002 SHORT | | | L-003 BOTH | | |
|--------|-----|-----|------|------|-----|------|------|-----|------|
| | Trades | PF | P&L | Trades | PF | P&L | Trades | PF | P&L |
| AAPL | 4 | 0.10 | $-724 | 5 | 0.20 | $-1085 | 8 | 0.18 | $-1509 |
| AMZN | 1 | 0.00 | $-299 | 4 | 1.27 | $77 | 4 | 0.64 | $-201 |
| GOOGL | 2 | 0.40 | $-179 | 2 | 1.50 | $151 | 4 | 0.95 | $-28 |
| TSLA | 0 | 0.00 | $0 | 2 | 0.04 | $-287 | 2 | 0.04 | $-287 |

## 2b. Per-Ticker Breakdown (OOS)

| Ticker | L-001 LONG | | | L-002 SHORT | | | L-003 BOTH | | |
|--------|-----|-----|------|------|-----|------|------|-----|------|
| | Trades | PF | P&L | Trades | PF | P&L | Trades | PF | P&L |
| AAPL | 2 | 0.55 | $-202 | 4 | 35.92 | $845 | 6 | 2.36 | $643 |
| AMZN | 10 | 0.80 | $-277 | 13 | 1.35 | $588 | 19 | 1.32 | $806 |
| GOOGL | 4 | 0.72 | $-183 | 13 | 1.33 | $423 | 15 | 1.20 | $333 |
| TSLA | 20 | 4.94 | $5209 | 13 | 0.43 | $-1293 | 23 | 1.10 | $289 |

## 3. Direction Split within BOTH (L-003)

### OOS per-ticker direction counts

| Ticker | LONG trades | SHORT trades |
|--------|-------------|--------------|
| AAPL | 2 | 4 |
| AMZN | 9 | 10 |
| GOOGL | 3 | 12 |
| TSLA | 12 | 11 |

## 4. Walk-Forward Comparison (8 windows)

| Window | Period | L-001 LONG | | L-002 SHORT | | L-003 BOTH | |
|--------|--------|------|------|-------|------|------|------|
| | | Trades | P&L | Trades | P&L | Trades | P&L |
| 1 | 2025-05-10 → 2025-06-10 | 4 | $-1498 | 5 | $-162 | 7 | $-1061 |
| 2 | 2025-06-10 → 2025-07-10 | 6 | $-1010 | 12 | $1086 | 11 | $-1880 |
| 3 | 2025-07-10 → 2025-08-10 | 22 | $-1206 | 18 | $-349 | 32 | $-990 |
| 4 | 2025-08-10 → 2025-09-10 | 12 | $818 | 7 | $-1159 | 14 | $-1146 |
| 5 | 2025-09-10 → 2025-10-10 | 15 | $-197 | 19 | $-1652 | 21 | $-1563 |
| 6 | 2025-10-10 → 2025-11-10 | 18 | $-427 | 23 | $-89 | 29 | $-1045 |
| 7 | 2025-11-10 → 2025-12-10 | 12 | $-977 | 9 | $1731 | 13 | $526 |
| 8 | 2025-12-10 → 2026-01-10 | 14 | $3844 | 11 | $-1622 | 21 | $-833 |

### Walk-Forward Summary

| Metric | L-001 LONG | L-002 SHORT | L-003 BOTH |
|--------|-----------|------------|-----------|
| Positive windows | 1/8 | 4/8 | 0/8 |
| Mean Sharpe | -65.64 | 20.79 | -6.29 |
| Mean PF | 1.05 | 1.11 | 0.63 |
| Total trades | 103 | 104 | 148 |
| Total P&L | $-655 | $-2215 | $-7991 |
| Mean P&L/window | $-82 | $-277 | $-999 |

## 5. Verdict

**Best OOS PF:** L-001 (long) — PF=2.19, $4546

**Best WF stability:** L-002 (short) — 4/8 positive windows, mean Sharpe=20.79

**Recommendation:** SHORT ONLY shows the most promising walk-forward stability (4/8 positive, mean Sharpe +20.79 vs 0/8 baseline). LONG ONLY has best OOS PF but is TSLA-concentrated (20/36 trades, $5,209/$4,546) and worst WF (1/8, Sharpe=-65.64). Next step: test per-ticker direction preferences (TSLA=BOTH, others=SHORT) and SHORT-only walk-forward stability.
