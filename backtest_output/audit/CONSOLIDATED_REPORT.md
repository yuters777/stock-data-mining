# CONSOLIDATED AUDIT REPORT
## Stock Data Mining Framework — Empirical Validation

**Date range:** 2025-02-03 to 2026-03-18
**Tickers:** 25 equities + SPY + VIXY (27 total)
**Data:** 5-minute bars (regular session), VIX daily

---

## Master Results Table

| # | Test | Framework Claim | Actual Result | Verdict | N |
|---|------|----------------|---------------|---------|---|
| A1 | Volume J-Shape | First/last 30 min dominate volume (U-shape) | Open 33.4%, close period elevated, midday 1.7% — J-shape confirmed | **CONFIRMED** | 7,359 ticker-days |
| A2 | Power Hour > Dead Zone | Zone 5 (14:45-15:55) abs return > Zone 3 (12:00-13:30) | Zone 5 (0.390%) < Zone 3 (0.417%), p=0.0036 significant | **REJECTED** | 7,359 ticker-days |
| A3 | Phantom Lunch-Crunch | Systematic sell-off at 11:30 ET | Mean phantom return −0.004%, Wilcoxon p=0.27, not significant | **REJECTED** | 1,642 ticker-days |
| B1 | Gap-Fill Rates by Size | Fill rates: 75%/58%/48%/29%/20% by gap bucket | Actual: 91%/80%/69%/52%/29% — monotonic pattern correct, rates higher | **REVISED** | 8,053 gap-days |
| B2 | Gap-Fill Timing | 10:00 fills 51-61%, 10:30 fills 66-72% | 10:00 = 52.3% (in range), 10:30 = 59.7% (close), 13:00 = 78.4% (close) | **REVISED** | 4,258 fills |
| B3 | Gap-Fill by Range Position | Inside > Above ≈ Below fill rates | Inside 61.6% > Below 42.6% > Above 39.5% — ordering confirmed | **CONFIRMED** | 8,053 gap-days |
| C1 | Opening-Range Spike Rate | ~30-34% of days, first 30 min sets day extreme | Actual 44.1% — directionally right but rate higher by +10pp | **REVISED** | 7,911 ticker-days |
| C2 | Wide-Day Double Breakout | Wide days have ~4.8% double breakout rate | Actual 30.0% — 6x higher than claimed | **REJECTED** | 4,211 wide days |
| C3 | Dead Zone False Breakout | Dead Zone (12:00-13:30) false breakout = 45-55% | Actual 76.4% — directionally right (highest zone) but rate much higher | **REVISED** | 2,453 breakouts |
| D1 | CE Multiplier Comparison | CE 2.0× is optimal Chandelier Exit | CE 2.5× best (PF=1.48, AvgR=+0.554R); CE 2.0× middle (PF=1.13) | **REVISED** | 295 trades × 5 mult |
| D2 | Clock-Stop Saved:Killed | +0.5R clock stop saved:killed = 14:1 | Actual 61:24 = 2.5:1 — still beneficial but far less extreme | **REVISED** | 111 clock-stop exits |
| D3 | Time-Based Partial Exits | Time partials improve returns | T90 best (AvgR=+0.190, PF=1.18) vs NO_TP (AvgR=+0.116, PF=1.11) | **CONFIRMED** | 295 trades × 6 var |
| E2 | TQS: DMI Dominant Weight | DMI is most important TQS component (weight 0.35) | RSI has highest std β (0.314 vs DMI 0.055) — RSI dominates empirically | **REJECTED** | 92,053 obs |
| F1 | BTC-ETH Lag | BTC leads ETH on moves | Mean lag 5.6 min, median 0 min; 69% within 5 min — moves near-simultaneous | **REVISED** | 535 events |
| F2 | Coin-Bank Divergence Signal | COIN vs IBIT divergence predicts next-day IBIT | Correlation = 0.081 — near zero, no predictive value | **REJECTED** | 286 days |
| G1 | VIX Change > VIX Level | VIX change predicts SPY returns better than VIX level | R² 0.524 (change) vs 0.047 (level) = 11.1× higher — strongly confirmed | **CONFIRMED** | 272 days |
| G2 | High VIX = Best Regime | High Vol (VIX≥25) entries = only profitable regime | High: +0.335% mean; Low: −0.031%; Normal: −0.060%. Also Elevated: +0.238% | **REVISED** | 272 days |
| H1 | Exit Time 15:30 Optimal | 15:30 ET exit for laggard noon entries | 15:30 is optimal: +0.895% mean, 72.2% win rate, Sharpe +0.541 | **CONFIRMED** | 108 trades |
| H2 | Stress > Non-Stress Reversal | Stress +1.51%, non-stress +0.78% | Stress +0.895%, non-stress +1.108% — both significant, but non-stress stronger | **REJECTED** | 552 trades |

---

## Summary by Verdict

### CONFIRMED (5 tests)

| # | Test | Key Finding |
|---|------|-------------|
| A1 | Volume J-Shape | Opening 30 min = 33% of volume, midday collapses to 1.7% |
| B3 | Gap-Fill by Range | Inside-range opens fill at 62% vs 40% for outside — use as filter |
| D3 | Time Partials | T90 partial adds +0.074R avg vs no partial — modest but consistent |
| G1 | VIX Change > Level | 11× more predictive — use ΔVIX not VIX level for regime |
| H1 | Exit at 15:30 | Peak mean reversion captured; 15:00 viable conservative alt (best Sharpe) |

