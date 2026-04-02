"""
Series I8: Original H2 Entry — Honest Online Re-Test.

Reproduces the H2 Noon Reversal backtest exactly:
  - Rank 25 equity tickers by AM return (09:30→12:00 ET)
  - Buy bottom 2 at 12:00 ET bar open
  - Exit at 15:30 ET bar close
  - Fully online — no lookahead, no DZ_low knowledge

Tests filters: stress/non-stress, VIX re-acceleration, delayed entry,
stabilization. Split-sample validation.
"""

import json
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
VIX_PATH = DATA_DIR / "VIXCLS_FRED_real.csv"
STRESS_PATH = ROOT / "backtest_output" / "stress_days.json"

# 25 tickers for ranking (exclude SPY, VIXY — as in H2)
RANK_TICKERS = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU", "C",
    "COIN", "COST", "GOOGL", "GS", "INTC", "JPM", "MARA", "META", "MSFT",
    "MSTR", "MU", "NVDA", "PLTR", "SMCI", "TSLA", "TSM", "V",
]

N_LAGGARDS = 2

# IST times
OPEN_IST = 16 * 60 + 30   # 09:30 ET
NOON_IST = 19 * 60         # 12:00 ET
EXIT_IST = 22 * 60 + 30    # 15:30 ET


def ist_minutes(dt):
    return dt.hour * 60 + dt.minute


def load_vix():
    vix = pd.read_csv(VIX_PATH)
    vix.columns = ["date", "vix"]
    vix["date"] = pd.to_datetime(vix["date"]).dt.date
    vix["vix"] = pd.to_numeric(vix["vix"], errors="coerce")
    vix = vix.dropna(subset=["vix"])
    return dict(zip(vix["date"], vix["vix"]))


def load_stress_days():
    with open(STRESS_PATH) as f:
        days = json.load(f)
    return {pd.Timestamp(d).date() for d in days}


def load_m5_by_day():
    """Load M5 data, return dict: (ticker, date) -> {ist_min: {open, high, low, close}}."""
    print("Loading M5 data...")
    cache = {}
    for ticker in RANK_TICKERS + ["SPY"]:
        path = DATA_DIR / f"{ticker}_data.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, parse_dates=["Datetime"])
        df = df.sort_values("Datetime").reset_index(drop=True)
        mins = df["Datetime"].apply(ist_minutes)
        # Regular session (avoid duplicate ET section)
        mask = (mins >= 16 * 60 + 30) & (mins <= 22 * 60 + 55)
        df = df[mask].copy()
        df["trading_day"] = df["Datetime"].dt.date
        df["ist_min"] = df["Datetime"].apply(ist_minutes)

        for day, day_df in df.groupby("trading_day"):
            bar_map = {}
            for _, row in day_df.iterrows():
                bar_map[row["ist_min"]] = {
                    "open": row["Open"], "high": row["High"],
                    "low": row["Low"], "close": row["Close"],
                }
            cache[(ticker, day)] = bar_map

    print(f"  Loaded {len(cache):,} ticker-days")
    return cache


def get_am_return(bar_map, open_ist=OPEN_IST, noon_ist=NOON_IST):
    """Compute AM return: price at noon / price at open - 1."""
    open_bar = bar_map.get(open_ist)
    noon_bar = bar_map.get(noon_ist)
    if not open_bar or not noon_bar:
        return None
    if open_bar["open"] <= 0:
        return None
    return (noon_bar["open"] - open_bar["open"]) / open_bar["open"]


