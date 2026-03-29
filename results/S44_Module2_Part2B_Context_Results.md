# S44 Module 2 — Part 2B: 4H Context Enhancement

**Date:** 2026-03-29 18:52
**Entry:** E2 (RSI<40 dip + recovery)
**Exit:** X8 (4H EMA gate flips DOWN)
**Safety:** -1.5% hard stop + EOD flat at 15:50 ET
**Total baseline trades:** 6,766

## 1. Context Layer Results

| Context | Description | N | Mean% | Median% | WR% | PF | Sharpe | Stop% | EOD% | p-val |
|---------|-------------|---|-------|---------|-----|----|--------|-------|------|-------|
| NONE | No context (E2 + X8 baseline) | 6,766 | +0.1676 | +0.1427 | 60.1 | 1.64 | 0.166 | 11.4 | 87.1 | 0.0000*** |
| C1 | 4H RSI 35-65 (neutral zone) | 4,483 | +0.1872 | +0.1531 | 60.4 | 1.71 | 0.182 | 11.3 | 86.4 | 0.0000*** |
| C2 | 4H ADX < 25 (fresh trend) | 3,614 | +0.2079 | +0.1615 | 61.2 | 1.83 | 0.206 | 10.5 | 87.2 | 0.0000*** |
| C3 | 4H ADX < 20 (very fresh trend) | 1,967 | +0.2543 | +0.1854 | 61.7 | 2.08 | 0.252 | 9.4 | 87.8 | 0.0000*** |
| C4 | VIX < 20 only (NORMAL regime) | 5,609 | +0.1284 | +0.1284 | 59.7 | 1.48 | 0.132 | 11.6 | 86.9 | 0.0000*** |
| C5 | C1 + C2 (RSI neutral + fresh ADX) | 2,952 | +0.2311 | +0.1842 | 61.9 | 1.93 | 0.223 | 10.5 | 86.7 | 0.0000*** |

## 2. Separation from Baseline (NONE)

| Context | N | Mean% | Delta Mean% | Delta PF | Delta Sharpe | Sep p-val | Significant? |
|---------|---|-------|-------------|----------|-------------|-----------|-------------|
| C1 | 4,483 | +0.1872 | +0.0197 | +0.08 | +0.015 | 0.3170 | no |
| C2 | 3,614 | +0.2079 | +0.0403 | +0.19 | +0.040 | 0.0521 | no |
| C3 | 1,967 | +0.2543 | +0.0868 | +0.45 | +0.086 | 0.0008 | YES |
| C4 | 5,609 | +0.1284 | -0.0392 | -0.16 | -0.034 | 0.0281 | YES |
| C5 | 2,952 | +0.2311 | +0.0635 | +0.29 | +0.057 | 0.0051 | YES |

## 3. Ranking by Profit Factor

| Rank | Context | PF | Sharpe | Mean% | N | Significant? |
|------|---------|----|----- --|-------|---|-------------|
| 1 | C3 | 2.08 | 0.252 | +0.2543 | 1,967 | YES |
| 2 | C5 | 1.93 | 0.223 | +0.2311 | 2,952 | YES |
| 3 | C2 | 1.83 | 0.206 | +0.2079 | 3,614 | no |
| 4 | C1 | 1.71 | 0.182 | +0.1872 | 4,483 | no |
| 5 | C4 | 1.48 | 0.132 | +0.1284 | 5,609 | YES |

## 4. Winner Identification

**Winner: C3** — 4H ADX < 20 (very fresh trend)
- PF: 2.08 (baseline 1.64)
- Sharpe: 0.252 (baseline 0.166)
- Mean: +0.2543% (baseline +0.1676%)
- N: 1,967 (29% of baseline)

## 5. Risk Profile Comparison

| Context | Avg MAE% | Avg MFE% | MFE/MAE | Avg Hold |
|---------|----------|----------|---------|----------|
| NONE | -0.5857 | +0.7903 | 1.35 | 35.9 |
| C1 | -0.5857 | +0.8252 | 1.41 | 35.7 |
| C2 | -0.5805 | +0.8133 | 1.40 | 36.4 |
| C3 | -0.5641 | +0.8482 | 1.50 | 36.4 |
| C4 | -0.5819 | +0.7390 | 1.27 | 35.5 |
| C5 | -0.5836 | +0.8435 | 1.45 | 36.3 |

## 6. Final Module 2 Trend Spec

```
PERMISSION:  4H EMA gate UP (EMA9 > EMA21) + VIX < 25 + NOT Module 4 window
ENTRY:       E2 — M5 RSI(14) dips below 40, first bar RSI crosses back above 40
EXIT:        X8 — 4H EMA gate flips DOWN (EMA9 <= EMA21)
CONTEXT:     C3 — 4H ADX < 20 (very fresh trend)
STOP:        -1.5% hard stop from entry price
EOD:         Flat at 15:50 ET if no exit signal
```

## 7. Honest Assessment

**E2 + X8 baseline performance:**
- N = 6,766 trades across 25 tickers
- Mean = +0.1676%, WR = 60.1%, PF = 1.64
- Sharpe (per-trade) = 0.166
- Stop-out rate = 11.4%
- EOD flat rate = 87.1%

**Assessment: Module 2 shows a genuine, statistically significant trend-following edge.**

The E2 entry (RSI pullback recovery within 4H uptrend) produces:
- Consistent positive returns (+0.1676% per trade)
- Strong win rate (60.1%)
- Favorable risk profile (MFE/MAE = 1.35)

**Caveat:** 87% of trades exit EOD flat, meaning the 4H gate rarely flips 
within the same session. This is effectively a 'hold until close' strategy 
after a pullback entry. The edge comes from ENTRY TIMING, not exit sophistication.

**Grade: PASSIVE FILTER with entry timing edge** — not autonomous-grade.
PF < 2.0 and mean < 0.20% per trade = useful as a bias/filter layer,
but not strong enough to trade standalone without additional confluence.

## 8. Configuration

```
RSI period:    14 (Wilder smoothing)
EMA periods:   9, 21
CE params:     period=14, lookback=22, mult=2.0
Hard stop:     -1.5%
EOD flat:      15:50 ET
4H indicators: rsi_14, adx_14 (from data/indicators_4h/)
```
