#!/usr/bin/env python3
"""
Module 4 Envelope Tests — Shared Data Loading, Trigger Detection, Trade Simulation.

Frozen parameters (from validated M4 backtest):
  TRIGGER:  3 consecutive 4H down bars (close < open)
  REGIME:   prior-day VIX close >= 25
  STRETCH:  4H RSI(14) < 35 at trigger bar
  ENTRY:    buy at 4H trigger bar close
  EXIT:     first 4H close >= EMA21 (primary) OR 10 completed 4H bars (hard max)
  SCOPE:    25 equity tickers
"""

import math
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
INDICATORS_4H_DIR = ROOT / "data" / "indicators_4h"
VIX_PATH = ROOT / "Fetched_Data" / "VIXCLS_FRED_real.csv"
OUTPUT_DIR = ROOT / "backtest_output" / "m4_envelope"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Frozen Config ────────────────────────────────────────────────────────────
TICKERS = [
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN",
    "COST", "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU",
    "NVDA", "PLTR", "SNOW", "TSLA", "TSM", "TXN", "V",
]

STREAK_LEN = 3
VIX_THRESHOLD = 25.0
RSI_GATE = 35.0
EMA_PERIOD = 21
HARD_MAX_BARS = 10


# ── Indicator Computation ────────────────────────────────────────────────────

def compute_rsi_wilder(closes, period=14):
    """Wilder RSI. Returns list aligned with closes (None for warmup)."""
    n = len(closes)
    out = [None] * n
    if n < period + 1:
        return out
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            out[i + 1] = 100.0
        else:
            out[i + 1] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def compute_ema(closes, period=21):
    """EMA with SMA seed. Returns list aligned with closes (None for warmup)."""
    n = len(closes)
    out = [None] * n
    if n < period:
        return out
    out[period - 1] = float(np.mean(closes[:period]))
    k = 2.0 / (period + 1)
    for i in range(period, n):
        out[i] = closes[i] * k + out[i - 1] * (1 - k)
    return out


# ── Data Loading ─────────────────────────────────────────────────────────────

def load_vix_daily():
    """Load VIX daily close from FRED CSV → {date_str: float}."""
    df = pd.read_csv(VIX_PATH)
    vix = {}
    for _, row in df.iterrows():
        try:
            val = float(row["VIXCLS"])
            if math.isnan(val):
                continue
            vix[str(row["observation_date"])] = val
        except (ValueError, TypeError):
            continue
    return vix


def get_prior_vix(vix_daily, date_str):
    """Prior trading day's VIX close (no lookahead)."""
    dt = pd.Timestamp(date_str)
    for offset in range(1, 6):
        prior = (dt - timedelta(days=offset)).strftime("%Y-%m-%d")
        if prior in vix_daily:
            return vix_daily[prior]
    return None


def load_4h_bars(ticker):
    """Load 4H bars, recompute RSI(14) and EMA(21) from close prices."""
    path = INDICATORS_4H_DIR / f"{ticker}_4h_indicators.csv"
    df = pd.read_csv(path, parse_dates=["timestamp"])
    bars = []
    for _, row in df.iterrows():
        bars.append({
            "timestamp": row["timestamp"],
            "date_str": row["timestamp"].strftime("%Y-%m-%d"),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]) if pd.notna(row.get("volume")) else 0,
        })

    closes = np.array([b["close"] for b in bars])
    rsi_vals = compute_rsi_wilder(closes, 14)
    ema_vals = compute_ema(closes, EMA_PERIOD)

    for i, b in enumerate(bars):
        b["rsi"] = rsi_vals[i]
        b["ema21"] = ema_vals[i]
    return bars


def load_all_bars(tickers=None):
    """Load 4H bars for all tickers. Returns {ticker: bars_list}."""
    if tickers is None:
        tickers = TICKERS
    all_bars = {}
    for ticker in tickers:
        path = INDICATORS_4H_DIR / f"{ticker}_4h_indicators.csv"
        if not path.exists():
            continue
        all_bars[ticker] = load_4h_bars(ticker)
    return all_bars


# ── Streak Detection ─────────────────────────────────────────────────────────

def count_down_streak(bars, idx):
    """Count consecutive down bars (close < open) ending at idx."""
    streak = 0
    for j in range(idx, -1, -1):
        if bars[j]["close"] < bars[j]["open"]:
            streak += 1
        else:
            break
    return streak


# ── Trade Simulation ─────────────────────────────────────────────────────────

