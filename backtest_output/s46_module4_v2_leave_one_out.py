#!/usr/bin/env python3
"""
S46 Module 4 V2 — Leave-One-Episode-Out Validation.

Tests whether V2 (close-to-close) streak definition survives when the
April 2025 selloff cluster is removed. Also runs leave-one-ticker-out
and full count reconciliation between V0 and V2.

Common setup (same as S44):
  Trigger:  streak condition AND prior-day VIX >= 25 AND 4H RSI(14) < 35
  Entry:    4H trigger bar close
  Exit:     first 4H close >= EMA21 (hard max 10 bars)
  Scope:    25 equity tickers (excl SPY, VIXY)
"""

import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── Config ───────────────────────────────────────────────────────────────────

TICKERS = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU", "C",
    "COIN", "COST", "GOOGL", "GS", "INTC", "JPM", "MARA", "META", "MSFT",
    "MSTR", "MU", "NVDA", "PLTR", "SMCI", "TSLA", "TSM", "V",
]

VIX_THRESHOLD = 25.0
RSI_THRESHOLD = 35.0
STREAK_LEN = 3
MAX_HOLD = 10
APRIL_START = "2025-04-01"
APRIL_END = "2025-04-30"

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


def detect_v2(bars):
    """V2: DOWN = close < prior_bar_close. 3 consecutive."""
    closes = bars["close"].values
    is_down = pd.Series(
        [False] + [closes[i] < closes[i - 1] for i in range(1, len(closes))],
        index=bars.index,
    )
    triggers = []
    for i in range(STREAK_LEN, len(bars)):
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
            return _trade(bars, entry_idx, j, entry_price, bar["close"])
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


def _sig(p):
    if p < 0.001:
        return "***"
    elif p < 0.01:
        return "**"
    elif p < 0.05:
        return "*"
    return ""


def is_april_2025(date_str):
    return APRIL_START <= date_str <= APRIL_END


# ── Collect all trades ──────────────────────────────────────────────────────


def collect_all_trades(vix_daily):
    """Run V0 and V2 detectors on all tickers. Return trade lists with metadata."""
    detectors = {"V0": detect_v0, "V2": detect_v2}
    all_trades = {v: [] for v in detectors}
    all_triggers = {v: [] for v in detectors}  # list of dicts for detailed reconciliation

    for ticker in TICKERS:
        print(f"  {ticker}...", end="", flush=True)
        bars = load_4h_bars(ticker)

        for vname, detect_fn in detectors.items():
            raw_triggers = detect_fn(bars)

            for idx in raw_triggers:
                bar = bars.iloc[idx]

                rsi = bar.get("rsi_14")
                if pd.isna(rsi) or rsi >= RSI_THRESHOLD:
                    continue

                vix_val = get_prior_vix(vix_daily, bar["date_str"])
                if vix_val is None or vix_val < VIX_THRESHOLD:
                    continue

                trigger_info = {
                    "ticker": ticker,
                    "date_str": bar["date_str"],
                    "timestamp": str(bar["timestamp"]),
                }
                all_triggers[vname].append(trigger_info)

                entry_price = bar["close"]
                trade = compute_exit(bars, idx, entry_price)
                if trade:
                    trade["ticker"] = ticker
                    trade["date_str"] = bar["date_str"]
                    trade["timestamp"] = str(bar["timestamp"])
                    all_trades[vname].append(trade)

        print(" done")

    return all_trades, all_triggers


# ── Test A: Leave-April-2025-Out ────────────────────────────────────────────


