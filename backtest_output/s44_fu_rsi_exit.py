#!/usr/bin/env python3
"""
S44-FU Priority #1+#2: RSI<35 Horse Race + Exit Topology.

Reuses the 159-trigger Module 4 sample (3 consecutive 4H down + VIX>=25).
Tests RSI filter variants and exit topology to finalize Module 4 spec.

Task A: RSI<35 as hard gate vs sizing modifier vs no filter
Task B: Exit topology — E1/E2-pure/E2-backstop-2/E2-backstop-3
Task C: Combined best spec

Output: results/S44_FU_RSI_HorseRace_Results.md
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

from utils.data_loader import load_m5_regsess

# ── Config ────────────────────────────────────────────────────────────────────

TICKERS = [
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN",
    "COST", "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU",
    "NVDA", "PLTR", "SNOW", "TSLA", "TSM", "TXN", "V",
]

VIX_THRESHOLD = 25.0
STREAK_LEN = 3
RSI_GATE_THRESHOLD = 35.0
RSI_BOOST_MULT = 1.5
RSI_NORMAL_MULT = 0.75

INDICATORS_4H_DIR = ROOT / "data" / "indicators_4h"
VIX_PATH = ROOT / "Fetched_Data" / "VIXCLS_FRED_real.csv"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)


# ── Data loading (from Prompt 2) ──────────────────────────────────────────────

def load_vix_daily():
    df = pd.read_csv(VIX_PATH)
    vix = {}
    for _, row in df.iterrows():
        try:
            vix[str(row["observation_date"])] = float(row["VIXCLS"])
        except (ValueError, TypeError):
            continue
    return vix


def load_4h_bars(ticker):
    path = INDICATORS_4H_DIR / f"{ticker}_4h_indicators.csv"
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["date_str"] = df["timestamp"].dt.strftime("%Y-%m-%d")
    df["is_down"] = df["close"] < df["open"]
    return df


def get_prior_vix(vix_daily, date_str):
    dt = pd.Timestamp(date_str)
    for offset in range(1, 6):
        prior = (dt - timedelta(days=offset)).strftime("%Y-%m-%d")
        if prior in vix_daily:
            return vix_daily[prior]
    return None


# ── Trigger detection (same as Prompt 2, but also captures RSI) ───────────────

def detect_triggers(bars_4h, vix_daily):
    """Find 3 consecutive 4H down bars with VIX>=25. Tag with 4H RSI at trigger."""
    triggers = []
    for i in range(STREAK_LEN - 1, len(bars_4h)):
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

        rsi_val = trigger_bar.get("rsi_14")
        rsi_val = float(rsi_val) if pd.notna(rsi_val) else None

        triggers.append({
            "idx": i,
            "timestamp": trigger_bar["timestamp"],
            "date_str": trigger_bar["date_str"],
            "close": trigger_bar["close"],
            "vix": vix_val,
            "rsi": rsi_val,
            "ticker": None,  # filled by caller
        })
    return triggers


# ── Exit functions ────────────────────────────────────────────────────────────

def _trade_metrics(bars_4h, entry_idx, exit_idx, entry_price, exit_price):
    ret_pct = (exit_price - entry_price) / entry_price * 100
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


def exit_e1(bars_4h, entry_idx, entry_price):
    """E1: Fixed +2 4H bars."""
    exit_idx = entry_idx + 2
    if exit_idx >= len(bars_4h):
        return None
    return _trade_metrics(bars_4h, entry_idx, exit_idx, entry_price,
                          bars_4h.iloc[exit_idx]["close"])


def exit_e2_pure(bars_4h, entry_idx, entry_price, max_hold=10):
    """E2-pure: EMA21 touch only, hard max of 5 4H bars (configurable)."""
    for j in range(entry_idx + 1, min(entry_idx + max_hold + 1, len(bars_4h))):
        bar = bars_4h.iloc[j]
        ema21 = bar.get("ema_21")
        if pd.notna(ema21) and bar["high"] >= ema21:
            exit_price = min(bar["high"], ema21)
            result = _trade_metrics(bars_4h, entry_idx, j, entry_price, exit_price)
            result["exit_type"] = "ema21_touch"
            return result
    # Hard max exit
    exit_idx = min(entry_idx + max_hold, len(bars_4h) - 1)
    if exit_idx <= entry_idx:
        return None
    result = _trade_metrics(bars_4h, entry_idx, exit_idx, entry_price,
                            bars_4h.iloc[exit_idx]["close"])
    result["exit_type"] = "hard_max"
    return result


def exit_e2_backstop(bars_4h, entry_idx, entry_price, backstop_bars=2):
    """E2-backstop: EMA21 touch OR +N bars, whichever first."""
    for j in range(entry_idx + 1, min(entry_idx + backstop_bars + 1, len(bars_4h))):
        bar = bars_4h.iloc[j]
        ema21 = bar.get("ema_21")
        if pd.notna(ema21) and bar["high"] >= ema21:
            exit_price = min(bar["high"], ema21)
            result = _trade_metrics(bars_4h, entry_idx, j, entry_price, exit_price)
            result["exit_type"] = "ema21_touch"
            return result
    # Backstop exit
    exit_idx = entry_idx + backstop_bars
    if exit_idx >= len(bars_4h):
        return None
    result = _trade_metrics(bars_4h, entry_idx, exit_idx, entry_price,
                            bars_4h.iloc[exit_idx]["close"])
    result["exit_type"] = "backstop"
    return result


# ── Main analysis ─────────────────────────────────────────────────────────────

def run_analysis():
    print("Loading VIX data...")
    vix_daily = load_vix_daily()

    all_triggers = []

    for ticker in TICKERS:
        print(f"Processing {ticker}...")
        bars_4h = load_4h_bars(ticker)
        triggers = detect_triggers(bars_4h, vix_daily)

        for trig in triggers:
            trig["ticker"] = ticker

            idx = trig["idx"]
            entry_price = trig["close"]

            # Compute all exit variants
            trig["e1"] = exit_e1(bars_4h, idx, entry_price)
            trig["e2_pure"] = exit_e2_pure(bars_4h, idx, entry_price, max_hold=10)
            trig["e2_bs2"] = exit_e2_backstop(bars_4h, idx, entry_price, backstop_bars=2)
            trig["e2_bs3"] = exit_e2_backstop(bars_4h, idx, entry_price, backstop_bars=3)

        all_triggers.extend(triggers)

    print(f"\nTotal triggers: {len(all_triggers)}")
    return all_triggers


# ── Metrics ───────────────────────────────────────────────────────────────────

def compute_metrics(trades):
    """Compute summary metrics from a list of trade dicts."""
    if not trades:
        return {
            "N": 0, "mean_ret": 0, "median_ret": 0, "win_rate": 0,
            "profit_factor": 0, "mae": 0, "mfe": 0, "sharpe": 0,
            "total_pnl": 0, "avg_hold": 0, "p_value": 1.0,
        }

    rets = [t["return_pct"] for t in trades]
    n = len(trades)
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    mean_ret = np.mean(rets)
    median_ret = np.median(rets)
    std_ret = np.std(rets, ddof=1) if n > 1 else 1.0
    win_rate = len(wins) / n * 100
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0.001
    profit_factor = gross_profit / gross_loss
    mae = np.mean([t["mae"] for t in trades])
    mfe = np.mean([t["mfe"] for t in trades])
    sharpe = mean_ret / std_ret if std_ret > 0 else 0
    total_pnl = sum(rets)
    avg_hold = np.mean([t["hold_bars"] for t in trades])

    if n >= 2:
        t_stat, p_val = stats.ttest_1samp(rets, 0)
        p_val = p_val / 2 if t_stat > 0 else 1 - p_val / 2
    else:
        p_val = 1.0

    return {
        "N": n, "mean_ret": mean_ret, "median_ret": median_ret,
        "win_rate": win_rate, "profit_factor": profit_factor,
        "mae": mae, "mfe": mfe, "sharpe": sharpe,
        "total_pnl": total_pnl, "avg_hold": avg_hold, "p_value": p_val,
    }


def compute_sized_metrics(trades, sizes):
    """Compute metrics with position sizing applied to returns."""
    if not trades:
        return compute_metrics([])
    sized_trades = []
    for t, s in zip(trades, sizes):
        st = dict(t)
        st["return_pct"] = t["return_pct"] * s
        st["mae"] = t["mae"] * s
        st["mfe"] = t["mfe"] * s
        sized_trades.append(st)
    return compute_metrics(sized_trades)


def sig_star(p):
    if p < 0.001: return "***"
    if p < 0.01: return "**"
    if p < 0.05: return "*"
    return ""


# ── Report ────────────────────────────────────────────────────────────────────

def generate_report(all_triggers):
    lines = []
    lines.append("# S44-FU: RSI<35 Horse Race + Exit Topology")
    lines.append("")
    lines.append(f"**Date:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Total triggers (3 down + VIX>=25):** {len(all_triggers)}")
    lines.append(f"**Tickers with triggers:** {len(set(t['ticker'] for t in all_triggers))}/25")
    lines.append("")

    # ══════════════════════════════════════════════════════════════════════
    # TASK A: RSI<35 HORSE RACE
    # ══════════════════════════════════════════════════════════════════════

    lines.append("---")
    lines.append("## Task A: RSI<35 Horse Race")
    lines.append("")

    # RSI distribution
    rsi_vals = [t["rsi"] for t in all_triggers if t["rsi"] is not None]
    rsi_bins = {
        "RSI < 25": len([r for r in rsi_vals if r < 25]),
        "RSI 25-30": len([r for r in rsi_vals if 25 <= r < 30]),
        "RSI 30-35": len([r for r in rsi_vals if 30 <= r < 35]),
        "RSI 35-40": len([r for r in rsi_vals if 35 <= r < 40]),
        "RSI 40-50": len([r for r in rsi_vals if 40 <= r < 50]),
        "RSI >= 50": len([r for r in rsi_vals if r >= 50]),
    }
    no_rsi = len([t for t in all_triggers if t["rsi"] is None])

    lines.append("### RSI Distribution at Trigger")
    lines.append("")
    lines.append("| RSI Range | N | % |")
    lines.append("|-----------|---|---|")
    total_rsi = len(rsi_vals)
    for label, count in rsi_bins.items():
        pct = count / total_rsi * 100 if total_rsi > 0 else 0
        lines.append(f"| {label} | {count} | {pct:.1f}% |")
    if no_rsi:
        lines.append(f"| No RSI data | {no_rsi} | — |")
    lines.append(f"| **Total** | **{len(all_triggers)}** | |")
    lines.append("")

    if rsi_vals:
        lines.append(f"Mean RSI: {np.mean(rsi_vals):.1f} | Median: {np.median(rsi_vals):.1f} | "
                     f"Min: {min(rsi_vals):.1f} | Max: {max(rsi_vals):.1f}")
        lines.append("")

    # Use E2-backstop-2 as the primary exit for Task A (matches Prompt 2's E2 behavior)
    # The exit key for Task A comparison
    exit_key = "e2_bs2"

    # V1: No RSI filter (all triggers)
    v1_trades = [t[exit_key] for t in all_triggers if t[exit_key] is not None]
    v1_m = compute_metrics(v1_trades)

    # V2: RSI < 35 hard gate
    v2_passing = [t for t in all_triggers if t["rsi"] is not None and t["rsi"] < RSI_GATE_THRESHOLD]
    v2_skipped = [t for t in all_triggers if t["rsi"] is None or t["rsi"] >= RSI_GATE_THRESHOLD]
    v2_trades = [t[exit_key] for t in v2_passing if t[exit_key] is not None]
    v2_m = compute_metrics(v2_trades)

    # Skipped trade analysis
    v2_skipped_trades = [t[exit_key] for t in v2_skipped if t[exit_key] is not None]
    v2_skipped_m = compute_metrics(v2_skipped_trades)

    # V3: RSI<35 sizing boost
    v3_trades = []
    v3_sizes = []
    for t in all_triggers:
        trade = t[exit_key]
        if trade is None:
            continue
        v3_trades.append(trade)
        if t["rsi"] is not None and t["rsi"] < RSI_GATE_THRESHOLD:
            v3_sizes.append(RSI_BOOST_MULT)
        else:
            v3_sizes.append(RSI_NORMAL_MULT)
    v3_m = compute_sized_metrics(v3_trades, v3_sizes)

    lines.append("### RSI Variant Comparison (Exit: EMA21 touch + 2-bar backstop)")
    lines.append("")
    lines.append("| Variant | N | Mean% | Med% | WR% | PF | MAE% | Sharpe | TotalP&L% | p-val |")
    lines.append("|---------|---|-------|------|-----|-----|------|--------|-----------|-------|")

    for label, m in [("V1: No filter", v1_m), ("V2: RSI<35 gate", v2_m), ("V3: RSI sizing", v3_m)]:
        lines.append(
            f"| {label} | {m['N']} | {m['mean_ret']:+.2f} | {m['median_ret']:+.2f} | "
            f"{m['win_rate']:.0f} | {m['profit_factor']:.2f} | {m['mae']:.2f} | "
            f"{m['sharpe']:.3f} | {m['total_pnl']:+.1f} | {m['p_value']:.4f}{sig_star(m['p_value'])} |"
        )
    lines.append("")

    # Missed trade analysis
    lines.append("### V2 Missed Trade Analysis")
    lines.append("")
    lines.append(f"V2 hard gate passes: {len(v2_passing)} | skips: {len(v2_skipped)}")
    lines.append("")
    if v2_skipped_trades:
        lines.append(f"**Skipped trades (RSI >= 35):** N={v2_skipped_m['N']}, "
                     f"Mean={v2_skipped_m['mean_ret']:+.2f}%, WR={v2_skipped_m['win_rate']:.0f}%, "
                     f"PF={v2_skipped_m['profit_factor']:.2f}")
        if v2_skipped_m["mean_ret"] > 0 and v2_skipped_m["p_value"] < 0.05:
            lines.append("-> **Skipped trades were profitable and significant.** Hard gate DESTROYS value.")
        elif v2_skipped_m["mean_ret"] > 0:
            lines.append("-> Skipped trades were positive but not significant. Hard gate may destroy value.")
        else:
            lines.append("-> Skipped trades were flat/negative. Hard gate ADDS value.")
    lines.append("")

    # RSI-binned return analysis
    lines.append("### Return by RSI Bin (EMA21 touch + 2-bar backstop)")
    lines.append("")
    lines.append("| RSI Range | N | Mean% | WR% | PF | p-val |")
    lines.append("|-----------|---|-------|-----|-----|-------|")
    rsi_ranges = [(0, 25), (25, 30), (30, 35), (35, 40), (40, 50), (50, 100)]
    rsi_labels = ["< 25", "25-30", "30-35", "35-40", "40-50", ">= 50"]
    for (lo, hi), label in zip(rsi_ranges, rsi_labels):
        bin_trades = [t[exit_key] for t in all_triggers
                      if t["rsi"] is not None and lo <= t["rsi"] < hi and t[exit_key] is not None]
        m = compute_metrics(bin_trades)
        if m["N"] > 0:
            lines.append(
                f"| {label} | {m['N']} | {m['mean_ret']:+.2f} | {m['win_rate']:.0f} | "
                f"{m['profit_factor']:.2f} | {m['p_value']:.4f}{sig_star(m['p_value'])} |"
            )
        else:
            lines.append(f"| {label} | 0 | — | — | — | — |")
    lines.append("")

    # ══════════════════════════════════════════════════════════════════════
    # TASK B: EXIT TOPOLOGY
    # ══════════════════════════════════════════════════════════════════════

    lines.append("---")
    lines.append("## Task B: Exit Topology")
    lines.append("")

    exit_configs = [
        ("E1: Fixed +2 bars", "e1"),
        ("E2-pure: EMA21 only (max 10)", "e2_pure"),
        ("E2-backstop-2: EMA21 OR +2 bars", "e2_bs2"),
        ("E2-backstop-3: EMA21 OR +3 bars", "e2_bs3"),
    ]

    lines.append("### Exit Comparison (BASELINE entry, all triggers)")
    lines.append("")
    lines.append("| Exit | N | Mean% | Med% | WR% | PF | MAE% | Sharpe | AvgHold | p-val |")
    lines.append("|------|---|-------|------|-----|-----|------|--------|---------|-------|")

    exit_metrics = {}
    for label, key in exit_configs:
        trades = [t[key] for t in all_triggers if t[key] is not None]
        m = compute_metrics(trades)
        exit_metrics[key] = m
        lines.append(
            f"| {label} | {m['N']} | {m['mean_ret']:+.2f} | {m['median_ret']:+.2f} | "
            f"{m['win_rate']:.0f} | {m['profit_factor']:.2f} | {m['mae']:.2f} | "
            f"{m['sharpe']:.3f} | {m['avg_hold']:.1f} | {m['p_value']:.4f}{sig_star(m['p_value'])} |"
        )
    lines.append("")

    # EMA21 touch rate analysis
    lines.append("### EMA21 Touch Rate")
    lines.append("")
    for label, key in exit_configs[1:]:  # skip E1
        trades = [t[key] for t in all_triggers if t[key] is not None]
        ema_touches = sum(1 for t in trades if t.get("exit_type") == "ema21_touch")
        backstops = sum(1 for t in trades if t.get("exit_type") in ("backstop", "hard_max"))
        total = len(trades)
        touch_rate = ema_touches / total * 100 if total > 0 else 0
        lines.append(f"**{label}:** {ema_touches}/{total} EMA21 touches ({touch_rate:.0f}%), "
                     f"{backstops} backstop/max exits")
    lines.append("")

    # E2-pure non-completion analysis
    e2_pure_trades = [t["e2_pure"] for t in all_triggers if t["e2_pure"] is not None]
    hard_max_trades = [t for t in e2_pure_trades if t.get("exit_type") == "hard_max"]
    if hard_max_trades:
        hm_m = compute_metrics(hard_max_trades)
        lines.append(f"### E2-pure Non-Completion (hard max at +10 bars)")
        lines.append("")
        lines.append(f"Trades needing hard max exit: {len(hard_max_trades)}/{len(e2_pure_trades)}")
        lines.append(f"Their mean return: {hm_m['mean_ret']:+.2f}%, WR: {hm_m['win_rate']:.0f}%")
        lines.append("")

    # Backstop impact: compare EMA21-touch trades vs backstop-forced trades within E2-bs2
    e2_bs2_trades = [t["e2_bs2"] for t in all_triggers if t["e2_bs2"] is not None]
    ema_touch_trades = [t for t in e2_bs2_trades if t.get("exit_type") == "ema21_touch"]
    backstop_trades = [t for t in e2_bs2_trades if t.get("exit_type") == "backstop"]

    if ema_touch_trades and backstop_trades:
        lines.append("### E2-backstop-2: Touch vs Backstop Split")
        lines.append("")
        et_m = compute_metrics(ema_touch_trades)
        bs_m = compute_metrics(backstop_trades)
        lines.append(f"| Exit Type | N | Mean% | WR% | PF | AvgHold |")
        lines.append(f"|-----------|---|-------|-----|-----|---------|")
        lines.append(f"| EMA21 touch | {et_m['N']} | {et_m['mean_ret']:+.2f} | "
                     f"{et_m['win_rate']:.0f} | {et_m['profit_factor']:.2f} | {et_m['avg_hold']:.1f} |")
        lines.append(f"| Backstop (+2) | {bs_m['N']} | {bs_m['mean_ret']:+.2f} | "
                     f"{bs_m['win_rate']:.0f} | {bs_m['profit_factor']:.2f} | {bs_m['avg_hold']:.1f} |")
        lines.append("")

    # ══════════════════════════════════════════════════════════════════════
    # TASK C: COMBINED BEST SPEC
    # ══════════════════════════════════════════════════════════════════════

    lines.append("---")
    lines.append("## Task C: Combined Best Spec")
    lines.append("")

    # Determine winners
    # Task A winner: compare sharpe of V1, V2, V3
    rsi_candidates = {"V1": v1_m, "V2": v2_m, "V3": v3_m}
    rsi_winner = max(rsi_candidates, key=lambda k: rsi_candidates[k]["sharpe"])
    rsi_winner_m = rsi_candidates[rsi_winner]

    # Task B winner: compare sharpe across exits
    exit_winner_key = max(exit_metrics, key=lambda k: exit_metrics[k]["sharpe"])
    exit_winner_label = {k: l for l, k in exit_configs}[exit_winner_key]

    # Now compute the combined spec
    # Apply RSI winner filter + exit winner
    if rsi_winner == "V1":
        combined_triggers = all_triggers
        rsi_rule = "No RSI filter (all triggers enter)"
    elif rsi_winner == "V2":
        combined_triggers = [t for t in all_triggers if t["rsi"] is not None and t["rsi"] < RSI_GATE_THRESHOLD]
        rsi_rule = f"RSI < {RSI_GATE_THRESHOLD} hard gate"
    else:
        combined_triggers = all_triggers  # V3 uses all triggers with sizing
        rsi_rule = f"RSI < {RSI_GATE_THRESHOLD}: {RSI_BOOST_MULT}x size; RSI >= {RSI_GATE_THRESHOLD}: {RSI_NORMAL_MULT}x size"

    combined_trades = [t[exit_winner_key] for t in combined_triggers if t[exit_winner_key] is not None]

    if rsi_winner == "V3":
        sizes = []
        for t in combined_triggers:
            if t[exit_winner_key] is None:
                continue
            if t["rsi"] is not None and t["rsi"] < RSI_GATE_THRESHOLD:
                sizes.append(RSI_BOOST_MULT)
            else:
                sizes.append(RSI_NORMAL_MULT)
        combined_m = compute_sized_metrics(combined_trades, sizes)
    else:
        combined_m = compute_metrics(combined_trades)

    lines.append("```")
    lines.append(f"TRIGGER:    3 consecutive 4H down bars + VIX >= {VIX_THRESHOLD}")
    lines.append(f"RSI RULE:   {rsi_rule} (winner: {rsi_winner})")
    lines.append(f"ENTRY:      4H trigger bar close")
    lines.append(f"EXIT:       {exit_winner_label} (winner)")
    lines.append(f"")
    lines.append(f"Final N:    {combined_m['N']}")
    lines.append(f"Mean %:     {combined_m['mean_ret']:+.2f}")
    lines.append(f"Median %:   {combined_m['median_ret']:+.2f}")
    lines.append(f"WR %:       {combined_m['win_rate']:.0f}")
    lines.append(f"PF:         {combined_m['profit_factor']:.2f}")
    lines.append(f"MAE:        {combined_m['mae']:.2f}%")
    lines.append(f"Sharpe:     {combined_m['sharpe']:.3f}")
    lines.append(f"Total P&L:  {combined_m['total_pnl']:+.1f}%")
    lines.append(f"Avg Hold:   {combined_m['avg_hold']:.1f} 4H bars")
    lines.append(f"p-val:      {combined_m['p_value']:.6f}")
    lines.append("```")
    lines.append("")

    # ── Production spec ──
    lines.append("### Production Implementation Rule")
    lines.append("")
    lines.append("```python")
    lines.append("# Module 4 — Final Research Spec")
    lines.append("def module4_trigger(bars_4h, vix_prior_close):")
    lines.append("    \"\"\"")
    lines.append("    Trigger: 3 consecutive 4H down bars + VIX >= 25")
    lines.append("    Entry:   4H trigger bar close")
    lines.append(f"    RSI:     {rsi_rule}")
    lines.append(f"    Exit:    {exit_winner_label}")
    lines.append("    \"\"\"")
    lines.append(f"    # Check 3 consecutive down bars")
    lines.append(f"    if not all(b.close < b.open for b in bars_4h[-{STREAK_LEN}:]):")
    lines.append(f"        return None")
    lines.append(f"    if vix_prior_close < {VIX_THRESHOLD}:")
    lines.append(f"        return None")
    if rsi_winner == "V2":
        lines.append(f"    if bars_4h[-1].rsi_14 >= {RSI_GATE_THRESHOLD}:")
        lines.append(f"        return None  # RSI hard gate")
    elif rsi_winner == "V3":
        lines.append(f"    size_mult = {RSI_BOOST_MULT} if bars_4h[-1].rsi_14 < {RSI_GATE_THRESHOLD} else {RSI_NORMAL_MULT}")
    lines.append(f"    return {{'entry': bars_4h[-1].close, 'exit': '{exit_winner_key}'}}")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    all_triggers = run_analysis()
    report = generate_report(all_triggers)

    output_path = RESULTS_DIR / "S44_FU_RSI_HorseRace_Results.md"
    output_path.write_text(report)
    print(f"\nResults saved to {output_path}")
    print("\n" + report)
