# GN-1 Feasibility Report — stock-data-mining harness

**Mode:** READ-ONLY inventory. No code edited, no backtest run, nothing committed/pushed.
**Repo:** `stock-data-mining` @ branch `claude/compassionate-darwin-36jw6b`
**Question:** Can this harness faithfully run the frozen GN-1 strategy on 2021-04-19 → 2025-12-31?

---

## Executive summary

The repo contains a **close-cousin runnable harness** (`scripts/m4_backtest_5yr.py`) that already
implements the same data family, the **EMA21 + max-bars dual exit**, a **VIX daily gate**, and
**LONG-only mean-reversion** entries at the trigger bar close. It does **not** implement the GN-1
**σ-band trigger** (`close ≤ EMA21 − 2σ`), the **rolling stdev**, or the **ADX(4H)** gate, and its VIX
gate is wired as `VIX ≥ 25` (GN-1 needs `VIX < 20`). All missing pieces are small, additive, and the
building blocks (an ADX function, rolling-std via pandas) already exist elsewhere in the tree.

Full-range **spot** VIX is already on disk and git-tracked (`Fetched_Data/VIX_daily_fmp.json`, 1,264
rows, 2021-03-23 → 2026-03-23) — **no FMP GET was needed**. M5 data for **22 of the 27** canonical
universe tickers is committed and covers the full period; **5 tickers have no M5 data at all**.

**VERDICT (one line at bottom):** YES — runnable faithfully after the stand-up list, with one caveat
on universe completeness.

---

## Q1 — Harness + strategy interface

There are **two** candidate harnesses in the tree:

| Harness | What it is | Fit for GN-1 |
|---|---|---|
| `scripts/m4_backtest_5yr.py` (+ `scripts/_backtest_lib_m4.py`, `scripts/_data_loaders.py`) | Self-contained 4H mean-reversion backtest over `Fetched_Data/*.csv`. Long-only, EMA21 exit, max-bars exit, daily VIX gate. | **Primary candidate** — same data family & exit logic as GN-1. |
| `backtester/` package (`backtester.py` + `core/*`) | A *different* strategy: "False Breakout" with D1 level detection, pattern engine, filter chain, risk/trade managers (`backtester/backtester.py:1-21`). M5 bar-by-bar, level-proximity driven. | **Not a fit** — wrong strategy family; would be a rewrite, not an adaptation. |

**How a strategy is defined/run in the primary candidate:** it is *not* a pluggable strategy
interface — the rules are hard-coded inside `backtest_ticker()`. The loop discovers tickers
(`get_tickers`, `m4_backtest_5yr.py:256`), builds 4H bars (`build_4h`, `:137`), computes indicators
inline, then walks bars applying gate → trigger → exit (`backtest_ticker`, `:295-399`). To run GN-1 you
adapt this function's gate/trigger blocks (or clone it).

`scripts/_backtest_lib_m4.py` is a parallel, cleaner reimplementation (`run_module4_backtest`,
`:81`) that consumes `*_m5_extended.csv` via `_data_loaders.load_m5_extended` — but **note** those
`*_m5_extended.csv` files are **not present** on disk (the data is `*_data.csv`), so the directly
runnable path today is `scripts/m4_backtest_5yr.py`, which reads `*_data.csv`.

### 8-primitive table (decomposing the GN-1 rules)

