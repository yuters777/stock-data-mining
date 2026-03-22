# S28 RSI Phase Scoring — Calibration Results

**Date**: 2026-03-22
**Repo**: yuters77/stock-data-mining
**Tag**: s28-rsi-phase-v1

## Verdict: **CONFIRMED**

## Summary

| Metric | Value |
|--------|-------|
| Total cross events | 34835 |
| Zone 2 events | 7704 |
| Zone 2 events with fwd_60m | 7704 |
| Walk-forward folds | 6 |
| Mean OOS Spearman IC | 0.0515 ± 0.0485 |
| % folds IC > 0 | 83.3% |
| Mean quintile spread | 0.2752% |
| Mean decile violations | 4.3 |
| % folds top > bottom | 83.3% |

## Overfit Controls

| Check | Result |
|-------|--------|
| OOS IC positive ≥70% folds | 83.3% → PASS |
| Top > bottom quintile ≥70% folds | 83.3% → PASS |
| Jackknife flagged tickers | NVDA (Δ=20.4%) |

## Quintile Returns (Zone 2, fwd_60m)

| Quintile | Mean fwd_60m | Std | Count |
|----------|-------------|-----|-------|
| Q1(Low) | -0.5378% | 1.2008% | 1541 |
| Q2 | -0.3614% | 0.9805% | 1541 |
| Q3 | -0.4079% | 1.0272% | 1542 |
| Q4 | -0.4100% | 1.0533% | 1540 |
| Q5(High) | -0.3428% | 1.0009% | 1540 |


## Supplementary Zone Analysis

| Zone | Events | Spearman IC |
|------|--------|-------------|
| 1 | 4234 | -0.015 |
| 3 | 11386 | 0.1212 |
| 4 | 6025 | 0.0619 |
| 5 | 5481 | 0.0722 |

## Events by Direction

| Direction | Count |
|-----------|-------|
| LONG | 17412 |
| SHORT | 17423 |

## Events by Ticker (Top 10)

| Ticker | Count |
|--------|-------|
| C | 2391 |
| GS | 2315 |
| TXN | 2225 |
| COST | 1900 |
| V | 1852 |
| SNOW | 1710 |
| BIDU | 1674 |
| JPM | 1606 |
| BA | 1580 |
| MSFT | 1092 |

## Files Generated

- `s28_ema_cross_events.csv` — All cross events with scores and forward returns
- `fold_details.csv` — Per-fold walk-forward metrics
- `phase_distribution.csv` — Event counts by RSI phase
- `score_distribution.png` — Score histogram
- `quintile_returns.png` — Mean returns by score quintile
- `ic_by_fold.png` — Spearman IC over time
- `ticker_jackknife.png` — Leave-one-out IC stability
- `score_vs_return_scatter.png` — Score vs return scatter

## Interpretation

The RSI Phase Scoring curve shows statistically meaningful rank-ordering ability
for forward 60-minute returns on EMA 9/21 cross entries. The designed sigmoid
parameters from S28 DR produce a score that positively correlates with
directional returns in the majority of out-of-sample folds.

**Recommendation**: Deploy to shadow portfolio for live monitoring. Monitor for
20+ sessions before trusting for position sizing.

## Constants Used (S28 DR — NOT optimized)

- Level sigmoid center low: 28.0
- Level sigmoid width low: 4.5
- Level sigmoid center high: 68.0
- Level sigmoid width high: 5.0
- Level normalization: 0.9710
- Slope sigmoid center: 0.10
- Slope sigmoid width: 0.65
