#!/usr/bin/env python3
"""
S44 Module 2 — Part 1/3: Entry Variants (M5 Pullback within 4H Uptrend).

Pre-filter:
  1. 4H EMA9 > EMA21 on most recent COMPLETED 4H bar (gate UP)
  2. VIX < 25 (prior-day close) — NORMAL or ELEVATED only
  3. NOT within Module 4 trigger window (3 consecutive 4H down bars)

Entry variants:
  BASELINE — Any qualifying M5 bar (no M5 filter)
  E1 — EMA9 pullback + reclaim
  E2 — RSI dip below 40 + recovery above 40
  E3 — CE flip from SHORT to LONG
  E4 — EMA21 dip + reclaim
  E5 — Combined: RSI < 50 AND close < EMA9, then both flip back

Forward returns: +6, +12, +24, +48 M5 bars
VIX regime split: NORMAL (<20), ELEVATED (20-25)

Output: results/S44_Module2_Part1_Entry_Results.md
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
    "AAPL", "AMD", "AMZN", "AVGO", "BA", "BABA", "BIDU", "C", "COIN",
    "COST", "GOOGL", "GS", "IBIT", "JPM", "MARA", "META", "MSFT", "MU",
    "NVDA", "PLTR", "SNOW", "TSLA", "TSM", "TXN", "V",
]

INDICATORS_4H_DIR = ROOT / "data" / "indicators_4h"
VIX_PATH = ROOT / "Fetched_Data" / "VIXCLS_FRED_real.csv"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

FORWARD_BARS = [6, 12, 24, 48]
FORWARD_LABELS = {6: "+30m", 12: "+1hr", 24: "+2hr", 48: "+4hr"}

# Indicator params
EMA9_PERIOD = 9
EMA21_PERIOD = 21
RSI_PERIOD = 14
CE_ATR_PERIOD = 14
CE_HH_LOOKBACK = 22
CE_MULT = 2.0
ADX_PERIOD = 20  # Fixed from DMI diagnostics


# ── Indicator functions ───────────────────────────────────────────────────────

def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(close, period=14):
    """RSI with Wilder smoothing."""
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
    """CE LONG state: close > (highest_high_22 - mult * ATR)."""
    atr = calc_atr(high, low, close, atr_period)
    hh = high.rolling(window=hh_lookback, min_periods=hh_lookback).max()
    ce_long_stop = hh - mult * atr
    return close > ce_long_stop


# ── VIX loading ───────────────────────────────────────────────────────────────

def load_vix():
    """Load VIX daily closes. Returns Series indexed by date string."""
    df = pd.read_csv(VIX_PATH)
    df["observation_date"] = pd.to_datetime(df["observation_date"])
    df = df.dropna(subset=["VIXCLS"])
    df = df.set_index("observation_date").sort_index()
    # Forward-fill to cover weekends/holidays, then create date-string lookup
    df = df.reindex(pd.date_range(df.index.min(), df.index.max(), freq="D"), method="ffill")
    return df["VIXCLS"]


# ── 4H EMA gate + Module 4 exclusion ─────────────────────────────────────────

def load_4h_bars(ticker):
    path = INDICATORS_4H_DIR / f"{ticker}_4h_indicators.csv"
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["date_str"] = df["timestamp"].dt.strftime("%Y-%m-%d")
    df["time_str"] = df["timestamp"].dt.strftime("%H:%M")
    return df


def detect_module4_windows(bars_4h):
    """
    Module 4 trigger: 3 consecutive 4H bars where close < open (down bars).
    Returns set of (date_str, session) tuples that fall within trigger windows.
    The window covers the 3 down bars themselves.
    """
    closes = bars_4h["close"].values
    opens = bars_4h["open"].values
    is_down = closes < opens

    blocked = set()
    for i in range(2, len(bars_4h)):
        if is_down[i] and is_down[i - 1] and is_down[i - 2]:
            # Block all 3 bars' sessions
            for j in [i - 2, i - 1, i]:
                row = bars_4h.iloc[j]
                session = "AM" if row["time_str"] == "09:30" else "PM"
                blocked.add((row["date_str"], session))
    return blocked


def map_m5_to_4h_gate_and_filters(m5_df, bars_4h, vix_series):
    """
    For each M5 bar, determine:
    - gate_up: 4H EMA9 > EMA21 on most recent completed bar
    - vix_ok: prior-day VIX < 25
    - vix_regime: 'NORMAL' (<20) or 'ELEVATED' (20-25)
    - not_module4: not in a Module 4 trigger window
    """
    # Build 4H bar lookup
    bar_lookup = {}
    for i, row in bars_4h.iterrows():
        session = "AM" if row["time_str"] == "09:30" else "PM"
        bar_lookup[(row["date_str"], session)] = i

    trading_dates = sorted(bars_4h["date_str"].unique())
    date_to_prev = {}
    for j in range(1, len(trading_dates)):
        date_to_prev[trading_dates[j]] = trading_dates[j - 1]

    # Module 4 blocked sessions
    module4_blocked = detect_module4_windows(bars_4h)

    n = len(m5_df)
    gate_up = np.zeros(n, dtype=bool)
    vix_ok = np.zeros(n, dtype=bool)
    vix_regime = np.full(n, "", dtype=object)
    not_module4 = np.ones(n, dtype=bool)

    for idx in range(n):
        m5_ts = m5_df["Datetime"].iloc[idx]
        m5_date = m5_ts.strftime("%Y-%m-%d")
        m5_minutes = m5_ts.hour * 60 + m5_ts.minute

        # Determine which completed 4H bar to reference
        if m5_minutes < 13 * 60 + 30:
            # AM session: use previous day's PM bar
            prev_date = date_to_prev.get(m5_date)
            bar_idx = bar_lookup.get((prev_date, "PM")) if prev_date else None
            current_session = (m5_date, "AM")
        else:
            # PM session: use today's AM bar
            bar_idx = bar_lookup.get((m5_date, "AM"))
            current_session = (m5_date, "PM")

        # 4H EMA gate
        if bar_idx is not None:
            h4 = bars_4h.iloc[bar_idx]
            ema9 = h4["ema_9"]
            ema21 = h4["ema_21"]
            if pd.notna(ema9) and pd.notna(ema21):
                gate_up[idx] = ema9 > ema21

        # Module 4 exclusion
        if current_session in module4_blocked:
            not_module4[idx] = False

        # VIX: prior-day close
        m5_date_ts = pd.Timestamp(m5_date)
        prior_day = m5_date_ts - pd.Timedelta(days=1)
        # Walk back to find a valid VIX observation
        vix_val = None
        for offset in range(4):  # up to 3 days back for weekends
            lookup = prior_day - pd.Timedelta(days=offset)
            if lookup in vix_series.index:
                vix_val = vix_series[lookup]
                break

        if vix_val is not None and vix_val < 25:
            vix_ok[idx] = True
            if vix_val < 20:
                vix_regime[idx] = "NORMAL"
            else:
                vix_regime[idx] = "ELEVATED"

    return gate_up, vix_ok, vix_regime, not_module4


# ── Forward returns ───────────────────────────────────────────────────────────

def compute_forward_returns(closes, horizons):
    """Forward return % at each horizon, session-boundary aware."""
    result = {}
    vals = closes.values
    n = len(vals)
    for h in horizons:
        fwd = np.full(n, np.nan)
        for i in range(n - h):
            fwd[i] = (vals[i + h] - vals[i]) / vals[i] * 100
        result[h] = fwd
    return result


# ── Entry signal detection ────────────────────────────────────────────────────

def detect_entry_signals(m5_df, ema9, ema21, rsi, ce_long):
    """
    Detect entry signals for E1-E5.
    Returns dict of boolean arrays (True on the signal bar).
    """
    close = m5_df["Close"].values
    ema9_v = ema9.values
    ema21_v = ema21.values
    rsi_v = rsi.values
    ce_v = ce_long.values
    n = len(close)

    # E1: EMA9 pullback + reclaim
    # Close dips below EMA9, then first bar closing back above
    e1 = np.zeros(n, dtype=bool)
    below_ema9 = False
    for i in range(1, n):
        if np.isnan(ema9_v[i]):
            below_ema9 = False
            continue
        if close[i - 1] < ema9_v[i - 1] if not np.isnan(ema9_v[i - 1]) else False:
            below_ema9 = True
        if below_ema9 and close[i] > ema9_v[i]:
            e1[i] = True
            below_ema9 = False  # Reset after signal

    # E2: RSI dip below 40 + recovery above 40
    e2 = np.zeros(n, dtype=bool)
    below_40 = False
    for i in range(1, n):
        if np.isnan(rsi_v[i]):
            below_40 = False
            continue
        if rsi_v[i - 1] < 40 if not np.isnan(rsi_v[i - 1]) else False:
            below_40 = True
        if below_40 and rsi_v[i] >= 40:
            e2[i] = True
            below_40 = False

    # E3: CE flip from SHORT to LONG
    e3 = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(ce_v[i]) and not np.isnan(ce_v[i - 1]):
            if ce_v[i] and not ce_v[i - 1]:
                e3[i] = True

    # E4: EMA21 dip + reclaim
    e4 = np.zeros(n, dtype=bool)
    below_ema21 = False
    for i in range(1, n):
        if np.isnan(ema21_v[i]):
            below_ema21 = False
            continue
        if close[i - 1] < ema21_v[i - 1] if not np.isnan(ema21_v[i - 1]) else False:
            below_ema21 = True
        if below_ema21 and close[i] > ema21_v[i]:
            e4[i] = True
            below_ema21 = False

    # E5: Combined — RSI < 50 AND close < EMA9 simultaneously,
    #     then first bar where BOTH flip back (RSI >= 50 AND close >= EMA9)
    e5 = np.zeros(n, dtype=bool)
    in_dip = False
    for i in range(1, n):
        if np.isnan(rsi_v[i]) or np.isnan(ema9_v[i]):
            in_dip = False
            continue
        prev_rsi = rsi_v[i - 1] if not np.isnan(rsi_v[i - 1]) else 50
        prev_ema9 = ema9_v[i - 1] if not np.isnan(ema9_v[i - 1]) else close[i - 1]
        if prev_rsi < 50 and close[i - 1] < prev_ema9:
            in_dip = True
        if in_dip and rsi_v[i] >= 50 and close[i] >= ema9_v[i]:
            e5[i] = True
            in_dip = False

    return {"E1": e1, "E2": e2, "E3": e3, "E4": e4, "E5": e5}


# ── Main analysis ─────────────────────────────────────────────────────────────

def run_analysis():
    vix_series = load_vix()
    print(f"VIX data: {len(vix_series)} daily observations")

    all_rows = []

    for ticker in TICKERS:
        print(f"Processing {ticker}...")

        bars_4h = load_4h_bars(ticker)
        try:
            m5_df = load_m5_regsess(ticker)
        except (FileNotFoundError, ValueError) as e:
            print(f"  SKIP {ticker}: {e}")
            continue

        # Pre-filters
        gate_up, vix_ok, vix_regime, not_module4 = map_m5_to_4h_gate_and_filters(
            m5_df, bars_4h, vix_series
        )

        # M5 indicators
        close = m5_df["Close"]
        high = m5_df["High"]
        low = m5_df["Low"]

        ema9 = calc_ema(close, EMA9_PERIOD)
        ema21 = calc_ema(close, EMA21_PERIOD)
        rsi = calc_rsi(close, RSI_PERIOD)
        ce_long = calc_chandelier_state(high, low, close, CE_ATR_PERIOD, CE_HH_LOOKBACK, CE_MULT)

        # Forward returns
        fwd_rets = compute_forward_returns(close, FORWARD_BARS)

        # Entry signals
        signals = detect_entry_signals(m5_df, ema9, ema21, rsi, ce_long)

        # Build rows (only qualifying bars)
        for i in range(len(m5_df)):
            if not (gate_up[i] and vix_ok[i] and not_module4[i]):
                continue

            row = {
                "ticker": ticker,
                "datetime": m5_df["Datetime"].iloc[i],
                "vix_regime": vix_regime[i],
                "is_baseline": True,
            }

            for name, sig_arr in signals.items():
                row[name] = bool(sig_arr[i])

            for h in FORWARD_BARS:
                row[f"fwd_{h}"] = fwd_rets[h][i]

            all_rows.append(row)

    df = pd.DataFrame(all_rows)
    print(f"\nTotal qualifying M5 bars (BASELINE): {len(df):,}")
    for name in ["E1", "E2", "E3", "E4", "E5"]:
        print(f"  {name} signals: {df[name].sum():,}")
    return df


# ── Metrics ───────────────────────────────────────────────────────────────────

def group_metrics(vals):
    """Compute N, mean, win rate, profit factor, std, p-value."""
    vals = vals.dropna()
    n = len(vals)
    if n < 3:
        return {"N": n, "mean": np.nan, "wr": np.nan, "pf": np.nan, "std": np.nan, "p": np.nan}
    mean = vals.mean()
    wr = (vals > 0).sum() / n * 100
    gains = vals[vals > 0].sum()
    losses = abs(vals[vals < 0].sum())
    pf = gains / losses if losses > 0 else np.inf
    std = vals.std()
    _, p = stats.ttest_1samp(vals, 0)
    p = p / 2 if mean > 0 else 1 - p / 2  # one-sided
    return {"N": n, "mean": mean, "wr": wr, "pf": pf, "std": std, "p": p}


def separation_test(variant_vals, baseline_vals):
    """Two-sample t-test for separation between variant and baseline."""
    v = variant_vals.dropna()
    b = baseline_vals.dropna()
    if len(v) < 3 or len(b) < 3:
        return np.nan
    _, p = stats.ttest_ind(v, b, equal_var=False)
    return p


# ── Report ────────────────────────────────────────────────────────────────────

def generate_report(df):
    lines = []
    lines.append("# S44 Module 2 — Part 1: Entry Variants (M5 Pullback within 4H Uptrend)")
    lines.append("")
    lines.append(f"**Date:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Pre-filter:** 4H EMA gate UP + VIX < 25 + NOT Module 4 window")
    lines.append(f"**Total qualifying M5 bars (BASELINE):** {len(df):,}")
    lines.append(f"**Tickers:** {df['ticker'].nunique()}/25")
    lines.append("")

    variant_names = {
        "BASELINE": "Any qualifying M5 bar (no M5 filter)",
        "E1": "EMA9 pullback + reclaim",
        "E2": "RSI dip below 40 + recovery",
        "E3": "CE flip SHORT → LONG",
        "E4": "EMA21 dip + reclaim",
        "E5": "Combined: RSI<50 & close<EMA9, then both flip",
    }

    regimes = ["ALL", "NORMAL", "ELEVATED"]

    # ── Section 1: Full results table ──
    lines.append("## 1. Entry Variant Results")
    lines.append("")

    # Store results for ranking
    all_results = {}  # (variant, regime, horizon) -> metrics dict
    baseline_cache = {}  # (regime, horizon) -> Series of returns

    for regime in regimes:
        lines.append(f"### VIX Regime: {regime}")
        lines.append("")

        if regime == "ALL":
            regime_df = df
        elif regime == "NORMAL":
            regime_df = df[df["vix_regime"] == "NORMAL"]
        else:
            regime_df = df[df["vix_regime"] == "ELEVATED"]

        if len(regime_df) == 0:
            lines.append("*No data for this regime.*")
            lines.append("")
            continue

        lines.append("| Variant | Description | Horizon | N | Mean% | WR% | PF | Sep% | Sep p-val |")
        lines.append("|---------|-------------|---------|---|-------|-----|----|------|-----------|")

        # BASELINE
        for h in FORWARD_BARS:
            col = f"fwd_{h}"
            baseline_vals = regime_df[col]
            baseline_cache[(regime, h)] = baseline_vals
            m = group_metrics(baseline_vals)
            all_results[("BASELINE", regime, h)] = m

            pf_str = f"{m['pf']:.2f}" if m['pf'] != np.inf else "∞"
            lines.append(
                f"| BASELINE | {variant_names['BASELINE']} | {FORWARD_LABELS[h]} | "
                f"{m['N']:,} | {m['mean']:+.4f} | {m['wr']:.1f} | {pf_str} | — | — |"
                if not np.isnan(m['mean']) else
                f"| BASELINE | {variant_names['BASELINE']} | {FORWARD_LABELS[h]} | {m['N']} | — | — | — | — | — |"
            )

        # Entry variants E1-E5
        for variant in ["E1", "E2", "E3", "E4", "E5"]:
            variant_df = regime_df[regime_df[variant] == True]

            for h in FORWARD_BARS:
                col = f"fwd_{h}"
                v_vals = variant_df[col]
                m = group_metrics(v_vals)
                all_results[(variant, regime, h)] = m

                # Separation from baseline
                b_m = all_results[("BASELINE", regime, h)]
                sep = m["mean"] - b_m["mean"] if not (np.isnan(m["mean"]) or np.isnan(b_m["mean"])) else np.nan
                sep_p = separation_test(v_vals, baseline_cache[(regime, h)])

                sig = ""
                if not np.isnan(sep_p):
                    sig = "***" if sep_p < 0.001 else ("**" if sep_p < 0.01 else ("*" if sep_p < 0.05 else ""))

                if not np.isnan(m["mean"]):
                    pf_str = f"{m['pf']:.2f}" if m['pf'] != np.inf else "∞"
                    sep_str = f"{sep:+.4f}" if not np.isnan(sep) else "—"
                    sep_p_str = f"{sep_p:.4f}{sig}" if not np.isnan(sep_p) else "—"
                    lines.append(
                        f"| {variant} | {variant_names[variant]} | {FORWARD_LABELS[h]} | "
                        f"{m['N']:,} | {m['mean']:+.4f} | {m['wr']:.1f} | {pf_str} | "
                        f"{sep_str} | {sep_p_str} |"
                    )
                else:
                    lines.append(
                        f"| {variant} | {variant_names[variant]} | {FORWARD_LABELS[h]} | "
                        f"{m['N']} | — | — | — | — | — |"
                    )

        lines.append("")

    # ── Section 2: Ranking by separation from BASELINE ──
    lines.append("## 2. Ranking by Separation from BASELINE")
    lines.append("")
    lines.append("Ranked by absolute separation at +2hr horizon (ALL regimes).")
    lines.append("")
    lines.append("| Rank | Variant | Sep% (+2hr) | p-val | Significant? |")
    lines.append("|------|---------|-------------|-------|--------------|")

    ranking = []
    for variant in ["E1", "E2", "E3", "E4", "E5"]:
        v_m = all_results.get((variant, "ALL", 24))
        b_m = all_results.get(("BASELINE", "ALL", 24))
        if v_m and b_m and not np.isnan(v_m["mean"]) and not np.isnan(b_m["mean"]):
            sep = v_m["mean"] - b_m["mean"]
            # Recompute p-val for ALL regime
            all_df = df
            v_vals = all_df[all_df[variant] == True]["fwd_24"]
            b_vals = all_df["fwd_24"]
            sep_p = separation_test(v_vals, b_vals)
            ranking.append((variant, sep, sep_p))

    ranking.sort(key=lambda x: abs(x[1]), reverse=True)
    for rank, (variant, sep, sep_p) in enumerate(ranking, 1):
        is_sig = "YES" if (not np.isnan(sep_p) and sep_p < 0.05) else "no"
        sep_p_str = f"{sep_p:.4f}" if not np.isnan(sep_p) else "—"
        lines.append(f"| {rank} | {variant} | {sep:+.4f} | {sep_p_str} | {is_sig} |")
    lines.append("")

    # ── Section 3: Best horizon for each variant ──
    lines.append("## 3. Best Horizon per Variant")
    lines.append("")
    lines.append("| Variant | Best Horizon | Mean% | Sep% from BASELINE | p-val |")
    lines.append("|---------|-------------|-------|-------------------|-------|")

    for variant in ["BASELINE", "E1", "E2", "E3", "E4", "E5"]:
        best_h = None
        best_mean = -np.inf
        for h in FORWARD_BARS:
            m = all_results.get((variant, "ALL", h))
            if m and not np.isnan(m["mean"]) and m["mean"] > best_mean:
                best_mean = m["mean"]
                best_h = h
        if best_h is not None:
            b_m = all_results.get(("BASELINE", "ALL", best_h))
            sep = best_mean - b_m["mean"] if variant != "BASELINE" and not np.isnan(b_m["mean"]) else 0
            # p-val
            if variant != "BASELINE":
                v_vals = df[df[variant] == True][f"fwd_{best_h}"]
                sep_p = separation_test(v_vals, df[f"fwd_{best_h}"])
                sep_p_str = f"{sep_p:.4f}" if not np.isnan(sep_p) else "—"
            else:
                sep_p_str = "—"
            lines.append(
                f"| {variant} | {FORWARD_LABELS[best_h]} | {best_mean:+.4f} | "
                f"{sep:+.4f} | {sep_p_str} |"
            )
    lines.append("")

    # ── Section 4: Winner identification ──
    lines.append("## 4. Winner Identification")
    lines.append("")

    sig_winners = [(v, s, p) for v, s, p in ranking if not np.isnan(p) and p < 0.05]

    if sig_winners:
        best_v, best_sep, best_p = sig_winners[0]
        lines.append(f"**Winner: {best_v}** — {variant_names[best_v]}")
        lines.append(f"- Separation from BASELINE at +2hr: {best_sep:+.4f}% (p={best_p:.4f})")
        lines.append("")
        lines.append("Significant variants:")
        for v, s, p in sig_winners:
            lines.append(f"- **{v}**: {variant_names[v]} — sep={s:+.4f}%, p={p:.4f}")
    else:
        lines.append("**No variant beats BASELINE significantly (p < 0.05).**")
        lines.append("")
        lines.append("M5 pullback entry does not add value within 4H uptrend.")
        lines.append("This is consistent with S44's finding that 4H context explains 10× more than M5 scoring.")
    lines.append("")

    # ── Section 5: VIX regime comparison ──
    lines.append("## 5. VIX Regime Comparison")
    lines.append("")
    lines.append("| Regime | BASELINE N | BASELINE Mean% (+2hr) | Best Variant | Best Sep% | p-val |")
    lines.append("|--------|-----------|----------------------|-------------|----------|-------|")

    for regime in ["NORMAL", "ELEVATED"]:
        b_m = all_results.get(("BASELINE", regime, 24), {})
        if not b_m or np.isnan(b_m.get("mean", np.nan)):
            lines.append(f"| {regime} | — | — | — | — | — |")
            continue

        best_v = None
        best_sep = 0
        best_p = 1
        for variant in ["E1", "E2", "E3", "E4", "E5"]:
            v_m = all_results.get((variant, regime, 24))
            if v_m and not np.isnan(v_m["mean"]):
                sep = v_m["mean"] - b_m["mean"]
                if abs(sep) > abs(best_sep):
                    best_sep = sep
                    best_v = variant
                    # Compute p-val
                    if regime == "NORMAL":
                        rdf = df[df["vix_regime"] == "NORMAL"]
                    else:
                        rdf = df[df["vix_regime"] == "ELEVATED"]
                    v_vals = rdf[rdf[variant] == True]["fwd_24"]
                    best_p = separation_test(v_vals, rdf["fwd_24"])

        best_p_str = f"{best_p:.4f}" if not np.isnan(best_p) else "—"
        lines.append(
            f"| {regime} | {b_m['N']:,} | {b_m['mean']:+.4f} | "
            f"{best_v or '—'} | {best_sep:+.4f} | {best_p_str} |"
        )
    lines.append("")

    # ── Section 6: Signal counts summary ──
    lines.append("## 6. Signal Count Summary")
    lines.append("")
    lines.append("| Variant | Total Signals | % of BASELINE | Avg Signals/Ticker |")
    lines.append("|---------|--------------|--------------|-------------------|")

    n_tickers = df["ticker"].nunique()
    for variant in ["BASELINE", "E1", "E2", "E3", "E4", "E5"]:
        if variant == "BASELINE":
            n_sig = len(df)
        else:
            n_sig = df[variant].sum()
        pct = n_sig / len(df) * 100 if len(df) > 0 else 0
        avg = n_sig / n_tickers if n_tickers > 0 else 0
        lines.append(f"| {variant} | {n_sig:,} | {pct:.1f}% | {avg:,.0f} |")
    lines.append("")

    # ── Config note ──
    lines.append("## 7. Configuration")
    lines.append("")
    lines.append("```")
    lines.append(f"RSI period:    {RSI_PERIOD} (Wilder smoothing)")
    lines.append(f"ADX period:    {ADX_PERIOD} (Wilder smoothing)")
    lines.append(f"EMA periods:   {EMA9_PERIOD}, {EMA21_PERIOD}")
    lines.append(f"CE params:     period={CE_ATR_PERIOD}, lookback={CE_HH_LOOKBACK}, mult={CE_MULT}")
    lines.append(f"RSI threshold: 40 (E2), 50 (E5)")
    lines.append(f"Horizons:      {', '.join(FORWARD_LABELS[h] for h in FORWARD_BARS)}")
    lines.append(f"VIX regimes:   NORMAL (<20), ELEVATED (20-25)")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    df = run_analysis()
    report = generate_report(df)

    output_path = RESULTS_DIR / "S44_Module2_Part1_Entry_Results.md"
    output_path.write_text(report)
    print(f"\nResults saved to {output_path}")
    print("\n" + report)
