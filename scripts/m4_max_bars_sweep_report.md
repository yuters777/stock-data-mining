# M4 MAX_BARS Bar-by-Bar Sensitivity Sweep — Report

Run date: 2026-05-06T22:19:10
Source: backtest_results/m4_5yr_trades.csv (28 trades)
Successfully enriched: 28 / 28 trades
Variants tested: [4, 5, 6, 7, 8, 9, 10]

Counterfactual semantics: trades held within cap pass through with
actual return; trades that actually held longer are re-priced at the
close of the cap-bar (using forward-walked 4H closes from entry_date).

## Per-MAX_BARS Counterfactual Results

| MAX_BARS | N | Mean | Median | Total | WR | PF | HardMax Δ (synth-actual) |
|---|---|---|---|---|---|---|---|
| 4 | 28 | +3.81% | +3.15% | +106.64% | 82.1% | 5.52 | +19.96% (N=18) |
| 5 | 28 | +4.09% | +2.38% | +114.43% | 85.7% | 6.30 | +22.60% (N=18) |
| 6 | 28 | +2.96% | +1.82% | +82.81% | 67.9% | 4.77 | +0.61% (N=18) |
| 7 | 28 | +3.03% | +0.88% | +84.84% | 67.9% | 3.42 | -9.18% (N=18) |
| 8 | 28 | +6.34% | +5.32% | +177.43% | 78.6% | 10.90 | +47.49% (N=18) |
| 9 | 28 | +6.12% | +5.06% | +171.47% | 78.6% | 9.61 | +41.24% (N=18) |
| 10 | 28 | +4.63% | +4.15% | +129.75% | 71.4% | 4.95 | +0.00% (N=18) |

## Per-Year Breakdown

| Year | M4 mean (N) | M5 mean (N) | M6 mean (N) | M7 mean (N) | M8 mean (N) | M9 mean (N) | M10 mean (N) |
|---|---|---|---|---|---|---|---|
| 2025 | +4.21% (N=26) | +4.48% (N=26) | +3.18% (N=26) | +3.31% (N=26) | +7.10% (N=26) | +6.84% (N=26) | +5.40% (N=26) |
| 2026 | -1.42% (N=2) ⚠N<10 | -1.09% (N=2) ⚠N<10 | +0.02% (N=2) ⚠N<10 | -0.59% (N=2) ⚠N<10 | -3.56% (N=2) ⚠N<10 | -3.21% (N=2) ⚠N<10 | -5.27% (N=2) ⚠N<10 |

Per Principle #2: any year-bucket with N<10 marked ⚠ is anecdotal.

## Operator-Actionable Verdict

Compare per-MAX_BARS total return + per-year stability. Decision rules:

1. **Keep MAX_BARS=10** — if no other variant produces meaningfully higher total return AND lower variants don't improve 2022-type bear regime
2. **Lower to MAX_BARS=8** — if 8 produces higher total return AND maintains positive returns across all years (esp. 2025/2026)
3. **Lower to MAX_BARS=6** — if 6 produces highest total return AND 2022 bear meaningfully cuts losses without sacrificing 2025 winners
4. **Per-regime tiered MAX_BARS** — if bear-regime years prefer short, bull-regime years prefer long (would require D6/regime-aware logic)

**NOTE:** This is research-only. Production change requires DR + quarterly window per Module 4 Spec §9.
