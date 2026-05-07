#!/usr/bin/env python3
"""Step 1.4 — Read and validate M4 frozen constants from module4.py snapshot.

Parses data/snapshots/module4_py_9a6f7e1.txt. Falls back to reading the
production mirror's constants if snapshot is absent.
Outputs JSON to audits/output/m4_baseline_probe_S304_constants.json.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from scripts.audits.m4_baseline_probe._constants import (
    CLAIMED_STREAK_LENGTH,
    CLAIMED_VIX_GATE,
    CLAIMED_RSI_THRESHOLD,
    CLAIMED_D6_VIX_ROC_THRESHOLD,
    CLAIMED_MAX_BARS_HOLD,
    SNAPSHOTS_DIR,
    MODULE4_SNAPSHOT_NAME,
    AUDITS_OUTPUT_DIR,
)

CONSTANT_NAMES = {
    "STREAK_LENGTH": ("STREAK_LENGTH", CLAIMED_STREAK_LENGTH),
    "VIX_GATE": ("VIX_GATE", CLAIMED_VIX_GATE),
    "RSI_THRESHOLD": ("RSI_THRESHOLD", CLAIMED_RSI_THRESHOLD),
    "D6_VIX_ROC_THRESHOLD": ("D6_VIX_ROC_THRESHOLD", CLAIMED_D6_VIX_ROC_THRESHOLD),
    "MAX_BARS_HOLD": ("MAX_BARS_HOLD", CLAIMED_MAX_BARS_HOLD),
}

# Also accept production-mirror constant names
ALIAS_MAP = {
    "STREAK_THRESHOLD": "STREAK_LENGTH",
    "RSI_GATE": "RSI_THRESHOLD",
    "MAX_HOLD_BARS": "MAX_BARS_HOLD",
}


def _extract_constants(source: str) -> dict[str, Any]:
    """Extract module-level assignments using regex (tolerant of complex files)."""
    found: dict[str, Any] = {}
    pattern = re.compile(
        r'^(?P<name>[A-Z_][A-Z_0-9]*)\s*=\s*(?P<value>[^\n#]+)',
        re.MULTILINE,
    )
    for m in pattern.finditer(source):
        name = m.group("name").strip()
        raw = m.group("value").strip()
        try:
            val = ast.literal_eval(raw)
        except Exception:
            val = raw
        found[name] = val
    return found


def read_constants(snapshot_path: Path | None = None) -> dict:
    source_label = "unknown"
    source_path = snapshot_path or (SNAPSHOTS_DIR / MODULE4_SNAPSHOT_NAME)

    if source_path.exists():
        text = source_path.read_text(encoding="utf-8", errors="replace")
        source_label = str(source_path)
    else:
        # Fall back to production mirror constants
        try:
            from scripts._production_mirror.module4_mirror import (
                STREAK_THRESHOLD, VIX_GATE, RSI_GATE,
                D6_VIX_ROC_THRESHOLD, MAX_HOLD_BARS,
            )
            text = (
                f"STREAK_THRESHOLD = {STREAK_THRESHOLD}\n"
                f"VIX_GATE = {VIX_GATE}\n"
                f"RSI_GATE = {RSI_GATE}\n"
                f"D6_VIX_ROC_THRESHOLD = {D6_VIX_ROC_THRESHOLD}\n"
                f"MAX_HOLD_BARS = {MAX_HOLD_BARS}\n"
            )
            source_label = "scripts/_production_mirror/module4_mirror.py (fallback)"
        except Exception as e:
            return {
                "error": f"Snapshot missing and fallback failed: {e}",
                "snapshot_path": str(source_path),
                "source": source_label,
                "constants": {},
                "all_match": False,
            }

    raw = _extract_constants(text)

    # Normalise alias names
    for alias, canonical in ALIAS_MAP.items():
        if alias in raw and canonical not in raw:
            raw[canonical] = raw[alias]

    results = {}
    for key, (_, claimed) in CONSTANT_NAMES.items():
        if key in raw:
            actual = raw[key]
            match = (float(actual) == float(claimed)) if isinstance(claimed, float) else (actual == claimed)
            results[key] = {"actual": actual, "claimed": claimed, "match": match}
        else:
            results[key] = {"actual": None, "claimed": claimed, "match": False, "error": "not_found"}

    all_match = all(v["match"] for v in results.values())
    return {
        "source": source_label,
        "constants": results,
        "all_match": all_match,
    }


def main() -> int:
    result = read_constants()
    AUDITS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = AUDITS_OUTPUT_DIR / "m4_baseline_probe_S304_constants.json"
    out.write_text(json.dumps(result, indent=2))

    if "error" in result:
        print(f"ERROR: {result['error']}")
        return 1

    for k, v in result["constants"].items():
        status = "OK" if v["match"] else "MISMATCH"
        print(f"  {k}: {v['actual']} (claimed {v['claimed']}) [{status}]")

    if result["all_match"]:
        print("All 5 constants match claimed values.")
    else:
        mismatches = [k for k, v in result["constants"].items() if not v["match"]]
        print(f"ABORT: constant mismatch for: {mismatches}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
