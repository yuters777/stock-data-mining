# S15-CC v2: Parallel Strategic Blind Spot Discovery (Corrected)
**Date:** 2026-03-15
**Model:** Claude Opus 4.6
**Session:** S15-CC v2 (parallel with ChatGPT Pro S15)
**Scope:** Exit strategy, position sizing, orthogonal signals, crypto edge, build priority
**Correction:** v1 incorrectly analyzed against the retired Config A' backtester. This version addresses the actual system: discretionary TradingView-based Temporal Framework.

---

## Scope Correction

v1 grounded analysis in the `backtester/` codebase (Config A' — retired March 6, 2026). That was wrong. The actual trading system is:

- **Execution:** Human discretionary via TradingView (Premium)
- **Primary filter:** EMA 9/21 cross on 4H, read visually
- **Scoring:** TSS = 0.40×EMA + 0.25×DMI_ADX + 0.20×RSI + 0.15×Squeeze + 0.10×Volume_bonus (computed mentally)
- **Regime:** Override 3.0 (VIX z-score + dVIX/dt), read from VIX chart overlay
- **Temporal:** 5-Zone Grid with regime conditioning (validated S12 H6, promoted)
- **Entry:** M5 Sub-State (Pullback → EMA9 Test → Hold/Fail) + A/B/C Buckets (v1, just created)
- **Advisory:** LLM Trading Council (3-model consensus, FastAPI — architecture designed in S13)
- **Alerts:** Telegram bot (planned, architecture in S13)
- **Track record:** 5 observation days, 0 live trades with Temporal Framework. No statistical performance data.

All recommendations below target this discretionary workflow. No backtester code modifications.

---

## Q1: Exit Strategy — Resolve the Horse Race

### The Real Question
"I entered a long on a 4H EMA 9/21 cross UP with TSS confirmation. When do I close?" Three candidates:
- **(A)** Wait for 4H EMA 9/21 cross DOWN
- **(B)** ATR trailing stop on 4H
- **(C)** Hybrid: first-to-trigger

### Context From Prior Sessions
- S12 H6 validated the 5-Zone temporal grid with regime conditioning
- S13 validated A/B/C entry buckets and flagged that BreakQuality needs N=50+ for calibration
- S11 validated TWAP detection and morning exhaustion patterns
- You have NO exit performance data — the horse race is theoretical until you trade

### Top 3 Recommendations

**Rank 1: Hybrid (C) with Regime-Dependent ATR Multiplier — But Reframe the Question**
- **HIGH VALUE**
- The literature on discretionary trend-following exits converges on one finding: **no single exit method dominates across regimes** (Covel, "Trend Following," 2004; Clenow, "Following the Trend," 2013). This is why the horse race is unresolvable in theory — it must be resolved empirically with YOUR data.
- **However**, for a system with zero track record, you need a starting point. The hybrid (C) is correct as a default because it provides downside protection (ATR trail) while allowing full trend capture (EMA cross):

  **Proposed hybrid logic (discretionary, on TradingView):**
  1. **Initial stop:** Below the M5 pullback low that formed your entry (the EMA9 test hold). This is your A/B/C bucket-defined risk.
  2. **Trail activation:** Once price moves 1.5× your initial stop distance in your favor, activate a trailing stop at 2.0× ATR(14) on 4H below the highest close.
  3. **Trail tightening:** If 4H EMA9 flattens (slope approaching zero), tighten trail to 1.5× ATR(14). This catches momentum deceleration before the full EMA cross DOWN.
  4. **Hard exit:** 4H EMA 9/21 cross DOWN = close remaining position. This is the backstop.
  5. **Zone override:** If in Zone 5 (Power Hour) and trade is profitable, wait for MOC imbalance data at 15:50 ET before exiting. Per S12 H6, Power Hour is directional resolution.

- **Why NOT pure EMA cross (A):** The 4H EMA cross DOWN is lagging by definition — you give back 1-2 full 4H bars of profit (4-8 hours of price action). On a $300 ticker moving $8/day (TSLA), that's potentially $3-5 per share of give-back. For intraday where you hold 2-6 hours, this is a significant fraction of the entire move.
- **Why NOT pure ATR trail (B):** ATR trail alone gets shaken out by normal intraday noise. A 2.0× ATR(14) trail on M5 is too tight; on 4H it's reasonable but you lose the trend-structure signal that EMA cross provides.
- **Evidence:** Kaufman ("Trading Systems and Methods," 6th ed.) shows hybrid exits (trend confirmation + volatility trail) outperform either standalone by 15-25% in risk-adjusted terms on daily data. The effect is amplified on intraday data due to higher noise.
- **Implementation:** Pine Script ATR Trailing Stop indicator exists on TradingView (built-in, free). Overlay it on your 4H chart alongside EMA 9/21. Visually manage: exit when EITHER trail is hit OR EMA crosses. No code needed.
- **Effort:** 30 minutes to set up TradingView layout. Zero cost.

**Rank 2: Time-Based Partial Exit as a Regime-Independent Safety Net**
- **HIGH VALUE**
- Your system is intraday. Positions opened in Zone 2 (10:00-11:30) have 4.5-6 hours of runway. Positions opened in Zone 4 (14:00-15:00) have 1-2 hours. Yet both use the same exit rules.
- **Recommendation:** Add a time-decay partial exit rule:
  - If position is open >3 hours AND profitable → take 50% off
  - If position is open >3 hours AND at breakeven → tighten stop to breakeven
  - If position is open >3 hours AND losing → re-evaluate: is the 4H EMA structure still intact?
- **Rationale:** This is not in the academic literature because institutions don't generally time-limit intraday holds. But for a discretionary trader with ONE shot per setup, protecting open profits against the inevitable late-day volatility is more valuable than maximizing tail gains.
- **Implementation:** Set a TradingView alert at entry_time + 3 hours. Manual decision at alert.
- **Effort:** 5 minutes per trade setup. Zero cost.

**Rank 3: Exit Differences — Equity vs Crypto ETFs**
- **MEDIUM VALUE**
- For IBIT/ETHA/COIN, exits should respect the equity-wrapper microstructure validated in S12 H3/H4:
  - **IBIT/ETHA:** Do NOT hold through the closing cross (15:50-16:00 ET) expecting crypto momentum. The closing price is determined by MOC/LOC imbalance + AP NAV arbitrage, not by BTC/ETH spot direction. If your trailing stop hasn't triggered, exit at 15:45 ET or accept the closing cross outcome.
  - **COIN:** Treat as a pure equity. COIN's price is driven by COIN-specific fundamentals (revenue, regulatory risk) layered on crypto correlation. Exit the same as TSLA or any other high-vol equity.
- **Regime difference:** On VIX >25 days, IBIT's closing discount widens (per S12 H3: -0.82% midday, -0.30% close on VIX +12% day). If you're long IBIT on a rising-VIX day, exit earlier — the closing cross will pull your position toward a discounted NAV.
- **Implementation:** Mental rule + TradingView alert at 15:45 ET for crypto ETF positions. Zero cost.

### Divergence Prediction
ChatGPT Pro will likely recommend:
1. Chandelier Exit (ATR-based, popular in trend-following literature)
2. Parabolic SAR as an alternative trailing mechanism
3. Possibly regime-specific exit selection tables

**I disagree on Parabolic SAR** because: it accelerates too aggressively for intraday holds — SAR convergence on M5 produces premature exits during normal consolidation. Chandelier is essentially what I'm recommending (ATR trail below highest high), so expect convergence there. **The key divergence will be:** ChatGPT Pro will likely NOT address the time-based partial exit (Rank 2) because it's a practitioner heuristic, not an academic method. I think it's the most practically valuable for a new discretionary trader. **HIGH VALUE divergence.**

---

## Q2: Position Sizing Methodology

### The Real Question
"I have a $50-100K account, zero track record with the Temporal Framework, just-created A/B/C entry buckets, and I'm about to take my first live trade. How do I size?"

### Top 3 Recommendations

**Rank 1: Fixed Fractional at 0.5% with Manual Kill Switch — The Only Correct Answer for N=0**
- **HIGH VALUE**
- With zero track record, **every sizing formula that requires historical parameters is inapplicable.** Kelly requires win rate and win/loss ratio. Optimal f requires a trade distribution. Vol-targeting requires realized portfolio volatility. You have none of these.
- The Config A' backtester produced PF 1.71 and Sharpe 1.82 — but that's a DIFFERENT STRATEGY (false breakout) on different entry/exit logic. You cannot apply those statistics to the Temporal Framework. The standing rejection of "Config A' automated" reinforces this boundary.
- **Starting position:**
  - **Risk per trade: 0.50% of account** ($250-500 on $50-100K)
  - This is a practitioner consensus starting point (Van Tharp, "Trade Your Way to Financial Freedom"; Elder, "Trading for a Living")
  - Conservative enough to survive 10 consecutive losers (5% drawdown) while learning
  - Aggressive enough that wins are psychologically meaningful (avoiding the "playing with toy money" trap that distorts discretionary decision-making)
- **Kill switch:** If cumulative loss exceeds 5% of account in any rolling 20-trade window, stop trading for 1 week. Review every trade. This is more important than the sizing formula.
- **Graduation:** After 30 trades with documented results, compute realized Kelly fraction and adjust. Not before.
- **Implementation:** Calculator on phone or simple spreadsheet. `position_size = (account × 0.005) / stop_distance_per_share`.
- **Effort:** 5 minutes. Zero cost.

**Rank 2: A/B/C Bucket Multipliers — Start Conservative, Let Data Differentiate**
- **HIGH VALUE**
- Your A/B/C buckets (pullback depth, reclaim speed, consolidation tightness) are just-created with no performance data. Assigning aggressive differentiation (e.g., A=1.5×, C=0.5×) before validation is premature optimization.
- **Starting multipliers:**
  - **A (ideal setup — all criteria met):** 1.0× base risk (full 0.50%)
  - **B (acceptable — 2 of 3 criteria met):** 0.75× base risk (0.375%)
  - **C (marginal — 1 of 3 criteria met):** 0.50× base risk (0.25%)
- **Track the labels.** Every trade entry, record A/B/C classification in your trade log BEFORE the trade resolves. After 30 trades, compute WR and avg R per bucket. If A-trades significantly outperform, widen the multiplier spread. If performance is uniform across buckets, your A/B/C criteria need refinement, not your sizing.
- **This is the critical insight:** A/B/C sizing is useless without A/B/C classification being predictive. Proving classification accuracy comes BEFORE optimizing size differentials.
- **Implementation:** Add A/B/C column to your trade log spreadsheet/journal.
- **Effort:** 1 minute per trade. Zero cost.

**Rank 3: Regime-Dependent Sizing via Override 3.0 — Reduce, Never Increase**
- **MEDIUM VALUE**
- Override 3.0 gives you a regime assessment (ON = normal conditions, OFF = elevated risk). Map this to sizing:
  - **Override ON (normal regime):** Full size per A/B/C bucket
  - **Override Stage 1 (elevated VIX z-score):** 0.75× multiplier on all positions
  - **Override Stage 2 (two-stage OFF confirmation):** 0.50× multiplier OR no new entries
  - **GeoStress active:** No new entries. Period.
- **Direction of adjustment:** ONLY reduce. Never size UP based on regime. "Low VIX = I should go bigger" is how discretionary traders blow up. Low VIX means lower reward, not lower risk.
- **The CryptoOverride weighting (0.7E+0.4C / 0.6C+0.4E):** Keep it as a regime classification tool (described in Q4 below) but do NOT map it to sizing multipliers. The weighting tells you which signal set to prioritize, not how much to bet. These are different questions.
- **Implementation:** Mental checklist before each trade: "What is Override state? Apply multiplier."
- **Effort:** 10 seconds per trade. Zero cost.

### Divergence Prediction
ChatGPT Pro will likely recommend:
1. Kelly Criterion with estimated parameters
2. Volatility targeting (e.g., 10-15% annualized portfolio vol)
3. Possibly Risk Parity across tickers

**I strongly disagree on Kelly with estimated parameters** at N=0. Kelly is garbage-in-garbage-out — estimating WR and payoff ratio from "it feels like this system should have 45% WR" produces meaningless sizing. The v1 analysis computed Kelly from Config A' data (different strategy) — that was wrong and I correct it here. **ChatGPT Pro may make this same error** by accepting the framework description and estimating Kelly from theoretical performance. This is the highest-value divergence prediction for Q2.

**Volatility targeting** has merit in theory but requires daily position adjustment, which conflicts with intraday hold periods and discretionary entry timing. It's the right framework for a portfolio of swing trades, not intraday trend-following.

---

## Q3: Orthogonal Information Gaps

### Context Correction
v1 correctly identified VIX term structure and market breadth as top orthogonal signals. These recommendations stand — but the implementation path changes from "add to `filter_chain.py`" to "add to TradingView layout + Telegram alerts."

### Top 3 Recommendations

**Rank 1: VIX Term Structure Slope — TradingView Implementation**
- **HIGH VALUE**
- Add `VIX/VIX3M` ratio as a TradingView chart or watchlist column:
  - TradingView has `CBOE:VIX` and `CBOE:VIX3M` as free symbols
  - Create a simple ratio: `CBOE:VIX / CBOE:VIX3M`
  - Display on a separate pane on your main layout
  - **Decision rule:** Ratio > 1.0 (backwardation) = Override 3.0 input toward OFF state. Ratio < 0.85 (steep contango) = complacency, watch for reversal. Ratio 0.85-1.0 = normal.
- **Integration with Override 3.0:** This should be a NAMED INPUT to your Override assessment. When you evaluate Override state, VIX term structure slope is one of the factors alongside VIX z-score and dVIX/dt. It provides a different dimension: VIX level tells you "how scared the market is now," term structure tells you "how scared the market expects to be."
- **Telegram alert trigger:** If your architecture follows S13 design, add a threshold alert: `VIX/VIX3M crosses above 1.0` → Telegram notification "Term structure inverted — Override input: caution."
- **Evidence:** Mixon (2007) shows VIX term structure backwardation predicts subsequent realized vol increases with R² ~0.15 at daily frequency — modest but genuinely orthogonal to price-based signals. More importantly, Konstantinidi and Skiadopoulos (2011) show that term structure carries information about future volatility beyond what VIX level alone provides.
- **Effort:** 15 minutes on TradingView. Pine Script for custom alert: ~30 lines, 1 hour.
- **Cost:** $0 (TradingView Premium already has these symbols).

**Rank 2: Market Breadth (%Above 20 EMA) — TradingView Watchlist + Override Input**
- **HIGH VALUE**
- TradingView provides `MMTW` (% of stocks above 20-day MA) as a built-in symbol. Add to your layout.
- **Decision rule:**
  - MMTW > 60%: Broad participation, longs favored. Your EMA 9/21 UP cross is aligned with the market.
  - MMTW 40-60%: Neutral, no adjustment.
  - MMTW < 40%: Narrow/declining participation, long signals face headwind. Require higher TSS for long entries (e.g., TSS ≥ 0.70 instead of default threshold). Short signals favored.
- **Why this is orthogonal:** Your TSS is computed from individual-ticker indicators (EMA, ADX, RSI, Squeeze, Volume). Breadth tells you about the market's aggregate condition — a stock can have a perfect TSS while the market is deteriorating underneath it. This catches the "last bull standing" trap.
- **Integration:** Breadth becomes a Layer 2 (Regime) input, alongside Override 3.0 and VIX term structure. It doesn't override Override — it provides context for borderline cases.
- **Effort:** 5 minutes to add to TradingView layout. 1 hour for Pine Script alert.
- **Cost:** $0.

**Rank 3: Sector Relative Strength (XLK/SPY, XLE/SPY) — Directional Context**
- **MEDIUM VALUE**
- Your 38-ticker watchlist spans multiple sectors (tech: NVDA/AAPL/META, financials: JPM/GS/C, energy-adjacent: oil correlation, China ADRs: BABA/BIDU). Sector rotation provides directional context that individual-stock indicators miss.
- **Implementation:** Add ratio charts to TradingView:
  - `XLK/SPY` (tech relative strength)
  - `XLF/SPY` (financials)
  - `KWEB/SPY` (China tech — directly relevant to BABA/BIDU)
- **Decision rule:** If your signal is long NVDA but XLK/SPY is making lower highs on 4H, the sector headwind reduces your edge. Downgrade from A-bucket to B-bucket or skip.
- **Why not higher ranked:** Sector rotation is daily/weekly information applied to intraday trades — the coarseness limits its value. But it's free, takes 5 minutes to set up, and catches the "right stock, wrong sector" error.
- **Effort:** 10 minutes. Zero cost.

### What I Upgraded from v1
- **Put/Call ratio demoted.** In v1, I ranked it #3. On reflection, for a discretionary TradingView workflow, put/call ratio is a "check once in the morning" signal — it won't change your intraday decisions. Sector relative strength is more continuously useful.

### What I'm NOT Recommending (Retained from v1)
- **GEX/DIX:** $50+/month, not on TradingView, declining edge. SKIP.
- **Order flow / Level 2:** Wait for IB Pro. No framework without data.
- **Credit spreads (HY-IG):** Too slow-moving for intraday. Track it if curious but don't trade on it.
- **Options-derived signals (skew, gamma profile):** Theoretically valuable but requires real-time options data not available in your stack. TradingView has basic options chains but not the derived analytics (GEX computation, skew curves). DEFER until you have infrastructure.

### Divergence Prediction
ChatGPT Pro will likely recommend:
1. Options-derived signals (GEX, dark pool prints, unusual options activity)
2. Intermarket analysis (bonds/TLT as equity context)
3. Possibly sentiment indicators (AAII, CNN Fear/Greed)

**I disagree on options-derived signals** for the same reasons as v1 (cost, data availability). **TLT/bonds is a reasonable suggestion** I didn't include — if ChatGPT Pro recommends it, consider adding `TLT` or `US10Y` to your TradingView layout. Bond yields moving sharply while equities are flat IS an orthogonal signal. But it's a slower-moving signal than VIX term structure, so I rank it below my top 3.

**Sentiment indicators (AAII, Fear/Greed):** These update weekly (AAII) or daily (F&G) — far too coarse for intraday decisions. If ChatGPT Pro recommends these, it's thinking about swing trading, not intraday.

---

## Q4: Crypto-Specific Edge

### Context Correction
v1 correctly identified that IBIT/COIN/MARA are stocks, not crypto. That stands. The corrected question: "Should we keep the CryptoOverride weighting (0.7E+0.3C for equity, 0.6C+0.4E for crypto-adjacent), and what else is useful for crypto-adjacent equity trading?"

### Top 3 Recommendations

**Rank 1: Keep CryptoOverride Weighting — But Reframe as Signal Source Priority, Not Sizing**
- **HIGH VALUE**
- The 0.7E+0.3C (equity trades) / 0.6C+0.4E (crypto-adjacent trades) concept is sound as a **signal priority framework:**
  - When assessing NVDA for entry: 70% weight on equity signals (TSS, EMA cross, breadth, VIX) + 30% weight on crypto context (BTC trend, DVOL). This means: check crypto context for confirmation but don't let BTC price action override your equity analysis.
  - When assessing IBIT for entry: 60% weight on crypto context (BTC 4H structure, DVOL, funding rate) + 40% weight on equity context (SPX direction, VIX, breadth). This means: BTC's chart matters more than SPX for IBIT direction, but equity market conditions still affect IBIT's spread, liquidity, and closing behavior.
- **What this ISN'T:** It's not a position sizing multiplier. Don't bet 0.7× on NVDA and 0.6× on IBIT. The weights determine which signals you prioritize in your discretionary assessment, not how much you bet.
- **Refinement:** The 0.7/0.3 and 0.6/0.4 splits are arbitrary starting points. Track prediction accuracy: when crypto context disagreed with equity signals, who was right? After 20 such events, adjust the weights.
- **Implementation:** Mental model + trade log column: "crypto/equity signal agreement: Y/N."
- **Effort:** Zero implementation. Just awareness.

**Rank 2: BTC Realized Vol vs DVOL Spread — Crypto Regime Indicator for IBIT/COIN**
- **MEDIUM VALUE**
- You already have Deribit DVOL API access. The spread between DVOL (implied vol) and BTC realized vol is a crypto-specific regime signal:
  - **DVOL > realized vol (vol premium):** Options market expects more volatility than is occurring. Crypto is in "calm before the storm" mode. Be cautious with IBIT longs — a vol expansion event could create sharp moves.
  - **DVOL < realized vol (vol discount):** Market is under-pricing volatility. This often occurs AFTER a move, when options premiums haven't caught up. Safer for trend-following entries on IBIT because the move is underway but options market is still pricing pre-move vol.
  - **DVOL ≈ realized vol:** No edge from this signal.
- **TradingView implementation:** DVOL is available on TradingView (`DERIBIT:DVOL`). Realized vol can be approximated with a custom Pine Script using ATR or standard deviation of returns.
- **Comparison to equity VIX:** This is the crypto analogue of your VIX z-score. Just as VIX z-score informs Override 3.0 for equities, DVOL spread should inform CryptoOverride for IBIT/COIN entries.
- **Effort:** 1-2 hours Pine Script for realized vol overlay. Add DVOL to layout: 2 minutes. Zero cost.

**Rank 3: Funding Rate as a Telegram Alert (Not a Trading Signal)**
- **LOW VALUE** (but minimal effort)
- Funding rates on Binance/Bybit perp futures don't directly drive IBIT price. But extreme funding (>0.05% per 8h for >24h) indicates crowded positioning in crypto perps, which occasionally spills into equity-wrapped crypto via sentiment contagion.
- **Implementation:** Don't build a trading rule. Add a Telegram alert (via your planned bot) that fires when BTC funding rate on Binance exceeds ±0.05% for 3 consecutive 8h periods. Treat as context, not signal.
- **Free data:** Binance API is free, no account needed for public endpoints (`/fapi/v1/fundingRate`).
- **Standing rejections respected:** This is NOT "funding rate predicts IBIT direction" (which would violate your rejections). It's "funding rate alerts you to crowded positioning" — purely informational.
- **Effort:** 30 minutes API integration if building the Telegram bot per S13 architecture. Zero cost.

### What I'm NOT Recommending (Retained from v1)
- **On-chain metrics (MVRV, SOPR, exchange flows):** Predict BTC spot, not IBIT equity. Glassnode costs $29-799/month. SKIP.
- **OI analysis as entry signal:** Standing rejections cover crypto-leads-equity signals. OI is useful context but not actionable for equity-wrapped crypto.

### Divergence Prediction
ChatGPT Pro will likely present a comprehensive on-chain analytics framework with MVRV, SOPR, exchange net flows, and possibly whale wallet tracking. **I predict this will be the single largest divergence between our sessions.** ChatGPT Pro will treat your crypto exposure as if you're trading BTC spot on Binance. You're not — you're trading IBIT on NYSE. The entire on-chain toolkit is designed for direct crypto markets and has minimal relevance to equity wrappers. **HIGH VALUE divergence.**

---

## Q5: Build Prioritization

### Context Correction
v1 recommended backtester code modifications (Monte Carlo in `scripts/`, entry time analysis in `analyzer.py`, VIX integration in `filter_chain.py`). All wrong — the backtester is retired.

The actual build priority should target: TradingView layout, Telegram bot, LLM Council prompts, and trade journaling.

### Top 3 Recommendations

**Rank 1: Trade Journal with Structured Classification — Before Anything Else**
- **HIGH VALUE** — This is the single most important build item.
- You have zero track record. Every recommendation in Q1-Q4 includes "after 20-30 trades, calibrate." Without a structured journal, you cannot calibrate anything.
- **Minimum viable journal (spreadsheet is fine):**

  | Column | Purpose |
  |--------|---------|
  | Date/Time | When |
  | Ticker | What |
  | Zone (1-5) | Temporal context |
  | Override State | Regime context |
  | TSS Score (est.) | Signal quality |
  | A/B/C Bucket | Entry quality |
  | Entry Price | Execution |
  | Stop Price | Risk defined |
  | Exit Price | Outcome |
  | Exit Reason | EMA cross / trail / time / manual |
  | Exit Zone | When exited |
  | P&L ($) | Result |
  | P&L (R) | Normalized result |
  | Crypto/Equity Signal Agreement | CryptoOverride validation |
  | Notes | Qualitative observations |

- **Why this outranks everything:** TradingView indicators, Telegram alerts, and Council prompt upgrades are all optimizations of a system that hasn't been validated. A trade journal is the validation mechanism itself. Without it, you're optimizing blind.
- **Effort:** 2 hours to set up Google Sheet with formulas. Zero cost.
- **After 30 trades:** Compute WR, PF, avg R overall AND per-zone, per-bucket, per-regime. This data unlocks every subsequent optimization.

**Rank 2: TradingView Layout Optimization — Add Orthogonal Signals**
- **HIGH VALUE** — Immediate visual upgrade to decision quality.
- Based on Q3 recommendations, add to your TradingView layout:

  **New panes/overlays (in priority order):**
  1. `CBOE:VIX / CBOE:VIX3M` ratio (custom, ~5 min setup)
  2. `MMTW` — % stocks above 20-day MA (built-in symbol)
  3. `DERIBIT:DVOL` — crypto implied vol (for IBIT/COIN days)
  4. `XLK/SPY`, `XLF/SPY`, `KWEB/SPY` — sector rotation ratios

  **Pine Script indicators to build or install:**
  1. **ATR Trailing Stop on 4H** — for Q1 hybrid exit. Built-in indicator exists, just add to layout.
  2. **TSS Dashboard** — Pine Script panel showing computed TSS components in real-time. This removes the mental computation burden and makes your process more consistent.
     - EMA 9/21 cross state (above/below + angle)
     - ADX value + DI+/DI- positions
     - RSI(14) value
     - Squeeze state (BB inside Keltner)
     - Volume vs 20-period MA ratio
     - Weighted sum displayed as single number
  3. **Zone Clock** — Simple Pine Script that colors the chart background by current zone (green=Zone 2/5, yellow=Zone 4, red=Zone 3, neutral=Zone 1). This prevents zone-identification errors during fast markets.

  **Estimated effort:** ATR trail = 5 min (add built-in). TSS dashboard = 2-4 hours Pine Script. Zone clock = 1-2 hours Pine Script. Watchlist additions = 15 min.
  **Total:** ~1 day. Zero cost.

**Rank 3: LLM Council Prompt Upgrade — Integrate Prior Session Knowledge**
- **MEDIUM VALUE** — Improves advisory quality but depends on Council architecture from S13.
- Your Council currently runs 3 models for consensus. The prompts should encode:
  1. **Standing rejections (all 13)** — hardcoded as system-prompt constraints. No model should ever recommend RSI standalone, BTC leads equities, etc.
  2. **Promoted rules from S11/S12** — TWAP detection criteria, IBIT closing cross behavior, temporal zone characterization, ETHA friction amplification. These are validated findings that should be in the Council's knowledge base.
  3. **A/B/C bucket definitions** — so the Council can classify entry quality consistently.
  4. **Override 3.0 state** — passed as context to every Council call. If Override is OFF, the Council should not recommend entries.
  5. **Exit framework from Q1** — the hybrid exit logic should be encoded so the Council can advise on exit timing.

  **Prompt structure recommendation:**
  ```
  [SYSTEM] You are a trading advisor for an intraday discretionary framework.
  STANDING REJECTIONS (never violate):
  - {list all 13}
  PROMOTED RULES:
  - {TWAP detection, IBIT closing cross, temporal zones, etc.}
  CURRENT STATE:
  - Override: {ON/OFF + stage}
  - Zone: {1-5}
  - VIX term structure: {contango/backwardation/flat}
  - Breadth (MMTW): {value}
  [USER] Assess {TICKER} for {LONG/SHORT} entry. 4H EMA state: {X}. TSS: {Y}. M5 sub-state: {Z}.
  ```

- **Effort:** 2-4 hours to revise Council prompts. Depends on Council codebase (not in repo).
- **Cost:** Only API call costs (existing).

### What NOT to Build

- **Backtester modifications:** Config A' is retired. Don't invest in it.
- **Automated execution:** Your edge is discretionary judgment + framework discipline. Automation removes the judgment layer. Defer until you have 200+ trades proving the framework works without it.
- **ML/AI trade classification:** GMM/HMM standing rejection. N=0 makes any ML approach absurd.
- **Mobile app / complex dashboard:** S13 correctly identified that a Telegram bot covers mobile needs. Don't build a custom app.
- **Monte Carlo simulation of Config A' data:** v1 recommended this. Wrong — different strategy. After you have 30+ trades with the Temporal Framework, THEN build Monte Carlo for your actual data.

### Open-Source Tools (Revised for Discretionary Workflow)
| Tool | Use Case | Cost |
|------|----------|------|
| Google Sheets | Trade journal + basic analytics | Free |
| TradingView Pine Script | TSS dashboard, Zone clock, alerts | Free (included in Premium) |
| Telegram Bot API (python-telegram-bot) | Alerts, notifications, Council interface | Free |
| FastAPI | Council API (per S13 architecture) | Free |
| `yfinance` (Python) | Historical data pulls for research | Free |

### Divergence Prediction
ChatGPT Pro will likely recommend:
1. Building a comprehensive trading dashboard (web-based, React/Next.js)
2. Integrating with a professional journaling platform (Tradervue, TradesVault)
3. Setting up proper CI/CD for the Council codebase
4. Possibly recommending a backtesting framework for the Temporal Framework

**I disagree on the dashboard** — TradingView IS your dashboard. Building a separate one is duplicating what you already pay for. **I partially agree on journaling platforms** — Tradervue ($30-50/month) is good but over your budget; a Google Sheet does 90% of what you need for free. **CI/CD is premature** — you don't have production code to deploy yet (the Council architecture from S13 is designed but not built). **Backtesting the Temporal Framework is the interesting one:** ChatGPT Pro may suggest backtesting the EMA 9/21 + TSS system using your Alpha Vantage M5 data. This is VALID and I should have ranked it higher — building a lightweight backtester for the Temporal Framework (not modifying the retired Config A' one) could provide the N=100+ trades needed for Kelly calibration. **However**, the manual discretionary component (M5 sub-state reading, A/B/C classification) is hard to automate in a backtest, so the results would test only the mechanical components (EMA cross + TSS threshold). Worth doing after trade journal is set up and you have 30 manual trades for calibration. **MEDIUM VALUE, 1-2 week build.**

