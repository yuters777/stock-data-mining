"""Harness validation orchestrator — runs all 3 module mirrors and compares
to canonical baselines. Acceptance per spec §0:
  M4: N 42-52, PF ≥18.0     — ≥1 of 2 PASS
  M6: N 359-397, PF ≥1.55   — BOTH PASS
  M7: N 160-216, PF ≥1.5    — ≥1 of 2 PASS

Harness validated when: 5/6 metrics PASS (M6 BOTH + M4 ≥1 + M7 ≥1).
Below this → triage, not validation.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# Allow running as a module: python -m scripts.run_harness_validation
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts._production_mirror.module4_mirror import run_module4_mirror_backtest
from scripts._production_mirror.module6_mirror import run_module6_mirror_backtest
from scripts._production_mirror.module7_mirror import run_module7_mirror_backtest
from scripts._production_mirror.override_4_mirror import load_vix_daily
from scripts._metrics import compute_metrics

# Canonical baselines — Day 41 post-mortem
CANONICAL = {
    "M4": {"N": 47, "PF": 21.38, "N_min": 42, "N_max": 52, "PF_min": 18.0},
    "M6": {"N": 378, "PF": 1.68, "N_min": 359, "N_max": 397, "PF_min": 1.55},
    "M7": {"N": 188, "PF": 1.72, "N_min": 160, "N_max": 216, "PF_min": 1.5},
}

UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA",
    "TSLA", "AMD", "SMCI", "PLTR", "AVGO", "ARM", "TSM",
    "MU", "INTC", "COST",
    "COIN", "MSTR", "MARA",
    "C", "GS", "V", "BA", "JPM",
    "BABA", "JD", "BIDU",
]  # 27 equity tickers (excludes SPY/VIXY/BTC/ETH per Module 4/6/7 scope)

DATA_ROOT = Path(__file__).resolve().parent.parent / "Fetched_Data"


def main() -> None:
    print("=== Harness Validation v1.0 ===")
    print(f"Universe: {len(UNIVERSE)} tickers")

    # Load shared data
    vix_df = load_vix_daily()
    print(f"VIX rows loaded: {len(vix_df)} (HARN-D-8: VXVCLS.csv)")

    # Try to load earnings calendar; fall back to empty (HARN-D-9)
    earnings_path = DATA_ROOT / "earnings_calendar.csv"
    if earnings_path.exists():
        earnings_df = pd.read_csv(earnings_path)
    else:
        print("WARNING: earnings_calendar.csv not found — using empty DataFrame (HARN-D-9)")
        earnings_df = pd.DataFrame({"ticker": [], "earnings_date": pd.to_datetime([])})

    date_range = (date(2021, 4, 28), date(2026, 4, 28))
    results: dict = {}

    # M4 (no earnings filter per Day 7 standing policy)
    print("\n--- M4 Mean Reversion ---")
    m4_trades = run_module4_mirror_backtest(UNIVERSE, date_range, 0, earnings_df, vix_df)
    m4_metrics = compute_metrics([t["return_pct"] for t in m4_trades])
    results["M4"] = {"N": len(m4_trades), "PF": m4_metrics["PF"]}
    print(f"  N={len(m4_trades)}, PF={m4_metrics['PF']:.2f}")

    # M6 (±1d earnings filter)
    print("\n--- M6 No-News Shock ---")
    m6_trades = run_module6_mirror_backtest(UNIVERSE, date_range, 1, earnings_df, vix_df, m4_trades=m4_trades)
    m6_metrics = compute_metrics([t["return_pct"] for t in m6_trades])
    results["M6"] = {"N": len(m6_trades), "PF": m6_metrics["PF"]}
    print(f"  N={len(m6_trades)}, PF={m6_metrics['PF']:.2f}")

    # M7 (±6d earnings filter, requires M4+M6 trade tables)
    print("\n--- M7 RS Leader Pullback ---")
    m7_trades = run_module7_mirror_backtest(
        UNIVERSE,
        date_range,
        6,
        earnings_df,
        vix_df,
        m4_trades=m4_trades,
        m6_trades=m6_trades,
    )
    m7_metrics = compute_metrics([t["return_pct"] for t in m7_trades])
    results["M7"] = {"N": len(m7_trades), "PF": m7_metrics["PF"]}
    print(f"  N={len(m7_trades)}, PF={m7_metrics['PF']:.2f}")

    # Validation report
    print("\n=== Acceptance ===")
    pass_count = 0
    m6_both_pass = False
    for mod in ("M4", "M6", "M7"):
        c = CANONICAL[mod]
        r = results[mod]
        n_pass = c["N_min"] <= r["N"] <= c["N_max"]
        pf_pass = r["PF"] >= c["PF_min"]
        n_str = "✅" if n_pass else "❌"
        pf_str = "✅" if pf_pass else "❌"
        print(
            f"  {mod}: N={r['N']} {n_str} ({c['N_min']}-{c['N_max']})  "
            f"PF={r['PF']:.2f} {pf_str} (≥{c['PF_min']})"
        )
        if n_pass:
            pass_count += 1
        if pf_pass:
            pass_count += 1
        if mod == "M6" and n_pass and pf_pass:
            m6_both_pass = True

    print(f"\nPASS: {pass_count}/6")
    if pass_count >= 5 and m6_both_pass:
        print("✅ HARNESS VALIDATED")
    else:
        print("❌ HARNESS NOT VALIDATED — triage required")
        if not m6_both_pass:
            print("  → M6 anchor failed (both metrics required)")


if __name__ == "__main__":
    main()
