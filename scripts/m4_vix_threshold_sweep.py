"""M4 VIX Threshold Sensitivity Sweep v1.0

Tests M4 mean-reversion strategy across VIX_GATE thresholds [20, 22, 23, 24, 25, 26, 28, 30]
on 5yr data (2021-2026, 27 equity tickers).

Closes empirical gap identified Day 47:
- Override 4.0 cliff analysis showed VIX 22-25 bucket has anomalously low bad day prob (1.9%)
  vs VIX 20-22 (8.2%) - possibly mean-reversion-friendly regime
- M4 currently uses VIX_GATE=25.0 (frozen per PI v33). VIX 20-25 range has NEVER been tested
- 5yr M4 data: 264 trades, all with VIX>=25 by definition (current gate)
- Question: is VIX 22-25 range tradeable? Or VIX>=25 empirically optimal?

This sprint runs M4 backtest 8 times (one per threshold) and compares results.
NO production code changes - pure research analysis.

Output: scripts/m4_vix_threshold_sweep_report.md with per-threshold + per-bucket breakdown.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Dict, List, Optional
import json

import pandas as pd

from scripts._production_mirror.module4_mirror import run_module4_mirror_backtest
from scripts._production_mirror._data_paths import load_vix, load_earnings
from scripts._metrics import compute_metrics


# Thresholds to test (frozen per spec - coordinated with operator decision matrix)
VIX_THRESHOLDS = [20.0, 22.0, 23.0, 24.0, 25.0, 26.0, 28.0, 30.0]

# Universe (per Module 4 spec section 8)
UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA",
    "TSLA", "AMD", "SMCI", "PLTR", "AVGO", "ARM", "TSM",
    "MU", "INTC", "COST",
    "COIN", "MSTR", "MARA",
    "C", "GS", "V", "BA", "JPM",
    "BABA", "JD", "BIDU",
]

DATE_RANGE = (date(2021, 4, 28), date(2026, 5, 6))

# VIX buckets for per-bucket trade analysis (frozen - match Day 47 cliff bins)
# Half-open intervals [low, high) to avoid double-counting at boundary.
VIX_BUCKETS = [
    (20.0, 22.0, "20-22"),
    (22.0, 25.0, "22-25"),
    (25.0, 30.0, "25-30"),
    (30.0, 35.0, "30-35"),
    (35.0, 100.0, "35+"),
]


def _vix_prior_close_lookup(vix_df: pd.DataFrame) -> Dict[date, float]:
    """Build {entry_date -> prior trading-day VIX close} map from canonical VIX df."""
    df = vix_df.sort_values("date").reset_index(drop=True)
    closes = df["vix_close"].astype(float).tolist()
    dates = pd.to_datetime(df["date"]).dt.date.tolist()
    # For each date, the "prior close" is the close from the previous row.
    return {dates[i]: closes[i - 1] for i in range(1, len(dates))}


def _attach_vix_at_entry(trades: List[Dict], vix_df: pd.DataFrame) -> List[Dict]:
    """Per VTS-D-3: trade dicts don't include vix_at_entry; compute from vix_df + entry_date."""
    lookup = _vix_prior_close_lookup(vix_df)
    enriched = []
    for t in trades:
        entry_d = t.get("entry_date")
        if isinstance(entry_d, pd.Timestamp):
            entry_d = entry_d.date()
        # Walk back up to 5 calendar days to find the most recent VIX close (handles weekends/holidays)
        vix_val: Optional[float] = None
        if entry_d is not None:
            cursor = entry_d
            for _ in range(7):
                if cursor in lookup:
                    vix_val = lookup[cursor]
                    break
                cursor = cursor.fromordinal(cursor.toordinal() - 1)
        out = dict(t)
        out["vix_at_entry"] = vix_val
        enriched.append(out)
    return enriched


