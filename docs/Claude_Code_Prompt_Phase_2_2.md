# CLAUDE CODE — Phase 2.2 Parameter Optimization

## CONTEXT

Baseline backtest complete: 7 tickers, 8 trades, PF 2.03, WR 37.5%, DD 1.20%.
Signal Funnel bottlenecks identified:
- ATR filter blocks 75% of signals (382/509)
- Sawing invalidates 95% of levels (58/61)
- Only 8 trades in 10 months — insufficient for statistics

Goal: Find parameter set that produces 30-50+ trades with positive expectancy.

## APPROACH: Grid Search (NOT walk-forward yet)

Walk-forward requires sufficient trades per window. First, find parameter ranges that generate enough signals. Then validate with walk-forward in Phase 2.3.

## EXPERIMENT 1: ATR Sensitivity

The ATR filter is the #1 bottleneck. Test how trade count and quality change across ATR thresholds.

Run 5 backtests on all 7 tickers with ONLY the ATR_MIN_ENTRY parameter changed:

| Run | ATR_MIN_ENTRY | ATR_BLOCK_THRESHOLD |
|-----|--------------|---------------------|
| A   | 0.80 (current spec) | 0.30 |
| B   | 0.70 | 0.25 |
| C   | 0.60 | 0.20 |
| D   | 0.50 | 0.15 |
| E   | 0.40 | 0.10 |

For each run report: trades, WR, PF, avg_R, max_DD, Sharpe.

## EXPERIMENT 2: Sawing Sensitivity

Sawing kills 95% of levels. Test relaxation:

| Run | SAWING_THRESHOLD | SAWING_PERIOD_D1 |
|-----|-----------------|------------------|
| F   | 3 (current) | 20 |
| G   | 4 | 20 |
| H   | 5 | 20 |
| I   | 3 | 30 |
| J   | 5 | 30 |

For each run report: levels surviving, trades, WR, PF, avg_R, max_DD.

## EXPERIMENT 3: Combined Best

Take the best ATR setting from Exp 1 and best Sawing setting from Exp 2. Run combined.

Also test FRACTAL_DEPTH variations in the combo:

| Run | FRACTAL_DEPTH | ATR_MIN_ENTRY | SAWING |
|-----|--------------|---------------|--------|
| K   | 5 | best_from_exp1 | best_from_exp2 |
| L   | 7 (current) | best_from_exp1 | best_from_exp2 |
| M   | 10 | best_from_exp1 | best_from_exp2 |

## EXPERIMENT 4: Tail Ratio & LP2 Engulfing

After finding best structural params, test pattern sensitivity:

| Run | TAIL_RATIO_MIN | LP2_ENGULFING |
|-----|---------------|---------------|
| N   | 0.10 | On |
| O   | 0.15 (current) | On |
| P   | 0.20 | On |
| Q   | 0.15 | Off |

## OUTPUT FORMAT

For each experiment, create a summary table:

```
| Run | Param Value | Trades | WR% | PF | Avg_R | MaxDD% | Sharpe | 
```

At the end, report:
1. Recommended parameter set
2. Total trades with recommended set
3. Full metrics with recommended set
4. Signal Funnel with recommended set (where are signals blocked now?)

## IMPORTANT RULES

1. ALL runs use the same data (7 tickers, full date range)
2. ALL runs use both directions (LONG + SHORT)  
3. Change ONLY the parameter being tested — everything else stays DEFAULT_CONFIG
4. MIN_RISK_REWARD stays 3.0 (non-negotiable per spec)
5. If a parameter change produces more trades but PF < 1.0, note it as NEGATIVE
6. Record everything — even bad results are data

## WHEN DONE

Provide the recommended DEFAULT_CONFIG changes with justification per parameter.
