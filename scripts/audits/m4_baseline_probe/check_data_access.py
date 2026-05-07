#!/usr/bin/env python3
"""Step 1.2 — Verify 5yr extended M5 dataset accessibility for 27 canonical tickers.

Checks that {TICKER}_m5_extended.csv exists and is readable under FETCHED_DATA_DIR.
Outputs a summary; non-zero exit if any ticker is missing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from scripts.audits.m4_baseline_probe._constants import (
    CANONICAL_UNIVERSE,
    FETCHED_DATA_DIR,
    AUDITS_OUTPUT_DIR,
)


def check_data_access(data_dir: Path | None = None) -> dict:
    base = data_dir or FETCHED_DATA_DIR

    present, missing = [], []
    for ticker in CANONICAL_UNIVERSE:
        path = base / f"{ticker}_m5_extended.csv"
        if path.exists() and path.stat().st_size > 0:
            present.append(ticker)
        else:
            missing.append(ticker)

    result = {
        "total": len(CANONICAL_UNIVERSE),
        "accessible": len(present),
        "missing": missing,
        "present": present,
        "all_accessible": len(missing) == 0,
        "data_dir": str(base),
    }
    return result


def main() -> int:
    result = check_data_access()
    accessible = result["accessible"]
    total = result["total"]
    missing = result["missing"]

    print(f"{accessible}/{total} tickers accessible in {result['data_dir']}")
    if missing:
        print(f"MISSING: {missing}")

    AUDITS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = AUDITS_OUTPUT_DIR / "m4_baseline_probe_S304_data_access.json"
    out.write_text(json.dumps(result, indent=2))

    if missing:
        print(f"WARNING: {len(missing)} tickers missing. Probe will run on available data.")
        print("NOTE: Step 1.2 abort_if triggered — data prerequisite for full probe not met.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
