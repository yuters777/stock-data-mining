"""Module 7 production-mirror — full port of module7.py Phase 1+2+3.

Production reference: market-engine HEAD a673359,
  src/market_engine/modules/module7.py
  - DR_FROZEN_M7: lines 165 (EARNINGS_BLOCK_DAYS=6, MAX_HOLD_DAYS=6,
    DISTANCE_THRESHOLD=-5.0, TOP_PCT=30)
  - is_final_session_bar gate: line 1020
  - should_skip_m7_today (SPY gate): lines 200-270
  - compute_daily_rs with CA guard: lines 273-398 (CA guard: 309-323)
  - final-bar gate: lines 404-442
  - _get_daily_close / _get_high_60d: lines 499-534
  - compute_daily_ema9: lines 539-593
  - check_m7_entry pre-filter cascade: lines 870-998
  - compute_module7 Phase 1+2+3 with state machine: lines 1004-1223
    - Override gate: lines 1124-1133
    - top_30pct gate: lines 1135-1138
    - distance gate: lines 1140-1145
    - IDLE/PULLBACK state machine: lines 1174-1219
    - recovery condition: line 1192 (daily_close > pullback_high — NOT EMA21)

14 production behaviors implemented. Critical fix: recovery = daily_close > pullback_high.
HARN-D-4: Active M4/M6 lookup via pre-computed trade tables (production uses live state DB).
"""
from __future__ import annotations

import math
from datetime import date
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

from scripts._production_mirror.bars_4h_reconstructor import load_m5, reconstruct_4h
from scripts._production_mirror.ema_engine import compute_ema_series, compute_daily_ema_for_ticker
from scripts._production_mirror.override_4_mirror import build_override_history, get_override_state_at
from scripts._earnings_filter import is_in_earnings_window

# DR_FROZEN_M7 constants — production module7.py:165
_MAX_HOLD_DAYS = 6
_DISTANCE_THRESHOLD = -5.0  # distance_to_high_pct < -5.0% → reset (production line 1140-1145)
_TOP_PCT = 30
_RS_LOOKBACK = 20
_ROLLING_HIGH_WINDOW = 60
_CA_GUARD_THRESHOLD = 0.50  # abs(return_20d) > 0.50 suppresses from RS pool (production line 310)
_EMA9_PERIOD = 9
_EMA21_PERIOD = 21


def _compute_rs_adjusted(
    ticker_closes: List[float],
    spy_closes: List[float],
) -> float:
    """SPY-adjusted 20d return differential.

    CA guard applied BEFORE this computation (production line 309-323).
    Returns NaN if insufficient data.
    Production reference: module7.py:307, 333.
    """
    if len(ticker_closes) < _RS_LOOKBACK + 1 or len(spy_closes) < _RS_LOOKBACK + 1:
        return float("nan")
    return_20d = (ticker_closes[-1] - ticker_closes[-_RS_LOOKBACK - 1]) / ticker_closes[-_RS_LOOKBACK - 1]
    spy_return_20d = (spy_closes[-1] - spy_closes[-_RS_LOOKBACK - 1]) / spy_closes[-_RS_LOOKBACK - 1]
    return return_20d - spy_return_20d


def _select_top_30pct(rs_scores: Dict[str, float]) -> Set[str]:
    """Select top 30% (using ceil) of universe by RS score.

    top_k = ceil(eligible_count * 0.30) — production module7.py:356 (math.ceil).
    """
    valid = {t: s for t, s in rs_scores.items() if not math.isnan(s)}
    n_top = math.ceil(len(valid) * (_TOP_PCT / 100.0))
    sorted_tickers = sorted(valid, key=lambda t: valid[t], reverse=True)
    return set(sorted_tickers[:n_top])


def _rolling_high(closes: List[float], window: int = _ROLLING_HIGH_WINDOW) -> Optional[float]:
    """Rolling N-day high. Returns None if insufficient data."""
    if len(closes) < window:
        return None
    return max(closes[-window:])