def test_a_leave_april_out(all_trades):
    lines = []
    lines.append("LEAVE-APRIL-OUT")
    lines.append("=" * 50)
    lines.append("")

    for v in ["V0", "V2"]:
        trades = all_trades[v]
        ex_april = [t for t in trades if not is_april_2025(t["date_str"])]
        april_only = [t for t in trades if is_april_2025(t["date_str"])]

        m_full = compute_metrics(trades)
        m_ex = compute_metrics(ex_april)
        m_apr = compute_metrics(april_only)

        lines.append(f"{v} full:      N={m_full['N']} | Mean={m_full['mean']:+.2f}% | "
                     f"WR={m_full['wr']:.0f}% | PF={m_full['pf']:.2f} | "
                     f"Sharpe={m_full['sharpe']:.2f} | p={m_full['p']:.4f}{_sig(m_full['p'])}")
        lines.append(f"{v} ex-April:  N={m_ex['N']} | Mean={m_ex['mean']:+.2f}% | "
                     f"WR={m_ex['wr']:.0f}% | PF={m_ex['pf']:.2f} | "
                     f"Sharpe={m_ex['sharpe']:.2f} | p={m_ex['p']:.4f}{_sig(m_ex['p'])}")
        lines.append(f"{v} April-only: N={m_apr['N']} | Mean={m_apr['mean']:+.2f}% | "
                     f"WR={m_apr['wr']:.0f}%")
        lines.append("")

    # Compare V2 vs V0 ex-April
    v0_ex = compute_metrics([t for t in all_trades["V0"] if not is_april_2025(t["date_str"])])
    v2_ex = compute_metrics([t for t in all_trades["V2"] if not is_april_2025(t["date_str"])])

    v2_better = (v2_ex["sharpe"] > v0_ex["sharpe"]
                 and v2_ex["N"] >= v0_ex["N"]
                 and v2_ex["wr"] >= v0_ex["wr"] - 2)
    verdict = "YES" if v2_better else "NO (but check details)"

    lines.append(f"V2 still better than V0 with April removed? **{verdict}**")
    lines.append(f"  V2 ex-April Sharpe={v2_ex['sharpe']:.2f} vs V0 ex-April Sharpe={v0_ex['sharpe']:.2f}")
    lines.append(f"  V2 ex-April N={v2_ex['N']} vs V0 ex-April N={v0_ex['N']}")
    lines.append(f"  V2 ex-April WR={v2_ex['wr']:.0f}% vs V0 ex-April WR={v0_ex['wr']:.0f}%")
    lines.append("")

    # List April V2 trades
    april_v2 = [t for t in all_trades["V2"] if is_april_2025(t["date_str"])]
    if april_v2:
        lines.append("April 2025 V2 trades:")
        lines.append("| Ticker | Date | Return% | Win |")
        lines.append("|--------|------|---------|-----|")
        for t in sorted(april_v2, key=lambda x: (x["date_str"], x["ticker"])):
            w = "Y" if t["win"] else "N"
            lines.append(f"| {t['ticker']} | {t['date_str']} | {t['return_pct']:+.2f}% | {w} |")
    lines.append("")

    return lines


# ── Test B: Leave-One-Ticker-Out ────────────────────────────────────────────


def test_b_leave_one_ticker_out(all_trades):
    lines = []
    lines.append("LEAVE-ONE-TICKER-OUT (V2)")
    lines.append("=" * 50)
    lines.append("")

    v2_trades = all_trades["V2"]
    full_m = compute_metrics(v2_trades)

    results = []
    for excluded in TICKERS:
        remaining = [t for t in v2_trades if t["ticker"] != excluded]
        m = compute_metrics(remaining)
        delta_mean = m["mean"] - full_m["mean"]
        delta_wr = m["wr"] - full_m["wr"]
        n_removed = full_m["N"] - m["N"]
        results.append({
            "ticker": excluded,
            "N": m["N"],
            "mean": m["mean"],
            "wr": m["wr"],
            "pf": m["pf"],
            "sharpe": m["sharpe"],
            "delta_mean": delta_mean,
            "delta_wr": delta_wr,
            "n_removed": n_removed,
        })

    lines.append(f"Full V2: N={full_m['N']} | Mean={full_m['mean']:+.2f}% | WR={full_m['wr']:.0f}%")
    lines.append("")
    lines.append("| Excluded | N | N_removed | Mean% | dMean% | WR% | dWR% | PF | Sharpe | Flag |")
    lines.append("|----------|---|-----------|-------|--------|-----|------|----|--------|------|")

    flagged = []
    for r in sorted(results, key=lambda x: abs(x["delta_mean"]), reverse=True):
        flag = ""
        if abs(r["delta_mean"]) > 2.0:
            flag += "MEAN>"
            flagged.append(f"{r['ticker']} (mean delta {r['delta_mean']:+.2f}%)")
        if abs(r["delta_wr"]) > 5.0:
            flag += "WR>"
            flagged.append(f"{r['ticker']} (WR delta {r['delta_wr']:+.1f}%)")
        lines.append(f"| {r['ticker']:>8} | {r['N']:>3} | {r['n_removed']:>9} | "
                     f"{r['mean']:+.2f} | {r['delta_mean']:+.2f} | {r['wr']:.0f} | "
                     f"{r['delta_wr']:+.1f} | {r['pf']:.2f} | {r['sharpe']:.2f} | {flag} |")

    lines.append("")

    means = [r["mean"] for r in results]
    wrs = [r["wr"] for r in results]
    ns = [r["N"] for r in results]

    most_influential = max(results, key=lambda x: abs(x["delta_mean"]))
    least_influential = min(results, key=lambda x: abs(x["delta_mean"]))

    lines.append(f"Most influential ticker:  {most_influential['ticker']} "
                 f"(removal changes mean by {most_influential['delta_mean']:+.2f}%)")
    lines.append(f"Least influential ticker: {least_influential['ticker']} "
                 f"(removal changes mean by {least_influential['delta_mean']:+.2f}%)")
    lines.append(f"Range of N:     {min(ns)} to {max(ns)}")
    lines.append(f"Range of means: {min(means):+.2f}% to {max(means):+.2f}%")
    lines.append(f"Range of WRs:   {min(wrs):.0f}% to {max(wrs):.0f}%")
    lines.append("")

    if flagged:
        lines.append(f"FLAGGED tickers (mean>2% or WR>5%): {', '.join(flagged)}")
        lines.append("")

    # Verdict
    mean_spread = max(means) - min(means)
    wr_spread = max(wrs) - min(wrs)
    if mean_spread < 3.0 and wr_spread < 8.0 and not any(abs(r["delta_mean"]) > 2.0 for r in results):
        verdict = "ROBUST — no single ticker dominates"
    else:
        verdict = "CONCENTRATED — results depend on specific tickers"
    lines.append(f"VERDICT: {verdict}")
    lines.append(f"  (mean spread={mean_spread:.2f}%, WR spread={wr_spread:.1f}%)")
    lines.append("")

    return lines


