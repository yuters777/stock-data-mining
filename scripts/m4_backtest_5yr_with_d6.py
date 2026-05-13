#!/usr/bin/env python3
"""
Module 4 Mean-Reversion -- 5-Year Backtest (D6 filter ON)
Production-mirror version: streak>=3 + VIX>=25 + RSI<35 + D6 VIX 5d ROC > 30%

D6 VIX ROC filter (FROZEN per PI v33):
  ROC = (vix_today - vix_5d_trading_days_ago) / vix_5d_ago * 100
  D6 BLOCKS when ROC <= 30% (chronic elevation)
  D6 PASSES when ROC > 30% (acute spike)
"""

import os
import sys
import json
import glob
import warnings
import numpy as np
import pandas as pd
from urllib.request import urlopen

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import everything from base script
from m4_backtest_5yr import (
    load_vix, rsi14, _norm_m5, build_4h, flag_corrupt, calc_streak,
    apply_ema21_warmup_mask, get_tickers, prior_vix,
    backtest_antisignal, stats, profit_factor,
    DATA, OUT, EXCLUDE,
)
from backtest_utils_extended import load_earnings, is_earnings_window

warnings.filterwarnings("ignore")

# D6 frozen constants from production module4.py
D6_VIX_ROC_ENABLED = True
D6_VIX_ROC_THRESHOLD = 30.0


def compute_vix_5d_roc(bar_date, vix: pd.Series) -> float | None:
    """Production D6 ROC: (vix_today - vix_5d_ago) / vix_5d_ago * 100.
    Uses 5 prior trading days from VIX daily series.
    Returns None if insufficient history.
    """
    # All VIX dates strictly before bar_date (most recent first lookup)
    available = vix.index[vix.index < bar_date]
    if len(available) < 6:
        return None
    today_vix = float(vix[available[-1]])
    vix_5d_ago = float(vix[available[-6]])  # -1 = today, -6 = 5 days back
    if vix_5d_ago <= 0:
        return None
    return (today_vix - vix_5d_ago) / vix_5d_ago * 100.0


def backtest_ticker_d6(ticker: str, fpath: str, vix: pd.Series,
                       earnings_dict: dict = None, buffer_days: int = 0) -> list[dict]:
    """Same as base backtest_ticker but adds D6 filter after VIX gate."""
    try:
        raw = pd.read_csv(fpath)
    except Exception:
        return []
    raw = _norm_m5(raw)
    if raw.empty or "Close" not in raw.columns:
        return []

    bars = build_4h(raw)
    if bars.empty or len(bars) < 20:
        return []

    corrupt = flag_corrupt(bars["Close"]).values
    bars["ema21"] = bars["Close"].ewm(span=21, adjust=False).mean()
    if not fpath.endswith("_m5_full.csv"):
        bars["ema21"] = apply_ema21_warmup_mask(bars)
    bars["rsi"] = rsi14(bars["Close"])
    bars["streak"] = calc_streak(bars)

    closes = bars["Close"].values
    emas = bars["ema21"].values
    rsis = bars["rsi"].values
    streaks = bars["streak"]
    dates = [ts.date() for ts in bars["ts"]]

    trades = []
    i = 0
    while i < len(bars):
        if corrupt[i]:
            i += 1
            continue

        vix_val = prior_vix(dates[i], vix)
        if np.isnan(vix_val) or vix_val < 25:
            i += 1
            continue

        # D6 VIX 5d ROC filter (PRODUCTION GATE, blocks chronic elevation)
        if D6_VIX_ROC_ENABLED:
            roc_5d = compute_vix_5d_roc(dates[i], vix)
            if roc_5d is None:
                i += 1
                continue
            if roc_5d <= D6_VIX_ROC_THRESHOLD:
                i += 1
                continue

        rsi_val = rsis[i]
        if np.isnan(rsi_val) or rsi_val >= 35:
            i += 1
            continue

        if streaks.iloc[i] < 3:
            i += 1
            continue

        if np.isnan(emas[i]):
            i += 1
            continue

        if buffer_days > 0 and earnings_dict is not None:
            if is_earnings_window(ticker, dates[i], earnings_dict, buffer_days=buffer_days):
                i += 1
                continue

        entry_price = closes[i]
        entry_date = dates[i]

        exit_price = None
        exit_date = None
        exit_type = None
        bars_held = 0

        for j in range(i + 1, min(i + 11, len(bars))):
            bars_held += 1
            if corrupt[j]:
                exit_price = closes[j]
                exit_date = dates[j]
                exit_type = "hard_max"
                break
            if closes[j] >= emas[j]:
                exit_price = closes[j]
                exit_date = dates[j]
                exit_type = "ema21"
                break
            if bars_held == 10:
                exit_price = closes[j]
                exit_date = dates[j]
                exit_type = "hard_max"
                break

        if exit_price is None:
            i += 1
            continue

        ret = (exit_price - entry_price) / entry_price * 100
        trades.append({
            "ticker": ticker,
            "entry_date": str(entry_date),
            "exit_date": str(exit_date),
            "entry_price": round(float(entry_price), 4),
            "exit_price": round(float(exit_price), 4),
            "return_pct": round(float(ret), 4),
            "bars_held": int(bars_held),
            "exit_type": exit_type,
            "rsi_at_entry": round(float(rsi_val), 2),
            "vix_at_entry": round(float(vix_val), 2),
            "vix_5d_roc": round(float(roc_5d), 2),
        })
        i += bars_held + 1

    return trades


