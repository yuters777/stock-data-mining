#!/usr/bin/env python3
"""
Consecutive Down Days → Bounce Probability Study

Stage 0 Dataset Certification enforced:
  - Uses ONLY 25 certified tickers (excludes SPY, VIXY)
  - M5 session data: 09:30–15:55 ET
  - Daily close = last M5 bar close (15:55 ET)

No lookahead: VIX regime = prior day close.
No volume-based features.

Output saved to backtest_output/consecutive_down_study/
"""

import csv
import hashlib
import json
import os
import sys
from collections import defaultdict
from math import erfc, sqrt
from pathlib import Path
from random import Random

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "backtest_output"
OUT_DIR = ROOT / "backtest_output" / "consecutive_down_study"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Certified tickers (25/27 — exclude SPY, VIXY) ────────────────────────
CERTIFIED_TICKERS = [
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN",
    "COST", "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU",
    "NVDA", "PLTR", "SNOW", "TSLA", "TSM", "TXN", "V",
]

STREAK_BINS = [2, 3, 4, "5+"]
VIX_BUCKETS = ["<20", "20-25", ">=25"]
RSI_PERIOD = 14
SPLIT_SEED = 42


# ── Helpers ───────────────────────────────────────────────────────────────

def p_from_t(t_stat, df_):
    """Two-sided p-value from t-stat using normal approx."""
    return erfc(abs(t_stat) / sqrt(2))


