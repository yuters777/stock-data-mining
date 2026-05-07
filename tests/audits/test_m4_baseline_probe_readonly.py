"""TP-2 — Read-only invariant: all DB connections set PRAGMA query_only=ON.

Verifies claim PS-002 and SB-002: probe never writes to any DB file.
"""
from __future__ import annotations

import ast
import re
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
PROBE_DIR = ROOT / "scripts" / "audits" / "m4_baseline_probe"


def _get_sqlite_connect_files() -> list[Path]:
    """Return all Python files in probe dir that call sqlite3.connect."""
    result = []
    for f in PROBE_DIR.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        if "sqlite3.connect" in text:
            result.append(f)
    return result


def _has_query_only_pragma(source: str) -> bool:
    """Check that every sqlite3.connect() is followed (within 10 lines) by PRAGMA query_only."""
    lines = source.splitlines()
    for i, line in enumerate(lines):
        if "sqlite3.connect" in line:
            # Look for PRAGMA query_only in next 10 lines
            window = "\n".join(lines[i : i + 10])
            if "query_only" not in window.lower():
                return False
    return True


def _connect_targets_snapshots_only(source: str) -> bool:
    """Check that sqlite3.connect() calls only use snapshot paths."""
    connect_pattern = re.compile(r'sqlite3\.connect\(([^)]+)\)')
    for m in connect_pattern.finditer(source):
        arg = m.group(1).strip()
        # Allow: str(db), str(snapshot_path), variables containing 'db' or 'snapshot'
        # Disallow: hardcoded /var/lib/ or live paths
        if "/var/lib" in arg or "market.db" in arg.lower():
            return False
    return True


def test_no_sqlite_files_without_query_only() -> None:
    """Every file calling sqlite3.connect must set PRAGMA query_only=ON."""
    files = _get_sqlite_connect_files()
    violations = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        if not _has_query_only_pragma(text):
            violations.append(f.name)
    assert not violations, (
        f"Files with sqlite3.connect but no PRAGMA query_only=ON within 10 lines: {violations}"
    )


def test_no_hardcoded_live_db_paths() -> None:
    """Probe scripts must not use the live VPS DB path in sqlite3.connect() calls."""
    connect_with_live = re.compile(r'sqlite3\.connect\s*\([^)]*var/lib/market-system', re.DOTALL)
    for f in PROBE_DIR.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        if connect_with_live.search(text):
            pytest.fail(f"{f.name}: sqlite3.connect references live VPS path")


def test_no_write_sql() -> None:
    """No probe script should execute INSERT/UPDATE/DELETE/CREATE TABLE SQL."""
    write_pattern = re.compile(
        r'\.execute\s*\(\s*["\']?\s*'
        r'(INSERT\s+INTO|UPDATE\s+\w|DELETE\s+FROM|DROP\s+TABLE|CREATE\s+TABLE|ALTER\s+TABLE)',
        re.IGNORECASE,
    )
    for f in PROBE_DIR.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        m = write_pattern.search(text)
        if m:
            pytest.fail(f"{f.name}: write SQL in .execute() call: {m.group()!r}")


def test_snapshot_dir_used_for_db_connections() -> None:
    """DB connections in audit scripts reference snapshot paths, not live paths."""
    files = _get_sqlite_connect_files()
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert _connect_targets_snapshots_only(text), (
            f"{f.name}: sqlite3.connect references live DB path"
        )


def test_no_ssh_or_scp_in_probe_scripts() -> None:
    """Probe scripts must not invoke SSH/SCP (operator manages snapshot fetch out-of-band)."""
    ssh_pattern = re.compile(r'\b(subprocess|os\.system|paramiko)\b.*\b(ssh|scp)\b', re.IGNORECASE)
    for f in PROBE_DIR.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        if ssh_pattern.search(text):
            pytest.fail(f"{f.name}: SSH/SCP invocation found — violates SB-002")
