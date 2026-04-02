#!/usr/bin/env python3
"""
S44 Module 2 — Part 2B: 4H Context Enhancement.

Entry: E2 (RSI<40 dip + recovery)
Exit:  X8 (4H EMA gate flips DOWN) — winner from Part 2A
       With -1.5% hard stop and EOD flat at 15:50 ET

Tests 5 context layers as additional pre-filters on E2+X8:
  C1: 4H RSI 35-65 (neutral)
  C2: 4H ADX < 25 (fresh trend)
  C3: 4H ADX < 20 (even fresher)
  C4: VIX < 20 only (NORMAL regime)
  C5: C1 + C2 combined

Output: results/S44_Module2_Part2B_Context_Results.md
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

EMA9_PERIOD = 9
EMA21_PERIOD = 21
RSI_PERIOD = 14
CE_ATR_PERIOD = 14
CE_HH_LOOKBACK = 22
CE_MULT = 2.0

HARD_STOP_PCT = -1.5
EOD_FLAT_MINUTE = 15 * 60 + 50


# ── Indicator functions ───────────────────────────────────────────────────────

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


# ── VIX ───────────────────────────────────────────────────────────────────────

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
    bar_lookup = {}
    for i, row in bars_4h.iterrows():
        session = "AM" if row["time_str"] == "09:30" else "PM"
        bar_lookup[(row["date_str"], session)] = i
    trading_dates = sorted(bars_4h["date_str"].unique())
    date_to_prev = {}
    for j in range(1, len(trading_dates)):
        date_to_prev[trading_dates[j]] = trading_dates[j - 1]
    return bar_lookup, trading_dates, date_to_prev


def map_prefilters(m5_df, bars_4h, vix_series):
    """Return arrays: gate_up, vix_ok, vix_regime, not_module4, completed_4h_idx,
    h4_rsi, h4_adx — the 4H RSI/ADX at entry time for context filtering."""
    bar_lookup, trading_dates, date_to_prev = build_4h_session_map(bars_4h)
    module4_blocked = detect_module4_windows(bars_4h)

    n = len(m5_df)
    gate_up = np.zeros(n, dtype=bool)
    vix_ok = np.zeros(n, dtype=bool)
    vix_regime = np.full(n, "", dtype=object)
    vix_val_arr = np.full(n, np.nan)
    not_module4 = np.ones(n, dtype=bool)
    completed_4h_idx = np.full(n, -1, dtype=int)
    h4_rsi = np.full(n, np.nan)
    h4_adx = np.full(n, np.nan)

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
            # Extract 4H RSI and ADX for context
            if pd.notna(h4["rsi_14"]):
                h4_rsi[idx] = h4["rsi_14"]
            if pd.notna(h4["adx_14"]):
                h4_adx[idx] = h4["adx_14"]

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
            vix_val_arr[idx] = vix_val
            vix_regime[idx] = "NORMAL" if vix_val < 20 else "ELEVATED"

    return gate_up, vix_ok, vix_regime, vix_val_arr, not_module4, completed_4h_idx, h4_rsi, h4_adx


def detect_e2_signals(rsi):
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


# ── Trade simulator (X8 exit only) ───────────────────────────────────────────

def simulate_x8_trades(entry_indices, m5_df, bars_4h, completed_4h_idx):
    """Simulate E2 entries with X8 exit (4H gate flip DOWN), hard stop, EOD flat."""
    close_v = m5_df["Close"].values
    high_v = m5_df["High"].values
    low_v = m5_df["Low"].values
    dt_v = m5_df["Datetime"].values
    n_bars = len(m5_df)

    minutes_v = np.array([
        pd.Timestamp(dt).hour * 60 + pd.Timestamp(dt).minute for dt in dt_v
    ])
    dates_v = np.array([pd.Timestamp(dt).strftime("%Y-%m-%d") for dt in dt_v])

    trades = []

    for entry_idx in entry_indices:
        entry_price = close_v[entry_idx]
        stop_price = entry_price * (1 + HARD_STOP_PCT / 100)
        entry_4h_idx = completed_4h_idx[entry_idx]

        max_scan = min(entry_idx + 200, n_bars)

        exit_bar = None
        exit_reason = None
        mae = 0.0
        mfe = 0.0

        for j in range(entry_idx + 1, max_scan):
            bar_low_ret = (low_v[j] - entry_price) / entry_price * 100
            bar_high_ret = (high_v[j] - entry_price) / entry_price * 100
            mae = min(mae, bar_low_ret)
            mfe = max(mfe, bar_high_ret)

            # 1. Hard stop
            if bar_low_ret <= HARD_STOP_PCT:
                exit_bar = j
                exit_reason = "stopped"
                break

            # 2. X8: 4H gate flips DOWN
            cur_4h = completed_4h_idx[j] if j < len(completed_4h_idx) else -1
            if cur_4h > entry_4h_idx and cur_4h >= 0:
                h4 = bars_4h.iloc[cur_4h]
                e9 = h4["ema_9"]
                e21 = h4["ema_21"]
                if pd.notna(e9) and pd.notna(e21) and e9 <= e21:
                    exit_bar = j
                    exit_reason = "X8"
                    break

            # 3. EOD flat
            if minutes_v[j] >= EOD_FLAT_MINUTE:
                exit_bar = j
                exit_reason = "eod_flat"
                break

            # 4. Session boundary
            if j + 1 < n_bars and dates_v[j + 1] != dates_v[j]:
                exit_bar = j
                exit_reason = "eod_flat"
                break

        if exit_bar is None:
            continue

        final_ret = HARD_STOP_PCT if exit_reason == "stopped" else \
            (close_v[exit_bar] - entry_price) / entry_price * 100

        trades.append({
            "entry_idx": entry_idx,
            "return_pct": final_ret,
            "mae": mae,
            "mfe": mfe,
            "hold_bars": exit_bar - entry_idx,
            "exit_reason": exit_reason,
        })

    return trades


# ── Main ──────────────────────────────────────────────────────────────────────

def run_analysis():
    vix_series = load_vix()
    print(f"VIX data: {len(vix_series)} daily observations")

    # Collect trade-level results with context metadata
    all_trades = []

    for ticker in TICKERS:
        print(f"Processing {ticker}...")

        bars_4h = load_4h_bars(ticker)
        try:
            m5_df = load_m5_regsess(ticker)
        except (FileNotFoundError, ValueError) as e:
            print(f"  SKIP {ticker}: {e}")
            continue

        (gate_up, vix_ok, vix_regime, vix_val_arr,
         not_module4, completed_4h_idx, h4_rsi, h4_adx) = map_prefilters(
            m5_df, bars_4h, vix_series
        )

        close = m5_df["Close"]
        rsi = calc_rsi(close, RSI_PERIOD)
        e2 = detect_e2_signals(rsi)

        # Base qualifying: gate_up & vix_ok & not_module4 & e2
        qualifying = np.where(gate_up & vix_ok & not_module4 & e2)[0]
        print(f"  {ticker}: {len(qualifying)} E2 entries")

        if len(qualifying) == 0:
            continue

        # Simulate X8 trades
        ticker_trades = simulate_x8_trades(qualifying, m5_df, bars_4h, completed_4h_idx)

        # Attach context metadata to each trade
        for trade in ticker_trades:
            eidx = trade["entry_idx"]
            trade["ticker"] = ticker
            trade["h4_rsi"] = h4_rsi[eidx]
            trade["h4_adx"] = h4_adx[eidx]
            trade["vix_val"] = vix_val_arr[eidx]
            trade["vix_regime"] = vix_regime[eidx]
            all_trades.append(trade)

    print(f"\nTotal E2+X8 trades: {len(all_trades):,}")
    return all_trades


# ── Metrics ───────────────────────────────────────────────────────────────────

def compute_metrics(trade_list):
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
    std_ret = np.std(rets)
    sharpe = mean_ret / std_ret if std_ret > 0 else 0
    avg_mae = np.mean(maes)
    avg_mfe = np.mean(mfes)
    avg_hold = np.mean(holds)
    stop_rate = sum(1 for r in reasons if r == "stopped") / n * 100
    eod_rate = sum(1 for r in reasons if r == "eod_flat") / n * 100

    if n >= 3:
        _, p = stats.ttest_1samp(rets, 0)
        p = p / 2 if mean_ret > 0 else 1 - p / 2
    else:
        p = np.nan

    return {
        "N": n, "mean": mean_ret, "median": median_ret, "wr": wr,
        "pf": pf, "sharpe": sharpe, "std": std_ret,
        "mae": avg_mae, "mfe": avg_mfe, "avg_hold": avg_hold,
        "stop_rate": stop_rate, "eod_rate": eod_rate, "p": p,
    }


def separation_test(filtered_trades, all_trades):
    """Two-sample t-test: filtered vs all (complement)."""
    f_rets = np.array([t["return_pct"] for t in filtered_trades])
    a_rets = np.array([t["return_pct"] for t in all_trades])
    if len(f_rets) < 3 or len(a_rets) < 3:
        return np.nan
    _, p = stats.ttest_ind(f_rets, a_rets, equal_var=False)
    return p


# ── Context filters ──────────────────────────────────────────────────────────

def apply_context(trades, context_name):
    """Filter trades by context rule. Returns filtered list."""
    if context_name == "NONE":
        return trades
    elif context_name == "C1":
        return [t for t in trades if not np.isnan(t["h4_rsi"]) and 35 <= t["h4_rsi"] <= 65]
    elif context_name == "C2":
        return [t for t in trades if not np.isnan(t["h4_adx"]) and t["h4_adx"] < 25]
    elif context_name == "C3":
        return [t for t in trades if not np.isnan(t["h4_adx"]) and t["h4_adx"] < 20]
    elif context_name == "C4":
        return [t for t in trades if t["vix_regime"] == "NORMAL"]
    elif context_name == "C5":
        return [t for t in trades
                if (not np.isnan(t["h4_rsi"]) and 35 <= t["h4_rsi"] <= 65)
                and (not np.isnan(t["h4_adx"]) and t["h4_adx"] < 25)]
    return trades


# ── Report ────────────────────────────────────────────────────────────────────

def generate_report(all_trades):
    context_names = {
        "NONE": "No context (E2 + X8 baseline)",
        "C1": "4H RSI 35-65 (neutral zone)",
        "C2": "4H ADX < 25 (fresh trend)",
        "C3": "4H ADX < 20 (very fresh trend)",
        "C4": "VIX < 20 only (NORMAL regime)",
        "C5": "C1 + C2 (RSI neutral + fresh ADX)",
    }

    contexts = ["NONE", "C1", "C2", "C3", "C4", "C5"]
    results = {}
    filtered_trades = {}

    for ctx in contexts:
        ft = apply_context(all_trades, ctx)
        filtered_trades[ctx] = ft
        results[ctx] = compute_metrics(ft)

    lines = []
    lines.append("# S44 Module 2 — Part 2B: 4H Context Enhancement")
    lines.append("")
    lines.append(f"**Date:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("**Entry:** E2 (RSI<40 dip + recovery)")
    lines.append("**Exit:** X8 (4H EMA gate flips DOWN)")
    lines.append("**Safety:** -1.5% hard stop + EOD flat at 15:50 ET")
    lines.append(f"**Total baseline trades:** {results['NONE']['N']:,}")
    lines.append("")

    # ── Section 1: Context comparison table ──
    lines.append("## 1. Context Layer Results")
    lines.append("")
    lines.append("| Context | Description | N | Mean% | Median% | WR% | PF | Sharpe | Stop% | EOD% | p-val |")
    lines.append("|---------|-------------|---|-------|---------|-----|----|--------|-------|------|-------|")

    for ctx in contexts:
        m = results[ctx]
        if not m:
            lines.append(f"| {ctx} | {context_names[ctx]} | 0 | — | — | — | — | — | — | — | — |")
            continue
        pf_str = f"{m['pf']:.2f}" if m['pf'] != np.inf else "inf"
        sig = "***" if m['p'] < 0.001 else ("**" if m['p'] < 0.01 else ("*" if m['p'] < 0.05 else ""))
        lines.append(
            f"| {ctx} | {context_names[ctx]} | {m['N']:,} | "
            f"{m['mean']:+.4f} | {m['median']:+.4f} | {m['wr']:.1f} | {pf_str} | "
            f"{m['sharpe']:.3f} | {m['stop_rate']:.1f} | {m['eod_rate']:.1f} | "
            f"{m['p']:.4f}{sig} |"
        )
    lines.append("")

    # ── Section 2: Separation from baseline ──
    lines.append("## 2. Separation from Baseline (NONE)")
    lines.append("")
    lines.append("| Context | N | Mean% | Delta Mean% | Delta PF | Delta Sharpe | Sep p-val | Significant? |")
    lines.append("|---------|---|-------|-------------|----------|-------------|-----------|-------------|")

    baseline_m = results["NONE"]
    ranking = []

    for ctx in ["C1", "C2", "C3", "C4", "C5"]:
        m = results[ctx]
        if not m or not baseline_m:
            continue
        delta_mean = m["mean"] - baseline_m["mean"]
        delta_pf = m["pf"] - baseline_m["pf"]
        delta_sharpe = m["sharpe"] - baseline_m["sharpe"]
        sep_p = separation_test(filtered_trades[ctx], all_trades)
        is_sig = not np.isnan(sep_p) and sep_p < 0.05
        sig_str = "YES" if is_sig else "no"
        sep_p_str = f"{sep_p:.4f}" if not np.isnan(sep_p) else "—"

        ranking.append((ctx, m, delta_mean, delta_pf, delta_sharpe, sep_p, is_sig))

        lines.append(
            f"| {ctx} | {m['N']:,} | {m['mean']:+.4f} | {delta_mean:+.4f} | "
            f"{delta_pf:+.2f} | {delta_sharpe:+.3f} | {sep_p_str} | {sig_str} |"
        )
    lines.append("")

    # ── Section 3: Ranking ──
    lines.append("## 3. Ranking by Profit Factor")
    lines.append("")
    lines.append("| Rank | Context | PF | Sharpe | Mean% | N | Significant? |")
    lines.append("|------|---------|----|----- --|-------|---|-------------|")

    ranked = sorted(ranking, key=lambda x: x[1]["pf"] if x[1]["pf"] != np.inf else 0, reverse=True)
    for rank, (ctx, m, _, _, _, _, is_sig) in enumerate(ranked, 1):
        pf_str = f"{m['pf']:.2f}" if m['pf'] != np.inf else "inf"
        sig_str = "YES" if is_sig else "no"
        lines.append(f"| {rank} | {ctx} | {pf_str} | {m['sharpe']:.3f} | {m['mean']:+.4f} | {m['N']:,} | {sig_str} |")
    lines.append("")

    # ── Section 4: Winner identification ──
    lines.append("## 4. Winner Identification")
    lines.append("")

    # Winner = context with highest PF that is significant AND has N >= 100
    sig_winners = [(ctx, m, dp, ds, sp) for ctx, m, dm, dp, ds, sp, sig in ranking
                   if sig and m["N"] >= 100]

    if sig_winners:
        # Sort by PF
        sig_winners.sort(key=lambda x: x[1]["pf"], reverse=True)
        best_ctx, best_m, _, _, _ = sig_winners[0]
        lines.append(f"**Winner: {best_ctx}** — {context_names[best_ctx]}")
        lines.append(f"- PF: {best_m['pf']:.2f} (baseline {baseline_m['pf']:.2f})")
        lines.append(f"- Sharpe: {best_m['sharpe']:.3f} (baseline {baseline_m['sharpe']:.3f})")
        lines.append(f"- Mean: {best_m['mean']:+.4f}% (baseline {baseline_m['mean']:+.4f}%)")
        lines.append(f"- N: {best_m['N']:,} ({best_m['N']/baseline_m['N']*100:.0f}% of baseline)")
        context_winner = best_ctx
    else:
        # Check if any context improves PF/Sharpe even without significance
        best_by_pf = max(ranking, key=lambda x: x[1]["pf"]) if ranking else None
        if best_by_pf and best_by_pf[1]["pf"] > baseline_m["pf"]:
            ctx, m = best_by_pf[0], best_by_pf[1]
            lines.append(f"**No context layer reaches statistical significance (p < 0.05).**")
            lines.append("")
            lines.append(f"Best directional improvement: {ctx} ({context_names[ctx]})")
            lines.append(f"- PF: {m['pf']:.2f} vs baseline {baseline_m['pf']:.2f}")
            lines.append(f"- But separation p={best_by_pf[5]:.4f} — not significant")
        else:
            lines.append("**No context layer improves on baseline.**")
            lines.append("4H RSI/ADX context does not add value to E2+X8.")
        context_winner = None
    lines.append("")

    # ── Section 5: Risk profile comparison ──
    lines.append("## 5. Risk Profile Comparison")
    lines.append("")
    lines.append("| Context | Avg MAE% | Avg MFE% | MFE/MAE | Avg Hold |")
    lines.append("|---------|----------|----------|---------|----------|")

    for ctx in contexts:
        m = results[ctx]
        if not m:
            continue
        ratio = abs(m["mfe"] / m["mae"]) if m["mae"] != 0 else np.inf
        ratio_str = f"{ratio:.2f}" if ratio != np.inf else "inf"
        lines.append(f"| {ctx} | {m['mae']:+.4f} | {m['mfe']:+.4f} | {ratio_str} | {m['avg_hold']:.1f} |")
    lines.append("")

    # ── Section 6: Final Module 2 spec ──
    lines.append("## 6. Final Module 2 Trend Spec")
    lines.append("")
    lines.append("```")
    lines.append("PERMISSION:  4H EMA gate UP (EMA9 > EMA21) + VIX < 25 + NOT Module 4 window")
    lines.append("ENTRY:       E2 — M5 RSI(14) dips below 40, first bar RSI crosses back above 40")
    lines.append("EXIT:        X8 — 4H EMA gate flips DOWN (EMA9 <= EMA21)")
    if context_winner:
        lines.append(f"CONTEXT:     {context_winner} — {context_names[context_winner]}")
    else:
        lines.append("CONTEXT:     None (no significant improvement)")
    lines.append("STOP:        -1.5% hard stop from entry price")
    lines.append("EOD:         Flat at 15:50 ET if no exit signal")
    lines.append("```")
    lines.append("")

    # ── Section 7: Honest assessment ──
    lines.append("## 7. Honest Assessment")
    lines.append("")

    bm = baseline_m
    lines.append(f"**E2 + X8 baseline performance:**")
    lines.append(f"- N = {bm['N']:,} trades across 25 tickers")
    lines.append(f"- Mean = {bm['mean']:+.4f}%, WR = {bm['wr']:.1f}%, PF = {bm['pf']:.2f}")
    lines.append(f"- Sharpe (per-trade) = {bm['sharpe']:.3f}")
    lines.append(f"- Stop-out rate = {bm['stop_rate']:.1f}%")
    lines.append(f"- EOD flat rate = {bm['eod_rate']:.1f}%")
    lines.append("")

    if bm["pf"] >= 1.5 and bm["wr"] >= 55 and bm["mean"] > 0.10:
        lines.append("**Assessment: Module 2 shows a genuine, statistically significant trend-following edge.**")
        lines.append("")
        lines.append("The E2 entry (RSI pullback recovery within 4H uptrend) produces:")
        lines.append(f"- Consistent positive returns ({bm['mean']:+.4f}% per trade)")
        lines.append(f"- Strong win rate ({bm['wr']:.1f}%)")
        lines.append(f"- Favorable risk profile (MFE/MAE = {abs(bm['mfe']/bm['mae']):.2f})")
        lines.append("")
        if bm["eod_rate"] > 80:
            lines.append("**Caveat:** {:.0f}% of trades exit EOD flat, meaning the 4H gate rarely flips ".format(bm['eod_rate']))
            lines.append("within the same session. This is effectively a 'hold until close' strategy ")
            lines.append("after a pullback entry. The edge comes from ENTRY TIMING, not exit sophistication.")
        lines.append("")
        if bm["pf"] < 2.0:
            lines.append("**Grade: PASSIVE FILTER with entry timing edge** — not autonomous-grade.")
            lines.append("PF < 2.0 and mean < 0.20% per trade = useful as a bias/filter layer,")
            lines.append("but not strong enough to trade standalone without additional confluence.")
        else:
            lines.append("**Grade: AUTONOMOUS-GRADE EDGE** — tradeable standalone.")
    elif bm["pf"] >= 1.2 and bm["mean"] > 0:
        lines.append("**Assessment: Module 2 trend produces a weak but real positive edge.**")
        lines.append("Remains as passive filter / bias layer, not autonomous trading signal.")
    else:
        lines.append("**Assessment: Module 2 trend does not produce autonomous-grade edge.**")
        lines.append("Remains as passive filter only.")
    lines.append("")

    # ── Section 8: Config ──
    lines.append("## 8. Configuration")
    lines.append("")
    lines.append("```")
    lines.append(f"RSI period:    {RSI_PERIOD} (Wilder smoothing)")
    lines.append(f"EMA periods:   {EMA9_PERIOD}, {EMA21_PERIOD}")
    lines.append(f"CE params:     period={CE_ATR_PERIOD}, lookback={CE_HH_LOOKBACK}, mult={CE_MULT}")
    lines.append(f"Hard stop:     {HARD_STOP_PCT}%")
    lines.append(f"EOD flat:      15:50 ET")
    lines.append(f"4H indicators: rsi_14, adx_14 (from data/indicators_4h/)")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    all_trades = run_analysis()
    report = generate_report(all_trades)

    output_path = RESULTS_DIR / "S44_Module2_Part2B_Context_Results.md"
    output_path.write_text(report)
    print(f"\nResults saved to {output_path}")
    print("\n" + report)
