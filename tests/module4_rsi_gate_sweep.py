#!/usr/bin/env python3
"""
Module 4 RSI Gate Sweep + Marginal Trade Analysis (Part 1 of 2).

Sweeps RSI gate thresholds for Module 4 (3-bar down-streak dip-buy)
across all certified equity tickers using 4H bars. Reports per-threshold
metrics and a marginal-trade analysis for the RSI 35-40 zone.

Output: results/rsi_gate_sweep.json + stdout tables.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

# ── Paths ────────────────────────────────────────────────────────────────
REPO = Path(__file__).resolve().parents[1]
INDICATORS_DIR = REPO / "data" / "indicators_4h"
VIX_PATH = REPO / "Fetched_Data" / "VIXCLS_FRED_real.csv"
RESULTS_DIR = REPO / "results"

# ── Config ───────────────────────────────────────────────────────────────
STREAK_THRESHOLD = 3
VIX_GATE = 25
HARD_MAX_BARS = 10
RSI_THRESHOLDS = [30, 32, 33, 34, 35, 36, 37, 38, 39, 40, 42, 45, 50, None]

EQUITY_TICKERS = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU", "C",
    "COIN", "COST", "GOOGL", "GS", "INTC", "JPM", "MARA", "META", "MSFT",
    "MSTR", "MU", "NVDA", "PLTR", "SMCI", "TSLA", "TSM", "V",
]


# ── Indicator functions ──────────────────────────────────────────────────
def compute_rsi_wilder(closes, period=14):
    """RSI with Wilder smoothing. Returns list aligned with closes."""
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
    """EMA with SMA seed. Returns list aligned with closes."""
    n = len(closes)
    out = [None] * n
    if n < period:
        return out
    out[period - 1] = float(np.mean(closes[:period]))
    k = 2.0 / (period + 1)
    for i in range(period, n):
        out[i] = closes[i] * k + out[i - 1] * (1 - k)
    return out


# ── Data loading ─────────────────────────────────────────────────────────
def load_vix_daily():
    """Load VIX daily close from FRED CSV → {date_str: float}."""
    df = pd.read_csv(VIX_PATH)
    vix = {}
    for _, row in df.iterrows():
        try:
            vix[str(row["observation_date"])] = float(row["VIXCLS"])
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
    """Load pre-computed 4H bars from indicators CSV, recompute RSI/EMA."""
    path = INDICATORS_DIR / f"{ticker}_4h_indicators.csv"
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
        })

    closes = np.array([b["close"] for b in bars])
    rsi_vals = compute_rsi_wilder(closes, 14)
    ema_vals = compute_ema(closes, 21)

    for i, b in enumerate(bars):
        b["rsi"] = rsi_vals[i]
        b["ema21"] = ema_vals[i]
    return bars


# ── Streak detection ─────────────────────────────────────────────────────
def is_down_v0(bar):
    """V0 (production): bar is down if close < open."""
    return bar["close"] < bar["open"]


def is_down_v2(bar, prev_bar):
    """V2 (shadow): bar is down if close < previous bar's close."""
    return bar["close"] < prev_bar["close"]


def count_streak_v0(bars, idx):
    """Count consecutive down bars ending at idx (V0 definition)."""
    streak = 0
    for j in range(idx, -1, -1):
        if is_down_v0(bars[j]):
            streak += 1
        else:
            break
    return streak


def count_streak_v2(bars, idx):
    """Count consecutive down bars ending at idx (V2 definition)."""
    streak = 0
    for j in range(idx, 0, -1):
        if is_down_v2(bars[j], bars[j - 1]):
            streak += 1
        else:
            break
    return streak


