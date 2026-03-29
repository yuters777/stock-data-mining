# S44 Module 4 Baseline Results — 4H-Close vs M5 Entry

**Date:** 2026-03-29 14:54
**Total 4H triggers (3 down + VIX>=25):** 159
**Tickers with triggers:** 25/25
**VIX threshold:** 25.0
**Streak length:** 3 consecutive 4H down bars

## Trigger Distribution

| Ticker | Triggers |
|--------|----------|
| AAPL | 5 |
| AMD | 9 |
| AMZN | 6 |
| AVGO | 7 |
| BA | 3 |
| BABA | 8 |
| BIDU | 5 |
| C | 3 |
| COIN | 6 |
| COST | 5 |
| GOOGL | 5 |
| GS | 7 |
| IBIT | 2 |
| JPM | 11 |
| MARA | 5 |
| META | 6 |
| MSFT | 10 |
| MU | 5 |
| NVDA | 9 |
| PLTR | 6 |
| SNOW | 6 |
| TSLA | 11 |
| TSM | 7 |
| TXN | 9 |
| V | 3 |

## Entry Comparison (E1: +2 4H bars exit)

| Entry | N | Fill% | Mean% | Med% | WR% | PF | MAE% | MFE% | NetExp | p-val |
|-------|---|-------|-------|------|-----|-----|------|------|--------|-------|
| BASELINE | 157 | 99 | +2.43 | +1.31 | 71 | 5.64 | -2.28 | 4.78 | +2.400 | 0.0000*** |
| M5-A | 157 | 99 | +1.82 | +0.58 | 60 | 3.35 | -2.86 | 4.15 | +1.800 | 0.0000*** |
| M5-B | 156 | 98 | +1.48 | +0.70 | 64 | 3.01 | -2.78 | 4.15 | +1.449 | 0.0000*** |
| M5-C | 111 | 70 | +1.50 | +0.77 | 71 | 3.76 | -2.51 | 4.09 | +1.047 | 0.0000*** |

## M5 Filter Miss Rates

| Variant | Triggers | Entries | Missed | Miss% |
|---------|----------|---------|--------|-------|
| M5-A | 159 | 157 | 2 | 1% |
| M5-B | 159 | 157 | 2 | 1% |
| M5-C | 159 | 111 | 48 | 30% |

## Exit Comparison for Winner: BASELINE

| Exit | N | Mean% | Med% | WR% | PF | MAE% | MFE% | p-val |
|------|---|-------|------|-----|-----|------|------|-------|
| E1 | 157 | +2.43 | +1.31 | 71 | 5.64 | -2.28 | 4.78 | 0.0000*** |
| E2 | 144 | +4.04 | +2.37 | 81 | 15.34 | -2.62 | 6.47 | 0.0000*** |
| E4 | 158 | +0.94 | +0.31 | 64 | 3.63 | -1.71 | 3.46 | 0.0000*** |

## Verdict

**BASELINE wins** with net expectancy +2.400%.
No M5 filter improves on plain 4H-close entry.

BASELINE is statistically significant (p=0.0000).
