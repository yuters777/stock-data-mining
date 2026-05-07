#!/usr/bin/env python3
"""Step 1.5 / 7.2 — Orchestrator for M4 Baseline Probe S304.

Runs all audit scripts in sequence, aggregates results, and emits
a final report. Exits 0 on GO, non-zero on NO-GO or fatal error.
"""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

# Ordered list: (module_name, step_id, fatal_on_fail)
STEPS = [
    ("scripts.audits.m4_baseline_probe.check_utils_import", "1.3", False),
    ("scripts.audits.m4_baseline_probe.read_m4_constants", "1.4", True),
    ("scripts.audits.m4_baseline_probe.read_ticker_universe", "1.6", False),
    ("scripts.audits.m4_baseline_probe.audit_module_baselines", "2.1", False),
    ("scripts.audits.m4_baseline_probe.snapshot_module_decisions", "2.2", False),
    ("scripts.audits.m4_baseline_probe.locate_n57_source", "3.1", True),
    ("scripts.audits.m4_baseline_probe.reconcile_n264", "3.2", False),
    ("scripts.audits.m4_baseline_probe.reconcile_n4_8", "3.3", False),
    ("scripts.audits.m4_baseline_probe.build_count_table", "3.4", True),
    ("scripts.audits.m4_baseline_probe.audit_cost_stress", "4.1", False),
    ("scripts.audits.m4_baseline_probe.audit_survivorship", "5.1", False),
    ("scripts.audits.m4_baseline_probe.robustness_loyo", "5.2", False),
    ("scripts.audits.m4_baseline_probe.robustness_loto", "5.3", False),
    ("scripts.audits.m4_baseline_probe.robustness_lovo", "5.4", False),
    ("scripts.audits.m4_baseline_probe.audit_lookahead", "6.1", False),
    ("scripts.audits.m4_baseline_probe.audit_rth_calendar", "6.2", False),
    ("scripts.audits.m4_baseline_probe.audit_corp_actions", "6.3", False),
    ("scripts.audits.m4_baseline_probe.build_final_report", "7.1", False),
]


def run_step(module_name: str, step_id: str) -> tuple[int, str]:
    """Import module and call main(). Returns (exit_code, status)."""
    try:
        mod = importlib.import_module(module_name)
        if not hasattr(mod, "main"):
            return 0, "no main() — skipped"
        code = mod.main()
        return (code or 0), "ok" if (code or 0) == 0 else "non-zero"
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        return code, "ok" if code == 0 else "non-zero"
    except Exception:
        tb = traceback.format_exc()
        print(f"EXCEPTION in {module_name}:\n{tb}")
        return 1, "exception"


def main() -> int:
    print("=" * 60)
    print("M4 Baseline Probe S304 — Orchestrator")
    print("=" * 60)

    results = []
    fatal_abort = False

    for module_name, step_id, fatal in STEPS:
        short = module_name.split(".")[-1]
        print(f"\n[Step {step_id}] {short}")
        code, status = run_step(module_name, step_id)
        results.append({
            "step": step_id,
            "module": short,
            "exit_code": code,
            "status": status,
        })
        print(f"  → exit={code} ({status})")

        if code != 0 and fatal:
            print(f"  FATAL: step {step_id} failed with exit {code}. Aborting.")
            fatal_abort = True
            break

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    n_ok = sum(1 for r in results if r["exit_code"] == 0)
    n_fail = len(results) - n_ok

    for r in results:
        icon = "OK" if r["exit_code"] == 0 else "FAIL"
        print(f"  [{icon}] Step {r['step']:4s} {r['module']}")

    print(f"\n{n_ok}/{len(results)} steps OK")

    if fatal_abort:
        print("ORCHESTRATOR: FATAL ABORT triggered")
        return 1

    if n_fail > 0:
        print(f"ORCHESTRATOR: {n_fail} step(s) reported non-zero (check individual reports)")

    # Final verdict from the report
    try:
        from scripts.audits.m4_baseline_probe._constants import AUDITS_OUTPUT_DIR
        import json
        p = AUDITS_OUTPUT_DIR / "m4_baseline_probe_S304.json"
        if p.exists():
            data = json.loads(p.read_text())
            verdict = data.get("verdict", "UNKNOWN")
            print(f"\nFINAL VERDICT: {verdict}")
            return 0 if verdict == "GO" else 1
    except Exception:
        pass

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
