# S11-CC: Batch Hypothesis Validation Report

**Date:** 2026-03-12
**Analyst:** Independent market microstructure review
**Data source:** 4 live sessions (March 9-12, 2026), TradingView charts, CBOE VIX real-time
**Framework:** Discretionary NYSE/NASDAQ equities + crypto cross-asset

---

## Q1: Morning Exhaustion = Institutional Floor Formation (N=5)

### Verdict: PARTIALLY VALIDATE — Confidence: MEDIUM

### Mechanism Assessment: Largely Correct, Incomplete

The 10:30-10:50 ET exhaustion window is well-documented in practitioner literature (Hasbrouck, "Empirical Market Microstructure"; Madhavan, "Market Microstructure in Practice"). The mechanism is:

1. **Opening auction imbalance resolution.** NYSE/NASDAQ opening crosses execute large MOO orders. The resulting imbalance takes 30-50 minutes to fully absorb as algorithms work residual positions.
2. **VWAP benchmark pressure.** Institutional VWAP algos front-load volume early in the session (U-shaped intraday volume curve). By ~10:35, the first VWAP tranche completes, creating a brief liquidity vacuum.
3. **Retail exhaustion.** Retail order flow is highest in the first 30 minutes. By 10:35-10:50, retail momentum exhausts and institutional flow becomes a larger share of the tape.

The claim that this is a "floor" rather than a "reversal" is a useful distinction. The literature supports it: Barclay and Hendershott (2003) show informed trading concentrating in the first 30 minutes, after which price discovery slows. This creates a natural floor, not a mechanical reversal.

**VIX +10% modification:** Reasonable. On high-vol days, market makers widen spreads and reduce displayed size. The floor becomes shallower and shorter-lived because aggressive sellers can punch through thinner books.

**Event day shift:** Consistent with the literature. CPI/FOMC create a new "synthetic open" at release time, effectively resetting the exhaustion clock. The +30-45 min shift is empirically reasonable.

### Evidence Quality

N=5 across 4 sessions is **marginal for promotion**. The concern is regime-dependence: all 4 sessions occurred in March 2026 under a specific volatility regime. The mechanism is sound, but the precise 10:35-10:50 window may shift across regimes.

Strengthening: Need 15+ observations spanning different VIX regimes (VIX 12-18, 18-25, 25+), plus at least 2 event days.

### Promotion Decision: REMAIN HYPOTHESIS — promote after N=15 across regimes

### Threshold Review

- 10:35-10:50 ET window: Reasonable. Academic literature and volume profiles support 10:30-11:00 as the transition zone. Narrowing to 10:35-10:50 is aggressive but defensible.
- VIX +10% = 15 min pause: Reasonable heuristic. Could refine with dVIX/dt rather than level.
- Event day +30-45 min: Consistent with observed post-release price discovery periods.

### Failure Modes

1. **Trend days.** On strong trend days (>2 sigma moves), the exhaustion floor does not hold. Selling resumes immediately after any pause. These are ~10-15% of trading days.
2. **Pre-market gap > 2%.** Large gaps reset institutional order flow entirely; the 10:35-10:50 window becomes meaningless as algos recalibrate.
3. **Index rebalance / OpEx.** Mechanical flows from rebalancing can overwhelm the exhaustion floor.
4. **Thin liquidity days.** Day-after-holiday, summer Fridays — the floor is less reliable because institutional participation is lower.

### Blind Spots

- You are measuring this on liquid mega-caps (NVDA, TSLA). The effect may not generalize to mid/small-cap where microstructure is different.
- You have no volume profile data to confirm the U-shape hypothesis directly. The observations are price-based, not flow-based.
- Consider whether the "floor" is really just mean-reversion to VWAP, which would have different implications for rule design.

---

## Q2: BTC TWAP/Iceberg Algo Footprint on Crypto (N=5)

### Verdict: VALIDATE — Confidence: HIGH

### Mechanism Assessment: Correct

