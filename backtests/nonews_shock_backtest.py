"""
No-News Shock Reversal Backtest (CC-NONEWS-4).

Strategy: large gap/move on non-earnings day -> trade the reversal.
Hypothesis: shocks without fundamental news tend to mean-revert.

Reads:
  - backtester/data/fmp_earnings.csv (earnings calendar for exclusion)
  - Fetched_Data/{TICKER}_data.csv (M5 OHLCV bars, IST-encoded)

Produces:
  - backtest_output/nonews_shock_events.csv (shock event table)
  - backtest_output/nonews_shock_trades.csv (trade details)
  - Console output with baseline, sweep, and robustness results

Usage:
    python backtests/nonews_shock_backtest.py               # baseline only
    python backtests/nonews_shock_backtest.py --sweep        # baseline + parameter sweeps
    python backtests/nonews_shock_backtest.py --robustness   # baseline + robustness checks (R1-R5)
"""

import argparse
import random
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

try:
    from scipy import stats as scipy_stats
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

from utils.data_loader import load_m5_regsess

# --- Paths ---
_EARNINGS_CSV = _REPO_ROOT / "backtester" / "data" / "fmp_earnings.csv"
_OUTPUT_DIR = _REPO_ROOT / "backtest_output"
_EVENTS_CSV = _OUTPUT_DIR / "nonews_shock_events.csv"
_TRADES_CSV = _OUTPUT_DIR / "nonews_shock_trades.csv"

# --- Sector map ---
SECTORS = {
    "mega_tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA"],
    "growth_semi": ["TSLA", "AMD", "SMCI", "PLTR", "AVGO", "ARM", "TSM", "MU", "INTC"],
    "crypto_proxy": ["COIN", "MSTR", "MARA"],
    "finance": ["C", "GS", "V", "BA", "JPM"],
    "china_adr": ["BABA", "JD", "BIDU"],
    "consumer": ["COST"],
}

EQUITY_TICKERS = sorted(set(
    t for tl in SECTORS.values() for t in tl
))

BEST_CONFIG = {
    "gap_threshold": 3.0,
    "max_hold": 10,
    "exit_strategy": "fixed_10",
    "direction": "both",
}


# ---------------------------------------------------------------------------
# Part A: Data Prep
# ---------------------------------------------------------------------------

def synthesize_4h_bars(m5_df: pd.DataFrame) -> pd.DataFrame:
    """Synthesize 4H bars from M5 data (already in ET).
    Bar 1: 09:30-13:25 ET, Bar 2: 13:30-15:55 ET.
    """
    df = m5_df.copy()
    df["trading_day"] = df["Datetime"].dt.date
    hm = df["Datetime"].dt.hour * 60 + df["Datetime"].dt.minute
    conditions = [
        (hm >= 570) & (hm <= 805),
        (hm >= 810) & (hm <= 955),
    ]
    df["bar_num"] = np.select(conditions, [1, 2], default=0)
    df = df[df["bar_num"] > 0].copy()
    bars_4h = df.groupby(["Ticker", "trading_day", "bar_num"]).agg(
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
        Volume=("Volume", "sum"),
    ).reset_index()
    bars_4h = bars_4h.sort_values(["Ticker", "trading_day", "bar_num"]).reset_index(drop=True)
    return bars_4h


def load_earnings_dates() -> dict:
    """Load earnings dates as {ticker: set(date)} for exclusion."""
    if not _EARNINGS_CSV.exists():
        print(f"WARNING: Earnings CSV not found: {_EARNINGS_CSV}")
        return {}
    df = pd.read_csv(_EARNINGS_CSV)
    result = {}
    for _, row in df.iterrows():
        ticker = row["ticker"]
        try:
            dt = pd.Timestamp(row["earnings_date"]).date()
        except Exception:
            continue
        if ticker not in result:
            result[ticker] = set()
        result[ticker].add(dt)
        # Also exclude the day after (earnings drift contamination)
        result[ticker].add(dt + pd.Timedelta(days=1))
        result[ticker].add(dt + pd.Timedelta(days=2))
    return result


def get_trading_days(bars_4h: pd.DataFrame) -> list:
    return sorted(bars_4h["trading_day"].unique())


def next_trading_day(day, trading_days: list):
    for td in trading_days:
        if td > day:
            return td
    return None


def prev_trading_day(day, trading_days: list):
    prev = None
    for td in trading_days:
        if td >= day:
            return prev
        prev = td
    return prev


def nth_trading_day_after(day, n: int, trading_days: list):
    count = 0
    for td in trading_days:
        if td > day:
            count += 1
            if count == n:
                return td
    return None


def get_bar(bars_4h: pd.DataFrame, ticker: str, day, bar_num: int):
    mask = (bars_4h["Ticker"] == ticker) & (bars_4h["trading_day"] == day) & (bars_4h["bar_num"] == bar_num)
    rows = bars_4h[mask]
    if rows.empty:
        return None
    return rows.iloc[0]


