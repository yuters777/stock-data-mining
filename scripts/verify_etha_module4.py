#!/usr/bin/env python3
"""
ETHA Module 4 Cross-Verification Script

Compiles engine MCP 4H indicator snapshots, compares against TradingView,
and checks all Module 4 gates for the March 25-27 2026 window.

NOTE: Independent Alpha Vantage M5 pipeline could NOT be executed because
outbound HTTP to alphavantage.co and finance.yahoo.com is blocked in this
environment. This script uses engine MCP data as the primary data source
and documents the cross-verification findings.
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]

# ══════════════════════════════════════════════════════════════════════
# ENGINE MCP DATA (collected via market_get_ticker_context / get_indicators)
# Each row = one historical snapshot at the END of a trading day
# ══════════════════════════════════════════════════════════════════════

ENGINE_4H_SNAPSHOTS = [
    # date, bar_count, bar_time_et, last_price, rsi14, ema9, ema21, ce_state, vix_level
    ("2026-03-20", 17, "13:30", 16.26, 55.84, 16.45, None,  "LONG",  None),
    ("2026-03-23", 18, "13:30", 16.28, 56.05, 16.42, None,  "LONG",  None),
    ("2026-03-24", 19, "13:30", 16.19, 54.79, 16.37, None,  "LONG",  None),
    ("2026-03-25", 21, "13:30", 16.32, 56.12, 16.36, 16.33, "LONG",  None),
    ("2026-03-26", 22, "13:30", 15.66, 47.02, 16.22, 16.27, "SHORT", 27.42),
    ("2026-03-27", 24, "13:30", 15.01, 40.46, 15.78, 16.04, "SHORT", None),
]

# Engine Module4 state (same at ALL snapshots — FROZEN)
ENGINE_MODULE4_FROZEN = {
    "down_streak": 0,
    "v2_down_streak": 0,
    "trigger_active": False,
    "v2_trigger_active": False,
    "v2_prev_close": 14.9501,  # stale initialization artifact
    "rsi_distance_to_gate": 5.46,  # frozen — not updating
}

# VIX data from engine override state
ENGINE_VIX = {
    date(2026, 3, 26): 27.42,  # from override vix_level at 17:30 UTC
    # Note: 28.06 appeared at 20:00 UTC query (intraday update)
}

# FRED VIX data (repo file, through 2026-03-12)
FRED_VIX_LATE = {
    date(2026, 3, 6): 29.49,
    date(2026, 3, 9): 25.50,
    date(2026, 3, 10): 24.93,
    date(2026, 3, 11): 24.23,
    date(2026, 3, 12): 27.29,
}

# TradingView reference values
TV_RSI = {
    "2026-03-26 09:30": 37.39,  # from 4H chart screenshot, purple RSI line
}


def main():
    print("=" * 80)
    print("ETHA MODULE 4 CROSS-VERIFICATION REPORT")
    print("Date: 2026-03-30  |  Source: Engine MCP + TradingView")
    print("=" * 80)

    # ── DATA AVAILABILITY ASSESSMENT ──
    print("\n## DATA SOURCE STATUS")
    print("-" * 80)
    print("  Alpha Vantage M5 pipeline:  BLOCKED (proxy 403 on alphavantage.co)")
    print("  Yahoo Finance (yfinance):   BLOCKED (proxy 403 on query1.finance.yahoo.com)")
    print("  Google Finance:             BLOCKED (proxy 403)")
    print("  Engine MCP (4H indicators): AVAILABLE — used as primary source")
    print("  Engine MCP (Module 4):      AVAILABLE but FROZEN (bug identified)")
    print("  TradingView (manual):       AVAILABLE — reference values from screenshot")
    print("  FRED VIX (repo cache):      AVAILABLE through 2026-03-12 only")

    # ── ENGINE BAR COUNT ANALYSIS ──
    print("\n\n## ENGINE 4H BAR INGESTION ANALYSIS")
    print("-" * 80)
    print(f"{'Date':<14} {'Bar Count':>10} {'Delta':>7} {'Expected':>9} {'Status':<15} {'Price':>8} {'RSI(14)':>8}")
    print("-" * 80)

    prev_count = None
    for row in ENGINE_4H_SNAPSHOTS:
        d, count, _, price, rsi, *_ = row
        delta = count - prev_count if prev_count else "—"
        # Expected: 2 bars/day (AM+PM), except first day
        if prev_count is None:
            expected = "—"
            status = "baseline"
        else:
            d_obj = pd.Timestamp(d)
            prev_d = pd.Timestamp(ENGINE_4H_SNAPSHOTS[ENGINE_4H_SNAPSHOTS.index(row) - 1][0])
            trading_days = np.busday_count(prev_d.date(), d_obj.date())
            expected = trading_days * 2
            if delta == expected:
                status = "OK"
            elif delta < expected:
                status = f"MISSING {expected - delta} bar(s)"
            else:
                status = f"EXTRA {delta - expected}"

        print(f"{d:<14} {count:>10} {str(delta):>7} {str(expected):>9} {status:<15} {price:>8.2f} {rsi:>8.2f}")
        prev_count = count

    print()
    print("  FINDING: Bar ingestion is INCOMPLETE for ETHA.")
    print("  - Mar 23 (Mon): only +1 bar (expected +2 for Mon AM+PM)")
    print("  - Mar 24 (Tue): only +1 bar (expected +2)")
    print("  - Mar 26 (Thu): only +1 bar (expected +2 — PM bar missing)")
    print("  - Total: 24 bars in 8 trading days. Expected: ~16 bars + initial = ~33")
    print("  - RSI(14) warmup requires 15 bars. With only 24 total and missing bars,")
    print("    the RSI values are computed from an incomplete/short series.")

    # ── TABLE 1: 4H Indicator Timeline ──
    print("\n\n" + "=" * 120)
    print("TABLE 1: ENGINE 4H INDICATOR SNAPSHOTS (March 20-27)")
    print("=" * 120)
    print(f"{'Date':<12} {'Bar ET':>8} {'Bars':>5} {'Price':>8} {'RSI(14)':>8} {'EMA9':>8} {'EMA21':>8} {'CE':>6} {'VIX':>8}")
    print("-" * 120)

    for row in ENGINE_4H_SNAPSHOTS:
        d, count, bar_t, price, rsi, ema9, ema21, ce, vix = row
        ema9_s = f"{ema9:.2f}" if ema9 else "—"
        ema21_s = f"{ema21:.2f}" if ema21 else "—"
        vix_s = f"{vix:.2f}" if vix else "—"
        print(f"{d:<12} {bar_t:>8} {count:>5} {price:>8.2f} {rsi:>8.2f} {ema9_s:>8} {ema21_s:>8} {ce:>6} {vix_s:>8}")

    # ── TABLE 2: RSI Comparison ──
    print("\n\n" + "=" * 110)
    print("TABLE 2: RSI COMPARISON — Engine vs TradingView")
    print("=" * 110)
    print(f"{'Date':<12} {'Bar ET':>8} {'RSI (Engine)':>13} {'RSI (TV)':>10} {'Delta':>8} {'Notes'}")
    print("-" * 110)

    comparisons = [
        ("2026-03-20", "13:30", 55.84, None,  "Pre-window baseline"),
        ("2026-03-23", "13:30", 56.05, None,  "Monday"),
        ("2026-03-24", "13:30", 54.79, None,  ""),
        ("2026-03-25", "13:30", 56.12, None,  ""),
        ("2026-03-26", "13:30", 47.02, 37.39, "TV value at AM bar (09:30); engine at PM bar (13:30)?"),
        ("2026-03-27", "13:30", 40.46, None,  "Lowest engine RSI in window"),
    ]

    for d, bt, eng_rsi, tv_rsi, notes in comparisons:
        tv_s = f"{tv_rsi:.2f}" if tv_rsi else "—"
        delta_s = f"{eng_rsi - tv_rsi:+.2f}" if tv_rsi else "—"
        print(f"{d:<12} {bt:>8} {eng_rsi:>13.2f} {tv_s:>10} {delta_s:>8}  {notes}")

    print()
    print("  CRITICAL FINDING: Engine RSI (47.02) vs TradingView RSI (37.39)")
    print("  Delta = +9.63 points. Possible causes:")
    print("  1. BAR MISMATCH: TV shows RSI at 09:30 AM bar; engine snaps to 13:30 PM bar")
    print("     The AM bar close would have a LOWER price (more of the selloff captured)")
    print("     while the PM bar is the NEXT bar with potentially different RSI")
    print("  2. WARMUP DIFFERENCE: Engine has only 22 bars (RSI computed from 8 actual")
    print("     price changes after warmup). TradingView has full history since ETHA IPO")
    print("     (July 2024 = ~340+ 4H bars), giving much more stable RSI.")
    print("  3. MISSING BARS: Engine is missing bars on some days (see Table 1),")
    print("     which corrupts the RSI series by skipping price deltas.")
    print("  4. BAR BOUNDARIES: If engine's 4H bars have different OHLC due to")
    print("     M5 data quality issues, RSI inputs would differ.")

    # ── TABLE 3: Module 4 Gate Check ──
    print("\n\n" + "=" * 110)
    print("TABLE 3: MODULE 4 GATE CHECK (March 25-27)")
    print("=" * 110)

    # Using engine data for what we have + TV RSI for the key bar
    gate_rows = [
        # date, bar_time, engine_rsi, tv_rsi, engine_price, vix_prior_close
        ("2026-03-25", "13:30", 56.12, None,   16.32, None),
        ("2026-03-26", "09:30", None,   37.39,  None,  27.42),  # TV bar - no engine AM data
        ("2026-03-26", "13:30", 47.02, None,   15.66, 27.42),
        ("2026-03-27", "13:30", 40.46, None,   15.01, None),   # VIX unknown for Mar 27
    ]

    print(f"{'Date':<12} {'Bar ET':>8} {'RSI Source':>12} {'RSI':>8} {'RSI<35?':>8} {'VIX':>8} {'VIX>=25?':>8} {'Streak':>8} {'ALL?':>6}")
    print("-" * 110)

    for d, bt, eng_r, tv_r, price, vix in gate_rows:
        rsi = tv_r if tv_r else eng_r
        rsi_src = "TV" if tv_r else "Engine"
        rsi_s = f"{rsi:.2f}" if rsi else "N/A"
        rsi_pass = rsi is not None and rsi < 35
        vix_s = f"{vix:.2f}" if vix else "N/A"
        vix_pass = vix is not None and vix >= 25
        # Streak: engine shows 0 (frozen), so unknown
        streak_s = "UNKNOWN"
        all_pass = "NO"
        if rsi_pass and vix_pass:
            all_pass = "POSS"  # possible if streak >= 3

        print(f"{d:<12} {bt:>8} {rsi_src:>12} {rsi_s:>8} {'YES' if rsi_pass else 'NO':>8} "
              f"{vix_s:>8} {'YES' if vix_pass else 'NO':>8} {streak_s:>8} {all_pass:>6}")

    # ── MODULE 4 ENGINE BUG ANALYSIS ──
    print("\n\n" + "=" * 80)
    print("CRITICAL BUG: ENGINE MODULE 4 STATE IS FROZEN FOR ETHA")
    print("=" * 80)
    print()
    print("  The engine's module4 section returns IDENTICAL values at ALL timestamps:")
    print(f"    down_streak:          {ENGINE_MODULE4_FROZEN['down_streak']}")
    print(f"    v2_down_streak:       {ENGINE_MODULE4_FROZEN['v2_down_streak']}")
    print(f"    trigger_active:       {ENGINE_MODULE4_FROZEN['trigger_active']}")
    print(f"    v2_prev_close:        {ENGINE_MODULE4_FROZEN['v2_prev_close']}")
    print(f"    rsi_distance_to_gate: {ENGINE_MODULE4_FROZEN['rsi_distance_to_gate']}")
    print()
    print("  Evidence of staleness:")
    print("  - v2_prev_close = 14.9501 at ALL timestamps (Mar 20-28)")
    print("    But actual prices: 16.26 → 16.28 → 16.19 → 16.32 → 15.66 → 15.01")
    print("    If Module 4 were running, v2_prev_close would track the last bar's close")
    print("  - rsi_distance_to_gate = 5.46 at ALL timestamps")
    print("    But RSI changes from 55.84 to 40.46 — distance should change too")
    print("  - down_streak = 0 at ALL timestamps")
    print("    Price drops: 16.32 → 15.66 → 15.01 (clearly consecutive down bars)")
    print()
    print("  ROOT CAUSE HYPOTHESIS:")
    print("  ETHA was recently added to the watchlist but Module 4 streak tracking")
    print("  was never initialized or is not being updated by the compute cycle.")
    print("  The module4 block appears to be returning default/stale initialization")
    print("  values rather than computing live state from the 4H bar series.")

    # ── CONCLUSIONS ──
    print("\n\n" + "=" * 80)
    print("CONCLUSIONS")
    print("=" * 80)

    print("""