This is one of the strongest hypotheses in the batch. The core claim — that institutional execution algorithms are more visible on crypto than on equities — is directly supported by market microstructure theory and empirical observation.

**Why crypto makes algos visible:**

1. **Fragmented liquidity.** Crypto trades across 20+ exchanges with no consolidated tape. TWAP algos slicing across these venues produce recognizable volume patterns because no single venue has enough depth to absorb the flow silently.
2. **Thinner order books.** BTC/ETH top-of-book depth is 1-2 orders of magnitude thinner than SPY or NVDA. Each TWAP slice represents a larger fraction of visible liquidity.
3. **No circuit breakers / trading halts.** Algos run continuously without interruption, producing cleaner statistical footprints.
4. **Less algo competition.** Equity markets have thousands of HFT firms providing liquidity and masking institutional flow. Crypto has fewer participants, so institutional footprints stand out.

**TWAP detection criteria review:**

The proposed criteria align well with Almgren-Chriss (2001) optimal execution framework and Kissell-Glantz (2003) practical implementation:

- **≥5 consecutive slices, CV < 0.20:** Reasonable. Almgren-Chriss TWAP produces uniform slice sizes by definition. CV < 0.20 is a good threshold — random retail flow typically has CV > 0.5.
- **Directional persistence ≥80%:** Strong discriminator. Random flow has ~50% directional persistence. 80%+ is consistent with a directional execution mandate.
- **Participation rate stable ±25%:** Consistent with standard TWAP configuration. Most execution desks set participation rate bounds at ±20-30%.
- **Thin-market = TWAP, not VWAP:** Correct insight. VWAP algos adapt to volume, producing variable slice sizes. Uniform slices in thin markets = time-scheduled (TWAP). This distinction demonstrates genuine understanding of algo mechanics.

**Iceberg pause behavior:** Well-documented. Iceberg orders on most exchanges expose a displayed portion and refill from a hidden reserve. The "pause-then-resume" pattern occurs when the hidden reserve exhausts and must be manually replenished or when the algo reaches a time/price checkpoint.

### Evidence Quality

N=5 is adequate given the mechanical nature of the claim. This is not a statistical pattern — it is an identification of a known execution algorithm. The CV and directional persistence criteria are sufficient to distinguish TWAP from random flow. The confidence ladder (POSSIBLE → PROBABLE → CONFIRMED) is appropriately conservative.

### Promotion Decision: PROMOTE to rule

The detection criteria are sound and the mechanism is well-understood. Promote with the caveat that this is a detection tool, not a directional signal. Detecting TWAP selling tells you what institutions are doing; it does not tell you when they will stop.

### Threshold Review

- CV < 0.20: Good. Consider tightening to CV < 0.15 for CONFIRMED status.
- ≥5 bars: Appropriate minimum. 3-4 bars is genuinely ambiguous.
- 80% directional persistence: Sound. Could lower to 75% for PROBABLE.
- Participation rate ±25%: Reasonable. Tighter than most institutional algo configs (which allow ±30%).

### Failure Modes

1. **Randomized TWAP.** Sophisticated execution desks add randomization to slice timing and size (Almgren-Chriss with randomization). This would increase CV above 0.20 and defeat detection.
2. **Multi-venue splitting.** If the algo splits across 5+ exchanges, no single exchange shows the full pattern. You need aggregated cross-exchange data.
3. **Market maker inventory management.** MM rebalancing can mimic TWAP patterns — uniform sells over time as they reduce inventory. This is a false positive risk.
4. **Low-volatility drift.** In calm markets, normal order flow can appear uniform simply because there is no volatility to create variation.

### Blind Spots

- You are observing this on 1-minute or 5-minute candles. True TWAP detection requires tick-level data. What you're seeing may be a coarsened approximation that happens to work at this resolution.
- The equity-invisible claim is correct for mega-caps but may not hold for smaller equities or less liquid ETFs where books are thinner.
- Consider adding a volume anomaly check: is the detected TWAP volume significantly above the rolling average for that time-of-day?