def simulate_trade(bars, entry_idx, entry_price, ema_period=EMA_PERIOD,
                   hard_max=HARD_MAX_BARS):
    """Simulate a single M4 trade from entry_idx.

    Exit: first 4H close >= EMA(ema_period) after entry, or hard_max bars.
    Returns trade dict or None if insufficient data.
    """
    if entry_idx + 1 >= len(bars):
        return None

    exit_price = None
    exit_reason = None
    exit_idx = None

    for k in range(1, hard_max + 1):
        j = entry_idx + k
        if j >= len(bars):
            exit_price = bars[j - 1]["close"]
            exit_reason = "data_end"
            exit_idx = j - 1
            break
        ema_val = bars[j]["ema21"]
        if ema_val is not None and bars[j]["close"] >= ema_val:
            exit_price = bars[j]["close"]
            exit_reason = "ema21_touch"
            exit_idx = j
            break
        if k == hard_max:
            exit_price = bars[j]["close"]
            exit_reason = "hard_max"
            exit_idx = j
            break

    if exit_price is None:
        return None

    ret_pct = (exit_price - entry_price) / entry_price * 100

    # MAE / MFE during hold
    hold_bars = bars[entry_idx:exit_idx + 1]
    lows = [b["low"] for b in hold_bars]
    highs = [b["high"] for b in hold_bars]
    mae = (min(lows) - entry_price) / entry_price * 100
    mfe = (max(highs) - entry_price) / entry_price * 100

    return {
        "entry_price": entry_price,
        "exit_price": exit_price,
        "return_pct": ret_pct,
        "hold_bars": exit_idx - entry_idx,
        "exit_reason": exit_reason,
        "entry_idx": entry_idx,
        "exit_idx": exit_idx,
        "mae": mae,
        "mfe": mfe,
    }


# ── Full Baseline Backtest ───────────────────────────────────────────────────

def run_baseline(tickers=None, vix_threshold=VIX_THRESHOLD, streak_len=STREAK_LEN,
                 rsi_gate=RSI_GATE, ema_period=EMA_PERIOD, hard_max=HARD_MAX_BARS,
                 all_bars=None, vix_daily=None):
    """Run the M4 baseline strategy. Returns list of trade dicts.

    Each trade dict includes: ticker, trigger_time, date_str, vix, rsi,
    streak, entry_price, exit_price, return_pct, hold_bars, exit_reason,
    entry_idx, exit_idx, mae, mfe.
    """
    if tickers is None:
        tickers = TICKERS
    if vix_daily is None:
        vix_daily = load_vix_daily()
    if all_bars is None:
        all_bars = load_all_bars(tickers)

    trades = []

    for ticker in tickers:
        bars = all_bars.get(ticker)
        if bars is None:
            continue

        # Recompute EMA if non-default period
        if ema_period != EMA_PERIOD:
            closes = np.array([b["close"] for b in bars])
            ema_vals = compute_ema(closes, ema_period)
            for i, b in enumerate(bars):
                b["ema21"] = ema_vals[i]

        in_trade_until = -1

        for i in range(streak_len - 1, len(bars)):
            if i <= in_trade_until:
                continue

            bar = bars[i]
            if bar["rsi"] is None or bar["ema21"] is None:
                continue

            # Streak check
            streak = count_down_streak(bars, i)
            if streak < streak_len:
                continue

            # RSI gate
            if rsi_gate is not None and bar["rsi"] >= rsi_gate:
                continue

            # VIX gate
            vix_val = get_prior_vix(vix_daily, bar["date_str"])
            if vix_val is None or vix_val < vix_threshold:
                continue

            # Entry
            entry_price = bar["close"]
            trade = simulate_trade(bars, i, entry_price, ema_period, hard_max)
            if trade is None:
                continue

            in_trade_until = trade["exit_idx"]

            trade["ticker"] = ticker
            trade["trigger_time"] = str(bar["timestamp"])
            trade["date_str"] = bar["date_str"]
            trade["vix"] = vix_val
            trade["rsi"] = bar["rsi"]
            trade["streak"] = streak
            trades.append(trade)

    return trades


# ── Metrics ──────────────────────────────────────────────────────────────────

def calc_metrics(trades):
    """Compute summary metrics for a list of trades."""
    if not trades:
        return {
            "n": 0, "mean_pct": 0.0, "median_pct": 0.0, "wr_pct": 0.0,
            "profit_factor": 0.0, "sharpe": 0.0, "worst_pct": 0.0,
            "best_pct": 0.0, "p_value": 1.0,
        }

    rets = np.array([t["return_pct"] for t in trades])
    gains = rets[rets > 0]
    losses = rets[rets <= 0]

    n = len(rets)
    mean_pct = float(rets.mean())
    median_pct = float(np.median(rets))
    wr_pct = float((rets > 0).sum() / n * 100)

    gross_profit = float(gains.sum()) if len(gains) > 0 else 0.0
    gross_loss = float(abs(losses.sum())) if len(losses) > 0 else 0.0
    pf = gross_profit / gross_loss if gross_loss > 0 else 9999.99

    std = float(rets.std(ddof=1)) if n > 1 else 0.0
    sharpe = float(mean_pct / std) if std > 0 else 9999.99

    if n >= 2:
        _, p_val = stats.ttest_1samp(rets, 0)
        p_val = float(p_val)
    else:
        p_val = 1.0

    return {
        "n": n,
        "mean_pct": mean_pct,
        "median_pct": median_pct,
        "wr_pct": wr_pct,
        "profit_factor": min(pf, 9999.99),
        "sharpe": min(sharpe, 9999.99),
        "worst_pct": float(rets.min()),
        "best_pct": float(rets.max()),
        "p_value": p_val,
    }


def fmt_pf(pf):
    return "inf" if pf >= 9999 else f"{pf:.2f}"


def fmt_sharpe(s):
    return "inf" if s >= 9999 else f"{s:.2f}"
