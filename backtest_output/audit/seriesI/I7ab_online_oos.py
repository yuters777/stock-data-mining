"""
Series I7a + I7b: Online Trigger Rewrite + Early-Low OOS Validation.

I7a: Replaces ex-post DZ_low entry with two online (real-time) variants:
  Online-A: Track running low, entry = first green close after each new low
            (only LAST trigger counts if low keeps updating). Entry-time cutoff sweep.
  Online-B: Simple "first green close after 12:00 ET". Entry-time cutoff sweep.

I7b: Split-sample validation of the early-low edge with the best online rule.
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ── paths ──
ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "Fetched_Data"
OUT_DIR = Path(__file__).resolve().parent
I4_DATA = OUT_DIR / "I4_depth_zscore_data.csv"

EQUITY_TICKERS = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU", "C",
    "COIN", "COST", "GOOGL", "GS", "INTC", "JPM", "MARA", "META", "MSFT",
    "MSTR", "MU", "NVDA", "PLTR", "SMCI", "SPY", "TSLA", "TSM", "V",
]

# IST zone boundaries
DZ_START_IST = 19 * 60       # 12:00 ET
DZ_END_IST = 20 * 60 + 30    # 13:30 ET
EXIT_IST = 22 * 60 + 30      # 15:30 ET


def ist_minutes(dt):
    return dt.hour * 60 + dt.minute


def ist_to_et(ist_min):
    return ist_min - 7 * 60


def et_to_ist(et_min):
    return et_min + 7 * 60


def load_all_m5():
    """Load M5 regular-session data keyed by (ticker, date)."""
    print("Loading M5 data...")
    cache = {}
    for ticker in EQUITY_TICKERS:
        path = DATA_DIR / f"{ticker}_data.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, parse_dates=["Datetime"])
        df = df.sort_values("Datetime").reset_index(drop=True)
        mins = df["Datetime"].apply(ist_minutes)
        mask = (mins >= 16 * 60 + 35) & (mins <= 22 * 60 + 55)
        df = df[mask].copy()
        df["trading_day"] = df["Datetime"].dt.date
        df["ist_min"] = df["Datetime"].apply(ist_minutes)
        for day, day_df in df.groupby("trading_day"):
            cache[(ticker, day)] = day_df.reset_index(drop=True)
    print(f"  Loaded {len(cache):,} ticker-days")
    return cache


def get_exit_price(day_df):
    """Close at 15:30 ET = 22:30 IST or nearest prior bar."""
    candidates = day_df[day_df["ist_min"] <= EXIT_IST]
    if candidates.empty:
        return None
    return candidates.iloc[-1]["Close"]


# ═══════════════════════════════════════════════════════════
# I7a: Online Trigger Variants
# ═══════════════════════════════════════════════════════════

def online_a_entry(day_df, cutoff_ist):
    """Online-A: Track running low through DZ, entry = first green close after
    each new running low. Only the LAST triggered entry counts (if low updates
    after a trigger, we re-trigger on next green close). Entry must be before cutoff.

    In practice: we're already in position from the first trigger, so if the low
    updates later, we DON'T exit and re-enter. We stay in from the first trigger.

    BUT the question is: does the FIRST trigger or the LAST trigger produce the
    actual entry price? Since we enter on first trigger and HOLD, the entry is
    the first trigger price. Let's implement both:
    - "first_trigger": enter on first green close after first running-low dip
    - "last_trigger": enter on last green close before cutoff (after final running low before cutoff)
    """
    dz_bars = day_df[(day_df["ist_min"] >= DZ_START_IST) & (day_df["ist_min"] < DZ_END_IST)]
    if dz_bars.empty:
        return None, None, None, None

    running_low = float("inf")
    last_low_idx = None
    first_trigger_entry = None
    first_trigger_ist = None

    # Walk through DZ bars chronologically
    for idx, bar in dz_bars.iterrows():
        if bar["ist_min"] >= cutoff_ist:
            break

        # Update running low
        if bar["Low"] < running_low:
            running_low = bar["Low"]
            last_low_idx = idx

    # After scanning up to cutoff: find first green close after last_low_idx within cutoff
    if last_low_idx is None:
        return None, None, None, None

    # Find first green close after the running low, within cutoff
    after_low = day_df.loc[last_low_idx + 1:]
    for idx, bar in after_low.iterrows():
        if bar["ist_min"] >= cutoff_ist:
            break
        if bar["Close"] > bar["Open"]:
            return bar["Close"], bar["ist_min"], running_low, last_low_idx

    return None, None, running_low, last_low_idx


def online_a_realtime(day_df, cutoff_ist):
    """Online-A (true real-time): Enter on FIRST green close after ANY running low update.
    Once in position, HOLD to exit. Don't re-enter.
    """
    dz_bars = day_df[(day_df["ist_min"] >= DZ_START_IST) & (day_df["ist_min"] < cutoff_ist)]
    if dz_bars.empty:
        return None, None

    running_low = float("inf")
    new_low_seen = False

    for idx, bar in dz_bars.iterrows():
        if bar["Low"] < running_low:
            running_low = bar["Low"]
            new_low_seen = True
            continue

        # First green close after a running low update
        if new_low_seen and bar["Close"] > bar["Open"]:
            return bar["Close"], bar["ist_min"]

    return None, None


def online_b_entry(day_df, cutoff_ist):
    """Online-B (simple): First green close after 12:00 ET, before cutoff.
    No reference to DZ low at all."""
    dz_bars = day_df[(day_df["ist_min"] >= DZ_START_IST) & (day_df["ist_min"] < cutoff_ist)]
    for idx, bar in dz_bars.iterrows():
        if bar["Close"] > bar["Open"]:
            return bar["Close"], bar["ist_min"]
    return None, None


def process_online(i4_df, m5_cache, cutoff_et_list):
    """Process all events with online entries for multiple cutoffs."""
    print("Processing online entries...")
    # Pre-compute: for each (ticker, day), store bars + exit price
    all_results = []
    n = len(i4_df)

    for row_i, (_, event) in enumerate(i4_df.iterrows()):
        if row_i % 1000 == 0 and row_i > 0:
            print(f"  {row_i}/{n}...")

        ticker = event["ticker"]
        day = event["trading_day"]
        key = (ticker, day)
        if key not in m5_cache:
            continue

        day_df = m5_cache[key]
        exit_price = get_exit_price(day_df)
        if exit_price is None:
            continue

        base = {
            "ticker": ticker, "trading_day": day,
            "depth_z": event["depth_z"], "zscore_bucket": event["zscore_bucket"],
            "compression_pct": event["compression_pct"],
            "compression_bucket": event["compression_bucket"],
            "dz_low": event["dz_low"], "z2_high": event["z2_high"],
            "exit_price": exit_price,
        }

        for cutoff_et in cutoff_et_list:
            cutoff_ist = et_to_ist(cutoff_et)
            tag = f"{cutoff_et // 60}:{cutoff_et % 60:02d}"

            # Online-A (real-time: first trigger and hold)
            a_entry, a_ist = online_a_realtime(day_df, cutoff_ist)
            a_pl = (exit_price - a_entry) / a_entry * 100 if a_entry else None
            a_et = ist_to_et(a_ist) if a_ist else None

            # Online-B (simple first green)
            b_entry, b_ist = online_b_entry(day_df, cutoff_ist)
            b_pl = (exit_price - b_entry) / b_entry * 100 if b_entry else None
            b_et = ist_to_et(b_ist) if b_ist else None

            all_results.append({
                **base,
                "cutoff_et": cutoff_et, "cutoff_tag": tag,
                "online_a_entry": a_entry, "online_a_ist": a_ist,
                "online_a_pl": a_pl, "online_a_et_min": a_et,
                "online_b_entry": b_entry, "online_b_ist": b_ist,
                "online_b_pl": b_pl, "online_b_et_min": b_et,
            })

    return pd.DataFrame(all_results)


def print_cutoff_sweep(df, pl_col, label):
    """Print P&L sweep across cutoffs."""
    print(f"\n--- {label} ---")
    print(f"{'Cutoff':>8s}  {'Avg PL':>9s}  {'Med PL':>9s}  {'WR':>7s}  {'N':>6s}  {'Trig%':>7s}")
    print("-" * 55)
    cutoffs = sorted(df["cutoff_et"].unique())
    rows = []
    for c in cutoffs:
        sub = df[df["cutoff_et"] == c].dropna(subset=[pl_col])
        n_total = len(df[df["cutoff_et"] == c])
        if sub.empty:
            continue
        avg = sub[pl_col].mean()
        med = sub[pl_col].median()
        wr = (sub[pl_col] > 0).mean() * 100
        trig = len(sub) / n_total * 100 if n_total > 0 else 0
        tag = f"{c // 60}:{c % 60:02d}"
        print(f"{tag:>8s}  {avg:>+8.4f}%  {med:>+8.4f}%  {wr:>6.1f}%  {len(sub):>6d}  {trig:>6.1f}%")
        rows.append({"cutoff": c, "tag": tag, "avg_pl": avg, "med_pl": med,
                      "wr": wr, "n": len(sub), "trig_pct": trig})
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════
# I7b: Split-Sample
# ═══════════════════════════════════════════════════════════

def run_i7b(df, best_cutoff, pl_col, label):
    """Split-sample validation for the best online cutoff."""
    print(f"\n{'='*70}")
    print(f"I7b: Split-Sample Validation ({label}, cutoff {best_cutoff//60}:{best_cutoff%60:02d} ET)")
    print("=" * 70)

    sub = df[df["cutoff_et"] == best_cutoff].dropna(subset=[pl_col]).copy()
    all_days = sorted(sub["trading_day"].unique())
    mid = len(all_days) // 2
    first_days = set(all_days[:mid])

    sub["half"] = sub["trading_day"].apply(lambda d: "First" if d in first_days else "Second")

    print(f"  First half:  {all_days[0]} to {all_days[mid-1]} ({mid} days)")
    print(f"  Second half: {all_days[mid]} to {all_days[-1]} ({len(all_days)-mid} days)")

    print(f"\n{'Half':>8s}  {'Avg PL':>9s}  {'Med PL':>9s}  {'WR':>7s}  {'N':>6s}")
    print("-" * 45)
    for h in ["First", "Second"]:
        s = sub[sub["half"] == h]
        print(f"{h:>8s}  {s[pl_col].mean():>+8.4f}%  {s[pl_col].median():>+8.4f}%  "
              f"{(s[pl_col]>0).mean()*100:>6.1f}%  {len(s):>6d}")

    # Time-of-entry bucket stability
    sub["entry_et"] = sub[pl_col.replace("_pl", "_et_min")]
    # Use entry time buckets similar to I6d
    def time_bucket(et_min):
        if pd.isna(et_min):
            return "unknown"
        if et_min < 12 * 60 + 30:
            return "Early"
        elif et_min < 13 * 60:
            return "Mid"
        else:
            return "Late"

    if pl_col.replace("_pl", "_et_min") in sub.columns:
        et_col = pl_col.replace("_pl", "_et_min")
        sub["time_bucket"] = sub[et_col].apply(time_bucket)

        print(f"\n  Time-of-entry × Half:")
        print(f"  {'Half':>8s}  {'Early PL':>10s}  {'Mid PL':>10s}  {'Late PL':>10s}")
        for h in ["First", "Second"]:
            vals = []
            for tb in ["Early", "Mid", "Late"]:
                s = sub[(sub["half"] == h) & (sub["time_bucket"] == tb)]
                vals.append(f"{s[pl_col].mean():+.4f}%" if len(s) > 10 else f"N={len(s)}")
            print(f"  {h:>8s}  {vals[0]:>10s}  {vals[1]:>10s}  {vals[2]:>10s}")

    # Depth × Half
    sub["depth_binary"] = np.where(sub["depth_z"] >= 1.0, "deep", "shallow")
    print(f"\n  Depth × Half:")
    print(f"  {'Half':>8s}  {'Shallow PL':>12s}  {'Deep PL':>10s}  {'Delta':>8s}")
    for h in ["First", "Second"]:
        sh = sub[(sub["half"] == h) & (sub["depth_binary"] == "shallow")]
        dp = sub[(sub["half"] == h) & (sub["depth_binary"] == "deep")]
        sh_pl = sh[pl_col].mean() if len(sh) > 0 else float("nan")
        dp_pl = dp[pl_col].mean() if len(dp) > 0 else float("nan")
        delta = dp_pl - sh_pl
        print(f"  {h:>8s}  {sh_pl:>+11.4f}%  {dp_pl:>+9.4f}%  {delta:>+7.4f}%")

    return sub


# ═══════════════════════════════════════════════════════════
# PLOTS
# ═══════════════════════════════════════════════════════════

def make_plots(sweep_a, sweep_b, split_df, pl_col):
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # 1. Cutoff sweep: Online-A vs Online-B avg P&L
    ax = axes[0, 0]
    if not sweep_a.empty:
        ax.plot(sweep_a["cutoff"], sweep_a["avg_pl"], "o-", color="#4CAF50", label="Online-A (running low)", linewidth=2)
    if not sweep_b.empty:
        ax.plot(sweep_b["cutoff"], sweep_b["avg_pl"], "s-", color="#2196F3", label="Online-B (simple green)", linewidth=2)
    ax.axhline(0.312, color="gray", linestyle="--", alpha=0.7, label="I6a V1 baseline (+0.312%)")
    ax.axhline(0, color="black", linewidth=0.5)
    ticks = sorted(set(list(sweep_a["cutoff"]) + list(sweep_b["cutoff"])))
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{t//60}:{t%60:02d}" for t in ticks], rotation=45, fontsize=8)
    ax.set_xlabel("Entry Cutoff (ET)")
    ax.set_ylabel("Avg P&L (%)")
    ax.set_title("I7a: Online Entry Cutoff Sweep")
    ax.legend(fontsize=8)

    # 2. Cutoff sweep: Win Rate
    ax = axes[0, 1]
    if not sweep_a.empty:
        ax.plot(sweep_a["cutoff"], sweep_a["wr"], "o-", color="#4CAF50", label="Online-A", linewidth=2)
    if not sweep_b.empty:
        ax.plot(sweep_b["cutoff"], sweep_b["wr"], "s-", color="#2196F3", label="Online-B", linewidth=2)
    ax.axhline(63.1, color="gray", linestyle="--", alpha=0.7, label="I6a V1 WR (63.1%)")
    ax.axhline(50, color="black", linewidth=0.5, linestyle=":")
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{t//60}:{t%60:02d}" for t in ticks], rotation=45, fontsize=8)
    ax.set_xlabel("Entry Cutoff (ET)")
    ax.set_ylabel("Win Rate (%)")
    ax.set_title("I7a: Win Rate by Cutoff")
    ax.legend(fontsize=8)

    # 3. Cutoff sweep: N trades (trigger rate)
    ax = axes[1, 0]
    if not sweep_a.empty:
        ax.plot(sweep_a["cutoff"], sweep_a["n"], "o-", color="#4CAF50", label="Online-A", linewidth=2)
    if not sweep_b.empty:
        ax.plot(sweep_b["cutoff"], sweep_b["n"], "s-", color="#2196F3", label="Online-B", linewidth=2)
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{t//60}:{t%60:02d}" for t in ticks], rotation=45, fontsize=8)
    ax.set_xlabel("Entry Cutoff (ET)")
    ax.set_ylabel("N Trades")
    ax.set_title("I7a: Trade Count by Cutoff")
    ax.legend(fontsize=8)

    # 4. I7b: Split-sample bar chart
    ax = axes[1, 1]
    if split_df is not None and not split_df.empty:
        halves = ["First", "Second"]
        x = np.arange(2)
        vals = []
        for h in halves:
            s = split_df[split_df["half"] == h]
            vals.append(s[pl_col].mean() if len(s) > 0 else 0)
        colors = ["#4CAF50", "#FF9800"]
        bars = ax.bar(x, vals, color=colors, alpha=0.85)
        ax.set_xticks(x)
        ax.set_xticklabels(halves)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.005,
                    f"{v:+.3f}%", ha="center", fontsize=10)
        ax.set_ylabel("Avg P&L (%)")
        ax.set_title("I7b: Split-Sample — Best Online Rule")
        ax.axhline(0, color="black", linewidth=0.5)

    plt.suptitle("I7a + I7b: Online Trigger & OOS Validation", fontsize=14)
    plt.tight_layout()
    plt.savefig(OUT_DIR / "I7ab_online_oos.png", dpi=150)
    plt.close()
    print("\nSaved: I7ab_online_oos.png")


def main():
    # Load I4 data (DZ compression events with z-scores)
    i4 = pd.read_csv(I4_DATA)
    i4["trading_day"] = pd.to_datetime(i4["trading_day"]).dt.date
    print(f"Loaded {len(i4)} events from I4")

    # Load M5
    m5_cache = load_all_m5()

    # ═══════════════════════════════════════════════════════
    # I7a: Cutoff sweep
    # ═══════════════════════════════════════════════════════
    cutoff_list = [
        12 * 60 + 30,   # 12:30
        12 * 60 + 45,   # 12:45
        12 * 60 + 55,   # 12:55
        13 * 60,         # 13:00
        13 * 60 + 5,     # 13:05
        13 * 60 + 10,    # 13:10
        13 * 60 + 15,    # 13:15
        13 * 60 + 30,    # 13:30 (no filter)
    ]

    df = process_online(i4, m5_cache, cutoff_list)
    df.to_csv(OUT_DIR / "I7a_online_data.csv", index=False)
    print(f"Generated {len(df)} rows ({len(df) // len(cutoff_list)} events × {len(cutoff_list)} cutoffs)")

    print(f"\n{'='*70}")
    print("I7a: Online Trigger Cutoff Sweep")
    print("=" * 70)

    sweep_a = print_cutoff_sweep(df, "online_a_pl", "Online-A: Running Low + First Green")
    sweep_b = print_cutoff_sweep(df, "online_b_pl", "Online-B: Simple First Green After Noon")

    # Find optimal cutoffs (maximize avg_pl × sqrt(n) = Sharpe proxy)
    for sweep, label in [(sweep_a, "Online-A"), (sweep_b, "Online-B")]:
        if sweep.empty:
            continue
        sweep["score"] = sweep["avg_pl"] * np.sqrt(sweep["n"])
        best = sweep.loc[sweep["score"].idxmax()]
        print(f"\n  {label} optimal: cutoff={best['tag']}, "
              f"avg P&L={best['avg_pl']:+.4f}%, WR={best['wr']:.1f}%, N={int(best['n'])}")

    # ═══════════════════════════════════════════════════════
    # I7b: Split-sample with best online rule
    # ═══════════════════════════════════════════════════════

    # Determine best variant and cutoff
    best_a = sweep_a.loc[sweep_a["avg_pl"].idxmax()] if not sweep_a.empty else None
    best_b = sweep_b.loc[sweep_b["avg_pl"].idxmax()] if not sweep_b.empty else None

    # Pick higher avg_pl
    if best_a is not None and best_b is not None:
        if best_a["avg_pl"] >= best_b["avg_pl"]:
            best_cutoff = int(best_a["cutoff"])
            best_pl_col = "online_a_pl"
            best_label = "Online-A"
        else:
            best_cutoff = int(best_b["cutoff"])
            best_pl_col = "online_b_pl"
            best_label = "Online-B"
    elif best_a is not None:
        best_cutoff = int(best_a["cutoff"])
        best_pl_col = "online_a_pl"
        best_label = "Online-A"
    else:
        best_cutoff = int(best_b["cutoff"])
        best_pl_col = "online_b_pl"
        best_label = "Online-B"

    print(f"\n  Best overall: {best_label} @ {best_cutoff//60}:{best_cutoff%60:02d} ET")

    # Also run I7b for the 13:30 (no filter) cutoff to compare
    split_df = run_i7b(df, best_cutoff, best_pl_col, best_label)

    # I7b for the no-filter 13:30 cutoff
    print(f"\n  --- Comparison: 13:30 (no time filter) ---")
    run_i7b(df, 13 * 60 + 30, best_pl_col, f"{best_label} (no filter)")

    # Plots
    make_plots(sweep_a, sweep_b, split_df, best_pl_col)


if __name__ == "__main__":
    main()
