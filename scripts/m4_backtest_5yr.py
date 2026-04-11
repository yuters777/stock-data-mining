#!/usr/bin/env python3
"""
Module 4 Mean-Reversion — 5-Year Backtest
Frozen parameters: 3 consecutive 4H down bars + VIX>=25 + RSI(14)<35
Entry: trigger bar close. Exit: first 4H close >= EMA21 or bar 10 hard max.
"""

import os
import json
import glob
import warnings
import numpy as np
import pandas as pd
from urllib.request import urlopen

warnings.filterwarnings("ignore")

# ── Paths ──────────────────────────────────────────────────────────────────
BASE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA  = os.path.join(BASE, "Fetched_Data")
OUT   = os.path.join(BASE, "backtest_results")
os.makedirs(OUT, exist_ok=True)

EXCLUDE    = {"SPY", "VIXY", "BTC", "ETH"}
SKIP_FILES = {"VIXCLS_FRED_real.csv", "VXVCLS.csv"}

VIX_URL = ("https://fred.stlouisfed.org/graph/fredgraph.csv"
           "?id=VIXCLS&cosd=2021-01-01&coed=2026-04-11")

# RTH in minutes-since-midnight (UTC): 13:30–19:55
RTH_S  = 13 * 60 + 30   # 810
RTH_E  = 19 * 60 + 55   # 1195
BAR1_E = 17 * 60 + 25   # 1045  Bar-1 ends
BAR2_S = 17 * 60 + 30   # 1050  Bar-2 starts


