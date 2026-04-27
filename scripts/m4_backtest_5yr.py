#!/usr/bin/env python3
"""
Module 4 Mean-Reversion — 5-Year Backtest
Frozen parameters: 3 consecutive 4H down bars + VIX>=25 + RSI(14)<35
Entry: trigger bar close. Exit: first 4H close >= EMA21 or bar 10 hard max.
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
from backtest_utils_extended import load_earnings, is_earnings_window

warnings.filterwarnings("ignore")

# ── Paths ──────────────────────────────────────────────────────────────────
BASE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA  = os.path.join(BASE, "Fetched_Data")
OUT   = os.path.join(BASE, "backtest_results")
os.makedirs(OUT, exist_ok=True)

# IBIT/SNOW/TXN/VIX excluded: not in trading universe
EXCLUDE    = {"SPY", "VIXY", "BTC", "ETH", "IBIT", "SNOW", "TXN", "VIX"}
SKIP_FILES = {"VIXCLS_FRED_real.csv", "VXVCLS.csv"}

VIX_URL = ("https://fred.stlouisfed.org/graph/fredgraph.csv"
           "?id=VIXCLS&cosd=2021-01-01&coed=2026-04-11")

# RTH boundaries — two formats depending on M5 data source.
# build_4h() auto-detects which set to use based on max hour in data.
# _m5_full.csv: timestamps in ET (09:30-15:55)
RTH_S_ET   = 9 * 60 + 30     # 570
RTH_E_ET   = 15 * 60 + 55    # 955
BAR1_E_ET  = 13 * 60 + 25    # 805
# _data.csv: timestamps in UTC (13:30-19:55)
RTH_S_UTC  = 13 * 60 + 30    # 810
RTH_E_UTC  = 19 * 60 + 55    # 1195
BAR1_E_UTC = 17 * 60 + 25    # 1045


# ── VIX ───────────────────────────────────────────────────────────────────
def load_vix() -> pd.Series:
    """Return Series{date -> float} of daily VIX closes.
    Priority:
      1. Fetched_Data/VIX_daily_fmp.json  (FMP daily, JSON array)
      2. FRED URL download
      3. Fetched_Data/VIXCLS_FRED_real.csv
      4. Fetched_Data/VXVCLS.csv          (2021+ proxy)
    """
    from io import StringIO

    # 1. FMP local JSON (preferred — full 2021-2026 coverage, no network needed)
    fmp_path = os.path.join(DATA, "VIX_daily_fmp.json")
    if os.path.exists(fmp_path):
        try:
            with open(fmp_path) as f:
                records = json.load(f)
            rows = [{"date": r["date"], "vix": r["close"]}
                    for r in records if r.get("date") and r.get("close") is not None]
            if rows:
                df = pd.DataFrame(rows)
                df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
                df["vix"]  = pd.to_numeric(df["vix"], errors="coerce")
                df = df.dropna()
                vix = df.set_index("date")["vix"].sort_index()
                print(f"  VIX source: VIX_daily_fmp.json  {len(vix)} rows, "
                      f"{vix.index.min()} to {vix.index.max()}")
                return vix
        except Exception:
            pass

    # 2. FRED URL
    df = None
    try:
        with urlopen(VIX_URL, timeout=10) as r:
            raw = r.read().decode()
        df = pd.read_csv(StringIO(raw))
    except Exception:
        pass

    # 3. Local VIXCLS_FRED_real.csv
    if df is None:
        local = os.path.join(DATA, "VIXCLS_FRED_real.csv")
        df = pd.read_csv(local)
        # If this file only covers ~15 months, fall through to VXVCLS
        tmp = pd.to_datetime(df.iloc[:, 0], errors="coerce")
        if tmp.dropna().dt.year.min() > 2022:
            # 4. VXVCLS proxy
            df = pd.read_csv(os.path.join(DATA, "VXVCLS.csv"))

    df.columns = ["date", "vix"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df["vix"]  = pd.to_numeric(df["vix"], errors="coerce")
    df = df.dropna()
    vix = df.set_index("date")["vix"]
    print(f"  VIX source: {len(vix)} rows, {vix.index.min()} to {vix.index.max()}")
    return vix


# ── RSI(14) — Wilder's smoothing ───────────────────────────────────────────
def rsi14(close: pd.Series) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    ag    = gain.ewm(alpha=1 / 14, adjust=False).mean()
    al    = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs    = ag / al.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


# ── M5 column normaliser ────────────────────────────────────────────────────
def _norm_m5(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalise raw M5 CSV to: Datetime, Open, High, Low, Close, Volume.
    Handles two formats:
      old _data.csv      : Datetime, Ticker, Open, High, Low, Close, Volume  (UTC)
      new _m5_full.csv   : date, open, high, low, close, volume              (ET)
    """
    df = df.copy()
    lc = {c.lower(): c for c in df.columns}
    if "Datetime" not in df.columns and "date" in lc:
        df = df.rename(columns={lc["date"]: "Datetime"})
    for cap, low in [("Open", "open"), ("High", "high"), ("Low", "low"),
                     ("Close", "close"), ("Volume", "volume")]:
        if cap not in df.columns and low in df.columns:
            df = df.rename(columns={low: cap})
    return df


