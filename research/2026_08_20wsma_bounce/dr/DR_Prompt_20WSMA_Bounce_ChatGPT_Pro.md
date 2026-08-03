# DR PROMPT — ChatGPT Pro session: NDX/QQQ 20-week SMA bounce pattern
# (paste everything below the line; attach 5 files listed at bottom)

---

## Context

You are reviewing a finding for a discretionary trading research framework (NYSE/NASDAQ equities, crypto, cross-asset VIX; research-only, no live capital). The framework's validated modules are intraday/swing (4H mean-reversion, gap-shock reversal) gated by a VIX-based regime layer (Override 4.0) and a 4H EMA permission filter. This session evaluates a **NEW concept**: a *weekly-timeframe regime overlay* candidate — explicitly NOT a trade-signal module.

**Pattern under evaluation** (viral retail claim, source: Telegram channel, claimed "7 of 8 winners"): when Nasdaq-100 has held above its 20-week SMA for 15+ consecutive weeks, then pulls back to touch the SMA and reclaims it, the index tends to be higher 4 weeks later.

**Our internal replication (pre-registered spec, QQQ 1999-2026, 27 years):**
- Weekly bars = W-FRI resample of daily unadjusted closes. SMA20 = 20-week SMA of weekly closes.
- Precondition: ≥15 consecutive weekly closes above SMA20. TOUCH = weekly Low ≤ SMA20. SIGNAL = first weekly Close back above SMA20 (entry at that close). Return measured at Close t+4 weeks. Cooldown: next event only after streak rebuilds to ≥15.
- **Full census: N=39 events** (the viral post showed a curated 8 — its per-case numbers reproduce almost exactly, but it omitted the worst losers: Apr-2000 −14.24% (MAE −26.85%), Dec-2021 −11.40%, Mar-2004 −6.28%).
- Results: 30/39 wins (77%), mean +2.50%, median +3.70% per event.
- Baseline (all weeks with Close>SMA20 regime): 65.1% positive 4-week forward, mean +1.01% (n=976 weeks).
- Excess: +12pp hit rate, +1.49pp mean. Binomial p=0.080; t-test on means p=0.053. Marginal.
- **Era split (post-hoc sensitivity): 1999-2012 N=10, 70% win, mean −0.45%. 2013-2026 N=29, 79% win, mean +3.51%.** The entire edge lives post-2013.
- Failures cluster at trend terminations: Apr-2000, Oct-2018 (−5.98%), Dec-2021.

**Cross-sectional follow-up (27-ticker panel, 2013-2026, 29 events + 1 live), pre-registered hypotheses:**
- H1 (returns rank by trailing 52w beta): high-tercile mean +4.33% vs low +1.89%, but spread positive in only 16/29 events, Wilcoxon p=0.185 → NOT confirmed.
- H2 (market breadth at touch — share of 22 core tickers above their own 20W SMA — separates winning bounces from failures): wins 55% vs fails 52%, Mann-Whitney p=0.446 → **REJECTED in our sample**. Dec-2021 disaster had breadth 55% = exact win-average.
- H3 (semiconductors NVDA/AMD/AVGO/TSM/MU break their own SMAs *before* the index in failing events): INVERTED — fails 33% semis-below vs wins 44%, p=0.846. Before both worst failures (Dec-2021, 2022) semis-below = 0%.
- Caveat we acknowledge: only 6 failure events → very low power; "rejected" = no support, not proof of absence.
- H4 (added post-panel, pre-registered direction-only: failures concentrate when the 2Y Treasury yield is in a 26-week uptrend at touch; full 39-event census, FRED DGS2): direction-consistent but NOT confirmed — fails mean Δ26w +0.22pp vs wins +0.06pp; fail-rate 27% (2Y rising, n=22) vs 18% (falling, n=17); mean 4w return +1.35% (rising) vs +3.98% (falling); Mann-Whitney p=0.159, Fisher p=0.377. Counterexamples both ways (largest riser +1.34pp in Sep-2023 → +6.05% win; Jan-2026 failure occurred with 2Y falling). Honest status: narrative-derived from this same sample's failures, so even the directional lean is hypothesis-grade.