1. INDEPENDENT RSI CALCULATION (Alpha Vantage Pipeline)
   STATUS: COULD NOT EXECUTE — external API access blocked by proxy.
   The stock-data-mining repo has no cached ETHA data (ETHA was never in
   the original 25-ticker watchlist). A manual run from an unrestricted
   environment is needed.

2. ENGINE vs TRADINGVIEW RSI COMPARISON
   Engine RSI at Mar 26 13:30 ET:  47.02
   TradingView RSI at Mar 26 ~09:30 ET:  37.39
   Delta:  +9.63 points (ENGINE HIGHER)

   This is a LARGE discrepancy. The most likely cause is a combination of:
   (a) Different bar alignment (TV=AM bar, engine=PM bar)
   (b) Insufficient RSI warmup in engine (22 bars vs 340+ in TV)
   (c) Missing bars in engine corrupting the RSI series

3. MAX V0/V2 STREAKS (Engine Data)
   Engine Module 4 streak tracking is FROZEN (always 0).
   CANNOT determine streaks from engine data.
   Visual inspection of prices shows a DOWN sequence:
     16.32 → 15.66 → 15.01 (Mar 25 PM → Mar 26 → Mar 27)
   This is at least 2-3 consecutive down closes, but without per-bar
   OHLC data, V0 (close<open) streaks cannot be computed.

