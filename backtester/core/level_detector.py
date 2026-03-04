"""
D1 Level Detection Module for the False Breakout Strategy Backtester.

Detects support/resistance levels from daily OHLCV data using fractal analysis,
validates with BPU touches, scores levels, detects mirrors, and manages level lifecycle.
Implements anti-sawing invalidation, Nison invalidation, and gap boundary scoring.

Reference: L-005.1 spec §2-4, strategy spec v3.4.
"""

import pandas as pd
import numpy as np
from typing import Optional

from backtester.data_types import Level, LevelType, LevelStatus

# Scoring constants (L-005.1 §2.4)
SCORE_MIRROR = 10
SCORE_PENNY_TOUCHES = 9   # 3+ penny-to-penny touches
SCORE_PARANORMAL = 8
SCORE_GAP_BOUNDARY = 8
SCORE_AGE = 7              # survived 20+ bars
SCORE_ROUND_NUMBER = 6
MIN_TOUCHES_PENNY = 3

# Anti-sawing (L-005.1 §2.5)
CROSS_COUNT_INVALIDATE = 3
CROSS_COUNT_WINDOW = 20

# Mirror validation (L-005.1 §2.6)
MIRROR_ATR_DISTANCE = 3.0
MIRROR_DAYS_BEYOND = 3


class LevelDetectorConfig:
    def __init__(self, **kwargs):
        self.fractal_depth = kwargs.get('fractal_depth', 10)
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
        self.gap_min_pct = kwargs.get('gap_min_pct', 0.005)  # 0.5% gap threshold

    def get_tolerance(self, price: float) -> float:
        if price > self.price_threshold:
            return price * self.tolerance_pct
        return self.tolerance_cents


