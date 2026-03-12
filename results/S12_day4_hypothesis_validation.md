# S12-CC: Day 4 Findings Validation — 6 Hypotheses

**Date:** 2026-03-12
**Analyst:** Independent market microstructure review (Claude Code Opus cross-validator)
**Session:** S12 (cross-validation peer to ChatGPT Pro S12)
**Data source:** Day 4 live session (March 12, 2026), plus Day 1-3 context
**Market context:** SPX -1.52%, VIX 27.16 (+12.09%), BTC +0.41%, ETH +1.03%

---

## H1: ETH Volume Asymmetry = Institutional Accumulation

### Verdict: PARTIALLY VALIDATE — Confidence: MEDIUM

### Mechanism Assessment: Plausible but Incomplete

The observed pattern — large volume on up-moves, small volume on down-moves — is consistent with Wyckoff accumulation theory and has parallels in institutional execution literature. The logic is straightforward: institutions accumulate on weakness (creating volume floors on dips) and the market rises on their passive bids during markup phases.

**What supports this interpretation:**

1. **Volume-price asymmetry as accumulation signal.** This is well-documented in equity microstructure (Llorente, Michaely, Saar, and Wang, 2002). When informed traders accumulate, volume concentrates on price-confirming moves (up-moves during accumulation). Uninformed/retail selling on pullbacks produces low volume because there is no conviction behind it.

2. **Wyckoff structure alignment.** The described pattern — accumulation (~1,920) → markup → re-accumulation (~2,000-2,050) → 2,074 — follows classic Wyckoff schematic. The re-accumulation (trading range within an uptrend) is the highest-confidence Wyckoff structure because it occurs after a confirmed trend change.

3. **4H EMA cross confirmation.** The 9/21 cross UP on 4H is the first bullish cross in the entire watchlist. Combined with volume asymmetry, this is a multi-signal confluence — stronger than either signal alone.

4. **ADX ~58 with no RSI divergence.** Extreme trend strength without divergence is the cleanest momentum signal available. Contrast with BTC (see H5).

**What weakens this interpretation:**

1. **Crypto volume data is unreliable.** Bitwise (2019) estimated that ~95% of reported crypto exchange volume is fabricated (wash trading). Even on reputable exchanges (Coinbase, Binance), volume spikes can reflect market maker activity, not institutional accumulation.

2. **4 days is insufficient for Wyckoff validation.** Wyckoff accumulation phases typically span weeks to months. What looks like accumulation on a 4-day window could be noise within a larger distribution pattern.

3. **Opening dump volume is ambiguous.** Large volume on the opening dump could be institutional selling (not retail/forced), with the low-volume pullbacks reflecting absence of buying interest rather than accumulation patience.

### Framework Integration: Confirmation Tool, NOT Independent Signal

Use volume asymmetry as a **confirmation filter** for 4H EMA cross signals:
- 4H EMA cross UP + volume asymmetry (up-volume > 1.5× down-volume on M5) → **HIGH CONFIDENCE** entry
- 4H EMA cross UP + no volume asymmetry → **STANDARD CONFIDENCE** entry
- Volume asymmetry alone (no EMA cross) → **DO NOT TRADE** on this signal alone

### Failure Modes

1. **Distribution disguised as accumulation.** Sophisticated sellers can distribute on up-moves (selling into strength), creating volume patterns that mimic accumulation. The distinguishing factor is what happens at range highs — does price break up (accumulation confirmed) or fail and reverse (distribution)?
2. **Exchange-specific volume distortion.** If you're looking at a single exchange, market maker inventory rotation can create artificial volume asymmetry.
3. **Thin-market magnification.** In crypto, a single large order can create a "large volume bar" that looks institutional but is just one retail whale.
4. **Weekend/off-hours reset.** Crypto volume patterns reset across weekends when institutional desks are offline and retail/algo flow dominates.

### Blind Spots