# ── Trade simulation ─────────────────────────────────────────────────────
def simulate_trades(bars, vix_daily, ticker, streak_fn, rsi_gate):
    """Find triggers and simulate Module 4 trades for one ticker."""
    trades = []
    in_trade_until = -1  # bar index when current trade exits

    start_idx = STREAK_THRESHOLD - 1 if streak_fn == "v0" else STREAK_THRESHOLD
    for i in range(start_idx, len(bars)):
        # Skip if we're still in a trade
        if i <= in_trade_until:
            continue

        bar = bars[i]
        # Need valid RSI and EMA21
        if bar["rsi"] is None or bar["ema21"] is None:
            continue

        # Check streak
        if streak_fn == "v0":
            streak = count_streak_v0(bars, i)
        else:
            streak = count_streak_v2(bars, i)
        if streak < STREAK_THRESHOLD:
            continue

        # RSI gate
        if rsi_gate is not None and bar["rsi"] >= rsi_gate:
            continue

        # VIX gate (prior-day close)
        vix_val = get_prior_vix(vix_daily, bar["date_str"])
        if vix_val is None or vix_val < VIX_GATE:
            continue

        # ── Entry ──
        entry_price = bar["close"]
        entry_idx = i

        # ── Exit: scan forward for EMA21 touch or hard max ──
        if i + 1 >= len(bars):
            continue  # no room to hold even 1 bar

        exit_price = None
        exit_reason = None
        exit_idx = None
        for k in range(1, HARD_MAX_BARS + 1):
            j = i + k
            if j >= len(bars):
                # End of data — exit at last available bar
                exit_price = bars[j - 1]["close"]
                exit_reason = "data_end"
                exit_idx = j - 1
                break
            if bars[j]["ema21"] is not None and bars[j]["close"] >= bars[j]["ema21"]:
                exit_price = bars[j]["close"]
                exit_reason = "ema21_touch"
                exit_idx = j
                break
            if k == HARD_MAX_BARS:
                exit_price = bars[j]["close"]
                exit_reason = "hard_max"
                exit_idx = j
                break

        if exit_price is None:
            continue

        in_trade_until = exit_idx
        ret_pct = (exit_price - entry_price) / entry_price * 100

        trades.append({
            "ticker": ticker,
            "trigger_time": str(bar["timestamp"]),
            "rsi": bar["rsi"],
            "vix": vix_val,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "return_pct": ret_pct,
            "hold_bars": exit_idx - entry_idx,
            "exit_reason": exit_reason,
            "streak": streak,
        })

    return trades


# ── Metrics ──────────────────────────────────────────────────────────────
def calc_metrics(trades):
    """Calculate aggregate metrics for a list of trades."""
    if not trades:
        return {
            "n": 0, "mean_pct": None, "median_pct": None, "wr_pct": None,
            "profit_factor": None, "sharpe": None, "worst_pct": None,
            "p_value": None,
        }

    rets = [t["return_pct"] for t in trades]
    arr = np.array(rets)
    gains = arr[arr > 0]
    losses = arr[arr <= 0]

    pf = (gains.sum() / abs(losses.sum())) if len(losses) > 0 and losses.sum() != 0 else float("inf")
    std = arr.std(ddof=1) if len(arr) > 1 else 0
    sharpe = float(arr.mean() / std) if std > 0 else float("inf")

    if len(arr) >= 2:
        _, p_val = stats.ttest_1samp(arr, 0)
    else:
        p_val = None

    return {
        "n": len(trades),
        "mean_pct": float(arr.mean()),
        "median_pct": float(np.median(arr)),
        "wr_pct": float((arr > 0).sum() / len(arr) * 100),
        "profit_factor": float(pf) if pf != float("inf") else 9999.99,
        "sharpe": float(sharpe) if sharpe != float("inf") else 9999.99,
        "worst_pct": float(arr.min()),
        "p_value": float(p_val) if p_val is not None else None,
    }


