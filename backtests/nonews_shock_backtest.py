"""
No-News Shock Reversal Backtest — Baseline + Parameter Sweeps.

Tests the hypothesis: stocks that experience large intraday moves WITHOUT
earnings news tend to revert (mean-revert) over subsequent days.

Shock detection:
  - Daily return = (close - prev_close) / prev_close * 100
  - |daily_return| >= shock_threshold => shock day
  - DOWN_SHOCK (return < 0) => enter LONG reversal
  - UP_SHOCK   (return > 0) => enter SHORT reversal

Filters:
  - No-news: exclude earnings day +/- 1 trading day
  - Idiosyncratic: |stock_return| / |SPY_return| >= multiplier
  - VIX regime: filter by VIXY proxy level

Exit:
  - Retracement target hit (% of shock bar retraced), OR
  - Max hold period (trading days) reached

Reads:
  - backtester/data/fmp_earnings.csv
  - Fetched_Data/{TICKER}_data.csv (M5 OHLCV bars, IST-encoded)

Usage:
    python backtests/nonews_shock_backtest.py            # baseline only
    python backtests/nonews_shock_backtest.py --sweep     # baseline + parameter sweeps
"""

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from utils.data_loader import load_m5_regsess

# --- Paths ---
_EARNINGS_CSV = _REPO_ROOT / "backtester" / "data" / "fmp_earnings.csv"
_OUTPUT_DIR = _REPO_ROOT / "backtest_output"

# Equity tickers (exclude VIXY, crypto)
_EQUITY_TICKERS = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU",
    "C", "COIN", "COST", "GOOGL", "GS", "INTC", "JPM", "MARA",
    "META", "MSFT", "MSTR", "MU", "NVDA", "PLTR", "SMCI",
    "TSLA", "TSM", "V",
]


# ---------------------------------------------------------------------------
# Part A: Data Preparation
# ---------------------------------------------------------------------------

