# GN-1 — Neutral-Regime Stretch Reversion — Label Report

**Pre-registration realized:** `PreReg_…_good-novel_v2` (LOCKED).
**Script:** `scripts/gn1_neutral_stretch_backtest.py` · **Run:** single, full period.
**Data commit:** the 5 added tickers (SMCI/INTC/JD/MSTR/ARM) come from commit
`ba89bb7` ("Add 5 missing tickers … for GN-1 backtest"), cherry-picked from
`origin/claude/compassionate-sagan-RxS4Q` into this working branch (content
identical; provenance noted for traceability). Universe = **27** equity tickers.

---

## (e) LABEL

> **Frozen criterion (applied once):**
> `GOOD = N≥40 AND PF≥1.5 AND mean>0` · `marginal = 1.0<PF<1.5 or N<40` · `BAD = PF≤1.0`

**Raw full-corpus numbers:** `N = 58`, `PF = 1.646`, `mean = +1.1449%`.

- N = 58 ≥ 40 ✓
- PF = 1.646 ≥ 1.5 ✓
- mean = +1.1449% > 0 ✓

## ➜ **LABEL = GOOD** — qualified **"regime-fragile GOOD"**

The full-corpus result satisfies GOOD, but the out-of-sample half fails
(`OOS PF = 0.814 < 1.0`, negative mean). Per the spec's own instruction
("if full=GOOD but OOS PF<1.0, note 'regime-fragile GOOD'"), the label is a
**regime-fragile GOOD**: the edge is concentrated in the in-sample period and
does not persist out-of-sample. See caveats below before trusting it.

---

## (a) Numbers — full corpus + informative IS/OOS split

| Split | Window | N | PF | mean/trade | win-rate | sum-ret | Sharpe |
|-------|--------|---|----|-----------|----------|---------|--------|
| **FULL** | 2021-04-19 → 2025-12-31 | **58** | **1.646** | **+1.1449%** | 53.45% | +66.41% | 1.453 |
| IS  | 2021-04-19 → 2024-06-30 | 26 | 3.869 | +3.0903% | 65.38% | +80.35% | 2.506 |
| OOS | 2024-07-01 → 2025-12-31 | 32 | 0.814 | −0.4357% | 43.75% | −13.94% | −0.461 |

IS/OOS is **informative, not gating** (the label is computed from the full
corpus only). Time split ≈ 68/32 (months); the trade split (26/32) reflects
when triggers actually fired. Numbers are reproducible from
`backtest_results/gn1_trades.csv` (verified: independent recompute of N/PF/mean/
WR/sum from the CSV matches the summary exactly).

---

## (b) Sanity counters

| Counter | Value |
|---------|-------|
| 4H bars scanned (27 tickers, in-period) | 34,283 |
| bars after **VIX < 20** gate | 24,151 |
| bars after **VIX < 20 AND ADX(4H) < 20** gate | 5,980 |
| **−2σ triggers** (eligible, gated) | 120 |
| **trades entered** (after one-position-per-ticker / no-stacking) | 58 |

Funnel is monotone and plausible: 34,283 → 24,151 (VIX) → 5,980 (ADX, the
binding gate — 4H ADX runs high) → 120 (−2σ stretch) → 58 trades. `trades (58) ≤
triggers (120)` because a new trigger inside an open position's hold window is
skipped (no stacking). No counts are implausibly round.

**Trades per ticker** (no single-ticker dominance — top is INTC at 9/58 = 15.5%):

| INTC | SMCI | JD | BA | BIDU | AVGO | TSLA | AMD | ARM | BABA | COIN | MSFT | TSM | V | AMZN | C | COST | GOOGL | MARA | MSTR | MU | NVDA | PLTR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 9 | 7 | 5 | 4 | 4 | 3 | 3 | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |

Zero trades: **AAPL, GS, JPM, META** (regime/stretch intersection never fired).

---

## (c) Realized-rule checklist — every §1 rule → exact code