def get_forward_bars(bars_4h, ticker, entry_day, trading_days, max_bars):
    """Get up to max_bars 4H bars starting from bar 2 on entry_day."""
    result = []
    day = entry_day
    bar_num = 2
    count = 0
    while count < max_bars:
        row = get_bar(bars_4h, ticker, day, bar_num)
        if row is None:
            break
        result.append({
            "day": day, "bar_num": bar_num,
            "Open": row["Open"], "High": row["High"],
            "Low": row["Low"], "Close": row["Close"],
        })
        count += 1
        if bar_num == 2:
            day = next_trading_day(day, trading_days)
            if day is None:
                break
            bar_num = 1
        else:
            bar_num = 2
    return result


def build_shock_events(ticker_4h: dict, ticker_trading_days: dict,
                       earnings_dates: dict, gap_threshold: float = 3.0,
                       include_earnings: bool = False) -> pd.DataFrame:
    """Build shock events: days with large gap that are NOT earnings days.

    A shock is defined as |gap_pct| >= gap_threshold where
    gap_pct = (today_open - prev_close) / prev_close * 100.

    Reversal direction: opposite of gap (gap up -> SHORT, gap down -> LONG).

    If include_earnings=True, returns ONLY earnings-day shocks (for R5 comparison).
    """
    events = []
    for ticker in sorted(ticker_4h.keys()):
        if ticker not in EQUITY_TICKERS:
            continue
        bars_4h = ticker_4h[ticker]
        trading_days = ticker_trading_days[ticker]
        earn_set = earnings_dates.get(ticker, set())

        for i, day in enumerate(trading_days):
            if i == 0:
                continue

            prev_day = trading_days[i - 1]
            prev_bar2 = get_bar(bars_4h, ticker, prev_day, 2)
            if prev_bar2 is None:
                prev_bar2 = get_bar(bars_4h, ticker, prev_day, 1)
            if prev_bar2 is None:
                continue
            prev_close = prev_bar2["Close"]

            bar1 = get_bar(bars_4h, ticker, day, 1)
            if bar1 is None:
                continue
            today_open = bar1["Open"]

            gap_pct = (today_open - prev_close) / prev_close * 100
            if abs(gap_pct) < gap_threshold:
                continue

            is_earnings = day in earn_set

            if include_earnings and not is_earnings:
                continue
            if not include_earnings and is_earnings:
                continue

            # Reversal direction: opposite of gap
            reversal_dir = "SHORT" if gap_pct > 0 else "LONG"
            gap_sign = -1 if gap_pct > 0 else 1  # reversal sign

            entry_price = bar1["Close"]  # enter at first 4H bar close

            events.append({
                "ticker": ticker,
                "date": day,
                "prev_close": round(prev_close, 4),
                "open_price": round(today_open, 4),
                "gap_pct": round(gap_pct, 4),
                "reversal_dir": reversal_dir,
                "gap_sign": gap_sign,
                "entry_price": round(entry_price, 4),
                "first_4h_open": round(bar1["Open"], 4),
                "first_4h_high": round(bar1["High"], 4),
                "first_4h_low": round(bar1["Low"], 4),
                "first_4h_close": round(entry_price, 4),
                "is_earnings": is_earnings,
                "year": day.year if hasattr(day, "year") else pd.Timestamp(day).year,
            })

    return pd.DataFrame(events)


# ---------------------------------------------------------------------------
# Part B: Trade Simulator & Metrics
# ---------------------------------------------------------------------------

def simulate_trade(ev, ticker_4h, ticker_trading_days, max_hold=10,
                   exit_strategy="fixed_10"):
    """Simulate a single reversal trade.

    Entry: first 4H bar close on shock day.
    Direction: reversal (opposite of gap).
    Exit strategies:
        'fixed_N' - exit at Nth forward bar
        'trailing50' - exit if gives back >50% of max unrealized gain
        'midpoint' - exit when price returns to gap midpoint
    """
    ticker = ev["ticker"]
    day = ev["date"]
    gap_sign = ev["gap_sign"]  # +1 for long reversal, -1 for short reversal
    entry_price = ev["entry_price"]

    if entry_price is None or (isinstance(entry_price, float) and np.isnan(entry_price)):
        return None

    bars_4h = ticker_4h[ticker]
    trading_days = ticker_trading_days[ticker]
    fwd = get_forward_bars(bars_4h, ticker, day, trading_days, max_hold)
    if not fwd:
        return None

    # Fixed hold
    if exit_strategy.startswith("fixed_"):
        target = int(exit_strategy.split("_")[1])
        if len(fwd) < target:
            return None
        exit_price = fwd[target - 1]["Close"]
        raw_ret = (exit_price - entry_price) / entry_price * 100
        signed_ret = raw_ret * gap_sign
        return _make_trade(ev, entry_price, exit_price, signed_ret, target,
                           "fixed_%d" % target)

    # Trailing 50%
    if exit_strategy == "trailing50":
        max_unrealized = 0.0
        for i, bar in enumerate(fwd):
            raw_ret = (bar["Close"] - entry_price) / entry_price * 100
            unrealized = raw_ret * gap_sign
            if unrealized > max_unrealized:
                max_unrealized = unrealized
            if max_unrealized > 0 and unrealized < max_unrealized * 0.5:
                return _make_trade(ev, entry_price, bar["Close"], unrealized,
                                   i + 1, "trailing50")
        exit_price = fwd[-1]["Close"]
        raw_ret = (exit_price - entry_price) / entry_price * 100
        signed_ret = raw_ret * gap_sign
        return _make_trade(ev, entry_price, exit_price, signed_ret,
                           len(fwd), "max_hold")

    # Midpoint exit
    if exit_strategy == "midpoint":
        gap_mid = (ev["prev_close"] + ev["open_price"]) / 2
        for i, bar in enumerate(fwd):
            if ev["gap_pct"] > 0 and bar["Close"] <= gap_mid:
                raw_ret = (bar["Close"] - entry_price) / entry_price * 100
                return _make_trade(ev, entry_price, bar["Close"],
                                   raw_ret * gap_sign, i + 1, "midpoint")
            if ev["gap_pct"] < 0 and bar["Close"] >= gap_mid:
                raw_ret = (bar["Close"] - entry_price) / entry_price * 100
                return _make_trade(ev, entry_price, bar["Close"],
                                   raw_ret * gap_sign, i + 1, "midpoint")
        exit_price = fwd[-1]["Close"]
        raw_ret = (exit_price - entry_price) / entry_price * 100
        return _make_trade(ev, entry_price, exit_price, raw_ret * gap_sign,
                           len(fwd), "max_hold")

    return None