- You need to specify WHICH exchange volume you're reading. TradingView aggregates vary by data provider. Coinbase volume ≠ Binance volume ≠ aggregate.
- Compare ETH volume asymmetry against BTC volume asymmetry on the same timeframe. If both show it, the signal is less ETH-specific and more about a broad crypto bid.
- Consider tracking **delta volume** (buy volume minus sell volume) rather than raw candle color. Candle color only tells you open-to-close direction, not who initiated the trades.

**Cross-reference: H5 (BTC RSI divergence).** ETH's clean accumulation vs. BTC's divergent signal creates a pair-trade thesis: long ETH / hedge with BTC short. This deserves separate analysis.

---

## H2: Crypto-Equity Full Divergence at VIX +12%

### Verdict: PARTIALLY VALIDATE — Confidence: MEDIUM-LOW

### Mechanism Assessment: Multiple Mechanisms, Uncertain Dominance

The observation is real: on Day 4, VIX +12.09% produced equity carnage (-1.5% to -4.4%) while BTC closed +0.41% and ETH +1.03%. But the mechanism is not singular — multiple factors contribute, and their relative importance is uncertain.

**Proposed mechanisms (ranked by likely contribution):**

1. **Different investor base and margin structure.** Crypto margin calls are settled in crypto or stablecoins, not by selling crypto to meet equity margin calls. Equity margin calls force equity liquidation but do not directly force crypto liquidation. This is the primary structural explanation for why crypto can decouple upward during equity stress.

2. **24/7 market allows faster repricing.** Crypto traded through the prior night while equity information accumulated. By the time US equity markets opened and sold off, crypto had already partially digested the same macro information and found a floor. The equity open is "old news" for crypto.

3. **Non-US bid.** During US equity hours, Asian and European crypto participants are active. If the VIX spike is driven by US-specific factors (tariff policy, domestic CPI), non-US crypto buyers may not share the same risk-off impulse.

4. **Crypto narrative regime.** In certain periods, crypto trades on its own narrative (halving cycle, ETF flows, DeFi catalysts) and temporarily decouples from macro. This is regime-dependent and NOT permanent.

**Why this is MEDIUM-LOW confidence:**

- **N=4 is grossly insufficient.** You have 4 days of data. VIX +12% days occur ~10-15 times per year. You need to sample across different VIX spike causes (CPI miss, geopolitical shock, liquidity crisis, credit event) to know if the pattern holds.
- **Survivorship bias.** You are looking at 4 specific days where crypto happened to recover. There are many VIX spike days where crypto sold off harder than equities (March 2020, May 2021, November 2022, August 2024). The pattern is NOT universal.
- **Day 4 specifics.** ETH's outperformance may be driven by ETH-specific catalysts (Pectra upgrade narrative, ETH/BTC ratio mean reversion) rather than a generic "crypto recovers first" dynamic.

### Framework Integration: Qualitative Watch, NOT a Trading Rule

**DO NOT** use crypto as a leading indicator for equity recovery timing. The evidence does not support this.

Instead, use as a **regime indicator:**
- IF VIX spikes AND crypto recovers within 2-4 hours → "VIX spike is equity-specific, not systemic risk-off" → be prepared for equity recovery
- IF VIX spikes AND crypto sells off in tandem → "systemic risk-off, all correlations going to 1" → maximum caution

This is a **classification tool**, not a timing signal.

### Failure Modes

1. **Systemic liquidity crisis.** When the issue is USD liquidity (2020 March, 2022 FTX contagion), crypto sells off harder than equities because crypto markets have no central bank backstop.
2. **Crypto-specific contagion.** Stablecoin depeg, exchange hack, major protocol exploit — crypto sells off while equities may be unaffected.
3. **Correlation regime shifts.** Crypto-equity correlation is time-varying. In 2020-2021, correlation was low. In 2022, correlation spiked to ~0.7. In 2024-2025, it varied. You cannot assume the current regime persists.
4. **Weekend gap risk.** If VIX spikes on Friday and crypto "recovers" over the weekend, the Monday equity open may gap down further, invalidating the "crypto leads recovery" thesis.

### Blind Spots

