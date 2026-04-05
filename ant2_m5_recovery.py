#!/usr/bin/env python3
"""
ANT-2: Earnings Recovery Ratio — M5 Precision Test
Tests whether INTRADAY recovery trajectory (6-point curve from M5 bars)
predicts multi-day drift, where daily-bar recovery ratio (ANT-1) failed.
"""
import json
import sqlite3
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

# ============================================================
# CONFIGURATION
# ============================================================
OUTPUT_DIR = Path("backtest_output/ant2")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = "/var/lib/market-system/market.db"
M5_DIR = Path("backtest_output")  # *_m5_regsess_FIXED.csv files

TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA",
    "TSLA", "AMD", "SMCI", "PLTR", "AVGO", "ARM", "TSM",
    "MU", "INTC", "COST",
    "COIN", "MSTR", "MARA",
    "C", "GS", "V", "BA", "JPM",
    "BABA", "JD", "BIDU",
]

AMC_TICKERS = {
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD",
    "COIN", "ARM", "SMCI", "PLTR", "MSTR", "MARA", "AVGO", "TSM",
    "V", "MU", "INTC", "COST",
}
BMO_TICKERS = {"JD", "BIDU", "BABA", "C", "GS", "BA", "JPM"}

GAP_THRESHOLD = -3.0  # wider net for M5 (more events)
GAP_THRESHOLD_STRICT = -5.0  # for strategy backtest
FORWARD_DAYS = 5

# 6-point recovery curve times (ET, as HH:MM)
CURVE_TIMES = ["10:00", "10:30", "12:00", "13:00", "13:30", "16:00"]
# Map to M5 bar close times (bar at 09:55 closes at 10:00, etc.)
# We use the bar whose interval ENDS at that time, i.e. bar starting 5 min earlier
CURVE_BAR_STARTS = ["09:55", "10:25", "11:55", "12:55", "13:25", "15:55"]


# ============================================================
# PART 1: DATA LOADING
# ============================================================
def load_earnings():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM earnings_calendar", conn)
    conn.close()
    df["earnings_date"] = pd.to_datetime(df["earnings_date"])
    return df


def load_m5_data():
    """Load M5 regular-session bars from CSV files."""
    all_m5 = {}
    for ticker in TICKERS:
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


# ============================================================
# PART 2: BUILD EVENTS
# ============================================================
def get_day_bars(m5_df, target_date):
    """Get all M5 bars for a specific trading day."""
    return m5_df[m5_df["date"] == target_date].copy()


def get_trading_days(m5_df):
    """Get sorted list of unique trading days."""
    return sorted(m5_df["date"].unique())


def compute_recovery_curve(day_bars, gap_size):
    """Compute 6-point recovery curve for a day's M5 bars."""
    if len(day_bars) == 0 or gap_size <= 0:
        return {}

    curve = {}
    for label, bar_time in zip(CURVE_TIMES, CURVE_BAR_STARTS):
        # Get all bars from session start up to this time
        bars_up_to = day_bars[day_bars["time"] <= bar_time]
        if len(bars_up_to) == 0:
            curve[label] = np.nan
            continue

        # Running minimum of lows from 09:30 to this time
        running_low = bars_up_to["Low"].min()
        # Close at this time
        close_at_t = bars_up_to.iloc[-1]["Close"]
        # Recovery from running low relative to gap size
        recovery = (close_at_t - running_low) / gap_size
        curve[label] = recovery

    return curve


def classify_shape(curve):
    """Classify recovery trajectory shape."""
    early = curve.get("10:30", np.nan)
    late = curve.get("16:00", np.nan)

    if pd.isna(early) or pd.isna(late):
        return "UNKNOWN"

    if early > 0.30 and late > 0.30:
        return "EARLY_HOLD"
    elif early < 0.15 and late > 0.30:
        return "LATE_REVERSAL"
    elif early > 0.30 and late < 0.15:
        return "EARLY_FADE"
    elif early < 0.15 and late < 0.15:
        return "NO_RECOVERY"
    else:
        return "MIXED"


