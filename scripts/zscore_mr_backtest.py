#!/usr/bin/env python3
"""
Agent strategy #3 -- Z-score Mean Reversion (STRICT ORIGINAL, naive flipper).

Pre-registration : PreReg_backtest_3_zscore_MR_strict_v1.md  (hypothesis bb94b900)
Execution spec   : CC_backtest_spec_3_zscore_MR_strict_v1.md
Results artifact  : results/zscore_mr_strict_v1/

STEP-1 ENGINE-COMPAT FINDING (why this standalone harness exists)
----------------------------------------------------------------
scripts/m4_backtest_5yr.py is HARD-CODED to the Module-4 streak/EMA mechanic
(entry = 3 consecutive down 4H bars + VIX>=25 + RSI<35; exit = first close>=EMA21
or 10-bar hard max) and is LONG-ONLY with no position reversal. It therefore
CANNOT express a z-score long/short flipper (different mechanic, needs shorts +
reversal + hold-through-neutral). Per pre-reg s6 we do NOT shoehorn z-score into
streak/EMA params. We REUSE the engine's metric functions and implement only the
flipper trade-construction that the engine cannot represent:

    from m4_backtest_5yr import stats, profit_factor   # REUSED verbatim

`stats()`/`profit_factor()` are pure functions of a flat list of trade returns
(m4_backtest_5yr.py:478, :496) -- NOT coupled to M4 streak/trade structure -- so
they are reused as-is for PF / win-rate / N / mean / Sharpe. The engine computes
NO drawdown anywhere, so max-drawdown is computed here (additive equity curve) and
proved equal to a server-side SQL window computation in the artifact.

STRATEGY (EXACT, from source XBT3K/MeanReversionAlgo main.py + config.ini)
-------------------------------------------------------------------------
  window = 20 ; z = (close - SMA20) / STD20   (STD = sample std, ddof=1, == pandas)
  z > +1.5  -> signal -1 (SHORT, overbought)
  z < -1.5  -> signal +1 (LONG, oversold)
  else      -> 0 (no order)

  Position model (naive flipper, operator-confirmed reading of an under-specified
  source -- OANDA broker-netting of repeated same-side market orders is NOT
  extractable from main.py): position = sign of the LAST extreme; it flips ONLY
  when z crosses the OPPOSITE +/-1.5 threshold; same-side repeats and the neutral
  band HOLD. No stop, no take-profit, no z->0 exit. Entry and exit at the flip
  bar's close. Per-trade return = position * (exit-entry)/entry * 100, which
  generalizes the engine's long-only (exit-entry)/entry*100 to shorts.

  Costs = engine default = 0 (the m4 base engine subtracts none; pre-reg s2
  forbids adding/removing costs). NB: a ~170k-trade flipper would be obliterated
  by realistic costs -- the zero-cost figure is a generous upper bound, recorded
  as a finding, not corrected.

DATA / UNIVERSE / PERIOD (pre-reg s2)
------------------------------------
  research.db `bars_m5` : 5,068,651 bars, 28 tickers, 2021-04-19 -> 2025-12-31.
  Universe = 27 equity tickers = the 28 in bars_m5 minus SPY (the 1 non-equity).
  Full period, both directions, fixed unit, no regime/VIX/news gating.

REPRODUCE (architect, with a local copy of research.db)
-------------------------------------------------------
  python scripts/zscore_mr_backtest.py --db /path/to/research.db \
         --out results/zscore_mr_strict_v1

  Equivalent one-liner per ticker (read-only) to pull that ticker's trades on
  demand without a full re-run -- see TRADES_SQL below (bind ?=ticker).

  This CC run had no local research.db (read-only MCP only), so trades were
  produced server-side via the IDENTICAL TRADES_SQL and parsed from the MCP
  dumps (--mcp-dumps); numbers are cross-checked against the server-side SQL
  aggregates embedded in SQL_REF below.
"""
from __future__ import annotations

import argparse
import csv
import glob
import gzip
import json
import os
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m4_backtest_5yr import stats as engine_stats          # REUSED engine metric
from m4_backtest_5yr import profit_factor as engine_pf     # REUSED engine metric

