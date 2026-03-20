#!/usr/bin/env python3
"""Audit D3: Time-based partial profit-taking on 4H EMA cross-UP entries.

Same entry as D1/D2:
  - Signal: EMA9 > EMA21 cross on 4H bars
  - Execution: next M5 bar Open after signal 4H bar
  - Initial stop: min(Low) of entry bar + 2 prior; 1R = entry - stop
  - Clock stop (bar 6): if close < entry + 0.5R → EXIT
  - Phase2 gate: first M5 close >= entry + 1R
  - CE trail (post-Phase2): HH(22) - 2.0 × ATR(14)
  - Exits: CE | disaster stop | EOD 15:50

Partial take-profit addition:
  At T minutes after entry, if position is profitable (close > entry):
    - Cut 50% at current close → "partial leg" locked in
    - Remaining 50% rides CE trail to full exit → "remainder leg"
  Combined PnL_R = 0.5 × partial_R + 0.5 × remainder_R

Sweep T = [60, 75, 90, 105, 120] minutes + NO_TP baseline.
"""

import csv
import os
import numpy as np
from collections import defaultdict

AUDIT_DIR = os.path.dirname(__file__)
BACKTEST_DIR = os.path.join(AUDIT_DIR, "..")

ATR_PERIOD = 14
HH_LOOKBACK = 22
CE_MULT = 2.0
CLOCK_BAR = 6
CLOCK_THRESH_R = 0.50
TP_TIMES = [None, 60, 75, 90, 105, 120]  # None = no partial
TP_LABELS = ["NO_TP", "T60", "T75", "T90", "T105", "T120"]
PARTIAL_FRAC = 0.50


def load_m5(ticker):
    fpath = os.path.join(BACKTEST_DIR, f"{ticker}_m5_regsess.csv")
    bars = []
    with open(fpath) as f:
        for row in csv.DictReader(f):
            bars.append({
                "datetime": row["Datetime"],
                "date": row["Datetime"][:10],
                "hhmm": row["Datetime"][11:16],
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(float(row["Volume"])),
            })
    return bars


def calc_atr(bars):
    n = len(bars)
    tr = np.zeros(n)
    tr[0] = bars[0]["high"] - bars[0]["low"]
    for i in range(1, n):
        hl = bars[i]["high"] - bars[i]["low"]
        hc = abs(bars[i]["high"] - bars[i - 1]["close"])
        lc = abs(bars[i]["low"] - bars[i - 1]["close"])
        tr[i] = max(hl, hc, lc)
    atr = np.full(n, np.nan)
    if n < ATR_PERIOD:
        return atr
    atr[ATR_PERIOD - 1] = np.mean(tr[:ATR_PERIOD])
    k = 2.0 / (ATR_PERIOD + 1)
    for i in range(ATR_PERIOD, n):
        atr[i] = tr[i] * k + atr[i - 1] * (1 - k)
    return atr


def load_crosses():
    crosses = []
    fpath = os.path.join(AUDIT_DIR, "ema_4h_crosses.csv")
    with open(fpath) as f:
        for row in csv.DictReader(f):
            if row["direction"] == "UP":
                crosses.append(row)
    return crosses


def parse_minutes(hhmm):
    """Convert HH:MM to minutes since midnight."""
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    return h * 60 + m


