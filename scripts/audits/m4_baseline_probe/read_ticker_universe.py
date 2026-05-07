#!/usr/bin/env python3
"""Step 1.6 — Read canonical 27-ticker universe from tickers.py snapshot.

Falls back to hardcoded CANONICAL_UNIVERSE if snapshot absent.
Outputs JSON to audits/output/m4_baseline_probe_S304_ticker_universe.json.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from scripts.audits.m4_baseline_probe._constants import (
    CANONICAL_UNIVERSE,
    SNAPSHOTS_DIR,
    TICKERS_SNAPSHOT_NAME,
    AUDITS_OUTPUT_DIR,
)

EXCLUDED = {"SPY", "VIXY", "BTC", "ETH", "IBIT", "SNOW", "TXN", "VIX"}


def _parse_tickers_from_source(text: str) -> list[str]:
    """Extract ticker symbols from Python source (string literals in lists)."""
    tickers = re.findall(r'"([A-Z]{1,6})"', text)
    seen, result = set(), []
    for t in tickers:
        if t not in EXCLUDED and t not in seen:
            seen.add(t)
            result.append(t)
    return result


def read_ticker_universe() -> dict:
    snapshot_path = SNAPSHOTS_DIR / TICKERS_SNAPSHOT_NAME
    if snapshot_path.exists():
        text = snapshot_path.read_text(encoding="utf-8", errors="replace")
        parsed = _parse_tickers_from_source(text)
        source = str(snapshot_path)
    else:
        parsed = list(CANONICAL_UNIVERSE)
        source = "hardcoded CANONICAL_UNIVERSE (snapshot absent)"

    matches_canonical = set(parsed) == set(CANONICAL_UNIVERSE)
    extra = sorted(set(parsed) - set(CANONICAL_UNIVERSE))
    missing = sorted(set(CANONICAL_UNIVERSE) - set(parsed))

    return {
        "source": source,
        "tickers": parsed,
        "count": len(parsed),
        "matches_canonical_27": matches_canonical,
        "extra_vs_canonical": extra,
        "missing_vs_canonical": missing,
    }


def main() -> int:
    result = read_ticker_universe()
    AUDITS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = AUDITS_OUTPUT_DIR / "m4_baseline_probe_S304_ticker_universe.json"
    out.write_text(json.dumps(result, indent=2))

    print(f"Universe: {result['count']} tickers from {result['source']}")
    print(f"Matches canonical 27: {result['matches_canonical_27']}")
    if result["extra_vs_canonical"]:
        print(f"Extra: {result['extra_vs_canonical']}")
    if result["missing_vs_canonical"]:
        print(f"Missing: {result['missing_vs_canonical']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
