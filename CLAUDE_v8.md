# CLAUDE.md v8 — Mirror Reversal Signal System

## Context

Phases 1-7 proved that the False Breakout strategy has a real but narrow edge (PF=2.64 on 4 tickers with direction filter, WF 4/8). The strongest theoretical setup in Gerchik's methodology — Mirror Level + False Breakout — was never isolated and tested as a standalone strategy.

**New architecture:** Instead of trading ALL D1 levels, trade ONLY confirmed Mirror Levels with multi-indicator confirmation. Quality over quantity. This is a signal system, not a full autotrader.

**Key shift:** From "catch all false breakouts" → "wait for the highest-conviction mirror reversal setups"

---

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│           MIRROR REVERSAL SIGNAL SYSTEM          │
├─────────────────────────────────────────────────┤
│                                                  │
│  1. MIRROR DETECTION (D1)                        │
│     Level was Support → broke → now Resistance   │
│     (or vice versa)                              │
│     Validation: 3×ATR distance + 3 days          │
│                                                  │
│  2. FALSE BREAKOUT PATTERN (M5)                  │
│     LP1/LP2/CLP at the mirror level              │
│     = TRIGGER (raw signal generated)             │
│                                                  │
│  3. CONFIRMATION SCORING (M5/H1/D1)             │
│     RSI Divergence          +1                   │
│     Volume Climax           +1                   │
│     ATR Exhaustion (≥75%)   +1                   │
│     VWAP Alignment          +1                   │
│     H1 Trend Alignment      +1                   │
│     ─────────────────────────                    │
│     Score: 0-5                                   │
│     MIN SCORE TO SIGNAL: 3                       │
│                                                  │
│  4. STOP-CANCEL CONDITIONS                       │
│     Signal cancelled if:                         │
│     - Price closes beyond level 2 bars in a row  │
│     - ATR drops below 30% (no energy)            │
│     - Squeeze detected (compression = breakout)  │
│                                                  │
│  5. OUTPUT: Telegram-ready alert                 │
│                                                  │
└─────────────────────────────────────────────────┘
```

---

## Phase 8A: Build Confirmation Indicators

### Indicator 1: RSI Divergence

```python
def detect_rsi_divergence(m5_bars, level, direction, period=14):
    """
    BEARISH divergence (for SHORT at resistance mirror):
      Price makes higher high → RSI makes lower high
      = momentum fading, reversal likely
    
    BULLISH divergence (for LONG at support mirror):
      Price makes lower low → RSI makes higher low
      = sellers exhausted, bounce likely
    """
    rsi = compute_rsi(m5_bars['Close'], period)
    
    # Look at last 20 M5 bars approaching the level
    window = m5_bars.tail(20)
    
    if direction == 'SHORT':
        # Find two recent highs
        price_high1, price_high2 = find_two_recent_highs(window)
        rsi_high1, rsi_high2 = rsi at those points
        
        # Bearish divergence: price ↑, RSI ↓
        if price_high2 > price_high1 and rsi_high2 < rsi_high1:
            return True, rsi_high2, 'bearish_divergence'
    
    elif direction == 'LONG':
        price_low1, price_low2 = find_two_recent_lows(window)
        rsi_low1, rsi_low2 = rsi at those points
        
        # Bullish divergence: price ↓, RSI ↑
        if price_low2 < price_low1 and rsi_low2 > rsi_low1:
            return True, rsi_low2, 'bullish_divergence'
    
    return False, rsi.iloc[-1], 'no_divergence'
```

**RSI Implementation:** Standard 14-period RSI on M5 data. Use `ta` library or manual Wilder smoothing.

### Indicator 2: Volume Climax

```python
def detect_volume_climax(m5_bars, level, direction, lookback=20, threshold=2.0):
    """
    Volume climax = abnormally high volume on the bar that touches/breaches 
    the level, combined with price rejection (close back inside level).
    
    This signals exhaustion: massive effort to break through, but failed.
    The crowd threw everything at the level and lost.
    """
    current_bar = m5_bars.iloc[-1]
    avg_volume = m5_bars['Volume'].tail(lookback).mean()
    
    volume_ratio = current_bar['Volume'] / avg_volume
    
    if volume_ratio >= threshold:
        # High volume + price rejected from level = climax
        if direction == 'SHORT' and current_bar['Close'] < level:
            return True, volume_ratio, 'selling_climax'
        elif direction == 'LONG' and current_bar['Close'] > level:
            return True, volume_ratio, 'buying_climax'
    
    return False, volume_ratio, 'normal_volume'
