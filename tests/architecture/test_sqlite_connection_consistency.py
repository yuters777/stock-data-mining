"""
Architecture guard: all aiosqlite.connect() call-sites must live in ALLOWED_OFFENDERS.

After Wave 5b (webhook + debug migration) the allowlist shrinks to exactly 2 entries:
  1. db/connection.py  — the helper itself (permanent)
  2. dashboard/services/db.py — read-only; needs open_db_ro helper before migration

Run: pytest tests/architecture/ -v
"""
from pathlib import Path

# ---------------------------------------------------------------------------
# §7 Allowlist — exactly 2 entries after Wave 5b
# ---------------------------------------------------------------------------

ALLOWED_OFFENDERS: set[str] = {
    "src/market_engine/db/connection.py",          # the helper itself (permanent)
    "src/market_engine/dashboard/services/db.py",  # read-only — needs open_db_ro helper
}

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"


def _scan_for_raw_connect() -> list[str]:
    """Return relative paths of any src file that calls aiosqlite.connect() outside the allowlist."""
    offenders: list[str] = []
    for pyfile in sorted(_SRC.rglob("*.py")):
        rel = str(pyfile.relative_to(_REPO_ROOT))
        if rel in ALLOWED_OFFENDERS:
            continue
        if "aiosqlite.connect" in pyfile.read_text(encoding="utf-8"):
            offenders.append(rel)
    return offenders


# ---------------------------------------------------------------------------
# Test 1 — no raw connect outside allowlist
# ---------------------------------------------------------------------------

def test_no_raw_aiosqlite_connect_outside_allowlist():
    """
    All aiosqlite.connect() calls must be inside ALLOWED_OFFENDERS.
    Wave 5b migrated: webhook/worker.py (6), webhook/app.py (1), debug/server.py (1).
    """
    offenders = _scan_for_raw_connect()
    assert not offenders, (
        f"Raw aiosqlite.connect() found in {len(offenders)} file(s) outside ALLOWED_OFFENDERS:\n"
        + "\n".join(f"  {f}" for f in offenders)
    )


# ---------------------------------------------------------------------------
# Test 2 — allowlist entries all exist (no stale paths)
# ---------------------------------------------------------------------------

def test_allowed_offenders_all_exist():
    """Every entry in ALLOWED_OFFENDERS must point to a real file."""
    missing = [rel for rel in ALLOWED_OFFENDERS if not (_REPO_ROOT / rel).exists()]
    assert not missing, (
        "ALLOWED_OFFENDERS contains non-existent paths (stale entries?):\n"
        + "\n".join(f"  {m}" for m in missing)
    )


# ---------------------------------------------------------------------------
# Test 3 — the helper itself actually contains aiosqlite.connect
# ---------------------------------------------------------------------------

def test_helper_contains_connect():
    """db/connection.py must contain aiosqlite.connect (sanity check the helper)."""
    helper = _REPO_ROOT / "src/market_engine/db/connection.py"
    assert helper.exists(), "db/connection.py missing — helper was deleted?"
    assert "aiosqlite.connect" in helper.read_text(encoding="utf-8"), (
        "db/connection.py no longer calls aiosqlite.connect — helper is broken"
    )