### REVISED (7 tests — directionally correct, numbers differ)

| # | Test | Claim → Actual | Adjustment Needed |
|---|------|----------------|-------------------|
| B1 | Gap-Fill Rates | Claimed 75/58/48/29/20% → Actual 91/80/69/52/29% | Fill rates are **higher** than modeled — framework is conservative |
| B2 | Gap-Fill Timing | Claimed 66-72% by 10:30 → Actual 59.7% | Slightly slower fills — widen timing window |
| C1 | Opening Spike | Claimed 30-34% → Actual 44.1% | First-30-min extremes more common — increase spike expectation |
| C3 | Dead Zone False BO | Claimed 45-55% → Actual 76.4% | Dead Zone is **far worse** for breakouts than modeled — avoid entirely |
| D1 | CE Multiplier | Claimed 2.0× optimal → Actual 2.5× best | Widen CE multiplier from 2.0× to 2.5× |
| D2 | Clock-Stop Ratio | Claimed 14:1 → Actual 2.5:1 | Clock stop still net beneficial but overfit in original claim |
| F1 | BTC-ETH Lag | Claimed BTC leads → Actual median 0 min | Lag is too short for practical trading; moves are near-simultaneous |
| G2 | High VIX Regime | Claimed "only profitable" → Elevated also profitable | Both VIX ≥ 20 regimes are profitable; Elevated has better Sharpe (+0.281) |

### REJECTED (5 tests — claim not supported by data)

| # | Test | Claim | Reality |
|---|------|-------|---------|
| A2 | Power Hour | Zone 5 outperforms Zone 3 | Zone 5 is **weaker** than Zone 3 (p=0.004) |
| A3 | Phantom Lunch-Crunch | Systematic 11:30 sell-off | No statistical evidence (p=0.27, N=3 anecdote) |
| C2 | Wide-Day Double BO | 4.8% double breakout on wide days | Actual 30% — claim was off by 6× |
| E2 | DMI Dominant | DMI most important TQS signal | RSI has 5.7× higher standardized beta |
| F2 | Coin Divergence | COIN-IBIT divergence predicts next day | Correlation 0.081 — no signal |
| H2 | Stress > Non-Stress | Stress reversal stronger (+1.51% vs +0.78%) | Non-stress actually stronger (+1.11% vs +0.90%) |

---

## Recommended Parameter Changes

Based on the audit findings, the following framework parameters should be updated:

### High Priority (clear evidence, material impact)

1. **CE Multiplier: 2.0× → 2.5×**
   D1 audit shows CE 2.5× has PF=1.48 vs 2.0× PF=1.13 (+31% improvement). Wider trail captures more of the move.

2. **TQS Weights: Increase RSI, decrease DMI**
   E2 regression: RSI std β = 0.314, DMI std β = 0.055. RSI should have the highest weight, not DMI. Suggested: RSI 0.35, DMI 0.15 (swap current weights).

3. **Dead Zone: Avoid ALL breakout entries 12:00-14:45**
   C3 shows 75-76% false breakout rate in Zones 3-4, vs 42% in Zone 2. The dead zone is far more treacherous than modeled.

4. **VIX Regime Filter: Use ΔVIX, not VIX level**
   G1 confirms 11× more predictive power. Add VIX daily change as primary regime signal.

### Medium Priority (useful refinements)

5. **Gap-Fill Rate Model: Update to actual rates**
   B1 shows framework underestimates fill rates by 15-22pp in the 0.3-1.5% gap range. Recalibrate expected fill probabilities upward.

6. **Clock-Stop Saved:Killed: Recalibrate from 14:1 to 2.5:1**
   D2 shows clock stop is still net positive but the extreme ratio was overfit. Keep the rule but adjust sizing/confidence accordingly.

7. **Time Partial at T90: Implement**
   D3 shows T90 adds +0.074R avg per trade with PF 1.18 vs 1.11 baseline. Modest but consistent alpha.

8. **Non-Stress Noon Reversal: Keep in strategy**
   H2 shows non-stress reversal is +1.11% mean with 83.6% win rate, highly significant (p<0.0001). Remove stress-only restriction.

### Low Priority (informational, no action required)

9. **Exit time 15:30: No change needed** — H1 confirms it's optimal.
10. **Opening spike rate: Informational** — actual 44% vs claimed 30-34%, but no parameter depends on this.
11. **BTC-ETH lag: Not actionable** — too short for manual trading.
12. **Coin divergence signal: Remove** — F2 shows no predictive value.

---

## Scorecard

| Verdict | Count | % |
|---------|-------|---|
| CONFIRMED | 5 | 29% |
| REVISED | 7 | 41% |
| REJECTED | 5 | 29% |
| **Total tested** | **17** | **100%** |

**Overall:** 71% of framework claims are directionally correct (CONFIRMED + REVISED), but specific parameter values frequently overfit to small samples. The framework's structural intuitions are sound — the calibration needs tightening.