- You are not controlling for **USD index (DXY) direction**. A VIX spike with DXY falling (risk-off but dollar-negative) is very different from a VIX spike with DXY rising (true flight to safety). Crypto is partially a dollar-denominator trade.
- **Stablecoin flows** (USDT/USDC market cap changes, exchange stablecoin reserves) are a better indicator of crypto-specific demand than price-based analysis.
- The "sequence" observation (VIX peak → crypto bounce → equity still falling) could be an artifact of market hours. Crypto bounces first because it trades 24/7, not because it "leads." This is a timing artifact, not a causal relationship.

**Cross-reference: H6 (Temporal zones).** The Power Hour crypto bounce (H2) coincides with the Power Hour MOC flow (H6). Are you sure crypto is bouncing because of crypto-specific demand, or because equity MOC buying pushes risk-on sentiment that bleeds into crypto?

---

## H3: IBIT Closing Cross Recouple — Live Observed

### Verdict: VALIDATE — Confidence: HIGH

### Mechanism Assessment: Correct and Predicted by S11 Q4

This observation is a direct confirmation of the S11 Q4 promoted rule. The Day 4 data is textbook:

**The Nasdaq Closing Cross mechanism:**

1. **3:50 PM ET:** Nasdaq begins publishing MOC/LOC order imbalance data. APs observe the imbalance and begin positioning.
2. **3:50-4:00 PM ET:** APs calculate IBIT NAV based on real-time BTC price. If IBIT is trading at a discount to NAV (which it was, ~-0.82% midday vs BTC near flat), APs buy IBIT in the secondary market and submit creation baskets.
3. **4:00 PM ET:** Closing Cross executes. IBIT closing price reflects the combined equity MOC flow + AP NAV arbitrage, pulling the price toward BTC NAV.
4. **NAV strike at 4:00 PM ET:** IBIT's official NAV is calculated using BTC price at 4:00 PM ET (per the prospectus, using CF Benchmarks BRR rate). APs settle creation/redemption against this NAV.

**The -0.30% residual at close:**

The -0.30% IBIT close vs. BTC +0.41% implies a closing discount of ~0.71% to a BTC-equivalent NAV. This is consistent with:
- AP transaction costs (custody, settlement, BTC transfer fees): ~10-25 bps
- Bid-ask spread in creation/redemption: ~10-20 bps
- Residual equity selling pressure from MOC orders not fully offset by AP buying: variable

A ~70 bps closing discount is within the expected range for high-VIX days when APs are less aggressive (wider risk limits, higher hedging costs). On calm days, the closing discount should be <30 bps.

**The 18% volume concentration claim:**

Nasdaq Closing Cross handling ~18% of daily IBIT volume is plausible and consistent with broader equity market data. NYSE closing auction handles ~25-30% of large-cap daily volume. For ETFs, the percentage is somewhat lower because ETFs also trade heavily in the first and last 30 minutes of the regular session.

### Framework Integration: Daily Metric — IBIT Closing Discount

Track as a daily metric:
- **IBIT_discount_3PM** = (IBIT_price_3PM - IBIT_iNAV_3PM) / IBIT_iNAV_3PM
- **IBIT_discount_4PM** = (IBIT_close - IBIT_NAV) / IBIT_NAV
- **Recouple_magnitude** = IBIT_discount_3PM - IBIT_discount_4PM

This metric tells you:
- How much equity pressure distorted IBIT during the session (3PM discount)
- How aggressively APs arbitraged at close (recouple magnitude)
- Whether APs are becoming more or less active (trend in recouple magnitude)

### Failure Modes

1. **BTC flash crash near close.** If BTC drops sharply between 3:50-4:00 PM ET, the NAV calculation shifts and IBIT may appear to "not recouple" because NAV moved against it during the closing cross.
2. **Extreme market stress.** During extreme VIX (>35-40), APs may reduce activity entirely, widening the closing discount beyond normal ranges.
3. **IBIT options expiration.** Delta hedging flows from IBIT options can distort the closing cross, creating anomalous premium/discount readings.

