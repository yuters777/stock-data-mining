"""M4 Mean Reversion backtest reimplementation.

Production reference: module4.py at HEAD 62bf5b1
  - compute_streak_update (line 75)
  - compute_rsi_4h (line 98)
  - check_triggers (line 321)
"""
from __future__ import annotations

from datetime import date as Date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from scripts._data_loaders import aggregate_m5_to_4h_rth, load_m5_extended, load_vix_daily
from scripts._earnings_filter import is_in_earnings_window


def compute_rsi_14(closes: List[float]) -> Optional[float]:
    """Standard 14-period RSI (Wilder's). Returns None if <15 closes available."""
    if len(closes) < 15:
        return None
    arr = np.array(closes, dtype=float)
    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains[:14].mean()
    avg_loss = losses[:14].mean()
    for i in range(14, len(deltas)):
        avg_gain = (avg_gain * 13 + gains[i]) / 14
        avg_loss = (avg_loss * 13 + losses[i]) / 14
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_ema_21(closes: List[float]) -> Optional[float]:
    """21-period EMA. Returns None if <21 closes available."""
    if len(closes) < 21:
        return None
    alpha = 2.0 / 22.0
    ema = sum(closes[:21]) / 21
    for c in closes[21:]:
        ema = alpha * c + (1 - alpha) * ema
    return ema


def _lookup_vix_prior_close(vix_df: pd.DataFrame, current_date: Date) -> Optional[float]:
    """VIX close at most recent trading day strictly before current_date."""
    prior = vix_df[vix_df["date"].dt.date < current_date]
    if prior.empty:
        return None
    return float(prior.iloc[-1]["vix_close"])


def run_module4_backtest(
    universe: List[str],
    date_range: Tuple[str, str],
    earnings_buffer_days: int,
    data_root: Path,
    earnings_df: pd.DataFrame,
    vix_df: pd.DataFrame,
) -> List[Dict]:
    """Run M4 Mean Reversion backtest with parameterized earnings buffer.

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

        # Filter to date range
        bars = bars[
            (bars["date_et"] >= start_dt) & (bars["date_et"] <= end_dt)
        ].reset_index(drop=True)
        if len(bars) < 4:
            continue

        state = "FLAT"
        entry: Optional[Dict] = None
        trades: List[Dict] = []

        for i, row in bars.iterrows():
            bar_date = row["date_et"]

            if state == "FLAT":
                if i < 3:
                    continue
                prior = bars.iloc[i - 3:i]
                if not all(r["close"] < r["open"] for _, r in prior.iterrows()):
                    continue

                vix_val = _lookup_vix_prior_close(vix_df, bar_date)
                if vix_val is None or vix_val < 25.0:
                    continue

                recent_closes = bars.iloc[max(0, i - 19):i + 1]["close"].tolist()
                rsi = compute_rsi_14(recent_closes)
                if rsi is None or rsi >= 35.0:
                    continue

                if is_in_earnings_window(
                    ticker, str(bar_date), earnings_buffer_days, earnings_df
                ):
                    continue

                state = "OPEN"
                entry = {
                    "ticker": ticker,
                    "entry_date_et": str(bar_date),
                    "entry_bar_index": int(row["bar_index"]),
                    "entry_price": float(row["close"]),
                    "entry_idx": i,
                }
                continue

            # state == "OPEN"
            bars_held = i - entry["entry_idx"]
            closes_so_far = bars.iloc[max(0, i - 25):i + 1]["close"].tolist()
            ema21 = compute_ema_21(closes_so_far)

            if ema21 is not None and row["close"] >= ema21:
                trades.append({
                    **entry,
                    "exit_date_et": str(bar_date),
                    "exit_price": float(row["close"]),
                    "exit_reason": "ema21_touch",
                    "return_pct": (row["close"] - entry["entry_price"]) / entry["entry_price"],
                    "bars_held": bars_held,
                })
                state = "FLAT"
                entry = None
                continue

            if bars_held >= 10:
                trades.append({
                    **entry,
                    "exit_date_et": str(bar_date),
                    "exit_price": float(row["close"]),
                    "exit_reason": "hard_max",
                    "return_pct": (row["close"] - entry["entry_price"]) / entry["entry_price"],
                    "bars_held": bars_held,
                })
                state = "FLAT"
                entry = None

        # Close any open trade at end of data
        if state == "OPEN" and entry is not None:
            last = bars.iloc[-1]
            bars_held = len(bars) - 1 - entry["entry_idx"]
            trades.append({
                **entry,
                "exit_date_et": str(last["date_et"]),
                "exit_price": float(last["close"]),
                "exit_reason": "end_of_data",
                "return_pct": (last["close"] - entry["entry_price"]) / entry["entry_price"],
                "bars_held": bars_held,
            })

        all_trades.extend(trades)

    return all_trades
