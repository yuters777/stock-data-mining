# ANT-4 Follow-Up: Zombie Trigger-Price Returns

**Date:** 2026-04-05
**Purpose:** Compute actual returns from realistic zombie entry point (trigger price),
not from Day 1 close.

---

## M5 Zombie Trigger Returns

Entry at M5 bar where recovery first crosses threshold (after 10:00 ET).

| Thresh | N | Trigger→Close | Trigger→Day2 | Trigger→Day3 | Trigger→Day4 | Trigger→Day5 |
|--------|---|---------------|--------------|--------------|--------------|--------------|
| 0.35 | 9 | +0.64% / 56% WR | -1.24% / 33% WR | -2.25% / 22% WR | -2.32% / 22% WR | -3.74% / 44% WR |
| 0.40 | 7 | +1.02% / 71% WR | -1.24% / 29% WR | -3.44% / 14% WR | -3.07% / 14% WR | -5.22% / 29% WR |

### Individual M5 Trades (threshold 0.35)

| Ticker | Date | Gap | Trigger Time | →Close | →Day2 | →Day3 |
|--------|------|-----|-------------|--------|-------|-------|
| AAPL | 2025-05-02 | -3.2% | 10:10 | +0.1% | -3.1% | -3.3% |
| AMD | 2025-02-05 | -10.0% | 12:00 | +1.2% | -0.5% | -2.9% |
| AMD | 2025-04-30 | -3.4% | 10:05 | +4.1% | +3.3% | +5.6% |
| COIN | 2025-02-14 | -3.4% | 12:00 | -1.6% | -5.0% | -7.2% |
| COST | 2025-03-07 | -3.1% | 13:35 | +0.9% | -2.2% | -2.7% |
| MARA | 2025-11-07 | -3.6% | 10:00 | +4.9% | +2.7% | -3.3% |
| META | 2025-10-30 | -11.0% | 12:30 | -2.0% | -4.6% | -6.1% |
| PLTR | 2025-05-06 | -9.1% | 11:00 | -0.5% | +1.0% | +8.9% |
| PLTR | 2025-11-04 | -7.4% | 10:00 | -1.2% | -2.7% | -9.4% |

---

## Daily Zombie: Estimated Trigger-Price Returns

**Trigger price estimate:** `day1_low + 0.35 * |prior_close - day1_open|`
This approximates where a trader would enter after seeing 35% recovery.

**N = 13 zombie events** (gap <= -5%, recovery_ratio >= 0.35)

| Horizon | N | Mean Return | Median | WR | Flag |
|---------|---|-------------|--------|-----|------|
| D1 Close | 13 | +7.66% | +2.96% | 100.0% | LOW N |
| Day 2 | 13 | +10.28% | +3.49% | 84.6% | LOW N |
| Day 3 | 13 | +7.66% | +4.45% | 69.2% | LOW N |
| Day 4 | 13 | +10.37% | +6.00% | 69.2% | LOW N |
| Day 5 | 13 | +7.68% | +4.34% | 84.6% | LOW N |
| Day 6 | 13 | +8.73% | +4.08% | 69.2% | LOW N |
| Day 10 | 13 | +9.77% | +6.87% | 84.6% | LOW N |

### Key Findings

1. **From trigger price, Day 1 close gives +7.66% mean return.**
   This is the "remaining runway" after zombie confirmation.

2. **Day 2 return from trigger: +10.28%** — 
   maintains from trigger entry.

3. **Day 3 return from trigger: +7.66%** —
   still positive.

### Comparison: Trigger Entry vs Day 1 Close Entry

The ANT-4 main test measured drift from Day 1 close. Trigger-price entry is EARLIER
(mid-day), so it captures more of the Day 1 recovery AND the overnight move.

| Entry Point | Day 2 Return | Day 3 Return |
|-------------|-------------|-------------|
| Day 1 Close (ANT-4) | drift_1d = +2.09% | drift_2d = -0.08% |
| Trigger Price (this) | +10.28% | +7.66% |

### Individual Events

| Ticker | Date | Gap% | Trigger$ | D1Close | Day2 | Day3 | Day5 |
|--------|------|------|---------|---------|------|------|------|
| AMD | 2025-02-05 | -9.9% | $110.66 | +1.2% | -0.5% | -2.8% | +0.4% |
| AMZN | 2024-08-05 | -8.2% | $156.40 | +3.0% | +3.5% | +4.1% | +6.7% |
| AMZN | 2026-02-06 | -9.0% | $207.31 | +1.5% | +0.7% | -0.2% | -3.7% |
| ARM | 2024-02-09 | -6.9% | $104.85 | +9.9% | +42.1% | +14.4% | +27.5% |
| ARM | 2025-04-04 | -6.2% | $86.51 | +1.4% | +2.4% | -0.8% | +16.1% |
| BABA | 2022-10-24 | -12.2% | $58.01 | +3.4% | +3.5% | +12.2% | +4.3% |
| BABA | 2024-05-14 | -5.9% | $76.47 | +0.1% | +1.9% | +9.1% | +11.1% |
| BIDU | 2022-07-29 | -5.4% | $133.69 | +2.2% | +1.0% | +0.4% | +4.8% |
| COIN | 2022-05-12 | -9.6% | $42.64 | +37.2% | +59.2% | +44.7% | +47.8% |
| COIN | 2022-11-11 | -6.7% | $47.45 | +21.1% | +12.2% | +17.0% | +2.8% |
| MSTR | 2022-01-24 | -14.9% | $33.86 | +9.4% | +7.8% | +4.5% | +0.1% |
| SMCI | 2024-08-28 | -11.3% | $41.68 | +6.4% | +7.7% | +5.0% | +1.6% |
| SMCI | 2024-10-31 | -9.1% | $28.27 | +3.0% | -7.9% | -7.9% | -19.7% |

---

## Verdict

The trigger-price perspective confirms ANT-4's finding: zombie entry captures
meaningful same-day recovery, but multi-day holding is uncertain.
