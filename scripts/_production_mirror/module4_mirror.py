"""Module 4 production-mirror — full port of module4.py check_triggers + exit logic.

Production reference: market-engine HEAD a673359,
  src/market_engine/modules/module4.py
  - Constants: lines 29-39
  - check_triggers: lines 350-470
  - compute_vix_5d_roc: lines 115-151
  - compute_rsi_4h: lines 98-112
  - classify_conviction_tier: lines 87-95

8 production behaviors implemented (closes EBS-1.1 gaps from operator authoring miss #2).
HARN-D-3: Exit reason labels simplified vs production nuanced codes.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Tuple

import pandas as pd

from scripts._production_mirror.bars_4h_reconstructor import load_m5, reconstruct_4h
from scripts._production_mirror.ema_engine import (
    compute_daily_ema_for_ticker,
    compute_ema_series,
    detect_warmup_after_gap,
)
from scripts._production_mirror.override_4_mirror import build_override_history, get_override_state_at
from scripts._earnings_filter import is_in_earnings_window

# DR-frozen constants per PI v33 — production module4.py:29-39
STREAK_THRESHOLD = 3
VIX_GATE = 25.0
RSI_GATE = 35.0
D6_VIX_ROC_ENABLED = True
D6_VIX_ROC_THRESHOLD = 30.0  # percent
MAX_HOLD_BARS = 10  # 4H bars (≤40h)


def compute_rsi_4h(bars_4h_ticker: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Compute RSI(14) on 4H closes for one ticker. Returns None if <15 bars.
    Production reference: module4.py:98-112."""
    if len(bars_4h_ticker) < period + 1:
        return None
    closes = bars_4h_ticker["close"].astype(float).values
    deltas = closes[1:] - closes[:-1]
    gains = pd.Series([max(d, 0.0) for d in deltas])
    losses = pd.Series([max(-d, 0.0) for d in deltas])
    avg_gain = float(gains.iloc[:period].mean())
    avg_loss = float(losses.iloc[:period].mean())
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains.iloc[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses.iloc[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def compute_vix_5d_roc(vix_df: pd.DataFrame, current_date_et: date) -> Optional[float]:
    """Compute VIX 5-trading-day ROC.
    Production reference: module4.py:115-151.

    Formula: (vix_today - vix_5d_ago) / vix_5d_ago * 100
    Threshold: <= 30% blocks (production uses <=, not <, line 383).
    None blocks (production line 378-382).
    """
    relevant = vix_df[pd.to_datetime(vix_df["date"]).dt.date < current_date_et].sort_values("date")
    if len(relevant) < 6:
        return None
    last_6 = relevant.tail(6)
    vix_today = float(last_6.iloc[-1]["vix_close"])
    vix_5d_ago = float(last_6.iloc[0]["vix_close"])
    if vix_5d_ago <= 0:
        return None
    return round((vix_today - vix_5d_ago) / vix_5d_ago * 100, 2)


def run_module4_mirror_backtest(
    universe: List[str],
    date_range: Tuple[date, date],
    earnings_buffer_days: int,
    earnings_df: pd.DataFrame,
    vix_df: pd.DataFrame,
) -> List[Dict]:
    """Full M4 backtest with all 8 production behaviors.

    Returns list of trade dicts: ticker, entry_date, entry_price, exit_date,
    exit_price, exit_reason, return_pct, conviction_tier, bars_held.
    """
    start_date, end_date = date_range
    override_df = build_override_history(vix_df)

    trades: List[Dict] = []

    for ticker in universe:
        try:
            m5 = load_m5(ticker)
        except FileNotFoundError:
            continue

        bars_4h = reconstruct_4h(m5, ticker, rth_only=True)
        if bars_4h.empty:
            continue
        bars_4h = bars_4h.sort_values(["date_et", "timestamp_et"]).reset_index(drop=True)

        # Pre-compute EMA21 4H for the ticker
        ema_series = compute_ema_series(bars_4h["close"], period=21)
        bars_4h = bars_4h.copy()
        bars_4h["ema_21"] = ema_series.values

        # Pre-compute daily EMA21 for warmup detection (Finding 6)
        daily_ema21 = compute_daily_ema_for_ticker(m5, period=21)

        in_trigger = False
        entry_bar_idx: Optional[int] = None
        entry_price: Optional[float] = None
        entry_date: Optional[date] = None
        conviction: Optional[str] = None

        for i in range(len(bars_4h)):
            bar = bars_4h.iloc[i]
            bar_date = bar["date_et"]

            if bar_date < start_date or bar_date > end_date:
                continue

            # ── Exit logic for active trigger ──────────────────────────────
            if in_trigger:
                bars_held = i - entry_bar_idx
                ema21 = bar["ema_21"]

                exit_reason = None
                exit_price = float(bar["close"])

                # Exit A: close > EMA21 — mean-reversion target (production module4.py:455-460)
                if pd.notna(ema21) and float(bar["close"]) > float(ema21):
                    exit_reason = "EMA21_TARGET"

                # Exit B: max hold reached (production module4.py:462-465)
                if not exit_reason and bars_held >= MAX_HOLD_BARS:
                    exit_reason = "MAX_HOLD"

                if exit_reason:
                    return_pct = (exit_price - entry_price) / entry_price
                    trades.append(
                        {
                            "ticker": ticker,
                            "entry_date": entry_date,
                            "entry_price": entry_price,
                            "exit_date": bar_date,
                            "exit_price": exit_price,
                            "exit_reason": exit_reason,
                            "return_pct": return_pct,
                            "conviction_tier": conviction,
                            "bars_held": bars_held,
                        }
                    )
                    in_trigger = False
                    entry_bar_idx = None
                continue  # skip entry logic while in trigger

            # ── Entry logic ─────────────────────────────────────────────────
            # Need at least 15 bars for RSI, 3 for streak
            if i < 15:
                continue

            # Pre-flight 1: Override state — block SUSPENDED/STALE (production line 360-362)
            override_state = get_override_state_at(override_df, bar_date)
            if override_state in ("SUSPENDED", "STALE"):
                continue

            # Pre-flight 2: VIX prior close availability (production line 364-366)
            vix_row = override_df[override_df["date_et"] == bar_date]
            if vix_row.empty or pd.isna(vix_row.iloc[0]["vix_prior_close"]):
                continue
            vix_prior_close = float(vix_row.iloc[0]["vix_prior_close"])

            # Pre-flight 3: VIX gate — require VIX ≥ 25 (production line 367-372)
            if vix_prior_close < VIX_GATE:
                continue

            # Pre-flight 4: D6 VIX 5d ROC (production line 374-393)
            if D6_VIX_ROC_ENABLED:
                vix_5d_roc = compute_vix_5d_roc(vix_df, bar_date)
                if vix_5d_roc is None:
                    continue  # insufficient VIX history (production line 378-382)
                if vix_5d_roc <= D6_VIX_ROC_THRESHOLD:
                    continue  # chronic elevation blocked (production line 383)

            # Pre-flight 5: 3-bar RED streak (STREAK_THRESHOLD=3, production module4.py:29)
            if i < 3:
                continue
            recent_3 = bars_4h.iloc[i - 2 : i + 1]
            # All 3 bars must be RED (close < open) and closes trending down
            is_all_red = all(
                float(recent_3.iloc[k]["close"]) < float(recent_3.iloc[k]["open"])
                for k in range(len(recent_3))
            )
            is_closing_lower = all(
                float(recent_3.iloc[k]["close"]) < float(recent_3.iloc[k - 1]["close"])
                for k in range(1, len(recent_3))
            )
            if not (is_all_red and is_closing_lower):
                continue

            # Pre-flight 6: RSI(14) gate (production module4.py:31)
            rsi = compute_rsi_4h(bars_4h.iloc[: i + 1])
            if rsi is None or rsi >= RSI_GATE:
                continue

            # Pre-flight 7: Finding 4 — EMA21 availability per ticker (production line 435-442)
            ema21 = bar["ema_21"]
            if pd.isna(ema21):
                continue

            # Pre-flight 8: Finding 6 — EMA warmup post-gap (production line 444-450)
            if detect_warmup_after_gap(daily_ema21, bar_date):
                continue

            # Pre-flight 9: earnings filter
            if earnings_buffer_days > 0 and is_in_earnings_window(
                ticker, str(bar_date), earnings_buffer_days, earnings_df
            ):
                continue

            # All checks passed — trigger active
            in_trigger = True
            entry_bar_idx = i
            entry_price = float(bar["close"])
            entry_date = bar_date
            # Conviction tier classification (production module4.py:87-95)
            conviction = "TIER_A" if 25.0 <= rsi < 35.0 else "TIER_B"

        # End-of-data: close any open trigger at last bar
        if in_trigger:
            last_bar = bars_4h.iloc[-1]
            return_pct = (float(last_bar["close"]) - entry_price) / entry_price
            trades.append(
                {
                    "ticker": ticker,
                    "entry_date": entry_date,
                    "entry_price": entry_price,
                    "exit_date": last_bar["date_et"],
                    "exit_price": float(last_bar["close"]),
                    "exit_reason": "DATA_END",
                    "return_pct": return_pct,
                    "conviction_tier": conviction,
                    "bars_held": len(bars_4h) - 1 - entry_bar_idx,
                }
            )

    return trades
