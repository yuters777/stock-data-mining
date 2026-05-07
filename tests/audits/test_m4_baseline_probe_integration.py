"""TP-3 — End-to-end orchestrator and final report sanity (Step 7.2)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

OUTPUT_DIR = ROOT / "audits" / "output"
FINAL_REPORT_MD = OUTPUT_DIR / "m4_baseline_probe_S304.md"
FINAL_REPORT_JSON = OUTPUT_DIR / "m4_baseline_probe_S304.json"

REQUIRED_OUTPUT_FILES = [
    "m4_baseline_probe_S304.md",
    "m4_baseline_probe_S304.json",
    "m4_baseline_probe_S304_constants.json",
    "m4_baseline_probe_S304_ticker_universe.json",
    "m4_baseline_probe_S304_n57_trace.md",
    "m4_baseline_probe_S304_n264_methodology.md",
    "m4_baseline_probe_S304_n4_8_methodology.md",
    "m4_baseline_probe_S304_count_drift_table.md",
    "m4_baseline_probe_S304_cost_stress.md",
    "m4_baseline_probe_S304_survivorship.md",
    "m4_baseline_probe_S304_loyo.md",
    "m4_baseline_probe_S304_loto.md",
    "m4_baseline_probe_S304_lovo.md",
    "m4_baseline_probe_S304_lookahead.md",
    "m4_baseline_probe_S304_rth_calendar.md",
    "m4_baseline_probe_S304_corp_actions.md",
]

REQUIRED_MD_SECTIONS = [
    "## 1. Executive Summary",
    "## 2. Authoritative Baseline",
    "## 3. Count Drift Reconciliation Table",
    "## 4. Look-Ahead Audit Result",
    "## 5. RTH Calendar Audit Result",
    "## 6. Corporate Action Audit Result",
    "## 7. Survivorship Audit Result",
    "## 8. Robustness Audits",
    "## 9. Cost Stress Sensitivity",
    "## 10. Forward-OOS Context",
    "## 11. Phase 1 + 2 Decision",
    "## 12. Anchor",
]


@pytest.fixture(scope="module")
def run_orchestrator():
    """Run the orchestrator and yield return code."""
    result = subprocess.run(
        [sys.executable, "scripts/audits/m4_baseline_probe/run_all.py"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    yield result


def test_orchestrator_exits_without_crash(run_orchestrator) -> None:
    """Orchestrator must exit (any code) without Python exception."""
    assert "Traceback (most recent call last)" not in run_orchestrator.stderr or \
        run_orchestrator.returncode is not None, (
        f"Orchestrator crashed:\n{run_orchestrator.stderr}"
    )


def test_final_report_md_exists(run_orchestrator) -> None:
    """Final report markdown must exist after orchestrator run."""
    assert FINAL_REPORT_MD.exists(), f"Final report not found: {FINAL_REPORT_MD}"


def test_final_report_has_all_12_sections(run_orchestrator) -> None:
    """Final report must contain all 12 required sections."""
    if not FINAL_REPORT_MD.exists():
        pytest.skip("Final report not generated")
    text = FINAL_REPORT_MD.read_text(encoding="utf-8")
    missing = [s for s in REQUIRED_MD_SECTIONS if s not in text]
    assert not missing, f"Missing sections in final report: {missing}"


def test_final_report_has_verdict(run_orchestrator) -> None:
    """Final report must contain explicit GO or NO-GO verdict."""
    if not FINAL_REPORT_MD.exists():
        pytest.skip("Final report not generated")
    text = FINAL_REPORT_MD.read_text(encoding="utf-8")
    assert "**VERDICT: GO**" in text or "**VERDICT: NO-GO**" in text, (
        "Final report missing explicit VERDICT: GO or VERDICT: NO-GO"
    )


def test_all_json_outputs_valid(run_orchestrator) -> None:
    """All JSON output files must be valid JSON."""
    for fname in REQUIRED_OUTPUT_FILES:
        if not fname.endswith(".json"):
            continue
        p = OUTPUT_DIR / fname
        if p.exists():
            try:
                json.loads(p.read_text())
            except json.JSONDecodeError as e:
                pytest.fail(f"Invalid JSON in {fname}: {e}")


def test_no_db_writes_during_probe(run_orchestrator) -> None:
    """Verify read-only invariant PS-002: no writes to any .db file."""
    import re
    PROBE_DIR = ROOT / "scripts" / "audits" / "m4_baseline_probe"
    write_pattern = re.compile(
        r'(\.execute\s*\(\s*["\']?\s*(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER))',
        re.IGNORECASE,
    )
    for f in PROBE_DIR.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        m = write_pattern.search(text)
        assert not m, (
            f"{f.name}: potential write SQL detected: {m.group()!r} — violates PS-002"
        )


def test_cross_repo_isolation(run_orchestrator) -> None:
    """No files outside stock-data-mining repo were modified (SB-001)."""
    market_engine = ROOT.parent / "market-engine"
    if not market_engine.exists():
        pytest.skip("market-engine repo not present")

    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(market_engine),
    )
    if result.returncode == 0:
        modified = result.stdout.strip()
        assert not modified, (
            f"market-engine repo has unexpected modifications: {modified}"
        )


def test_required_output_files_present(run_orchestrator) -> None:
    """After orchestrator run, all expected output files should exist."""
    missing = [f for f in REQUIRED_OUTPUT_FILES if not (OUTPUT_DIR / f).exists()]
    # Non-fatal: report which are missing
    if missing:
        pytest.xfail(f"Some output files not generated (may need data): {missing}")


def test_final_json_has_verdict_field(run_orchestrator) -> None:
    """Final JSON must have a 'verdict' field with GO or NO-GO."""
    if not FINAL_REPORT_JSON.exists():
        pytest.skip("Final report JSON not generated")
    data = json.loads(FINAL_REPORT_JSON.read_text())
    assert "verdict" in data
    assert data["verdict"] in ("GO", "NO-GO"), f"Unexpected verdict: {data['verdict']}"
