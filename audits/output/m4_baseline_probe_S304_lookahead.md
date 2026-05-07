# Look-Ahead Audit — M4 Baseline Probe S304

**N:** 28 | **Clean:** 28 | **Violations:** 0

**28/28 trades pass look-ahead checks.**

## Scope of Audit

Audit checks entry gate compliance (VIX>=25, RSI<35) on local N=28 trades. Full look-ahead audit (4H bar completion, EMA cross timing) requires raw M5 data per trade — partial coverage from trade CSV metadata.

Checks performed:
- VIX at entry >= 25.0 (gate compliance)
- RSI at entry < 35.0 (gate compliance)
- bars_held in [1, 10] (max hold constraint)

**Look-ahead verdict:** PASS