### Blind Spots

- You should track **iNAV** (indicative NAV, ticker IBITIV) in real-time to observe the premium/discount path intraday, not just at checkpoints.
- Compare recouple magnitude on high-volume vs low-volume days. If APs are flow-dependent, the recouple should be stronger on high-volume days.

**Cross-reference: H4 (ETHA).** ETHA should exhibit the same recouple mechanism but with larger residual friction due to lower AUM and fewer APs.

### Promotion Decision: Already promoted (S11 Q4). This observation CONFIRMS the rule. Add the closing discount metric as a daily tracking item.

---

## H4: ETHA Hybrid Instrument (N=6 → Promotion)

### Verdict: VALIDATE — Confidence: MEDIUM-HIGH

### Mechanism Assessment: Same as IBIT, with Amplified Friction

ETHA (iShares Ethereum Trust ETF) is structurally identical to IBIT in its microstructure:
- Direct-hold ETF (holds ETH, not futures)
- Trades on NASDAQ during equity hours
- Subject to the same equity order flow, MOC/LOC, margin call dynamics
- APs arbitrage NAV via creation/redemption

**Why ETHA shows MORE friction than IBIT:**

1. **Lower AUM.** ETHA's AUM is substantially smaller than IBIT's (~$3-4B vs ~$55B+ for IBIT as of early 2026). Lower AUM means:
   - Fewer APs competing to arbitrage (less efficient NAV tracking)
   - Wider bid-ask spreads in the secondary market
   - Larger percentage impact from the same dollar flow

2. **ETH settlement is slower and more complex.** ETH block times are ~12 seconds (vs BTC ~10 minutes), but ETH has more complex custody requirements (staking considerations, smart contract risk). AP creation/redemption may carry higher operational friction.

3. **Lower institutional adoption.** ETH ETF flows have lagged BTC ETF flows since launch. Fewer institutional holders means less AP incentive to maintain tight tracking.

4. **Wider NAV benchmark spread.** ETHA uses CF Benchmarks ETH Reference Rate, which may have wider confidence intervals than the BTC equivalent due to ETH's greater exchange fragmentation.

**Day 4 evidence: ETH +1.03% vs ETHA -0.38% = 1.41% spread**

This 1.41% spread is large but consistent with the amplified friction thesis. On a VIX +12% day:
- ETHA's equity selling pressure is the same as IBIT's (NASDAQ flow, margin calls)
- ETHA's AP arbitrage is weaker (fewer APs, less AUM, wider spreads)
- Result: larger intraday divergence from spot, less complete recouple at close

### Evidence Quality

N=6 across 4 days showing consistent ETH > ETHA is sufficient for promotion, especially because:
- The mechanism is identical to IBIT (already promoted)
- The direction is always the same (ETHA underperforms ETH spot)
- The magnitude varies with VIX (larger divergence on higher VIX days), which is predicted by the mechanism

### Framework Integration: Extend IBIT Rule to ETHA

Promote ETHA to the **Crypto-Equity Microstructure** parent module alongside IBIT:

**Rule:** "ETHA is an equity-hours wrapper around ETH NAV, with greater friction than IBIT/BTC due to lower AUM and fewer APs. For intraday trading, ETHA ≠ ETH. Expect 1.0-1.5% divergence on high-VIX days, 0.3-0.5% on calm days."

Track the same daily metrics as IBIT:
- ETHA_discount_3PM, ETHA_discount_4PM, recouple_magnitude
- Compare ETHA recouple to IBIT recouple — if ETHA consistently recouples less, AP activity is structurally weaker

### Failure Modes

1. **ETHA AUM growth.** If ETHA attracts significantly more AUM (institutional ETH adoption, staking yield addition), AP competition increases and friction decreases. The 1.0-1.5% divergence threshold would need tightening.
2. **ETH staking integration.** If ETHA adds staking yield (as proposed by multiple ETF issuers), the NAV calculation changes and premium/discount dynamics shift. Staking yield creates a persistent NAV growth component.
3. **ETH-specific volatility.** ETH has higher annualized volatility than BTC (~75% vs ~60%). This means wider intraday swings, making the equity-wrapper effect harder to isolate from spot volatility.

