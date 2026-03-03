# CLAUDE.md — False Breakout Strategy Optimization Lab

## Mission

You are an **autonomous quantitative research lab**. Your goal: iteratively optimize the "False Breakout" trading strategy to achieve maximum risk-adjusted performance on real 5-minute OHLCV data for NYSE/NASDAQ stocks.

You operate in a **hypothesis → implement → backtest → analyze → refine** loop. Each cycle produces measurable results. You stop when further iterations show diminishing returns (<0.5% improvement in out-of-sample Sharpe).

## Repository Structure

```
stock-data-mining/
├── level_detection/          # Existing Phase 1 code (BSU/BPU detection)
├── docs/                     # Strategy specifications (TZ v3.4, research docs)
├── data/                     # 5-min OHLCV CSVs (NVDA, AMZN — loaded from MarketPatterns_AI or local)
├── backtester/               # NEW — you build this
│   ├── core/
│   │   ├── level_detector.py     # D1 level detection (fractals, BPU, mirror, scoring)
│   │   ├── pattern_engine.py     # LP1, LP2, CLP, Model4 recognition
│   │   ├── filter_chain.py       # ATR, volume, time, squeeze, earnings filters
│   │   ├── risk_manager.py       # Stop, target, position sizing, circuit breakers
│   │   └── trade_manager.py      # Entry execution, partial TP, breakeven, EOD exit
│   ├── backtester.py             # Main orchestrator: data → levels → signals → trades → results
│   ├── optimizer.py              # Parameter grid search + walk-forward validation
│   ├── analyzer.py               # Signal funnel, performance metrics, regime analysis
│   └── tests/
│       ├── test_level_detector.py
│       ├── test_pattern_engine.py
│       ├── test_filter_chain.py
│       └── test_risk_manager.py
├── experiments/              # NEW — experiment logs (auto-generated)
│   └── EXPERIMENT_LOG.md
├── results/                  # NEW — final outputs
│   └── OPTIMIZATION_REPORT.md
└── CLAUDE.md                 # This file
```

## Data

- **NVDA_data.csv** and **AMZN_data.csv**: 5-min OHLCV, ~45K bars each, Feb 2025 – Jan 2026
- Columns: `Datetime, Open, High, Low, Close, Volume, Ticker`
- Aggregate to D1 for level detection, use M5 for intraday signals
- **Split: 70% in-sample (Feb–Oct 2025) / 30% out-of-sample (Oct 2025–Jan 2026)**

## Strategy Specification (Baseline v3.4)

### Module 1: Level Detection (D1)
- **BSU:** Fractal highs/lows. `H[i] > max(H[i-k]...H[i-1]) AND H[i] > max(H[i+1]...H[i+k])`, k=5 for D1
- **BPU:** Subsequent touch within tolerance. Min 1 BPU to activate level
- **Tolerance:** 5 cents for stocks $20–100; 0.1% for $100+
- **Anti-Sawing:** CrossCount ≥ 3 in 20 bars → INVALIDATE level
- **Mirror Validation:** After breakout: price must travel ≥3×ATR_D1 away AND stay ≥3 days beyond → MIRROR_CANDIDATE. On return + BPU → MIRROR_CONFIRMED (Score=10)
- **Scoring:** Mirror=10, Penny-touches(3+)=9, Paranormal-stop=8, Gap-boundary=8, Age=7, Round(.00/.50)=6, Air=IGNORE

### Module 2: ATR & Energy Filter
- **Modified ATR(5):** Exclude bars where TrueRange > 2×ATR_prev or < 0.5×ATR_prev
- **ATR Ratio:** `DistanceTraveled / ATR_D1` where DistanceTraveled = distance from day extreme to level in trade direction
- **Hard Block:** ATR_ratio < 0.30 → BLOCK (no exceptions)
- **Entry Threshold:** ATR_ratio ≥ 0.75 → ALLOW (configurable)
- **Paranormal zone:** ATR_ratio > 1.0 → bonus priority

### Module 3: Pattern Recognition (M5)
- **LP1 (1-bar):** Open < Level AND High > Level AND Close < Level (for short). TailRatio = (High-Level)/(High-Low); strong if > 0.30
- **LP2 (2-bar):** Bar1 closes beyond level; Bar2 closes back. Filters: Bar2 is NEXT bar, Bar2.High ≤ Bar1.High, Engulfing: Bar2.Close < Bar1.Open
- **CLP (3-7 bars):** Breakout → 3-5 bars consolidate beyond level (none close back) → trigger bar returns. MaxDeviation: 2.5×ATR_M5
- **Model 4:** Paranormal bar (Range ≥ 2×ATR(5)) + Mirror level (Score=10) + any LP pattern → MAXIMUM priority, position ×1.5

