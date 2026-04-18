#!/usr/bin/env python3
"""Phase 1 OOS Event Study: compression_score → Z4 forward return (2025 data).

Zone_Compression_Module_Spec_v1_1.md §7.2.  No VPS, no DB, pure local.

Compression score formula (Zone_Guide_v2_1_IST.md §2.5):
  Z3 = slots 30-47  (12:00-13:25 ET, 18 M5 bars)
  today_Z3_range       = (max(Z3 highs) - min(Z3 lows)) / Z3 open
  today_Z3_avg_abs_ret = mean(|M5 close - M5 open| / M5 open) across 18 Z3 bars
  activity_raw         = sqrt(today_Z3_range * today_Z3_avg_abs_ret)
  compression_score    = percentile_rank(activity_raw within historical_Z3_activity_raw)

Z3 slot range : slots 30-47 (12:00-13:25 ET, 18 bars).  Z3 open = bar at slot 30.
Z4 start      : slot 48 (13:30 ET) — signal reference bar for M8 forward returns.
"""

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

_BASE = Path(__file__).resolve().parent.parent
for _p in (str(_BASE), str(_BASE / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.backtest_utils_extended import is_earnings_window, load_earnings  # noqa: E402

# ── Constants ──────────────────────────────────────────────────────────────────

EXPECTED_BASELINE_SHA = "661975f5e7e5f061c0fd0221c2b9976a4a0e395affa410a34ee0f12796ae3024"

# FOMC announcement days (Fed 8-meeting calendar 2025)
# CPI release days (BLS schedule 2025)
# NFP Employment Situation release days (BLS 2025)
# Note: Beige Book (8×/year, mid-cycle) omitted — dates not bundled locally.
HIGH_IMPACT_DAYS_2025 = frozenset({
    date(2025, 1, 29), date(2025, 3, 19), date(2025, 5, 7),   # FOMC
    date(2025, 6, 18), date(2025, 7, 30), date(2025, 9, 17),
    date(2025, 10, 29), date(2025, 12, 10),
    date(2025, 1, 15), date(2025, 2, 12), date(2025, 3, 12),   # CPI
    date(2025, 4, 10), date(2025, 5, 13), date(2025, 6, 11),
    date(2025, 7, 15), date(2025, 8, 12), date(2025, 9, 11),
    date(2025, 10, 15), date(2025, 11, 13), date(2025, 12, 10),
    date(2025, 1, 10), date(2025, 2, 7), date(2025, 3, 7),    # NFP (BLS schedule)
    date(2025, 4, 4), date(2025, 5, 2), date(2025, 6, 6),
    date(2025, 7, 3), date(2025, 8, 1), date(2025, 9, 5),     # TODO: verify Jul 3 pre-holiday
    date(2025, 10, 3), date(2025, 11, 7), date(2025, 12, 5),
})

Z3_SLOTS = frozenset(range(30, 48))    # 12:00–13:25 ET (18 bars)
Z4_SLOT  = 48                           # 13:30 ET — signal reference bar
FWD_SLOTS = frozenset(range(49, 57))   # 13:35–14:10 ET (8 bars forward)

_DATA_DIRS = [_BASE / "data", _BASE / "Fetched_Data"]

BUCKET_NAMES = ("deep", "neutral", "active")
EX_VERSIONS  = ("full", "earnings_excluded", "earnings_and_hi_day_excluded")


# ── Data loading ───────────────────────────────────────────────────────────────

def _load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    if "datetime" in df.columns:
        df = df.rename(columns={"datetime": "date"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    df["date_only"] = df["date"].dt.date
    df["hour"]    = df["date"].dt.hour
    df["minute"]  = df["date"].dt.minute
    df["slot_id"] = ((df["hour"] - 9) * 60 + df["minute"] - 30) // 5
    return df


def _find_and_load(ticker: str, data_dirs=None) -> pd.DataFrame | None:
    for d in (data_dirs or _DATA_DIRS):
        p = Path(d) / f"{ticker}_data.csv"
        if p.exists():
            return _load_csv(p)
    return None


def _rth_2025(df: pd.DataFrame) -> pd.DataFrame:
    mask = (
        ((df["hour"] == 9) & (df["minute"] >= 30))
        | ((df["hour"] >= 10) & (df["hour"] < 16))
    )
    return df[mask & (df["date"].dt.year == 2025)].reset_index(drop=True)


# ── Core formula (R4) ──────────────────────────────────────────────────────────

def compression_score_from_baseline(
    baseline: dict, ticker: str, activity_raw: float
) -> float:
    """Percentile rank of activity_raw within historical Z3 distribution."""
    arr = (
        baseline.get("per_zone_distributions", {})
        .get(ticker, {})
        .get("Z3", {})
        .get("sorted_values", [])
    )
    n = len(arr)
    if n < 100:
        return 0.5  # insufficient sample, abstain
    rank = int(np.searchsorted(np.array(arr, dtype=float), activity_raw, side="right"))
    return float(min(1.0, max(0.0, rank / n)))


def _bucket_name(cs: float) -> str:
    if cs <= 0.30:
        return "deep"
    if cs >= 0.70:
        return "active"
    return "neutral"


# ── Session processing (R3-R6) ─────────────────────────────────────────────────

def _process_session(
    day_df: pd.DataFrame,
    spy_day_df: pd.DataFrame | None,
    baseline: dict,
    ticker: str,
) -> dict | None:
    """Compute per-session Z3/Z4 metrics.  Returns None if session must be skipped."""
    z3 = day_df[day_df["slot_id"].isin(Z3_SLOTS)]
    if len(z3) != 18:                          # R3: require exactly 18 Z3 bars
        return None
    z3 = z3.sort_values("date")
    z3_open = float(z3.iloc[0]["open"])
    if z3_open <= 0:
        return None

    z3_range    = (float(z3["high"].max()) - float(z3["low"].min())) / z3_open
    z3_avg_abs  = float(((z3["close"] - z3["open"]).abs() / z3_open).mean())
    product     = z3_range * z3_avg_abs
    if product < 0:
        return None
    activity_raw = float(product ** 0.5)
    cs     = compression_score_from_baseline(baseline, ticker, activity_raw)  # R4
    z3_high = float(z3["high"].max())

    z4_bar = day_df[day_df["slot_id"] == Z4_SLOT]
    if len(z4_bar) != 1:                       # R5: require exactly 1 Z4 bar
        return None
    signal_ref = float(z4_bar.iloc[0]["open"])
    z4_close   = float(z4_bar.iloc[0]["close"])
    breakout   = bool(z4_close > z3_high)

    fwd = day_df[day_df["slot_id"].isin(FWD_SLOTS)].sort_values("date")
    if len(fwd) != 8:                          # R5: require all 8 forward bars
        return None
    last_close    = float(fwd.iloc[-1]["close"])
    eight_bar_ret = (last_close - signal_ref) / signal_ref * 100.0
    mfe = float(((fwd["high"] - signal_ref) / signal_ref * 100.0).max())
    mae = float(((fwd["low"]  - signal_ref) / signal_ref * 100.0).min())

    spy_adj = None
    if spy_day_df is not None:                 # R6: SPY adjustment
        spy_z4  = spy_day_df[spy_day_df["slot_id"] == Z4_SLOT]
        spy_fwd = spy_day_df[spy_day_df["slot_id"].isin(FWD_SLOTS)].sort_values("date")
        if len(spy_z4) == 1 and len(spy_fwd) == 8:
            spy_ref  = float(spy_z4.iloc[0]["open"])
            spy_last = float(spy_fwd.iloc[-1]["close"])
            spy_ret  = (spy_last - spy_ref) / spy_ref * 100.0
            spy_adj  = eight_bar_ret - spy_ret

    return {
        "compression_score": cs,
        "activity_raw":      activity_raw,
        "z3_high":           z3_high,
        "signal_ref":        signal_ref,
        "breakout":          breakout,
        "eight_bar_ret":     eight_bar_ret,
        "mfe":               mfe,
        "mae":               mae,
        "spy_adj_ret":       spy_adj,
    }


# ── Bucketing + metrics (R8) ───────────────────────────────────────────────────

def _metrics(sessions: list) -> dict:
    if not sessions:
        return {k: None for k in (
            "N", "breakout_rate", "mean_return_8bar",
            "mean_spy_adj_return_8bar", "mfe_p50", "mfe_p90", "mae_p50", "mae_p90",
        )}
    n    = len(sessions)
    rets = np.array([s["eight_bar_ret"] for s in sessions], dtype=float)
    mfes = np.array([s["mfe"] for s in sessions], dtype=float)
    maes = np.array([s["mae"] for s in sessions], dtype=float)
    spy_rets = [s["spy_adj_ret"] for s in sessions if s["spy_adj_ret"] is not None]
    return {
        "N":                       n,
        "breakout_rate":           float(sum(s["breakout"] for s in sessions) / n),
        "mean_return_8bar":        float(np.mean(rets)),
        "mean_spy_adj_return_8bar": float(np.mean(spy_rets)) if spy_rets else None,
        "mfe_p50": float(np.percentile(mfes, 50)),
        "mfe_p90": float(np.percentile(mfes, 90)),
        "mae_p50": float(np.percentile(maes, 50)),
        "mae_p90": float(np.percentile(maes, 90)),
    }


def _compute_buckets(all_sessions: list, earnings_dict: dict) -> dict:
    raw: dict = {b: {v: [] for v in EX_VERSIONS} for b in BUCKET_NAMES}
    for s in all_sessions:
        b          = _bucket_name(s["compression_score"])
        in_earn    = is_earnings_window(s["ticker"], s["session_date"], earnings_dict)
        in_hi      = s["session_date"] in HIGH_IMPACT_DAYS_2025
        raw[b]["full"].append(s)
        if not in_earn:
            raw[b]["earnings_excluded"].append(s)
            if not in_hi:
                raw[b]["earnings_and_hi_day_excluded"].append(s)
    return {b: {v: _metrics(raw[b][v]) for v in EX_VERSIONS} for b in BUCKET_NAMES}


# ── Kill-switch (R9) ───────────────────────────────────────────────────────────

def _kill_switch(buckets: dict) -> tuple:
    deep    = buckets["deep"]["earnings_excluded"]
    neutral = buckets["neutral"]["earnings_excluded"]
    ks = {
        "deep_breakout_gt_neutral_breakout": bool(
            deep["breakout_rate"] is not None
            and neutral["breakout_rate"] is not None
            and deep["breakout_rate"] > neutral["breakout_rate"]
        ),
        "deep_spy_adj_return_gt_neutral_spy_adj": bool(
            deep["mean_spy_adj_return_8bar"] is not None
            and neutral["mean_spy_adj_return_8bar"] is not None
            and deep["mean_spy_adj_return_8bar"] > neutral["mean_spy_adj_return_8bar"]
        ),
        "deep_n_gte_40": bool(deep["N"] is not None and deep["N"] >= 40),
        "deep_breakout_rate_gte_20pct": bool(
            deep["breakout_rate"] is not None and deep["breakout_rate"] >= 0.20
        ),
    }
    rec = (
        "PROCEED_TO_PHASE_2"
        if all(ks.values())
        else "SHELVE_M8_PHASE_B_GATE_MAY_STILL_PROCEED"
    )
    return ks, rec


# ── Report generation (R10) ────────────────────────────────────────────────────

def _write_report(results: dict, buckets: dict, ks: dict, rec: str,
                  per_ticker: dict, output_md: str) -> None:
    sha_match = results.get("baseline_sha256_match", False)
    sha_note  = "SHA match ✓" if sha_match else (
        "SHA mismatch — local fallback baseline (not canonical 2023-2024)"
    )
    deep_ee    = buckets["deep"]["earnings_excluded"]
    neutral_ee = buckets["neutral"]["earnings_excluded"]

    def _fp(x, fmt=".3f"):
        return f"{x:{fmt}}" if x is not None else "N/A"

    lines = [
        "# Phase 1 OOS Event Study — compression_score Validation (2025)",
        "",
        f"**Test window:** {results['test_window']}  ",
        f"**Computed:** {results['computed_at']}  ",
        f"**Baseline SHA:** {sha_note}  ",
        f"**Recommendation:** **{rec}**",
        "",
        "## Executive Summary",
        "",
        (
            f"{results['tickers_with_data']}/{results['tickers_analyzed']} tickers had 2025 data. "
            f"{results['total_valid_sessions']} valid sessions "
            f"({results['total_rejected_incomplete']} rejected as incomplete). "
            f"Deep-compression bucket (earnings-excluded): N={deep_ee['N']}, "
            f"breakout_rate={_fp(deep_ee['breakout_rate'] * 100 if deep_ee['breakout_rate'] is not None else None, '.1f')}% "
            f"vs neutral {_fp(neutral_ee['breakout_rate'] * 100 if neutral_ee['breakout_rate'] is not None else None, '.1f')}%. "
            f"Kill-switch verdict: **{rec}**."
        ),
        "",
        "## Bucket Results",
        "",
        "| Bucket | Version | N | Breakout% | MeanRet% | SPYAdj% | MFE p50 | MFE p90 | MAE p50 | MAE p90 |",
        "|--------|---------|---|-----------|----------|---------|---------|---------|---------|---------|",
    ]
    for b in BUCKET_NAMES:
        for v in EX_VERSIONS:
            m  = buckets[b][v]
            n  = m["N"] if m["N"] is not None else 0
            br = _fp(m["breakout_rate"] * 100 if m["breakout_rate"] is not None else None, ".1f")
            lines.append(
                f"| {b} | {v} | {n} | {br}% "
                f"| {_fp(m['mean_return_8bar'])} "
                f"| {_fp(m['mean_spy_adj_return_8bar'])} "
                f"| {_fp(m['mfe_p50'])} | {_fp(m['mfe_p90'])} "
                f"| {_fp(m['mae_p50'])} | {_fp(m['mae_p90'])} |"
            )
    lines += [
        "",
        "## Kill-Switch Verdict",
        "",
        "| Criterion | Result |",
        "|-----------|--------|",
    ]
    for k, v in ks.items():
        lines.append(f"| {k} | {'**PASS**' if v else 'FAIL'} |")
    lines += [
        "",
        f"**All-pass → {rec}**",
        "",
        "## Per-Ticker Session Counts",
        "",
        "| Ticker | Deep | Neutral | Active |",
        "|--------|------|---------|--------|",
    ]
    for t in sorted(per_ticker):
        c = per_ticker[t]
        lines.append(f"| {t} | {c['deep']} | {c['neutral']} | {c['active']} |")
    lines += [
        "",
        "## Limitations",
        "",
        (
            f"- **Baseline data:** The canonical 2023-2024 baseline (SHA "
            f"`{EXPECTED_BASELINE_SHA[:16]}…`) was not available in this environment. "
            "A local fallback was used, computed from pre-2025 Z3 sessions in Fetched_Data. "
            "Tickers with fewer than 100 pre-2025 Z3 sessions received abstain score 0.50 "
            "(neutral bucket). Obtain the canonical baseline from CC-BASELINE-1 for "
            "production-grade kill-switch decisions."
        ),
        "- **News-based filters:** Skipped — not in local repo. Sprint 2 backtest to include.",
        "- **Beige Book dates:** Not included in HIGH_IMPACT_DAYS_2025 (8×/year, mid-cycle).",
        (
            "- **SPY adjustment:** Computed when SPY data exists for same date; "
            "`mean_spy_adj_return_8bar` is None if SPY bars are missing."
        ),
        "- **Ticker coverage:** Tickers absent from local data/ or Fetched_Data/ are skipped.",
    ]
    Path(output_md).write_text("\n".join(lines) + "\n")


# ── Main pipeline ──────────────────────────────────────────────────────────────

def run(baseline_path: str, output_json: str, output_md: str,
        verbose: bool = False) -> dict:
    # R1: load baseline, record SHA (warn on mismatch, do not abort)
    raw        = Path(baseline_path).read_bytes()
    actual_sha = hashlib.sha256(raw).hexdigest()
    sha_match  = actual_sha == EXPECTED_BASELINE_SHA
    if not sha_match and verbose:
        print(
            f"WARNING: baseline SHA mismatch.\n"
            f"  actual:   {actual_sha}\n"
            f"  expected: {EXPECTED_BASELINE_SHA}\n"
            f"  (local fallback baseline — results not suitable for production)"
        )
    baseline = json.loads(raw)
    tickers  = baseline["tickers_accepted"]  # 27 tickers (ARM excluded)

    earnings_dict = load_earnings()

    # Load SPY once for SPY-adjusted return (R6)
    spy_raw  = _find_and_load("SPY")
    spy_2025 = _rth_2025(spy_raw) if spy_raw is not None else pd.DataFrame()
    spy_by_date: dict = {}
    if not spy_2025.empty:
        for d, grp in spy_2025.groupby("date_only"):
            spy_by_date[d] = grp.reset_index(drop=True)

    all_sessions: list  = []
    total_eligible: int = 0
    total_rejected: int = 0
    per_ticker: dict    = {}

    for ticker in tickers:
        df_raw = _find_and_load(ticker)
        if df_raw is None:
            if verbose:
                print(f"  SKIP {ticker}: no data file found")
            continue
        df = _rth_2025(df_raw)
        if df.empty:
            if verbose:
                print(f"  SKIP {ticker}: no 2025 RTH data")
            continue

        ticker_sessions: list = []
        for session_date, day_df in df.groupby("date_only"):
            total_eligible += 1
            spy_day = spy_by_date.get(session_date)
            sess    = _process_session(day_df, spy_day, baseline, ticker)
            if sess is None:
                total_rejected += 1
            else:
                sess["ticker"]       = ticker
                sess["session_date"] = session_date
                all_sessions.append(sess)
                ticker_sessions.append(sess)

        if verbose:
            print(f"  {ticker}: {len(ticker_sessions)} valid sessions")

        per_ticker[ticker] = {
            b: sum(1 for s in ticker_sessions if _bucket_name(s["compression_score"]) == b)
            for b in BUCKET_NAMES
        }

    buckets    = _compute_buckets(all_sessions, earnings_dict)
    ks, rec    = _kill_switch(buckets)

    results = {
        "test_window":              "2025-01-01 to 2025-12-31",
        "tickers_analyzed":         len(tickers),
        "tickers_with_data":        len(per_ticker),
        "baseline_sha256":          actual_sha,
        "baseline_sha256_expected": EXPECTED_BASELINE_SHA,
        "baseline_sha256_match":    sha_match,
        "total_eligible_sessions":  total_eligible,
        "total_rejected_incomplete": total_rejected,
        "total_valid_sessions":     len(all_sessions),
        "buckets":                  buckets,
        "kill_switch":              ks,
        "recommendation":           rec,
        "computed_at":              datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    with open(output_json, "w") as f:
        json.dump(results, f, indent=2, default=str)
    _write_report(results, buckets, ks, rec, per_ticker, output_md)

    if verbose:
        print(f"\nRecommendation : {rec}")
        print(f"Valid sessions : {len(all_sessions)}")
        for b in BUCKET_NAMES:
            n = buckets[b]["earnings_excluded"]["N"]
            print(f"  {b:7s}: N={n}")
        print(f"Written: {output_json}, {output_md}")

    return results


# ── CLI (R11) ──────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Phase 1 OOS event study (2025)")
    p.add_argument("--baseline",    default="baselines_2023_2024.json",
                   help="Path to baselines JSON (default: baselines_2023_2024.json)")
    p.add_argument("--output-json", default="phase1_results.json")
    p.add_argument("--output-md",   default="phase1_event_study_report.md")
    p.add_argument("--verbose",     action="store_true")
    args = p.parse_args(argv)

    if not Path(args.baseline).exists():
        print(
            f"ERROR: {args.baseline} not found.\n"
            "Run scripts/generate_baseline_local.py first, or supply CC-BASELINE-1 output."
        )
        return 1

    run(args.baseline, args.output_json, args.output_md, args.verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main())
