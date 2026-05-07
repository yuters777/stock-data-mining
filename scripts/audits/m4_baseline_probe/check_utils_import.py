#!/usr/bin/env python3
"""Step 1.3 — Verify backtest_utils_extended.py exposes required utilities.

Verifies that 6 utility functions are importable and callable.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

REQUIRED_UTILITIES = [
    "load_extended_data",
    "build_4h_extended",
    "compute_indicators",
    "load_vix_daily",
    "load_earnings",
    "is_earnings_window",
]


def check_utils_import() -> dict:
    results = {}
    try:
        import scripts.backtest_utils_extended as bue
        for name in REQUIRED_UTILITIES:
            obj = getattr(bue, name, None)
            results[name] = callable(obj)
    except Exception as e:
        for name in REQUIRED_UTILITIES:
            results[name] = False
        results["_import_error"] = str(e)
    return results


def main() -> int:
    results = check_utils_import()
    errors = [k for k, v in results.items() if not v and not k.startswith("_")]
    ok = len(REQUIRED_UTILITIES) - len(errors)
    print(f"{ok}/{len(REQUIRED_UTILITIES)} utilities importable and callable")
    if errors:
        print(f"FAILED: {errors}")
    if "_import_error" in results:
        print(f"Import error: {results['_import_error']}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
