#!/usr/bin/env python3
"""
Module 4 Mean-Reversion -- DAILY Backtest (5yr)
Daily-bar equivalent of the 4H M4 signal.
Mapping: streak>=2 daily down bars, RSI(14)<35, VIX>=25,
         exit first daily close >= EMA(10) or day-5 hard max.
"""

import os, json, glob, warnings
import numpy as np
import pandas as pd
from urllib.request import urlopen

warnings.filterwarnings("ignore")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "Fetched_Data")
BO   = os.path.join(BASE, "backtest_output")   # existing FMP-sourced daily CSVs
OUT  = os.path.join(BASE, "backtest_results")
os.makedirs(OUT, exist_ok=True)

EXCLUDE = {"SPY", "VIXY", "BTC", "ETH", "IBIT", "SNOW", "TXN"}
SKIP    = {"VIXCLS_FRED_real.csv", "VXVCLS.csv"}
FMP_KEY = "PRAtaveLKuyLOcdMUOMwg2aTvqSg2ab3"
FMP_URL = ("https://financialmodelingprep.com/stable/historical-price-eod/full"
           "?symbol={}&apikey=" + FMP_KEY)
VIX_URL = ("https://fred.stlouisfed.org/graph/fredgraph.csv"
           "?id=VIXCLS&cosd=2021-01-01&coed=2026-04-11")
RTH_S   = 13 * 60 + 30    # UTC minute start for M5 RTH resample
RTH_E   = 19 * 60 + 55


