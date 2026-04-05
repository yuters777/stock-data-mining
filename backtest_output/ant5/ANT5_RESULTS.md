# ANT-5: Strong Stock — Earnings Gap-UP Dip-Buy — Results

**Date:** 2026-04-05
**Data:** 444 events (daily, 2022-2026), 22 tickers M5 (Feb 2025 - Mar 2026)
**Gap-UP Universe (>= +5%):** N=33 (daily), N=15 with M5

---

## TEST 0: Universe

- Gap >= +5%: 33 (7.4% of all earnings)
- Gap >= +7%: 22, Gap >= +10%: 13
- Symmetry: 33 gap-UP vs 30 gap-DOWN (roughly balanced)
- 17 tickers contributed; PLTR (5), BIDU (4), BABA/META/TSLA (3 each)

---

## TEST 1: Strength Ratio vs Drift

| Bucket | N | Drift 1d | Drift 5d | WR 5d | Flag |
|--------|---|----------|----------|-------|------|
| A (>1.00, extended) | 14 | -0.07% | -2.03% | 35.7% | LOW N |
| B (0.80-1.00) | 6 | +0.50% | +0.35% | 66.7% | ANECDOTAL |
| **C (0.60-0.80)** | **3** | **+4.83%** | **+9.06%** | **100%** | **ANECDOTAL** |
| D (0.40-0.60) | 7 | +0.30% | -2.10% | 57.1% | ANECDOTAL |
| E (<0.40, faded) | 3 | +2.73% | -3.48% | 0.0% | ANECDOTAL |

**Spearman: rho = -0.09 (p=0.61) for drift_5d — NO correlation.**

### Counter-intuitive finding:
- **Bucket A (gap EXTENDED, closed above open)** shows WORST 5d drift (-2.03%, WR 35.7%)
- **Bucket C (moderate retention 0.60-0.80)** shows BEST drift (+9.06%, 100% WR) but N=3
- Stocks that gap UP and EXTEND the gap on Day 1 tend to REVERSE over 5 days
- This is classic mean-reversion: the more extreme the Day 1 move, the bigger the pullback

---

## TEST 2: Sawtooth Check

### Cumulative Drift

| Group | N | 1d | 2d | 3d | 5d | 10d |
|-------|---|----|----|----|----|-----|
| Strong (ret>=0.80) | 20 | +0.10% | -0.13% | -1.33% | -1.31% | +3.17% |
| Weak (<0.60) | 10 | +1.03% | -0.14% | -0.14% | -2.52% | -0.94% |
| ALL gap-UP | 33 | +0.81% | +0.70% | -0.01% | -0.73% | +2.60% |

### Incremental Drift

| Group | N | Day 1 | Day 2 | Day 3 | Day 4-5 |
|-------|---|-------|-------|-------|---------|
| Strong | 20 | +0.10% | -0.23% | **-1.20%** | +0.01% |
| ALL | 33 | +0.81% | -0.11% | **-0.71%** | -0.36% |

### Gap-UP Sawtooth Pattern:
```
Day 1: +0.81%    ← mild continuation
Day 2: +0.70%    ← still positive (cumulative)
Day 3: -0.01%    ← REVERSAL kicks in
Day 5: -0.73%    ← negative (profit-taking won)
Day 10: +2.60%   ← slow recovery
```

**Different from gap-DOWN sawtooth.** Gap-DOWN had sharp Day 1 bounce (+2.09%)
then Day 2 reversal. Gap-UP has slower erosion starting Day 3.

---

## TEST 3: Pullback Threshold (ANT's 40% Rule)

| Max Pullback < | N | Drift 1d | Drift 5d | WR 1d | WR 5d |
|----------------|---|----------|----------|-------|-------|
| 30% | 5 | -0.03% | +3.04% | 40% | 80% |
| **40% (ANT)** | **7** | **+0.87%** | **+0.93%** | **42.9%** | **57.1%** |
| 50% | 16 | +1.74% | +2.51% | 56.2% | 62.5% |
| 60% | 19 | +2.13% | +1.93% | 63.2% | 57.9% |
| ALL | 33 | +0.81% | -0.73% | 60.6% | 48.5% |

**ANT's 40% threshold is too restrictive.** It only captures 7 events.
The pullback < 50% filter (N=16) shows better metrics across the board.
But the real finding: **stocks with SMALL pullbacks (< 30%) have the best 5d drift (+3.04%, 80% WR)** though N=5.

**Filtering OUT high-pullback events (>50%) improves drift_5d from -0.73% to +2.51%.**
This is directionally what ANT claims but the optimal threshold is 50%, not 40%.

---

## TEST 4: Gap Size Interaction

Drift shown as d1/d5:

| | +3-5% | +5-10% | +10-15% | >+15% |
|---|---|---|---|---|
| Str>0.80 | -0.1/+1.8% (N=9) | -1.0/-2.3% (N=12) | -1.9/-5.4% (N=4) | +5.4/+5.7% (N=4) |
| Str 0.60-0.80 | +1.7/+6.1% (N=5) | +3.5/+12.5% (N=1) | +5.5/+7.3% (N=2) | N/A |
| Str<0.60 | +2.9/+3.5% (N=11) | -0.5/-3.3% (N=7) | +5.2/-4.9% (N=2) | +3.2/+7.5% (N=1) |

**Moderate gaps (+3-5%) with low retention show BEST forward drift (+2.9% d1, +3.5% d5).**
This is counter-intuitive: "weak" stocks after small gaps bounce more than "strong" ones.
Again, mean-reversion dominates.

---

## TEST 5: EPS Surprise Interaction

Very sparse data (21 events with surprise). No cell > N=6. INCONCLUSIVE.
Only notable: Strong + Big Surprise (|surp|>15%) shows +6.44% drift_5d (N=6) — 
directionally supports ANT's "strong reason" claim but too few events.

---

## TEST 6: Strategy Backtest — **KEY RESULTS**

| Variant | Exit | N | Mean% | WR | PF | Flag |
|---------|------|---|-------|----|----|------|
| **V1 ANT Basic** | **1d** | **23** | **+0.72%** | **60.9%** | **1.40** | |
| **V1 ANT Basic** | **2d** | **23** | **+1.06%** | **65.2%** | **1.48** | |
| V1 ANT Basic | 3d | 23 | +0.05% | 47.8% | 1.02 | |
| V1 ANT Basic | 5d | 23 | +0.04% | 52.2% | 1.01 | |
| **V2 +BigSurp** | **1d** | **9** | **+3.25%** | **77.8%** | **6.41** | **ANECDOTAL** |
| **V2 +BigSurp** | **2d** | **9** | **+5.24%** | **88.9%** | **10.25** | **ANECDOTAL** |
| V2 +BigSurp | 5d | 9 | +7.32% | 88.9% | 44.87 | ANECDOTAL |
| V3 Fade Buy | 1d | 14 | -0.07% | 57.1% | 0.97 | LOW N |
| V4 Extending | 1d | 14 | -0.07% | 57.1% | 0.97 | LOW N |

### Key Findings:

1. **V1 ANT Basic (gap >=5%, retention >=0.60) is profitable on 1-2 day holds:**
   - 1d: PF 1.40, WR 60.9%, N=23 (provisional!)
   - 2d: PF 1.48, WR 65.2%, N=23 (best exit)
   - 3d+: edge collapses to PF ≈ 1.0

2. **V2 (+ Big Surprise) is spectacular but ANECDOTAL (N=9):**
   - PF 6.41 to 44.87 — way too good, likely overfitted/small sample
   - But directionally: big earnings surprise + strength retention = strongest signal

3. **V3/V4 (fade buy / extending) underperform V1:**
   - Buying stocks that extended the gap (closed above open) = buying the top
   - V3 Fade Buy (pullback + recovery) is marginally better but PF < 1.0

---

## TEST 7: Day of Peak

| Day | % of Events | Mean Max Return |
|-----|-------------|-----------------|
| Day 0 | 17.4% | +0.00% |
| Day 1 | 17.4% | +5.42% |
| Day 4-5 | 13.0% | +9.87% |
| **Day 6-10** | **47.8%** | **+16.08%** |

**Mode: Day 0 / Day 1 (tie)**. But 47.8% of strong gap-UP stocks peak in Day 6-10.
This is OPPOSITE of gap-DOWN where peak was bimodal (Day 0 or Day 9-10).

For gap-UP: momentum is slow-building. The stock keeps grinding higher for a week.
This supports the V1 finding that 2d exit captures some continuation.

---

## M5 RESULTS

### TEST 8: Intraday Strength Curve (N=19 gap-UP >= +3%)

| Time | Winners (N=14) | Losers (N=5) | Separation |
|------|----------------|--------------|------------|
| 10:00 | 0.867 | 0.937 | -0.069 |
| **10:30** | **0.863** | **1.016** | **-0.153** |
| 12:00 | 0.779 | 0.808 | -0.030 |
| 13:30 | 0.881 | 0.767 | +0.113 |
| 16:00 | 0.836 | 0.690 | +0.147 |

**Biggest separation at 10:30 ET (-0.153) — but NEGATIVE.**
Losers (5d) show HIGHER strength at 10:30 than winners!
Late-day strength (13:30, 16:00) separates positively.

This means: strong opening does NOT predict 5d continuation — it predicts reversal.
The stocks that "hold" through end of day (16:00 strength higher) are the winners.

