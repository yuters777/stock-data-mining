#!/usr/bin/env python3
"""
S44 Module 4 Streak Sensitivity — V0 / V1 / V2.

Tests 3 streak definitions for Module 4 trigger, comparing trigger count and
performance.

Common setup (all variants):
  Trigger:  streak condition (varies) AND prior-day VIX close >= 25 AND 4H RSI(14) < 35
  Entry:    4H trigger bar close
  Exit:     first 4H close >= EMA21 (hard max 10 bars)
  Scope:    23 equity tickers (AAPL..V, excl SPY/VIXY)

V0 — Baseline:  DOWN = close < open; streak = 3 consecutive DOWN bars
V1 — Min Body:  DOWN = (open-close)/open > 0.1%; NEUTRAL (<=0.1%) skipped, doesn't break
V2 — Close-Close: DOWN = close < prior_bar_close; streak = 3 consecutive
"""

import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── Config ───────────────────────────────────────────────────────────────────

TICKERS = [
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN",
    "COST", "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU",
    "NVDA", "PLTR", "SNOW", "TSLA", "TSM", "TXN", "V",
]

VIX_THRESHOLD = 25.0
RSI_THRESHOLD = 35.0
STREAK_LEN = 3
MAX_HOLD = 10          # hard max bars for exit
BODY_THRESHOLD = 0.001  # 0.1% for V1

INDICATORS_4H_DIR = ROOT / "data" / "indicators_4h"
VIX_PATH = ROOT / "Fetched_Data" / "VIXCLS_FRED_real.csv"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# ── Helpers ──────────────────────────────────────────────────────────────────

def load_vix_daily():
    df = pd.read_csv(VIX_PATH)
    vix = {}
    for _, row in df.iterrows():
        try:
            val = float(row["VIXCLS"])
            vix[str(row["observation_date"])] = val
        except (ValueError, TypeError):
            continue
    return vix


def load_4h_bars(ticker):
    path = INDICATORS_4H_DIR / f"{ticker}_4h_indicators.csv"
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["date_str"] = df["timestamp"].dt.strftime("%Y-%m-%d")
    return df


def get_prior_vix(vix_daily, date_str):
    dt = pd.Timestamp(date_str)
    for offset in range(1, 6):
        prior = (dt - timedelta(days=offset)).strftime("%Y-%m-%d")
        if prior in vix_daily:
            return vix_daily[prior]
    return None


# ── Streak detectors ────────────────────────────────────────────────────────

def detect_v0(bars):
    """V0: DOWN = close < open. 3 consecutive DOWN bars."""
    is_down = bars["close"] < bars["open"]
    triggers = []
    for i in range(STREAK_LEN - 1, len(bars)):
        if all(is_down.iloc[i - j] for j in range(STREAK_LEN)):
            triggers.append(i)
    return triggers


def detect_v1(bars):
    """V1: DOWN = (open-close)/open > 0.1%. NEUTRAL skipped (doesn't break)."""
    body_pct = (bars["open"] - bars["close"]) / bars["open"]
    is_down = body_pct > BODY_THRESHOLD
    is_neutral = body_pct.abs() <= BODY_THRESHOLD
    # is_up = body_pct < -BODY_THRESHOLD  (breaks streak)

    triggers = []
    for i in range(len(bars)):
        # Walk backwards from bar i, skipping neutrals, counting downs
        count = 0
        j = i
        while j >= 0 and count < STREAK_LEN:
            if is_down.iloc[j]:
                count += 1
                j -= 1
            elif is_neutral.iloc[j]:
                j -= 1  # skip neutral
            else:
                break  # up bar breaks streak
        if count >= STREAK_LEN:
            triggers.append(i)
    return triggers


def detect_v2(bars):
    """V2: DOWN = close < prior_bar_close. 3 consecutive."""
    closes = bars["close"].values
    is_down = pd.Series([False] + [closes[i] < closes[i - 1] for i in range(1, len(closes))],
                        index=bars.index)
    triggers = []
    for i in range(STREAK_LEN, len(bars)):  # need prior close for first bar
        if all(is_down.iloc[i - j] for j in range(STREAK_LEN)):
            triggers.append(i)
    return triggers


