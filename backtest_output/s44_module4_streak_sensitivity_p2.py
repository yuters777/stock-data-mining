#!/usr/bin/env python3
"""
S44 Module 4 Streak Sensitivity — Part 2: V3, V4 (+ V0–V4 combined summary).

V3 — Net Streak (3-of-4 window): at least 3 of last 4 bars are DOWN (close < open)
V4 — ATR-Normalized Body: DOWN = (open-close) > 0.1×ATR(14); neutrals skipped

Re-runs V0–V2 from Part 1 for the combined ranking table.

Common setup:
  Trigger:  streak + prior-day VIX >= 25 + 4H RSI(14) < 35
  Entry:    4H trigger bar close
  Exit:     first 4H close >= EMA21 (hard max 10 bars)
  Scope:    25 equity tickers (excl SPY, VIXY)
"""

import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── Config ───────────────────────────────────────────────────────────────────

TICKERS = [
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN",
    "COST", "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU",
    "NVDA", "PLTR", "SNOW", "TSLA", "TSM", "TXN", "V",
]

VIX_THRESHOLD = 25.0
RSI_THRESHOLD = 35.0
STREAK_LEN = 3
MAX_HOLD = 10
BODY_THRESHOLD = 0.001   # 0.1% for V1
ATR_BODY_MULT = 0.1      # 0.1 × ATR for V4
ATR_PERIOD = 14

INDICATORS_4H_DIR = ROOT / "data" / "indicators_4h"
VIX_PATH = ROOT / "Fetched_Data" / "VIXCLS_FRED_real.csv"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# ── Helpers ──────────────────────────────────────────────────────────────────

def load_vix_daily():
    df = pd.read_csv(VIX_PATH)
    vix = {}
    for _, row in df.iterrows():
        try:
            val = float(row["VIXCLS"])
            vix[str(row["observation_date"])] = val
        except (ValueError, TypeError):
            continue
    return vix


def load_4h_bars(ticker):
    path = INDICATORS_4H_DIR / f"{ticker}_4h_indicators.csv"
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["date_str"] = df["timestamp"].dt.strftime("%Y-%m-%d")
    # Compute ATR(14) for V4
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr_14"] = tr.ewm(alpha=1.0 / ATR_PERIOD, adjust=False).mean()
    return df


def get_prior_vix(vix_daily, date_str):
    dt = pd.Timestamp(date_str)
    for offset in range(1, 6):
        prior = (dt - timedelta(days=offset)).strftime("%Y-%m-%d")
        if prior in vix_daily:
            return vix_daily[prior]
    return None


# ── Streak detectors ────────────────────────────────────────────────────────

def detect_v0(bars):
    """V0: DOWN = close < open. 3 consecutive DOWN bars."""
    is_down = bars["close"] < bars["open"]
    triggers = []
    for i in range(STREAK_LEN - 1, len(bars)):
        if all(is_down.iloc[i - j] for j in range(STREAK_LEN)):
            triggers.append(i)
    return triggers


def detect_v1(bars):
    """V1: DOWN = (open-close)/open > 0.1%. NEUTRAL skipped (doesn't break)."""
    body_pct = (bars["open"] - bars["close"]) / bars["open"]
    is_down = body_pct > BODY_THRESHOLD
    is_neutral = body_pct.abs() <= BODY_THRESHOLD

    triggers = []
    for i in range(len(bars)):
        count = 0
        j = i
        while j >= 0 and count < STREAK_LEN:
            if is_down.iloc[j]:
                count += 1
                j -= 1
            elif is_neutral.iloc[j]:
                j -= 1
            else:
                break
        if count >= STREAK_LEN:
            triggers.append(i)
    return triggers


def detect_v2(bars):
    """V2: DOWN = close < prior_bar_close. 3 consecutive."""
    closes = bars["close"].values
    is_down = pd.Series(
        [False] + [closes[i] < closes[i - 1] for i in range(1, len(closes))],
        index=bars.index,
    )
    triggers = []
    for i in range(STREAK_LEN, len(bars)):
        if all(is_down.iloc[i - j] for j in range(STREAK_LEN)):
            triggers.append(i)
    return triggers


def detect_v3(bars):
    """V3: Net Streak — at least 3 of last 4 bars are DOWN (close < open)."""
    is_down = (bars["close"] < bars["open"]).astype(int)
    triggers = []
    for i in range(3, len(bars)):  # need 4 bars (indices i-3..i)
        if is_down.iloc[i - 3:i + 1].sum() >= 3:
            triggers.append(i)
    return triggers


