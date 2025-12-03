"""
Configuration parameters for BSU Detection.

Based on Gerchik False Breakout Strategy Specification v3.4, Section 8.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    """Configuration parameters for level detection."""

    # Fractal parameters (Section 2.1)
    FRACTAL_DEPTH_D1: int = 5  # Number of bars on each side for fractal detection

    # Tolerance for price comparison (Section 2.2)
    TOLERANCE_PERCENT: float = 0.002  # 0.2% for stocks >$100
    TOLERANCE_CENTS: float = 0.05  # $0.05 for stocks <=$100
    PRICE_THRESHOLD: float = 100.0  # Price threshold for tolerance selection

    # ATR parameters (Section 2.3)
    ATR_PERIOD: int = 5  # Modified ATR period
    PARANORMAL_MULT: float = 2.0  # Multiplier for paranormal bar detection (Range >= 2.0 × ATR)
    ATR_UPPER_MULT: float = 2.0  # Exclude bars with range > 2.0 × previous ATR
    ATR_LOWER_MULT: float = 0.5  # Exclude bars with range < 0.5 × previous ATR

    # Scoring thresholds (Section 2.6)
    MIN_LEVEL_SCORE: int = 5  # Minimum score to save a level

    # Scoring values (Table 2.6)
    SCORE_MIRROR: int = 10  # Mirror level (acts as both support and resistance)
    SCORE_PENNY_TOUCHES: int = 9  # "Penny-to-penny" touches (3+ touches)
    SCORE_PARANORMAL: int = 8  # Paranormal bar at level
    SCORE_DURATION: int = 7  # Level duration significance
    SCORE_ROUND_NUMBER: int = 6  # Round numbers (.00, .50)

    # Touch detection
    MIN_TOUCHES_PENNY: int = 3  # Minimum touches for penny-to-penny score

    # Round number thresholds
    ROUND_FULL: float = 1.0  # .00 detection
    ROUND_HALF: float = 0.5  # .50 detection

    # File paths
    DATA_PATH: Path = Path("MarketPatterns_AI/Fetched_Data/combined_sp500_all_data_5min.csv")
    OUTPUT_PATH: Path = Path("level_detection/output/levels_detected.csv")

    # Trading session hours (for filtering)
    MARKET_OPEN_HOUR: int = 9
    MARKET_OPEN_MINUTE: int = 30
    MARKET_CLOSE_HOUR: int = 16
    MARKET_CLOSE_MINUTE: int = 0

    def get_tolerance(self, price: float) -> float:
        """
        Get appropriate tolerance based on price level.

        Args:
            price: Current price level

        Returns:
            Tolerance value (percentage for >$100, cents for <=$100)
        """
        if price > self.PRICE_THRESHOLD:
            return price * self.TOLERANCE_PERCENT
        return self.TOLERANCE_CENTS


# Default configuration instance
DEFAULT_CONFIG = Config()