4. MINIMUM RSI IN WINDOW
   Engine minimum:  40.46 (at Mar 27 13:30 ET) — 5.46 points above gate
   TradingView:     37.39 (at Mar 26 09:30 ET) — 2.39 points above gate
   Neither crosses the RSI < 35 hard gate.

5. VIX CHECK
   Mar 26: VIX = 27.42 (from engine override state) → PASSES ≥ 25 gate
   FRED data ends Mar 12. No VIX available for Mar 24-25, 27 from
   accessible sources. Engine shows HIGH_RISK override on Mar 26,
   suggesting VIX was elevated throughout the window.

6. DATA ISSUES IDENTIFIED
   (a) ETHA missing from stock-data-mining repo entirely (not in 25-ticker list)
   (b) Engine has only 24 4H bars for ETHA (started ~Mar 13)
   (c) Several days show only 1 bar instead of expected 2 (AM+PM)
   (d) Module 4 state is COMPLETELY FROZEN — streaks never computed
   (e) External data sources inaccessible from this environment

7. FINAL VERDICT
   ┌─────────────────────────────────────────────────────────────────────┐
   │ LEGITIMATE NEAR-MISS — with caveats about engine data quality      │
   │                                                                    │
   │ Even using TradingView's lower RSI of 37.39, the RSI < 35 gate    │
   │ was never breached. Module 4 correctly did NOT trigger.            │
   │                                                                    │
   │ HOWEVER: The engine's Module 4 would not have triggered even if    │
   │ RSI had crossed 35, because the streak counter is FROZEN at 0.    │
   │ This is a DETECTION BUG that needs immediate investigation.        │
   │                                                                    │
   │ RECOMMENDATION:                                                    │
   │ 1. Fix Module 4 streak tracking for ETHA (and verify all tickers) │
   │ 2. Investigate missing 4H bars in ETHA ingestion pipeline         │
   │ 3. Run independent AV verification from unrestricted environment  │
   │ 4. Add ETHA to stock-data-mining repo's ticker list               │
   └─────────────────────────────────────────────────────────────────────┘
""")

    # Save engine data to CSV for reference
    df = pd.DataFrame(ENGINE_4H_SNAPSHOTS,
                       columns=["date", "bar_count", "bar_time_et", "price", "rsi14",
                                "ema9", "ema21", "ce_state", "vix_level"])
    out_path = ROOT / "backtest_output" / "ETHA_4h_engine_verification.csv"
    df.to_csv(out_path, index=False)
    print(f"Engine data saved to: {out_path}")


if __name__ == "__main__":
    main()
