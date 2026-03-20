#!/usr/bin/env python3
"""Audit D2: Clock-stop variants on 4H EMA cross-UP entries with CE 2.0×.

Same entry logic as D1:
  - Signal: EMA9 crosses above EMA21 on 4H bars
  - Execution: next M5 bar Open after signal 4H bar completes
  - Initial stop: min(Low) of entry bar + 2 prior; 1R = entry - stop
  - Phase2 gate: first M5 close >= entry + 1R
  - CE trail (post-Phase2): HH(22) - 2.0 × ATR(14)
  - Exits: CE | disaster stop | EOD 15:50

Clock stop addition:
  At bar 6 after entry, if Close < entry + threshold → EXIT immediately.
  Thresholds: [+0.25R, +0.50R, +0.75R, +1.00R] + NO_CS baseline.

Saved/killed analysis (for +0.5R and +1.0R):
  - "saved": clock stop fires AND trade would have hit disaster stop within next 20 bars
  - "killed": clock stop fires AND trade would have been profitable (pnl_r > 0 in baseline)
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
CLOCK_THRESHOLDS = [None, 0.25, 0.50, 0.75, 1.00]  # None = no clock stop
THRESHOLD_LABELS = ["NO_CS", "+0.25R", "+0.50R", "+0.75R", "+1.00R"]
SAVED_KILLED_THRESHOLDS = [0.50, 1.00]
LOOKAHEAD_DISASTER = 20


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


def simulate_trade(bars, atr, entry_idx, clock_threshold_r):
    """Simulate one long trade. Returns trade dict with extra fields for analysis."""
    entry_price = bars[entry_idx]["open"]

    lb_start = max(0, entry_idx - 2)
    lowest_low = min(bars[j]["low"] for j in range(lb_start, entry_idx + 1))
    one_r = entry_price - lowest_low
    if one_r <= 0:
        one_r = entry_price * 0.005

    disaster_stop = entry_price - one_r
    phase2 = False
    chandelier_stop = 0.0
    exit_price = None
    exit_reason = None
    exit_dt = None
    bars_in_trade = 0

    highs = np.array([b["high"] for b in bars])

    for i in range(entry_idx + 1, len(bars)):
        bar = bars[i]
        prev_close = bars[i - 1]["close"]
        bars_in_trade += 1

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

        # Clock stop: at bar CLOCK_BAR, check threshold
        if clock_threshold_r is not None and bars_in_trade == CLOCK_BAR:
            required = entry_price + clock_threshold_r * one_r
            if bar["close"] < required:
                exit_price = bar["close"]
                exit_reason = "clock_stop"
                exit_dt = bar["datetime"]
                break

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
        "disaster_stop": disaster_stop,
        "phase2_reached": phase2,
    }


def would_hit_disaster(bars, entry_idx, disaster_stop, clock_exit_bar_count):
    """After clock stop fires at bar N, check if disaster would trigger in next 20 bars."""
    start = entry_idx + clock_exit_bar_count + 1
    end = min(len(bars), start + LOOKAHEAD_DISASTER)
    for i in range(start, end):
        if bars[i]["low"] <= disaster_stop:
            return True
    return False


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
    cross_date = cross["date"]
    if cross["half"] == "AM":
        target_dt = f"{cross_date} 13:30:00"
        if target_dt in dt_index[ticker]:
            return dt_index[ticker][target_dt]
    else:
        dates = sorted(set(b["date"] for b in bars))
        for d in dates:
            if d > cross_date:
                target_dt = f"{d} 09:30:00"
                if target_dt in dt_index[ticker]:
                    return dt_index[ticker][target_dt]
                break
    return None


# Build all entry points
entries = []  # (ticker, cross, entry_idx)
for ticker in tickers:
    for cross in crosses_by_ticker[ticker]:
        entry_idx = find_entry_idx(ticker, cross)
        if entry_idx is not None and entry_idx >= 3:
            entries.append((ticker, cross, entry_idx))

print(f"Tickers: {len(tickers)} | UP crosses: {len(crosses)} | Valid entries: {len(entries)}")

# ── Run all variants ────────────────────────────────────────────────────────

# results[variant_label] = list of trade dicts
results = {label: [] for label in THRESHOLD_LABELS}

for ticker, cross, entry_idx in entries:
    bars = m5_cache[ticker]
    atr = atr_cache[ticker]

    for thresh, label in zip(CLOCK_THRESHOLDS, THRESHOLD_LABELS):
        trade = simulate_trade(bars, atr, entry_idx, thresh)
        trade["ticker"] = ticker
        trade["cross_date"] = cross["date"]
        trade["cross_half"] = cross["half"]
        trade["variant"] = label
        results[label].append(trade)


def calc_metrics(trades):
    if not trades:
        return {"PF": 0, "AvgR": 0, "WinRate": 0, "N": 0}
    n = len(trades)
    wins = [t for t in trades if t["pnl_r"] > 0]
    losses = [t for t in trades if t["pnl_r"] <= 0]
    gp = sum(t["pnl_r"] for t in wins) if wins else 0
    gl = abs(sum(t["pnl_r"] for t in losses)) if losses else 0.001
    return {
        "PF": round(gp / gl, 2) if gl > 0 else 99.99,
        "AvgR": round(sum(t["pnl_r"] for t in trades) / n, 3),
        "WinRate": round(100 * len(wins) / n, 1),
        "N": n,
    }


# ── Print metrics table ────────────────────────────────────────────────────

lines = []


def p(line=""):
    print(line)
    lines.append(line)


p("=" * 78)
p("AUDIT D2: CLOCK-STOP VARIANTS (CE 2.0×, 4H EMA CROSS-UP ENTRIES)")
p("=" * 78)
p(f"Clock check: bar {CLOCK_BAR} after entry | CE: {CE_MULT}× ATR(14), HH(22)")
p()
p(f"  {'Variant':<10} {'PF':>7} {'AvgR':>8} {'WinRate':>8} {'N':>5}  {'CS_exits':>8}  {'Disaster':>8}  {'CE':>5}  {'EOD':>5}")
p(f"  {'-' * 75}")

for label in THRESHOLD_LABELS:
    trades = results[label]
    m = calc_metrics(trades)
    reasons = defaultdict(int)
    for t in trades:
        reasons[t["exit_reason"]] += 1
    cs = reasons.get("clock_stop", 0)
    ds = reasons.get("disaster_stop", 0)
    ce = reasons.get("chandelier_stop", 0)
    eod = reasons.get("eod_1550", 0)
    p(f"  {label:<10} {m['PF']:>7.2f} {m['AvgR']:>8.3f} {m['WinRate']:>7.1f}% {m['N']:>5}  {cs:>8}  {ds:>8}  {ce:>5}  {eod:>5}")

p()

# ── Saved vs Killed analysis ───────────────────────────────────────────────

p("SAVED vs KILLED ANALYSIS")
p("  'saved'  = clock stop fired AND would have hit disaster within next 20 bars")
p("  'killed' = clock stop fired AND baseline (NO_CS) trade was profitable")
p()

# Build baseline PnL lookup: (ticker, cross_date) → baseline pnl_r
baseline_pnl = {}
for t in results["NO_CS"]:
    key = (t["ticker"], t["cross_date"])
    baseline_pnl[key] = t["pnl_r"]

for thresh_r in SAVED_KILLED_THRESHOLDS:
    label = f"+{thresh_r:.2f}R"
    variant_label = f"+{thresh_r:.2f}R".replace(".00", ".00").replace("+0.", "+0.")
    # Find the matching THRESHOLD_LABELS entry
    for tl in THRESHOLD_LABELS:
        if tl == f"+{thresh_r:.2f}R":
            variant_label = tl
            break

    trades = results[variant_label]
    cs_trades = [t for t in trades if t["exit_reason"] == "clock_stop"]

    saved = 0
    killed = 0
    neutral = 0

    for t in cs_trades:
        key = (t["ticker"], t["cross_date"])
        # Check if would have hit disaster
        ticker = t["ticker"]
        entry_idx = dt_index[ticker].get(t["entry_dt"])
        if entry_idx is None:
            continue

        was_saved = would_hit_disaster(
            m5_cache[ticker], entry_idx, t["disaster_stop"], CLOCK_BAR
        )
        base_pnl = baseline_pnl.get(key, 0)
        was_killed = base_pnl > 0

        if was_saved:
            saved += 1
        elif was_killed:
            killed += 1
        else:
            neutral += 1

    total_cs = len(cs_trades)
    ratio_str = f"{saved}:{killed}" if killed > 0 else f"{saved}:0"
    ratio_val = saved / killed if killed > 0 else float("inf")

    p(f"  {variant_label}:")
    p(f"    Clock-stop exits: {total_cs}")
    p(f"    Saved (avoided disaster):    {saved:>4}  ({100*saved/total_cs:.1f}%)" if total_cs else "    N/A")
    p(f"    Killed (would have profited): {killed:>3}  ({100*killed/total_cs:.1f}%)" if total_cs else "    N/A")
    p(f"    Neutral (neither):           {neutral:>4}  ({100*neutral/total_cs:.1f}%)" if total_cs else "    N/A")
    p(f"    Saved:Killed ratio:          {ratio_str}  ({ratio_val:.1f}:1)")
    p()

# Claim check
p("CLAIM CHECK:")
p("  Prior claim: +0.5R clock stop saved:killed = 14:1")
# Find +0.50R stats
cs_05 = [t for t in results["+0.50R"] if t["exit_reason"] == "clock_stop"]
saved_05 = 0
killed_05 = 0
for t in cs_05:
    key = (t["ticker"], t["cross_date"])
    entry_idx = dt_index[t["ticker"]].get(t["entry_dt"])
    if entry_idx is None:
        continue
    if would_hit_disaster(m5_cache[t["ticker"]], entry_idx, t["disaster_stop"], CLOCK_BAR):
        saved_05 += 1
    elif baseline_pnl.get(key, 0) > 0:
        killed_05 += 1
actual_ratio = saved_05 / killed_05 if killed_05 > 0 else float("inf")
p(f"  Actual: {saved_05}:{killed_05} = {actual_ratio:.1f}:1")
match = "YES" if actual_ratio >= 10 else ("~CLOSE" if actual_ratio >= 7 else "NO")
p(f"  Match: {match}")
p()

# ── Per-ticker comparison: NO_CS vs best clock-stop ─────────────────────────

# Find best clock-stop variant by PF
cs_labels = [l for l in THRESHOLD_LABELS if l != "NO_CS"]
best_cs = max(cs_labels, key=lambda l: calc_metrics(results[l])["PF"])
p(f"PER-TICKER: NO_CS vs {best_cs}")
p(f"  {'Ticker':<8} {'NO_CS_PF':>9} {'NO_CS_AvgR':>11} {best_cs+'_PF':>10} {best_cs+'_AvgR':>12} {'N':>5}")
p(f"  {'-' * 60}")

for ticker in tickers:
    base = [t for t in results["NO_CS"] if t["ticker"] == ticker]
    best = [t for t in results[best_cs] if t["ticker"] == ticker]
    mb = calc_metrics(base)
    mc = calc_metrics(best)
    if mb["N"] > 0:
        p(f"  {ticker:<8} {mb['PF']:>9.2f} {mb['AvgR']:>11.3f} {mc['PF']:>10.2f} {mc['AvgR']:>12.3f} {mb['N']:>5}")

# ── Save CSV ────────────────────────────────────────────────────────────────
csv_path = os.path.join(AUDIT_DIR, "audit_d2_clock_stop.csv")
detail_rows = []
for label in THRESHOLD_LABELS:
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
            "pnl_r": f"{t['pnl_r']:.3f}",
        })

with open(csv_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(detail_rows[0].keys()))
    writer.writeheader()
    writer.writerows(detail_rows)
p(f"Saved: {csv_path}")

# Save text report
txt_path = os.path.join(AUDIT_DIR, "audit_d2_saved_killed.txt")
with open(txt_path, "w") as f:
    f.write("\n".join(lines) + "\n")
p(f"Saved: {txt_path}")

# ── Chart ───────────────────────────────────────────────────────────────────
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(16, 5.5))

    # Metrics per variant
    pfs, avgrs, winrs = [], [], []
    for label in THRESHOLD_LABELS:
        m = calc_metrics(results[label])
        pfs.append(m["PF"])
        avgrs.append(m["AvgR"])
        winrs.append(m["WinRate"])

    x = range(len(THRESHOLD_LABELS))
    colors = ["#607D8B"] + ["#2196F3", "#4CAF50", "#FF9800", "#F44336"]

    # Panel 1: PF
    ax = axes[0]
    bars_pf = ax.bar(x, pfs, color=colors, alpha=0.85, edgecolor="white")
    ax.axhline(1.0, color="gray", ls="--", alpha=0.5)
    for b, pf in zip(bars_pf, pfs):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.01,
                f"{pf:.2f}", ha="center", va="bottom", fontsize=9)
    ax.set_xticks(list(x))
    ax.set_xticklabels(THRESHOLD_LABELS, fontsize=8, rotation=15)
    ax.set_ylabel("Profit Factor")
    ax.set_title("PF by Clock-Stop Threshold")

    # Panel 2: AvgR
    ax2 = axes[1]
    bars_ar = ax2.bar(x, avgrs, color=colors, alpha=0.85, edgecolor="white")
    ax2.axhline(0, color="gray", ls="--", alpha=0.5)
    for b, ar in zip(bars_ar, avgrs):
        ax2.text(b.get_x() + b.get_width() / 2, ar + 0.005 if ar >= 0 else ar - 0.02,
                 f"{ar:.3f}R", ha="center", va="bottom" if ar >= 0 else "top", fontsize=9)
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(THRESHOLD_LABELS, fontsize=8, rotation=15)
    ax2.set_ylabel("Average R")
    ax2.set_title("AvgR by Clock-Stop Threshold")

    # Panel 3: Saved vs Killed
    ax3 = axes[2]
    sk_labels = []
    sk_saved = []
    sk_killed = []
    sk_neutral = []
    for thresh_r in SAVED_KILLED_THRESHOLDS:
        lbl = f"+{thresh_r:.2f}R"
        for tl in THRESHOLD_LABELS:
            if tl == lbl:
                lbl = tl
                break
        cs_t = [t for t in results[lbl] if t["exit_reason"] == "clock_stop"]
        s, k, n2 = 0, 0, 0
        for t in cs_t:
            key = (t["ticker"], t["cross_date"])
            eidx = dt_index[t["ticker"]].get(t["entry_dt"])
            if eidx is None:
                continue
            if would_hit_disaster(m5_cache[t["ticker"]], eidx, t["disaster_stop"], CLOCK_BAR):
                s += 1
            elif baseline_pnl.get(key, 0) > 0:
                k += 1
            else:
                n2 += 1
        sk_labels.append(lbl)
        sk_saved.append(s)
        sk_killed.append(k)
        sk_neutral.append(n2)

    x3 = range(len(sk_labels))
    w = 0.25
    ax3.bar([i - w for i in x3], sk_saved, w, label="Saved", color="#4CAF50", alpha=0.85)
    ax3.bar([i for i in x3], sk_killed, w, label="Killed", color="#F44336", alpha=0.85)
    ax3.bar([i + w for i in x3], sk_neutral, w, label="Neutral", color="#9E9E9E", alpha=0.85)
    for i, (s, k) in enumerate(zip(sk_saved, sk_killed)):
        ratio = s / k if k > 0 else float("inf")
        ax3.text(i, max(s, k, sk_neutral[i]) + 1, f"{s}:{k}\n({ratio:.1f}:1)",
                 ha="center", fontsize=9, fontweight="bold")
    ax3.set_xticks(list(x3))
    ax3.set_xticklabels(sk_labels, fontsize=9)
    ax3.set_ylabel("Count")
    ax3.set_title("Saved vs Killed by Clock-Stop")
    ax3.legend(fontsize=8)

    plt.suptitle("Audit D2: Clock-Stop Variants (CE 2.0×, 4H EMA Cross-UP)",
                 fontsize=12, fontweight="bold", y=1.02)
    plt.tight_layout()
    chart_path = os.path.join(AUDIT_DIR, "audit_d2_chart.png")
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    p(f"Saved: {chart_path}")

except ImportError:
    print("matplotlib not available — chart skipped")
