"""
BSU (Bar Setting Level) Detector Module.

Implements fractal-based level detection with scoring system
based on Gerchik False Breakout Strategy Specification v3.4, Section 2.1-2.6.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

from .config import Config, DEFAULT_CONFIG


class LevelType(Enum):
    """Type of price level."""

    RESISTANCE = "R"
    SUPPORT = "S"
    MIRROR = "M"  # Acts as both support and resistance


@dataclass
class Level:
    """Represents a detected price level."""

    date: pd.Timestamp
    ticker: str
    price: float
    level_type: LevelType
    score: int
    bsu_index: int
    atr: float
    is_paranormal: bool = False
    touches: int = 1
    is_round_number: bool = False
    is_mirror: bool = False


class BSUDetector:
    """
    Detects Bar Setting Levels (BSU) using fractal analysis.

    Fractal model:
    - Resistance: H[i] > MAX(H[i-k]...H[i-1]) AND H[i] > MAX(H[i+1]...H[i+k])
    - Support: L[i] < MIN(L[i-k]...L[i-1]) AND L[i] < MIN(L[i+1]...L[i+k])

    where k = FRACTAL_DEPTH_D1
    """

    def __init__(self, config: Config = DEFAULT_CONFIG):
        """
        Initialize BSU Detector with configuration.

        Args:
            config: Configuration parameters
        """
        self.config = config

    def detect_fractals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Detect fractal highs (resistance) and lows (support).

        Excludes first and last k bars due to edge effects.

        Args:
            df: DataFrame with OHLCV data for a single ticker

        Returns:
            DataFrame with fractal detection columns added
        """
        df = df.copy()
        k = self.config.FRACTAL_DEPTH_D1

        df["IsFractalHigh"] = False
        df["IsFractalLow"] = False

        if len(df) < 2 * k + 1:
            return df

        # Process each bar (excluding first/last k bars)
        for i in range(k, len(df) - k):
            # Get window indices
            left_start = i - k
            left_end = i
            right_start = i + 1
            right_end = i + k + 1

            # Current bar values
            current_high = df.iloc[i]["High"]
            current_low = df.iloc[i]["Low"]

            # Left window (before current bar)
            left_highs = df.iloc[left_start:left_end]["High"].values
            left_lows = df.iloc[left_start:left_end]["Low"].values

            # Right window (after current bar)
            right_highs = df.iloc[right_start:right_end]["High"].values
            right_lows = df.iloc[right_start:right_end]["Low"].values

            # Fractal High (Resistance): H[i] > max of left AND > max of right
            if current_high > np.max(left_highs) and current_high > np.max(right_highs):
                df.iloc[i, df.columns.get_loc("IsFractalHigh")] = True

            # Fractal Low (Support): L[i] < min of left AND < min of right
            if current_low < np.min(left_lows) and current_low < np.min(right_lows):
                df.iloc[i, df.columns.get_loc("IsFractalLow")] = True

        return df

    def _is_round_number(self, price: float) -> bool:
        """
        Check if price is a round number (.00 or .50).

        Args:
            price: Price to check

        Returns:
            True if price ends in .00 or .50
        """
        decimal_part = abs(price) % 1
        tolerance = 0.01  # Allow small deviation

        is_full = abs(decimal_part) < tolerance or abs(decimal_part - 1.0) < tolerance
        is_half = abs(decimal_part - 0.5) < tolerance

        return is_full or is_half

    def _calculate_touch_score(
        self, df: pd.DataFrame, level_price: float, level_idx: int
    ) -> int:
        """
        Count "penny-to-penny" touches at a level.

        Args:
            df: DataFrame with OHLCV data
            level_price: Price level to check
            level_idx: Index of the level bar

        Returns:
            Number of touches within tolerance
        """
        tolerance = self.config.get_tolerance(level_price)
        touches = 0

        for i in range(len(df)):
            if i == level_idx:
                continue

            high = df.iloc[i]["High"]
            low = df.iloc[i]["Low"]

            # Check if bar touches the level
            if low - tolerance <= level_price <= high + tolerance:
                touches += 1

        return touches

    def _check_mirror_level(
        self, df: pd.DataFrame, level_price: float, level_idx: int
    ) -> bool:
        """
        Check if level acts as both support and resistance (mirror level).

        Args:
            df: DataFrame with OHLCV data
            level_price: Price level to check
            level_idx: Index of the level bar

        Returns:
            True if level acts as both support and resistance
        """
        tolerance = self.config.get_tolerance(level_price)
        acted_as_support = False
        acted_as_resistance = False

        for i in range(len(df)):
            if i == level_idx:
                continue

            close = df.iloc[i]["Close"]
            high = df.iloc[i]["High"]
            low = df.iloc[i]["Low"]

            # Level acted as support: price bounced up from level
            if abs(low - level_price) <= tolerance and close > level_price:
                acted_as_support = True

            # Level acted as resistance: price bounced down from level
            if abs(high - level_price) <= tolerance and close < level_price:
                acted_as_resistance = True

            if acted_as_support and acted_as_resistance:
                return True

        return False

    def _calculate_duration_score(
        self, df: pd.DataFrame, level_idx: int, level_price: float
    ) -> int:
        """
        Calculate score based on level duration/significance.

        Args:
            df: DataFrame with OHLCV data
            level_idx: Index of the level bar
            level_price: Price level

        Returns:
            Duration-based score component
        """
        tolerance = self.config.get_tolerance(level_price)
        duration_bars = 0

        # Count how many bars the level remained valid
        for i in range(level_idx + 1, len(df)):
            close = df.iloc[i]["Close"]
            # Level is still valid if close is near the level
            if abs(close - level_price) <= tolerance * 5:  # Wider tolerance for duration
                duration_bars += 1
            else:
                break

        # Return score based on duration thresholds
        if duration_bars >= 10:
            return self.config.SCORE_DURATION
        elif duration_bars >= 5:
            return self.config.SCORE_DURATION - 2
        return 0

    def calculate_level_score(
        self,
        df: pd.DataFrame,
        level_price: float,
        level_idx: int,
        is_paranormal: bool = False,
    ) -> tuple[int, dict]:
        """
        Calculate total score for a level based on scoring criteria.

        Scoring (Table 2.6):
        - Mirror level: 10
        - Penny-to-penny touches (3+): 9
        - Paranormal bar: 8
        - Duration: 7
        - Round numbers (.00, .50): 6

        Args:
            df: DataFrame with OHLCV data
            level_price: Price level
            level_idx: Index of the level bar
            is_paranormal: Whether bar is paranormal

        Returns:
            Tuple of (total_score, score_breakdown_dict)
        """
        score = 0
        breakdown = {
            "mirror": 0,
            "penny_touches": 0,
            "paranormal": 0,
            "duration": 0,
            "round_number": 0,
        }

        # Check mirror level
        if self._check_mirror_level(df, level_price, level_idx):
            score += self.config.SCORE_MIRROR
            breakdown["mirror"] = self.config.SCORE_MIRROR

        # Check penny-to-penny touches
        touches = self._calculate_touch_score(df, level_price, level_idx)
        if touches >= self.config.MIN_TOUCHES_PENNY:
            score += self.config.SCORE_PENNY_TOUCHES
            breakdown["penny_touches"] = self.config.SCORE_PENNY_TOUCHES

        # Check paranormal bar
        if is_paranormal:
            score += self.config.SCORE_PARANORMAL
            breakdown["paranormal"] = self.config.SCORE_PARANORMAL

        # Check duration
        duration_score = self._calculate_duration_score(df, level_idx, level_price)
        score += duration_score
        breakdown["duration"] = duration_score

        # Check round numbers
        if self._is_round_number(level_price):
            score += self.config.SCORE_ROUND_NUMBER
            breakdown["round_number"] = self.config.SCORE_ROUND_NUMBER

        return score, breakdown

    def detect_levels(self, df: pd.DataFrame, ticker: str) -> List[Level]:
        """
        Detect all BSU levels for a ticker.

        Args:
            df: DataFrame with OHLCV and ATR data for a single ticker
            ticker: Ticker symbol

        Returns:
            List of detected Level objects
        """
        # Detect fractals
        df = self.detect_fractals(df)
        levels = []

        for i in range(len(df)):
            row = df.iloc[i]

            # Check for resistance level (fractal high)
            if row["IsFractalHigh"]:
                level_price = row["High"]
                is_paranormal = row.get("IsParanormal", False)
                atr = row.get("ModifiedATR", row.get("ATR", np.nan))

                score, _ = self.calculate_level_score(
                    df, level_price, i, is_paranormal
                )

                if score >= self.config.MIN_LEVEL_SCORE:
                    # Check if also a mirror level
                    is_mirror = self._check_mirror_level(df, level_price, i)
                    level_type = LevelType.MIRROR if is_mirror else LevelType.RESISTANCE

                    level = Level(
                        date=row["Date"],
                        ticker=ticker,
                        price=level_price,
                        level_type=level_type,
                        score=score,
                        bsu_index=i,
                        atr=atr if pd.notna(atr) else 0.0,
                        is_paranormal=is_paranormal,
                        touches=self._calculate_touch_score(df, level_price, i),
                        is_round_number=self._is_round_number(level_price),
                        is_mirror=is_mirror,
                    )
                    levels.append(level)

            # Check for support level (fractal low)
            if row["IsFractalLow"]:
                level_price = row["Low"]
                is_paranormal = row.get("IsParanormal", False)
                atr = row.get("ModifiedATR", row.get("ATR", np.nan))

                score, _ = self.calculate_level_score(
                    df, level_price, i, is_paranormal
                )

                if score >= self.config.MIN_LEVEL_SCORE:
                    # Check if also a mirror level
                    is_mirror = self._check_mirror_level(df, level_price, i)
                    level_type = LevelType.MIRROR if is_mirror else LevelType.SUPPORT

                    level = Level(
                        date=row["Date"],
                        ticker=ticker,
                        price=level_price,
                        level_type=level_type,
                        score=score,
                        bsu_index=i,
                        atr=atr if pd.notna(atr) else 0.0,
                        is_paranormal=is_paranormal,
                        touches=self._calculate_touch_score(df, level_price, i),
                        is_round_number=self._is_round_number(level_price),
                        is_mirror=is_mirror,
                    )
                    levels.append(level)

        return levels

    def detect_all_tickers(
        self, df: pd.DataFrame
    ) -> tuple[List[Level], pd.DataFrame]:
        """
        Detect levels for all tickers in the dataset.

        Args:
            df: DataFrame with OHLCV and ATR data for all tickers

        Returns:
            Tuple of (list of Level objects, results DataFrame)
        """
        all_levels = []

        for ticker in df["Ticker"].unique():
            ticker_df = df[df["Ticker"] == ticker].copy().reset_index(drop=True)
            levels = self.detect_levels(ticker_df, ticker)
            all_levels.extend(levels)

        # Convert to DataFrame
        results_df = self.levels_to_dataframe(all_levels)

        return all_levels, results_df

    def levels_to_dataframe(self, levels: List[Level]) -> pd.DataFrame:
        """
        Convert list of Level objects to DataFrame.

        Args:
            levels: List of Level objects

        Returns:
            DataFrame with level information
        """
        if not levels:
            return pd.DataFrame(columns=[
                "Date", "Ticker", "Price", "Type", "Score",
                "BSU_Index", "ATR", "IsParanormal", "Touches",
                "IsRoundNumber", "IsMirror"
            ])

        data = []
        for level in levels:
            data.append({
                "Date": level.date,
                "Ticker": level.ticker,
                "Price": level.price,
                "Type": level.level_type.value,
                "Score": level.score,
                "BSU_Index": level.bsu_index,
                "ATR": level.atr,
                "IsParanormal": level.is_paranormal,
                "Touches": level.touches,
                "IsRoundNumber": level.is_round_number,
                "IsMirror": level.is_mirror,
            })

        df = pd.DataFrame(data)
        df = df.sort_values(["Ticker", "Date", "Score"], ascending=[True, True, False])
        df = df.reset_index(drop=True)

        return df

    def save_levels(
        self, levels_df: pd.DataFrame, output_path: Optional[Path] = None
    ) -> Path:
        """
        Save detected levels to CSV file.

        Args:
            levels_df: DataFrame with level information
            output_path: Path to output file. Uses config default if not provided.

        Returns:
            Path to saved file
        """
        path = output_path or self.config.OUTPUT_PATH
        path = Path(path)

        # Create output directory if needed
        path.parent.mkdir(parents=True, exist_ok=True)

        levels_df.to_csv(path, index=False)
        return path
