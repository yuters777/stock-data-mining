"""Module 6 production-mirror — port of _backtest_lib_m6.py using _production_mirror layer.

Production reference: market-engine HEAD a673359, module6.py lines 213-779.

Additions over EBS-1 anchor (_backtest_lib_m6.py):
  - Override gating: skip if Override != NORMAL (HARN-D-2 — may shift N slightly)
  - Uses bars_4h_reconstructor for 4H bar reconstruction

All M6-specific filter parameters kept identical to EBS-1 anchor:
  - gap ≥ -4% required
  - entry_price < gap_midpoint
  - exit: close >= gap_midpoint OR bars_held >= 15
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Tuple

import pandas as pd

from scripts._production_mirror.bars_4h_reconstructor import load_m5, reconstruct_4h
from scripts._production_mirror.override_4_mirror import build_override_history, get_override_state_at
from scripts._earnings_filter import is_in_earnings_window

# M6 constants (production module6.py)
GAP_THRESHOLD = -0.04  # ≥ -4% gap-down required
MAX_BARS_HELD = 15


def run_module6_mirror_backtest(
    universe: List[str],
    date_range: Tuple[date, date],
    earnings_buffer_days: int,
    earnings_df: pd.DataFrame,
    vix_df: pd.DataFrame,
    m4_trades: Optional[List[Dict]] = None,
) -> List[Dict]:
    """Run M6 No-News Shock backtest using _production_mirror layer.

    Returns list of trade dicts: ticker, entry_date, entry_price, exit_date,
    exit_price, exit_reason, return_pct, bars_held.

    HARN-D-2: Override gating added vs EBS-1 anchor. N may shift ≤5% from 379.
    """
    start_date, end_date = date_range
    override_df = build_override_history(vix_df)

    # Build active M4 lookup
    active_m4_set: set = set()
    if m4_trades:
        for t in m4_trades:
            entry_d = t.get("entry_date") or t.get("entry_date_et")
            exit_d = t.get("exit_date") or t.get("exit_date_et")
            if entry_d and exit_d:
                if isinstance(entry_d, str):
                    entry_d = pd.Timestamp(entry_d).date()
                if isinstance(exit_d, str):
                    exit_d = pd.Timestamp(exit_d).date()
                active_m4_set.add((t["ticker"], entry_d, exit_d))

    def _has_active_m4(ticker: str, shock_date: date) -> bool:
        for tk, ed, xd in active_m4_set:
            if tk == ticker and ed <= shock_date <= xd:
                return True
        return False

    all_trades: List[Dict] = []

    for ticker in universe:
        try:
            m5 = load_m5(ticker)
        except FileNotFoundError:
            continue

        bars = reconstruct_4h(m5, ticker, rth_only=True)
        if bars.empty:
            continue
        bars = bars.sort_values(["date_et", "timestamp_et"]).reset_index(drop=True)
        bars = bars[
            (bars["date_et"] >= start_date) & (bars["date_et"] <= end_date)
        ].reset_index(drop=True)
        if len(bars) < 3:
            continue

        state = "FLAT"
        entry: Optional[Dict] = None
        ticker_trades: List[Dict] = []

        dates = sorted(bars["date_et"].unique())

        for day_idx, current_date in enumerate(dates):
            if day_idx == 0:
                continue  # need prior day

            today_bars = bars[bars["date_et"] == current_date].reset_index(drop=True)
            prior_date = dates[day_idx - 1]
            prior_bars = bars[bars["date_et"] == prior_date].reset_index(drop=True)

            if today_bars.empty or prior_bars.empty:
                continue

            today_open = float(today_bars.iloc[0]["open"])
            prior_close = float(prior_bars.iloc[-1]["close"])

            gap_pct = (today_open - prior_close) / prior_close

            if gap_pct > GAP_THRESHOLD:
                # No sufficient gap-down — manage any open trade
                if state == "OPEN" and entry is not None:
                    for _, bar in today_bars.iterrows():
                        abs_idx = bars[bars["date_et"] == current_date].index[0] + int(_)
                        bars_held = abs_idx - entry["entry_abs_idx"]
                        if float(bar["close"]) >= entry["gap_midpoint"]:
                            ticker_trades.append(
                                _close_trade(entry, bar, current_date, "gap_midpoint", bars_held)
                            )
                            state = "FLAT"
                            entry = None
                            break
                        if bars_held >= MAX_BARS_HELD:
                            ticker_trades.append(
                                _close_trade(entry, bar, current_date, "hard_max", bars_held)
                            )
                            state = "FLAT"
                            entry = None
                            break
                continue

            gap_midpoint = prior_close - (prior_close - today_open) * 0.5

            if state == "FLAT":
                # Override gate (production: M6 operates in NORMAL conditions)
                override_state = get_override_state_at(override_df, current_date)
                if override_state != "NORMAL":
                    continue  # HARN-D-2

                if _has_active_m4(ticker, current_date):
                    continue

                if is_in_earnings_window(ticker, str(current_date), earnings_buffer_days, earnings_df):
                    continue

                # Entry: first bar's close
                entry_bar = today_bars.iloc[0]
                entry_price = float(entry_bar["close"])

                if entry_price >= gap_midpoint:
                    continue

                abs_idx = int(bars[bars["date_et"] == current_date].index[0])
                state = "OPEN"
                entry = {
                    "ticker": ticker,
                    "entry_date": current_date,
                    "entry_price": entry_price,
                    "gap_midpoint": gap_midpoint,
                    "entry_abs_idx": abs_idx,
                }
                # Check remaining bars of entry day for immediate exit
                for j in range(1, len(today_bars)):
                    bar = today_bars.iloc[j]
                    bars_held = j
                    if float(bar["close"]) >= gap_midpoint:
                        ticker_trades.append(
                            _close_trade(entry, bar, current_date, "gap_midpoint", bars_held)
                        )
                        state = "FLAT"
                        entry = None
                        break
                    if bars_held >= MAX_BARS_HELD:
                        ticker_trades.append(
                            _close_trade(entry, bar, current_date, "hard_max", bars_held)
                        )
                        state = "FLAT"
                        entry = None
                        break

            elif state == "OPEN" and entry is not None:
                day_start_abs = int(bars[bars["date_et"] == current_date].index[0])
                for j, (_, bar) in enumerate(today_bars.iterrows()):
                    abs_idx = day_start_abs + j
                    bars_held = abs_idx - entry["entry_abs_idx"]
                    if float(bar["close"]) >= entry["gap_midpoint"]:
                        ticker_trades.append(
                            _close_trade(entry, bar, current_date, "gap_midpoint", bars_held)
                        )
                        state = "FLAT"
                        entry = None
                        break
                    if bars_held >= MAX_BARS_HELD:
                        ticker_trades.append(
                            _close_trade(entry, bar, current_date, "hard_max", bars_held)
                        )
                        state = "FLAT"
                        entry = None
                        break

        # Close any open trade at end of data
        if state == "OPEN" and entry is not None:
            last = bars.iloc[-1]
            bars_held = len(bars) - 1 - entry["entry_abs_idx"]
            ticker_trades.append(
                {
                    "ticker": ticker,
                    "entry_date": entry["entry_date"],
                    "entry_price": entry["entry_price"],
                    "exit_date": last["date_et"],
                    "exit_price": float(last["close"]),
                    "exit_reason": "end_of_data",
                    "return_pct": (float(last["close"]) - entry["entry_price"])
                    / entry["entry_price"],
                    "bars_held": bars_held,
                }
            )

        all_trades.extend(ticker_trades)

    return all_trades


def _close_trade(
    entry: Dict, bar: pd.Series, exit_date: date, reason: str, bars_held: int
) -> Dict:
    return {
        "ticker": entry["ticker"],
        "entry_date": entry["entry_date"],
        "entry_price": entry["entry_price"],
        "exit_date": exit_date,
        "exit_price": float(bar["close"]),
        "exit_reason": reason,
        "return_pct": (float(bar["close"]) - entry["entry_price"]) / entry["entry_price"],
        "bars_held": bars_held,
    }