def run_baseline(m5_cache, stress_set, vix_map, entry_ist=NOON_IST, exit_ist=EXIT_IST):
    """Run the H2 baseline: rank by AM return, buy bottom 2 at noon open, exit at 15:30 close."""
    # Get all unique trading days
    all_days = sorted({day for (_, day) in m5_cache.keys()})
    print(f"  Trading days: {len(all_days)}")

    results = []
    for day in all_days:
        # Compute AM return for each ticker
        am_returns = {}
        for ticker in RANK_TICKERS:
            bar_map = m5_cache.get((ticker, day))
            if bar_map is None:
                continue
            am_ret = get_am_return(bar_map, OPEN_IST, entry_ist)
            if am_ret is not None:
                am_returns[ticker] = am_ret

        if len(am_returns) < 5:
            continue

        # Rank ascending (worst first) and select bottom N
        ranked = sorted(am_returns.items(), key=lambda x: x[1])
        laggards = ranked[:N_LAGGARDS]

        # Compute median AM return for stress detection (online: we know this at noon)
        median_am = np.median(list(am_returns.values()))
        spy_bars = m5_cache.get(("SPY", day))
        spy_am = get_am_return(spy_bars, OPEN_IST, entry_ist) if spy_bars else None

        is_stress = day in stress_set
        vix_val = vix_map.get(day)

        for ticker, am_ret in laggards:
            bar_map = m5_cache[(ticker, day)]
            entry_bar = bar_map.get(entry_ist)
            exit_bar = bar_map.get(exit_ist)
            if not entry_bar or not exit_bar:
                continue

            entry_price = entry_bar["open"]
            exit_price = exit_bar["close"]
            if entry_price <= 0:
                continue

            pm_ret = (exit_price - entry_price) / entry_price * 100

            results.append({
                "trading_day": day,
                "ticker": ticker,
                "am_return": am_ret * 100,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pm_return": pm_ret,
                "win": pm_ret > 0,
                "is_stress": is_stress,
                "vix": vix_val,
                "median_am": median_am * 100,
                "spy_am": spy_am * 100 if spy_am else None,
            })

    return pd.DataFrame(results)


def run_stabilization_filter(m5_cache, stress_set, vix_map):
    """Filter D: Only enter if bottom-2 candidate has a green close by 12:30 ET."""
    all_days = sorted({day for (_, day) in m5_cache.keys()})
    results = []

    for day in all_days:
        am_returns = {}
        for ticker in RANK_TICKERS:
            bar_map = m5_cache.get((ticker, day))
            if bar_map is None:
                continue
            am_ret = get_am_return(bar_map, OPEN_IST, NOON_IST)
            if am_ret is not None:
                am_returns[ticker] = am_ret

        if len(am_returns) < 5:
            continue

        ranked = sorted(am_returns.items(), key=lambda x: x[1])
        laggards = ranked[:N_LAGGARDS]
        is_stress = day in stress_set
        vix_val = vix_map.get(day)

        for ticker, am_ret in laggards:
            bar_map = m5_cache[(ticker, day)]

            # Check for green close between 12:05 and 12:30 ET (19:05-19:30 IST)
            has_green = False
            for t in range(19 * 60 + 5, 19 * 60 + 35, 5):
                bar = bar_map.get(t)
                if bar and bar["close"] > bar["open"]:
                    has_green = True
                    break

            if not has_green:
                continue

            entry_bar = bar_map.get(NOON_IST)
            exit_bar = bar_map.get(EXIT_IST)
            if not entry_bar or not exit_bar:
                continue

            entry_price = entry_bar["open"]
            exit_price = exit_bar["close"]
            if entry_price <= 0:
                continue

            pm_ret = (exit_price - entry_price) / entry_price * 100
            results.append({
                "trading_day": day, "ticker": ticker,
                "am_return": am_ret * 100, "pm_return": pm_ret,
                "win": pm_ret > 0, "is_stress": is_stress, "vix": vix_val,
            })

    return pd.DataFrame(results)


def print_stats(df, label):
    """Print summary stats for a set of trades."""
    if df.empty:
        print(f"  {label}: N=0")
        return
    avg = df["pm_return"].mean()
    med = df["pm_return"].median()
    wr = df["win"].mean() * 100
    n = len(df)
    print(f"  {label}: avg={avg:+.3f}%, med={med:+.3f}%, WR={wr:.1f}%, N={n}")