def build_events(earnings_df, all_m5):
    """Build events with M5-based recovery curves."""
    events = []

    for _, earn_row in earnings_df.iterrows():
        ticker = earn_row["ticker"]
        if ticker not in all_m5:
            continue

        m5_df = all_m5[ticker]
        earn_date = earn_row["earnings_date"].date()
        timing = earn_row.get("time_of_day", "Unknown")

        if timing not in ("BMO", "AMC"):
            timing = "AMC" if ticker in AMC_TICKERS else ("BMO" if ticker in BMO_TICKERS else "AMC")

        trading_days = get_trading_days(m5_df)

        # Determine Day 1
        if timing == "BMO":
            day1_date = earn_date
        else:  # AMC
            # Day 1 = next trading day after earnings_date
            future_days = [d for d in trading_days if d > earn_date]
            if not future_days:
                continue
            day1_date = future_days[0]

        if day1_date not in trading_days:
            # Find nearest
            exact_match = [d for d in trading_days if d == day1_date]
            if not exact_match:
                future = [d for d in trading_days if d >= day1_date]
                if not future:
                    continue
                day1_date = future[0]

        day1_idx = trading_days.index(day1_date)

        # Need prior day and forward days
        if day1_idx < 1 or day1_idx + FORWARD_DAYS >= len(trading_days):
            continue

        prior_date = trading_days[day1_idx - 1]

        # Get prior close (last bar of prior day)
        prior_bars = get_day_bars(m5_df, prior_date)
        if len(prior_bars) == 0:
            continue
        prior_close = prior_bars.iloc[-1]["Close"]

        # Get Day 1 bars
        day1_bars = get_day_bars(m5_df, day1_date)
        if len(day1_bars) < 10:  # need reasonable bar count
            continue

        day1_open = day1_bars.iloc[0]["Open"]
        day1_close = day1_bars.iloc[-1]["Close"]
        day1_low = day1_bars["Low"].min()
        day1_high = day1_bars["High"].max()

        if prior_close <= 0 or day1_open <= 0:
            continue

        gap_pct = (day1_open - prior_close) / prior_close * 100
        gap_size = abs(prior_close - day1_open)

        # Compute 6-point recovery curve
        curve = compute_recovery_curve(day1_bars, gap_size)

        # Classify shape
        shape = classify_shape(curve)

        # Forward drifts (using day close prices)
        drifts = {}
        for fd in [1, 2, 3, 5]:
            fwd_date = trading_days[day1_idx + fd]
            fwd_bars = get_day_bars(m5_df, fwd_date)
            if len(fwd_bars) > 0:
                fwd_close = fwd_bars.iloc[-1]["Close"]
                drifts[f"drift_{fd}d"] = (fwd_close - day1_close) / day1_close * 100
            else:
                drifts[f"drift_{fd}d"] = np.nan

        # Prices at each curve time (for entry timing test)
        prices_at = {}
        for label, bar_time in zip(CURVE_TIMES, CURVE_BAR_STARTS):
            bars_at = day1_bars[day1_bars["time"] == bar_time]
            if len(bars_at) > 0:
                prices_at[f"price_{label}"] = bars_at.iloc[0]["Close"]
            else:
                prices_at[f"price_{label}"] = np.nan

        # EPS surprise
        eps_surprise = np.nan
        surp = earn_row.get("surprise_pct", np.nan)
        if pd.notna(surp):
            try:
                eps_surprise = float(surp)
            except (ValueError, TypeError):
                pass

        event = {
            "ticker": ticker,
            "earnings_date": str(earn_date),
            "day1_date": str(day1_date),
            "timing": timing,
            "prior_close": prior_close,
            "day1_open": day1_open,
            "day1_high": day1_high,
            "day1_low": day1_low,
            "day1_close": day1_close,
            "gap_pct": gap_pct,
            "gap_size": gap_size,
            "shape": shape,
            "eps_surprise_pct": eps_surprise,
        }

        # Add curve points
        for label, val in curve.items():
            event[f"rec_{label}"] = val

        event.update(drifts)
        event.update(prices_at)
        events.append(event)

    df = pd.DataFrame(events)
    if not df.empty:
        df = df.drop_duplicates(subset=["ticker", "day1_date"], keep="first")
        df = df.sort_values(["ticker", "day1_date"]).reset_index(drop=True)
    return df


# ============================================================
# PART 3: TESTS
# ============================================================

def n_flag(n):
    if n < 10:
        return " **ANECDOTAL**"
    elif n < 20:
        return " *LOW N*"
    return ""


