"""
Intraday Level Detector for the False Breakout Strategy Backtester.

Detects M5 and H1 fractal support/resistance levels for TARGET placement.
Entry signals still use D1 levels — this module provides closer, reachable
profit targets to replace the unreachable D1-only target system.

Key insight from v2: 57% of trades exit at EOD because D1 targets are too far.
Intraday fractals provide intermediate S/R that price actually reaches.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional


@dataclass
class IntradayLevel:
    """A detected intraday support/resistance level."""
    price: float
    timeframe: str  # "M5" or "H1"
    bar_time: pd.Timestamp
    bar_index: int
    level_type: str  # "resistance" or "support"
    touches: int = 1  # subsequent touches at this level
    strength: float = 1.0  # relative strength score


class IntradayLevelConfig:
    def __init__(self, **kwargs):
        self.fractal_depth_m5 = kwargs.get('fractal_depth_m5', 3)
        self.fractal_depth_h1 = kwargs.get('fractal_depth_h1', 3)
        self.min_m5_level_age_bars = kwargs.get('min_m5_level_age_bars', 6)
        self.enable_h1 = kwargs.get('enable_h1', False)
        self.min_target_r = kwargs.get('min_target_r', 1.0)  # min R for intraday target
        self.level_merge_tolerance = kwargs.get('level_merge_tolerance', 0.05)
        self.lookback_bars = kwargs.get('lookback_bars', 500)  # how far back to find levels


class IntradayLevelDetector:
    def __init__(self, config: Optional[IntradayLevelConfig] = None):
        self.config = config or IntradayLevelConfig()

    def aggregate_m5_to_h1(self, m5_df: pd.DataFrame) -> pd.DataFrame:
        """Aggregate 5-minute data to 1-hour bars."""
        df = m5_df.copy()
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        df['Hour'] = df['Datetime'].dt.floor('h')

        h1 = df.groupby(['Ticker', 'Hour']).agg(
            Open=('Open', 'first'),
            High=('High', 'max'),
            Low=('Low', 'min'),
            Close=('Close', 'last'),
            Volume=('Volume', 'sum')
        ).reset_index()

        h1 = h1.rename(columns={'Hour': 'Datetime'})
        h1 = h1.sort_values(['Ticker', 'Datetime']).reset_index(drop=True)
        return h1

    def detect_fractals(self, bars_df: pd.DataFrame, depth: int,
                        timeframe: str) -> list[IntradayLevel]:
        """Detect fractal highs and lows on any timeframe bars."""
        levels = []
        k = depth

        for ticker in bars_df['Ticker'].unique():
            tdf = bars_df[bars_df['Ticker'] == ticker].reset_index(drop=True)
            highs = tdf['High'].values
            lows = tdf['Low'].values
            n = len(highs)

            for i in range(k, n - k):
                # Fractal high → resistance
                left_h = highs[i - k:i]
                right_h = highs[i + 1:i + k + 1]
                if highs[i] > np.max(left_h) and highs[i] > np.max(right_h):
                    levels.append(IntradayLevel(
                        price=highs[i],
                        timeframe=timeframe,
                        bar_time=pd.Timestamp(tdf.iloc[i]['Datetime']),
                        bar_index=tdf.index[i],
                        level_type="resistance",
                    ))

                # Fractal low → support
                left_l = lows[i - k:i]
                right_l = lows[i + 1:i + k + 1]
                if lows[i] < np.min(left_l) and lows[i] < np.min(right_l):
                    levels.append(IntradayLevel(
                        price=lows[i],
                        timeframe=timeframe,
                        bar_time=pd.Timestamp(tdf.iloc[i]['Datetime']),
                        bar_index=tdf.index[i],
                        level_type="support",
                    ))

        return levels

    def merge_nearby_levels(self, levels: list[IntradayLevel]) -> list[IntradayLevel]:
        """Merge levels within tolerance into single level with higher touch count."""
        if not levels:
            return []

        tol = self.config.level_merge_tolerance
        sorted_levels = sorted(levels, key=lambda l: l.price)
        merged = []
        current = sorted_levels[0]

        for lvl in sorted_levels[1:]:
            if abs(lvl.price - current.price) <= tol:
                # Merge: keep earlier time, bump touches, keep stronger type
                current.touches += 1
                current.strength += 1.0
                if lvl.bar_time < current.bar_time:
                    current.bar_time = lvl.bar_time
                    current.bar_index = lvl.bar_index
            else:
                merged.append(current)
                current = lvl

        merged.append(current)
        return merged

    def detect_levels(self, m5_df: pd.DataFrame, ticker: str,
                      current_bar_idx: int) -> list[IntradayLevel]:
        """Detect intraday levels visible before current_bar_idx.

        Only returns levels formed at least min_m5_level_age_bars ago,
        looking back up to lookback_bars.
        """
        # Window of M5 bars to analyze
        start_idx = max(0, current_bar_idx - self.config.lookback_bars)
        end_idx = current_bar_idx - self.config.min_m5_level_age_bars
        if end_idx <= start_idx:
            return []

        ticker_mask = m5_df['Ticker'] == ticker
        window = m5_df[ticker_mask].iloc[start_idx:end_idx + 1]

        if len(window) < 2 * self.config.fractal_depth_m5 + 1:
            return []

        # Detect M5 fractals
        m5_levels = self.detect_fractals(window, self.config.fractal_depth_m5, "M5")

        # Detect H1 fractals if enabled
        h1_levels = []
        if self.config.enable_h1:
            h1_window = m5_df[ticker_mask].iloc[start_idx:end_idx + 1]
            if len(h1_window) >= 12 * (2 * self.config.fractal_depth_h1 + 1):
                h1_bars = self.aggregate_m5_to_h1(h1_window)
                h1_levels = self.detect_fractals(
                    h1_bars, self.config.fractal_depth_h1, "H1"
                )

        all_levels = m5_levels + h1_levels
        return self.merge_nearby_levels(all_levels)

    def get_intraday_targets(self, levels: list[IntradayLevel],
                             entry_price: float, direction: str,
                             stop_distance: float,
                             d1_target: float) -> list[IntradayLevel]:
        """Get qualifying intraday levels between entry and D1 target.

        Returns levels sorted by distance from entry (nearest first).
        Filters out levels too close (< min_target_r * stop_distance).

        Args:
            levels: all detected intraday levels
            entry_price: trade entry price
            direction: "short" or "long"
            stop_distance: absolute stop distance for R calculation
            d1_target: the original D1-level target price
        """
        min_dist = self.config.min_target_r * stop_distance
        candidates = []

        for lvl in levels:
            if direction == "short":
                # Target below entry for shorts
                dist = entry_price - lvl.price
                if dist < min_dist:
                    continue
                # Must be above (closer than) D1 target
                if lvl.price <= d1_target:
                    continue
                candidates.append((dist, lvl))
            else:
                # Target above entry for longs
                dist = lvl.price - entry_price
                if dist < min_dist:
                    continue
                # Must be below (closer than) D1 target
                if lvl.price >= d1_target:
                    continue
                candidates.append((dist, lvl))

        # Sort by distance (nearest first)
        candidates.sort(key=lambda x: x[0])
        return [c[1] for c in candidates]
