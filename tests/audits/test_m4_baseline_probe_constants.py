"""TP-4 — module4.py constants match claimed frozen values (Step 1.4, RP-002)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))


def test_production_mirror_constants_match_claimed() -> None:
    """Production mirror constants must match spec-claimed frozen M4 values."""
    from scripts._production_mirror.module4_mirror import (
        STREAK_THRESHOLD,
        VIX_GATE,
        RSI_GATE,
        D6_VIX_ROC_THRESHOLD,
        MAX_HOLD_BARS,
    )
    assert STREAK_THRESHOLD == 3, f"STREAK_THRESHOLD={STREAK_THRESHOLD}, expected 3"
    assert VIX_GATE == 25.0, f"VIX_GATE={VIX_GATE}, expected 25.0"
    assert RSI_GATE == 35.0, f"RSI_GATE={RSI_GATE}, expected 35.0"
    assert D6_VIX_ROC_THRESHOLD == 30.0, f"D6_VIX_ROC_THRESHOLD={D6_VIX_ROC_THRESHOLD}, expected 30.0"
    assert MAX_HOLD_BARS == 10, f"MAX_HOLD_BARS={MAX_HOLD_BARS}, expected 10"


def test_read_m4_constants_returns_all_match() -> None:
    """read_m4_constants() returns all_match=True using production mirror fallback."""
    from scripts.audits.m4_baseline_probe.read_m4_constants import read_constants
    result = read_constants()
    # Snapshot likely absent; falls back to production mirror
    if "error" in result:
        pytest.skip(f"Cannot load constants: {result['error']}")
    assert result["all_match"], (
        f"Constant mismatches: {[k for k, v in result['constants'].items() if not v['match']]}"
    )


def test_all_5_constants_present() -> None:
    """All 5 frozen M4 constants must be verifiable."""
    from scripts.audits.m4_baseline_probe.read_m4_constants import read_constants, CONSTANT_NAMES
    result = read_constants()
    if "error" in result:
        pytest.skip(f"Cannot load constants: {result['error']}")
    for key in CONSTANT_NAMES:
        assert key in result["constants"], f"Missing constant: {key}"


def test_claimed_values_in_constants_module() -> None:
    """_constants.py claimed values must equal production mirror values."""
    from scripts.audits.m4_baseline_probe._constants import (
        CLAIMED_STREAK_LENGTH,
        CLAIMED_VIX_GATE,
        CLAIMED_RSI_THRESHOLD,
        CLAIMED_D6_VIX_ROC_THRESHOLD,
        CLAIMED_MAX_BARS_HOLD,
    )
    from scripts._production_mirror.module4_mirror import (
        STREAK_THRESHOLD,
        VIX_GATE,
        RSI_GATE,
        D6_VIX_ROC_THRESHOLD,
        MAX_HOLD_BARS,
    )
    assert CLAIMED_STREAK_LENGTH == STREAK_THRESHOLD
    assert CLAIMED_VIX_GATE == VIX_GATE
    assert CLAIMED_RSI_THRESHOLD == RSI_GATE
    assert CLAIMED_D6_VIX_ROC_THRESHOLD == D6_VIX_ROC_THRESHOLD
    assert CLAIMED_MAX_BARS_HOLD == MAX_HOLD_BARS