# ── Exit logic ──────────────────────────────────────────────────────────────

def compute_exit(bars, entry_idx, entry_price):
    """Exit at first 4H close >= EMA21, hard max 10 bars."""
    for j in range(entry_idx + 1, min(entry_idx + MAX_HOLD + 1, len(bars))):
        bar = bars.iloc[j]
        ema21 = bar.get("ema_21")
        if pd.notna(ema21) and bar["close"] >= ema21:
            exit_price = bar["close"]
            return _trade(bars, entry_idx, j, entry_price, exit_price)
    # Hard max: exit at bar +MAX_HOLD
    max_idx = entry_idx + MAX_HOLD
    if max_idx < len(bars):
        return _trade(bars, entry_idx, max_idx, entry_price, bars.iloc[max_idx]["close"])
    return None


def _trade(bars, entry_idx, exit_idx, entry_price, exit_price):
    ret = (exit_price - entry_price) / entry_price * 100
    hold = bars.iloc[entry_idx:exit_idx + 1]
    return {
        "return_pct": ret,
        "exit_price": exit_price,
        "hold_bars": exit_idx - entry_idx,
        "win": ret > 0,
        "mae": (hold["low"].min() - entry_price) / entry_price * 100,
        "mfe": (hold["high"].max() - entry_price) / entry_price * 100,
    }


# ── Metrics ─────────────────────────────────────────────────────────────────

def compute_metrics(trades):
    if not trades:
        return {"N": 0, "mean": 0, "wr": 0, "pf": 0, "sharpe": 0, "p": 1.0}

    rets = [t["return_pct"] for t in trades]
    n = len(rets)
    mean_r = np.mean(rets)
    std_r = np.std(rets, ddof=1) if n > 1 else 1.0
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0.001
    pf = gross_profit / gross_loss
    wr = len(wins) / n * 100
    sharpe = mean_r / std_r * np.sqrt(n) if std_r > 0 else 0

    if n >= 2:
        t_stat, p_val = stats.ttest_1samp(rets, 0)
        p_val = p_val / 2 if t_stat > 0 else 1 - p_val / 2
    else:
        p_val = 1.0

    return {"N": n, "mean": mean_r, "wr": wr, "pf": pf, "sharpe": sharpe, "p": p_val}


# ── Main ────────────────────────────────────────────────────────────────────

