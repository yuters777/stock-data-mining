# N=57 Source Trace — M4 Baseline Probe S304

**Source file:** `results/S44_Module4_Streak_Sensitivity.md`
**Producing script:** scripts/m4_backtest_5yr.py (S44 era, V0 streak definition)

## N=57 Methodology

- Streak definition: V0: close < open (3 consecutive 4H bars)
- Universe: 25 tickers (excl SPY, VIXY; includes SNOW, TXN, IBIT not in canonical 27)
- D6_VIX_ROC filter: NOT applied (pre-D6 implementation)
- VIX gate: prior-day VIX >= 25.0
- RSI gate: RSI(14) < 35.0
- Entry timing: 4H trigger bar close

## N=57 vs Canonical N=47 Delta

- Streak definition change: V0 (close<open) → production (close<prior_close) reduces triggers
- Universe change: 25→27 tickers: removed SNOW/TXN/IBIT, added SMCI/PLTR/AVGO/ARM/TSM/MU/COST/COIN/MSTR/MARA/C/GS/V/BA/BABA/JD/BIDU minus others
- D6 filter: D6_VIX_ROC gate added post-S44, filters some triggers
- HARN-1.1: HARN-1.1: standalone harness under-fires production by ~6.7x

**Conclusion:** N=57 (S44 V0) vs N=47 (canonical) reflects: different streak definition, pre-D6 filter, different ticker universe, and different data vintage. N=57 is NOT the canonical baseline — it is a research artifact from streak sensitivity sprint S44.

## 2/57 Losers Attribution

- Losers: 2/57
- Win rate: 96%
- Source: S44_Module4_Streak_Sensitivity.md V0: WR=96%, N=57 → 2 losers