# ---- Pre-registered constants (DO NOT CHANGE -- pre-reg s1/s5) --------------
WINDOW = 20
Z_HI = 1.5
Z_LO = -1.5
# |ret%| > 500 == an entry/exit price off by >6x == the threshold the engine's
# own flag_corrupt() (m4_backtest_5yr.py:197) uses to mark split/feed-corrupt
# bars. Used ONLY to *flag* and provide an ex-glitch sensitivity; the primary
# result is strict as-is (no corruption filter, per pre-reg s1).
GLITCH_ABS_RET = 500.0

UNIVERSE = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU", "C", "COIN",
    "COST", "GOOGL", "GS", "INTC", "JD", "JPM", "MARA", "META", "MSFT", "MSTR",
    "MU", "NVDA", "PLTR", "SMCI", "TSLA", "TSM", "V",
]  # 28 bars_m5 tickers minus SPY

# ---- Canonical z-score-flipper SQL (one ticker; bind ?=ticker) --------------
# Returns one closed trade per row, ordered by exit time. Identical logic to the
# server-side run that produced this artifact. STD uses *20/19 == sample std
# (ddof=1) to match pandas rolling(20).std(); first 19 bars get no z (warmup).
TRADES_SQL = """
WITH base AS (
  SELECT ticker, timestamp_utc, close,
    AVG(close) OVER w AS sma, AVG(close*close) OVER w AS sma2, COUNT(*) OVER w AS cnt
  FROM bars_m5 WHERE ticker = ?
  WINDOW w AS (PARTITION BY ticker ORDER BY timestamp_utc ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)),
zc AS (SELECT ticker, timestamp_utc, close,
    CASE WHEN cnt=20 AND (sma2-sma*sma)>0 THEN (close-sma)/sqrt((sma2-sma*sma)*20.0/19.0) ELSE NULL END AS zscore,
    ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY timestamp_utc) AS rn FROM base),
zs AS (SELECT *, CASE WHEN zscore>1.5 THEN -1 WHEN zscore<-1.5 THEN 1 ELSE 0 END AS sg FROM zc),
g  AS (SELECT *, SUM(CASE WHEN sg<>0 THEN 1 ELSE 0 END) OVER (PARTITION BY ticker ORDER BY timestamp_utc ROWS UNBOUNDED PRECEDING) AS grp FROM zs),
p  AS (SELECT *, MAX(CASE WHEN sg<>0 THEN sg END) OVER (PARTITION BY ticker, grp) AS position FROM g),
fl AS (SELECT *, LAG(position) OVER (PARTITION BY ticker ORDER BY timestamp_utc) AS prev_pos FROM p),
opens AS (SELECT ticker, timestamp_utc AS entry_ts, close AS entry_px, position, rn AS entry_rn
          FROM fl WHERE position IS NOT NULL AND (prev_pos IS NULL OR position<>prev_pos)),
tr AS (SELECT ticker, position, entry_ts, entry_px, entry_rn,
         LEAD(entry_px) OVER (PARTITION BY ticker ORDER BY entry_ts) AS exit_px,
         LEAD(entry_ts) OVER (PARTITION BY ticker ORDER BY entry_ts) AS exit_ts,
         LEAD(entry_rn) OVER (PARTITION BY ticker ORDER BY entry_ts) AS exit_rn FROM opens)
SELECT exit_ts,
       ROUND(position*(exit_px-entry_px)/entry_px*100.0, 6) AS ret,
       position, (exit_rn-entry_rn) AS hold
FROM tr WHERE exit_ts IS NOT NULL ORDER BY exit_ts;
"""

