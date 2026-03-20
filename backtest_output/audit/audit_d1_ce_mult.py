#!/usr/bin/env python3
"""Audit D1: Chandelier-Exit multiplier sweep on 4H EMA cross-UP entries.

Entry logic:
  - Signal: EMA9 crosses above EMA21 on 4H bars (from ema_4h_crosses.csv)
  - Execution: next M5 bar Open after the signal 4H bar completes
    (AM cross → 13:30 entry; PM cross → next day 09:30 entry)
  - Initial stop: min(Low) of entry bar and 2 prior bars; 1R = entry - stop
  - Phase2 gate: first M5 close >= entry + 1R
  - CE trail (post-Phase2): Highest-High(22) - mult × ATR(14)
  - Exits: M5 close < CE line | close < disaster stop | EOD 15:50 bar

Sweep: mult = [1.50, 1.75, 2.00, 2.25, 2.50]
"""

import csv
import os
import numpy as np
from collections import defaultdict

AUDIT_DIR = os.path.dirname(__file__)
BACKTEST_DIR = os.path.join(AUDIT_DIR, "..")

ATR_PERIOD = 14
HH_LOOKBACK = 22
INITIAL_STOP_BARS = 3       # entry bar + 2 prior
MULTIPLIERS = [1.50, 1.75, 2.00, 2.25, 2.50]


# ── Helpers ─────────────────────────────────────────────────────────────────

def load_m5(ticker):
    """Load M5 regsess bars as list of dicts with floats."""
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
    """ATR(14) via EMA on True Range. Returns array len(bars)."""
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
    """Load UP crosses from ema_4h_crosses.csv."""
    crosses = []
    fpath = os.path.join(AUDIT_DIR, "ema_4h_crosses.csv")
    with open(fpath) as f:
        for row in csv.DictReader(f):
            if row["direction"] == "UP":
                crosses.append(row)
    return crosses


# ── Trade simulation ────────────────────────────────────────────────────────

def simulate_trade(bars, atr, entry_idx, multiplier):
    """Simulate one long trade from entry_idx. Returns trade dict or None."""
    entry_price = bars[entry_idx]["open"]

    # Initial stop: min(Low) of entry bar and 2 prior bars
    lb_start = max(0, entry_idx - 2)
    lowest_low = min(bars[j]["low"] for j in range(lb_start, entry_idx + 1))
    one_r = entry_price - lowest_low

    if one_r <= 0:
        one_r = entry_price * 0.005  # fallback 0.5%

    disaster_stop = entry_price - one_r
    phase2 = False
    chandelier_stop = 0.0
    exit_price = None
    exit_reason = None
    exit_dt = None

    highs = np.array([b["high"] for b in bars])

    for i in range(entry_idx + 1, len(bars)):
        bar = bars[i]
        prev_close = bars[i - 1]["close"]

        # EOD forced exit at 15:50
        if bar["hhmm"] >= "15:50":
            exit_price = bar["close"]
            exit_reason = "eod_1550"
            exit_dt = bar["datetime"]
            break

        # Disaster stop (always active)
        if prev_close < disaster_stop:
            exit_price = bar["open"]
            exit_reason = "disaster_stop"
            exit_dt = bar["datetime"]
            break

        # Phase2 gate: close >= entry + 1R
        if not phase2 and bar["close"] >= entry_price + one_r:
            phase2 = True

        # CE trail (only after Phase2)
        if phase2 and i >= HH_LOOKBACK and not np.isnan(atr[i]):
            hh = highs[i - HH_LOOKBACK + 1:i + 1].max()
            new_stop = hh - multiplier * atr[i]
            chandelier_stop = max(chandelier_stop, new_stop)

            if prev_close < chandelier_stop:
                exit_price = bar["open"]
                exit_reason = "chandelier_stop"
                exit_dt = bar["datetime"]
                break

    # End-of-data fallback
    if exit_price is None:
        exit_price = bars[-1]["close"]
        exit_reason = "end_of_data"
        exit_dt = bars[-1]["datetime"]

    pnl = exit_price - entry_price
    pnl_r = pnl / one_r

    return {
        "entry_dt": bars[entry_idx]["datetime"],
        "entry_price": entry_price,
        "exit_dt": exit_dt,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "one_r": one_r,
        "pnl": pnl,
        "pnl_r": pnl_r,
        "phase2_reached": phase2,
    }


# ── Main ────────────────────────────────────────────────────────────────────

crosses = load_crosses()
print(f"Loaded {len(crosses)} UP crosses")

# Group crosses by ticker
crosses_by_ticker = defaultdict(list)
for c in crosses:
    crosses_by_ticker[c["ticker"]].append(c)

