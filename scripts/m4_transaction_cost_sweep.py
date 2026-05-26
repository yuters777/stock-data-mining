#!/usr/bin/env python3
"""M4 Transaction-Cost Survival Sweep — spec_2026_05_26_001.

C6 discovery: scripts/_metrics.py.compute_metrics() found but NOT reused.
  Reason 1 (C7): _metrics.py imports numpy; C7 mandates stdlib-only.
  Reason 2 (definition mismatch): _metrics.py uses arr <= 0 for losses;
    spec §5 step 4 defines losses as net < 0 (strict).
Implementing per explicit §5 step-4 formulas.
"""
import csv
import hashlib
import json
import math
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = REPO_ROOT / "backtest_results" / "m4_5yr_trades_D6.csv"
SUMMARY_PATH = REPO_ROOT / "backtest_results" / "m4_5yr_summary_D6.json"
OUT_CSV = REPO_ROOT / "backtest_results" / "m4_transaction_cost_sweep.csv"
OUT_MD = REPO_ROOT / "backtest_results" / "m4_transaction_cost_sweep.md"

COST_BPS = [0, 1, 3, 5, 10, 20]
VIABILITY_PF_THRESHOLD = 2.0


def ledger_digest(path: Path = LEDGER_PATH) -> str:
    """SHA-256 digest of the ledger file (byte-identity guard)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_gross_returns(path: Path = LEDGER_PATH) -> list:
    """Load return_pct column from ledger CSV. File opened read-only."""
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        return [float(row["return_pct"]) for row in reader]


def compute_row(gross_returns: list, cost_bps: int) -> dict:
    """Compute metric triad for one cost level per §5 step 4.

    C5: 1 bp = 0.01 percentage points. Cost applied once per row (round-trip total).
    """
    cost_pct = cost_bps * 0.01
    net_returns = [g - cost_pct for g in gross_returns]
    n = len(net_returns)

    wins = [r for r in net_returns if r > 0]
    losses = [r for r in net_returns if r < 0]  # strict < 0 per §5 step 4

    sum_wins = sum(wins)
    sum_losses_abs = abs(sum(losses))

    pf_undefined = len(losses) == 0
    if pf_undefined:
        pf = "inf"
    else:
        pf = sum_wins / sum_losses_abs

    expectancy = sum(net_returns) / n
    win_rate = 100.0 * len(wins) / n

    flipped_to_loss = sum(
        1 for g in gross_returns
        if g > 0 and (g - cost_pct) <= 0
    )

    return {
        "cost_bps": cost_bps,
        "n": n,
        "profit_factor": pf,
        "pf_undefined": pf_undefined,
        "expectancy": expectancy,
        "win_rate": win_rate,
        "flipped_to_loss": flipped_to_loss,
    }


def self_check(row: dict, summary_path: Path = SUMMARY_PATH) -> None:
    """§5 step 5: verify 0-bps row reproduces frozen baseline. Raises on mismatch."""
    with summary_path.open() as f:
        anchor = json.load(f)["overall"]

    errors = []
    if row["n"] != anchor["n"]:
        errors.append(f"N: observed={row['n']}, expected={anchor['n']}")
    pf = row["profit_factor"]
    if isinstance(pf, float) and abs(pf - anchor["pf"]) > 0.01:
        errors.append(f"PF: observed={pf:.6f}, expected={anchor['pf']}")
    if abs(row["expectancy"] - anchor["mean"]) > 0.01:
        errors.append(f"expectancy: observed={row['expectancy']:.6f}, expected={anchor['mean']}")
    if abs(row["win_rate"] - anchor["wr"]) > 0.1:
        errors.append(f"win_rate: observed={row['win_rate']:.4f}, expected={anchor['wr']}")

    if errors:
        raise AssertionError(
            "0-bps self-check FAILED — frozen baseline not reproduced:\n"
            + "\n".join(errors)
        )


def find_break_point(rows: list) -> tuple:
    """§5 step 6: lowest cost where PF < 2.0 OR expectancy <= 0."""
    for row in rows:
        pf = row["profit_factor"]
        pf_val = math.inf if pf == "inf" else float(pf)
        if pf_val < VIABILITY_PF_THRESHOLD or row["expectancy"] <= 0:
            return row["cost_bps"], f"{row['cost_bps']} bps"
    return None, "survives >=20bps"


def run_sweep(
    ledger_path: Path = LEDGER_PATH,
    summary_path: Path = SUMMARY_PATH,
) -> list:
    """Load ledger, compute all cost levels, run self-check. Returns row list."""
    gross_returns = load_gross_returns(ledger_path)
    rows = [compute_row(gross_returns, c) for c in COST_BPS]
    self_check(rows[0], summary_path)
    return rows


def _write_csv(rows: list) -> None:
    fieldnames = [
        "cost_bps", "n", "profit_factor", "pf_undefined",
        "expectancy", "win_rate", "flipped_to_loss",
    ]
    with OUT_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out = dict(row)
            pf = out["profit_factor"]
            out["profit_factor"] = "inf" if pf == "inf" else f"{float(pf):.4f}"
            out["expectancy"] = f"{out['expectancy']:.4f}"
            out["win_rate"] = f"{out['win_rate']:.2f}"
            writer.writerow(out)


def _write_md(rows: list, break_str: str) -> None:
    lines = [
        "# M4 Transaction-Cost Survival Sweep",
        "",
        "spec_id: spec_2026_05_26_001  ",
        "input: `backtest_results/m4_5yr_trades_D6.csv` (N=44, frozen read-only)  ",
        "",
        "| cost_bps | n | profit_factor | pf_undefined | expectancy | win_rate | flipped_to_loss |",
        "|---:|---:|---:|:---:|---:|---:|---:|",
    ]
    for row in rows:
        pf = row["profit_factor"]
        pf_str = "inf" if pf == "inf" else f"{float(pf):.4f}"
        lines.append(
            f"| {row['cost_bps']} | {row['n']} | {pf_str} | {row['pf_undefined']} "
            f"| {row['expectancy']:.4f} | {row['win_rate']:.2f} | {row['flipped_to_loss']} |"
        )
    lines += [
        "",
        f"**Break-point (PF < 2.0 OR expectancy ≤ 0):** {break_str}",
        "",
        "## Reading",
        "",
        (
            "At 0 bps the ledger exactly reproduces the D6 frozen baseline "
            "(PF 8.4075, expectancy 6.8716, WR 86.36%, N=44). "
            "Round-trip cost degrades profit factor and expectancy monotonically; "
            f"the viability threshold (PF < 2.0 or expectancy ≤ 0) is first breached at **{break_str}**."
        ),
        "",
        "## Caveat — N=44 and sub-sample instability",
        "",
        (
            "At N=44, profit factor is dominated by a handful of large 2025 winners. "
            "The 2022 sub-sample alone shows mean −4.94% and WR 16.67%, "
            "illustrating that the aggregate PF can look cost-robust while the underlying edge is regime-dependent. "
            "**EXPECTANCY and flipped_to_loss are the load-bearing metrics, not PF.** "
            "Track expectancy approaching zero and flipped_to_loss growing to understand "
            "where the actual execution-cost cliff lies."
        ),
    ]
    OUT_MD.write_text("\n".join(lines) + "\n")


def write_outputs(rows: list) -> None:
    """Write CSV and markdown outputs (§5 steps 7-8)."""
    _write_csv(rows)
    _, break_str = find_break_point(rows)
    _write_md(rows, break_str)


def _print_table(rows: list, break_str: str) -> None:
    header = (
        f"{'cost_bps':>8}  {'n':>4}  {'profit_factor':>13}  "
        f"{'pf_undef':>8}  {'expectancy':>11}  {'win_rate':>9}  {'flipped':>8}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        pf = row["profit_factor"]
        pf_str = f"{'inf':>13}" if pf == "inf" else f"{float(pf):>13.4f}"
        print(
            f"{row['cost_bps']:>8}  {row['n']:>4}  {pf_str}  "
            f"{str(row['pf_undefined']):>8}  {row['expectancy']:>11.4f}  "
            f"{row['win_rate']:>9.2f}  {row['flipped_to_loss']:>8}"
        )
    print(f"\nBreak-point: {break_str}")


def main() -> None:
    rows = run_sweep()
    write_outputs(rows)
    _, break_str = find_break_point(rows)
    _print_table(rows, break_str)


if __name__ == "__main__":
    main()
