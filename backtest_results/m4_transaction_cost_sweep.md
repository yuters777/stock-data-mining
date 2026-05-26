# M4 Transaction-Cost Survival Sweep

spec_id: spec_2026_05_26_001  
input: `backtest_results/m4_5yr_trades_D6.csv` (N=44, frozen read-only)  

| cost_bps | n | profit_factor | pf_undefined | expectancy | win_rate | flipped_to_loss |
|---:|---:|---:|:---:|---:|---:|---:|
| 0 | 44 | 8.4075 | False | 6.8716 | 86.36 | 0 |
| 1 | 44 | 8.3858 | False | 6.8616 | 86.36 | 0 |
| 3 | 44 | 8.3428 | False | 6.8416 | 86.36 | 0 |
| 5 | 44 | 8.2999 | False | 6.8216 | 86.36 | 0 |
| 10 | 44 | 8.1939 | False | 6.7716 | 86.36 | 0 |
| 20 | 44 | 7.9865 | False | 6.6716 | 86.36 | 0 |

**Break-point (PF < 2.0 OR expectancy ≤ 0):** survives >=20bps

## Reading

At 0 bps the ledger exactly reproduces the D6 frozen baseline (PF 8.4075, expectancy 6.8716, WR 86.36%, N=44). Round-trip cost degrades profit factor and expectancy monotonically; the viability threshold (PF < 2.0 or expectancy ≤ 0) is first breached at **survives >=20bps**.

## Caveat — N=44 and sub-sample instability

At N=44, profit factor is dominated by a handful of large 2025 winners. The 2022 sub-sample alone shows mean −4.94% and WR 16.67%, illustrating that the aggregate PF can look cost-robust while the underlying edge is regime-dependent. **EXPECTANCY and flipped_to_loss are the load-bearing metrics, not PF.** Track expectancy approaching zero and flipped_to_loss growing to understand where the actual execution-cost cliff lies.