### Module 4: Volume (VSA)
- V > 2×Avg AND Close < Level → Buying Climax (strongest short signal)
- V < 0.7×Avg on breakout → no institutional interest (FB likely)
- V > 2×Avg AND Close > Level → true breakout → BLOCK

### Module 5: Time & Event Filters
- Open delay: no signals before 09:35 ET
- Earnings day: BLOCK ticker entirely
- Time buckets: Open (9:35–10:30), Midday (10:30–14:00), Close (14:00–16:00)

### Module 6: Risk Management
- Stop: beyond LP candle extreme + buffer (max($0.02, 0.10×ATR_M5))
- **Dynamic Stop Cap:** stop ≤ 15% of ATR_D1
- **Hard Cap:** $20-50→15¢, $50-100→25¢, $100-200→40¢, >$200→Dynamic only
- **Min Stop:** max(0.15×ATR_M5, $0.05) — prevents micro-stops
- Final: MIN(Dynamic, Hard)
- **Min R:R:** 3.0 (target must be ≥ 3× stop)
- Target: nearest opposing D1 level minus offset
- **Partial TP:** 50% at 2R, remainder at full target
- Breakeven: after 2× stop distance OR 50% of TP path
- Position size: `Capital × 0.3% / |Entry - Stop|`
- **Slippage:** $0.02/share entry + $0.02/share exit
- Circuit breakers: 3 consecutive stops → stop day; 1% daily loss → stop; 2% weekly; 8% monthly

### Module 7: Gap Fade (Optional — implement after core is validated)
- Breakaway gap (crosses D1 level) → NEVER fade
- Common gap (within range) → fade target = prev close
- Exhaustion gap (end of trend) → ideal fade setup

## Development Protocol

### Phase 1: Build & Verify (do this FIRST)

1. Build each module independently with unit tests
2. **Critical assertion checks in every module:**
   ```python
   # In filter_chain.py — MUST exist:
   assert atr_ratio >= ATR_BLOCK_THRESHOLD, f"ATR {atr_ratio} below block zone"
   
   # In trade_manager.py — MUST exist:
   assert not has_open_position(ticker), f"Already in position for {ticker}"
   assert not stopped_today_at_level(ticker, level), f"Already stopped at this level today"
   
   # In risk_manager.py — MUST exist:
   assert stop_distance <= max_stop, f"Stop {stop_distance} exceeds cap {max_stop}"
   assert rr_ratio >= MIN_RR, f"R:R {rr_ratio} below minimum {MIN_RR}"
   ```
3. Run on first 30 days of data — manually verify 3-5 trades against chart logic
4. Generate **Signal Funnel** report (see below)

### Phase 2: Baseline Backtest

Run the full spec on both tickers. Generate:
- Signal funnel (where signals are lost)
- Trade list with all metrics
- Performance: WR, Avg R, Profit Factor, Sharpe, Max DD
- Level audit: total levels, confirmed, mirrors, invalidated

### Phase 3: Optimization Loop

```
FOR each experiment:
    1. Form hypothesis (e.g., "Reducing ATR_MIN_ENTRY from 0.75 to 0.65 will increase trade count without degrading WR")
    2. Change ONE parameter (or add/remove ONE filter)
    3. Run in-sample backtest
    4. Compare vs baseline: trades, WR, Sharpe, PF
    5. If improved → validate on out-of-sample
    6. Log to EXPERIMENT_LOG.md
    7. If OOS confirms → update baseline
    8. Repeat
```

**Parameters to explore (priority order):**

| Priority | Parameter | Range to Test | Hypothesis |
|----------|-----------|---------------|------------|
| 1 | FRACTAL_DEPTH | 3, 5, 7, 10 | Shallower = more levels = more trades |
| 2 | ATR_MIN_ENTRY | 0.60, 0.65, 0.70, 0.75, 0.80 | Lower = more trades, possibly lower WR |
| 3 | MAX_STOP_ATR_PCT | 0.10, 0.15, 0.20, 0.25 | Higher = fewer "stop too big" blocks |
| 4 | MIN_RISK_REWARD | 2.0, 2.5, 3.0, 3.5 | Lower RR + higher WR might beat 3:1 |
| 5 | TOLERANCE | 3¢, 5¢, 7¢, 10¢ / 0.08%, 0.10%, 0.12% | Wider = more BPU matches |
| 6 | PARTIAL_TP_AT | 1.5R, 2.0R, 2.5R | Earlier TP = higher WR, lower avg R |
| 7 | CLP_MIN_BARS | 2, 3, 4, 5 | Fewer = more CLP signals |
| 8 | LP2_ENGULFING | true / false | Strict vs relaxed LP2 |
| 9 | TAIL_RATIO_MIN | 0.10, 0.15, 0.20, 0.25 | LP1 quality filter |
| 10 | Add: H1 trend filter | on/off | Multi-TF confirmation |
| 11 | Add: RSI divergence | on/off | Momentum confirmation |
| 12 | Remove: Volume filter | on/off | Is VSA helping or hurting? |
| 13 | Time bucket filter | Open-only / All-day | Best session for signals |

