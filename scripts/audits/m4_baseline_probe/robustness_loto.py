#!/usr/bin/env python3
"""Step 5.3 — Leave-one-ticker-out robustness.

For each of 27 canonical tickers: filters trades by ticker != target,
recomputes PF + WR. Reports delta vs full-sample baseline.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from scripts.audits.m4_baseline_probe._constants import (
    CANONICAL_UNIVERSE,
    LOCAL_TRADES_CSV,
    AUDITS_OUTPUT_DIR,
    CANONICAL_BASELINE_PF,
    CANONICAL_BASELINE_N,
    LOTO_MIN_PF,
)


def _compute_pf(df: pd.DataFrame) -> float:
    returns = df["return_pct"].astype(float)
    gains = returns[returns > 0].sum()
    losses = returns[returns < 0].abs().sum()
    if losses == 0:
        return float("inf") if gains > 0 else float("nan")
    return float(gains / losses)


def _compute_wr(df: pd.DataFrame) -> float:
    returns = df["return_pct"].astype(float)
    if len(returns) == 0:
        return float("nan")
    return float((returns > 0).mean())


def robustness_loto(trades_path: Path | None = None) -> dict:
    path = trades_path or LOCAL_TRADES_CSV

    if not path.exists():
        return {"error": f"Trades CSV not found: {path}", "per_ticker": [], "any_fail": False}

    df = pd.read_csv(path)
    if "return_pct" not in df.columns or "ticker" not in df.columns:
        return {"error": "Required columns missing", "per_ticker": [], "any_fail": False}

    full_pf = _compute_pf(df)
    full_wr = _compute_wr(df)
    full_n = len(df)

    tickers_in_data = sorted(df["ticker"].unique().tolist())
    per_ticker = []
    any_fail = False

    for ticker in tickers_in_data:
        subset = df[df["ticker"] != ticker]
        if len(subset) == 0:
            continue
        pf = _compute_pf(subset)
        wr = _compute_wr(subset)
        import math
        pass_threshold = math.isfinite(pf) and pf >= LOTO_MIN_PF
        if not pass_threshold:
            any_fail = True
        per_ticker.append({
            "excluded_ticker": ticker,
            "n": len(subset),
            "n_excluded": int((df["ticker"] == ticker).sum()),
            "pf": round(pf, 4) if pd.notna(pf) else None,
            "wr": round(wr, 4) if pd.notna(wr) else None,
            "pf_delta": round(pf - full_pf, 4) if (pd.notna(pf) and pd.notna(full_pf)) else None,
            "pass_min_pf_5": pass_threshold,
        })

    # Tickers in canonical universe but not in data
    missing_from_data = sorted(set(CANONICAL_UNIVERSE) - set(tickers_in_data))

    return {
        "trades_file": str(path.relative_to(Path(__file__).parent.parent.parent.parent)),
        "full_sample": {"n": full_n, "pf": round(full_pf, 4), "wr": round(full_wr, 4)},
        "canonical_pf": CANONICAL_BASELINE_PF,
        "canonical_n": CANONICAL_BASELINE_N,
        "per_ticker": per_ticker,
        "tickers_in_data": tickers_in_data,
        "missing_from_data": missing_from_data,
        "any_fail": any_fail,
        "abort_triggered": any_fail,
        "min_pf_threshold": LOTO_MIN_PF,
        "harn_1_1_caveat": f"Local N={full_n} vs canonical N={CANONICAL_BASELINE_N} (HARN-1.1)",
    }


def _write_report(result: dict) -> Path:
    out_dir = AUDITS_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / "m4_baseline_probe_S304_loto.md"

    lines = [
        "# Leave-One-Ticker-Out Robustness — M4 Baseline Probe S304",
        "",
        f"**Full sample:** N={result['full_sample']['n']}, PF={result['full_sample']['pf']}, WR={result['full_sample']['wr']}",
        f"**Canonical:** N={result['canonical_n']}, PF={result['canonical_pf']}",
        f"**Min PF threshold:** {result['min_pf_threshold']}",
        "",
    ]

    if result.get("missing_from_data"):
        lines.append(f"**Tickers in canonical universe but not in local data:** {result['missing_from_data']}")
        lines.append("")

    if "error" in result:
        lines.append(f"**ERROR:** {result['error']}")
    else:
        lines += [
            "## Per-Ticker Results",
            "",
            "| Excluded Ticker | N | N Excluded | PF | WR | PF Delta | Pass (PF≥5) |",
            "|-----------------|---|------------|----|----|----------|-------------|",
        ]
        for r in result["per_ticker"]:
            pf = f"{r['pf']:.4f}" if r["pf"] is not None else "N/A"
            wr = f"{r['wr']:.2%}" if r["wr"] is not None else "N/A"
            delta = f"{r['pf_delta']:+.4f}" if r["pf_delta"] is not None else "N/A"
            pass_str = "YES" if r["pass_min_pf_5"] else "**FAIL**"
            lines.append(
                f"| {r['excluded_ticker']} | {r['n']} | {r['n_excluded']} "
                f"| {pf} | {wr} | {delta} | {pass_str} |"
            )

    verdict = "NO-GO" if result.get("abort_triggered") else "PASS"
    lines += [
        "",
        f"**LOTO verdict:** {verdict}",
        "",
        f"**HARN-1.1:** {result.get('harn_1_1_caveat', '')}",
    ]

    out_md.write_text("\n".join(lines), encoding="utf-8")
    return out_md


def main() -> int:
    result = robustness_loto()
    out_md = _write_report(result)
    out_json = AUDITS_OUTPUT_DIR / "m4_baseline_probe_S304_loto.json"
    out_json.write_text(json.dumps(result, indent=2, default=str))

    if "error" in result:
        print(f"ERROR: {result['error']}")
        return 1

    print(f"LOTO: {len(result['per_ticker'])} tickers, any_fail={result['any_fail']}")
    print(f"Report: {out_md}")
    return 1 if result["abort_triggered"] else 0


if __name__ == "__main__":
    sys.exit(main())
