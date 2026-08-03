#!/usr/bin/env python3
"""
GN-1 — Neutral-Regime Stretch Reversion — pre-registered backtest.

Realizes the LOCKED pre-registration `PreReg_..._good-novel_v2` EXACTLY.
This is NOT Module 4. The frozen strategy contract is:

    Regime gate     : VIX < 20  AND  ADX(4H) < 20
    Stretch trigger : 4H close <= EMA21 - 2*sigma,
                      sigma = stdev(close - EMA21) over trailing 50x4H bars
    Direction       : LONG only
    Entry           : close of the trigger 4H bar
    Exit            : first 4H close >= EMA21, OR hard-max 10 4H bars
    Universe        : 27 equity tickers (Fetched_Data/, excl. SPY/VIXY/crypto)
    Period          : 2021-04-19 -> 2025-12-31 inclusive (cap 2025-12-31 23:55 UTC)

Frozen constants (EMA 21, sigma window 50, 2 sigma, VIX 20, ADX 20, max-bars 10)
are NOT tunables. Exactly one run; no parameter sweeps. A marginal/BAD label is a
valid, honest outcome.

Reuse policy (see GN1_label_report.md "Implementation notes" for the rationale of
each delta):
  * Bar building / RTH filter      : m4_backtest_5yr.build_4h        (reused as-is)
  * 4H column normaliser           : m4_backtest_5yr._norm_m5        (reused as-is)
  * Split-corruption flag          : m4_backtest_5yr.flag_corrupt    (reused as-is)
  * Spot-VIX loader (FMP json)     : m4_backtest_5yr.load_vix        (reused as-is)
  * Daily-VIX -> bar join          : m4_backtest_5yr.prior_vix       (reused as-is)
  * 27-ticker universe discovery   : m4_backtest_5yr.get_tickers     (reused as-is)
  * Stats (n/mean/wr/pf/sharpe)    : m4_backtest_5yr.stats           (reused as-is)
  * ADX(4H) helper                 : ema_cross_part1_data.adx14      (reused as-is)
  * Dual-exit (EMA-cross or N-bar) : structure of m4_backtest_5yr L361-377 (reused)
m4_backtest_5yr.py is imported, never modified.

GN-1-specific (new): the regime gate (VIX<20 & ADX<20) and the -2sigma stretch
entry. M4's streak/RSI entry is deliberately NOT used.
"""

import os
import sys
import json
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# Import the reusable machinery (do NOT modify m4_backtest_5yr.py).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m4_backtest_5yr import (        # noqa: E402
    load_vix,
    get_tickers,
    build_4h,
    _norm_m5,
    flag_corrupt,
    prior_vix,
    stats,
)
from ema_cross_part1_data import adx14   # noqa: E402  (4H ADX, Wilder DI+/DI-)

# ── FROZEN CONSTANTS (do not tune; not exposed as CLI tunables) ───────────────
EMA_SPAN     = 21          # EMA21
SIGMA_WINDOW = 50          # trailing 50x4H bars for sigma
SIGMA_MULT   = 2.0         # -2 sigma stretch
VIX_MAX      = 20.0        # regime gate: VIX < 20
ADX_MAX      = 20.0        # regime gate: ADX(4H) < 20
MAX_BARS     = 10          # hard-max hold = 10 4H bars

PERIOD_START = pd.Timestamp("2021-04-19 00:00:00")   # inclusive
PERIOD_END   = pd.Timestamp("2025-12-31 23:55:00")   # inclusive cap (UTC)

# Informative IS/OOS split by entry date (NOT gating — see report §5).
IS_END    = pd.Timestamp("2024-06-30 23:59:59")      # IS  : start .. 2024-06-30
OOS_START = pd.Timestamp("2024-07-01 00:00:00")      # OOS : 2024-07-01 .. end

# ── Paths ────────────────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "Fetched_Data")
OUT  = os.path.join(BASE, "backtest_results")
os.makedirs(OUT, exist_ok=True)