---

## Q3: COIN Conditional Divergence from Crypto Spot (N=13)

### Verdict: VALIDATE — Confidence: HIGH

### Mechanism Assessment: Correct

The dual-listing / equity-proxy mechanism is well-established in market microstructure. COIN is a NASDAQ-listed equity and is subject to:

1. **Equity-specific order flow.** COIN sits in equity portfolios, ETFs (e.g., ARKK held COIN), and margin accounts. When equities sell off, COIN gets sold for reasons unrelated to crypto fundamentals — margin calls, portfolio rebalancing, sector rotation out of "risk-on" names.
2. **Different market hours.** COIN trades NYSE hours only; BTC/ETH trade 24/7. COIN cannot reflect overnight crypto moves in real-time, creating structural divergence.
3. **Different investor base.** COIN holders include equity mutual funds, ETFs, and retail equity traders. BTC/ETH holders include crypto-native funds, DeFi participants, and non-US retail. The overlap is partial.
4. **Correlation regime shifts.** Hasbrouck and Seppi (2001) showed that stocks with dual exposure (industry + market) exhibit time-varying correlation depending on which factor dominates. During equity stress, the equity factor dominates COIN; during crypto stress, the crypto factor dominates.

This is entirely consistent with Gagnon and Karolyi (2010) on ADR pricing: dual-listed securities reflect the microstructure of their listing venue, not just fundamental value.

### Evidence Quality

N=13 across 4 sessions is **sufficient for promotion**. The key strength is the unidirectionality: all 13 observations show COIN underperforming BTC during equity stress, never the reverse. This asymmetry is what you would expect from the mechanism — equity selling pressure is additive to crypto selling pressure, never subtractive.

### Promotion Decision: PROMOTE to rule

### Threshold Review

- **COIN_chg < BTC_chg - 1.5%:** Reasonable but potentially too tight. The median divergence in your data appears to be ~2%, so 1.5% gives some buffer. However, consider:
  - Adjusting for COIN's beta to BTC (COIN has historically exhibited ~1.5-2.5x beta to BTC). A 1.5% raw divergence may be normal given COIN's higher beta.
  - Recommend: Use COIN_chg < (BTC_chg × COIN_beta) - 1.0% to normalize for beta. If beta data is unavailable, 1.5% raw is a reasonable proxy.
- **equity_index < -0.5%:** Reasonable. This confirms the equity stress channel is active.
- **1-2h lag for crypto spot follow-through:** Insufficient evidence to pin down timing. The lag depends on whether equity stress is a US-specific event or a global risk-off event. Keep this as a qualitative warning, not a timed signal.

### Failure Modes

1. **Crypto-specific stress.** If the selloff originates in crypto (exchange hack, regulatory action, stablecoin depeg), COIN and BTC can sell together or COIN can actually outperform BTC (because COIN has equity circuit breakers and BTC does not).
2. **Earnings proximity.** Near COIN earnings, the stock reflects idiosyncratic expectations, not crypto-equity dynamics.
3. **COIN-specific news.** SEC actions, product launches, or management changes decouple COIN from both crypto and equity factors.
4. **Low-vol drift.** In quiet markets, the 1.5% divergence threshold may never trigger because neither COIN nor BTC moves enough.

### Blind Spots

- You are comparing COIN to BTC, but COIN's revenue is driven by trading volume across many cryptos, not BTC price. A more precise comparison might be COIN vs. total crypto trading volume, not COIN vs. BTC price.
- Short interest in COIN can amplify divergence during equity selloffs (short covering / piling on). Check COIN short interest levels to understand if the divergence magnitude is influenced by positioning.
- The "crypto spot may follow with 1-2h lag" claim has no statistical backing in the data presented. This is an assertion, not an observation. Keep it as a qualitative watch, not a rule.

---

