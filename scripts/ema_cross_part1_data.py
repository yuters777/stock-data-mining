#!/usr/bin/env python3
"""
EMA Cross Falsification Study — Part 1: Data + Cross Detection

Builds 4H bars from M5 data, computes EMA9/21/RSI/ADX/ATR indicators,
detects all EMA9/21 cross events, and saves results for Part 2 analysis.

Standing Rejection #22: "4H cross as return predictor — Negative, filter only."
"""

import os
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "Fetched_Data")
OUT  = os.path.join(BASE, "results", "ema_cross_falsification")
os.makedirs(OUT, exist_ok=True)

TICKERS = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU",
    "C", "COIN", "COST", "GOOGL", "GS", "INTC", "JPM",
    "JD", "MARA", "META", "MSFT", "MSTR", "MU", "NVDA",
    "PLTR", "SMCI", "TSLA", "TSM", "V",
]

# RTH boundaries — two formats depending on M5 data source.
# _m5_full.csv: timestamps in ET (09:30-15:55)
RTH_S_ET   = 9 * 60 + 30     # 570
RTH_E_ET   = 15 * 60 + 55    # 955
BAR1_E_ET  = 13 * 60 + 25    # 805
# _data.csv: timestamps in UTC (13:30-19:55)
RTH_S_UTC  = 13 * 60 + 30    # 810
RTH_E_UTC  = 19 * 60 + 55    # 1195
BAR1_E_UTC = 17 * 60 + 25    # 1045

WARMUP_BARS = 30  # skip first N bars per ticker for EMA warmup


