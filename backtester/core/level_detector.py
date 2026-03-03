"""
D1 Level Detection Module for the False Breakout Strategy Backtester.

Detects support/resistance levels from daily OHLCV data using fractal analysis,
validates with BPU touches, scores levels, detects mirrors, and manages level lifecycle.
Builds on existing level_detection/ code but adds anti-sawing invalidation and
mirror confirmation logic required by the strategy spec v3.4.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class LevelType(Enum):
    RESISTANCE = "R"
    SUPPORT = "S"
    MIRROR = "M"


class LevelStatus(Enum):
    ACTIVE = "active"
    INVALIDATED = "invalidated"
    MIRROR_CANDIDATE = "mirror_candidate"
    MIRROR_CONFIRMED = "mirror_confirmed"


@dataclass
class Level:
    date: pd.Timestamp
    ticker: str
    price: float
    level_type: LevelType
    score: int
    bsu_index: int
    atr_d1: float
    is_paranormal: bool
    touches: int
    is_round_number: bool
    is_mirror: bool
    status: LevelStatus = LevelStatus.ACTIVE
    cross_count: int = 0
    last_cross_bar: int = -1
    mirror_breakout_date: Optional[pd.Timestamp] = None
    mirror_max_distance_atr: float = 0.0
    mirror_days_beyond: int = 0
    score_breakdown: dict = field(default_factory=dict)


# Scoring constants
SCORE_MIRROR = 10
SCORE_PENNY_TOUCHES = 9
SCORE_PARANORMAL = 8
SCORE_GAP_BOUNDARY = 8
SCORE_AGE = 7
SCORE_ROUND_NUMBER = 6
MIN_TOUCHES_PENNY = 3

# Anti-sawing
CROSS_COUNT_INVALIDATE = 3
CROSS_COUNT_WINDOW = 20

# Mirror validation
MIRROR_ATR_DISTANCE = 3.0
MIRROR_DAYS_BEYOND = 3


class LevelDetectorConfig:
    def __init__(self, **kwargs):
        self.fractal_depth = kwargs.get('fractal_depth', 5)
        self.tolerance_cents = kwargs.get('tolerance_cents', 0.05)
        self.tolerance_pct = kwargs.get('tolerance_pct', 0.001)  # 0.1% for >$100
        self.price_threshold = kwargs.get('price_threshold', 100.0)
        self.atr_period = kwargs.get('atr_period', 5)
        self.paranormal_mult = kwargs.get('paranormal_mult', 2.0)
        self.atr_upper_mult = kwargs.get('atr_upper_mult', 2.0)
        self.atr_lower_mult = kwargs.get('atr_lower_mult', 0.5)
        self.min_level_score = kwargs.get('min_level_score', 5)
        self.cross_count_invalidate = kwargs.get('cross_count_invalidate', CROSS_COUNT_INVALIDATE)
        self.cross_count_window = kwargs.get('cross_count_window', CROSS_COUNT_WINDOW)
        self.mirror_atr_distance = kwargs.get('mirror_atr_distance', MIRROR_ATR_DISTANCE)
        self.mirror_days_beyond = kwargs.get('mirror_days_beyond', MIRROR_DAYS_BEYOND)

    def get_tolerance(self, price: float) -> float:
        if price > self.price_threshold:
            return price * self.tolerance_pct
        return self.tolerance_cents


class LevelDetector:
    def __init__(self, config: Optional[LevelDetectorConfig] = None):
        self.config = config or LevelDetectorConfig()
        self.levels: list[Level] = []

    def aggregate_m5_to_d1(self, m5_df: pd.DataFrame) -> pd.DataFrame:
        """Aggregate 5-minute OHLCV data to daily bars."""
        df = m5_df.copy()
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        df['Date'] = df['Datetime'].dt.date

        daily = df.groupby(['Ticker', 'Date']).agg(
            Open=('Open', 'first'),
            High=('High', 'max'),
            Low=('Low', 'min'),
            Close=('Close', 'last'),
            Volume=('Volume', 'sum')
        ).reset_index()

        daily['Date'] = pd.to_datetime(daily['Date'])
        daily = daily.sort_values(['Ticker', 'Date']).reset_index(drop=True)
        return daily

    def calculate_true_range(self, daily_df: pd.DataFrame) -> pd.DataFrame:
        """Calculate True Range for each daily bar."""
        df = daily_df.copy()
        df['PrevClose'] = df.groupby('Ticker')['Close'].shift(1)
        df['HL'] = df['High'] - df['Low']
        df['HC'] = (df['High'] - df['PrevClose']).abs()
        df['LC'] = (df['Low'] - df['PrevClose']).abs()
        df['TrueRange'] = df[['HL', 'HC', 'LC']].max(axis=1)
        # First bar of each ticker: TR = H - L
        mask = df['PrevClose'].isna()
        df.loc[mask, 'TrueRange'] = df.loc[mask, 'HL']
        df.drop(columns=['PrevClose', 'HL', 'HC', 'LC'], inplace=True)
        return df

    def calculate_modified_atr(self, daily_df: pd.DataFrame) -> pd.DataFrame:
        """Calculate Modified ATR(5) excluding paranormal and insignificant bars."""
        df = daily_df.copy()
        period = self.config.atr_period
        upper = self.config.atr_upper_mult
        lower = self.config.atr_lower_mult

        df['ATR'] = np.nan
        df['ModifiedATR'] = np.nan
        df['IsParanormal'] = False

        for ticker in df['Ticker'].unique():
            mask = df['Ticker'] == ticker
            idx = df.loc[mask].index
            tr_vals = df.loc[idx, 'TrueRange'].values.astype(float)

            if len(tr_vals) < period:
                continue

            # Initial ATR = simple average of first `period` bars
            initial_atr = np.mean(tr_vals[:period])
            atr_arr = np.full(len(tr_vals), np.nan)
            mod_atr_arr = np.full(len(tr_vals), np.nan)
            paranormal_arr = np.zeros(len(tr_vals), dtype=bool)

            atr_arr[period - 1] = initial_atr
            mod_atr_arr[period - 1] = initial_atr

            for i in range(period, len(tr_vals)):
                prev_atr = atr_arr[i - 1]
                prev_mod_atr = mod_atr_arr[i - 1]
                tr = tr_vals[i]

                # Standard ATR (Wilder's smoothing)
                atr_arr[i] = ((period - 1) * prev_atr + tr) / period

                # Modified ATR: exclude paranormal and insignificant bars
                if tr >= upper * prev_mod_atr:
                    paranormal_arr[i] = True
                    mod_atr_arr[i] = prev_mod_atr  # carry forward
                elif tr < lower * prev_mod_atr:
                    mod_atr_arr[i] = prev_mod_atr  # carry forward
                else:
                    mod_atr_arr[i] = ((period - 1) * prev_mod_atr + tr) / period

            df.loc[idx, 'ATR'] = atr_arr
            df.loc[idx, 'ModifiedATR'] = mod_atr_arr
            df.loc[idx, 'IsParanormal'] = paranormal_arr

        return df

    def detect_fractals(self, daily_df: pd.DataFrame) -> pd.DataFrame:
        """Detect fractal highs and lows."""
        df = daily_df.copy()
        k = self.config.fractal_depth
        df['IsFractalHigh'] = False
        df['IsFractalLow'] = False

        for ticker in df['Ticker'].unique():
            mask = df['Ticker'] == ticker
            idx = df.loc[mask].index
            highs = df.loc[idx, 'High'].values
            lows = df.loc[idx, 'Low'].values
            n = len(highs)

            fh = np.zeros(n, dtype=bool)
            fl = np.zeros(n, dtype=bool)

            for i in range(k, n - k):
                # Fractal high: H[i] > max of k bars on each side
                left_highs = highs[i - k:i]
                right_highs = highs[i + 1:i + k + 1]
                if highs[i] > np.max(left_highs) and highs[i] > np.max(right_highs):
                    fh[i] = True

                # Fractal low: L[i] < min of k bars on each side
                left_lows = lows[i - k:i]
                right_lows = lows[i + 1:i + k + 1]
                if lows[i] < np.min(left_lows) and lows[i] < np.min(right_lows):
                    fl[i] = True

            df.loc[idx, 'IsFractalHigh'] = fh
            df.loc[idx, 'IsFractalLow'] = fl

        return df

    def _is_round_number(self, price: float) -> bool:
        cents = round(price * 100) % 100
        return cents == 0 or cents == 50

    def _count_touches(self, price: float, daily_df: pd.DataFrame,
                       ticker: str, bsu_index: int) -> int:
        """Count BPU touches at level price after the BSU bar."""
        tdf = daily_df[daily_df['Ticker'] == ticker]
        tol = self.config.get_tolerance(price)
        touches = 0
        for _, row in tdf.iterrows():
            if row.name <= bsu_index:
                continue
            if (row['Low'] - tol) <= price <= (row['High'] + tol):
                touches += 1
        return touches

    def _check_mirror(self, price: float, daily_df: pd.DataFrame,
                      ticker: str, bsu_index: int) -> bool:
        """Check if level acts as both support and resistance."""
        tdf = daily_df[daily_df['Ticker'] == ticker]
        tol = self.config.get_tolerance(price)
        acted_as_support = False
        acted_as_resistance = False

        for _, row in tdf.iterrows():
            if row.name <= bsu_index:
                continue
            # Support: price bounced up from level
            if abs(row['Low'] - price) <= tol and row['Close'] > price:
                acted_as_support = True
            # Resistance: price bounced down from level
            if abs(row['High'] - price) <= tol and row['Close'] < price:
                acted_as_resistance = True

        return acted_as_support and acted_as_resistance

    def _score_level(self, price: float, is_paranormal: bool, touches: int,
                     is_mirror: bool, is_round: bool, bsu_index: int,
                     total_bars: int) -> tuple[int, dict]:
        """Calculate composite score for a level."""
        breakdown = {}
        score = 0

        if is_mirror:
            score += SCORE_MIRROR
            breakdown['mirror'] = SCORE_MIRROR
        if touches >= MIN_TOUCHES_PENNY:
            score += SCORE_PENNY_TOUCHES
            breakdown['penny_touches'] = SCORE_PENNY_TOUCHES
        if is_paranormal:
            score += SCORE_PARANORMAL
            breakdown['paranormal'] = SCORE_PARANORMAL
        # Age/duration score: if level has survived > 20 bars
        bars_alive = total_bars - bsu_index
        if bars_alive >= 20:
            score += SCORE_AGE
            breakdown['age'] = SCORE_AGE
        if is_round:
            score += SCORE_ROUND_NUMBER
            breakdown['round_number'] = SCORE_ROUND_NUMBER

        return score, breakdown

    def detect_levels(self, daily_df: pd.DataFrame) -> tuple[list['Level'], pd.DataFrame]:
        """Run full level detection pipeline on daily data.
        Returns (levels, enriched_daily_df) with ATR and fractal columns added.
        """
        df = self.calculate_true_range(daily_df)
        df = self.calculate_modified_atr(df)
        df = self.detect_fractals(df)

        levels = []
        for ticker in df['Ticker'].unique():
            tdf = df[df['Ticker'] == ticker]
            total_bars = len(tdf)

            for idx_pos, (idx, row) in enumerate(tdf.iterrows()):
                fractal_prices = []
                if row['IsFractalHigh']:
                    fractal_prices.append((row['High'], LevelType.RESISTANCE))
                if row['IsFractalLow']:
                    fractal_prices.append((row['Low'], LevelType.SUPPORT))

                for price, ltype in fractal_prices:
                    atr = row.get('ModifiedATR', row.get('ATR', 0))
                    if pd.isna(atr) or atr == 0:
                        continue

                    is_paranormal = bool(row.get('IsParanormal', False))
                    touches = self._count_touches(price, df, ticker, idx)
                    is_mirror = self._check_mirror(price, df, ticker, idx)
                    is_round = self._is_round_number(price)

                    if is_mirror:
                        ltype = LevelType.MIRROR

                    score, breakdown = self._score_level(
                        price, is_paranormal, touches, is_mirror,
                        is_round, idx_pos, total_bars
                    )

                    # Minimum 1 BPU touch to activate
                    if touches < 1:
                        continue

                    if score < self.config.min_level_score:
                        continue

                    level = Level(
                        date=row['Date'],
                        ticker=ticker,
                        price=price,
                        level_type=ltype,
                        score=score,
                        bsu_index=idx,
                        atr_d1=atr,
                        is_paranormal=is_paranormal,
                        touches=touches,
                        is_round_number=is_round,
                        is_mirror=is_mirror,
                        score_breakdown=breakdown,
                    )
                    levels.append(level)

        self.levels = levels
        return levels, df

    def build_daily_index(self, daily_df: pd.DataFrame) -> dict:
        """Pre-index daily data by ticker for fast lookups."""
        index = {}
        for ticker in daily_df['Ticker'].unique():
            tdf = daily_df[daily_df['Ticker'] == ticker].sort_values('Date')
            index[ticker] = {
                'dates': tdf['Date'].values,
                'highs': tdf['High'].values,
                'lows': tdf['Low'].values,
                'closes': tdf['Close'].values,
            }
        return index

    def check_anti_sawing(self, level: Level, daily_df: pd.DataFrame,
                          current_date: pd.Timestamp,
                          daily_index: dict = None) -> bool:
        """Check if level is invalidated by cross-count sawing.
        Returns True if level is INVALIDATED (should not trade).
        Uses daily bars up to current_date (last N bars where N=window).
        """
        # Already invalidated
        if level.status == LevelStatus.INVALIDATED:
            return True

        window = self.config.cross_count_window
        price = level.price
        tol = self.config.get_tolerance(price)

        # Use pre-indexed data if available
        if daily_index and level.ticker in daily_index:
            idx = daily_index[level.ticker]
            date_mask = idx['dates'] <= np.datetime64(current_date)
            closes = idx['closes'][date_mask]
            if len(closes) > window:
                closes = closes[-window:]

            cross_count = 0
            prev_side = None
            for c in closes:
                if c > price + tol:
                    current_side = 'above'
                elif c < price - tol:
                    current_side = 'below'
                else:
                    continue
                if prev_side is not None and current_side != prev_side:
                    cross_count += 1
                prev_side = current_side
        else:
            tdf = daily_df[
                (daily_df['Ticker'] == level.ticker) &
                (daily_df['Date'] <= current_date)
            ]
            if len(tdf) > window:
                tdf = tdf.tail(window)

            cross_count = 0
            prev_side = None
            for _, row in tdf.iterrows():
                if row['Close'] > price + tol:
                    current_side = 'above'
                elif row['Close'] < price - tol:
                    current_side = 'below'
                else:
                    continue
                if prev_side is not None and current_side != prev_side:
                    cross_count += 1
                prev_side = current_side

        if cross_count >= self.config.cross_count_invalidate:
            level.status = LevelStatus.INVALIDATED
            level.cross_count = cross_count
            return True

        return False

    def update_mirror_status(self, level: Level, daily_df: pd.DataFrame,
                             current_date: pd.Timestamp,
                             daily_index: dict = None) -> None:
        """Update mirror candidate/confirmed status for a level after breakout."""
        if level.status == LevelStatus.MIRROR_CONFIRMED:
            return

        price = level.price
        atr = level.atr_d1
        if atr <= 0:
            return
        min_distance = self.config.mirror_atr_distance * atr
        tol = self.config.get_tolerance(price)

        if daily_index and level.ticker in daily_index:
            idx = daily_index[level.ticker]
            date_mask = (idx['dates'] <= np.datetime64(current_date)) & \
                        (idx['dates'] > np.datetime64(level.date))
            highs = idx['highs'][date_mask]
            lows = idx['lows'][date_mask]

            if len(highs) == 0:
                return

            max_dist_above = (highs - price).max()
            max_dist_below = (price - lows).max()
            max_distance = max(max_dist_above, max_dist_below)

            if max_distance < min_distance:
                return

            days_beyond = int(((lows > price + tol) | (highs < price - tol)).sum())

            if days_beyond >= self.config.mirror_days_beyond:
                level.status = LevelStatus.MIRROR_CANDIDATE
                level.mirror_max_distance_atr = max_distance / atr
                level.mirror_days_beyond = days_beyond

                # Check last 10 bars for return touch
                last_h = highs[-10:] if len(highs) >= 10 else highs
                last_l = lows[-10:] if len(lows) >= 10 else lows
                for h, l in zip(last_h, last_l):
                    if (l - tol) <= price <= (h + tol):
                        level.status = LevelStatus.MIRROR_CONFIRMED
                        level.is_mirror = True
                        level.level_type = LevelType.MIRROR
                        if 'mirror' not in level.score_breakdown:
                            level.score += SCORE_MIRROR
                            level.score_breakdown['mirror'] = SCORE_MIRROR
                        break
        else:
            tdf = daily_df[
                (daily_df['Ticker'] == level.ticker) &
                (daily_df['Date'] <= current_date) &
                (daily_df['Date'] > level.date)
            ]
            if tdf.empty:
                return

            max_dist_above = (tdf['High'] - price).max()
            max_dist_below = (price - tdf['Low']).max()
            max_distance = max(max_dist_above, max_dist_below)

            if max_distance < min_distance:
                return

            days_beyond = 0
            for _, row in tdf.iterrows():
                if row['Low'] > price + tol or row['High'] < price - tol:
                    days_beyond += 1

            if days_beyond >= self.config.mirror_days_beyond:
                level.status = LevelStatus.MIRROR_CANDIDATE
                level.mirror_max_distance_atr = max_distance / atr
                level.mirror_days_beyond = days_beyond

                last_bars = tdf.tail(10)
                for _, row in last_bars.iterrows():
                    if (row['Low'] - tol) <= price <= (row['High'] + tol):
                        level.status = LevelStatus.MIRROR_CONFIRMED
                        level.is_mirror = True
                        level.level_type = LevelType.MIRROR
                        if 'mirror' not in level.score_breakdown:
                            level.score += SCORE_MIRROR
                            level.score_breakdown['mirror'] = SCORE_MIRROR
                        break

    def get_active_levels(self, ticker: str, current_date: pd.Timestamp,
                          daily_df: pd.DataFrame,
                          daily_index: dict = None) -> list[Level]:
        """Get all active (non-invalidated) levels for a ticker on a given date."""
        active = []
        for level in self.levels:
            if level.ticker != ticker:
                continue
            if level.date > current_date:
                continue
            if level.status == LevelStatus.INVALIDATED:
                continue

            # Update mirror status
            self.update_mirror_status(level, daily_df, current_date, daily_index)

            active.append(level)
        return active

    def process_data(self, m5_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[Level]]:
        """Full pipeline: M5 data -> daily aggregation -> level detection.
        Returns (m5_df, enriched_daily_df, levels).
        """
        daily_df = self.aggregate_m5_to_d1(m5_df)
        levels, daily_df = self.detect_levels(daily_df)
        return m5_df, daily_df, levels