tickers = sorted(crosses_by_ticker.keys())
print(f"Tickers: {len(tickers)}")

# Pre-load M5 data and ATR per ticker
m5_cache = {}
atr_cache = {}
for ticker in tickers:
    bars = load_m5(ticker)
    m5_cache[ticker] = bars
    atr_cache[ticker] = calc_atr(bars)

# Build datetime index for fast lookup
dt_index = {}
for ticker in tickers:
    dt_index[ticker] = {b["datetime"]: i for i, b in enumerate(m5_cache[ticker])}


def find_entry_idx(ticker, cross):
    """Find entry bar index: next M5 bar after the cross 4H bar."""
    bars = m5_cache[ticker]
    cross_date = cross["date"]
    cross_half = cross["half"]

    if cross_half == "AM":
        # AM bar ends at 13:25 → entry at 13:30 same day
        target_dt = f"{cross_date} 13:30:00"
        if target_dt in dt_index[ticker]:
            return dt_index[ticker][target_dt]
    else:
        # PM bar ends at 15:55 → entry at 09:30 next trading day
        # Find next date in data after cross_date
        dates = sorted(set(b["date"] for b in bars))
        for d in dates:
            if d > cross_date:
                target_dt = f"{d} 09:30:00"
                if target_dt in dt_index[ticker]:
                    return dt_index[ticker][target_dt]
                break
    return None


# ── Run sweep ───────────────────────────────────────────────────────────────

all_results = []  # (mult, ticker, trade_dict)

for mult in MULTIPLIERS:
    for ticker in tickers:
        for cross in crosses_by_ticker[ticker]:
            entry_idx = find_entry_idx(ticker, cross)
            if entry_idx is None or entry_idx < 3:
                continue
            trade = simulate_trade(m5_cache[ticker], atr_cache[ticker], entry_idx, mult)
            if trade:
                trade["ticker"] = ticker
                trade["multiplier"] = mult
                trade["cross_date"] = cross["date"]
                trade["cross_half"] = cross["half"]
                all_results.append(trade)

# ── Metrics ─────────────────────────────────────────────────────────────────

def calc_metrics(trades):
    if not trades:
        return {"PF": 0, "AvgR": 0, "WinRate": 0, "N": 0}
    n = len(trades)
    wins = [t for t in trades if t["pnl_r"] > 0]
    losses = [t for t in trades if t["pnl_r"] <= 0]
    gross_profit = sum(t["pnl_r"] for t in wins) if wins else 0
    gross_loss = abs(sum(t["pnl_r"] for t in losses)) if losses else 0.001
    return {
        "PF": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 99.99,
        "AvgR": round(sum(t["pnl_r"] for t in trades) / n, 3),
        "WinRate": round(100 * len(wins) / n, 1),
        "N": n,
    }


print("\n" + "=" * 70)
print("AUDIT D1: CHANDELIER-EXIT MULTIPLIER SWEEP (4H EMA CROSS-UP ENTRIES)")
print("=" * 70)
print(f"{'Mult':>6} {'PF':>7} {'AvgR':>8} {'WinRate':>8} {'N':>6}  {'P2%':>6}  Exit Breakdown")
print(f"{'-' * 75}")

summary_rows = []

for mult in MULTIPLIERS:
    trades = [t for t in all_results if t["multiplier"] == mult]
    m = calc_metrics(trades)

    # Exit breakdown
    reasons = defaultdict(int)
    for t in trades:
        reasons[t["exit_reason"]] += 1
    p2_pct = round(100 * sum(1 for t in trades if t["phase2_reached"]) / len(trades), 1) if trades else 0

    breakdown = "  ".join(f"{k}:{v}" for k, v in sorted(reasons.items()))
    print(f"{mult:>6.2f} {m['PF']:>7.2f} {m['AvgR']:>8.3f} {m['WinRate']:>7.1f}% {m['N']:>6}  {p2_pct:>5.1f}%  {breakdown}")

    summary_rows.append({
        "multiplier": f"{mult:.2f}",
        "profit_factor": f"{m['PF']:.2f}",
        "avg_r": f"{m['AvgR']:.3f}",
        "win_rate_pct": f"{m['WinRate']:.1f}",
        "n_trades": str(m["N"]),
        "phase2_pct": f"{p2_pct:.1f}",
        **{f"exit_{k}": str(v) for k, v in sorted(reasons.items())},
    })

# Per-ticker breakdown for best multiplier
best_mult = max(MULTIPLIERS, key=lambda m: calc_metrics([t for t in all_results if t["multiplier"] == m])["PF"])
print(f"\nBest multiplier by PF: {best_mult:.2f}x")