```

### Indicator 3: ATR Exhaustion (existing)

```python
def check_atr_exhaustion(day_data, level, direction, threshold=0.75):
    """Already implemented in filter_chain.py. Reuse.
    
    Distance traveled / ATR_D1 >= threshold = exhausted.
    """
    if direction == 'SHORT':
        distance = level - day_data['Low']
    else:
        distance = day_data['High'] - level
    
    atr_ratio = distance / day_data['ATR_D1']
    return atr_ratio >= threshold, atr_ratio
```

### Indicator 4: VWAP Alignment

```python
def check_vwap_alignment(m5_bars, level, direction):
    """
    VWAP = Volume-Weighted Average Price (intraday institutional benchmark).
    
    SHORT signal: price ABOVE VWAP at mirror resistance
      → "expensive" relative to institutional average → good short
    
    LONG signal: price BELOW VWAP at mirror support
      → "cheap" relative to institutional average → good long
    """
    # Calculate intraday VWAP
    cumulative_vp = (m5_bars['Close'] * m5_bars['Volume']).cumsum()
    cumulative_v = m5_bars['Volume'].cumsum()
    vwap = cumulative_vp / cumulative_v
    
    current_price = m5_bars['Close'].iloc[-1]
    current_vwap = vwap.iloc[-1]
    
    if direction == 'SHORT' and current_price > current_vwap:
        return True, current_vwap, 'above_vwap_good_short'
    elif direction == 'LONG' and current_price < current_vwap:
        return True, current_vwap, 'below_vwap_good_long'
    
    return False, current_vwap, 'vwap_not_aligned'
```

### Indicator 5: H1 Trend Alignment

```python
def check_h1_trend(m5_bars, direction, ema_fast=8, ema_slow=21):
    """
    Aggregate M5 to H1, compute EMA crossover.
    
    SHORT signal: H1 fast EMA < slow EMA (downtrend on H1)
      → selling into resistance in a downtrend = high probability
    
    LONG signal: H1 fast EMA > slow EMA (uptrend on H1)
      → buying at support in an uptrend = high probability
    """
    h1_bars = aggregate_to_h1(m5_bars)
    
    ema_f = h1_bars['Close'].ewm(span=ema_fast).mean()
    ema_s = h1_bars['Close'].ewm(span=ema_slow).mean()
    
    if direction == 'SHORT' and ema_f.iloc[-1] < ema_s.iloc[-1]:
        return True, 'h1_downtrend'
    elif direction == 'LONG' and ema_f.iloc[-1] > ema_s.iloc[-1]:
        return True, 'h1_uptrend'
    
    return False, 'h1_not_aligned'
```

---

## Phase 8B: Confirmation Scoring System

```python
class ConfirmationScorer:
    """Score a mirror reversal signal from 0 to 5."""
    
    def score_signal(self, m5_bars, h1_bars, daily_data, level, direction):
        confirmations = {}
        total = 0
        
        # 1. RSI Divergence
        rsi_ok, rsi_val, rsi_desc = detect_rsi_divergence(m5_bars, level, direction)
        confirmations['rsi_divergence'] = {'active': rsi_ok, 'value': rsi_val, 'desc': rsi_desc}
        if rsi_ok: total += 1
        
        # 2. Volume Climax
        vol_ok, vol_ratio, vol_desc = detect_volume_climax(m5_bars, level, direction)
        confirmations['volume_climax'] = {'active': vol_ok, 'value': vol_ratio, 'desc': vol_desc}
        if vol_ok: total += 1
        
        # 3. ATR Exhaustion
        atr_ok, atr_ratio = check_atr_exhaustion(daily_data, level, direction)
        confirmations['atr_exhaustion'] = {'active': atr_ok, 'value': atr_ratio}
        if atr_ok: total += 1
        
        # 4. VWAP Alignment
        vwap_ok, vwap_val, vwap_desc = check_vwap_alignment(m5_bars, level, direction)
        confirmations['vwap_alignment'] = {'active': vwap_ok, 'value': vwap_val, 'desc': vwap_desc}
        if vwap_ok: total += 1
        
        # 5. H1 Trend
        h1_ok, h1_desc = check_h1_trend(m5_bars, direction)
        confirmations['h1_trend'] = {'active': h1_ok, 'desc': h1_desc}
        if h1_ok: total += 1
        
        return total, confirmations
