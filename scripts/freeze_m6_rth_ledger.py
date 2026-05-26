#!/usr/bin/env python3
"""Freeze canonical M6 RTH trade ledger — spec_2026_05_26_002 Step 0.

Imports run_m6_backtest / _compute_stats from m6_backtest_extended and
load_earnings from backtest_utils_extended without modifying those files.

DATA REQUIREMENT (C6):
  Requires Fetched_Data/{TICKER}_m5_extended.csv for all 27 M6 tickers.
  These files must start at 09:30 ET so that build_4h_extended correctly
  computes bar '1' (09:30-13:25) for the RTH gap-entry signal.
  The repo's Fetched_Data/_data.csv files are INCOMPATIBLE — they start
  at 11:00 ET, shifting bar '1' open to 11:00 and producing wrong gaps.
  If _m5_extended.csv files are absent, run_m6_backtest silently skips
  those tickers; the Step-0d self-check catches the resulting N != 378
  and aborts. Obtain the correct extended CSVs on the operator's local
  machine before running this script (see C6 abort_if).
"""
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m6_backtest_extended import run_m6_backtest, _compute_stats
from backtest_utils_extended import load_earnings

REPO_ROOT = Path(__file__).resolve().parents[1]
FETCHED_DATA = REPO_ROOT / "Fetched_Data"
OUT_CSV = REPO_ROOT / "backtest_results" / "m6_rth_trades_frozen.csv"
OUT_JSON = REPO_ROOT / "backtest_results" / "m6_rth_baseline.json"

# Server-locked baseline: module_baselines(module_number=6), engine v95,
# locked 2026-04-16, is_active=true. RTH canonical mode.
M6_SERVER_BASELINE = {'N': 378, 'PF': 1.68, 'WR': 69.3, 'Mean': 1.75}

TRADE_COLUMNS = [
    'ticker', 'entry_date', 'entry_bar', 'entry_price',
    'gap_pct', 'gap_midpoint', 'prior_close',
    'exit_date', 'exit_bar', 'exit_price', 'exit_reason',
    'return_pct', 'hold_bars',
]

_M6_TICKERS = [
    'AAPL', 'AMD', 'AMZN', 'ARM', 'AVGO', 'BA', 'BABA', 'BIDU',
    'C', 'COIN', 'COST', 'GOOGL', 'GS', 'INTC', 'JD', 'JPM',
    'MARA', 'META', 'MSFT', 'MSTR', 'MU', 'NVDA', 'PLTR',
    'SMCI', 'TSLA', 'TSM', 'V',
]


def _check_data_availability() -> None:
    """Warn about missing or incompatible data files before running the backtest.

    Prints diagnostics without aborting; the Step-0d self-check enforces
    the hard gate so any data deficiency is caught there.
    """
    missing_extended = []
    has_incompatible = []
    for ticker in _M6_TICKERS:
        ext_path = FETCHED_DATA / f"{ticker}_m5_extended.csv"
        data_path = FETCHED_DATA / f"{ticker}_data.csv"
        if not ext_path.exists():
            missing_extended.append(ticker)
            if data_path.exists():
                has_incompatible.append(ticker)

    if missing_extended:
        print(
            f"  WARNING: {len(missing_extended)} of {len(_M6_TICKERS)} tickers "
            f"lack _m5_extended.csv: {missing_extended}",
            file=sys.stderr,
        )
    if has_incompatible:
        print(
            "  WARNING: _data.csv files found for some tickers but are INCOMPATIBLE "
            "(start at 11:00 ET; M6 bar '1' needs 09:30 ET open). "
            "Do NOT convert them — obtain proper _m5_extended.csv files.",
            file=sys.stderr,
        )


def _load_earnings_strict() -> dict:
    """Load earnings; abort non-zero if empty or raises (C6 abort_if)."""
    try:
        earnings = load_earnings()
    except Exception as exc:
        print(f"ABORT: load_earnings() raised: {exc}", file=sys.stderr)
        sys.exit(1)
    if not earnings:
        print(
            "ABORT: load_earnings() returned empty dict — earnings exclusion "
            "disabled; trade population would be wrong.",
            file=sys.stderr,
        )
        sys.exit(1)
    return earnings


def _freeze_self_check(stats: dict) -> None:
    """Step 0d: assert stats match server-locked baseline. Raises on mismatch."""
    b = M6_SERVER_BASELINE
    errors = []
    if stats['N'] != b['N']:
        errors.append(f"N: observed={stats['N']}, expected={b['N']}")
    if abs(stats['PF'] - b['PF']) > 0.01:
        errors.append(f"PF: observed={stats['PF']}, expected={b['PF']}")
    if abs(stats['WR'] - b['WR']) > 0.1:
        errors.append(f"WR: observed={stats['WR']}, expected={b['WR']}")
    if abs(stats['Mean'] - b['Mean']) > 0.01:
        errors.append(f"Mean: observed={stats['Mean']}, expected={b['Mean']}")
    if errors:
        raise AssertionError(
            "FREEZE SELF-CHECK FAILED — observed stats do not match "
            "module_baselines server baseline:\n" + "\n".join(errors)
        )


def main() -> None:
    print("Step 0: checking data availability...")
    _check_data_availability()

    print("Step 0b: loading earnings...")
    earnings = _load_earnings_strict()
    print(f"  loaded {len(earnings)} ticker earnings calendars")

    print("Step 0c: running M6 RTH backtest...")
    trades, _ = run_m6_backtest('rth', earnings_dict=earnings)
    stats = _compute_stats(trades)
    print(f"  raw stats: N={stats['N']}, PF={stats['PF']}, WR={stats['WR']}, Mean={stats['Mean']}")

    print("Step 0d: freeze self-check vs server baseline...")
    _freeze_self_check(stats)
    print("  PASS")

    print("Step 0e: writing artifacts...")
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_COLUMNS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(trades)

    baseline = {
        'n': stats['N'],
        'pf': stats['PF'],
        'wr': stats['WR'],
        'mean': stats['Mean'],
        'source': (
            'Step-0d freeze self-check vs module_baselines(module_number=6) '
            'server baseline, engine v95, locked 2026-04-16'
        ),
    }
    OUT_JSON.write_text(json.dumps(baseline, indent=2) + '\n')

    print(f"  written: {OUT_CSV}")
    print(f"  written: {OUT_JSON}")
    print(f"Freeze complete: N={stats['N']}, PF={stats['PF']}, WR={stats['WR']}%, Mean={stats['Mean']}")


if __name__ == '__main__':
    main()