print(f"\nPer-ticker breakdown (mult={best_mult:.2f}x):")
print(f"  {'Ticker':<8} {'PF':>7} {'AvgR':>8} {'WinRate':>8} {'N':>5}")
print(f"  {'-' * 40}")

for ticker in tickers:
    tt = [t for t in all_results if t["multiplier"] == best_mult and t["ticker"] == ticker]
    if not tt:
        continue
    m = calc_metrics(tt)
    print(f"  {ticker:<8} {m['PF']:>7.2f} {m['AvgR']:>8.3f} {m['WinRate']:>7.1f}% {m['N']:>5}")

# ── Save CSV ────────────────────────────────────────────────────────────────
csv_path = os.path.join(AUDIT_DIR, "audit_d1_ce_mult.csv")

# All trade details
detail_rows = []
for t in all_results:
    detail_rows.append({
        "multiplier": f"{t['multiplier']:.2f}",
        "ticker": t["ticker"],
        "cross_date": t["cross_date"],
        "cross_half": t["cross_half"],
        "entry_dt": t["entry_dt"],
        "entry_price": f"{t['entry_price']:.4f}",
        "exit_dt": t["exit_dt"],
        "exit_price": f"{t['exit_price']:.4f}",
        "exit_reason": t["exit_reason"],
        "one_r": f"{t['one_r']:.4f}",
        "pnl_r": f"{t['pnl_r']:.3f}",
        "phase2": "1" if t["phase2_reached"] else "0",
    })

with open(csv_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(detail_rows[0].keys()))
    writer.writeheader()
    writer.writerows(detail_rows)
print(f"\nSaved: {csv_path}")

# ── Chart ───────────────────────────────────────────────────────────────────
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    # Compute metrics per mult
    mults_f = []
    pfs = []
    avgrs = []
    winrs = []
    ns = []
    for mult in MULTIPLIERS:
        trades = [t for t in all_results if t["multiplier"] == mult]
        m = calc_metrics(trades)
        mults_f.append(mult)
        pfs.append(m["PF"])
        avgrs.append(m["AvgR"])
        winrs.append(m["WinRate"])
        ns.append(m["N"])

    # Panel 1: Profit Factor
    ax = axes[0]
    colors = ["#F44336" if pf < 1.0 else "#4CAF50" for pf in pfs]
    bars = ax.bar([f"{m:.2f}x" for m in mults_f], pfs, color=colors, alpha=0.85, edgecolor="white")
    ax.axhline(1.0, color="gray", linestyle="--", alpha=0.5, label="Breakeven")
    for bar, pf, n in zip(bars, pfs, ns):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                f"{pf:.2f}\nN={n}", ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("Profit Factor")
    ax.set_xlabel("CE Multiplier")
    ax.set_title("Profit Factor by CE Multiplier")
    ax.legend(fontsize=8)

    # Panel 2: Avg R
    ax2 = axes[1]
    colors2 = ["#F44336" if r < 0 else "#2196F3" for r in avgrs]
    bars2 = ax2.bar([f"{m:.2f}x" for m in mults_f], avgrs, color=colors2, alpha=0.85, edgecolor="white")
    ax2.axhline(0, color="gray", linestyle="--", alpha=0.5)
    for bar, r in zip(bars2, avgrs):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.005,
                 f"{r:.3f}R", ha="center", va="bottom", fontsize=9)
    ax2.set_ylabel("Average R")
    ax2.set_xlabel("CE Multiplier")
    ax2.set_title("Average R-Multiple by CE Multiplier")

    # Panel 3: Win Rate
    ax3 = axes[2]
    bars3 = ax3.bar([f"{m:.2f}x" for m in mults_f], winrs, color="#FF9800", alpha=0.85, edgecolor="white")
    for bar, w in zip(bars3, winrs):
        ax3.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                 f"{w:.1f}%", ha="center", va="bottom", fontsize=9)
    ax3.set_ylabel("Win Rate (%)")
    ax3.set_xlabel("CE Multiplier")
    ax3.set_title("Win Rate by CE Multiplier")

    plt.suptitle("Audit D1: Chandelier-Exit Multiplier Sweep\n(4H EMA Cross-UP Entries, M5 Execution)",
                 fontsize=12, fontweight="bold", y=1.02)
    plt.tight_layout()
    chart_path = os.path.join(AUDIT_DIR, "audit_d1_chart.png")
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    print(f"Saved: {chart_path}")

except ImportError:
    print("matplotlib not available — chart skipped")