| §1 frozen rule | Realization in code | `file:line` |
|----------------|---------------------|-------------|
| Regime gate **VIX < 20** | `prior_vix(date,vix)` (most-recent daily spot VIX before bar date); skip if `≥ VIX_MAX` (=20) | `gn1:176-179`, const `gn1:66`; reuses `m4_backtest_5yr.py:286-291` (prior_vix) + `load_vix` `:48-103` (FMP spot json) |
| Regime gate **ADX(4H) < 20** | `adx14(H,L,C)` on 4H bars; skip if `≥ ADX_MAX` (=20) | `gn1:144,180-183`, const `gn1:67`; reuses `ema_cross_part1_data.py:144-187` (Wilder ADX) |
| **Stretch trigger** `close ≤ EMA21 − 2σ` | `entry_price <= ema_val - SIGMA_MULT*sigma_val` | `gn1:190-192` |
| `EMA21` | `Close.ewm(span=21, adjust=False).mean()` | `gn1:141` |
| `σ = stdev(close−EMA21)` over **50×4H** | `resid = Close-ema21; resid.rolling(50).std()` (≥50-bar warm-up) | `gn1:142-143` |
| **LONG only** | long entry; `ret=(exit−entry)/entry` | `gn1:189,215` |
| **Entry = trigger bar close** | `entry_price = closes[i]` | `gn1:189` |
| **Exit = first close ≥ EMA21, else 10-bar hard-max** | dual-exit loop (EMA-cross or `bars_held==10`) | `gn1:199-213` (reuses structure of `m4_backtest_5yr.py:361-377`) |
| **Universe = 27 equity** (excl. SPY/VIXY/crypto) | `get_tickers()` → 27 | `gn1:270`; reuses `m4_backtest_5yr.py:256-282` + `EXCLUDE` `:29` |
| **Period** 2021-04-19 → 2025-12-31, cap 23:55 UTC | truncate raw to `[START,END]` before resample | `gn1:69-70,130` |
| Leading-bar hygiene (drop leading V=0 & O=H=L=C) | `drop_leading_degenerate()` | `gn1:84-105,131` |

M4's streak/RSI/VIX≥25 entry logic is **not** imported or used. No RSI gate,
no streak gate (confirmed: `rsi14`, `calc_streak`, `backtest_ticker` are never
referenced by the GN-1 script).

---

## (d) Sample trades (first 5 / last 5) — exit obeys "EMA21-cross or 10-bar"

| # | ticker | entry_ts | entry_px | exit_ts | exit_px | bars | ret% | exit |
|---|--------|----------|----------|---------|---------|------|------|------|
| 1 | INTC | 2021-07-19 13:30 | 54.2050 | 2021-07-21 13:30 | 55.9120 | 4 | +3.149 | ema21 |
| 2 | INTC | 2021-07-23 13:30 | 52.4399 | 2021-07-30 13:30 | 53.5900 | 10 | +2.193 | hard_max |
| 3 | JD | 2021-07-26 13:30 | 66.7500 | 2021-07-29 13:30 | 71.6100 | 6 | +7.281 | ema21 |
| 4 | INTC | 2021-10-12 13:30 | 52.2450 | 2021-10-14 13:30 | 53.7750 | 4 | +2.929 | ema21 |
| 5 | SMCI | 2021-10-18 17:30 | 3.4970 | 2021-10-25 17:30 | 3.5330 | 10 | +1.030 | hard_max |
| … | | | | | | | | |
| 54 | TSLA | 2025-11-07 17:30 | 426.8800 | 2025-11-10 17:30 | 448.1900 | 2 | +4.992 | ema21 |
| 55 | TSLA | 2025-11-13 13:30 | 410.3500 | 2025-11-20 13:30 | 427.8100 | 10 | +4.255 | ema21 |
| 56 | V | 2025-11-17 17:30 | 327.9600 | 2025-11-21 17:30 | 329.8000 | 8 | +0.561 | ema21 |
| 57 | BABA | 2025-12-15 13:30 | 150.4000 | 2025-12-22 13:30 | 150.0900 | 10 | −0.206 | hard_max |
| 58 | COST | 2025-12-15 17:30 | 857.0800 | 2025-12-22 17:30 | 849.6900 | 10 | −0.862 | hard_max |