def _make_trade(ev, entry_price, exit_price, return_pct, bars_held, exit_reason):
    return {
        "ticker": ev["ticker"],
        "date": ev["date"],
        "gap_pct": ev["gap_pct"],
        "gap_sign": ev["gap_sign"],
        "reversal_dir": ev["reversal_dir"],
        "entry_price": entry_price,
        "exit_price": exit_price,
        "return_pct": return_pct,
        "bars_held": bars_held,
        "exit_reason": exit_reason,
        "year": ev["year"],
    }


def compute_metrics(trades_df):
    """Compute standard metrics from trades DataFrame."""
    if trades_df.empty or len(trades_df) == 0:
        return {"N": 0, "mean_pct": 0.0, "wr_pct": 0.0, "pf": 0.0,
                "sharpe": 0.0, "max_dd": 0.0, "avg_bars": 0.0}
    rets = trades_df["return_pct"]
    n = len(rets)
    mean_r = rets.mean()
    wr = (rets > 0).mean() * 100
    gp = rets[rets > 0].sum()
    gl = abs(rets[rets <= 0].sum())
    pf = gp / gl if gl > 0 else float("inf")
    std = rets.std()
    sharpe = (mean_r / std * np.sqrt(100)) if std > 0 else 0.0
    cum = rets.cumsum()
    peak = cum.cummax()
    max_dd = (cum - peak).min()
    avg_bars = trades_df["bars_held"].mean() if "bars_held" in trades_df.columns else 0
    return {"N": n, "mean_pct": mean_r, "wr_pct": wr, "pf": pf,
            "sharpe": sharpe, "max_dd": max_dd, "avg_bars": avg_bars}


def run_backtest(events_df, ticker_4h, ticker_trading_days,
                 gap_threshold=3.0, max_hold=10, exit_strategy="fixed_10",
                 direction="both", exclude_ticker=None, exclude_year=None):
    """Run backtest with given parameters. Returns DataFrame of trades."""
    df = events_df.copy()
    df = df[df["gap_pct"].abs() >= gap_threshold]
    if direction == "long":
        df = df[df["reversal_dir"] == "LONG"]
    elif direction == "short":
        df = df[df["reversal_dir"] == "SHORT"]
    if exclude_ticker is not None:
        df = df[df["ticker"] != exclude_ticker]
    if exclude_year is not None:
        df = df[df["year"] != exclude_year]

    trades = []
    for _, ev in df.iterrows():
        t = simulate_trade(ev, ticker_4h, ticker_trading_days,
                           max_hold=max_hold, exit_strategy=exit_strategy)
        if t is not None:
            trades.append(t)
    return pd.DataFrame(trades) if trades else pd.DataFrame()


# ---------------------------------------------------------------------------
# Part C: Baseline Test
# ---------------------------------------------------------------------------

def _fmt_pf(pf):
    return "inf" if pf == float("inf") else "%.2f" % pf


def run_baseline(events_df, ticker_4h, ticker_trading_days, config=None):
    """Run baseline test with best config."""
    if config is None:
        config = BEST_CONFIG.copy()

    print("\n" + "=" * 60)
    print("=== No-News Shock Reversal \u2014 Baseline ===")
    print("=" * 60)
    print("Config: gap>=%s%%, hold=%d, exit=%s, dir=%s" % (
        config["gap_threshold"], config["max_hold"],
        config["exit_strategy"], config["direction"]))
    print("Total shock events (non-earnings): %d" % len(events_df))

    trades = run_backtest(events_df, ticker_4h, ticker_trading_days, **config)
    m = compute_metrics(trades)

    print("\nResults:")
    print("  N: %d" % m["N"])
    print("  Mean return: %.2f%%" % m["mean_pct"])
    print("  Win rate: %.1f%%" % m["wr_pct"])
    print("  Profit factor: %s" % _fmt_pf(m["pf"]))
    print("  Sharpe: %.2f" % m["sharpe"])
    print("  Max drawdown: %.2f%%" % m["max_dd"])
    print("  Avg bars held: %.1f" % m["avg_bars"])

    if HAS_SCIPY and not trades.empty and len(trades) >= 2:
        _, p = scipy_stats.ttest_1samp(trades["return_pct"], 0)
        print("  p-value: %.4f" % p)

    # Per-direction breakdown
    if not trades.empty:
        for d in ["LONG", "SHORT"]:
            sub = trades[trades["reversal_dir"] == d]
            if len(sub) > 0:
                sm = compute_metrics(sub)
                print("  %s: N=%d, Mean=%.2f%%, WR=%.1f%%, PF=%s" % (
                    d, sm["N"], sm["mean_pct"], sm["wr_pct"], _fmt_pf(sm["pf"])))

    return trades, m