# ── M5 column normaliser (from m4_backtest_5yr.py) ───────────────────────────
def _norm_m5(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    lc = {c.lower(): c for c in df.columns}
    if "Datetime" not in df.columns and "date" in lc:
        df = df.rename(columns={lc["date"]: "Datetime"})
    for cap, low in [("Open", "open"), ("High", "high"), ("Low", "low"),
                     ("Close", "close"), ("Volume", "volume")]:
        if cap not in df.columns and low in df.columns:
            df = df.rename(columns={low: cap})
    return df


# ── 4H bar builder (from m4_backtest_5yr.py) ─────────────────────────────────
def build_4h(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filter raw M5 data to RTH, assign to Bar-1 / Bar-2, aggregate OHLCV.
    Auto-detects timestamp timezone:
      _m5_full.csv  -> ET  (max hour <= 16, RTH 09:30-15:55)
      _data.csv     -> UTC (max hour > 16,  RTH 13:30-19:55)
    Returns DataFrame with columns:
      date, bar_slot, Open, High, Low, Close, Volume, ts
    """
    df = df.copy()
    df["dt"] = pd.to_datetime(df["Datetime"], errors="coerce")
    df = df.sort_values("dt").dropna(subset=["dt"])
    if df.empty:
        return pd.DataFrame()

    # Auto-detect timezone
    if df["dt"].dt.hour.max() <= 16:
        rth_s, rth_e, bar1_e = RTH_S_ET, RTH_E_ET, BAR1_E_ET
        h1, m1, h2, m2 = 9, 30, 13, 30
    else:
        rth_s, rth_e, bar1_e = RTH_S_UTC, RTH_E_UTC, BAR1_E_UTC
        h1, m1, h2, m2 = 13, 30, 17, 30

    tod = df["dt"].dt.hour * 60 + df["dt"].dt.minute
    df = df[(tod >= rth_s) & (tod <= rth_e)].copy()
    if df.empty:
        return pd.DataFrame()

    tod_filt = df["dt"].dt.hour * 60 + df["dt"].dt.minute
    df["date"] = df["dt"].dt.date
    df["session"] = (tod_filt > bar1_e).astype(int)  # 0=Bar-1, 1=Bar-2

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

    # bar_slot: 1 for morning, 2 for afternoon
    bars["bar_slot"] = bars["session"] + 1

    # Canonical bar timestamp
    bar_ts = bars.apply(
        lambda r: pd.Timestamp(str(r["date"])) + pd.Timedelta(hours=h1, minutes=m1)
        if r["session"] == 0
        else pd.Timestamp(str(r["date"])) + pd.Timedelta(hours=h2, minutes=m2),
        axis=1,
    )
    bars["ts"] = bar_ts
    bars = bars.sort_values("ts").reset_index(drop=True)
    return bars


# ── RSI(14) — Wilder's smoothing (from m4_backtest_5yr.py) ──────────────────
def rsi14(close: pd.Series) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    ag    = gain.ewm(alpha=1 / 14, adjust=False).mean()
    al    = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs    = ag / al.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


# ── ATR(14) — Wilder's smoothing ─────────────────────────────────────────────
def atr14(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / 14, adjust=False).mean()


# ── ADX(14, smoothing=20) — Wilder DI+/DI- method ────────────────────────────
def adx14(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """
    ADX using:
    - DI period = 14 (Wilder smoothing, alpha=1/14)
    - ADX smoothing period = 20 (Wilder smoothing, alpha=1/20)
    """
    prev_high  = high.shift(1)
    prev_low   = low.shift(1)
    prev_close = close.shift(1)

    # True Range
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    # Directional Movement
    up_move   = high - prev_high
    down_move = prev_low - low

    plus_dm  = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm  = pd.Series(plus_dm, index=high.index)
    minus_dm = pd.Series(minus_dm, index=high.index)

    # Wilder smoothed (period=14)
    atr_smooth  = tr.ewm(alpha=1 / 14, adjust=False).mean()
    plus_smooth = plus_dm.ewm(alpha=1 / 14, adjust=False).mean()
    minus_smooth = minus_dm.ewm(alpha=1 / 14, adjust=False).mean()

    # DI+ and DI-
    plus_di  = 100 * plus_smooth / atr_smooth.replace(0, np.nan)
    minus_di = 100 * minus_smooth / atr_smooth.replace(0, np.nan)

    # DX
    di_sum  = plus_di + minus_di
    di_diff = (plus_di - minus_di).abs()
    dx = 100 * di_diff / di_sum.replace(0, np.nan)

    # ADX = Wilder smoothed DX (smoothing period=20)
    adx = dx.ewm(alpha=1 / 20, adjust=False).mean()
    return adx


# ── VIX loader ────────────────────────────────────────────────────────────────
def load_vix() -> pd.Series:
    """
    Load VIX daily closes. Returns Series{date -> float}.
    Priority: VIX_daily_fmp.json > VIXCLS_FRED_real.csv > VXVCLS.csv
    """
    import json

    # 1. FMP JSON (best coverage)
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

    # 2. FRED CSV
    fred_path = os.path.join(DATA, "VIXCLS_FRED_real.csv")
    if os.path.exists(fred_path):
        df = pd.read_csv(fred_path)
        df.columns = ["date", "vix"]
        # Skip rows with "." for missing days
        df = df[df["vix"] != "."]
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        df["vix"]  = pd.to_numeric(df["vix"], errors="coerce")
        df = df.dropna()
        if not df.empty:
            vix = df.set_index("date")["vix"].sort_index()
            print(f"  VIX source: VIXCLS_FRED_real.csv  {len(vix)} rows, "
                  f"{vix.index.min()} to {vix.index.max()}")
            return vix

    # 3. VXVCLS fallback
    vx_path = os.path.join(DATA, "VXVCLS.csv")
    if os.path.exists(vx_path):
        df = pd.read_csv(vx_path)
        df.columns = ["date", "vix"]
        df = df[df["vix"] != "."]
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        df["vix"]  = pd.to_numeric(df["vix"], errors="coerce")
        df = df.dropna()
        vix = df.set_index("date")["vix"].sort_index()
        print(f"  VIX source: VXVCLS.csv  {len(vix)} rows, "
              f"{vix.index.min()} to {vix.index.max()}")
        return vix

    raise FileNotFoundError("No VIX data file found in Fetched_Data/")


def prior_vix(bar_date, vix: pd.Series):
    """Return the most-recent VIX close strictly before bar_date, or NaN."""
    avail = vix.index[vix.index < bar_date]
    if len(avail) == 0:
        return np.nan
    return float(vix[avail[-1]])


# ── Ticker file discovery ────────────────────────────────────────────────────
def find_ticker_file(ticker: str) -> str | None:
    """Find M5 CSV for ticker. Priority: _m5_full.csv > _data.csv."""
    for suffix in ["_m5_full.csv", "_data.csv"]:
        path = os.path.join(DATA, f"{ticker}{suffix}")
        if os.path.exists(path):
            return path
    return None


# ── Build 4H bars with all indicators for one ticker ─────────────────────────
def process_ticker(ticker: str, fpath: str) -> pd.DataFrame | None:
    """Load M5, build 4H bars, compute all indicators. Returns DataFrame or None."""
    try:
        raw = pd.read_csv(fpath)
    except Exception as e:
        print(f"  WARNING: {ticker} — could not read {fpath}: {e}")
        return None

    raw = _norm_m5(raw)
    if raw.empty or "Close" not in raw.columns:
        print(f"  WARNING: {ticker} — empty or missing Close column")
        return None

    bars = build_4h(raw)
    if bars.empty or len(bars) < WARMUP_BARS + 5:
        print(f"  WARNING: {ticker} — too few 4H bars ({len(bars)})")
        return None

    # Add ticker
    bars["ticker"] = ticker

    # Indicators on 4H close series
    bars["ema9"]  = bars["Close"].ewm(span=9, adjust=False).mean()
    bars["ema21"] = bars["Close"].ewm(span=21, adjust=False).mean()
    bars["rsi"]   = rsi14(bars["Close"])
    bars["adx"]   = adx14(bars["High"], bars["Low"], bars["Close"])
    bars["atr"]   = atr14(bars["High"], bars["Low"], bars["Close"])

    # Derived
    bars["ema_spread"]     = bars["ema9"] - bars["ema21"]
    bars["ema_spread_pct"] = (bars["ema9"] - bars["ema21"]) / bars["ema21"] * 100
    bars["adx_slope"]      = bars["adx"] - bars["adx"].shift(1)

    # Skip warmup bars
    bars = bars.iloc[WARMUP_BARS:].reset_index(drop=True)

    return bars


# ── Cross detection ──────────────────────────────────────────────────────────
def detect_crosses(bars: pd.DataFrame, vix: pd.Series) -> pd.DataFrame:
    """Detect all EMA9/21 cross events in the ticker's 4H bars."""
    ema9  = bars["ema9"]
    ema21 = bars["ema21"]

    cross_up   = (ema9 > ema21) & (ema9.shift(1) <= ema21.shift(1))
    cross_down = (ema9 < ema21) & (ema9.shift(1) >= ema21.shift(1))

    events = []
    for idx in bars.index:
        if not (cross_up.iloc[idx] or cross_down.iloc[idx]):
            continue

        row = bars.iloc[idx]
        direction = "UP" if cross_up.iloc[idx] else "DOWN"

        vix_val = prior_vix(row["date"], vix)

        cross_bar_body_pct = abs(row["Close"] - row["Open"]) / row["Open"] * 100
        atr_pct = row["atr"] / row["Close"] * 100 if row["Close"] != 0 else np.nan
        is_anomaly = cross_bar_body_pct > 2 * atr_pct if not np.isnan(atr_pct) else False

        events.append({
            "ticker":            row["ticker"],
            "date":              row["date"],
            "bar_slot":          int(row["bar_slot"]),
            "direction":         direction,
            "open":              round(float(row["Open"]), 4),
            "high":              round(float(row["High"]), 4),
            "low":               round(float(row["Low"]), 4),
            "close":             round(float(row["Close"]), 4),
            "ema9":              round(float(row["ema9"]), 4),
            "ema21":             round(float(row["ema21"]), 4),
            "ema_spread_pct":    round(float(row["ema_spread_pct"]), 4),
            "rsi":               round(float(row["rsi"]), 2),
            "adx":               round(float(row["adx"]), 2),
            "adx_slope":         round(float(row["adx_slope"]), 4) if not np.isnan(row["adx_slope"]) else np.nan,
            "atr":               round(float(row["atr"]), 4),
            "atr_pct":           round(float(atr_pct), 4) if not np.isnan(atr_pct) else np.nan,
            "vix_prior_close":   round(float(vix_val), 2) if not np.isnan(vix_val) else np.nan,
            "cross_bar_body_pct": round(float(cross_bar_body_pct), 4),
            "is_anomaly_bar":    bool(is_anomaly),
            "bar_idx":           int(idx),
        })

    return pd.DataFrame(events)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("EMA Cross Falsification Study — Part 1: Data + Cross Detection")
    print("=" * 70)

    # Load VIX
    print("\nLoading VIX data...")
    vix = load_vix()

    # Build VIX prior-day lookup (precompute for efficiency)
    vix_dates = sorted(vix.index)

    # Process all tickers
    print(f"\nProcessing {len(TICKERS)} tickers...")
    all_bars_list = []
    all_crosses_list = []
    ticker_stats = {}

    for ticker in TICKERS:
        fpath = find_ticker_file(ticker)
        if fpath is None:
            print(f"  WARNING: {ticker} — no CSV file found, skipping")
            continue

        bars = process_ticker(ticker, fpath)
        if bars is None:
            continue

        # Map VIX prior-day close to all bars
        bars["vix_prior_close"] = bars["date"].apply(lambda d: prior_vix(d, vix))

        # Detect crosses
        crosses = detect_crosses(bars, vix)

        n_bars = len(bars)
        n_up   = len(crosses[crosses["direction"] == "UP"]) if not crosses.empty else 0
        n_down = len(crosses[crosses["direction"] == "DOWN"]) if not crosses.empty else 0

        # Date range
        date_min = bars["date"].min()
        date_max = bars["date"].max()
        years_span = (pd.Timestamp(str(date_max)) - pd.Timestamp(str(date_min))).days / 365.25

        ticker_stats[ticker] = {
            "n_bars": n_bars,
            "n_up": n_up,
            "n_down": n_down,
            "date_min": date_min,
            "date_max": date_max,
            "years": years_span,
        }

        print(f"  {ticker:6s}: {n_bars:5d} bars, {n_up:3d} UP / {n_down:3d} DOWN crosses "
              f"({date_min} to {date_max})")

        all_bars_list.append(bars)
        if not crosses.empty:
            all_crosses_list.append(crosses)

    if not all_bars_list:
        print("\nERROR: No ticker data processed. Check Fetched_Data/ directory.")
        return

    # Combine all data
    all_bars = pd.concat(all_bars_list, ignore_index=True)
    all_crosses = pd.concat(all_crosses_list, ignore_index=True) if all_crosses_list else pd.DataFrame()

    # ── Save outputs ──────────────────────────────────────────────────────────

    # 1. All 4H bars -> parquet (try) or CSV
    bars_path = os.path.join(OUT, "all_4h_bars.parquet")
    try:
        all_bars.to_parquet(bars_path, index=False)
        print(f"\n4H bars  -> {bars_path}")
    except Exception:
        bars_path = os.path.join(OUT, "all_4h_bars.csv")
        all_bars.to_csv(bars_path, index=False)
        print(f"\n4H bars  -> {bars_path} (CSV fallback)")

    # 2. Cross events -> CSV
    crosses_path = os.path.join(OUT, "ema_cross_events.csv")
    if not all_crosses.empty:
        all_crosses.to_csv(crosses_path, index=False)
    else:
        pd.DataFrame().to_csv(crosses_path, index=False)
    print(f"Crosses  -> {crosses_path}")

    # ── Summary statistics ────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    # Total bars
    total_bars = sum(s["n_bars"] for s in ticker_stats.values())
    avg_bars   = total_bars / len(ticker_stats) if ticker_stats else 0
    print(f"\n4H Bars: {total_bars} total, {avg_bars:.0f} avg per ticker "
          f"({len(ticker_stats)} tickers)")

    if all_crosses.empty:
        print("\nNo cross events detected.")
        return

    total_up   = len(all_crosses[all_crosses["direction"] == "UP"])
    total_down = len(all_crosses[all_crosses["direction"] == "DOWN"])
    print(f"\nCross Events: {len(all_crosses)} total")
    print(f"  UP crosses:   {total_up}")
    print(f"  DOWN crosses: {total_down}")

    # Cross frequency
    total_years = sum(s["years"] for s in ticker_stats.values())
    n_tickers   = len(ticker_stats)
    crosses_per_ticker_yr = len(all_crosses) / total_years if total_years > 0 else 0
    avg_years = total_years / n_tickers if n_tickers > 0 else 0
    print(f"\nCross Frequency: {crosses_per_ticker_yr:.1f} crosses/ticker/year "
          f"(avg {avg_years:.1f} years/ticker)")

    # Breakdown by VIX bucket
    print("\nBy VIX bucket:")
    vix_col = all_crosses["vix_prior_close"]
    for label, mask in [
        ("<20",   vix_col < 20),
        ("20-25", (vix_col >= 20) & (vix_col < 25)),
        (">=25",  vix_col >= 25),
    ]:
        n = mask.sum()
        n_nan = vix_col.isna().sum()
        pct = n / len(all_crosses) * 100 if len(all_crosses) > 0 else 0
        print(f"  VIX {label:5s}: {n:5d} ({pct:5.1f}%)")
    if vix_col.isna().sum() > 0:
        print(f"  VIX NaN  : {vix_col.isna().sum():5d}")

    # Breakdown by ADX bucket
    print("\nBy ADX bucket:")
    adx_col = all_crosses["adx"]
    for label, mask in [
        ("<20",  adx_col < 20),
        ("20-30", (adx_col >= 20) & (adx_col <= 30)),
        (">30",  adx_col > 30),
    ]:
        n = mask.sum()
        pct = n / len(all_crosses) * 100 if len(all_crosses) > 0 else 0
        print(f"  ADX {label:5s}: {n:5d} ({pct:5.1f}%)")

    # Breakdown by bar_slot
    print("\nBy bar_slot:")
    for slot in [1, 2]:
        n = (all_crosses["bar_slot"] == slot).sum()
        pct = n / len(all_crosses) * 100 if len(all_crosses) > 0 else 0
        label = "morning" if slot == 1 else "afternoon"
        print(f"  Slot {slot} ({label:9s}): {n:5d} ({pct:5.1f}%)")

    # Breakdown by year
    print("\nBy year:")
    all_crosses["_year"] = pd.to_datetime(all_crosses["date"].astype(str)).dt.year
    for yr in sorted(all_crosses["_year"].unique()):
        sub = all_crosses[all_crosses["_year"] == yr]
        n_up   = (sub["direction"] == "UP").sum()
        n_down = (sub["direction"] == "DOWN").sum()
        print(f"  {yr}: {len(sub):5d} ({n_up} UP, {n_down} DOWN)")

    # Anomaly bar count
    n_anomaly = all_crosses["is_anomaly_bar"].sum()
    print(f"\nAnomaly bars (body > 2x ATR): {n_anomaly} "
          f"({n_anomaly / len(all_crosses) * 100:.1f}%)")

    print(f"\nDone. Output in: {OUT}/")


if __name__ == "__main__":
    main()