---

## Summary: Ranked Action Items (Corrected)

| Priority | Action | Value | Effort | Cost | Layer |
|----------|--------|-------|--------|------|-------|
| 1 | Set up structured trade journal | HIGH | 2 hours | $0 | Foundation |
| 2 | Add VIX term structure ratio to TradingView | HIGH | 15 min | $0 | Layer 2 |
| 3 | Add MMTW (breadth) to TradingView | HIGH | 5 min | $0 | Layer 2 |
| 4 | Add ATR Trailing Stop overlay on 4H | HIGH | 5 min | $0 | Layer 4 |
| 5 | Build TSS Dashboard Pine Script | HIGH | 2-4 hours | $0 | Layer 3 |
| 6 | Build Zone Clock Pine Script | MEDIUM | 1-2 hours | $0 | Layer 1 |
| 7 | Add sector rotation ratios to watchlist | MEDIUM | 10 min | $0 | Layer 2 |
| 8 | Add DVOL to layout (crypto days) | MEDIUM | 2 min | $0 | Layer 2 |
| 9 | Upgrade Council prompts with S11-S13 knowledge | MEDIUM | 2-4 hours | $0 | Layer 4 |
| 10 | Implement hybrid exit rules (mental model) | HIGH | 0 (mental) | $0 | Layer 4 |
| 11 | Implement A/B/C sizing (0.50/0.375/0.25% risk) | HIGH | 0 (mental) | $0 | Layer 4 |
| 12 | Funding rate Telegram alert | LOW | 30 min | $0 | Layer 2 |

