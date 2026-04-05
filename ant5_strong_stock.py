#!/usr/bin/env python3
"""
ANT-5: Strong Stock — Earnings Gap-UP Dip-Buy Backtest
Tests 0-7 (daily data) + Tests 8-11 (M5 intraday).
Combined into single script for efficiency.
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

OUTPUT_DIR = Path("backtest_output/ant5")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = "/var/lib/market-system/market.db"
DAILY_DIR = Path("backtester/data/daily")
M5_DIR = Path("backtest_output")

GAP_THRESHOLD = 5.0  # minimum gap-UP %

def n_flag(n):
    if n < 10: return " **ANECDOTAL**"
    elif n < 20: return " *LOW N*"
    return ""

def load_events():
    df = pd.read_csv("backtest_output/ant1/events.csv")
    df["day1_date"] = pd.to_datetime(df["day1_date"])
    # Add strength metrics for gap-UP events
    df["gap_size_up"] = df["day1_open"] - df["prior_close"]  # positive for gap-UP
    # gap_retention: how much of gap retained at close
    mask_up = df["gap_pct"] > 0
    df.loc[mask_up, "gap_retention"] = (
        (df.loc[mask_up, "day1_close"] - df.loc[mask_up, "prior_close"]) /
        (df.loc[mask_up, "day1_open"] - df.loc[mask_up, "prior_close"])
    )
    # strength_ratio: close relative to high
    df.loc[mask_up, "strength_ratio"] = (
        (df.loc[mask_up, "day1_close"] - df.loc[mask_up, "prior_close"]) /
        (df.loc[mask_up, "day1_high"] - df.loc[mask_up, "prior_close"])
    )
    # pullback_depth: max intraday giveback from high
    df.loc[mask_up, "pullback_depth"] = (
        (df.loc[mask_up, "day1_high"] - df.loc[mask_up, "day1_low"]) /
        (df.loc[mask_up, "day1_high"] - df.loc[mask_up, "prior_close"])
    )
    return df

def load_daily(ticker):
    fpath = DAILY_DIR / f"{ticker}_daily.csv"
    if not fpath.exists(): return None
    df = pd.read_csv(fpath, header=[0,1], index_col=0, parse_dates=True)
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

def compute_metrics(rets):
    if len(rets) == 0: return {"n":0}
    n = len(rets)
    wins = rets[rets > 0].sum()
    losses = abs(rets[rets <= 0].sum())
    return {"n": int(n), "mean": round(rets.mean(), 3),
            "wr": round((rets > 0).mean() * 100, 1),
            "pf": round(wins / losses if losses > 0 else float("inf"), 2)}


# ============================================================
# TEST 0
# ============================================================
def test0(events):
    print("=" * 70)
    print("TEST 0: GAP-UP UNIVERSE STATISTICS")
    print("=" * 70)
    total = len(events)
    for thresh in [3, 5, 7, 10, 15]:
        n = (events["gap_pct"] >= thresh).sum()
        print(f"  Gap >= +{thresh}%: {n} ({n/total*100:.1f}%)")
    n_dn = (events["gap_pct"] <= -5).sum()
    n_up = (events["gap_pct"] >= 5).sum()
    print(f"\n  Symmetry: gap-DOWN<=-5% = {n_dn}, gap-UP>=+5% = {n_up}")
    gu = events[events["gap_pct"] >= 5]
    print(f"\n  Gap-UP tickers: {sorted(gu['ticker'].unique())}")
    print(f"  Per ticker: {gu['ticker'].value_counts().to_dict()}")
    print()
    return {"gap_up_5": int(n_up), "gap_down_5": int(n_dn)}


# ============================================================
# TEST 1: Strength Ratio vs Drift
# ============================================================
def test1(events):
    print("=" * 70)
    print("TEST 1: STRENGTH RATIO vs MULTI-DAY DRIFT")
    print("=" * 70)
    gu = events[events["gap_pct"] >= GAP_THRESHOLD].dropna(subset=["gap_retention","drift_5d"]).copy()
    print(f"Gap-UP events (>= +{GAP_THRESHOLD}%): N={len(gu)}")

    buckets = [
        ("A (>1.00, extended)", lambda x: x > 1.0),
        ("B (0.80-1.00)", lambda x: (x >= 0.80) & (x <= 1.0)),
        ("C (0.60-0.80)", lambda x: (x >= 0.60) & (x < 0.80)),
        ("D (0.40-0.60)", lambda x: (x >= 0.40) & (x < 0.60)),
        ("E (<0.40, faded)", lambda x: x < 0.40),
    ]

    print(f"\n{'Bucket':<22} {'N':>4} {'d1':>8} {'d3':>8} {'d5':>8} {'d10':>8} {'med5':>8} {'WR5':>7} {'std5':>7}")
    print("-" * 88)

    results = {}
    for name, cond in buckets:
        sub = gu[cond(gu["gap_retention"])]
        n = len(sub)
        if n == 0: continue
        d1 = sub["drift_1d"].mean(); d3 = sub["drift_3d"].mean()
        d5 = sub["drift_5d"].mean(); d10 = sub["drift_10d"].mean()
        med5 = sub["drift_5d"].median()
        wr5 = (sub["drift_5d"] > 0).mean() * 100
        std5 = sub["drift_5d"].std()
        flag = n_flag(n)
        print(f"{name:<22} {n:>4} {d1:>+7.2f}% {d3:>+7.2f}% {d5:>+7.2f}% {d10:>+7.2f}% {med5:>+7.2f}% {wr5:>6.1f}% {std5:>6.2f}%{flag}")
        results[name] = {"n": int(n), "d1": round(d1,3), "d5": round(d5,3), "wr5": round(wr5,1)}

    # Spearman
    valid = gu.dropna(subset=["gap_retention","drift_1d","drift_5d"])
    if len(valid) >= 5:
        rho1, p1 = stats.spearmanr(valid["gap_retention"], valid["drift_1d"])
        rho5, p5 = stats.spearmanr(valid["gap_retention"], valid["drift_5d"])
        print(f"\nSpearman (gap_retention vs drift_1d): rho={rho1:+.4f}, p={p1:.4f}")
        print(f"Spearman (gap_retention vs drift_5d): rho={rho5:+.4f}, p={p5:.4f}")
    else:
        rho1 = rho5 = p1 = p5 = np.nan
    print()
    return {"buckets": results, "rho_1d": round(rho1,4) if not np.isnan(rho1) else None,
            "rho_5d": round(rho5,4) if not np.isnan(rho5) else None}


# ============================================================
# TEST 2: Sawtooth Check
# ============================================================
def test2(events):
    print("=" * 70)
    print("TEST 2: SAWTOOTH CHECK — INCREMENTAL DRIFT BY DAY")
    print("=" * 70)
    gu = events[events["gap_pct"] >= GAP_THRESHOLD].dropna(subset=["drift_1d","drift_5d"]).copy()

    strength_groups = [
        ("Strong (ret>=0.80)", gu[gu["gap_retention"] >= 0.80]),
        ("Medium (0.60-0.80)", gu[(gu["gap_retention"] >= 0.60) & (gu["gap_retention"] < 0.80)]),
        ("Weak (<0.60)", gu[gu["gap_retention"] < 0.60]),
        ("ALL gap-UP", gu),
    ]

    # Cumulative
    drift_cols = ["drift_1d","drift_2d","drift_3d","drift_5d","drift_7d","drift_10d"]
    hold_labels = ["1d","2d","3d","5d","7d","10d"]

    print("--- Cumulative Drift ---")
    print(f"{'Group':<22} {'N':>4}", end="")
    for h in hold_labels: print(f" {h:>8}", end="")
    print()
    print("-" * 78)

    cum_results = {}
    for gname, gsub in strength_groups:
        n = len(gsub)
        if n == 0: continue
        flag = n_flag(n)
        print(f"{gname:<22} {n:>4}", end="")
        row = {"n": int(n)}
        for dc, hl in zip(drift_cols, hold_labels):
            v = gsub[dc].mean()
            print(f" {v:>+7.2f}%", end="")
            row[hl] = round(v, 3)
        print(flag)
        cum_results[gname] = row

    # Incremental
    print("\n--- Incremental Drift (marginal value of extra day) ---")
    print(f"{'Group':<22} {'N':>4} {'i_1d':>8} {'i_2d':>8} {'i_3d':>8} {'i_4-5d':>8}")
    print("-" * 58)

    incr_results = {}
    for gname, gsub in strength_groups:
        n = len(gsub)
        if n == 0: continue
        d1 = gsub["drift_1d"].mean()
        d2 = gsub["drift_2d"].mean()
        d3 = gsub["drift_3d"].mean()
        d5 = gsub["drift_5d"].mean()
        i1 = d1; i2 = d2 - d1; i3 = d3 - d2; i5 = (d5 - d3) / 2
        flag = n_flag(n)
        print(f"{gname:<22} {n:>4} {i1:>+7.2f}% {i2:>+7.2f}% {i3:>+7.2f}% {i5:>+7.2f}%{flag}")
        incr_results[gname] = {"n":int(n),"i1":round(i1,3),"i2":round(i2,3),"i3":round(i3,3),"i5":round(i5,3)}
    print()
    return {"cumulative": cum_results, "incremental": incr_results}


# ============================================================
# TEST 3: Pullback Threshold
# ============================================================
def test3(events):
    print("=" * 70)
    print("TEST 3: 40% STRENGTH LOSS THRESHOLD")
    print("=" * 70)
    gu = events[events["gap_pct"] >= GAP_THRESHOLD].dropna(subset=["pullback_depth","drift_1d","drift_5d"]).copy()
    print(f"Events with pullback data: N={len(gu)}")

    thresholds = [0.20, 0.30, 0.40, 0.50, 0.60, 1.01]  # 1.01 = ALL
    print(f"\n{'Max Pullback <':>16} {'N':>4} {'d1':>8} {'d5':>8} {'WR1':>7} {'WR5':>7}")
    print("-" * 50)

    results = {}
    for t in thresholds:
        label = f"<{t:.0%}" if t < 1.0 else "ALL"
        sub = gu[gu["pullback_depth"] < t] if t < 1.0 else gu
        n = len(sub)
        if n == 0: continue
        d1 = sub["drift_1d"].mean(); d5 = sub["drift_5d"].mean()
        wr1 = (sub["drift_1d"] > 0).mean() * 100
        wr5 = (sub["drift_5d"] > 0).mean() * 100
        flag = n_flag(n)
        print(f"{label:>16} {n:>4} {d1:>+7.2f}% {d5:>+7.2f}% {wr1:>6.1f}% {wr5:>6.1f}%{flag}")
        results[label] = {"n":int(n),"d1":round(d1,3),"d5":round(d5,3),"wr1":round(wr1,1),"wr5":round(wr5,1)}
    print()
    return results


# ============================================================
# TEST 4: Gap Size Interaction
# ============================================================
def test4(events):
    print("=" * 70)
    print("TEST 4: GAP SIZE x STRENGTH INTERACTION")
    print("=" * 70)
    gu = events[events["gap_pct"] >= 3].dropna(subset=["gap_retention","drift_1d","drift_5d"]).copy()

    gap_b = [("+3% to +5%", 3, 5), ("+5% to +10%", 5, 10), ("+10% to +15%", 10, 15), ("> +15%", 15, 999)]
    str_b = [("Str>0.80", lambda x: x >= 0.80), ("Str 0.60-0.80", lambda x: (x>=0.60)&(x<0.80)),
             ("Str<0.60", lambda x: x < 0.60)]

    print(f"{'':>16}", end="")
    for gn, _, _ in gap_b: print(f"{gn:>22}", end="")
    print()
    print("-" * 104)

    results = {}
    for sn, sf in str_b:
        print(f"{sn:<16}", end="")
        for gn, glo, ghi in gap_b:
            mask = (gu["gap_pct"] >= glo) & ((gu["gap_pct"] < ghi) if ghi != 999 else True) & sf(gu["gap_retention"])
            sub = gu[mask]
            n = len(sub)
            if n > 0:
                d1 = sub["drift_1d"].mean(); d5 = sub["drift_5d"].mean()
                flag = n_flag(n)
                print(f" {d1:>+.1f}/{d5:>+.1f}% N={n:>2}{flag[:4]}", end="")
                results[f"{sn}|{gn}"] = {"d1":round(d1,3),"d5":round(d5,3),"n":int(n)}
            else:
                print(f"{'N/A':>22}", end="")
        print()
    print()
    return results


# ============================================================
# TEST 5: EPS Surprise Interaction
# ============================================================
def test5(events):
    print("=" * 70)
    print("TEST 5: EPS SURPRISE x STRENGTH INTERACTION")
    print("=" * 70)
    gu = events[events["gap_pct"] >= GAP_THRESHOLD].dropna(subset=["gap_retention","drift_5d"]).copy()
    gu["abs_surp"] = gu["eps_surprise_pct"].abs()
    has = gu.dropna(subset=["abs_surp"])
    print(f"Events with surprise data: {len(has)} / {len(gu)}")
    if len(has) < 5:
        print("Insufficient data.\n")
        return {}

    surp_b = [("<5%", lambda x: x<5), ("5-15%", lambda x: (x>=5)&(x<15)), (">15%", lambda x: x>=15)]
    str_b = [("Str>0.80", lambda x: x>=0.80), ("Str 0.60-0.80", lambda x: (x>=0.60)&(x<0.80)),
             ("Str<0.60", lambda x: x<0.60)]

    print(f"{'':>16}", end="")
    for sn, _ in surp_b: print(f"{'|Surp| '+sn:>22}", end="")
    print()
    print("-" * 82)

    results = {}
    for strn, strf in str_b:
        print(f"{strn:<16}", end="")
        for sn, sf in surp_b:
            mask = sf(has["abs_surp"]) & strf(has["gap_retention"])
            sub = has[mask]
            n = len(sub)
            if n > 0:
                d5 = sub["drift_5d"].mean()
                flag = n_flag(n)
                print(f" {d5:>+6.2f}%(N={n:>2}){flag[:5]}", end="")
            else:
                print(f"{'N/A':>22}", end="")
        print()
    print()
    return results


# ============================================================
# TEST 6: Strategy Backtest (Daily)
# ============================================================
def test6(events, all_daily):
    print("=" * 70)
    print("TEST 6: STRONG STOCK DIP-BUY STRATEGY BACKTEST")
    print("=" * 70)

    gu_all = events[events["gap_pct"] >= GAP_THRESHOLD].copy()

    variants = {
        "V1 ANT Basic": gu_all[gu_all["gap_retention"] >= 0.60],
        "V2 +BigSurp": gu_all[(gu_all["gap_retention"] >= 0.60) & (gu_all["eps_surprise_pct"].abs() >= 10)],
        "V3 Fade Buy": gu_all[(gu_all["day1_low"] < gu_all["day1_open"]) & (gu_all["day1_close"] > gu_all["day1_open"])],
        "V4 Extending": gu_all[gu_all["day1_close"] > gu_all["day1_open"]],
    }

    exit_types = [("1d", 1), ("2d", 2), ("3d", 3), ("5d", 5)]

    print(f"{'Variant':<16} {'Exit':>5} {'N':>4} {'Mean%':>8} {'WR':>6} {'PF':>7}")
    print("-" * 52)

    results = {}
    for vname, vsub in variants.items():
        for exit_label, exit_fd in exit_types:
            trades = []
            for _, ev in vsub.iterrows():
                t = ev["ticker"]
                if t not in all_daily: continue
                daily = all_daily[t]
                idx = daily.index
                d1 = pd.Timestamp(ev["day1_date"])
                if d1 not in idx: continue
                pos = idx.get_loc(d1)
                if pos + exit_fd >= len(idx): continue

                entry = ev["day1_close"]
                exit_price = daily.iloc[pos + exit_fd]["Close"]
                ret = (exit_price - entry) / entry * 100
                trades.append(ret)

            if not trades: continue
            rets = pd.Series(trades)
            m = compute_metrics(rets)
            flag = n_flag(m["n"])
            print(f"{vname:<16} {exit_label:>5} {m['n']:>4} {m['mean']:>+7.2f}% {m['wr']:>5.1f}% {m['pf']:>6.2f}{flag}")
            results[f"{vname}_{exit_label}"] = m
    print()
    return results


# ============================================================
# TEST 7: Day of Peak
# ============================================================
def test7(events):
    print("=" * 70)
    print("TEST 7: DAY OF PEAK — WHEN DOES GAP-UP MOMENTUM EXHAUST?")
    print("=" * 70)
    gu = events[(events["gap_pct"] >= GAP_THRESHOLD) & (events["gap_retention"] >= 0.60)].dropna(subset=["trajectory"]).copy()
    print(f"Strong gap-UP events (gap>=5%, retention>=0.60): N={len(gu)}")

    peak_days = []
    peak_rets = []
    for _, ev in gu.iterrows():
        try:
            traj = json.loads(ev["trajectory"])
        except: continue
        if len(traj) < 2: continue
        mx = np.argmax(traj)
        peak_days.append(mx)
        peak_rets.append(traj[mx])

    if not peak_days:
        print("No trajectories.\n")
        return {}

    peak_days = np.array(peak_days)
    peak_rets = np.array(peak_rets)

    groups = [(0,0,"Day 0 (gap day)"),(1,1,"Day 1"),(2,2,"Day 2"),(3,3,"Day 3"),
              (4,5,"Day 4-5"),(6,10,"Day 6-10")]

    print(f"\n{'Day of Peak':<18} {'Count':>6} {'%':>7} {'Mean Max Ret':>14}")
    print("-" * 48)
    peak_dist = {}
    for lo,hi,label in groups:
        mask = (peak_days >= lo) & (peak_days <= hi)
        n = int(mask.sum())
        pct = n / len(peak_days) * 100
        mr = peak_rets[mask].mean() if n > 0 else 0
        print(f"{label:<18} {n:>6} {pct:>6.1f}% {mr:>+13.2f}%")
        peak_dist[label] = {"n": n, "pct": round(pct,1)}

    mode = int(pd.Series(peak_days).mode().iloc[0])
    mean = peak_days.mean()
    print(f"\nMode: Day {mode}, Mean: Day {mean:.1f}")
    print()

    # Chart
    fig, ax = plt.subplots(figsize=(10,6))
    ax.hist(peak_days, bins=range(12), align="left", color="blue", alpha=0.7, edgecolor="black")
    ax.set_xlabel("Day of Maximum Close (0 = gap day)")
    ax.set_ylabel("Count")
    ax.set_title("ANT-5: When Does Gap-UP Momentum Peak?")
    ax.set_xticks(range(11))
    plt.tight_layout()
    fig.savefig(OUTPUT_DIR / "ant5_day_of_peak.png", dpi=150)
    plt.close(fig)
    print("  Saved ant5_day_of_peak.png")

    return {"peak_dist": peak_dist, "mode": mode, "mean": round(mean,1)}


# ============================================================
# M5 TESTS (8-11)
# ============================================================
AMC_TICKERS = {"AAPL","MSFT","GOOGL","AMZN","META","NVDA","TSLA","AMD",
               "COIN","ARM","SMCI","PLTR","MSTR","MARA","AVGO","TSM",
               "V","MU","INTC","COST"}
BMO_TICKERS = {"JD","BIDU","BABA","C","GS","BA","JPM"}

CURVE_TIMES = ["10:00","10:30","12:00","13:00","13:30","16:00"]
CURVE_BAR_STARTS = ["09:55","10:25","11:55","12:55","13:25","15:55"]


def test8(events, all_m5):
    print("=" * 70)
    print("TEST 8: M5 INTRADAY STRENGTH CURVE")
    print("=" * 70)

    conn = sqlite3.connect(DB_PATH)
    earn_df = pd.read_sql("SELECT * FROM earnings_calendar", conn)
    conn.close()
    earn_df["earnings_date"] = pd.to_datetime(earn_df["earnings_date"])

    m5_events = []
    for _, er in earn_df.iterrows():
        ticker = er["ticker"]
        if ticker not in all_m5: continue
        m5 = all_m5[ticker]
        ed = er["earnings_date"].date()
        timing = er.get("time_of_day", "Unknown")
        if timing not in ("BMO","AMC"):
            timing = "AMC" if ticker in AMC_TICKERS else ("BMO" if ticker in BMO_TICKERS else "AMC")

        tdays = sorted(m5["date"].unique())
        day1 = ed if timing == "BMO" else ([d for d in tdays if d > ed] or [None])[0]
        if day1 is None or day1 not in tdays: continue
        d1i = tdays.index(day1)
        if d1i < 1 or d1i + 5 >= len(tdays): continue

        prior_bars = m5[m5["date"] == tdays[d1i-1]]
        if len(prior_bars) == 0: continue
        prior_close = prior_bars.iloc[-1]["Close"]

        day1_bars = m5[m5["date"] == day1]
        if len(day1_bars) < 10: continue
        day1_open = day1_bars.iloc[0]["Open"]
        if prior_close <= 0 or day1_open <= 0: continue

        gap_pct = (day1_open - prior_close) / prior_close * 100
        if gap_pct < 3: continue  # gap-UP only

        gap_size = day1_open - prior_close
        if gap_size <= 0: continue

        # Strength curve
        curve = {}
        for label, bt in zip(CURVE_TIMES, CURVE_BAR_STARTS):
            bars_at = day1_bars[day1_bars["time"] <= bt]
            if len(bars_at) > 0:
                curve[label] = (bars_at.iloc[-1]["Close"] - prior_close) / gap_size
            else:
                curve[label] = np.nan

        # Forward closes
        day1_close = day1_bars.iloc[-1]["Close"]
        fwd = {}
        for fd in [1,2,3,5]:
            if d1i + fd < len(tdays):
                fb = m5[m5["date"] == tdays[d1i+fd]]
                if len(fb) > 0: fwd[f"drift_{fd}d"] = (fb.iloc[-1]["Close"] - day1_close) / day1_close * 100

        # Pullback detection
        running_high = -float("inf")
        pullback_info = None
        for _, bar in day1_bars.iterrows():
            if bar["High"] > running_high:
                running_high = bar["High"]
            drawdown = (running_high - bar["Low"]) / running_high * 100 if running_high > 0 else 0
            if drawdown >= 1.0 and pullback_info is None and bar["time"] >= "10:00":
                pullback_info = {
                    "time": bar["time"],
                    "depth_pct": drawdown,
                    "depth_of_gain": (running_high - bar["Low"]) / (running_high - prior_close) if running_high > prior_close else 0,
                    "low": bar["Low"],
                }

        ev = {"ticker": ticker, "date": str(day1), "gap_pct": gap_pct,
              "day1_close": day1_close, "prior_close": prior_close, "day1_open": day1_open}
        for k, v in curve.items(): ev[f"str_{k}"] = v
        ev.update(fwd)
        if pullback_info:
            ev["pb_time"] = pullback_info["time"]
            ev["pb_depth"] = pullback_info["depth_pct"]
            ev["pb_depth_gain"] = pullback_info["depth_of_gain"]
            ev["pb_low"] = pullback_info["low"]
        m5_events.append(ev)

    mdf = pd.DataFrame(m5_events)
    if mdf.empty:
        print("No M5 gap-UP events.\n")
        return {}
    print(f"M5 gap-UP events (>= +3%): N={len(mdf)}")

    # Strength curve by drift direction
    has_d5 = mdf.dropna(subset=["drift_5d"])
    ga = has_d5[has_d5["drift_5d"] > 0]
    gb = has_d5[has_d5["drift_5d"] <= 0]
    print(f"  Winners (5d up): N={len(ga)}, Losers: N={len(gb)}")
    print(f"\n{'Time':<8}", end="")
    for t in CURVE_TIMES: print(f"{t:>10}", end="")
    print()
    print("-" * 68)

    for label, grp in [("Winners", ga), ("Losers", gb)]:
        print(f"{label:<8}", end="")
        for t in CURVE_TIMES:
            col = f"str_{t}"
            v = grp[col].mean() if col in grp.columns else np.nan
            print(f"{v:>10.3f}", end="")
        print(f"  (N={len(grp)})")

    # Separation
    print(f"{'Sep':<8}", end="")
    best_sep = 0; best_t = None
    for t in CURVE_TIMES:
        col = f"str_{t}"
        sa = ga[col].mean() if col in ga.columns else 0
        sb = gb[col].mean() if col in gb.columns else 0
        sep = sa - sb
        if abs(sep) > abs(best_sep): best_sep = sep; best_t = t
        print(f"{sep:>+10.3f}", end="")
    print(f"\n\nBest separation: {best_t} ({best_sep:+.3f})")

    # Spearman by time
    print(f"\n{'Time':<8} {'rho vs d1':>12} {'p':>8} {'rho vs d5':>12} {'p':>8}")
    print("-" * 52)
    for t in CURVE_TIMES:
        col = f"str_{t}"
        v1 = has_d5.dropna(subset=[col,"drift_1d"])
        v5 = has_d5.dropna(subset=[col,"drift_5d"])
        r1 = p1 = r5 = p5 = np.nan
        if len(v1) >= 5: r1, p1 = stats.spearmanr(v1[col], v1["drift_1d"])
        if len(v5) >= 5: r5, p5 = stats.spearmanr(v5[col], v5["drift_5d"])
        print(f"{t:<8} {r1:>+12.4f} {p1:>8.4f} {r5:>+12.4f} {p5:>8.4f}")
    print()

    # Chart
    fig, ax = plt.subplots(figsize=(10,7))
    for label, grp, color in [("Winners (5d up)", ga, "green"), ("Losers (5d dn)", gb, "red")]:
        means = [grp[f"str_{t}"].mean() for t in CURVE_TIMES]
        ax.plot(range(len(CURVE_TIMES)), means, "o-", color=color, linewidth=2, markersize=8,
                label=f"{label} (N={len(grp)})")
    ax.set_xticks(range(len(CURVE_TIMES))); ax.set_xticklabels(CURVE_TIMES)
    ax.set_xlabel("Time (ET)"); ax.set_ylabel("Strength Ratio (fraction of gap retained)")
    ax.set_title("ANT-5: Intraday Strength Curve — Gap-UP Events")
    ax.legend(); ax.grid(True, alpha=0.3)
    plt.tight_layout()
    fig.savefig(OUTPUT_DIR / "ant5_strength_curve.png", dpi=150)
    plt.close(fig)
    print("  Saved ant5_strength_curve.png")

    # TEST 9: Pullback pattern
    print("\n" + "=" * 70)
    print("TEST 9: INTRADAY PULLBACK PATTERN")
    print("=" * 70)
    has_pb = mdf.dropna(subset=["pb_time"])
    print(f"Events with pullback >= 1%: {len(has_pb)} / {len(mdf)}")
    if len(has_pb) > 0:
        mins = has_pb["pb_time"].apply(lambda t: int(t[:2])*60+int(t[3:]))
        print(f"  Mean pullback time: {int(mins.mean()//60):02d}:{int(mins.mean()%60):02d} ET")
        print(f"  Median: {int(mins.median()//60):02d}:{int(mins.median()%60):02d} ET")
        print(f"  Mean depth: {has_pb['pb_depth'].mean():.2f}% from high")
        print(f"  Mean depth of gain: {has_pb['pb_depth_gain'].mean():.1%} of total gain")
        # Return from pullback to close
        has_pb_close = has_pb.dropna(subset=["pb_low"])
        if len(has_pb_close) > 0:
            pb_to_close = (has_pb_close["day1_close"] - has_pb_close["pb_low"]) / has_pb_close["pb_low"] * 100
            print(f"  Pullback-to-close return: mean {pb_to_close.mean():+.2f}%, WR {(pb_to_close>0).mean()*100:.0f}%")

    # TEST 10: M5 Dip-Buy
    print("\n" + "=" * 70)
    print("TEST 10: M5 DIP-BUY STRATEGY")
    print("=" * 70)
    # Simple: buy at pullback low + recovery confirmation, exit at close
    dip_buy = has_pb[has_pb["gap_pct"] >= 5].copy()
    print(f"Dip-buy candidates (gap>=5%, pullback detected): N={len(dip_buy)}")
    if len(dip_buy) > 0 and "pb_low" in dip_buy.columns:
        # Intraday return: pb_low to day1_close
        rets_intra = (dip_buy["day1_close"] - dip_buy["pb_low"]) / dip_buy["pb_low"] * 100
        m = compute_metrics(rets_intra)
        print(f"  Intraday (pb_low -> close): N={m['n']}, mean={m['mean']:+.2f}%, WR={m['wr']}%, PF={m['pf']}")

        for fd_label, fd_col in [("Day2","drift_1d"),("Day3","drift_2d"),("Day5","drift_5d")]:
            valid = dip_buy.dropna(subset=["pb_low", fd_col])
            if len(valid) == 0: continue
            # Return from day1_close (entry proxy) to forward
            m2 = compute_metrics(valid[fd_col])
            print(f"  {fd_label} (close->fwd): N={m2['n']}, mean={m2['mean']:+.2f}%, WR={m2['wr']}%, PF={m2['pf']}")
    print()

    # TEST 11: Symmetry comparison
    print("=" * 70)
    print("TEST 11: SYMMETRY — GAP-UP vs GAP-DOWN SAWTOOTH")
    print("=" * 70)

    # Load ANT-4 gap-down data from events
    ev_daily = load_events()
    gd = ev_daily[ev_daily["gap_pct"] <= -5].dropna(subset=["drift_1d","drift_5d"])
    gu_daily = ev_daily[ev_daily["gap_pct"] >= 5].dropna(subset=["drift_1d","drift_5d"])

    drift_cols = ["drift_1d","drift_2d","drift_3d","drift_5d","drift_10d"]
    labels = ["1d","2d","3d","5d","10d"]

    print(f"{'Metric':<12} {'Gap-UP (N={len(gu_daily)})':>22} {'Gap-DOWN (N={len(gd)})':>22} {'Symmetric?':>12}")
    print("-" * 72)

    sym_results = {}
    for dc, hl in zip(drift_cols, labels):
        up_v = gu_daily[dc].mean()
        dn_v = gd[dc].mean()
        # For symmetry: gap-DOWN positive drift = bounce (same direction as gap-UP continuation)
        sym = "YES" if (up_v > 0 and dn_v > 0) or (up_v < 0 and dn_v < 0) else "NO"
        print(f"{hl:<12} {up_v:>+21.2f}% {dn_v:>+21.2f}% {sym:>12}")
        sym_results[hl] = {"up": round(up_v,3), "down": round(dn_v,3)}

    # Sawtooth comparison
    print(f"\nIncremental:")
    up_incr = [gu_daily["drift_1d"].mean(),
               (gu_daily["drift_2d"]-gu_daily["drift_1d"]).mean(),
               (gu_daily["drift_3d"]-gu_daily["drift_2d"]).mean()]
    dn_incr = [gd["drift_1d"].mean(),
               (gd["drift_2d"]-gd["drift_1d"]).mean(),
               (gd["drift_3d"]-gd["drift_2d"]).mean()]
    for i, day in enumerate(["Day 1","Day 2","Day 3"]):
        print(f"  {day}: UP={up_incr[i]:+.2f}%, DOWN={dn_incr[i]:+.2f}%")
    print()

    # Chart: sawtooth comparison
    fig, ax = plt.subplots(figsize=(10,7))
    x_lab = ["D0","D1","D2","D3","D5","D10"]
    up_traj = [0] + [gu_daily[dc].mean() for dc in drift_cols]
    dn_traj = [0] + [gd[dc].mean() for dc in drift_cols]
    ax.plot(range(len(x_lab)), up_traj, "go-", linewidth=2, markersize=8,
            label=f"Gap-UP >= +5% (N={len(gu_daily)})")
    ax.plot(range(len(x_lab)), dn_traj, "rs-", linewidth=2, markersize=8,
            label=f"Gap-DOWN <= -5% (N={len(gd)})")
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_xticks(range(len(x_lab))); ax.set_xticklabels(x_lab)
    ax.set_xlabel("Hold Period"); ax.set_ylabel("Cumulative Drift (%)")
    ax.set_title("ANT-5: Gap-UP vs Gap-DOWN — Sawtooth Comparison")
    ax.legend(); ax.grid(True, alpha=0.3)
    plt.tight_layout()
    fig.savefig(OUTPUT_DIR / "ant5_sawtooth_comparison.png", dpi=150)
    plt.close(fig)
    print("  Saved ant5_sawtooth_comparison.png")

    return {"m5_events": len(mdf), "symmetry": sym_results}


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 70)
    print("ANT-5: STRONG STOCK — EARNINGS GAP-UP DIP-BUY BACKTEST")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)
    print()

    events = load_events()
    print(f"Loaded {len(events)} events")

    all_daily = {}
    for t in events["ticker"].unique():
        df = load_daily(t)
        if df is not None: all_daily[t] = df
    print(f"Daily data: {len(all_daily)} tickers")

    all_m5 = load_m5_data()
    print(f"M5 data: {len(all_m5)} tickers\n")

    results = {}
    results["test0"] = test0(events)
    results["test1"] = test1(events)
    results["test2"] = test2(events)
    results["test3"] = test3(events)
    results["test4"] = test4(events)
    results["test5"] = test5(events)
    results["test6"] = test6(events, all_daily)
    results["test7"] = test7(events)
    results["test8_11"] = test8(events, all_m5)

    results["meta"] = {"date_run": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "n_events": len(events), "n_gap_up_5": int((events["gap_pct"]>=5).sum())}

    with open(OUTPUT_DIR / "ANT5_summary.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("\nSaved ANT5_summary.json")
    print("Done. All outputs in backtest_output/ant5/")


if __name__ == "__main__":
    main()
