"""M4 MAX_BARS Bar-by-Bar Sensitivity Sweep v1.0

True counterfactual analysis: for each M4 trade from Day 32 backtest,
records bar-by-bar close prices from entry through up to 10 forward 4H bars,
then computes synthetic exit P&L for MAX_BARS in [4, 5, 6, 7, 8, 9, 10].

Closes Day 47 evening question: "is MAX_BARS=10 too long?"

Naive analysis (delete trades with bars_held > MAX) is misleading because it
assumes deleted trades would not exist. Real counterfactual needs actual price
at the cap-bar to compute synthetic exit.

Output:
- scripts/m4_5yr_trades_enriched.csv (trades + bar1_close..bar10_close)
- scripts/m4_max_bars_sweep_report.md (per-variant + per-year tables)
- scripts/m4_max_bars_sweep_results.json (structured data)

Per MBS-D-1: reuses scripts/_production_mirror/bars_4h_reconstructor.py for
4H bar synthesis (RTH-only, NYSE calendar aware, early-close handling).

Production reference: market-engine HEAD 9a6f7e1.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import json
import numpy as np
import pandas as pd

from scripts._production_mirror.bars_4h_reconstructor import load_m5, reconstruct_4h


TRADES_CSV = Path("backtest_results/m4_5yr_trades.csv")
OUT_DIR = Path("scripts")
MAX_BARS_VARIANTS = [4, 5, 6, 7, 8, 9, 10]


def _build_4h_bars(ticker: str) -> pd.DataFrame:
    """Load M5 + reconstruct 4H RTH bars (B + C labels), sorted chronologically.

    Returns DataFrame with date_et, bar_label, close (and other OHLCV cols).
    """
    m5 = load_m5(ticker)
    bars = reconstruct_4h(m5, ticker, rth_only=True)
    if bars.empty:
        return bars
    label_order = {"B": 0, "C": 1}
    bars = bars.copy()
    bars["_label_ord"] = bars["bar_label"].map(label_order)
    bars = bars.sort_values(["date_et", "_label_ord"]).reset_index(drop=True)
    return bars.drop(columns=["_label_ord"])


def _walk_forward_bars(
    bars_4h: pd.DataFrame,
    entry_date: pd.Timestamp,
    max_bars: int = 10,
) -> List[Dict]:
    """Walk forward from the first 4H bar of entry_date and record next max_bars.

    Returns list of {bar_idx, date_et, bar_label, close} for offsets 1..max_bars.
    Per spec §0: bar_idx=1 is the first 4H bar AFTER the entry trigger bar.
    Approximation: trigger bar is the first 4H bar of entry_date (could be off
    by 1 if M4 actually entered on the afternoon C bar — see spec assumption A4).
    """
    if bars_4h.empty:
        return []
    entry_d = entry_date.date()
    matching = bars_4h.index[bars_4h["date_et"] == entry_d]
    if len(matching) == 0:
        return []
    start = matching[0]
    walked = []
    for offset in range(1, max_bars + 1):
        bar_pos = start + offset
        if bar_pos >= len(bars_4h):
            break
        row = bars_4h.iloc[bar_pos]
        walked.append(
            {
                "bar_idx": offset,
                "date_et": str(row["date_et"]),
                "bar_label": row["bar_label"],
                "close": float(row["close"]),
            }
        )
    return walked


def enrich_trades_with_bar_by_bar(trades_df: pd.DataFrame) -> pd.DataFrame:
    """Add bar1_close..bar10_close columns to each trade row."""
    enriched = trades_df.copy()
    for n in range(1, 11):
        enriched[f"bar{n}_close"] = np.nan
    enriched["bars_walked"] = 0
    enriched["enrich_status"] = ""

    bars_cache: Dict[str, pd.DataFrame] = {}

    for idx, trade in trades_df.iterrows():
        ticker = trade["ticker"]
        try:
            if ticker not in bars_cache:
                bars_cache[ticker] = _build_4h_bars(ticker)
            bars_4h = bars_cache[ticker]
        except FileNotFoundError:
            enriched.at[idx, "enrich_status"] = f"missing_data:{ticker}"
            continue

        if bars_4h.empty:
            enriched.at[idx, "enrich_status"] = f"empty_bars:{ticker}"
            continue

        entry_date = pd.to_datetime(trade["entry_date"])
        walked = _walk_forward_bars(bars_4h, entry_date, max_bars=10)

        if not walked:
            enriched.at[idx, "enrich_status"] = "no_entry_bar"
            continue

        for bar in walked:
            n = bar["bar_idx"]
            enriched.at[idx, f"bar{n}_close"] = bar["close"]
        enriched.at[idx, "bars_walked"] = len(walked)
        enriched.at[idx, "enrich_status"] = "ok"

    return enriched


def _compute_counterfactual_exit(
    trade: pd.Series,
    max_bars_cap: int,
) -> Optional[float]:
    """Synthetic return_pct if trade's exit is capped at `max_bars_cap` bars.

      - actual bars_held <= cap: passthrough actual return_pct
      - actual bars_held > cap: synthetic exit at bar{cap}_close
      - bar{cap}_close NaN: returns None (data unavailable)
    """
    actual_bars = int(trade["bars_held"])
    if actual_bars <= max_bars_cap:
        return float(trade["return_pct"])

    cap_close_col = f"bar{max_bars_cap}_close"
    if cap_close_col not in trade.index or pd.isna(trade[cap_close_col]):
        return None

    entry_price = float(trade["entry_price"])
    synthetic_exit = float(trade[cap_close_col])
    return (synthetic_exit - entry_price) / entry_price * 100.0


def _aggregate(returns: List[float]) -> Dict:
    rets = np.array(returns)
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    if len(losses) > 0 and losses.sum() != 0:
        pf = wins.sum() / abs(losses.sum())
    else:
        pf = float("inf")
    return {
        "N": len(rets),
        "mean_return": float(rets.mean()),
        "median_return": float(np.median(rets)),
        "total_return": float(rets.sum()),
        "win_rate": float((rets > 0).mean()),
        "PF": None if np.isinf(pf) else float(pf),
        "PF_label": "inf" if np.isinf(pf) else f"{pf:.2f}",
    }


def compute_counterfactual_sweep(enriched: pd.DataFrame) -> Dict[int, Dict]:
    """For each MAX_BARS variant, compute synthetic results across all trades."""
    results: Dict[int, Dict] = {}

    for cap in MAX_BARS_VARIANTS:
        synthetic_returns: List[float] = []
        skipped = 0
        for _, trade in enriched.iterrows():
            if trade.get("enrich_status", "ok") != "ok":
                continue
            ret = _compute_counterfactual_exit(trade, cap)
            if ret is None:
                skipped += 1
                continue
            synthetic_returns.append(ret)

        if not synthetic_returns:
            results[cap] = {"N": 0, "skipped": skipped}
            continue

        agg = _aggregate(synthetic_returns)
        agg["skipped"] = skipped

        # Hard-max savings: count of actual hard_max trades whose synthetic
        # cap-bar return is better (less negative) than actual return.
        hm_mask = enriched["exit_type"] == "hard_max"
        hm_savings = 0.0
        hm_count = 0
        for _, trade in enriched[hm_mask].iterrows():
            if trade.get("enrich_status", "ok") != "ok":
                continue
            synth = _compute_counterfactual_exit(trade, cap)
            if synth is None:
                continue
            actual = float(trade["return_pct"])
            hm_savings += synth - actual
            hm_count += 1
        agg["hard_max_synth_minus_actual_total"] = float(hm_savings)
        agg["hard_max_N"] = hm_count

        results[cap] = agg

    return results


def compute_per_year_sweep(enriched: pd.DataFrame) -> Dict[int, Dict[int, Dict]]:
    """Per-year breakdown: does any year reverse the verdict?"""
    by_year: Dict[int, Dict[int, Dict]] = {}
    for year in sorted(enriched["year"].unique()):
        year_df = enriched[enriched["year"] == year]
        year_results: Dict[int, Dict] = {}
        for cap in MAX_BARS_VARIANTS:
            rets: List[float] = []
            for _, trade in year_df.iterrows():
                if trade.get("enrich_status", "ok") != "ok":
                    continue
                r = _compute_counterfactual_exit(trade, cap)
                if r is None:
                    continue
                rets.append(r)
            if not rets:
                year_results[cap] = {"N": 0}
                continue
            arr = np.array(rets)
            year_results[cap] = {
                "N": len(arr),
                "mean": float(arr.mean()),
                "total": float(arr.sum()),
                "WR": float((arr > 0).mean()),
            }
        by_year[int(year)] = year_results
    return by_year


def write_report(
    sweep: Dict[int, Dict],
    by_year: Dict[int, Dict[int, Dict]],
    n_total: int,
    n_enriched: int,
    out_path: Path,
) -> None:
    lines = [
        "# M4 MAX_BARS Bar-by-Bar Sensitivity Sweep — Report",
        "",
        f"Run date: {datetime.now().isoformat(timespec='seconds')}",
        f"Source: {TRADES_CSV} ({n_total} trades)",
        f"Successfully enriched: {n_enriched} / {n_total} trades",
        f"Variants tested: {MAX_BARS_VARIANTS}",
        "",
        "Counterfactual semantics: trades held within cap pass through with",
        "actual return; trades that actually held longer are re-priced at the",
        "close of the cap-bar (using forward-walked 4H closes from entry_date).",
        "",
        "## Per-MAX_BARS Counterfactual Results",
        "",
        "| MAX_BARS | N | Mean | Median | Total | WR | PF | HardMax Δ (synth-actual) |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for cap in MAX_BARS_VARIANTS:
        r = sweep.get(cap, {})
        if r.get("N", 0) == 0:
            lines.append(f"| {cap} | 0 | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        hm_delta = r.get("hard_max_synth_minus_actual_total", 0.0)
        hm_n = r.get("hard_max_N", 0)
        lines.append(
            f"| {cap} | {r['N']} | {r['mean_return']:+.2f}% | "
            f"{r['median_return']:+.2f}% | {r['total_return']:+.2f}% | "
            f"{r['win_rate']:.1%} | {r['PF_label']} | "
            f"{hm_delta:+.2f}% (N={hm_n}) |"
        )

    lines.extend(["", "## Per-Year Breakdown", ""])
    header = "| Year | " + " | ".join([f"M{c} mean (N)" for c in MAX_BARS_VARIANTS]) + " |"
    sep = "|---|" + "|".join(["---"] * len(MAX_BARS_VARIANTS)) + "|"
    lines.append(header)
    lines.append(sep)
    for year, year_data in sorted(by_year.items()):
        cells = [f"| {year}"]
        for cap in MAX_BARS_VARIANTS:
            d = year_data.get(cap, {})
            n = d.get("N", 0)
            mean = d.get("mean")
            if n == 0 or mean is None:
                cells.append("n/a")
            else:
                tag = " ⚠N<10" if n < 10 else ""
                cells.append(f"{mean:+.2f}% (N={n}){tag}")
        lines.append(" | ".join(cells) + " |")

    lines.extend(
        [
            "",
            "Per Principle #2: any year-bucket with N<10 marked ⚠ is anecdotal.",
            "",
            "## Operator-Actionable Verdict",
            "",
            "Compare per-MAX_BARS total return + per-year stability. Decision rules:",
            "",
            "1. **Keep MAX_BARS=10** — if no other variant produces meaningfully higher"
            " total return AND lower variants don't improve 2022-type bear regime",
            "2. **Lower to MAX_BARS=8** — if 8 produces higher total return AND"
            " maintains positive returns across all years (esp. 2025/2026)",
            "3. **Lower to MAX_BARS=6** — if 6 produces highest total return AND"
            " 2022 bear meaningfully cuts losses without sacrificing 2025 winners",
            "4. **Per-regime tiered MAX_BARS** — if bear-regime years prefer short,"
            " bull-regime years prefer long (would require D6/regime-aware logic)",
            "",
            "**NOTE:** This is research-only. Production change requires DR + quarterly"
            " window per Module 4 Spec §9.",
        ]
    )

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    print("=== M4 MAX_BARS Bar-by-Bar Sweep v1.0 ===")

    trades = pd.read_csv(TRADES_CSV)
    print(f"Loaded {len(trades)} trades from {TRADES_CSV}")

    print("Enriching with bar-by-bar prices...")
    enriched = enrich_trades_with_bar_by_bar(trades)
    n_ok = int((enriched["enrich_status"] == "ok").sum())
    print(f"Enriched OK: {n_ok}/{len(trades)}")

    enriched_path = OUT_DIR / "m4_5yr_trades_enriched.csv"
    enriched.to_csv(enriched_path, index=False)
    print(f"Enriched trades CSV: {enriched_path}")

    print("Running counterfactual sweep...")
    sweep_results = compute_counterfactual_sweep(enriched)
    by_year = compute_per_year_sweep(enriched)

    json_path = OUT_DIR / "m4_max_bars_sweep_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "sweep": sweep_results,
                "by_year": {str(y): yd for y, yd in by_year.items()},
                "n_total": int(len(trades)),
                "n_enriched": n_ok,
                "variants": MAX_BARS_VARIANTS,
            },
            f,
            indent=2,
            default=str,
        )
    print(f"Results JSON: {json_path}")

    report_path = OUT_DIR / "m4_max_bars_sweep_report.md"
    write_report(sweep_results, by_year, len(trades), n_ok, report_path)
    print(f"Report: {report_path}")

    print("\n=== Per-MAX_BARS Summary ===")
    for cap in MAX_BARS_VARIANTS:
        r = sweep_results.get(cap, {})
        if r.get("N", 0) == 0:
            print(f"  MAX_BARS={cap}: insufficient data")
            continue
        print(
            f"  MAX_BARS={cap}: N={r['N']}, mean={r['mean_return']:+.2f}%, "
            f"total={r['total_return']:+.2f}%, WR={r['win_rate']:.1%}, "
            f"PF={r['PF_label']}"
        )


if __name__ == "__main__":
    main()
