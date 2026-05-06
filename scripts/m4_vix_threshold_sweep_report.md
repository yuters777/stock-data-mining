# M4 VIX Threshold Sensitivity Sweep - Report

Run date: 2026-05-06
Universe: 27 equity tickers
Date range: 2021-04-28 to 2026-05-06
Earnings buffer: 0 days (M4 standing policy)

## Per-Threshold Sweep Results

| VIX Gate | N | PF | WR | Mean Return | Verdict |
|---|---|---|---|---|---|
| 20 | 8 | 18.71 | 87.5% | +6.13% | insufficient N |
| 22 | 7 | 11.44 | 85.7% | +4.13% | insufficient N |
| 23 | 7 | 11.44 | 85.7% | +4.13% | insufficient N |
| 24 | 7 | 11.44 | 85.7% | +4.13% | insufficient N |
| 25 | 7 | 11.44 | 85.7% | +4.13% | insufficient N |
| 26 | 7 | 11.44 | 85.7% | +4.13% | insufficient N |
| 28 | 7 | 11.44 | 85.7% | +4.13% | insufficient N |
| 30 | 4 | inf | 100.0% | +6.43% | insufficient N |

## Per-Bucket Breakdown (at most-permissive threshold = 20)

Each row = trades whose VIX value at entry falls in bucket range.

| VIX Bucket | N | PF | WR | Mean Return |
|---|---|---|---|---|
| 20-22 | 1 | inf | 100.0% | +20.13% |
| 22-25 | 0 | n/a | n/a | n/a |
| 25-30 | 3 | 2.15 | 66.7% | +1.06% |
| 30-35 | 4 | inf | 100.0% | +6.43% |
| 35+ | 0 | n/a | n/a | n/a |

## Operator-Actionable Verdict

Compare per-bucket PF and N. Decision rules:

1. **Keep VIX>=25 (current frozen)** - if VIX 20-25 buckets show PF<1.0 OR N<10
2. **Lower to VIX>=22 or VIX>=23** - if VIX 22-25 bucket shows PF>=1.5 AND N>=20
3. **Raise to VIX>=30** - if VIX 25-30 bucket shows PF<1.0 (current entries actively hurt)
4. **Tier-based sizing** - if VIX 25-30 PF<2.0 but VIX>=30 PF>3.0 (split allocation)

**NOTE:** This is research-only. Production code changes require:
- DR validation (ChatGPT Pro X/10)
- Quarterly parameter window per Module 4 Spec section 9
- Forward OOS observation period per cc-acceptance discipline
