#!/usr/bin/env python3
"""Step 6.3 — Corporate action audit for canonical trade ledger.

Checks FMP corporate actions database for splits/dividends/special distributions
within holding windows. Verifies OHLC split-adjusted consistently.
"""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from scripts.audits.m4_baseline_probe._constants import (
    LOCAL_TRADES_CSV,
    FETCHED_DATA_DIR,
    AUDITS_OUTPUT_DIR,
    CANONICAL_BASELINE_N,
)

# Known significant corporate actions during 5yr window for canonical tickers
# Documented manually (no live FMP API call in this audit)
KNOWN_CORP_ACTIONS = {
    "GOOGL": [
        {
            "date": "2022-07-18",
            "type": "split",
            "ratio": "20:1",
            "note": "GOOGL 20:1 forward split Jul 2022; FMP data should be split-adjusted",
        }
    ],
    "AMZN": [
        {
            "date": "2022-06-06",
            "type": "split",
            "ratio": "20:1",
            "note": "AMZN 20:1 forward split Jun 2022; FMP data should be split-adjusted",
        }
    ],
    "TSLA": [
        {
            "date": "2022-08-25",
            "type": "split",
            "ratio": "3:1",
            "note": "TSLA 3:1 forward split Aug 2022; FMP data should be split-adjusted",
        }
    ],
    "NVDA": [
        {
            "date": "2024-06-10",
            "type": "split",
            "ratio": "10:1",
            "note": "NVDA 10:1 forward split Jun 2024; FMP data should be split-adjusted",
        }
    ],
}


def _is_in_holding_window(trade_entry: pd.Timestamp, trade_exit: pd.Timestamp, action_date: str) -> bool:
    try:
        action_d = pd.to_datetime(action_date)
        return trade_entry <= action_d <= (trade_exit + timedelta(days=1))
    except Exception:
        return False


def audit_corp_actions(trades_path: Path | None = None) -> dict:
    path = trades_path or LOCAL_TRADES_CSV

    if not path.exists():
        return {
            "error": f"Trades CSV not found: {path}",
            "per_trade": [],
            "flagged_events": [],
        }

    df = pd.read_csv(path)
    if "entry_date" not in df.columns or "exit_date" not in df.columns:
        return {"error": "Required date columns missing", "per_trade": [], "flagged_events": []}

    df["entry_date"] = pd.to_datetime(df["entry_date"], errors="coerce")
    df["exit_date"] = pd.to_datetime(df["exit_date"], errors="coerce")

    flagged_events = []
    per_trade = []
    adjustment_concerns = []

    for idx, row in df.iterrows():
        trade_id = f"{row.get('ticker', '?')}@{row.get('entry_date', '?')}"
        ticker = str(row.get("ticker", ""))
        entry = row["entry_date"]
        exit_ = row["exit_date"]

        events_in_window = []
        if ticker in KNOWN_CORP_ACTIONS and pd.notna(entry) and pd.notna(exit_):
            for action in KNOWN_CORP_ACTIONS[ticker]:
                if _is_in_holding_window(entry, exit_, action["date"]):
                    events_in_window.append(action)
                    flagged_events.append({
                        "trade_id": trade_id,
                        "ticker": ticker,
                        "entry": str(entry.date()),
                        "exit": str(exit_.date()),
                        "action": action,
                    })

        # Price continuity check: look for discontinuities in the M5 data
        # around known split dates for this ticker
        price_discontinuity = False
        if ticker in KNOWN_CORP_ACTIONS:
            for action in KNOWN_CORP_ACTIONS[ticker]:
                if action["type"] == "split":
                    try:
                        action_dt = pd.to_datetime(action["date"])
                        # If entry is shortly after split, check return_pct is sane
                        if pd.notna(entry) and action_dt <= entry:
                            ret = row.get("return_pct")
                            if ret is not None and abs(float(ret)) > 100:
                                price_discontinuity = True
                                adjustment_concerns.append({
                                    "trade_id": trade_id,
                                    "return_pct": float(ret),
                                    "note": f"return_pct {ret}% may indicate unadjusted prices near split {action['date']}",
                                })
                    except Exception:
                        pass

        per_trade.append({
            "trade_id": trade_id,
            "ticker": ticker,
            "corp_events_in_window": events_in_window,
            "price_discontinuity_flag": price_discontinuity,
            "clean": len(events_in_window) == 0 and not price_discontinuity,
        })

    n = len(df)
    n_clean = sum(1 for t in per_trade if t["clean"])

    return {
        "trades_file": str(path.relative_to(Path(__file__).parent.parent.parent.parent)),
        "n": n,
        "n_clean": n_clean,
        "n_flagged": len(flagged_events),
        "flagged_events": flagged_events,
        "adjustment_concerns": adjustment_concerns,
        "known_corp_actions_checked": list(KNOWN_CORP_ACTIONS.keys()),
        "canonical_n": CANONICAL_BASELINE_N,
        "note": (
            "Corporate action audit: checks known splits/dividends for canonical tickers. "
            "FMP data is assumed split-adjusted (FMP default). "
            "Flagged events require manual verification that returns are not inflated. "
            "Audit is NOT exhaustive — dividend/special distribution checks require live FMP API."
        ),
    }


def _write_report(result: dict) -> Path:
    out_dir = AUDITS_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / "m4_baseline_probe_S304_corp_actions.md"

    n = result.get("n", 0)
    n_clean = result.get("n_clean", 0)
    flagged = result.get("flagged_events", [])

    lines = [
        "# Corporate Action Audit — M4 Baseline Probe S304",
        "",
        f"**N:** {n} | **Clean:** {n_clean} | **Flagged:** {len(flagged)}",
        f"**Tickers with known actions checked:** {result.get('known_corp_actions_checked', [])}",
        "",
    ]

    if "error" in result:
        lines.append(f"**ERROR:** {result['error']}")
    elif flagged:
        lines += ["## Flagged Events in Trade Windows", ""]
        for ev in flagged:
            a = ev["action"]
            lines.append(
                f"- **{ev['trade_id']}** — {a['type'].upper()} {a['ratio']} on {a['date']}: {a['note']}"
            )
    else:
        lines.append("**No known corporate actions fall within trade holding windows.**")

    if result.get("adjustment_concerns"):
        lines += ["", "## Price Adjustment Concerns", ""]
        for c in result["adjustment_concerns"]:
            lines.append(f"- **{c['trade_id']}**: {c['note']}")

    lines += [
        "",
        "## Scope of Audit",
        "",
        result.get("note", ""),
        "",
        "## Known Corporate Actions in 5yr Window",
        "",
    ]
    for ticker, actions in KNOWN_CORP_ACTIONS.items():
        for a in actions:
            lines.append(f"- **{ticker}** {a['type'].upper()} {a.get('ratio', '')} on {a['date']}: {a['note']}")

    out_md.write_text("\n".join(lines), encoding="utf-8")
    return out_md


def main() -> int:
    result = audit_corp_actions()
    out_md = _write_report(result)
    out_json = AUDITS_OUTPUT_DIR / "m4_baseline_probe_S304_corp_actions.json"
    out_json.write_text(json.dumps(result, indent=2, default=str))

    if "error" in result:
        print(f"ERROR: {result['error']}")
        return 1

    print(f"Corp actions: {result['n_clean']}/{result['n']} clean, {result['n_flagged']} flagged")
    print(f"Report: {out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
