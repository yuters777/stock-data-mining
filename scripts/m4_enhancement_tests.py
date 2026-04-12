#!/usr/bin/env python3
"""
M4 Enhancement Tests -- PARTS 1-2 (Tests A-G)
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
                ticker=ticker, date=dt[i], year=dt[i].year, vix_val=vv, rsi_val=rv,
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


# -- PART 2 helpers ----------------------------------------------------------

def _stall_trade(tg, mode, ns):
    """Run single trade with stall early-exit.  mode: range/high/close."""
    fc, fe, fx = tg["fc"], tg["fe"], tg["fx"]
    entry = fc[0]
    th, tl, tc = tg["trig_h"], tg["trig_l"], tg["trig_c"]
    sn = 0
    for k in range(1, min(11, len(fc))):
        if fx[k]:
            return ((fc[k] - entry) / entry * 100, k, "hard_max")
        if fc[k] >= fe[k]:
            return ((fc[k] - entry) / entry * 100, k, "ema21")
        if mode == "range":
            stalled = tl <= fc[k] <= th
        elif mode == "high":
            stalled = fc[k] < th
        else:
            stalled = fc[k] < tc
        sn = sn + 1 if stalled else 0
        if sn >= ns:
            return ((fc[k] - entry) / entry * 100, k, "stall_exit")
        if k == 10:
            return ((fc[k] - entry) / entry * 100, k, "hard_max")
    return None


ALL_VARIANTS = []


def reg(vid, name, desc, trades, trigs=None):
    """Register variant for ranking and DR package."""
    s = trade_stats(trades)
    ALL_VARIANTS.append(dict(id=vid, name=name, desc=desc, stats=s,
                             trades=trades, trigs=trigs or []))
    return s


def collect_ad(triggers, vix):
    """Register Tests A-D variants into ALL_VARIANTS (no printing)."""
    reg("A1", "Base M4", "streak>=3 VIX>=25 RSI<35",
        [tg["base"] for tg in triggers], list(triggers))
    for aid, ck, desc in [
        ("A2", lambda tg: len(tg["fc"]) >= 2 and tg["fc"][1] > tg["fo"][1],
         "Bar+1 green"),
        ("A3", lambda tg: (len(tg["fc"]) > 1 and tg["fc"][1] > tg["fo"][1])
                        or (len(tg["fc"]) > 2 and tg["fc"][2] > tg["fo"][2]),
         "Bar+1|2 green"),
    ]:
        t, g = [], []
        for tg in triggers:
            if ck(tg):
                r = run_fwd(tg["fc"], tg["fe"], tg["fx"])
                if r:
                    t.append(r); g.append(tg)
        reg(aid, desc, f"Confirm: {desc}", t, g)
    for x in [30, 40, 50, 60, 70]:
        t, g = [], []
        for tg in triggers:
            tb = abs(tg["trig_c"] - tg["trig_o"])
            bb = abs(tg["bm2_c"] - tg["bm2_o"])
            if not np.isnan(bb) and bb > 0 and tb >= (x / 100.0) * bb:
                t.append(tg["base"]); g.append(tg)
        reg(f"B{x}", f"Body>={x}%", f"Trig body >= {x}% of bar-2", t, g)
    for cl, mode in [("C1", "range"), ("C2", "high"), ("C3", "close")]:
        for ns in [1, 2, 3, 4]:
            t, g = [], []
            for tg in triggers:
                r = _stall_trade(tg, mode, ns)
                if r:
                    t.append(r); g.append(tg)
            reg(f"{cl}N{ns}", f"{cl} stall N={ns}", f"Stall {mode} {ns}bars", t, g)
    dur = vix_duration_map(vix)
    roc = vix_roc_map(vix, 5)
    def _gd(tg):
        d = prior_vix_dt(tg["date"], vix)
        return dur.get(d, 0) if d else 0
    def _gr(tg):
        d = prior_vix_dt(tg["date"], vix)
        return roc.get(d, 0.0) if d else 0.0
    for vid, nm, fn in [
        ("D1", "VIX dur<=5",    lambda tg: _gd(tg) <= 5),
        ("D2", "VIX dur<=7",    lambda tg: _gd(tg) <= 7),
        ("D3", "VIX dur<=10",   lambda tg: _gd(tg) <= 10),
        ("D4", "VIX excl 6-10", lambda tg: _gd(tg) <= 5 or _gd(tg) > 10),
        ("D5", "ROC>20%",       lambda tg: _gr(tg) > 20),
        ("D6", "ROC>30%",       lambda tg: _gr(tg) > 30),
        ("D7", "ROC>50%",       lambda tg: _gr(tg) > 50),
    ]:
        sub = [tg for tg in triggers if fn(tg)]
        reg(vid, nm, f"Filter: {nm}", [tg["base"] for tg in sub], sub)


def enrich_for_g(triggers, tickers):
    """Add fh, fe10, fe14 arrays to triggers for Test G."""
    by_tk = {}
    for i, tg in enumerate(triggers):
        by_tk.setdefault(tg["ticker"], []).append(i)
    tk_path = {t: p for t, p in tickers}
    for tk, idxs in by_tk.items():
        bars = load_bars(tk_path.get(tk, ""))
        if bars is None:
            continue
        h_arr = bars["High"].values
        c_arr = bars["Close"].values
        e10 = bars["Close"].ewm(span=10, adjust=False).mean().values
        e14 = bars["Close"].ewm(span=14, adjust=False).mean().values
        dt_arr = bars["bar_date"].values
        dt_map = {}
        for j in range(len(dt_arr)):
            dt_map.setdefault((dt_arr[j], c_arr[j]), j)
        for ti in idxs:
            tg = triggers[ti]
            bi = dt_map.get((tg["date"], tg["trig_c"]))
            if bi is None:
                continue
            end = min(bi + 11, len(bars))
            tg["fh"] = h_arr[bi:end].copy()
            tg["fe10"] = e10[bi:end].copy()
            tg["fe14"] = e14[bi:end].copy()
    print("  Enrichment for Test G done.")


# -- TEST E: Combined filters -----------------------------------------------

def test_e(triggers, vix):
    print("\n=== TEST E: COMBINED FILTERS ===")
    dur = vix_duration_map(vix)
    def gd(tg):
        d = prior_vix_dt(tg["date"], vix)
        return dur.get(d, 0) if d else 0
    def conf(tg):
        return len(tg["fc"]) >= 2 and tg["fc"][1] > tg["fo"][1]
    tier_b = lambda tg: tg["rsi_val"] < 25
    tier_a = lambda tg: 25 <= tg["rsi_val"] < 35

    combos = [
        ("E1", "TIER_B+dur<=5",      "RSI<25 + VIX dur<=5d",
         lambda tg: tier_b(tg) and gd(tg) <= 5, None),
        ("E2", "TIER_B+confirm",     "RSI<25 + bar+1 green",
         lambda tg: tier_b(tg) and conf(tg), None),
        ("E3", "Confirm+dur<=7",     "bar+1 green + VIX dur<=7",
         lambda tg: conf(tg) and gd(tg) <= 7, None),
        ("E4", "Conf+C2N2+dur<=7",   "confirm + C2 stall N=2 + dur<=7",
         lambda tg: conf(tg) and gd(tg) <= 7,
         lambda tg: _stall_trade(tg, "high", 2)),
        ("E5", "TIER_B+conf+dur<=5", "RSI<25 + confirm + VIX dur<=5",
         lambda tg: tier_b(tg) and conf(tg) and gd(tg) <= 5, None),
        ("E6", "TIER_A+dur<=5+conf", "RSI 25-35 + dur<=5 + confirm",
         lambda tg: tier_a(tg) and gd(tg) <= 5 and conf(tg), None),
    ]
    for vid, nm, desc, filt, tfn in combos:
        t, g = [], []
        for tg in triggers:
            if not filt(tg):
                continue
            r = tfn(tg) if tfn else run_fwd(tg["fc"], tg["fe"], tg["fx"])
            if r:
                t.append(r); g.append(tg)
        s = reg(vid, nm, desc, t, g)
        print(f"  {vid}: {fmt(s)}")
    print("  [E complete]")


# -- TEST F: Early exit sweep -----------------------------------------------

def test_f(triggers):
    print("\n=== TEST F: EARLY EXIT SWEEP ===")
    for mx in [3, 4, 5, 6, 7, 8]:
        t, g = [], []
        for tg in triggers:
            r = run_fwd(tg["fc"], tg["fe"], tg["fx"], max_bars=mx)
            if r:
                t.append(r); g.append(tg)
        s = reg(f"F{mx}", f"Hard max={mx}", f"Max hold {mx} bars", t, g)
        hm = [x[0] for x in t if x[2] == "hard_max"]
        hm_avg = round(float(np.mean(hm)), 3) if hm else 0.0
        print(f"  F max={mx}: {fmt(s)}, hm_avg_loss={hm_avg:+.3f}%")
    print("  [F complete]")


# -- TEST G: Adaptive exit --------------------------------------------------

def test_g(triggers, tickers):
    print("\n=== TEST G: ADAPTIVE EXIT ===")
    enrich_for_g(triggers, tickers)

    # G1/G2: alternative EMA spans
    for gid, span, key in [("G1", 10, "fe10"), ("G2", 14, "fe14")]:
        t, g = [], []
        for tg in triggers:
            fe_alt = tg.get(key)
            if fe_alt is None:
                continue
            r = run_fwd(tg["fc"], fe_alt, tg["fx"])
            if r:
                t.append(r); g.append(tg)
        s = reg(gid, f"EMA({span}) exit", f"EMA{span} replaces EMA21", t, g)
        print(f"  {gid} EMA({span}):       {fmt(s)}")

    # G3: close > trigger high (breakout)
    t, g = [], []
    for tg in triggers:
        fc, fx = tg["fc"], tg["fx"]
        entry, th = fc[0], tg["trig_h"]
        for k in range(1, min(11, len(fc))):
            if fx[k]:
                t.append(((fc[k]-entry)/entry*100, k, "hard_max")); g.append(tg); break
            if fc[k] > th:
                t.append(((fc[k]-entry)/entry*100, k, "breakout")); g.append(tg); break
            if k == 10:
                t.append(((fc[k]-entry)/entry*100, k, "hard_max")); g.append(tg); break
    s = reg("G3", "Breakout exit", "Close > trigger high", t, g)
    print(f"  G3 breakout:      {fmt(s)}")

    # G4: close > prior bar high
    t, g = [], []
    for tg in triggers:
        fh = tg.get("fh")
        if fh is None:
            continue
        fc, fx = tg["fc"], tg["fx"]
        entry = fc[0]
        for k in range(1, min(11, len(fc))):
            if fx[k]:
                t.append(((fc[k]-entry)/entry*100, k, "hard_max")); g.append(tg); break
            if fc[k] > fh[k - 1]:
                t.append(((fc[k]-entry)/entry*100, k, "prior_high")); g.append(tg); break
            if k == 10:
                t.append(((fc[k]-entry)/entry*100, k, "hard_max")); g.append(tg); break
    s = reg("G4", "Prior bar high", "Close > prior bar high", t, g)
    print(f"  G4 prior high:    {fmt(s)}")

    # G5: trailing stop -- exit if close < lowest close seen during position
    t, g = [], []
    for tg in triggers:
        fc, fx = tg["fc"], tg["fx"]
        entry = fc[0]
        min_c = float("inf")
        for k in range(1, min(11, len(fc))):
            if fx[k]:
                t.append(((fc[k]-entry)/entry*100, k, "hard_max")); g.append(tg); break
            if k >= 2 and fc[k] < min_c:
                t.append(((fc[k]-entry)/entry*100, k, "trail_stop")); g.append(tg); break
            min_c = min(min_c, fc[k])
            if k == 10:
                t.append(((fc[k]-entry)/entry*100, k, "hard_max")); g.append(tg); break
    s = reg("G5", "Trailing stop", "Exit if new low in position", t, g)
    print(f"  G5 trail stop:    {fmt(s)}")
    print("  [G complete]")


# -- Ranking -----------------------------------------------------------------

def print_ranking():
    print("\n=== RANKING TABLE (Top 20 by PF, min N>=5) ===")
    valid = [v for v in ALL_VARIANTS if v["stats"]["N"] >= 5]
    valid.sort(key=lambda v: v["stats"]["PF"], reverse=True)
    print(f"  {'#':<4} {'ID':<10} {'Name':<24} {'N':>4} {'Mean':>8} "
          f"{'WR':>6} {'PF':>7} {'Hold':>5}")
    print(f"  {'----':<4} {'--------':<10} {'----------------------':<24} "
          f"{'----':>4} {'-------':>8} {'-----':>6} {'------':>7} {'----':>5}")
    for rank, v in enumerate(valid[:20], 1):
        s = v["stats"]
        pf = "inf" if s["PF"] == float("inf") else f"{s['PF']:.2f}"
        print(f"  {rank:<4} {v['id']:<10} {v['name']:<24} {s['N']:>4} "
              f"{s['Mean']:>+7.3f}% {s['WR']:>5.1f}% {pf:>7} {s['avg_hold']:>5.1f}")
    return valid[:20]


# -- DR package --------------------------------------------------------------

def save_dr():
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    OUT = os.path.join(BASE_DIR, "backtest_results")
    os.makedirs(OUT, exist_ok=True)

    # 1. Results CSV -- one row per variant
    rows = []
    for v in ALL_VARIANTS:
        s = v["stats"]
        rows.append(dict(variant_id=v["id"], name=v["name"],
                         description=v["desc"], N=s["N"], mean_pct=s["Mean"],
                         wr_pct=s["WR"], pf=s["PF"], avg_hold=s["avg_hold"],
                         ema_exit_pct=s["ema_exit"],
                         hard_max_pct=s["hard_max"]))
    rows.sort(key=lambda r: r["variant_id"])
    pd.DataFrame(rows).to_csv(
        os.path.join(OUT, "m4_enhancement_results.csv"), index=False)
    print(f"  Saved m4_enhancement_results.csv ({len(rows)} variants)")

    # 2. Top-5 trades CSV
    top5 = sorted([v for v in ALL_VARIANTS if v["stats"]["N"] >= 5],
                  key=lambda v: v["stats"]["PF"], reverse=True)[:5]
    trows = []
    for v in top5:
        for trade, trig in zip(v["trades"], v["trigs"]):
            trows.append(dict(
                variant_id=v["id"], ticker=trig.get("ticker", ""),
                entry_date=str(trig.get("date", "")),
                return_pct=round(trade[0], 4),
                bars_held=trade[1], exit_type=trade[2]))
    pd.DataFrame(trows).to_csv(
        os.path.join(OUT, "m4_enhancement_trades_top5.csv"), index=False)
    print(f"  Saved m4_enhancement_trades_top5.csv ({len(trows)} trades)")

    # 3. Summary MD
    ln = ["# M4 Enhancement Tests -- Summary", "",
          "## Overview",
          f"Total variants tested: {len(ALL_VARIANTS)}",
          "Base trigger: streak>=3, VIX>=25, RSI<35 on 4H bars (ET)", ""]
    base_v = next((v for v in ALL_VARIANTS if v["id"] == "A1"), None)
    if base_v:
        bs = base_v["stats"]
        ln.append(f"Baseline (A1): N={bs['N']}, Mean={bs['Mean']:+.3f}%, "
                  f"WR={bs['WR']:.1f}%, PF={bs['PF']}")
        ln.append("")
    for tid, tnm in [("A", "Confirmation Bar"), ("B", "Third Bar Size"),
                     ("C", "Stall Detection"), ("D", "VIX Duration"),
                     ("E", "Combined Filters"), ("F", "Early Exit Sweep"),
                     ("G", "Adaptive Exit")]:
        tvars = [v for v in ALL_VARIANTS if v["id"].startswith(tid)]
        if not tvars:
            continue
        best = max(tvars, key=lambda v: v["stats"]["PF"]
                   if v["stats"]["N"] >= 5 else -1)
        bs = best["stats"]
        pf_s = "inf" if bs["PF"] == float("inf") else f"{bs['PF']:.2f}"
        ln += [f"## Test {tid}: {tnm}", f"Variants: {len(tvars)}",
               f"Best: {best['id']} ({best['name']}) -- "
               f"N={bs['N']}, Mean={bs['Mean']:+.3f}%, PF={pf_s}", ""]
    ln += ["## Top 10 Variants by Profit Factor", "",
           "| Rank | ID | Name | N | Mean | WR | PF |",
           "|------|-----|------|---|------|----|----|"]
    top10 = sorted([v for v in ALL_VARIANTS if v["stats"]["N"] >= 5],
                   key=lambda v: v["stats"]["PF"], reverse=True)[:10]
    for rk, v in enumerate(top10, 1):
        s = v["stats"]
        pf_s = "inf" if s["PF"] == float("inf") else f"{s['PF']:.2f}"
        ln.append(f"| {rk} | {v['id']} | {v['name']} | {s['N']} | "
                  f"{s['Mean']:+.3f}% | {s['WR']:.1f}% | {pf_s} |")
    ln += ["", "## Recommendations", "",
           "1. Top variant should be validated with walk-forward testing",
           "2. Consider combining best filter + best exit for production",
           "3. Minimum N>=10 recommended for statistical significance", ""]
    with open(os.path.join(OUT, "m4_enhancement_summary.md"), "w") as f:
        f.write("\n".join(ln))
    print("  Saved m4_enhancement_summary.md")


# -- Main --------------------------------------------------------------------

def main():
    print("M4 Enhancement Tests -- PARTS 1-2 (A-G)")
    print("=" * 60)
    print("Loading VIX...")
    vix = load_vix()

    tickers = get_tickers()
    print(f"Tickers ({len(tickers)}): {[t for t, _ in tickers]}\n")

    print("Scanning triggers (streak>=3, VIX>=25, RSI<35)...")
    triggers = scan_triggers(tickers, vix)
    print(f"Total triggers: {len(triggers)}")

    # PART 1
    test_a(triggers)
    test_b(triggers)
    test_c(triggers)
    test_d(triggers, vix)
    print("\n" + "=" * 60)
    print("PART 1 complete (Tests A-D).\n")

    # PART 2
    print("=" * 60)
    print("PART 2 (Tests E-G)")
    test_e(triggers, vix)
    test_f(triggers)
    test_g(triggers, tickers)

    # Collect A-D variants for ranking
    print("\nRegistering all variants...")
    collect_ad(triggers, vix)

    # Ranking table
    print_ranking()

    # DR package
    print("\nSaving DR package...")
    save_dr()

    print("\n" + "=" * 60)
    print("All tests complete (PARTS 1-2).")


if __name__ == "__main__":
    main()
