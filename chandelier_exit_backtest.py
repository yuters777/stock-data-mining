#!/usr/bin/env python3
"""
Chandelier Exit ATR Backtest — Phase 1
=======================================
Compare 4 ATR multiplier variants of the Chandelier Exit trailing stop
on M5 OHLCV data for NVDA, TSLA, GOOGL, META.

Entry: Simplified 4H EMA9/21 cross (long only)
Exit: Chandelier Exit with activation gate at +1R
Multipliers tested: 1.25, 1.50, 2.00, 2.25

Phase 1 of 3 | Market Structure & Trading Systems
"""

import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import timedelta
from pathlib import Path

# ─── Configuration ───────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).parent / "MarketPatterns_AI" / "Fetched_Data"
OUTPUT_DIR = Path(__file__).parent / "results" / "chandelier_exit_phase1"
TICKERS = ["NVDA", "TSLA", "GOOGL", "META"]
MULTIPLIERS = [1.25, 1.50, 2.00, 2.25]

# RTH boundaries in data timezone (IST = ET + 7h)
RTH_START_HOUR, RTH_START_MIN = 16, 30  # 9:30 AM ET
RTH_END_HOUR, RTH_END_MIN = 22, 55      # 3:55 PM ET (last M5 bar)

# 4H bar boundaries (M5 bar start times, IST)
BAR_4H_1_START = (16, 30)  # 9:30 AM ET
BAR_4H_1_END = (20, 25)    # 1:25 PM ET (last M5 bar in first 4H)
BAR_4H_2_START = (20, 30)  # 1:30 PM ET
BAR_4H_2_END = (22, 55)    # 3:55 PM ET (last M5 bar in second 4H)

# Chandelier parameters
ATR_PERIOD = 14
HH_LOOKBACK = 22
INITIAL_STOP_LOOKBACK = 5  # bars to find lowest low for 1R

# Max hold time
MAX_HOLD_DAYS = 5

# EMA periods for entry signal
EMA_FAST = 9
EMA_SLOW = 21


# ─── Data Loading ────────────────────────────────────────────────────────────

def load_m5_data(ticker):
    """Load M5 OHLCV CSV and filter to RTH bars only."""
    path = DATA_DIR / f"{ticker}_data.csv"
    df = pd.read_csv(path, parse_dates=["Datetime"])
    df = df.sort_values("Datetime").reset_index(drop=True)

    # Filter to RTH: 16:30 to 22:55 (inclusive)
    time_minutes = df["Datetime"].dt.hour * 60 + df["Datetime"].dt.minute
    rth_start = RTH_START_HOUR * 60 + RTH_START_MIN  # 990
    rth_end = RTH_END_HOUR * 60 + RTH_END_MIN        # 1375
    df = df[(time_minutes >= rth_start) & (time_minutes <= rth_end)].copy()
    df = df.reset_index(drop=True)

    # Assign trading day (date of bar)
    df["trading_day"] = df["Datetime"].dt.date
    return df


# ─── 4H Bar Construction ────────────────────────────────────────────────────

def build_4h_bars(m5_df):
    """Aggregate M5 bars into 4H bars using fixed RTH boundaries.

    Bar 1: 16:30-20:25 IST (9:30 AM - 1:25 PM ET, 48 bars)
    Bar 2: 20:30-22:55 IST (1:30 PM - 3:55 PM ET, 30 bars)
    """
    time_minutes = m5_df["Datetime"].dt.hour * 60 + m5_df["Datetime"].dt.minute
    bar1_end = BAR_4H_1_END[0] * 60 + BAR_4H_1_END[1]  # 20:25 = 1225

    m5_df = m5_df.copy()
    m5_df["bar_4h_id"] = m5_df["trading_day"].astype(str)
    m5_df.loc[time_minutes <= bar1_end, "bar_4h_id"] += "_1"
    m5_df.loc[time_minutes > bar1_end, "bar_4h_id"] += "_2"

    bars_4h = m5_df.groupby("bar_4h_id", sort=False).agg(
        Datetime=("Datetime", "last"),
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
        Volume=("Volume", "sum"),
        trading_day=("trading_day", "first"),
    ).reset_index(drop=True)

    bars_4h = bars_4h.sort_values("Datetime").reset_index(drop=True)
    return bars_4h


# ─── EMA Calculation ────────────────────────────────────────────────────────

