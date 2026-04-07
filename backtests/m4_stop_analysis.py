#!/usr/bin/env python3
"""
Module 4 MAE/MFE Distribution + Delayed Catastrophe Stop Backtest.

Tasks:
  1. Per-trade MAE/MFE study for all M4 triggers
  2. Stop-loss variant comparison (V0-V10)
  3. Regime-based MAE breakdown (VIX / RSI / ticker class)

Trigger:  3 consecutive 4H down bars (close < open) + prior-day VIX >= 25 + 4H RSI(14) < 35
Entry:    4H trigger bar close
Exit:     first 4H close >= EMA21 (hard max 10 bars)

Uses certified 4H dataset (same as S44 cycle).
"""

import csv
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── Config ──────────────────────────────────────────────────────────────────

TICKERS = [
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN",
    "COST", "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU",
    "NVDA", "PLTR", "SNOW", "TSLA", "TSM", "TXN", "V",
]

VIX_THRESHOLD = 25.0
RSI_THRESHOLD = 35.0
STREAK_LEN = 3
MAX_HOLD = 10
ATR_PERIOD = 14

INDICATORS_4H_DIR = ROOT / "data" / "indicators_4h"
VIX_PATH = ROOT / "Fetched_Data" / "VIXCLS_FRED_real.csv"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# Ticker classifications for regime analysis
MEGA_CAP_TECH = {"AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA"}
ADR_TICKERS = {"BABA", "BIDU", "TSM"}
CRYPTO_PROXY = {"COIN", "IBIT", "MARA"}

# ── Data loaders ────────────────────────────────────────────────────────────

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
    # Compute ATR(14) using Wilder's smoothing
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr_14"] = tr.ewm(alpha=1.0 / ATR_PERIOD, adjust=False).mean()
    return df


def get_prior_vix(vix_daily, date_str):
    dt = pd.Timestamp(date_str)
    for offset in range(1, 6):
        prior = (dt - timedelta(days=offset)).strftime("%Y-%m-%d")
        if prior in vix_daily:
            return vix_daily[prior]
    return None


# ── Trigger detection ───────────────────────────────────────────────────────

def detect_triggers(bars, vix_daily):
    """V0: DOWN = close < open, 3 consecutive + VIX >= 25 + RSI < 35."""
    is_down = bars["close"] < bars["open"]
    triggers = []
    for i in range(STREAK_LEN - 1, len(bars)):
        if not all(is_down.iloc[i - j] for j in range(STREAK_LEN)):
            continue
        bar = bars.iloc[i]
        rsi = bar.get("rsi_14")
        if pd.isna(rsi) or rsi >= RSI_THRESHOLD:
            continue
        vix_val = get_prior_vix(vix_daily, bar["date_str"])
        if vix_val is None or vix_val < VIX_THRESHOLD:
            continue
        triggers.append(i)
    return triggers


# ── Trade execution with full bar-by-bar tracking ──────────────────────────

def execute_trade(bars, entry_idx, entry_price):
    """Execute baseline trade (EMA21 exit / hard max 10) with bar-by-bar tracking."""
    bar_returns = []  # (bar_num, close_return, low_return, high_return)
    exit_idx = None
    exit_reason = None
    exit_price = None

    for j in range(entry_idx + 1, min(entry_idx + MAX_HOLD + 1, len(bars))):
        bar = bars.iloc[j]
        bar_num = j - entry_idx
        close_ret = (bar["close"] - entry_price) / entry_price
        low_ret = (bar["low"] - entry_price) / entry_price
        high_ret = (bar["high"] - entry_price) / entry_price
        bar_returns.append((bar_num, close_ret, low_ret, high_ret, bar["close"]))

        ema21 = bar.get("ema_21")
        if exit_idx is None and pd.notna(ema21) and bar["close"] >= ema21:
            exit_idx = j
            exit_reason = "ema21"
            exit_price = bar["close"]
            break

    if exit_idx is None:
        max_idx = entry_idx + MAX_HOLD
        if max_idx < len(bars):
            exit_idx = max_idx
            exit_reason = "hard_max"
            exit_price = bars.iloc[max_idx]["close"]
            # Ensure we have all bars tracked
            for j in range(entry_idx + 1 + len(bar_returns), max_idx + 1):
                if j >= len(bars):
                    break
                bar = bars.iloc[j]
                bar_num = j - entry_idx
                close_ret = (bar["close"] - entry_price) / entry_price
                low_ret = (bar["low"] - entry_price) / entry_price
                high_ret = (bar["high"] - entry_price) / entry_price
                bar_returns.append((bar_num, close_ret, low_ret, high_ret, bar["close"]))
        else:
            return None

    # Compute MAE/MFE from bar-by-bar data
    if not bar_returns:
        return None

    close_rets = [r[1] for r in bar_returns]
    low_rets = [r[2] for r in bar_returns]
    high_rets = [r[3] for r in bar_returns]
    bar_nums = [r[0] for r in bar_returns]

    mae_close = min(close_rets)
    mae_low = min(low_rets)
    mfe = max(high_rets)
    bars_to_mae = bar_nums[close_rets.index(mae_close)]
    mfe_high_idx = high_rets.index(mfe)
    bars_to_mfe = bar_nums[mfe_high_idx]
    final_return = (exit_price - entry_price) / entry_price

    return {
        "exit_idx": exit_idx,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "final_return": final_return,
        "mae_close": mae_close,
        "mae_low": mae_low,
        "mfe": mfe,
        "bars_to_mae": bars_to_mae,
        "bars_to_mfe": bars_to_mfe,
        "bars_held": exit_idx - entry_idx,
        "bar_returns": bar_returns,  # for stop simulation
    }