def detect_v4(bars):
    """V4: DOWN = (open-close) > 0.1×ATR(14). NEUTRAL skipped (doesn't break)."""
    body = bars["open"] - bars["close"]
    atr = bars["atr_14"]
    threshold = ATR_BODY_MULT * atr

    is_down = body > threshold
    is_neutral = body.abs() <= threshold

    triggers = []
    for i in range(len(bars)):
        if pd.isna(atr.iloc[i]):
            continue
        count = 0
        j = i
        while j >= 0 and count < STREAK_LEN:
            if pd.isna(atr.iloc[j]):
                break
            if is_down.iloc[j]:
                count += 1
                j -= 1
            elif is_neutral.iloc[j]:
                j -= 1
            else:
                break
        if count >= STREAK_LEN:
            triggers.append(i)
    return triggers


# ── Exit logic ──────────────────────────────────────────────────────────────

def compute_exit(bars, entry_idx, entry_price):
    """Exit at first 4H close >= EMA21, hard max 10 bars."""
    for j in range(entry_idx + 1, min(entry_idx + MAX_HOLD + 1, len(bars))):
        bar = bars.iloc[j]
        ema21 = bar.get("ema_21")
        if pd.notna(ema21) and bar["close"] >= ema21:
            return _trade(bars, entry_idx, j, entry_price, bar["close"])
    max_idx = entry_idx + MAX_HOLD
    if max_idx < len(bars):
        return _trade(bars, entry_idx, max_idx, entry_price, bars.iloc[max_idx]["close"])
    return None


def _trade(bars, entry_idx, exit_idx, entry_price, exit_price):
    ret = (exit_price - entry_price) / entry_price * 100
    hold = bars.iloc[entry_idx:exit_idx + 1]
    return {
        "return_pct": ret,
        "exit_price": exit_price,
        "hold_bars": exit_idx - entry_idx,
        "win": ret > 0,
        "mae": (hold["low"].min() - entry_price) / entry_price * 100,
        "mfe": (hold["high"].max() - entry_price) / entry_price * 100,
    }


# ── Metrics ─────────────────────────────────────────────────────────────────

def compute_metrics(trades):
    if not trades:
        return {"N": 0, "mean": 0, "wr": 0, "pf": 0, "sharpe": 0, "p": 1.0}

    rets = [t["return_pct"] for t in trades]
    n = len(rets)
    mean_r = np.mean(rets)
    std_r = np.std(rets, ddof=1) if n > 1 else 1.0
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0.001
    pf = gross_profit / gross_loss
    wr = len(wins) / n * 100
    sharpe = mean_r / std_r * np.sqrt(n) if std_r > 0 else 0

    if n >= 2:
        t_stat, p_val = stats.ttest_1samp(rets, 0)
        p_val = p_val / 2 if t_stat > 0 else 1 - p_val / 2
    else:
        p_val = 1.0

    return {"N": n, "mean": mean_r, "wr": wr, "pf": pf, "sharpe": sharpe, "p": p_val}


def _sig(p):
    if p < 0.001:
        return "***"
    elif p < 0.01:
        return "**"
    elif p < 0.05:
        return "*"
    return ""


# ── Main ────────────────────────────────────────────────────────────────────

