# M4 MAX_BARS Bar-by-Bar Sensitivity Sweep — Report

Run date: 2026-05-07T01:48:28
Source: backtest_results\m4_5yr_trades.csv (264 trades)
Successfully enriched: 80 / 264 trades
Variants tested: [4, 5, 6, 7, 8, 9, 10]

Counterfactual semantics: trades held within cap pass through with
actual return; trades that actually held longer are re-priced at the
close of the cap-bar (using forward-walked 4H closes from entry_date).

## Per-MAX_BARS Counterfactual Results

| MAX_BARS | N | Mean | Median | Total | WR | PF | HardMax Δ (synth-actual) |
|---|---|---|---|---|---|---|---|
| 4 | 80 | +2.23% | +0.98% | +178.51% | 55.0% | 1.98 | +3.77% (N=43) |
| 5 | 80 | +2.45% | +0.81% | +195.88% | 56.2% | 2.04 | -7.55% (N=43) |
| 6 | 80 | +1.20% | +1.07% | +96.35% | 60.0% | 1.32 | -133.55% (N=43) |
| 7 | 80 | +2.47% | +2.81% | +197.77% | 62.5% | 1.68 | -126.31% (N=43) |
| 8 | 80 | +2.26% | +3.35% | +180.55% | 62.5% | 1.56 | -155.57% (N=43) |
| 9 | 80 | +2.07% | +3.33% | +165.65% | 60.0% | 1.50 | -171.24% (N=43) |
| 10 | 80 | +3.10% | +3.28% | +247.99% | 60.0% | 2.67 | +0.00% (N=43) |

## Per-Year Breakdown

| Year | M4 mean (N) | M5 mean (N) | M6 mean (N) | M7 mean (N) | M8 mean (N) | M9 mean (N) | M10 mean (N) |
|---|---|---|---|---|---|---|---|
| 2021 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| 2022 | +0.82% (N=45) | +1.14% (N=45) | -1.73% (N=45) | -1.59% (N=45) | -2.49% (N=45) | -2.33% (N=45) | -0.98% (N=45) |
| 2023 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| 2024 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| 2025 | +4.60% (N=31) | +4.67% (N=31) | +5.18% (N=31) | +8.34% (N=31) | +9.25% (N=31) | +8.55% (N=31) | +9.10% (N=31) |
| 2026 | -0.32% (N=4) ⚠N<10 | -0.06% (N=4) ⚠N<10 | +3.45% (N=4) ⚠N<10 | +2.70% (N=4) ⚠N<10 | +1.41% (N=4) ⚠N<10 | +1.34% (N=4) ⚠N<10 | +2.54% (N=4) ⚠N<10 |

Per Principle #2: any year-bucket with N<10 marked ⚠ is anecdotal.

## Operator-Actionable Verdict

Compare per-MAX_BARS total return + per-year stability. Decision rules:

1. **Keep MAX_BARS=10** — if no other variant produces meaningfully higher total return AND lower variants don't improve 2022-type bear regime
2. **Lower to MAX_BARS=8** — if 8 produces higher total return AND maintains positive returns across all years (esp. 2025/2026)
3. **Lower to MAX_BARS=6** — if 6 produces highest total return AND 2022 bear meaningfully cuts losses without sacrificing 2025 winners
4. **Per-regime tiered MAX_BARS** — if bear-regime years prefer short, bull-regime years prefer long (would require D6/regime-aware logic)

**NOTE:** This is research-only. Production change requires DR + quarterly window per Module 4 Spec §9.