def calc_ema(series, period):
    """Standard EMA: k = 2/(N+1)."""
    return series.ewm(span=period, adjust=False).mean()


# ─── Entry Signal Detection ─────────────────────────────────────────────────

def detect_entries(bars_4h):
    """Detect EMA9 crosses above EMA21 on 4H close.

    Returns list of (signal_datetime, trading_day, bar_index) for each cross.
    """
    ema_fast = calc_ema(bars_4h["Close"], EMA_FAST)
    ema_slow = calc_ema(bars_4h["Close"], EMA_SLOW)

    entries = []
    for i in range(1, len(bars_4h)):
        # EMA9 crosses above EMA21
        if ema_fast.iloc[i] > ema_slow.iloc[i] and ema_fast.iloc[i - 1] <= ema_slow.iloc[i - 1]:
            entries.append({
                "signal_datetime": bars_4h["Datetime"].iloc[i],
                "signal_bar_idx": i,
                "trading_day": bars_4h["trading_day"].iloc[i],
            })
    return entries


# ─── ATR Calculation (EMA-based, matching TradingView) ───────────────────────

def calc_atr_series(m5_df):
    """Calculate True Range and ATR(14) using EMA for the entire M5 series."""
    high = m5_df["High"].values
    low = m5_df["Low"].values
    close = m5_df["Close"].values

    tr = np.zeros(len(m5_df))
    tr[0] = high[0] - low[0]
    for i in range(1, len(m5_df)):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1])
        )

    # ATR as EMA of TR
    atr = np.zeros(len(m5_df))
    atr[:ATR_PERIOD] = np.nan
    if len(m5_df) >= ATR_PERIOD:
        atr[ATR_PERIOD - 1] = np.mean(tr[:ATR_PERIOD])  # seed with SMA
        k = 2.0 / (ATR_PERIOD + 1)
        for i in range(ATR_PERIOD, len(m5_df)):
            atr[i] = tr[i] * k + atr[i - 1] * (1 - k)

    return tr, atr


# ─── Chandelier Exit Backtest Engine ─────────────────────────────────────────

def run_backtest_for_ticker(ticker):
    """Run backtest for a single ticker across all multipliers.

    Returns list of trade dicts.
    """
    print(f"\n{'='*60}")
    print(f"  Processing {ticker}")
    print(f"{'='*60}")

    m5_df = load_m5_data(ticker)
    print(f"  RTH bars: {len(m5_df)}, "
          f"Date range: {m5_df['Datetime'].iloc[0]} → {m5_df['Datetime'].iloc[-1]}")

    bars_4h = build_4h_bars(m5_df)
    print(f"  4H bars: {len(bars_4h)}")

    entries = detect_entries(bars_4h)
    print(f"  EMA9/21 cross entries: {len(entries)}")

    # Pre-calculate ATR series
    _, atr_series = calc_atr_series(m5_df)

    # For each entry signal, run all 4 multipliers
    all_trades = []

    for entry_info in entries:
        signal_dt = entry_info["signal_datetime"]

        # Find the NEXT M5 bar after signal for entry (realistic execution)
        entry_idx = m5_df["Datetime"].searchsorted(signal_dt, side="right")
        if entry_idx >= len(m5_df):
            continue

        entry_bar = m5_df.iloc[entry_idx]
        entry_price = entry_bar["Open"]
        entry_dt = entry_bar["Datetime"]

        # Calculate 1R: entry - lowest low of last 5 M5 bars at entry
        lookback_start = max(0, entry_idx - INITIAL_STOP_LOOKBACK)
        lowest_low = m5_df["Low"].iloc[lookback_start:entry_idx + 1].min()
        one_r = entry_price - lowest_low
        if one_r <= 0:
            one_r = entry_price * 0.005  # fallback: 0.5% of price

        disaster_stop = entry_price - one_r

        # Run each multiplier on the same entry
        for mult in MULTIPLIERS:
            trade = simulate_trade(
                m5_df, atr_series, entry_idx, entry_price, entry_dt,
                one_r, disaster_stop, mult, ticker
            )
            if trade is not None:
                all_trades.append(trade)

    print(f"  Total trades across all multipliers: {len(all_trades)}")
    return all_trades


