# CLAUDE CODE — Phase 2.1 Steps 4-6

## CONTEXT

Steps 1-3 are complete (data_types, config, data_loader, atr). Now build the strategy core.

**Read first:**
- `docs/Claude_Code_Prompt_Steps_1_3.md` — for overall architecture context
- `backtester/data_types.py` — all enums and dataclasses you'll use
- `backtester/atr.py` — modified ATR and exhaustion calculations
- `backtester/config.py` — DEFAULT_CONFIG with all parameters

**Spec reference:** L-005.1 sections §2, §3, §4 (in project KB or see parameter details in config.py)

---

## Step 4: `backtester/level_detector.py` (L-005.1 §2)

Detects D1 support/resistance levels using fractal model. Extends Phase 1 prototype in `level_detection/`.

### Class: `LevelDetector`

```python
def __init__(self, config: dict)
```

### Methods:

**`detect_levels(d1_bars: list[Bar], as_of_date: date) -> list[Level]`**

Fractal-based BSU detection:
```
Resistance: H[i] > MAX(H[i-k]...H[i-1]) AND H[i] > MAX(H[i+1]...H[i+k])
Support:    L[i] < MIN(L[i-k]...L[i-1]) AND L[i] < MIN(L[i+1]...L[i+k])
k = config['FRACTAL_DEPTH_D1'] (default: 7, range 5-10)
```

CRITICAL — Lookahead protection:
- Level at bar index `i` requires bars `[i-k ... i+k]` to exist
- Level becomes available (confirmed_at) at bar `i+k`, NOT at bar `i`
- `detect_levels()` must ONLY return levels where `confirmed_at <= as_of_date`

**`update_level_status(levels: list[Level], current_bar: Bar) -> list[Level]`**

For each level, check:
1. **Sawing filter (§2.4):** Count body crosses in last `SAWING_PERIOD_D1` (20) bars. If `cross_count >= SAWING_THRESHOLD` (3) → status = INVALIDATED
2. **Broken detection:** If close breaks through level by more than tolerance → status = BROKEN
3. **Mirror candidate (§2.5):** If BROKEN and `max_distance >= 3 × ATR_D1` AND `days_beyond >= 3` → status = MIRROR_CANDIDATE
4. **Mirror confirmed:** If MIRROR_CANDIDATE and price returns to level and forms BPU → status = MIRROR_CONFIRMED, score = 10
5. **Nison invalidation:** If price retests mirror, bounces, then closes back beyond → INVALIDATED (immediate exit signal)

**`get_active_levels(levels: list[Level], min_score: int = 5) -> list[Level]`**

Return levels where status is ACTIVE or MIRROR_CONFIRMED and score >= min_score.

**`score_level(level: Level) -> int`**

Scoring table (§2.6):
| Criterion | Score |
|-----------|-------|
| Mirror (polarity change) | 10 |
| Penny-to-penny (3+ exact touches) | 9 |
| Paranormal approach (stops paranormal bar) | 8 |
| Gap boundaries | 8 |
| Duration (older = stronger) | 7 |
| Round numbers (.00, .50) | 6 |
| Air level (no history) | IGNORE |

Minimum score for signal: 5

**BPU matching (§2.2):**
```
Tolerance for stocks $20-100: 5 cents (LEVEL_TOLERANCE_CENTS)
Tolerance for stocks >$100: 0.2% (LEVEL_TOLERANCE_PCT)
```
Use whichever is appropriate based on price. BPU = another bar touching same price within tolerance.

### Tests (test_level_detector.py):
- Fractal detection with known D1 bars (construct bars where level is obvious)
- Lookahead: level at bar 10 with k=5 must NOT appear before bar 15
- Sawing: 3 body crosses → INVALIDATED
- Mirror lifecycle: ACTIVE → BROKEN → MIRROR_CANDIDATE → MIRROR_CONFIRMED
- Nison invalidation: mirror retested, bounces, closes beyond → INVALIDATED
- Scoring: mirror = 10, round number = 6, penny-to-penny = 9
- BPU count increments on tolerance match

---

## Step 5: `backtester/pattern_engine.py` (L-005.1 §3)

Detects LP1, LP2, CLP, Model #4 patterns on M5 bars against active levels.

### Class: `PatternEngine`

```python
def __init__(self, config: dict)
```

### Main method:

**`scan_bar(bar_idx: int, m5_bars: list[Bar], active_levels: list[Level], atr_d1: float, atr_m5: float, avg_volume_20: float) -> list[Signal]`**