def synthesize_daily_bars(m5_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate M5 bars into daily OHLCV bars."""
    df = m5_df.copy()
    df["trading_day"] = df["Datetime"].dt.date

    daily = df.groupby(["Ticker", "trading_day"]).agg(
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
        Volume=("Volume", "sum"),
    ).reset_index()

    daily = daily.sort_values(["Ticker", "trading_day"]).reset_index(drop=True)
    return daily


def load_earnings_exclusions() -> set:
    """Build set of (ticker, date) pairs to exclude (earnings +/- 1 day)."""
    if not _EARNINGS_CSV.exists():
        print(f"WARNING: Earnings CSV not found: {_EARNINGS_CSV}")
        print("  Proceeding without earnings filter.")
        return set()

    df = pd.read_csv(_EARNINGS_CSV)
    exclusions = set()

    for _, row in df.iterrows():
        ticker = row["ticker"]
        try:
            edate = pd.Timestamp(row["earnings_date"]).date()
        except Exception:
            continue
        # Exclude earnings day and +/- 1 calendar day
        for offset in [-1, 0, 1]:
            excl_date = edate + pd.Timedelta(days=offset)
            exclusions.add((ticker, excl_date))

    return exclusions


def build_vix_proxy(daily_vixy: pd.DataFrame) -> dict:
    """Build date -> VIXY close mapping as VIX proxy."""
    vix = {}
    for _, row in daily_vixy.iterrows():
        vix[row["trading_day"]] = row["Close"]
    return vix


def detect_shocks(ticker_daily: dict, spy_daily: pd.DataFrame,
                  earnings_exclusions: set,
                  shock_threshold: float = 2.0,
                  idio_multiplier: float = 1.5) -> pd.DataFrame:
    """Detect shock events across all tickers.

    Returns DataFrame with columns:
        ticker, date, prev_close, shock_close, daily_return_pct,
        spy_return_pct, direction (DOWN_SHOCK / UP_SHOCK)
    """
    # Build SPY return lookup
    spy = spy_daily.sort_values("trading_day").reset_index(drop=True)
    spy["prev_close"] = spy["Close"].shift(1)
    spy["spy_ret"] = (spy["Close"] - spy["prev_close"]) / spy["prev_close"] * 100
    spy_ret_map = dict(zip(spy["trading_day"], spy["spy_ret"]))

    events = []

    for ticker, daily in ticker_daily.items():
        if ticker == "SPY":
            continue

        df = daily.sort_values("trading_day").reset_index(drop=True)
        df["prev_close"] = df["Close"].shift(1)
        df["daily_ret"] = (df["Close"] - df["prev_close"]) / df["prev_close"] * 100

        for i, row in df.iterrows():
            if pd.isna(row["daily_ret"]) or pd.isna(row["prev_close"]):
                continue

            ret = row["daily_ret"]

            # Shock threshold check
            if abs(ret) < shock_threshold:
                continue

            day = row["trading_day"]

            # No-news filter
            if (ticker, day) in earnings_exclusions:
                continue

            # Idiosyncratic filter
            spy_ret = spy_ret_map.get(day)
            if spy_ret is not None and abs(spy_ret) > 0.01:
                ratio = abs(ret) / abs(spy_ret)
                if ratio < idio_multiplier:
                    continue
            # If SPY didn't move (or no data), any stock shock is idiosyncratic

            direction = "DOWN_SHOCK" if ret < 0 else "UP_SHOCK"

            events.append({
                "ticker": ticker,
                "date": day,
                "prev_close": round(row["prev_close"], 4),
                "shock_close": round(row["Close"], 4),
                "shock_high": round(row["High"], 4),
                "shock_low": round(row["Low"], 4),
                "daily_return_pct": round(ret, 4),
                "spy_return_pct": round(spy_ret, 4) if spy_ret is not None else None,
                "direction": direction,
            })

    return pd.DataFrame(events) if events else pd.DataFrame()


# ---------------------------------------------------------------------------
# Part B: Trade Simulation
# ---------------------------------------------------------------------------

def simulate_reversal_trades(shocks_df: pd.DataFrame, ticker_daily: dict,
                             max_hold: int = 5,
                             retrace_pct: float = 50.0,
                             direction_filter: str = "both",
                             vix_proxy: dict = None,
                             vix_filter: str = "all") -> pd.DataFrame:
    """Simulate reversal trades from shock events.

    Entry: close of shock day (reversal direction).
    Exit: retracement target hit OR max_hold trading days.

    Args:
        shocks_df: shock events from detect_shocks()
        ticker_daily: {ticker: daily_bars DataFrame}
        max_hold: max holding period in trading days
        retrace_pct: % of shock range to retrace for target exit
        direction_filter: "both", "down" (long reversals only), "up" (short reversals only)
        vix_proxy: {date: vixy_close} for VIX filtering
        vix_filter: "all", "below20", "above25", "20to25"
    """
    if shocks_df.empty:
        return pd.DataFrame()

    df = shocks_df.copy()

    # Direction filter
    if direction_filter == "down":
        df = df[df["direction"] == "DOWN_SHOCK"]
    elif direction_filter == "up":
        df = df[df["direction"] == "UP_SHOCK"]

    # VIX filter
    if vix_proxy and vix_filter != "all":
        keep = []
        for _, row in df.iterrows():
            vix_val = vix_proxy.get(row["date"])
            if vix_val is None:
                continue
            if vix_filter == "below20" and vix_val >= 20:
                continue
            if vix_filter == "above25" and vix_val < 25:
                continue
            if vix_filter == "20to25" and (vix_val < 20 or vix_val >= 25):
                continue
            keep.append(True)
            continue
        # Rebuild using index-based filtering
        keep_idx = []
        for idx, row in df.iterrows():
            vix_val = vix_proxy.get(row["date"])
            if vix_val is None:
                continue
            if vix_filter == "below20" and vix_val >= 20:
                continue
            if vix_filter == "above25" and vix_val < 25:
                continue
            if vix_filter == "20to25" and (vix_val < 20 or vix_val >= 25):
                continue
            keep_idx.append(idx)
        df = df.loc[keep_idx]

    if df.empty:
        return pd.DataFrame()

    trades = []

    for _, shock in df.iterrows():
        ticker = shock["ticker"]
        shock_date = shock["date"]
        prev_close = shock["prev_close"]
        shock_close = shock["shock_close"]
        direction = shock["direction"]

        daily = ticker_daily.get(ticker)
        if daily is None:
            continue

        daily_sorted = daily.sort_values("trading_day").reset_index(drop=True)
        trading_days = daily_sorted["trading_day"].tolist()

        # Find shock day index
        try:
            shock_idx = trading_days.index(shock_date)
        except ValueError:
            continue

        # Entry at shock close
        entry_price = shock_close

        # Compute shock range and retracement target
        shock_range = abs(shock_close - prev_close)
        retrace_amount = shock_range * retrace_pct / 100.0

        if direction == "DOWN_SHOCK":
            # Long reversal: target is above entry
            target_price = entry_price + retrace_amount
        else:
            # Short reversal: target is below entry
            target_price = entry_price - retrace_amount

        # Forward days
        exit_price = None
        exit_reason = None
        days_held = 0

        for d in range(1, max_hold + 1):
            fwd_idx = shock_idx + d
            if fwd_idx >= len(daily_sorted):
                break

            fwd_row = daily_sorted.iloc[fwd_idx]
            days_held = d

            # Check if target hit during the day using high/low
            if direction == "DOWN_SHOCK":
                if fwd_row["High"] >= target_price:
                    exit_price = target_price
                    exit_reason = "retrace_target"
                    break
            else:
                if fwd_row["Low"] <= target_price:
                    exit_price = target_price
                    exit_reason = "retrace_target"
                    break

        # If no target hit, exit at close of last held day
        if exit_price is None and days_held > 0:
            last_idx = shock_idx + days_held
            if last_idx < len(daily_sorted):
                exit_price = daily_sorted.iloc[last_idx]["Close"]
                exit_reason = "max_hold"

        if exit_price is None:
            continue

        # Compute return
        if direction == "DOWN_SHOCK":
            # Long: buy at entry, sell at exit
            ret_pct = (exit_price - entry_price) / entry_price * 100
        else:
            # Short: sell at entry, buy at exit
            ret_pct = (entry_price - exit_price) / entry_price * 100

        trades.append({
            "ticker": ticker,
            "shock_date": shock_date,
            "direction": direction,
            "prev_close": prev_close,
            "entry_price": entry_price,
            "exit_price": round(exit_price, 4),
            "target_price": round(target_price, 4),
            "return_pct": round(ret_pct, 4),
            "days_held": days_held,
            "exit_reason": exit_reason,
            "shock_pct": shock["daily_return_pct"],
            "spy_return_pct": shock["spy_return_pct"],
        })

    return pd.DataFrame(trades) if trades else pd.DataFrame()


# ---------------------------------------------------------------------------
# Part C: Metrics
# ---------------------------------------------------------------------------

def compute_metrics(trades_df: pd.DataFrame) -> dict:
    """Compute standard metrics from trades DataFrame."""
    if trades_df.empty or len(trades_df) == 0:
        return {"N": 0, "mean_pct": 0.0, "wr_pct": 0.0, "pf": 0.0, "avg_hold": 0.0}

    rets = trades_df["return_pct"]
    n = len(rets)
    mean_r = rets.mean()
    wr = (rets > 0).mean() * 100
    gp = rets[rets > 0].sum()
    gl = abs(rets[rets <= 0].sum())
    pf = gp / gl if gl > 0 else float("inf")
    avg_hold = trades_df["days_held"].mean() if "days_held" in trades_df.columns else 0.0

    return {"N": n, "mean_pct": mean_r, "wr_pct": wr, "pf": pf, "avg_hold": avg_hold}


def fmt_pf(pf):
    return f"{pf:.2f}" if pf != float("inf") else "  inf"


# ---------------------------------------------------------------------------
# Part D: Baseline (TEST 0)
# ---------------------------------------------------------------------------

def run_baseline(shocks_df, ticker_daily, vix_proxy):
    """TEST 0: Baseline with default parameters."""
    print("\n" + "=" * 60)
    print("=== TEST 0: No-News Shock Reversal Baseline ===")
    print("=" * 60)
    print("  Params: shock>=2%, mult>=1.5, max_hold=5, retrace=50%, all VIX")

    trades = simulate_reversal_trades(
        shocks_df, ticker_daily,
        max_hold=5, retrace_pct=50.0,
        direction_filter="both",
        vix_proxy=vix_proxy, vix_filter="all",
    )

    m = compute_metrics(trades)
    print(f"\n  N: {m['N']}")
    print(f"  Mean return: {m['mean_pct']:.2f}%")
    print(f"  Win rate: {m['wr_pct']:.1f}%")
    print(f"  Profit factor: {fmt_pf(m['pf'])}")
    print(f"  Avg hold: {m['avg_hold']:.1f} days")

    if not trades.empty:
        longs = trades[trades["direction"] == "DOWN_SHOCK"]
        shorts = trades[trades["direction"] == "UP_SHOCK"]
        lm = compute_metrics(longs)
        sm = compute_metrics(shorts)
        print(f"\n  LONG reversals (DOWN_SHOCK):  N={lm['N']}, Mean={lm['mean_pct']:.2f}%, "
              f"WR={lm['wr_pct']:.1f}%, PF={fmt_pf(lm['pf'])}")
        print(f"  SHORT reversals (UP_SHOCK):   N={sm['N']}, Mean={sm['mean_pct']:.2f}%, "
              f"WR={sm['wr_pct']:.1f}%, PF={fmt_pf(sm['pf'])}")

        # Exit reason breakdown
        reasons = trades["exit_reason"].value_counts()
        print(f"\n  Exit reasons:")
        for reason, count in reasons.items():
            pct = count / len(trades) * 100
            print(f"    {reason}: {count} ({pct:.1f}%)")

    return trades


# ---------------------------------------------------------------------------
# Part E: Sweep Tests 1-7
# ---------------------------------------------------------------------------

def sweep_test1(shocks_all, ticker_daily, vix_proxy):
    """TEST 1: Shock Threshold sweep."""
    print("\n" + "=" * 60)
    print("=== TEST 1: Shock Threshold Sweep ===")
    print("=" * 60)

    values = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
    hdr = f" {'Shock%':>7} | {'N':>5} | {'Mean%':>8} | {'WR%':>7} | {'PF':>7}"
    print(hdr)
    print("-" * len(hdr))

    best_val, best_pf = 2.0, 0
    for v in values:
        # Re-detect shocks with different threshold (keep idio_mult=1.5 default)
        trades = _run_with_shock_threshold(
            ticker_daily, v, 1.5, vix_proxy,
            max_hold=5, retrace_pct=50.0,
        )
        m = compute_metrics(trades)
        print(f" {v:>6.1f}% | {m['N']:>5} | {m['mean_pct']:>8.2f} | "
              f"{m['wr_pct']:>7.1f} | {fmt_pf(m['pf']):>7}")
        if m["N"] >= 5 and m["pf"] > best_pf:
            best_pf = m["pf"]
            best_val = v

    print(f"\n  Best shock threshold: {best_val}% (PF={fmt_pf(best_pf)})")
    return best_val


def sweep_test2(shocks_all, ticker_daily, vix_proxy):
    """TEST 2: Idiosyncratic Multiplier sweep."""
    print("\n" + "=" * 60)
    print("=== TEST 2: Idiosyncratic Multiplier Sweep ===")
    print("=" * 60)

    values = [1.0, 1.25, 1.5, 2.0, 3.0]
    hdr = f" {'Mult':>7} | {'N':>5} | {'Mean%':>8} | {'WR%':>7} | {'PF':>7}"
    print(hdr)
    print("-" * len(hdr))

    best_val, best_pf = 1.5, 0
    for v in values:
        trades = _run_with_shock_threshold(
            ticker_daily, 2.0, v, vix_proxy,
            max_hold=5, retrace_pct=50.0,
        )
        m = compute_metrics(trades)
        print(f" {v:>6.2f}x | {m['N']:>5} | {m['mean_pct']:>8.2f} | "
              f"{m['wr_pct']:>7.1f} | {fmt_pf(m['pf']):>7}")
        if m["N"] >= 5 and m["pf"] > best_pf:
            best_pf = m["pf"]
            best_val = v

    print(f"\n  Best idiosyncratic multiplier: {best_val}x (PF={fmt_pf(best_pf)})")
    return best_val


def sweep_test3(shocks_df, ticker_daily, vix_proxy):
    """TEST 3: Max Hold Period sweep."""
    print("\n" + "=" * 60)
    print("=== TEST 3: Max Hold Period Sweep ===")
    print("=" * 60)

    values = [2, 3, 5, 7, 10]
    hdr = f" {'Days':>7} | {'N':>5} | {'Mean%':>8} | {'WR%':>7} | {'PF':>7} | {'AvgHold':>7}"
    print(hdr)
    print("-" * len(hdr))

    best_val, best_pf = 5, 0
    for v in values:
        trades = simulate_reversal_trades(
            shocks_df, ticker_daily,
            max_hold=v, retrace_pct=50.0,
            vix_proxy=vix_proxy, vix_filter="all",
        )
        m = compute_metrics(trades)
        print(f" {v:>6}d | {m['N']:>5} | {m['mean_pct']:>8.2f} | "
              f"{m['wr_pct']:>7.1f} | {fmt_pf(m['pf']):>7} | {m['avg_hold']:>7.1f}")
        if m["N"] >= 5 and m["pf"] > best_pf:
            best_pf = m["pf"]
            best_val = v

    print(f"\n  Best max hold: {best_val}d (PF={fmt_pf(best_pf)})")
    return best_val


def sweep_test4(shocks_df, ticker_daily, vix_proxy):
    """TEST 4: Retracement Target sweep."""
    print("\n" + "=" * 60)
    print("=== TEST 4: Retracement Target Sweep ===")
    print("=" * 60)

    values = [25, 50, 75, 100]
    hdr = f" {'Retrace%':>8} | {'N':>5} | {'Mean%':>8} | {'WR%':>7} | {'PF':>7}"
    print(hdr)
    print("-" * len(hdr))

    best_val, best_pf = 50, 0
    for v in values:
        trades = simulate_reversal_trades(
            shocks_df, ticker_daily,
            max_hold=5, retrace_pct=float(v),
            vix_proxy=vix_proxy, vix_filter="all",
        )
        m = compute_metrics(trades)
        print(f" {v:>7}% | {m['N']:>5} | {m['mean_pct']:>8.2f} | "
              f"{m['wr_pct']:>7.1f} | {fmt_pf(m['pf']):>7}")
        if m["N"] >= 5 and m["pf"] > best_pf:
            best_pf = m["pf"]
            best_val = v

    print(f"\n  Best retracement target: {best_val}% (PF={fmt_pf(best_pf)})")
    return best_val


def sweep_test5(shocks_df, ticker_daily, vix_proxy):
    """TEST 5: Direction Split."""
    print("\n" + "=" * 60)
    print("=== TEST 5: Direction Split ===")
    print("=" * 60)

    hdr = f" {'Direction':>12} | {'N':>5} | {'Mean%':>8} | {'WR%':>7} | {'PF':>7}"
    print(hdr)
    print("-" * len(hdr))

    for label, filt in [("DOWN (long)", "down"), ("UP (short)", "up"), ("Combined", "both")]:
        trades = simulate_reversal_trades(
            shocks_df, ticker_daily,
            max_hold=5, retrace_pct=50.0,
            direction_filter=filt,
            vix_proxy=vix_proxy, vix_filter="all",
        )
        m = compute_metrics(trades)
        print(f" {label:>12} | {m['N']:>5} | {m['mean_pct']:>8.2f} | "
              f"{m['wr_pct']:>7.1f} | {fmt_pf(m['pf']):>7}")


def sweep_test6(shocks_df, ticker_daily, vix_proxy):
    """TEST 6: VIX Regime Filter."""
    print("\n" + "=" * 60)
    print("=== TEST 6: VIX Regime Filter ===")
    print("=" * 60)

    regimes = [
        ("All regimes", "all"),
        ("VIX < 20", "below20"),
        ("VIX >= 25", "above25"),
        ("VIX 20-25", "20to25"),
    ]
    hdr = f" {'Regime':>12} | {'N':>5} | {'Mean%':>8} | {'WR%':>7} | {'PF':>7}"
    print(hdr)
    print("-" * len(hdr))

    best_label, best_filter, best_pf = "All regimes", "all", 0
    for label, vf in regimes:
        trades = simulate_reversal_trades(
            shocks_df, ticker_daily,
            max_hold=5, retrace_pct=50.0,
            vix_proxy=vix_proxy, vix_filter=vf,
        )
        m = compute_metrics(trades)
        print(f" {label:>12} | {m['N']:>5} | {m['mean_pct']:>8.2f} | "
              f"{m['wr_pct']:>7.1f} | {fmt_pf(m['pf']):>7}")
        if m["N"] >= 5 and m["pf"] > best_pf:
            best_pf = m["pf"]
            best_label = label
            best_filter = vf

    print(f"\n  Best VIX regime: {best_label} (PF={fmt_pf(best_pf)})")
    return best_filter


def sweep_test7(ticker_daily, vix_proxy, earnings_exclusions,
                best_shock, best_mult, best_hold, best_retrace, best_vix):
    """TEST 7: Combined Best + specific combos."""
    print("\n" + "=" * 60)
    print("=== TEST 7: Combined Best + Specific Combos ===")
    print("=" * 60)

    combos = [
        ("Best sweep", best_shock, best_mult, best_hold, best_retrace, best_vix),
        ("Combo A", 3.0, 2.0, 5, 50.0, "all"),
        ("Combo B", 2.0, 1.5, 3, 50.0, "below20"),
        ("Combo C", 4.0, 2.0, 7, 75.0, "above25"),
    ]

    hdr = f" {'Combo':>12} | {'N':>5} | {'Mean%':>8} | {'WR%':>7} | {'PF':>7}"
    print(hdr)
    print("-" * len(hdr))

    for label, shock_t, mult, hold, retrace, vf in combos:
        trades = _run_with_shock_threshold(
            ticker_daily, shock_t, mult, vix_proxy,
            max_hold=hold, retrace_pct=retrace,
            direction_filter="both", vix_filter=vf,
            earnings_exclusions=earnings_exclusions,
        )
        m = compute_metrics(trades)
        print(f" {label:>12} | {m['N']:>5} | {m['mean_pct']:>8.2f} | "
              f"{m['wr_pct']:>7.1f} | {fmt_pf(m['pf']):>7}")
        if label != "Best sweep":
            desc = (f"    shock>={shock_t}%, mult>={mult}x, hold<={hold}d, "
                    f"retrace={retrace:.0f}%, vix={vf}")
            print(desc)


# ---------------------------------------------------------------------------
# Helpers for re-detecting shocks with different params
# ---------------------------------------------------------------------------

# Module-level cache populated during load_data()
_spy_daily = None
_earnings_exclusions = None


def _run_with_shock_threshold(ticker_daily, shock_threshold, idio_multiplier,
                              vix_proxy, max_hold=5, retrace_pct=50.0,
                              direction_filter="both", vix_filter="all",
                              earnings_exclusions=None):
    """Re-detect shocks with custom threshold/multiplier, then simulate trades."""
    global _spy_daily, _earnings_exclusions

    excl = earnings_exclusions if earnings_exclusions is not None else _earnings_exclusions
    if excl is None:
        excl = set()

    spy_daily = ticker_daily.get("SPY")
    if spy_daily is None:
        spy_daily = _spy_daily

    shocks = detect_shocks(
        ticker_daily, spy_daily,
        earnings_exclusions=excl,
        shock_threshold=shock_threshold,
        idio_multiplier=idio_multiplier,
    )

    return simulate_reversal_trades(
        shocks, ticker_daily,
        max_hold=max_hold, retrace_pct=retrace_pct,
        direction_filter=direction_filter,
        vix_proxy=vix_proxy, vix_filter=vix_filter,
    )


# ---------------------------------------------------------------------------
# Sweep Orchestrator
# ---------------------------------------------------------------------------

def run_sweep(shocks_df, ticker_daily, vix_proxy, earnings_exclusions):
    """Run all 7 sweep tests."""
    print("\n" + "=" * 60)
    print("=== No-News Shock Reversal — Parameter Sweeps ===")
    print("=" * 60)

    # TEST 1: Shock threshold
    best_shock = sweep_test1(shocks_df, ticker_daily, vix_proxy)

    # TEST 2: Idiosyncratic multiplier
    best_mult = sweep_test2(shocks_df, ticker_daily, vix_proxy)

    # TEST 3: Max hold period
    best_hold = sweep_test3(shocks_df, ticker_daily, vix_proxy)

    # TEST 4: Retracement target
    best_retrace = sweep_test4(shocks_df, ticker_daily, vix_proxy)

    # TEST 5: Direction split
    sweep_test5(shocks_df, ticker_daily, vix_proxy)

    # TEST 6: VIX regime
    best_vix = sweep_test6(shocks_df, ticker_daily, vix_proxy)

    # TEST 7: Combined best + specific combos
    sweep_test7(ticker_daily, vix_proxy, earnings_exclusions,
                best_shock, best_mult, best_hold, float(best_retrace), best_vix)

    # Print sweep winners summary
    print("\n" + "=" * 60)
    print("=== Sweep Winners Summary ===")
    print("=" * 60)
    print(f"  Shock threshold: {best_shock}%")
    print(f"  Idiosyncratic multiplier: {best_mult}x")
    print(f"  Max hold period: {best_hold}d")
    print(f"  Retracement target: {best_retrace}%")
    print(f"  VIX regime: {best_vix}")

    # Run combined best
    best_trades = _run_with_shock_threshold(
        ticker_daily, best_shock, best_mult, vix_proxy,
        max_hold=best_hold, retrace_pct=float(best_retrace),
        direction_filter="both", vix_filter=best_vix,
        earnings_exclusions=earnings_exclusions,
    )
    m = compute_metrics(best_trades)
    print(f"\n  Combined best performance:")
    print(f"    N: {m['N']}, Mean: {m['mean_pct']:.2f}%, WR: {m['wr_pct']:.1f}%, "
          f"PF: {fmt_pf(m['pf'])}, AvgHold: {m['avg_hold']:.1f}d")

    # Verdict
    if m["N"] >= 20 and m["wr_pct"] >= 55 and m["pf"] >= 1.5:
        verdict = "PROMISING"
    elif m["N"] >= 10 and (m["wr_pct"] >= 50 or m["pf"] >= 1.2):
        verdict = "MARGINAL"
    else:
        verdict = "NO_EDGE"
    print(f"\n  VERDICT: {verdict}")


# ---------------------------------------------------------------------------
# Data Loading + Main
# ---------------------------------------------------------------------------

def load_data():
    """Load all data: M5 -> daily bars, earnings exclusions, VIX proxy."""
    global _spy_daily, _earnings_exclusions

    print("=" * 60)
    print("No-News Shock Reversal Backtest — Data Prep")
    print("=" * 60)

    # Load earnings exclusions
    earnings_exclusions = load_earnings_exclusions()
    _earnings_exclusions = earnings_exclusions
    print(f"Earnings exclusion pairs: {len(earnings_exclusions)}")

    # Load M5 and build daily bars for all tickers (including SPY)
    tickers_to_load = _EQUITY_TICKERS + ["SPY"]
    ticker_daily = {}

    print("\nLoading M5 data and synthesizing daily bars...")
    for ticker in sorted(set(tickers_to_load)):
        try:
            m5 = load_m5_regsess(ticker)
            daily = synthesize_daily_bars(m5)
            ticker_daily[ticker] = daily
            trading_days = sorted(daily["trading_day"].unique())
            print(f"  {ticker}: {len(m5)} M5 bars -> {len(daily)} daily bars "
                  f"({trading_days[0]} to {trading_days[-1]})")
        except (FileNotFoundError, ValueError) as e:
            print(f"  {ticker}: SKIPPED -- {e}")

    # SPY daily (needed for idiosyncratic filter)
    spy_daily = ticker_daily.get("SPY")
    _spy_daily = spy_daily
    if spy_daily is None:
        print("\nWARNING: SPY data not available. Idiosyncratic filter disabled.")

    # VIX proxy from VIXY
    vix_proxy = {}
    try:
        m5_vixy = load_m5_regsess("VIXY")
        daily_vixy = synthesize_daily_bars(m5_vixy)
        vix_proxy = build_vix_proxy(daily_vixy)
        print(f"\n  VIXY: {len(vix_proxy)} daily VIX proxy values")
    except (FileNotFoundError, ValueError) as e:
        print(f"\n  VIXY: SKIPPED -- {e}")
        print("  VIX regime filters will be unavailable.")

    # Detect shocks with default params
    print("\nDetecting shock events (threshold=2%, idio_mult=1.5)...")
    shocks_df = detect_shocks(
        ticker_daily, spy_daily,
        earnings_exclusions=earnings_exclusions,
        shock_threshold=2.0, idio_multiplier=1.5,
    )

    print(f"\n{'=' * 50}")
    print("=== Data Prep Summary ===")
    print(f"{'=' * 50}")
    print(f"Tickers loaded: {len(ticker_daily)}")
    print(f"Shock events (default params): {len(shocks_df)}")

    if not shocks_df.empty:
        down = (shocks_df["direction"] == "DOWN_SHOCK").sum()
        up = (shocks_df["direction"] == "UP_SHOCK").sum()
        print(f"  DOWN_SHOCK: {down}")
        print(f"  UP_SHOCK: {up}")
        print(f"  Mean |shock|: {shocks_df['daily_return_pct'].abs().mean():.2f}%")

        # Distribution
        abs_ret = shocks_df["daily_return_pct"].abs()
        for t in [2.0, 3.0, 4.0, 5.0]:
            print(f"  |shock| >= {t}%: {(abs_ret >= t).sum()}")

        # Top tickers
        top = shocks_df["ticker"].value_counts().head(5)
        print(f"\n  Top tickers by shock count:")
        for tk, cnt in top.items():
            print(f"    {tk}: {cnt}")

    return shocks_df, ticker_daily, vix_proxy, earnings_exclusions


def main():
    parser = argparse.ArgumentParser(description="No-News Shock Reversal Backtest")
    parser.add_argument("--sweep", action="store_true",
                        help="Run parameter sweeps (Tests 1-7)")
    args = parser.parse_args()

    shocks_df, ticker_daily, vix_proxy, earnings_exclusions = load_data()

    if shocks_df.empty:
        print("\nNo shock events detected. Exiting.")
        sys.exit(1)

    # Always run baseline
    run_baseline(shocks_df, ticker_daily, vix_proxy)

    # Sweep mode
    if args.sweep:
        run_sweep(shocks_df, ticker_daily, vix_proxy, earnings_exclusions)


if __name__ == "__main__":
    main()
