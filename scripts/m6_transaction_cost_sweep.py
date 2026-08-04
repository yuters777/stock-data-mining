#!/usr/bin/env python3
"""M6 Transaction-Cost Survival Sweep — spec_2026_05_26_002 v2.

Loss convention (C4): losses = net <= 0 (INCLUSIVE of zero).
This differs from M4's strict < 0 — using < 0 here would make the 0-bps
anchor fail to reproduce the baseline.

Viability threshold (§5 step 6): M6_VIABILITY_PF = 1.0 (break-even).
Re-validated M6 baseline PF is 1.41 (thin edge; 2.0 would be meaningless).
"""
import csv
import hashlib
import json
import math
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = REPO_ROOT / "backtest_results" / "m6_rth_trades_frozen.csv"
BASELINE_PATH = REPO_ROOT / "backtest_results" / "m6_rth_baseline.json"
OUT_CSV = REPO_ROOT / "backtest_results" / "m6_transaction_cost_sweep.csv"
OUT_MD = REPO_ROOT / "backtest_results" / "m6_transaction_cost_sweep.md"

COST_BPS = [0, 1, 3, 5, 10, 20]
M6_VIABILITY_PF = 1.0  # break-even; re-validated baseline PF 1.41 is a thin edge


def ledger_digest(path: Path = LEDGER_PATH) -> str:
    """SHA-256 digest of the ledger file (byte-identity guard)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_gross_returns(path: Path = LEDGER_PATH) -> list:
    """Load return_pct column from frozen ledger. File opened read-only."""
    with path.open(newline='') as f:
        reader = csv.DictReader(f)
        return [float(row['return_pct']) for row in reader]


def compute_row(gross_returns: list, cost_bps: int) -> dict:
    """Compute metric triad for one cost level.

    C4 loss convention: losses = net <= 0 (inclusive of zero).
    C5: 1 bp = 0.01 percentage points. Applied once per trade (round-trip).
    pf_undefined when losses.sum() == 0 — matches _compute_stats behaviour.
    """
    cost_pct = cost_bps * 0.01
    net_returns = [g - cost_pct for g in gross_returns]
    n = len(net_returns)

    wins = [r for r in net_returns if r > 0]
    losses = [r for r in net_returns if r <= 0]  # C4: <= 0 inclusive

    sum_wins = sum(wins)
    sum_losses = sum(losses)  # <= 0; abs used for PF denominator

    pf_undefined = (sum_losses == 0)  # mirrors _compute_stats: if losses.sum()==0 → inf
    if pf_undefined:
        pf = "inf"
    else:
        pf = sum_wins / abs(sum_losses)

    expectancy = sum(net_returns) / n
    win_rate = 100.0 * len(wins) / n

    flipped_to_loss = sum(
        1 for g in gross_returns
        if g > 0 and (g - cost_pct) <= 0  # C4: <= 0 consistent with loss convention
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


def self_check(row: dict, baseline_path: Path = BASELINE_PATH) -> None:
    """§5 step 5: verify 0-bps row reproduces m6_rth_baseline.json. Raises on mismatch."""
    with baseline_path.open() as f:
        anchor = json.load(f)

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
    """§5 step 6: lowest cost where PF <= 1.0 OR expectancy <= 0."""
    for row in rows:
        pf = row["profit_factor"]
        pf_val = math.inf if pf == "inf" else float(pf)
        if pf_val <= M6_VIABILITY_PF or row["expectancy"] <= 0:
            return row["cost_bps"], f"{row['cost_bps']} bps"
    return None, "survives >=20bps"


def run_sweep(
    ledger_path: Path = LEDGER_PATH,
    baseline_path: Path = BASELINE_PATH,
) -> list:
    """Load ledger, compute all cost levels, run 0-bps self-check. Returns rows."""
    gross_returns = load_gross_returns(ledger_path)
    rows = [compute_row(gross_returns, c) for c in COST_BPS]
    self_check(rows[0], baseline_path)
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
        "# M6 Transaction-Cost Survival Sweep",
        "",
        "spec_id: spec_2026_05_26_002  ",
        "input: `backtest_results/m6_rth_trades_frozen.csv` (N=544, frozen read-only)  ",
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
        f"**Break-point (PF ≤ 1.0 OR expectancy ≤ 0):** {break_str}",
        "",
        "## Reading",
        "",
        (
            "M6 is a THIN-EDGE module (re-validated baseline PF 1.41, 27-ticker scope, "
            "2021-2025 epoch): cost erosion is materially more consequential here than for M4. "
            "Expectancy and flipped_to_loss are the load-bearing metrics — "
            "PF approaching 1.0 is the real cliff, not an abstract 2× threshold. "
            f"Break-point (PF ≤ 1.0 or expectancy ≤ 0) first reached at **{break_str}**."
        ),
        "",
        "## Note on thin-edge framing",
        "",
        (
            "At re-validated baseline PF 1.41 (27-ticker, 2021-2025), the M6 edge has limited cost headroom. "
            "Even a few basis points of round-trip cost compress expectancy "
            "significantly. Track flipped_to_loss (previously profitable trades "
            "turned losing by cost) and expectancy approaching zero to understand "
            "where the execution-cost cliff actually lies, not just the headline PF."
        ),
    ]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
