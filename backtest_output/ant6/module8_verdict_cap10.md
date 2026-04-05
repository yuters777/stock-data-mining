# Module 8 Clean Re-Test — Verdict
## ANT-6 Pass A: Method Cleanup — cap10
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
| Robustness | PASS | IS mean=2.18%, OOS mean=1.51% — same sign |
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

### eps_surprise
| Bucket | N | Mean% | Med% | WR | PF |
|--------|---|-------|------|----|----|
| MISS (<-5%) | 5 | 5.55 | 3.71 | 80.0 | 18.08 | ◀ANECDOTAL
| INLINE (-5,+5) | 2 | 4.17 | 7.17 | 100.0 | 999.00 | ◀ANECDOTAL
| BEAT (>+5%) | 7 | -1.47 | -0.98 | 28.6 | 0.09 | ◀ANECDOTAL

### revenue_surprise
| Bucket | N | Mean% | Med% | WR | PF |
|--------|---|-------|------|----|----|
| MISS (<-2%) | 3 | 2.27 | 0.61 | 66.7 | 7.95 | ◀ANECDOTAL
| INLINE (-2,+2) | 3 | 3.84 | -0.75 | 33.3 | 5.85 | ◀ANECDOTAL
| BEAT (>+2%) | 8 | 0.93 | 1.17 | 62.5 | 1.78 | ◀ANECDOTAL

### release_timing
| Bucket | N | Mean% | Med% | WR | PF |
|--------|---|-------|------|----|----|
| BMO | 2 | 0.21 | 1.17 | 50.0 | 1.56 | ◀ANECDOTAL
| AMC | 12 | 2.11 | 0.61 | 58.3 | 3.08 |

### damage_class
| Bucket | N | Mean% | Med% | WR | PF |
|--------|---|-------|------|----|----|
| MIXED | 8 | 4.32 | 3.71 | 75.0 | 14.27 | ◀ANECDOTAL
| SOFT | 6 | -1.46 | -0.75 | 33.3 | 0.15 | ◀ANECDOTAL

## Bootstrap (10,000 resamples)

- Mean 95% CI: [-0.61%, 4.65%]
- Median 95% CI: [-0.98%, 3.71%]
- E1-C2 diff 95% CI: [-5.64%, 4.78%]
- E1-C2 point est: -0.52%

## IS/OOS Split (chronological 50/50)

- IS:  N=7, mean=2.18%, median=0.40%, WR=57.1%
- OOS: N=7, mean=1.51%, median=0.61%, WR=57.1%

## Top Winner Removal

- full: N=14, mean=1.84%
- remove_top1: N=13, mean=0.92%
- remove_top2: N=12, mean=0.12%

## Leave-One-Ticker-Out

| Ticker Removed | N | Mean% | WR | PF | Impact |
|---------------|---|-------|----|----|--------|
| AMD | 13 | 1.70 | 53.8 | 2.71 | -8% |
| AMZN | 13 | 2.11 | 61.5 | 3.42 | +14% |
| AVGO | 13 | 2.28 | 61.5 | 4.29 | +24% |
| BABA | 13 | 1.89 | 53.8 | 2.90 | +3% |
| BIDU | 13 | 2.04 | 61.5 | 3.18 | +11% |
| COIN | 12 | 0.68 | 50.0 | 1.63 | -63% |
| COST | 13 | 2.10 | 61.5 | 3.40 | +14% |
| GOOGL | 13 | 1.95 | 53.8 | 2.96 | +6% |
| MARA | 13 | 0.92 | 53.8 | 1.92 | -50% |
| META | 13 | 1.88 | 53.8 | 2.89 | +2% |
| MU | 13 | 1.94 | 53.8 | 2.95 | +5% |
| NVDA | 13 | 2.06 | 61.5 | 3.24 | +12% |
| PLTR | 13 | 2.30 | 61.5 | 4.41 | +25% |