# ── Stop variant simulation ────────────────────────────────────────────────

def apply_stop(trade, entry_price, atr_at_entry, variant):
    """Apply a stop variant to a trade. Returns (stopped, stop_bar, stop_price)."""
    bar_returns = trade["bar_returns"]
    vname, threshold_pct, atr_mult, delayed, combo_atr, combo_pct = variant

    for bar_num, close_ret, low_ret, high_ret, bar_close in bar_returns:
        # Delayed stops only activate bar 5+
        if delayed and bar_num < 5:
            continue

        # Determine stop level
        if combo_atr is not None and combo_pct is not None:
            # V10: max(ATR-based, pct-based) distance
            atr_dist = combo_atr * atr_at_entry
            pct_dist = combo_pct * entry_price
            stop_price = entry_price - max(atr_dist, pct_dist)
        elif atr_mult is not None:
            stop_price = entry_price - atr_mult * atr_at_entry
        else:
            stop_price = entry_price * (1 + threshold_pct)

        if bar_close <= stop_price:
            return True, bar_num, bar_close

    return False, None, None


STOP_VARIANTS = [
    # (name, pct_threshold, atr_mult, delayed, combo_atr, combo_pct)
    ("V0",  None,   None, False, None, None),    # No stop (baseline)
    ("V1",  -0.03,  None, False, None, None),    # Immediate -3%
    ("V2",  -0.05,  None, False, None, None),    # Immediate -5%
    ("V3",  -0.07,  None, False, None, None),    # Immediate -7%
    ("V4",  -0.04,  None, True,  None, None),    # Delayed -4%
    ("V5",  -0.05,  None, True,  None, None),    # Delayed -5%
    ("V6",  -0.06,  None, True,  None, None),    # Delayed -6%
    ("V7",  None,   2.0,  True,  None, None),    # Delayed 2.0x ATR
    ("V8",  None,   2.5,  True,  None, None),    # Delayed 2.5x ATR
    ("V9",  None,   3.0,  True,  None, None),    # Delayed 3.0x ATR
    ("V10", None,   None, True,  2.5,  0.05),    # Delayed max(2.5xATR, 5%)
]


# ── Main ────────────────────────────────────────────────────────────────────

