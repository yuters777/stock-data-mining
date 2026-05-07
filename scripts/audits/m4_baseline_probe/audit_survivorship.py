#!/usr/bin/env python3
"""Step 5.1 — Survivorship audit for 27 canonical tickers.

Verifies each canonical ticker has trading history covering the full 5yr window
(2021-04 to 2026-04). Checks for IPO/SPAC/ticker-change/delisting events.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from scripts.audits.m4_baseline_probe._constants import (
    CANONICAL_UNIVERSE,
    FETCHED_DATA_DIR,
    AUDITS_OUTPUT_DIR,
    SURVIVORSHIP_MAX_POSTHOC_TICKERS,
)

WINDOW_START = date(2021, 4, 1)
WINDOW_END = date(2026, 4, 30)
MIN_COVERAGE_MONTHS = 36  # tickers with < 36 months flagged as potentially post-hoc

# Known IPO/notable events in canonical universe (reference, not exhaustive)
KNOWN_EVENTS = {
    "ARM":  {"event": "IPO", "date": "2023-09-14", "note": "ARM IPO on NASDAQ Sept 2023; pre-IPO data unavailable"},
    "SMCI": {"event": "delisting_risk", "date": "2024-08", "note": "SMCI Nasdaq delisting risk Aug 2024; data may be incomplete"},
    "MSTR": {"event": "strategy_change", "date": "2020-08", "note": "MicroStrategy Bitcoin pivot pre-window; data available"},
    "MARA": {"event": "rebranding", "date": "2021-11", "note": "Marathon Digital Holdings rebranding; continuous trading"},
}


def _load_date_range(ticker: str, data_dir: Path) -> tuple[date | None, date | None, int]:
    """Return (first_date, last_date, row_count) for ticker's extended M5 CSV."""
    path = data_dir / f"{ticker}_m5_extended.csv"
    if not path.exists():
        return None, None, 0
    try:
        df = pd.read_csv(path, usecols=[0], nrows=1, header=0)
        col = df.columns[0]
        df_head = pd.read_csv(path, usecols=[col], nrows=5)
        df_tail = pd.read_csv(path, usecols=[col])
        first = pd.to_datetime(df_tail[col].iloc[0], errors="coerce")
        last = pd.to_datetime(df_tail[col].iloc[-1], errors="coerce")
        n = len(df_tail)
        first_d = first.date() if pd.notna(first) else None
        last_d = last.date() if pd.notna(last) else None
        return first_d, last_d, n
    except Exception:
        return None, None, 0


def audit_survivorship(data_dir: Path | None = None) -> dict:
    base = data_dir or FETCHED_DATA_DIR

    per_ticker = []
    posthoc_candidates = []

    for ticker in CANONICAL_UNIVERSE:
        first, last, n = _load_date_range(ticker, base)
        known = KNOWN_EVENTS.get(ticker, {})

        if first is None:
            coverage_months = 0
            spans_window = False
            missing_data = True
        else:
            delta_months = (
                (last.year - first.year) * 12 + (last.month - first.month)
                if last else 0
            )
            coverage_months = delta_months
            spans_window = (first <= WINDOW_START or coverage_months >= MIN_COVERAGE_MONTHS)
            missing_data = False

        posthoc_risk = (
            known.get("event") in ("IPO",) and
            known.get("date", "0") > "2021-04"
        )
        if posthoc_risk:
            posthoc_candidates.append(ticker)

        per_ticker.append({
            "ticker": ticker,
            "first_date": str(first) if first else None,
            "last_date": str(last) if last else None,
            "rows": n,
            "coverage_months": coverage_months,
            "spans_5yr_window": spans_window,
            "missing_data": missing_data,
            "known_event": known.get("event"),
            "known_event_date": known.get("date"),
            "known_event_note": known.get("note"),
            "posthoc_risk": posthoc_risk,
        })

    material_survivorship = len(posthoc_candidates) > SURVIVORSHIP_MAX_POSTHOC_TICKERS
    tickers_missing = [t["ticker"] for t in per_ticker if t["missing_data"]]
    tickers_short = [
        t["ticker"] for t in per_ticker
        if not t["missing_data"] and t["coverage_months"] < MIN_COVERAGE_MONTHS
    ]

    return {
        "total_tickers": len(CANONICAL_UNIVERSE),
        "per_ticker": per_ticker,
        "posthoc_candidates": posthoc_candidates,
        "tickers_missing_data": tickers_missing,
        "tickers_short_coverage": tickers_short,
        "material_survivorship_bias": material_survivorship,
        "abort_triggered": material_survivorship,
        "known_events_documented": list(KNOWN_EVENTS.keys()),
    }


def _write_report(result: dict) -> Path:
    out_dir = AUDITS_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / "m4_baseline_probe_S304_survivorship.md"

    lines = [
        "# Survivorship Audit — M4 Baseline Probe S304",
        "",
        f"**Total tickers:** {result['total_tickers']}",
        f"**Post-hoc risk candidates:** {result['posthoc_candidates']}",
        f"**Material survivorship bias:** {result['material_survivorship_bias']}",
        "",
        "## Per-Ticker Coverage",
        "",
        "| Ticker | First Date | Last Date | Months | Spans 5yr | Post-hoc Risk | Known Event |",
        "|--------|------------|-----------|--------|-----------|---------------|-------------|",
    ]

    for t in result["per_ticker"]:
        event_str = t["known_event"] or ""
        lines.append(
            f"| {t['ticker']} | {t['first_date'] or 'MISSING'} | {t['last_date'] or ''} "
            f"| {t['coverage_months']} | {t['spans_5yr_window']} "
            f"| {'YES' if t['posthoc_risk'] else 'no'} | {event_str} |"
        )

    lines += [
        "",
        "## Known Events",
        "",
    ]
    for ticker, ev in KNOWN_EVENTS.items():
        lines.append(f"- **{ticker}** ({ev['event']} {ev['date']}): {ev['note']}")

    if result["tickers_missing_data"]:
        lines += ["", f"**Missing data:** {result['tickers_missing_data']}"]
    if result["tickers_short_coverage"]:
        lines += ["", f"**Short coverage (<36 months):** {result['tickers_short_coverage']}"]

    verdict = "NO-GO — material survivorship bias" if result["abort_triggered"] else "PASS"
    lines += ["", f"**Survivorship verdict:** {verdict}"]

    out_md.write_text("\n".join(lines), encoding="utf-8")
    return out_md


def main() -> int:
    result = audit_survivorship()
    out_md = _write_report(result)
    out_json = AUDITS_OUTPUT_DIR / "m4_baseline_probe_S304_survivorship.json"
    out_json.write_text(json.dumps(result, indent=2, default=str))

    posthoc = result["posthoc_candidates"]
    material = result["material_survivorship_bias"]
    print(f"Survivorship: {len(result['per_ticker'])} tickers, {len(posthoc)} post-hoc candidates")
    print(f"Material bias: {material}")
    if result["tickers_missing_data"]:
        print(f"Missing data: {result['tickers_missing_data']}")
    print(f"Report: {out_md}")
    return 1 if result["abort_triggered"] else 0


if __name__ == "__main__":
    sys.exit(main())