def run_sweep_at_threshold(
    threshold: float,
    earnings_df: pd.DataFrame,
    vix_df: pd.DataFrame,
) -> Dict:
    """Run M4 backtest with VIX_GATE=threshold. Returns metrics + trades list."""
    # run_module4_mirror_backtest reads VIX_GATE as a module-level constant.
    # Monkey-patch for this sweep iteration (intentional - cleanest sweep without modifying mirror).
    import scripts._production_mirror.module4_mirror as m4mod
    original_gate = m4mod.VIX_GATE
    m4mod.VIX_GATE = threshold

    try:
        trades = run_module4_mirror_backtest(
            universe=UNIVERSE,
            date_range=DATE_RANGE,
            earnings_buffer_days=0,  # M4 has no earnings filter (Day 7 standing policy)
            earnings_df=earnings_df,
            vix_df=vix_df,
        )
    finally:
        m4mod.VIX_GATE = original_gate

    trades = _attach_vix_at_entry(trades, vix_df)

    if not trades:
        return {
            "threshold": threshold,
            "N": 0,
            "PF": None,
            "WR": None,
            "mean_return": None,
            "trades": [],
        }

    returns = [t["return_pct"] for t in trades]
    metrics = compute_metrics(returns)

    return {
        "threshold": threshold,
        "N": len(trades),
        "PF": metrics["PF"],
        "WR": metrics["WR"],
        "mean_return": metrics["mean"],
        "trades": trades,
    }


def analyze_per_bucket(trades: List[Dict]) -> Dict[str, Dict]:
    """Bucket trades by VIX value at entry. Returns per-bucket metrics."""
    buckets_result: Dict[str, Dict] = {}

    for vix_min, vix_max, label in VIX_BUCKETS:
        bucket_trades = [
            t for t in trades
            if t.get("vix_at_entry") is not None
            and vix_min <= t["vix_at_entry"] < vix_max
        ]

        if not bucket_trades:
            buckets_result[label] = {"N": 0, "PF": None, "WR": None, "mean": None}
            continue

        returns = [t["return_pct"] for t in bucket_trades]
        metrics = compute_metrics(returns)
        buckets_result[label] = {
            "N": len(bucket_trades),
            "PF": metrics["PF"],
            "WR": metrics["WR"],
            "mean": metrics["mean"],
        }

    return buckets_result


def _fmt_pf(pf) -> str:
    if pf is None:
        return "n/a"
    if isinstance(pf, float) and (pf != pf):  # NaN
        return "n/a"
    if pf == float("inf"):
        return "inf"
    return f"{pf:.2f}"


def _fmt_wr(wr) -> str:
    if wr is None or (isinstance(wr, float) and wr != wr):
        return "n/a"
    return f"{wr:.1%}"


def _fmt_mean_pct(mean) -> str:
    """compute_metrics returns mean as decimal (0.05 = 5%); display as percent."""
    if mean is None or (isinstance(mean, float) and mean != mean):
        return "n/a"
    return f"{mean * 100:+.2f}%"