# ── §2.6 leading-bar hygiene (generic, uniform across all tickers) ───────────
def drop_leading_degenerate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drop the contiguous block of LEADING rows where
        Volume == 0 AND Open == High == Low == Close
    (degenerate bootstrap bars, e.g. ARM's first $51/V=0 reference bar).
    Interior degenerate bars are left untouched. df must be sorted ascending.
    """
    if df.empty:
        return df
    deg = (
        (df["Volume"] == 0)
        & (df["Open"] == df["High"])
        & (df["High"] == df["Low"])
        & (df["Low"] == df["Close"])
    ).to_numpy()
    k = 0
    for v in deg:
        if v:
            k += 1
        else:
            break
    return df.iloc[k:].reset_index(drop=True) if k else df


# ── GN-1 backtest for one ticker ─────────────────────────────────────────────
def backtest_gn1(ticker: str, fpath: str, vix: pd.Series):
    """
    Return (trades:list[dict], counters:dict) for one ticker.

    counters keys: bars, vix_pass, vix_adx_pass, trig_eligible, trades
    """
    empty_cnt = {"bars": 0, "vix_pass": 0, "vix_adx_pass": 0,
                 "trig_eligible": 0, "trades": 0}
    try:
        raw = pd.read_csv(fpath)
    except Exception:
        return [], dict(empty_cnt)
    raw = _norm_m5(raw)
    if raw.empty or "Close" not in raw.columns:
        return [], dict(empty_cnt)

    # Parse, sort, truncate to the frozen period BEFORE resampling (§2.5),
    # then drop leading degenerate bars BEFORE indicators (§2.6).
    raw = raw.copy()
    raw["dt"] = pd.to_datetime(raw["Datetime"], errors="coerce")
    raw = raw.dropna(subset=["dt"]).sort_values("dt")
    raw = raw[(raw["dt"] >= PERIOD_START) & (raw["dt"] <= PERIOD_END)]
    raw = drop_leading_degenerate(raw)
    if raw.empty:
        return [], dict(empty_cnt)

    bars = build_4h(raw)                       # reused: RTH filter + 4H aggregation
    if bars.empty or len(bars) <= SIGMA_WINDOW:
        return [], dict(empty_cnt)

    # ── Indicators on the 4H series (frozen contract) ──
    corrupt = flag_corrupt(bars["Close"]).to_numpy()          # reused
    bars["ema21"] = bars["Close"].ewm(span=EMA_SPAN, adjust=False).mean()
    resid          = bars["Close"] - bars["ema21"]
    bars["sigma"]  = resid.rolling(SIGMA_WINDOW).std()        # 50-bar warm-up
    bars["adx"]    = adx14(bars["High"], bars["Low"], bars["Close"])  # reused

    closes = bars["Close"].to_numpy()
    emas   = bars["ema21"].to_numpy()
    sigmas = bars["sigma"].to_numpy()
    adxs   = bars["adx"].to_numpy()
    ts     = bars["ts"].tolist()
    dates  = [t.date() for t in ts]
    n      = len(bars)

    # ── Sequential-gate diagnostic counters (independent of trade state) ──
    nc       = ~corrupt
    vix_arr  = np.array([prior_vix(d, vix) for d in dates], dtype=float)
    vix_mask = nc & ~np.isnan(vix_arr) & (vix_arr < VIX_MAX)          # VIX<20
    adx_mask = vix_mask & ~np.isnan(adxs) & (adxs < ADX_MAX)          # &ADX<20
    sig_ok   = ~np.isnan(sigmas) & ~np.isnan(emas)
    trig_msk = adx_mask & sig_ok & (closes <= emas - SIGMA_MULT * sigmas)
    counters = {
        "bars":          int(n),
        "vix_pass":      int(vix_mask.sum()),
        "vix_adx_pass":  int(adx_mask.sum()),
        "trig_eligible": int(trig_msk.sum()),
        "trades":        0,
    }

    # ── Trade loop: one position per ticker at a time (no stacking) ──
    trades: list[dict] = []
    i = 0
    while i < n:
        if corrupt[i]:                       # skip split-corrupt bar (data hygiene)
            i += 1
            continue
        vix_val = prior_vix(dates[i], vix)   # regime gate 1: VIX < 20
        if np.isnan(vix_val) or vix_val >= VIX_MAX:
            i += 1
            continue
        adx_val = adxs[i]                    # regime gate 2: ADX(4H) < 20
        if np.isnan(adx_val) or adx_val >= ADX_MAX:
            i += 1
            continue
        sigma_val = sigmas[i]               # need >=50-bar warm-up for sigma/ema
        ema_val   = emas[i]
        if np.isnan(sigma_val) or np.isnan(ema_val):
            i += 1
            continue
        entry_price = closes[i]
        if not (entry_price <= ema_val - SIGMA_MULT * sigma_val):   # -2 sigma stretch
            i += 1
            continue

        # ── Trigger fired -> LONG entry at trigger-bar close ──
        entry_ts = ts[i]
        exit_price = exit_ts = exit_type = None
        bars_held = 0
        # Dual exit (reuse of m4_backtest_5yr L361-377 structure):
        for j in range(i + 1, min(i + 1 + MAX_BARS, n)):
            bars_held += 1
            if corrupt[j]:
                exit_price, exit_ts, exit_type = closes[j], ts[j], "hard_max"
                break
            if closes[j] >= emas[j]:                     # first 4H close >= EMA21
                exit_price, exit_ts, exit_type = closes[j], ts[j], "ema21"
                break
            if bars_held == MAX_BARS:                    # hard-max 10 bars
                exit_price, exit_ts, exit_type = closes[j], ts[j], "hard_max"
                break

        if exit_price is None:               # trigger on the final bar -> no exit bar
            i += 1
            continue

        ret = (exit_price - entry_price) / entry_price * 100.0
        entry_dt = pd.Timestamp(entry_ts)
        split = "IS" if entry_dt <= IS_END else "OOS"
        trades.append({
            "ticker":        ticker,
            "entry_ts":      str(entry_ts),
            "exit_ts":       str(exit_ts),
            "entry_date":    str(entry_dt.date()),
            "exit_date":     str(pd.Timestamp(exit_ts).date()),
            "entry_price":   round(float(entry_price), 4),
            "exit_price":    round(float(exit_price), 4),
            "return_pct":    round(float(ret), 4),
            "bars_held":     int(bars_held),
            "exit_type":     exit_type,
            "vix_at_entry":  round(float(vix_val), 2),
            "adx_at_entry":  round(float(adx_val), 2),
            "sigma_at_entry": round(float(sigma_val), 4),
            "ema21_at_entry": round(float(ema_val), 4),
            "split":         split,
        })
        i += bars_held + 1                   # skip past exit bar (no stacking)

    counters["trades"] = len(trades)
    return trades, counters


# ── Stats helper (mirror M4 stats() shape + sum of returns) ──────────────────
def split_stats(rets: list[float]) -> dict:
    s = stats(rets)                          # {n, mean, wr, pf, sharpe}
    s["sum"] = round(float(np.sum(rets)), 4) if rets else 0.0
    return s


# ── Frozen label criterion (applied exactly once) ────────────────────────────
def gn1_label(n: int, pf: float, mean: float) -> str:
    """
    GOOD     = N>=40 AND PF>=1.5 AND mean>0
    marginal = 1.0 < PF < 1.5  OR  N<40   (i.e. not GOOD and not BAD)
    BAD      = PF <= 1.0
    Precedence: BAD first, then GOOD, else marginal.
    """
    if pf <= 1.0:
        return "BAD"
    if n >= 40 and pf >= 1.5 and mean > 0:
        return "GOOD"
    return "marginal"


def main():
    print("=" * 72)
    print("GN-1 Neutral-Regime Stretch Reversion — pre-registered backtest")
    print("=" * 72)
    print("Loading spot VIX (FMP json)...")
    vix = load_vix()

    tickers = get_tickers()
    print(f"  Universe ({len(tickers)} equity tickers): {[t for t, _ in tickers]}\n")
    if len(tickers) != 27:
        print(f"  WARNING: expected 27 equity tickers, found {len(tickers)}.")

    # ── Single run over the full period ──
    all_trades: list[dict] = []
    per_ticker_counters: dict[str, dict] = {}
    print("Per-ticker run:")
    for ticker, fpath in tickers:
        trades, cnt = backtest_gn1(ticker, fpath, vix)
        per_ticker_counters[ticker] = cnt
        all_trades.extend(trades)
        print(f"  {ticker:6s}: bars={cnt['bars']:5d}  VIX<20={cnt['vix_pass']:5d}  "
              f"VIX&ADX<20={cnt['vix_adx_pass']:5d}  trig={cnt['trig_eligible']:4d}  "
              f"trades={cnt['trades']:3d}")

    df = pd.DataFrame(all_trades)

    # ── (a) Numbers: full corpus + IS/OOS ──
    if df.empty:
        full = split_stats([])
        is_s = split_stats([])
        oos_s = split_stats([])
    else:
        df = df.sort_values("entry_ts").reset_index(drop=True)
        full = split_stats(df["return_pct"].tolist())
        is_s = split_stats(df[df["split"] == "IS"]["return_pct"].tolist())
        oos_s = split_stats(df[df["split"] == "OOS"]["return_pct"].tolist())

    label = gn1_label(full["n"], full["pf"], full["mean"])

    # ── Aggregate sanity counters ──
    tot = {k: sum(c[k] for c in per_ticker_counters.values())
           for k in ["bars", "vix_pass", "vix_adx_pass", "trig_eligible", "trades"]}

    # ── PRINT: (a) numbers ──
    def fmt(s):
        return (f"N={s['n']}, PF={s['pf']}, mean={s['mean']}%, "
                f"WR={s['wr']}%, sum={s['sum']}%")
    print("\n" + "=" * 72)
    print("(a) RESULTS")
    print("=" * 72)
    print(f"  FULL CORPUS : {fmt(full)}")
    print(f"  IS (->2024-06-30) : {fmt(is_s)}")
    print(f"  OOS(2024-07-01->) : {fmt(oos_s)}")

    # ── PRINT: (b) sanity counters ──
    print("\n" + "=" * 72)
    print("(b) SANITY COUNTERS")
    print("=" * 72)
    print(f"  bars after VIX<20 gate          : {tot['vix_pass']}")
    print(f"  bars after VIX<20 AND ADX<20    : {tot['vix_adx_pass']}")
    print(f"  -2 sigma triggers (eligible)    : {tot['trig_eligible']}")
    print(f"  trades entered (after no-stack)  : {tot['trades']}")
    print("  trades per ticker:")
    nz = [(t, c["trades"]) for t, c in per_ticker_counters.items() if c["trades"] > 0]
    nz.sort(key=lambda x: -x[1])
    for t, n in nz:
        print(f"      {t:6s}: {n}")
    zero = [t for t, c in per_ticker_counters.items() if c["trades"] == 0]
    print(f"      (0 trades): {zero}")
    if not df.empty:
        top_t, top_n = nz[0]
        share = top_n / max(1, full["n"])
        flag = "  <-- DOMINANT (>40% of trades)" if share > 0.40 else ""
        print(f"  concentration: top ticker {top_t} holds "
              f"{top_n}/{full['n']} = {share*100:.1f}%{flag}")

    # ── PRINT: (d) sample trades ──
    print("\n" + "=" * 72)
    print("(d) SAMPLE TRADES (first 5 / last 5; verify EMA21-cross or 10-bar exit)")
    print("=" * 72)
    if not df.empty:
        cols = ["ticker", "entry_ts", "entry_price", "exit_ts", "exit_price",
                "bars_held", "return_pct", "exit_type"]
        head = df.head(5)[cols]
        tail = df.tail(5)[cols]
        hdr = (f"  {'ticker':6s} {'entry_ts':19s} {'entry_px':>10s} "
               f"{'exit_ts':19s} {'exit_px':>10s} {'bars':>4s} {'ret%':>8s} {'exit':>8s}")
        print("  FIRST 5:")
        print(hdr)
        for _, r in head.iterrows():
            print(f"  {r['ticker']:6s} {r['entry_ts']:19s} {r['entry_price']:>10.4f} "
                  f"{r['exit_ts']:19s} {r['exit_price']:>10.4f} {r['bars_held']:>4d} "
                  f"{r['return_pct']:>8.4f} {r['exit_type']:>8s}")
        print("  LAST 5:")
        print(hdr)
        for _, r in tail.iterrows():
            print(f"  {r['ticker']:6s} {r['entry_ts']:19s} {r['entry_price']:>10.4f} "
                  f"{r['exit_ts']:19s} {r['exit_price']:>10.4f} {r['bars_held']:>4d} "
                  f"{r['return_pct']:>8.4f} {r['exit_type']:>8s}")
    else:
        print("  (no trades)")

    # ── PRINT: (e) label ──
    print("\n" + "=" * 72)
    print("(e) FROZEN LABEL (applied once)")
    print("=" * 72)
    print("  GOOD = N>=40 AND PF>=1.5 AND mean>0 | "
          "marginal = 1.0<PF<1.5 or N<40 | BAD = PF<=1.0")
    print(f"  full-corpus: N={full['n']}, PF={full['pf']}, mean={full['mean']}%")
    print(f"  ==> LABEL: {label}")
    if label == "GOOD" and oos_s["n"] > 0 and oos_s["pf"] < 1.0:
        print("  NOTE: full=GOOD but OOS PF<1.0 -> regime-fragile GOOD")

    # ── Save (a) outputs ──
    trades_path  = os.path.join(OUT, "gn1_trades.csv")
    summary_path = os.path.join(OUT, "gn1_summary.json")
    if df.empty:
        pd.DataFrame(columns=[
            "ticker", "entry_ts", "exit_ts", "entry_date", "exit_date",
            "entry_price", "exit_price", "return_pct", "bars_held", "exit_type",
            "vix_at_entry", "adx_at_entry", "sigma_at_entry", "ema21_at_entry",
            "split",
        ]).to_csv(trades_path, index=False)
    else:
        df.to_csv(trades_path, index=False)

    summary = {
        "strategy": "GN-1 Neutral-Regime Stretch Reversion",
        "frozen_contract": {
            "regime_gate": "VIX < 20 AND ADX(4H) < 20",
            "trigger": "4H close <= EMA21 - 2*sigma; sigma=stdev(close-EMA21) over 50x4H",
            "direction": "LONG",
            "entry": "trigger 4H bar close",
            "exit": "first 4H close >= EMA21, else hard-max 10 4H bars",
            "constants": {"ema_span": EMA_SPAN, "sigma_window": SIGMA_WINDOW,
                          "sigma_mult": SIGMA_MULT, "vix_max": VIX_MAX,
                          "adx_max": ADX_MAX, "max_bars": MAX_BARS},
            "period": "2021-04-19 .. 2025-12-31 (cap 2025-12-31 23:55 UTC)",
            "universe_n": len(tickers),
            "costs": "none (consistency with M4 baseline family)",
        },
        "full":  full,
        "is":    is_s,
        "oos":   oos_s,
        "label": label,
        "label_criterion": "GOOD=N>=40 & PF>=1.5 & mean>0; marginal=1.0<PF<1.5 or N<40; BAD=PF<=1.0",
        "sanity_counters_total": tot,
        "trades_per_ticker": {t: c["trades"] for t, c in per_ticker_counters.items()},
        "per_ticker_counters": per_ticker_counters,
    }
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\nTrades  -> {trades_path}")
    print(f"Summary -> {summary_path}")
    print("DONE (single run).")


if __name__ == "__main__":
    main()