class LevelDetector:
    def __init__(self, config: Optional[LevelDetectorConfig] = None):
        self.config = config or LevelDetectorConfig()
        self.levels: list[Level] = []

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

                atr_arr[i] = ((period - 1) * prev_atr + tr) / period

                if tr >= upper * prev_mod_atr:
                    paranormal_arr[i] = True
                    mod_atr_arr[i] = prev_mod_atr
                elif tr < lower * prev_mod_atr:
                    mod_atr_arr[i] = prev_mod_atr
                else:
                    mod_atr_arr[i] = ((period - 1) * prev_mod_atr + tr) / period

            df.loc[idx, 'ATR'] = atr_arr
            df.loc[idx, 'ModifiedATR'] = mod_atr_arr
            df.loc[idx, 'IsParanormal'] = paranormal_arr

        return df

    def detect_fractals(self, daily_df: pd.DataFrame) -> pd.DataFrame:
        """Detect fractal highs and lows with configurable k (fractal_depth).

        A fractal at bar[i] is only confirmed after bar[i+k] completes,
        so confirmed_at = date of bar[i+k].
        """
        df = daily_df.copy()
        k = self.config.fractal_depth
        df['IsFractalHigh'] = False
        df['IsFractalLow'] = False
        df['FractalConfirmedAt'] = pd.NaT

        for ticker in df['Ticker'].unique():
            mask = df['Ticker'] == ticker
            idx = df.loc[mask].index
            highs = df.loc[idx, 'High'].values
            lows = df.loc[idx, 'Low'].values
            dates = df.loc[idx, 'Date'].values
            n = len(highs)

            fh = np.zeros(n, dtype=bool)
            fl = np.zeros(n, dtype=bool)
            confirmed_at = [pd.NaT] * n

            for i in range(k, n - k):
                left_highs = highs[i - k:i]
                right_highs = highs[i + 1:i + k + 1]
                if highs[i] > np.max(left_highs) and highs[i] > np.max(right_highs):
                    fh[i] = True
                    # Confirmed when the last right-side bar completes
                    confirmed_at[i] = dates[i + k]

                left_lows = lows[i - k:i]
                right_lows = lows[i + 1:i + k + 1]
                if lows[i] < np.min(left_lows) and lows[i] < np.min(right_lows):
                    fl[i] = True
                    confirmed_at[i] = dates[i + k]

            df.loc[idx, 'IsFractalHigh'] = fh
            df.loc[idx, 'IsFractalLow'] = fl
            df.loc[idx, 'FractalConfirmedAt'] = confirmed_at

        return df

    def _is_round_number(self, price: float) -> bool:
        cents = round(price * 100) % 100
        return cents == 0 or cents == 50

    def _count_touches(self, price: float, daily_df: pd.DataFrame,
                       ticker: str, bsu_index: int) -> int:
        """Count BPU touches at level price after the BSU bar.

        Penny-to-penny: close within tolerance of the level price.
        """
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
            if abs(row['Low'] - price) <= tol and row['Close'] > price:
                acted_as_support = True
            if abs(row['High'] - price) <= tol and row['Close'] < price:
                acted_as_resistance = True

        return acted_as_support and acted_as_resistance

    def _detect_gap_boundary(self, price: float, daily_df: pd.DataFrame,
                             ticker: str, bsu_index: int) -> bool:
        """Check if level price coincides with a gap boundary.

        A gap exists when prev_close and next_open differ by >= gap_min_pct.
        The gap boundary is the close or open price at the gap edge.
        """
        tdf = daily_df[daily_df['Ticker'] == ticker].sort_values('Date')
        tol = self.config.get_tolerance(price)
        gap_threshold = self.config.gap_min_pct

        closes = tdf['Close'].values
        opens = tdf['Open'].values

        for i in range(1, len(closes)):
            prev_close = closes[i - 1]
            curr_open = opens[i]

            if prev_close <= 0:
                continue

            gap_pct = abs(curr_open - prev_close) / prev_close
            if gap_pct >= gap_threshold:
                # Gap up: boundary at prev_close (support) and curr_open (resistance)
                # Gap down: boundary at curr_open (support) and prev_close (resistance)
                if abs(prev_close - price) <= tol or abs(curr_open - price) <= tol:
                    return True

        return False

    def _score_level(self, price: float, is_paranormal: bool, touches: int,
                     is_mirror: bool, is_round: bool, bsu_index: int,
                     total_bars: int, is_gap_boundary: bool = False) -> tuple[int, dict]:
        """Calculate composite score for a level (L-005.1 §2.4)."""
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
        if is_gap_boundary:
            score += SCORE_GAP_BOUNDARY
            breakdown['gap_boundary'] = SCORE_GAP_BOUNDARY
        bars_alive = total_bars - bsu_index
        if bars_alive >= 20:
            score += SCORE_AGE
            breakdown['age'] = SCORE_AGE
        if is_round:
            score += SCORE_ROUND_NUMBER
            breakdown['round_number'] = SCORE_ROUND_NUMBER

        return score, breakdown

    def detect_levels(self, daily_df: pd.DataFrame) -> tuple[list[Level], pd.DataFrame]:
        """Run full level detection pipeline on daily data.

        Returns (levels, enriched_daily_df) with ATR, fractal, and confirmed_at columns.
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
                    is_gap = self._detect_gap_boundary(price, df, ticker, idx)

                    if is_mirror:
                        ltype = LevelType.MIRROR

                    score, breakdown = self._score_level(
                        price, is_paranormal, touches, is_mirror,
                        is_round, idx_pos, total_bars, is_gap
                    )

                    if touches < 1:
                        continue

                    if score < self.config.min_level_score:
                        continue

                    # confirmed_at from fractal detection
                    confirmed_at = row.get('FractalConfirmedAt', None)
                    if pd.isna(confirmed_at) if confirmed_at is not None else True:
                        confirmed_at = None

                    level = Level(
                        price=price,
                        level_type=ltype,
                        score=score,
                        confirmed_at=pd.Timestamp(confirmed_at) if confirmed_at is not None else None,
                        ticker=ticker,
                        date=row['Date'],
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
                'opens': tdf['Open'].values,
            }
        return index

    def check_anti_sawing(self, level: Level, daily_df: pd.DataFrame,
                          current_date: pd.Timestamp,
                          daily_index: dict = None) -> bool:
        """Check if level is invalidated by cross-count sawing.

        Returns True if level is INVALIDATED (should not trade).
        """
        if level.status == LevelStatus.INVALIDATED:
            return True

        window = self.config.cross_count_window
        price = level.price
        tol = self.config.get_tolerance(price)

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

    def check_nison_invalidation(self, level: Level, daily_df: pd.DataFrame,
                                 current_date: pd.Timestamp,
                                 daily_index: dict = None) -> bool:
        """Nison invalidation: if price retests a mirror level, bounces,
        then closes back beyond the level → INVALIDATED.

        Specifically: after mirror confirmation, if price touches the level,
        moves away (bounce), then a subsequent bar closes on the breakout side
        of the level, the mirror is invalidated.

        Returns True if level is INVALIDATED.
        """
        if level.status not in (LevelStatus.MIRROR_CANDIDATE, LevelStatus.MIRROR_CONFIRMED):
            return False

        price = level.price
        tol = self.config.get_tolerance(price)

        if daily_index and level.ticker in daily_index:
            idx = daily_index[level.ticker]
            date_mask = idx['dates'] <= np.datetime64(current_date)
            closes = idx['closes'][date_mask]
            highs = idx['highs'][date_mask]
            lows = idx['lows'][date_mask]
        else:
            tdf = daily_df[
                (daily_df['Ticker'] == level.ticker) &
                (daily_df['Date'] <= current_date)
            ].sort_values('Date')
            closes = tdf['Close'].values
            highs = tdf['High'].values
            lows = tdf['Low'].values

        # Look at last 10 bars for the Nison pattern
        n = min(10, len(closes))
        if n < 3:
            return False

        closes = closes[-n:]
        highs = highs[-n:]
        lows = lows[-n:]

        # State machine: touch → bounce → close beyond
        touched = False
        bounced = False

        for i in range(n):
            bar_touched_level = (lows[i] - tol) <= price <= (highs[i] + tol)

            if not touched:
                if bar_touched_level:
                    touched = True
                continue

            if touched and not bounced:
                # Bounce = close back on the expected side
                if not bar_touched_level:
                    bounced = True
                continue

            if touched and bounced:
                # Close beyond = invalidation
                # For a resistance-turned-mirror: close above = breakout beyond
                # For a support-turned-mirror: close below = breakout beyond
                if level.level_type == LevelType.MIRROR:
                    # Check both directions
                    if closes[i] > price + tol or closes[i] < price - tol:
                        if bar_touched_level or (closes[i] > price + tol) or (closes[i] < price - tol):
                            level.status = LevelStatus.INVALIDATED
                            return True

        return False

    def update_mirror_status(self, level: Level, daily_df: pd.DataFrame,
                             current_date: pd.Timestamp,
                             daily_index: dict = None) -> None:
        """Update mirror lifecycle: ACTIVE → BROKEN → MIRROR_CANDIDATE → MIRROR_CONFIRMED.

        BROKEN: price has decisively moved beyond the level (>= mirror_atr_distance × ATR).
        MIRROR_CANDIDATE: price stayed beyond for >= mirror_days_beyond days.
        MIRROR_CONFIRMED: price returned to touch the level after being a candidate.
        """
        if level.status == LevelStatus.MIRROR_CONFIRMED:
            return
        if level.status == LevelStatus.INVALIDATED:
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
        else:
            tdf = daily_df[
                (daily_df['Ticker'] == level.ticker) &
                (daily_df['Date'] <= current_date) &
                (daily_df['Date'] > level.date)
            ]
            if tdf.empty:
                return
            highs = tdf['High'].values
            lows = tdf['Low'].values

        if len(highs) == 0:
            return

        max_dist_above = (highs - price).max()
        max_dist_below = (price - lows).max()
        max_distance = max(max_dist_above, max_dist_below)

        # ACTIVE → BROKEN: price moved beyond level significantly
        if level.status == LevelStatus.ACTIVE:
            if max_distance >= min_distance:
                level.status = LevelStatus.BROKEN
                level.mirror_max_distance_atr = max_distance / atr
            return

        # BROKEN → MIRROR_CANDIDATE: price stayed beyond for enough days
        if level.status == LevelStatus.BROKEN:
            days_beyond = int(((lows > price + tol) | (highs < price - tol)).sum())
            if days_beyond >= self.config.mirror_days_beyond:
                level.status = LevelStatus.MIRROR_CANDIDATE
                level.mirror_max_distance_atr = max_distance / atr
                level.mirror_days_beyond = days_beyond
            # Fall through to check for MIRROR_CONFIRMED too

        # MIRROR_CANDIDATE → MIRROR_CONFIRMED: price returns to touch level
        if level.status == LevelStatus.MIRROR_CANDIDATE:
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

    def get_active_levels(self, ticker: str, current_date: pd.Timestamp,
                          daily_df: pd.DataFrame,
                          daily_index: dict = None) -> list[Level]:
        """Get all active (non-invalidated) levels for a ticker on a given date.

        Enforces lookahead protection: only returns levels where
        confirmed_at <= current_date (fractal fully formed before trading).
        """
        active = []
        for level in self.levels:
            if level.ticker != ticker:
                continue
            if level.date > current_date:
                continue
            if level.status == LevelStatus.INVALIDATED:
                continue

            # Lookahead protection: fractal must be confirmed before this date
            if level.confirmed_at is not None and level.confirmed_at > current_date:
                continue

            # Update mirror status
            self.update_mirror_status(level, daily_df, current_date, daily_index)

            # Check Nison invalidation for mirror levels
            if level.status in (LevelStatus.MIRROR_CANDIDATE, LevelStatus.MIRROR_CONFIRMED):
                if self.check_nison_invalidation(level, daily_df, current_date, daily_index):
                    continue

            active.append(level)
        return active

    def process_data(self, daily_df: pd.DataFrame) -> tuple[pd.DataFrame, list[Level]]:
        """Full pipeline: daily data -> level detection.

        Expects pre-aggregated D1 data (from data_loader.aggregate_d1).
        Returns (enriched_daily_df, levels).
        """
        levels, enriched_df = self.detect_levels(daily_df)
        return enriched_df, levels