class _M7TickerState:
    """Named pullback state machine per ticker.
    States: IDLE | PULLBACK_1 | PULLBACK_2 | PULLBACK_3
    Production reference: module7.py:1174-1219.
    """

    def __init__(self) -> None:
        self.state = "IDLE"
        self.pullback_high: Optional[float] = None   # pre-pullback close (production line 1192)
        self.pullback_low: Optional[float] = None
        self.pullback_bars: int = 0

    def reset(self) -> None:
        self.state = "IDLE"
        self.pullback_high = None
        self.pullback_low = None
        self.pullback_bars = 0

    def step(
        self,
        today_close: float,
        prior_close: Optional[float],
        ema21: Optional[float],
    ) -> Optional[Dict]:
        """Advance state machine. Returns entry snapshot dict on recovery, else None.

        Entry snapshot has keys: pullback_high, pullback_low, pullback_bars, recovery_close.
        Recovery condition: today_close > pullback_high (production line 1192 — NOT > EMA21).
        """
        is_down_bar = prior_close is not None and today_close < prior_close
        above_ema21 = ema21 is not None and today_close > ema21

        if self.state == "IDLE":
            # IDLE → PULLBACK_1: is_down_bar AND close > ema21_4h (production line 1174-1179)
            if is_down_bar and above_ema21:
                self.state = "PULLBACK_1"
                self.pullback_high = prior_close  # pre-pullback close (production line 1192)
                self.pullback_low = today_close
                self.pullback_bars = 1
            return None

        # State is PULLBACK_1, PULLBACK_2, or PULLBACK_3
        # Recovery check: today_close > pullback_high (production line 1192)
        if today_close > self.pullback_high:
            snapshot = {
                "pullback_high": self.pullback_high,
                "pullback_low": self.pullback_low,
                "pullback_bars": self.pullback_bars,
                "recovery_close": today_close,
            }
            self.reset()
            return snapshot  # caller runs pre-filter cascade and enters if passes

        # Extend pullback: is_down_bar AND close > ema21 AND pullback_bars < 3
        # (production line 1204)
        if is_down_bar and above_ema21 and self.pullback_bars < 3:
            self.pullback_bars += 1
            self.state = f"PULLBACK_{self.pullback_bars}"
            self.pullback_low = min(float(self.pullback_low), today_close)
            return None

        # Neither recovery nor valid extension → reset to IDLE
        self.reset()
        return None


