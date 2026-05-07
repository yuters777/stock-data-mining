#!/usr/bin/env python3
"""Step 2.1 — Reconcile module_baselines authoritative baseline from DB snapshot.

Connects to data/snapshots/market_db_snapshot_*.db with PRAGMA query_only=ON.
Aborts if snapshot absent. Verifies baseline_n=47, baseline_pf=21.38, etc.
"""
from __future__ import annotations

import glob
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from scripts.audits.m4_baseline_probe._constants import (
    SNAPSHOTS_DIR,
    AUDITS_OUTPUT_DIR,
    CANONICAL_BASELINE_N,
    CANONICAL_BASELINE_PF,
    CANONICAL_BASELINE_WR,
    CANONICAL_BASELINE_MEAN_RETURN,
    CANONICAL_BASELINE_SHARPE,
    CANONICAL_BASELINE_LOCKED_DATE,
)

TOLERANCE = 0.005  # 0.5% relative tolerance for float comparisons


def _find_snapshot() -> Path | None:
    pattern = str(SNAPSHOTS_DIR / "market_db_snapshot_*.db")
    matches = sorted(glob.glob(pattern))
    if matches:
        return Path(matches[-1])  # most recent
    return None


def _float_match(actual: float, claimed: float, tol: float = TOLERANCE) -> bool:
    if claimed == 0:
        return abs(actual) < tol
    return abs(actual - claimed) / abs(claimed) <= tol


def audit_module_baselines(snapshot_path: Path | None = None) -> dict:
    db = snapshot_path or _find_snapshot()

    if db is None:
        return {
            "snapshot_found": False,
            "error": (
                "No market_db_snapshot_*.db found in data/snapshots/. "
                "Operator must SCP snapshot before Step 2.1 can execute. "
                "See spec §5 Step 0.1."
            ),
            "row": None,
            "all_match": False,
        }

    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA query_only = ON")
    try:
        cur = conn.execute(
            "SELECT module, module_version, baseline_n, baseline_pf, "
            "baseline_wr, baseline_mean_return, baseline_sharpe, "
            "locked_date, is_active "
            "FROM module_baselines WHERE module='M4' AND is_active=1"
        )
        rows = cur.fetchall()
    except sqlite3.OperationalError as e:
        conn.close()
        return {
            "snapshot_found": True,
            "db_path": str(db),
            "error": f"Query failed: {e}",
            "row": None,
            "all_match": False,
        }
    conn.close()

    if not rows:
        return {
            "snapshot_found": True,
            "db_path": str(db),
            "error": "No active M4 row in module_baselines",
            "row": None,
            "all_match": False,
        }

    row = rows[0]
    actual = {
        "module": row[0],
        "module_version": row[1],
        "baseline_n": row[2],
        "baseline_pf": float(row[3]),
        "baseline_wr": float(row[4]),
        "baseline_mean_return": float(row[5]),
        "baseline_sharpe": float(row[6]),
        "locked_date": row[7],
        "is_active": row[8],
    }

    checks = {
        "baseline_n": actual["baseline_n"] == CANONICAL_BASELINE_N,
        "baseline_pf": _float_match(actual["baseline_pf"], CANONICAL_BASELINE_PF),
        "baseline_wr": _float_match(actual["baseline_wr"], CANONICAL_BASELINE_WR),
        "baseline_mean_return": _float_match(actual["baseline_mean_return"], CANONICAL_BASELINE_MEAN_RETURN),
        "baseline_sharpe": _float_match(actual["baseline_sharpe"], CANONICAL_BASELINE_SHARPE),
        "locked_date": actual["locked_date"] == CANONICAL_BASELINE_LOCKED_DATE,
    }
    all_match = all(checks.values())

    return {
        "snapshot_found": True,
        "db_path": str(db),
        "row": actual,
        "checks": checks,
        "all_match": all_match,
        "claimed": {
            "baseline_n": CANONICAL_BASELINE_N,
            "baseline_pf": CANONICAL_BASELINE_PF,
            "baseline_wr": CANONICAL_BASELINE_WR,
            "baseline_mean_return": CANONICAL_BASELINE_MEAN_RETURN,
            "baseline_sharpe": CANONICAL_BASELINE_SHARPE,
            "locked_date": CANONICAL_BASELINE_LOCKED_DATE,
        },
    }


def main() -> int:
    result = audit_module_baselines()
    AUDITS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = AUDITS_OUTPUT_DIR / "m4_baseline_probe_S304_db_baseline.json"
    out.write_text(json.dumps(result, indent=2))

    if not result["snapshot_found"]:
        print(f"ABORT: {result['error']}")
        return 1

    if "error" in result:
        print(f"ERROR: {result['error']}")
        return 1

    row = result["row"]
    checks = result["checks"]
    print(f"DB: {result['db_path']}")
    print(f"baseline_n={row['baseline_n']} (claimed {CANONICAL_BASELINE_N}) [{_ok(checks['baseline_n'])}]")
    print(f"baseline_pf={row['baseline_pf']:.4f} (claimed {CANONICAL_BASELINE_PF}) [{_ok(checks['baseline_pf'])}]")
    print(f"locked_date={row['locked_date']} [{_ok(checks['locked_date'])}]")

    if result["all_match"]:
        print("All baseline fields match claimed values.")
        return 0
    else:
        failed = [k for k, v in checks.items() if not v]
        print(f"ABORT P0: baseline field mismatch for: {failed}")
        return 1


def _ok(v: bool) -> str:
    return "OK" if v else "FAIL"


if __name__ == "__main__":
    sys.exit(main())