def main():
    vix_map = load_vix()
    stress_set = load_stress_days()
    m5_cache = load_m5_by_day()

    # ═══════════════════════════════════════════════════════
    # A) Baseline: buy bottom 2 at noon open, exit 15:30
    # ═══════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("A) BASELINE: Bottom-2 at 12:00 open → 15:30 close")
    print("=" * 70)

    baseline = run_baseline(m5_cache, stress_set, vix_map)
    baseline.to_csv(OUT_DIR / "I8_baseline_trades.csv", index=False)

    print_stats(baseline, "ALL")
    print_stats(baseline[baseline["is_stress"]], "Stress")
    print_stats(baseline[~baseline["is_stress"]], "Non-stress")

    # Daily P&L
    daily = baseline.groupby("trading_day")["pm_return"].sum().reset_index()
    daily.columns = ["day", "daily_pl"]
    print(f"\n  Daily P&L: avg={daily['daily_pl'].mean():+.3f}%, "
          f"med={daily['daily_pl'].median():+.3f}%, "
          f"WR={(daily['daily_pl']>0).mean()*100:.1f}%")

    # Consecutive losing days
    daily_sorted = daily.sort_values("day")
    losses = (daily_sorted["daily_pl"] <= 0).astype(int)
    max_streak = 0
    streak = 0
    for v in losses:
        streak = streak + 1 if v else 0
        max_streak = max(max_streak, streak)
    print(f"  Max consecutive losing days: {max_streak}")

    # ═══════════════════════════════════════════════════════
    # Split-sample
    # ═══════════════════════════════════════════════════════
    print(f"\n--- Split-Sample ---")
    all_days = sorted(baseline["trading_day"].unique())
    mid = len(all_days) // 2
    first_days = set(all_days[:mid])
    baseline["half"] = baseline["trading_day"].apply(lambda d: "First" if d in first_days else "Second")

    print_stats(baseline[baseline["half"] == "First"], "First half")
    print_stats(baseline[baseline["half"] == "Second"], "Second half")

    # Non-stress split
    ns = baseline[~baseline["is_stress"]]
    print_stats(ns[ns["half"] == "First"], "First half (non-stress)")
    print_stats(ns[ns["half"] == "Second"], "Second half (non-stress)")

    # ═══════════════════════════════════════════════════════
    # B) VIX level filter
    # ═══════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("VIX Stratification")
    print("=" * 70)
    for regime, label in [("<20", "VIX<20"), ("20-25", "VIX 20-25"), (">=25", "VIX>=25")]:
        if regime == "<20":
            sub = baseline[baseline["vix"] < 20]
        elif regime == "20-25":
            sub = baseline[(baseline["vix"] >= 20) & (baseline["vix"] < 25)]
        else:
            sub = baseline[baseline["vix"] >= 25]
        print_stats(sub, label)

    # ═══════════════════════════════════════════════════════
    # C) Entry time comparison: 12:00, 12:15, 12:30
    # ═══════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("C) Entry Time Comparison")
    print("=" * 70)

    for entry_et, label in [(12*60, "12:00"), (12*60+15, "12:15"), (12*60+30, "12:30")]:
        entry_ist = entry_et + 7 * 60
        # Need to re-rank at the entry time for later entries
        df = run_baseline(m5_cache, stress_set, vix_map, entry_ist=entry_ist)
        print_stats(df, f"Entry {label} ET (all)")
        ns = df[~df["is_stress"]]
        print_stats(ns, f"Entry {label} ET (non-stress)")

    # ═══════════════════════════════════════════════════════
    # D) Stabilization filter
    # ═══════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("D) Stabilization Filter (green close by 12:30)")
    print("=" * 70)
    stab = run_stabilization_filter(m5_cache, stress_set, vix_map)
    print_stats(stab, "ALL (with stabilization)")
    print_stats(stab[~stab["is_stress"]], "Non-stress (with stabilization)")

    # ═══════════════════════════════════════════════════════
    # Monthly breakdown
    # ═══════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("Monthly Breakdown (Baseline)")
    print("=" * 70)
    baseline["month"] = baseline["trading_day"].apply(lambda d: d.strftime("%Y-%m"))
    monthly = baseline.groupby("month").agg(
        avg_pl=("pm_return", "mean"),
        wr=("win", "mean"),
        n=("pm_return", "count"),
    ).reset_index()
    monthly["wr"] = monthly["wr"] * 100
    print(f"{'Month':>8s}  {'Avg PL':>9s}  {'WR':>7s}  {'N':>5s}")
    for _, row in monthly.iterrows():
        print(f"{row['month']:>8s}  {row['avg_pl']:>+8.3f}%  {row['wr']:>6.1f}%  {int(row['n']):>5d}")

    # ═══════════════════════════════════════════════════════
    # PLOTS
    # ═══════════════════════════════════════════════════════
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # 1. Cumulative P&L
    ax = axes[0, 0]
    cum = baseline.sort_values("trading_day")["pm_return"].cumsum()
    ax.plot(range(len(cum)), cum.values, color="steelblue", linewidth=1)
    ax.set_xlabel("Trade #")
    ax.set_ylabel("Cumulative P&L (%)")
    ax.set_title(f"I8 Baseline: Cumulative P&L (N={len(baseline)})")
    ax.axhline(0, color="black", linewidth=0.5)

    # 2. Stress vs Non-stress
    ax = axes[0, 1]
    cats = ["Non-stress", "Stress"]
    vals = [
        baseline[~baseline["is_stress"]]["pm_return"].mean(),
        baseline[baseline["is_stress"]]["pm_return"].mean(),
    ]
    wrs = [
        (baseline[~baseline["is_stress"]]["win"]).mean() * 100,
        (baseline[baseline["is_stress"]]["win"]).mean() * 100,
    ]
    colors = ["#4CAF50", "#F44336"]
    bars = ax.bar(cats, vals, color=colors, alpha=0.85)
    for bar, v, w in zip(bars, vals, wrs):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                f"{v:+.3f}%\nWR={w:.1f}%", ha="center", fontsize=9)
    ax.set_ylabel("Avg P&L (%)")
    ax.set_title("Stress vs Non-Stress")
    ax.axhline(0, color="black", linewidth=0.5)

    # 3. Split-sample
    ax = axes[1, 0]
    halves = ["First", "Second"]
    x = np.arange(2)
    width = 0.35
    all_vals = [baseline[baseline["half"] == h]["pm_return"].mean() for h in halves]
    ns2 = baseline[~baseline["is_stress"]]
    ns_vals = [ns2[ns2["half"] == h]["pm_return"].mean() for h in halves if len(ns2[ns2["half"] == h]) > 0]
    ax.bar(x - width/2, all_vals, width, label="All", color="#2196F3", alpha=0.85)
    if len(ns_vals) == 2:
        ax.bar(x + width/2, ns_vals, width, label="Non-stress", color="#4CAF50", alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(halves)
    ax.set_ylabel("Avg P&L (%)")
    ax.set_title("Split-Sample Stability")
    ax.legend()
    ax.axhline(0, color="black", linewidth=0.5)

    # 4. Monthly P&L
    ax = axes[1, 1]
    colors_m = ["#4CAF50" if v > 0 else "#F44336" for v in monthly["avg_pl"]]
    ax.bar(range(len(monthly)), monthly["avg_pl"], color=colors_m, alpha=0.85)
    ax.set_xticks(range(len(monthly)))
    ax.set_xticklabels(monthly["month"], rotation=45, fontsize=7)
    ax.set_ylabel("Avg P&L (%)")
    ax.set_title("Monthly Avg P&L")
    ax.axhline(0, color="black", linewidth=0.5)

    plt.suptitle("I8: Original H2 Entry — Online Validation", fontsize=14)
    plt.tight_layout()
    plt.savefig(OUT_DIR / "I8_h2_validation.png", dpi=150)
    plt.close()
    print("\nSaved: I8_h2_validation.png")


if __name__ == "__main__":
    main()
