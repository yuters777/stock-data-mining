# Power Hour Audit — Summary of Results (PH1–PH6)

**Zone 5** (Power Hour): 14:45–16:00 ET
**Zone 3** (Midday Lull): 12:00–13:30 ET
**Zone 2** (Mid-morning): 10:00–12:00 ET
**Metric**: Absolute return = |close_end − close_start| / close_start
**Data**: M5 regular-session bars, 27 tickers, ~282 trading days (Feb 2025–Mar 2026)

---

## PH1: Per-Ticker Power Hour Analysis

**Question**: Does Zone 5 produce larger absolute returns than Zone 3 across tickers?

| Finding | Value |
|---------|-------|
| Tickers with Z5/Z3 ratio > 1.0 | 15/27 (56%) |
| Tickers with significant Z5 > Z3 (p<0.05) | 13/27 (48%) |
| Median ratio across tickers | 1.13 |
| Mean ratio across tickers | 1.03 |

**Verdict**: **Mixed.** A slim majority of tickers show Power Hour > midday, but it is not universal. The strongest effects are in high-momentum tech/crypto names (TSM, META, AMD, GOOGL). Many low-vol names (C, BA, GS, COST, V) show the opposite — Zone 3 dominates.

---

## PH2: VIX Regime Analysis

**Question**: Does VIX level affect the Power Hour advantage?

| Regime | N days | Z5 (bps) | Z3 (bps) | Ratio | P-value |
|--------|--------|----------|----------|-------|---------|
| Low (<16) | 66 | 31.2 | 29.3 | 1.06 | 0.210 |
| Normal (16–20) | 128 | 34.9 | 37.1 | 0.94 | 0.038 * |
| Elevated (20–25) | 56 | 46.3 | 47.5 | 0.98 | 0.568 |
| High (>=25) | 23 | 68.7 | 87.5 | 0.78 | 0.003 ** |

**Verdict**: **Power Hour advantage erodes as VIX rises.** Only in low-VIX (<16) environments does Zone 5 outperform Zone 3. In high-VIX (>=25), Zone 3 significantly exceeds Zone 5 — midday absorbs more of the volatility surge.

---

## PH3: Event Proxy Days

**Question**: Do high-VIX-range days (top 25% by VIXY daily range) amplify Zone 5 or Zone 3 more?

| Group | N days | Z5 (bps) | Z3 (bps) | Ratio | P-value |
|-------|--------|----------|----------|-------|---------|
| Event proxy (top 25%) | 71 | 53.8 | 60.3 | 0.89 | 0.009 ** |
| Normal | 211 | 34.2 | 34.8 | 0.98 | 0.480 |

**Verdict**: **Event days amplify Zone 3 more than Zone 5.** Both zones scale up (Z5 by 1.57×, Z3 by 1.73×), but Zone 3 captures the larger share. The Power Hour advantage weakens on volatile days.

---

## PH4: Beta Group Analysis

**Question**: Does the Power Hour effect vary by stock beta?

| Group | Tickers | Z5 (bps) | Z3 (bps) | Ratio | P-value |
|-------|---------|----------|----------|-------|---------|
| High-beta (top 9) | SPY, MARA, MU, TSLA, AMD, COIN, PLTR, TSM, AMZN | 44.2 | 38.2 | 1.16 | <0.001 *** |
| Medium-beta (mid 9) | IBIT, BA, NVDA, GOOGL, META, GS, C, BIDU, AVGO | 36.5 | 42.6 | 0.86 | <0.001 *** |
| Low-beta (bottom 9) | TXN, AAPL, BABA, MSFT, SNOW, JPM, V, COST, VIXY | 36.7 | 43.1 | 0.85 | <0.001 *** |

**Verdict**: **Power Hour is exclusively a high-beta phenomenon.** Only the top 9 tickers by 60-day trailing beta show Zone 5 > Zone 3. Medium and low-beta tickers show the opposite, all highly significant.

---

## PH5: Beta × VIX Interaction

**Question**: Is the Power Hour effect concentrated in high-beta tickers on elevated-VIX days?

| # | Subset | Z5 (bps) | Z3 (bps) | Ratio | P-value |
|---|--------|----------|----------|-------|---------|
| 1 | High-beta × Elevated+ VIX (>=20) | 58.3 | 53.7 | 1.09 | 0.151 |
| 2 | High-beta × Low/Normal VIX (<20) | 38.4 | 31.9 | **1.20** | <0.001 *** |
| 3 | Low-beta × Elevated+ VIX | 52.9 | 64.7 | 0.82 | 0.021 * |
| 4 | Low-beta × Low/Normal VIX | 30.3 | 35.0 | 0.86 | 0.003 ** |

**Verdict**: **Surprise — the best subset is #2, not #1.** High-beta tickers in calm markets (VIX <20) show the strongest and only significant Power Hour advantage (ratio 1.20, p<0.001). Elevated VIX dilutes the effect even for high-beta names. Beta is the primary driver; VIX modulates magnitude but doesn't flip the sign.

---

## PH6: Directional Analysis

**Question**: Does Power Hour resolve direction (align with the day's trend) or just amplify noise?

Focused on best subset: **High-beta × Low/Normal VIX**.

| Metric | Zone 5 | Zone 2 (control) |
|--------|--------|-----------------|
| Mean signed return (bps) | +3.03 (p=0.04 *) | +2.92 (p=0.53) |
| Day-direction agreement | 56.3% (p<0.001 ***) | 54.7% (p<0.001 ***) |

**Verdict**: **Power Hour resolves direction, not just noise.** Zone 5 carries a small but significant positive drift (+3 bps), and aligns with the day's direction 56.3% of the time — significantly above chance. This is stronger than Zone 2's directional agreement (54.7%). The Power Hour for high-beta names in calm markets produces larger moves that systematically trend with the session's direction.

---

## Overall Verdict

The "Power Hour beats midday" claim is **conditionally true**, with strict qualifying conditions:

1. **Stock selection matters most.** The effect is real and significant for **high-beta tickers only** (top 9 by 60-day trailing beta vs SPY). For medium and low-beta names, midday (Zone 3) actually produces larger absolute returns.

2. **Calm markets are better.** Counter to intuition, the Power Hour advantage is strongest when VIX < 20. Elevated VIX amplifies both zones, but midday absorbs more of the extra volatility, eroding the Power Hour edge.

3. **It resolves direction.** In the best subset (high-beta × calm VIX), Power Hour moves are not random — they align with the day's prevailing direction 56% of the time and carry a positive signed drift. This is trend-confirmation, not noise.

4. **The optimal conditions are specific.** The only statistically significant Power Hour advantage occurs at the intersection of high beta and low/normal VIX — roughly 9 of 27 tickers on roughly 70% of trading days.

### Trading Implication

A Power Hour strategy should:
- **Filter for high-beta names** (MARA, MU, TSLA, AMD, COIN, PLTR, TSM, AMZN, SPY)
- **Avoid elevated-VIX days** (VIX >= 20), where the edge disappears
- **Trade in the direction of the day's trend** (established by Zone 1/2), since Zone 5 confirms rather than reverses