**Live event (pre-registered forward observation):** signal fired 2026-07-31, entry QQQ 687.99, streak-at-touch 16 weeks, evaluation at close 2026-08-28. Context: NDX in a ~10% correction from June high; semiconductor names at touch week all above their own weekly SMAs (semis-below = 0%); breadth 59%.

**Already rejected in this framework (do not re-propose):**
- #22: 4H EMA cross as *return predictor* — negative; MA constructs validated only as permission filters.
- #20: daily VIX change as directional predictor (R²→0.004).
- #19: ADX as entry-quality minimum (inverted).
- #32: Zone Gate advisor layer (killed; a rule no stage feeds does not exist).

## Research Question

Does the 20-week-SMA bounce pattern on NDX/QQQ carry exploitable conditional edge beyond long-only regime drift — and if so, which *externally validated* conditioning variables separate successful bounces from trend-terminal failures, given that our internal candidates (breadth, semis lead-lag, beta-ranking) found no support?

## Required Analysis

1. **Independent evidence.** Identify published or reputable independent studies of this pattern class (pullback-to-rising-long-term-MA on index; SentimenTrader-style event studies; academic trend-following/pullback literature). For each: sample period, result, and whether it survives baseline-drift adjustment. State "insufficient data" if you cannot source it — do not fabricate citations.
2. **Era-dependence challenge.** The edge concentrates entirely in 2013-2026. Is this consistent with known structural explanations (QE-era buy-the-dip flows, vol-targeting/passive flows, 0DTE-era dynamics)? Is there a principled reason to expect persistence out of this regime, or is the pattern an artifact of one macro era? Take a position.
3. **Conditioning variables with published validation.** Candidates: HY credit spreads (OAS level/trend), yield-curve state, VIX term structure (VIX/VIX3M), % of index members above 200-day MA, NYSE A/D line divergence, realized-vol regime. For each: is there credible published evidence it discriminates benign pullbacks from trend terminations at a weekly horizon? Rank by evidence quality. (Note: VIX/VIX3M as *daily directional* signal is already rejected in our framework — the question here is the *weekly regime* use, which is distinct.)
4. **Audit our negative results.** Critique the H2/H3 methodology (breadth definition on 22 correlated mega/growth names; touch-week timing; N=6 failures). Would a different breadth construction plausibly change the verdict, or is cross-sectional conditioning inside one index simply underpowered/too collinear here?
5. **Live-event context.** For 2026-07-31: which currently observable variables (from item 3) would most credibly discriminate this instance between the "healthy pullback" analogs (2014, 2019, 2023) and the "trend-terminal" analogs (Oct-2018, Dec-2021)? Do not predict the outcome; specify the discriminators.
6. **Verdict.** Given all above: is "provisional context-overlay" the right status (influences bias/sizing context only, never entries), or should this be archived as baseline drift + era artifact? Flag every claim as VALIDATED / PARTIALLY VALIDATED / REJECTED / NEEDS MORE DATA.

## Output Format

- Numbered sections matching the six items above.
- Explicit confidence level and evidence quality per claim.
- State "insufficient data" rather than fabricating numbers or citations.
- Reference sources where available (author/publication/year sufficient).

## Constraints

- Scope: discretionary research framework; weekly overlay candidate only — never an entry signal.
- Statistical honesty over narrative: we prefer a defensible "archive it" to an enthusiastic "trade it".
- Attached files are the full evidence set: `qqq_20wsma_events.csv` (39-event census), `qqq_20wsma_study.py` (index-study spec), `panel_events.csv` (29 events + breadth/semis readings), `panel_ticker_obs.csv` (per-ticker observations, H1), `panel_study.py` (panel spec), `h4_events_dgs2.csv` (39 events with 26-week 2Y-yield trend at touch; live-event reading: Δ26w = +0.71pp, above every historical failure's reading except one winning counterexample). Recompute from them freely; if your recomputation disagrees with our numbers, flag the divergence explicitly — divergences are the highest-value output.