def simulate_trade(m5_df, atr_series, entry_idx, entry_price, entry_dt,
                   one_r, disaster_stop, multiplier, ticker):
    """Simulate a single trade with given Chandelier Exit multiplier."""

    chandelier_active = False
    chandelier_stop = 0.0
    max_price = entry_price  # for MFE tracking
    min_price = entry_price  # for MAE tracking
    one_r_reached = False
    one_r_time = None
    exit_reason = None
    exit_price = None
    exit_dt = None
    exit_idx = None

    # Calculate max hold cutoff (5 trading days)
    entry_trading_day = m5_df.iloc[entry_idx]["trading_day"]
    trading_days = sorted(m5_df["trading_day"].unique())
    day_idx = list(trading_days).index(entry_trading_day)
    max_day_idx = min(day_idx + MAX_HOLD_DAYS, len(trading_days) - 1)
    max_hold_date = trading_days[max_day_idx]

    # Walk forward bar-by-bar from entry
    for i in range(entry_idx + 1, len(m5_df)):
        bar = m5_df.iloc[i]
        current_day = bar["trading_day"]

        # Max hold check
        if current_day > max_hold_date:
            exit_reason = "max_hold_5d"
            exit_price = bar["Open"]
            exit_dt = bar["Datetime"]
            exit_idx = i
            break

        prev_close = m5_df.iloc[i - 1]["Close"]

        # Track MFE/MAE using bar high/low
        max_price = max(max_price, bar["High"])
        min_price = min(min_price, bar["Low"])

        # Check if +1R reached (using close)
        if not one_r_reached and bar["Close"] >= entry_price + one_r:
            one_r_reached = True
            one_r_time = bar["Datetime"]
            chandelier_active = True

        # Before +1R: check disaster stop
        if not chandelier_active:
            if prev_close < disaster_stop:
                # Exit at this bar's open
                exit_reason = "disaster_stop"
                exit_price = bar["Open"]
                exit_dt = bar["Datetime"]
                exit_idx = i
                break
        else:
            # Chandelier is active — calculate and check
            if i >= HH_LOOKBACK and not np.isnan(atr_series[i]):
                highest_high = m5_df["High"].iloc[i - HH_LOOKBACK + 1:i + 1].max()
                new_stop = highest_high - (multiplier * atr_series[i])
                # Trailing: can only move up
                chandelier_stop = max(chandelier_stop, new_stop)

                if prev_close < chandelier_stop:
                    exit_reason = "chandelier_stop"
                    exit_price = bar["Open"]
                    exit_dt = bar["Datetime"]
                    exit_idx = i
                    break

    # If we reached end of data without exit
    if exit_reason is None:
        exit_reason = "end_of_data"
        exit_price = m5_df.iloc[-1]["Close"]
        exit_dt = m5_df.iloc[-1]["Datetime"]
        exit_idx = len(m5_df) - 1

    # Calculate metrics
    pnl_dollars = exit_price - entry_price
    pnl_r = pnl_dollars / one_r if one_r > 0 else 0
    mfe_r = (max_price - entry_price) / one_r if one_r > 0 else 0
    mae_r = (entry_price - min_price) / one_r if one_r > 0 else 0

    # Hold time
    hold_bars = exit_idx - entry_idx
    hold_hours = hold_bars * 5 / 60  # M5 bars to hours

    # Give-back ratio
    give_back = (mfe_r - pnl_r) / mfe_r if mfe_r > 0 else 0

    return {
        "ticker": ticker,
        "multiplier": multiplier,
        "entry_datetime": entry_dt,
        "entry_price": round(entry_price, 2),
        "initial_stop_1r": round(disaster_stop, 2),
        "one_r_dollars": round(one_r, 2),
        "one_r_reached": one_r_reached,
        "one_r_time": one_r_time,
        "chandelier_activated": chandelier_active,
        "exit_datetime": exit_dt,
        "exit_price": round(exit_price, 2),
        "exit_reason": exit_reason,
        "pnl_dollars": round(pnl_dollars, 2),
        "pnl_r": round(pnl_r, 4),
        "mfe_r": round(mfe_r, 4),
        "mae_r": round(mae_r, 4),
        "give_back_ratio": round(give_back, 4),
        "hold_bars": hold_bars,
        "hold_hours": round(hold_hours, 2),
    }


# ─── Metrics Calculation ────────────────────────────────────────────────────

