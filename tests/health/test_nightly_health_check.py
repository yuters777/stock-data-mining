"""Tests for tools/nightly_health_check.py — press_releases category check."""
from market_engine.tools.nightly_health_check import (
    _FMP_OPTIONAL_CATEGORIES,
    _FMP_REQUIRED_CATEGORIES,
)


def test_press_releases_not_in_optional_categories() -> None:
    """press_releases must not appear in _FMP_OPTIONAL_CATEGORIES after disable."""
    assert "press_releases" not in _FMP_OPTIONAL_CATEGORIES


def test_press_releases_not_in_required_categories() -> None:
    assert "press_releases" not in _FMP_REQUIRED_CATEGORIES


def test_earnings_is_required() -> None:
    assert "earnings" in _FMP_REQUIRED_CATEGORIES