def run():
    print("=" * 70)
    print("MODULE 4 MAE/MFE + STOP VARIANT ANALYSIS")
    print("=" * 70)

    vix_daily = load_vix_daily()
    print(f"VIX: {len(vix_daily)} days loaded")

    # ── Collect all trades ──────────────────────────────────────────────────
    all_trades = []

    for ticker in TICKERS:
        print(f"  {ticker}...", end="", flush=True)
        bars = load_4h_bars(ticker)
        triggers = detect_triggers(bars, vix_daily)

        for idx in triggers:
            bar = bars.iloc[idx]
            entry_price = bar["close"]
            atr_at_entry = bar["atr_14"]
            rsi_at_entry = bar["rsi_14"]
            vix_at_entry = get_prior_vix(vix_daily, bar["date_str"])

            trade = execute_trade(bars, idx, entry_price)
            if trade is None:
                continue

            trade["ticker"] = ticker
            trade["entry_date"] = str(bar["timestamp"])
            trade["entry_price"] = entry_price
            trade["atr14_at_entry"] = atr_at_entry
            trade["rsi_at_entry"] = rsi_at_entry
            trade["vix_at_entry"] = vix_at_entry
            all_trades.append(trade)

        print(f" {len(triggers)} triggers")

    N = len(all_trades)
    print(f"\nTotal trades: {N}")
    winners = [t for t in all_trades if t["final_return"] > 0]
    losers = [t for t in all_trades if t["final_return"] <= 0]
    print(f"Winners: {len(winners)}, Losers: {len(losers)}")

    # ── Task 1: Per-Trade MAE/MFE CSV ───────────────────────────────────────
    print("\n--- Task 1: Per-Trade MAE/MFE ---")
    csv_path = RESULTS_DIR / "m4_mae_mfe_per_trade.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "ticker", "entry_date", "entry_price", "exit_price", "final_return",
            "MAE_close", "MAE_low", "MFE", "bars_to_MAE", "bars_to_MFE",
            "bars_held", "exit_reason", "atr14_at_entry", "rsi_at_entry", "vix_at_entry",
        ])
        for t in all_trades:
            writer.writerow([
                t["ticker"], t["entry_date"],
                f"{t['entry_price']:.4f}", f"{t['exit_price']:.4f}",
                f"{t['final_return']*100:.2f}",
                f"{t['mae_close']*100:.2f}", f"{t['mae_low']*100:.2f}",
                f"{t['mfe']*100:.2f}",
                t["bars_to_mae"], t["bars_to_mfe"],
                t["bars_held"], t["exit_reason"],
                f"{t['atr14_at_entry']:.4f}" if pd.notna(t["atr14_at_entry"]) else "",
                f"{t['rsi_at_entry']:.2f}" if pd.notna(t["rsi_at_entry"]) else "",
                f"{t['vix_at_entry']:.2f}" if t["vix_at_entry"] else "",
            ])
    print(f"  Saved: {csv_path}")

    # ── Task 1: Summary Statistics ──────────────────────────────────────────
    print("\n--- Task 1: MAE/MFE Summary ---")
    summary_lines = []
    p = summary_lines.append

    p("# Module 4 MAE/MFE Distribution + Stop Variant Analysis")
    p("")
    p(f"**Date:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    p(f"**Tickers:** {len(TICKERS)}")
    p(f"**Trigger:** 3 consecutive 4H down bars (close < open) + VIX >= {VIX_THRESHOLD} + RSI < {RSI_THRESHOLD}")
    p(f"**Entry:** 4H trigger bar close")
    p(f"**Exit:** first 4H close >= EMA21 (hard max {MAX_HOLD} bars)")
    p(f"**Total trades:** {N} (Winners: {len(winners)}, Losers: {len(losers)})")
    p("")
    p("---")
    p("")

    # Table 2: MAE/MFE Summary
    p("## Table 2: MAE/MFE Summary Statistics")
    p("")

    def pct_arr(trades, field):
        return np.array([t[field] * 100 for t in trades])

    def int_arr(trades, field):
        return np.array([t[field] for t in trades])

    groups = [("Winners", winners), ("Losers", losers), ("All", all_trades)]

    p("| Metric | " + " | ".join(g[0] + f" (N={len(g[1])})" for g in groups) + " |")
    p("|--------|" + "|".join("-------" for _ in groups) + "|")

    for label, field in [
        ("MAE_close p50", "mae_close"), ("MAE_close p75", "mae_close"),
        ("MAE_close p90", "mae_close"), ("MAE_close p95", "mae_close"),
        ("MAE_close worst", "mae_close"),
        ("MAE_low p50", "mae_low"), ("MAE_low p75", "mae_low"),
        ("MAE_low p90", "mae_low"), ("MAE_low worst", "mae_low"),
        ("MFE p50", "mfe"), ("MFE p75", "mfe"), ("MFE p90", "mfe"),
        ("bars_to_MAE avg", "bars_to_mae"), ("bars_to_MFE avg", "bars_to_mfe"),
        ("bars_held avg", "bars_held"),
    ]:
        row = f"| {label} |"
        for gname, gdata in groups:
            if not gdata:
                row += " — |"
                continue
            if "avg" in label:
                vals = int_arr(gdata, field)
                row += f" {np.mean(vals):.1f} |"
            elif "worst" in label:
                vals = pct_arr(gdata, field)
                row += f" {np.min(vals):.2f}% |"
            else:
                pctl = int(label.split("p")[1].split(" ")[0])
                vals = pct_arr(gdata, field)
                row += f" {np.percentile(vals, pctl):.2f}% |"
        p(row)
    p("")

    # Table 3: ATR Context
    p("## Table 3: ATR Context")
    p("")
    atr_vals = np.array([t["atr14_at_entry"] for t in all_trades if pd.notna(t["atr14_at_entry"])])
    mae_close_vals = np.array([abs(t["mae_close"]) * t["entry_price"] for t in all_trades if pd.notna(t["atr14_at_entry"])])
    atr_for_ratio = np.array([t["atr14_at_entry"] for t in all_trades if pd.notna(t["atr14_at_entry"])])
    mae_atr_ratio = mae_close_vals / atr_for_ratio

    p("| Metric | Value |")
    p("|--------|-------|")
    p(f"| ATR14 at entry mean | {np.mean(atr_vals):.4f} |")
    p(f"| ATR14 at entry p50 | {np.median(atr_vals):.4f} |")
    p(f"| MAE/ATR ratio p50 | {np.median(mae_atr_ratio):.2f} |")
    p(f"| MAE/ATR ratio p90 | {np.percentile(mae_atr_ratio, 90):.2f} |")
    p("")

    # ── Task 2: Stop Variants ───────────────────────────────────────────────
    print("\n--- Task 2: Stop Variants ---")
    p("---")
    p("")
    p("## Table 4: Stop Variant Comparison")
    p("")

    variant_results = {}

    for variant in STOP_VARIANTS:
        vname = variant[0]
        v_rets = []
        stopped_count = 0
        winners_stopped = 0
        losers_stopped = 0

        for t in all_trades:
            if vname == "V0":
                # Baseline — no stop
                v_rets.append(t["final_return"] * 100)
                continue

            atr = t["atr14_at_entry"] if pd.notna(t["atr14_at_entry"]) else 0
            stopped, stop_bar, stop_price = apply_stop(t, t["entry_price"], atr, variant)

            if stopped:
                stopped_count += 1
                stop_ret = (stop_price - t["entry_price"]) / t["entry_price"] * 100
                v_rets.append(stop_ret)
                # Was this trade a baseline winner or loser?
                if t["final_return"] > 0:
                    winners_stopped += 1
                else:
                    losers_stopped += 1
            else:
                v_rets.append(t["final_return"] * 100)

        rets_arr = np.array(v_rets)
        n = len(rets_arr)
        mean_r = np.mean(rets_arr)
        win_count = np.sum(rets_arr > 0)
        wr = win_count / n * 100 if n > 0 else 0
        wins_sum = np.sum(rets_arr[rets_arr > 0])
        loss_sum = abs(np.sum(rets_arr[rets_arr <= 0])) if np.any(rets_arr <= 0) else 0.001
        pf = wins_sum / loss_sum if loss_sum > 0 else 9999
        max_loss = np.min(rets_arr)
        std_r = np.std(rets_arr, ddof=1) if n > 1 else 1.0
        sharpe = mean_r / std_r * np.sqrt(n) if std_r > 0 else 0

        # Expected shortfall at 5% tail
        sorted_rets = np.sort(rets_arr)
        tail_n = max(1, int(np.ceil(n * 0.05)))
        es_5 = np.mean(sorted_rets[:tail_n])

        variant_results[vname] = {
            "N": n, "stopped": stopped_count,
            "winners_stopped": winners_stopped, "losers_stopped": losers_stopped,
            "mean": mean_r, "wr": wr, "pf": pf,
            "max_loss": max_loss, "es_5": es_5, "sharpe": sharpe,
        }

    # Format table
    p("| Variant | N | Stopped | Win_Stopped | Loss_Stopped | Mean% | WR% | PF | Max_Loss% | ES_5% | Sharpe |")
    p("|---------|---|---------|-------------|--------------|-------|-----|-----|-----------|-------|--------|")
    for variant in STOP_VARIANTS:
        vname = variant[0]
        r = variant_results[vname]
        p(f"| {vname} | {r['N']} | {r['stopped']} | {r['winners_stopped']} | "
          f"{r['losers_stopped']} | {r['mean']:+.2f} | {r['wr']:.0f} | "
          f"{r['pf']:.2f} | {r['max_loss']:.2f} | {r['es_5']:.2f} | {r['sharpe']:.2f} |")
    p("")

    # Acceptance criteria check
    p("## Acceptance Criteria")
    p("")
    baseline_wr = variant_results["V0"]["wr"]
    for variant in STOP_VARIANTS[1:]:
        vname = variant[0]
        r = variant_results[vname]
        false_stop_rate = r["winners_stopped"] / len(winners) * 100 if len(winners) > 0 else 0
        verdict = "PASS" if false_stop_rate < 10 else ("MARGINAL" if false_stop_rate < 15 else "REJECT")
        if false_stop_rate >= 15:
            verdict = "REJECT (>15% winner clipping)"
        p(f"- **{vname}**: False stop rate = {false_stop_rate:.1f}% → **{verdict}**")
    p("")

    # Save stop variants report
    stop_path = RESULTS_DIR / "m4_stop_variants.md"
    # Extract just Task 2 section for separate file
    task2_start = next(i for i, l in enumerate(summary_lines) if "Table 4" in l)
    stop_lines = summary_lines[:8] + [""] + summary_lines[task2_start:]
    stop_path.write_text("\n".join(stop_lines) + "\n")
    print(f"  Saved: {stop_path}")

    # ── Task 3: Regime Analysis ─────────────────────────────────────────────
    print("\n--- Task 3: Regime Analysis ---")
    p("---")
    p("")
    p("## Regime Analysis")
    p("")

    def regime_table(title, group_fn):
        p(f"### {title}")
        p("")
        p("| Group | N | MAE_close p50 | MAE_close p90 | Mean% | WR% |")
        p("|-------|---|---------------|---------------|-------|-----|")
        groups_dict = {}
        for t in all_trades:
            g = group_fn(t)
            if g not in groups_dict:
                groups_dict[g] = []
            groups_dict[g].append(t)
        for gname in sorted(groups_dict.keys()):
            gdata = groups_dict[gname]
            mae_vals = pct_arr(gdata, "mae_close")
            rets = np.array([t["final_return"] * 100 for t in gdata])
            wr = np.sum(rets > 0) / len(rets) * 100
            p(f"| {gname} | {len(gdata)} | {np.percentile(mae_vals, 50):.2f}% | "
              f"{np.percentile(mae_vals, 90):.2f}% | {np.mean(rets):+.2f} | {wr:.0f} |")
        p("")

    # VIX level
    def vix_group(t):
        v = t["vix_at_entry"]
        if v is None:
            return "Unknown"
        if v < 30:
            return "VIX 25-30"
        elif v < 40:
            return "VIX 30-40"
        else:
            return "VIX 40+"

    regime_table("MAE by VIX Level at Entry", vix_group)

    # RSI tier
    def rsi_group(t):
        r = t["rsi_at_entry"]
        if pd.isna(r):
            return "Unknown"
        if r < 25:
            return "RSI <25"
        elif r < 30:
            return "RSI 25-30"
        else:
            return "RSI 30-35"

    regime_table("MAE by RSI Tier at Entry", rsi_group)

    # Ticker class
    def ticker_class(t):
        tk = t["ticker"]
        if tk in MEGA_CAP_TECH:
            return "Mega-cap tech"
        elif tk in ADR_TICKERS:
            return "ADR"
        elif tk in CRYPTO_PROXY:
            return "Crypto-proxy"
        else:
            return "Other"

    regime_table("MAE by Ticker Class", ticker_class)

    # Override state (VIX-based proxy)
    def override_group(t):
        v = t["vix_at_entry"]
        if v is None:
            return "Unknown"
        return "HIGH_RISK" if v >= 35 else "ELEVATED"

    regime_table("MAE by Override State (VIX proxy)", override_group)

    # Save regime report
    regime_path = RESULTS_DIR / "m4_mae_by_regime.md"
    regime_start = next(i for i, l in enumerate(summary_lines) if "Regime Analysis" in l)
    regime_lines = summary_lines[:8] + [""] + summary_lines[regime_start:]
    regime_path.write_text("\n".join(regime_lines) + "\n")
    print(f"  Saved: {regime_path}")

    # Save full summary
    summary_path = RESULTS_DIR / "m4_mae_mfe_summary.md"
    summary_path.write_text("\n".join(summary_lines) + "\n")
    print(f"  Saved: {summary_path}")

    # Print full report
    print("\n" + "=" * 70)
    print("\n".join(summary_lines))

    return all_trades, variant_results


if __name__ == "__main__":
    run()
