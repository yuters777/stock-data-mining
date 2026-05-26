# M6 Transaction-Cost Survival Sweep

spec_id: spec_2026_05_26_002  
input: `backtest_results/m6_rth_trades_frozen.csv` (N=544, frozen read-only)  

| cost_bps | n | profit_factor | pf_undefined | expectancy | win_rate | flipped_to_loss |
|---:|---:|---:|:---:|---:|---:|---:|
| 0 | 544 | 1.4099 | False | 1.0020 | 63.42 | 0 |
| 1 | 544 | 1.4052 | False | 0.9920 | 63.42 | 0 |
| 3 | 544 | 1.3959 | False | 0.9720 | 63.42 | 0 |
| 5 | 544 | 1.3866 | False | 0.9520 | 63.42 | 0 |
| 10 | 544 | 1.3636 | False | 0.9020 | 63.42 | 0 |
| 20 | 544 | 1.3186 | False | 0.8020 | 63.42 | 0 |

**Break-point (PF ≤ 1.0 OR expectancy ≤ 0):** survives >=20bps

## Reading

M6 is a THIN-EDGE module (re-validated baseline PF 1.41, 27-ticker scope, 2021-2025 epoch): cost erosion is materially more consequential here than for M4. Expectancy and flipped_to_loss are the load-bearing metrics — PF approaching 1.0 is the real cliff, not an abstract 2× threshold. Break-point (PF ≤ 1.0 or expectancy ≤ 0) first reached at **survives >=20bps**.

## Note on thin-edge framing

At re-validated baseline PF 1.41 (27-ticker, 2021-2025), the M6 edge has limited cost headroom. Even a few basis points of round-trip cost compress expectancy significantly. Track flipped_to_loss (previously profitable trades turned losing by cost) and expectancy approaching zero to understand where the execution-cost cliff actually lies, not just the headline PF.
