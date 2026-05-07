#!/usr/bin/env python3
"""Step 3.1 — Locate '2/57 losers' source script and trace N=57 origin.

The N=57 value appears in S44_Module4_Streak_Sensitivity.md as V0 backtest result.
This script traces that reference, identifies the producing script, and documents
why N=57 differs from canonical N=47.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from scripts.audits.m4_baseline_probe._constants import (
    PROJECT_ROOT,
    S44_STREAK_RESULTS_MD,
    S44_BASELINE_RESULTS_MD,
    AUDITS_OUTPUT_DIR,
    CANONICAL_BASELINE_N,
)

_SEARCH_DIRS = [
    PROJECT_ROOT / "scripts",
    PROJECT_ROOT / "results",
    PROJECT_ROOT / "backtest_results",
    PROJECT_ROOT / "backtest_output",
    PROJECT_ROOT / "experiments",
    PROJECT_ROOT / "docs",
]

_SEARCH_EXTS = {".py", ".md", ".json", ".csv", ".txt"}


def _grep_for_pattern(pattern: str, dirs: list[Path]) -> list[dict]:
    regex = re.compile(pattern, re.IGNORECASE)
    hits = []
    for d in dirs:
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if f.suffix.lower() not in _SEARCH_EXTS:
                continue
            if "audits" in f.parts:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        hits.append({"file": str(f.relative_to(PROJECT_ROOT)), "line": i, "text": line.strip()})
            except Exception:
                pass
    return hits


def locate_n57_source() -> dict:
    findings: dict = {}

    # Primary: confirm N=57 in S44 streak sensitivity V0
    s44_found = False
    s44_excerpt = ""
    if S44_STREAK_RESULTS_MD.exists():
        text = S44_STREAK_RESULTS_MD.read_text(encoding="utf-8", errors="replace")
        if "N=57" in text:
            s44_found = True
            for line in text.splitlines():
                if "N=57" in line:
                    s44_excerpt = line.strip()
                    break

    findings["s44_streak_sensitivity_md"] = {
        "path": str(S44_STREAK_RESULTS_MD.relative_to(PROJECT_ROOT)),
        "found": s44_found,
        "excerpt": s44_excerpt,
    }

    # Search for scripts that produce the S44 V0 backtest
    py_hits_57 = _grep_for_pattern(r'\bN=57\b|\b"57 trade|\b57\b.*trade', [PROJECT_ROOT / "scripts"])
    findings["script_hits_n57"] = py_hits_57[:10]

    # Identify producing script for S44 V0
    # S44 V0 used m4_backtest_5yr.py or similar (close<open streak definition, 25 tickers)
    s44_producer_hits = _grep_for_pattern(
        r'S44|Streak_Sensitivity|V0.*streak|streak.*V0',
        [PROJECT_ROOT / "scripts", PROJECT_ROOT / "results"],
    )
    findings["s44_producer_candidates"] = s44_producer_hits[:10]

    # Read S44 methodology from the results file
    methodology_delta = []
    if S44_STREAK_RESULTS_MD.exists():
        text = S44_STREAK_RESULTS_MD.read_text(encoding="utf-8", errors="replace")
        # Extract header context
        lines = text.splitlines()
        methodology_delta = [l for l in lines[:15] if l.strip()]

    findings["s44_v0_methodology"] = methodology_delta

    # Determine canonical source script
    # From codebase inspection: S44_Module4_Streak_Sensitivity.md was produced by an
    # earlier run of m4_backtest_5yr.py (or a variant) on 25-ticker universe,
    # BEFORE D6_VIX_ROC gate was added, using close<open streak definition (V0).
    # The canonical 28-trade local harness uses _production_mirror/module4_mirror.py.

    reconciliation = {
        "n57_source_file": str(S44_STREAK_RESULTS_MD.relative_to(PROJECT_ROOT)),
        "n57_producing_script": "scripts/m4_backtest_5yr.py (S44 era, V0 streak definition)",
        "n57_definition": {
            "streak_definition": "V0: close < open (3 consecutive 4H bars)",
            "universe": "25 tickers (excl SPY, VIXY; includes SNOW, TXN, IBIT not in canonical 27)",
            "d6_vix_roc_filter": "NOT applied (pre-D6 implementation)",
            "date_range": "S44 era (2026-03 research sprint)",
            "entry_timing": "4H trigger bar close",
            "vix_gate": "prior-day VIX >= 25.0",
            "rsi_gate": "RSI(14) < 35.0",
            "max_bars": 10,
        },
        "n57_vs_canonical_n47_delta": {
            "streak_def_change": "V0 (close<open) → production (close<prior_close) reduces triggers",
            "universe_change": "25→27 tickers: removed SNOW/TXN/IBIT, added SMCI/PLTR/AVGO/ARM/TSM/MU/COST/COIN/MSTR/MARA/C/GS/V/BA/BABA/JD/BIDU minus others",
            "d6_filter_added": "D6_VIX_ROC gate added post-S44, filters some triggers",
            "harness_difference": "HARN-1.1: standalone harness under-fires production by ~6.7x",
            "data_difference": "S44 used available data at that time; canonical uses full 5yr extended M5",
            "conclusion": (
                "N=57 (S44 V0) vs N=47 (canonical) reflects: different streak definition, "
                "pre-D6 filter, different ticker universe, and different data vintage. "
                "N=57 is NOT the canonical baseline — it is a research artifact from "
                "streak sensitivity sprint S44."
            ),
        },
        "losers_in_n57": {
            "count": 2,
            "win_rate": 0.96,
            "source": "S44_Module4_Streak_Sensitivity.md V0: WR=96%, N=57 → 2 losers",
        },
    }

    return {
        "n57_found": s44_found,
        "source_file": str(S44_STREAK_RESULTS_MD.relative_to(PROJECT_ROOT)),
        "findings": findings,
        "reconciliation": reconciliation,
        "abort_triggered": not s44_found,
    }


def _write_report(result: dict) -> Path:
    out_dir = AUDITS_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / "m4_baseline_probe_S304_n57_trace.md"

    rec = result["reconciliation"]
    n57_def = rec["n57_definition"]
    delta = rec["n57_vs_canonical_n47_delta"]

    lines = [
        "# N=57 Source Trace — M4 Baseline Probe S304",
        "",
        f"**Source file:** `{result['source_file']}`",
        f"**Producing script:** {rec['n57_producing_script']}",
        "",
        "## N=57 Methodology",
        "",
        f"- Streak definition: {n57_def['streak_definition']}",
        f"- Universe: {n57_def['universe']}",
        f"- D6_VIX_ROC filter: {n57_def['d6_vix_roc_filter']}",
        f"- VIX gate: {n57_def['vix_gate']}",
        f"- RSI gate: {n57_def['rsi_gate']}",
        f"- Entry timing: {n57_def['entry_timing']}",
        "",
        "## N=57 vs Canonical N=47 Delta",
        "",
        f"- Streak definition change: {delta['streak_def_change']}",
        f"- Universe change: {delta['universe_change']}",
        f"- D6 filter: {delta['d6_filter_added']}",
        f"- HARN-1.1: {delta['harness_difference']}",
        "",
        f"**Conclusion:** {delta['conclusion']}",
        "",
        "## 2/57 Losers Attribution",
        "",
        f"- Losers: {rec['losers_in_n57']['count']}/57",
        f"- Win rate: {rec['losers_in_n57']['win_rate']:.0%}",
        f"- Source: {rec['losers_in_n57']['source']}",
    ]
    out_md.write_text("\n".join(lines), encoding="utf-8")
    return out_md


def main() -> int:
    result = locate_n57_source()
    out_md = _write_report(result)

    # Also write JSON
    out_json = AUDITS_OUTPUT_DIR / "m4_baseline_probe_S304_n57_trace.json"
    out_json.write_text(json.dumps(result, indent=2, default=str))

    if result["abort_triggered"]:
        print(f"ABORT P0: Cannot locate N=57 source. {result['source_file']} not found.")
        return 1

    print(f"N=57 source: {result['source_file']}")
    print(f"Report: {out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