def test0_coverage(events):
    print("=" * 70)
    print("TEST 0: M5 DATA COVERAGE CHECK")
    print("=" * 70)
    total = len(events)
    print(f"Total earnings events with M5 data: {total}")
    print()
    for thresh in [-3, -5, -7, -10]:
        n = (events["gap_pct"] <= thresh).sum()
        print(f"  Gap <= {thresh}%: {n} events{n_flag(n)}")
    n_up = (events["gap_pct"] >= 3).sum()
    print(f"  Gap >= +3%: {n_up}")
    print()
    print("Gap-down events per ticker (gap <= -3%):")
    gd = events[events["gap_pct"] <= -3]
    for t in sorted(gd["ticker"].unique()):
        n = (gd["ticker"] == t).sum()
        print(f"  {t}: {n}")
    print()
    return {"total": int(total), "gap_down_3": int((events["gap_pct"] <= -3).sum()),
            "gap_down_5": int((events["gap_pct"] <= -5).sum()),
            "gap_down_10": int((events["gap_pct"] <= -10).sum())}


def test1_recovery_curves(events):
    print("=" * 70)
    print("TEST 1: 6-POINT RECOVERY CURVE BY DRIFT DIRECTION")
    print("=" * 70)

    gd = events[events["gap_pct"] <= GAP_THRESHOLD].dropna(subset=["drift_5d"]).copy()
    print(f"Gap-down events (gap <= {GAP_THRESHOLD}%): N={len(gd)}")

    group_a = gd[gd["drift_5d"] > 0]  # recovered
    group_b = gd[gd["drift_5d"] <= 0]  # continued falling
    print(f"  Group A (drift_5d > 0, recovered): N={len(group_a)}")
    print(f"  Group B (drift_5d <= 0, continued): N={len(group_b)}")
    print()

    rec_cols = [f"rec_{t}" for t in CURVE_TIMES]

    print(f"{'Time':<8}", end="")
    for t in CURVE_TIMES:
        print(f"{t:>10}", end="")
    print()
    print("-" * 68)

    curve_a = {}
    curve_b = {}
    separations = {}

    for label in ["Group A", "Group B"]:
        grp = group_a if label == "Group A" else group_b
        print(f"{label:<8}", end="")
        for t in CURVE_TIMES:
            col = f"rec_{t}"
            val = grp[col].mean() if col in grp.columns else np.nan
            if label == "Group A":
                curve_a[t] = val
            else:
                curve_b[t] = val
            print(f"{val:>10.3f}", end="")
        print(f"  (N={len(grp)})")

    # Separation
    print(f"{'Sep':<8}", end="")
    best_sep_time = None
    best_sep_val = 0
    for t in CURVE_TIMES:
        sep = curve_a.get(t, 0) - curve_b.get(t, 0)
        separations[t] = sep
        print(f"{sep:>+10.3f}", end="")
        if abs(sep) > abs(best_sep_val):
            best_sep_val = sep
            best_sep_time = t
    print()
    print()
    print(f"Largest separation at: {best_sep_time} ({best_sep_val:+.3f})")
    print(f"ANT predicts 10:30 ET. Data says: {best_sep_time}")
    print()

    return {"curve_a": curve_a, "curve_b": curve_b, "separations": separations,
            "n_a": len(group_a), "n_b": len(group_b), "best_sep_time": best_sep_time}


def test2_optimal_time(events):
    print("=" * 70)
    print("TEST 2: OPTIMAL RECOVERY MEASUREMENT TIME")
    print("=" * 70)

    gd = events[events["gap_pct"] <= GAP_THRESHOLD].dropna(subset=["drift_5d"]).copy()

    print(f"{'Time':<10} {'Zone':<10} {'Spearman rho':>13} {'p-value':>10} {'Sig':>5}")
    print("-" * 55)

    zone_map = {"10:00": "Zone 1", "10:30": "Zone 2", "12:00": "Zone 2-3",
                "13:00": "Zone 3", "13:30": "Bar 1", "16:00": "Close"}

    results = {}
    best_rho = 0
    best_time = None

    for t in CURVE_TIMES:
        col = f"rec_{t}"
        valid = gd.dropna(subset=[col, "drift_5d"])
        if len(valid) < 5:
            print(f"{t:<10} {zone_map.get(t, ''):<10} {'N/A':>13}")
            continue

        rho, pval = stats.spearmanr(valid[col], valid["drift_5d"])
        sig = "YES" if pval < 0.05 else ("~" if pval < 0.10 else "NO")
        print(f"{t:<10} {zone_map.get(t, ''):<10} {rho:>+13.4f} {pval:>10.4f} {sig:>5}")

        results[t] = {"rho": round(rho, 4), "p": round(pval, 4), "n": len(valid)}
        if abs(rho) > abs(best_rho):
            best_rho = rho
            best_time = t

    print()
    print(f"Best measurement time: {best_time} (rho = {best_rho:+.4f})")
    print(f"ANT-1 daily close rho: +0.02. ANT predicts 10:30 is best.")
    print()

    return {"correlations": results, "best_time": best_time, "best_rho": round(best_rho, 4)}