# ── Test C: Count Reconciliation ────────────────────────────────────────────


def test_c_count_reconciliation(all_triggers, all_trades):
    lines = []
    lines.append("COUNT RECONCILIATION")
    lines.append("=" * 50)
    lines.append("")

    # Build trigger key sets: (ticker, date_str, timestamp)
    v0_keys = set()
    for t in all_triggers["V0"]:
        v0_keys.add((t["ticker"], t["date_str"], t["timestamp"]))

    v2_keys = set()
    for t in all_triggers["V2"]:
        v2_keys.add((t["ticker"], t["date_str"], t["timestamp"]))

    overlap = v0_keys & v2_keys
    v2_only = v2_keys - v0_keys
    v0_only = v0_keys - v2_keys

    lines.append(f"V0 total triggers: {len(v0_keys)}")
    lines.append(f"V2 total triggers: {len(v2_keys)}")
    lines.append(f"Overlap (both):    {len(overlap)}")
    lines.append(f"V2-only:           {len(v2_only)}")
    lines.append(f"V0-only:           {len(v0_only)}")
    lines.append(f"Net diff (V2-V0):  {len(v2_keys) - len(v0_keys)} "
                 f"(+{len(v2_only)} extra, -{len(v0_only)} lost)")
    lines.append("")

    # Trade-level reconciliation (triggers that produced trades)
    v0_trade_keys = set((t["ticker"], t["date_str"], t["timestamp"]) for t in all_trades["V0"])
    v2_trade_keys = set((t["ticker"], t["date_str"], t["timestamp"]) for t in all_trades["V2"])
    trade_overlap = v0_trade_keys & v2_trade_keys
    v2_trade_only = v2_trade_keys - v0_trade_keys
    v0_trade_only = v0_trade_keys - v2_trade_keys

    lines.append("Trade-level (triggers that produced exits):")
    lines.append(f"  V0 trades: {len(v0_trade_keys)}")
    lines.append(f"  V2 trades: {len(v2_trade_keys)}")
    lines.append(f"  Overlap:   {len(trade_overlap)}")
    lines.append(f"  V2-only:   {len(v2_trade_only)}")
    lines.append(f"  V0-only:   {len(v0_trade_only)}")
    lines.append("")

    # Triggers without trades (exit couldn't complete)
    v0_no_exit = v0_keys - v0_trade_keys
    v2_no_exit = v2_keys - v2_trade_keys
    lines.append(f"Triggers without exit (truncated at data end):")
    lines.append(f"  V0: {len(v0_no_exit)} triggers had no exit")
    lines.append(f"  V2: {len(v2_no_exit)} triggers had no exit")
    lines.append("")

    # Explain the discrepancy flagged by DR
    lines.append("DR flagged discrepancy: '+29 extra, -14 lost = net +15, but N diff = +17'")
    lines.append(f"Actual trigger counts: +{len(v2_only)} extra, -{len(v0_only)} lost = "
                 f"net {len(v2_only) - len(v0_only):+d}")
    lines.append(f"Actual trade counts: V2={len(all_trades['V2'])}, V0={len(all_trades['V0'])}, "
                 f"diff={len(all_trades['V2']) - len(all_trades['V0']):+d}")
    lines.append("")

    # The discrepancy can arise from triggers vs trades difference
    trigger_diff = len(v2_keys) - len(v0_keys)
    trade_diff = len(all_trades["V2"]) - len(all_trades["V0"])
    if trigger_diff != trade_diff:
        lines.append(f"EXPLANATION: Trigger net diff ({trigger_diff:+d}) != Trade net diff ({trade_diff:+d}).")
        lines.append(f"  This is because {abs(trigger_diff - trade_diff)} trigger(s) in one variant")
        lines.append(f"  fail to produce an exit (data ends before max-hold completes).")
        lines.append(f"  V0 no-exit: {len(v0_no_exit)}, V2 no-exit: {len(v2_no_exit)}")
        lines.append(f"  Difference in no-exits: {len(v2_no_exit) - len(v0_no_exit):+d}")
        lines.append(f"  Trade diff = trigger diff - no-exit diff = "
                     f"{trigger_diff:+d} - ({len(v2_no_exit) - len(v0_no_exit):+d}) = {trade_diff:+d}")
    else:
        lines.append(f"No discrepancy: trigger diff = trade diff = {trade_diff:+d}")
    lines.append("")

    # List V2-only triggers
    lines.append("V2-only triggers (not in V0):")
    lines.append("| Ticker | Date | Timestamp |")
    lines.append("|--------|------|-----------|")
    for ticker, date_str, ts in sorted(v2_only):
        lines.append(f"| {ticker} | {date_str} | {ts} |")
    lines.append("")

    # List V0-only triggers
    lines.append("V0-only triggers (not in V2):")
    lines.append("| Ticker | Date | Timestamp |")
    lines.append("|--------|------|-----------|")
    for ticker, date_str, ts in sorted(v0_only):
        lines.append(f"| {ticker} | {date_str} | {ts} |")
    lines.append("")

    return lines


