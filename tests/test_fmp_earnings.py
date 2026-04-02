"""Tests for FMP earnings fetcher surprise calculations and output format."""

import csv
import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.fmp_earnings_fetcher import (
    AMC_TICKERS,
    BMO_TICKERS,
    CSV_COLUMNS,
    EQUITY_TICKERS,
    compute_eps_surprise,
    compute_revenue_surprise,
    get_time_of_day,
    _parse_fmp_row,
    _save_csv,
    _CSV_PATH,
)


class TestComputeSurpriseNormal:
    def test_positive_surprise(self):
        # Beat by 20%: actual=1.20, estimated=1.00
        result = compute_eps_surprise(1.20, 1.00)
        assert result == 20.0

    def test_negative_surprise(self):
        # Missed by 10%: actual=0.90, estimated=1.00
        result = compute_eps_surprise(0.90, 1.00)
        assert result == -10.0

    def test_revenue_surprise(self):
        # Revenue beat 5%: actual=10.5B, estimated=10.0B
        result = compute_revenue_surprise(10.5e9, 10.0e9)
        assert result == 5.0

    def test_negative_estimate_uses_abs(self):
        # EPS: actual=-0.50, estimated=-1.00 → surprise = (-0.50 - (-1.00)) / abs(-1.00) = 50%
        result = compute_eps_surprise(-0.50, -1.00)
        assert result == 50.0

    def test_small_values(self):
        result = compute_eps_surprise(0.01, 0.02)
        assert result == -50.0


class TestComputeSurpriseNull:
    def test_actual_none(self):
        assert compute_eps_surprise(None, 1.00) is None

    def test_estimated_none(self):
        assert compute_eps_surprise(1.00, None) is None

    def test_both_none(self):
        assert compute_eps_surprise(None, None) is None

    def test_revenue_actual_none(self):
        assert compute_revenue_surprise(None, 10e9) is None

    def test_revenue_estimated_none(self):
        assert compute_revenue_surprise(10e9, None) is None


class TestComputeSurpriseZeroEstimate:
    def test_eps_zero_estimate(self):
        assert compute_eps_surprise(0.50, 0) is None

    def test_eps_zero_estimate_float(self):
        assert compute_eps_surprise(0.50, 0.0) is None

    def test_revenue_zero_estimate(self):
        assert compute_revenue_surprise(1e9, 0) is None

    def test_revenue_zero_estimate_float(self):
        assert compute_revenue_surprise(1e9, 0.0) is None


class TestCsvOutputFormat:
    def test_columns_match(self):
        expected = [
            "ticker", "earnings_date", "time_of_day", "eps_estimated",
            "eps_actual", "eps_surprise_pct", "revenue_estimated",
            "revenue_actual", "revenue_surprise_pct", "source",
        ]
        assert CSV_COLUMNS == expected

    def test_parse_fmp_row_complete(self):
        fmp_row = {
            "symbol": "AAPL",
            "date": "2025-01-30",
            "epsActual": 2.40,
            "epsEstimated": 2.35,
            "revenueActual": 124e9,
            "revenueEstimated": 119e9,
        }
        result = _parse_fmp_row(fmp_row)
        assert result["ticker"] == "AAPL"
        assert result["earnings_date"] == "2025-01-30"
        assert result["time_of_day"] == "AMC"
        assert result["eps_actual"] == 2.40
        assert result["eps_estimated"] == 2.35
        assert result["source"] == "fmp"
        assert result["eps_surprise_pct"] is not None
        assert result["revenue_surprise_pct"] is not None

    def test_parse_fmp_row_missing_fields(self):
        fmp_row = {
            "symbol": "AAPL",
            "date": "2026-04-30",
            "epsActual": None,
            "epsEstimated": 2.50,
            "revenueActual": None,
            "revenueEstimated": None,
        }
        result = _parse_fmp_row(fmp_row)
        assert result["eps_actual"] is None
        assert result["eps_surprise_pct"] is None
        assert result["revenue_surprise_pct"] is None

    def test_save_csv_creates_valid_file(self, tmp_path):
        rows = [
            {
                "ticker": "AAPL", "earnings_date": "2025-01-30",
                "time_of_day": "AMC", "eps_estimated": 2.35,
                "eps_actual": 2.40, "eps_surprise_pct": 2.1277,
                "revenue_estimated": 119e9, "revenue_actual": 124e9,
                "revenue_surprise_pct": 4.2017, "source": "fmp",
            },
            {
                "ticker": "AAPL", "earnings_date": "2025-05-01",
                "time_of_day": "AMC", "eps_estimated": 1.60,
                "eps_actual": 1.65, "eps_surprise_pct": 3.125,
                "revenue_estimated": 95e9, "revenue_actual": 95.4e9,
                "revenue_surprise_pct": 0.4211, "source": "fmp",
            },
        ]
        # Patch the CSV path to use tmp dir
        csv_path = tmp_path / "fmp_earnings.csv"
        with patch("utils.fmp_earnings_fetcher._CSV_PATH", csv_path), \
             patch("utils.fmp_earnings_fetcher._DATA_DIR", tmp_path):
            _save_csv(rows)

        assert csv_path.exists()
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            loaded = list(reader)
        assert len(loaded) == 2
        assert set(loaded[0].keys()) == set(CSV_COLUMNS)


class TestBmoAmcLookupCoverage:
    def test_all_equity_tickers_classified(self):
        """Every equity ticker should be AMC, BMO, or Unknown."""
        for ticker in EQUITY_TICKERS:
            tod = get_time_of_day(ticker)
            assert tod in ("AMC", "BMO", "Unknown"), f"{ticker} has no classification: {tod}"

    def test_amc_tickers_not_in_bmo(self):
        assert AMC_TICKERS.isdisjoint(BMO_TICKERS), "Overlap between AMC and BMO"

    def test_known_amc(self):
        for t in ["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA", "META"]:
            assert get_time_of_day(t) == "AMC", f"{t} should be AMC"

    def test_known_bmo(self):
        for t in ["JPM", "GS", "C", "BA", "BABA", "BIDU"]:
            assert get_time_of_day(t) == "BMO", f"{t} should be BMO"

    def test_coverage_count(self):
        classified = sum(1 for t in EQUITY_TICKERS if get_time_of_day(t) != "Unknown")
        # At least 25 of 26 should be classified
        assert classified >= 25, f"Only {classified}/26 tickers classified"
