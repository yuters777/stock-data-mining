#!/usr/bin/env python3
"""
ANT-3 Test A: PEAD-lite Gap Cap
Tests whether adding an upper bound on gap size improves PEAD strategy PF.
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

OUTPUT_DIR = Path("backtest_output/ant3")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = "/var/lib/market-system/market.db"
DAILY_DIR = Path("backtester/data/daily")


def load_daily(ticker):
    fpath = DAILY_DIR / f"{ticker}_daily.csv"
    if not fpath.exists():
        return None
    df = pd.read_csv(fpath, header=[0, 1], index_col=0, parse_dates=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.sort_index()


def load_events():
    """Load precomputed events from ANT-1."""
    df = pd.read_csv("backtest_output/ant1/events.csv")
    df["day1_date"] = pd.to_datetime(df["day1_date"])
    df["earnings_date"] = pd.to_datetime(df["earnings_date"])
    return df


def n_flag(n):
    if n < 10: return " **ANECDOTAL**"
    elif n < 20: return " *LOW N*"
    return ""


def run_pead_trade(ev, daily_df):
    """Run a single PEAD-lite trade. Returns dict or None."""
    ticker = ev["ticker"]
    idx = daily_df.index
    day1_date = pd.Timestamp(ev["day1_date"])
    if day1_date not in idx:
        return None
    d1_pos = idx.get_loc(day1_date)
    if d1_pos + 10 >= len(idx):
        return None

    entry_price = ev["day1_close"]
    prior_close = ev["prior_close"]
    day1_open = ev["day1_open"]
    gap_pct = ev["gap_pct"]

    # Gap midpoint
    midpoint = (prior_close + day1_open) / 2.0

    # Direction: LONG if gap-down, SHORT if gap-up
    direction = "LONG" if gap_pct < 0 else "SHORT"

    exit_price = None
    exit_reason = None
    hold_days = 0

    for fd in range(1, 11):
        if d1_pos + fd >= len(idx):
            break
        hold_days = fd
        bar_close = daily_df.iloc[d1_pos + fd]["Close"]

        if direction == "LONG":
            if bar_close >= midpoint:
                exit_price = midpoint
                exit_reason = "midpoint"
                break
        else:
            if bar_close <= midpoint:
                exit_price = midpoint
                exit_reason = "midpoint"
                break

    if exit_price is None and hold_days > 0:
        exit_price = daily_df.iloc[d1_pos + hold_days]["Close"]
        exit_reason = "max_hold"

    if exit_price is None:
        return None

    if direction == "LONG":
        ret = (exit_price - entry_price) / entry_price * 100
    else:
        ret = (entry_price - exit_price) / entry_price * 100

    return {
        "ticker": ticker, "date": str(day1_date.date()), "gap_pct": gap_pct,
        "direction": direction, "entry": entry_price, "exit": exit_price,
        "return_pct": ret, "reason": exit_reason, "hold_days": hold_days,
    }


def compute_metrics(trades_df):
    if len(trades_df) == 0:
        return {"n": 0}
    n = len(trades_df)
    mean_ret = trades_df["return_pct"].mean()
    wr = (trades_df["return_pct"] > 0).mean() * 100
    wins = trades_df[trades_df["return_pct"] > 0]["return_pct"].sum()
    losses = abs(trades_df[trades_df["return_pct"] <= 0]["return_pct"].sum())
    pf = wins / losses if losses > 0 else float("inf")
    return {"n": int(n), "mean": round(mean_ret, 3), "wr": round(wr, 1), "pf": round(pf, 2)}


def test_a(events, all_daily):
    print("=" * 70)
    print("TEST A: PEAD-LITE GAP CAP")
    print("=" * 70)

    # Run all trades first
    all_trades = []
    for _, ev in events.iterrows():
        ticker = ev["ticker"]
        if ticker not in all_daily:
            continue
        trade = run_pead_trade(ev, all_daily[ticker])
        if trade:
            all_trades.append(trade)

    tdf = pd.DataFrame(all_trades)
    print(f"Total PEAD trades: {len(tdf)}")
    print(f"  LONG: {(tdf['direction']=='LONG').sum()}, SHORT: {(tdf['direction']=='SHORT').sum()}")
    print()

    # Gap bucket drift analysis
    print("--- Gap Bucket Drift Analysis ---")
    print(f"{'Bucket':<16} {'N':>5} {'Mean drift_5d':>14} {'Mean drift_10d':>15} {'WR (5d)':>8}")
    print("-" * 65)

    gap_buckets_neg = [
        ("-5% to -8%", -8, -5), ("-8% to -10%", -10, -8),
        ("-10% to -15%", -15, -10), ("-15% to -20%", -20, -15), ("< -20%", -999, -20),
    ]
    gap_buckets_pos = [
        ("+5% to +8%", 5, 8), ("+8% to +10%", 8, 10),
        ("+10% to +15%", 10, 15), ("> +15%", 15, 999),
    ]

    bucket_results = {}
    for label, lo, hi in gap_buckets_neg + gap_buckets_pos:
        if lo == -999:
            mask = events["gap_pct"] < hi
        elif hi == 999:
            mask = events["gap_pct"] >= lo
        elif lo < 0:
            mask = (events["gap_pct"] >= lo) & (events["gap_pct"] < hi)
        else:
            mask = (events["gap_pct"] >= lo) & (events["gap_pct"] < hi)
        sub = events[mask]
        n = len(sub)
        if n == 0:
            continue
        d5 = sub["drift_5d"].mean()
        d10 = sub["drift_10d"].mean()
        wr5 = (sub["drift_5d"] > 0).mean() * 100 if "drift_5d" in sub else 0
        flag = n_flag(n)
        print(f"{label:<16} {n:>5} {d5:>+13.2f}% {d10:>+14.2f}% {wr5:>7.1f}%{flag}")
        bucket_results[label] = {"n": int(n), "drift_5d": round(d5, 3), "drift_10d": round(d10, 3), "wr_5d": round(wr5, 1)}
    print()

    # Gap floor x cap matrix
    print("--- Gap Floor x Cap Matrix (LONG only) ---")
    floors = [2, 3, 5]
    caps = [8, 10, 12, 15, 999]
    cap_labels = {8: "8%", 10: "10%", 12: "12%", 15: "15%", 999: "no cap"}

    print(f"{'Floor':>6} {'Cap':>8} {'N':>5} {'Mean%':>8} {'WR%':>7} {'PF':>7}")
    print("-" * 48)

    matrix_results = {}
    for floor in floors:
        no_cap_pf = None
        for cap in caps:
            long_trades = tdf[
                (tdf["direction"] == "LONG") &
                (tdf["gap_pct"].abs() >= floor) &
                ((tdf["gap_pct"].abs() <= cap) if cap != 999 else True)
            ]
            m = compute_metrics(long_trades)
            if cap == 999:
                no_cap_pf = m.get("pf", 0)
            delta = ""
            if no_cap_pf is not None and cap != 999 and m["n"] > 0:
                delta = f" (Δ{m['pf'] - no_cap_pf:+.2f})"
            flag = n_flag(m["n"])
            if m["n"] > 0:
                print(f"{floor:>5}% {cap_labels[cap]:>8} {m['n']:>5} {m['mean']:>+7.2f}% {m['wr']:>6.1f}% {m['pf']:>6.2f}{delta}{flag}")
            key = f"LONG_{floor}_{cap}"
            matrix_results[key] = m
    print()

    # SHORT side
    print("--- Gap Floor x Cap Matrix (SHORT only) ---")
    print(f"{'Floor':>6} {'Cap':>8} {'N':>5} {'Mean%':>8} {'WR%':>7} {'PF':>7}")
    print("-" * 48)
    for floor in floors:
        for cap in caps:
            short_trades = tdf[
                (tdf["direction"] == "SHORT") &
                (tdf["gap_pct"].abs() >= floor) &
                ((tdf["gap_pct"].abs() <= cap) if cap != 999 else True)
            ]
            m = compute_metrics(short_trades)
            if m["n"] > 0:
                flag = n_flag(m["n"])
                print(f"{floor:>5}% {cap_labels[cap]:>8} {m['n']:>5} {m['mean']:>+7.2f}% {m['wr']:>6.1f}% {m['pf']:>6.2f}{flag}")
            key = f"SHORT_{floor}_{cap}"
            matrix_results[key] = m
    print()

    # Chart: gap bucket drift
    neg_labels = [b[0] for b in gap_buckets_neg if b[0] in bucket_results]
    neg_d5 = [bucket_results[l]["drift_5d"] for l in neg_labels]
    pos_labels = [b[0] for b in gap_buckets_pos if b[0] in bucket_results]
    pos_d5 = [bucket_results[l]["drift_5d"] for l in pos_labels]

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    if neg_labels:
        axes[0].barh(range(len(neg_labels)), neg_d5, color=["green" if v > 0 else "red" for v in neg_d5])
        axes[0].set_yticks(range(len(neg_labels)))
        axes[0].set_yticklabels(neg_labels)
        axes[0].set_xlabel("Mean Drift 5d (%)")
        axes[0].set_title("Gap-Down Buckets: 5-Day Drift")
        axes[0].axvline(0, color="black", linewidth=0.5)
        for i, l in enumerate(neg_labels):
            axes[0].text(neg_d5[i], i, f" N={bucket_results[l]['n']}", va="center", fontsize=8)

    if pos_labels:
        axes[1].barh(range(len(pos_labels)), pos_d5, color=["green" if v > 0 else "red" for v in pos_d5])
        axes[1].set_yticks(range(len(pos_labels)))
        axes[1].set_yticklabels(pos_labels)
        axes[1].set_xlabel("Mean Drift 5d (%)")
        axes[1].set_title("Gap-Up Buckets: 5-Day Drift")
        axes[1].axvline(0, color="black", linewidth=0.5)
        for i, l in enumerate(pos_labels):
            axes[1].text(pos_d5[i], i, f" N={bucket_results[l]['n']}", va="center", fontsize=8)

    plt.tight_layout()
    fig.savefig(OUTPUT_DIR / "ant3_gap_bucket_drift.png", dpi=150)
    plt.close(fig)
    print("  Saved ant3_gap_bucket_drift.png")

    # Chart: PF with gap cap for LONG
    fig, ax = plt.subplots(figsize=(10, 6))
    for floor in floors:
        pfs = []
        ns = []
        for cap in caps:
            key = f"LONG_{floor}_{cap}"
            m = matrix_results.get(key, {"pf": 0, "n": 0})
            pfs.append(m.get("pf", 0))
            ns.append(m.get("n", 0))
        ax.plot([cap_labels[c] for c in caps], pfs, "o-", label=f"Floor {floor}%", linewidth=2)
    ax.axhline(1.0, color="gray", linestyle=":", label="Breakeven")
    ax.set_xlabel("Gap Cap")
    ax.set_ylabel("Profit Factor")
    ax.set_title("ANT-3A: PEAD LONG — PF by Gap Cap")
    ax.legend()
    plt.tight_layout()
    fig.savefig(OUTPUT_DIR / "ant3_gap_cap_pf.png", dpi=150)
    plt.close(fig)
    print("  Saved ant3_gap_cap_pf.png")

    return {"buckets": bucket_results, "matrix": matrix_results}


def run_m6e_trade(ev, daily_df, entry_day="day2", stop_type="day1_low"):
    """Run Module 6E trade (LONG only, gap-down)."""
    idx = daily_df.index
    day1_date = pd.Timestamp(ev["day1_date"])
    if day1_date not in idx:
        return None
    d1_pos = idx.get_loc(day1_date)
    if d1_pos + 11 >= len(idx):
        return None

    prior_close = ev["prior_close"]
    day1_open = ev["day1_open"]
    day1_low = ev["day1_low"]
    day1_close = ev["day1_close"]
    midpoint = (prior_close + day1_open) / 2.0

    if entry_day == "day2":
        entry_price = daily_df.iloc[d1_pos + 1]["Open"]
        start_fd = 1
    else:
        entry_price = day1_close
        start_fd = 1

    if entry_price <= 0:
        return None

    stop_price = day1_low
    exit_price = None
    exit_reason = None
    hold_days = 0

    for fd in range(start_fd, start_fd + 10):
        if d1_pos + fd >= len(idx):
            break
        hold_days = fd - start_fd + 1
        bar = daily_df.iloc[d1_pos + fd]

        # Stop: close below day1_low
        if bar["Low"] <= stop_price:
            exit_price = stop_price
            exit_reason = "stop"
            break
        # Target: close >= midpoint
        if bar["Close"] >= midpoint:
            exit_price = midpoint
            exit_reason = "midpoint"
            break

    if exit_price is None and hold_days > 0:
        exit_price = daily_df.iloc[d1_pos + start_fd + hold_days - 1]["Close"]
        exit_reason = "max_hold"

    if exit_price is None:
        return None

    ret = (exit_price - entry_price) / entry_price * 100
    return {
        "ticker": ev["ticker"], "date": str(day1_date.date()),
        "gap_pct": ev["gap_pct"], "recovery_ratio": ev.get("recovery_ratio", np.nan),
        "entry": entry_price, "exit": exit_price, "return_pct": ret,
        "reason": exit_reason, "hold_days": hold_days, "entry_type": entry_day,
    }


def test_b(events, all_daily):
    print("=" * 70)
    print("TEST B: MODULE 6E — EARNINGS-DAY SHOCK VARIANT")
    print("=" * 70)

    # Filter to gap-down events only
    gd_events = events[events["gap_pct"] < 0].copy()
    print(f"Total gap-down earnings events: {len(gd_events)}")
    print()

    gap_floors = [-5, -7, -10]
    variants = {
        "V1 Basic": lambda e: True,
        "V2 Low Rec": lambda e: e["recovery_ratio"] < 0.30 if pd.notna(e.get("recovery_ratio")) else False,
        "V3 Bad Surp": lambda e: abs(e.get("eps_surprise_pct", 0) or 0) >= 10,
        "V4 Combined": lambda e: (e["recovery_ratio"] < 0.30 if pd.notna(e.get("recovery_ratio")) else False) and abs(e.get("eps_surprise_pct", 0) or 0) >= 10,
    }

    print("--- Module 6E Variants (Day 2 Entry) ---")
    print(f"{'Variant':<16} {'Gap':>5} {'N':>5} {'Mean%':>8} {'WR%':>7} {'PF':>7} {'AvgHold':>8}")
    print("-" * 62)

    variant_results = {}
    for vname, vfilter in variants.items():
        for gap_floor in gap_floors:
            subset = gd_events[gd_events["gap_pct"] <= gap_floor]
            filtered = subset[subset.apply(vfilter, axis=1)]

            trades = []
            for _, ev in filtered.iterrows():
                t = ev["ticker"]
                if t not in all_daily:
                    continue
                trade = run_m6e_trade(ev, all_daily[t], entry_day="day2")
                if trade:
                    trades.append(trade)

            if not trades:
                continue

            tdf_v = pd.DataFrame(trades)
            m = compute_metrics(tdf_v)
            avg_hold = tdf_v["hold_days"].mean()
            flag = n_flag(m["n"])
            print(f"{vname:<16} {gap_floor:>4}% {m['n']:>5} {m['mean']:>+7.2f}% {m['wr']:>6.1f}% {m['pf']:>6.2f} {avg_hold:>7.1f}{flag}")
            key = f"{vname}_{gap_floor}"
            variant_results[key] = {**m, "avg_hold": round(avg_hold, 1)}

    print()

    # Day 1 vs Day 2 entry comparison
    print("--- Day 1 Close vs Day 2 Open Entry (V1 Basic, gap <= -5%) ---")
    print(f"{'Entry':>10} {'N':>5} {'Mean%':>8} {'WR%':>7} {'PF':>7}")
    print("-" * 42)

    entry_comparison = {}
    for entry_type in ["day1", "day2"]:
        subset = gd_events[gd_events["gap_pct"] <= -5]
        trades = []
        for _, ev in subset.iterrows():
            t = ev["ticker"]
            if t not in all_daily:
                continue
            trade = run_m6e_trade(ev, all_daily[t], entry_day=entry_type)
            if trade:
                trades.append(trade)
        if trades:
            tdf_e = pd.DataFrame(trades)
            m = compute_metrics(tdf_e)
            flag = n_flag(m["n"])
            label = "Day1 Close" if entry_type == "day1" else "Day2 Open"
            print(f"{label:>10} {m['n']:>5} {m['mean']:>+7.2f}% {m['wr']:>6.1f}% {m['pf']:>6.2f}{flag}")
            entry_comparison[entry_type] = m
    print()

    # Chart
    fig, ax = plt.subplots(figsize=(10, 6))
    labels = []
    pfs = []
    ns = []
    for vname in variants:
        for gf in gap_floors:
            key = f"{vname}_{gf}"
            if key in variant_results and variant_results[key]["n"] > 0:
                labels.append(f"{vname}\n(gap<={gf}%)")
                pfs.append(variant_results[key]["pf"])
                ns.append(variant_results[key]["n"])

    if labels:
        colors = ["green" if p >= 1.5 else ("orange" if p >= 1.0 else "red") for p in pfs]
        ax.bar(range(len(labels)), pfs, color=colors, edgecolor="black")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, fontsize=7, rotation=45, ha="right")
        for i, (p, n) in enumerate(zip(pfs, ns)):
            ax.text(i, p + 0.05, f"N={n}", ha="center", fontsize=7)
        ax.axhline(1.0, color="gray", linestyle=":", label="Breakeven")
        ax.axhline(2.72, color="blue", linestyle="--", alpha=0.5, label="Module 6 baseline")
        ax.set_ylabel("Profit Factor")
        ax.set_title("ANT-3B: Module 6E Variants — Profit Factor")
        ax.legend()
    plt.tight_layout()
    fig.savefig(OUTPUT_DIR / "ant3_m6e_variants.png", dpi=150)
    plt.close(fig)
    print("  Saved ant3_m6e_variants.png")

    return {"variants": variant_results, "entry_comparison": entry_comparison}


def load_m5_data():
    """Load M5 regular-session bars."""
    M5_DIR = Path("backtest_output")
    all_m5 = {}
    tickers = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA",
        "TSLA", "AMD", "AVGO", "TSM", "MU", "COST",
        "COIN", "MARA", "C", "GS", "V", "BA", "JPM",
        "BABA", "BIDU", "PLTR",
    ]
    for ticker in tickers:
        fpath = M5_DIR / f"{ticker}_m5_regsess_FIXED.csv"
        if not fpath.exists():
            fpath = M5_DIR / f"{ticker}_m5_regsess.csv"
        if not fpath.exists():
            continue
        df = pd.read_csv(fpath, parse_dates=["Datetime"])
        df = df.rename(columns={"Datetime": "datetime"})
        df["date"] = df["datetime"].dt.date
        df["time"] = df["datetime"].dt.strftime("%H:%M")
        df = df.sort_values("datetime").reset_index(drop=True)
        all_m5[ticker] = df
    return all_m5


def synthesize_4h_bars(m5_df):
    """Synthesize 4H bars from M5 data.
    Bar 1: 09:30-13:25 ET -> close at 13:25
    Bar 2: 13:30-15:55 ET -> close at 15:55
    """
    bars = []
    for date, day_df in m5_df.groupby("date"):
        if len(day_df) < 10:
            continue
        # Bar 1: 09:30 to 13:25
        bar1 = day_df[day_df["time"] <= "13:25"]
        # Bar 2: 13:30 to 15:55
        bar2 = day_df[day_df["time"] >= "13:30"]

        if len(bar1) > 0:
            bars.append({
                "date": date, "bar_num": 1,
                "open": bar1.iloc[0]["Open"], "high": bar1["High"].max(),
                "low": bar1["Low"].min(), "close": bar1.iloc[-1]["Close"],
                "volume": bar1["Volume"].sum(),
            })
        if len(bar2) > 0:
            bars.append({
                "date": date, "bar_num": 2,
                "open": bar2.iloc[0]["Open"], "high": bar2["High"].max(),
                "low": bar2["Low"].min(), "close": bar2.iloc[-1]["Close"],
                "volume": bar2["Volume"].sum(),
            })
    return pd.DataFrame(bars)


def test_c(events, all_m5):
    print("=" * 70)
    print("TEST C: MODULE 6 GAP UPPER BOUND (M5 DATA)")
    print("=" * 70)

    # Load earnings dates for exclusion
    conn = sqlite3.connect(DB_PATH)
    earn_df = pd.read_sql("SELECT ticker, earnings_date FROM earnings_calendar", conn)
    conn.close()
    earn_df["earnings_date"] = pd.to_datetime(earn_df["earnings_date"]).dt.date
    earnings_dates = set()
    for _, r in earn_df.iterrows():
        ed = r["earnings_date"]
        earnings_dates.add((r["ticker"], ed))
        # +/- 1 day
        from datetime import timedelta
        earnings_dates.add((r["ticker"], ed - timedelta(days=1)))
        earnings_dates.add((r["ticker"], ed + timedelta(days=1)))

    # Build 4H bars and find gap events
    all_events = []
    for ticker, m5_df in all_m5.items():
        bars_4h = synthesize_4h_bars(m5_df)
        if len(bars_4h) < 4:
            continue

        trading_days = sorted(bars_4h["date"].unique())

        for i in range(1, len(trading_days)):
            curr_date = trading_days[i]
            prev_date = trading_days[i - 1]

            # Check earnings exclusion
            if (ticker, curr_date) in earnings_dates:
                continue

            prev_bar2 = bars_4h[(bars_4h["date"] == prev_date) & (bars_4h["bar_num"] == 2)]
            curr_bar1 = bars_4h[(bars_4h["date"] == curr_date) & (bars_4h["bar_num"] == 1)]
            curr_bar2 = bars_4h[(bars_4h["date"] == curr_date) & (bars_4h["bar_num"] == 2)]

            if len(prev_bar2) == 0 or len(curr_bar1) == 0:
                continue

            prior_close = prev_bar2.iloc[0]["close"]
            day_open = curr_bar1.iloc[0]["open"]
            bar1_close = curr_bar1.iloc[0]["close"]

            if prior_close <= 0:
                continue

            gap_pct = (day_open - prior_close) / prior_close * 100

            # Module 6 conditions: gap <= -4%, LONG only
            if gap_pct > -4.0:
                continue

            # Gap midpoint
            midpoint = (prior_close + day_open) / 2.0

            # Entry guard: entry < midpoint
            if bar1_close >= midpoint:
                continue

            # Simulate trade: entry at bar1_close, exit at midpoint or 15 4H bars max
            entry_price = bar1_close
            exit_price = None
            exit_reason = None
            bars_held = 0

            # Check rest of day (bar2)
            if len(curr_bar2) > 0:
                bars_held += 1
                if curr_bar2.iloc[0]["close"] >= midpoint:
                    exit_price = midpoint
                    exit_reason = "midpoint"

            if exit_price is None:
                # Forward days
                for j in range(i + 1, min(i + 8, len(trading_days))):  # ~15 4H bars = 7.5 days
                    fwd_date = trading_days[j]
                    fwd_bars = bars_4h[bars_4h["date"] == fwd_date].sort_values("bar_num")
                    for _, bar in fwd_bars.iterrows():
                        bars_held += 1
                        if bar["close"] >= midpoint:
                            exit_price = midpoint
                            exit_reason = "midpoint"
                            break
                    if exit_price is not None:
                        break

            if exit_price is None and bars_held > 0:
                # Find last bar
                last_j = min(i + 7, len(trading_days) - 1)
                last_bars = bars_4h[bars_4h["date"] == trading_days[last_j]].sort_values("bar_num")
                if len(last_bars) > 0:
                    exit_price = last_bars.iloc[-1]["close"]
                    exit_reason = "max_hold"

            if exit_price is None:
                continue

            ret = (exit_price - entry_price) / entry_price * 100
            all_events.append({
                "ticker": ticker, "date": str(curr_date), "gap_pct": gap_pct,
                "entry": entry_price, "exit": exit_price, "return_pct": ret,
                "reason": exit_reason, "bars_held": bars_held,
            })

    edf = pd.DataFrame(all_events)
    print(f"Module 6-eligible gap events (non-earnings, gap <= -4%): N={len(edf)}")
    print()

    if edf.empty:
        print("No events found.")
        return {}

    # Gap bucket analysis
    print("--- Module 6 PF by Gap Severity Bucket ---")
    gap_buckets = [
        ("-4% to -7%", -7, -4), ("-7% to -10%", -10, -7),
        ("-10% to -15%", -15, -10), ("< -15%", -999, -15),
        ("ALL", -999, -4),
    ]

    print(f"{'Bucket':<16} {'N':>5} {'Mean%':>8} {'WR%':>7} {'PF':>7} {'AvgBars':>8}")
    print("-" * 56)

    bucket_results = {}
    for label, lo, hi in gap_buckets:
        if lo == -999 and hi == -4:
            sub = edf
        elif lo == -999:
            sub = edf[edf["gap_pct"] < hi]
        else:
            sub = edf[(edf["gap_pct"] >= lo) & (edf["gap_pct"] < hi)]
        n = len(sub)
        if n == 0:
            continue
        m = compute_metrics(sub)
        avg_bars = sub["bars_held"].mean()
        flag = n_flag(n)
        print(f"{label:<16} {m['n']:>5} {m['mean']:>+7.2f}% {m['wr']:>6.1f}% {m['pf']:>6.2f} {avg_bars:>7.1f}{flag}")
        bucket_results[label] = {**m, "avg_bars": round(avg_bars, 1)}
    print()

    # Gap cap test
    print("--- Module 6 with Gap Cap ---")
    print(f"{'Config':<25} {'N':>5} {'Mean%':>8} {'WR%':>7} {'PF':>7}")
    print("-" * 55)

    cap_results = {}
    for cap_label, cap_val in [("no cap (current)", 999), ("cap -10%", -10), ("cap -12%", -12), ("cap -15%", -15)]:
        if cap_val == 999:
            sub = edf
        else:
            sub = edf[edf["gap_pct"] >= cap_val]
        n = len(sub)
        if n == 0:
            continue
        m = compute_metrics(sub)
        flag = n_flag(n)
        print(f"{'gap>=-4%, ' + cap_label:<25} {m['n']:>5} {m['mean']:>+7.2f}% {m['wr']:>6.1f}% {m['pf']:>6.2f}{flag}")
        cap_results[cap_label] = m
    print()

    # Examine extreme-gap losers
    extreme_losers = edf[(edf["gap_pct"] < -10) & (edf["return_pct"] < 0)]
    if len(extreme_losers) > 0:
        print("--- Extreme Gap Losers (gap < -10%, lost money) ---")
        for _, row in extreme_losers.iterrows():
            print(f"  {row['ticker']} {row['date']}: gap={row['gap_pct']:.1f}%, ret={row['return_pct']:+.1f}%, exit={row['reason']}")
    else:
        print("No extreme-gap losers (gap < -10%).")
    print()

    # Chart
    labels_c = []
    pfs_c = []
    ns_c = []
    for label, _, _ in gap_buckets:
        if label in bucket_results and bucket_results[label]["n"] > 0:
            labels_c.append(f"{label}\n(N={bucket_results[label]['n']})")
            pfs_c.append(bucket_results[label]["pf"])

    if labels_c:
        fig, ax = plt.subplots(figsize=(10, 6))
        colors = ["green" if p >= 1.5 else ("orange" if p >= 1.0 else "red") for p in pfs_c]
        ax.bar(range(len(labels_c)), pfs_c, color=colors, edgecolor="black")
        ax.set_xticks(range(len(labels_c)))
        ax.set_xticklabels(labels_c)
        ax.axhline(1.0, color="gray", linestyle=":")
        ax.axhline(2.72, color="blue", linestyle="--", alpha=0.5, label="M6 shadow PF=2.72")
        ax.set_ylabel("Profit Factor")
        ax.set_title("ANT-3C: Module 6 PF by Gap Severity (Non-Earnings)")
        ax.legend()
        plt.tight_layout()
        fig.savefig(OUTPUT_DIR / "ant3_m6_gap_buckets.png", dpi=150)
        plt.close(fig)
        print("  Saved ant3_m6_gap_buckets.png")

    return {"buckets": bucket_results, "caps": cap_results}


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 70)
    print("ANT-3: ANT-DERIVED MODULE IMPROVEMENTS")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)
    print()

    # Load data
    print("Loading events from ANT-1...")
    events = load_events()
    print(f"  {len(events)} events loaded")

    print("Loading daily price data...")
    all_daily = {}
    tickers = events["ticker"].unique()
    for t in tickers:
        df = load_daily(t)
        if df is not None:
            all_daily[t] = df
    print(f"  {len(all_daily)} tickers with daily data")
    print()

    results = {}

    # Test A
    results["test_a"] = test_a(events, all_daily)

    # Test B
    results["test_b"] = test_b(events, all_daily)

    # Test C
    print("Loading M5 data for Test C...")
    all_m5 = load_m5_data()
    print(f"  {len(all_m5)} tickers with M5 data")
    print()
    results["test_c"] = test_c(events, all_m5)

    # Save summary
    results["meta"] = {
        "date_run": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "n_events": len(events),
        "n_tickers_daily": len(all_daily),
        "n_tickers_m5": len(all_m5),
    }
    with open(OUTPUT_DIR / "ANT3_summary.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("Saved ANT3_summary.json")
    print()
    print("Done. All outputs in backtest_output/ant3/")


if __name__ == "__main__":
    main()