### Blind Spots

- You should track ETHA's **creation/redemption basket size and frequency** vs IBIT. If ETHA has larger minimum baskets or less frequent creation windows, friction is structurally higher.
- Monitor ETHA's **bid-ask spread** relative to IBIT. Wider spreads = less AP competition = more equity-driven pricing.
- Check whether ETHA has the same Closing Cross recouple pattern as IBIT. If the Day 4 -0.38% close still left significant discount to NAV, APs may not be active enough to recouple even at close.

**Cross-reference: H3 (IBIT Closing Cross).** IBIT recoupled from -1.12% to -0.30% (82 bps improvement). ETHA would need similar analysis — did ETHA also narrow its discount into the close? If not, ETHA's AP arbitrage is structurally weaker.

**Cross-reference: H1 (ETH volume asymmetry).** ETH spot shows accumulation volume, but ETHA does not capture this because ETHA's volume is equity-driven. This is another reason to trade ETH exposure via spot/futures rather than ETHA for intraday.

### Promotion Decision: PROMOTE to rule — integrate into Crypto-Equity Microstructure module alongside IBIT.

---

## H5: BTC RSI Bearish Divergence vs "Cannot Fall" Pattern

### Verdict: NEEDS MORE DATA — Confidence: LOW

### Mechanism Assessment: Known Tension, No Reliable Resolution Rule

RSI divergence is one of the most studied technical analysis patterns, and the academic evidence is decidedly mixed. The tension you describe — price making higher highs while RSI makes lower highs — is a standard bearish divergence setup. But the resolution is not deterministic.

**What RSI divergence actually measures:**

RSI divergence indicates that **momentum is decelerating** — each successive price high is achieved with less buying intensity relative to the lookback period. This is a necessary but NOT sufficient condition for reversal. Momentum deceleration can resolve in three ways:

1. **Price correction to meet RSI.** Price drops, RSI and price re-synchronize. This is the "textbook" bearish divergence resolution.
2. **Sideways consolidation (RSI reset).** Price moves sideways for enough periods that RSI resets (the denominator in the RSI calculation shifts). Price then continues upward with refreshed momentum. This is common in strong trends.
3. **Divergence failure.** RSI makes a new high on the next leg, negating the divergence. This happens when the buying pressure that appeared to be fading was actually a brief pause (e.g., institutional algo pausing between tranches).

**In crypto specifically:**

- RSI divergence is LESS reliable in crypto than in equities (Detzel, Liu, Strauss, Zhou, and Zhu, 2021 — momentum factor in crypto is weaker and more regime-dependent than in equities).
- 24/7 trading means RSI never "gaps" (unlike equities where overnight gaps can create RSI distortions). This makes crypto RSI marginally more meaningful mechanically, but the signal-to-noise ratio is still low.
- BTC's "cannot fall" behavior suggests a persistent bid — likely institutional TWAP buying (cross-reference with S11 Q2 TWAP detection). If the bid is algorithmic, RSI divergence is capturing the algo's pacing (which will eventually complete), not a fundamental shift.

**Standing framework position:** RSI as a standalone signal was REJECTED in earlier sessions. This is consistent with that rejection — RSI divergence alone should not drive decisions.

### Framework Integration: Conditional Confirmation, Never Primary

The ETH vs BTC divergence comparison is the most useful insight here:

- **ETH: 4H EMA cross UP + volume asymmetry + NO RSI divergence = clean signal**
- **BTC: 4H EMA cross UP + RSI divergence = conflicted signal**

Rule: When two correlated assets (BTC/ETH) show conflicting momentum quality, **weight the cleaner signal**. If ETH is clean and BTC is divergent:
- Prefer ETH for directional crypto exposure
- Size BTC positions smaller (e.g., 50% of normal)
- Monitor BTC for divergence resolution: if BTC consolidates sideways for 3-5 4H bars without breaking higher highs, divergence is likely resolving via reset (bullish). If BTC makes a lower high on 4H, divergence is resolving via correction (bearish).

