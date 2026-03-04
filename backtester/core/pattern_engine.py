"""
Pattern Recognition Engine for the False Breakout Strategy Backtester.

Detects LP1 (1-bar), LP2 (2-bar), CLP (3-7 bar), and Model4 patterns
on M5 intraday data at D1 support/resistance levels.

Reference: L-005.1 §5.
"""

import pandas as pd
import numpy as np
from typing import Optional

from backtester.data_types import (
    Level, LevelType, Signal, SignalDirection, PatternType, LP2Quality,
)


class PatternEngineConfig:
    def __init__(self, **kwargs):
        self.tail_ratio_min = kwargs.get('tail_ratio_min', 0.10)
        self.lp2_engulfing_required = kwargs.get('lp2_engulfing_required', True)
        self.clp_min_bars = kwargs.get('clp_min_bars', 3)
        self.clp_max_bars = kwargs.get('clp_max_bars', 7)
        self.clp_max_deviation_atr_mult = kwargs.get('clp_max_deviation_atr_mult', 2.5)
        self.clp_min_overlap_pct = kwargs.get('clp_min_overlap_pct', 0.50)  # range compression
        self.atr_m5_period = kwargs.get('atr_m5_period', 5)


# LP2 quality → position size multiplier
LP2_QUALITY_MULT = {
    LP2Quality.IDEAL: 1.0,
    LP2Quality.ACCEPTABLE: 0.7,
    LP2Quality.WEAK: 0.5,
}


