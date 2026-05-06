"""Tests for canonical data loader (HARN-1.1 mini-patch).
Closes HARN-D-7/8/9 from Backtest Harness v1.0 Day 43 ship."""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts._production_mirror._data_paths import (
    load_vix,
    load_earnings,
    load_m5_bars,
    m5_bars_path,
    VIX_CANONICAL_PATH,
    VIX_REJECTED_PATHS,
    EARNINGS_CSV_PATH,
    EARNINGS_JSON_PATH,
)


def test_load_vix_canonical_returns_correct_schema():
    """Canonical VIX_daily.csv must load with schema {date, vix_close} and >100 rows."""
    df = load_vix()
    assert "date" in df.columns
    assert "vix_close" in df.columns
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    assert pd.api.types.is_numeric_dtype(df["vix_close"])
    assert len(df) > 100, f"Expected >100 rows, got {len(df)}"
    # Sanity: VIX values in plausible range 5-100
    assert df["vix_close"].min() >= 5.0
    assert df["vix_close"].max() <= 100.0


def test_load_vix_rejects_vxvcls_explicitly(tmp_path):
    """Loader MUST refuse VXVCLS.csv even if explicitly passed as path.

    This is a hard guard against the Day 43-47 silent semantic drift incident
    where loader read VIX3M as VIX, breaking M4 N=4 vs canonical N=47.
    """
    vxvcls_path = VIX_REJECTED_PATHS[0]  # canonical VXVCLS.csv path
    with pytest.raises(ValueError) as exc_info:
        load_vix(path=vxvcls_path)
    err_msg = str(exc_info.value)
    assert "VIX3M" in err_msg
    assert "VIXCLS" in err_msg
    # Must reference Day 43 incident for documentation trail
    assert "M4 N=4" in err_msg


def test_load_earnings_handles_json_format():
    """Earnings JSON [{symbol, date}, ...] must normalize to {ticker, earnings_date}."""
    df = load_earnings()
    assert "ticker" in df.columns
    assert "earnings_date" in df.columns
    assert pd.api.types.is_datetime64_any_dtype(df["earnings_date"])
    # Sanity: at least 27 tickers' worth of earnings (5yr × ~4/yr × 27 = ~540+)
    assert df["ticker"].nunique() >= 20


def test_load_earnings_prefers_csv_over_json(tmp_path, monkeypatch):
    """If both CSV and JSON exist, CSV takes precedence (legacy compatibility)."""
    # Create temp data dir
    data_dir = tmp_path / "Fetched_Data"
    data_dir.mkdir()

    csv_path = data_dir / "earnings_calendar.csv"
    json_path = data_dir / "earnings_calendar.json"

    pd.DataFrame({"ticker": ["TEST"], "earnings_date": ["2025-01-15"]}).to_csv(csv_path, index=False)
    json_path.write_text(json.dumps([{"symbol": "OTHER", "date": "2025-06-01"}]))

    monkeypatch.setattr("scripts._production_mirror._data_paths.EARNINGS_CSV_PATH", csv_path)
    monkeypatch.setattr("scripts._production_mirror._data_paths.EARNINGS_JSON_PATH", json_path)

    df = load_earnings()
    assert "TEST" in df["ticker"].values  # CSV won, not JSON's "OTHER"


def test_load_m5_bars_uses_data_csv_naming():
    """Per HARN-D-7, M5 bars use `{TICKER}_data.csv` not `_m5_extended.csv`."""
    # Pick any canonical ticker
    path = m5_bars_path("AAPL")
    assert path.name == "AAPL_data.csv"

    if path.exists():
        df = load_m5_bars("AAPL")
        expected_cols = {"date", "open", "high", "low", "close", "volume"}
        assert expected_cols.issubset(set(df.columns))


def test_load_vix_raises_filenotfound_with_helpful_message(tmp_path, monkeypatch):
    """If canonical VIX file missing, error message must include curl command."""
    fake_path = tmp_path / "nonexistent_VIX.csv"
    monkeypatch.setattr("scripts._production_mirror._data_paths.VIX_CANONICAL_PATH", fake_path)

    with pytest.raises(FileNotFoundError) as exc_info:
        load_vix()
    err_msg = str(exc_info.value)
    assert "VIXCLS" in err_msg
    assert "fred.stlouisfed.org" in err_msg