def main():
    print("=== Module 4 Mean-Reversion — 5yr Backtest (D6 FILTER ON) ===\n")
    print("Loading VIX data...")
    vix = load_vix()

    tickers = get_tickers()
    print(f"  Tickers ({len(tickers)}): {[t for t, _ in tickers]}\n")

    earnings_dict = load_earnings()

    all_trades = []
    for ticker, fpath in tickers:
        trades = backtest_ticker_d6(ticker, fpath, vix, earnings_dict=earnings_dict, buffer_days=0)
        print(f"  {ticker:6s}: {len(trades)} trades")
        all_trades.extend(trades)

    if not all_trades:
        print("\nNo trades found.")
        return

    df = pd.DataFrame(all_trades)
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["year"] = df["entry_date"].dt.year

    overall = stats(df["return_pct"].tolist())
    overall["avg_hold"] = round(float(df["bars_held"].mean()), 2)
    overall["ema21_exit_pct"] = round(float((df["exit_type"] == "ema21").mean() * 100), 2)
    overall["hardmax_pct"] = round(float((df["exit_type"] == "hard_max").mean() * 100), 2)

    by_year = {}
    for yr in sorted(df["year"].unique()):
        sub = df[df["year"] == yr]
        s = stats(sub["return_pct"].tolist())
        by_year[str(yr)] = {"n": s["n"], "mean": s["mean"], "wr": s["wr"]}

    o = overall
    print("\n=== RESULTS WITH D6 FILTER ===")
    print(f"OVERALL: N={o['n']}, Mean={o['mean']}%, WR={o['wr']}%, PF={o['pf']}, Sharpe={o['sharpe']}, Avg hold={o['avg_hold']} bars")
    print(f"         EMA21 exit={o['ema21_exit_pct']}%, Hard max exit={o['hardmax_pct']}%")

    print("\nBY YEAR:")
    for yr, s in by_year.items():
        print(f"  {yr}: N={s['n']}, Mean={s['mean']}%, WR={s['wr']}%")

    print("\nCANONICAL COMPARISON:")
    print(f"  DB locked Apr 16: N=47, Mean=+7.52%, WR=94%, PF=21.38")
    print(f"  Reconstructed   : N={o['n']}, Mean={o['mean']}%, WR={o['wr']}%, PF={o['pf']}")
    delta_n = o['n'] - 47
    print(f"  N delta: {delta_n:+d}")

    trades_path = os.path.join(OUT, "m4_5yr_trades_D6.csv")
    summary_path = os.path.join(OUT, "m4_5yr_summary_D6.json")
    df.to_csv(trades_path, index=False)

    summary = {
        "overall": overall,
        "by_year": by_year,
        "config": {
            "d6_filter_enabled": True,
            "d6_threshold": D6_VIX_ROC_THRESHOLD,
            "streak_threshold": 3,
            "vix_gate": 25.0,
            "rsi_gate": 35.0,
            "max_bars": 10,
            "tickers": [t for t, _ in tickers],
        },
    }
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\nTrades  -> {trades_path}")
    print(f"Summary -> {summary_path}")


if __name__ == "__main__":
    main()