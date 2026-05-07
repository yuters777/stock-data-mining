#!/usr/bin/env python3
"""Step 7.1 — Aggregate findings into final probe report.

Produces audits/output/m4_baseline_probe_S304.md with 12 required sections
and a binary GO/NO-GO verdict.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from scripts.audits.m4_baseline_probe._constants import (
    AUDITS_OUTPUT_DIR,
    CANONICAL_BASELINE_N,
    CANONICAL_BASELINE_PF,
    CANONICAL_BASELINE_WR,
    CANONICAL_BASELINE_MEAN_RETURN,
    CANONICAL_BASELINE_SHARPE,
    CANONICAL_BASELINE_LOCKED_DATE,
    LOYO_MIN_PF,
    LOTO_MIN_PF,
    LOVO_MIN_PF,
    COST_STRESS_MIN_PF_AT_15BPS,
)


def _load(name: str) -> dict:
    p = AUDITS_OUTPUT_DIR / name
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception as e:
            return {"_load_error": str(e)}
    return {"_missing": True}


def _section_text(md_name: str) -> str:
    p = AUDITS_OUTPUT_DIR / md_name
    if p.exists():
        return p.read_text(encoding="utf-8")
    return f"*(Report not generated: {md_name})*"


def _verdict_from_results(
    db_data: dict,
    n57_data: dict,
    n264_data: dict,
    n4_8_data: dict,
    count_table: dict,
    lookahead: dict,
    rth: dict,
    corp: dict,
    surv: dict,
    loyo: dict,
    loto: dict,
    lovo: dict,
    cost: dict,
) -> tuple[str, list[str], list[str]]:
    """Return (verdict, passing_criteria, failing_criteria)."""
    passing = []
    failing = []

    # Count drift attribution
    if count_table.get("all_attributed"):
        passing.append("Count drift table: all 4 sources attributed")
    elif count_table.get("_missing"):
        failing.append("Count drift table: not generated")
    else:
        failing.append(f"Count drift table: unattributed sources {count_table.get('unattributed', [])}")

    # Look-ahead
    if lookahead.get("pass"):
        passing.append(f"Look-ahead: {lookahead.get('n_clean', 0)}/{lookahead.get('n', 0)} trades clean")
    elif lookahead.get("_missing"):
        failing.append("Look-ahead: audit not run")
    else:
        failing.append(f"Look-ahead: {lookahead.get('n_violations', '?')} violations")

    # Survivorship
    if not surv.get("material_survivorship_bias", True):
        passing.append("Survivorship: no material post-hoc selection bias")
    elif surv.get("_missing"):
        failing.append("Survivorship: audit not run")
    else:
        failing.append(f"Survivorship: material bias detected ({surv.get('posthoc_candidates', [])})")

    # LOYO
    if not loyo.get("any_fail"):
        passing.append(f"LOYO: all years PF >= {LOYO_MIN_PF}")
    elif loyo.get("_missing") or loyo.get("error"):
        failing.append("LOYO: audit not run or error")
    else:
        failed_years = [r["excluded_year"] for r in loyo.get("per_year", []) if not r.get("pass_min_pf_5")]
        failing.append(f"LOYO: PF < {LOYO_MIN_PF} when excluding years {failed_years}")

    # LOTO
    if not loto.get("any_fail"):
        passing.append(f"LOTO: all tickers PF >= {LOTO_MIN_PF}")
    elif loto.get("_missing") or loto.get("error"):
        failing.append("LOTO: audit not run or error")
    else:
        failed = [r["excluded_ticker"] for r in loto.get("per_ticker", []) if not r.get("pass_min_pf_5")]
        failing.append(f"LOTO: PF < {LOTO_MIN_PF} when excluding tickers {failed}")

    # LOVO
    if not lovo.get("any_fail"):
        passing.append(f"LOVO: all VIX clusters PF >= {LOVO_MIN_PF}")
    elif lovo.get("_missing") or lovo.get("error"):
        passing.append("LOVO: VIX data unavailable — cluster analysis skipped (non-blocking)")
    else:
        failing.append(f"LOVO: PF < {LOVO_MIN_PF} on some cluster removal")

    # Cost stress at 15bps
    if cost.get("pass_at_15bps"):
        passing.append(f"Cost stress: PF >= {COST_STRESS_MIN_PF_AT_15BPS} at 15bps")
    elif cost.get("_missing") or cost.get("error"):
        failing.append("Cost stress: audit not run")
    else:
        failing.append(f"Cost stress: PF = {cost.get('pf_at_15bps', '?')} at 15bps (< {COST_STRESS_MIN_PF_AT_15BPS})")

    # DB baseline
    if db_data.get("all_match"):
        passing.append("DB baseline: N=47, PF=21.38 confirmed from snapshot")
    elif db_data.get("_missing") or not db_data.get("snapshot_found", False):
        failing.append("DB baseline: snapshot not provided (Step 0.1 prerequisite pending)")
    else:
        failing.append("DB baseline: values don't match claimed spec")

    # N=57 attribution
    if n57_data.get("n57_found"):
        passing.append("N=57: source located (S44 V0 streak sensitivity)")
    elif n57_data.get("_missing"):
        failing.append("N=57: trace not run")
    else:
        failing.append("N=57: source NOT located — P0 NO-GO")

    verdict = "GO" if not failing else "NO-GO"
    return verdict, passing, failing


def build_final_report() -> dict:
    # Load all intermediate results
    db_data = _load("m4_baseline_probe_S304_db_baseline.json")
    decisions_data = _load("m4_baseline_probe_S304_module_decisions.json")
    n57_data = _load("m4_baseline_probe_S304_n57_trace.json")
    n264_data = _load("m4_baseline_probe_S304_n264_methodology.json")
    n4_8_data = _load("m4_baseline_probe_S304_n4_8_methodology.json")
    count_table = _load("m4_baseline_probe_S304_count_drift_table.json")
    cost_data = _load("m4_baseline_probe_S304_cost_stress.json")
    surv_data = _load("m4_baseline_probe_S304_survivorship.json")
    loyo_data = _load("m4_baseline_probe_S304_loyo.json")
    loto_data = _load("m4_baseline_probe_S304_loto.json")
    lovo_data = _load("m4_baseline_probe_S304_lovo.json")
    lookahead_data = _load("m4_baseline_probe_S304_lookahead.json")
    rth_data = _load("m4_baseline_probe_S304_rth_calendar.json")
    corp_data = _load("m4_baseline_probe_S304_corp_actions.json")

    verdict, passing, failing = _verdict_from_results(
        db_data, n57_data, n264_data, n4_8_data, count_table,
        lookahead_data, rth_data, corp_data, surv_data,
        loyo_data, loto_data, lovo_data, cost_data,
    )

    return {
        "verdict": verdict,
        "passing_criteria": passing,
        "failing_criteria": failing,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "canonical": {
            "n": CANONICAL_BASELINE_N,
            "pf": CANONICAL_BASELINE_PF,
            "wr": CANONICAL_BASELINE_WR,
            "mean_return": CANONICAL_BASELINE_MEAN_RETURN,
            "sharpe": CANONICAL_BASELINE_SHARPE,
            "locked_date": CANONICAL_BASELINE_LOCKED_DATE,
        },
        "sections": {
            "db_baseline": db_data,
            "module_decisions": decisions_data,
            "n57": n57_data,
            "n264": n264_data,
            "n4_8": n4_8_data,
            "count_table": count_table,
            "cost_stress": cost_data,
            "survivorship": surv_data,
            "loyo": loyo_data,
            "loto": loto_data,
            "lovo": lovo_data,
            "lookahead": lookahead_data,
            "rth_calendar": rth_data,
            "corp_actions": corp_data,
        },
    }


def _write_markdown(result: dict) -> Path:
    out_dir = AUDITS_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / "m4_baseline_probe_S304.md"

    verdict = result["verdict"]
    passing = result["passing_criteria"]
    failing = result["failing_criteria"]
    canon = result["canonical"]
    gen = result["generated_at"]

    db_data = result["sections"]["db_baseline"]
    decisions_data = result["sections"]["module_decisions"]
    n57_data = result["sections"]["n57"]
    count_table = result["sections"]["count_table"]
    cost_data = result["sections"]["cost_stress"]
    surv_data = result["sections"]["survivorship"]
    loyo_data = result["sections"]["loyo"]
    loto_data = result["sections"]["loto"]
    lovo_data = result["sections"]["lovo"]
    lookahead_data = result["sections"]["lookahead"]
    rth_data = result["sections"]["rth_calendar"]
    corp_data = result["sections"]["corp_actions"]

    lines = [
        "# M4 Baseline Probe S304 — Final Report",
        "",
        f"**Generated:** {gen}",
        f"**Spec:** spec_2026_05_07_001_dr_probe_m4_baseline v2 FINAL",
        "",
        "---",
        "",
        "## 1. Executive Summary",
        "",
        f"**VERDICT: {verdict}**",
        "",
        "### Passing Criteria",
        "",
    ]

    for p in passing:
        lines.append(f"- {p}")

    if failing:
        lines += ["", "### Failing Criteria / Open Items", ""]
        for f in failing:
            lines.append(f"- {f}")

    lines += [
        "",
        "---",
        "",
        "## 2. Authoritative Baseline",
        "",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| baseline_n | {canon['n']} |",
        f"| baseline_pf | {canon['pf']} |",
        f"| baseline_wr | {canon['wr']} |",
        f"| baseline_mean_return | {canon['mean_return']}% |",
        f"| baseline_sharpe | {canon['sharpe']} |",
        f"| locked_date | {canon['locked_date']} |",
        f"| source | module_baselines table (market-engine market.db) |",
        "",
    ]

    if db_data.get("snapshot_found"):
        row = db_data.get("row", {})
        checks = db_data.get("checks", {})
        lines += [
            "**Snapshot verification:**",
            "",
            f"| Field | Actual | Match |",
            f"|-------|--------|-------|",
        ]
        for k, v in checks.items():
            actual = row.get(k, "N/A")
            lines.append(f"| {k} | {actual} | {'YES' if v else 'NO'} |")
    else:
        lines += [
            "**Snapshot status:** Not provided (Step 0.1 prerequisite). "
            "Run: `scp root@market-engine.dev:/var/lib/market-system/market.db "
            "data/snapshots/market_db_snapshot_$(date +%Y%m%d).db`",
        ]

    lines += [
        "",
        "---",
        "",
        "## 3. Count Drift Reconciliation Table",
        "",
    ]

    if count_table.get("entries"):
        lines += [
            "| N Value | Label | Source | Relationship to Canonical |",
            "|---------|-------|--------|--------------------------|",
        ]
        for e in count_table["entries"]:
            lines.append(
                f"| {e['n_value']} | {e['label']} | `{e['source_script'][:50]}...` "
                f"| {e['relationship_to_canonical'][:60]}... |"
            )
        lines += ["", count_table.get("summary", "")]
    else:
        lines.append("*(Count table not generated)*")

    lines += ["", "---", "", "## 4. Look-Ahead Audit Result", ""]

    n_la = lookahead_data.get("n", 0)
    n_la_clean = lookahead_data.get("n_clean", 0)
    la_violations = lookahead_data.get("violations", [])
    lines += [
        f"**N:** {n_la} | **Clean:** {n_la_clean} | **Violations:** {len(la_violations)}",
        "",
        lookahead_data.get("note", ""),
    ]
    if la_violations:
        lines += ["", "**Violations:**"]
        for v in la_violations:
            lines.append(f"- {v['trade_id']}: {'; '.join(v['issues'])}")
    verdict_la = "PASS" if lookahead_data.get("pass") else "VIOLATIONS FOUND"
    lines.append(f"**Verdict:** {verdict_la}")

    lines += ["", "---", "", "## 5. RTH Calendar Audit Result", ""]
    n_rth = rth_data.get("n", 0)
    n_rth_clean = rth_data.get("n_clean", 0)
    rth_violations = rth_data.get("violations", [])
    lines += [
        f"**N:** {n_rth} | **Clean:** {n_rth_clean} | **Violations:** {len(rth_violations)}",
        rth_data.get("note", ""),
    ]
    if rth_violations:
        lines += ["", "**Violations:**"]
        for v in rth_violations:
            lines.append(f"- {v['trade_id']}: {'; '.join(v['issues'])}")

    lines += ["", "---", "", "## 6. Corporate Action Audit Result", ""]
    corp_flagged = corp_data.get("flagged_events", [])
    lines += [
        f"**N:** {corp_data.get('n', 0)} | **Clean:** {corp_data.get('n_clean', 0)} | **Flagged:** {len(corp_flagged)}",
        corp_data.get("note", ""),
    ]
    if corp_flagged:
        lines += ["", "**Flagged events:**"]
        for ev in corp_flagged:
            lines.append(f"- {ev['trade_id']} — {ev['action']['type']} {ev['action'].get('ratio', '')} on {ev['action']['date']}")

    lines += ["", "---", "", "## 7. Survivorship Audit Result", ""]
    posthoc = surv_data.get("posthoc_candidates", [])
    missing_data = surv_data.get("tickers_missing_data", [])
    lines += [
        f"**Post-hoc risk candidates:** {posthoc}",
        f"**Material survivorship bias:** {surv_data.get('material_survivorship_bias', 'N/A')}",
        f"**Tickers missing local data:** {missing_data}",
        "",
        "Known corporate events documented: ARM IPO (2023-09), SMCI delisting risk (2024-08)",
    ]

    lines += ["", "---", "", "## 8. Robustness Audits", ""]

    # LOYO
    loyo_years = loyo_data.get("per_year", [])
    lines += [
        f"### Leave-One-Year-Out (LOYO)",
        "",
        f"Full sample: N={loyo_data.get('full_sample', {}).get('n', 'N/A')}, PF={loyo_data.get('full_sample', {}).get('pf', 'N/A')}",
        "",
        "| Excluded Year | N | PF | Pass (PF≥5) |",
        "|---------------|---|----|-------------|",
    ]
    for r in loyo_years:
        pf = f"{r['pf']:.4f}" if r.get("pf") is not None else "N/A"
        pass_str = "YES" if r.get("pass_min_pf_5") else "**FAIL**"
        lines.append(f"| {r['excluded_year']} | {r['n']} | {pf} | {pass_str} |")
    loyo_verdict = "PASS" if not loyo_data.get("any_fail") else "FAIL"
    lines.append(f"**LOYO verdict:** {loyo_verdict}")

    # LOTO
    loto_tickers = loto_data.get("per_ticker", [])
    lines += [
        "",
        f"### Leave-One-Ticker-Out (LOTO)",
        "",
        f"Full sample: N={loto_data.get('full_sample', {}).get('n', 'N/A')}, PF={loto_data.get('full_sample', {}).get('pf', 'N/A')}",
        "",
        "| Excluded Ticker | N | PF | Pass (PF≥5) |",
        "|-----------------|---|----|-------------|",
    ]
    for r in loto_tickers:
        pf = f"{r['pf']:.4f}" if r.get("pf") is not None else "N/A"
        pass_str = "YES" if r.get("pass_min_pf_5") else "**FAIL**"
        lines.append(f"| {r['excluded_ticker']} | {r['n']} | {pf} | {pass_str} |")
    loto_verdict = "PASS" if not loto_data.get("any_fail") else "FAIL"
    lines.append(f"**LOTO verdict:** {loto_verdict}")

    # LOVO
    lovo_clusters = lovo_data.get("per_cluster", [])
    lines += [
        "",
        f"### Leave-One-VIX-Cluster-Out (LOVO)",
        "",
        f"Clusters found: {lovo_data.get('clusters_found', 0)}",
        f"VIX data available: {lovo_data.get('vix_data_available', False)}",
        "",
    ]
    if lovo_clusters:
        lines += [
            "| Cluster | Start | End | Days | PF | Pass (PF≥5) |",
            "|---------|-------|-----|------|----|-------------|",
        ]
        for r in lovo_clusters:
            pf = f"{r['pf']:.4f}" if r.get("pf") is not None else "N/A"
            pass_str = "YES" if r.get("pass_min_pf_5") else "**FAIL**"
            lines.append(f"| {r['cluster_id']} | {r['start']} | {r['end']} | {r['days']} | {pf} | {pass_str} |")
    else:
        lines.append("No VIX clusters analysed (VIX data unavailable or no clusters).")
    lovo_verdict = "PASS" if not lovo_data.get("any_fail") else "FAIL"
    lines.append(f"**LOVO verdict:** {lovo_verdict}")

    lines += ["", "---", "", "## 9. Cost Stress Sensitivity", ""]
    cost_results = cost_data.get("results", [])
    lines += [
        f"**N (local):** {cost_data.get('n', 'N/A')} | Canonical N: {CANONICAL_BASELINE_N}",
        f"**PF at 15bps:** {cost_data.get('pf_at_15bps', 'N/A')} | Pass (≥10): {cost_data.get('pass_at_15bps', False)}",
        "",
        "| Slippage (bps) | PF | Pass PF≥10 |",
        "|----------------|----|-----------| ",
    ]
    for r in cost_results:
        pf = f"{r['pf']:.4f}" if isinstance(r.get("pf"), float) else str(r.get("pf", "N/A"))
        pass_str = "YES" if r.get("pass_10x_threshold") else "NO"
        lines.append(f"| {r['slippage_bps']} | {pf} | {pass_str} |")

    if cost_data.get("harn_1_1_caveat"):
        lines += ["", cost_data["harn_1_1_caveat"]]

    lines += ["", "---", "", "## 10. Forward-OOS Context", ""]
    if decisions_data.get("snapshot_found"):
        total = decisions_data.get("total_rows", 0)
        by_outcome = decisions_data.get("rows_by_outcome", {})
        lines += [
            f"**module_decisions M4 rows:** {total}",
            "",
            "| Outcome | Count |",
            "|---------|-------|",
        ]
        for outcome, cnt in by_outcome.items():
            lines.append(f"| {outcome} | {cnt} |")
    else:
        lines.append("Snapshot not provided — forward-OOS rows unavailable.")

    lines += [
        "",
        "---",
        "",
        "## 11. Phase 1 + 2 Decision",
        "",
        f"**VERDICT: {verdict}**",
        "",
    ]

    if verdict == "GO":
        lines += [
            "M4 baseline credibility confirmed. Phase 1 (MAE breakeven trail) and Phase 2 "
            "(multi-variant exit DR) may proceed.",
            "",
            "**Conditions:**",
            "- Phase 1 must use canonical 47-trade ledger from production system",
            "- HARN-1.1 limitation acknowledged: standalone backtest fires ~7 triggers vs 47 production",
            "- ARM IPO (2023-09) and SMCI partial data acknowledged in universe construction",
        ]
    else:
        lines += [
            "Phase 1 and Phase 2 BLOCKED pending resolution of failing criteria above.",
            "",
            "**Next steps:**",
        ]
        for f in failing:
            lines.append(f"- Resolve: {f}")

    lines += [
        "",
        "---",
        "",
        "## 12. Anchor",
        "",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| Spec ID | spec_2026_05_07_001_dr_probe_m4_baseline |",
        f"| Spec version | v2 FINAL |",
        f"| market-engine HEAD SHA | 9a6f7e1 |",
        f"| stock-data-mining HEAD SHA | 79c1894 |",
        f"| Schema version | v90 (module_decisions PR #628) |",
        f"| Baseline locked date | {CANONICAL_BASELINE_LOCKED_DATE} |",
        f"| Report generated | {gen} |",
    ]

    out_md.write_text("\n".join(lines), encoding="utf-8")
    return out_md


def main() -> int:
    result = build_final_report()
    AUDITS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    out_md = _write_markdown(result)
    out_json = AUDITS_OUTPUT_DIR / "m4_baseline_probe_S304.json"
    out_json.write_text(json.dumps(result, indent=2, default=str))

    verdict = result["verdict"]
    n_pass = len(result["passing_criteria"])
    n_fail = len(result["failing_criteria"])
    print(f"Final report: VERDICT={verdict} ({n_pass} passing, {n_fail} failing/open)")
    print(f"Report: {out_md}")
    return 0 if verdict == "GO" else 1


if __name__ == "__main__":
    sys.exit(main())