def calc_metrics(trades_df):
    """Calculate performance metrics for a group of trades."""
    if len(trades_df) == 0:
        return {}

    winners = trades_df[trades_df["pnl_r"] > 0]
    losers = trades_df[trades_df["pnl_r"] <= 0]

    gross_profit = winners["pnl_r"].sum() if len(winners) > 0 else 0
    gross_loss = abs(losers["pnl_r"].sum()) if len(losers) > 0 else 0

    return {
        "total_trades": len(trades_df),
        "win_rate": round(len(winners) / len(trades_df) * 100, 1) if len(trades_df) > 0 else 0,
        "avg_r": round(trades_df["pnl_r"].mean(), 4),
        "median_r": round(trades_df["pnl_r"].median(), 4),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "avg_winner_r": round(winners["pnl_r"].mean(), 4) if len(winners) > 0 else 0,
        "avg_loser_r": round(losers["pnl_r"].mean(), 4) if len(losers) > 0 else 0,
        "avg_hold_hours": round(trades_df["hold_hours"].mean(), 1),
        "avg_mfe_r": round(trades_df["mfe_r"].mean(), 4),
        "give_back_ratio": round(
            trades_df.loc[trades_df["chandelier_activated"], "give_back_ratio"].mean(), 4
        ) if trades_df["chandelier_activated"].any() else 0,
        "worst_trade_r": round(trades_df["pnl_r"].min(), 4),
        "best_trade_r": round(trades_df["pnl_r"].max(), 4),
        "pct_reached_1r": round(trades_df["one_r_reached"].mean() * 100, 1),
        "pct_reached_2r": round((trades_df["mfe_r"] >= 2).mean() * 100, 1),
        "pct_reached_3r": round((trades_df["mfe_r"] >= 3).mean() * 100, 1),
    }


# ─── Visualization ──────────────────────────────────────────────────────────

def plot_r_distribution(trades_df, output_dir):
    """R-multiple distribution histogram, 4 multipliers overlaid, per ticker."""
    for ticker in TICKERS:
        fig, ax = plt.subplots(figsize=(10, 6))
        ticker_trades = trades_df[trades_df["ticker"] == ticker]

        for mult in MULTIPLIERS:
            subset = ticker_trades[ticker_trades["multiplier"] == mult]
            if len(subset) > 0:
                ax.hist(subset["pnl_r"], bins=20, alpha=0.4, label=f"{mult}x ATR",
                        edgecolor="black", linewidth=0.5)

        ax.set_title(f"{ticker} — R-Multiple Distribution by Chandelier Multiplier")
        ax.set_xlabel("R-Multiple")
        ax.set_ylabel("Frequency")
        ax.legend()
        ax.axvline(x=0, color="black", linestyle="--", alpha=0.5)
        plt.tight_layout()
        fig.savefig(output_dir / f"r_distribution_{ticker}.png", dpi=150)
        plt.close(fig)


def plot_give_back(trades_df, output_dir):
    """Give-back ratio by multiplier (bar chart)."""
    fig, ax = plt.subplots(figsize=(8, 5))
    give_backs = []
    for mult in MULTIPLIERS:
        subset = trades_df[(trades_df["multiplier"] == mult) & (trades_df["chandelier_activated"])]
        give_backs.append(subset["give_back_ratio"].mean() if len(subset) > 0 else 0)

    bars = ax.bar([f"{m}x" for m in MULTIPLIERS], give_backs,
                  color=["#e74c3c", "#f39c12", "#2ecc71", "#3498db"])
    ax.set_title("Average Give-Back Ratio by Multiplier")
    ax.set_xlabel("ATR Multiplier")
    ax.set_ylabel("Give-Back Ratio (lower = better)")
    for bar, val in zip(bars, give_backs):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.005,
                f"{val:.3f}", ha="center", va="bottom", fontsize=10)
    plt.tight_layout()
    fig.savefig(output_dir / "give_back_by_multiplier.png", dpi=150)
    plt.close(fig)


