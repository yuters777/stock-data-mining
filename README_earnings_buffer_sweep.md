# Earnings Buffer Sensitivity Sweep — Operator Workflow

Empirical sensitivity analysis for M4/M6/M7 earnings filter parameters per PI v48 §"Earnings Policy".
Sweeps buffer values ±0/±1/±3/±5d against the pre-registered 5-criterion decision rule.
Production reference HEAD: market-engine `62bf5b1`.

---

## Prerequisites

### Data files (place all in `C:\Projects\stock-data-mining\Fetched_Data\`)

| File | Required | Purpose |
|---|---|---|
| `{TICKER}_m5_extended.csv` | Yes (all 27 tickers + SPY) | M5 intraday bars, date column ET naive |
| `earnings_calendar.csv` | Yes | Columns: `ticker, earnings_date` |
| `VIX_daily.csv` | Yes | Columns: `date, vix_close` |
| `news_index.csv` | Optional | M6 no-news filter; if absent, no-news assumed |
| `corporate_actions.csv` | Optional | M6 CA guard; if absent, CA guard skipped |

### Python packages

```
pandas >= 1.5
numpy >= 1.23
```

Verify: `python -c "import pandas, numpy; print('OK')"`

---

## Run instructions

### Step 1 — Pull branch and validate data

```bash
git pull origin claude/earnings-buffer-sensitivity-5kPd4
python scripts/earnings_buffer_sweep.py --validate-only
```

Expected output: `All required data files present` and exit 0.
If files are missing, populate `Fetched_Data\` accordingly before proceeding.

### Step 2 — Run full sweep

```bash
python scripts/earnings_buffer_sweep.py
```

Runtime estimate: 20–60 min depending on hardware and data volume.
To run a subset: `python scripts/earnings_buffer_sweep.py --modules M6,M7`

### Step 3 — Review results

Two output files are written to `scripts/`:
- `earnings_buffer_sweep_results.json` — raw metrics for all buckets
- `earnings_buffer_sweep_report.md` — human-readable table + decisions

Open `earnings_buffer_sweep_report.md` and check:
1. **Acceptance:** should show `PASS` for each module (baseline reproduction within ±5% N, ±10% PF).
   If `FAIL`, the reimplementation drifts from production — do not act on results; open issue.
2. **Decision:** shows `STATUS_QUO` or `CHANGE_TO_{N}d` per module.

### Step 4 — Apply decision rule

For each module:
- `STATUS_QUO` → no action; document as confirmed optimal.
- `CHANGE_TO_{N}d` → all 5 criteria passed; proceed per KB cascade protocol.
  Open DR for production parameter change; do not change production code directly.

---

## Output interpretation

### Metrics columns

| Column | Meaning |
|---|---|
| N | Number of trades |
| PF | Profit factor = sum(wins) / abs(sum(losses)) |
| WR | Win rate |
| Mean | Mean trade return |
| p-value | One-tailed bootstrap p-value (H0: mean ≤ 0) |
| CI low/high | 95% bootstrap CI on PF (seed=42, 1000 iterations) |

### Decision rule (all 5 must pass to recommend change)

1. New PF ≥ current_PF × 1.10
2. N ≥ 30 trades
3. 95% bootstrap CI lower bound > current_PF
4. Adjacent buffer bucket also passes criterion 1 (monotonic direction)
5. Holm-Bonferroni significant at family-wise α=0.05

**Default: STATUS_QUO.**

### Canonical baselines (acceptance gate)

| Module | Current buffer | Baseline N | Baseline PF |
|---|---|---|---|
| M4 | ±0d | 47 | 21.38 |
| M6 | ±1d | 378 | 1.68 |
| M7 | ±6d | 188 | 1.72 |

---

## Troubleshooting

**`FileNotFoundError: M5 file not found`**
→ Ticker CSV missing from `Fetched_Data\`. Check ticker spelling and file naming convention: `{TICKER}_m5_extended.csv`.

**`Acceptance: FAIL` for a module**
→ N or PF deviates >10% from canonical baseline. Possible causes: date range mismatch, timezone handling difference, or data quality issue. Do not act on sweep results. Open issue with full log.

**`MemoryError` or very slow performance**
→ Reduce `UNIVERSE` list in `earnings_buffer_sweep.py` temporarily to diagnose. Full 27-ticker sweep is memory-intensive.

**News index absent (warning)**
→ Expected if `news_index.csv` not available. M6 proceeds assuming no classified news (conservative).

**`assert len(UNIVERSE) == 27`**
→ Do not modify the `UNIVERSE` list without updating this assertion and re-validating baselines.