# ---------------------------------------------------------------------------
# Part D: Sweep Engine
# ---------------------------------------------------------------------------

def run_sweep(events_df, ticker_4h, ticker_trading_days):
    """Run parameter sweeps to find best config."""
    print("\n" + "=" * 60)
    print("=== No-News Shock Reversal \u2014 Parameter Sweeps ===")
    print("=" * 60)

    # Sweep 1: Gap threshold
    print("\n--- Sweep 1: Gap Threshold ---")
    print("  %6s | %5s | %7s | %6s | %7s | %7s" % ("Gap%", "N", "Mean%", "WR%", "PF", "Sharpe"))
    print("  " + "-" * 50)
    gap_results = {}
    for g in [2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0]:
        trades = run_backtest(events_df, ticker_4h, ticker_trading_days,
                              gap_threshold=g, max_hold=10, exit_strategy="fixed_10")
        m = compute_metrics(trades)
        gap_results[g] = m
        print("  %5.1f%% | %5d | %+7.2f | %5.1f%% | %7s | %7.2f" % (
            g, m["N"], m["mean_pct"], m["wr_pct"], _fmt_pf(m["pf"]), m["sharpe"]))

    best_gap = 3.0
    best_pf = 0
    for g, m in gap_results.items():
        if m["N"] >= 10 and m["pf"] > best_pf:
            best_pf = m["pf"]
            best_gap = g
    print("  Best gap: %.1f%% (PF=%s)" % (best_gap, _fmt_pf(best_pf)))

    # Sweep 2: Max hold bars
    print("\n--- Sweep 2: Max Hold Bars ---")
    print("  %6s | %5s | %7s | %6s | %7s" % ("Bars", "N", "Mean%", "WR%", "PF"))
    print("  " + "-" * 40)
    hold_results = {}
    for h in [4, 6, 8, 10, 15, 20]:
        trades = run_backtest(events_df, ticker_4h, ticker_trading_days,
                              gap_threshold=best_gap, max_hold=h,
                              exit_strategy="fixed_%d" % h)
        m = compute_metrics(trades)
        hold_results[h] = m
        print("  %6d | %5d | %+7.2f | %5.1f%% | %7s" % (
            h, m["N"], m["mean_pct"], m["wr_pct"], _fmt_pf(m["pf"])))

    best_hold = 10
    best_pf = 0
    for h, m in hold_results.items():
        if m["N"] >= 10 and m["pf"] > best_pf:
            best_pf = m["pf"]
            best_hold = h
    print("  Best hold: %d bars (PF=%s)" % (best_hold, _fmt_pf(best_pf)))

    # Sweep 3: Exit strategy
    print("\n--- Sweep 3: Exit Strategy ---")
    print("  %12s | %5s | %7s | %6s | %7s" % ("Exit", "N", "Mean%", "WR%", "PF"))
    print("  " + "-" * 44)
    for strat_name, strat, mb in [("fixed_%d" % best_hold, "fixed_%d" % best_hold, best_hold),
                                   ("trailing50", "trailing50", best_hold),
                                   ("midpoint", "midpoint", best_hold)]:
        trades = run_backtest(events_df, ticker_4h, ticker_trading_days,
                              gap_threshold=best_gap, max_hold=mb,
                              exit_strategy=strat)
        m = compute_metrics(trades)
        print("  %12s | %5d | %+7.2f | %5.1f%% | %7s" % (
            strat_name, m["N"], m["mean_pct"], m["wr_pct"], _fmt_pf(m["pf"])))

    # Sweep 4: Direction
    print("\n--- Sweep 4: Direction ---")
    print("  %8s | %5s | %7s | %6s | %7s" % ("Dir", "N", "Mean%", "WR%", "PF"))
    print("  " + "-" * 38)
    for d_name, d_key in [("LONG", "long"), ("SHORT", "short"), ("BOTH", "both")]:
        trades = run_backtest(events_df, ticker_4h, ticker_trading_days,
                              gap_threshold=best_gap, max_hold=best_hold,
                              exit_strategy="fixed_%d" % best_hold, direction=d_key)
        m = compute_metrics(trades)
        print("  %8s | %5d | %+7.2f | %5.1f%% | %7s" % (
            d_name, m["N"], m["mean_pct"], m["wr_pct"], _fmt_pf(m["pf"])))

    # Determine best overall config
    configs = []
    for g in [best_gap, 3.0, 2.5]:
        for h in [best_hold, 10, 8]:
            for strat in ["fixed_%d" % h, "trailing50", "midpoint"]:
                for d in ["both", "long", "short"]:
                    cfg = {"gap_threshold": g, "max_hold": h,
                           "exit_strategy": strat, "direction": d}
                    trades = run_backtest(events_df, ticker_4h, ticker_trading_days, **cfg)
                    m = compute_metrics(trades)
                    if m["N"] >= 10:
                        configs.append((cfg, m))

    if configs:
        def score(m):
            n_bonus = min(m["N"] / 40.0, 1.0)
            return (m["pf"] * 0.5 + m["sharpe"] * 0.3 + m["wr_pct"] / 100 * 0.2) * n_bonus
        configs.sort(key=lambda x: score(x[1]), reverse=True)
        best_cfg, best_m = configs[0]
        print("\n  Best config: gap>=%.1f%%, hold=%d, exit=%s, dir=%s" % (
            best_cfg["gap_threshold"], best_cfg["max_hold"],
            best_cfg["exit_strategy"], best_cfg["direction"]))
        print("  N=%d, Mean=%.2f%%, WR=%.1f%%, PF=%s" % (
            best_m["N"], best_m["mean_pct"], best_m["wr_pct"], _fmt_pf(best_m["pf"])))
        return best_cfg
    else:
        print("\n  No valid config found with N >= 10. Using defaults.")
        return BEST_CONFIG.copy()