def plot_equity_curves(trades_df, output_dir):
    """Cumulative R over time, all 4 multipliers, per ticker."""
    for ticker in TICKERS:
        fig, ax = plt.subplots(figsize=(12, 6))
        ticker_trades = trades_df[trades_df["ticker"] == ticker]

        for mult in MULTIPLIERS:
            subset = ticker_trades[ticker_trades["multiplier"] == mult].sort_values("exit_datetime")
            if len(subset) > 0:
                cumulative_r = subset["pnl_r"].cumsum()
                ax.plot(subset["exit_datetime"].values, cumulative_r.values,
                        label=f"{mult}x ATR", linewidth=1.5)

        ax.set_title(f"{ticker} — Equity Curve (Cumulative R)")
        ax.set_xlabel("Date")
        ax.set_ylabel("Cumulative R")
        ax.legend()
        ax.axhline(y=0, color="black", linestyle="--", alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()
        fig.savefig(output_dir / f"equity_curve_{ticker}.png", dpi=150)
        plt.close(fig)


def plot_mfe_vs_exit(trades_df, output_dir):
    """Scatter: MFE vs Actual Exit R — profit capture analysis."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    colors = {1.25: "#e74c3c", 1.50: "#f39c12", 2.00: "#2ecc71", 2.25: "#3498db"}

    for ax, ticker in zip(axes.flat, TICKERS):
        ticker_trades = trades_df[trades_df["ticker"] == ticker]
        for mult in MULTIPLIERS:
            subset = ticker_trades[ticker_trades["multiplier"] == mult]
            if len(subset) > 0:
                ax.scatter(subset["mfe_r"], subset["pnl_r"], alpha=0.5,
                           label=f"{mult}x", color=colors[mult], s=20)

        # Perfect capture line
        max_val = max(ticker_trades["mfe_r"].max(), 1) if len(ticker_trades) > 0 else 5
        ax.plot([0, max_val], [0, max_val], "k--", alpha=0.3, label="Perfect capture")
        ax.set_title(ticker)
        ax.set_xlabel("MFE (R)")
        ax.set_ylabel("Exit P&L (R)")
        ax.legend(fontsize=8)

    plt.suptitle("MFE vs Actual Exit R — Profit Capture Analysis", fontsize=14)
    plt.tight_layout()
    fig.savefig(output_dir / "mfe_vs_exit_r.png", dpi=150)
    plt.close(fig)


# ─── Report Generation ──────────────────────────────────────────────────────

def generate_report(trades_df, output_dir):
    """Generate markdown summary report."""

    lines = [
        "# Chandelier Exit ATR Backtest — Phase 1 Results",
        "",
        "## Overview",
        f"- **Tickers**: {', '.join(TICKERS)}",
        f"- **Multipliers tested**: {', '.join(str(m) + 'x' for m in MULTIPLIERS)}",
        f"- **Entry**: 4H EMA9/21 crossover (long only)",
        f"- **Exit**: Chandelier Exit (ATR14, HH22) with +1R activation gate",
        f"- **Max hold**: {MAX_HOLD_DAYS} trading days",
        "",
    ]

    # Cross-multiplier comparison
    lines.append("## Cross-Multiplier Comparison (All Tickers Combined)")
    lines.append("")
    header = "| Metric | 1.25x | 1.50x | 2.00x | 2.25x |"
    separator = "|--------|-------|-------|-------|-------|"
    lines.append(header)
    lines.append(separator)

    metrics_by_mult = {}
    for mult in MULTIPLIERS:
        subset = trades_df[trades_df["multiplier"] == mult]
        metrics_by_mult[mult] = calc_metrics(subset)

    metric_labels = [
        ("total_trades", "Total Trades"),
        ("win_rate", "Win Rate (%)"),
        ("avg_r", "Avg R-Multiple"),
        ("median_r", "Median R-Multiple"),
        ("profit_factor", "Profit Factor"),
        ("avg_winner_r", "Avg Winner R"),
        ("avg_loser_r", "Avg Loser R"),
        ("avg_hold_hours", "Avg Hold (hrs)"),
        ("avg_mfe_r", "Avg MFE (R)"),
        ("give_back_ratio", "Give-Back Ratio"),
        ("worst_trade_r", "Worst Trade (R)"),
        ("best_trade_r", "Best Trade (R)"),
        ("pct_reached_1r", "% Reached +1R"),
        ("pct_reached_2r", "% Reached +2R"),
        ("pct_reached_3r", "% Reached +3R"),
    ]

    for key, label in metric_labels:
        vals = [str(metrics_by_mult[m].get(key, "N/A")) for m in MULTIPLIERS]
        lines.append(f"| {label} | {' | '.join(vals)} |")

    # Per-ticker breakdown
    lines.append("")
    lines.append("## Per-Ticker Breakdown")
    lines.append("")

    for ticker in TICKERS:
        lines.append(f"### {ticker}")
        lines.append("")
        lines.append(header)
        lines.append(separator)

        ticker_metrics = {}
        for mult in MULTIPLIERS:
            subset = trades_df[(trades_df["ticker"] == ticker) & (trades_df["multiplier"] == mult)]
            ticker_metrics[mult] = calc_metrics(subset)

        for key, label in metric_labels:
            vals = [str(ticker_metrics[m].get(key, "N/A")) for m in MULTIPLIERS]
            lines.append(f"| {label} | {' | '.join(vals)} |")
        lines.append("")

    # Recommendations
    lines.append("## Recommendations")
    lines.append("")

    # Find best profit factor
    best_pf_mult = max(MULTIPLIERS, key=lambda m: metrics_by_mult[m].get("profit_factor", 0))
    best_gb_mult = min(MULTIPLIERS, key=lambda m: metrics_by_mult[m].get("give_back_ratio", 1))
    best_avg_r_mult = max(MULTIPLIERS, key=lambda m: metrics_by_mult[m].get("avg_r", -999))

    lines.append(f"1. **Best Profit Factor**: {best_pf_mult}x ATR "
                 f"(PF = {metrics_by_mult[best_pf_mult]['profit_factor']})")
    lines.append(f"2. **Lowest Give-Back Ratio**: {best_gb_mult}x ATR "
                 f"(GB = {metrics_by_mult[best_gb_mult]['give_back_ratio']})")
    lines.append(f"3. **Best Average R**: {best_avg_r_mult}x ATR "
                 f"(Avg R = {metrics_by_mult[best_avg_r_mult]['avg_r']})")
    lines.append("")

    # Per-ticker optimal
    lines.append("### Optimal Multiplier by Ticker")
    lines.append("")
    for ticker in TICKERS:
        ticker_pf = {}
        for mult in MULTIPLIERS:
            subset = trades_df[(trades_df["ticker"] == ticker) & (trades_df["multiplier"] == mult)]
            m = calc_metrics(subset)
            ticker_pf[mult] = m.get("profit_factor", 0)
        best = max(MULTIPLIERS, key=lambda m: ticker_pf[m])
        lines.append(f"- **{ticker}**: {best}x ATR (PF = {ticker_pf[best]})")

    lines.append("")
    lines.append("### Phase 2 Recommendation")
    lines.append("")

    # Top 2 multipliers by profit factor for Phase 2
    sorted_mults = sorted(MULTIPLIERS, key=lambda m: metrics_by_mult[m].get("profit_factor", 0),
                          reverse=True)
    lines.append(f"Recommend testing **{sorted_mults[0]}x** and **{sorted_mults[1]}x** "
                 f"with dynamic VIX regime switching in Phase 2.")
    lines.append("")
    lines.append("### Phase 1b Note")
    lines.append("")
    lines.append("When crypto data (ETH, BTC) arrives, re-run this backtest with 6 tickers total "
                 "to validate whether crypto's 24/7 nature changes the optimal multiplier.")
    lines.append("")

    report = "\n".join(lines)
    report_path = output_dir / "RESULTS.md"
    with open(report_path, "w") as f:
        f.write(report)
    print(f"\nReport saved to {report_path}")
    return report


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Run backtest for all tickers
    all_trades = []
    for ticker in TICKERS:
        trades = run_backtest_for_ticker(ticker)
        all_trades.extend(trades)

    if not all_trades:
        print("ERROR: No trades generated. Check data and entry signals.")
        return

    trades_df = pd.DataFrame(all_trades)
    trades_df["entry_datetime"] = pd.to_datetime(trades_df["entry_datetime"])
    trades_df["exit_datetime"] = pd.to_datetime(trades_df["exit_datetime"])

    # Save trade log
    csv_path = OUTPUT_DIR / "all_trades.csv"
    trades_df.to_csv(csv_path, index=False)
    print(f"\nTrade log saved to {csv_path} ({len(trades_df)} trades)")

    # Generate charts
    print("\nGenerating charts...")
    plot_r_distribution(trades_df, OUTPUT_DIR)
    plot_give_back(trades_df, OUTPUT_DIR)
    plot_equity_curves(trades_df, OUTPUT_DIR)
    plot_mfe_vs_exit(trades_df, OUTPUT_DIR)
    print("Charts saved to", OUTPUT_DIR)

    # Generate report
    report = generate_report(trades_df, OUTPUT_DIR)
    print("\n" + report)


if __name__ == "__main__":
    main()