### TEST 9: Pullback Pattern
- First pullback: 10:00-10:01 ET (within 30 min of open)
- Mean depth: 2.57% from high (32% of total gain)
- Pullback-to-close return: -0.09%, WR 37% — **buying the pullback does NOT work intraday**

### TEST 10: M5 Dip-Buy
| Horizon | N | Mean% | WR | PF |
|---------|---|-------|----|----|
| Intraday (pb → close) | 15 | +0.01% | 33.3% | 1.01 |
| **Day 2** | **15** | **+1.52%** | **66.7%** | **2.60** |
| **Day 3** | **15** | **+2.15%** | **66.7%** | **2.75** |
| **Day 5** | **15** | **+3.19%** | **73.3%** | **3.66** |

**Critical finding:** M5 dip-buy shows the OPPOSITE of gap-DOWN zombie:
- **Intraday: no edge (PF 1.01)**
- **Multi-day: strong edge (PF 2.6-3.7)** — momentum builds over days

This is the mirror-image of ANT-4's gap-DOWN finding where the edge was
purely intraday and multi-day destroyed it.

### TEST 11: Symmetry Comparison

| Metric | Gap-UP (N=33) | Gap-DOWN (N=30) | Symmetric? |
|--------|---------------|-----------------|------------|
| Day 1 drift | +0.81% | +1.27% | YES (both positive) |
| Day 2 drift | +0.70% | +0.44% | YES |
| Day 3 drift | -0.01% | +1.73% | **NO** |
| Day 5 drift | -0.73% | +1.72% | **NO** |
| Day 10 drift | +2.60% | +1.08% | YES |

**NOT symmetric.** Gap-DOWN stocks bounce consistently through Day 5 (mean-reversion).
Gap-UP stocks show momentum for 2 days then fade. Different mechanisms at work.

---

## VERDICT

### What We Found

| Finding | Implication |
|---------|------------|
| **V1 ANT Basic PF 1.40-1.48 on 1-2d hold (N=23)** | Most promising finding — above provisional threshold |
| V2 BigSurp PF 6-45 (N=9) | Spectacular but ANECDOTAL — validate with more data |
| Strength ratio does NOT correlate with drift | ANT's "confirmed strength" is not the mechanism |
| **Optimal exit: Day 2** (not Day 1 or Day 5) | Gap-UP momentum lasts ~2 days, then reverses |
| M5 dip-buy: intraday no edge, multi-day PF 2.6-3.7 | Opposite of gap-DOWN zombie pattern |
| **Gap-UP and gap-DOWN are NOT symmetric** | Different mechanisms: momentum vs mean-reversion |

### The Asymmetry Explained

| | Gap-DOWN (ANT-4) | Gap-UP (ANT-5) |
|---|---|---|
| Day 1 edge | +2.09% (strong bounce) | +0.81% (mild continuation) |
| Day 2 edge | REVERSAL (-0.08%) | STILL POSITIVE (+0.70%) |
| Day 3+ | Sawtooth, fading | Reversal begins |
| Best hold | **1 day only** | **2 days** |
| Mechanism | Mean-reversion (oversold bounce) | Momentum (PEAD continuation) |
| Strategy PF | Weak (ANT-4 was N=13) | **PF 1.48 at 2d (N=23)** |

### Recommendations

1. **V1 ANT Basic (gap >=5%, retention >=0.60, 2d exit) is a candidate signal:**
   - PF 1.48, WR 65.2%, N=23 — meets "provisional" threshold (N >= 20)
   - Needs DR validation and OOS testing before parameter freezing
   - This could become a Module 5 (PEAD-lite) entry variant

2. **V2 + Big Surprise needs more data:**
   - PF > 6 with N=9 is compelling but dangerous — likely overfitted
   - If validated at N >= 20, this could be the strongest PEAD signal

3. **Gap-UP dip-buy (M5 Test 10) is worth pursuing:**
   - PF 2.6-3.7 on multi-day holds with N=15 (LOW N)
   - The "buy the gap-UP pullback, hold 2-5 days" pattern is real

4. **Do NOT mirror gap-DOWN and gap-UP strategies:**
   - They have fundamentally different timing profiles
   - Gap-DOWN = 1-day edge (mean-reversion)
   - Gap-UP = 2-5 day edge (PEAD momentum)

---

## CHARTS

1. `ant5_day_of_peak.png` — Day of max close (gap-UP peaks late)
2. `ant5_strength_curve.png` — M5 intraday strength curve
3. `ant5_sawtooth_comparison.png` — Gap-UP vs Gap-DOWN drift trajectories

---

## REPRODUCIBILITY

```bash
cd /home/user/stock-data-mining
python3 ant5_strong_stock.py
# Outputs in backtest_output/ant5/
```
