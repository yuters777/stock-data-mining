# M4 Mean-Reversion: Extended Hours 4H Backtest — Comparison

| Metric | RTH (2 bars/day) | Extended (4 bars/day) | Known Baseline |
|--------|-------------------|----------------------|----------------|
| N | 0 | 0 | 28 |
| PF | 0.00 | 0.00 | 4.95 |
| WR % | 0.0% | 0.0% | 71.4% |
| Mean % | +0.00% | +0.00% | +4.63% |
| Avg Hold (bars) | 0.0 | 0.0 | 8.8 |

## Configuration

- **RTH mode**: 2 bars/day — Bar 1 (09:30–13:25 ET), Bar 2 (13:30–15:55 ET)
- **Extended mode**: 4 bars/day — Bar A (04:00–07:55 ET), Bar B (08:00–11:55 ET), Bar C (12:00–15:55 ET), Bar D (16:00–19:55 ET)
- **Known Baseline**: RTH-only result from prior 1-year backtest run

## Entry Rules (ALL required)

1. 3+ consecutive 4H down bars (close < open)
2. Prior-day VIX close >= 25
3. RSI(14) < 35 at trigger bar  *(frozen hard gate)*
4. EMA21 valid (not in warmup)

## Exit Rules (first triggered)

1. 4H close >= EMA21
2. 10-bar hard maximum

## Streak Definition

- Down bar: close < open
- Streak resets on: non-down bar OR time gap > 30 hours (resets every weekend)

## Conviction Tiers

- **TIER_A**: RSI 25–35 at entry
- **TIER_B**: RSI < 25 at entry

## Notes

- No earnings filter for M4
- One position per ticker at a time (no stacking)
- Entry price = trigger bar close; Exit price = exit bar close
- VIX = prior trading-day close (max vix_date strictly before bar date)