All exits are `ema21` (close crossed back ≥ EMA21) or `hard_max` (exactly 10
bars held). `bars_held ∈ [2,10]`. Spot-checked trade #1 against independently
rebuilt 4H bars: entry gate (close 54.205 ≤ band 54.506; ADX 15.06<20; prior-VIX
19.22<20) and exit (first close≥EMA21 at +4 bars) both reproduce exactly.

---

## ⚠ Material caveats (read before trusting the GOOD label)

The label is **honestly GOOD by the frozen formula**, but two structural facts
qualify it heavily:

1. **Out-of-sample failure (regime-fragile).** All of the edge is in-sample:
   IS PF 3.87 vs OOS PF 0.81 (OOS mean −0.44%). The full-corpus PF is buoyed by
   2021–2024. A practitioner should treat this as fragile, not robust.

2. **Return is concentrated in the 5 newly-added, full-coverage tickers.**
   ARM/INTC/JD/MSTR/SMCI = 24/58 trades (41%) but **+64.15% of the +66.41% total
   sum-return (96.6%)**. The original 22 tickers are ~net-flat (+2.26% over 34
   trades). Root cause is a **data-coverage asymmetry**, not per-ticker logic:
   the 5 added files have ~full daily coverage (~1,246–1,265 trading days,
   ≈2,365 4H bars each) while the original `*_data.csv` files are sparse
   (~502–686 unique days, ≈780–1,090 bars) — i.e. they are missing ~40–55% of
   trading days. All 27 tickers are processed identically (same `build_4h`, same
   indicators, same gates); the asymmetry is purely in the input data.

3. **3 trades span data gaps** (BA, V, MSFT: 26–31 calendar days for 8–10 4H
   bars), a consequence of the sparse original data combined with the frozen
   exit being defined in *4H bars*, not calendar time. Net effect ≈ +5%;
   removing them does **not** change the label.

These do not alter the computed label (the spec forbids post-hoc adjustment),
but they bound its trustworthiness. The operator, as keeper of the frozen
pre-reg, should weigh them.

---

## Implementation notes (reuse + judgment calls, for operator verification)

- **No costs/slippage** modeled — consistent with the M4 baseline family
  (stated per §2 trade-accounting note).
- **VIX join — prior-trading-day, lookahead-free.** Reuses `m4.prior_vix` (most
  recent daily spot VIX **strictly before** the bar's date), with M4's gate
  threshold flipped `≥25 → <20` (per §2.1, which frames GN-1's gate as a
  modification of M4's VIX gate). The §2.1 parenthetical "daily VIX applies to
  that day's 4H bars" is realized lookahead-free (prior daily close), matching
  the M4 family and avoiding intraday look-ahead. *If the pre-reg intended a
  strict same-day close join, that is the one place to adjust.*
- **EMA21 = plain `EMA(close,21)`** per §2.3's explicit formula; the only
  warm-up is the 50-bar σ window. M4's post-gap 21-bar EMA "warm-up mask"
  (`m4_backtest_5yr.py:236-252`, applied to `_data.csv` in M4) is **not** applied
  here, because it is not part of the GN-1 frozen contract and adding it would
  alter the trigger's EMA definition. (This decision was fixed at design time,
  before the run, not chosen on the result.) Practical impact is confined to the
  sparse original tickers, which are net-flat regardless.
- **Split-corruption guard** (`flag_corrupt`, 6× price-jump) **is** reused, as it
  is part of the exact exit machinery (`m4:361-377`) the spec instructs to reuse;
  on this (split-adjusted) data it flags nothing material.
- **One run only.** No parameter sweeps, no threshold nudging, no re-run for a
  better number. All frozen constants are module-level and not exposed as
  tunables. No bug-fix re-run was needed (the first run verified clean).

---

## Files
- `scripts/gn1_neutral_stretch_backtest.py` — the backtest (single entry point).
- `backtest_results/gn1_summary.json` — full/IS/OOS stats, counters, per-ticker.
- `backtest_results/gn1_trades.csv` — all 58 trades (label reproducible from this).
- `GN1_label_report.md` — this report.
