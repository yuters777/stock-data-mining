#!/usr/bin/env python3
"""Generate baselines_2023_2024.json from available local data.

Uses pre-2025 Z3 sessions from Fetched_Data/{TICKER}_data.csv.
Relaxes the canonical 78-bar-per-day requirement to Z3-only completeness,
because the Fetched_Data files contain only partial RTH bars for 2021-2024.

WARNING: This is a LOCAL FALLBACK baseline.  The canonical baseline was
generated on the operator's Windows machine with full 2023-2024 RTH data.
Expected canonical SHA: 661975f5e7e5f061c0fd0221c2b9976a4a0e395affa410a34ee0f12796ae3024

Tickers with fewer than 100 pre-2025 Z3 sessions will receive abstain
compression_score = 0.50 during the event study (per R4 spec).
"""

import hashlib
import json
import math
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

_BASE = Path(__file__).resolve().parent.parent
FETCHED_DATA = _BASE / "Fetched_Data"

UNIVERSE_28 = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA",
    "TSLA", "AMD", "SMCI", "PLTR", "AVGO", "ARM", "TSM",
    "MU", "INTC", "COST",
    "COIN", "MSTR", "MARA",
    "C", "GS", "V", "BA", "JPM",
    "BABA", "JD", "BIDU",
    "SPY",
]


def _load_raw(ticker: str) -> pd.DataFrame | None:
    path = FETCHED_DATA / f"{ticker}_data.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    if "datetime" in df.columns:
        df = df.rename(columns={"datetime": "date"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    df["date_only"] = df["date"].dt.date
    df["hour"] = df["date"].dt.hour
    df["minute"] = df["date"].dt.minute
    df["slot_id"] = ((df["hour"] - 9) * 60 + df["minute"] - 30) // 5
    return df


def _z3_distribution(df: pd.DataFrame) -> list:
    """Compute sorted Z3 activity_raw values from pre-2025 RTH data."""
    pre2025 = df[df["date"].dt.year < 2025].copy()
    if pre2025.empty:
        return []
    rth = pre2025[
        ((pre2025["hour"] == 9) & (pre2025["minute"] >= 30))
        | ((pre2025["hour"] >= 10) & (pre2025["hour"] < 16))
    ]
    z3 = rth[(rth["slot_id"] >= 30) & (rth["slot_id"] <= 47)].copy()
    for col in ("open", "high", "low", "close"):
        z3[col] = pd.to_numeric(z3[col], errors="coerce")
    z3 = z3.dropna(subset=["open", "high", "low", "close"])

    values = []
    for session_date, day in z3.groupby("date_only"):
        if len(day) != 18:
            continue
        day = day.sort_values("date")
        z3_open = float(day.iloc[0]["open"])
        if z3_open <= 0 or math.isnan(z3_open):
            continue
        z3_range = (float(day["high"].max()) - float(day["low"].min())) / z3_open
        z3_avg_abs = float(
            ((day["close"] - day["open"]).abs() / z3_open).mean()
        )
        product = z3_range * z3_avg_abs
        if product <= 0 or math.isnan(product):
            continue
        values.append(math.sqrt(product))
    return sorted(values)


def main(output: str = "baselines_2023_2024.json") -> None:
    accepted, rejected = [], []
    per_zone_distributions: dict = OrderedDict()

    for ticker in UNIVERSE_28:
        if ticker == "ARM":
            rejected.append({"ticker": ticker, "reason": "ipo_sept_2023_excluded_per_spec"})
            print(f"REJECTED {ticker} (ARM: IPO Sept 2023, excluded per spec)")
            continue

        df = _load_raw(ticker)
        if df is None:
            rejected.append({"ticker": ticker, "reason": "file_not_found"})
            print(f"REJECTED {ticker} (no Fetched_Data/{ticker}_data.csv)")
            continue

        values = _z3_distribution(df)
        n = len(values)
        arr = np.array(values, dtype=float) if values else np.array([], dtype=float)

        # Always accept — compression_score returns 0.5 for n < 100 (abstain).
        accepted.append(ticker)
        per_zone_distributions[ticker] = {
            "Z3": {
                "sorted_values": values,
                "sample_size": n,
                "min_value": float(arr.min()) if n > 0 else None,
                "max_value": float(arr.max()) if n > 0 else None,
                "mean_value": float(arr.mean()) if n > 0 else None,
                "std_value": float(arr.std(ddof=0)) if n > 0 else None,
            }
        }
        note = f"n={n}" + (" ← n<100, will abstain" if n < 100 else "")
        print(f"ACCEPTED {ticker}: {note}")

    payload = OrderedDict([
        ("train_window", "2021-2024-partial"),
        ("train_window_requested", "2023-2024"),
        ("baseline_type", "local_fallback"),
        ("computed_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        ("universe_size", len(UNIVERSE_28)),
        ("tickers_accepted", sorted(accepted)),
        ("tickers_rejected", sorted(rejected, key=lambda r: r["ticker"])),
        ("per_slot_stats", {}),
        ("per_zone_distributions", OrderedDict(
            (t, per_zone_distributions[t]) for t in sorted(per_zone_distributions)
        )),
        ("qa_checks", {"note": "local_fallback_qa_not_performed"}),
        ("metadata", {
            "note": (
                "Generated from pre-2025 Z3 sessions in Fetched_Data/*.csv. "
                "The 78-bar RTH completeness requirement is relaxed to Z3-only. "
                "Tickers with n<100 Z3 sessions return abstain score 0.5 during event study. "
                "Canonical SHA: 661975f5e7e5f061c0fd0221c2b9976a4a0e395affa410a34ee0f12796ae3024"
            ),
        }),
    ])

    with open(output, "w") as f:
        json.dump(payload, f, indent=2)

    sha = hashlib.sha256(Path(output).read_bytes()).hexdigest()
    print(f"\nWrote {output}")
    print(f"SHA256 (actual):   {sha}")
    print(f"SHA256 (canonical): 661975f5e7e5f061c0fd0221c2b9976a4a0e395affa410a34ee0f12796ae3024")
    print(f"Accepted: {len(accepted)}/{len(UNIVERSE_28)} tickers")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "baselines_2023_2024.json"
    main(out)
