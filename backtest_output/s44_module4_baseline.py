#!/usr/bin/env python3
"""
S44 Module 4 Baseline — 4H-Close vs M5 Entry Comparison.

Detects 3 consecutive 4H down bars with VIX >= 25, then compares:
  BASELINE: enter at 4H bar close
  M5-A: first M5 close > M5 EMA9 after trigger
  M5-B: first M5 higher-low + close > prior M5 swing high
  M5-C: first M5 RSI(14) crosses back above 30

Exit variants: E1 (+2 4H bars), E2 (4H EMA21 touch), E3 (not impl), E4 (+1 4H bar)

Output: results/S44_Module4_Baseline_Results.md
"""

import csv
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.data_loader import load_m5_regsess

# ── Config ────────────────────────────────────────────────────────────────────

TICKERS = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU", "C",
    "COIN", "COST", "GOOGL", "GS", "INTC", "JPM", "MARA", "META", "MSFT",
    "MSTR", "MU", "NVDA", "PLTR", "SMCI", "TSLA", "TSM", "V",
]

VIX_THRESHOLD = 25.0
STREAK_LEN = 3
M5_SEARCH_WINDOW = 2  # search within next 2 4H bars for M5 entry
EMA9_PERIOD = 9
RSI_PERIOD = 14

INDICATORS_4H_DIR = ROOT / "data" / "indicators_4h"
VIX_PATH = ROOT / "Fetched_Data" / "VIXCLS_FRED_real.csv"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)


# ── Helper functions ──────────────────────────────────────────────────────────

def load_vix_daily():
    """Load VIX daily close from FRED CSV. Returns {date_str: close}."""
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
    """Load 4H indicator bars for a ticker."""
    path = INDICATORS_4H_DIR / f"{ticker}_4h_indicators.csv"
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["date_str"] = df["timestamp"].dt.strftime("%Y-%m-%d")
    df["is_down"] = df["close"] < df["open"]
    return df


def get_prior_vix(vix_daily, date_str):
    """Get prior trading day's VIX close (no lookahead)."""
    dt = pd.Timestamp(date_str)
    # Go back up to 5 calendar days to find prior VIX
    for offset in range(1, 6):
        prior = (dt - timedelta(days=offset)).strftime("%Y-%m-%d")
        if prior in vix_daily:
            return vix_daily[prior]
    return None


def calc_ema_series(values, period):
    """Standard EMA on a pandas Series."""
    return values.ewm(span=period, adjust=False).mean()