def simulate_trade(bars, atr, entry_idx, tp_minutes):
    """Simulate one long trade with optional time-based partial TP.

    Returns dict with partial_pnl_r, remainder_pnl_r, combined_pnl_r.
    """
    entry_price = bars[entry_idx]["open"]
    entry_time_min = parse_minutes(bars[entry_idx]["hhmm"])
    entry_date = bars[entry_idx]["date"]

    lb_start = max(0, entry_idx - 2)
    lowest_low = min(bars[j]["low"] for j in range(lb_start, entry_idx + 1))
    one_r = entry_price - lowest_low
    if one_r <= 0:
        one_r = entry_price * 0.005

    disaster_stop = entry_price - one_r
    phase2 = False
    chandelier_stop = 0.0
    bars_in_trade = 0

    partial_taken = False
    partial_price = None
    partial_pnl_r = None

    exit_price = None
    exit_reason = None
    exit_dt = None

    highs = np.array([b["high"] for b in bars])

    for i in range(entry_idx + 1, len(bars)):
        bar = bars[i]
        prev_close = bars[i - 1]["close"]
        bars_in_trade += 1

        # Minutes elapsed since entry (handle multi-day)
        if bar["date"] == entry_date:
            elapsed = parse_minutes(bar["hhmm"]) - entry_time_min
        else:
            # Count remaining minutes of entry day + full days + current day
            # Simplified: each trading day = 390 min (09:30-16:00)
            days_between = 0
            d = entry_date
            dates_seen = sorted(set(b["date"] for b in bars[entry_idx:i + 1]))
            day_idx_entry = dates_seen.index(entry_date) if entry_date in dates_seen else 0
            day_idx_bar = dates_seen.index(bar["date"]) if bar["date"] in dates_seen else 0
            days_between = day_idx_bar - day_idx_entry
            # Minutes remaining on entry day
            entry_day_remaining = parse_minutes("16:00") - entry_time_min
            # Minutes into current day
            current_day_elapsed = parse_minutes(bar["hhmm"]) - parse_minutes("09:30")
            # Full days in between
            full_days = max(0, days_between - 1)
            elapsed = entry_day_remaining + full_days * 390 + current_day_elapsed

        # EOD forced exit
        if bar["hhmm"] >= "15:50":
            exit_price = bar["close"]
            exit_reason = "eod_1550"
            exit_dt = bar["datetime"]
            break

        # Disaster stop
        if prev_close < disaster_stop:
            exit_price = bar["open"]
            exit_reason = "disaster_stop"
            exit_dt = bar["datetime"]
            break

        # Clock stop at bar 6
        if bars_in_trade == CLOCK_BAR:
            required = entry_price + CLOCK_THRESH_R * one_r
            if bar["close"] < required:
                exit_price = bar["close"]
                exit_reason = "clock_stop"
                exit_dt = bar["datetime"]
                break

        # Time-based partial TP
        if tp_minutes is not None and not partial_taken and elapsed >= tp_minutes:
            if bar["close"] > entry_price:
                partial_taken = True
                partial_price = bar["close"]
                partial_pnl_r = (partial_price - entry_price) / one_r

        # Phase2 gate
        if not phase2 and bar["close"] >= entry_price + one_r:
            phase2 = True

        # CE trail
        if phase2 and i >= HH_LOOKBACK and not np.isnan(atr[i]):
            hh = highs[i - HH_LOOKBACK + 1:i + 1].max()
            new_stop = hh - CE_MULT * atr[i]
            chandelier_stop = max(chandelier_stop, new_stop)
            if prev_close < chandelier_stop:
                exit_price = bar["open"]
                exit_reason = "chandelier_stop"
                exit_dt = bar["datetime"]
                break

    if exit_price is None:
        exit_price = bars[-1]["close"]
        exit_reason = "end_of_data"
        exit_dt = bars[-1]["datetime"]

    remainder_pnl_r = (exit_price - entry_price) / one_r

    # Combined PnL
    if partial_taken:
        combined_pnl_r = PARTIAL_FRAC * partial_pnl_r + (1 - PARTIAL_FRAC) * remainder_pnl_r
    else:
        # No partial taken (either NO_TP, or not profitable at T, or exited before T)
        partial_pnl_r = None
        combined_pnl_r = remainder_pnl_r

    return {
        "entry_dt": bars[entry_idx]["datetime"],
        "entry_price": entry_price,
        "exit_dt": exit_dt,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "one_r": one_r,
        "partial_taken": partial_taken,
        "partial_price": partial_price if partial_taken else None,
        "partial_pnl_r": partial_pnl_r,
        "remainder_pnl_r": remainder_pnl_r,
        "combined_pnl_r": combined_pnl_r,
        "phase2_reached": phase2,
    }


# ── Main ────────────────────────────────────────────────────────────────────

crosses = load_crosses()
crosses_by_ticker = defaultdict(list)
for c in crosses:
    crosses_by_ticker[c["ticker"]].append(c)
tickers = sorted(crosses_by_ticker.keys())