# ── Main sweep ───────────────────────────────────────────────────────────
def run_sweep():
    print("=" * 80)
    print("Module 4 RSI Gate Sweep — Part 1")
    print("=" * 80)

    # Load VIX
    vix_daily = load_vix_daily()
    vix_dates = sorted(vix_daily.keys())
    print(f"\nVIX data: {vix_dates[0]} → {vix_dates[-1]} ({len(vix_dates)} days)")

    # Load all ticker 4H bars
    all_bars = {}
    date_min, date_max = None, None
    total_bars = 0
    for ticker in EQUITY_TICKERS:
        path = INDICATORS_DIR / f"{ticker}_4h_indicators.csv"
        if not path.exists():
            print(f"  SKIP {ticker}: no 4H data")
            continue
        bars = load_4h_bars(ticker)
        all_bars[ticker] = bars
        total_bars += len(bars)
        d0, d1 = bars[0]["date_str"], bars[-1]["date_str"]
        if date_min is None or d0 < date_min:
            date_min = d0
        if date_max is None or d1 > date_max:
            date_max = d1

    tickers_used = sorted(all_bars.keys())
    print(f"Tickers loaded: {len(tickers_used)} ({total_bars} total 4H bars)")
    print(f"Date range: {date_min} → {date_max}")

    # Stage 0: sanity checks
    print("\n── Stage 0: Data Verification ──")
    bar_counts = {}
    for ticker, bars in all_bars.items():
        dates = set(b["date_str"] for b in bars)
        bars_per_day = len(bars) / len(dates) if dates else 0
        bar_counts[ticker] = bars_per_day
    mean_bpd = np.mean(list(bar_counts.values()))
    print(f"  Mean bars/day: {mean_bpd:.2f} (expected: 2.0)")
    outliers = {t: v for t, v in bar_counts.items() if abs(v - 2.0) > 0.05}
    if outliers:
        print(f"  WARNING: bar-count outliers: {outliers}")
    else:
        print("  ✓ All tickers have ~2 bars/day")
    print(f"  ✓ RSI computed from completed 4H bars only (no lookahead)")
    print(f"  ✓ VIX uses prior-day close via get_prior_vix()")

    # ── Sweep ──
    results = {"v0": {}, "v2": {}}  # rsi_gate → list of trades

    for streak_type in ["v0", "v2"]:
        for rsi_gate in RSI_THRESHOLDS:
            all_trades = []
            for ticker, bars in all_bars.items():
                trades = simulate_trades(bars, vix_daily, ticker, streak_type, rsi_gate)
                all_trades.extend(trades)
            gate_key = rsi_gate if rsi_gate is not None else "no_gate"
            results[streak_type][gate_key] = all_trades

    # ── Print Tables ──
    for streak_type in ["v0", "v2"]:
        label = "V0 (close<open)" if streak_type == "v0" else "V2 (close<prev_close)"
        print(f"\n{'=' * 80}")
        print(f"Table: RSI Gate Sweep — {label}")
        print(f"{'=' * 80}")
        header = f"{'RSI Gate':>9} | {'N':>5} | {'Mean %':>8} | {'Med %':>8} | {'WR %':>6} | {'PF':>9} | {'Sharpe':>7} | {'Worst %':>8} | {'p-value':>8}"
        print(header)
        print("-" * len(header))

        for rsi_gate in RSI_THRESHOLDS:
            gate_key = rsi_gate if rsi_gate is not None else "no_gate"
            trades = results[streak_type][gate_key]
            m = calc_metrics(trades)
            gate_str = f"{rsi_gate}" if rsi_gate is not None else "no_gate"
            if rsi_gate == 35:
                gate_str += " ★"

            if m["n"] == 0:
                print(f"{gate_str:>9} | {0:>5} |      — |      — |    — |       — |     — |      — |      —")
                continue

            p_str = f"{m['p_value']:.4f}" if m["p_value"] is not None else "—"
            pf_str = f"{m['profit_factor']:.2f}" if m["profit_factor"] < 9999 else "inf"
            sh_str = f"{m['sharpe']:.2f}" if m["sharpe"] < 9999 else "inf"
            print(
                f"{gate_str:>9} | {m['n']:>5} | {m['mean_pct']:>+8.2f} | "
                f"{m['median_pct']:>+8.2f} | {m['wr_pct']:>5.1f} | "
                f"{pf_str:>9} | {sh_str:>7} | {m['worst_pct']:>+8.2f} | {p_str:>8}"
            )

    # ── Marginal Trade Analysis (V2, RSI 35-40) ──
    print(f"\n{'=' * 80}")
    print("Marginal Trade Analysis — V2 streak, RSI gate 35 vs 40")
    print(f"{'=' * 80}")

    trades_35 = results["v2"].get(35, [])
    trades_40 = results["v2"].get(40, [])
    core_keys = {(t["ticker"], t["trigger_time"]) for t in trades_35}
    marginal = [t for t in trades_40 if (t["ticker"], t["trigger_time"]) not in core_keys]

    print(f"\nCore trades (RSI<35): {len(trades_35)}")
    print(f"All trades (RSI<40):  {len(trades_40)}")
    print(f"Marginal (35≤RSI<40): {len(marginal)}")

    if marginal:
        print(f"\n{'Ticker':>8} | {'Trigger Time':>22} | {'RSI':>6} | {'Ret %':>8} | {'Bars':>5} | {'Exit':>12}")
        print("-" * 75)
        for t in sorted(marginal, key=lambda x: x["trigger_time"]):
            print(
                f"{t['ticker']:>8} | {t['trigger_time']:>22} | {t['rsi']:>6.1f} | "
                f"{t['return_pct']:>+8.2f} | {t['hold_bars']:>5} | {t['exit_reason']:>12}"
            )

    # Marginal vs Core comparison
    print(f"\n{'Group':>16} | {'N':>5} | {'Mean %':>8} | {'WR %':>6} | {'PF':>9} | {'MW p':>8}")
    print("-" * 65)

    core_m = calc_metrics(trades_35)
    marg_m = calc_metrics(marginal)

    if len(trades_35) > 0 and len(marginal) > 0:
        mw_stat, mw_p = stats.mannwhitneyu(
            [t["return_pct"] for t in trades_35],
            [t["return_pct"] for t in marginal],
            alternative="two-sided",
        )
    else:
        mw_p = None

    def fmt_row(label, m, p=None):
        if m["n"] == 0:
            return f"{label:>16} | {0:>5} |      — |    — |       — |      —"
        pf_s = f"{m['profit_factor']:.2f}" if m["profit_factor"] < 9999 else "inf"
        p_s = f"{p:.4f}" if p is not None else "—"
        return (
            f"{label:>16} | {m['n']:>5} | {m['mean_pct']:>+8.2f} | "
            f"{m['wr_pct']:>5.1f} | {pf_s:>9} | {p_s:>8}"
        )

    print(fmt_row("Core (RSI<35)", core_m, None))
    print(fmt_row("Marginal(35-40)", marg_m, mw_p))

    # ── Save JSON ──
    RESULTS_DIR.mkdir(exist_ok=True)

    def sweep_to_list(sweep_dict):
        out = []
        for rsi_gate in RSI_THRESHOLDS:
            gate_key = rsi_gate if rsi_gate is not None else "no_gate"
            m = calc_metrics(sweep_dict[gate_key])
            m["rsi_gate"] = rsi_gate
            out.append(m)
        return out

    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "data_range": {"start": date_min, "end": date_max},
        "tickers_used": tickers_used,
        "vix_source": str(VIX_PATH),
        "v0_sweep": sweep_to_list(results["v0"]),
        "v2_sweep": sweep_to_list(results["v2"]),
        "marginal_trades_v2": [
            {
                "ticker": t["ticker"],
                "time": t["trigger_time"],
                "rsi": round(t["rsi"], 2),
                "return_pct": round(t["return_pct"], 4),
                "hold_bars": t["hold_bars"],
                "exit_reason": t["exit_reason"],
                "vix": t["vix"],
                "streak": t["streak"],
            }
            for t in sorted(marginal, key=lambda x: x["trigger_time"])
        ],
        "marginal_vs_core": {
            "core_n": core_m["n"],
            "core_mean_pct": core_m["mean_pct"],
            "marginal_n": marg_m["n"],
            "marginal_mean_pct": marg_m["mean_pct"],
            "mann_whitney_p": float(mw_p) if mw_p is not None else None,
        },
    }

    out_path = RESULTS_DIR / "rsi_gate_sweep.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved → {out_path}")


if __name__ == "__main__":
    run_sweep()