# ── VIX ───────────────────────────────────────────────────────────────────
def load_vix() -> pd.Series:
    """Return Series{date -> float} of daily VIX closes."""
    from io import StringIO
    try:
        with urlopen(VIX_URL, timeout=10) as r:
            raw = r.read().decode()
        df = pd.read_csv(StringIO(raw))
    except Exception:
        df = pd.read_csv(os.path.join(DATA, "VIXCLS_FRED_real.csv"))
    df.columns = ["date", "vix"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df["vix"]  = pd.to_numeric(df["vix"], errors="coerce")
    df = df.dropna()
    return df.set_index("date")["vix"]


# ── RSI(14) — Wilder's smoothing ───────────────────────────────────────────
def rsi14(close: pd.Series) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    ag    = gain.ewm(alpha=1 / 14, adjust=False).mean()
    al    = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs    = ag / al.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


# ── 4H bar builder ─────────────────────────────────────────────────────────
def build_4h(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filter raw M5 data to RTH, assign to Bar-1 (13:30-17:25) or
    Bar-2 (17:30-19:55), then aggregate OHLCV.
    """
    df = df.copy()
    df["dt"]  = pd.to_datetime(df["Datetime"], errors="coerce")
    df = df.sort_values("dt").dropna(subset=["dt"])
    tod = df["dt"].dt.hour * 60 + df["dt"].dt.minute

    rth_mask = (tod >= RTH_S) & (tod <= RTH_E)
    df = df[rth_mask].copy()
    if df.empty:
        return pd.DataFrame()

    tod_filt     = df["dt"].dt.hour * 60 + df["dt"].dt.minute
    df["date"]   = df["dt"].dt.date
    df["session"] = (tod_filt > BAR1_E).astype(int)   # 0 = Bar-1, 1 = Bar-2

    def agg_bar(g):
        g = g.sort_values("dt")
        return pd.Series({
            "Open":   g["Open"].iloc[0],
            "High":   g["High"].max(),
            "Low":    g["Low"].min(),
            "Close":  g["Close"].iloc[-1],
            "Volume": g["Volume"].sum(),
        })

    bars = (
        df.groupby(["date", "session"], sort=True)
          .apply(agg_bar)
          .reset_index()
    )

    # Canonical bar timestamp (start of each session)
    bar_ts = bars.apply(
        lambda r: pd.Timestamp(str(r["date"])) + pd.Timedelta(
            hours=13, minutes=30) if r["session"] == 0
        else pd.Timestamp(str(r["date"])) + pd.Timedelta(hours=17, minutes=30),
        axis=1,
    )
    bars["ts"] = bar_ts
    return bars.sort_values("ts").reset_index(drop=True)


# ── Meta protection: flag split-corrupted bars ─────────────────────────────
def flag_corrupt(closes: pd.Series) -> pd.Series:
    """True where an adjacent-bar price ratio exceeds 6× (>500% jump)."""
    ratio   = closes / closes.shift(1)
    bad     = (ratio > 6) | (ratio < 1 / 6)
    # Contaminate the surrounding bar as well
    return bad | bad.shift(1, fill_value=False) | bad.shift(-1, fill_value=False)


# ── Consecutive down-bar streak ────────────────────────────────────────────
def calc_streak(bars: pd.DataFrame) -> np.ndarray:
    """
    Streak of consecutive 4H down bars (close < open).
    Resets on: (a) up bar, or (b) time gap > 30 h between bars.
    """
    n       = len(bars)
    streaks = np.zeros(n, dtype=np.int32)
    ts_ns   = bars["ts"].values.astype(np.int64)   # nanoseconds
    closes  = bars["Close"].values
    opens   = bars["Open"].values
    s = 0
    for i in range(n):
        if i > 0:
            gap_h = (ts_ns[i] - ts_ns[i - 1]) / 3_600_000_000_000  # ns → h
            if gap_h > 30:
                s = 0
        if closes[i] < opens[i]:
            s += 1
        else:
            s = 0
        streaks[i] = s
    return streaks


# ── Ticker discovery ────────────────────────────────────────────────────────
def get_tickers() -> list[tuple[str, str]]:
    result = []
    for fpath in sorted(glob.glob(os.path.join(DATA, "*.csv"))):
        name = os.path.basename(fpath)
        if name in SKIP_FILES:
            continue
        if name.endswith("_crypto_data.csv"):
            ticker = name[: -len("_crypto_data.csv")]
        elif name.endswith("_data.csv"):
            ticker = name[: -len("_data.csv")]
        else:
            continue
        if ticker not in EXCLUDE:
            result.append((ticker, fpath))
    return result


# ── Prior-day VIX lookup ────────────────────────────────────────────────────
def prior_vix(bar_date, vix: pd.Series):
    """Return the most-recent VIX close strictly before bar_date, or NaN."""
    avail = vix.index[vix.index < bar_date]
    if len(avail) == 0:
        return np.nan
    return float(vix[avail[-1]])


# ── Core backtest (main signal) ─────────────────────────────────────────────
def backtest_ticker(ticker: str, fpath: str, vix: pd.Series) -> list[dict]:
    try:
        raw = pd.read_csv(fpath)
    except Exception:
        return []
    if raw.empty or "Close" not in raw.columns:
        return []

    bars = build_4h(raw)
    if bars.empty or len(bars) < 20:
        return []

    corrupt         = flag_corrupt(bars["Close"]).values
    bars["ema21"]   = bars["Close"].ewm(span=21, adjust=False).mean()
    bars["rsi"]     = rsi14(bars["Close"])
    bars["streak"]  = calc_streak(bars)

    closes  = bars["Close"].values
    emas    = bars["ema21"].values
    rsis    = bars["rsi"].values
    streaks = bars["streak"]
    dates   = [ts.date() for ts in bars["ts"]]

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

        rsi_val = rsis[i]
        if np.isnan(rsi_val) or rsi_val >= 35:
            i += 1
            continue

        if streaks.iloc[i] < 3:
            i += 1
            continue

        # ── Trigger fired ──
        entry_price = closes[i]
        entry_date  = dates[i]

        exit_price = None
        exit_date  = None
        exit_type  = None
        bars_held  = 0

        for j in range(i + 1, min(i + 11, len(bars))):
            bars_held += 1
            if corrupt[j]:
                exit_price = closes[j]
                exit_date  = dates[j]
                exit_type  = "hard_max"
                break
            if closes[j] >= emas[j]:
                exit_price = closes[j]
                exit_date  = dates[j]
                exit_type  = "ema21"
                break
            if bars_held == 10:
                exit_price = closes[j]
                exit_date  = dates[j]
                exit_type  = "hard_max"
                break

        if exit_price is None:
            i += 1
            continue

        ret = (exit_price - entry_price) / entry_price * 100
        trades.append({
            "ticker":       ticker,
            "entry_date":   str(entry_date),
            "exit_date":    str(exit_date),
            "entry_price":  round(float(entry_price), 4),
            "exit_price":   round(float(exit_price), 4),
            "return_pct":   round(float(ret), 4),
            "bars_held":    int(bars_held),
            "exit_type":    exit_type,
            "rsi_at_entry": round(float(rsi_val), 2),
            "vix_at_entry": round(float(vix_val), 2),
        })
        # Skip past exit bar — one position per ticker, no stacking
        i += bars_held + 1

    return trades


# ── Anti-signal backtest ───────────────────────────────────────────────────
def backtest_antisignal(ticker: str, fpath: str, vix: pd.Series,
                         mode: str) -> list[float]:
    """
    mode='rsi_high' : streak>=3, VIX>=25, RSI>=35  (relaxed RSI gate)
    mode='vix_low'  : streak>=3, VIX<20,  RSI<35   (relaxed VIX gate)
    Returns list of return_pct values.
    """
    try:
        raw = pd.read_csv(fpath)
    except Exception:
        return []
    bars = build_4h(raw)
    if bars.empty or len(bars) < 20:
        return []

    corrupt        = flag_corrupt(bars["Close"]).values
    bars["ema21"]  = bars["Close"].ewm(span=21, adjust=False).mean()
    bars["rsi"]    = rsi14(bars["Close"])
    bars["streak"] = calc_streak(bars)

    closes  = bars["Close"].values
    emas    = bars["ema21"].values
    rsis    = bars["rsi"].values
    streaks = bars["streak"]
    dates   = [ts.date() for ts in bars["ts"]]

    rets = []
    i = 0
    while i < len(bars):
        if corrupt[i] or streaks.iloc[i] < 3:
            i += 1
            continue
        vix_val = prior_vix(dates[i], vix)
        if np.isnan(vix_val):
            i += 1
            continue
        rsi_val = rsis[i]
        if np.isnan(rsi_val):
            i += 1
            continue

        if mode == "rsi_high":
            triggered = (vix_val >= 25) and (rsi_val >= 35)
        else:  # vix_low
            triggered = (vix_val < 20) and (rsi_val < 35)

        if not triggered:
            i += 1
            continue

        entry_price = closes[i]
        exit_price  = None
        bars_held   = 0
        for j in range(i + 1, min(i + 11, len(bars))):
            bars_held += 1
            if closes[j] >= emas[j] or bars_held == 10:
                exit_price = closes[j]
                break

        if exit_price is None:
            i += 1
            continue

        rets.append((exit_price - entry_price) / entry_price * 100)
        i += bars_held + 1

    return rets


# ── Statistics ─────────────────────────────────────────────────────────────
def stats(rets) -> dict:
    if not rets:
        return {"n": 0, "mean": 0.0, "wr": 0.0, "pf": 0.0, "sharpe": 0.0}
    a      = np.array(rets, dtype=float)
    wins   = a[a > 0]
    losses = a[a <= 0]
    pf     = float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float("inf")
    std    = float(a.std(ddof=1))
    sharpe = float(a.mean() / std * np.sqrt(len(a))) if std > 0 else 0.0
    return {
        "n":      int(len(a)),
        "mean":   round(float(a.mean()), 4),
        "wr":     round(float((a > 0).mean() * 100), 2),
        "pf":     round(pf, 4),
        "sharpe": round(sharpe, 4),
    }


def profit_factor(rets) -> float:
    a      = np.array(rets, dtype=float)
    wins   = a[a > 0].sum()
    losses = abs(a[a <= 0].sum())
    return round(float(wins / losses), 4) if losses > 0 else float("inf")


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    print("Loading VIX data...")
    vix = load_vix()
    print(f"  VIX rows: {len(vix)}  range: {vix.index.min()} – {vix.index.max()}")

    tickers = get_tickers()
    print(f"  Tickers ({len(tickers)}): {[t for t, _ in tickers]}\n")

    # ── Main backtest ──
    all_trades: list[dict] = []
    for ticker, fpath in tickers:
        trades = backtest_ticker(ticker, fpath, vix)
        print(f"  {ticker:6s}: {len(trades)} trades")
        all_trades.extend(trades)

    if not all_trades:
        print("\nNo trades found.")
        return

    df = pd.DataFrame(all_trades)
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["year"]       = df["entry_date"].dt.year

    # ── Anti-signal ──
    print("\nRunning anti-signal checks...")
    anti_rsi_rets: list[float] = []
    anti_vix_rets: list[float] = []
    for ticker, fpath in tickers:
        anti_rsi_rets.extend(backtest_antisignal(ticker, fpath, vix, "rsi_high"))
        anti_vix_rets.extend(backtest_antisignal(ticker, fpath, vix, "vix_low"))

    # ── Assemble results ──
    overall = stats(df["return_pct"].tolist())
    overall["avg_hold"]       = round(float(df["bars_held"].mean()), 2)
    overall["ema21_exit_pct"] = round(float((df["exit_type"] == "ema21").mean() * 100), 2)
    overall["hardmax_pct"]    = round(float((df["exit_type"] == "hard_max").mean() * 100), 2)

    by_year: dict[str, dict] = {}
    for yr in sorted(df["year"].unique()):
        sub = df[df["year"] == yr]
        s = stats(sub["return_pct"].tolist())
        by_year[str(yr)] = {"n": s["n"], "mean": s["mean"], "wr": s["wr"]}

    tier_a = df[(df["rsi_at_entry"] >= 25) & (df["rsi_at_entry"] < 35)]
    tier_b = df[df["rsi_at_entry"] < 25]
    by_rsi = {
        "TIER_A_25_35": stats(tier_a["return_pct"].tolist()),
        "TIER_B_lt25":  stats(tier_b["return_pct"].tolist()),
    }

    by_vix: dict[str, dict] = {}
    for lo, hi, label in [(25, 30, "25-30"), (30, 35, "30-35"), (35, 999, "35+")]:
        sub = df[(df["vix_at_entry"] >= lo) & (df["vix_at_entry"] < hi)]
        s = stats(sub["return_pct"].tolist())
        by_vix[label] = {"n": s["n"], "mean": s["mean"], "wr": s["wr"]}

    anti_signal = {
        "rsi_high_streak_vix25": stats(anti_rsi_rets),
        "vix_low_streak_rsi35":  stats(anti_vix_rets),
    }

    vix_cliff: dict[str, float] = {}
    for thr in [24, 25, 26]:
        sub = df[df["vix_at_entry"] >= thr]
        vix_cliff[f">={thr}"] = profit_factor(sub["return_pct"].tolist())

    ticker_perf = (
        df.groupby("ticker")["return_pct"]
          .agg(["mean", "count"])
          .sort_values("mean", ascending=False)
    )
    top5    = ticker_perf.head(5).reset_index().to_dict("records")
    bottom5 = ticker_perf.tail(5).reset_index().to_dict("records")

    # ── Print ──────────────────────────────────────────────────────────────
    o = overall
    print("\n=== Module 4 Mean-Reversion — 5-Year Backtest ===")
    print(f"OVERALL: N={o['n']}, Mean={o['mean']}%, WR={o['wr']}%, "
          f"PF={o['pf']}, Sharpe={o['sharpe']}, "
          f"Avg hold={o['avg_hold']} bars, "
          f"EMA21 exit={o['ema21_exit_pct']}%, Hard max exit={o['hardmax_pct']}%")

    print("\nBY YEAR:")
    for yr, s in by_year.items():
        print(f"  {yr}: N={s['n']}, Mean={s['mean']}%, WR={s['wr']}%")

    print("\nBY RSI TIER:")
    for label, s in by_rsi.items():
        print(f"  {label}: N={s['n']}, Mean={s['mean']}%, WR={s['wr']}%")

    print("\nBY VIX LEVEL:")
    for label, s in by_vix.items():
        print(f"  {label}: N={s['n']}, Mean={s['mean']}%, WR={s['wr']}%")

    print("\nANTI-SIGNAL VERIFICATION:")
    ar = anti_signal["rsi_high_streak_vix25"]
    av = anti_signal["vix_low_streak_rsi35"]
    print(f"  RSI>=35, streak+VIX>=25 : N={ar['n']}, Mean={ar['mean']}%, "
          f"WR={ar['wr']}%  (expect ~0 or negative)")
    print(f"  VIX<20,  streak+RSI<35  : N={av['n']}, Mean={av['mean']}%, "
          f"WR={av['wr']}%  (expect negative)")

    print("\nVIX CLIFF CHECK:")
    for k, v in vix_cliff.items():
        print(f"  VIX{k}: PF={v}")

    print("\nTOP 5 tickers by mean return:")
    for r in top5:
        print(f"  {r['ticker']:6s}: mean={r['mean']:+.3f}% (n={r['count']})")

    print("\nBOTTOM 5 tickers by mean return:")
    for r in bottom5:
        print(f"  {r['ticker']:6s}: mean={r['mean']:+.3f}% (n={r['count']})")

    print("\n1-YEAR COMPARISON:")
    print(f"  Baseline (1yr): N=63, Mean=+7.52%, WR=94%, PF=126.88")
    print(f"  5yr:            N={o['n']}, Mean={o['mean']}%, "
          f"WR={o['wr']}%, PF={o['pf']}")

    # ── Save ───────────────────────────────────────────────────────────────
    trades_path  = os.path.join(OUT, "m4_5yr_trades.csv")
    summary_path = os.path.join(OUT, "m4_5yr_summary.json")

    df.to_csv(trades_path, index=False)

    summary = {
        "overall":     overall,
        "by_year":     by_year,
        "by_rsi":      by_rsi,
        "by_vix":      by_vix,
        "anti_signal": anti_signal,
        "vix_cliff":   vix_cliff,
        "top5_tickers":    top5,
        "bottom5_tickers": bottom5,
    }
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\nTrades  → {trades_path}")
    print(f"Summary → {summary_path}")


if __name__ == "__main__":
    main()
