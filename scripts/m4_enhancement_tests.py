#!/usr/bin/env python3
"""
M4 Enhancement Tests -- PART 1 (Tests A-D)
Base trigger: streak>=3, VIX>=25, RSI<35 on 4H bars (ET).
Exit: close >= EMA21 or 10-bar hard max.
27 equity tickers, _m5_full.csv, VIX_daily_fmp.json.
"""

import os
import sys
import numpy as np
import pandas as pd
import warnings

warnings.filterwarnings("ignore")

# Reuse shared functions from the main backtest module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m4_backtest_5yr import (
    build_4h, rsi14, calc_streak, _norm_m5, flag_corrupt,
    apply_ema21_warmup_mask, load_vix, get_tickers, prior_vix,
)


# -- Helpers -----------------------------------------------------------------

def load_bars(fpath):
    """Load M5 CSV -> 4H bars with ema21, rsi, streak, corrupt flag."""
    try:
        raw = pd.read_csv(fpath)
    except Exception:
        return None
    raw = _norm_m5(raw)
    if raw.empty or "Close" not in raw.columns:
        return None
    bars = build_4h(raw)
    if bars.empty or len(bars) < 20:
        return None
    bars["corrupt"] = flag_corrupt(bars["Close"])
    bars["ema21"] = bars["Close"].ewm(span=21, adjust=False).mean()
    if not fpath.endswith("_m5_full.csv"):
        bars["ema21"] = apply_ema21_warmup_mask(bars)
    bars["rsi"] = rsi14(bars["Close"])
    bars["streak"] = calc_streak(bars)
    bars["bar_date"] = [ts.date() for ts in bars["ts"]]
    return bars


def run_fwd(fc, fe, fx, max_bars=10):
    """Forward-simulate trade.  fc/fe/fx = close/ema21/corrupt arrays.
    Index 0 is trigger bar (entry).  Returns (ret%, held, exit_type) or None."""
    entry = fc[0]
    for k in range(1, min(max_bars + 1, len(fc))):
        if fx[k]:
            return ((fc[k] - entry) / entry * 100, k, "hard_max")
        if fc[k] >= fe[k]:
            return ((fc[k] - entry) / entry * 100, k, "ema21")
        if k == max_bars:
            return ((fc[k] - entry) / entry * 100, k, "hard_max")
    return None


def trade_stats(trades):
    """Stats from list of (ret%, held, exit_type) tuples."""
    if not trades:
        return dict(N=0, Mean=0.0, WR=0.0, PF=0.0,
                    avg_hold=0.0, ema_exit=0.0, hard_max=0.0)
    rets = np.array([t[0] for t in trades])
    holds = np.array([t[1] for t in trades])
    exits = [t[2] for t in trades]
    n = len(rets)
    gw = float(rets[rets > 0].sum())
    gl = float(abs(rets[rets <= 0].sum()))
    pf = round(gw / gl, 2) if gl > 0 else float("inf")
    ema_n = sum(1 for e in exits if e == "ema21")
    hm_n = sum(1 for e in exits if e == "hard_max")
    return dict(
        N=n, Mean=round(float(rets.mean()), 3),
        WR=round(float((rets > 0).mean() * 100), 1), PF=pf,
        avg_hold=round(float(holds.mean()), 1),
        ema_exit=round(ema_n / n * 100, 1),
        hard_max=round(hm_n / n * 100, 1),
    )


def fmt(s):
    """Format stats dict as single line."""
    if s["N"] == 0:
        return "N=0"
    pf = "inf" if s["PF"] == float("inf") else f"{s['PF']:.2f}"
    return (f"N={s['N']}, Mean={s['Mean']:+.3f}%, WR={s['WR']:.1f}%, PF={pf}, "
            f"avg_hold={s['avg_hold']:.1f}, "
            f"ema_exit={s['ema_exit']:.1f}%, hard_max={s['hard_max']:.1f}%")


# -- VIX duration / ROC helpers ----------------------------------------------

def vix_duration_map(vix):
    """dict{date -> consecutive trading days VIX>=25 as of that date}."""
    dm, streak = {}, 0
    for dt in sorted(vix.index):
        streak = streak + 1 if vix[dt] >= 25 else 0
        dm[dt] = streak
    return dm


def vix_roc_map(vix, window=5):
    """dict{date -> VIX pct change over last `window` trading days}."""
    idx = sorted(vix.index)
    rm = {}
    for k, dt in enumerate(idx):
        if k < window:
            rm[dt] = 0.0
        else:
            old = vix[idx[k - window]]
            rm[dt] = ((vix[dt] - old) / old * 100) if old > 0 else 0.0
    return rm


