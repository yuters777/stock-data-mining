#!/usr/bin/env python3
"""
S46 Module 4 V2 — Part 2: Subtype Attribution + Sector Concentration.

Classifies V2-only triggers (in V2 but not V0) by candle subtype and checks
sector concentration across all V2 triggers. Requested by DR before promotion.

Common setup (same as S44/S46-P1):
  Trigger:  streak condition AND prior-day VIX >= 25 AND 4H RSI(14) < 35
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
FLAT_THRESHOLD = 0.001   # 0.1% for FLAT_OPEN_DRIFT
TINY_THRESHOLD = 0.001   # 0.1% for TINY_LOWER

INDICATORS_4H_DIR = ROOT / "data" / "indicators_4h"
VIX_PATH = ROOT / "Fetched_Data" / "VIXCLS_FRED_real.csv"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# ── Sector mapping ──────────────────────────────────────────────────────────
# Tickers present in the actual universe get mapped; others are ignored.
# MU/TSM assigned to Semi (not Tech) per spec.

SECTOR_MAP = {
    # Tech
    "NVDA": "Tech", "AAPL": "Tech", "MSFT": "Tech", "GOOGL": "Tech",
    "AMZN": "Tech", "META": "Tech", "AVGO": "Tech", "AMD": "Tech",
    "PLTR": "Tech",
    # Crypto-proxy
    "COIN": "Crypto-proxy", "MARA": "Crypto-proxy", "IBIT": "Crypto-proxy",
    # China ADR
    "BABA": "China ADR", "BIDU": "China ADR",
    # Finance
    "GS": "Finance", "C": "Finance", "JPM": "Finance", "V": "Finance",
    # Semi
    "MU": "Semi", "TSM": "Semi",
    # Industrial
    "BA": "Industrial",
    # Consumer
    "COST": "Consumer",
    # Cloud/SaaS
    "SNOW": "Cloud/SaaS",
    # Crypto-equity (also crypto-adjacent but equity-like)
    "TSLA": "Consumer Disc.",
    "TXN": "Semi",
}

SECTOR_ORDER = ["Tech", "Crypto-proxy", "China ADR", "Finance", "Semi",
                "Industrial", "Consumer", "Cloud/SaaS", "Consumer Disc."]

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
    is_down = bars["close"] < bars["open"]
    triggers = []
    for i in range(STREAK_LEN - 1, len(bars)):
        if all(is_down.iloc[i - j] for j in range(STREAK_LEN)):
            triggers.append(i)
    return triggers


def detect_v2(bars):
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


# ── Exit logic ──────────────────────────────────────────────────────────────


def compute_exit(bars, entry_idx, entry_price):
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


# ── Subtype classifier ─────────────────────────────────────────────────────


def classify_trigger_bar(bar_open, bar_close, prior_close):
    """Classify a V2 trigger bar into a subtype based on candle structure.

    Subtypes (all satisfy V2's close < prior_close, but NOT V0's close < open):
      GAP_DOWN_GREEN: open < prior_close AND close > open (gapped down, green body)
      FLAT_OPEN_DRIFT: open ~ prior_close (within 0.1%) AND close < prior_close
      TINY_LOWER: close < prior_close but drop < 0.1%
      OTHER: anything else
    """
    gap_down = bar_open < prior_close
    green_body = bar_close > bar_open
    open_vs_prior = abs(bar_open - prior_close) / prior_close if prior_close != 0 else 0
    drop_pct = (prior_close - bar_close) / prior_close if prior_close != 0 else 0

    if gap_down and green_body:
        return "GAP_DOWN_GREEN"
    if open_vs_prior <= FLAT_THRESHOLD and bar_close < prior_close:
        return "FLAT_OPEN_DRIFT"
    if 0 < drop_pct <= TINY_THRESHOLD:
        return "TINY_LOWER"
    return "OTHER"


# ── Collect trades with bar-level data ──────────────────────────────────────


def collect_all_trades(vix_daily):
    """Run V0 and V2, returning trades with bar-level metadata for subtype classification."""
    detectors = {"V0": detect_v0, "V2": detect_v2}
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
                    # Store bar-level data for subtype classification
                    trade["bar_open"] = bar["open"]
                    trade["bar_close"] = bar["close"]
                    if idx > 0:
                        trade["prior_close"] = bars.iloc[idx - 1]["close"]
                    else:
                        trade["prior_close"] = np.nan
                    all_trades[vname].append(trade)

        print(" done")

    return all_trades, all_trigger_keys


# ── Test A: V2-Only Trigger Subtypes ───────────────────────────────────────


def test_a_subtypes(all_trades, all_trigger_keys):
    lines = []
    lines.append("V2-ONLY SUBTYPE ATTRIBUTION")
    lines.append("=" * 50)
    lines.append("")

    # Identify V2-only trades
    v0_keys = all_trigger_keys["V0"]
    v2_only_trades = [
        t for t in all_trades["V2"]
        if (t["ticker"], t["date_str"], t["timestamp"]) not in v0_keys
    ]

    lines.append(f"Total V2 trades: {len(all_trades['V2'])}")
    lines.append(f"V2-only trades (not in V0): {len(v2_only_trades)}")
    lines.append("")

    # Classify each V2-only trade
    subtypes = {"GAP_DOWN_GREEN": [], "FLAT_OPEN_DRIFT": [], "TINY_LOWER": [], "OTHER": []}
    for t in v2_only_trades:
        if pd.notna(t["prior_close"]):
            st = classify_trigger_bar(t["bar_open"], t["bar_close"], t["prior_close"])
        else:
            st = "OTHER"
        t["subtype"] = st
        subtypes[st].append(t)

    total_v2_only = len(v2_only_trades)
    for st_name in ["GAP_DOWN_GREEN", "FLAT_OPEN_DRIFT", "TINY_LOWER", "OTHER"]:
        trades = subtypes[st_name]
        m = compute_metrics(trades)
        pct = len(trades) / total_v2_only * 100 if total_v2_only > 0 else 0
        lines.append(f"{st_name:20s}: N={m['N']:>3} ({pct:5.1f}%) | "
                     f"Mean={m['mean']:+.2f}% | WR={m['wr']:.0f}%")

    lines.append("")

    # Dominant subtype
    dominant = max(subtypes.keys(), key=lambda k: len(subtypes[k]))
    dom_pct = len(subtypes[dominant]) / total_v2_only * 100 if total_v2_only > 0 else 0
    lines.append(f"Dominant: {dominant} ({dom_pct:.0f}% of V2-only trades)")
    lines.append("")

    # Detail table for V2-only trades
    lines.append("V2-only trade details:")
    lines.append("| Ticker | Date | Subtype | Open | Close | PriorCl | Ret% | Win |")
    lines.append("|--------|------|---------|------|-------|---------|------|-----|")
    for t in sorted(v2_only_trades, key=lambda x: (x["subtype"], x["date_str"], x["ticker"])):
        w = "Y" if t["win"] else "N"
        lines.append(f"| {t['ticker']} | {t['date_str']} | {t.get('subtype', '?'):17s} | "
                     f"{t['bar_open']:.2f} | {t['bar_close']:.2f} | "
                     f"{t['prior_close']:.2f} | {t['return_pct']:+.2f}% | {w} |")
    lines.append("")

    return lines


# ── Test B: Sector Concentration ───────────────────────────────────────────


def test_b_sector_concentration(all_trades):
    lines = []
    lines.append("SECTOR CONCENTRATION (all V2 triggers)")
    lines.append("=" * 50)
    lines.append("")

    v2_trades = all_trades["V2"]
    total = len(v2_trades)

    # Group by sector
    sector_trades = {}
    unmapped = []
    for t in v2_trades:
        sector = SECTOR_MAP.get(t["ticker"])
        if sector is None:
            unmapped.append(t["ticker"])
            sector = "UNMAPPED"
        if sector not in sector_trades:
            sector_trades[sector] = []
        sector_trades[sector].append(t)

    if unmapped:
        lines.append(f"WARNING: unmapped tickers: {set(unmapped)}")
        lines.append("")

    # Report by sector in order
    lines.append(f"Total V2 trades: {total}")
    lines.append("")

    max_pct = 0
    max_sector = ""
    for sector in SECTOR_ORDER:
        trades = sector_trades.get(sector, [])
        if not trades:
            continue
        m = compute_metrics(trades)
        pct = len(trades) / total * 100
        tickers_in = sorted(set(t["ticker"] for t in trades))
        lines.append(f"{sector:15s}: N={m['N']:>3} ({pct:5.1f}%) | "
                     f"Mean={m['mean']:+.2f}% | WR={m['wr']:.0f}% | "
                     f"Tickers: {', '.join(tickers_in)}")
        if pct > max_pct:
            max_pct = pct
            max_sector = sector

    # Any unmapped
    if "UNMAPPED" in sector_trades:
        trades = sector_trades["UNMAPPED"]
        m = compute_metrics(trades)
        pct = len(trades) / total * 100
        lines.append(f"{'UNMAPPED':15s}: N={m['N']:>3} ({pct:5.1f}%) | "
                     f"Mean={m['mean']:+.2f}% | WR={m['wr']:.0f}%")

    lines.append("")

    # Verdict
    if max_pct > 50:
        verdict = f"CONCENTRATED in {max_sector} ({max_pct:.0f}%)"
    else:
        verdict = f"DIVERSIFIED (largest sector: {max_sector} at {max_pct:.0f}%)"
    lines.append(f"VERDICT: {verdict}")
    lines.append("")

    # Per-ticker breakdown within top sector
    lines.append(f"Top sector breakdown ({max_sector}):")
    top_trades = sector_trades.get(max_sector, [])
    ticker_groups = {}
    for t in top_trades:
        ticker_groups.setdefault(t["ticker"], []).append(t)
    for tk in sorted(ticker_groups.keys()):
        tg = ticker_groups[tk]
        m = compute_metrics(tg)
        lines.append(f"  {tk}: N={m['N']} | Mean={m['mean']:+.2f}% | WR={m['wr']:.0f}%")
    lines.append("")

    return lines


# ── Main ────────────────────────────────────────────────────────────────────


def run():
    vix_daily = load_vix_daily()
    print(f"VIX: {len(vix_daily)} days loaded")
    print(f"Tickers: {len(TICKERS)}")
    print()

    all_trades, all_trigger_keys = collect_all_trades(vix_daily)
    print()

    report_lines = []
    report_lines.append("# S46 Module 4 V2 — Part 2: Subtype Attribution + Sector Check")
    report_lines.append("")
    report_lines.append(f"**Date:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    report_lines.append(f"**Tickers:** {len(TICKERS)} equity (excl SPY, VIXY)")
    report_lines.append(f"**Filters:** prior-day VIX >= {VIX_THRESHOLD}, 4H RSI(14) < {RSI_THRESHOLD}")
    report_lines.append(f"**Entry:** 4H trigger bar close")
    report_lines.append(f"**Exit:** first 4H close >= EMA21 (hard max {MAX_HOLD} bars)")
    report_lines.append(f"**V0:** close < open, 3 consecutive")
    report_lines.append(f"**V2:** close < prior_bar_close, 3 consecutive")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")

    # Test A: Subtypes
    print("=== Test A: V2-Only Subtype Attribution ===")
    report_lines.append("## Test A: V2-Only Trigger Subtypes")
    report_lines.append("")
    report_lines.append("```")
    report_lines.extend(test_a_subtypes(all_trades, all_trigger_keys))
    report_lines.append("```")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")

    # Test B: Sector
    print("=== Test B: Sector Concentration ===")
    report_lines.append("## Test B: Sector Concentration")
    report_lines.append("")
    report_lines.append("```")
    report_lines.extend(test_b_sector_concentration(all_trades))
    report_lines.append("```")
    report_lines.append("")

    report = "\n".join(report_lines)

    out_path = RESULTS_DIR / "S46_Module4_V2_Subtype_Sector.md"
    out_path.write_text(report)
    print(f"\nResults saved to {out_path}")
    print()
    print(report)


if __name__ == "__main__":
    run()
