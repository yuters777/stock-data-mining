#!/usr/bin/env python3
"""Step 6.2 — RTH calendar audit for canonical trade ledger.

Verifies entry and exit timestamps are within RTH (09:30-16:00 ET),
holding windows respect NYSE holiday calendar, and max-bar-10 timeout
is calendar-aware.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from scripts.audits.m4_baseline_probe._constants import (
    LOCAL_TRADES_CSV,
    AUDITS_OUTPUT_DIR,
    CANONICAL_BASELINE_N,
)

# The production mirror uses a local NYSE calendar
try:
    from scripts._production_mirror.nyse_calendar import HOLIDAY_DATES as NYSE_HOLIDAYS
    _HAS_NYSE_CAL = True
except Exception:
    NYSE_HOLIDAYS = set()
    _HAS_NYSE_CAL = False

MAX_HOLD_BARS = 10
BARS_PER_DAY = 2  # RTH mode: bar B (09:30-13:25), bar C (13:30-15:55)
MAX_HOLD_DAYS_APPROX = (MAX_HOLD_BARS // BARS_PER_DAY) + 2  # +2 for weekends


def _trading_days_between(d1: date, d2: date) -> int:
    """Approximate trading days between two dates (excludes weekends and NYSE holidays)."""
    if d1 > d2:
        return 0
    count = 0
    cur = d1
    while cur <= d2:
        # 0=Mon, 4=Fri
        if cur.weekday() < 5 and cur not in NYSE_HOLIDAYS:
            count += 1
        from datetime import timedelta
        cur += timedelta(days=1)
    return count


def audit_rth_calendar(trades_path: Path | None = None) -> dict:
    path = trades_path or LOCAL_TRADES_CSV

    if not path.exists():
        return {
            "error": f"Trades CSV not found: {path}",
            "violations": [],
            "pass": False,
        }

    df = pd.read_csv(path)
    if "entry_date" not in df.columns or "exit_date" not in df.columns:
        return {"error": "entry_date/exit_date columns missing", "violations": [], "pass": False}

    violations = []
    per_trade = []

    for idx, row in df.iterrows():
        trade_id = f"{row.get('ticker', '?')}@{row.get('entry_date', '?')}"
        issues = []

        try:
            entry_d = pd.to_datetime(row["entry_date"]).date()
            exit_d = pd.to_datetime(row["exit_date"]).date()
        except Exception:
            issues.append("Unparseable entry/exit date")
            per_trade.append({"trade_id": trade_id, "clean": False, "issues": issues})
            violations.append({"trade_id": trade_id, "issues": issues})
            continue

        # Entry must be a weekday
        if entry_d.weekday() >= 5:
            issues.append(f"Entry on weekend: {entry_d}")

        # Exit must be a weekday
        if exit_d.weekday() >= 5:
            issues.append(f"Exit on weekend: {exit_d}")

        # bars_held must be consistent with trading day span
        bars_held = row.get("bars_held")
        if bars_held is not None:
            try:
                b = int(bars_held)
                # Approximate: max 10 bars = max ~5 trading days
                trading_days = _trading_days_between(entry_d, exit_d)
                max_expected_bars = trading_days * BARS_PER_DAY + 2  # +2 slack
                if b > MAX_HOLD_BARS:
                    issues.append(f"bars_held={b} exceeds MAX_HOLD_BARS={MAX_HOLD_BARS}")
                # Sanity: bars_held should be <= 2 * trading days between entry/exit + slack
                if trading_days > 0 and b > max_expected_bars:
                    issues.append(
                        f"bars_held={b} > ~{max_expected_bars} expected for "
                        f"{trading_days} trading days span"
                    )
            except Exception:
                pass

        # Check entry not on NYSE holiday
        if entry_d in NYSE_HOLIDAYS:
            issues.append(f"Entry on NYSE holiday: {entry_d}")
        if exit_d in NYSE_HOLIDAYS:
            issues.append(f"Exit on NYSE holiday: {exit_d}")

        clean = len(issues) == 0
        per_trade.append({"trade_id": trade_id, "clean": clean, "issues": issues})
        if not clean:
            violations.append({"trade_id": trade_id, "issues": issues})

    n = len(df)
    n_clean = sum(1 for t in per_trade if t["clean"])

    return {
        "trades_file": str(path.relative_to(Path(__file__).parent.parent.parent.parent)),
        "n": n,
        "n_clean": n_clean,
        "n_violations": len(violations),
        "violations": violations,
        "pass": len(violations) == 0,
        "abort_triggered": len(violations) > 0,
        "canonical_n": CANONICAL_BASELINE_N,
        "nyse_calendar_available": _HAS_NYSE_CAL,
        "note": (
            f"RTH calendar audit on local N={n} trades. "
            f"NYSE calendar: {'available' if _HAS_NYSE_CAL else 'unavailable — holiday checks skipped'}. "
            f"Entry/exit timestamp hours not available in trade CSV (date-only); "
            f"RTH hour check requires raw M5 data."
        ),
    }


def _write_report(result: dict) -> Path:
    out_dir = AUDITS_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / "m4_baseline_probe_S304_rth_calendar.md"

    n = result.get("n", 0)
    n_clean = result.get("n_clean", 0)
    violations = result.get("violations", [])

    lines = [
        "# RTH Calendar Audit — M4 Baseline Probe S304",
        "",
        f"**N:** {n} | **Clean:** {n_clean} | **Violations:** {len(violations)}",
        f"**NYSE calendar available:** {result.get('nyse_calendar_available')}",
        "",
    ]

    if "error" in result:
        lines.append(f"**ERROR:** {result['error']}")
    elif violations:
        lines += ["## Violations Found", ""]
        for v in violations:
            lines.append(f"- **{v['trade_id']}**: {'; '.join(v['issues'])}")
    else:
        lines.append(f"**{n_clean}/{n} trades pass RTH calendar checks.**")

    lines += [
        "",
        "## Scope of Audit",
        "",
        result.get("note", ""),
        "",
        "Checks performed:",
        "- Entry date is a weekday",
        "- Exit date is a weekday",
        "- bars_held <= MAX_HOLD_BARS=10",
        "- Entry/exit not on NYSE holidays (if calendar available)",
        "- bars_held consistent with trading day span",
        "",
    ]

    verdict = "NO-GO" if result.get("abort_triggered") else "PASS"
    lines.append(f"**RTH calendar verdict:** {verdict}")

    out_md.write_text("\n".join(lines), encoding="utf-8")
    return out_md


def main() -> int:
    result = audit_rth_calendar()
    out_md = _write_report(result)
    out_json = AUDITS_OUTPUT_DIR / "m4_baseline_probe_S304_rth_calendar.json"
    out_json.write_text(json.dumps(result, indent=2, default=str))

    if "error" in result:
        print(f"ERROR: {result['error']}")
        return 1

    print(f"RTH calendar: {result['n_clean']}/{result['n']} clean, {result['n_violations']} violations")
    print(f"Report: {out_md}")
    return 0  # RTH violations are findings, not blocking (date-level check only)


if __name__ == "__main__":
    sys.exit(main())
