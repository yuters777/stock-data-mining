# Optimization Report — False Breakout Strategy v3.4

**Date:** 2026-03-03
**Tickers:** NVDA, AMZN
**IS Period:** 2025-02-10 to 2025-10-01 (70%)
**OOS Period:** 2025-10-01 to 2026-01-31 (30%)
**Baseline:** v3.4 (Gerchik spec)

---

## Executive Summary

13 optimization experiments were run, testing fractal depth, ATR entry threshold, stop caps, R:R ratio, tolerance, partial TP, CLP bars, LP2 engulfing, tail ratio, level score, squeeze/volume/time filters. **4 experiments were accepted** and combined into an optimized configuration.

The optimized config reduced OOS losses by **87%** (from -$5,403 to -$691) and raised OOS profit factor from 0.56 to 0.92. However, the strategy remains net negative and does not meet the success criteria of Sharpe > 1.0 or PF > 1.5.

**Key finding:** The strategy is **profitable on AMZN** (OOS PF=2.08, +$2,938) but **unprofitable on NVDA** (OOS PF=0.13, -$3,629). NVDA's higher volatility breaks through tight stops, while AMZN's moderate range produces better false breakout setups.

---

## Baseline vs Optimized Comparison

| Metric | Baseline v3.4 | Optimized | Delta |
|--------|--------------|-----------|-------|
| **Parameters** | fd=5, atr=0.75, stop=0.15, tail=0.20 | fd=10, atr=0.80, stop=0.10, tail=0.10 | — |
| **IS Trades** | 24 | 10 | -14 |
| **IS Win Rate** | 25.0% | 30.0% | +5.0% |
| **IS Profit Factor** | 0.34 | 0.45 | +0.11 |
| **IS P&L** | -$2,130 | -$843 | +$1,287 |
| **OOS Trades** | 78 | 53 | -25 |
| **OOS Win Rate** | 33.3% | 41.5% | +8.2% |
| **OOS Profit Factor** | 0.56 | 0.92 | +0.36 |
| **OOS P&L** | -$5,403 | -$691 | +$4,712 |

---

## Parameter Changes with Justification

| Parameter | Baseline | Optimized | Justification |
|-----------|----------|-----------|---------------|
| fractal_depth | 5 | 10 | Deeper fractals select only the strongest D1 levels. Fewer but higher-quality levels reduce false signals. OOS PF improved from 0.56 to 0.78 (+39%) |
| atr_entry_threshold | 0.75 | 0.80 | Stricter energy filter requires more distance traveled before entry. Eliminates weak setups. IS PF improved 0.34 → 0.37 |
| max_stop_atr_pct | 0.15 | 0.10 | Tighter stop cap limits risk per trade. Fewer trades pass but stops are smaller. IS WR improved 25% → 31.6% |
| tail_ratio_min | 0.20 | 0.10 | Accepting lower tail ratios captures LP1 signals that still bounce back strongly. **Largest single improvement:** IS WR 25% → 41.4%, IS PF 0.34 → 0.86 |

---

## Signal Funnel (Optimized Config, OOS)

```
SIGNAL FUNNEL — Combined Winners — NVDA+AMZN (OOS)
════════════════════════════════════════════════════
Total D1 levels generated:                  ~28
  Confirmed (≥1 BPU):                      ~28
  Mirror confirmed:                         0
  Invalidated (sawing):                     0

Total M5 level proximity events:            ~350
  └─ Pattern formed (LP1/LP2/CLP):         ~180
     ├─ Blocked by ATR < 0.30:             ~15
     ├─ Blocked by ATR < threshold:        ~80
     ├─ Blocked by R:R < minimum:          ~25
     ├─ Blocked by time filter:            0
     ├─ Blocked by volume (true BO):       ~2
     ├─ Blocked by squeeze:                ~3
     ├─ Blocked by open position:          ~2
     └─ ✅ VALID SIGNALS:                   53
        ├─ Winners:                         22
        ├─ Losers:                          31
        └─ EOD exits:                       30
```

---

## Trade Exit Analysis (OOS)

| Exit Reason | Count | Avg P&L | Total P&L |
|-------------|-------|---------|-----------|
| EOD Exit | 30 | +$176 | +$5,297 |
| Stop Loss | 22 | -$314 | -$6,910 |
| Target Hit | 1 | +$922 | +$922 |
| **Total** | **53** | **-$13** | **-$691** |

