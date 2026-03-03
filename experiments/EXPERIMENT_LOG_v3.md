# Experiment Log v3 — Structural Target Optimization

**Date:** 2026-03-03 12:34
**Tickers:** NVDA, AMZN
**IS Period:** 2025-02-10 to 2025-10-01
**OOS Period:** 2025-10-01 to 2026-01-31
**Baseline:** v2 optimized (fd=10, atr=0.80, stop=0.10, tail=0.10)

---

## Baseline (v2 optimized, D1 targets only)

| Period | Trades | WR | PF | P&L | Target Hits | EOD Exits | Stops |
|--------|--------|-----|-----|------|-------------|-----------|-------|
| IS | 10 | 30.0% | 0.45 | $-843 | 0 | 6 | 4 |
| OOS | 53 | 41.5% | 0.92 | $-691 | 1 | 30 | 22 |

---

## STRUCT-001: M5 Intraday Targets (Single-Tier Replacement)

**Hypothesis:** Replacing D1 targets with M5 fractal intraday targets will increase target hit rate from ~2% to >20%, improving P&L.
**Change:** Use IntradayLevelDetector to find M5/H1 fractal S/R, set as trade target. Min R:R reduced to 1.5.

| Variant | Trades (IS) | WR (IS) | PF (IS) | P&L (IS) | Trades (OOS) | WR (OOS) | PF (OOS) | P&L (OOS) | Targets Used |
|---------|-------------|---------|---------|----------|--------------|----------|----------|-----------|-------------|
| STRUCT-001a: M5 fractal k=3 | 7 | 14.3% | 0.25 | $-1099 | 29 | 37.9% | 0.59 | $-2180 | 92 |
| STRUCT-001b: M5 fractal k=5 | 7 | 14.3% | 0.25 | $-1099 | 33 | 39.4% | 0.67 | $-1974 | 87 |
| STRUCT-001c: M5 fractal k=10 | 7 | 14.3% | 0.25 | $-1099 | 42 | 28.6% | 0.40 | $-5224 | 60 |
| STRUCT-001d: H1 fractal k=3 | 6 | 16.7% | 0.31 | $-800 | 33 | 45.5% | 0.97 | $-185 | 90 |

### Target Hit Analysis (OOS)

| Variant | Target Hits | EOD Exits | Stops | Hit Rate |
|---------|-------------|-----------|-------|----------|
| STRUCT-001a | 3 | 12 | 14 | 10% |
| STRUCT-001b | 4 | 13 | 16 | 12% |
| STRUCT-001c | 3 | 17 | 22 | 7% |
| STRUCT-001d | 5 | 13 | 15 | 15% |

**Best STRUCT-001:** STRUCT-001d (H1 fractal k=3)

---

## STRUCT-002: Tiered Exit System

**Hypothesis:** Multi-level partial exits at M5/H1/D1 levels will capture more profit than single-target approach.
**Base intraday config:** H1 fractal k=3

| Variant | Trades (IS) | WR (IS) | PF (IS) | P&L (IS) | Trades (OOS) | WR (OOS) | PF (OOS) | P&L (OOS) | Targets Used |
|---------|-------------|---------|---------|----------|--------------|----------|----------|-----------|-------------|
| STRUCT-002a: 2-tier 50/50 M5+D1 | 6 | 16.7% | 0.31 | $-800 | 33 | 45.5% | 0.94 | $-310 | 89 |
| STRUCT-002b: 2-tier 60/40 M5+D1 | 6 | 16.7% | 0.31 | $-800 | 31 | 41.9% | 0.91 | $-505 | 83 |
| STRUCT-002c: 3-tier 40/30/30 M5+H1+D1 | 6 | 16.7% | 0.31 | $-800 | 31 | 41.9% | 0.94 | $-329 | 83 |
| STRUCT-002d: 2-tier 50% M5 + trail | 6 | 16.7% | 0.31 | $-800 | 33 | 45.5% | 1.03 | $156 | 89 |

### Target Hit Analysis (OOS)

| Variant | Target Hits | EOD Exits | Stops | Hit Rate |
|---------|-------------|-----------|-------|----------|
| STRUCT-002a | 1 | 16 | 16 | 3% |
| STRUCT-002b | 0 | 14 | 17 | 0% |
| STRUCT-002c | 0 | 14 | 17 | 0% |
| STRUCT-002d | 0 | 15 | 15 | 0% |

---

## STRUCT-003: Combined Winner

**Config:** STRUCT-002d: 2-tier 50% M5 + trail

| Period | Trades | WR | PF | P&L | Target Hits | EOD | Stops |
|--------|--------|-----|-----|------|-------------|-----|-------|
| Baseline OOS | 53 | 41.5% | 0.92 | $-691 | 1 | 30 | 22 |
| Combined IS | 6 | 16.7% | 0.31 | $-800 | 0 | 3 | 3 |
| Combined OOS | 33 | 45.5% | 1.03 | $156 | 0 | 15 | 15 |

---

## Walk-Forward Validation

**Config:** Combined winner
**Windows:** 8 (3-month train / 1-month test)

| Window | Test Period | Trades | WR | PF | Sharpe | P&L |
|--------|-------------|--------|-----|-----|--------|------|
| 1 | 2025-05-10->2025-06-10 | 3 | 0.0% | 0.00 | -79.60 | $-817 |
| 2 | 2025-06-10->2025-07-10 | 3 | 0.0% | 0.00 | -11.22 | $-600 |
| 3 | 2025-07-10->2025-08-10 | 25 | 52.0% | 1.25 | 1.00 | $569 |
| 4 | 2025-08-10->2025-09-10 | 0 | 0.0% | 0.00 | 0.00 | $0 |
| 5 | 2025-09-10->2025-10-10 | 18 | 38.9% | 0.68 | 10.89 | $-876 |
| 6 | 2025-10-10->2025-11-10 | 21 | 28.6% | 0.32 | -17.70 | $-2655 |
| 7 | 2025-11-10->2025-12-10 | 12 | 50.0% | 1.29 | 1.37 | $551 |
| 8 | 2025-12-10->2026-01-10 | 14 | 21.4% | 0.23 | -36.62 | $-2341 |

**Summary:**
- Mean Sharpe: -16.49 +/- 27.53
- Positive Sharpe windows: 3/8
- Mean PF: 0.47
- Mean WR: 23.9%
- Total Trades: 96
- Total P&L: $-6170