**After grid exploration, test combinations of top 3-5 best individual changes.**

### Phase 4: Walk-Forward Validation

Don't trust a single train/test split. Run:
- Rolling 3-month train / 1-month test
- 8 windows across the dataset
- Report: mean OOS Sharpe, std dev, worst window

### Phase 5: Final Report

Generate `results/OPTIMIZATION_REPORT.md`:
- Baseline vs Optimized comparison table
- Parameter changes with justification
- Signal funnel (before/after)
- Equity curves
- Walk-forward stability
- Recommended production parameters

## Signal Funnel Template

Generate this for EVERY backtest run:

```
SIGNAL FUNNEL — {config_name} — {ticker}
════════════════════════════════════════
Total D1 levels generated:                  ???
  Confirmed (≥1 BPU):                       ???
  Mirror confirmed:                         ???
  Invalidated (sawing):                     ???

Total M5 level proximity events:            ???
  └─ Pattern formed (LP1/LP2/CLP):         ???
     ├─ Blocked by ATR < 0.30:             ???
     ├─ Blocked by ATR < threshold:        ???
     ├─ Blocked by stop too big:           ???
     ├─ Blocked by R:R < minimum:          ???
     ├─ Blocked by time filter:            ???
     ├─ Blocked by volume (true BO):       ???
     ├─ Blocked by squeeze:                ???
     ├─ Blocked by earnings:               ???
     ├─ Blocked by open position:          ???
     └─ ✅ VALID SIGNALS:                   ???
        ├─ Winners:                         ???
        ├─ Losers:                          ???
        └─ EOD exits:                       ???
```

## Experiment Log Format

Each experiment in `experiments/EXPERIMENT_LOG.md`:

```markdown
## EXP-{NNN}: {Title}
**Date:** {date}
**Hypothesis:** {what we expect}
**Change:** {parameter X from A to B}
**Baseline:** {WR}% / {Sharpe} / {trades} trades
**Result (IS):** {WR}% / {Sharpe} / {trades} trades
**Result (OOS):** {WR}% / {Sharpe} / {trades} trades
**Verdict:** ✅ ACCEPT / ❌ REJECT / ⚠️ INCONCLUSIVE
**Notes:** {observations}
```

## Critical Rules

1. **NEVER skip the ATR filter.** It IS the strategy. Without it you're gambling.
2. **ONE trade per ticker at a time.** No re-entry at same level same day after stop.
3. **Assert everything.** If an assertion fails, the trade doesn't happen. Period.
4. **Log everything.** Every blocked signal goes into the funnel. We need to know WHY trades don't happen.
5. **OOS is truth.** In-sample is for hypothesis generation. Out-of-sample is for validation. Never optimize on OOS.
6. **Include slippage.** $0.02/share each way. Micro-stop strategies die under real costs.
7. **Mirror levels matter.** If zero mirrors are detected in 11 months, the detection is broken — debug it.

## Getting Started

```bash
# 1. Check existing code
ls level_detection/
cat level_detection/*.py

# 2. Check available data
ls data/ || ls MarketPatterns_AI/

# 3. Build backtester modules (Phase 1)
mkdir -p backtester/core backtester/tests experiments results

# 4. Start with level_detector.py — build on existing level_detection/ code
# 5. Add tests, verify against spec
# 6. Then pattern_engine → filter_chain → risk_manager → trade_manager
# 7. Wire up backtester.py
# 8. Run baseline → begin optimization loop
```

## Success Criteria

The optimization is successful when we achieve ALL of:
- [ ] Out-of-sample Sharpe > 1.0 (annualized)
- [ ] Win Rate > 45% with Avg R > 1.5
- [ ] Profit Factor > 1.5
- [ ] Max Drawdown < 5%
- [ ] ≥ 20 trades in OOS period (statistical significance)
- [ ] Walk-forward: positive Sharpe in ≥ 6 of 8 windows
- [ ] All assertions pass (zero filter violations)