m5_cache = {}
atr_cache = {}
dt_index = {}
for ticker in tickers:
    bars = load_m5(ticker)
    m5_cache[ticker] = bars
    atr_cache[ticker] = calc_atr(bars)
    dt_index[ticker] = {b["datetime"]: i for i, b in enumerate(bars)}


def find_entry_idx(ticker, cross):
    bars = m5_cache[ticker]
    if cross["half"] == "AM":
        target_dt = f"{cross['date']} 13:30:00"
        if target_dt in dt_index[ticker]:
            return dt_index[ticker][target_dt]
    else:
        dates = sorted(set(b["date"] for b in bars))
        for d in dates:
            if d > cross["date"]:
                target_dt = f"{d} 09:30:00"
                if target_dt in dt_index[ticker]:
                    return dt_index[ticker][target_dt]
                break
    return None


# Build entries
entries = []
for ticker in tickers:
    for cross in crosses_by_ticker[ticker]:
        entry_idx = find_entry_idx(ticker, cross)
        if entry_idx is not None and entry_idx >= 3:
            entries.append((ticker, cross, entry_idx))

print(f"Tickers: {len(tickers)} | Valid entries: {len(entries)}")

# ── Run all variants ────────────────────────────────────────────────────────

results = {label: [] for label in TP_LABELS}

for ticker, cross, entry_idx in entries:
    bars = m5_cache[ticker]
    atr = atr_cache[ticker]
    for tp_min, label in zip(TP_TIMES, TP_LABELS):
        trade = simulate_trade(bars, atr, entry_idx, tp_min)
        trade["ticker"] = ticker
        trade["cross_date"] = cross["date"]
        trade["cross_half"] = cross["half"]
        trade["variant"] = label
        results[label].append(trade)


def calc_metrics(trades):
    if not trades:
        return {"PF": 0, "AvgR": 0, "WinRate": 0, "N": 0}
    n = len(trades)
    wins = [t for t in trades if t["combined_pnl_r"] > 0]
    losses = [t for t in trades if t["combined_pnl_r"] <= 0]
    gp = sum(t["combined_pnl_r"] for t in wins) if wins else 0
    gl = abs(sum(t["combined_pnl_r"] for t in losses)) if losses else 0.001
    return {
        "PF": round(gp / gl, 2) if gl > 0 else 99.99,
        "AvgR": round(sum(t["combined_pnl_r"] for t in trades) / n, 3),
        "WinRate": round(100 * len(wins) / n, 1),
        "N": n,
    }


# ── Print ───────────────────────────────────────────────────────────────────

lines = []


def p(line=""):
    print(line)
    lines.append(line)


p("=" * 85)
p("AUDIT D3: TIME-BASED PARTIAL PROFIT-TAKING (CE 2.0×, CS-6 +0.5R)")
p("=" * 85)
p(f"At T minutes post-entry, if profitable: cut 50%. Remainder rides CE trail.")
p(f"Combined R = 0.5 × partial_R + 0.5 × remainder_R")
p()
p(f"  {'Variant':<8} {'PF':>7} {'CombAvgR':>9} {'WinRate':>8} {'N':>5}  "
  f"{'PartAvgR':>9} {'RemAvgR':>8} {'%Partial':>9}")
p(f"  {'-' * 75}")

for label in TP_LABELS:
    trades = results[label]
    m = calc_metrics(trades)

    # Partial leg stats
    partial_trades = [t for t in trades if t["partial_taken"]]
    n_partial = len(partial_trades)
    pct_partial = 100 * n_partial / len(trades) if trades else 0

    if partial_trades:
        avg_partial_r = sum(t["partial_pnl_r"] for t in partial_trades) / n_partial
        avg_remainder_r = sum(t["remainder_pnl_r"] for t in partial_trades) / n_partial
    else:
        avg_partial_r = 0
        avg_remainder_r = 0

    # For NO_TP, show remainder = full trade avg
    if label == "NO_TP":
        avg_remainder_r = sum(t["remainder_pnl_r"] for t in trades) / len(trades)
        p(f"  {label:<8} {m['PF']:>7.2f} {m['AvgR']:>9.3f} {m['WinRate']:>7.1f}% {m['N']:>5}  "
          f"{'  ---':>9} {avg_remainder_r:>8.3f} {'  ---':>9}")
    else:
        p(f"  {label:<8} {m['PF']:>7.2f} {m['AvgR']:>9.3f} {m['WinRate']:>7.1f}% {m['N']:>5}  "
          f"{avg_partial_r:>9.3f} {avg_remainder_r:>8.3f} {pct_partial:>8.1f}%")

