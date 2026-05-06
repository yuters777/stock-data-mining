"""Tests for scripts/_production_mirror/override_4_mirror.py.

Coverage: derive NORMAL/ELEVATED/HIGH_RISK from VIX, gap-based HIGH_RISK
promotion, build_override_history, get_override_state_at, prior-close shift.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts._production_mirror.override_4_mirror import (
    VIX_HIGH_RISK_MIN,
    VIX_NORMAL_MAX,
    build_override_history,
    derive_override_state,
    get_override_state_at,
)


# ── derive_override_state ────────────────────────────────────────────────────

def test_derive_normal_below_20():
    """VIX < 20 → NORMAL."""
    assert derive_override_state(15.0) == "NORMAL"
    assert derive_override_state(19.99) == "NORMAL"


def test_derive_elevated_between_20_and_25():
    """20 ≤ VIX < 25 without gap → ELEVATED."""
    assert derive_override_state(20.0) == "ELEVATED"
    assert derive_override_state(24.99) == "ELEVATED"


def test_derive_high_risk_at_or_above_25():
    """VIX ≥ 25 → HIGH_RISK (production Override 4.0 spec)."""
    assert derive_override_state(25.0) == "HIGH_RISK"
    assert derive_override_state(40.0) == "HIGH_RISK"


def test_derive_high_risk_from_gap_in_elevated_zone():
    """VIX 20-25 + abs(gap_pct) > 1% → HIGH_RISK (gap promotion)."""
    assert derive_override_state(22.0, gap_pct=1.5) == "HIGH_RISK"
    assert derive_override_state(22.0, gap_pct=-1.5) == "HIGH_RISK"


def test_derive_elevated_with_small_gap():
    """VIX 20-25 + gap ≤ 1% → stays ELEVATED."""
    assert derive_override_state(22.0, gap_pct=0.5) == "ELEVATED"


def test_derive_none_vix_returns_elevated():
    """None VIX → conservative ELEVATED (backtest cannot block)."""
    assert derive_override_state(None) == "ELEVATED"


# ── build_override_history ───────────────────────────────────────────────────

def _make_vix_df(values: list, start: date = date(2022, 1, 1)) -> pd.DataFrame:
    rows = []
    d = start
    for v in values:
        rows.append({"date": pd.Timestamp(d), "vix_close": v})
        d += timedelta(days=1)
    return pd.DataFrame(rows)


def test_build_override_history_prior_close_shift():
    """override_df.vix_prior_close is shifted by 1 (prior day's VIX)."""
    vix = _make_vix_df([15.0, 20.0, 28.0, 30.0])
    result = build_override_history(vix)
    # Row 0: no prior → NaN
    assert pd.isna(result.iloc[0]["vix_prior_close"])
    # Row 1: prior = 15.0
    assert result.iloc[1]["vix_prior_close"] == 15.0
    # Row 2: prior = 20.0
    assert result.iloc[2]["vix_prior_close"] == 20.0


def test_build_override_history_state_matches_prior_close():
    """Override state derived from prior day's VIX, not today's."""
    # Day 0: VIX=15, Day 1: VIX=30 → Day 1's state uses VIX=15 (prior) → NORMAL
    vix = _make_vix_df([15.0, 30.0])
    result = build_override_history(vix)
    assert result.iloc[1]["override_state"] == "NORMAL"
    # Day 2 (if existed) would use VIX=30 (prior) → HIGH_RISK


def test_build_override_history_columns():
    """Result has date_et, vix_prior_close, override_state columns."""
    vix = _make_vix_df([20.0, 25.0])
    result = build_override_history(vix)
    assert "date_et" in result.columns
    assert "vix_prior_close" in result.columns
    assert "override_state" in result.columns


# ── get_override_state_at ────────────────────────────────────────────────────

def test_get_override_state_at_returns_correct_state():
    """Lookup returns matching state for known date."""
    vix = _make_vix_df([15.0, 15.0, 30.0])
    override_df = build_override_history(vix)
    # Day 2 (index 2): prior = 15.0 → NORMAL
    d2 = date(2022, 1, 3)
    assert get_override_state_at(override_df, d2) == "NORMAL"


def test_get_override_state_at_returns_normal_for_unknown_date():
    """Unknown date returns 'NORMAL' (safe default)."""
    vix = _make_vix_df([20.0])
    override_df = build_override_history(vix)
    assert get_override_state_at(override_df, date(1990, 1, 1)) == "NORMAL"