# ---------------------------------------------------------------------------
# Part E: Robustness Checks (R1-R5)
# ---------------------------------------------------------------------------

def robustness_r1_loto(events_df, ticker_4h, ticker_trading_days, config):
    """R1: Leave-One-Ticker-Out -- flag >20% PF impact."""
    print("\n" + "=" * 60)
    print("=== R1: Leave-One-Ticker-Out ===")
    print("=" * 60)

    base_trades = run_backtest(events_df, ticker_4h, ticker_trading_days, **config)
    base_m = compute_metrics(base_trades)
    base_pf = base_m["pf"]
    print("Baseline: N=%d, PF=%s" % (base_m["N"], _fmt_pf(base_pf)))

    tickers = sorted(events_df["ticker"].unique())
    print("\n  %8s | %4s | %7s | %8s | Flag" % ("Excluded", "N", "PF", "PF_chg%"))
    print("  " + "-" * 45)

    max_impact = 0.0
    results = []
    for t in tickers:
        trades = run_backtest(events_df, ticker_4h, ticker_trading_days,
                              exclude_ticker=t, **config)
        m = compute_metrics(trades)
        pf_change = ((base_pf - m["pf"]) / base_pf * 100) if base_pf > 0 else 0
        flag = " ***" if abs(pf_change) > 20 else ""
        print("  %8s | %4d | %7s | %+7.1f%% |%s" % (
            t, m["N"], _fmt_pf(m["pf"]), pf_change, flag))
        if abs(pf_change) > max_impact:
            max_impact = abs(pf_change)
        results.append({"ticker": t, "N": m["N"], "pf": m["pf"],
                         "pf_change_pct": pf_change})

    print("\n  Max LOTO impact: %.1f%%" % max_impact)
    print("  Threshold: <20%%  ->  %s" % ("PASS" if max_impact < 20 else "FAIL"))
    return max_impact, results


def robustness_r2_loyo(events_df, ticker_4h, ticker_trading_days, config):
    """R2: Leave-One-Year-Out -- flag >25% PF impact."""
    print("\n" + "=" * 60)
    print("=== R2: Leave-One-Year-Out ===")
    print("=" * 60)

    base_trades = run_backtest(events_df, ticker_4h, ticker_trading_days, **config)
    base_m = compute_metrics(base_trades)
    base_pf = base_m["pf"]
    print("Baseline: N=%d, PF=%s" % (base_m["N"], _fmt_pf(base_pf)))

    years = [2022, 2023, 2024, 2025]
    print("\n  %10s | %4s | %7s | %8s | Flag" % ("Excl Year", "N", "PF", "PF_chg%"))
    print("  " + "-" * 47)

    max_impact = 0.0
    results = []
    for yr in years:
        trades = run_backtest(events_df, ticker_4h, ticker_trading_days,
                              exclude_year=yr, **config)
        m = compute_metrics(trades)
        pf_change = ((base_pf - m["pf"]) / base_pf * 100) if base_pf > 0 else 0
        flag = " ***" if abs(pf_change) > 25 else ""
        print("  %10d | %4d | %7s | %+7.1f%% |%s" % (
            yr, m["N"], _fmt_pf(m["pf"]), pf_change, flag))
        if abs(pf_change) > max_impact:
            max_impact = abs(pf_change)
        results.append({"year": yr, "N": m["N"], "pf": m["pf"],
                         "pf_change_pct": pf_change})

    print("\n  Max LOYO impact: %.1f%%" % max_impact)
    print("  Threshold: <25%%  ->  %s" % ("PASS" if max_impact < 25 else "FAIL"))
    return max_impact, results