def test3_shape_vs_drift(events):
    print("=" * 70)
    print("TEST 3: RECOVERY TRAJECTORY SHAPE vs DRIFT")
    print("=" * 70)

    gd = events[events["gap_pct"] <= GAP_THRESHOLD].dropna(subset=["drift_5d"]).copy()

    shape_order = ["EARLY_HOLD", "LATE_REVERSAL", "EARLY_FADE", "NO_RECOVERY", "MIXED", "UNKNOWN"]

    print(f"{'Shape':<16} {'N':>5} {'Drift 1d':>10} {'Drift 5d':>10} {'Med 5d':>10} {'WR 5d':>8} {'Std 5d':>8}")
    print("-" * 75)

    results = {}
    for shape in shape_order:
        subset = gd[gd["shape"] == shape]
        n = len(subset)
        if n == 0:
            continue
        d1 = subset["drift_1d"].mean()
        d5 = subset["drift_5d"].mean()
        med5 = subset["drift_5d"].median()
        wr5 = (subset["drift_5d"] > 0).mean() * 100
        std5 = subset["drift_5d"].std()
        flag = n_flag(n)
        print(f"{shape:<16} {n:>5} {d1:>+9.2f}% {d5:>+9.2f}% {med5:>+9.2f}% {wr5:>7.1f}% {std5:>7.2f}%{flag}")

        results[shape] = {"n": int(n), "drift_1d": round(d1, 3), "drift_5d": round(d5, 3),
                          "median_5d": round(med5, 3), "wr_5d": round(wr5, 1)}
    print()

    # ANT predictions check
    eh = results.get("EARLY_HOLD", {})
    nr = results.get("NO_RECOVERY", {})
    ef = results.get("EARLY_FADE", {})
    print("ANT Predictions Check:")
    if eh and nr:
        print(f"  EARLY_HOLD drift_5d = {eh.get('drift_5d', 'N/A')}% vs NO_RECOVERY = {nr.get('drift_5d', 'N/A')}%")
        if eh.get("drift_5d", 0) > nr.get("drift_5d", 0):
            print("  -> Directionally consistent with ANT (EARLY_HOLD > NO_RECOVERY)")
        else:
            print("  -> CONTRADICTS ANT (NO_RECOVERY drifts higher than EARLY_HOLD)")
    if ef:
        print(f"  EARLY_FADE drift_5d = {ef.get('drift_5d', 'N/A')}% (ANT predicts negative)")
    print()

    return results


def test4_entry_timing(events, all_m5):
    print("=" * 70)
    print("TEST 4: ZONE-BASED ENTRY TIMING")
    print("=" * 70)

    gd = events[(events["gap_pct"] <= GAP_THRESHOLD) &
                (events["rec_10:30"] >= 0.25)].dropna(subset=["drift_5d"]).copy()
    print(f"Events with gap <= {GAP_THRESHOLD}% and recovery >= 0.25 at 10:30: N={len(gd)}")
    print()

    entry_times = [("10:00", "price_10:00"), ("10:30", "price_10:30"),
                   ("12:00", "price_12:00"), ("13:30", "price_13:30")]

    print(f"{'Entry Time':<12} {'N':>5} {'Intraday Ret':>13} {'5d Return':>10} {'WR':>7} {'PF':>7}")
    print("-" * 60)

    results = {}
    for time_label, price_col in entry_times:
        valid = gd.dropna(subset=[price_col, "drift_5d"]).copy()
        if len(valid) == 0:
            continue

        trades = []
        for _, ev in valid.iterrows():
            entry_price = ev[price_col]
            if entry_price <= 0 or pd.isna(entry_price):
                continue

            # Intraday return (to day1 close)
            intraday_ret = (ev["day1_close"] - entry_price) / entry_price * 100

            # 5d return
            ticker = ev["ticker"]
            if ticker not in all_m5:
                continue
            m5_df = all_m5[ticker]
            day1_date = pd.Timestamp(ev["day1_date"]).date()
            tdays = get_trading_days(m5_df)
            if day1_date not in tdays:
                continue
            d1_idx = tdays.index(day1_date)
            if d1_idx + FORWARD_DAYS >= len(tdays):
                continue

            # Exit after 5 days or at stop
            stop_price = entry_price * 0.97
            exit_price = None
            exit_day = 0

            for fd in range(1, FORWARD_DAYS + 1):
                fwd_date = tdays[d1_idx + fd]
                fwd_bars = get_day_bars(m5_df, fwd_date)
                if len(fwd_bars) == 0:
                    continue
                exit_day = fd

                # Check stop
                if fwd_bars["Low"].min() <= stop_price:
                    exit_price = stop_price
                    break

                if fd == FORWARD_DAYS:
                    exit_price = fwd_bars.iloc[-1]["Close"]

            if exit_price is None:
                continue

            ret_5d = (exit_price - entry_price) / entry_price * 100
            trades.append({"return": ret_5d, "intraday": intraday_ret, "hold": exit_day})

        if not trades:
            continue

        tdf = pd.DataFrame(trades)
        n = len(tdf)
        mean_intra = tdf["intraday"].mean()
        mean_5d = tdf["return"].mean()
        wr = (tdf["return"] > 0).mean() * 100
        wins = tdf[tdf["return"] > 0]["return"].sum()
        losses = abs(tdf[tdf["return"] <= 0]["return"].sum())
        pf = wins / losses if losses > 0 else float("inf")

        flag = n_flag(n)
        print(f"{time_label:<12} {n:>5} {mean_intra:>+12.2f}% {mean_5d:>+9.2f}% {wr:>6.1f}% {pf:>6.2f}{flag}")

        results[time_label] = {"n": int(n), "mean_intraday": round(mean_intra, 3),
                                "mean_5d": round(mean_5d, 3), "wr": round(wr, 1),
                                "pf": round(pf, 2)}
    print()
    return results