Scan current bar for patterns against ALL active levels. Return candidate Signals (status=CANDIDATE).

Pattern priority: Model#4 > CLP > LP2 > LP1. If higher-priority pattern found at same level, drop lower ones.

### Pattern implementations:

**LP1 — Simple False Breakout (§3.1):**
```
LP1_SHORT: Open < Level AND High > Level AND Close < Level
LP1_LONG:  Open > Level AND Low < Level AND Close > Level

TailRatio = (High - Level) / (High - Low)  # for SHORT
If TailRatio < TAIL_RATIO_MIN (0.15) → Strength = WEAK
If TailRatio > TAIL_RATIO_STRONG (0.30) → Strength = HIGH
```

**LP2 — Complex False Breakout (§3.2):**
```
SHORT scenario:
  Bar1 (Breakout): Close > Level (breaks above and closes above)
  Bar2 (Return): Close < Level (returns below)

Filters:
  1. TIMER: Bar2 must be immediately next bar (bar_idx == bar1_idx + 1)
  2. HIGH UPDATE: High_Bar2 must NOT exceed High_Bar1
  3. QUALITY TIERS:
     - IDEAL: Close_Bar2 < Open_Bar1 (full engulfing) → 100% position
     - ACCEPTABLE: Close_Bar2 < Close_Bar1 → 70% position
     - WEAK: Close_Bar2 < Level but no engulfing → 50% position
     - Else: INVALIDATED
```

**CLP — Complex LP with Consolidation (§3.3):**

State machine with 3 phases:
```
Phase 1 — Breakout:
  Bar closes ABOVE resistance (or BELOW support)
  
Phase 2 — Consolidation (3-7 bars):
  ALL closes stay above level (mandatory invariant)
  Max deviation: highest close ≤ Level + CLP_MAX_DEV_M5_ATR × ATR_M5
  Range compression: ≥50% of bars must overlap with previous bar's range
  
Phase 3 — Trigger:
  Return bar closes BELOW level AND meets at least ONE:
    (a) bar body ≥ 1.5 × ATR_M5
    (b) bar volume ≥ 2.0 × avg_volume_20
    (c) bar close in bottom 25% of its range
```

CLP needs state tracking across bars. Implement `CLPTracker` that maintains state per level:
```python
class CLPTracker:
    def __init__(self):
        self.active_setups: dict[float, CLPState] = {}  # level_price → state
    
    def update(self, bar_idx, bar, level, atr_m5, avg_volume) -> Signal | None
```

**Model #4 — Paranormal + Mirror + LP (§3.4):**
```
IF bar.range >= 2.0 × ATR_D1 (paranormal)
AND level.is_mirror == True (score = 10)  
AND pattern IN [LP1, LP2, CLP]
THEN Signal.priority = MAXIMUM, position_mult = 1.0
```

### Tests (test_pattern_engine.py):
- LP1 SHORT: construct bar that pierces resistance and closes below → signal generated
- LP1 LONG: construct bar that pierces support and closes above → signal generated
- LP1 weak tail: TailRatio < 0.15 → tail_ratio field set correctly
- LP2 IDEAL: Bar1 breaks above, Bar2 engulfs → quality = IDEAL
- LP2 ACCEPTABLE: partial engulf → quality = ACCEPTABLE
- LP2 INVALIDATED: Bar2 high exceeds Bar1 high → no signal
- LP2 TIMER: Bar2 not immediately next → no signal
- CLP full lifecycle: breakout → 4 bars consolidation → trigger → signal
- CLP fails: close drops below level during consolidation → no signal
- CLP max deviation exceeded → no signal
- Model #4: paranormal bar + mirror level + LP1 → Model4 signal
- Priority: CLP at same level as LP1 → only CLP returned

---

## Step 6: `backtester/filter_chain.py` (L-005.1 §4)

8-stage filter precedence chain. BLOCK at any stage kills the signal — no downstream override.

### Class: `FilterChain`

```python
def __init__(self, config: dict)
```

### Main method:

**`evaluate(signal: Signal, context: FilterContext) -> Signal`**

Run through all 8 stages in order. Update signal.status to APPROVED or BLOCKED. Populate signal.filter_results dict.

### FilterContext dataclass (already in data_types.py):