def robustness_r3_sector(events_df, ticker_4h, ticker_trading_days, config):
    """R3: Sector Breakdown."""
    print("\n" + "=" * 60)
    print("=== R3: Sector Breakdown ===")
    print("=" * 60)

    trades = run_backtest(events_df, ticker_4h, ticker_trading_days, **config)
    if trades.empty:
        print("  No trades.")
        return

    print("\n  %14s | %4s | %7s | %6s | %7s" % ("Sector", "N", "Mean%", "WR%", "PF"))
    print("  " + "-" * 46)

    for sector, tickers in SECTORS.items():
        sub = trades[trades["ticker"].isin(tickers)]
        if len(sub) == 0:
            print("  %14s | %4d |    -    |   -    |    -  " % (sector, 0))
            continue
        m = compute_metrics(sub)
        print("  %14s | %4d | %+7.2f | %5.1f%% | %7s" % (
            sector, m["N"], m["mean_pct"], m["wr_pct"], _fmt_pf(m["pf"])))

    # Unclassified
    classified = set(t for tl in SECTORS.values() for t in tl)
    unclass = trades[~trades["ticker"].isin(classified)]
    if len(unclass) > 0:
        m = compute_metrics(unclass)
        print("  %14s | %4d | %+7.2f | %5.1f%% | %7s" % (
            "other", m["N"], m["mean_pct"], m["wr_pct"], _fmt_pf(m["pf"])))


def robustness_r4_random(events_df, ticker_4h, ticker_trading_days, config):
    """R4: Random Entry Comparison -- 1000 iterations, seed=42."""
    print("\n" + "=" * 60)
    print("=== R4: Random Entry Comparison ===")
    print("=" * 60)

    # Get actual trades first
    actual_trades = run_backtest(events_df, ticker_4h, ticker_trading_days, **config)
    actual_m = compute_metrics(actual_trades)
    actual_pf = actual_m["pf"]
    print("Actual strategy: N=%d, PF=%s" % (actual_m["N"], _fmt_pf(actual_pf)))

    if actual_trades.empty:
        print("  No actual trades to compare.")
        return False

    max_hold = config.get("max_hold", 10)
    gap_threshold = config.get("gap_threshold", 3.0)
    n_iterations = 1000
    random_pfs = []

    rng = random.Random(42)

    # Pre-filter events for speed
    filtered_events = events_df[events_df["gap_pct"].abs() >= gap_threshold]

    for iteration in range(n_iterations):
        random_rets = []
        for _, ev in filtered_events.iterrows():
            ticker = ev["ticker"]
            if ticker not in ticker_4h:
                continue

            entry_price = ev["entry_price"]
            if entry_price is None or (isinstance(entry_price, float) and np.isnan(entry_price)):
                continue

            bars_4h = ticker_4h[ticker]
            trading_days = ticker_trading_days[ticker]
            fwd = get_forward_bars(bars_4h, ticker, ev["date"], trading_days, max_hold)

            if len(fwd) < max_hold:
                continue

            exit_price = fwd[max_hold - 1]["Close"]
            raw_ret = (exit_price - entry_price) / entry_price * 100
            rand_sign = rng.choice([1, -1])
            random_rets.append(raw_ret * rand_sign)

        if random_rets:
            rets_arr = np.array(random_rets)
            gp = rets_arr[rets_arr > 0].sum()
            gl = abs(rets_arr[rets_arr <= 0].sum())
            rpf = gp / gl if gl > 0 else float("inf")
            random_pfs.append(rpf)

    if not random_pfs:
        print("  Could not generate random comparisons.")
        return False

    random_pfs_arr = np.array([p for p in random_pfs if p != float("inf")])
    if len(random_pfs_arr) == 0:
        print("  All random PFs infinite.")
        return False

    mean_rpf = np.mean(random_pfs_arr)
    std_rpf = np.std(random_pfs_arr)
    ci_low = np.percentile(random_pfs_arr, 2.5)
    ci_high = np.percentile(random_pfs_arr, 97.5)

    beats_random = actual_pf > ci_high

    print("\n  Random entry (%d iterations):" % n_iterations)
    print("    Mean PF: %.2f" % mean_rpf)
    print("    Std PF:  %.2f" % std_rpf)
    print("    95%% CI:  [%.2f, %.2f]" % (ci_low, ci_high))
    print("\n  Our PF: %s  vs  Random CI upper: %.2f" % (_fmt_pf(actual_pf), ci_high))
    print("  Beats random: %s" % ("YES" if beats_random else "NO"))

    return beats_random