### Failure Modes

1. **Divergence persists through multiple legs.** In strong trends, RSI can stay "divergent" for weeks while price continues higher. The divergence is technically valid but practically useless as a timing tool.
2. **Different RSI periods give different signals.** RSI(14) may show divergence while RSI(21) does not. The signal is period-dependent, reducing reliability.
3. **Crypto regime shift.** If the market transitions from momentum-driven to mean-reverting (e.g., post-halving euphoria → consolidation), RSI divergence reliability changes.

### Blind Spots

- The RSI values cited (~21 → 15 → 13) seem extremely low for a "higher highs" price pattern. Standard RSI(14) near 13-21 indicates deeply oversold conditions, not a "higher highs" environment. **Verify these RSI readings.** If accurate, this is an unusual configuration that may indicate data or calculation issues, or a very specific lookback period.
- Consider using **MACD histogram divergence** instead of RSI divergence. MACD is momentum-based but less bounded, making divergence signals less ambiguous.
- Check whether the "cannot fall" pattern corresponds to TWAP buying detected via S11 Q2 criteria. If so, the divergence resolves when the TWAP completes.

**Cross-reference: H1 (ETH accumulation).** ETH's clean accumulation pattern vs BTC's divergent pattern supports a relative-value thesis: long ETH / reduce BTC. This is the most actionable insight from H5.

### Promotion Decision: REMAIN HYPOTHESIS — RSI divergence is consistent with the standing rejection of RSI as a standalone signal. The ETH vs BTC relative quality comparison is useful but needs more data (N>10 divergence events with tracked resolutions).

---

## H6: Temporal Zone Reliability (N=4 → Near Promotion)

### Verdict: VALIDATE — Confidence: HIGH

### Mechanism Assessment: Correct — Each Zone Has a Known Microstructure Driver

The 5-zone intraday structure is well-documented across multiple academic and practitioner sources. Each zone has a distinct microstructure mechanism:

**Zone 1: Opening Dump (first 10-30 min)**
- Mechanism: Opening auction imbalance resolution + overnight order accumulation
- Academic support: Barclay and Hendershott (2003) — price discovery is highest in the first 30 minutes. Madhavan, Richardson, and Roomans (1997) — opening spreads are widest and narrow over the first 30 minutes.
- The "dump" characterization is specific to bear/high-VIX days. On bull days, this zone is an "opening pop." The mechanism is the same — accumulated orders execute — but the direction depends on overnight sentiment.

**Zone 2: Recovery to London Close +30 min (~11:30 ET)**
- Mechanism: **London Close IS a documented liquidity event.** The London fix occurs at 4:00 PM GMT (11:00 AM ET during EST, 12:00 PM ET during EDT — note: March 12 is EDT, so London Close = 12:00 PM ET, not 11:30 ET). FX fixing flows spill into equity markets as global macro desks rebalance.
- The "+30 min" buffer accounts for residual FX flow and the transition from European to US-only participation.
- Breedon and Ranaldo (2013) documented the London fix's impact on FX markets. The equity spillover is less studied but practitioner-recognized.
- **Note:** Your timing may be off by 30 min. In EDT (which March 12 falls under), London Close is 12:00 PM ET, not 11:30 ET. Verify whether your "recovery to 11:30 ET" is actually a recovery to London Close or an independent US-morning pattern. This distinction matters.

**Zone 3: Dead Zone / US Lunch (12:00-13:30 ET)**
- Mechanism: **Well-documented.** Jain and Joh (1988) and McInish and Wood (1992) showed the U-shaped intraday volume pattern — volume drops to its daily minimum between 12:00-14:00 ET.
- Institutional desks reduce activity during lunch. Market makers widen spreads. Algorithmic participation rate drops because VWAP/TWAP algos reduce volume targets to match the U-shaped curve.
- This zone is universal across bull and bear days. It is NOT specific to sell days.