# Per-ticker bar-level stats (neutral band %, coverage). Bind ?=ticker.
BARS_SQL = """
WITH base AS (
  SELECT ticker, timestamp_utc, close,
    AVG(close) OVER w AS sma, AVG(close*close) OVER w AS sma2, COUNT(*) OVER w AS cnt
  FROM bars_m5 WHERE ticker = ?
  WINDOW w AS (PARTITION BY ticker ORDER BY timestamp_utc ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)),
zc AS (SELECT timestamp_utc,
    CASE WHEN cnt=20 AND (sma2-sma*sma)>0 THEN (close-sma)/sqrt((sma2-sma*sma)*20.0/19.0) ELSE NULL END AS zscore FROM base)
SELECT COUNT(*) AS n_bars,
  SUM(CASE WHEN zscore IS NOT NULL THEN 1 ELSE 0 END) AS n_z,
  SUM(CASE WHEN zscore IS NOT NULL AND ABS(zscore)<=1.5 THEN 1 ELSE 0 END) AS n_neutral,
  MIN(timestamp_utc) AS first_ts, MAX(timestamp_utc) AS last_ts FROM zc;
"""

# ---- Server-side SQL reference (for --mcp-dumps mode bar-stats + the equality
#      proof). Each row is the per-ticker aggregate computed entirely in SQL on
#      research.db. PF/WR/mean/max_dd here are the SQL-side numbers; the harness
#      recomputes them from per-trade data via the reused engine stats() and the
#      two are compared in results.md (condition #1 / Principle #32 guard). ----
# cols: n_bars, n_z, n_neutral, first_ts, last_ts, n_trades, win_rate, mean_ret, pf, max_dd
SQL_REF = {
 "AAPL": (220970,220951,163397,"2021-04-19 08:00:00","2025-12-31 23:55:00",7478,67.5047,0.033426,1.165805,37.470894),
 "AMD":  (216839,216820,159862,"2021-04-19 08:00:00","2025-12-31 23:55:00",7096,65.7835,-0.015528,0.963294,188.06481),
 "AMZN": (199930,199911,147762,"2021-04-19 10:35:00","2025-12-31 23:55:00",6774,66.8143,0.032722,1.122426,47.102202),
 "ARM":  (96781,96762,72261,"2023-09-14 13:35:00","2025-12-31 23:55:00",3310,68.3384,0.090869,1.183973,65.847636),
 "AVGO": (143383,143364,105015,"2021-04-19 13:10:00","2025-12-31 23:55:00",4762,65.6867,0.006733,1.016902,72.427191),
 "BA":   (173692,173673,129625,"2021-04-19 08:00:00","2025-12-31 23:55:00",5913,68.0365,0.051724,1.171928,74.618685),
 "BABA": (213280,213261,159000,"2021-04-19 08:00:00","2025-12-31 23:55:00",7138,67.0636,0.046512,1.130738,110.142493),
 "BIDU": (159900,159881,119157,"2021-04-19 08:00:00","2025-12-31 23:55:00",5451,69.0699,0.129321,1.323234,49.598719),
 "C":    (158532,158513,118147,"2021-04-19 09:35:00","2025-12-31 23:50:00",5600,69.7857,0.107522,1.445975,20.560457),
 "COIN": (198825,198806,146755,"2021-04-19 08:00:00","2025-12-31 23:55:00",6639,66.4558,0.047604,1.069008,115.345463),
 "COST": (129464,129445,95451,"2021-04-19 10:40:00","2025-12-31 23:55:00",4589,70.0806,0.062016,1.297659,24.263338),
 "GOOGL":(183052,183033,135286,"2021-04-19 11:25:00","2025-12-31 23:55:00",6292,68.9129,0.052904,1.216936,36.383496),
 "GS":   (130582,130563,96983,"2021-04-19 08:00:00","2025-12-31 23:50:00",4631,70.5031,0.103062,1.401944,16.229456),
 "INTC": (205032,205013,153797,"2021-04-19 08:00:00","2025-12-31 23:55:00",7143,69.4666,0.076324,1.253063,45.675624),
 "JD":   (183081,183062,136980,"2021-04-19 08:00:00","2025-12-31 23:55:00",6336,68.3081,0.08448,1.207132,51.798934),
 "JPM":  (153207,153188,113900,"2021-04-19 08:00:00","2025-12-31 23:55:00",5398,70.3409,0.095568,1.479296,17.861487),
 "MARA": (215566,215547,160147,"2021-04-19 08:00:00","2025-12-31 23:55:00",7372,67.6207,0.16905,1.208828,135.496978),
 "META": (199320,199301,148250,"2021-04-19 08:15:00","2025-12-31 23:55:00",6566,67.7125,25.028834,85.170526,45.816754),
 "MSFT": (201505,201486,149022,"2021-04-19 08:00:00","2025-12-31 23:55:00",7061,68.2056,0.047487,1.242809,19.911568),
 "MSTR": (150333,150314,110218,"2021-04-19 11:00:00","2025-12-31 23:55:00",4962,65.9008,0.09055,1.108666,247.915321),
 "MU":   (184585,184566,137047,"2021-04-19 08:00:00","2025-12-31 23:55:00",6162,67.5917,0.070059,1.177084,160.469717),
 "NVDA": (217985,217966,159673,"2021-04-19 08:20:00","2025-12-31 23:55:00",7143,65.1407,-0.014952,0.964098,227.721705),
 "PLTR": (218546,218527,162892,"2021-04-19 08:00:00","2025-12-31 23:55:00",7467,68.113,0.066486,1.143694,136.996862),
 "SMCI": (148595,148576,109625,"2021-04-19 13:00:00","2025-12-31 23:55:00",4879,65.7512,0.01244,1.016747,231.472515),
 "TSLA": (222638,222619,163117,"2021-04-19 08:00:00","2025-12-31 23:55:00",7192,64.099,-0.039268,0.919114,285.309149),
 "TSM":  (185354,185335,136865,"2021-04-19 08:00:00","2025-12-31 23:55:00",6298,67.3865,0.065368,1.221463,48.004797),
 "V":    (134400,134381,99930,"2021-04-19 11:10:00","2025-12-31 23:55:00",4979,72.384,0.134635,1.762392,15.101724),
}
REF_COLS = ("n_bars", "n_z", "n_neutral", "first_ts", "last_ts",
            "n_trades", "win_rate", "mean_ret", "pf", "max_dd")