def prior_vix_dt(bar_date, vix):
    """Most recent VIX date strictly before bar_date, or None."""
    avail = vix.index[vix.index < bar_date]
    return avail[-1] if len(avail) else None


# -- Trigger scanner ---------------------------------------------------------

def scan_triggers(tickers, vix):
    """Find all base M4 triggers.  Returns list of trigger context dicts."""
    triggers = []
    for ticker, fpath in tickers:
        bars = load_bars(fpath)
        if bars is None:
            print(f"  {ticker:6s}: skip")
            continue
        c, o = bars["Close"].values, bars["Open"].values
        h, lo = bars["High"].values, bars["Low"].values
        ema = bars["ema21"].values
        rsi = bars["rsi"].values
        stk = bars["streak"].values if hasattr(bars["streak"], "values") else bars["streak"]
        dt = bars["bar_date"].values
        cor = bars["corrupt"].values
        n, cnt = len(bars), 0
        i = 0
        while i < n:
            if cor[i] or np.isnan(ema[i]) or stk[i] < 3:
                i += 1; continue
            vv = prior_vix(dt[i], vix)
            if np.isnan(vv) or vv < 25:
                i += 1; continue
            rv = rsi[i]
            if np.isnan(rv) or rv >= 35:
                i += 1; continue
            end = min(i + 11, n)
            fc = c[i:end].copy()
            fe = ema[i:end].copy()
            fx = cor[i:end].copy()
            base = run_fwd(fc, fe, fx)
            if base is None:
                i += 1; continue
            triggers.append(dict(
                ticker=ticker, date=dt[i], year=dt[i].year, vix_val=vv,
                trig_o=o[i], trig_c=c[i], trig_h=h[i], trig_l=lo[i],
                bm2_o=o[i - 2] if i >= 2 else np.nan,
                bm2_c=c[i - 2] if i >= 2 else np.nan,
                fc=fc, fo=o[i:end].copy(), fe=fe, fx=fx, base=base,
            ))
            cnt += 1
            i += base[1] + 1
        print(f"  {ticker:6s}: {cnt} triggers")
    return triggers


# -- TEST A: Confirmation bar ------------------------------------------------

def test_a(triggers):
    print("\n=== TEST A: CONFIRMATION BAR ===")
    # A1 -- base M4 (comparison)
    print(f"  A1 base M4:       {fmt(trade_stats([tg['base'] for tg in triggers]))}")

    # A2 -- hold if bar+1 green, else exit at bar+1 close
    conf, rej = [], []
    for tg in triggers:
        fc, fo, fe, fx = tg["fc"], tg["fo"], tg["fe"], tg["fx"]
        if len(fc) < 2:
            continue
        if fc[1] > fo[1]:  # bar+1 green
            t = run_fwd(fc, fe, fx)
            if t:
                conf.append(t)
        else:
            rej.append(((fc[1] - fc[0]) / fc[0] * 100, 1, "rejected"))
    print(f"  A2 confirmed:     {fmt(trade_stats(conf))}")
    print(f"  A2 rejected:      {fmt(trade_stats(rej))}")

    # A3 -- hold if bar+1 OR bar+2 green, else exit at bar+2 close
    conf, rej = [], []
    for tg in triggers:
        fc, fo, fe, fx = tg["fc"], tg["fo"], tg["fe"], tg["fx"]
        if len(fc) < 2:
            continue
        g1 = len(fc) > 1 and fc[1] > fo[1]
        g2 = len(fc) > 2 and fc[2] > fo[2]
        if g1 or g2:
            t = run_fwd(fc, fe, fx)
            if t:
                conf.append(t)
        else:
            ek = min(2, len(fc) - 1)
            rej.append(((fc[ek] - fc[0]) / fc[0] * 100, ek, "rejected"))
    print(f"  A3 confirmed:     {fmt(trade_stats(conf))}")
    print(f"  A3 rejected:      {fmt(trade_stats(rej))}")
    print("  [A complete]")


# -- TEST B: Third bar size -------------------------------------------------

def test_b(triggers):
    print("\n=== TEST B: THIRD BAR SIZE ===")
    print("  Skip if trigger bar body < X% of bar-2 body")
    for x in [30, 40, 50, 60, 70]:
        passed = []
        for tg in triggers:
            tb = abs(tg["trig_c"] - tg["trig_o"])
            bb = abs(tg["bm2_c"] - tg["bm2_o"])
            if np.isnan(bb) or bb == 0:
                continue
            if tb >= (x / 100.0) * bb:
                passed.append(tg["base"])
        print(f"  B skip<{x:2d}%:      {fmt(trade_stats(passed))}")
    print("  [B complete]")


