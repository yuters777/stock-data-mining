#!/usr/bin/env python3
"""Step 5.4 — Leave-one-VIX-cluster-out robustness.

Identifies VIX>=25 episodes in 5yr window. For each cluster: filters trades
by entry_date NOT IN cluster, recomputes PF.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List, Tuple

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from scripts.audits.m4_baseline_probe._constants import (
    LOCAL_TRADES_CSV,
    FETCHED_DATA_DIR,
    AUDITS_OUTPUT_DIR,
    CANONICAL_BASELINE_PF,
    CANONICAL_BASELINE_N,
    LOVO_MIN_PF,
)

VIX_THRESHOLD = 25.0
MIN_CLUSTER_DAYS = 3  # minimum contiguous days to be a "cluster"


def _load_vix_daily() -> pd.DataFrame:
    """Load VIX daily data from Fetched_Data. Try VIXCLS_FRED_real.csv first."""
    for fname in ["VIXCLS_FRED_real.csv", "VIX_daily.csv", "SPY_m5_extended.csv"]:
        p = FETCHED_DATA_DIR / fname
        if p.exists():
            try:
                df = pd.read_csv(p)
                # Normalize column names
                df.columns = [c.lower() for c in df.columns]
                date_col = next((c for c in df.columns if "date" in c), None)
                vix_col = next((c for c in df.columns if "vix" in c or "close" in c.lower()), None)
                if date_col and vix_col:
                    df = df[[date_col, vix_col]].copy()
                    df.columns = ["date", "vix_close"]
                    df["date"] = pd.to_datetime(df["date"], errors="coerce")
                    df = df.dropna().sort_values("date")
                    return df
            except Exception:
                continue

    # Try loading from scripts path (backtest_utils_extended uses Fetched_Data/VIXCLS)
    vix_path = FETCHED_DATA_DIR / "VIXCLS.csv"
    if vix_path.exists():
        try:
            df = pd.read_csv(vix_path)
            df.columns = ["date", "vix_close"] if len(df.columns) == 2 else df.columns
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"]).sort_values("date")
            return df
        except Exception:
            pass

    return pd.DataFrame(columns=["date", "vix_close"])


def _identify_vix_clusters(
    vix_df: pd.DataFrame,
    threshold: float = VIX_THRESHOLD,
    min_days: int = MIN_CLUSTER_DAYS,
) -> List[Tuple[date, date]]:
    """Return list of (start_date, end_date) for contiguous VIX>=threshold episodes."""
    if vix_df.empty:
        return []

    vix_df = vix_df.copy()
    vix_df["above"] = vix_df["vix_close"].astype(float) >= threshold
    vix_df["date_only"] = pd.to_datetime(vix_df["date"]).dt.date

    clusters = []
    in_cluster = False
    start = None

    for _, row in vix_df.iterrows():
        if row["above"] and not in_cluster:
            in_cluster = True
            start = row["date_only"]
        elif not row["above"] and in_cluster:
            end = row["date_only"] - timedelta(days=1)
            if (end - start).days >= min_days:
                clusters.append((start, end))
            in_cluster = False

    if in_cluster and start is not None:
        end = vix_df["date_only"].iloc[-1]
        if (end - start).days >= min_days:
            clusters.append((start, end))

    return clusters


def _compute_pf(df: pd.DataFrame) -> float:
    returns = df["return_pct"].astype(float)
    gains = returns[returns > 0].sum()
    losses = returns[returns < 0].abs().sum()
    if losses == 0:
        return float("inf") if gains > 0 else float("nan")
    return float(gains / losses)


def robustness_lovo(trades_path: Path | None = None) -> dict:
    trades_p = trades_path or LOCAL_TRADES_CSV

    if not trades_p.exists():
        return {"error": f"Trades CSV not found: {trades_p}", "per_cluster": [], "any_fail": False}

    df = pd.read_csv(trades_p)
    if "return_pct" not in df.columns or "entry_date" not in df.columns:
        return {"error": "Required columns missing", "per_cluster": [], "any_fail": False}

    df["entry_date"] = pd.to_datetime(df["entry_date"], errors="coerce").dt.date

    vix_df = _load_vix_daily()
    clusters = _identify_vix_clusters(vix_df)

    full_pf = _compute_pf(df)
    full_n = len(df)
    per_cluster = []
    any_fail = False

    for i, (start, end) in enumerate(clusters):
        in_cluster = df["entry_date"].apply(
            lambda d: d is not None and start <= d <= end
        )
        subset = df[~in_cluster]
        if len(subset) == 0:
            continue

        pf = _compute_pf(subset)
        import math
        pass_threshold = math.isfinite(pf) and pf >= LOVO_MIN_PF
        if not pass_threshold:
            any_fail = True

        per_cluster.append({
            "cluster_id": i + 1,
            "start": str(start),
            "end": str(end),
            "days": (end - start).days + 1,
            "trades_in_cluster": int(in_cluster.sum()),
            "n": len(subset),
            "pf": round(pf, 4) if pd.notna(pf) else None,
            "pf_delta": round(pf - full_pf, 4) if pd.notna(pf) else None,
            "pass_min_pf_5": pass_threshold,
        })

    vix_available = not vix_df.empty

    return {
        "trades_file": str(trades_p.relative_to(Path(__file__).parent.parent.parent.parent)),
        "vix_data_available": vix_available,
        "clusters_found": len(clusters),
        "full_sample": {"n": full_n, "pf": round(full_pf, 4)},
        "canonical_pf": CANONICAL_BASELINE_PF,
        "canonical_n": CANONICAL_BASELINE_N,
        "per_cluster": per_cluster,
        "any_fail": any_fail,
        "abort_triggered": any_fail,
        "min_pf_threshold": LOVO_MIN_PF,
        "note": "VIX data unavailable — cluster analysis skipped" if not vix_available else "",
    }


def _write_report(result: dict) -> Path:
    out_dir = AUDITS_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / "m4_baseline_probe_S304_lovo.md"

    lines = [
        "# Leave-One-VIX-Cluster-Out Robustness — M4 Baseline Probe S304",
        "",
        f"**Full sample:** N={result['full_sample']['n']}, PF={result['full_sample']['pf']}",
        f"**Canonical:** N={result['canonical_n']}, PF={result['canonical_pf']}",
        f"**VIX clusters found (≥25, ≥3 days):** {result['clusters_found']}",
        f"**VIX data available:** {result['vix_data_available']}",
        "",
    ]

    if result.get("note"):
        lines.append(f"**Note:** {result['note']}")
        lines.append("")

    if "error" in result:
        lines.append(f"**ERROR:** {result['error']}")
    elif result["per_cluster"]:
        lines += [
            "## Per-Cluster Results",
            "",
            "| Cluster | Start | End | Days | Trades In | N | PF | PF Delta | Pass (PF≥5) |",
            "|---------|-------|-----|------|-----------|---|----|----------|-------------|",
        ]
        for r in result["per_cluster"]:
            pf = f"{r['pf']:.4f}" if r["pf"] is not None else "N/A"
            delta = f"{r['pf_delta']:+.4f}" if r["pf_delta"] is not None else "N/A"
            pass_str = "YES" if r["pass_min_pf_5"] else "**FAIL**"
            lines.append(
                f"| {r['cluster_id']} | {r['start']} | {r['end']} | {r['days']} "
                f"| {r['trades_in_cluster']} | {r['n']} | {pf} | {delta} | {pass_str} |"
            )
    else:
        lines.append("No VIX clusters processed (VIX data unavailable or no clusters found).")

    verdict = "NO-GO" if result.get("abort_triggered") else "PASS"
    lines += ["", f"**LOVO verdict:** {verdict}"]

    out_md.write_text("\n".join(lines), encoding="utf-8")
    return out_md


def main() -> int:
    result = robustness_lovo()
    out_md = _write_report(result)
    out_json = AUDITS_OUTPUT_DIR / "m4_baseline_probe_S304_lovo.json"
    out_json.write_text(json.dumps(result, indent=2, default=str))

    if "error" in result:
        print(f"ERROR: {result['error']}")
        return 1

    print(f"LOVO: {result['clusters_found']} clusters, any_fail={result['any_fail']}")
    print(f"Report: {out_md}")
    return 1 if result["abort_triggered"] else 0


if __name__ == "__main__":
    sys.exit(main())