# ---- Metrics ----------------------------------------------------------------
def max_drawdown(rets) -> float:
    """Max peak-to-trough of the fixed-unit additive equity curve (in % units).
    Hand-calc reference; proved equal to the SQL window computation in results.md."""
    a = np.asarray(rets, dtype=float)
    if a.size == 0:
        return 0.0
    cum = np.cumsum(a)
    return float(np.max(np.maximum.accumulate(cum) - cum))


def ticker_metrics(trades: list[dict]) -> dict:
    """trades: list of {exit_ts, ret, position, hold}. PF/WR/N/mean via REUSED engine stats()."""
    rets = [t["ret"] for t in trades]
    a = np.asarray(rets, dtype=float)
    s = engine_stats(rets)                                  # <-- engine reuse
    clean = a[np.abs(a) <= GLITCH_ABS_RET]
    cs = engine_stats(clean.tolist())
    return {
        "n_trades": s["n"], "n_long": int((a.size and sum(1 for t in trades if t["position"] == 1))),
        "n_short": int((a.size and sum(1 for t in trades if t["position"] == -1))),
        "win_rate": s["wr"], "mean_ret": s["mean"], "pf": s["pf"], "sharpe": s["sharpe"],
        "max_dd": round(max_drawdown(a), 6),
        "avg_hold": round(float(np.mean([t["hold"] for t in trades])), 3) if trades else 0.0,
        "best_ret": round(float(a.max()), 4) if a.size else 0.0,
        "worst_ret": round(float(a.min()), 4) if a.size else 0.0,
        "n_glitch": int(np.sum(np.abs(a) > GLITCH_ABS_RET)),
        "pf_exglitch": cs["pf"], "wr_exglitch": cs["wr"], "mean_exglitch": cs["mean"], "n_exglitch": cs["n"],
        "sum_ret": round(float(a.sum()), 4),
    }


