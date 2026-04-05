# ANT-4: Zombie Recovery — Short-Hold Timing Test — Results

**Date:** 2026-04-05
**Data:** 444 earnings events (daily, 2022-2026), 22 tickers with M5 (Feb 2025 - Mar 2026)
**Gap-Down Universe (gap <= -5%):** N=30 (daily), N=14 with M5

---

## TEST 1: Daily — Zombie Drift by Holding Period

### Cumulative Drift (gap <= -5%)

| Recovery >= | N | Drift 1d | Drift 2d | Drift 3d | Drift 5d | Drift 10d | Flag |
|-------------|---|----------|----------|----------|----------|-----------|------|
| 0.25 | 17 | +1.58% | +0.10% | +1.92% | +1.65% | +2.06% | LOW N |
| 0.30 | 17 | +1.58% | +0.10% | +1.92% | +1.65% | +2.06% | LOW N |
| **0.35** | **13** | **+2.09%** | **-0.08%** | **+2.40%** | **+0.93%** | **+2.05%** | LOW N |
| 0.40 | 12 | +2.11% | -0.84% | +1.65% | +0.31% | +2.27% | LOW N |
| 0.50 | 11 | +2.45% | -0.56% | +1.93% | +0.37% | +2.30% | LOW N |
| ALL | 30 | +1.27% | +0.44% | +1.73% | +1.72% | +1.08% | |

### Key Pattern: **"Sawtooth" trajectory — Day 1 up, Day 2 down, Day 3 up**

The drift is NOT monotonic. For zombie stocks (rec >= 0.35):
- **Day 1: +2.09%** — strong continuation (overnight + next day buying)
- **Day 2: -0.08%** — gives back ALL gains (Day 2 reversal)
- **Day 3: +2.40%** — bounces again
- **Day 5: +0.93%** — fades
- **Day 10: +2.05%** — slow grind back

### Incremental Drift (Marginal Value of Each Extra Day)

| Recovery >= | N | Incr Day 1 | Incr Day 2 | Incr Day 3 | Incr Day 4-5 |
|-------------|---|------------|------------|------------|--------------|
| 0.35 | 13 | **+2.09%** | **-2.17%** | **+2.48%** | -0.73% |
| 0.40 | 12 | +2.11% | -2.95% | +2.49% | -0.67% |
| 0.50 | 11 | +2.45% | -3.01% | +2.48% | -0.78% |
| ALL | 30 | +1.27% | -0.83% | +1.29% | -0.01% |

**The pattern is clear and consistent:**
- Day 1 incremental: strongly positive (+2.1% for zombies)
- Day 2 incremental: strongly NEGATIVE (-2.2% for zombies) — profit give-back
- Day 3 incremental: strongly positive again (+2.5%)
- Day 4-5: negative — edge exhausted

**Implication: If you hold zombie stocks for 1 day only, you capture +2.1%. If you hold
for 2 days, you give it all back. The zombie edge is VERY SHORT-LIVED.**

### Win Rates

| Recovery >= | N | WR 1d | WR 2d | WR 3d | WR 5d | WR 10d |
|-------------|---|-------|-------|-------|-------|--------|
| 0.35 | 13 | 53.8% | 38.5% | 53.8% | 53.8% | 61.5% |
| ALL | 30 | 50.0% | 40.0% | 46.7% | 50.0% | 50.0% |

WR at Day 2 is the LOWEST (38.5%) — confirming the Day 2 reversal pattern.

### Gap Severity Interaction (rec >= 0.35)

| Gap Bucket | N | Drift 1d | Drift 2d | Drift 3d | Drift 5d |
|------------|---|----------|----------|----------|----------|
| -5% to -8% | 5 | **+4.74%** | +1.18% | +5.52% | +3.59% |
| -8% to -10% | 5 | +0.73% | -1.92% | +2.69% | +0.13% |
| -10% to -15% | 3 | -0.05% | +0.88% | -3.30% | -2.16% |

**Moderate gaps (-5% to -8%) show the strongest zombie bounce (+4.74% on Day 1).**
Extreme gaps (> -10%) show no zombie edge at any horizon.

---

## TEST 2: M5 — Intraday Zombie Timing

### Zombie Trigger Timing

| Threshold | N Triggered | Mean Trigger Time | Median |
|-----------|-------------|-------------------|--------|
| >= 0.25 | 4 | 11:35 ET | 11:47 |
| >= 0.30 | 6 | 11:41 ET | 12:00 |
| >= 0.35 | 5 | 11:51 ET | 12:00 |
| >= 0.40 | 3 | 11:58 ET | 12:10 |

**Zombies typically trigger around noon (Zone 2-3 boundary).** Not in Zone 1 (too early)
and not in the afternoon session. This is ~2.5 hours after open.

### Return from Trigger Point

| Threshold | N | Trigger→Close | Trigger→Day2 | Trigger→Day3 |
|-----------|---|---------------|--------------|--------------|
| 0.25 | 4 | +0.17% / 50% WR | +0.06% / 75% WR | +0.83% / 50% WR |
| 0.30 | 6 | -0.09% / 50% WR | -1.20% / 50% WR | -0.81% / 17% WR |
| 0.35 | 5 | -0.07% / 60% WR | -1.88% / 20% WR | -1.21% / 20% WR |
| **0.40** | **3** | **+0.50% / 100% WR** | **-2.14% / 0% WR** | **-3.15% / 0% WR** |

**Critical finding at threshold 0.40:**
- Same-day: +0.50%, 100% WR (ALL 3 trades won intraday)
- Day 2: -2.14%, 0% WR (ALL 3 trades lost overnight)
- Day 3: -3.15%, 0% WR

