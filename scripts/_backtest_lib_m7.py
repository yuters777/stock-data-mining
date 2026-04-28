"""M7 RS Leader Pullback backtest reimplementation.

Production reference: module7.py at HEAD 62bf5b1
  - DR_FROZEN_M7 (line 165): EARNINGS_BLOCK_DAYS=6, MAX_HOLD_DAYS=6,
    DISTANCE_THRESHOLD=-5.0, TOP_PCT=30
  - compute_daily_rs (line 273)
  - compute_hold_days (line 445)
  - compute_daily_ema9 (line 539)
  - is_earnings_window (line 797)
  - check_m7_entry (line 873)
  - compute_module7 (line 1004)
"""
from __future__ import annotations

import math
from datetime import date as Date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from scripts._data_loaders import aggregate_m5_to_daily, load_m5_extended
from scripts._earnings_filter import is_in_earnings_window

# Production frozen parameters (DR_FROZEN_M7 line 165)
_MAX_HOLD_DAYS = 6
_DISTANCE_THRESHOLD = -5.0  # pullback ≤ -5% from 60d high
_TOP_PCT = 30
_RS_LOOKBACK = 20
_ROLLING_HIGH_WINDOW = 60
_MAX_POSITIONS = 2


def compute_rs_score(
    ticker_closes: List[float],
    spy_closes: List[float],
    lookback: int = _RS_LOOKBACK,
) -> float:
    """SPY-adjusted 20d return differential."""
    if len(ticker_closes) < lookback + 1 or len(spy_closes) < lookback + 1:
        return float("nan")
    t_return = (ticker_closes[-1] - ticker_closes[-lookback - 1]) / ticker_closes[-lookback - 1]
    s_return = (spy_closes[-1] - spy_closes[-lookback - 1]) / spy_closes[-lookback - 1]
    return t_return - s_return


def select_top_30(rs_scores: Dict[str, float]) -> List[str]:
    """Select top 30% (using ceil) of universe by RS score."""
    valid = {t: s for t, s in rs_scores.items() if not math.isnan(s)}
    n_top = math.ceil(len(valid) * (_TOP_PCT / 100.0))
    return sorted(valid, key=lambda t: valid[t], reverse=True)[:n_top]


def compute_ema_9(closes: List[float]) -> Optional[float]:
    """9-period EMA. Returns None if <9 closes available."""
    if len(closes) < 9:
        return None
    alpha = 2.0 / 10.0
    ema = sum(closes[:9]) / 9
    for c in closes[9:]:
        ema = alpha * c + (1 - alpha) * ema
    return ema


def compute_ema_21_daily(closes: List[float]) -> Optional[float]:
    """21-period EMA for daily bars. Returns None if <21 closes available."""
    if len(closes) < 21:
        return None
    alpha = 2.0 / 22.0
    ema = sum(closes[:21]) / 21
    for c in closes[21:]:
        ema = alpha * c + (1 - alpha) * ema
    return ema


def _rolling_60d_high(closes: List[float]) -> Optional[float]:
    """60-day rolling high. Returns None if <60 closes."""
    if len(closes) < _ROLLING_HIGH_WINDOW:
        return None
    return max(closes[-_ROLLING_HIGH_WINDOW:])