If not already there, ensure FilterContext has:
```python
@dataclass
class FilterContext:
    current_time: datetime        # Bar timestamp (IST)
    is_earnings_day: bool
    is_post_earnings: bool
    atr_d1: float
    atr_m5: float
    exhaustion_pct: float         # From atr.calc_exhaustion()
    low_so_far: float             # Session low at decision time
    high_so_far: float
    avg_volume_20: float
    current_volume: float
    bar: Bar
    has_squeeze: bool
    has_breakaway_gap: bool
    gap_type: str | None
    open_positions: int
    sector_exposure: dict[str, int]
    portfolio_risk_pct: float
    circuit_breaker_active: bool
    consecutive_losses: int
    daily_loss_pct: float
```

### 8 Stages:

**Stage 1 — Context Blocks (hard kills):**
```
- Earnings day → BLOCK
- Post-earnings before delay expires → BLOCK  
- Before OPEN_DELAY after market open → BLOCK
- Circuit breaker active → BLOCK
```

**Stage 2 — Structural Blocks:**
```
- Squeeze detection (has_squeeze=True) → BLOCK
- Breakaway gap (gap_type='breakaway') → BLOCK
- Level invalidated (sawing) → BLOCK (shouldn't reach here, but safety check)
```

**Stage 3 — Pattern Detection:**
Already done by pattern_engine. Just record PASS in filter_results.

**Stage 4 — Energy Gate (ATR exhaustion):**
```
- exhaustion_pct < ATR_BLOCK_THRESHOLD (30%) → BLOCK
- exhaustion_pct >= ATR_MIN_ENTRY (75%) → PASS
- Between 30-75% → CAUTION (pass but flag for logging)
```

**Stage 5 — Volume Confirmation:**
```
- V > 2× avg AND close beyond level → BLOCK (true breakout)
- V > 2× avg AND close returned → STRONGEST signal (PASS)
- V < 0.7× avg on breakout → LP probable (PASS)
- Price↑ Volume↓ divergence → PASS
```

**Stage 6 — Risk Feasibility:**
```
- Calculate stop distance from signal
- If stop > Final_Max_Stop (MIN of 15% ATR_D1, Hard Cap) → SKIP
- If Final_Max_Stop < MVS → SKIP
```
Note: full stop/target calc is in risk_manager (Step 7). Here just check feasibility.

**Stage 7 — R:R Feasibility:**
```
- Estimate target = nearest opposing level - buffer
- If potential < 3 × stop → SKIP
```

**Stage 8 — Portfolio Constraints:**
```
- open_positions >= MAX_CONCURRENT_POSITIONS (5) → SKIP
- sector count >= MAX_PER_SECTOR (2) → SKIP
- portfolio_risk + new risk >= MAX_PORTFOLIO_RISK (1.5%) → SKIP
```

### Key rule:
Squeeze BLOCK (stage 2) ALWAYS overrides ATR ALLOW (stage 4). If stages are executed in order and BLOCK stops processing, this is automatic.

### Tests (test_filter_chain.py):
- BLOCK at stage 1 → stages 2-8 never execute (check filter_results has only stage 1)
- Earnings day → BLOCK regardless of perfect setup
- Squeeze → BLOCK even with 90% ATR exhaustion
- Exhaustion < 30% → BLOCK
- Exhaustion 50% → CAUTION flag
- Exhaustion 80% → PASS
- Volume > 2× with close beyond level → BLOCK (true breakout)
- R:R < 3:1 → SKIP
- Portfolio full (5 positions) → SKIP
- Perfect setup (all pass) → APPROVED
- filter_results dict populated correctly for each stage

---

## FILE STRUCTURE

Add to `backtester/`:
```
backtester/
├── level_detector.py      # Step 4
├── pattern_engine.py      # Step 5
└── filter_chain.py        # Step 6

backtester/tests/
├── test_level_detector.py
├── test_pattern_engine.py
└── test_filter_chain.py
```

---

## DESIGN NOTES

1. **CLP state tracking** — CLPTracker must persist across bars within a trading day. Reset at start of each day.

2. **Squeeze detection** — For v1, simple heuristic: 3+ consecutive higher lows approaching a resistance level (or lower highs for support). Full implementation can be enhanced later.

3. **Earnings data** — For now, accept `is_earnings_day` as input (FilterContext). Actual earnings calendar integration comes in Step 7-8.

4. **Target estimation in Stage 7** — needs access to opposing levels. Pass `active_levels` list in FilterContext or as separate param to filter_chain.evaluate().

5. **All signals must have filter_results populated** — even APPROVED signals. This is critical for Signal Funnel analysis.

---

## WHEN DONE

Report:
- Files created (with line counts)
- Tests run (pass/fail count)  
- Any design decisions made that deviate from spec
- Questions for Steps 7-9 (risk_manager, trade_manager, portfolio_manager)