def calc_rsi_series(close, period=14):
    """Wilder RSI on a pandas Series."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# ── Trigger detection ─────────────────────────────────────────────────────────

def detect_triggers(bars_4h, vix_daily):
    """Find 3 consecutive 4H down bars where prior-day VIX >= 25."""
    triggers = []
    for i in range(STREAK_LEN - 1, len(bars_4h)):
        # Check streak of down bars
        streak_ok = True
        for j in range(STREAK_LEN):
            if not bars_4h.iloc[i - j]["is_down"]:
                streak_ok = False
                break
        if not streak_ok:
            continue

        trigger_bar = bars_4h.iloc[i]
        vix_val = get_prior_vix(vix_daily, trigger_bar["date_str"])
        if vix_val is None or vix_val < VIX_THRESHOLD:
            continue

        triggers.append({
            "idx": i,
            "timestamp": trigger_bar["timestamp"],
            "date_str": trigger_bar["date_str"],
            "close": trigger_bar["close"],
            "vix": vix_val,
        })
    return triggers


# ── Exit logic ────────────────────────────────────────────────────────────────

def compute_exit_e1(bars_4h, entry_idx, entry_price):
    """E1: +2 4H bars after entry."""
    exit_idx = entry_idx + 2
    if exit_idx >= len(bars_4h):
        return None
    exit_price = bars_4h.iloc[exit_idx]["close"]
    return _trade_metrics(bars_4h, entry_idx, exit_idx, entry_price, exit_price)


def compute_exit_e2(bars_4h, entry_idx, entry_price):
    """E2: First touch of 4H EMA21 after entry."""
    for j in range(entry_idx + 1, min(entry_idx + 20, len(bars_4h))):
        bar = bars_4h.iloc[j]
        ema21 = bar.get("ema_21")
        if pd.notna(ema21) and bar["high"] >= ema21:
            exit_price = min(bar["high"], ema21)  # assume fill at EMA21
            return _trade_metrics(bars_4h, entry_idx, j, entry_price, exit_price)
    return None


def compute_exit_e4(bars_4h, entry_idx, entry_price):
    """E4: +1 4H bar after entry."""
    exit_idx = entry_idx + 1
    if exit_idx >= len(bars_4h):
        return None
    exit_price = bars_4h.iloc[exit_idx]["close"]
    return _trade_metrics(bars_4h, entry_idx, exit_idx, entry_price, exit_price)


def _trade_metrics(bars_4h, entry_idx, exit_idx, entry_price, exit_price):
    """Compute return, MAE, MFE for a long trade from entry_idx to exit_idx."""
    ret_pct = (exit_price - entry_price) / entry_price * 100

    # MAE/MFE during hold period (inclusive of entry bar's remaining action)
    hold_bars = bars_4h.iloc[entry_idx:exit_idx + 1]
    mae = (hold_bars["low"].min() - entry_price) / entry_price * 100
    mfe = (hold_bars["high"].max() - entry_price) / entry_price * 100

    return {
        "return_pct": ret_pct,
        "exit_price": exit_price,
        "mae": mae,
        "mfe": mfe,
        "hold_bars": exit_idx - entry_idx,
        "win": ret_pct > 0,
    }


# ── M5 entry variants ────────────────────────────────────────────────────────

def find_m5_window(m5_df, trigger_ts, bars_4h, trigger_4h_idx):
    """Get M5 bars in the next M5_SEARCH_WINDOW 4H bars after trigger."""
    # Window = from trigger bar close to end of +2 4H bars
    window_end_idx = trigger_4h_idx + M5_SEARCH_WINDOW
    if window_end_idx >= len(bars_4h):
        return pd.DataFrame()

    start_ts = trigger_ts
    end_ts = bars_4h.iloc[window_end_idx]["timestamp"] + timedelta(hours=4)

    mask = (m5_df["Datetime"] > start_ts) & (m5_df["Datetime"] <= end_ts)
    return m5_df[mask].copy()


def m5_entry_a(m5_window):
    """M5-A: First M5 close > M5 EMA9."""
    if m5_window.empty or len(m5_window) < EMA9_PERIOD:
        return None
    ema9 = calc_ema_series(m5_window["Close"], EMA9_PERIOD)
    for i in range(EMA9_PERIOD, len(m5_window)):
        if m5_window.iloc[i]["Close"] > ema9.iloc[i]:
            return {
                "entry_price": m5_window.iloc[i]["Close"],
                "entry_ts": m5_window.iloc[i]["Datetime"],
                "entry_m5_idx": m5_window.index[i],
            }
    return None


def m5_entry_b(m5_window):
    """M5-B: First M5 higher-low + close > prior swing high."""
    if m5_window.empty or len(m5_window) < 5:
        return None
    lows = m5_window["Low"].values
    highs = m5_window["High"].values
    closes = m5_window["Close"].values

    # Track swing high as rolling 5-bar high
    for i in range(5, len(m5_window)):
        prior_swing_high = highs[i - 5:i].max()
        higher_low = lows[i] > lows[i - 1]
        close_above_swing = closes[i] > prior_swing_high

        if higher_low and close_above_swing:
            return {
                "entry_price": closes[i],
                "entry_ts": m5_window.iloc[i]["Datetime"],
                "entry_m5_idx": m5_window.index[i],
            }
    return None


def m5_entry_c(m5_window):
    """M5-C: First M5 RSI(14) crosses back above 30."""
    if m5_window.empty or len(m5_window) < RSI_PERIOD + 2:
        return None
    rsi = calc_rsi_series(m5_window["Close"], RSI_PERIOD)
    rsi_vals = rsi.values

    for i in range(RSI_PERIOD + 1, len(m5_window)):
        if pd.isna(rsi_vals[i]) or pd.isna(rsi_vals[i - 1]):
            continue
        if rsi_vals[i - 1] < 30 and rsi_vals[i] >= 30:
            return {
                "entry_price": m5_window.iloc[i]["Close"],
                "entry_ts": m5_window.iloc[i]["Datetime"],
                "entry_m5_idx": m5_window.index[i],
            }
    return None


# ── Map M5 entry time back to 4H bar index ────────────────────────────────────

def m5_ts_to_4h_idx(bars_4h, entry_ts):
    """Find the 4H bar index that contains the given M5 timestamp."""
    entry_ts = pd.Timestamp(entry_ts)
    for i in range(len(bars_4h)):
        bar_ts = bars_4h.iloc[i]["timestamp"]
        # Each 4H bar starts at bar_ts. Next bar starts at bars_4h[i+1].timestamp
        if i + 1 < len(bars_4h):
            next_ts = bars_4h.iloc[i + 1]["timestamp"]
            if bar_ts <= entry_ts < next_ts:
                return i
        else:
            if bar_ts <= entry_ts:
                return i
    return None


# ── Main backtest ─────────────────────────────────────────────────────────────

def run_backtest():
    print("Loading VIX data...")
    vix_daily = load_vix_daily()
    print(f"  VIX: {len(vix_daily)} trading days")

    # Results accumulators
    results = {
        "BASELINE": {"E1": [], "E2": [], "E4": []},
        "M5-A": {"E1": [], "E2": [], "E4": []},
        "M5-B": {"E1": [], "E2": [], "E4": []},
        "M5-C": {"E1": [], "E2": [], "E4": []},
    }
    trigger_counts = defaultdict(int)
    missed = {"M5-A": 0, "M5-B": 0, "M5-C": 0}
    m5_entry_counts = {"M5-A": 0, "M5-B": 0, "M5-C": 0}

    for ticker in TICKERS:
        print(f"Processing {ticker}...")

        # Load 4H bars
        bars_4h = load_4h_bars(ticker)

        # Load M5 bars
        try:
            m5_df = load_m5_regsess(ticker)
        except (FileNotFoundError, ValueError) as e:
            print(f"  SKIP {ticker}: {e}")
            continue

        # Detect triggers
        triggers = detect_triggers(bars_4h, vix_daily)
        trigger_counts[ticker] = len(triggers)

        if not triggers:
            continue

        for trig in triggers:
            idx = trig["idx"]
            entry_price = trig["close"]

            # BASELINE exits
            for exit_name, exit_fn in [("E1", compute_exit_e1), ("E2", compute_exit_e2), ("E4", compute_exit_e4)]:
                trade = exit_fn(bars_4h, idx, entry_price)
                if trade:
                    trade["ticker"] = ticker
                    trade["trigger_ts"] = trig["timestamp"]
                    trade["vix"] = trig["vix"]
                    trade["entry_price"] = entry_price
                    results["BASELINE"][exit_name].append(trade)

            # M5 window for variant entries
            m5_window = find_m5_window(m5_df, trig["timestamp"], bars_4h, idx)

            for variant_name, entry_fn in [("M5-A", m5_entry_a), ("M5-B", m5_entry_b), ("M5-C", m5_entry_c)]:
                m5_entry = entry_fn(m5_window)
                if m5_entry is None:
                    missed[variant_name] += 1
                    continue

                m5_entry_counts[variant_name] += 1
                m5_price = m5_entry["entry_price"]
                m5_4h_idx = m5_ts_to_4h_idx(bars_4h, m5_entry["entry_ts"])
                if m5_4h_idx is None:
                    missed[variant_name] += 1
                    continue

                for exit_name, exit_fn in [("E1", compute_exit_e1), ("E2", compute_exit_e2), ("E4", compute_exit_e4)]:
                    trade = exit_fn(bars_4h, m5_4h_idx, m5_price)
                    if trade:
                        trade["ticker"] = ticker
                        trade["trigger_ts"] = trig["timestamp"]
                        trade["vix"] = trig["vix"]
                        trade["entry_price"] = m5_price
                        results[variant_name][exit_name].append(trade)

    total_triggers = sum(trigger_counts.values())
    print(f"\nTotal triggers: {total_triggers} across {sum(1 for v in trigger_counts.values() if v > 0)} tickers")

    return results, total_triggers, trigger_counts, missed, m5_entry_counts


# ── Metrics computation ───────────────────────────────────────────────────────

def compute_metrics(trades, total_triggers):
    """Compute summary metrics for a list of trades."""
    if not trades:
        return {
            "N": 0, "fill_rate": 0, "mean_ret": 0, "win_rate": 0,
            "profit_factor": 0, "mae": 0, "mfe": 0, "net_expectancy": 0,
            "p_value": 1.0, "median_ret": 0,
        }

    rets = [t["return_pct"] for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    n = len(trades)
    fill_rate = n / total_triggers if total_triggers > 0 else 0
    mean_ret = np.mean(rets)
    median_ret = np.median(rets)
    win_rate = len(wins) / n * 100 if n > 0 else 0
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0.001
    profit_factor = gross_profit / gross_loss
    mae = np.mean([t["mae"] for t in trades])
    mfe = np.mean([t["mfe"] for t in trades])
    net_expectancy = mean_ret * fill_rate

    # p-value: one-sample t-test vs 0
    if n >= 2:
        t_stat, p_val = stats.ttest_1samp(rets, 0)
        p_val = p_val / 2 if t_stat > 0 else 1 - p_val / 2  # one-tailed
    else:
        p_val = 1.0

    return {
        "N": n,
        "fill_rate": fill_rate * 100,
        "mean_ret": mean_ret,
        "median_ret": median_ret,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "mae": mae,
        "mfe": mfe,
        "net_expectancy": net_expectancy,
        "p_value": p_val,
    }


# ── Output ────────────────────────────────────────────────────────────────────

def format_results(results, total_triggers, trigger_counts, missed, m5_entry_counts):
    lines = []
    lines.append("# S44 Module 4 Baseline Results — 4H-Close vs M5 Entry")
    lines.append("")
    lines.append(f"**Date:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Total 4H triggers (3 down + VIX>=25):** {total_triggers}")
    lines.append(f"**Tickers with triggers:** {sum(1 for v in trigger_counts.values() if v > 0)}/{len(TICKERS)}")
    lines.append(f"**VIX threshold:** {VIX_THRESHOLD}")
    lines.append(f"**Streak length:** {STREAK_LEN} consecutive 4H down bars")
    lines.append("")

    # Per-ticker trigger counts
    lines.append("## Trigger Distribution")
    lines.append("")
    lines.append("| Ticker | Triggers |")
    lines.append("|--------|----------|")
    for t in sorted(trigger_counts.keys()):
        if trigger_counts[t] > 0:
            lines.append(f"| {t} | {trigger_counts[t]} |")
    lines.append("")

    # Main comparison table (E1 exit)
    lines.append("## Entry Comparison (E1: +2 4H bars exit)")
    lines.append("")
    lines.append("| Entry | N | Fill% | Mean% | Med% | WR% | PF | MAE% | MFE% | NetExp | p-val |")
    lines.append("|-------|---|-------|-------|------|-----|-----|------|------|--------|-------|")

    e1_metrics = {}
    for variant in ["BASELINE", "M5-A", "M5-B", "M5-C"]:
        m = compute_metrics(results[variant]["E1"], total_triggers)
        e1_metrics[variant] = m
        sig = "***" if m["p_value"] < 0.001 else ("**" if m["p_value"] < 0.01 else ("*" if m["p_value"] < 0.05 else ""))
        lines.append(
            f"| {variant} | {m['N']} | {m['fill_rate']:.0f} | "
            f"{m['mean_ret']:+.2f} | {m['median_ret']:+.2f} | "
            f"{m['win_rate']:.0f} | {m['profit_factor']:.2f} | "
            f"{m['mae']:.2f} | {m['mfe']:.2f} | "
            f"{m['net_expectancy']:+.3f} | {m['p_value']:.4f}{sig} |"
        )
    lines.append("")

    # Missed trade rates
    lines.append("## M5 Filter Miss Rates")
    lines.append("")
    lines.append("| Variant | Triggers | Entries | Missed | Miss% |")
    lines.append("|---------|----------|---------|--------|-------|")
    for v in ["M5-A", "M5-B", "M5-C"]:
        entries = m5_entry_counts[v]
        miss = missed[v]
        total = entries + miss
        miss_pct = miss / total * 100 if total > 0 else 0
        lines.append(f"| {v} | {total} | {entries} | {miss} | {miss_pct:.0f}% |")
    lines.append("")

    # Exit comparison for best entry
    best_variant = max(e1_metrics, key=lambda k: e1_metrics[k]["net_expectancy"])
    lines.append(f"## Exit Comparison for Winner: {best_variant}")
    lines.append("")
    lines.append("| Exit | N | Mean% | Med% | WR% | PF | MAE% | MFE% | p-val |")
    lines.append("|------|---|-------|------|-----|-----|------|------|-------|")
    for exit_name in ["E1", "E2", "E4"]:
        m = compute_metrics(results[best_variant][exit_name], total_triggers)
        sig = "***" if m["p_value"] < 0.001 else ("**" if m["p_value"] < 0.01 else ("*" if m["p_value"] < 0.05 else ""))
        lines.append(
            f"| {exit_name} | {m['N']} | {m['mean_ret']:+.2f} | "
            f"{m['median_ret']:+.2f} | {m['win_rate']:.0f} | "
            f"{m['profit_factor']:.2f} | {m['mae']:.2f} | {m['mfe']:.2f} | "
            f"{m['p_value']:.4f}{sig} |"
        )
    lines.append("")

    # Verdict
    lines.append("## Verdict")
    lines.append("")
    baseline_ne = e1_metrics["BASELINE"]["net_expectancy"]
    best_ne = e1_metrics[best_variant]["net_expectancy"]
    if best_variant == "BASELINE":
        lines.append(f"**BASELINE wins** with net expectancy {baseline_ne:+.3f}%.")
        lines.append("No M5 filter improves on plain 4H-close entry.")
    else:
        delta = best_ne - baseline_ne
        lines.append(f"**{best_variant} wins** with net expectancy {best_ne:+.3f}% "
                     f"(+{delta:.3f}% vs BASELINE {baseline_ne:+.3f}%).")
    lines.append("")

    # Statistical significance note
    baseline_p = e1_metrics["BASELINE"]["p_value"]
    best_p = e1_metrics[best_variant]["p_value"]
    if baseline_p < 0.05:
        lines.append(f"BASELINE is statistically significant (p={baseline_p:.4f}).")
    else:
        lines.append(f"BASELINE is NOT statistically significant (p={baseline_p:.4f}).")
    if best_variant != "BASELINE" and best_p < 0.05:
        lines.append(f"{best_variant} is statistically significant (p={best_p:.4f}).")
    lines.append("")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    results, total_triggers, trigger_counts, missed, m5_entry_counts = run_backtest()
    report = format_results(results, total_triggers, trigger_counts, missed, m5_entry_counts)

    output_path = RESULTS_DIR / "S44_Module4_Baseline_Results.md"
    output_path.write_text(report)
    print(f"\nResults saved to {output_path}")
    print("\n" + report)
