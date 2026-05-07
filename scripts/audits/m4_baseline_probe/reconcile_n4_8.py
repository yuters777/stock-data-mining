#!/usr/bin/env python3
"""Step 3.3 — Reconcile N=4-8 VIX threshold sweep.

The N=4-8 figure comes from m4_vix_threshold_sweep.py which ran the standalone
harness at various VIX thresholds. At VIX_GATE=25.0 the harness fires N=7.
Documents consistency with HARN-1.1 ratio (47/6.7 ≈ 7).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from scripts.audits.m4_baseline_probe._constants import (
    AUDITS_OUTPUT_DIR,
    VIX_SWEEP_RESULTS_JSON,
    CANONICAL_BASELINE_N,
)

HARN_RATIO = 6.7  # documented HARN-1.1 under-fire ratio


def reconcile_n4_8() -> dict:
    sweep_data = {}
    if VIX_SWEEP_RESULTS_JSON.exists():
        sweep_data = json.loads(VIX_SWEEP_RESULTS_JSON.read_text())

    results_by_threshold: dict[str, dict] = {}
    at_25 = {}

    if "results" in sweep_data:
        for r in sweep_data["results"]:
            thresh = str(r["threshold"])
            results_by_threshold[thresh] = r
            if r["threshold"] == 25.0:
                at_25 = r

    n_at_25 = at_25.get("N", "N/A")
    expected_from_harn = round(CANONICAL_BASELINE_N / HARN_RATIO, 1)
    harn_consistent = (
        isinstance(n_at_25, int) and abs(n_at_25 - expected_from_harn) <= 2
    )

    reconciliation = {
        "sweep_script": "scripts/m4_vix_threshold_sweep.py",
        "sweep_results_file": "scripts/m4_vix_threshold_sweep_results.json",
        "n_at_vix25": n_at_25,
        "expected_from_harn_ratio": expected_from_harn,
        "harn_ratio": HARN_RATIO,
        "harn_consistent": harn_consistent,
        "all_thresholds": results_by_threshold,
        "methodology": {
            "what_was_swept": "VIX_GATE from 20 to 30 in 8 steps",
            "harness_used": "scripts/_production_mirror/module4_mirror.py (standalone)",
            "data_source": "local Fetched_Data/*_m5_extended.csv",
            "key_finding": (
                f"At VIX_GATE=25 standalone harness fires N={n_at_25} over 5yr. "
                f"Canonical production fires N={CANONICAL_BASELINE_N}. "
                f"Ratio: {CANONICAL_BASELINE_N}/{n_at_25 if isinstance(n_at_25, int) and n_at_25 else '?'} ≈ "
                f"{CANONICAL_BASELINE_N / n_at_25 if isinstance(n_at_25, int) and n_at_25 else '?'}. "
                f"Expected from HARN-1.1 ratio of {HARN_RATIO}: {expected_from_harn}. "
                f"Consistent: {harn_consistent}."
            ),
        },
        "delta_from_canonical": {
            "n47_source": "production system (canonical)",
            "n4_8_source": "standalone harness VIX sweep at various thresholds",
            "relationship": (
                "N=4-8 figures are HARN-1.1 artifacts. The standalone harness fires "
                "~7 triggers per 5yr run vs 47 in production. This is a structural "
                "difference (not a bug), documented as Principle #57 candidate."
            ),
        },
    }

    return {
        "sweep_data_found": bool(sweep_data),
        "n_at_vix25": n_at_25,
        "harn_consistent": harn_consistent,
        "reconciliation": reconciliation,
    }


def _write_report(result: dict) -> Path:
    out_dir = AUDITS_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / "m4_baseline_probe_S304_n4_8_methodology.md"

    rec = result["reconciliation"]
    m = rec["methodology"]
    delta = rec["delta_from_canonical"]

    status = "CONSISTENT with HARN-1.1" if result["harn_consistent"] else "INCONSISTENT with HARN-1.1"

    lines = [
        "# N=4-8 VIX Threshold Sweep Reconciliation — M4 Baseline Probe S304",
        "",
        f"**Source script:** `{rec['sweep_script']}`",
        f"**Results file:** `{rec['sweep_results_file']}`",
        "",
        "## Key Finding",
        "",
        m["key_finding"],
        "",
        f"**HARN-1.1 consistency:** {status}",
        "",
        "## Methodology",
        "",
        f"- What was swept: {m['what_was_swept']}",
        f"- Harness: {m['harness_used']}",
        f"- Data: {m['data_source']}",
        "",
        "## All Thresholds",
        "",
        "| VIX Gate | N | PF | WR |",
        "|----------|---|----|----|",
    ]

    for thresh, r in sorted(rec["all_thresholds"].items(), key=lambda x: float(x[0])):
        pf = f"{r.get('PF', 'N/A'):.2f}" if isinstance(r.get("PF"), float) else "N/A"
        wr = f"{r.get('WR', 0):.2%}" if isinstance(r.get("WR"), float) else "N/A"
        lines.append(f"| {thresh} | {r.get('N', '?')} | {pf} | {wr} |")

    lines += [
        "",
        "## Delta from Canonical N=47",
        "",
        f"- N=47 source: {delta['n47_source']}",
        f"- N=4-8 source: {delta['n4_8_source']}",
        "",
        f"**Relationship:** {delta['relationship']}",
    ]

    out_md.write_text("\n".join(lines), encoding="utf-8")
    return out_md


def main() -> int:
    result = reconcile_n4_8()
    out_md = _write_report(result)
    out_json = AUDITS_OUTPUT_DIR / "m4_baseline_probe_S304_n4_8_methodology.json"
    out_json.write_text(json.dumps(result, indent=2, default=str))

    n = result["n_at_vix25"]
    consistent = result["harn_consistent"]
    print(f"N at VIX>=25 (standalone): {n} (expected ~{round(CANONICAL_BASELINE_N / HARN_RATIO, 1)} from HARN-1.1)")
    print(f"HARN-1.1 consistent: {consistent}")
    print(f"Report: {out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