def robustness_r5_earnings(events_df_nonearnings, ticker_4h, ticker_trading_days,
                           earnings_dates, config):
    """R5: Earnings vs Non-Earnings Comparison.

    Run same reversal strategy ON earnings days (the ones we excluded).
    Compare: non-earnings shock reversals vs earnings shock reversals.
    If non-earnings much better -> earnings exclusion filter validated.
    """
    print("\n" + "=" * 60)
    print("=== R5: Earnings vs Non-Earnings Comparison ===")
    print("=" * 60)

    # Non-earnings trades (our main strategy)
    ne_trades = run_backtest(events_df_nonearnings, ticker_4h, ticker_trading_days,
                             **config)
    ne_m = compute_metrics(ne_trades)

    # Build earnings shock events
    earnings_events = build_shock_events(
        ticker_4h, ticker_trading_days, earnings_dates,
        gap_threshold=config.get("gap_threshold", 3.0),
        include_earnings=True
    )

    # Run same strategy on earnings-day shocks
    e_trades = run_backtest(earnings_events, ticker_4h, ticker_trading_days,
                            **config)
    e_m = compute_metrics(e_trades)

    print("\n  %16s | %4s | %7s | %6s | %7s" % ("Type", "N", "Mean%", "WR%", "PF"))
    print("  " + "-" * 48)
    print("  %16s | %4d | %+7.2f | %5.1f%% | %7s" % (
        "Non-earnings", ne_m["N"], ne_m["mean_pct"], ne_m["wr_pct"], _fmt_pf(ne_m["pf"])))
    print("  %16s | %4d | %+7.2f | %5.1f%% | %7s" % (
        "Earnings", e_m["N"], e_m["mean_pct"], e_m["wr_pct"], _fmt_pf(e_m["pf"])))

    # Compare
    ne_better = ne_m["pf"] > e_m["pf"] if e_m["N"] > 0 else True
    similar = (abs(ne_m["pf"] - e_m["pf"]) < 0.3) if e_m["N"] > 0 else False

    if similar:
        print("\n  Result: Similar PF -> earnings exclusion may not add value")
        validated = False
    elif ne_better:
        print("\n  Result: Non-earnings much better -> earnings exclusion VALIDATED")
        validated = True
    else:
        print("\n  Result: Earnings shocks reverse better -> exclusion hurts")
        validated = False

    return validated, ne_m, e_m


# ---------------------------------------------------------------------------
# Part F: Final Verdict
# ---------------------------------------------------------------------------

def print_final_verdict(config, base_m, p_value, loto_impact, loyo_impact,
                        beats_random, earnings_validated):
    """Print the final robustness scorecard and verdict."""
    print("\n")
    print("=" * 60)
    print("=== No-News Shock Reversal \u2014 Final Verdict ===")
    print("=" * 60)

    p_s = "%.4f" % p_value if p_value is not None else "N/A"

    print("\nBest config: gap>=%.1f%%, hold=%d, exit=%s, dir=%s" % (
        config["gap_threshold"], config["max_hold"],
        config["exit_strategy"], config["direction"]))
    print("N: %d | Mean: %.2f%% | WR: %.1f%% | PF: %s | p-value: %s" % (
        base_m["N"], base_m["mean_pct"], base_m["wr_pct"],
        _fmt_pf(base_m["pf"]), p_s))

    # Criteria
    n_ok = base_m["N"] >= 40
    wr_ok = base_m["wr_pct"] >= 55
    pf_ok = base_m["pf"] >= 1.5
    p_ok = (p_value is not None and p_value < 0.05)
    loto_ok = loto_impact < 20
    loyo_ok = loyo_impact < 25
    random_ok = beats_random
    earnings_ok = earnings_validated

    checks = [
        ("N >= 40 (S54 expected 40-90)", n_ok),
        ("WR >= 55%", wr_ok),
        ("PF >= 1.5", pf_ok),
        ("p < 0.05", p_ok),
        ("LOTO < 20%", loto_ok),
        ("LOYO < 25%", loyo_ok),
        ("Beats random", random_ok),
        ("Non-earnings > earnings (exclusion validated)", earnings_ok),
    ]

    print("\nRobustness scorecard:")
    for label, ok in checks:
        mark = "X" if ok else " "
        print("  [%s] %s" % (mark, label))

    score = sum(ok for _, ok in checks)
    print("\nScore: %d/8" % score)

    if score >= 6:
        verdict = "VALIDATED"
    elif score >= 4:
        verdict = "MARGINAL"
    else:
        verdict = "REJECTED"

    print("VERDICT: %s" % verdict)
    print("\nThresholds: N>=40, WR>=55%%, PF>=1.5, LOTO<20%%, LOYO<25%%")
    return verdict, score


# ---------------------------------------------------------------------------
# Part G: Data Loading & Main
# ---------------------------------------------------------------------------

