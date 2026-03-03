# CLAUDE.md v3 — Breakthrough Phase

## Context

Phase 1 (Build) and Phase 2 (Parameter Optimization) are COMPLETE. 13 experiments ran. Strategy improved from PF=0.56 to PF=0.92 on OOS, but remains net negative. **The core problem is structural, not parametric.**

**DO NOT re-run v2 experiments. DO NOT rebuild modules.** Focus on the three structural changes below.

---

## Key Findings from Phase 2

### What Works
- **AMZN is profitable:** OOS PF=2.08, WR=48.7%, +$2,938 across 39 trades
- **NVDA destroys results:** OOS PF=0.13, WR=21.4%, -$3,629 across 14 trades
- **EOD exits are net positive:** 30 EOD exits averaged +$176 each (+$5,297 total)
- **Stops are net negative:** 22 stops averaged -$314 each (-$6,910 total)
- **Only 1 trade hit target** out of 53 OOS trades

### The Structural Problem
The strategy detects false breakouts correctly (price reverses from level) but the **exit mechanism is broken for intraday trading**:
- D1 targets are $5-$60 away — unreachable in one session
- MIN_RR=3.0 doesn't matter because targets never hit regardless
- Partial TP @2R never triggers because 2R ($0.60-$1.60) requires reaching the D1 target
- The actual edge is: entry reversal + directional drift → EOD exit captures 0.2-0.7R

### Current Best Config (from v2)
```python
fractal_depth = 10
atr_entry_threshold = 0.80
max_stop_atr_pct = 0.10
tail_ratio_min = 0.10
# Everything else = v3.4 baseline
```

---

## Phase 3: Three Structural Experiments

### STRUCT-001: Intraday Target System (Replace D1 targets with M5/H1)

**Problem:** D1-level targets are unreachable intraday. 57% of trades exit EOD.

**Hypothesis:** Using intraday support/resistance (M5 fractals or H1 levels) as targets will create reachable targets within 1-3 hours, converting EOD drifts into actual TP hits.

**Implementation:**

```python
# CURRENT (broken):
target = nearest_opposing_D1_level - offset  # $5-$60 away, never reached

# NEW — Tiered target system:
def calculate_targets(entry, stop, direction, m5_bars, h1_levels, d1_levels):
    stop_dist = abs(entry - stop)
    
    # Tier 1: Nearest M5 fractal in profit direction (must be ≥ 2R away)
    m5_target = find_nearest_m5_fractal(entry, direction, m5_bars, min_distance=2.0 * stop_dist)
    
    # Tier 2: Nearest H1 level (must be ≥ 2R away)
    h1_target = find_nearest_h1_level(entry, direction, h1_levels, min_distance=2.0 * stop_dist)
    
    # Tier 3: Fixed R-multiple (fallback)
    fixed_target = entry + direction * 2.5 * stop_dist
    
    # Use nearest valid target
    target = nearest_of(m5_target, h1_target, fixed_target)
    
    # Sanity check: target must be ≥ 2R and ≤ 5R
    if distance(entry, target) < 2.0 * stop_dist:
        return SKIP  # No reachable target
    if distance(entry, target) > 5.0 * stop_dist:
        target = entry + direction * 5.0 * stop_dist  # Cap at 5R
    
    return target
```

**What to build:**
1. M5 fractal detector (k=3, running on intraday data)
2. H1 level aggregator (aggregate M5→H1, find fractals with k=3-5)
3. Tiered target selector
4. Update trade_manager to use new targets

**MIN_RR:** Lower to 2.0 (targets are now reachable)

**Test matrix:**

| Experiment | Target Source | Min RR | Description |
|------------|-------------|--------|-------------|
| STRUCT-001a | M5 fractals only | 2.0 | Fastest targets, highest WR expected |
| STRUCT-001b | H1 levels only | 2.0 | Medium targets, balanced |
| STRUCT-001c | Tiered (M5→H1→Fixed 2.5R) | 2.0 | Best of all worlds |
| STRUCT-001d | Fixed 2.5R (no level lookup) | 2.0 | Simple baseline comparison |
| STRUCT-001e | Fixed 2.0R | 2.0 | Minimum viable target |

---

### STRUCT-002: Trailing Stop System (Replace fixed target with profit-lock)

**Problem:** Price reverses from level (entry is good) but drifts slowly — never reaching 3R target, exiting EOD at 0.3R.

