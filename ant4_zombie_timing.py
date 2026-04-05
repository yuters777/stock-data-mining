#!/usr/bin/env python3
"""
ANT-4: Zombie Recovery — Short-Hold Timing Test
Tests whether "zombie" stocks (high intraday recovery after earnings gap-down)
have an edge on SHORT holds (1-2 days) even though 5-day drift is weak.
"""
import json
import sqlite3
import warnings
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

OUTPUT_DIR = Path("backtest_output/ant4")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = "/var/lib/market-system/market.db"
DAILY_DIR = Path("backtester/data/daily")
M5_DIR = Path("backtest_output")


def n_flag(n):
    if n < 10: return " **ANECDOTAL**"
    elif n < 20: return " *LOW N*"
    return ""


def load_events():
    df = pd.read_csv("backtest_output/ant1/events.csv")
    df["day1_date"] = pd.to_datetime(df["day1_date"])
    return df


def load_daily(ticker):
    fpath = DAILY_DIR / f"{ticker}_daily.csv"
    if not fpath.exists():
        return None
    df = pd.read_csv(fpath, header=[0, 1], index_col=0, parse_dates=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.sort_index()


def load_m5_data():
    all_m5 = {}
    for ticker in ["AAPL","MSFT","GOOGL","AMZN","META","NVDA","TSLA","AMD",
                    "AVGO","TSM","MU","COST","COIN","MARA","C","GS","V","BA",
                    "JPM","BABA","BIDU","PLTR","SMCI","INTC","MSTR","ARM"]:
        for suffix in ["_m5_regsess_FIXED.csv", "_m5_regsess.csv"]:
            fpath = M5_DIR / f"{ticker}{suffix}"
            if fpath.exists():
                df = pd.read_csv(fpath, parse_dates=["Datetime"])
                df = df.rename(columns={"Datetime": "datetime"})
                df["date"] = df["datetime"].dt.date
                df["time"] = df["datetime"].dt.strftime("%H:%M")
                df = df.sort_values("datetime").reset_index(drop=True)
                all_m5[ticker] = df
                break
    return all_m5


# ============================================================
# TEST 1: Daily — Zombie Drift by Holding Period
# ============================================================
def test1(events):
    print("=" * 70)
    print("TEST 1: DAILY — ZOMBIE DRIFT BY HOLDING PERIOD")
    print("=" * 70)

    gd = events[events["gap_pct"] <= -5].dropna(subset=["drift_1d","drift_5d"]).copy()
    print(f"Gap-down events (gap <= -5%): N={len(gd)}")
    print()

    rec_thresholds = [0.25, 0.30, 0.35, 0.40, 0.50, None]  # None = all
    drift_cols = ["drift_1d", "drift_2d", "drift_3d", "drift_5d", "drift_7d", "drift_10d"]
    hold_labels = ["1d", "2d", "3d", "5d", "7d", "10d"]

    # Table 1: Cumulative drift
    print("--- Cumulative Drift by Hold Period ---")
    print(f"{'Recovery >=':>12} {'N':>5}", end="")
    for h in hold_labels:
        print(f"  {h:>8}", end="")
    print()
    print("-" * 80)

    results_t1 = {}
    for thresh in rec_thresholds:
        if thresh is not None:
            subset = gd[gd["recovery_ratio"] >= thresh]
            label = f">={thresh:.2f}"
        else:
            subset = gd
            label = "ALL"
        n = len(subset)
        if n == 0:
            continue
        flag = n_flag(n)
        print(f"{label:>12} {n:>5}", end="")
        row = {"n": int(n)}
        for dc, hl in zip(drift_cols, hold_labels):
            val = subset[dc].mean()
            print(f" {val:>+8.2f}%", end="")
            row[hl] = round(val, 3)
        print(flag)
        results_t1[label] = row
    print()

    # Table 2: Win rates
    print("--- Win Rate (% positive) by Hold Period ---")
    print(f"{'Recovery >=':>12} {'N':>5}", end="")
    for h in hold_labels:
        print(f"  {h:>8}", end="")
    print()
    print("-" * 80)

    wr_results = {}
    for thresh in rec_thresholds:
        if thresh is not None:
            subset = gd[gd["recovery_ratio"] >= thresh]
            label = f">={thresh:.2f}"
        else:
            subset = gd
            label = "ALL"
        n = len(subset)
        if n == 0:
            continue
        flag = n_flag(n)
        print(f"{label:>12} {n:>5}", end="")
        row = {"n": int(n)}
        for dc, hl in zip(drift_cols, hold_labels):
            wr = (subset[dc] > 0).mean() * 100
            print(f"  {wr:>7.1f}%", end="")
            row[hl] = round(wr, 1)
        print(flag)
        wr_results[label] = row
    print()

    # Table 3: Incremental drift
    print("--- Incremental Drift (marginal value of extra day) ---")
    print(f"{'Recovery >=':>12} {'N':>5}  {'incr_1d':>8}  {'incr_2d':>8}  {'incr_3d':>8}  {'incr_5d':>8}")
    print("-" * 60)

    incr_results = {}
    for thresh in rec_thresholds:
        if thresh is not None:
            subset = gd[gd["recovery_ratio"] >= thresh]
            label = f">={thresh:.2f}"
        else:
            subset = gd
            label = "ALL"
        n = len(subset)
        if n == 0:
            continue
        d1 = subset["drift_1d"].mean()
        d2 = subset["drift_2d"].mean()
        d3 = subset["drift_3d"].mean()
        d5 = subset["drift_5d"].mean()
        i1 = d1
        i2 = d2 - d1
        i3 = d3 - d2
        i5 = (d5 - d3) / 2  # per-day average over 2 days
        flag = n_flag(n)
        print(f"{label:>12} {n:>5}  {i1:>+7.2f}%  {i2:>+7.2f}%  {i3:>+7.2f}%  {i5:>+7.2f}%{flag}")
        incr_results[label] = {"n": int(n), "i1": round(i1,3), "i2": round(i2,3),
                                "i3": round(i3,3), "i5": round(i5,3)}
    print()

    # Table 4: Gap severity interaction for recovery >= 0.35
    print("--- Gap Severity x Zombie (rec>=0.35) Drift by Hold ---")
    gap_buckets = [
        ("-5% to -8%", -8, -5), ("-8% to -10%", -10, -8), ("-10% to -15%", -15, -10),
    ]
    zombie = gd[gd["recovery_ratio"] >= 0.35]
    print(f"{'Gap Bucket':<16} {'N':>4}  {'1d':>8}  {'2d':>8}  {'3d':>8}  {'5d':>8}")
    print("-" * 56)
    for label, lo, hi in gap_buckets:
        sub = zombie[(zombie["gap_pct"] >= lo) & (zombie["gap_pct"] < hi)]
        n = len(sub)
        if n == 0:
            continue
        flag = n_flag(n)
        d1 = sub["drift_1d"].mean()
        d2 = sub["drift_2d"].mean()
        d3 = sub["drift_3d"].mean()
        d5 = sub["drift_5d"].mean()
        print(f"{label:<16} {n:>4}  {d1:>+7.2f}%  {d2:>+7.2f}%  {d3:>+7.2f}%  {d5:>+7.2f}%{flag}")
    print()

    return {"cumulative": results_t1, "win_rates": wr_results, "incremental": incr_results}


# ============================================================
# TEST 2: M5 — Intraday Zombie Timing
# ============================================================
def test2(events, all_m5):
    print("=" * 70)
    print("TEST 2: M5 — INTRADAY ZOMBIE TIMING")
    print("=" * 70)

    conn = sqlite3.connect(DB_PATH)
    earn_df = pd.read_sql("SELECT * FROM earnings_calendar", conn)
    conn.close()
    earn_df["earnings_date"] = pd.to_datetime(earn_df["earnings_date"])

    AMC_TICKERS = {"AAPL","MSFT","GOOGL","AMZN","META","NVDA","TSLA","AMD",
                   "COIN","ARM","SMCI","PLTR","MSTR","MARA","AVGO","TSM",
                   "V","MU","INTC","COST"}
    BMO_TICKERS = {"JD","BIDU","BABA","C","GS","BA","JPM"}

    thresholds = [0.25, 0.30, 0.35, 0.40]

    zombie_events = []

    for _, earn_row in earn_df.iterrows():
        ticker = earn_row["ticker"]
        if ticker not in all_m5:
            continue
        m5 = all_m5[ticker]
        earn_date = earn_row["earnings_date"].date()
        timing = earn_row.get("time_of_day", "Unknown")
        if timing not in ("BMO", "AMC"):
            timing = "AMC" if ticker in AMC_TICKERS else ("BMO" if ticker in BMO_TICKERS else "AMC")

        tdays = sorted(m5["date"].unique())
        if timing == "BMO":
            day1_date = earn_date
        else:
            future = [d for d in tdays if d > earn_date]
            if not future:
                continue
            day1_date = future[0]

        if day1_date not in tdays:
            continue
        d1_idx = tdays.index(day1_date)
        if d1_idx < 1 or d1_idx + 5 >= len(tdays):
            continue

        prior_date = tdays[d1_idx - 1]
        prior_bars = m5[m5["date"] == prior_date]
        if len(prior_bars) == 0:
            continue
        prior_close = prior_bars.iloc[-1]["Close"]

        day1_bars = m5[m5["date"] == day1_date].copy()
        if len(day1_bars) < 10:
            continue

        day1_open = day1_bars.iloc[0]["Open"]
        if prior_close <= 0 or day1_open <= 0:
            continue
        gap_pct = (day1_open - prior_close) / prior_close * 100
        if gap_pct > -3:
            continue

        gap_size = abs(prior_close - day1_open)
        if gap_size <= 0:
            continue

        # Find zombie trigger times for each threshold
        running_low = float("inf")
        trigger_info = {t: None for t in thresholds}

        for _, bar in day1_bars.iterrows():
            running_low = min(running_low, bar["Low"])
            recovery = (bar["Close"] - running_low) / gap_size

            for thresh in thresholds:
                if trigger_info[thresh] is None and recovery >= thresh:
                    trigger_info[thresh] = {
                        "time": bar["time"],
                        "price": bar["Close"],
                        "recovery": recovery,
                    }

        day1_close = day1_bars.iloc[-1]["Close"]
        day1_low = day1_bars["Low"].min()

        # Forward closes
        fwd_closes = {}
        for fd in [1, 2, 3, 5]:
            if d1_idx + fd < len(tdays):
                fwd_date = tdays[d1_idx + fd]
                fwd_bars = m5[m5["date"] == fwd_date]
                if len(fwd_bars) > 0:
                    fwd_closes[fd] = fwd_bars.iloc[-1]["Close"]

        for thresh in thresholds:
            ti = trigger_info[thresh]
            if ti is None:
                continue

            entry_price = ti["price"]
            trigger_time = ti["time"]

            # Skip Zone 1 triggers (before 10:00)
            if trigger_time < "10:00":
                continue

            returns = {}
            # To close same day
            returns["to_close"] = (day1_close - entry_price) / entry_price * 100
            for fd, fc in fwd_closes.items():
                returns[f"to_day{fd+1}"] = (fc - entry_price) / entry_price * 100

            zombie_events.append({
                "ticker": ticker, "date": str(day1_date), "gap_pct": gap_pct,
                "threshold": thresh, "trigger_time": trigger_time,
                "trigger_price": entry_price, "day1_close": day1_close,
                "day1_low": day1_low, "prior_close": prior_close,
                **returns,
            })

    zdf = pd.DataFrame(zombie_events)
    if zdf.empty:
        print("No zombie events found in M5 data.")
        return {}

    print(f"Total zombie trigger events: {len(zdf)}")
    print()

    # Trigger timing distribution
    print("--- Zombie Trigger Timing ---")
    print(f"{'Threshold':>10} {'N':>5} {'Mean Time':>12} {'Median Time':>12}")
    print("-" * 45)

    trigger_results = {}
    for thresh in thresholds:
        sub = zdf[zdf["threshold"] == thresh]
        n = len(sub)
        if n == 0:
            continue
        # Convert time strings to minutes for stats
        minutes = sub["trigger_time"].apply(lambda t: int(t[:2])*60 + int(t[3:]))
        mean_min = minutes.mean()
        med_min = minutes.median()
        mean_t = f"{int(mean_min//60):02d}:{int(mean_min%60):02d}"
        med_t = f"{int(med_min//60):02d}:{int(med_min%60):02d}"
        flag = n_flag(n)
        print(f"{thresh:>10.2f} {n:>5} {mean_t:>12} {med_t:>12}{flag}")
        trigger_results[str(thresh)] = {"n": int(n), "mean_time": mean_t, "median_time": med_t}
    print()

    # Return from trigger point
    print("--- Return from Zombie Trigger Point ---")
    ret_cols = ["to_close", "to_day2", "to_day3", "to_day4", "to_day6"]
    ret_labels = ["->Close", "->Day2", "->Day3", "->Day4", "->Day6"]
    available = [c for c in ret_cols if c in zdf.columns]
    avail_labels = [ret_labels[i] for i, c in enumerate(ret_cols) if c in zdf.columns]

    print(f"{'Thresh':>7} {'N':>4}", end="")
    for l in avail_labels:
        print(f"  {l:>12}", end="")
    print()
    print("-" * (15 + 14 * len(avail_labels)))

    return_results = {}
    for thresh in thresholds:
        sub = zdf[zdf["threshold"] == thresh]
        n = len(sub)
        if n == 0:
            continue
        flag = n_flag(n)
        print(f"{thresh:>7.2f} {n:>4}", end="")
        row = {"n": int(n)}
        for col, label in zip(available, avail_labels):
            vals = sub[col].dropna()
            if len(vals) > 0:
                mean_v = vals.mean()
                wr = (vals > 0).mean() * 100
                print(f"  {mean_v:>+5.2f}/{wr:>4.0f}%", end="")
                row[label] = {"mean": round(mean_v, 3), "wr": round(wr, 1)}
            else:
                print(f"  {'N/A':>12}", end="")
        print(flag)
        return_results[str(thresh)] = row
    print()

    # Zombie M5 backtest
    print("--- Zombie M5 Strategy Backtest ---")
    print(f"{'Exit':>10} {'Thresh':>7} {'N':>4} {'Mean%':>8} {'WR':>6} {'PF':>7}")
    print("-" * 48)

    strat_results = {}
    for thresh in thresholds:
        sub = zdf[zdf["threshold"] == thresh].copy()
        if len(sub) == 0:
            continue

        for exit_label, exit_col in [("Day1Close", "to_close"), ("Day2", "to_day2"),
                                      ("Day3", "to_day3")]:
            if exit_col not in sub.columns:
                continue
            valid = sub.dropna(subset=[exit_col])
            if len(valid) == 0:
                continue

            # Apply stop: if any forward low < day1_low, cap loss
            # (simplified: just use the return column as-is for now)
            rets = valid[exit_col]
            n = len(rets)
            mean_r = rets.mean()
            wr = (rets > 0).mean() * 100
            wins = rets[rets > 0].sum()
            losses = abs(rets[rets <= 0].sum())
            pf = wins / losses if losses > 0 else float("inf")
            flag = n_flag(n)
            print(f"{exit_label:>10} {thresh:>7.2f} {n:>4} {mean_r:>+7.2f}% {wr:>5.1f}% {pf:>6.2f}{flag}")
            strat_results[f"{exit_label}_{thresh}"] = {
                "n": int(n), "mean": round(mean_r, 3), "wr": round(wr, 1), "pf": round(pf, 2)}
    print()

    # Chart: trigger time distribution
    if len(zdf) > 0:
        fig, ax = plt.subplots(figsize=(10, 6))
        for thresh in thresholds:
            sub = zdf[zdf["threshold"] == thresh]
            if len(sub) == 0:
                continue
            minutes = sub["trigger_time"].apply(lambda t: int(t[:2]) * 60 + int(t[3:]))
            ax.hist(minutes, bins=range(570, 960, 15), alpha=0.4,
                    label=f"Rec >= {thresh:.2f} (N={len(sub)})")
        ax.set_xlabel("Time (minutes from midnight, 570=09:30)")
        ax.set_ylabel("Count")
        ax.set_title("ANT-4: Zombie Trigger Time Distribution")
        ax.legend()
        ticks = [570, 600, 630, 660, 720, 780, 840, 900, 960]
        ax.set_xticks(ticks)
        ax.set_xticklabels(["9:30","10:00","10:30","11:00","12:00","13:00","14:00","15:00","16:00"])
        plt.tight_layout()
        fig.savefig(OUTPUT_DIR / "ant4_trigger_time_dist.png", dpi=150)
        plt.close(fig)
        print("  Saved ant4_trigger_time_dist.png")

    return {"triggers": trigger_results, "returns": return_results, "strategy": strat_results}


# ============================================================
# TEST 3: Zombie Peak — When Does Recovery Max Out?
# ============================================================
def test3(events):
    print("=" * 70)
    print("TEST 3: ZOMBIE PEAK — WHEN DOES RECOVERY MAX OUT?")
    print("=" * 70)

    gd = events[events["gap_pct"] <= -5].copy()
    zombie = gd[gd["recovery_ratio"] >= 0.35].dropna(subset=["trajectory"]).copy()
    print(f"Zombie events (gap <= -5%, recovery >= 0.35): N={len(zombie)}")
    print()

    if len(zombie) == 0:
        return {}

    # Parse trajectories
    peak_days = []
    peak_returns = []
    for _, ev in zombie.iterrows():
        try:
            traj = json.loads(ev["trajectory"])
        except:
            continue
        if len(traj) < 2:
            continue
        max_idx = np.argmax(traj)
        max_val = traj[max_idx]
        peak_days.append(max_idx)
        peak_returns.append(max_val)

    if not peak_days:
        print("No valid trajectories.")
        return {}

    peak_days = np.array(peak_days)
    peak_returns = np.array(peak_returns)

    # Distribution
    print("--- Day of Maximum Close (Post-Gap) ---")
    day_groups = [(0, 0, "Day 0 (gap day)"), (1, 1, "Day 1"), (2, 2, "Day 2"),
                  (3, 3, "Day 3"), (4, 5, "Day 4-5"), (6, 10, "Day 6-10")]

    peak_dist = {}
    for lo, hi, label in day_groups:
        mask = (peak_days >= lo) & (peak_days <= hi)
        n = mask.sum()
        pct = n / len(peak_days) * 100
        mean_ret = peak_returns[mask].mean() if n > 0 else 0
        print(f"  {label:<16}: {n:>3} ({pct:>5.1f}%)  mean max return: {mean_ret:>+.2f}%")
        peak_dist[label] = {"n": int(n), "pct": round(pct, 1), "mean_max_ret": round(mean_ret, 3)}
    print()

    mode_day = pd.Series(peak_days).mode().iloc[0]
    mean_day = peak_days.mean()
    print(f"Mode: Day {mode_day}, Mean: Day {mean_day:.1f}")
    print()

    # Also for non-zombie
    non_zombie = gd[gd["recovery_ratio"] < 0.20].dropna(subset=["trajectory"]).copy()
    nz_peak_days = []
    for _, ev in non_zombie.iterrows():
        try:
            traj = json.loads(ev["trajectory"])
        except:
            continue
        if len(traj) >= 2:
            nz_peak_days.append(np.argmax(traj))
    print(f"Non-zombie peak day (recovery < 0.20, N={len(nz_peak_days)}):")
    if nz_peak_days:
        nz_arr = np.array(nz_peak_days)
        print(f"  Mode: Day {pd.Series(nz_arr).mode().iloc[0]}, Mean: Day {nz_arr.mean():.1f}")
    print()

    # Chart
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.hist(peak_days, bins=range(12), align="left", color="green", alpha=0.7,
            edgecolor="black", label=f"Zombie rec>=0.35 (N={len(peak_days)})")
    if nz_peak_days:
        ax.hist(nz_peak_days, bins=range(12), align="left", color="red", alpha=0.5,
                edgecolor="black", label=f"Non-zombie rec<0.20 (N={len(nz_peak_days)})")
    ax.set_xlabel("Day of Maximum Close (0 = gap day)")
    ax.set_ylabel("Count")
    ax.set_title("ANT-4: When Does Post-Earnings Recovery Peak?")
    ax.legend()
    ax.set_xticks(range(11))
    plt.tight_layout()
    fig.savefig(OUTPUT_DIR / "ant4_zombie_peak_dist.png", dpi=150)
    plt.close(fig)
    print("  Saved ant4_zombie_peak_dist.png")

    return {"peak_dist": peak_dist, "mode_day": int(mode_day), "mean_day": round(mean_day, 1)}


# ============================================================
# TEST 4: Anti-Zombie Control
# ============================================================
def test4(events):
    print("=" * 70)
    print("TEST 4: ZOMBIE vs NON-ZOMBIE COMPARISON")
    print("=" * 70)

    gd = events[events["gap_pct"] <= -5].dropna(subset=["drift_1d", "drift_5d"]).copy()

    groups = [
        ("Zombie (rec>=0.35)", gd[gd["recovery_ratio"] >= 0.35]),
        ("Non-zombie (rec<0.20)", gd[gd["recovery_ratio"] < 0.20]),
        ("All gap-downs", gd),
    ]

    drift_cols = ["drift_1d", "drift_2d", "drift_3d", "drift_5d", "drift_10d"]
    hold_labels = ["1d", "2d", "3d", "5d", "10d"]

    print("--- Cumulative Drift Comparison ---")
    print(f"{'Group':<24} {'N':>4}", end="")
    for h in hold_labels:
        print(f"  {h:>8}", end="")
    print()
    print("-" * 72)

    results = {}
    traj_data = {}
    for gname, gsub in groups:
        n = len(gsub)
        if n == 0:
            continue
        flag = n_flag(n)
        print(f"{gname:<24} {n:>4}", end="")
        row = {"n": int(n)}
        means = []
        for dc, hl in zip(drift_cols, hold_labels):
            val = gsub[dc].mean()
            print(f" {val:>+8.2f}%", end="")
            row[hl] = round(val, 3)
            means.append(val)
        print(flag)
        results[gname] = row
        traj_data[gname] = [0.0] + means
    print()

    # Win rate comparison
    print("--- Win Rate Comparison ---")
    print(f"{'Group':<24} {'N':>4}", end="")
    for h in hold_labels:
        print(f"  {h:>8}", end="")
    print()
    print("-" * 72)

    for gname, gsub in groups:
        n = len(gsub)
        if n == 0:
            continue
        flag = n_flag(n)
        print(f"{gname:<24} {n:>4}", end="")
        for dc, hl in zip(drift_cols, hold_labels):
            wr = (gsub[dc] > 0).mean() * 100
            print(f"  {wr:>7.1f}%", end="")
        print(flag)
    print()

    # Key comparison
    z = results.get("Zombie (rec>=0.35)", {})
    nz = results.get("Non-zombie (rec<0.20)", {})
    if z and nz:
        print("--- Zombie Advantage (Zombie minus Non-zombie) ---")
        for hl in hold_labels:
            diff = z.get(hl, 0) - nz.get(hl, 0)
            print(f"  {hl}: {diff:>+.2f}%", end="")
        print()
        print()
        # At which horizon does zombie lose?
        for hl in hold_labels:
            diff = z.get(hl, 0) - nz.get(hl, 0)
            if diff < 0:
                print(f"  Zombie advantage disappears at {hl} hold")
                break
        else:
            print("  Zombie advantage persists through 10d")
    print()

    # Chart: cumulative drift curves
    fig, ax = plt.subplots(figsize=(10, 7))
    colors = {"Zombie (rec>=0.35)": "green", "Non-zombie (rec<0.20)": "red", "All gap-downs": "gray"}
    x_labels = ["D0", "D1", "D2", "D3", "D5", "D10"]

    for gname, vals in traj_data.items():
        ax.plot(range(len(vals)), vals, "o-", color=colors.get(gname, "blue"),
                linewidth=2, markersize=8, label=f"{gname} (N={results[gname]['n']})")
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_xticks(range(len(x_labels)))
    ax.set_xticklabels(x_labels)
    ax.set_xlabel("Holding Period")
    ax.set_ylabel("Cumulative Drift (%)")
    ax.set_title("ANT-4: Zombie vs Non-Zombie — Cumulative Drift by Hold Period")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    fig.savefig(OUTPUT_DIR / "ant4_cumulative_drift_curve.png", dpi=150)
    plt.close(fig)
    print("  Saved ant4_cumulative_drift_curve.png")

    # Chart: incremental drift
    fig, ax = plt.subplots(figsize=(10, 6))
    incr_labels = ["Day 1", "Day 2", "Day 3", "Day 4-5"]
    width = 0.3
    x = np.arange(len(incr_labels))

    for i, (gname, gsub) in enumerate([(g, s) for g, s in groups[:2] if len(s) > 0]):
        d = [gsub["drift_1d"].mean(),
             (gsub["drift_2d"] - gsub["drift_1d"]).mean(),
             (gsub["drift_3d"] - gsub["drift_2d"]).mean(),
             ((gsub["drift_5d"] - gsub["drift_3d"]) / 2).mean()]
        ax.bar(x + i * width - width/2, d, width,
               label=f"{gname} (N={len(gsub)})",
               color=list(colors.values())[i], alpha=0.8)

    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(incr_labels)
    ax.set_xlabel("Holding Day")
    ax.set_ylabel("Incremental Drift (%)")
    ax.set_title("ANT-4: Marginal Drift by Day — Zombie vs Non-Zombie")
    ax.legend()
    plt.tight_layout()
    fig.savefig(OUTPUT_DIR / "ant4_incremental_drift.png", dpi=150)
    plt.close(fig)
    print("  Saved ant4_incremental_drift.png")

    return results


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 70)
    print("ANT-4: ZOMBIE RECOVERY — SHORT-HOLD TIMING TEST")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)
    print()

    events = load_events()
    print(f"Loaded {len(events)} events from ANT-1")
    print()

    results = {}

    # Test 1: Daily
    results["test1"] = test1(events)

    # Test 2: M5
    print("Loading M5 data...")
    all_m5 = load_m5_data()
    print(f"  {len(all_m5)} tickers with M5 data")
    print()
    results["test2"] = test2(events, all_m5)

    # Test 3: Zombie peak
    results["test3"] = test3(events)

    # Test 4: Zombie vs non-zombie
    results["test4"] = test4(events)

    # Save
    results["meta"] = {
        "date_run": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "n_events": len(events),
        "n_gap_down_5": int((events["gap_pct"] <= -5).sum()),
    }
    with open(OUTPUT_DIR / "ANT4_summary.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("Saved ANT4_summary.json")
    print()
    print("Done. All outputs in backtest_output/ant4/")


if __name__ == "__main__":
    main()
