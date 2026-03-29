# S45 Overnight Decomposition — Part 2: Strategy Backtest

**Generated:** 2026-03-29 21:36
**Tickers:** 27  |  **Date range:** 2025-02-04 → 2026-03-18

## Task A: Overnight Hold Strategy

Buy at today's close (15:55 ET), sell at tomorrow's open (09:30 ET).

### Overnight Variants

| Variant | N | Mean (%) | WR (%) | Profit Factor | Sharpe | Max Lose Streak | p-value |
|---------|---|----------|--------|---------------|--------|-----------------|---------|
| V1: No filter | 7428 | 0.1039 | 52.1 | 1.11 | 0.0351 | 9 | 0.0025 ** |
| V2: Gate UP | 3678 | 0.3700 | 55.7 | 1.52 | 0.1393 | 8 | 0.0000 *** |
| V3: VIX < 25 | 6717 | 0.1043 | 52.5 | 1.12 | 0.0392 | 8 | 0.0013 ** |
| V4: VIX ≥ 25 | 568 | -0.0754 | 44.9 | 0.96 | -0.0142 | 8 | 0.7358 |
| V5: Gate UP + ADX < 20 | 1192 | 0.5643 | 57.8 | 1.89 | 0.2035 | 8 | 0.0000 *** |

## Task B: Intraday-Only Comparison

Buy at today's open (09:30 ET), sell at today's close (15:55 ET).

### Intraday Variants

| Variant | N | Mean (%) | WR (%) | Profit Factor | Sharpe | Max Lose Streak | p-value |
|---------|---|----------|--------|---------------|--------|-----------------|---------|
| V1: No filter | 7428 | 0.0134 | 50.8 | 1.05 | 0.0121 | 14 | 0.2963 |
| V2: Gate UP | 3678 | -0.0033 | 50.5 | 0.98 | -0.0049 | 14 | 0.7660 |
| V3: VIX < 25 | 6717 | 0.0057 | 50.5 | 1.02 | 0.0059 | 14 | 0.6287 |
| V4: VIX ≥ 25 | 568 | 0.1134 | 55.3 | 1.25 | 0.0522 | 7 | 0.2141 |
| V5: Gate UP + ADX < 20 | 1192 | -0.0157 | 49.0 | 0.93 | -0.0239 | 10 | 0.4099 |

## Head-to-Head: Overnight vs Intraday

| Variant | ON Mean (%) | Intra Mean (%) | ON Sharpe | Intra Sharpe | ON WR | Intra WR | Winner |
|---------|-------------|----------------|-----------|--------------|-------|----------|--------|
| V1: No filter | 0.1039 | 0.0134 | 0.0351 | 0.0121 | 52.1 | 50.8 | **Overnight** |
| V2: Gate UP | 0.3700 | -0.0033 | 0.1393 | -0.0049 | 55.7 | 50.5 | **Overnight** |
| V3: VIX < 25 | 0.1043 | 0.0057 | 0.0392 | 0.0059 | 52.5 | 50.5 | **Overnight** |
| V4: VIX ≥ 25 | -0.0754 | 0.1134 | -0.0142 | 0.0522 | 44.9 | 55.3 | **Intraday** |
| V5: Gate UP + ADX < 20 | 0.5643 | -0.0157 | 0.2035 | -0.0239 | 57.8 | 49.0 | **Overnight** |

## Task C: Combined Strategy

Since Part 1 confirmed overnight >> intraday, we test two combined approaches.

### C1: Full Hold (close → next close) when Gate UP + ADX < 20

Hold overnight AND intraday — capture total return when trend filter is active.

| Metric | Value |
|--------|-------|
| N | 1192 |
| Mean return (%) | 0.5465 |
| Win rate (%) | 57.6 |
| Profit factor | 1.83 |
| Sharpe | 0.1971 |
| Max losing streak | 8 |
| p-value | 0.0000 *** |

### C2: Overnight + Selective Intraday (gap reversal filter)

Capture overnight always (Gate UP), then add intraday only when overnight gap was small (<1% absolute) — avoiding the reversal drag from big gaps.

| Metric | Value |
|--------|-------|
| N | 3678 |
| Mean return (%) | 0.3656 |
| Win rate (%) | 55.1 |
| Profit factor | 1.49 |
| Sharpe | 0.1366 |
| Max losing streak | 9 |
| p-value | 0.0000 *** |

### Combined vs Pure Overnight (Gate UP)

| Strategy | Mean (%) | Sharpe | WR (%) | PF |
|----------|----------|--------|--------|----|
| V2 Overnight only | 0.3700 | 0.1393 | 55.7 | 1.52 |
| C1 Full hold (Gate UP + ADX<20) | 0.5465 | 0.1971 | 57.6 | 1.83 |
| C2 ON + selective intra | 0.3656 | 0.1366 | 55.1 | 1.49 |

## Verdict

**Best overnight variant:** V5: Gate UP + ADX < 20
  - Sharpe: 0.2035, Mean: 0.5643%, p=0.0000
**Best intraday variant:** V4: VIX ≥ 25
  - Sharpe: 0.0522, Mean: 0.1134%, p=0.2141

### Recommendation: Module 2 should incorporate overnight hold as primary return source

The overnight edge is **statistically significant** and materially larger than intraday. The filtered variant (V5: Gate UP + ADX < 20) achieves a Sharpe of 0.2035 vs best intraday Sharpe of 0.0522. 

**Action items:**
1. Redesign Module 2 entry to target close-to-open holds when 4H EMA gate is UP
2. Use VIX < 25 as a regime guard (overnight edge disappears in HIGH_RISK)
3. Intraday re-entry should be selective — only when overnight gap is small (<1%)
4. The current intraday-only Module 2 is not broken; it's targeting the weaker leg of returns

---
*End of S45 Part 2 Strategy Backtest*