def test5_gap_recovery_cross(events):
    print("=" * 70)
    print("TEST 5: GAP SEVERITY x RECOVERY INTERACTION (M5)")
    print("=" * 70)

    gd = events[events["gap_pct"] <= GAP_THRESHOLD].dropna(subset=["rec_12:00", "drift_5d"]).copy()

    gap_buckets = [
        ("-3% to -5%", lambda x: (x <= -3) & (x > -5)),
        ("-5% to -10%", lambda x: (x <= -5) & (x > -10)),
        ("< -10%", lambda x: x <= -10),
    ]
    rec_buckets = [
        ("Rec < 0.20", lambda x: x < 0.20),
        ("Rec 0.20-0.40", lambda x: (x >= 0.20) & (x < 0.40)),
        ("Rec > 0.40", lambda x: x >= 0.40),
    ]

    print(f"{'':>18}", end="")
    for gn, _ in gap_buckets:
        print(f"{gn:>22}", end="")
    print()
    print("-" * 84)

    results = {}
    for rn, rc in rec_buckets:
        print(f"{rn:<18}", end="")
        for gn, gc in gap_buckets:
            mask = gc(gd["gap_pct"]) & rc(gd["rec_12:00"])
            subset = gd[mask]
            n = len(subset)
            if n > 0:
                d5 = subset["drift_5d"].mean()
                flag = n_flag(n)
                print(f"{d5:>+7.2f}% (N={n:>3}){flag:>5}", end="")
                results[f"{rn}|{gn}"] = {"drift_5d": round(d5, 3), "n": int(n)}
            else:
                print(f"{'N/A':>22}", end="")
        print()
    print()
    return results


