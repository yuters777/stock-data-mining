# RTH Calendar Audit — M4 Baseline Probe S304

**N:** 28 | **Clean:** 28 | **Violations:** 0
**NYSE calendar available:** False

**28/28 trades pass RTH calendar checks.**

## Scope of Audit

RTH calendar audit on local N=28 trades. NYSE calendar: unavailable — holiday checks skipped. Entry/exit timestamp hours not available in trade CSV (date-only); RTH hour check requires raw M5 data.

Checks performed:
- Entry date is a weekday
- Exit date is a weekday
- bars_held <= MAX_HOLD_BARS=10
- Entry/exit not on NYSE holidays (if calendar available)
- bars_held consistent with trading day span

**RTH calendar verdict:** PASS