# ── Main ────────────────────────────────────────────────────────────────────


def run():
    vix_daily = load_vix_daily()
    print(f"VIX: {len(vix_daily)} days loaded")
    print(f"Tickers: {len(TICKERS)}")
    print()

    all_trades, all_triggers = collect_all_trades(vix_daily)
    print()

    report_lines = []
    report_lines.append("# S46 Module 4 V2 — Leave-One-Episode-Out Validation")
    report_lines.append("")
    report_lines.append(f"**Date:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    report_lines.append(f"**Tickers:** {len(TICKERS)} equity (excl SPY, VIXY)")
    report_lines.append(f"**Filters:** prior-day VIX >= {VIX_THRESHOLD}, 4H RSI(14) < {RSI_THRESHOLD}")
    report_lines.append(f"**Entry:** 4H trigger bar close")
    report_lines.append(f"**Exit:** first 4H close >= EMA21 (hard max {MAX_HOLD} bars)")
    report_lines.append(f"**V0:** close < open, 3 consecutive")
    report_lines.append(f"**V2:** close < prior_bar_close, 3 consecutive")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")

    # Test A
    print("=== Test A: Leave-April-2025-Out ===")
    report_lines.append("## Test A: Leave-April-2025-Out")
    report_lines.append("")
    report_lines.append("```")
    report_lines.extend(test_a_leave_april_out(all_trades))
    report_lines.append("```")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")

    # Test B
    print("=== Test B: Leave-One-Ticker-Out ===")
    report_lines.append("## Test B: Leave-One-Ticker-Out")
    report_lines.append("")
    report_lines.append("```")
    report_lines.extend(test_b_leave_one_ticker_out(all_trades))
    report_lines.append("```")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")

    # Test C
    print("=== Test C: Count Reconciliation ===")
    report_lines.append("## Test C: Count Reconciliation")
    report_lines.append("")
    report_lines.append("```")
    report_lines.extend(test_c_count_reconciliation(all_triggers, all_trades))
    report_lines.append("```")
    report_lines.append("")

    report = "\n".join(report_lines)

    out_path = RESULTS_DIR / "S46_Module4_V2_Leave_One_Out.md"
    out_path.write_text(report)
    print(f"\nResults saved to {out_path}")
    print()
    print(report)


if __name__ == "__main__":
    run()