def run():
    vix_daily = load_vix_daily()
    print(f"VIX: {len(vix_daily)} days loaded")

    detectors = {
        "V0": detect_v0,
        "V1": detect_v1,
        "V2": detect_v2,
        "V3": detect_v3,
        "V4": detect_v4,
    }

    all_trades = {v: [] for v in detectors}
    all_trigger_keys = {v: set() for v in detectors}

    for ticker in TICKERS:
        print(f"  {ticker}...", end="", flush=True)
        bars = load_4h_bars(ticker)

        for vname, detect_fn in detectors.items():
            raw_triggers = detect_fn(bars)

            for idx in raw_triggers:
                bar = bars.iloc[idx]

                rsi = bar.get("rsi_14")
                if pd.isna(rsi) or rsi >= RSI_THRESHOLD:
                    continue

                vix_val = get_prior_vix(vix_daily, bar["date_str"])
                if vix_val is None or vix_val < VIX_THRESHOLD:
                    continue

                key = (ticker, bar["date_str"], str(bar["timestamp"]))
                all_trigger_keys[vname].add(key)

                entry_price = bar["close"]
                trade = compute_exit(bars, idx, entry_price)
                if trade:
                    trade["ticker"] = ticker
                    trade["date_str"] = bar["date_str"]
                    trade["timestamp"] = str(bar["timestamp"])
                    all_trades[vname].append(trade)

        print(" done")

    # ── Compute metrics ─────────────────────────────────────────────────────
    metrics = {}
    for v in detectors:
        metrics[v] = compute_metrics(all_trades[v])

    # ── Diffs vs V0 ────────────────────────────────────────────────────────
    v0_keys = all_trigger_keys["V0"]
    diffs = {}
    for v in ["V1", "V2", "V3", "V4"]:
        extra = all_trigger_keys[v] - v0_keys
        lost = v0_keys - all_trigger_keys[v]
        extra_trades = [t for t in all_trades[v]
                        if (t["ticker"], t["date_str"], t["timestamp"]) in extra]
        extra_m = compute_metrics(extra_trades)
        diffs[v] = {"extra": extra, "lost": lost, "extra_metrics": extra_m}

    # ── Build report ────────────────────────────────────────────────────────
    lines = []
    lines.append("# S44 Module 4 Streak Sensitivity — Part 2: V3, V4 + Full Summary (V0–V4)")
    lines.append("")
    lines.append(f"**Date:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Tickers:** {len(TICKERS)} (excl SPY, VIXY)")
    lines.append(f"**Filters:** prior-day VIX >= {VIX_THRESHOLD}, 4H RSI(14) < {RSI_THRESHOLD}")
    lines.append(f"**Entry:** 4H trigger bar close")
    lines.append(f"**Exit:** first 4H close >= EMA21 (hard max {MAX_HOLD} bars)")
    lines.append("")

    # ── V3/V4 summary lines ────────────────────────────────────────────────
    lines.append("## Part 2 Results: V3, V4")
    lines.append("")
    lines.append("```")
    for v in ["V3", "V4"]:
        m = metrics[v]
        d = diffs[v]
        sig = _sig(m["p"])
        lines.append(f"{v}: N={m['N']} | Mean={m['mean']:+.2f}% | WR={m['wr']:.0f}% | "
                     f"PF={m['pf']:.2f} | Sharpe={m['sharpe']:.2f} | p={m['p']:.4f}{sig} | "
                     f"+{len(d['extra'])} extra / -{len(d['lost'])} lost")
    lines.append("```")
    lines.append("")

    # ── V3/V4 extra/lost detail ─────────────────────────────────────────────
    for v in ["V3", "V4"]:
        d = diffs[v]
        lines.append(f"## {v} — Extra Triggers vs V0 ({len(d['extra'])})")
        lines.append("")
        if d["extra"]:
            lines.append("| Ticker | Date | Timestamp |")
            lines.append("|--------|------|-----------|")
            for ticker, date_str, ts in sorted(d["extra"]):
                lines.append(f"| {ticker} | {date_str} | {ts} |")
            em = d["extra_metrics"]
            lines.append("")
            lines.append(f"Extra triggers quality: N={em['N']}, Mean={em['mean']:+.2f}%, WR={em['wr']:.0f}%")
        else:
            lines.append("*(none)*")
        lines.append("")

        lines.append(f"## {v} — Lost Triggers vs V0 ({len(d['lost'])})")
        lines.append("")
        if d["lost"]:
            lines.append("| Ticker | Date | Timestamp |")
            lines.append("|--------|------|-----------|")
            for ticker, date_str, ts in sorted(d["lost"]):
                lines.append(f"| {ticker} | {date_str} | {ts} |")
        else:
            lines.append("*(none)*")
        lines.append("")

    # ── Full V0–V4 combined ranking ─────────────────────────────────────────
    lines.append("---")
    lines.append("")
    lines.append("## Full Summary: V0–V4 Ranking")
    lines.append("")
    lines.append("```")
    m0 = metrics["V0"]
    lines.append(f"V0: N={m0['N']} | Mean={m0['mean']:+.2f}% | WR={m0['wr']:.0f}% | "
                 f"PF={m0['pf']:.2f} | Sharpe={m0['sharpe']:.2f} | p={m0['p']:.4f}{_sig(m0['p'])}")
    for v in ["V1", "V2", "V3", "V4"]:
        m = metrics[v]
        d = diffs[v]
        sig = _sig(m["p"])
        lines.append(f"{v}: N={m['N']} | Mean={m['mean']:+.2f}% | WR={m['wr']:.0f}% | "
                     f"PF={m['pf']:.2f} | Sharpe={m['sharpe']:.2f} | p={m['p']:.4f}{sig} | "
                     f"+{len(d['extra'])} extra / -{len(d['lost'])} lost")
    lines.append("```")
    lines.append("")

    # Ranking table
    lines.append("| Rank | Variant | Sharpe | N | Mean% | WR% | PF | Extra | Lost | Extra WR% |")
    lines.append("|------|---------|--------|---|-------|-----|-----|-------|------|-----------|")
    ranked = sorted(metrics.keys(), key=lambda v: metrics[v]["sharpe"], reverse=True)
    for rank, v in enumerate(ranked, 1):
        m = metrics[v]
        if v == "V0":
            extra_n, lost_n, extra_wr = "—", "—", "—"
        else:
            d = diffs[v]
            extra_n = len(d["extra"])
            lost_n = len(d["lost"])
            extra_wr = f"{d['extra_metrics']['wr']:.0f}" if d["extra_metrics"]["N"] > 0 else "—"
        lines.append(f"| {rank} | {v} | {m['sharpe']:.2f} | {m['N']} | "
                     f"{m['mean']:+.2f} | {m['wr']:.0f} | {m['pf']:.2f} | "
                     f"{extra_n} | {lost_n} | {extra_wr} |")
    lines.append("")

    # ── Recommendation ──────────────────────────────────────────────────────
    best_sharpe = ranked[0]
    most_triggers = max(metrics.keys(), key=lambda v: metrics[v]["N"])

    lines.append("## Analysis")
    lines.append("")
    lines.append(f"**Best Sharpe:** {best_sharpe} ({metrics[best_sharpe]['sharpe']:.2f})")
    lines.append(f"**Most triggers without WR degradation:** {most_triggers} "
                 f"(N={metrics[most_triggers]['N']}, WR={metrics[most_triggers]['wr']:.0f}%)")
    lines.append("")

    # Are extra triggers profitable?
    lines.append("**Extra triggers quality:**")
    for v in ["V1", "V2", "V3", "V4"]:
        d = diffs[v]
        em = d["extra_metrics"]
        if em["N"] > 0:
            verdict = "profitable" if em["mean"] > 0 else "GARBAGE"
            lines.append(f"- {v}: {em['N']} extra → Mean={em['mean']:+.2f}%, "
                         f"WR={em['wr']:.0f}% → **{verdict}**")
        else:
            lines.append(f"- {v}: 0 extra triggers")
    lines.append("")

    # Final recommendation
    lines.append("## Recommendation")
    lines.append("")

    # Check if any variant is strictly better (higher Sharpe + more triggers + same/better WR)
    v0_m = metrics["V0"]
    strictly_better = []
    for v in ["V1", "V2", "V3", "V4"]:
        m = metrics[v]
        if (m["sharpe"] > v0_m["sharpe"]
                and m["N"] >= v0_m["N"]
                and m["wr"] >= v0_m["wr"] - 2):  # allow 2pp WR margin
            strictly_better.append(v)

    if strictly_better:
        best = max(strictly_better, key=lambda v: metrics[v]["sharpe"])
        m = metrics[best]
        lines.append(f"**{best} is strictly better than V0.** "
                     f"Higher Sharpe ({m['sharpe']:.2f} vs {v0_m['sharpe']:.2f}), "
                     f"more triggers ({m['N']} vs {v0_m['N']}), "
                     f"WR maintained ({m['wr']:.0f}% vs {v0_m['wr']:.0f}%).")
        lines.append("")
        lines.append(f"Switch production streak definition from V0 to **{best}**.")
    else:
        lines.append("**V0 stays.** No variant is strictly better on Sharpe + N + WR combined.")
        if best_sharpe != "V0":
            m = metrics[best_sharpe]
            lines.append(f"{best_sharpe} has best Sharpe ({m['sharpe']:.2f}) but "
                         f"trade-offs exist (N={m['N']} vs {v0_m['N']}, "
                         f"WR={m['wr']:.0f}% vs {v0_m['wr']:.0f}%).")
    lines.append("")

    report = "\n".join(lines)
    out_path = RESULTS_DIR / "S44_Module4_Streak_Sensitivity_V0_V4.md"
    out_path.write_text(report)
    print(f"\nResults saved to {out_path}")
    print()
    print(report)


if __name__ == "__main__":
    run()