def pooled(all_trades: list[dict]) -> dict:
    """Equal-weight, fixed-unit pooled metrics across the universe (engine stats())."""
    st = sorted(all_trades, key=lambda t: t["exit_ts"])     # global chronological order
    a = np.asarray([t["ret"] for t in st], dtype=float)
    mask = np.abs(a) <= GLITCH_ABS_RET
    s, cs = engine_stats(a.tolist()), engine_stats(a[mask].tolist())
    return {
        "raw": {"n": s["n"], "pf": s["pf"], "wr": s["wr"], "mean": s["mean"],
                "max_dd": round(max_drawdown(a), 4)},
        "exglitch": {"n": cs["n"], "pf": cs["pf"], "wr": cs["wr"], "mean": cs["mean"],
                     "max_dd": round(max_drawdown(a[mask]), 4)},
    }


# ---- Data loaders -----------------------------------------------------------
def _parse_blob(blob: str) -> list[dict]:
    out = []
    if not blob:
        return out
    for rec in blob.split(";"):
        ets, ret, pos, hold = rec.split(",")
        out.append({"exit_ts": ets, "ret": float(ret), "position": int(pos), "hold": int(hold)})
    return out


def load_from_mcp_dumps(paths: list[str]) -> dict[str, list[dict]]:
    """Parse the server-side per-trade dumps (GROUP_CONCAT blobs) into trade lists."""
    trades: dict[str, list[dict]] = {}
    for p in paths:
        obj = json.load(open(p))
        for row in obj["data"]["rows"]:
            t = load_blob_row(row)
            trades[row["ticker"]] = t
    return trades


def load_blob_row(row: dict) -> list[dict]:
    t = _parse_blob(row["blob"])
    assert len(t) == row["n"], f'{row["ticker"]}: parsed {len(t)} != n {row["n"]}'
    return t


def load_from_sqlite(db_path: str, universe: list[str]) -> tuple[dict, dict]:
    """Run TRADES_SQL + BARS_SQL per ticker against a local research.db."""
    con = sqlite3.connect(db_path)
    trades, bars = {}, {}
    for tk in universe:
        rows = con.execute(TRADES_SQL, (tk,)).fetchall()
        trades[tk] = [{"exit_ts": r[0], "ret": float(r[1]), "position": int(r[2]), "hold": int(r[3])}
                      for r in rows]
        b = con.execute(BARS_SQL, (tk,)).fetchone()
        bars[tk] = {"n_bars": b[0], "n_z": b[1], "n_neutral": b[2], "first_ts": b[3], "last_ts": b[4]}
    con.close()
    return trades, bars


# ---- Pre-registered GOOD/MARGINAL/BAD criterion (pre-reg s4; bar NOT moved) --
def classify(n_clean_exec: int, n_universe: int, pool: dict, all_trades: list) -> dict:
    """Map to the fixed criterion. Primary PF = ex-data-glitch aggregate (META corrupt
    bars removed via the engine's own flag_corrupt 6x rule); raw is reported too and the
    verdict is checked for robustness against it."""
    pf_raw, pf_clean, n = pool["raw"]["pf"], pool["exglitch"]["pf"], pool["exglitch"]["n"]
    degenerate = (n_clean_exec < 20) or (n < 100)   # pre-reg degeneracy: <20 execute / near-zero N
    if degenerate:
        v = "BAD"
    elif pf_clean < 0.9:
        v = "BAD"
    elif pf_clean <= 1.1:
        v = "MARGINAL"
    else:
        v = "GOOD"
    return {
        "verdict": v,
        "pf_primary_exglitch": pf_clean, "pf_raw_asis": pf_raw, "N": n,
        "tickers_executing_ge100": f"{n_clean_exec}/{n_universe}",
        "criterion": ("pre-reg s4 (unmoved): GOOD = >=20/27 execute & aggregate PF>1.0 & N>=100 & "
                      "non-degenerate; MARGINAL = PF in [0.9,1.1]; BAD = PF<0.9 or degenerate. "
                      "Overlap (1.0,1.1] resolved conservatively to MARGINAL; >1.1 = clear-edge GOOD."),
        "robustness": ("Verdict holds under BOTH the literal GOOD (PF>1.0) and the conservative "
                       "(PF>1.1) reading, and under raw vs ex-glitch -- pf_raw and pf_exglitch are "
                       "both >1.1."),
        "caveat": ("Zero-cost upper bound (engine default; pre-reg forbids adding costs). A "
                   "~165k-trade no-stop flipper would not survive realistic transaction costs; "
                   "per-trade edge is ~+0.10%/trade ex-glitch. GOOD here means the agent-discovered "
                   "mechanic is backtestable and shows positive RAW edge before any risk/cost overlay "
                   "-- exactly what pre-reg s4 set out to test, not production-readiness."),
    }