def test6_m5_zombie(events, all_m5):
    print("=" * 70)
    print("TEST 6: M5 ZOMBIE STRATEGY BACKTEST")
    print("=" * 70)

    results = {}

    for entry_label, entry_time_col, entry_time_bar in [
        ("12:00 ET (Zone 2 end)", "price_12:00", "11:55"),
        ("10:30 ET (ANT 1-hour)", "price_10:30", "10:25"),
    ]:
        print(f"\n--- Entry at {entry_label} ---")
        # Filter: gap <= -5%, recovery at 10:30 >= 0.25, recovery holding at 12:00
        gd = events[(events["gap_pct"] <= GAP_THRESHOLD_STRICT)].copy()

        if entry_label.startswith("12:00"):
            gd = gd[(gd["rec_10:30"] >= 0.25) & (gd["rec_12:00"] >= gd["rec_10:30"])].copy()
        else:
            gd = gd[(gd["rec_10:30"] >= 0.25)].copy()

        trades = []
        for _, ev in gd.iterrows():
            ticker = ev["ticker"]
            if ticker not in all_m5:
                continue
            m5_df = all_m5[ticker]
            day1_date = pd.Timestamp(ev["day1_date"]).date()
            tdays = get_trading_days(m5_df)
            if day1_date not in tdays:
                continue
            d1_idx = tdays.index(day1_date)
            if d1_idx + FORWARD_DAYS >= len(tdays):
                continue

            entry_price = ev.get(entry_time_col)
            if pd.isna(entry_price) or entry_price <= 0:
                continue

            prior_close = ev["prior_close"]
            day1_low = ev["day1_low"]
            stop_price = day1_low  # recovery failed = new low
            target_price = prior_close  # full gap fill

            exit_price = None
            exit_reason = None
            holding_days = 0

            for fd in range(0 if entry_label.startswith("10:30") else 0, FORWARD_DAYS + 1):
                if fd == 0:
                    # Rest of day1 after entry
                    fwd_date = day1_date
                    fwd_bars = get_day_bars(m5_df, fwd_date)
                    # Only bars after entry time
                    fwd_bars = fwd_bars[fwd_bars["time"] > entry_time_bar]
                else:
                    fwd_date = tdays[d1_idx + fd]
                    fwd_bars = get_day_bars(m5_df, fwd_date)

                if len(fwd_bars) == 0:
                    continue
                holding_days = fd

                # Check stop (bar low below day1_low)
                if fwd_bars["Low"].min() <= stop_price:
                    exit_price = stop_price
                    exit_reason = "stop"
                    break

                # Check target (bar high reaches prior_close)
                if fwd_bars["High"].max() >= target_price:
                    exit_price = target_price
                    exit_reason = "gap_fill"
                    break

            if exit_price is None and holding_days > 0:
                last_date = tdays[min(d1_idx + FORWARD_DAYS, len(tdays) - 1)]
                last_bars = get_day_bars(m5_df, last_date)
                if len(last_bars) > 0:
                    exit_price = last_bars.iloc[-1]["Close"]
                    exit_reason = "max_hold"

            if exit_price is not None:
                ret = (exit_price - entry_price) / entry_price * 100
                trades.append({
                    "ticker": ticker, "entry_date": str(day1_date),
                    "entry": entry_price, "exit": exit_price,
                    "return_pct": ret, "reason": exit_reason,
                    "holding_days": holding_days
                })

        key = entry_label.split(" ")[0]
        if trades:
            tdf = pd.DataFrame(trades)
            n = len(tdf)
            mean_ret = tdf["return_pct"].mean()
            wr = (tdf["return_pct"] > 0).mean() * 100
            wins = tdf[tdf["return_pct"] > 0]["return_pct"].sum()
            losses = abs(tdf[tdf["return_pct"] <= 0]["return_pct"].sum())
            pf = wins / losses if losses > 0 else float("inf")
            max_loss = tdf["return_pct"].min()
            avg_hold = tdf["holding_days"].mean()

            print(f"  N trades: {n}{n_flag(n)}")
            print(f"  Mean return: {mean_ret:+.2f}%")
            print(f"  Win rate: {wr:.1f}%")
            print(f"  Profit factor: {pf:.2f}")
            print(f"  Max single loss: {max_loss:+.2f}%")
            print(f"  Avg holding: {avg_hold:.1f} days")
            print(f"  Exits: {tdf['reason'].value_counts().to_dict()}")

            results[key] = {
                "n": int(n), "mean_return": round(mean_ret, 3),
                "wr": round(wr, 1), "pf": round(pf, 2),
                "max_loss": round(max_loss, 3), "avg_hold": round(avg_hold, 1),
                "exits": tdf["reason"].value_counts().to_dict()
            }
        else:
            print("  No trades.")
            results[key] = {"n": 0}

    print()
    return results


# ============================================================
# PART 4: CHARTS
# ============================================================