class PatternEngine:
    def __init__(self, config: Optional[PatternEngineConfig] = None):
        self.config = config or PatternEngineConfig()

    def calculate_m5_atr(self, m5_df: pd.DataFrame, ticker: str) -> pd.Series:
        """Calculate ATR on M5 bars for a given ticker."""
        tdf = m5_df[m5_df['Ticker'] == ticker].copy()
        period = self.config.atr_m5_period

        tdf['PrevClose'] = tdf['Close'].shift(1)
        tdf['TR'] = pd.concat([
            tdf['High'] - tdf['Low'],
            (tdf['High'] - tdf['PrevClose']).abs(),
            (tdf['Low'] - tdf['PrevClose']).abs()
        ], axis=1).max(axis=1)

        first_idx = tdf.index[0]
        tdf.loc[first_idx, 'TR'] = tdf.loc[first_idx, 'High'] - tdf.loc[first_idx, 'Low']

        atr = tdf['TR'].ewm(alpha=1.0 / period, adjust=False).mean()
        return atr

    def _check_lp1_short(self, bar: pd.Series, level_price: float,
                         tolerance: float) -> Optional[tuple[float, float]]:
        """Check LP1 short: Open < Level, High > Level, Close < Level."""
        if bar['Open'] >= level_price + tolerance:
            return None
        if bar['High'] <= level_price:
            return None
        if bar['Close'] >= level_price:
            return None

        bar_range = bar['High'] - bar['Low']
        if bar_range <= 0:
            return None

        tail_ratio = (bar['High'] - level_price) / bar_range
        entry_price = bar['Close']
        return entry_price, tail_ratio

    def _check_lp1_long(self, bar: pd.Series, level_price: float,
                        tolerance: float) -> Optional[tuple[float, float]]:
        """Check LP1 long: Open > Level, Low < Level, Close > Level."""
        if bar['Open'] <= level_price - tolerance:
            return None
        if bar['Low'] >= level_price:
            return None
        if bar['Close'] <= level_price:
            return None

        bar_range = bar['High'] - bar['Low']
        if bar_range <= 0:
            return None

        tail_ratio = (level_price - bar['Low']) / bar_range
        entry_price = bar['Close']
        return entry_price, tail_ratio

    def detect_lp1(self, m5_bars: pd.DataFrame, bar_idx: int,
                   level: Level, tolerance: float) -> Optional[Signal]:
        """Detect LP1 (1-bar false breakout) at the given bar."""
        bar = m5_bars.iloc[bar_idx]
        level_price = level.price

        if level.level_type in (LevelType.RESISTANCE, LevelType.MIRROR):
            result = self._check_lp1_short(bar, level_price, tolerance)
            if result:
                entry_price, tail_ratio = result
                if tail_ratio >= self.config.tail_ratio_min:
                    return Signal(
                        pattern=PatternType.LP1,
                        direction=SignalDirection.SHORT,
                        level=level,
                        timestamp=bar['Datetime'],
                        ticker=bar['Ticker'],
                        entry_price=entry_price,
                        trigger_bar_idx=bar_idx,
                        tail_ratio=tail_ratio,
                        priority=5 if tail_ratio >= 0.30 else 3,
                    )

        if level.level_type in (LevelType.SUPPORT, LevelType.MIRROR):
            result = self._check_lp1_long(bar, level_price, tolerance)
            if result:
                entry_price, tail_ratio = result
                if tail_ratio >= self.config.tail_ratio_min:
                    return Signal(
                        pattern=PatternType.LP1,
                        direction=SignalDirection.LONG,
                        level=level,
                        timestamp=bar['Datetime'],
                        ticker=bar['Ticker'],
                        entry_price=entry_price,
                        trigger_bar_idx=bar_idx,
                        tail_ratio=tail_ratio,
                        priority=5 if tail_ratio >= 0.30 else 3,
                    )

        return None

    def _classify_lp2_quality(self, bar1: pd.Series, bar2: pd.Series,
                              level_price: float,
                              direction: SignalDirection) -> LP2Quality:
        """Classify LP2 quality tier based on engulfing strength.

        SHORT:
          IDEAL:      Close_Bar2 < Open_Bar1 (full engulfing)
          ACCEPTABLE: Close_Bar2 < Close_Bar1
          WEAK:       Close_Bar2 < Level only

        LONG:
          IDEAL:      Close_Bar2 > Open_Bar1 (full engulfing)
          ACCEPTABLE: Close_Bar2 > Close_Bar1
          WEAK:       Close_Bar2 > Level only
        """
        if direction == SignalDirection.SHORT:
            if bar2['Close'] < bar1['Open']:
                return LP2Quality.IDEAL
            elif bar2['Close'] < bar1['Close']:
                return LP2Quality.ACCEPTABLE
            else:
                return LP2Quality.WEAK
        else:  # LONG
            if bar2['Close'] > bar1['Open']:
                return LP2Quality.IDEAL
            elif bar2['Close'] > bar1['Close']:
                return LP2Quality.ACCEPTABLE
            else:
                return LP2Quality.WEAK

    def detect_lp2(self, m5_bars: pd.DataFrame, bar_idx: int,
                   level: Level, tolerance: float) -> Optional[Signal]:
        """Detect LP2 (2-bar false breakout) with quality tier classification."""
        if bar_idx < 1:
            return None

        bar2 = m5_bars.iloc[bar_idx]
        bar1 = m5_bars.iloc[bar_idx - 1]
        level_price = level.price

        # Short LP2
        if level.level_type in (LevelType.RESISTANCE, LevelType.MIRROR):
            if (bar1['Close'] > level_price and
                    bar2['Close'] < level_price and
                    bar2['High'] <= bar1['High']):

                quality = self._classify_lp2_quality(bar1, bar2, level_price,
                                                     SignalDirection.SHORT)

                # If engulfing required, only IDEAL passes (close < open of bar1)
                if self.config.lp2_engulfing_required and quality != LP2Quality.IDEAL:
                    return None

                mult = LP2_QUALITY_MULT[quality]
                return Signal(
                    pattern=PatternType.LP2,
                    direction=SignalDirection.SHORT,
                    level=level,
                    timestamp=bar2['Datetime'],
                    ticker=bar2['Ticker'],
                    entry_price=bar2['Close'],
                    trigger_bar_idx=bar_idx,
                    lp2_quality=quality,
                    position_size_mult=mult,
                    priority=4,
                    meta={'bar1_close': bar1['Close'], 'bar2_close': bar2['Close'],
                          'lp2_quality': quality.value},
                )

        # Long LP2
        if level.level_type in (LevelType.SUPPORT, LevelType.MIRROR):
            if (bar1['Close'] < level_price and
                    bar2['Close'] > level_price and
                    bar2['Low'] >= bar1['Low']):

                quality = self._classify_lp2_quality(bar1, bar2, level_price,
                                                     SignalDirection.LONG)

                if self.config.lp2_engulfing_required and quality != LP2Quality.IDEAL:
                    return None

                mult = LP2_QUALITY_MULT[quality]
                return Signal(
                    pattern=PatternType.LP2,
                    direction=SignalDirection.LONG,
                    level=level,
                    timestamp=bar2['Datetime'],
                    ticker=bar2['Ticker'],
                    entry_price=bar2['Close'],
                    trigger_bar_idx=bar_idx,
                    lp2_quality=quality,
                    position_size_mult=mult,
                    priority=4,
                    meta={'bar1_close': bar1['Close'], 'bar2_close': bar2['Close'],
                          'lp2_quality': quality.value},
                )

        return None

    def _check_bar_overlap(self, bars: pd.DataFrame) -> float:
        """Calculate minimum pairwise overlap ratio across consolidation bars.

        Overlap = intersection of [low, high] ranges / union of ranges.
        Returns the minimum overlap ratio (0.0 = no overlap, 1.0 = identical).
        """
        if len(bars) < 2:
            return 1.0

        min_overlap = 1.0
        for i in range(1, len(bars)):
            prev = bars.iloc[i - 1]
            curr = bars.iloc[i]

            intersection_lo = max(prev['Low'], curr['Low'])
            intersection_hi = min(prev['High'], curr['High'])
            intersection = max(0.0, intersection_hi - intersection_lo)

            union_lo = min(prev['Low'], curr['Low'])
            union_hi = max(prev['High'], curr['High'])
            union = union_hi - union_lo

            if union <= 0:
                continue

            overlap = intersection / union
            min_overlap = min(min_overlap, overlap)

        return min_overlap

    def detect_clp(self, m5_bars: pd.DataFrame, bar_idx: int,
                   level: Level, tolerance: float,
                   atr_m5: pd.Series) -> Optional[Signal]:
        """Detect CLP (Consolidation Level Pattern, 3-7 bars).

        3 phases: breakout → consolidation (with range compression) → trigger bar returns.
        Range compression: >=50% bar overlap between consecutive consolidation bars.
        """
        min_bars = self.config.clp_min_bars
        max_bars = self.config.clp_max_bars
        max_dev_mult = self.config.clp_max_deviation_atr_mult
        min_overlap = self.config.clp_min_overlap_pct

        if bar_idx < min_bars + 1:
            return None

        trigger_bar = m5_bars.iloc[bar_idx]
        level_price = level.price

        current_atr = atr_m5.iloc[bar_idx] if bar_idx < len(atr_m5) else None
        if current_atr is None or pd.isna(current_atr) or current_atr <= 0:
            return None
        max_deviation = max_dev_mult * current_atr

        # Short CLP: consolidation above resistance, trigger closes back below
        if level.level_type in (LevelType.RESISTANCE, LevelType.MIRROR):
            if trigger_bar['Close'] < level_price:
                for n_bars in range(min_bars, min(max_bars + 1, bar_idx)):
                    consol_start = bar_idx - n_bars
                    consol_bars = m5_bars.iloc[consol_start:bar_idx]

                    # All consolidation bars must close above level
                    if not (consol_bars['Close'] > level_price).all():
                        continue

                    # Max deviation from level
                    if (consol_bars['High'] - level_price).max() > max_deviation:
                        continue

                    # Range compression check: consecutive bars must overlap >= 50%
                    overlap = self._check_bar_overlap(consol_bars)
                    if overlap < min_overlap:
                        continue

                    # Breakout bar validation: bar before consolidation must have broken level
                    if consol_start > 0:
                        breakout_bar = m5_bars.iloc[consol_start - 1]
                        # Breakout bar should have pushed through the level
                        if breakout_bar['High'] <= level_price:
                            continue  # no breakout occurred

                    return Signal(
                        pattern=PatternType.CLP,
                        direction=SignalDirection.SHORT,
                        level=level,
                        timestamp=trigger_bar['Datetime'],
                        ticker=trigger_bar['Ticker'],
                        entry_price=trigger_bar['Close'],
                        trigger_bar_idx=bar_idx,
                        bars_beyond=n_bars,
                        priority=6,
                        meta={'consolidation_bars': n_bars, 'overlap': overlap},
                    )

        # Long CLP: consolidation below support, trigger closes back above
        if level.level_type in (LevelType.SUPPORT, LevelType.MIRROR):
            if trigger_bar['Close'] > level_price:
                for n_bars in range(min_bars, min(max_bars + 1, bar_idx)):
                    consol_start = bar_idx - n_bars
                    consol_bars = m5_bars.iloc[consol_start:bar_idx]

                    if not (consol_bars['Close'] < level_price).all():
                        continue

                    if (level_price - consol_bars['Low']).max() > max_deviation:
                        continue

                    overlap = self._check_bar_overlap(consol_bars)
                    if overlap < min_overlap:
                        continue

                    if consol_start > 0:
                        breakout_bar = m5_bars.iloc[consol_start - 1]
                        if breakout_bar['Low'] >= level_price:
                            continue

                    return Signal(
                        pattern=PatternType.CLP,
                        direction=SignalDirection.LONG,
                        level=level,
                        timestamp=trigger_bar['Datetime'],
                        ticker=trigger_bar['Ticker'],
                        entry_price=trigger_bar['Close'],
                        trigger_bar_idx=bar_idx,
                        bars_beyond=n_bars,
                        priority=6,
                        meta={'consolidation_bars': n_bars, 'overlap': overlap},
                    )

        return None

    def detect_model4(self, signal: Signal, m5_bars: pd.DataFrame,
                      atr_m5: pd.Series) -> Signal:
        """Upgrade signal to Model4 if: paranormal bar + mirror level."""
        bar = m5_bars.iloc[signal.trigger_bar_idx]
        bar_range = bar['High'] - bar['Low']

        current_atr = atr_m5.iloc[signal.trigger_bar_idx] if signal.trigger_bar_idx < len(atr_m5) else None
        if current_atr is None or pd.isna(current_atr) or current_atr <= 0:
            return signal

        is_paranormal_bar = bar_range >= 2.0 * current_atr
        is_mirror_level = signal.level.is_mirror or signal.level.level_type == LevelType.MIRROR

        if is_paranormal_bar and is_mirror_level:
            signal.is_model4 = True
            signal.pattern = PatternType.MODEL4
            signal.priority = 10
            signal.meta['paranormal_range'] = bar_range
            signal.meta['atr_m5'] = current_atr

        return signal

    def scan_bar(self, m5_bars: pd.DataFrame, bar_idx: int,
                 active_levels: list[Level], atr_m5: pd.Series,
                 tolerance_func) -> list[Signal]:
        """Scan a single M5 bar against all active levels for patterns."""
        signals = []
        bar = m5_bars.iloc[bar_idx]

        for level in active_levels:
            tol = tolerance_func(level.price)

            if bar['Low'] - tol > level.price or bar['High'] + tol < level.price:
                continue

            signal = None

            # CLP first (most specific, highest priority)
            clp = self.detect_clp(m5_bars, bar_idx, level, tol, atr_m5)
            if clp:
                signal = clp

            if signal is None:
                lp2 = self.detect_lp2(m5_bars, bar_idx, level, tol)
                if lp2:
                    signal = lp2

            if signal is None:
                lp1 = self.detect_lp1(m5_bars, bar_idx, level, tol)
                if lp1:
                    signal = lp1

            if signal:
                signal = self.detect_model4(signal, m5_bars, atr_m5)
                signals.append(signal)

        return signals
