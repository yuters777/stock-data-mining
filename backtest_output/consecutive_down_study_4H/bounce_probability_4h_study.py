#!/usr/bin/env python3
"""
4H Consecutive Down Bars → Bounce Probability Study (Stage 2)

Aggregates M5 bars into two 4H bars per session:
  Bar 1: 09:30-13:25 ET (48 M5 bars)
  Bar 2: 13:30-15:55 ET (30 M5 bars)

Consecutive 4H down closes span across days:
  Bar2 of day N → Bar1 of day N+1 is a valid consecutive pair.

Cross-references with Stage 1 daily study for overlapping events.

Constraints:
  - 25 certified tickers only (excludes SPY, VIXY)
  - No lookahead: VIX = prior day close
  - No volume features
  - Session hours only: 09:30-15:55 ET
"""

import csv
import json
import os
from collections import defaultdict
from math import erfc, sqrt
from pathlib import Path
from random import Random

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "backtest_output"
OUT_DIR = ROOT / "backtest_output" / "consecutive_down_study_4H"
STAGE1_DIR = ROOT / "backtest_output" / "consecutive_down_study"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CERTIFIED_TICKERS = [
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN",
    "COST", "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU",
    "NVDA", "PLTR", "SNOW", "TSLA", "TSM", "TXN", "V",
]

# 4H bar boundaries (minutes from midnight)
BAR1_START = 9 * 60 + 30   # 09:30
BAR1_END = 13 * 60 + 25    # 13:25
BAR2_START = 13 * 60 + 30  # 13:30
BAR2_END = 15 * 60 + 55    # 15:55

STREAK_BINS = [2, 3, 4, 5, 6, 7, 8]  # 8 means 8+
VIX_BUCKETS = ["<20", "20-25", ">=25"]
RSI_PERIOD = 14
SPLIT_SEED = 42


# ── Helpers ───────────────────────────────────────────────────────────────

def p_from_t(t_stat, df_):
    return erfc(abs(t_stat) / sqrt(2))


def t_test_vs_zero(arr):
    n = len(arr)
    if n < 2:
        m = np.mean(arr) if n else 0.0
        return (m, 0.0, 0.0, 1.0, n)
    m = np.mean(arr)
    s = np.std(arr, ddof=1)
    t = m / (s / sqrt(n)) if s > 0 else 0.0
    p = p_from_t(t, n - 1)
    return (m, s, t, p, n)


