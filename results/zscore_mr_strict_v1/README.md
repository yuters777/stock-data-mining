# Backtest #3 — Z-score Mean Reversion (STRICT ORIGINAL) — results artifact

First close of the agent product loop. Agent-discovered hypothesis `bb94b900`
(`XBT3K/MeanReversionAlgo`), backtested strictly per
`PreReg_backtest_3_zscore_MR_strict_v1.md` (governing) and
`CC_backtest_spec_3_zscore_MR_strict_v1.md` (execution).

Harness: `scripts/zscore_mr_backtest.py`. **VERDICT: GOOD** (see `results.md`).

## STEP-1 engine-compatibility finding
`scripts/m4_backtest_5yr.py` is **hard-coded to the Module-4 streak/EMA mechanic**
(entry = 3 consecutive down 4H bars + VIX≥25 + RSI<35; exit = first close≥EMA21 or
10-bar max) and is **LONG-ONLY with no position reversal**. It therefore cannot
express a z-score long/short flipper (different mechanic; needs shorts + reversal +
hold-through-neutral). Per pre-reg §6 we did **not** shoehorn z-score into
streak/EMA params. We built a standalone harness that **reuses the engine's metric
functions** `m4_backtest_5yr.stats()` / `profit_factor()` (pure functions of a
trade-return list, not coupled to M4) and implements only the flipper
trade-construction the engine cannot represent. The engine computes no drawdown,
so max-DD is computed here and **proved equal to a server-side SQL computation**
(`equality_proof.json`; max abs PF diff across 27 tickers = 4.7e-05).

## Data / universe / params (locked, pre-reg §1–§2)
- Source: **research.db `bars_m5`** (5,068,651 bars, 28 tickers, 2021-04-19 → 2025-12-31),
  accessed read-only. This is the pre-reg's named source (the repo's `Fetched_Data/*.csv`
  is a *different* snapshot — different universe, coverage to 2026-04 — and was **not** used).
- Universe: **27 equity = 28 minus SPY** (the one non-equity).
- window=20; z=(close−SMA20)/STD20 (sample std, ddof=1); z>+1.5 SHORT, z<−1.5 LONG, else hold.
- Flipper: position = sign of last extreme; reverse **only** on opposite ±1.5; same-side
  repeats and neutral band HOLD; no stop/TP/z→0 exit. Entry & exit at flip-bar close.
- Per-trade return = `position*(exit−entry)/entry*100` (engine long-only formula generalized to shorts).
- **Costs = engine default = 0** (base m4 engine subtracts none; pre-reg forbids adding).

## Headline result
| set | N | PF | win% | mean%/trade | max DD (additive %) |
|---|--:|--:|--:|--:|--:|
| raw (as-is) | 164,631 | 3.717 | 67.74 | 1.0551 | 399.53 |
| ex-glitch (primary) | 164,559 | **1.2571** | 67.72 | 0.0999 | 399.53 |

- 27/27 tickers execute (thousands of trades each); 24/27 PF>1; per-ticker PF median 1.184;
  exactly 1 unclosed position/ticker (not degenerate); long/short ~50/50; ~74% of bars neutral.
- **Data-glitch finding:** META has 72 trades with >2,400% returns from **corrupt bars**
  (Aug–Sep 2021 prints at ~$15 vs real ~$370). The naive strategy has no corruption guard
  (the M4 engine's `flag_corrupt` would catch it — a finding). These inflate the *raw* aggregate;
  the **primary** figure removes |ret|>500% trades using the engine's own 6× corruption threshold.
  Only META is affected. Verdict is robust either way (both PFs > 1.1).
- **Caveat:** zero-cost upper bound. A ~165k-trade no-stop flipper would not survive realistic
  transaction costs; per-trade edge is ~+0.10%/trade. GOOD = the discovered mechanic is
  backtestable and shows positive *raw* edge before any risk/cost overlay — what pre-reg §4 tested.

## Files
- `results.md` — full results table + verdict + SQL↔engine equality proof.
- `summary.json` — machine-readable (verdict, params, aggregate, per-ticker).
- `per_ticker.csv` — per-ticker metrics (27 rows).
- `equality_proof.json` — engine-`stats()` vs server-side SQL, per ticker (condition #1).
- `backtest3_trades.sqlite.gz` — all 164,631 trades (the per-trade queryable store; see below).

## Reproduce
Canonical (architect, with a local copy of research.db):
```
python scripts/zscore_mr_backtest.py --db /path/to/research.db --out results/zscore_mr_strict_v1
```
This CC run had only read-only MCP access to research.db (no local file, 1000-row cap), so the
**identical** flipper SQL (`TRADES_SQL` in the harness) was executed server-side and the per-trade
output parsed via `--mcp-dumps`. Both paths produce the same numbers (the equality proof confirms it).

Query the per-trade store (read-only, no re-run needed):
```
gunzip -k backtest3_trades.sqlite.gz
sqlite3 backtest3_trades.sqlite \
  "SELECT ticker, COUNT(*) n, ROUND(AVG(ret),4) mean_pct FROM backtest3_trades GROUP BY ticker ORDER BY ticker;"
```
Columns: `ticker, exit_ts, ret (%), position (+1 long / −1 short), hold (bars)`.