def make_charts(events):
    gd = events[events["gap_pct"] <= GAP_THRESHOLD].dropna(subset=["drift_5d"]).copy()

    # --- Chart 1: Recovery curves by drift direction ---
    fig, ax = plt.subplots(figsize=(10, 7))
    group_a = gd[gd["drift_5d"] > 0]
    group_b = gd[gd["drift_5d"] <= 0]
    times_x = range(len(CURVE_TIMES))

    for label, grp, color, marker in [("Recovered (5d up)", group_a, "green", "o"),
                                       ("Continued (5d dn)", group_b, "red", "s")]:
        means = [grp[f"rec_{t}"].mean() for t in CURVE_TIMES]
        ax.plot(times_x, means, f"{color[0]}-{marker}", linewidth=2,
                markersize=8, label=f"{label} (N={len(grp)})")

    ax.set_xticks(times_x)
    ax.set_xticklabels(CURVE_TIMES)
    ax.set_xlabel("Time (ET)")
    ax.set_ylabel("Recovery Ratio (fraction of gap)")
    ax.set_title("ANT-2: 6-Point Recovery Curve by 5-Day Drift Direction")
    ax.legend()
    ax.axhline(0.35, color="gray", linestyle=":", label="ANT threshold")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    fig.savefig(OUTPUT_DIR / "ant2_recovery_curves.png", dpi=150)
    plt.close(fig)
    print("  Saved ant2_recovery_curves.png")

    # --- Chart 2: Spearman rho by time ---
    rhos = []
    pvals = []
    for t in CURVE_TIMES:
        col = f"rec_{t}"
        valid = gd.dropna(subset=[col, "drift_5d"])
        if len(valid) >= 5:
            rho, pval = stats.spearmanr(valid[col], valid["drift_5d"])
            rhos.append(rho)
            pvals.append(pval)
        else:
            rhos.append(0)
            pvals.append(1)

    fig, ax = plt.subplots(figsize=(10, 6))
    colors = ["green" if p < 0.05 else ("orange" if p < 0.10 else "gray") for p in pvals]
    bars = ax.bar(range(len(CURVE_TIMES)), rhos, color=colors, edgecolor="black")
    ax.set_xticks(range(len(CURVE_TIMES)))
    ax.set_xticklabels(CURVE_TIMES)
    ax.set_xlabel("Measurement Time (ET)")
    ax.set_ylabel("Spearman rho")
    ax.set_title("ANT-2: Recovery Ratio Predictive Power by Measurement Time")
    ax.axhline(0, color="black", linewidth=0.5)
    # Add p-value labels
    for i, (r, p) in enumerate(zip(rhos, pvals)):
        ax.text(i, r + 0.01 * (1 if r >= 0 else -1), f"p={p:.2f}",
                ha="center", va="bottom" if r >= 0 else "top", fontsize=8)
    from matplotlib.patches import Patch
    legend_els = [Patch(facecolor="green", label="p < 0.05"),
                  Patch(facecolor="orange", label="p < 0.10"),
                  Patch(facecolor="gray", label="p >= 0.10")]
    ax.legend(handles=legend_els)
    plt.tight_layout()
    fig.savefig(OUTPUT_DIR / "ant2_spearman_by_time.png", dpi=150)
    plt.close(fig)
    print("  Saved ant2_spearman_by_time.png")

    # --- Chart 3: Shape vs drift box plot ---
    shape_order = ["EARLY_HOLD", "LATE_REVERSAL", "EARLY_FADE", "NO_RECOVERY", "MIXED"]
    shape_data = []
    shape_labels = []
    for s in shape_order:
        subset = gd[gd["shape"] == s]["drift_5d"].dropna()
        if len(subset) > 0:
            shape_data.append(subset.values)
            shape_labels.append(f"{s}\n(N={len(subset)})")

    if shape_data:
        fig, ax = plt.subplots(figsize=(12, 7))
        bp = ax.boxplot(shape_data, labels=shape_labels, patch_artist=True)
        colors_box = ["lightgreen", "lightyellow", "lightsalmon", "lightcoral", "lightgray"]
        for patch, color in zip(bp["boxes"], colors_box[:len(bp["boxes"])]):
            patch.set_facecolor(color)
        ax.axhline(0, color="black", linewidth=0.5)
        ax.set_ylabel("5-Day Drift (%)")
        ax.set_title("ANT-2: 5-Day Drift Distribution by Recovery Trajectory Shape")
        plt.tight_layout()
        fig.savefig(OUTPUT_DIR / "ant2_shape_drift.png", dpi=150)
        plt.close(fig)
        print("  Saved ant2_shape_drift.png")

    # --- Chart 4: Entry timing comparison ---
    # Simple bar chart placeholder
    fig, ax = plt.subplots(figsize=(10, 6))
    entry_labels = ["10:00", "10:30", "12:00", "13:30"]
    # Compute mean 5d return for each entry time (simple version)
    gd_filtered = gd[gd["rec_10:30"] >= 0.25]
    means = []
    wrs = []
    for t in entry_labels:
        col = f"price_{t}"
        valid = gd_filtered.dropna(subset=[col])
        if len(valid) > 0:
            rets = (valid["day1_close"] - valid[col]) / valid[col] * 100
            means.append(rets.mean())
            wrs.append((rets > 0).mean() * 100)
        else:
            means.append(0)
            wrs.append(50)

    x = np.arange(len(entry_labels))
    ax.bar(x - 0.15, means, 0.3, label="Mean Intraday Ret", color="steelblue")
    ax2 = ax.twinx()
    ax2.plot(x, wrs, "ro-", linewidth=2, label="Win Rate")
    ax.set_xticks(x)
    ax.set_xticklabels(entry_labels)
    ax.set_xlabel("Entry Time (ET)")
    ax.set_ylabel("Mean Intraday Return (%)")
    ax2.set_ylabel("Win Rate (%)")
    ax.set_title("ANT-2: Entry Timing Comparison")
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
    plt.tight_layout()
    fig.savefig(OUTPUT_DIR / "ant2_entry_timing.png", dpi=150)
    plt.close(fig)
    print("  Saved ant2_entry_timing.png")


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 70)
    print("ANT-2: EARNINGS RECOVERY RATIO — M5 PRECISION TEST")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)
    print()

    print("PHASE 1: Loading M5 data...")
    all_m5 = load_m5_data()
    print(f"  Loaded M5 data for {len(all_m5)} tickers")
    for t in sorted(all_m5.keys()):
        df = all_m5[t]
        tdays = get_trading_days(df)
        print(f"    {t}: {len(df)} bars, {len(tdays)} trading days ({tdays[0]} to {tdays[-1]})")
    print()

    print("PHASE 2: Loading earnings calendar...")
    earnings = load_earnings()
    # Filter to M5 data range
    m5_start = min(get_trading_days(list(all_m5.values())[0]))
    m5_end = max(get_trading_days(list(all_m5.values())[0]))
    earnings = earnings[(earnings["earnings_date"].dt.date >= m5_start) &
                        (earnings["earnings_date"].dt.date <= m5_end)]
    print(f"  Earnings in M5 range: {len(earnings)} events")
    print()

    print("PHASE 3: Building events with M5 recovery curves...")
    events = build_events(earnings, all_m5)
    print(f"  Events built: {len(events)}")
    events.to_csv(OUTPUT_DIR / "events_m5.csv", index=False)
    print("  Saved events_m5.csv")
    print()

    if events.empty:
        print("ERROR: No events. Exiting.")
        return

    # --- RUN TESTS ---
    all_results = {}
    print("PHASE 4: Running tests...")
    print()

    all_results["test0"] = test0_coverage(events)
    all_results["test1"] = test1_recovery_curves(events)
    all_results["test2"] = test2_optimal_time(events)
    all_results["test3"] = test3_shape_vs_drift(events)
    all_results["test4"] = test4_entry_timing(events, all_m5)
    all_results["test5"] = test5_gap_recovery_cross(events)
    all_results["test6"] = test6_m5_zombie(events, all_m5)

    # --- CHARTS ---
    print("PHASE 5: Generating charts...")
    make_charts(events)
    print()

    # --- SAVE SUMMARY ---
    all_results["meta"] = {
        "date_run": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "n_tickers_m5": len(all_m5),
        "n_events": int(len(events)),
        "gap_threshold": GAP_THRESHOLD,
        "gap_threshold_strict": GAP_THRESHOLD_STRICT,
        "m5_range": f"{m5_start} to {m5_end}",
    }

    with open(OUTPUT_DIR / "ANT2_summary.json", "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print("  Saved ANT2_summary.json")

    # --- VERDICT ---
    print()
    print("=" * 70)
    print("VERDICT: M5 vs DAILY COMPARISON")
    print("=" * 70)

    t2 = all_results.get("test2", {})
    best_time = t2.get("best_time", "N/A")
    best_rho = t2.get("best_rho", 0)
    print(f"Best M5 measurement time: {best_time} (rho = {best_rho:+.4f})")
    print(f"ANT-1 daily rho: +0.02 (p=0.92)")
    if abs(best_rho) > 0.20:
        print("  -> M5 timing IMPROVES predictive power over daily")
    else:
        print("  -> M5 timing does NOT meaningfully improve over daily")

    t3 = all_results.get("test3", {})
    eh = t3.get("EARLY_HOLD", {})
    nr = t3.get("NO_RECOVERY", {})
    if eh and nr:
        print(f"Shape test: EARLY_HOLD={eh.get('drift_5d','N/A')}% vs NO_RECOVERY={nr.get('drift_5d','N/A')}%")

    print()
    print("Done. All outputs saved to backtest_output/ant2/")


if __name__ == "__main__":
    main()
