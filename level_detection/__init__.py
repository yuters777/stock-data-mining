"""
Level Detection Module for Gerchik False Breakout Strategy.

Phase 1: BSU (Bar Setting Level) Detection
- Fractal-based level detection
- Modified ATR calculation
- Scoring system for level significance
- MarketPatterns-AI data integration
- TradingView serialization
- Earnings calendar filtering
"""

from .config import Config
from .data_aggregator import DataAggregator
from .bsu_detector import BSUDetector
from .visualizer import LevelVisualizer
from .tradingview_serializer import TradingViewSerializer
from .earnings_filter import EarningsFilter, EarningsCheckResult
from .market_data_fetcher import MarketDataFetcher
from .batch_processor import BatchProcessor

__version__ = "1.1.0"
__all__ = [
    "Config",
    "DataAggregator",
    "BSUDetector",
    "LevelVisualizer",
    "TradingViewSerializer",
    "EarningsFilter",
    "EarningsCheckResult",
    "MarketDataFetcher",
    "BatchProcessor",
]