## Q4: IBIT Mirrors Equity, Not Crypto Spot (N=9+)

### Verdict: VALIDATE — Confidence: HIGH

### Mechanism Assessment: Correct and Well-Supported

This is the strongest hypothesis in the batch. It is directly predicted by ETF microstructure theory.

**ETF Intraday Price Formation (Lettau and Madhavan, 2018; Ben-David, Franzoni, and Moussawi, 2018):**

ETF prices are determined by two forces:
1. **Secondary market supply/demand** (equity order flow, MOC/LOC, index rebalancing, margin calls)
2. **Arbitrage by Authorized Participants** (creation/redemption to enforce NAV)

Crucially, AP arbitrage is **not continuous**. APs create/redeem in large blocks (typically 25,000-50,000 shares) and only when the premium/discount exceeds their transaction costs. For IBIT specifically:

- **Creation/redemption in BTC is T+1 or T+2.** APs must acquire BTC, transfer to Coinbase Custody, and settle. This introduces a lag that prevents real-time arbitrage.
- **Intraday premium/discount can persist.** Academic literature on commodity ETFs (Petajisto, 2017) shows that ETFs with illiquid or hard-to-trade underlyings sustain larger intraday dislocations.
- **AP stepping-in threshold:** Typically 25-75 bps for liquid equity ETFs. For crypto ETFs, the threshold is likely **50-150 bps** given BTC settlement costs, custody fees, and the need to hedge during the creation/redemption process.

**Why IBIT tracks equity intraday:**

- IBIT is in NASDAQ order books. It receives MOC/LOC orders from equity index funds.
- IBIT is held in equity portfolios and margin accounts. Forced liquidation hits IBIT through equity mechanics.
- IBIT market makers hedge with equity instruments (futures, other ETFs), not directly with BTC spot. This creates equity-correlated hedging flow.
- Retail equity traders trade IBIT like a tech stock, contributing equity-sentiment-driven flow.

### Evidence Quality

N=9+ across 4 sessions is sufficient. The mechanism is well-understood theoretically, and 9 observations confirm the direction. The key observation — BTC green / IBIT red — is the critical test case, and it appears consistently.

### Promotion Decision: PROMOTE to rule

**Proposed rule language:** "For intraday trading, treat IBIT as an equity instrument that happens to have a BTC NAV anchor. Do not use IBIT as a BTC proxy for intraday decisions. For multi-day holds, AP arbitrage will enforce NAV convergence."

### Threshold Review

The hypothesis does not propose specific thresholds, which is appropriate. The key insight is qualitative: IBIT ≠ BTC intraday. No threshold needed — this is a regime classification.

### Failure Modes

1. **Large BTC moves (>5%).** When BTC moves sharply, the NAV dislocation becomes large enough that APs step in intraday. At some point, the crypto factor overwhelms the equity factor. Estimate threshold: BTC move >3-5% in a session.
2. **High creation/redemption activity.** On days with large IBIT inflows/outflows, AP activity can dominate the tape and bring IBIT closer to BTC spot.
3. **Crypto-driven equity sessions.** If crypto IS the story (e.g., major regulatory announcement), IBIT and BTC will co-move because equity traders are trading IBIT as a crypto proxy intentionally.
4. **End-of-day convergence.** IBIT typically snaps toward NAV in the last 30-60 minutes as APs position for closing NAV calculations. Intraday divergence may be most extreme mid-session.

### Blind Spots

- You should track IBIT premium/discount to NAV intraday. iNAV (indicative NAV) is published in real-time for most ETFs. The premium/discount level tells you how much equity-vs-crypto pressure is being exerted.
- ETHA (Ethereum ETF) likely exhibits the same behavior but with more extreme dislocations due to lower AUM and less AP activity. Confirm independently.
- Consider that IBIT may have different behavior on options expiration days due to delta hedging flows from IBIT options market makers.

---

## Q5: China ADR Partial Decoupling = Catalyst-Dependent (N=5)