# ── 4H bar builder ─────────────────────────────────────────────────────────
def build_4h(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filter raw M5 data to RTH, assign to Bar-1 / Bar-2, aggregate OHLCV.
    Auto-detects timestamp timezone:
      _m5_full.csv  -> ET  (max hour <= 16, RTH 09:30-15:55)
      _data.csv     -> UTC (max hour > 16,  RTH 13:30-19:55)
    """
    df = df.copy()
    df["dt"]  = pd.to_datetime(df["Datetime"], errors="coerce")
    df = df.sort_values("dt").dropna(subset=["dt"])
    if df.empty:
        return pd.DataFrame()

    # Auto-detect: _m5_full.csv has RTH-only bars (max hour <= 16 = ET);
    #              _data.csv has extended-hours bars (max hour > 16 = UTC).
    if df["dt"].dt.hour.max() <= 16:
        rth_s, rth_e, bar1_e = RTH_S_ET, RTH_E_ET, BAR1_E_ET
        h1, m1, h2, m2 = 9, 30, 13, 30
    else:
        rth_s, rth_e, bar1_e = RTH_S_UTC, RTH_E_UTC, BAR1_E_UTC
        h1, m1, h2, m2 = 13, 30, 17, 30

    tod = df["dt"].dt.hour * 60 + df["dt"].dt.minute
    rth_mask = (tod >= rth_s) & (tod <= rth_e)
    df = df[rth_mask].copy()
    if df.empty:
        return pd.DataFrame()

    tod_filt     = df["dt"].dt.hour * 60 + df["dt"].dt.minute
    df["date"]   = df["dt"].dt.date
    df["session"] = (tod_filt > bar1_e).astype(int)   # 0 = Bar-1, 1 = Bar-2

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
        lambda r: pd.Timestamp(str(r["date"])) + pd.Timedelta(hours=h1, minutes=m1)
        if r["session"] == 0
        else pd.Timestamp(str(r["date"])) + pd.Timedelta(hours=h2, minutes=m2),
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

    BUG-FIX: bars["ts"].values has dtype datetime64[us] in pandas >= 2.0, so
    the old integer-division approach (/ 3_600_000_000_000) silently gave
    values 1000x too small — no gap ever exceeded 30h.  Using pd.Timestamp
    subtraction with .total_seconds() is unit-agnostic and always correct.
    """
    n       = len(bars)
    streaks = np.zeros(n, dtype=np.int32)
    ts_ns   = bars["ts"].values          # datetime64[us] — keep as-is for indexing
    closes  = bars["Close"].values
    opens   = bars["Open"].values
    s = 0
    for i in range(n):
        if i > 0:
            gap_h = (pd.Timestamp(ts_ns[i]) - pd.Timestamp(ts_ns[i - 1])).total_seconds() / 3600
            if gap_h > 30:
                s = 0
        if closes[i] < opens[i]:
            s += 1
        else:
            s = 0
        streaks[i] = s
    return streaks


# ── EMA21 warmup mask after data gaps ─────────────────────────────────────
def apply_ema21_warmup_mask(bars: pd.DataFrame) -> pd.Series:
    """
    After any data gap > 7 calendar days, NaN-out the next 21 EMA21 bars.
    Stale carry-forward EMA (sometimes 20-33% above post-gap price) must not
    be used as an exit reference — doing so inflates hard-max exit rate.
    """
    ema      = bars["ema21"].copy()
    ts_list  = bars["ts"].tolist()
    n        = len(bars)
    warmup_end = -1
    for i in range(1, n):
        gap_days = (ts_list[i] - ts_list[i - 1]).total_seconds() / 86400
        if gap_days > 7:
            warmup_end = min(n - 1, i + 20)   # bars i … i+20 inclusive
        if i <= warmup_end:
            ema.iloc[i] = np.nan
    return ema


# ── Ticker discovery ────────────────────────────────────────────────────────
def get_tickers() -> list[tuple[str, str]]:
    """
    Discover tickers from M5 CSV files.
    Priority per ticker: _m5_full.csv (0) > _data.csv (1) > _crypto_data.csv (2).
    If a full-coverage file exists it is preferred over the sparse fallback.
    """
    candidates: dict[str, tuple[int, str]] = {}  # ticker -> (priority, path)
    for fpath in sorted(glob.glob(os.path.join(DATA, "*.csv"))):
        name = os.path.basename(fpath)
        if name in SKIP_FILES:
            continue
        if name.endswith("_m5_full.csv"):
            ticker = name[: -len("_m5_full.csv")]
            prio   = 0
        elif name.endswith("_crypto_data.csv"):
            ticker = name[: -len("_crypto_data.csv")]
            prio   = 2
        elif name.endswith("_data.csv"):
            ticker = name[: -len("_data.csv")]
            prio   = 1
        else:
            continue
        if ticker in EXCLUDE:
            continue
        if ticker not in candidates or prio < candidates[ticker][0]:
            candidates[ticker] = (prio, fpath)
    return sorted((t, p) for t, (_, p) in candidates.items())


# ── Prior-day VIX lookup ────────────────────────────────────────────────────
def prior_vix(bar_date, vix: pd.Series):
    """Return the most-recent VIX close strictly before bar_date, or NaN."""
    avail = vix.index[vix.index < bar_date]
    if len(avail) == 0:
        return np.nan
    return float(vix[avail[-1]])


# ── Core backtest (main signal) ─────────────────────────────────────────────
def backtest_ticker(ticker: str, fpath: str, vix: pd.Series,
                    earnings_dict: dict = None, buffer_days: int = 0) -> list[dict]:
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

    corrupt         = flag_corrupt(bars["Close"]).values
    bars["ema21"]   = bars["Close"].ewm(span=21, adjust=False).mean()
    if not fpath.endswith("_m5_full.csv"):   # full-coverage files have no stale gaps
        bars["ema21"] = apply_ema21_warmup_mask(bars)
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

        if np.isnan(emas[i]):   # EMA21 warmup zone — no valid exit reference
            i += 1
            continue

        if buffer_days > 0 and earnings_dict is not None:
            if is_earnings_window(ticker, dates[i], earnings_dict, buffer_days=buffer_days):
                i += 1
                continue  # Retroactive filter: skip valid M4 signal due to earnings proximity

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
    raw = _norm_m5(raw)
    if raw.empty or "Close" not in raw.columns:
        return []
    bars = build_4h(raw)
    if bars.empty or len(bars) < 20:
        return []

    corrupt        = flag_corrupt(bars["Close"]).values
    bars["ema21"]  = bars["Close"].ewm(span=21, adjust=False).mean()
    if not fpath.endswith("_m5_full.csv"):   # full-coverage files have no stale gaps
        bars["ema21"] = apply_ema21_warmup_mask(bars)
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
        if corrupt[i] or streaks.iloc[i] < 3 or np.isnan(emas[i]):
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

    tickers = get_tickers()
    print(f"  Tickers ({len(tickers)}): {[t for t, _ in tickers]}\n")

    earnings_dict = load_earnings()

    # ── Main backtest ──
    all_trades: list[dict] = []
    for ticker, fpath in tickers:
        trades = backtest_ticker(ticker, fpath, vix,
                                 earnings_dict=earnings_dict, buffer_days=0)
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
    print("\n=== Module 4 Mean-Reversion -- 5-Year Backtest ===")
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

    print(f"\nTrades  -> {trades_path}")
    print(f"Summary -> {summary_path}")


if __name__ == "__main__":
    main()