def compute_rsi(closes, period=14):
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def load_vix():
    vix_path = ROOT / "Fetched_Data" / "VIXCLS_FRED_real.csv"
    vix = {}
    with open(vix_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            val = row["VIXCLS"].strip()
            if val in ("", "."):
                continue
            try:
                vix[row["observation_date"]] = float(val)
            except ValueError:
                continue
    return vix


def vix_bucket(vix_val):
    if vix_val is None:
        return None
    if vix_val < 20:
        return "<20"
    elif vix_val < 25:
        return "20-25"
    return ">=25"


def aggregate_m5_to_4h(ticker):
    """
    Load M5 FIXED data, aggregate into 4H bars.
    Bar 1: 09:30-13:25 ET
    Bar 2: 13:30-15:55 ET
    Returns DataFrame: date, bar_num (1 or 2), open, high, low, close, bar_label
    """
    fp = DATA_DIR / f"{ticker}_m5_regsess_FIXED.csv"
    if not fp.exists():
        return None

    df = pd.read_csv(fp, parse_dates=["Datetime"])
    df["date"] = df["Datetime"].dt.date
    df["minutes"] = df["Datetime"].dt.hour * 60 + df["Datetime"].dt.minute

    # Assign bar number
    df["bar_num"] = None
    df.loc[(df["minutes"] >= BAR1_START) & (df["minutes"] <= BAR1_END), "bar_num"] = 1
    df.loc[(df["minutes"] >= BAR2_START) & (df["minutes"] <= BAR2_END), "bar_num"] = 2
    df = df.dropna(subset=["bar_num"])
    df["bar_num"] = df["bar_num"].astype(int)

    bars_4h = df.groupby(["date", "bar_num"]).agg(
        open=("Open", "first"),
        high=("High", "max"),
        low=("Low", "min"),
        close=("Close", "last"),
    ).reset_index()

    bars_4h = bars_4h.sort_values(["date", "bar_num"]).reset_index(drop=True)
    bars_4h["bar_label"] = bars_4h.apply(
        lambda r: f"{r['date']}_B{r['bar_num']}", axis=1
    )
    return bars_4h


def load_stage1_events():
    """Load Stage 1 daily streak events for cross-reference."""
    path = STAGE1_DIR / "all_streak_events.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    return df


def build_4h_streak_events(bars_4h, vix_dict):
    """
    Identify consecutive 4H down closes (close < prior 4H close).
    Cross-day continuity: Bar2 day N → Bar1 day N+1 is consecutive.
    For each streak endpoint where streak >= 2, measure:
      - Next 4H bar return
      - Next 2 bars cumulative return
      - RSI(14) on 4H closes at streak end
    VIX regime = prior day close (no lookahead).
    """
    bars = bars_4h.copy()
    bars["ret"] = bars["close"].pct_change()
    bars["rsi"] = compute_rsi(bars["close"], RSI_PERIOD)

    # For each 4H bar, determine VIX: use prior day's VIX close
    # "prior day" = the trading day before the bar's date
    dates_sorted = sorted(bars["date"].unique())
    date_to_prior = {}
    for i in range(1, len(dates_sorted)):
        date_to_prior[str(dates_sorted[i])] = str(dates_sorted[i - 1])
    # For bar_num=1, prior day = the day before this bar's date
    # For bar_num=2, prior day = still the day before (VIX at streak start day = prior day close)
    # Actually the spec says "VIX regime at streak start day" — use prior day close for the bar's date
    bars["vix_prior"] = bars["date"].apply(
        lambda d: vix_dict.get(date_to_prior.get(str(d)))
    )

    n = len(bars)
    events = []
    streak = 0

    for i in range(1, n):
        if bars.iloc[i]["close"] < bars.iloc[i - 1]["close"]:
            streak += 1
        else:
            streak = 0

        if streak >= 2:
            streak_len = streak
            streak_bin = min(streak_len, 8)

            end_close = bars.iloc[i]["close"]
            end_date = str(bars.iloc[i]["date"])
            end_bar = int(bars.iloc[i]["bar_num"])
            rsi_val = bars.iloc[i]["rsi"]
            vix_val = bars.iloc[i]["vix_prior"]

            # Next 4H bar return
            next_bar_ret = None
            if i + 1 < n:
                next_bar_ret = (bars.iloc[i + 1]["close"] - end_close) / end_close

            # Next 2 bars cumulative return
            next_2bar_ret = None
            if i + 2 < n:
                next_2bar_ret = (bars.iloc[i + 2]["close"] - end_close) / end_close

            events.append({
                "streak_len": streak_len,
                "streak_bin": streak_bin,
                "date": end_date,
                "bar_num": end_bar,
                "bar_label": bars.iloc[i]["bar_label"],
                "next_bar_ret": next_bar_ret,
                "next_2bar_ret": next_2bar_ret,
                "rsi": rsi_val,
                "vix": vix_val,
                "vix_bucket": vix_bucket(vix_val),
            })

    return events


def cross_reference_stage1(events_4h, stage1_df, ticker):
    """
    For 4H events that map to a daily 4-day streak + VIX >= 25,
    compare entry timing: 4H-timed vs daily close-to-close.

    A 4H streak endpoint on date D maps to a daily streak if Stage 1
    has a streak_bin >= 4 event on date D for this ticker.
    """
    if stage1_df is None:
        return []

    # Stage 1 events for this ticker with streak >= 4 and VIX >= 25
    s1 = stage1_df[
        (stage1_df["ticker"] == ticker)
        & (stage1_df["streak_bin"] >= 4)
        & (stage1_df["vix_bucket"] == ">=25")
    ]
    s1_dates = set(s1["date"].astype(str).values)

    overlaps = []
    for e in events_4h:
        if e["date"] in s1_dates and e["vix_bucket"] == ">=25":
            # Find matching Stage 1 event
            s1_match = s1[s1["date"] == e["date"]]
            if len(s1_match) > 0:
                s1_row = s1_match.iloc[-1]  # Take the longest streak if multiple
                overlaps.append({
                    "ticker": ticker,
                    "date": e["date"],
                    "bar_num": e["bar_num"],
                    "streak_4h": e["streak_len"],
                    "streak_daily": int(s1_row["streak_len"]),
                    "next_bar_ret_4h": e["next_bar_ret"],
                    "next_day_ret_daily": s1_row["next_day_ret"],
                    "rsi_4h": e["rsi"],
                    "rsi_daily": s1_row["rsi"],
                    "vix": e["vix"],
                })
    return overlaps


# ── Printing helpers ──────────────────────────────────────────────────────

def fmt(val, decimals=4):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "N/A"
    return f"{val:.{decimals}f}"


# ── Main ──────────────────────────────────────────────────────────────────

def run_study():
    print("=" * 80)
    print("4H CONSECUTIVE DOWN BARS → BOUNCE PROBABILITY STUDY (Stage 2)")
    print("=" * 80)

    vix_dict = load_vix()
    print(f"VIX data: {len(vix_dict)} days loaded")

    stage1_df = load_stage1_events()
    if stage1_df is not None:
        print(f"Stage 1 events loaded: {len(stage1_df)} rows")
    else:
        print("Stage 1 events not found — skipping cross-reference")

    all_events = []
    all_overlaps = []
    ticker_counts = {}

    for ticker in CERTIFIED_TICKERS:
        bars_4h = aggregate_m5_to_4h(ticker)
        if bars_4h is None:
            print(f"  SKIP {ticker}: no data")
            continue

        events = build_4h_streak_events(bars_4h, vix_dict)
        overlaps = cross_reference_stage1(events, stage1_df, ticker)

        ticker_counts[ticker] = len(events)
        for e in events:
            e["ticker"] = ticker
        all_events.extend(events)
        all_overlaps.extend(overlaps)

        n_bars = len(bars_4h)
        print(f"  {ticker}: {n_bars} 4H bars, {len(events)} streak events, {len(overlaps)} Stage1 overlaps")

    print(f"\nTotal: {len(all_events)} events across {len(ticker_counts)} tickers")
    print(f"Stage 1 overlaps (4-day+ daily streak, VIX>=25): {len(all_overlaps)}")

    # ── Split-sample: random 50/50 ───────────────────────────────────────
    rng = Random(SPLIT_SEED)
    indices = list(range(len(all_events)))
    rng.shuffle(indices)
    mid = len(indices) // 2
    split_a = set(indices[:mid])
    for i, e in enumerate(all_events):
        e["split"] = "A" if i in split_a else "B"

    streak_labels = {2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8+"}

    # ══════════════════════════════════════════════════════════════════════
    # TABLE 1: N_consecutive_4H × VIX_bucket → next-bar return
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("TABLE 1: 4H Streak Length × VIX Bucket → Next-Bar Return")
    print("=" * 80)

    table1_rows = []
    for sbin in [2, 3, 4, 5, 6, 7, 8]:
        for vb in VIX_BUCKETS:
            subset = [e for e in all_events
                      if e["streak_bin"] == sbin and e["vix_bucket"] == vb
                      and e["next_bar_ret"] is not None]
            if not subset:
                table1_rows.append({
                    "streak": streak_labels[sbin], "vix_bucket": vb,
                    "mean_ret": None, "win_rate": None, "n_obs": 0,
                    "p_value": None, "flag": "N<20",
                })
                continue
            rets = [e["next_bar_ret"] for e in subset]
            m, s, t, p, n = t_test_vs_zero(rets)
            wr = sum(1 for r in rets if r > 0) / len(rets)
            flag = "N<20" if n < 20 else ""
            table1_rows.append({
                "streak": streak_labels[sbin], "vix_bucket": vb,
                "mean_ret": round(m * 100, 4), "win_rate": round(wr * 100, 2),
                "n_obs": n, "p_value": round(p, 4), "flag": flag,
            })

    header = f"{'Streak':<8} {'VIX':<8} {'Mean Ret%':>10} {'Win%':>8} {'N':>6} {'p-val':>8} {'Flag':>6}"
    print(header)
    print("-" * len(header))
    for r in table1_rows:
        print(f"{r['streak']:<8} {r['vix_bucket']:<8} {fmt(r['mean_ret']):>10} "
              f"{fmt(r['win_rate'], 2):>8} {r['n_obs']:>6} {fmt(r['p_value']):>8} {r['flag']:>6}")

    # ══════════════════════════════════════════════════════════════════════
    # TABLE 1b: Next 2-bar cumulative return
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("TABLE 1b: 4H Streak Length × VIX Bucket → Next 2-Bar Cumulative Return")
    print("=" * 80)

    table1b_rows = []
    for sbin in [2, 3, 4, 5, 6, 7, 8]:
        for vb in VIX_BUCKETS:
            subset = [e for e in all_events
                      if e["streak_bin"] == sbin and e["vix_bucket"] == vb
                      and e["next_2bar_ret"] is not None]
            if not subset:
                table1b_rows.append({
                    "streak": streak_labels[sbin], "vix_bucket": vb,
                    "mean_ret_2bar": None, "win_rate": None,
                    "n_obs": 0, "p_value": None, "flag": "N<20",
                })
                continue
            rets = [e["next_2bar_ret"] for e in subset]
            m, s, t, p, n = t_test_vs_zero(rets)
            wr = sum(1 for r in rets if r > 0) / len(rets)
            flag = "N<20" if n < 20 else ""
            table1b_rows.append({
                "streak": streak_labels[sbin], "vix_bucket": vb,
                "mean_ret_2bar": round(m * 100, 4), "win_rate": round(wr * 100, 2),
                "n_obs": n, "p_value": round(p, 4), "flag": flag,
            })

    header = f"{'Streak':<8} {'VIX':<8} {'Mean 2Bar%':>10} {'Win%':>8} {'N':>6} {'p-val':>8} {'Flag':>6}"
    print(header)
    print("-" * len(header))
    for r in table1b_rows:
        print(f"{r['streak']:<8} {r['vix_bucket']:<8} {fmt(r['mean_ret_2bar']):>10} "
              f"{fmt(r['win_rate'], 2):>8} {r['n_obs']:>6} {fmt(r['p_value']):>8} {r['flag']:>6}")

    # ══════════════════════════════════════════════════════════════════════
    # TABLE 2: RSI(14) 4H < 30 at streak end → next-bar return by VIX
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("TABLE 2: RSI(14) 4H < 30 at Streak End → Next-Bar Return by VIX Bucket")
    print("=" * 80)

    table2_rows = []
    for rsi_label, rsi_lo, rsi_hi in [("RSI<30", 0, 30), ("RSI 30-40", 30, 40), ("RSI>=40", 40, 101)]:
        for vb in VIX_BUCKETS:
            subset = [e for e in all_events
                      if e["rsi"] is not None and not np.isnan(e["rsi"])
                      and rsi_lo <= e["rsi"] < rsi_hi
                      and e["vix_bucket"] == vb
                      and e["next_bar_ret"] is not None]
            if not subset:
                table2_rows.append({
                    "rsi_group": rsi_label, "vix_bucket": vb,
                    "mean_ret": None, "win_rate": None,
                    "n_obs": 0, "p_value": None, "flag": "N<20",
                })
                continue
            rets = [e["next_bar_ret"] for e in subset]
            m, s, t, p, n = t_test_vs_zero(rets)
            wr = sum(1 for r in rets if r > 0) / len(rets)
            flag = "N<20" if n < 20 else ""
            table2_rows.append({
                "rsi_group": rsi_label, "vix_bucket": vb,
                "mean_ret": round(m * 100, 4), "win_rate": round(wr * 100, 2),
                "n_obs": n, "p_value": round(p, 4), "flag": flag,
            })

    header = f"{'RSI':<12} {'VIX':<8} {'Mean Ret%':>10} {'Win%':>8} {'N':>6} {'p-val':>8} {'Flag':>6}"
    print(header)
    print("-" * len(header))
    for r in table2_rows:
        print(f"{r['rsi_group']:<12} {r['vix_bucket']:<8} {fmt(r['mean_ret']):>10} "
              f"{fmt(r['win_rate'], 2):>8} {r['n_obs']:>6} {fmt(r['p_value']):>8} {r['flag']:>6}")

    # ══════════════════════════════════════════════════════════════════════
    # TABLE 3: Cross-reference — Daily entry vs 4H-timed entry
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("TABLE 3: Stage 1 vs Stage 2 Entry Comparison (4-day+ daily streak, VIX>=25)")
    print("=" * 80)

    if all_overlaps:
        # Summary stats
        daily_rets = [o["next_day_ret_daily"] for o in all_overlaps
                      if o["next_day_ret_daily"] is not None and not np.isnan(o["next_day_ret_daily"])]
        h4_rets = [o["next_bar_ret_4h"] for o in all_overlaps
                   if o["next_bar_ret_4h"] is not None and not np.isnan(o["next_bar_ret_4h"])]

        print(f"\nOverlapping events: {len(all_overlaps)}")
        if daily_rets:
            dm, ds, dt, dp, dn = t_test_vs_zero(daily_rets)
            dwr = sum(1 for r in daily_rets if r > 0) / len(daily_rets)
            print(f"  Daily entry:  mean={dm*100:.4f}%, win={dwr*100:.1f}%, N={dn}, p={dp:.4f}")
        if h4_rets:
            hm, hs, ht, hp, hn = t_test_vs_zero(h4_rets)
            hwr = sum(1 for r in h4_rets if r > 0) / len(h4_rets)
            print(f"  4H entry:     mean={hm*100:.4f}%, win={hwr*100:.1f}%, N={hn}, p={hp:.4f}")

        # Detail table
        print(f"\n{'Ticker':<8} {'Date':<12} {'Bar':<4} {'4H Str':>6} {'D Str':>5} "
              f"{'4H Ret%':>9} {'Daily Ret%':>10}")
        print("-" * 65)
        for o in sorted(all_overlaps, key=lambda x: (x["ticker"], x["date"])):
            h4r = fmt(o["next_bar_ret_4h"] * 100 if o["next_bar_ret_4h"] is not None else None)
            dr = fmt(o["next_day_ret_daily"] * 100 if o["next_day_ret_daily"] is not None else None)
            print(f"{o['ticker']:<8} {o['date']:<12} B{o['bar_num']:<3} {o['streak_4h']:>6} "
                  f"{o['streak_daily']:>5} {h4r:>9} {dr:>10}")
    else:
        print("No overlapping events found.")

    # ══════════════════════════════════════════════════════════════════════
    # SPLIT-SAMPLE VALIDATION
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("SPLIT-SAMPLE VALIDATION (50/50 random split)")
    print("=" * 80)

    split_rows = []
    for sbin in [2, 3, 4, 5, 6, 7, 8]:
        for vb in VIX_BUCKETS:
            for sp in ["A", "B"]:
                subset = [e for e in all_events
                          if e["streak_bin"] == sbin and e["vix_bucket"] == vb
                          and e["split"] == sp and e["next_bar_ret"] is not None]
                if not subset:
                    split_rows.append({
                        "streak": streak_labels[sbin], "vix_bucket": vb,
                        "split": sp, "mean_ret": None, "n_obs": 0,
                    })
                    continue
                rets = [e["next_bar_ret"] for e in subset]
                split_rows.append({
                    "streak": streak_labels[sbin], "vix_bucket": vb,
                    "split": sp, "mean_ret": round(np.mean(rets) * 100, 4),
                    "n_obs": len(rets),
                })

    header = f"{'Streak':<8} {'VIX':<8} {'Split':<6} {'Mean Ret%':>10} {'N':>6} {'Sign Match':>12}"
    print(header)
    print("-" * len(header))

    sign_matches = 0
    sign_total = 0
    prev = None
    for r in split_rows:
        sign_match = ""
        if r["split"] == "B" and prev is not None:
            if prev["mean_ret"] is not None and r["mean_ret"] is not None:
                sign_total += 1
                a_sign = 1 if prev["mean_ret"] > 0 else (-1 if prev["mean_ret"] < 0 else 0)
                b_sign = 1 if r["mean_ret"] > 0 else (-1 if r["mean_ret"] < 0 else 0)
                if a_sign == b_sign:
                    sign_matches += 1
                    sign_match = "YES"
                else:
                    sign_match = "NO"
        print(f"{r['streak']:<8} {r['vix_bucket']:<8} {r['split']:<6} "
              f"{fmt(r['mean_ret']):>10} {r['n_obs']:>6} {sign_match:>12}")
        prev = r

    pct = (sign_matches / sign_total * 100) if sign_total > 0 else 0
    print(f"\nSign consistency: {sign_matches}/{sign_total} ({pct:.0f}%)")

    # ── SAVE ALL RESULTS ─────────────────────────────────────────────────
    events_df = pd.DataFrame(all_events)
    events_df.to_csv(OUT_DIR / "all_4h_streak_events.csv", index=False)
    pd.DataFrame(table1_rows).to_csv(OUT_DIR / "table1_4h_streak_vix_nextbar.csv", index=False)
    pd.DataFrame(table1b_rows).to_csv(OUT_DIR / "table1b_4h_streak_vix_next2bar.csv", index=False)
    pd.DataFrame(table2_rows).to_csv(OUT_DIR / "table2_rsi4h_vix_nextbar.csv", index=False)
    pd.DataFrame(split_rows).to_csv(OUT_DIR / "split_sample_validation.csv", index=False)

    if all_overlaps:
        pd.DataFrame(all_overlaps).to_csv(OUT_DIR / "table3_stage1_vs_4h_comparison.csv", index=False)

    summary = {
        "study": "4H Consecutive Down Bars Bounce Probability (Stage 2)",
        "tickers_used": CERTIFIED_TICKERS,
        "n_tickers": len(ticker_counts),
        "total_events": len(all_events),
        "stage1_overlaps": len(all_overlaps),
        "bar_definition": {
            "bar1": "09:30-13:25 ET (48 M5 bars)",
            "bar2": "13:30-15:55 ET (30 M5 bars)",
        },
        "cross_day_continuity": "Bar2 day N → Bar1 day N+1 counted as consecutive",
        "vix_source": "FRED VIXCLS (prior day close, no lookahead)",
        "rsi_period": RSI_PERIOD,
        "split_seed": SPLIT_SEED,
        "split_sign_consistency": f"{sign_matches}/{sign_total} ({pct:.0f}%)",
        "ticker_event_counts": ticker_counts,
        "constraints": [
            "No lookahead: VIX = prior day close",
            "No volume features",
            "Session hours only: 09:30-15:55 ET",
            "Excluded: SPY (truncated), VIXY (truncated)",
        ],
    }
    with open(OUT_DIR / "study_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nAll results saved to {OUT_DIR}/")
    return summary


if __name__ == "__main__":
    run_study()
