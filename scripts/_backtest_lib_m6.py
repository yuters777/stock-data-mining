"""M6 No-News Shock backtest reimplementation.

Production reference: module6.py at HEAD 62bf5b1
  - compute_gap_midpoint (line 213)
  - is_earnings_window (line 351)
  - Entry/exit dispatcher (~lines 722-779)
"""
from __future__ import annotations

from datetime import date as Date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from scripts._data_loaders import aggregate_m5_to_4h_rth, load_m5_extended
from scripts._earnings_filter import is_in_earnings_window


def _has_classified_news(
    ticker: str,
    shock_date: Date,
    news_df: Optional[pd.DataFrame],
) -> bool:
    """Return True if any classified news hit exists for ticker on shock_date pre-market window.

    Window: previous trading day 16:00 through shock_date 09:30 ET (approx 17.5h).
    If news_df is None → assume NO_CLASSIFIED_NEWS (returns False).
    """
    if news_df is None:
        return False
    window_start = pd.Timestamp(shock_date - timedelta(days=1)).replace(hour=16, minute=0)
    window_end = pd.Timestamp(shock_date).replace(hour=9, minute=30)
    ticker_news = news_df[news_df["ticker"] == ticker]
    if ticker_news.empty:
        return False
    ts_col = pd.to_datetime(ticker_news["news_timestamp_utc"])
    in_window = ticker_news[
        (ts_col >= window_start) & (ts_col <= window_end)
    ]
    classified = in_window[
        in_window["classification"] == "CLASSIFIED_NEWS_HIT"
    ]
    return not classified.empty


def _has_corporate_action(
    ticker: str,
    shock_date: Date,
    ca_df: Optional[pd.DataFrame],
) -> bool:
    """Return True if ticker has a split or dividend on shock_date."""
    if ca_df is None:
        return False
    hits = ca_df[
        (ca_df["ticker"] == ticker) &
        (ca_df["action_date"].dt.date == shock_date)
    ]
    return not hits.empty


def _has_active_m4_trade(
    ticker: str,
    shock_date: Date,
    active_m4_df: Optional[pd.DataFrame],
) -> bool:
    """Return True if there is an open M4 trade for ticker on shock_date."""
    if active_m4_df is None or active_m4_df.empty:
        return False
    hits = active_m4_df[
        (active_m4_df["ticker"] == ticker) &
        (pd.to_datetime(active_m4_df["entry_date_et"]).dt.date <= shock_date) &
        (pd.to_datetime(active_m4_df["exit_date_et"]).dt.date >= shock_date)
    ]
    return not hits.empty