### Verdict: VALIDATE — Confidence: MEDIUM-HIGH

### Mechanism Assessment: Correct, with Nuance

The catalyst-dependent decoupling claim is consistent with the ADR microstructure literature, particularly Gagnon and Karolyi (2010) and Levy Yeyati, Schmukler, and Van Horen (2009).

**Dual-listing price formation for China ADRs:**

China ADRs have two price discovery venues:
1. **Hong Kong (HK) market** — reflects Asian session, China-specific fundamentals, HKMA/PBoC liquidity, South China Morning Post flow
2. **US (NASDAQ/NYSE) market** — reflects US session equity order flow, global macro, US-China geopolitical sentiment

The key insight: which venue dominates depends on **information asymmetry**. When there is China-specific news, HK is the informed venue, and the ADR price anchors to HK. When there is no China-specific news, the ADR is just another US-listed equity and trades with the S&P.

**HK-to-US overnight gap positioning mechanism:**

1. HK closes at 4:00 PM HKT (4:00 AM ET).
2. US pre-market opens at 4:00 AM ET.
3. If HK closed strongly positive (gap-up positioning), US-based arbitrageurs and informed traders buy ADRs in pre-market to capture the expected gap-up.
4. This pre-market positioning creates a "floor" for the ADR during the US session — holders are positioned for China upside and are reluctant to sell during US-specific weakness.
5. Conversely, if HK was flat or red, there is no positioning anchor, and the ADR trades with US flow.

This mechanism is well-documented in Bae, Ozoguz, Tan, and Wirjanto (2012) on the information transmission between dual-listed securities across time zones.

### Evidence Quality

N=5 across 4 sessions with **both directions observed** (catalyst present → decoupled; no catalyst → correlated) is strong qualitative evidence. The Day 3/Day 4 observations where ADRs sold off without catalyst are particularly valuable because they demonstrate the boundary condition.

Strengthening: Need observations on earnings weeks, during active US-China trade policy news, and during HK-specific stress (e.g., HKMA intervention, PBoC rate changes).

### Promotion Decision: PROMOTE to rule (conditional)

Promote with the following conditions:
- Must check HK close before US session (non-negotiable pre-session check)
- "Catalyst" must be explicitly defined (see below)
- Earnings proximity rule (DO NOT ENTER) is correct and should be strict (±3 trading days)

### Threshold Review

The hypothesis does not propose numerical thresholds, which is appropriate for a qualitative regime classification. Suggest adding:
- **HK gap-up > +1.0%** on the relevant HK-listed shares (700.HK for TCEHY, 9988.HK for BABA) as the minimum catalyst signal.
- **Correlation LOW** should be quantified: if possible, track rolling 20-minute correlation between ADR and SPY. Correlation < 0.3 = decoupled; > 0.6 = coupled.

### Catalysts Beyond HK Gap-Up

1. **PBoC policy actions** (rate cuts, RRR cuts, liquidity injections)
2. **State Council / Politburo statements** on tech regulation, property, or stimulus
3. **Earnings beats** from major China tech (these create multi-day momentum)
4. **MSCI/FTSE index rebalancing** involving China weights
5. **US-China diplomatic events** (positive = decouple up; negative = decouple down)

### Failure Modes

1. **Systemic global risk-off.** In a true global panic (2020 March, 2022 October), all correlations go to 1. China catalyst cannot save ADRs from a -5% SPX day.
2. **US-China escalation.** Delisting threats, tariff escalation, or sanctions override any HK positioning. The ADR reflects political risk, not HK price discovery.
3. **HK market closure.** During HK holidays, the overnight gap positioning mechanism is absent. ADRs revert to US flow entirely.
4. **Currency moves.** Sharp CNY/CNH depreciation can override positive HK positioning because ADRs are USD-denominated.

### Time-of-Day Patterns for Decoupling Breakdown

