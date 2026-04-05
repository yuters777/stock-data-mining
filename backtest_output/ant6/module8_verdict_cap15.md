# Module 8 Clean Re-Test — Verdict
## ANT-6 Pass A: Method Cleanup — cap15
Date: 2026-04-05

### Best combo (Layer A): C1 → X1_D1_open

## KEY FINDING: Trigger entry DOES NOT beat control entries

Across ALL exit variants, E1 (trigger-next) loses to C1 (10:00 buy)
and C2 (noon buy). The trigger adds negative value — it delays entry
into a bounce that is already largely captured by buying at 10:00.

## Dimension Ratings

| Dimension | Rating | Evidence |
|-----------|--------|----------|
| Data integrity | PASS | 22/27 tickers with cached daily+M5 data, 5 excluded (SMCI/ARM/INTC/MSTR/JD) for lack of data. Single daily provider. |
| No look-ahead | PASS | Trigger uses running low from bars strictly prior to current bar. Entry at next bar open. |
| Universe consistency | PASS | Fixed 22-ticker universe, canonical D0 mapping, gap convention consistent. |
| Trigger adds value | **FAIL** | E1 loses to C1 on every exit. E1 loses to C2 on every exit. Trigger subtracts value. |
| Exit stability | PARTIAL | Best exit is X1_D1_open but the edge belongs to C1 (control), not trigger entries. |
| Robustness | PASS | IS mean=2.27%, OOS mean=2.34% — same sign |
| Mechanism coherence | **FAIL** | The hypothesized mechanism — that a recovery trigger identifies optimal re-entry timing — is falsified. Simple early buying (C1 at 10:00) captures the gap-fill drift without needing any trigger. The trigger's delay costs performance. |

## Final Verdict: **REJECTED**

### Fail conditions triggered:
- **Controls beat trigger entries** — C1 dominates E1/E2/E3 across all exits
- **Trigger subtracts value** — waiting for recovery confirmation misses the bounce
- **E1 mean and median both negative gross** for most exits

### What the data shows:
- Gap-down earnings reactions DO show mean-reversion toward prior close
- The reversion begins early (hence C1 at 10:00 captures it)
- Waiting for a 35% recovery trigger means entering AFTER most of the intraday bounce, leaving the trade exposed to overnight/multi-day risk
- The best strategy in this universe is simply buying at 10:00 and selling at D1 open or D1 close (C1→X1 or C1→X2)

### Implication:
Module 8's trigger mechanism is not useful. If anything, the underlying 
gap-fill phenomenon (C1 results) could be studied further, but the 
trigger itself should be retired.

## Conditioning Summary (best control: C1)

### gap_severity
| Bucket | N | Mean% | Med% | WR | PF |
|--------|---|-------|------|----|----|
| 5-8% | 10 | 2.41 | 1.17 | 70.0 | 6.82 |
| 8-10% | 4 | 0.42 | -0.75 | 25.0 | 1.19 | ◀ANECDOTAL
| 10-15% | 3 | 4.50 | 3.76 | 100.0 | 999.00 | ◀ANECDOTAL

### eps_surprise
| Bucket | N | Mean% | Med% | WR | PF |
|--------|---|-------|------|----|----|
| MISS (<-5%) | 6 | 5.25 | 3.76 | 83.3 | 20.39 | ◀ANECDOTAL
| INLINE (-5,+5) | 4 | 4.52 | 6.80 | 100.0 | 999.00 | ◀ANECDOTAL
| BEAT (>+5%) | 7 | -1.47 | -0.98 | 28.6 | 0.09 | ◀ANECDOTAL

### revenue_surprise
| Bucket | N | Mean% | Med% | WR | PF |
|--------|---|-------|------|----|----|
| MISS (<-2%) | 5 | 3.47 | 3.76 | 80.0 | 18.75 | ◀ANECDOTAL
| INLINE (-2,+2) | 3 | 3.84 | -0.75 | 33.3 | 5.85 | ◀ANECDOTAL
| BEAT (>+2%) | 9 | 1.16 | 1.17 | 66.7 | 2.09 | ◀ANECDOTAL

### release_timing
| Bucket | N | Mean% | Med% | WR | PF |
|--------|---|-------|------|----|----|
| BMO | 2 | 0.21 | 1.17 | 50.0 | 1.56 | ◀ANECDOTAL
| AMC | 15 | 2.59 | 1.30 | 66.7 | 4.19 |

### damage_class
| Bucket | N | Mean% | Med% | WR | PF |
|--------|---|-------|------|----|----|
| HARD | 1 | 3.76 | 3.76 | 100.0 | 999.00 | ◀ANECDOTAL
| MIXED | 9 | 4.60 | 3.71 | 77.8 | 16.88 | ◀ANECDOTAL
| SOFT | 7 | -0.83 | -0.75 | 42.9 | 0.43 | ◀ANECDOTAL

## Bootstrap (10,000 resamples)

- Mean 95% CI: [0.16%, 4.64%]
- Median 95% CI: [-0.98%, 3.76%]
- E1-C2 diff 95% CI: [-5.03%, 3.82%]
- E1-C2 point est: -0.59%

## IS/OOS Split (chronological 50/50)

- IS:  N=8, mean=2.27%, median=1.17%, WR=62.5%
- OOS: N=9, mean=2.34%, median=1.30%, WR=66.7%

## Top Winner Removal

- full: N=17, mean=2.31%
- remove_top1: N=16, mean=1.59%
- remove_top2: N=15, mean=1.00%

## Leave-One-Ticker-Out

| Ticker Removed | N | Mean% | WR | PF | Impact |
|---------------|---|-------|----|----|--------|
| AMD | 16 | 2.22 | 62.5 | 3.75 | -4% |
| AMZN | 15 | 2.48 | 66.7 | 4.28 | +7% |
| AVGO | 16 | 2.70 | 68.8 | 5.78 | +17% |
| BABA | 16 | 2.38 | 62.5 | 3.95 | +3% |
| BIDU | 16 | 2.50 | 68.8 | 4.28 | +8% |
| COIN | 15 | 1.44 | 60.0 | 2.67 | -38% |
| COST | 16 | 2.55 | 68.8 | 4.58 | +10% |
| GOOGL | 16 | 2.43 | 62.5 | 4.01 | +5% |
| MARA | 15 | 1.24 | 60.0 | 2.44 | -46% |
| META | 16 | 2.37 | 62.5 | 3.94 | +3% |
| MU | 16 | 2.42 | 62.5 | 3.99 | +5% |
| NVDA | 16 | 2.52 | 68.8 | 4.37 | +9% |
| PLTR | 15 | 2.70 | 66.7 | 5.61 | +17% |