p()

# Exit breakdown
p("EXIT BREAKDOWN:")
p(f"  {'Variant':<8} {'clock':>6} {'disaster':>9} {'CE':>5} {'EOD':>5} {'other':>6}")
p(f"  {'-' * 45}")
for label in TP_LABELS:
    reasons = defaultdict(int)
    for t in results[label]:
        reasons[t["exit_reason"]] += 1
    p(f"  {label:<8} {reasons.get('clock_stop',0):>6} {reasons.get('disaster_stop',0):>9} "
      f"{reasons.get('chandelier_stop',0):>5} {reasons.get('eod_1550',0):>5} "
      f"{reasons.get('end_of_data',0):>6}")

p()

# Claim check
p("CLAIM CHECK:")
p("  Prior: T=90 min best at PF 2.08")
tp_labels_only = [l for l in TP_LABELS if l != "NO_TP"]
best_tp = max(tp_labels_only, key=lambda l: calc_metrics(results[l])["PF"])
best_m = calc_metrics(results[best_tp])
t90_m = calc_metrics(results["T90"])
p(f"  T90 actual:  PF={t90_m['PF']:.2f}, AvgR={t90_m['AvgR']:.3f}")
p(f"  Best actual: {best_tp} PF={best_m['PF']:.2f}, AvgR={best_m['AvgR']:.3f}")
match_pf = "YES" if abs(t90_m["PF"] - 2.08) < 0.3 else ("~CLOSE" if abs(t90_m["PF"] - 2.08) < 0.6 else "NO")
p(f"  T90 PF match: {match_pf}")
is_best = best_tp == "T90"
p(f"  T90 is best variant: {'YES' if is_best else 'NO — ' + best_tp + ' is better'}")

p()

# Per-ticker for best variant
p(f"PER-TICKER ({best_tp} vs NO_TP):")
p(f"  {'Ticker':<8} {'NO_TP_PF':>9} {'NO_TP_AvgR':>11} {best_tp+'_PF':>10} {best_tp+'_AvgR':>12} {'N':>5}")
p(f"  {'-' * 60}")
for ticker in tickers:
    base = [t for t in results["NO_TP"] if t["ticker"] == ticker]
    best = [t for t in results[best_tp] if t["ticker"] == ticker]
    mb = calc_metrics(base)
    mc = calc_metrics(best)
    if mb["N"] > 0:
        p(f"  {ticker:<8} {mb['PF']:>9.2f} {mb['AvgR']:>11.3f} {mc['PF']:>10.2f} {mc['AvgR']:>12.3f} {mb['N']:>5}")

# ── Save CSV ────────────────────────────────────────────────────────────────
csv_path = os.path.join(AUDIT_DIR, "audit_d3_time_partial.csv")
detail_rows = []
for label in TP_LABELS:
    for t in results[label]:
        detail_rows.append({
            "variant": t["variant"],
            "ticker": t["ticker"],
            "cross_date": t["cross_date"],
            "cross_half": t["cross_half"],
            "entry_dt": t["entry_dt"],
            "entry_price": f"{t['entry_price']:.4f}",
            "exit_dt": t["exit_dt"],
            "exit_price": f"{t['exit_price']:.4f}",
            "exit_reason": t["exit_reason"],
            "one_r": f"{t['one_r']:.4f}",
            "partial_taken": "1" if t["partial_taken"] else "0",
            "partial_price": f"{t['partial_price']:.4f}" if t["partial_price"] else "",
            "partial_pnl_r": f"{t['partial_pnl_r']:.3f}" if t["partial_pnl_r"] is not None else "",
            "remainder_pnl_r": f"{t['remainder_pnl_r']:.3f}",
            "combined_pnl_r": f"{t['combined_pnl_r']:.3f}",
        })

with open(csv_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(detail_rows[0].keys()))
    writer.writeheader()
    writer.writerows(detail_rows)
