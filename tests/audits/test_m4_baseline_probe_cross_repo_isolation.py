"""TP-5 — No file modifications outside stock-data-mining repo working tree (SB-001)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

MARKET_ENGINE_PATH = ROOT.parent / "market-engine"
PROBE_DIR = ROOT / "scripts" / "audits" / "m4_baseline_probe"


def test_no_market_engine_imports_in_probe() -> None:
    """Probe scripts must not directly import from the market-engine repo or use sys.path to reach it."""
    import re
    # Detect sys.path manipulation pointing outside stock-data-mining
    bad_path_pattern = re.compile(r'sys\.path.*market.engine', re.IGNORECASE)
    for f in PROBE_DIR.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        if bad_path_pattern.search(text):
            pytest.fail(f"{f.name}: sys.path references market-engine repo")
        # Flag only if it appears as an actual Python path (sys.path insert, open(), import)
        bad_path = re.compile(r'(sys\.path\s*\.\s*insert|open\s*\()\s*.*market.engine', re.IGNORECASE)
        if bad_path.search(text):
            pytest.fail(f"{f.name}: Python path manipulation to market-engine repo found")


def test_probe_scripts_only_write_to_allowed_paths() -> None:
    """Probe scripts should only write to audits/output/ or temp paths."""
    import re
    write_pattern = re.compile(r'\.write_text\(|open\([^)]+["\']w["\']|json\.dump\([^)]+open')
    forbidden_dirs = ["src/", "scripts/", ".claude/", ".github/", "migrations"]
    # Allow audits/output, data/snapshots (for new files but not operator files)

    for f in PROBE_DIR.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        lines = text.splitlines()
        for i, line in enumerate(lines, 1):
            if write_pattern.search(line):
                for forbidden in forbidden_dirs:
                    # Very crude check: ensure we're not writing to production dirs
                    if f"'{forbidden}" in line or f'"{forbidden}' in line:
                        pytest.fail(
                            f"{f.name}:{i}: potential write to forbidden path '{forbidden}': {line.strip()!r}"
                        )


def test_never_touch_list_respected() -> None:
    """Key never_touch paths should not appear as write targets in probe scripts."""
    import re
    for f in PROBE_DIR.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        # These paths should never be written to
        assert ".claude/hooks" not in text, f"{f.name}: references .claude/hooks"
        assert ".claude/settings.json" not in text, f"{f.name}: references .claude/settings.json"
        assert ".github/workflows" not in text, f"{f.name}: references .github/workflows"
        assert "migrations" not in text or "migration" in f.name, (
            f"{f.name}: references migrations"
        )


def test_market_engine_repo_not_modified() -> None:
    """Market-engine repo directory (if present) has no staged/modified files from probe scripts."""
    if not MARKET_ENGINE_PATH.exists():
        pytest.skip("market-engine repo not present alongside stock-data-mining")

    import subprocess
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=str(MARKET_ENGINE_PATH),
    )
    # Any modifications would indicate cross-repo contamination
    if result.returncode == 0 and result.stdout.strip():
        # Check if any modified files match probe output patterns
        modified = result.stdout.strip().splitlines()
        probe_related = [
            line for line in modified
            if "m4_baseline_probe" in line or "S304" in line or "audits" in line
        ]
        assert not probe_related, (
            f"market-engine repo has probe-related modifications: {probe_related}"
        )


def test_probe_output_dir_is_within_repo() -> None:
    """All probe output paths resolve within the stock-data-mining repo."""
    from scripts.audits.m4_baseline_probe._constants import AUDITS_OUTPUT_DIR, SNAPSHOTS_DIR
    assert AUDITS_OUTPUT_DIR.resolve().is_relative_to(ROOT.resolve()), (
        f"AUDITS_OUTPUT_DIR {AUDITS_OUTPUT_DIR} is outside repo root {ROOT}"
    )
    assert SNAPSHOTS_DIR.resolve().is_relative_to(ROOT.resolve()), (
        f"SNAPSHOTS_DIR {SNAPSHOTS_DIR} is outside repo root {ROOT}"
    )
