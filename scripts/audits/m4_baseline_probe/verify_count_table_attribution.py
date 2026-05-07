#!/usr/bin/env python3
"""V-4 verification helper — verify count drift table has >=4 rows with full attribution."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from scripts.audits.m4_baseline_probe._constants import AUDITS_OUTPUT_DIR


def verify() -> int:
    p = AUDITS_OUTPUT_DIR / "m4_baseline_probe_S304_count_drift_table.json"
    if not p.exists():
        print(f"FAIL: {p} not found")
        return 1

    data = json.loads(p.read_text())
    entries = data.get("entries", [])

    if len(entries) < 4:
        print(f"FAIL: only {len(entries)} entries (need >= 4)")
        return 1

    unattributed = [e["label"] for e in entries if not e.get("fully_attributed")]
    if unattributed:
        print(f"FAIL: unattributed entries: {unattributed}")
        return 1

    print(f"PASS: {len(entries)} entries, all attributed")
    return 0


if __name__ == "__main__":
    sys.exit(verify())