```

---

## Phase 8C: Stop-Cancel Conditions

```python
class SignalCanceller:
    """Conditions that invalidate a mirror reversal signal."""
    
    def check_cancel(self, signal, m5_bars, daily_data, level):
        
        # Cancel 1: Price closes beyond level for 2 consecutive bars
        # = level is truly broken, not a false breakout
        last_2 = m5_bars.tail(2)
        if signal.direction == 'SHORT':
            if all(last_2['Close'] > level):
                return True, 'Price closed above level 2 bars — breakout confirmed'
        elif signal.direction == 'LONG':
            if all(last_2['Close'] < level):
                return True, 'Price closed below level 2 bars — breakdown confirmed'
        
        # Cancel 2: ATR below 30% (no energy for reversal)
        atr_ratio = compute_atr_ratio(daily_data, level, signal.direction)
        if atr_ratio < 0.30:
            return True, f'ATR ratio {atr_ratio:.2f} < 0.30 — insufficient energy'
        
        # Cancel 3: Squeeze detected (compression before breakout)
        if detect_squeeze(m5_bars, level):
            return True, 'Squeeze pattern — likely true breakout incoming'
        
        # Cancel 4: Earnings today
        if check_earnings(signal.ticker, signal.date):
            return True, 'Earnings day — fundamental risk'
        
        return False, 'Signal valid'
```

---

## Phase 8D: Backtesting the Mirror-Only Strategy

### Experiment Matrix

| Experiment | Config | Description |
|------------|--------|-------------|
| M-001 | Mirror only, no confirmation, no direction filter | How many mirror signals exist? Baseline. |
| M-002 | Mirror only, confirmation ≥ 1 | Loose filter |
| M-003 | Mirror only, confirmation ≥ 2 | Medium filter |
| M-004 | Mirror only, confirmation ≥ 3 | Strict filter (target) |
| M-005 | Mirror only, confirmation ≥ 4 | Very strict |
| M-006 | M-004 + direction filter (TSLA=long, others=short) | Combined v6 insight + mirror + confirmation |
| M-007 | M-004 + ALL tickers both directions | Mirror might fix direction naturally |

### For each experiment, report:

```
=== M-00X ===
IS:  X trades, X% WR, PF=X.XX, $XXX
OOS: X trades, X% WR, PF=X.XX, $XXX

Signal Funnel:
  Total D1 levels: X
  Mirror confirmed: X (X%)          ← KEY: how many mirrors?
  Proximity events at mirrors: X
  Patterns at mirrors: X
  Confirmation score distribution:
    Score 0: X signals
    Score 1: X signals
    Score 2: X signals
    Score 3: X signals
    Score 4: X signals
    Score 5: X signals
  Passed min score: X
  After other filters: X
  VALID SIGNALS: X

Per-indicator hit rate:
  RSI divergence: X/X signals (X%)
  Volume climax: X/X signals (X%)
  ATR exhaustion: X/X signals (X%)
  VWAP alignment: X/X signals (X%)
  H1 trend: X/X signals (X%)

Confirmation score vs outcome:
  Score 0-1: X trades, WR=X%, PF=X.XX
  Score 2: X trades, WR=X%, PF=X.XX
  Score 3: X trades, WR=X%, PF=X.XX
  Score 4-5: X trades, WR=X%, PF=X.XX