- **10:00-10:30 ET:** Decoupling is strongest here because HK positioning is freshest.
- **12:00-14:00 ET:** Decoupling weakens as HK positioning fades and US flow dominates.
- **15:00-16:00 ET:** Decoupling can reassert if HK overnight positioning begins (HK futures open at ~9:00 PM HKT = ~9:00 AM ET during daylight saving).
- **Power Hour (15:30-16:00):** MOC/LOC orders are US-centric. ADRs recouple to US flow during this period regardless of catalyst.

### Blind Spots

- You are not tracking **HK short selling data.** HK exchange publishes daily short selling turnover. High short interest in HK-listed shares signals potential for a negative HK catalyst that would override US positioning.
- **ADR premium/discount to HK NAV** is a more precise measure than raw price comparison. Track this to detect when arbitrageurs are active vs. absent.
- **Volume in the ADR vs. HK-listed share** tells you which venue is leading price discovery. If ADR volume surges above normal, US flow is dominating and decoupling is less likely to hold.

---

## Summary Table

| # | Hypothesis | Verdict | Confidence | Decision | Key Condition |
|---|-----------|---------|------------|----------|---------------|
| Q1 | Morning Exhaustion Floor | PARTIALLY VALIDATE | MEDIUM | REMAIN HYPOTHESIS | Need N=15 across VIX regimes |
| Q2 | BTC TWAP/Iceberg Detection | VALIDATE | HIGH | PROMOTE | Detection tool, not directional signal |
| Q3 | COIN Conditional Divergence | VALIDATE | HIGH | PROMOTE | Normalize for COIN beta to BTC |
| Q4 | IBIT Mirrors Equity Intraday | VALIDATE | HIGH | PROMOTE | AP threshold ~50-150 bps |
| Q5 | China ADR Catalyst Decoupling | VALIDATE | MEDIUM-HIGH | PROMOTE (conditional) | Must define catalyst checklist |

### Cross-Hypothesis Dependencies

- Q3 and Q4 are deeply related: both describe the same mechanism (equity-listed crypto instruments track equity flow, not crypto spot). Consider merging into a single "crypto-equity microstructure" rule set.
- Q1 (morning exhaustion) interacts with Q2 (TWAP detection): institutional TWAP selling may be what creates the exhaustion floor — the TWAP tranche completes at ~10:35, creating the floor. If confirmed, this would strengthen both hypotheses.
- Q5 (China ADR) is independent of the other four. No cross-hypothesis interaction detected.

### Key Academic References

- Almgren, R. and Chriss, N. (2001). "Optimal execution of portfolio transactions." *Journal of Risk*, 3(2), 5-39.
- Bae, K.H., Ozoguz, A., Tan, H., and Wirjanto, T.S. (2012). "Do foreigners facilitate information transmission in emerging markets?" *Journal of Financial Economics*, 105(1), 209-227.
- Barclay, M.J. and Hendershott, T. (2003). "Price Discovery and Trading After Hours." *Review of Financial Studies*, 16(4), 1041-1073.
- Ben-David, I., Franzoni, F., and Moussawi, R. (2018). "Do ETFs Increase Volatility?" *Journal of Finance*, 73(6), 2471-2535.
- Gagnon, L. and Karolyi, G.A. (2010). "Multi-market trading and arbitrage." *Journal of Financial Economics*, 97(1), 53-80.
- Hasbrouck, J. (2007). *Empirical Market Microstructure.* Oxford University Press.
- Kissell, R. and Glantz, M. (2003). *Optimal Trading Strategies.* AMACOM.
- Lettau, M. and Madhavan, A. (2018). "Exchange-Traded Funds 101 for Economists." *Journal of Economic Perspectives*, 32(1), 135-154.
- Madhavan, A. (2000). "Market Microstructure: A Survey." *Journal of Financial Markets*, 3(3), 205-258.
- Petajisto, A. (2017). "Inefficiencies in the Pricing of Exchange-Traded Funds." *Financial Analysts Journal*, 73(1), 24-54.
