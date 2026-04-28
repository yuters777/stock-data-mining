"""Tests for scripts/_earnings_filter.py — synthetic data only."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts._earnings_filter import is_in_earnings_window


@pytest.fixture
def earnings_df():
    return pd.DataFrame({
        "ticker": ["AAPL", "AAPL", "MSFT"],
        "earnings_date": pd.to_datetime(["2025-01-30", "2025-04-30", "2025-04-25"]),
    })


def test_buffer_zero_no_filter(earnings_df):
    """buffer_days=0 means no filter — always False even on exact earnings date."""
    assert is_in_earnings_window("AAPL", "2025-04-30", 0, earnings_df) is False


def test_exact_date_match_buffer_1(earnings_df):
    assert is_in_earnings_window("AAPL", "2025-04-30", 1, earnings_df) is True


def test_within_buffer_5d(earnings_df):
    # 2025-04-25 is 5 days before 2025-04-30; buffer=5 covers it
    assert is_in_earnings_window("AAPL", "2025-04-25", 5, earnings_df) is True


def test_outside_buffer_3d(earnings_df):
    # 5-day gap NOT covered by ±3d buffer
    assert is_in_earnings_window("AAPL", "2025-04-25", 3, earnings_df) is False


def test_different_ticker(earnings_df):
    # GOOGL has no earnings in the fixture
    assert is_in_earnings_window("GOOGL", "2025-04-30", 10, earnings_df) is False
