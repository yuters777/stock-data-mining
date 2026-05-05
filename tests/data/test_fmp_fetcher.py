"""Tests for data/fmp_fetcher.py — press_releases disable verification."""
from pathlib import Path

from market_engine.data.fmp_fetcher import (
    _CATEGORY_FETCHERS,
    _fetch_press_releases,
    run_category_fetchers,
)


def test_press_releases_not_in_category_fetchers() -> None:
    """Spec 3 Option B: press_releases must be removed from _CATEGORY_FETCHERS."""
    assert "press_releases" not in _CATEGORY_FETCHERS, (
        "'press_releases' is still registered in _CATEGORY_FETCHERS — "
        "spec disable not applied"
    )


def test_expected_categories_present() -> None:
    """Active categories after press_releases disable."""
    expected = {"earnings", "analyst_estimates", "news", "sec_filings", "insider_trades"}
    assert expected == set(_CATEGORY_FETCHERS.keys()), (
        f"_CATEGORY_FETCHERS mismatch. Got: {set(_CATEGORY_FETCHERS.keys())}"
    )


def test_fetch_press_releases_function_still_defined() -> None:
    """_fetch_press_releases function must be preserved for future revival."""
    assert callable(_fetch_press_releases), (
        "_fetch_press_releases was deleted — must be preserved per spec"
    )


def test_fmp_fetcher_no_aiosqlite_connect() -> None:
    """fmp_fetcher.py uses open_db(), not raw aiosqlite.connect()."""
    src = Path(__file__).resolve().parents[2] / "src/market_engine/data/fmp_fetcher.py"
    assert "aiosqlite.connect" not in src.read_text()
