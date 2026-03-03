"""
Pattern Recognition Engine for the False Breakout Strategy Backtester.

Detects LP1 (1-bar), LP2 (2-bar), CLP (3-7 bar), and Model4 patterns
on M5 intraday data at D1 support/resistance levels.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from backtester.core.level_detector import Level, LevelType


class PatternType(Enum):
    LP1 = "LP1"
    LP2 = "LP2"
    CLP = "CLP"
    MODEL4 = "MODEL4"


class TradeDirection(Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class Signal:
    """Represents a detected false breakout signal."""
    timestamp: pd.Timestamp
    ticker: str
    level: Level
    pattern: PatternType
    direction: TradeDirection
    entry_price: float
    trigger_bar_idx: int
    tail_ratio: float = 0.0
    bars_beyond: int = 0
    is_model4: bool = False
    priority: int = 0  # higher = better
    meta: dict = None

    def __post_init__(self):
        if self.meta is None:
            self.meta = {}


class PatternEngineConfig:
    def __init__(self, **kwargs):
        self.tail_ratio_min = kwargs.get('tail_ratio_min', 0.20)
        self.lp2_engulfing_required = kwargs.get('lp2_engulfing_required', True)
        self.clp_min_bars = kwargs.get('clp_min_bars', 3)
        self.clp_max_bars = kwargs.get('clp_max_bars', 7)
        self.clp_max_deviation_atr_mult = kwargs.get('clp_max_deviation_atr_mult', 2.5)
        self.atr_m5_period = kwargs.get('atr_m5_period', 5)


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

        # First bar: TR = H - L
        first_idx = tdf.index[0]
        tdf.loc[first_idx, 'TR'] = tdf.loc[first_idx, 'High'] - tdf.loc[first_idx, 'Low']

        # Wilder's smoothing ATR
        atr = tdf['TR'].ewm(alpha=1.0 / period, adjust=False).mean()
        return atr

    def _check_lp1_short(self, bar: pd.Series, level_price: float,
                         tolerance: float) -> Optional[tuple[float, float]]:
        """Check LP1 pattern for short: Open < Level, High > Level, Close < Level.
        Returns (entry_price, tail_ratio) or None.
        """
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
        """Check LP1 pattern for long: Open > Level, Low < Level, Close > Level.
        Returns (entry_price, tail_ratio) or None.
        """
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

        # Try short signal (breakout above resistance, close back below)
        if level.level_type in (LevelType.RESISTANCE, LevelType.MIRROR):
            result = self._check_lp1_short(bar, level_price, tolerance)
            if result:
                entry_price, tail_ratio = result
                if tail_ratio >= self.config.tail_ratio_min:
                    return Signal(
                        timestamp=bar['Datetime'],
                        ticker=bar['Ticker'],
                        level=level,
                        pattern=PatternType.LP1,
                        direction=TradeDirection.SHORT,
                        entry_price=entry_price,
                        trigger_bar_idx=bar_idx,
                        tail_ratio=tail_ratio,
                        priority=5 if tail_ratio >= 0.30 else 3,
                    )

        # Try long signal (breakout below support, close back above)
        if level.level_type in (LevelType.SUPPORT, LevelType.MIRROR):
            result = self._check_lp1_long(bar, level_price, tolerance)
            if result:
                entry_price, tail_ratio = result
                if tail_ratio >= self.config.tail_ratio_min:
                    return Signal(
                        timestamp=bar['Datetime'],
                        ticker=bar['Ticker'],
                        level=level,
                        pattern=PatternType.LP1,
                        direction=TradeDirection.LONG,
                        entry_price=entry_price,
                        trigger_bar_idx=bar_idx,
                        tail_ratio=tail_ratio,
                        priority=5 if tail_ratio >= 0.30 else 3,
                    )

        return None

    def detect_lp2(self, m5_bars: pd.DataFrame, bar_idx: int,
                   level: Level, tolerance: float) -> Optional[Signal]:
        """Detect LP2 (2-bar false breakout). Bar1 closes beyond level; Bar2 closes back."""
        if bar_idx < 1:
            return None

        bar2 = m5_bars.iloc[bar_idx]
        bar1 = m5_bars.iloc[bar_idx - 1]
        level_price = level.price

        # Short LP2: Bar1 closes above level, Bar2 closes below
        if level.level_type in (LevelType.RESISTANCE, LevelType.MIRROR):
            if (bar1['Close'] > level_price and
                    bar2['Close'] < level_price and
                    bar2['High'] <= bar1['High']):

                engulfing_ok = (not self.config.lp2_engulfing_required or
                                bar2['Close'] < bar1['Open'])
                if engulfing_ok:
                    return Signal(
                        timestamp=bar2['Datetime'],
                        ticker=bar2['Ticker'],
                        level=level,
                        pattern=PatternType.LP2,
                        direction=TradeDirection.SHORT,
                        entry_price=bar2['Close'],
                        trigger_bar_idx=bar_idx,
                        priority=4,
                        meta={'bar1_close': bar1['Close'], 'bar2_close': bar2['Close']},
                    )

        # Long LP2: Bar1 closes below level, Bar2 closes above
        if level.level_type in (LevelType.SUPPORT, LevelType.MIRROR):
            if (bar1['Close'] < level_price and
                    bar2['Close'] > level_price and
                    bar2['Low'] >= bar1['Low']):

                engulfing_ok = (not self.config.lp2_engulfing_required or
                                bar2['Close'] > bar1['Open'])
                if engulfing_ok:
                    return Signal(
                        timestamp=bar2['Datetime'],
                        ticker=bar2['Ticker'],
                        level=level,
                        pattern=PatternType.LP2,
                        direction=TradeDirection.LONG,
                        entry_price=bar2['Close'],
                        trigger_bar_idx=bar_idx,
                        priority=4,
                        meta={'bar1_close': bar1['Close'], 'bar2_close': bar2['Close']},
                    )

        return None

    def detect_clp(self, m5_bars: pd.DataFrame, bar_idx: int,
                   level: Level, tolerance: float,
                   atr_m5: pd.Series) -> Optional[Signal]:
        """Detect CLP (Consolidation Level Pattern, 3-7 bars).
        Breakout -> 3+ bars consolidate beyond level (none close back) -> trigger bar returns.
        """
        min_bars = self.config.clp_min_bars
        max_bars = self.config.clp_max_bars
        max_dev_mult = self.config.clp_max_deviation_atr_mult

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
            if trigger_bar['Close'] >= level_price:
                pass  # trigger must close back below
            else:
                # Look back for consolidation bars above level
                for n_bars in range(min_bars, min(max_bars + 1, bar_idx)):
                    consol_start = bar_idx - n_bars
                    consol_bars = m5_bars.iloc[consol_start:bar_idx]

                    # All consolidation bars must close above level
                    all_above = (consol_bars['Close'] > level_price).all()
                    if not all_above:
                        continue

                    # Check max deviation from level
                    max_dist = (consol_bars['High'] - level_price).max()
                    if max_dist > max_deviation:
                        continue

                    # Breakout bar before consolidation must have broken level
                    if consol_start > 0:
                        breakout_bar = m5_bars.iloc[consol_start - 1]
                        if breakout_bar['Close'] <= level_price:
                            # Verify break happened
                            pass

                    return Signal(
                        timestamp=trigger_bar['Datetime'],
                        ticker=trigger_bar['Ticker'],
                        level=level,
                        pattern=PatternType.CLP,
                        direction=TradeDirection.SHORT,
                        entry_price=trigger_bar['Close'],
                        trigger_bar_idx=bar_idx,
                        bars_beyond=n_bars,
                        priority=6,
                        meta={'consolidation_bars': n_bars},
                    )

        # Long CLP: consolidation below support, trigger closes back above
        if level.level_type in (LevelType.SUPPORT, LevelType.MIRROR):
            if trigger_bar['Close'] <= level_price:
                pass  # trigger must close back above
            else:
                for n_bars in range(min_bars, min(max_bars + 1, bar_idx)):
                    consol_start = bar_idx - n_bars
                    consol_bars = m5_bars.iloc[consol_start:bar_idx]

                    all_below = (consol_bars['Close'] < level_price).all()
                    if not all_below:
                        continue

                    max_dist = (level_price - consol_bars['Low']).max()
                    if max_dist > max_deviation:
                        continue

                    return Signal(
                        timestamp=trigger_bar['Datetime'],
                        ticker=trigger_bar['Ticker'],
                        level=level,
                        pattern=PatternType.CLP,
                        direction=TradeDirection.LONG,
                        entry_price=trigger_bar['Close'],
                        trigger_bar_idx=bar_idx,
                        bars_beyond=n_bars,
                        priority=6,
                        meta={'consolidation_bars': n_bars},
                    )

        return None

    def detect_model4(self, signal: Signal, m5_bars: pd.DataFrame,
                      atr_m5: pd.Series) -> Signal:
        """Upgrade signal to Model4 if conditions met:
        Paranormal bar + Mirror level + any LP pattern -> MAXIMUM priority.
        """
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
            signal.priority = 10  # Maximum priority
            signal.meta['paranormal_range'] = bar_range
            signal.meta['atr_m5'] = current_atr

        return signal

    def scan_bar(self, m5_bars: pd.DataFrame, bar_idx: int,
                 active_levels: list[Level], atr_m5: pd.Series,
                 tolerance_func) -> list[Signal]:
        """Scan a single M5 bar against all active levels for patterns.
        Returns list of signals found (usually 0 or 1).
        """
        signals = []
        bar = m5_bars.iloc[bar_idx]

        for level in active_levels:
            tol = tolerance_func(level.price)

            # Quick proximity check: is this bar near the level?
            if bar['Low'] - tol > level.price or bar['High'] + tol < level.price:
                continue

            # Try patterns in order of specificity
            signal = None

            # CLP is checked first (most specific, highest priority)
            clp = self.detect_clp(m5_bars, bar_idx, level, tol, atr_m5)
            if clp:
                signal = clp

            # LP2
            if signal is None:
                lp2 = self.detect_lp2(m5_bars, bar_idx, level, tol)
                if lp2:
                    signal = lp2

            # LP1
            if signal is None:
                lp1 = self.detect_lp1(m5_bars, bar_idx, level, tol)
                if lp1:
                    signal = lp1

            if signal:
                # Check for Model4 upgrade
                signal = self.detect_model4(signal, m5_bars, atr_m5)
                signals.append(signal)

        return signals