**Hypothesis:** A trailing stop captures the actual drift by locking in profit as price moves. No fixed target needed. EOD exits become trailing-stop exits at better prices.

**Implementation:**

```python
def manage_trailing_stop(trade, current_bar, config):
    pnl_R = (current_price - entry) * direction / stop_dist
    
    # Phase 1: Fixed stop (until price moves 1R in profit)
    if pnl_R < 1.0:
        return original_stop
    
    # Phase 2: Breakeven (after 1R)
    if pnl_R >= 1.0 and not trade.breakeven_set:
        trade.stop = entry + direction * 0.1 * stop_dist  # Lock in 0.1R
        trade.breakeven_set = True
    
    # Phase 3: Trail (after 1.5R)
    if pnl_R >= 1.5:
        # Trail at 0.7R behind current price
        trail_distance = config.trail_factor * stop_dist  # trail_factor = 0.7
        new_trail_stop = current_price - direction * trail_distance
        
        # Only move stop in profit direction (never widen)
        if direction == 1:  # LONG
            trade.stop = max(trade.stop, new_trail_stop)
        else:  # SHORT
            trade.stop = min(trade.stop, new_trail_stop)
    
    return trade.stop
```

**Test matrix:**

| Experiment | BE Trigger | Trail Start | Trail Factor | Description |
|------------|-----------|-------------|-------------|-------------|
| STRUCT-002a | 1.0R | 1.5R | 0.7 | Conservative |
| STRUCT-002b | 0.7R | 1.0R | 0.5 | Aggressive (quick lock) |
| STRUCT-002c | 1.0R | 1.5R | 1.0 | Wide trail (lets profits run) |
| STRUCT-002d | 0.5R | 0.7R | 0.5 | Ultra-aggressive |

**Combine winner with STRUCT-001 winner** for final config.

---

### STRUCT-003: Volatility-Adaptive Parameters (Per-Ticker Profiles)

**Problem:** AMZN (moderate vol, ATR~$3-5) is profitable. NVDA (high vol, ATR~$5-12) is a disaster with the same parameters. One-size-fits-all doesn't work.

**Hypothesis:** Classifying tickers into volatility buckets and applying different parameters per bucket will turn NVDA from -$3,629 to breakeven or positive.

**Implementation:**

```python
# Classify ticker daily
def get_volatility_profile(ticker, atr_d1, price):
    relative_atr = atr_d1 / price  # Normalized volatility
    
    if relative_atr < 0.015:  # < 1.5% daily range
        return 'LOW_VOL'     # e.g., JNJ, KO, PG
    elif relative_atr < 0.030:  # 1.5% - 3.0%
        return 'MED_VOL'     # e.g., AMZN, MSFT, AAPL
    else:                     # > 3.0%
        return 'HIGH_VOL'    # e.g., NVDA, TSLA, AMD

# Profile-specific parameters
PROFILES = {
    'LOW_VOL': {
        'fractal_depth': 7,
        'max_stop_atr_pct': 0.15,
        'atr_entry_threshold': 0.70,
        'tail_ratio_min': 0.10,
    },
    'MED_VOL': {
        'fractal_depth': 10,     # Current optimized (works for AMZN)
        'max_stop_atr_pct': 0.10,
        'atr_entry_threshold': 0.80,
        'tail_ratio_min': 0.10,
    },
    'HIGH_VOL': {
        'fractal_depth': 5,      # More levels for fast-moving names
        'max_stop_atr_pct': 0.20, # Wider stops to survive volatility
        'atr_entry_threshold': 0.85, # Stricter energy requirement
        'tail_ratio_min': 0.15,
    },
}
```

**Test matrix:**

| Experiment | Description |
|------------|-------------|
| STRUCT-003a | Adaptive profiles (table above) vs uniform (current optimized) |
| STRUCT-003b | NVDA-only with HIGH_VOL params vs current params |
| STRUCT-003c | AMZN-only with MED_VOL params (should match current) |

---

## Execution Order

```
1. STRUCT-001 (all 5 variants) → pick winner
2. STRUCT-002 (all 4 variants) → pick winner  
3. Combine STRUCT-001 winner + STRUCT-002 winner → test
4. STRUCT-003 (adaptive profiles) on combined config → test
5. Walk-forward validation (8 windows) on final config
6. Generate OPTIMIZATION_REPORT_v3.md
```

---