**Zone 4: Breakdown Zone (13:00-14:30 ET)**
- Mechanism: This is the most regime-dependent zone. On bear/high-VIX days, the "breakdown" occurs because:
  - European desks close their books (final European participation ends ~14:00 ET)
  - US institutional desks receive updated risk limits after lunch, and on sell days, risk managers tighten limits → forced selling
  - Algo TWAP/VWAP programs that were paused during lunch resume with the afternoon volume ramp
- On bull/calm days, this zone is NOT a breakdown — it's a low-conviction drift or mild continuation.
- The characterization as a "Breakdown Zone" is bear-day-specific and should be labeled accordingly.

**Zone 5: Power Hour (14:45-16:00 ET)**
- Mechanism: **MOC/LOC order imbalance.** NYSE publishes regulatory MOC/LOC imbalance data at 15:50 ET. Institutional closing algorithms activate. Volume spikes to its daily maximum.
- Bogousslavsky (2016) documented that the last 30 minutes contain ~25-30% of daily volume for large-cap equities.
- On sell days, MOC sell imbalances create the final push down. On buy days, MOC buy imbalances create the closing rally. Power Hour is "directional resolution" — this characterization is correct.

### Evidence Quality

N=4 is marginal for the overall structure but the individual zones are independently well-documented with decades of academic evidence. The key question is not whether the zones exist (they do) but whether the **characterization** (dump → recovery → dead → breakdown → resolution) is specific to high-VIX bear days or more universal.

Based on the evidence: the zone TIMING is universal. The zone CHARACTER (dump vs. pop, breakdown vs. drift) is regime-dependent.

### Framework Integration: Promote as Conditional Temporal Grid

**Promote with regime conditioning:**

| Zone | Time (ET) | VIX >20 / Bear Day | VIX <18 / Bull Day |
|------|-----------|--------------------|--------------------|
| 1 | 9:30-10:00 | Opening dump | Opening pop |
| 2 | 10:00-11:30 | Recovery / mean reversion | Continuation or fade |
| 3 | 12:00-13:30 | Dead zone (universal) | Dead zone (universal) |
| 4 | 13:30-14:45 | Breakdown zone | Low-conviction drift |
| 5 | 14:45-16:00 | Directional resolution (MOC) | Directional resolution (MOC) |

**Rules:**
- Dead Zone (Zone 3): No new entries. Universal across regimes.
- Power Hour (Zone 5): Wait for MOC imbalance data (15:50 ET) before directional commitment.
- Zone 4 (13:30-14:45): Only trade as "Breakdown" when VIX >20 AND VIX rising. Otherwise treat as low-conviction.

### London Close Timing Correction

**Important:** Verify your London Close timing. In EDT (March 12):
- London Close = 4:00 PM GMT = 12:00 PM ET (not 11:30 ET)
- During EST (November-March): London Close = 4:00 PM GMT = 11:00 AM ET

March 12 is in the transition period — US switched to EDT on March 8, 2026 (second Sunday of March). So London Close on Day 4 = **12:00 PM ET**. Your "recovery to 11:30 ET" may be a US-morning mean reversion pattern, not a London Close effect. Disentangle these.

### Failure Modes

1. **Event days (CPI, FOMC, NFP).** The temporal grid resets around the event release time. Post-FOMC (14:00 ET), zones 4 and 5 merge into a single volatility event. Pre-CPI (08:30 ET), zone 1 is delayed until the release.
2. **OpEx / quad witching.** Options expiration creates non-standard flow patterns. Zone 4 becomes dominated by delta hedging, and Zone 5 by pin risk, neither of which follows the standard bear/bull characterization.
3. **Half days (day before Thanksgiving, Christmas Eve).** Market closes at 13:00 ET. Zones 3-5 do not exist.
4. **Low-VIX grind days.** When VIX <14, the 5-zone structure collapses into noise. Volume is low across all zones, and the "breakdown" and "resolution" zones are indistinguishable from the dead zone.

### Blind Spots