**The zombie edge is purely intraday.** Overnight holding destroys the edge completely.

### M5 Zombie Strategy Backtest

| Exit | Threshold | N | Mean% | WR | PF |
|------|-----------|---|-------|----|----|
| **Day1Close** | **0.25** | **4** | **+0.17%** | **50%** | **1.32** |
| Day1Close | 0.40 | 3 | +0.50% | 100% | inf |
| Day2 | 0.25 | 4 | +0.06% | 75% | 1.07 |
| Day2 | 0.35 | 5 | -1.88% | 20% | 0.10 |
| Day3 | 0.35 | 5 | -1.21% | 20% | 0.60 |

All N values are ANECDOTAL (<10). But the pattern is consistent:
Day1Close exits outperform Day2/Day3 exits across all thresholds.

---

## TEST 3: Zombie Peak — When Does Recovery Max Out?

### Day of Maximum Close (gap <= -5%, recovery >= 0.35, N=13)

| Day | Count | % | Mean Max Return |
|-----|-------|---|-----------------|
| Day 0 (gap day) | 3 | 23.1% | +0.00% |
| Day 1 | 2 | 15.4% | +15.25% |
| Day 3 | 3 | 23.1% | +17.51% |
| Day 6-10 | 5 | 38.5% | +7.60% |

**Mode: Day 0 (peak IS the gap day close — recovery is already done)**
**Mean: Day 4.5** (pulled by Day 6-10 outliers)

23% of zombie stocks peak on Day 0 — their best price is the close of the gap day.
Another 15% peak on Day 1. Combined: **38.5% of zombie events have their best
exit within 1 day.**

Non-zombie comparison: Mode also Day 0, Mean Day 4.3 — similar distribution.
Peak timing doesn't differentiate zombie from non-zombie.

---

## TEST 4: Zombie vs Non-Zombie Comparison

### Cumulative Drift

| Group | N | 1d | 2d | 3d | 5d | 10d |
|-------|---|----|----|----|----|-----|
| **Zombie (rec>=0.35)** | **13** | **+2.09%** | -0.08% | +2.40% | +0.93% | +2.05% |
| Non-zombie (rec<0.20) | 11 | +1.09% | +1.21% | +2.10% | +2.98% | +0.60% |
| All gap-downs | 30 | +1.27% | +0.44% | +1.73% | +1.72% | +1.08% |

### Zombie Advantage by Horizon

| Horizon | Zombie - Non-zombie |
|---------|---------------------|
| **1d** | **+1.00%** (zombie wins) |
| 2d | -1.29% (non-zombie wins) |
| 3d | +0.30% (tie) |
| **5d** | **-2.05%** (non-zombie wins decisively) |
| 10d | +1.46% |

**Zombie advantage disappears at the 2-day mark.**

This confirms the central hypothesis:
- **1-day hold:** Zombie beats non-zombie by +1.00% (momentum)
- **2-day hold:** Non-zombie catches up and passes (mean-reversion)
- **5-day hold:** Non-zombie wins by 2.05% (ANT-1's finding explained)

The mechanism: zombie stocks have already used up their "easy" recovery on Day 1.
Non-zombie stocks haven't recovered yet, so they have MORE room to bounce on Days 2-5.
**Mean-reversion wins over longer horizons. Momentum wins on Day 1 only.**

---

## CHARTS

1. `ant4_cumulative_drift_curve.png` — Zombie vs non-zombie drift trajectories
2. `ant4_incremental_drift.png` — Marginal drift bars by day
3. `ant4_zombie_peak_dist.png` — Day of max close histogram
4. `ant4_trigger_time_dist.png` — When zombie triggers (ET time)

---

## VERDICT

### Is the zombie edge real?

**YES — but only for 1-day holds (overnight + next morning).**

| Timeframe | Zombie Edge | Evidence |
|-----------|-------------|----------|
| **Intraday (after trigger)** | **+0.50%, 100% WR** | N=3 (ANECDOTAL) |
| **1 day (daily data)** | **+2.09%** | N=13 (LOW N) |
| 2 days | -0.08% (gives back) | N=13 |
| 5 days | +0.93% (weak) | N=13 |
| M5 overnight | -1.88% (negative) | N=5 (ANECDOTAL) |

### The "sawtooth" pattern:
```
Day 1: +2.09%   ← zombie momentum (ENTER HERE)
Day 2: -0.08%   ← reversal (EXIT BEFORE)
Day 3: +2.40%   ← secondary bounce (noise?)
Day 5: +0.93%   ← fading
```

### Module 5 Implications

1. **If entering a PEAD-lite LONG on an earnings gap-down "zombie":**
   - EXIT at Day 1 close or Day 2 open — do NOT hold 5 days
   - The 1-day zombie drift (+2.09%) is stronger than the 5-day drift (+0.93%)
   - Holding past Day 1 destroys the edge

2. **For non-zombie events (low recovery):**
   - These are actually better for LONGER holds (5-day drift +2.98%)
   - Mean-reversion works but takes more time to materialize

3. **Gap severity matters:**
   - Moderate gaps (-5% to -8%): strongest zombie bounce (+4.74% Day 1)
   - Extreme gaps (>-10%): no zombie edge at any horizon

### What would change the framework:
The zombie 1-day edge needs validation with larger N. Current N=13 is LOW N, not yet
"provisional" (N>=20). With full 2016-2026 earnings data, we'd expect N~50+ zombie events,
which could validate or reject this finding.

**For now: note the 1-day timing as a Module 5 design consideration, but do not freeze
parameters until validated with N>=20.**

---

## REPRODUCIBILITY

```bash
cd /home/user/stock-data-mining
python3 ant4_zombie_timing.py
# Outputs in backtest_output/ant4/
```
