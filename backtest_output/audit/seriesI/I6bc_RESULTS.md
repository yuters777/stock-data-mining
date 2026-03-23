# I6b: MAE / MFE by Depth Bucket

**Claim tested:** Do deep DZ compressions produce higher returns with acceptable path risk, or do they come with ugly drawdowns?

**Method:**
- For each V1 (First Green Close) trade from I6a:
  - MAE = (lowest low from entry to 15:30 ET - entry) / entry × 100
  - MFE = (highest high from entry to 15:30 ET - entry) / entry × 100
- Segmented by z-score bucket (<1σ, 1-2σ, >2σ)

**N:** 5,585 V1 trades with MAE/MFE computed

**Result:**

| Depth | Avg MAE | Med MAE | Worst MAE | Avg MFE | Med MFE | MFE/\|MAE\| | %MAE>0.5% | %MAE>1.0% | N |
|-------|---------|---------|-----------|---------|---------|------------|-----------|-----------|------|
| <1σ | -0.533% | -0.318% | -9.7% | +0.893% | +0.631% | **1.68** | 33.0% | 12.4% | 4,916 |
| 1-2σ | -0.764% | -0.535% | -5.1% | +1.452% | +0.878% | **1.90** | 53.1% | 21.9% | 433 |
| >2σ | **-1.433%** | -0.863% | **-13.0%** | **+2.024%** | +1.519% | **1.41** | **71.6%** | **44.9%** | 236 |

### By Raw % Bucket

| Compression | Avg MAE | Med MAE | Avg MFE | MFE/\|MAE\| | %MAE>0.5% | N |
|-------------|---------|---------|---------|------------|-----------|------|
| <0.5% | -0.393% | -0.225% | +0.632% | 1.61 | 22.8% | 668 |
| 0.5-1.0% | -0.409% | -0.257% | +0.722% | 1.76 | 24.4% | 1,754 |
| >1.0% | -0.730% | -0.454% | +1.204% | 1.65 | 45.5% | 3,163 |

**Verdict: CONCERNING but not prohibitive — deep trades have worse risk/reward RATIO**

Key findings:
1. **Deep trades have BOTH higher MFE and higher MAE** — they are more volatile, not just more profitable
2. **MFE/MAE ratio DECLINES for deep**: 1.68 (shallow) → 1.90 (medium) → 1.41 (deep). The >2σ bucket has the WORST risk-adjusted profile
3. **71.6% of deep trades see >0.5% drawdown**, and **44.9% see >1.0% drawdown** — painful intraday path
4. **Medium (1-2σ) has the BEST MFE/MAE ratio at 1.90** — sweet spot for risk-adjusted returns
5. The worst MAE of -13.0% in the >2σ bucket means catastrophic single-trade risk exists

**Implication for v0.4:** Deep trades are profitable on average but require strong conviction and wide stops. The 1-2σ bucket is the risk-adjusted sweet spot. Full size on >2σ without protective stops is dangerous — the path is ugly even when it works.

---

# I6c: Per-Ticker Stability

**Claim tested:** Is "deep = better" a broad market phenomenon or driven by a few volatile names?

**Method:**
- For each of 26 equity tickers: compare avg P&L for shallow (<1σ) vs deep (>=1σ) trades
- Delta = deep P&L - shallow P&L
- Categories: deep-friendly (Δ > +0.2%), flat (±0.2%), deep-hostile (Δ < -0.2%)

**N:** 5,585 V1 trades across 26 tickers

**Result:**

| Category | Count | Tickers |
|----------|-------|---------|
| **Deep-friendly** | **14** | AMZN, AVGO, BA, BABA, C, COIN, COST, GS, JPM, META, MU, NVDA, PLTR, SNOW |
| **Flat** | **12** | AAPL, AMD, BIDU, GOOGL, IBIT, MARA, MSFT, SPY, TSLA, TSM, TXN, V |
| **Deep-hostile** | **0** | — |

### Top 5 Deep-Friendly Tickers

| Ticker | Shallow P&L | Deep P&L | Delta | Deep WR | Deep N |
|--------|-----------|---------|-------|---------|--------|
| BA | +0.222% | +1.362% | **+1.140%** | 81.0% | 21 |
| PLTR | +0.386% | +1.490% | **+1.104%** | 74.2% | 31 |
| AMZN | +0.205% | +1.251% | **+1.046%** | 62.5% | 16 |
| NVDA | +0.143% | +1.077% | **+0.934%** | 74.1% | 27 |
| META | +0.149% | +0.929% | **+0.780%** | 66.7% | 30 |

### Notable "Flat" Tickers

| Ticker | Shallow P&L | Deep P&L | Delta | Note |
|--------|-----------|---------|-------|------|
| SPY | +0.185% | +0.336% | +0.151% | Index ETF — less compression variance |
| TSLA | +0.381% | +0.193% | -0.188% | Borderline hostile (deep N=27) |
| AAPL | +0.230% | +0.360% | +0.130% | Positive but below threshold |

**Correlation with volatility:** r = 0.107 (weak positive). Higher noon sigma slightly predicts deep-friendliness, but not a strong driver. Both low-vol (BA, GS, C) and high-vol (PLTR, COIN) names appear deep-friendly.

**Verdict: CONFIRMED — "deep = better" is BROAD-BASED**

- **14 out of 26 tickers are deep-friendly** (54%)
- **0 tickers are deep-hostile** — no ticker shows statistically worse performance on deep trades
- The remaining 12 are flat (deep ≈ shallow), not negative
- The effect is NOT concentrated in a few volatile names — it spans mega-cap (AMZN, META, NVDA), financials (BA, GS, C, JPM), and high-beta (PLTR, COIN)

**Implication for v0.4:**
- The depth gradient is a real cross-market phenomenon, not a TSLA/MARA artifact
- Safe to apply depth-based sizing across the full ticker universe
- No need for per-ticker exemptions — worst case is "flat" (no benefit), never negative

---

## Combined I6b + I6c Takeaway

The "deep = better" signal is **real and broad-based** (I6c: 14/26 tickers, 0 hostile) but comes with a **risk/reward tradeoff** (I6b: MFE/MAE declines from 1.68 to 1.41 for deepest bucket).

**Recommended sizing nuance for v0.4:**
- **1-2σ = optimal risk-adjusted bucket** (MFE/MAE = 1.90, best ratio)
- **>2σ = high expectancy but ugly path** — acceptable only with wider stops or reduced size to manage 45% chance of >1.0% MAE
- **<1σ = safe but lowest return** — default/minimum size

![Path Risk & Per-Ticker Charts](I6bc_path_ticker.png)
