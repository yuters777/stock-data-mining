"""
Modified ATR calculation for the False Breakout Strategy Backtester.

Implements:
- Standard True Range
- Modified ATR (SMA with paranormal/dead bar exclusion)
- ATR exhaustion at decision time
- Paranormal bar detection

Reference: L-005.1 §4.1.
"""

import logging
from typing import Optional

from backtester.data_types import Bar, SignalDirection

logger = logging.getLogger(__name__)

# Default thresholds for modified ATR filtering
DEFAULT_UPPER_MULT = 2.0   # TR > 2x ATR_prev → paranormal, exclude
DEFAULT_LOWER_MULT = 0.5   # TR < 0.5x ATR_prev → dead, exclude
DEFAULT_ATR_PERIOD = 5


def true_range(bar: Bar, prev_bar: Optional[Bar] = None) -> float:
    """Standard True Range calculation.

    TR = max(H - L, |H - C_prev|, |L - C_prev|)
    If no previous bar, TR = H - L.

    Args:
        bar: Current bar.
        prev_bar: Previous bar (for gap consideration). None for first bar.

    Returns:
        True range value.
    """
    hl = bar.high - bar.low
    if prev_bar is None:
        return hl

    hcp = abs(bar.high - prev_bar.close)
    lcp = abs(bar.low - prev_bar.close)
    return max(hl, hcp, lcp)


def modified_atr(
    bars: list[Bar],
    period: int = DEFAULT_ATR_PERIOD,
    upper_mult: float = DEFAULT_UPPER_MULT,
    lower_mult: float = DEFAULT_LOWER_MULT,
) -> float:
    """Modified ATR: SMA of True Range, excluding paranormal and dead bars.

    Bars where TR > upper_mult × ATR_prev (paranormal) or
    TR < lower_mult × ATR_prev (dead) are excluded from the average.

    Falls back to unfiltered SMA if all bars would be excluded.

    Args:
        bars: List of Bar objects (chronological, most recent last).
        period: Number of periods for SMA. Default 5.
        upper_mult: Multiplier for paranormal threshold. Default 2.0.
        lower_mult: Multiplier for dead bar threshold. Default 0.5.

    Returns:
        Modified ATR value. Returns 0.0 if fewer than 2 bars.
    """
    if len(bars) < 2:
        return 0.0

    # Calculate all true ranges
    tr_values = []
    for i in range(1, len(bars)):
        tr = true_range(bars[i], bars[i - 1])
        tr_values.append(tr)

    if not tr_values:
        return 0.0

    # Use the last `period` TRs (or all if fewer)
    recent_trs = tr_values[-period:] if len(tr_values) >= period else tr_values

    # First pass: compute raw ATR (unfiltered SMA) as baseline
    raw_atr = sum(recent_trs) / len(recent_trs)

    if raw_atr == 0.0:
        return 0.0

    # Second pass: filter out paranormal and dead bars
    filtered_trs = [
        tr for tr in recent_trs
        if (tr <= upper_mult * raw_atr) and (tr >= lower_mult * raw_atr)
    ]

    # Fallback: if all bars excluded, use unfiltered ATR
    if not filtered_trs:
        logger.warning("All bars excluded by modified ATR filter; using unfiltered ATR")
        return raw_atr

    return sum(filtered_trs) / len(filtered_trs)


def calc_exhaustion(
    level_price: float,
    direction: SignalDirection,
    session_bars: list[Bar],
    atr_d1: float,
) -> float:
    """ATR exhaustion percentage at decision time.

    Measures how much of the daily ATR has already been consumed
    by the time price reaches the level.

    For SHORT from resistance: (level - low_so_far) / atr_d1
    For LONG from support:     (high_so_far - level) / atr_d1

    Uses low_so_far / high_so_far at DECISION TIME (no full-day lookahead).

    Args:
        level_price: The support/resistance level price.
        direction: Signal direction (SHORT from resistance, LONG from support).
        session_bars: M5 bars from the current session up to decision time.
        atr_d1: Daily ATR value.

    Returns:
        Exhaustion as a fraction (0.0 to ~2.0+). E.g., 0.75 = 75% exhausted.
        Returns 0.0 if atr_d1 is zero or no bars provided.
    """
    if atr_d1 <= 0.0 or not session_bars:
        return 0.0

    if direction == SignalDirection.SHORT:
        # SHORT from resistance: how far has price moved from level to low
        low_so_far = min(bar.low for bar in session_bars)
        return (level_price - low_so_far) / atr_d1
    else:
        # LONG from support: how far has price moved from level to high
        high_so_far = max(bar.high for bar in session_bars)
        return (high_so_far - level_price) / atr_d1


def is_paranormal(bar: Bar, atr: float) -> bool:
    """Check if a bar is paranormal (range >= 2x ATR).

    Args:
        bar: The bar to check.
        atr: Current ATR value.

    Returns:
        True if bar.range >= 2.0 × ATR.
    """
    if atr <= 0.0:
        return False
    return bar.range >= DEFAULT_UPPER_MULT * atr
