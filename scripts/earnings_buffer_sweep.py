"""
Earnings Buffer Sensitivity Sweep — orchestrator entry point.

Pre-registered hypothesis test: are M4=0d / M6=±1d / M7=±6d earnings filters empirically optimal?

Usage:
    python scripts/earnings_buffer_sweep.py
    python scripts/earnings_buffer_sweep.py --validate-only  # data file checks only
    python scripts/earnings_buffer_sweep.py --modules M6,M7  # subset
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from scripts._backtest_lib_m4 import run_module4_backtest
from scripts._backtest_lib_m6 import run_module6_backtest
from scripts._backtest_lib_m7 import run_module7_backtest
from scripts._data_loaders import (
    load_corporate_actions,
    load_earnings_calendar,
    load_news_index,
    load_vix_daily,
)
from scripts._metrics import compute_metrics, holm_bonferroni

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("earnings_buffer_sweep")

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

DATA_ROOT = Path(r"C:\Projects\stock-data-mining\Fetched_Data")
RESULTS_PATH = Path("scripts/earnings_buffer_sweep_results.json")
REPORT_PATH = Path("scripts/earnings_buffer_sweep_report.md")

UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA",
    "TSLA", "AMD", "SMCI", "PLTR", "AVGO", "ARM", "TSM",
    "MU", "INTC", "COST",
    "COIN", "MSTR", "MARA",
    "C", "GS", "V", "BA", "JPM",
    "BABA", "JD", "BIDU",
]
assert len(UNIVERSE) == 27, f"Universe size error: {len(UNIVERSE)}"

DATE_RANGE = ("2021-04-28", "2026-04-28")
SWEEP_BUCKETS = [0, 1, 3, 5]

CANONICAL_BASELINES = {
    "M4": {"current_buffer": 0, "N": 47, "PF": 21.38},
    "M6": {"current_buffer": 1, "N": 378, "PF": 1.68},
    "M7": {"current_buffer": 6, "N": 188, "PF": 1.72},
}

TOLERANCE_N = 0.05
TOLERANCE_PF = 0.10
PF_IMPROVEMENT_THRESHOLD = 1.10
N_FLOOR = 30
ALPHA = 0.05


# ─── DATA VALIDATION ──────────────────────────────────────────────────────────

def validate_data() -> bool:
    """Check that all required data files are present. Returns True if all present."""
    log.info("Validating data files...")
    missing = []

    for ticker in UNIVERSE + ["SPY"]:
        f = DATA_ROOT / f"{ticker}_m5_extended.csv"
        if not f.exists():
            missing.append(str(f))

    for f_name in ["earnings_calendar.csv", "VIX_daily.csv"]:
        f = DATA_ROOT / f_name
        if not f.exists():
            missing.append(str(f))

    if missing:
        log.error(f"Missing data files ({len(missing)}):")
        for m in missing[:10]:
            log.error(f"  {m}")
        if len(missing) > 10:
            log.error(f"  ... and {len(missing) - 10} more")
        return False

    log.info("All required data files present")
    return True


# ─── ACCEPTANCE CHECK ─────────────────────────────────────────────────────────

def acceptance_check(module: str, results: Dict) -> bool:
    """Verify current-buffer bucket reproduces canonical baseline within tolerance."""
    baseline = CANONICAL_BASELINES[module]
    cur_buf = baseline["current_buffer"]

    if cur_buf not in results["buckets"]:
        log.warning(
            f"[{module}] current buffer ±{cur_buf}d not in sweep range — skipping baseline check"
        )
        return True

    bucket = results["buckets"][cur_buf]
    n_lo = baseline["N"] * (1 - TOLERANCE_N)
    n_hi = baseline["N"] * (1 + TOLERANCE_N)
    pf_lo = baseline["PF"] * (1 - TOLERANCE_PF)
    pf_hi = baseline["PF"] * (1 + TOLERANCE_PF)

    n_ok = n_lo <= bucket["N"] <= n_hi
    pf_ok = pf_lo <= bucket["PF"] <= pf_hi

    log.info(
        f"[{module}] ACCEPTANCE ±{cur_buf}d: "
        f"N={bucket['N']} ({'PASS' if n_ok else 'FAIL'} [{n_lo:.0f}-{n_hi:.0f}]), "
        f"PF={bucket['PF']:.2f} ({'PASS' if pf_ok else 'FAIL'} [{pf_lo:.2f}-{pf_hi:.2f}])"
    )

    return n_ok and pf_ok


# ─── DECISION RULE ────────────────────────────────────────────────────────────

def evaluate_decision(module: str, results: Dict) -> Dict:
    """Apply all 5 pre-registered decision criteria."""
    baseline = CANONICAL_BASELINES[module]
    cur_buf = baseline["current_buffer"]
    cur_pf = baseline["PF"]

    p_vals = {b: r["p_value"] for b, r in results["buckets"].items() if b != cur_buf}
    holm = holm_bonferroni(p_vals, alpha=ALPHA)

    candidates = []
    for buf, res in results["buckets"].items():
        if buf == cur_buf:
            continue
        c1 = res["PF"] >= cur_pf * PF_IMPROVEMENT_THRESHOLD
        c2 = res["N"] >= N_FLOOR
        c3 = res["ci_low"] > cur_pf
        c5 = holm.get(buf, False)
        if c1 and c2 and c3 and c5:
            candidates.append({"buffer": buf, "PF": res["PF"], "N": res["N"]})

    decision = "STATUS_QUO"
    rationale = []
    sorted_buckets = sorted(SWEEP_BUCKETS)

    if candidates:
        for cand in candidates:
            buf = cand["buffer"]
            if buf not in sorted_buckets:
                continue
            idx = sorted_buckets.index(buf)
            adjacent = []
            if idx > 0:
                adjacent.append(sorted_buckets[idx - 1])
            if idx < len(sorted_buckets) - 1:
                adjacent.append(sorted_buckets[idx + 1])
            adjacent_winners = [a for a in adjacent if a in {c["buffer"] for c in candidates}]
            if adjacent_winners:
                decision = f"CHANGE_TO_{buf}d"
                rationale.append(
                    f"Buffer ±{buf}d: PF={cand['PF']:.2f} (≥{cur_pf * PF_IMPROVEMENT_THRESHOLD:.2f}), "
                    f"N={cand['N']} (≥{N_FLOOR}), CI excludes baseline, Holm-corrected significant, "
                    f"adjacent ±{adjacent_winners[0]}d also winner."
                )
                break

    if not rationale:
        rationale.append(
            f"Current ±{cur_buf}d retained — no candidate passed all 5 criteria."
        )

    return {"decision": decision, "rationale": rationale, "candidates": candidates}


# ─── REPORT ───────────────────────────────────────────────────────────────────

def write_markdown_report(results: dict, path: Path) -> None:
    """Write human-readable Markdown results report."""
    lines = [
        "# Earnings Buffer Sweep — Results",
        "",
        f"**Date:** {pd.Timestamp.utcnow().isoformat()}",
        "**Spec:** CC_EARNINGS_BUFFER_SWEEP_v1_0_spec.md",
        "**Decision rule:** 5-criterion (PF≥1.10× + N≥30 + CI excludes baseline + adjacent + Holm)",
        "",
    ]

    for module, r in results.items():
        baseline = CANONICAL_BASELINES[module]
        lines.append(
            f"## {module} (current ±{baseline['current_buffer']}d, "
            f"baseline PF={baseline['PF']:.2f})"
        )
        lines.append("")
        lines.append("| Buffer | N | PF | WR | Mean | p-value | CI low | CI high |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for buf, m in sorted(r["buckets"].items()):
            marker = " ← current" if buf == baseline["current_buffer"] else ""
            pf_str = f"{m['PF']:.2f}" if not (isinstance(m["PF"], float) and m["PF"] != m["PF"]) else "nan"
            wr_str = f"{m['WR']:.1%}" if not (isinstance(m["WR"], float) and m["WR"] != m["WR"]) else "nan"
            mean_str = f"{m['mean']*100:+.2f}%" if not (isinstance(m["mean"], float) and m["mean"] != m["mean"]) else "nan"
            lines.append(
                f"| ±{buf}d{marker} | {m['N']} | {pf_str} | {wr_str} | {mean_str} | "
                f"{m['p_value']:.3f} | {m['ci_low']:.2f} | {m['ci_high']:.2f} |"
            )
        lines.append("")
        acc = "PASS" if r.get("acceptance_passed", False) else "FAIL"
        lines.append(f"**Acceptance:** {acc}")
        lines.append(f"**Decision:** **{r['decision']['decision']}**")
        for rationale in r["decision"]["rationale"]:
            lines.append(f"- {rationale}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main(modules: Optional[List[str]] = None, validate_only: bool = False) -> None:
    log.info("=== Earnings Buffer Sensitivity Sweep — Spec v1.0 ===")

    if not validate_data():
        sys.exit(1)

    if validate_only:
        log.info("--validate-only: data validation passed, exiting")
        return

    earnings_df = load_earnings_calendar(DATA_ROOT)
    vix_df = load_vix_daily(DATA_ROOT)
    news_df = load_news_index(DATA_ROOT)
    ca_df = load_corporate_actions(DATA_ROOT)

    target_modules = modules or ["M4", "M6", "M7"]

    results: Dict[str, Dict] = {}

    for module in target_modules:
        log.info(f"\n=== Sweep: {module} ===")

        def _make_runner(mod: str):
            def run_m4(buf):
                return run_module4_backtest(UNIVERSE, DATE_RANGE, buf, DATA_ROOT, earnings_df, vix_df)

            def run_m6(buf):
                return run_module6_backtest(UNIVERSE, DATE_RANGE, buf, DATA_ROOT, earnings_df, news_df, ca_df, None)

            def run_m7(buf):
                return run_module7_backtest(UNIVERSE, DATE_RANGE, buf, DATA_ROOT, earnings_df)

            return {"M4": run_m4, "M6": run_m6, "M7": run_m7}[mod]

        run_func = _make_runner(module)
        module_results: Dict = {"buckets": {}}

        for buf in SWEEP_BUCKETS:
            log.info(f"  Running {module} buffer=±{buf}d...")
            t0 = time.time()
            try:
                trades = run_func(buf)
                returns = [t["return_pct"] for t in trades]
                metrics = compute_metrics(returns, bootstrap_iters=1000, seed=42)
            except Exception as e:
                log.exception(f"  {module} buffer=±{buf}d FAILED: {e}")
                metrics = {
                    "N": 0, "PF": float("nan"), "WR": float("nan"),
                    "mean": float("nan"), "std": float("nan"),
                    "t_stat": float("nan"), "p_value": float("nan"),
                    "ci_low": float("nan"), "ci_high": float("nan"),
                    "error": str(e),
                }
            elapsed = time.time() - t0
            log.info(
                f"    N={metrics['N']}, PF={metrics['PF']:.2f}, "
                f"elapsed={elapsed:.1f}s"
            )
            module_results["buckets"][buf] = metrics

        module_results["acceptance_passed"] = acceptance_check(module, module_results)
        if module_results["acceptance_passed"]:
            module_results["decision"] = evaluate_decision(module, module_results)
        else:
            module_results["decision"] = {
                "decision": "INVALID",
                "rationale": ["Baseline reproduction FAILED — sweep results untrusted, do not act."],
                "candidates": [],
            }
        results[module] = module_results

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2, default=str)
    log.info(f"\nResults JSON: {RESULTS_PATH}")

    write_markdown_report(results, REPORT_PATH)
    log.info(f"Report: {REPORT_PATH}")

    log.info("\n=== DECISION SUMMARY ===")
    for module, r in results.items():
        log.info(f"  {module}: {r['decision']['decision']}")
        for line in r["decision"]["rationale"]:
            log.info(f"    - {line}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Earnings Buffer Sensitivity Sweep v1.0"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate data files only, do not run sweep",
    )
    parser.add_argument(
        "--modules",
        default="M4,M6,M7",
        help="Comma-separated module list (M4,M6,M7)",
    )
    args = parser.parse_args()
    main(modules=args.modules.split(","), validate_only=args.validate_only)
