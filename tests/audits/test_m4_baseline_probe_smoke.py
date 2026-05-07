"""TP-1 — Smoke tests: orchestrator and audit scripts importable, Steps 1.1-1.6."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

AUDIT_MODULES = [
    "scripts.audits.m4_baseline_probe._constants",
    "scripts.audits.m4_baseline_probe.check_data_access",
    "scripts.audits.m4_baseline_probe.check_utils_import",
    "scripts.audits.m4_baseline_probe.read_m4_constants",
    "scripts.audits.m4_baseline_probe.read_ticker_universe",
    "scripts.audits.m4_baseline_probe.audit_module_baselines",
    "scripts.audits.m4_baseline_probe.snapshot_module_decisions",
    "scripts.audits.m4_baseline_probe.locate_n57_source",
    "scripts.audits.m4_baseline_probe.reconcile_n264",
    "scripts.audits.m4_baseline_probe.reconcile_n4_8",
    "scripts.audits.m4_baseline_probe.build_count_table",
    "scripts.audits.m4_baseline_probe.audit_cost_stress",
    "scripts.audits.m4_baseline_probe.audit_survivorship",
    "scripts.audits.m4_baseline_probe.robustness_loyo",
    "scripts.audits.m4_baseline_probe.robustness_loto",
    "scripts.audits.m4_baseline_probe.robustness_lovo",
    "scripts.audits.m4_baseline_probe.audit_lookahead",
    "scripts.audits.m4_baseline_probe.audit_rth_calendar",
    "scripts.audits.m4_baseline_probe.audit_corp_actions",
    "scripts.audits.m4_baseline_probe.build_final_report",
    "scripts.audits.m4_baseline_probe.verify_count_table_attribution",
    "scripts.audits.m4_baseline_probe.run_all",
]


@pytest.mark.parametrize("module_name", AUDIT_MODULES)
def test_module_importable(module_name: str) -> None:
    mod = importlib.import_module(module_name)
    assert mod is not None


def test_orchestrator_has_main() -> None:
    mod = importlib.import_module("scripts.audits.m4_baseline_probe.run_all")
    assert callable(getattr(mod, "main", None))


def test_directory_structure_exists() -> None:
    assert (ROOT / "scripts" / "audits" / "m4_baseline_probe").is_dir()
    assert (ROOT / "tests" / "audits").is_dir()
    assert (ROOT / "audits" / "output").is_dir()
    assert (ROOT / "data" / "snapshots").is_dir()


def test_init_files_exist() -> None:
    assert (ROOT / "scripts" / "audits" / "__init__.py").exists()
    assert (ROOT / "scripts" / "audits" / "m4_baseline_probe" / "__init__.py").exists()
    assert (ROOT / "tests" / "audits" / "__init__.py").exists()


def test_constants_values() -> None:
    from scripts.audits.m4_baseline_probe._constants import (
        CANONICAL_BASELINE_N,
        CANONICAL_BASELINE_PF,
        CANONICAL_UNIVERSE,
        CLAIMED_STREAK_LENGTH,
        CLAIMED_VIX_GATE,
        CLAIMED_RSI_THRESHOLD,
        CLAIMED_D6_VIX_ROC_THRESHOLD,
        CLAIMED_MAX_BARS_HOLD,
    )
    assert CANONICAL_BASELINE_N == 47
    assert CANONICAL_BASELINE_PF == 21.38
    assert len(CANONICAL_UNIVERSE) == 27
    assert CLAIMED_STREAK_LENGTH == 3
    assert CLAIMED_VIX_GATE == 25.0
    assert CLAIMED_RSI_THRESHOLD == 35
    assert CLAIMED_D6_VIX_ROC_THRESHOLD == 30.0
    assert CLAIMED_MAX_BARS_HOLD == 10


def test_backtest_utils_importable() -> None:
    from scripts.audits.m4_baseline_probe.check_utils_import import check_utils_import
    results = check_utils_import()
    errors = [k for k, v in results.items() if not v and not k.startswith("_")]
    assert not errors, f"Utility import failures: {errors}"


def test_ticker_universe_27() -> None:
    from scripts.audits.m4_baseline_probe.read_ticker_universe import read_ticker_universe
    result = read_ticker_universe()
    assert result["count"] == 27
    assert result["matches_canonical_27"]