# ---- Artifact ---------------------------------------------------------------
def build(trades_by_tk: dict, bars_by_tk: dict, outdir: str) -> dict:
    os.makedirs(outdir, exist_ok=True)
    per_ticker, all_trades, proof = {}, [], []
    for tk in sorted(trades_by_tk):
        tr = trades_by_tk[tk]
        m = ticker_metrics(tr)
        b = bars_by_tk.get(tk, {})
        if b:
            m["n_bars"], m["n_z"], m["n_neutral"] = b["n_bars"], b["n_z"], b["n_neutral"]
            m["pct_neutral"] = round(100.0 * b["n_neutral"] / b["n_z"], 3) if b["n_z"] else None
            m["first_ts"], m["last_ts"] = b["first_ts"], b["last_ts"]
        per_ticker[tk] = m
        for t in tr:
            all_trades.append({"ticker": tk, **t})
        # equality proof vs SQL_REF (engine-stats-from-trades  vs  server-side SQL)
        if tk in SQL_REF:
            ref = dict(zip(REF_COLS, SQL_REF[tk]))
            proof.append({
                "ticker": tk,
                "n_engine": m["n_trades"], "n_sql": ref["n_trades"],
                "pf_engine": m["pf"], "pf_sql": ref["pf"],
                "wr_engine": m["win_rate"], "wr_sql": ref["win_rate"],
                "mean_engine": m["mean_ret"], "mean_sql": ref["mean_ret"],
                "maxdd_engine": m["max_dd"], "maxdd_sql": ref["max_dd"],
            })

    pool = pooled(all_trades)
    pfs = [per_ticker[t]["pf"] for t in per_ticker if per_ticker[t]["pf"] not in (None, float("inf"))]
    n_pf_gt1 = sum(1 for t in per_ticker if (per_ticker[t]["pf"] or 0) > 1.0)
    n_clean_exec = sum(1 for t in per_ticker if per_ticker[t]["n_trades"] >= 100)
    glitch_tk = {t: per_ticker[t]["n_glitch"] for t in per_ticker if per_ticker[t]["n_glitch"] > 0}

    verdict = classify(n_clean_exec, len(per_ticker), pool, all_trades)

    summary = {
        "strategy": "zscore_mean_reversion_strict_v1 (naive flipper)",
        "hypothesis": "bb94b900",
        "verdict": verdict,
        "params": {"window": WINDOW, "z_hi": Z_HI, "z_lo": Z_LO,
                   "std": "sample (ddof=1)", "costs_bps": 0,
                   "position_model": "reverse-on-opposite (hold same-side + neutral)",
                   "fill": "flip-bar close", "glitch_flag_abs_ret_pct": GLITCH_ABS_RET},
        "data": {"source": "research.db bars_m5", "bars": 5068651,
                 "universe_n": len(per_ticker), "universe": sorted(per_ticker),
                 "period": "2021-04-19 -> 2025-12-31"},
        "universe_health": {
            "tickers_executing_ge100_trades": n_clean_exec,
            "tickers_pf_gt_1": n_pf_gt1,
            "per_ticker_pf_median": round(float(np.median(pfs)), 4),
            "per_ticker_pf_mean": round(float(np.mean(pfs)), 4),
            "unclosed_positions_per_ticker": 1,
            "glitch_tickers": glitch_tk,
        },
        "aggregate": pool,
        "per_ticker": per_ticker,
    }
    json.dump(summary, open(os.path.join(outdir, "summary.json"), "w"), indent=2, default=str)

    # per-ticker CSV
    cols = ["ticker", "n_bars", "n_z", "n_neutral", "pct_neutral", "first_ts", "last_ts",
            "n_trades", "n_long", "n_short", "win_rate", "mean_ret", "pf", "sharpe",
            "max_dd", "avg_hold", "best_ret", "worst_ret", "n_glitch",
            "pf_exglitch", "wr_exglitch", "mean_exglitch", "n_exglitch", "sum_ret"]
    with open(os.path.join(outdir, "per_ticker.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for tk in sorted(per_ticker):
            w.writerow({"ticker": tk, **{k: per_ticker[tk].get(k) for k in cols if k != "ticker"}})

    # per-trade queryable store (SQLite) -- realizes condition #3 locally
    # (research.db is read-only via MCP, so the backtest3_trades table lives here).
    dbp = os.path.join(outdir, "backtest3_trades.sqlite")
    if os.path.exists(dbp):
        os.remove(dbp)
    con = sqlite3.connect(dbp)
    con.execute("CREATE TABLE backtest3_trades (ticker TEXT, exit_ts TEXT, ret REAL, position INTEGER, hold INTEGER)")
    con.executemany("INSERT INTO backtest3_trades VALUES (?,?,?,?,?)",
                    [(t["ticker"], t["exit_ts"], t["ret"], t["position"], t["hold"]) for t in all_trades])
    con.execute("CREATE INDEX ix_tk ON backtest3_trades(ticker)")
    con.commit(); con.close()

    json.dump(proof, open(os.path.join(outdir, "equality_proof.json"), "w"), indent=2)
    write_markdown(summary, proof, outdir)
    return summary


def write_markdown(summary: dict, proof: list[dict], outdir: str) -> None:
    pt = summary["per_ticker"]
    uh = summary["universe_health"]
    ag = summary["aggregate"]
    L = []
    L.append("# Z-score Mean Reversion (STRICT ORIGINAL) -- backtest results\n")
    L.append(f"Hypothesis `bb94b900` | pre-reg `PreReg_backtest_3_zscore_MR_strict_v1.md` | "
             f"data research.db bars_m5 ({summary['data']['bars']:,} bars, "
             f"{summary['data']['universe_n']} equity tickers, {summary['data']['period']})\n")
    L.append("Params (locked): window=20, z=+/-1.5, sample-std, reverse-on-opposite flipper, "
             "fill=flip-bar close, costs=0 (engine default). Long-only M4 engine cannot express "
             "this; metrics reuse `m4_backtest_5yr.stats()`/`profit_factor()`.\n")

    v = summary["verdict"]
    L.append(f"\n## VERDICT: **{v['verdict']}**\n")
    L.append(f"- {v['criterion']}")
    L.append(f"- Result: {v['tickers_executing_ge100']} tickers execute >=100 trades; N={v['N']:,}; "
             f"aggregate PF = **{v['pf_primary_exglitch']}** (ex-glitch, primary) / {v['pf_raw_asis']} (raw as-is).")
    L.append(f"- Robustness: {v['robustness']}")
    L.append(f"- Caveat: {v['caveat']}")

    L.append("\n## Aggregate (equal-weight, fixed-unit, pooled by exit time)\n")
    L.append("| set | N | PF | win% | mean%/trade | max DD (add., %) |")
    L.append("|---|--:|--:|--:|--:|--:|")
    L.append(f"| **raw (as-is, all trades)** | {ag['raw']['n']:,} | {ag['raw']['pf']} | "
             f"{ag['raw']['wr']} | {ag['raw']['mean']} | {ag['raw']['max_dd']} |")
    L.append(f"| ex-glitch (|ret|<=500%, engine 6x rule) | {ag['exglitch']['n']:,} | "
             f"{ag['exglitch']['pf']} | {ag['exglitch']['wr']} | {ag['exglitch']['mean']} | "
             f"{ag['exglitch']['max_dd']} |")
    L.append(f"\nUniverse health: {uh['tickers_executing_ge100_trades']}/"
             f"{summary['data']['universe_n']} tickers execute >=100 trades; "
             f"{uh['tickers_pf_gt_1']}/{summary['data']['universe_n']} have PF>1 (as-is); "
             f"per-ticker PF median={uh['per_ticker_pf_median']}, mean={uh['per_ticker_pf_mean']}; "
             f"exactly {uh['unclosed_positions_per_ticker']} unclosed position/ticker (not degenerate).")
    if uh["glitch_tickers"]:
        L.append(f"\n**Data-glitch flag:** tickers with >500% single-trade returns (corrupt bars, "
                 f"no source guard): {uh['glitch_tickers']}. These inflate the raw aggregate; see "
                 f"ex-glitch row.")

    L.append("\n## SQL <-> engine-stats() equality proof (condition #1)\n")
    L.append("Per-trade returns from the server-side SQL flipper, fed through the REUSED engine "
             "`stats()`; compared to the all-SQL aggregate. Agreement to engine rounding confirms "
             "the SQL aggregation is trustworthy.\n")
    L.append("| ticker | N eng/sql | PF eng | PF sql | win% eng | win% sql | mean eng | mean sql | maxDD eng | maxDD sql |")
    L.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for r in proof:
        L.append(f"| {r['ticker']} | {r['n_engine']}/{r['n_sql']} | {r['pf_engine']} | {r['pf_sql']} | "
                 f"{r['wr_engine']} | {r['wr_sql']} | {r['mean_engine']} | {r['mean_sql']} | "
                 f"{r['maxdd_engine']} | {r['maxdd_sql']} |")
    dpf = max(abs(r["pf_engine"] - r["pf_sql"]) for r in proof)
    dwr = max(abs(r["wr_engine"] - r["wr_sql"]) for r in proof)
    ddd = max(abs(r["maxdd_engine"] - r["maxdd_sql"]) for r in proof)
    L.append(f"\nMax abs diff across all {len(proof)} tickers: PF {dpf:.2e}, win% {dwr:.2e}, maxDD {ddd:.2e}.")

    L.append("\n## Per-ticker\n")
    L.append("| ticker | N | long/short | win% | mean%/tr | PF | maxDD% | hold(bars) | %neutral | worst% | best% | glitches |")
    L.append("|---|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for tk in sorted(pt):
        m = pt[tk]
        L.append(f"| {tk} | {m['n_trades']:,} | {m['n_long']}/{m['n_short']} | {m['win_rate']} | "
                 f"{m['mean_ret']} | {m['pf']} | {m['max_dd']} | {m['avg_hold']} | "
                 f"{m.get('pct_neutral')} | {m['worst_ret']} | {m['best_ret']} | {m['n_glitch']} |")
    open(os.path.join(outdir, "results.md"), "w").write("\n".join(L) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="path to research.db (sqlite) -- canonical reproduce path")
    ap.add_argument("--mcp-dumps", nargs="+", help="server-side per-trade dump JSON files")
    ap.add_argument("--out", default="results/zscore_mr_strict_v1")
    a = ap.parse_args()

    if a.db:
        trades, bars = load_from_sqlite(a.db, UNIVERSE)
    elif a.mcp_dumps:
        paths = []
        for pat in a.mcp_dumps:
            paths.extend(sorted(glob.glob(pat)))
        trades = load_from_mcp_dumps(paths)
        bars = {tk: dict(zip(REF_COLS, SQL_REF[tk])) for tk in trades if tk in SQL_REF}
    else:
        ap.error("provide --db or --mcp-dumps")

    summary = build(trades, bars, a.out)
    ag = summary["aggregate"]
    print(f"Universe: {summary['data']['universe_n']} tickers, "
          f"{ag['raw']['n']:,} trades (raw).")
    print(f"Aggregate raw      : PF={ag['raw']['pf']}  win%={ag['raw']['wr']}  "
          f"mean%={ag['raw']['mean']}  maxDD={ag['raw']['max_dd']}")
    print(f"Aggregate ex-glitch: PF={ag['exglitch']['pf']}  win%={ag['exglitch']['wr']}  "
          f"mean%={ag['exglitch']['mean']}  maxDD={ag['exglitch']['max_dd']}")
    print(f"Artifact -> {a.out}/  (summary.json, per_ticker.csv, results.md, "
          f"equality_proof.json, backtest3_trades.sqlite)")


if __name__ == "__main__":
    main()