```

---

## Phase 8E: Walk-Forward Validation

Best mirror config → 8-window walk-forward.

**Expectation:** Fewer trades than v4.1 (mirrors are rare), but higher PF and more stable WF.

---

## Phase 8F: Alert Format Design

If results are positive, define the production alert format:

```
🔄 MIRROR REVERSAL — {TICKER}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Level: ${price} (Mirror: was {old_type} → now {new_type})
Mirror Age: {days} days since flip
Pattern: {LP1/LP2/CLP} {direction}
Entry: ${entry} | Stop: ${stop} | Target: ${target}

Confirmations [{score}/5]:
  {✅/⬜} RSI Divergence ({desc})
  {✅/⬜} Volume Climax ({ratio}× avg)
  {✅/⬜} ATR Exhaustion ({pct}%)
  {✅/⬜} VWAP ({above/below})
  {✅/⬜} H1 Trend ({up/down})

Risk: ${risk} ({pct}% of account)
R:R: {rr}:1

⛔ CANCEL IF: {cancel_conditions}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Execution Order

```
1. Build 5 confirmation indicators (RSI, Volume, ATR reuse, VWAP, H1 trend)
2. Build ConfirmationScorer
3. Build SignalCanceller
4. M-001: Mirror-only baseline (no confirmations) — count mirror signals
5. M-002 through M-005: Confirmation threshold sweep
6. M-006: Best threshold + direction filter
7. M-007: Best threshold without direction filter
8. Pick winner → walk-forward
9. Diagnostic deep-dive (per-indicator value, score vs outcome)
10. Generate final report
```

---

## Module Structure

```
backtester/core/
├── confirmation/
│   ├── __init__.py
│   ├── rsi_divergence.py
│   ├── volume_climax.py
│   ├── vwap.py
│   ├── h1_trend.py
│   └── scorer.py
├── signal_canceller.py
├── level_detector.py      (existing — add mirror_only filter)
├── pattern_engine.py      (existing — unchanged)
├── filter_chain.py        (existing — add confirmation gate)
├── risk_manager.py        (existing — unchanged)
└── trade_manager.py       (existing — unchanged)
```

---

## Success Criteria v8

| Criterion | v6 (L-005) | v8 Target |
|-----------|-----------|-----------|
| OOS PF | 2.64 | **≥ 2.0** (fewer trades = lower PF OK) |
| WF Positive | 4/8 | **≥ 5/8** |
| WF Total P&L | +$4,876 | **> +$3,000** |
| OOS trades | ~50 | **≥ 15** (mirrors are rare, quality > quantity) |
| Confirmation score correlation | — | **Score 4-5 PF > Score 0-1 PF** |
| Mirror hit rate | — | **mirrors ≥ 30% of all D1 levels** |

---

## Critical Reminders

1. **Mirrors are RARE.** Expect 5-12 confirmed mirrors per ticker per year. Total signals with ≥3 confirmations might be 10-30 across all tickers. This is fine — each one is high-conviction.

2. **If M-001 shows < 5 mirror signals in OOS → data is too short.** We need mirrors to form AND be retested in 4 months. This may not happen for all tickers. Flag it honestly.

3. **RSI divergence detection is tricky.** Define "two recent highs/lows" precisely: use M5 fractals (k=3) within last 20 bars. If no two fractals found, RSI divergence = False (not an error).

4. **VWAP resets daily.** Calculate fresh each session. Only compare current price to current day's VWAP.

5. **Confirmation score must CORRELATE with outcome.** If Score 5 trades perform same as Score 1, the confirmations are noise. Phase 8D diagnostic will reveal this.

6. **Don't force it.** If mirrors are too rare or confirmations don't correlate, the honest answer is: "Mirror-only is theoretically sound but our data window is too short to validate."

7. **v4.1 params + v6 direction filter remain the fallback.** If v8 doesn't beat v6, we keep v6 as the best config.

**Start with building the 5 confirmation indicators. Then run M-001 to count mirror signals. Go.**