| # | GN-1 primitive | Status | Evidence |
|---|---|---|---|
| 1 | **M5 → 4H resample, RTH-only** | **PRESENT** | `build_4h()` `m4_backtest_5yr.py:137-193` (auto-detects ET vs UTC, RTH filter, 2 sessions/day); also `aggregate_m5_to_4h_rth()` `_data_loaders.py:27-71`. *Caveat:* repo "4H" = 2 RTH bars/day (09:30–13:30 + 13:30–16:00 ET), not calendar-4H. This is the data family the agent uses. |
| 2 | **EMA(21) on 4H close** | **PRESENT** | `bars["ema21"] = bars["Close"].ewm(span=21, adjust=False).mean()` `m4_backtest_5yr.py:310`; also `compute_ema_21()` `_backtest_lib_m4.py:44`. |
| 3 | **ADX(4H) gate (<20)** | **ADAPTABLE** | ADX functions exist but are **not** wired into the M4 harness: `adx14()` (DI=14/ADX-smooth=20) `scripts/ema_cross_part1_data.py:144`; `compute_adx(daily, period=14)` in `backtester/run_cscv_pbo.py:78` and ~8 sibling `run_*.py`. Pre-computed `adx_14` also sits in `data/indicators_4h/*_4h_indicators.csv` but only spans **2025-02 → 2026-03** (not full period). Must add an ADX call on 4H bars + a `< 20` gate. |
| 4 | **Rolling σ = stdev(close − EMA21) over 50×4H** | **MISSING** | No such computation anywhere in the M4 path. Trivial to add (`(close-ema21).rolling(50).std()`), but absent today. |
| 5 | **Trigger: close ≤ EMA21 − 2σ** | **MISSING** | M4's trigger is *3 consecutive down bars + RSI(14)<35* (`backtest_ticker` `:330-341`, and `_backtest_lib_m4.py:126-144`). The σ-band breach is a different trigger; must replace. |
| 6 | **VIX-level regime gate** | **PRESENT (wrong threshold/direction)** | Daily VIX load + prior-day lookup present: `load_vix()` `m4_backtest_5yr.py:48`, `prior_vix()` `:286`, gate at `:329-330` — but coded as `vix_val < 25 → skip` (i.e. requires VIX≥25). GN-1 needs `VIX < 20`. Flip the comparator. |
| 7 | **LONG-only entry at trigger bar close** | **PRESENT** | Entry `entry_price = closes[i]` at trigger bar `m4_backtest_5yr.py:353`; long-only by construction (`return_pct = (exit-entry)/entry`). |
| 8 | **Dual exit: first close ≥ EMA21 OR hard-max 10 bars** | **PRESENT (exact match)** | `m4_backtest_5yr.py:361-377`: loop `i+1 .. i+10`, exit when `closes[j] >= emas[j]` (`exit_type="ema21"`) else at `bars_held==10` (`exit_type="hard_max"`). Identical to GN-1 exit. |

