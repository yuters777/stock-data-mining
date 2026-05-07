#!/usr/bin/env python3
"""Step 2.2 — Snapshot module_decisions accumulated rows for M4.

Reads module_decisions table from DB snapshot (if present).
Records row counts by outcome for forward-OOS context in final report.
"""
from __future__ import annotations

import glob
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from scripts.audits.m4_baseline_probe._constants import SNAPSHOTS_DIR, AUDITS_OUTPUT_DIR
from scripts.audits.m4_baseline_probe.audit_module_baselines import _find_snapshot


def snapshot_module_decisions(snapshot_path: Path | None = None) -> dict:
    db = snapshot_path or _find_snapshot()

    if db is None:
        return {
            "snapshot_found": False,
            "note": "No snapshot present; module_decisions context unavailable.",
            "rows_by_outcome": {},
            "total_rows": 0,
        }

    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA query_only = ON")
    try:
        cur = conn.execute(
            "SELECT outcome, COUNT(*) as cnt "
            "FROM module_decisions WHERE module='M4' "
            "GROUP BY outcome ORDER BY cnt DESC"
        )
        rows = cur.fetchall()
    except sqlite3.OperationalError as e:
        conn.close()
        return {
            "snapshot_found": True,
            "db_path": str(db),
            "error": f"Query failed (table may not exist): {e}",
            "rows_by_outcome": {},
            "total_rows": 0,
        }
    conn.close()

    by_outcome = {r[0]: r[1] for r in rows}
    total = sum(by_outcome.values())

    return {
        "snapshot_found": True,
        "db_path": str(db),
        "rows_by_outcome": by_outcome,
        "total_rows": total,
        "note": f"Forward-OOS M4 decisions since PR #628 deployment.",
    }


def main() -> int:
    result = snapshot_module_decisions()
    AUDITS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = AUDITS_OUTPUT_DIR / "m4_baseline_probe_S304_module_decisions.json"
    out.write_text(json.dumps(result, indent=2))

    if not result["snapshot_found"]:
        print(f"NOTE: {result['note']}")
        return 0

    if "error" in result:
        print(f"NOTE (non-fatal): {result['error']}")
        return 0

    print(f"module_decisions M4 rows: {result['total_rows']}")
    for outcome, cnt in result["rows_by_outcome"].items():
        print(f"  {outcome}: {cnt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