- You are observing during a high-VIX week (VIX 24-27 across all 4 days). The temporal structure is most visible when volatility is elevated. In calm markets (VIX 12-15), the zones exist but the amplitude is much smaller, making them less tradeable.
- Consider adding **volume profile overlays** to confirm zone boundaries. If the U-shaped volume curve shifts on specific days, your zone timings should shift accordingly.
- **Monday vs Friday effects.** Mondays tend to have a stronger opening dump (weekend position adjustments), while Fridays have a weaker Power Hour (institutional desks reducing risk before the weekend). Track day-of-week variation.

**Cross-reference: H2 (Crypto-equity divergence).** The Power Hour crypto bounce (H2) may be an artifact of Zone 5's directional resolution. If equity MOC buying reduces selling pressure, crypto benefits from the same risk-sentiment shift. Test whether the crypto bounce occurs BEFORE or AFTER MOC imbalance data publication at 15:50 ET.

### Promotion Decision: PROMOTE to rule — as a conditional temporal grid with regime-dependent zone characterization.

---

## Overall Assessment

### Priority Ranking for Promotion

| Priority | Hypothesis | Action | Rationale |
|----------|-----------|--------|-----------|
| 1 | H6: Temporal Zones | PROMOTE | Well-documented microstructure, universal applicability, enhances all other rules |
| 2 | H4: ETHA Hybrid | PROMOTE | Direct extension of already-promoted IBIT rule, minimal incremental risk |
| 3 | H3: IBIT Closing Cross | CONFIRM (already promoted) | Add daily metric tracking |
| 4 | H1: ETH Volume Asymmetry | REMAIN HYPOTHESIS | Use as confirmation tool for 4H EMA cross, need more N |
| 5 | H5: BTC RSI Divergence | REMAIN HYPOTHESIS | Consistent with RSI rejection, useful only as ETH vs BTC relative quality |
| 6 | H2: Crypto-Equity Divergence | REMAIN HYPOTHESIS | Insufficient N, survivorship bias risk, mechanism unclear |

### Blind Spots Across All Hypotheses

1. **Regime dependence.** All 4 live sessions occurred in a high-VIX (24-27), risk-off macro environment with specific geopolitical context (tariff uncertainty, CPI). The hypotheses validated here may not hold in VIX <18 bull markets. Priority: re-test temporal zones and crypto-equity divergence in a calm week.

2. **Data source limitations.** TradingView volume data is aggregated and may not reflect true institutional flow. For TWAP detection (S11 Q2) and volume asymmetry (H1), exchange-specific Level 2 data would be materially more reliable.

3. **Sample size.** 4 days is a pilot, not a validation. The promoted rules from S11 (TWAP, COIN, IBIT, China ADR) and the new promotions here (H4, H6) should be tracked with explicit scorecards over the next 20+ trading days.

4. **Cross-asset contamination.** Several hypotheses interact (H1↔H5, H2↔H6, H3↔H4). Tracking these independently risks double-counting the same underlying effect. The Crypto-Equity Microstructure parent module should be the single source of truth for IBIT, ETHA, and COIN dynamics.

5. **Absence of counter-examples.** You have not documented days where the patterns FAILED. Failure documentation is as important as confirmation. Actively track when temporal zones break, when ETHA tracks ETH spot perfectly, or when COIN does NOT diverge. These counter-examples define the boundary conditions of each rule.

### Framework Evolution

The Crypto-Equity Microstructure module now contains:
- **IBIT** (S11 Q4, confirmed H3): equity wrapper, AP threshold 50-150 bps, closing cross recouple
- **ETHA** (H4, promoted): same mechanism, amplified friction (lower AUM, fewer APs)
- **COIN** (S11 Q3): beta-normalized conditional divergence during equity stress
- **Temporal grid** (H6, promoted): 5-zone structure with regime conditioning

Remaining hypotheses (H1 ETH accumulation, H2 crypto-equity divergence, H5 BTC RSI divergence) should continue as tracked observations with explicit N-count targets for re-evaluation.