So of the 8: **4 PRESENT**, **1 PRESENT-needs-threshold-flip** (#6), **1 ADAPTABLE** (#3 ADX), **2
MISSING** (#4 rolling σ, #5 σ-band trigger). None are hard; all the missing math is one-to-three lines
of pandas plus an existing ADX helper.

---

## Q2 — Performance output

**Yes — PF, N, and mean return are all emitted**, two independent implementations:

- `stats()` `m4_backtest_5yr.py:478-493` returns dict with keys **`n`** (trade count), **`mean`** (mean
  return %), **`pf`** (profit factor), plus `wr`, `sharpe`. Profit factor = `wins.sum()/abs(losses.sum())`
  (`:484`).
- Written to disk in `main()`:
  - **`backtest_results/m4_5yr_trades.csv`** — per-trade ledger (`df.to_csv`, `:629`); columns include
    `return_pct`, `bars_held`, `exit_type`, `vix_at_entry`, `rsi_at_entry` (`:384-395`).
  - **`backtest_results/m4_5yr_summary.json`** — `overall`/`by_year`/`by_vix`/… blocks (`:631-642`); the
    `overall` block carries `n`, `mean`, `pf`, `wr`, `sharpe`, `avg_hold`, `ema21_exit_pct`,
    `hardmax_pct`.
- Independent metrics lib `scripts/_metrics.py:9` `compute_metrics()` returns **`N`, `PF`, `mean`**, `WR`,
  `std`, `t_stat`, `p_value`, bootstrap `ci_low/ci_high` — usable as-is for the GN-1 run.

---

## Q3 — M5 data inventory (`Fetched_Data/`)

- **Reader actually used:** `scripts/m4_backtest_5yr.py` reads `Fetched_Data/*_data.csv` via
  `get_tickers()` (`:256`) → `pd.read_csv` (`:298`).
- **Format/columns:** `Datetime, Open, High, Low, Close, Volume, Ticker` (verified on `AAPL_data.csv`).
- **Timezone:** **UTC**, extended-hours included (e.g. first AAPL bar `2021-04-21 11:00:00` UTC = 07:00
  ET pre-market; `build_4h` auto-detects UTC because max hour > 16 and applies RTH 13:30–19:55 UTC).
- **Range (all 22 present universe tickers):** first bar **2021-04-21**, last bar **2026-04-10/11**.
  Covers the required 2021-04-19 → 2025-12-31 window (minus the first 2 calendar days 04-19/04-20, which
  precede the data start — negligible).
- **Per-ticker size:** ~4–8 MB, ~76,800 rows (AAPL) of M5.

**Universe coverage vs the canonical 27** (`scripts/audits/m4_baseline_probe/_constants.py:27`,
`CANONICAL_UNIVERSE`):

- **Present (22):** AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA, AMD, PLTR, AVGO, TSM, MU, COST, COIN,
  MARA, C, GS, V, BA, JPM, BABA, BIDU.
- **MISSING M5 entirely (5):** **SMCI, ARM, INTC, MSTR, JD** — no `*_data.csv` on disk.
- Note: `Fetched_Data` also has `SNOW_data.csv`, `TXN_data.csv`, `IBIT_data.csv` (present on disk but
  **not** in the canonical 27), plus `SPY`, `VIXY`, `BTC`, `ETH` (excluded). The current
  `m4_backtest_5yr.py` `EXCLUDE` set (`:29`) drops IBIT/SNOW/TXN, yielding ~22 tickers — which happens to
  equal the canonical-present set.

**Bottom line:** all 27 are **not** present for the full range; **22/27 are**, full-period. Standing up
the *exact* 27-ticker universe requires fetching M5 for 5 missing tickers.

---

## Q4 — VIX inventory

| File | Columns | Range | Rows | Spot or 3M? | Full-range spot? |
|---|---|---|---|---|---|
| `Fetched_Data/VIX_daily_fmp.json` | `date, close` (JSON array) | 2021-03-23 → 2026-03-23 | **1,264** | **Spot (FMP `^VIX`)** | ✅ **YES** |
| `backtester/data/vix_daily.csv` | `date, vix_close` | 2022-01-03 → 2026-04-01 | 1,094 | Spot | ❌ misses 2021-04…12 |
| `Fetched_Data/VIX_daily.csv` | `date, vix_close` | 2025-02-10 → 2026-03-12 | 281 | Spot | ❌ ~1yr only |
| `Fetched_Data/VIXCLS_FRED_real.csv` | `observation_date, VIXCLS` | 2025-02-10 → 2026-03-12 | 284 | Spot (FRED) | ❌ ~1yr only |
| `Fetched_Data/VXVCLS.csv` | `observation_date, VXVCLS` | 2021-03-23 → 2026-03-23 | 1,305 | **VIX3M (NOT spot)** | ❌ wrong series |

**Full-range daily spot VIX is already on disk:** `Fetched_Data/VIX_daily_fmp.json` (1,264 rows,
2021-03-23 → 2026-03-23) — this is exactly what `m4_backtest_5yr.py:load_vix()` prefers first
(`:59-74`). It fully covers 2021-04 → 2025-12. **No FMP GET was performed or needed** (the allowance was
not used). The `backtester/data/vix_daily.csv` path (loaded by `_data_loaders.load_vix_daily`, which
actually reads `VIX_daily.csv`, `:101-107`) starts in 2022 and is **insufficient** — do not use it for
the GN-1 gate.

---

## Q5 — Execution environment

- **CC is running in the CLOUD**, on Linux (`/home/user/stock-data-mining`, `Linux 6.18.5`). The Windows
  host `C:\Projects\stock-data-mining` is **not visible** — only the freshly-cloned repo is.
- **Data committed in the repo (no sync needed):** despite `.gitignore` listing `Fetched_Data/*.csv` and
  `data/*.csv`, the files are **force-tracked** — `git ls-files` confirms **33** tracked
  `Fetched_Data/*.csv`, plus `Fetched_Data/VIX_daily_fmp.json`, `backtester/data/vix_daily.csv`, and the
  `data/indicators_4h/*.csv`. So the 22 universe M5 files + full-range spot VIX are present in the clone
  and need **no** data push.
- **Must be synced/fetched before an exact-27 run:** M5 for the **5 missing tickers** (SMCI, ARM, INTC,
  MSTR, JD). If a 22-ticker run is acceptable, **zero** data sync is required.

---

## STAND-UP LIST (describe only — not implemented)

To run the frozen GN-1 rules faithfully on 2021-04-19 → 2025-12-31:

**Data**
1. **VIX:** none needed — use the on-disk full-range spot file `Fetched_Data/VIX_daily_fmp.json`
   (1,264 rows). (Do *not* use `backtester/data/vix_daily.csv` — starts 2022; nor `VXVCLS.csv` — it's
   VIX3M.)
2. **Universe gap:** fetch M5 (`*_data.csv`, same schema/UTC) for the **5 missing canonical tickers**
   — **SMCI, ARM, INTC, MSTR, JD** — into `Fetched_Data/`. *Or* explicitly down-scope GN-1 to the
   22 available tickers and document it. (Heads-up: ARM IPO'd 2023-09 and INTC/the others have full
   history; SMCI/MSTR availability for 2021-04 should be confirmed when fetched.)

**Code (adapt a clone of `scripts/m4_backtest_5yr.py::backtest_ticker`, keeping build_4h + the dual exit
verbatim):**
3. **Flip the VIX gate** to GN-1: replace `vix_val < 25 → skip` (`:330`) with `vix_val >= 20 → skip`
   (require `VIX < 20`). Remove the M4 RSI gate (`:334-337`) and the streak gate (`:339-341`).
4. **Add ADX(4H) gate:** compute ADX on the 4H `bars` (reuse `adx14()` from
   `scripts/ema_cross_part1_data.py:144`, or `compute_adx` from `backtester/run_cscv_pbo.py:78`),
   then `if adx[i] >= 20: skip`. Decide ADX period (GN-1 says "ADX(4H)" without N — default Wilder
   ADX(14); the existing `adx14` uses ADX-smoothing 20, so parameterize).
5. **Add rolling σ + σ-band trigger:** `dev = bars["Close"] - bars["ema21"]; sigma =
   dev.rolling(50).std()`; trigger when `closes[i] <= emas[i] - 2*sigma[i]` (and `sigma[i]` not NaN).
   This replaces the streak/RSI trigger.
6. **Keep verbatim:** the LONG entry at trigger-bar close (`:353`) and the dual exit
   (`first close ≥ EMA21` or `10`-bar hard max, `:361-377`).
7. **Set the date filter** to 2021-04-19 → 2025-12-31 (the M4 5yr script has no explicit start/end clamp;
   add one, e.g. filter `bars` by `ts` like `_backtest_lib_m4.py:109-111`).
8. **Universe/exclude:** set the ticker set to the canonical 27 (drop the M4 `EXCLUDE` of IBIT/SNOW/TXN;
   add the 5 fetched tickers); keep SPY excluded.
9. **Output:** reuse `stats()`/`_metrics.compute_metrics` and the existing
   `backtest_results/*_trades.csv` + `*_summary.json` writers — already emit PF, N, mean.

Estimated change surface: ~30–40 lines inside one cloned function, plus one ADX import. No new
framework.

---

## VERDICT

**YES** — this harness (`scripts/m4_backtest_5yr.py`) can run the frozen GN-1 strategy faithfully after
the stand-up list: full-range spot VIX and the EMA21/dual-exit/long-MR machinery are already present;
the only code additions are ADX(4H), a 50-bar rolling σ, the −2σ trigger, and flipping the VIX gate to
`<20`. **Caveat:** faithful execution of the *exact 27-ticker* universe additionally requires fetching
M5 for 5 missing tickers (SMCI, ARM, INTC, MSTR, JD); with the 22 on-disk tickers it runs today with
**zero** data sync.