**Total effort for items 1-8 (core improvements):** ~1 day
**Total additional cost:** $0
**Expected impact:** Transform from "framework in head + visual chart reading" to "framework with structured validation pipeline + orthogonal regime inputs"

---

## Appendix A: What v1 Got Right (Retained)

These findings from v1 remain valid and are incorporated:
- VIX term structure as orthogonal signal (now TradingView implementation)
- Market breadth as regime gate (now TradingView implementation)
- IBIT/COIN are stocks, not crypto (applied to Q4 CryptoOverride framing)
- GEX/DIX too expensive and declining edge (skip recommendation retained)
- Don't automate — discretionary edge matters (retained)
- Weekend gap risk for IBIT on Mondays (incorporated into Q4 Rank 2 context)

## Appendix B: What v1 Got Wrong (Corrected)

| v1 Claim | Correction |
|----------|------------|
| "Framework-Code Divergence is #1 risk" | Conscious architecture decision, not a risk |
| "60% EOD exits is the real exit problem" | Config A' backtester data, irrelevant to Temporal Framework |
| "Kelly at 5.5% based on Phase 3 data" | Phase 3 = different strategy, cannot cross-apply |
| "Build Monte Carlo for Phase 3" | Phase 3 is retired; build for Temporal Framework after N=30 |
| "Add to filter_chain.py" | Backtester is retired; add to TradingView + Telegram |
| "EMA 9/21 cross on 4H is too slow for intraday" | Incorrect framing — 4H is the TREND filter, M5 is the EXECUTION filter. EMA cross identifies regime, M5 sub-state times entry. These operate on different timescales by design. |

## Appendix C: Standing Rejections Audit (Updated)

All 13 standing rejections remain respected. No recommendation violates any:
1. RSI standalone (PF 0.55) — RSI is a TSS component, never standalone
2. BTC leads equities — explicitly avoided
3. VIX→China ADR — not referenced
4. Config A' automated — backtester is retired, staying discretionary
5. GMM/HMM — no ML recommended
6. ETH ETF overnight MR — intraday only
7. ETHA=ETHU — not equated
8. COIN universal lead — treated as equity
9. VIX 25 hard threshold — using ratio and z-score, not absolute level
10. Crypto algos hard-code VIX — no hardcoding
11. CPI-day VIX direction — not used as signal
12. COIN 1-2h lag — no lag-based signals
13. Crypto recovers first=timing signal — explicitly rejected