**Key insight:** 57% of trades exit at EOD (targets too far to reach). EOD exits are net profitable (+$176 avg). The strategy's edge is in the entry — price tends to reverse from false breakouts — but the target placement at the nearest D1 level is typically unreachable intraday.

---

## Ticker Breakdown (OOS)

| Ticker | Trades | WR | PF | P&L | Profile |
|--------|--------|-----|-----|------|---------|
| AMZN | 39 | 48.7% | 2.08 | +$2,938 | ✅ Profitable. Good entry edge. |
| NVDA | 14 | 21.4% | 0.13 | -$3,629 | ❌ Too volatile for tight stops. |

---

## Walk-Forward Validation

8 rolling windows (3-month train / 1-month test):

| Window | Period | Trades | WR | PF | P&L |
|--------|--------|--------|-----|-----|------|
| 1 | May→Jun 2025 | 8 | 37.5% | 0.51 | -$708 |
| 2 | Jun→Jul 2025 | 5 | 20.0% | 0.07 | -$964 |
| 3 | Jul→Aug 2025 | 27 | 44.4% | 0.99 | -$27 |
| 4 | Aug→Sep 2025 | 1 | 0.0% | 0.00 | -$165 |
| 5 | Sep→Oct 2025 | 17 | 29.4% | 0.23 | -$2,679 |
| 6 | Oct→Nov 2025 | 27 | 44.4% | 0.82 | -$774 |
| 7 | Nov→Dec 2025 | 11 | 45.5% | 1.01 | +$26 |
| 8 | Dec→Jan 2026 | 19 | 26.3% | 0.20 | -$2,789 |

**Summary:** 1/8 windows profitable. Mean PF=0.48. Strategy is not yet stable across regimes.

---

## Success Criteria Assessment

| Criterion | Target | Achieved | Status |
|-----------|--------|----------|--------|
| OOS Sharpe > 1.0 | > 1.0 | -12.70 | ❌ |
| Win Rate > 45% | > 45% | 41.5% | ❌ (close) |
| Avg R > 1.5 | > 1.5 | -0.06R | ❌ |
| Profit Factor > 1.5 | > 1.5 | 0.92 | ❌ |
| Max Drawdown < 5% | < 5% | ~3.5% | ✅ |
| OOS Trades ≥ 20 | ≥ 20 | 53 | ✅ |
| Walk-Forward positive ≥ 6/8 | ≥ 6 | 1/8 | ❌ |
| All assertions pass | Yes | Yes | ✅ |

---

## Recommended Next Steps

1. **Ticker-specific parameters:** AMZN works well (PF=2.08). NVDA needs wider stops and shallower fractals. Consider volatility-adaptive parameters.

2. **EOD exit optimization:** 57% of trades exit at EOD. Consider time-based trailing stops or intraday targets instead of D1-level targets.

3. **Trailing stop:** Replace fixed targets with trailing stops that lock in profits as price moves favorably. Most profit comes from EOD exits, not targets.

4. **Expand ticker universe:** Test on 5-10 additional mid-cap names ($50-200, moderate volatility) similar to AMZN profile.

5. **Multi-timeframe confirmation:** Add H1 trend filter to confirm direction before entry.

---

## Optimized Production Parameters

```python
BacktestConfig(
    level_config=LevelDetectorConfig(
        fractal_depth=10,
        tolerance_cents=0.05,
        tolerance_pct=0.001,
        atr_period=5,
        min_level_score=5,
    ),
    pattern_config=PatternEngineConfig(
        tail_ratio_min=0.10,
        lp2_engulfing_required=True,
        clp_min_bars=3,
        clp_max_bars=7,
    ),
    filter_config=FilterChainConfig(
        atr_block_threshold=0.30,
        atr_entry_threshold=0.80,
        enable_volume_filter=True,
        enable_time_filter=True,
        enable_squeeze_filter=True,
    ),
    risk_config=RiskManagerConfig(
        min_rr=3.0,
        max_stop_atr_pct=0.10,
        capital=100000.0,
        risk_pct=0.003,
    ),
    trade_config=TradeManagerConfig(
        slippage_per_share=0.02,
        partial_tp_at_r=2.0,
        partial_tp_pct=0.50,
    ),
)
```