## New Module Needed: H1/M5 Level Detector

The existing `level_detector.py` works on D1 data. We need an **intraday level detector** for STRUCT-001:

```python
class IntradayLevelDetector:
    """Detect support/resistance on M5 and H1 timeframes for intraday targets."""
    
    def detect_m5_fractals(self, m5_bars, k=3):
        """Find local highs/lows on M5 chart. 
        These serve as nearest intraday targets."""
        # Same fractal logic as D1, but on M5 data
        # Only consider fractals from today + yesterday (fresh levels)
        
    def detect_h1_levels(self, m5_bars, k=5):
        """Aggregate M5→H1, then find fractals.
        These serve as medium-distance intraday targets."""
        h1_bars = aggregate_to_h1(m5_bars)
        return find_fractals(h1_bars, k=k)
    
    def get_nearest_target(self, entry_price, direction, date, min_distance):
        """Return nearest valid target price above min_distance."""
        candidates = []
        
        # M5 fractals from past 2 days
        for level in self.m5_fractals:
            dist = (level.price - entry_price) * direction
            if dist >= min_distance:
                candidates.append(level.price)
        
        # H1 levels from past 5 days
        for level in self.h1_levels:
            dist = (level.price - entry_price) * direction
            if dist >= min_distance:
                candidates.append(level.price)
        
        if not candidates:
            return None  # No valid intraday target
        
        # Return nearest
        return min(candidates, key=lambda p: abs(p - entry_price))
```

---

## Updated Signal Funnel Template

Add target-related tracking:

```
SIGNAL FUNNEL — {config} — {ticker}
════════════════════════════════════
[... existing funnel ...]
     └─ ✅ VALID SIGNALS:                   ???
        ├─ Target Hit (TP):                 ???  ← KEY METRIC: should be >> 1
        ├─ Trailing Stop Hit:               ???
        ├─ Stop Loss:                       ???
        ├─ EOD Exit (profitable):           ???
        ├─ EOD Exit (loss):                 ???
        └─ Breakeven Exit:                  ???

Exit Quality:
  Avg R on TP exits:                        ???
  Avg R on Trail exits:                     ???
  Avg R on EOD exits:                       ???
  Avg R on Stop exits:                      ???
  % of trades reaching ≥1R:                 ???  ← measures entry quality
  % of trades reaching ≥2R:                 ???
```

---

## Success Criteria (Updated for v3)

| Criterion | v2 Result | v3 Target | Notes |
|-----------|-----------|-----------|-------|
| OOS Sharpe | -12.70 | **> 0.5** | Lowered from 1.0 — be realistic |
| Win Rate | 41.5% | **> 45%** | Close, achievable |
| Profit Factor | 0.92 | **> 1.3** | Must be net profitable |
| Max Drawdown | 3.5% | **< 5%** | Already met |
| OOS Trades | 53 | **≥ 30** | Sufficient for significance |
| Walk-Forward | 1/8 positive | **≥ 4/8** | Lowered from 6/8 |
| Target Hit Rate | 1.9% (1/53) | **> 20%** | Key structural metric |
| NVDA OOS P&L | -$3,629 | **> -$500** | Volatility adaptation |

---

## Experiment Log Format (Same as v2)

```markdown
## STRUCT-{NNN}{variant}: {Title}
**Hypothesis:** ...
**Change:** ...
**Baseline ref:** PF=0.92, 53 trades, 41.5% WR (v2 optimized)

### Results
| Metric | v2 Optimized | This Variant | Delta |
|--------|-------------|-------------|-------|

**Verdict:** ✅ / ❌ / ⚠️
```

---

## Critical Reminders

1. **Target reachability is THE problem.** Every STRUCT experiment should improve the "% trades reaching TP" metric. If TP hit rate stays at 1.9%, the change failed.
2. **EOD exits are the hidden edge.** The entry logic works — price does reverse from false breakouts. The profit is in the drift. Trailing stops should capture this drift better than fixed targets.
3. **NVDA needs wider stops.** Don't try to make tight stops work on a $5+ ATR stock. Either widen stops or skip the ticker.
4. **Build on v2 combined_winners config** as the new baseline. Don't revert to v3.4 spec defaults.
5. **Test each STRUCT independently first**, then combine winners. Same protocol as Phase 2.
6. **Commit after each experiment.**

**Start with STRUCT-001a (M5 fractal targets). Go.**