def load_data(gap_threshold=3.0):
    """Load all data and build shock events."""
    print("=" * 60)
    print("No-News Shock Reversal \u2014 Data Prep")
    print("=" * 60)

    # Load earnings dates for exclusion
    earnings_dates = load_earnings_dates()
    n_earn_tickers = len(earnings_dates)
    n_earn_dates = sum(len(v) for v in earnings_dates.values())
    print("Earnings dates loaded: %d date entries across %d tickers" % (
        n_earn_dates, n_earn_tickers))

    # Load M5 data
    print("\nLoading M5 data and synthesizing 4H bars...")
    ticker_4h = {}
    ticker_trading_days = {}
    for ticker in EQUITY_TICKERS:
        try:
            m5 = load_m5_regsess(ticker)
            bars_4h = synthesize_4h_bars(m5)
            ticker_4h[ticker] = bars_4h
            trading_days = get_trading_days(bars_4h)
            ticker_trading_days[ticker] = trading_days
            print("  %s: %d M5 bars -> %d 4H bars, %d days (%s to %s)" % (
                ticker, len(m5), len(bars_4h), len(trading_days),
                trading_days[0], trading_days[-1]))
        except (FileNotFoundError, ValueError) as e:
            print("  %s: SKIPPED -- %s" % (ticker, e))

    # Build non-earnings shock events
    print("\nBuilding non-earnings shock events (gap >= %.1f%%)..." % gap_threshold)
    events_df = build_shock_events(ticker_4h, ticker_trading_days, earnings_dates,
                                   gap_threshold=gap_threshold)

    n_total = len(events_df)
    if n_total == 0:
        print("No shock events found. Try lower gap threshold.")
        sys.exit(1)

    tickers_with_events = events_df["ticker"].nunique()
    print("\nShock events found: %d" % n_total)
    print("Tickers with events: %d" % tickers_with_events)
    print("Date range: %s to %s" % (events_df["date"].min(), events_df["date"].max()))
    print("Long reversals (gap down): %d" % (events_df["reversal_dir"] == "LONG").sum())
    print("Short reversals (gap up): %d" % (events_df["reversal_dir"] == "SHORT").sum())
    print("Mean |gap|: %.2f%%" % events_df["gap_pct"].abs().mean())

    return events_df, ticker_4h, ticker_trading_days, earnings_dates


def run_robustness(events_df, ticker_4h, ticker_trading_days, earnings_dates,
                   config=None):
    """Run all robustness checks R1-R5 and print final verdict."""
    if config is None:
        config = BEST_CONFIG.copy()

    print("\n" + "=" * 60)
    print("=== No-News Shock Reversal \u2014 Robustness Checks ===")
    print("=" * 60)
    print("Config: gap>=%.1f%%, hold=%d, exit=%s, dir=%s" % (
        config["gap_threshold"], config["max_hold"],
        config["exit_strategy"], config["direction"]))

    # Baseline metrics
    base_trades = run_backtest(events_df, ticker_4h, ticker_trading_days, **config)
    base_m = compute_metrics(base_trades)

    # p-value
    p_value = None
    if HAS_SCIPY and not base_trades.empty and len(base_trades) >= 2:
        _, p_value = scipy_stats.ttest_1samp(base_trades["return_pct"], 0)

    # R1: LOTO
    loto_impact, _ = robustness_r1_loto(events_df, ticker_4h, ticker_trading_days,
                                         config)

    # R2: LOYO
    loyo_impact, _ = robustness_r2_loyo(events_df, ticker_4h, ticker_trading_days,
                                         config)

    # R3: Sector breakdown
    robustness_r3_sector(events_df, ticker_4h, ticker_trading_days, config)

    # R4: Random entry comparison
    beats_random = robustness_r4_random(events_df, ticker_4h, ticker_trading_days,
                                         config)

    # R5: Earnings vs non-earnings
    earnings_validated, _, _ = robustness_r5_earnings(
        events_df, ticker_4h, ticker_trading_days, earnings_dates, config)

    # Final verdict
    verdict, score = print_final_verdict(
        config, base_m, p_value, loto_impact, loyo_impact,
        beats_random, earnings_validated)

    return verdict, score


def main():
    parser = argparse.ArgumentParser(
        description="No-News Shock Reversal Backtest (CC-NONEWS-4)")
    parser.add_argument("--sweep", action="store_true",
                        help="Run parameter sweeps")
    parser.add_argument("--robustness", action="store_true",
                        help="Run robustness checks R1-R5 with final verdict")
    parser.add_argument("--gap", type=float, default=3.0,
                        help="Gap threshold (default: 3.0%%)")
    parser.add_argument("--hold", type=int, default=10,
                        help="Max hold bars (default: 10)")
    parser.add_argument("--exit", type=str, default="fixed_10",
                        choices=["fixed_4", "fixed_6", "fixed_8", "fixed_10",
                                 "fixed_15", "fixed_20", "trailing50", "midpoint"],
                        help="Exit strategy (default: fixed_10)")
    parser.add_argument("--direction", type=str, default="both",
                        choices=["both", "long", "short"],
                        help="Trade direction (default: both)")
    args = parser.parse_args()

    config = {
        "gap_threshold": args.gap,
        "max_hold": args.hold,
        "exit_strategy": args.exit,
        "direction": args.direction,
    }

    events_df, ticker_4h, ticker_trading_days, earnings_dates = load_data(
        gap_threshold=args.gap)

    # Save events
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    events_df.to_csv(_EVENTS_CSV, index=False)
    print("\nEvents saved to: %s" % _EVENTS_CSV)

    # Always run baseline
    trades, base_m = run_baseline(events_df, ticker_4h, ticker_trading_days, config)

    # Save trades
    if not trades.empty:
        trades.to_csv(_TRADES_CSV, index=False)
        print("Trades saved to: %s" % _TRADES_CSV)

    # Sweep mode
    if args.sweep:
        best_cfg = run_sweep(events_df, ticker_4h, ticker_trading_days)
        config = best_cfg

    # Robustness mode
    if args.robustness:
        run_robustness(events_df, ticker_4h, ticker_trading_days,
                       earnings_dates, config)


if __name__ == "__main__":
    main()