# -- TEST C: Stall detection ------------------------------------------------

def test_c(triggers):
    print("\n=== TEST C: STALL DETECTION ===")
    print("  Early exit if close stalls for N consecutive bars")
    modes = [("C1 inside range",     "range"),
             ("C2 below trig high",  "high"),
             ("C3 below trig close", "close")]
    for label, mode in modes:
        for ns in [1, 2, 3, 4]:
            trades = []
            for tg in triggers:
                fc, fe, fx = tg["fc"], tg["fe"], tg["fx"]
                entry = fc[0]
                th, tl, tc = tg["trig_h"], tg["trig_l"], tg["trig_c"]
                sn, done = 0, False
                for k in range(1, min(11, len(fc))):
                    if fx[k]:
                        trades.append(((fc[k] - entry) / entry * 100,
                                       k, "hard_max"))
                        done = True; break
                    if fc[k] >= fe[k]:
                        trades.append(((fc[k] - entry) / entry * 100,
                                       k, "ema21"))
                        done = True; break
                    # stall check (only reached if EMA not hit)
                    if mode == "range":
                        stalled = tl <= fc[k] <= th
                    elif mode == "high":
                        stalled = fc[k] < th
                    else:
                        stalled = fc[k] < tc
                    sn = sn + 1 if stalled else 0
                    if sn >= ns:
                        trades.append(((fc[k] - entry) / entry * 100,
                                       k, "stall_exit"))
                        done = True; break
                    if k == 10:
                        trades.append(((fc[k] - entry) / entry * 100,
                                       k, "hard_max"))
                        done = True; break
            print(f"  {label} N={ns}: {fmt(trade_stats(trades))}")
        print()
    print("  [C complete]")


# -- TEST D: VIX duration ---------------------------------------------------

def test_d(triggers, vix):
    print("\n=== TEST D: VIX DURATION ===")
    dur = vix_duration_map(vix)
    roc = vix_roc_map(vix, 5)

    def get_dur(tg):
        dt = prior_vix_dt(tg["date"], vix)
        return dur.get(dt, 0) if dt else 0

    def get_roc(tg):
        dt = prior_vix_dt(tg["date"], vix)
        return roc.get(dt, 0.0) if dt else 0.0

    def show(passed, label):
        trades = [tg["base"] for tg in passed]
        print(f"  {label}: {fmt(trade_stats(trades))}")
        years = sorted(set(tg["year"] for tg in passed)) if passed else []
        for yr in years:
            yt = trade_stats([tg["base"] for tg in passed if tg["year"] == yr])
            print(f"    {yr}: N={yt['N']}, Mean={yt['Mean']:+.3f}%, "
                  f"WR={yt['WR']:.1f}%")

    # D1-D4: consecutive-days-above-25 filters
    print("  -- Duration of VIX>=25 streak (trading days) --")
    for label, fn in [
        ("D1 excl >5d",       lambda d: d <= 5),
        ("D2 excl >7d",       lambda d: d <= 7),
        ("D3 excl >10d",      lambda d: d <= 10),
        ("D4 excl 6-10 only", lambda d: d <= 5 or d > 10),
    ]:
        show([tg for tg in triggers if fn(get_dur(tg))], label)

    # D5-D7: VIX 5-day rate-of-change filters
    print("  -- VIX 5-day ROC filters --")
    for label, thr in [("D5 ROC>20%", 20), ("D6 ROC>30%", 30),
                        ("D7 ROC>50%", 50)]:
        show([tg for tg in triggers if get_roc(tg) > thr], label)

    print("  [D complete]")


# -- Main --------------------------------------------------------------------

def main():
    print("M4 Enhancement Tests -- PART 1 (A-D)")
    print("=" * 50)
    print("Loading VIX...")
    vix = load_vix()

    tickers = get_tickers()
    print(f"Tickers ({len(tickers)}): {[t for t, _ in tickers]}\n")

    print("Scanning triggers (streak>=3, VIX>=25, RSI<35)...")
    triggers = scan_triggers(tickers, vix)
    print(f"Total triggers: {len(triggers)}")

    test_a(triggers)
    test_b(triggers)
    test_c(triggers)
    test_d(triggers, vix)

    print("\n" + "=" * 50)
    print("PART 1 complete (Tests A-D).")


if __name__ == "__main__":
    main()
