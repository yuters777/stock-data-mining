#!/usr/bin/env python3
"""
S44 Module 2 — Part 2A: Exit Variants for E2 Entry.

Entry: E2 (M5 RSI dips below 40, first bar RSI crosses back above 40)
Pre-filter: 4H EMA gate UP + VIX < 25 + NOT Module 4 window

Tests 8 exit variants with -1.5% hard stop and EOD flat at 15:50 ET.

Output: results/S44_Module2_Part2A_Exit_Results.md
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.data_loader import load_m5_regsess

# ── Config ────────────────────────────────────────────────────────────────────

TICKERS = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU", "C",
    "COIN", "COST", "GOOGL", "GS", "INTC", "JPM", "MARA", "META", "MSFT",
    "MSTR", "MU", "NVDA", "PLTR", "SMCI", "TSLA", "TSM", "V",
]

INDICATORS_4H_DIR = ROOT / "data" / "indicators_4h"
VIX_PATH = ROOT / "Fetched_Data" / "VIXCLS_FRED_real.csv"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# Indicator params (same as Part 1)
EMA9_PERIOD = 9
EMA21_PERIOD = 21
RSI_PERIOD = 14
CE_ATR_PERIOD = 14
CE_HH_LOOKBACK = 22
CE_MULT = 2.0

# Safety
HARD_STOP_PCT = -1.5
EOD_FLAT_MINUTE = 15 * 60 + 50  # 15:50 ET


# ── Indicator functions (identical to Part 1) ─────────────────────────────────

def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_atr(high, low, close, period=14):
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def calc_chandelier_state(high, low, close, atr_period=14, hh_lookback=22, mult=2.0):
    atr = calc_atr(high, low, close, atr_period)
    hh = high.rolling(window=hh_lookback, min_periods=hh_lookback).max()
    ce_long_stop = hh - mult * atr
    return close > ce_long_stop


# ── VIX loading ───────────────────────────────────────────────────────────────

def load_vix():
    df = pd.read_csv(VIX_PATH)
    df["observation_date"] = pd.to_datetime(df["observation_date"])
    df = df.dropna(subset=["VIXCLS"])
    df = df.set_index("observation_date").sort_index()
    df = df.reindex(pd.date_range(df.index.min(), df.index.max(), freq="D"), method="ffill")
    return df["VIXCLS"]


# ── 4H helpers ────────────────────────────────────────────────────────────────

def load_4h_bars(ticker):
    path = INDICATORS_4H_DIR / f"{ticker}_4h_indicators.csv"
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["date_str"] = df["timestamp"].dt.strftime("%Y-%m-%d")
    df["time_str"] = df["timestamp"].dt.strftime("%H:%M")
    return df


def detect_module4_windows(bars_4h):
    closes = bars_4h["close"].values
    opens = bars_4h["open"].values
    is_down = closes < opens
    blocked = set()
    for i in range(2, len(bars_4h)):
        if is_down[i] and is_down[i - 1] and is_down[i - 2]:
            for j in [i - 2, i - 1, i]:
                row = bars_4h.iloc[j]
                session = "AM" if row["time_str"] == "09:30" else "PM"
                blocked.add((row["date_str"], session))
    return blocked


def build_4h_session_map(bars_4h):
    """Build lookup: (date_str, session) -> 4H bar index."""
    bar_lookup = {}
    for i, row in bars_4h.iterrows():
        session = "AM" if row["time_str"] == "09:30" else "PM"
        bar_lookup[(row["date_str"], session)] = i
    trading_dates = sorted(bars_4h["date_str"].unique())
    date_to_prev = {}
    for j in range(1, len(trading_dates)):
        date_to_prev[trading_dates[j]] = trading_dates[j - 1]
    return bar_lookup, trading_dates, date_to_prev


def get_m5_session_info(m5_ts):
    """Return (date_str, session, completed_4h_key) for an M5 timestamp."""
    m5_date = m5_ts.strftime("%Y-%m-%d")
    m5_minutes = m5_ts.hour * 60 + m5_ts.minute
    if m5_minutes < 13 * 60 + 30:
        return m5_date, "AM"
    else:
        return m5_date, "PM"


def map_prefilters(m5_df, bars_4h, vix_series):
    """Return arrays: gate_up, vix_ok, vix_regime, not_module4, completed_4h_idx."""
    bar_lookup, trading_dates, date_to_prev = build_4h_session_map(bars_4h)
    module4_blocked = detect_module4_windows(bars_4h)

    n = len(m5_df)
    gate_up = np.zeros(n, dtype=bool)
    vix_ok = np.zeros(n, dtype=bool)
    vix_regime = np.full(n, "", dtype=object)
    not_module4 = np.ones(n, dtype=bool)
    completed_4h_idx = np.full(n, -1, dtype=int)

    for idx in range(n):
        m5_ts = m5_df["Datetime"].iloc[idx]
        m5_date = m5_ts.strftime("%Y-%m-%d")
        m5_minutes = m5_ts.hour * 60 + m5_ts.minute

        if m5_minutes < 13 * 60 + 30:
            prev_date = date_to_prev.get(m5_date)
            bar_idx = bar_lookup.get((prev_date, "PM")) if prev_date else None
            current_session = (m5_date, "AM")
        else:
            bar_idx = bar_lookup.get((m5_date, "AM"))
            current_session = (m5_date, "PM")

        if bar_idx is not None:
            completed_4h_idx[idx] = bar_idx
            h4 = bars_4h.iloc[bar_idx]
            ema9 = h4["ema_9"]
            ema21 = h4["ema_21"]
            if pd.notna(ema9) and pd.notna(ema21):
                gate_up[idx] = ema9 > ema21

        if current_session in module4_blocked:
            not_module4[idx] = False

        m5_date_ts = pd.Timestamp(m5_date)
        prior_day = m5_date_ts - pd.Timedelta(days=1)
        vix_val = None
        for offset in range(4):
            lookup = prior_day - pd.Timedelta(days=offset)
            if lookup in vix_series.index:
                vix_val = vix_series[lookup]
                break

        if vix_val is not None and vix_val < 25:
            vix_ok[idx] = True
            vix_regime[idx] = "NORMAL" if vix_val < 20 else "ELEVATED"

    return gate_up, vix_ok, vix_regime, not_module4, completed_4h_idx


def detect_e2_signals(rsi):
    """E2: RSI dips below 40, first bar RSI crosses back above 40."""
    rsi_v = rsi.values
    n = len(rsi_v)
    e2 = np.zeros(n, dtype=bool)
    below_40 = False
    for i in range(1, n):
        if np.isnan(rsi_v[i]):
            below_40 = False
            continue
        if not np.isnan(rsi_v[i - 1]) and rsi_v[i - 1] < 40:
            below_40 = True
        if below_40 and rsi_v[i] >= 40:
            e2[i] = True
            below_40 = False
    return e2


# ── Trade simulator ───────────────────────────────────────────────────────────

def simulate_trades(entry_indices, m5_df, ema21, ce_long, bars_4h,
                    completed_4h_idx, bar_lookup, date_to_prev):
    """
    For each entry, simulate all 8 exit variants.
    Returns list of dicts, one per entry, with results for each exit.
    """
    close_v = m5_df["Close"].values
    high_v = m5_df["High"].values
    low_v = m5_df["Low"].values
    dt_v = m5_df["Datetime"].values
    ema21_v = ema21.values
    ce_v = ce_long.values
    n_bars = len(m5_df)

    # Precompute M5 bar minutes for EOD check
    minutes_v = np.array([
        pd.Timestamp(dt).hour * 60 + pd.Timestamp(dt).minute for dt in dt_v
    ])
    # Precompute trading dates for M5 bars
    dates_v = np.array([pd.Timestamp(dt).strftime("%Y-%m-%d") for dt in dt_v])

    # Build list of 4H bar timestamps for forward lookups
    h4_n = len(bars_4h)

    trades = []

    for entry_idx in entry_indices:
        entry_price = close_v[entry_idx]
        entry_dt = dt_v[entry_idx]
        stop_price = entry_price * (1 + HARD_STOP_PCT / 100)

        # Common: scan forward bar-by-bar tracking MAE/MFE and stop/EOD
        # We need to find exit bar for each variant

        # Pre-scan: collect bar-by-bar data from entry forward
        # Maximum scan: 200 M5 bars (>2 sessions) or end of data
        max_scan = min(entry_idx + 200, n_bars)

        # Track which 4H bar we're in at entry
        entry_4h_idx = completed_4h_idx[entry_idx]

        results = {}

        for exit_name in ["X1", "X2", "X3", "X4", "X5", "X6", "X7", "X8"]:
            exit_bar = None
            exit_reason = None
            mae = 0.0
            mfe = 0.0

            for j in range(entry_idx + 1, max_scan):
                bar_ret_pct = (close_v[j] - entry_price) / entry_price * 100
                bar_low_ret = (low_v[j] - entry_price) / entry_price * 100
                bar_high_ret = (high_v[j] - entry_price) / entry_price * 100
                mae = min(mae, bar_low_ret)
                mfe = max(mfe, bar_high_ret)
                bars_held = j - entry_idx

                # 1. Hard stop check (intrabar — use low)
                if bar_low_ret <= HARD_STOP_PCT:
                    exit_bar = j
                    exit_reason = "stopped"
                    bar_ret_pct = HARD_STOP_PCT
                    mae = HARD_STOP_PCT
                    break

                # 2. Exit signal check
                signal_hit = False

                if exit_name == "X1" and bars_held >= 12:
                    signal_hit = True
                elif exit_name == "X2" and bars_held >= 24:
                    signal_hit = True
                elif exit_name == "X3" and bars_held >= 48:
                    signal_hit = True
                elif exit_name == "X4":
                    # +1 completed 4H bar after entry
                    cur_4h = completed_4h_idx[j] if j < len(completed_4h_idx) else -1
                    if cur_4h > entry_4h_idx:
                        # The 4H bar that was in-progress at entry has now completed
                        # We want +1 completed = the NEXT completed bar
                        if cur_4h >= entry_4h_idx + 2:
                            signal_hit = True
                elif exit_name == "X5":
                    cur_4h = completed_4h_idx[j] if j < len(completed_4h_idx) else -1
                    if cur_4h >= entry_4h_idx + 3:
                        signal_hit = True
                elif exit_name == "X6":
                    # CE flip to SHORT: was LONG, now SHORT
                    if j >= 1 and not np.isnan(ce_v[j]) and not np.isnan(ce_v[j - 1]):
                        if ce_v[j - 1] and not ce_v[j]:
                            signal_hit = True
                elif exit_name == "X7":
                    # Close below EMA21
                    if not np.isnan(ema21_v[j]) and close_v[j] < ema21_v[j]:
                        signal_hit = True
                elif exit_name == "X8":
                    # 4H EMA gate flips DOWN
                    cur_4h = completed_4h_idx[j] if j < len(completed_4h_idx) else -1
                    if cur_4h > entry_4h_idx and cur_4h >= 0:
                        h4 = bars_4h.iloc[cur_4h]
                        e9 = h4["ema_9"]
                        e21 = h4["ema_21"]
                        if pd.notna(e9) and pd.notna(e21) and e9 <= e21:
                            signal_hit = True

                if signal_hit:
                    exit_bar = j
                    exit_reason = exit_name
                    break

                # 3. EOD flat check (15:50 ET)
                if minutes_v[j] >= EOD_FLAT_MINUTE:
                    exit_bar = j
                    exit_reason = "eod_flat"
                    break

                # 4. Session boundary — next bar is a different date or gap
                if j + 1 < n_bars and dates_v[j + 1] != dates_v[j]:
                    # We're at end of day without exit — EOD flat
                    exit_bar = j
                    exit_reason = "eod_flat"
                    break

            if exit_bar is None:
                # Ran out of data
                continue

            final_ret = (close_v[exit_bar] - entry_price) / entry_price * 100
            if exit_reason == "stopped":
                final_ret = HARD_STOP_PCT

            results[exit_name] = {
                "entry_idx": entry_idx,
                "exit_idx": exit_bar,
                "entry_price": entry_price,
                "exit_price": close_v[exit_bar],
                "return_pct": final_ret,
                "mae": mae,
                "mfe": mfe,
                "hold_bars": exit_bar - entry_idx,
                "exit_reason": exit_reason,
            }

        if results:
            trades.append(results)

    return trades


# ── Main analysis ─────────────────────────────────────────────────────────────

def run_analysis():
    vix_series = load_vix()
    print(f"VIX data: {len(vix_series)} daily observations")

    # Collect all trade results per exit variant
    all_trades = {f"X{i}": [] for i in range(1, 9)}

    for ticker in TICKERS:
        print(f"Processing {ticker}...")

        bars_4h = load_4h_bars(ticker)
        try:
            m5_df = load_m5_regsess(ticker)
        except (FileNotFoundError, ValueError) as e:
            print(f"  SKIP {ticker}: {e}")
            continue

        # Pre-filters
        gate_up, vix_ok, vix_regime, not_module4, completed_4h_idx = map_prefilters(
            m5_df, bars_4h, vix_series
        )

        # M5 indicators
        close = m5_df["Close"]
        high = m5_df["High"]
        low = m5_df["Low"]

        ema21 = calc_ema(close, EMA21_PERIOD)
        rsi = calc_rsi(close, RSI_PERIOD)
        ce_long = calc_chandelier_state(high, low, close, CE_ATR_PERIOD, CE_HH_LOOKBACK, CE_MULT)

        # E2 entry signals
        e2 = detect_e2_signals(rsi)

        # Filter to qualifying entries
        qualifying = np.where(gate_up & vix_ok & not_module4 & e2)[0]
        print(f"  {ticker}: {len(qualifying)} E2 entries")

        if len(qualifying) == 0:
            continue

        # Build 4H lookup for trade sim
        bar_lookup, trading_dates, date_to_prev = build_4h_session_map(bars_4h)

        # Simulate trades
        ticker_trades = simulate_trades(
            qualifying, m5_df, ema21, ce_long, bars_4h,
            completed_4h_idx, bar_lookup, date_to_prev
        )

        # Collect results
        for trade in ticker_trades:
            for exit_name, result in trade.items():
                result["ticker"] = ticker
                all_trades[exit_name].append(result)

    return all_trades


# ── Metrics ───────────────────────────────────────────────────────────────────

def compute_exit_metrics(trade_list):
    """Compute all 10 metrics for a list of trade dicts."""
    if not trade_list:
        return None

    rets = np.array([t["return_pct"] for t in trade_list])
    maes = np.array([t["mae"] for t in trade_list])
    mfes = np.array([t["mfe"] for t in trade_list])
    holds = np.array([t["hold_bars"] for t in trade_list])
    reasons = [t["exit_reason"] for t in trade_list]

    n = len(rets)
    mean_ret = np.mean(rets)
    median_ret = np.median(rets)
    wr = np.sum(rets > 0) / n * 100
    gains = np.sum(rets[rets > 0])
    losses = abs(np.sum(rets[rets < 0]))
    pf = gains / losses if losses > 0 else np.inf
    avg_mae = np.mean(maes)
    avg_mfe = np.mean(mfes)
    avg_hold = np.mean(holds)
    stop_rate = sum(1 for r in reasons if r == "stopped") / n * 100
    eod_rate = sum(1 for r in reasons if r == "eod_flat") / n * 100

    # Sharpe-like: mean / std (annualized doesn't apply here, use raw)
    std_ret = np.std(rets)
    sharpe = mean_ret / std_ret if std_ret > 0 else 0

    # p-value
    if n >= 3:
        _, p = stats.ttest_1samp(rets, 0)
        p = p / 2 if mean_ret > 0 else 1 - p / 2
    else:
        p = np.nan

    return {
        "N": n,
        "mean": mean_ret,
        "median": median_ret,
        "wr": wr,
        "pf": pf,
        "mae": avg_mae,
        "mfe": avg_mfe,
        "avg_hold": avg_hold,
        "stop_rate": stop_rate,
        "eod_rate": eod_rate,
        "sharpe": sharpe,
        "std": std_ret,
        "p": p,
    }


# ── Report ────────────────────────────────────────────────────────────────────

def generate_report(all_trades):
    exit_names = {
        "X1": "Fixed +12 bars (1hr)",
        "X2": "Fixed +24 bars (2hr)",
        "X3": "Fixed +48 bars (4hr)",
        "X4": "+1 completed 4H bar",
        "X5": "+2 completed 4H bars",
        "X6": "M5 CE flip to SHORT",
        "X7": "Close below M5 EMA21",
        "X8": "4H EMA gate flips DOWN",
    }

    metrics = {}
    for xname in exit_names:
        m = compute_exit_metrics(all_trades[xname])
        if m:
            metrics[xname] = m

    lines = []
    lines.append("# S44 Module 2 — Part 2A: Exit Variants for E2 Entry")
    lines.append("")
    lines.append(f"**Date:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("**Entry:** E2 (RSI dip below 40, first bar RSI crosses back above 40)")
    lines.append("**Pre-filter:** 4H EMA gate UP + VIX < 25 + NOT Module 4 window")
    lines.append("**Safety:** -1.5% hard stop + EOD flat at 15:50 ET")
    lines.append("")

    total_entries = max(len(all_trades[x]) for x in all_trades if all_trades[x])
    lines.append(f"**Total E2 entry signals:** {total_entries:,}")
    lines.append("")

    # ── Section 1: Exit Variant Results ──
    lines.append("## 1. Exit Variant Results")
    lines.append("")
    lines.append("| Exit | Description | N | Mean% | Median% | WR% | PF | Avg MAE% | Avg MFE% | Avg Hold | Stop% | EOD% | Sharpe | p-val |")
    lines.append("|------|-------------|---|-------|---------|-----|----|----------|----------|----------|-------|------|--------|-------|")

    for xname in ["X1", "X2", "X3", "X4", "X5", "X6", "X7", "X8"]:
        m = metrics.get(xname)
        if not m:
            lines.append(f"| {xname} | {exit_names[xname]} | 0 | — | — | — | — | — | — | — | — | — | — | — |")
            continue

        pf_str = f"{m['pf']:.2f}" if m['pf'] != np.inf else "inf"
        sig = "***" if m['p'] < 0.001 else ("**" if m['p'] < 0.01 else ("*" if m['p'] < 0.05 else ""))
        lines.append(
            f"| {xname} | {exit_names[xname]} | {m['N']:,} | "
            f"{m['mean']:+.4f} | {m['median']:+.4f} | {m['wr']:.1f} | {pf_str} | "
            f"{m['mae']:+.4f} | {m['mfe']:+.4f} | {m['avg_hold']:.1f} | "
            f"{m['stop_rate']:.1f} | {m['eod_rate']:.1f} | {m['sharpe']:.3f} | "
            f"{m['p']:.4f}{sig} |"
        )
    lines.append("")

    # ── Section 2: Ranking ──
    lines.append("## 2. Ranking")
    lines.append("")
    lines.append("### By Profit Factor")
    lines.append("")
    lines.append("| Rank | Exit | PF | Mean% | WR% | N |")
    lines.append("|------|------|----|-------|-----|---|")

    ranked_pf = sorted(metrics.items(), key=lambda x: x[1]["pf"] if x[1]["pf"] != np.inf else 0, reverse=True)
    for rank, (xname, m) in enumerate(ranked_pf, 1):
        pf_str = f"{m['pf']:.2f}" if m['pf'] != np.inf else "inf"
        lines.append(f"| {rank} | {xname} | {pf_str} | {m['mean']:+.4f} | {m['wr']:.1f} | {m['N']:,} |")
    lines.append("")

    lines.append("### By Sharpe (mean/std)")
    lines.append("")
    lines.append("| Rank | Exit | Sharpe | Mean% | Std% | N |")
    lines.append("|------|------|--------|-------|------|---|")

    ranked_sharpe = sorted(metrics.items(), key=lambda x: x[1]["sharpe"], reverse=True)
    for rank, (xname, m) in enumerate(ranked_sharpe, 1):
        lines.append(f"| {rank} | {xname} | {m['sharpe']:.3f} | {m['mean']:+.4f} | {m['std']:.4f} | {m['N']:,} |")
    lines.append("")

    # ── Section 3: Best exit ──
    lines.append("## 3. Best Exit Identification")
    lines.append("")

    # Best = highest PF among exits with N >= 100 and p < 0.05
    viable = [(x, m) for x, m in metrics.items() if m["N"] >= 100 and m["p"] < 0.05]
    if viable:
        best_pf = max(viable, key=lambda x: x[1]["pf"])
        best_sharpe = max(viable, key=lambda x: x[1]["sharpe"])

        lines.append(f"**Best by PF:** {best_pf[0]} ({exit_names[best_pf[0]]}) — "
                     f"PF={best_pf[1]['pf']:.2f}, Mean={best_pf[1]['mean']:+.4f}%, "
                     f"WR={best_pf[1]['wr']:.1f}%, N={best_pf[1]['N']:,}")
        lines.append("")
        lines.append(f"**Best by Sharpe:** {best_sharpe[0]} ({exit_names[best_sharpe[0]]}) — "
                     f"Sharpe={best_sharpe[1]['sharpe']:.3f}, Mean={best_sharpe[1]['mean']:+.4f}%, "
                     f"N={best_sharpe[1]['N']:,}")
        lines.append("")

        # Overall recommendation
        if best_pf[0] == best_sharpe[0]:
            winner = best_pf[0]
            lines.append(f"**Winner: {winner}** — {exit_names[winner]}")
            lines.append(f"Both PF and Sharpe agree.")
        else:
            # Prefer PF unless Sharpe is drastically better
            winner = best_pf[0]
            lines.append(f"**Winner: {winner}** — {exit_names[winner]} (highest PF among viable exits)")
            lines.append(f"Runner-up by Sharpe: {best_sharpe[0]} — {exit_names[best_sharpe[0]]}")
    else:
        winner = None
        lines.append("**No exit variant has N >= 100 and p < 0.05.**")
        lines.append("Module 2 trend exit does not produce reliable edge.")
    lines.append("")

    # ── Section 4: Exit reason breakdown ──
    lines.append("## 4. Exit Reason Breakdown")
    lines.append("")
    lines.append("| Exit | Signal% | Stopped% | EOD Flat% |")
    lines.append("|------|---------|----------|-----------|")

    for xname in ["X1", "X2", "X3", "X4", "X5", "X6", "X7", "X8"]:
        m = metrics.get(xname)
        if not m:
            continue
        signal_pct = 100 - m["stop_rate"] - m["eod_rate"]
        lines.append(f"| {xname} | {signal_pct:.1f} | {m['stop_rate']:.1f} | {m['eod_rate']:.1f} |")
    lines.append("")

    # ── Section 5: Risk profile ──
    lines.append("## 5. Risk Profile (MAE/MFE)")
    lines.append("")
    lines.append("| Exit | Avg MAE% | Avg MFE% | MFE/MAE Ratio | Avg Hold (bars) |")
    lines.append("|------|----------|----------|---------------|-----------------|")

    for xname in ["X1", "X2", "X3", "X4", "X5", "X6", "X7", "X8"]:
        m = metrics.get(xname)
        if not m:
            continue
        ratio = abs(m["mfe"] / m["mae"]) if m["mae"] != 0 else np.inf
        ratio_str = f"{ratio:.2f}" if ratio != np.inf else "inf"
        lines.append(f"| {xname} | {m['mae']:+.4f} | {m['mfe']:+.4f} | {ratio_str} | {m['avg_hold']:.1f} |")
    lines.append("")

    # ── Section 6: Config ──
    lines.append("## 6. Configuration")
    lines.append("")
    lines.append("```")
    lines.append(f"Entry:         E2 (RSI<40 dip + recovery above 40)")
    lines.append(f"RSI period:    {RSI_PERIOD} (Wilder smoothing)")
    lines.append(f"EMA periods:   {EMA9_PERIOD}, {EMA21_PERIOD}")
    lines.append(f"CE params:     period={CE_ATR_PERIOD}, lookback={CE_HH_LOOKBACK}, mult={CE_MULT}")
    lines.append(f"Hard stop:     {HARD_STOP_PCT}%")
    lines.append(f"EOD flat:      15:50 ET")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    all_trades = run_analysis()
    report = generate_report(all_trades)

    output_path = RESULTS_DIR / "S44_Module2_Part2A_Exit_Results.md"
    output_path.write_text(report)
    print(f"\nResults saved to {output_path}")
    print("\n" + report)