def run_module6_backtest(
    universe: List[str],
    date_range: Tuple[str, str],
    earnings_buffer_days: int,
    data_root: Path,
    earnings_df: pd.DataFrame,
    news_df: Optional[pd.DataFrame] = None,
    corporate_actions_df: Optional[pd.DataFrame] = None,
    active_m4_trades_df: Optional[pd.DataFrame] = None,
) -> List[Dict]:
    """Run M6 No-News Shock backtest with parameterized earnings buffer.

    Returns list of trade dicts with keys: ticker, entry_date_et, entry_price,
    exit_date_et, exit_price, exit_reason, return_pct, bars_held.
    """
    start_dt = pd.Timestamp(date_range[0]).date()
    end_dt = pd.Timestamp(date_range[1]).date()
    all_trades: List[Dict] = []

    for ticker in universe:
        try:
            df_m5 = load_m5_extended(data_root, ticker)
        except FileNotFoundError:
            continue

        bars = aggregate_m5_to_4h_rth(df_m5)
        if bars.empty:
            continue

        bars = bars[
            (bars["date_et"] >= start_dt) & (bars["date_et"] <= end_dt)
        ].reset_index(drop=True)
        if len(bars) < 3:
            continue

        state = "FLAT"
        entry: Optional[Dict] = None
        trades: List[Dict] = []

        # Group bars by date to identify day boundaries
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

            # Gap-down check
            gap_pct = (today_open - prior_close) / prior_close
            if gap_pct > -0.04:
                # No sufficient gap-down; handle open trades
                if state == "OPEN" and entry is not None and entry["ticker"] == ticker:
                    for _, bar in today_bars.iterrows():
                        bars_held = _count_bars_held(bars, entry["entry_bar_abs_idx"], bar.name + bars[bars["date_et"] == current_date].index[0])
                        if bar["close"] >= entry["gap_midpoint"]:
                            trades.append(_close_trade(entry, bar, current_date, "gap_midpoint", bars_held))
                            state = "FLAT"
                            entry = None
                            break
                        if bars_held >= 15:
                            trades.append(_close_trade(entry, bar, current_date, "hard_max", bars_held))
                            state = "FLAT"
                            entry = None
                            break
                continue

            gap_midpoint = prior_close - (prior_close - today_open) * 0.5

            if state == "FLAT":
                # Apply all entry guards
                if _has_classified_news(ticker, current_date, news_df):
                    continue
                if _has_active_m4_trade(ticker, current_date, active_m4_trades_df):
                    continue
                if _has_corporate_action(ticker, current_date, corporate_actions_df):
                    continue
                if is_in_earnings_window(ticker, str(current_date), earnings_buffer_days, earnings_df):
                    continue

                # Entry: first bar's close
                entry_bar = today_bars.iloc[0]
                entry_price = float(entry_bar["close"])

                # Entry guard: entry_price < gap_midpoint
                if entry_price >= gap_midpoint:
                    continue

                # Find absolute bar index for bars_held tracking
                abs_idx = bars[bars["date_et"] == current_date].index[0]

                state = "OPEN"
                entry = {
                    "ticker": ticker,
                    "entry_date_et": str(current_date),
                    "entry_price": entry_price,
                    "gap_midpoint": gap_midpoint,
                    "entry_bar_abs_idx": abs_idx,
                }
                # Check remaining bars of entry day for immediate exit
                for j in range(1, len(today_bars)):
                    bar = today_bars.iloc[j]
                    bars_held = j
                    if bar["close"] >= gap_midpoint:
                        trades.append(_close_trade(entry, bar, current_date, "gap_midpoint", bars_held))
                        state = "FLAT"
                        entry = None
                        break
                    if bars_held >= 15:
                        trades.append(_close_trade(entry, bar, current_date, "hard_max", bars_held))
                        state = "FLAT"
                        entry = None
                        break

            elif state == "OPEN" and entry is not None:
                # Manage open trade on non-entry days
                abs_start = entry["entry_bar_abs_idx"]
                for j, (_, bar) in enumerate(today_bars.iterrows()):
                    abs_idx = bars[bars["date_et"] == current_date].index[0] + j
                    bars_held = abs_idx - abs_start
                    if bar["close"] >= entry["gap_midpoint"]:
                        trades.append(_close_trade(entry, bar, current_date, "gap_midpoint", bars_held))
                        state = "FLAT"
                        entry = None
                        break
                    if bars_held >= 15:
                        trades.append(_close_trade(entry, bar, current_date, "hard_max", bars_held))
                        state = "FLAT"
                        entry = None
                        break

        # Close any open trade at end of data
        if state == "OPEN" and entry is not None:
            last = bars.iloc[-1]
            bars_held = len(bars) - 1 - entry["entry_bar_abs_idx"]
            trades.append({
                **{k: v for k, v in entry.items() if k != "gap_midpoint" and k != "entry_bar_abs_idx"},
                "exit_date_et": str(last["date_et"]),
                "exit_price": float(last["close"]),
                "exit_reason": "end_of_data",
                "return_pct": (last["close"] - entry["entry_price"]) / entry["entry_price"],
                "bars_held": bars_held,
            })

        all_trades.extend(trades)

    return all_trades


def _close_trade(entry: Dict, bar: pd.Series, exit_date: Date, reason: str, bars_held: int) -> Dict:
    return {
        "ticker": entry["ticker"],
        "entry_date_et": entry["entry_date_et"],
        "entry_price": entry["entry_price"],
        "exit_date_et": str(exit_date),
        "exit_price": float(bar["close"]),
        "exit_reason": reason,
        "return_pct": (bar["close"] - entry["entry_price"]) / entry["entry_price"],
        "bars_held": bars_held,
    }


def _count_bars_held(bars: pd.DataFrame, entry_abs_idx: int, current_abs_idx: int) -> int:
    return current_abs_idx - entry_abs_idx