# ── VIX ───────────────────────────────────────────────────────────────────
def load_vix() -> pd.Series:
    """FRED -> VIXCLS_FRED_real.csv -> VXVCLS.csv (proxy, covers 2021+)."""
    from io import StringIO
    df = None
    try:
        with urlopen(VIX_URL, timeout=10) as r:
            df = pd.read_csv(StringIO(r.read().decode()))
    except Exception:
        pass
    if df is None:
        local = os.path.join(DATA, "VIXCLS_FRED_real.csv")
        df = pd.read_csv(local)
        if pd.to_datetime(df.iloc[:, 0], errors="coerce").dropna().dt.year.min() > 2022:
            df = pd.read_csv(os.path.join(DATA, "VXVCLS.csv"))
    df.columns = ["date", "vix"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df["vix"]  = pd.to_numeric(df["vix"], errors="coerce")
    df = df.dropna()
    s = df.set_index("date")["vix"]
    print(f"  VIX: {len(s)} rows, {s.index.min()} to {s.index.max()}")
    return s


# ── RSI(14) — Wilder's smoothing ───────────────────────────────────────────
def rsi14(close: pd.Series) -> pd.Series:
    delta = close.diff()
    ag = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    al = (-delta).clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    return 100 - 100 / (1 + ag / al.replace(0, np.nan))


# ── Daily bar loaders ──────────────────────────────────────────────────────
def _norm(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise any daily CSV to columns [date, Open, High, Low, Close, Volume]."""
    df = df.copy()
    df.columns = [c.lower().strip() for c in df.columns]
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low",
                             "close": "Close", "adjclose": "Close",
                             "volume": "Volume"})
    needed = ["date", "Open", "High", "Low", "Close", "Volume"]
    for col in needed:
        if col not in df.columns:
            return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    return df[needed].dropna(subset=["date", "Close"])


def _resample_m5(m5_path: str) -> pd.DataFrame:
    """Resample M5 CSV -> RTH daily OHLCV bars."""
    try:
        df = pd.read_csv(m5_path)
    except Exception:
        return pd.DataFrame()
    df["dt"] = pd.to_datetime(df["Datetime"], errors="coerce")
    df = df.dropna(subset=["dt"]).sort_values("dt")
    tod = df["dt"].dt.hour * 60 + df["dt"].dt.minute
    df  = df[(tod >= RTH_S) & (tod <= RTH_E)].copy()
    df["date"] = df["dt"].dt.date
    daily = df.groupby("date").agg(
        Open=("Open", "first"), High=("High", "max"),
        Low=("Low", "min"), Close=("Close", "last"),
        Volume=("Volume", "sum"),
    ).reset_index()
    daily.columns = ["date", "Open", "High", "Low", "Close", "Volume"]
    return daily


def load_daily_bars(ticker: str, m5_path: str) -> pd.DataFrame:
    """
    Priority chain:
      1. FMP download  -> cache to Fetched_Data/{ticker}_daily.csv
      2. Fetched_Data/{ticker}_daily.csv  (previous download)
      3. backtest_output/{ticker}_daily.csv  (FMP-sourced, ~14 months Feb 2025+)
      4. Resample from Fetched_Data/{ticker}_data.csv  (M5 -> daily, 2021-2026)
    Sources 3 + 4 are merged: backtest_output fills 2025-2026 gap-free,
    M5 resample fills 2021-2024 (33-48% trading-day coverage).
    """
    cache = os.path.join(DATA, f"{ticker}_daily.csv")

    # 1. FMP download
    if not os.path.exists(cache):
        try:
            import json as _j
            with urlopen(FMP_URL.format(ticker), timeout=10) as r:
                data = _j.loads(r.read().decode())
            if isinstance(data, list) and data:
                rows = [{"date": x["date"], "Open": x["open"], "High": x["high"],
                         "Low": x["low"], "Close": x["close"],
                         "Volume": x.get("volume", 0)} for x in data]
                fmp_df = pd.DataFrame(rows)
                fmp_df.to_csv(cache, index=False)
        except Exception:
            pass

    frames = []

    # 2. Cached FMP file
    if os.path.exists(cache):
        fd = _norm(pd.read_csv(cache))
        if not fd.empty:
            frames.append(fd)

    # 3. backtest_output daily (complete FMP data, Feb 2025+)
    bo_path = os.path.join(BO, f"{ticker}_daily.csv")
    if os.path.exists(bo_path):
        bd = _norm(pd.read_csv(bo_path))
        if not bd.empty:
            frames.append(bd)

    # 4. M5 resample (2021-2026, partial coverage)
    m5d = _resample_m5(m5_path)
    if not m5d.empty:
        frames.append(m5d)

    if not frames:
        return pd.DataFrame()

    # Merge: deduplicate by date, prefer FMP/backtest_output over M5 resample
    combined = pd.concat(frames, ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"], errors="coerce").dt.date
    combined = (combined.sort_values("date")
                        .drop_duplicates("date", keep="first")
                        .reset_index(drop=True))
    combined = combined.dropna(subset=["Close"])
    return combined


# ── Indicators ─────────────────────────────────────────────────────────────
def calc_streak(dates: list, closes: np.ndarray, opens: np.ndarray) -> np.ndarray:
    """
    Consecutive daily down bars (close < open).
    Resets on: up bar, or calendar gap > 7 days between consecutive bars.
    """
    n = len(dates)
    streaks = np.zeros(n, dtype=np.int32)
    s = 0
    for i in range(n):
        if i > 0 and (dates[i] - dates[i - 1]).days > 7:
            s = 0
        s = s + 1 if closes[i] < opens[i] else 0
        streaks[i] = s
    return streaks


def apply_ema_warmup(df: pd.DataFrame, col: str,
                     gap_days: int = 7, warmup: int = 10) -> pd.Series:
    """
    NaN-out EMA `col` for `warmup` bars after any gap > gap_days calendar days.
    Prevents stale EMA carry-forward from driving exit decisions.
    """
    ema   = df[col].copy()
    dates = df["date"].tolist()
    n     = len(df)
    end   = -1
    for i in range(1, n):
        if (dates[i] - dates[i - 1]).days > gap_days:
            end = min(n - 1, i + warmup - 1)
        if i <= end:
            ema.iloc[i] = np.nan
    return ema


# ── Helpers ────────────────────────────────────────────────────────────────
def get_tickers() -> list:
    result = []
    for fpath in sorted(glob.glob(os.path.join(DATA, "*.csv"))):
        name = os.path.basename(fpath)
        if name in SKIP:
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


def prior_vix(bar_date, vix: pd.Series) -> float:
    avail = vix.index[vix.index < bar_date]
    return float(vix[avail[-1]]) if len(avail) else np.nan


# ── Backtest engine ────────────────────────────────────────────────────────
def _run(ticker: str, bars: pd.DataFrame, vix: pd.Series,
         streak_min: int, hard_max: int, mode: str = "main") -> list:
    """
    mode='main'     : standard signal, returns list[dict] trade records
    mode='rsi_high' : anti-signal (RSI>=35, VIX>=25), returns list[float]
    mode='vix_low'  : anti-signal (VIX<20, RSI<35),   returns list[float]
    """
    if bars.empty or len(bars) < 20:
        return []
    bars = bars.sort_values("date").reset_index(drop=True)
    bars["ema10"] = bars["Close"].ewm(span=10, adjust=False).mean()
    bars["ema10"] = apply_ema_warmup(bars, "ema10")
    bars["rsi"]   = rsi14(bars["Close"])

    dates   = bars["date"].tolist()
    closes  = bars["Close"].values
    opens   = bars["Open"].values
    emas    = bars["ema10"].values
    rsis    = bars["rsi"].values
    streaks = calc_streak(dates, closes, opens)

    out = []
    i   = 0
    while i < len(bars):
        sk = streaks[i]; rv = rsis[i]; em = emas[i]
        # Gate: streak, valid indicators, valid EMA
        if sk < streak_min or np.isnan(rv) or np.isnan(em):
            i += 1; continue

        vv = prior_vix(dates[i], vix)
        if np.isnan(vv):
            i += 1; continue

        # Mode-specific trigger
        if mode == "main":
            if vv < 25 or rv >= 35:
                i += 1; continue
        elif mode == "rsi_high":
            if not (vv >= 25 and rv >= 35):
                i += 1; continue
        else:  # vix_low
            if not (vv < 20 and rv < 35):
                i += 1; continue

        # Entry
        ep = closes[i]
        xp = None; xt = None; bh = 0; xdate = None

        for j in range(i + 1, min(i + hard_max + 1, len(bars))):
            bh += 1
            # EMA exit: only when EMA is valid
            if not np.isnan(emas[j]) and closes[j] >= emas[j]:
                xp = closes[j]; xt = "ema10"; xdate = dates[j]; break
            if bh == hard_max:
                xp = closes[j]; xt = "hard_max"; xdate = dates[j]; break

        if xp is None:
            i += 1; continue

        ret = (xp - ep) / ep * 100
        if mode == "main":
            out.append({
                "ticker": ticker,
                "entry_date": str(dates[i]),
                "exit_date":  str(xdate),
                "entry_price": round(float(ep), 4),
                "exit_price":  round(float(xp), 4),
                "return_pct":  round(float(ret), 4),
                "bars_held":   int(bh),
                "exit_type":   xt,
                "rsi_at_entry": round(float(rv), 2),
                "vix_at_entry": round(float(vv), 2),
            })
        else:
            out.append(float(ret))

        i += bh + 1

    return out


# ── Statistics ─────────────────────────────────────────────────────────────
def stats(rets) -> dict:
    if not rets:
        return {"n": 0, "mean": 0.0, "wr": 0.0, "pf": 0.0, "sharpe": 0.0}
    a = np.array(rets, dtype=float)
    w = a[a > 0]; l = a[a <= 0]
    pf  = float(w.sum() / abs(l.sum())) if l.sum() != 0 else float("inf")
    std = float(a.std(ddof=1))
    sh  = float(a.mean() / std * np.sqrt(len(a))) if std > 0 else 0.0
    return {"n": int(len(a)), "mean": round(float(a.mean()), 4),
            "wr": round(float((a > 0).mean() * 100), 2),
            "pf": round(pf, 4), "sharpe": round(sh, 4)}


def pf_only(rets) -> float:
    a = np.array(rets, dtype=float)
    w = a[a > 0].sum(); l = abs(a[a <= 0].sum())
    return round(float(w / l), 4) if l > 0 else float("inf")


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    print("Loading VIX data...")
    vix     = load_vix()
    tickers = get_tickers()
    print(f"Tickers ({len(tickers)}): {[t for t, _ in tickers]}\n")

    # Load bars once; run main backtest (streak>=2 and streak>=3 variants)
    print("Loading daily bars and running backtest (streak>=2 and streak>=3)...")
    bars_cache: dict = {}
    all_s2: list = []
    all_s3: list = []

    for ticker, fpath in tickers:
        bars = load_daily_bars(ticker, fpath)
        bars_cache[ticker] = bars
        t2 = _run(ticker, bars, vix, streak_min=2, hard_max=5)
        t3 = _run(ticker, bars, vix, streak_min=3, hard_max=5)
        n  = len(bars)
        print(f"  {ticker:6s}: {n:4d} daily bars | s>=2: {len(t2)} trades | s>=3: {len(t3)} trades")
        all_s2.extend(t2)
        all_s3.extend(t3)

    if not all_s2:
        print("No trades found (streak>=2). Check VIX coverage and data.")
        return

    df2 = pd.DataFrame(all_s2)
    df3 = pd.DataFrame(all_s3) if all_s3 else pd.DataFrame()

    for frame in [df2, df3]:
        if not frame.empty:
            frame["entry_date"] = pd.to_datetime(frame["entry_date"])
            frame["year"]       = frame["entry_date"].dt.year

    # Anti-signals (reuse cached bars)
    print("\nRunning anti-signal checks...")
    ar_rets: list = []
    av_rets: list = []
    for ticker, fpath in tickers:
        bars = bars_cache.get(ticker, pd.DataFrame())
        ar_rets.extend(_run(ticker, bars, vix, streak_min=2, hard_max=5, mode="rsi_high"))
        av_rets.extend(_run(ticker, bars, vix, streak_min=2, hard_max=5, mode="vix_low"))

    # ── Assemble stats ──
    ov = stats(df2["return_pct"].tolist())
    ov["avg_hold"]     = round(float(df2["bars_held"].mean()), 2)
    ov["ema_exit_pct"] = round(float((df2["exit_type"] == "ema10").mean() * 100), 2)
    ov["hardmax_pct"]  = round(float((df2["exit_type"] == "hard_max").mean() * 100), 2)

    by_year: dict = {}
    for yr in sorted(df2["year"].unique()):
        sub = df2[df2["year"] == yr]
        s   = stats(sub["return_pct"].tolist())
        by_year[str(yr)] = {"n": s["n"], "mean": s["mean"], "wr": s["wr"]}

    tier_a = df2[(df2["rsi_at_entry"] >= 25) & (df2["rsi_at_entry"] < 35)]
    tier_b = df2[df2["rsi_at_entry"] < 25]
    by_rsi = {"TIER_A_25_35": stats(tier_a["return_pct"].tolist()),
              "TIER_B_lt25":  stats(tier_b["return_pct"].tolist())}

    by_vix: dict = {}
    for lo, hi, lbl in [(25, 30, "25-30"), (30, 35, "30-35"), (35, 999, "35+")]:
        sub = df2[(df2["vix_at_entry"] >= lo) & (df2["vix_at_entry"] < hi)]
        s   = stats(sub["return_pct"].tolist())
        by_vix[lbl] = {"n": s["n"], "mean": s["mean"], "wr": s["wr"]}

    anti   = {"rsi_high": stats(ar_rets), "vix_low": stats(av_rets)}
    cliff  = {f">={t}": pf_only(df2[df2["vix_at_entry"] >= t]["return_pct"].tolist())
              for t in [24, 25, 26]}
    tp     = (df2.groupby("ticker")["return_pct"]
                 .agg(["mean", "count"])
                 .sort_values("mean", ascending=False))
    top5    = tp.head(5).reset_index().to_dict("records")
    bottom5 = tp.tail(5).reset_index().to_dict("records")
    ov3     = stats(df3["return_pct"].tolist()) if not df3.empty else \
              {"n": 0, "mean": 0.0, "wr": 0.0, "pf": 0.0}

    # ── Print ──
    o = ov
    print("\n=== Module 4 Mean-Reversion -- DAILY Backtest (5yr) ===")
    print(f"OVERALL (streak>=2): N={o['n']}, Mean={o['mean']}%, WR={o['wr']}%,"
          f" PF={o['pf']}, Sharpe={o['sharpe']},"
          f" Avg hold={o['avg_hold']} days,"
          f" EMA exit={o['ema_exit_pct']}%, Hard max={o['hardmax_pct']}%")

    print("\nBY YEAR:")
    for yr, s in by_year.items():
        print(f"  {yr}: N={s['n']}, Mean={s['mean']}%, WR={s['wr']}%")

    print("\nBY RSI TIER:")
    for lbl, s in by_rsi.items():
        print(f"  {lbl}: N={s['n']}, Mean={s['mean']}%, WR={s['wr']}%")

    print("\nBY VIX LEVEL:")
    for lbl, s in by_vix.items():
        print(f"  {lbl}: N={s['n']}, Mean={s['mean']}%, WR={s['wr']}%")

    print("\nANTI-SIGNAL VERIFICATION:")
    ar = anti["rsi_high"]; av = anti["vix_low"]
    print(f"  RSI>=35 + VIX>=25 + streak: N={ar['n']}, Mean={ar['mean']}%,"
          f" WR={ar['wr']}%  (expect ~0 or negative)")
    print(f"  VIX<20  + RSI<35  + streak: N={av['n']}, Mean={av['mean']}%,"
          f" WR={av['wr']}%  (expect negative)")

    print("\nVIX CLIFF CHECK:")
    for k, v in cliff.items():
        print(f"  VIX{k}: PF={v}")

    print("\nTOP 5 tickers by mean return:")
    for r in top5:
        print(f"  {r['ticker']:6s}: mean={r['mean']:+.3f}% (n={r['count']})")

    print("\nBOTTOM 5 tickers by mean return:")
    for r in bottom5:
        print(f"  {r['ticker']:6s}: mean={r['mean']:+.3f}% (n={r['count']})")

    print(f"\nSTREAK>=3 VARIANT (4H-equivalent):"
          f" N={ov3['n']}, Mean={ov3['mean']}%, WR={ov3['wr']}%, PF={ov3['pf']}")

    print("\n1-YR BASELINE COMPARISON:")
    print("  Baseline (4H 1yr): N=63, Mean=+7.52%, WR=94%, PF=126.88")
    print(f"  Daily 5yr (s>=2):  N={o['n']}, Mean={o['mean']}%, WR={o['wr']}%, PF={o['pf']}")
    print(f"  Daily 5yr (s>=3):  N={ov3['n']}, Mean={ov3['mean']}%, WR={ov3['wr']}%, PF={ov3['pf']}")

    # ── Save ──
    trades_path  = os.path.join(OUT, "m4_daily_trades.csv")
    summary_path = os.path.join(OUT, "m4_daily_summary.json")

    df2.to_csv(trades_path, index=False)
    summary = {
        "overall": ov, "by_year": by_year, "by_rsi": by_rsi, "by_vix": by_vix,
        "anti_signal": anti, "vix_cliff": cliff,
        "top5": top5, "bottom5": bottom5, "streak3_variant": ov3,
    }
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\nTrades  -> {trades_path}")
    print(f"Summary -> {summary_path}")


if __name__ == "__main__":
    main()