def run():
    vix_daily = load_vix_daily()
    print(f"VIX: {len(vix_daily)} days loaded")

    detectors = {"V0": detect_v0, "V1": detect_v1, "V2": detect_v2}

    # {variant: list of (ticker, date_str, trade_dict)}
    all_trades = {v: [] for v in detectors}
    # {variant: set of (ticker, date_str)}
    all_trigger_keys = {v: set() for v in detectors}

    for ticker in TICKERS:
        print(f"  {ticker}...", end="", flush=True)
        bars = load_4h_bars(ticker)

        for vname, detect_fn in detectors.items():
            raw_triggers = detect_fn(bars)

            for idx in raw_triggers:
                bar = bars.iloc[idx]

                # RSI filter
                rsi = bar.get("rsi_14")
                if pd.isna(rsi) or rsi >= RSI_THRESHOLD:
                    continue

                # VIX filter
                vix_val = get_prior_vix(vix_daily, bar["date_str"])
                if vix_val is None or vix_val < VIX_THRESHOLD:
                    continue

                key = (ticker, bar["date_str"], str(bar["timestamp"]))
                all_trigger_keys[vname].add(key)

                entry_price = bar["close"]
                trade = compute_exit(bars, idx, entry_price)
                if trade:
                    trade["ticker"] = ticker
                    trade["date_str"] = bar["date_str"]
                    trade["timestamp"] = str(bar["timestamp"])
                    all_trades[vname].append(trade)

        print(" done")

    # ── Compute metrics ─────────────────────────────────────────────────────
    metrics = {}
    for v in detectors:
        metrics[v] = compute_metrics(all_trades[v])

    # ── Diff vs V0 ──────────────────────────────────────────────────────────
    v0_keys = all_trigger_keys["V0"]
    diffs = {}
    for v in ["V1", "V2"]:
        extra = all_trigger_keys[v] - v0_keys
        lost = v0_keys - all_trigger_keys[v]
        # Quality of extra triggers
        extra_trades = [t for t in all_trades[v]
                        if (t["ticker"], t["date_str"], t["timestamp"]) in extra]
        extra_m = compute_metrics(extra_trades)
        diffs[v] = {"extra": extra, "lost": lost, "extra_metrics": extra_m}

    # ── Report ───────────────────────────────────────────────────────────────
    lines = []
    lines.append("# S44 Module 4 Streak Sensitivity — V0 / V1 / V2")
    lines.append("")
    lines.append(f"**Date:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Tickers:** {len(TICKERS)} (excl SPY, VIXY)")
    lines.append(f"**Filters:** prior-day VIX >= {VIX_THRESHOLD}, 4H RSI(14) < {RSI_THRESHOLD}")
    lines.append(f"**Entry:** 4H trigger bar close")
    lines.append(f"**Exit:** first 4H close >= EMA21 (hard max {MAX_HOLD} bars)")
    lines.append("")

    # Summary line for each variant
    lines.append("## Summary")
    lines.append("")
    m = metrics["V0"]
    sig = _sig(m["p"])
    lines.append(f"```")
    lines.append(f"V0: N={m['N']} | Mean={m['mean']:+.2f}% | WR={m['wr']:.0f}% | "
                 f"PF={m['pf']:.2f} | Sharpe={m['sharpe']:.2f} | p={m['p']:.4f}{sig}")

    for v in ["V1", "V2"]:
        m = metrics[v]
        d = diffs[v]
        sig = _sig(m["p"])
        lines.append(f"{v}: N={m['N']} | Mean={m['mean']:+.2f}% | WR={m['wr']:.0f}% | "
                     f"PF={m['pf']:.2f} | Sharpe={m['sharpe']:.2f} | p={m['p']:.4f}{sig} | "
                     f"+{len(d['extra'])} extra / -{len(d['lost'])} lost")
    lines.append(f"```")
    lines.append("")

    # Extra / lost trigger details
    for v in ["V1", "V2"]:
        d = diffs[v]
        lines.append(f"## {v} — Extra Triggers vs V0 ({len(d['extra'])})")
        lines.append("")
        if d["extra"]:
            lines.append("| Ticker | Date | Timestamp |")
            lines.append("|--------|------|-----------|")
            for ticker, date_str, ts in sorted(d["extra"]):
                lines.append(f"| {ticker} | {date_str} | {ts} |")
            em = d["extra_metrics"]
            lines.append("")
            lines.append(f"Extra triggers quality: N={em['N']}, Mean={em['mean']:+.2f}%, WR={em['wr']:.0f}%")
        else:
            lines.append("*(none)*")
        lines.append("")

        lines.append(f"## {v} — Lost Triggers vs V0 ({len(d['lost'])})")
        lines.append("")
        if d["lost"]:
            lines.append("| Ticker | Date | Timestamp |")
            lines.append("|--------|------|-----------|")
            for ticker, date_str, ts in sorted(d["lost"]):
                lines.append(f"| {ticker} | {date_str} | {ts} |")
        else:
            lines.append("*(none)*")
        lines.append("")

    report = "\n".join(lines)

    out_path = RESULTS_DIR / "S44_Module4_Streak_Sensitivity.md"
    out_path.write_text(report)
    print(f"\nResults saved to {out_path}")
    print()
    print(report)


def _sig(p):
    if p < 0.001:
        return "***"
    elif p < 0.01:
        return "**"
    elif p < 0.05:
        return "*"
    return ""


if __name__ == "__main__":
    run()
