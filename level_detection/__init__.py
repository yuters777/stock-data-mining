"""
Level Detection Module for Gerchik False Breakout Strategy.

Phase 1: BSU (Bar Setting Level) Detection
- Fractal-based level detection
- Modified ATR calculation
- Scoring system for level significance
"""

from .config import Config
from .data_aggregator import DataAggregator
from .bsu_detector import BSUDetector
from .visualizer import LevelVisualizer

__version__ = "1.0.0"
__all__ = ["Config", "DataAggregator", "BSUDetector", "LevelVisualizer"]