def run_module7_backtest(
    universe: List[str],
    date_range: Tuple[str, str],
    earnings_buffer_days: int,
    data_root: Path,
    earnings_df: pd.DataFrame,
    spy_data_root: Optional[Path] = None,
) -> List[Dict]:
    """Run M7 RS Leader Pullback backtest with parameterized earnings buffer.

    Returns list of trade dicts with keys: ticker, entry_date_et, entry_price,
    exit_date_et, exit_price, exit_reason, return_pct, days_held.
    """
    if spy_data_root is None:
        spy_data_root = data_root

    start_dt = pd.Timestamp(date_range[0]).date()
    end_dt = pd.Timestamp(date_range[1]).date()

    # Load daily bars for all tickers + SPY
    daily_bars: Dict[str, pd.DataFrame] = {}
    for ticker in universe + ["SPY"]:
        try:
            df_m5 = load_m5_extended(data_root if ticker != "SPY" else spy_data_root, ticker)
            daily = aggregate_m5_to_daily(df_m5)
            daily_bars[ticker] = daily
        except FileNotFoundError:
            continue

    if "SPY" not in daily_bars:
        return []

    spy_daily = daily_bars["SPY"]

    # Collect all unique trading dates across all tickers
    all_dates = sorted(set(
        d for df in daily_bars.values() for d in df["date_et"].tolist()
        if start_dt <= d <= end_dt
    ))

    # Open positions: list of dicts
    open_positions: List[Dict] = []
    all_trades: List[Dict] = []

    for date_idx, current_date in enumerate(all_dates):
        # ── Manage exits first ──────────────────────────────────────────────
        still_open = []
        for pos in open_positions:
            ticker = pos["ticker"]
            if ticker not in daily_bars:
                still_open.append(pos)
                continue

            df = daily_bars[ticker]
            today_rows = df[df["date_et"] == current_date]
            if today_rows.empty:
                still_open.append(pos)
                continue

            today_close = float(today_rows.iloc[0]["close"])
            days_held = pos["days_held"] + 1

            # EMA9 close exit
            closes_so_far = df[df["date_et"] <= current_date]["close"].tolist()
            ema9 = compute_ema_9(closes_so_far)
            if ema9 is not None and today_close < ema9:
                all_trades.append({
                    **{k: v for k, v in pos.items() if k not in ("entry_idx", "days_held")},
                    "exit_date_et": str(current_date),
                    "exit_price": today_close,
                    "exit_reason": "ema9_close",
                    "return_pct": (today_close - pos["entry_price"]) / pos["entry_price"],
                    "days_held": days_held,
                })
                continue

            # Hard max 6 days
            if days_held >= _MAX_HOLD_DAYS:
                all_trades.append({
                    **{k: v for k, v in pos.items() if k not in ("entry_idx", "days_held")},
                    "exit_date_et": str(current_date),
                    "exit_price": today_close,
                    "exit_reason": "hard_max",
                    "return_pct": (today_close - pos["entry_price"]) / pos["entry_price"],
                    "days_held": days_held,
                })
                continue

            pos["days_held"] = days_held
            still_open.append(pos)

        open_positions = still_open

        # ── Skip entry evaluation if at max positions ───────────────────────
        if len(open_positions) >= _MAX_POSITIONS:
            continue

        # ── Compute RS scores for all tickers today ─────────────────────────
        spy_closes_today = spy_daily[spy_daily["date_et"] <= current_date]["close"].tolist()
        rs_scores: Dict[str, float] = {}
        for ticker in universe:
            if ticker not in daily_bars:
                continue
            df = daily_bars[ticker]
            closes = df[df["date_et"] <= current_date]["close"].tolist()
            rs_scores[ticker] = compute_rs_score(closes, spy_closes_today)

        top_tickers = set(select_top_30(rs_scores))

        # ── Evaluate each ticker for entry ───────────────────────────────────
        candidates = []
        already_open = {p["ticker"] for p in open_positions}

        for ticker in universe:
            if ticker in already_open:
                continue
            if ticker not in top_tickers:
                continue
            if ticker not in daily_bars:
                continue

            df = daily_bars[ticker]
            closes_to_date = df[df["date_et"] <= current_date]["close"].tolist()
            if len(closes_to_date) < 2:
                continue

            today_close = closes_to_date[-1]
            yest_close = closes_to_date[-2]

            # Pullback: today_close ≤ -5% from 60d rolling high
            high_60 = _rolling_60d_high(closes_to_date)
            if high_60 is None:
                continue
            pullback_pct = (today_close - high_60) / high_60 * 100.0
            if pullback_pct > _DISTANCE_THRESHOLD:
                continue

            # Recovery day: close > yesterday's close AND close > EMA21
            if today_close <= yest_close:
                continue
            ema21 = compute_ema_21_daily(closes_to_date)
            if ema21 is None or today_close <= ema21:
                continue

            # Earnings filter
            if is_in_earnings_window(ticker, str(current_date), earnings_buffer_days, earnings_df):
                continue

            candidates.append({
                "ticker": ticker,
                "pullback_depth": abs(pullback_pct),
                "distance_from_60d_high": abs(pullback_pct),
                "rs_score": rs_scores.get(ticker, float("nan")),
                "recovery_strength": (today_close - yest_close) / yest_close,
                "entry_price": today_close,
                "entry_date_et": str(current_date),
            })

        # 4-tier ranking: deeper pullback, closer to high (same as deeper here), higher RS, stronger recovery
        candidates.sort(
            key=lambda c: (
                -c["pullback_depth"],
                -c["distance_from_60d_high"],
                -c["rs_score"],
                -c["recovery_strength"],
            )
        )

        slots = _MAX_POSITIONS - len(open_positions)
        for cand in candidates[:slots]:
            open_positions.append({
                "ticker": cand["ticker"],
                "entry_date_et": cand["entry_date_et"],
                "entry_price": cand["entry_price"],
                "days_held": 0,
            })

    # Close any positions still open at end of data
    for pos in open_positions:
        ticker = pos["ticker"]
        if ticker not in daily_bars:
            continue
        df = daily_bars[ticker]
        last_row = df[df["date_et"] <= end_dt]
        if last_row.empty:
            continue
        last = last_row.iloc[-1]
        all_trades.append({
            "ticker": ticker,
            "entry_date_et": pos["entry_date_et"],
            "entry_price": pos["entry_price"],
            "exit_date_et": str(last["date_et"]),
            "exit_price": float(last["close"]),
            "exit_reason": "end_of_data",
            "return_pct": (last["close"] - pos["entry_price"]) / pos["entry_price"],
            "days_held": pos["days_held"],
        })

    return all_trades