def write_report(results: List[Dict], bucket_analyses: Dict[float, Dict], out_path: Path) -> None:
    """Write markdown report with per-threshold and per-bucket breakdown."""
    lines = [
        "# M4 VIX Threshold Sensitivity Sweep - Report",
        "",
        f"Run date: {date.today().isoformat()}",
        f"Universe: {len(UNIVERSE)} equity tickers",
        f"Date range: {DATE_RANGE[0]} to {DATE_RANGE[1]}",
        "Earnings buffer: 0 days (M4 standing policy)",
        "",
        "## Per-Threshold Sweep Results",
        "",
        "| VIX Gate | N | PF | WR | Mean Return | Verdict |",
        "|---|---|---|---|---|---|",
    ]

    for r in results:
        n = r["N"]
        pf = r["PF"]
        if pf is None or n < 10:
            verdict = "insufficient N"
        elif isinstance(pf, float) and pf != pf:
            verdict = "insufficient N"
        elif pf == float("inf") or pf > 2.0:
            verdict = "strong edge"
        elif pf > 1.5:
            verdict = "moderate"
        elif pf > 1.0:
            verdict = "marginal"
        else:
            verdict = "no edge"

        lines.append(
            f"| {r['threshold']:.0f} | {n} | {_fmt_pf(pf)} | "
            f"{_fmt_wr(r['WR'])} | {_fmt_mean_pct(r['mean_return'])} | {verdict} |"
        )

    lines.extend(["", "## Per-Bucket Breakdown (at most-permissive threshold = 20)", ""])

    if VIX_THRESHOLDS[0] in bucket_analyses:
        lines.extend([
            "Each row = trades whose VIX value at entry falls in bucket range.",
            "",
            "| VIX Bucket | N | PF | WR | Mean Return |",
            "|---|---|---|---|---|",
        ])
        for label in [b[2] for b in VIX_BUCKETS]:
            b = bucket_analyses[VIX_THRESHOLDS[0]].get(label, {})
            n = b.get("N", 0)
            if n == 0:
                lines.append(f"| {label} | 0 | n/a | n/a | n/a |")
            else:
                lines.append(
                    f"| {label} | {n} | {_fmt_pf(b['PF'])} | "
                    f"{_fmt_wr(b['WR'])} | {_fmt_mean_pct(b['mean'])} |"
                )

    lines.extend([
        "",
        "## Operator-Actionable Verdict",
        "",
        "Compare per-bucket PF and N. Decision rules:",
        "",
        "1. **Keep VIX>=25 (current frozen)** - if VIX 20-25 buckets show PF<1.0 OR N<10",
        "2. **Lower to VIX>=22 or VIX>=23** - if VIX 22-25 bucket shows PF>=1.5 AND N>=20",
        "3. **Raise to VIX>=30** - if VIX 25-30 bucket shows PF<1.0 (current entries actively hurt)",
        "4. **Tier-based sizing** - if VIX 25-30 PF<2.0 but VIX>=30 PF>3.0 (split allocation)",
        "",
        "**NOTE:** This is research-only. Production code changes require:",
        "- DR validation (ChatGPT Pro X/10)",
        "- Quarterly parameter window per Module 4 Spec section 9",
        "- Forward OOS observation period per cc-acceptance discipline",
    ])

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _json_safe(obj):
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, float):
        if obj != obj or obj == float("inf") or obj == float("-inf"):
            return None
    return obj


def main() -> None:
    print("=== M4 VIX Threshold Sensitivity Sweep v1.0 ===")
    print(f"Universe: {len(UNIVERSE)} tickers")
    print(f"Thresholds: {VIX_THRESHOLDS}")
    print()

    print("Loading data...")
    earnings_df = load_earnings()
    vix_df = load_vix()
    print(f"  VIX rows: {len(vix_df)}")
    print(f"  Earnings records: {len(earnings_df)}")
    print()

    results = []
    bucket_analyses: Dict[float, Dict] = {}

    for threshold in VIX_THRESHOLDS:
        print(f"--- VIX Gate = {threshold} ---")
        result = run_sweep_at_threshold(threshold, earnings_df, vix_df)
        results.append(result)

        n = result["N"]
        pf_str = _fmt_pf(result["PF"])
        print(f"  N={n}, PF={pf_str}")

        if threshold == VIX_THRESHOLDS[0]:
            bucket_analyses[threshold] = analyze_per_bucket(result["trades"])

    out_dir = Path("scripts")
    json_path = out_dir / "m4_vix_threshold_sweep_results.json"

    results_for_json = [
        {k: v for k, v in r.items() if k != "trades"}
        for r in results
    ]

    payload = {
        "results": results_for_json,
        "bucket_analyses": {str(k): v for k, v in bucket_analyses.items()},
        "thresholds_tested": VIX_THRESHOLDS,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(_json_safe(payload), f, indent=2, default=str)

    report_path = out_dir / "m4_vix_threshold_sweep_report.md"
    write_report(results, bucket_analyses, report_path)

    print()
    print(f"Results JSON: {json_path}")
    print(f"Report: {report_path}")
    print()
    print("=== Per-Threshold Summary ===")
    for r in results:
        print(f"  VIX>={r['threshold']:.0f}: N={r['N']}, PF={_fmt_pf(r['PF'])}")


if __name__ == "__main__":
    main()