def t_test_vs_zero(arr):
    """One-sample t-test vs 0. Returns (mean, std, t, p, n)."""
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
    """Compute RSI(period) from a Series of closes. Returns Series."""
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def load_vix():
    """Load VIX daily data from FRED CSV. Returns dict: date_str -> close."""
    vix_path = ROOT / "Fetched_Data" / "VIXCLS_FRED_real.csv"
    vix = {}
    with open(vix_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            val = row["VIXCLS"].strip()
            if val == "." or val == "":
                continue
            try:
                vix[row["observation_date"]] = float(val)
            except ValueError:
                continue
    return vix


def vix_bucket(vix_val):
    """Classify VIX into buckets."""
    if vix_val is None:
        return None
    if vix_val < 20:
        return "<20"
    elif vix_val < 25:
        return "20-25"
    else:
        return ">=25"


def load_m5_daily(ticker):
    """
    Load M5 FIXED data, compute daily OHLC from session bars.
    Daily close = last bar close (15:55 ET).
    Daily high/low = session high/low.
    Returns DataFrame with columns: date, open, high, low, close.
    """
    fp = DATA_DIR / f"{ticker}_m5_regsess_FIXED.csv"
    if not fp.exists():
        return None
    df = pd.read_csv(fp, parse_dates=["Datetime"])
    df["date"] = df["Datetime"].dt.date

    daily = df.groupby("date").agg(
        open=("Open", "first"),
        high=("High", "max"),
        low=("Low", "min"),
        close=("Close", "last"),
    ).reset_index()
    daily = daily.sort_values("date").reset_index(drop=True)
    return daily


def build_streak_events(daily, vix_dict):
    """
    For each day, compute return (close-to-close).
    Identify consecutive down-day streaks.
    For each streak endpoint, gather metrics.
    No lookahead: VIX at streak end = prior day's VIX close.
    """
    daily = daily.copy()
    daily["ret"] = daily["close"].pct_change()
    daily["rsi"] = compute_rsi(daily["close"], RSI_PERIOD)
    daily["date_str"] = daily["date"].astype(str)

    # Map VIX: for day i, use prior day's VIX close (no lookahead)
    daily["vix_prior"] = None
    for i in range(1, len(daily)):
        prev_date = str(daily.iloc[i - 1]["date"])
        daily.iloc[i, daily.columns.get_loc("vix_prior")] = vix_dict.get(prev_date)

    events = []
    n = len(daily)
    streak = 0

    for i in range(1, n):
        if daily.iloc[i]["ret"] < 0:
            streak += 1
        else:
            # streak just ended at i-1, but we record at the END of streak
            # Actually, we want to measure at the streak endpoint
            # Let's reconsider: we record when streak >= 2 at position i-1
            streak = 0

    # Better approach: scan for all streak endpoints
    streak = 0
    for i in range(1, n):
        if daily.iloc[i]["ret"] < 0:
            streak += 1
        else:
            streak = 0

        # If we have streak >= 2 and next day exists
        if streak >= 2:
            streak_end_idx = i  # last down day
            streak_len = streak

            # Next-day return (close-to-close)
            if streak_end_idx + 1 < n:
                next_day_ret = daily.iloc[streak_end_idx + 1]["ret"]
                next_day_high = daily.iloc[streak_end_idx + 1]["high"]
                next_day_low = daily.iloc[streak_end_idx + 1]["low"]
                next_day_close = daily.iloc[streak_end_idx + 1]["close"]
                streak_end_close = daily.iloc[streak_end_idx]["close"]
                next_day_range = (next_day_high - next_day_low) / streak_end_close

                # Max bounce within next 3 days
                max_bounce = None
                for j in range(1, 4):
                    if streak_end_idx + j < n:
                        bounce = (daily.iloc[streak_end_idx + j]["close"] - streak_end_close) / streak_end_close
                        if max_bounce is None or bounce > max_bounce:
                            max_bounce = bounce

                rsi_val = daily.iloc[streak_end_idx]["rsi"]
                vix_val = daily.iloc[streak_end_idx]["vix_prior"]

                event = {
                    "streak_len": streak_len,
                    "streak_bin": min(streak_len, 5),  # 2,3,4,5+
                    "date": str(daily.iloc[streak_end_idx]["date"]),
                    "next_day_ret": next_day_ret,
                    "next_day_range": next_day_range,
                    "max_bounce_3d": max_bounce,
                    "rsi": rsi_val,
                    "vix": vix_val,
                    "vix_bucket": vix_bucket(vix_val),
                }
                events.append(event)

    return events


# ── Main ──────────────────────────────────────────────────────────────────

def run_study():
    print("=" * 80)
    print("CONSECUTIVE DOWN DAYS → BOUNCE PROBABILITY STUDY")
    print("=" * 80)

    # Load VIX
    vix_dict = load_vix()
    print(f"VIX data: {len(vix_dict)} days loaded")

    # Collect all events across tickers
    all_events = []
    ticker_counts = {}
    for ticker in CERTIFIED_TICKERS:
        daily = load_m5_daily(ticker)
        if daily is None:
            print(f"  SKIP {ticker}: no data")
            continue
        events = build_streak_events(daily, vix_dict)
        ticker_counts[ticker] = len(events)
        for e in events:
            e["ticker"] = ticker
        all_events.extend(events)
        print(f"  {ticker}: {len(events)} streak events from {len(daily)} days")

    print(f"\nTotal events: {len(all_events)} across {len(ticker_counts)} tickers")

    # ── Split-sample: random 50/50 ───────────────────────────────────────
    rng = Random(SPLIT_SEED)
    shuffled = list(range(len(all_events)))
    rng.shuffle(shuffled)
    mid = len(shuffled) // 2
    split_a_idx = set(shuffled[:mid])
    split_b_idx = set(shuffled[mid:])

    for i, e in enumerate(all_events):
        e["split"] = "A" if i in split_a_idx else "B"

    # ── TABLE 1: N_consecutive_days × VIX_bucket ─────────────────────────
    print("\n" + "=" * 80)
    print("TABLE 1: Streak Length × VIX Bucket → Next-Day Return Stats")
    print("=" * 80)

    streak_labels = {2: "2", 3: "3", 4: "4", 5: "5+"}
    table1_rows = []

    for sbin in [2, 3, 4, 5]:
        for vbucket in VIX_BUCKETS:
            subset = [e for e in all_events
                      if e["streak_bin"] == sbin
                      and e["vix_bucket"] == vbucket]
            if not subset:
                table1_rows.append({
                    "streak": streak_labels[sbin],
                    "vix_bucket": vbucket,
                    "mean_ret": None,
                    "win_rate": None,
                    "n_obs": 0,
                    "p_value": None,
                    "flag": "N<20",
                })
                continue

            rets = [e["next_day_ret"] for e in subset]
            m, s, t, p, n = t_test_vs_zero(rets)
            win_rate = sum(1 for r in rets if r > 0) / len(rets)
            flag = "N<20" if n < 20 else ""

            table1_rows.append({
                "streak": streak_labels[sbin],
                "vix_bucket": vbucket,
                "mean_ret": round(m * 100, 4),
                "win_rate": round(win_rate * 100, 2),
                "n_obs": n,
                "p_value": round(p, 4),
                "flag": flag,
            })

    # Print Table 1
    header = f"{'Streak':<8} {'VIX':<8} {'Mean Ret%':>10} {'Win%':>8} {'N':>6} {'p-val':>8} {'Flag':>6}"
    print(header)
    print("-" * len(header))
    for row in table1_rows:
        mr = f"{row['mean_ret']:.4f}" if row['mean_ret'] is not None else "N/A"
        wr = f"{row['win_rate']:.2f}" if row['win_rate'] is not None else "N/A"
        pv = f"{row['p_value']:.4f}" if row['p_value'] is not None else "N/A"
        print(f"{row['streak']:<8} {row['vix_bucket']:<8} {mr:>10} {wr:>8} {row['n_obs']:>6} {pv:>8} {row['flag']:>6}")

    # ── TABLE 1b: Same but with max_bounce_3d and intraday range ─────────
    print("\n" + "=" * 80)
    print("TABLE 1b: Streak Length × VIX Bucket → Max Bounce (3d) & Intraday Range")
    print("=" * 80)

    table1b_rows = []
    for sbin in [2, 3, 4, 5]:
        for vbucket in VIX_BUCKETS:
            subset = [e for e in all_events
                      if e["streak_bin"] == sbin
                      and e["vix_bucket"] == vbucket]
            if not subset:
                table1b_rows.append({
                    "streak": streak_labels[sbin],
                    "vix_bucket": vbucket,
                    "mean_bounce_3d": None,
                    "mean_range": None,
                    "n_obs": 0,
                    "flag": "N<20",
                })
                continue

            bounces = [e["max_bounce_3d"] for e in subset if e["max_bounce_3d"] is not None]
            ranges = [e["next_day_range"] for e in subset]
            n = len(subset)
            flag = "N<20" if n < 20 else ""

            table1b_rows.append({
                "streak": streak_labels[sbin],
                "vix_bucket": vbucket,
                "mean_bounce_3d": round(np.mean(bounces) * 100, 4) if bounces else None,
                "mean_range": round(np.mean(ranges) * 100, 4) if ranges else None,
                "n_obs": n,
                "flag": flag,
            })

    header = f"{'Streak':<8} {'VIX':<8} {'Bounce3d%':>10} {'Range%':>10} {'N':>6} {'Flag':>6}"
    print(header)
    print("-" * len(header))
    for row in table1b_rows:
        b3 = f"{row['mean_bounce_3d']:.4f}" if row['mean_bounce_3d'] is not None else "N/A"
        rg = f"{row['mean_range']:.4f}" if row['mean_range'] is not None else "N/A"
        print(f"{row['streak']:<8} {row['vix_bucket']:<8} {b3:>10} {rg:>10} {row['n_obs']:>6} {row['flag']:>6}")

    # ── TABLE 2: RSI extreme (<30) vs RSI moderate (30-40) ────────────────
    print("\n" + "=" * 80)
    print("TABLE 2: RSI at Streak End → Next-Day Return")
    print("=" * 80)

    table2_rows = []
    for rsi_label, rsi_lo, rsi_hi in [("RSI<30", 0, 30), ("RSI 30-40", 30, 40)]:
        subset = [e for e in all_events
                  if e["rsi"] is not None
                  and not np.isnan(e["rsi"])
                  and rsi_lo <= e["rsi"] < rsi_hi]
        if not subset:
            table2_rows.append({
                "rsi_group": rsi_label,
                "mean_ret": None,
                "win_rate": None,
                "n_obs": 0,
                "p_value": None,
                "flag": "N<20",
            })
            continue

        rets = [e["next_day_ret"] for e in subset]
        m, s, t, p, n = t_test_vs_zero(rets)
        win_rate = sum(1 for r in rets if r > 0) / len(rets)
        flag = "N<20" if n < 20 else ""

        table2_rows.append({
            "rsi_group": rsi_label,
            "mean_ret": round(m * 100, 4),
            "win_rate": round(win_rate * 100, 2),
            "n_obs": n,
            "p_value": round(p, 4),
            "flag": flag,
        })

    header = f"{'RSI Group':<12} {'Mean Ret%':>10} {'Win%':>8} {'N':>6} {'p-val':>8} {'Flag':>6}"
    print(header)
    print("-" * len(header))
    for row in table2_rows:
        mr = f"{row['mean_ret']:.4f}" if row['mean_ret'] is not None else "N/A"
        wr = f"{row['win_rate']:.2f}" if row['win_rate'] is not None else "N/A"
        pv = f"{row['p_value']:.4f}" if row['p_value'] is not None else "N/A"
        print(f"{row['rsi_group']:<12} {mr:>10} {wr:>8} {row['n_obs']:>6} {pv:>8} {row['flag']:>6}")

    # ── TABLE 2b: RSI breakdown by streak length ─────────────────────────
    print("\n" + "=" * 80)
    print("TABLE 2b: RSI Group × Streak Length → Next-Day Return")
    print("=" * 80)

    table2b_rows = []
    for rsi_label, rsi_lo, rsi_hi in [("RSI<30", 0, 30), ("RSI 30-40", 30, 40)]:
        for sbin in [2, 3, 4, 5]:
            subset = [e for e in all_events
                      if e["rsi"] is not None
                      and not np.isnan(e["rsi"])
                      and rsi_lo <= e["rsi"] < rsi_hi
                      and e["streak_bin"] == sbin]
            if not subset:
                table2b_rows.append({
                    "rsi_group": rsi_label,
                    "streak": streak_labels[sbin],
                    "mean_ret": None,
                    "win_rate": None,
                    "n_obs": 0,
                    "p_value": None,
                    "flag": "N<20",
                })
                continue
            rets = [e["next_day_ret"] for e in subset]
            m, s, t, p, n = t_test_vs_zero(rets)
            win_rate = sum(1 for r in rets if r > 0) / len(rets)
            flag = "N<20" if n < 20 else ""
            table2b_rows.append({
                "rsi_group": rsi_label,
                "streak": streak_labels[sbin],
                "mean_ret": round(m * 100, 4),
                "win_rate": round(win_rate * 100, 2),
                "n_obs": n,
                "p_value": round(p, 4),
                "flag": flag,
            })

    header = f"{'RSI':<12} {'Streak':<8} {'Mean Ret%':>10} {'Win%':>8} {'N':>6} {'p-val':>8} {'Flag':>6}"
    print(header)
    print("-" * len(header))
    for row in table2b_rows:
        mr = f"{row['mean_ret']:.4f}" if row['mean_ret'] is not None else "N/A"
        wr = f"{row['win_rate']:.2f}" if row['win_rate'] is not None else "N/A"
        pv = f"{row['p_value']:.4f}" if row['p_value'] is not None else "N/A"
        print(f"{row['rsi_group']:<12} {row['streak']:<8} {mr:>10} {wr:>8} {row['n_obs']:>6} {pv:>8} {row['flag']:>6}")

    # ── SPLIT-SAMPLE VALIDATION ──────────────────────────────────────────
    print("\n" + "=" * 80)
    print("SPLIT-SAMPLE VALIDATION (50/50 random split)")
    print("=" * 80)

    split_rows = []
    for sbin in [2, 3, 4, 5]:
        for vbucket in VIX_BUCKETS:
            for split_label in ["A", "B"]:
                subset = [e for e in all_events
                          if e["streak_bin"] == sbin
                          and e["vix_bucket"] == vbucket
                          and e["split"] == split_label]
                if not subset:
                    split_rows.append({
                        "streak": streak_labels[sbin],
                        "vix_bucket": vbucket,
                        "split": split_label,
                        "mean_ret": None,
                        "n_obs": 0,
                    })
                    continue
                rets = [e["next_day_ret"] for e in subset]
                m = np.mean(rets)
                split_rows.append({
                    "streak": streak_labels[sbin],
                    "vix_bucket": vbucket,
                    "split": split_label,
                    "mean_ret": round(m * 100, 4),
                    "n_obs": len(rets),
                })

    # Check sign consistency
    header = f"{'Streak':<8} {'VIX':<8} {'Split':<6} {'Mean Ret%':>10} {'N':>6} {'Sign Match':>12}"
    print(header)
    print("-" * len(header))

    sign_matches = 0
    sign_total = 0
    prev_row = None
    for row in split_rows:
        sign_match = ""
        if row["split"] == "B" and prev_row is not None:
            if prev_row["mean_ret"] is not None and row["mean_ret"] is not None:
                sign_total += 1
                a_sign = 1 if prev_row["mean_ret"] > 0 else (-1 if prev_row["mean_ret"] < 0 else 0)
                b_sign = 1 if row["mean_ret"] > 0 else (-1 if row["mean_ret"] < 0 else 0)
                if a_sign == b_sign:
                    sign_matches += 1
                    sign_match = "YES"
                else:
                    sign_match = "NO"
        mr = f"{row['mean_ret']:.4f}" if row['mean_ret'] is not None else "N/A"
        print(f"{row['streak']:<8} {row['vix_bucket']:<8} {row['split']:<6} {mr:>10} {row['n_obs']:>6} {sign_match:>12}")
        prev_row = row

    pct_match = (sign_matches / sign_total * 100) if sign_total > 0 else 0
    print(f"\nSign consistency: {sign_matches}/{sign_total} ({pct_match:.0f}%)")

    # ── SAVE RESULTS ─────────────────────────────────────────────────────
    # Save all events as CSV
    events_df = pd.DataFrame(all_events)
    events_path = OUT_DIR / "all_streak_events.csv"
    events_df.to_csv(events_path, index=False)
    print(f"\nSaved {len(events_df)} events to {events_path}")

    # Save Table 1
    t1_df = pd.DataFrame(table1_rows)
    t1_path = OUT_DIR / "table1_streak_vix_nextday.csv"
    t1_df.to_csv(t1_path, index=False)

    # Save Table 1b
    t1b_df = pd.DataFrame(table1b_rows)
    t1b_path = OUT_DIR / "table1b_bounce_range.csv"
    t1b_df.to_csv(t1b_path, index=False)

    # Save Table 2
    t2_df = pd.DataFrame(table2_rows)
    t2_path = OUT_DIR / "table2_rsi_nextday.csv"
    t2_df.to_csv(t2_path, index=False)

    # Save Table 2b
    t2b_df = pd.DataFrame(table2b_rows)
    t2b_path = OUT_DIR / "table2b_rsi_streak_nextday.csv"
    t2b_df.to_csv(t2b_path, index=False)

    # Save split-sample
    split_df = pd.DataFrame(split_rows)
    split_path = OUT_DIR / "split_sample_validation.csv"
    split_df.to_csv(split_path, index=False)

    # Save summary JSON
    summary = {
        "study": "Consecutive Down Days Bounce Probability",
        "tickers_used": CERTIFIED_TICKERS,
        "n_tickers": len(ticker_counts),
        "total_events": len(all_events),
        "data_source": "M5 regular session FIXED (15:55 ET close)",
        "vix_source": "FRED VIXCLS (prior day close, no lookahead)",
        "rsi_period": RSI_PERIOD,
        "split_seed": SPLIT_SEED,
        "split_sign_consistency": f"{sign_matches}/{sign_total} ({pct_match:.0f}%)",
        "ticker_event_counts": ticker_counts,
        "constraints": [
            "No lookahead: VIX = prior day close",
            "No volume-based features",
            "Session hours only: 09:30-15:55 ET",
            "Daily close = last M5 bar close",
            "Excluded: SPY (truncated), VIXY (truncated)",
        ],
    }
    summary_path = OUT_DIR / "study_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nAll results saved to {OUT_DIR}/")
    print("Files: all_streak_events.csv, table1_*.csv, table2_*.csv, split_sample_validation.csv, study_summary.json")

    return summary


if __name__ == "__main__":
    run_study()