p(f"Saved: {csv_path}")

# ── Chart ───────────────────────────────────────────────────────────────────
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(16, 5.5))

    # Compute metrics
    all_pf, all_avgr, all_winr = [], [], []
    part_avgr, rem_avgr = [], []
    for label in TP_LABELS:
        m = calc_metrics(results[label])
        all_pf.append(m["PF"])
        all_avgr.append(m["AvgR"])
        all_winr.append(m["WinRate"])
        pt = [t for t in results[label] if t["partial_taken"]]
        if pt:
            part_avgr.append(sum(t["partial_pnl_r"] for t in pt) / len(pt))
            rem_avgr.append(sum(t["remainder_pnl_r"] for t in pt) / len(pt))
        else:
            part_avgr.append(0)
            rem_avgr.append(sum(t["remainder_pnl_r"] for t in results[label]) / len(results[label]))

    x = range(len(TP_LABELS))
    colors = ["#607D8B", "#2196F3", "#4CAF50", "#FF9800", "#F44336", "#9C27B0"]

    # Panel 1: PF
    ax = axes[0]
    bars_pf = ax.bar(x, all_pf, color=colors, alpha=0.85, edgecolor="white")
    ax.axhline(1.0, color="gray", ls="--", alpha=0.5)
    for b, pf in zip(bars_pf, all_pf):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.01,
                f"{pf:.2f}", ha="center", va="bottom", fontsize=9)
    ax.set_xticks(list(x))
    ax.set_xticklabels(TP_LABELS, fontsize=8, rotation=15)
    ax.set_ylabel("Profit Factor")
    ax.set_title("Combined PF by TP Timing")

    # Panel 2: Combined AvgR
    ax2 = axes[1]
    bars_ar = ax2.bar(x, all_avgr, color=colors, alpha=0.85, edgecolor="white")
    ax2.axhline(0, color="gray", ls="--", alpha=0.5)
    for b, ar in zip(bars_ar, all_avgr):
        ax2.text(b.get_x() + b.get_width() / 2, ar + 0.003 if ar >= 0 else ar - 0.01,
                 f"{ar:.3f}R", ha="center", va="bottom" if ar >= 0 else "top", fontsize=9)
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(TP_LABELS, fontsize=8, rotation=15)
    ax2.set_ylabel("Combined Avg R")
    ax2.set_title("Combined AvgR by TP Timing")

    # Panel 3: Partial leg vs Remainder leg AvgR (only for TP variants)
    ax3 = axes[2]
    tp_x = range(1, len(TP_LABELS))
    tp_lab = TP_LABELS[1:]
    w = 0.35
    ax3.bar([i - w / 2 for i in tp_x], part_avgr[1:], w,
            label="Partial Leg AvgR", color="#4CAF50", alpha=0.85)
    ax3.bar([i + w / 2 for i in tp_x], rem_avgr[1:], w,
            label="Remainder Leg AvgR", color="#2196F3", alpha=0.85)
    for i, (pr, rr) in enumerate(zip(part_avgr[1:], rem_avgr[1:]), 1):
        ax3.text(i - w / 2, pr + 0.01, f"{pr:.2f}R", ha="center", fontsize=8, va="bottom")
        ax3.text(i + w / 2, rr + 0.01 if rr >= 0 else rr - 0.01,
                 f"{rr:.2f}R", ha="center", fontsize=8,
                 va="bottom" if rr >= 0 else "top")
    ax3.axhline(0, color="gray", ls="--", alpha=0.5)
    ax3.set_xticks(list(tp_x))
    ax3.set_xticklabels(tp_lab, fontsize=8)
    ax3.set_ylabel("Avg R")
    ax3.set_title("Partial vs Remainder Leg AvgR")
    ax3.legend(fontsize=8)

    plt.suptitle("Audit D3: Time-Based Partial TP (CE 2.0×, CS-6 +0.5R)",
                 fontsize=12, fontweight="bold", y=1.02)
    plt.tight_layout()
    chart_path = os.path.join(AUDIT_DIR, "audit_d3_chart.png")
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    p(f"Saved: {chart_path}")

except ImportError:
    print("matplotlib not available — chart skipped")