def run_module7_mirror_backtest(
    universe: List[str],
    date_range: Tuple[date, date],
    earnings_buffer_days: int,
    earnings_df: pd.DataFrame,
    vix_df: pd.DataFrame,
    m4_trades: Optional[List[Dict]] = None,
    m6_trades: Optional[List[Dict]] = None,
) -> List[Dict]:
    """Full M7 backtest with all 14 production behaviors.

    Returns list of trade dicts: ticker, entry_date, entry_price, exit_date,
    exit_price, exit_reason, return_pct, days_held, pullback_bars.

    HARN-D-4: Active M4/M6 lookup via pre-computed trade tables.
    """
    start_date, end_date = date_range
    override_df = build_override_history(vix_df)

    # Load all M5 data and compute daily closes + EMA series
    daily_data: Dict[str, pd.DataFrame] = {}
    for ticker in universe + ["SPY"]:
        try:
            m5 = load_m5(ticker)
        except FileNotFoundError:
            continue
        daily = compute_daily_ema_for_ticker(m5, period=_EMA21_PERIOD)
        # Also add EMA9 for exit condition
        daily["ema9"] = compute_ema_series(daily["daily_close"], _EMA9_PERIOD)
        daily_data[ticker] = daily

    if "SPY" not in daily_data:
        return []  # SPY gate fail-closed (production lines 200-270)

    # Build active trade lookups (HARN-D-4)
    def _has_active_m4(ticker: str, d: date) -> bool:
        if not m4_trades:
            return False
        for t in m4_trades:
            ed = t.get("entry_date") or t.get("entry_date_et")
            xd = t.get("exit_date") or t.get("exit_date_et")
            if not (ed and xd):
                continue
            if isinstance(ed, str):
                ed = pd.Timestamp(ed).date()
            if isinstance(xd, str):
                xd = pd.Timestamp(xd).date()
            if t["ticker"] == ticker and ed <= d <= xd:
                return True
        return False

    def _has_active_m6(ticker: str, d: date) -> bool:
        if not m6_trades:
            return False
        for t in m6_trades:
            ed = t.get("entry_date") or t.get("entry_date_et")
            xd = t.get("exit_date") or t.get("exit_date_et")
            if not (ed and xd):
                continue
            if isinstance(ed, str):
                ed = pd.Timestamp(ed).date()
            if isinstance(xd, str):
                xd = pd.Timestamp(xd).date()
            if t["ticker"] == ticker and ed <= d <= xd:
                return True
        return False

    # Per-ticker state machines
    states: Dict[str, _M7TickerState] = {t: _M7TickerState() for t in universe}

    # Collect all trading dates in range
    spy_df = daily_data["SPY"]
    all_dates = sorted(
        d
        for d in spy_df["date_et"].tolist()
        if start_date <= d <= end_date
    )

    # SPY availability gate: need ≥ _RS_LOOKBACK + 1 rows before current_date
    # (production lines 200-270: should_skip_m7_today)
    def _spy_available(d: date) -> bool:
        rows = spy_df[spy_df["date_et"] < d]
        return len(rows) >= _RS_LOOKBACK + 1

    # Open positions
    open_positions: List[Dict] = []
    all_trades: List[Dict] = []

    for current_date in all_dates:
        # ── Manage exits first ──────────────────────────────────────────────
        still_open = []
        for pos in open_positions:
            ticker = pos["ticker"]
            if ticker not in daily_data:
                still_open.append(pos)
                continue
            df = daily_data[ticker]
            today_rows = df[df["date_et"] == current_date]
            if today_rows.empty:
                still_open.append(pos)
                continue
            today_close = float(today_rows.iloc[0]["daily_close"])
            days_held = pos["days_held"] + 1

            # Exit: BELOW_EMA9 daily (production module7.py:1073-1087)
            ema9_val = today_rows.iloc[0]["ema9"]
            if pd.notna(ema9_val) and today_close < float(ema9_val):
                all_trades.append(
                    _close_m7_trade(pos, today_close, current_date, "BELOW_EMA9", days_held)
                )
                continue

            # Exit: MAX_HOLD_6D (production DR_FROZEN_M7.AGENT_M7_MAX_HOLD_DAYS=6)
            if days_held >= _MAX_HOLD_DAYS:
                all_trades.append(
                    _close_m7_trade(pos, today_close, current_date, "MAX_HOLD_6D", days_held)
                )
                continue

            # Exit: STOP_PULLBACK_LOW (production module7.py:1073-1087)
            if today_close < pos.get("pullback_low", float("-inf")):
                all_trades.append(
                    _close_m7_trade(pos, today_close, current_date, "STOP_PULLBACK_LOW", days_held)
                )
                continue

            pos["days_held"] = days_held
            still_open.append(pos)

        open_positions = still_open

        # ── SPY availability gate (production lines 200-270) ─────────────────
        if not _spy_available(current_date):
            continue

        # ── Compute RS scores with CA guard (production lines 273-398) ───────
        spy_closes_today = spy_df[spy_df["date_et"] <= current_date]["daily_close"].tolist()
        rs_scores: Dict[str, float] = {}
        for ticker in universe:
            if ticker not in daily_data:
                rs_scores[ticker] = float("nan")
                continue
            df = daily_data[ticker]
            closes = df[df["date_et"] <= current_date]["daily_close"].tolist()
            if len(closes) < _RS_LOOKBACK + 1:
                rs_scores[ticker] = float("nan")
                continue
            # Step 1: compute return_20d (production line 307)
            return_20d = (closes[-1] - closes[-_RS_LOOKBACK - 1]) / closes[-_RS_LOOKBACK - 1]
            # Step 2: CA guard BEFORE rs_adjusted (production line 309-323)
            if abs(return_20d) > _CA_GUARD_THRESHOLD:
                rs_scores[ticker] = float("nan")
                continue
            # Step 3: compute rs_adjusted (production line 333)
            rs_scores[ticker] = _compute_rs_adjusted(closes, spy_closes_today)

        top_tickers = _select_top_30pct(rs_scores)

        # ── Override state (production line 1124-1133) ────────────────────────
        override_state = get_override_state_at(override_df, current_date)

        # ── Update pullback state machines for all tickers ─────────────────
        already_open_tickers = {p["ticker"] for p in open_positions}

        candidates: List[Dict] = []
        for ticker in universe:
            if ticker not in daily_data:
                continue

            df = daily_data[ticker]
            closes_td = df[df["date_et"] <= current_date]["daily_close"].tolist()
            if len(closes_td) < 2:
                states[ticker].reset()
                continue

            today_close = closes_td[-1]
            prior_close = closes_td[-2]
            ema21_rows = df[df["date_et"] == current_date]
            ema21 = float(ema21_rows.iloc[0]["ema"]) if not ema21_rows.empty and pd.notna(ema21_rows.iloc[0]["ema"]) else None

            # Override gate (production line 1124-1133)
            if override_state != "NORMAL":
                states[ticker].reset()
                continue

            # Top-30% gate (production line 1135-1138)
            if ticker not in top_tickers:
                states[ticker].reset()
                continue

            # Distance-to-60d-high gate (production line 1140-1145)
            high_60 = _rolling_high(closes_td)
            if high_60 is None:
                states[ticker].reset()
                continue
            distance_to_high_pct = (today_close - high_60) / high_60 * 100.0
            if distance_to_high_pct < _DISTANCE_THRESHOLD:
                # distance < -5.0% → stock too far from high → reset (production line 1140-1145)
                states[ticker].reset()
                continue

            # Advance state machine (production lines 1174-1219)
            recovery = states[ticker].step(today_close, prior_close, ema21)

            if recovery is None:
                continue  # no recovery signal

            # Recovery triggered — run pre-filter cascade (production lines 890-941)
            # Filter 1: earnings window (production line 890)
            if is_in_earnings_window(ticker, str(current_date), earnings_buffer_days, earnings_df):
                continue
            # Filter 2: active M4 position (production line 907)
            if _has_active_m4(ticker, current_date):
                continue
            # Filter 3: active M6 position (production line 920)
            if _has_active_m6(ticker, current_date):
                continue
            # Filter 4: existing M7 position (production line 933)
            if ticker in already_open_tickers:
                continue

            candidates.append(
                {
                    "ticker": ticker,
                    "entry_date": current_date,
                    "entry_price": today_close,
                    "pullback_low": recovery["pullback_low"],
                    "pullback_bars": recovery["pullback_bars"],
                    "rs_score": rs_scores.get(ticker, float("nan")),
                    "distance_from_high": abs(distance_to_high_pct),
                }
            )

        # Rank candidates and fill available slots
        candidates.sort(key=lambda c: (-c["distance_from_high"], -c["rs_score"]))
        for cand in candidates:
            if cand["ticker"] in {p["ticker"] for p in open_positions}:
                continue
            open_positions.append(
                {
                    "ticker": cand["ticker"],
                    "entry_date": cand["entry_date"],
                    "entry_price": cand["entry_price"],
                    "pullback_low": cand["pullback_low"],
                    "pullback_bars": cand["pullback_bars"],
                    "days_held": 0,
                }
            )

    # Close any positions still open at end of data
    for pos in open_positions:
        ticker = pos["ticker"]
        if ticker not in daily_data:
            continue
        df = daily_data[ticker]
        last_row = df[df["date_et"] <= end_date]
        if last_row.empty:
            continue
        last = last_row.iloc[-1]
        all_trades.append(
            _close_m7_trade(pos, float(last["daily_close"]), last["date_et"], "DATA_END", pos["days_held"])
        )

    return all_trades


def _close_m7_trade(pos: Dict, exit_price: float, exit_date: date, reason: str, days_held: int) -> Dict:
    return {
        "ticker": pos["ticker"],
        "entry_date": pos["entry_date"],
        "entry_price": pos["entry_price"],
        "exit_date": exit_date,
        "exit_price": exit_price,
        "exit_reason": reason,
        "return_pct": (exit_price - pos["entry_price"]) / pos["entry_price"],
        "days_held": days_held,
        "pullback_bars": pos.get("pullback_bars", 0),
    }
