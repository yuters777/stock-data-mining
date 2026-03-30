#!/usr/bin/env python3
"""
Module 4 RSI Gate Optimization — Part 2 of 2.
Walk-Forward Validation + Robustness Curve + Final Recommendation.

Prerequisite: Part 1 must have produced results/rsi_gate_sweep.json.
Output: results/rsi_gate_walkforward.json + stdout tables.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

# ── Paths ────────────────────────────────────────────────────────────────
REPO = Path(__file__).resolve().parents[1]
INDICATORS_DIR = REPO / "data" / "indicators_4h"
VIX_PATH = REPO / "Fetched_Data" / "VIXCLS_FRED_real.csv"
RESULTS_DIR = REPO / "results"
PART1_PATH = RESULTS_DIR / "rsi_gate_sweep.json"

# ── Config ───────────────────────────────────────────────────────────────
STREAK_THRESHOLD = 3
VIX_GATE = 25
HARD_MAX_BARS = 10
WF_THRESHOLDS = [30, 33, 35, 36, 37, 38, 40, 45, None]

EQUITY_TICKERS = [
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN",
    "COST", "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU",
    "NVDA", "PLTR", "SNOW", "TSLA", "TSM", "TXN", "V",
]

# ── Indicator functions (copied from Part 1) ────────────────────────────
def compute_rsi_wilder(closes, period=14):
    n = len(closes)
    out = [None] * n
    if n < period + 1:
        return out
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    if avg_loss == 0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            out[i + 1] = 100.0
        else:
            out[i + 1] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


def compute_ema(closes, period=21):
    n = len(closes)
    out = [None] * n
    if n < period:
        return out
    out[period - 1] = float(np.mean(closes[:period]))
    k = 2.0 / (period + 1)
    for i in range(period, n):
        out[i] = closes[i] * k + out[i - 1] * (1 - k)
    return out


# ── Data loading ─────────────────────────────────────────────────────────
def load_vix_daily():
    df = pd.read_csv(VIX_PATH)
    vix = {}
    for _, row in df.iterrows():
        try:
            vix[str(row["observation_date"])] = float(row["VIXCLS"])
        except (ValueError, TypeError):
            continue
    return vix


def get_prior_vix(vix_daily, date_str):
    dt = pd.Timestamp(date_str)
    for offset in range(1, 6):
        prior = (dt - timedelta(days=offset)).strftime("%Y-%m-%d")
        if prior in vix_daily:
            return vix_daily[prior]
    return None


def load_4h_bars(ticker):
    path = INDICATORS_DIR / f"{ticker}_4h_indicators.csv"
    df = pd.read_csv(path, parse_dates=["timestamp"])
    bars = []
    for _, row in df.iterrows():
        bars.append({
            "timestamp": row["timestamp"],
            "date_str": row["timestamp"].strftime("%Y-%m-%d"),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        })
    closes = np.array([b["close"] for b in bars])
    rsi_vals = compute_rsi_wilder(closes, 14)
    ema_vals = compute_ema(closes, 21)
    for i, b in enumerate(bars):
        b["rsi"] = rsi_vals[i]
        b["ema21"] = ema_vals[i]
    return bars


# ── Streak + simulation (copied from Part 1) ────────────────────────────
def count_streak_v2(bars, idx):
    streak = 0
    for j in range(idx, 0, -1):
        if bars[j]["close"] < bars[j - 1]["close"]:
            streak += 1
        else:
            break
    return streak


def simulate_trades(bars, vix_daily, ticker, rsi_gate):
    """Simulate Module 4 trades (V2 streak only for Part 2)."""
    trades = []
    in_trade_until = -1
    for i in range(STREAK_THRESHOLD, len(bars)):
        if i <= in_trade_until:
            continue
        bar = bars[i]
        if bar["rsi"] is None or bar["ema21"] is None:
            continue
        if count_streak_v2(bars, i) < STREAK_THRESHOLD:
            continue
        if rsi_gate is not None and bar["rsi"] >= rsi_gate:
            continue
        vix_val = get_prior_vix(vix_daily, bar["date_str"])
        if vix_val is None or vix_val < VIX_GATE:
            continue
        if i + 1 >= len(bars):
            continue
        entry_price = bar["close"]
        exit_price, exit_reason, exit_idx = None, None, None
        for k in range(1, HARD_MAX_BARS + 1):
            j = i + k
            if j >= len(bars):
                exit_price = bars[j - 1]["close"]
                exit_reason = "data_end"
                exit_idx = j - 1
                break
            if bars[j]["ema21"] is not None and bars[j]["close"] >= bars[j]["ema21"]:
                exit_price = bars[j]["close"]
                exit_reason = "ema21_touch"
                exit_idx = j
                break
            if k == HARD_MAX_BARS:
                exit_price = bars[j]["close"]
                exit_reason = "hard_max"
                exit_idx = j
                break
        if exit_price is None:
            continue
        in_trade_until = exit_idx
        trades.append({
            "ticker": ticker,
            "trigger_time": str(bar["timestamp"]),
            "date_str": bar["date_str"],
            "rsi": bar["rsi"],
            "return_pct": (exit_price - entry_price) / entry_price * 100,
            "hold_bars": exit_idx - i,
            "exit_reason": exit_reason,
        })
    return trades


def calc_metrics(trades):
    if not trades:
        return {"n": 0, "mean_pct": None, "median_pct": None, "wr_pct": None,
                "profit_factor": None, "sharpe": None, "worst_pct": None, "p_value": None}
    rets = np.array([t["return_pct"] for t in trades])
    gains = rets[rets > 0]
    losses = rets[rets <= 0]
    pf = (gains.sum() / abs(losses.sum())) if len(losses) > 0 and losses.sum() != 0 else float("inf")
    std = rets.std(ddof=1) if len(rets) > 1 else 0
    sharpe = float(rets.mean() / std) if std > 0 else float("inf")
    _, p_val = stats.ttest_1samp(rets, 0) if len(rets) >= 2 else (None, None)
    return {
        "n": len(trades),
        "mean_pct": float(rets.mean()),
        "median_pct": float(np.median(rets)),
        "wr_pct": float((rets > 0).sum() / len(rets) * 100),
        "profit_factor": float(pf) if pf != float("inf") else 9999.99,
        "sharpe": float(sharpe) if sharpe != float("inf") else 9999.99,
        "worst_pct": float(rets.min()),
        "p_value": float(p_val) if p_val is not None else None,
    }


# ── Walk-forward: 60/40 split ───────────────────────────────────────────
def walk_forward_split(all_bars, vix_daily, rsi_gate):
    """60/40 chronological split across all tickers. Returns (train_m, test_m, degradation)."""
    # Collect all trading dates across all tickers
    all_dates = sorted({b["date_str"] for bars in all_bars.values() for b in bars})
    split_idx = int(len(all_dates) * 0.6)
    train_dates = set(all_dates[:split_idx])
    test_dates = set(all_dates[split_idx:])

    train_trades, test_trades = [], []
    for ticker, bars in all_bars.items():
        trades = simulate_trades(bars, vix_daily, ticker, rsi_gate)
        for t in trades:
            if t["date_str"] in train_dates:
                train_trades.append(t)
            elif t["date_str"] in test_dates:
                test_trades.append(t)

    train_m = calc_metrics(train_trades)
    test_m = calc_metrics(test_trades)

    if train_m["sharpe"] is not None and train_m["sharpe"] > 0 and train_m["sharpe"] < 9999:
        if test_m["sharpe"] is not None and test_m["sharpe"] < 9999:
            degradation = test_m["sharpe"] / train_m["sharpe"]
        else:
            degradation = None
    else:
        degradation = None

    return train_m, test_m, degradation, sorted(train_dates)[-1]


# ── N-sensitivity ────────────────────────────────────────────────────────
def n_sensitivity(trades, rsi_gate):
    rets = np.array([t["return_pct"] for t in trades])
    n = len(rets)
    if n < 2:
        return {"rsi_gate": rsi_gate, "n": n, "sufficient": False}
    mean = float(rets.mean())
    std = float(rets.std(ddof=1))
    ci_95 = 1.96 * std / np.sqrt(n)
    _, p_val = stats.ttest_1samp(rets, 0)
    return {
        "rsi_gate": rsi_gate, "n": n, "mean_pct": mean, "std_pct": std,
        "ci_95_lower": mean - ci_95, "ci_95_upper": mean + ci_95,
        "p_value": float(p_val), "sufficient_n": n >= 20, "significant": p_val < 0.01,
    }


# ── Robustness curve (ASCII) ────────────────────────────────────────────
def print_robustness_curve(sweep_results):
    print("\nROBUSTNESS CURVE: Sharpe vs RSI Gate (V2 streak)")
    print("=" * 62)

    valid = [(r["rsi_gate"], r["sharpe"]) for r in sweep_results
             if r["sharpe"] is not None and r["sharpe"] < 9999]
    if not valid:
        print("  No valid data.")
        return

    max_sharpe = max(s for _, s in valid)
    for gate, sharpe in valid:
        label = f"RSI<{gate}" if gate is not None else "no_gate"
        bar_len = int(40 * sharpe / max_sharpe) if max_sharpe > 0 else 0
        bar = "#" * bar_len
        marker = " *" if gate == 35 else ""
        print(f"  {label:>10} | {bar} {sharpe:.3f}{marker}")

    # Detect cliffs
    print()
    for i in range(1, len(valid)):
        prev_gate, prev_s = valid[i - 1]
        curr_gate, curr_s = valid[i]
        if prev_s > 0:
            change = (curr_s - prev_s) / prev_s
            if change < -0.10:
                print(f"  CLIFF: RSI<{prev_gate} -> RSI<{curr_gate} = {change:+.0%} Sharpe drop")


# ── Recommendation logic ────────────────────────────────────────────────
def make_recommendation(full_sweep, wf_results, nsens_results, marginal_stats):
    """Decision tree for RSI gate recommendation."""
    print("\n" + "=" * 62)
    print("FINAL RECOMMENDATION")
    print("=" * 62)

    # Baseline: RSI<35
    s35 = next((r for r in full_sweep if r["rsi_gate"] == 35), None)
    if s35 is None or s35["sharpe"] is None:
        print("ERROR: No RSI<35 baseline data.")
        return "NEEDS_DR", "No baseline"

    sharpe_35 = s35["sharpe"]
    print(f"\nBaseline RSI<35: Sharpe={sharpe_35:.3f}, N={s35['n']}")

    candidates = [36, 37, 38, 40]
    best_candidate = None
    evidence_lines = []

    for cand in candidates:
        print(f"\n--- Candidate RSI<{cand} ---")
        reasons = []

        # In-sample Sharpe
        sc = next((r for r in full_sweep if r["rsi_gate"] == cand), None)
        if sc is None or sc["sharpe"] is None:
            print(f"  No in-sample data for RSI<{cand}")
            continue
        sharpe_ratio = sc["sharpe"] / sharpe_35 if sharpe_35 > 0 else 0
        ok_sharpe = sharpe_ratio >= 0.80
        print(f"  In-sample Sharpe: {sc['sharpe']:.3f} ({sharpe_ratio:.0%} of baseline) {'PASS' if ok_sharpe else 'FAIL'}")
        if not ok_sharpe:
            reasons.append(f"Sharpe {sharpe_ratio:.0%} of baseline (<80%)")

        # Walk-forward degradation
        wf = wf_results.get(cand)
        if wf and wf["degradation"] is not None:
            ok_wf = wf["degradation"] > 0.5
            print(f"  WF degradation: {wf['degradation']:.2f} {'PASS' if ok_wf else 'FAIL'}")
            if not ok_wf:
                reasons.append(f"WF degradation {wf['degradation']:.2f} (<=0.5)")
        else:
            ok_wf = False
            reasons.append("WF degradation unavailable")
            print(f"  WF degradation: N/A FAIL")

        # Marginal trades
        marg = marginal_stats.get(cand, {})
        marg_mean = marg.get("mean_pct", 0)
        marg_n = marg.get("n", 0)
        ok_marg_mean = marg_mean > 0
        ok_marg_n = marg_n >= 10
        print(f"  Marginal N={marg_n} {'PASS' if ok_marg_n else 'FAIL'}, "
              f"mean={marg_mean:+.2f}% {'PASS' if ok_marg_mean else 'FAIL'}")
        if not ok_marg_mean:
            reasons.append(f"Marginal mean {marg_mean:+.2f}% (<=0)")
        if not ok_marg_n:
            reasons.append(f"Marginal N={marg_n} (<10)")

        # Overall p-value
        ns = next((r for r in nsens_results if r["rsi_gate"] == cand), None)
        ok_p = ns and ns.get("significant", False)
        if ns and "p_value" in ns:
            print(f"  p-value: {ns['p_value']:.4f} {'PASS' if ok_p else 'FAIL'}")
        if not ok_p:
            reasons.append("p >= 0.01")

        passes = ok_sharpe and ok_wf and ok_marg_mean and ok_marg_n and ok_p
        if passes:
            print(f"  => PASSES all criteria")
            if best_candidate is None:
                best_candidate = cand
        else:
            print(f"  => FAILS: {'; '.join(reasons)}")
        evidence_lines.append((cand, passes, reasons))

    # Verdict
    print("\n" + "=" * 62)
    if best_candidate:
        verdict = f"RAISE_{best_candidate}"
        summary = (f"RAISE to RSI < {best_candidate}. Passes all criteria: "
                   f"Sharpe retention >=80%, WF stable, marginal trades positive with N>=10, p<0.01. "
                   f"Requires external DR validation before engine parameter change (S44-FU2 principle).")
    else:
        # Check if 35 itself is stable
        wf35 = wf_results.get(35)
        if wf35 and wf35["degradation"] is not None and wf35["degradation"] > 0.5:
            verdict = "KEEP"
            summary = ("KEEP RSI < 35. No candidate threshold passes all criteria. "
                       "RSI<35 remains the optimal gate with stable walk-forward performance.")
        else:
            verdict = "NEEDS_DR"
            summary = ("NEEDS DR. Walk-forward data is too short (~13 months) for confident "
                       "validation. RSI<35 appears best in-sample but requires deeper data "
                       "for definitive walk-forward confirmation.")

    print(f"RECOMMENDATION: {verdict}")
    print(f"\n{summary}")

    return verdict, summary


# ── Main ─────────────────────────────────────────────────────────────────
def run():
    print("=" * 62)
    print("Module 4 RSI Gate Optimization — Part 2")
    print("Walk-Forward + Robustness + Recommendation")
    print("=" * 62)

    # Check Part 1
    if not PART1_PATH.exists():
        print(f"ERROR: Part 1 results not found at {PART1_PATH}")
        return
    with open(PART1_PATH) as f:
        part1 = json.load(f)
    print(f"\nPart 1 loaded: {part1['data_range']['start']} -> {part1['data_range']['end']}")

    # Load data
    vix_daily = load_vix_daily()
    all_bars = {}
    for ticker in EQUITY_TICKERS:
        path = INDICATORS_DIR / f"{ticker}_4h_indicators.csv"
        if path.exists():
            all_bars[ticker] = load_4h_bars(ticker)

    all_dates = sorted({b["date_str"] for bars in all_bars.values() for b in bars})
    data_span_days = (pd.Timestamp(all_dates[-1]) - pd.Timestamp(all_dates[0])).days
    data_span_years = data_span_days / 365.25
    print(f"Tickers: {len(all_bars)}, Dates: {all_dates[0]} -> {all_dates[-1]} ({data_span_years:.1f} years)")

    if data_span_years < 3:
        print(f"NOTE: Data span {data_span_years:.1f}y < 3y — rolling walk-forward SKIPPED, using 60/40 only.")

    # ── Phase 3: Walk-Forward 60/40 ──
    print(f"\n{'=' * 62}")
    print("Table 5: Walk-Forward Results (60/40 split, V2 streak)")
    print("=" * 62)

    header = (f"{'RSI Gate':>9} | {'Tr N':>5} | {'Tr Sharpe':>10} | {'Te N':>5} | "
              f"{'Te Sharpe':>10} | {'Degrad':>7} | {'Stable?':>7}")
    print(header)
    print("-" * len(header))

    wf_results = {}
    split_date = None
    for rsi_gate in WF_THRESHOLDS:
        train_m, test_m, deg, sd = walk_forward_split(all_bars, vix_daily, rsi_gate)
        if split_date is None:
            split_date = sd
        wf_results[rsi_gate] = {
            "train": train_m, "test": test_m, "degradation": deg,
        }

        gate_str = f"{rsi_gate}" if rsi_gate is not None else "no_gate"
        if rsi_gate == 35:
            gate_str += " *"

        def fmt_s(m):
            if m["sharpe"] is None:
                return "    —"
            return f"{m['sharpe']:>10.3f}" if m["sharpe"] < 9999 else "       inf"

        stable = "YES" if deg is not None and deg > 0.5 else ("NO" if deg is not None else "N/A")
        deg_str = f"{deg:.2f}" if deg is not None else "N/A"
        tn = train_m["n"]
        ten = test_m["n"]
        print(f"{gate_str:>9} | {tn:>5} | {fmt_s(train_m)} | {ten:>5} | "
              f"{fmt_s(test_m)} | {deg_str:>7} | {stable:>7}")

    print(f"\nSplit date: train <= {split_date}, test > {split_date}")

    # ── Phase 4: Robustness Curve ──
    # Use full-sample V2 sweep from Part 1
    print_robustness_curve(part1["v2_sweep"])

    # ── Phase 5: N-Sensitivity ──
    print(f"\n{'=' * 62}")
    print("Table 6: N-Sensitivity (V2 streak)")
    print("=" * 62)

    header2 = (f"{'RSI Gate':>9} | {'N':>5} | {'Mean %':>8} | {'95% CI':>20} | "
               f"{'p-value':>8} | {'N>=20':>5} | {'p<.01':>5}")
    print(header2)
    print("-" * len(header2))

    nsens_results = []
    for rsi_gate in WF_THRESHOLDS:
        all_trades = []
        for ticker, bars in all_bars.items():
            all_trades.extend(simulate_trades(bars, vix_daily, ticker, rsi_gate))
        ns = n_sensitivity(all_trades, rsi_gate)
        nsens_results.append(ns)

        gate_str = f"{rsi_gate}" if rsi_gate is not None else "no_gate"
        if rsi_gate == 35:
            gate_str += " *"
        if ns["n"] < 2:
            print(f"{gate_str:>9} | {ns['n']:>5} |      — |                  — |      — |   — |   —")
            continue
        ci_str = f"[{ns['ci_95_lower']:+.2f}, {ns['ci_95_upper']:+.2f}]"
        print(f"{gate_str:>9} | {ns['n']:>5} | {ns['mean_pct']:>+8.2f} | {ci_str:>20} | "
              f"{ns['p_value']:>8.4f} | {'YES' if ns['sufficient_n'] else 'NO':>5} | "
              f"{'YES' if ns['significant'] else 'NO':>5}")

    # ── Marginal stats for each candidate threshold vs 35 ──
    trades_35 = []
    for ticker, bars in all_bars.items():
        trades_35.extend(simulate_trades(bars, vix_daily, ticker, 35))
    core_keys = {(t["ticker"], t["trigger_time"]) for t in trades_35}

    marginal_stats = {}
    for cand in [36, 37, 38, 40]:
        cand_trades = []
        for ticker, bars in all_bars.items():
            cand_trades.extend(simulate_trades(bars, vix_daily, ticker, cand))
        marginal = [t for t in cand_trades if (t["ticker"], t["trigger_time"]) not in core_keys]
        m = calc_metrics(marginal)
        marginal_stats[cand] = {"n": m["n"], "mean_pct": m["mean_pct"] or 0}

    # ── Phase 6: Recommendation ──
    full_sweep = part1["v2_sweep"]
    verdict, summary = make_recommendation(full_sweep, wf_results, nsens_results, marginal_stats)

    # ── Save JSON ──
    RESULTS_DIR.mkdir(exist_ok=True)

    def safe_m(m):
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}

    def jsonify(obj):
        """Recursively convert numpy types for JSON serialization."""
        if isinstance(obj, dict):
            return {k: jsonify(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [jsonify(v) for v in obj]
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        return obj

    output = jsonify({
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "data_range": part1["data_range"],
        "data_span_years": round(data_span_years, 2),
        "walk_forward_60_40": {
            "split_date": split_date,
            "results": {
                str(k): {"train": safe_m(v["train"]), "test": safe_m(v["test"]),
                          "degradation": round(v["degradation"], 4) if v["degradation"] else None}
                for k, v in wf_results.items()
            },
        },
        "rolling_walk_forward": None,
        "rolling_walk_forward_note": f"Skipped: data span {data_span_years:.1f}y < 3y minimum",
        "n_sensitivity": [
            {k: (round(v, 4) if isinstance(v, float) else v) for k, v in ns.items()}
            for ns in nsens_results
        ],
        "robustness_pattern": _detect_pattern(full_sweep),
        "recommendation": verdict,
        "evidence_summary": summary,
    })

    out_path = RESULTS_DIR / "rsi_gate_walkforward.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved -> {out_path}")


def _detect_pattern(sweep):
    """Classify robustness curve as cliff, plateau, or monotonic."""
    sharpes = [(r["rsi_gate"], r["sharpe"]) for r in sweep
               if r["sharpe"] is not None and r["sharpe"] < 9999]
    if len(sharpes) < 3:
        return "insufficient_data"

    # Check for cliff (>30% drop between adjacent)
    for i in range(1, len(sharpes)):
        prev_s = sharpes[i - 1][1]
        curr_s = sharpes[i][1]
        if prev_s > 0 and (curr_s - prev_s) / prev_s < -0.30:
            return "cliff"

    # Check for plateau (<10% variation across 3+ consecutive)
    for i in range(len(sharpes) - 2):
        window = [s for _, s in sharpes[i:i + 3]]
        mean_w = np.mean(window)
        if mean_w > 0 and (max(window) - min(window)) / mean_w < 0.10:
            return "plateau"

    return "monotonic_decline"


if __name__ == "__main__":
    run()
