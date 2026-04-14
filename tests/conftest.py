"""Shared test fixtures for XVAL tests."""

import sys
from pathlib import Path

# Add src to path so market_engine is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
