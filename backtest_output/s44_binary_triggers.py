#!/usr/bin/env python3
"""
S44 Task: M5 TQS Replacement — Binary Triggers.

Pre-filter: 4H EMA gate = UP (EMA9 > EMA21 on most recent completed 4H bar).
Then compare 5 independent binary M5 triggers on forward returns.

Also computes TQS_quant = 0.76*RSI_phase + 0.24*DMI_alignment for head-to-head.

Output: results/S44_Binary_Triggers_Results.md
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
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

FORWARD_BARS = [6, 12, 24]
FORWARD_LABELS = {6: "+30m", 12: "+1hr", 24: "+2hr"}

# Chandelier Exit params (from chandelier_exit_backtest.py)
CE_ATR_PERIOD = 14
CE_HH_LOOKBACK = 22
CE_MULT = 2.0

# M5 indicator periods
EMA9_PERIOD = 9
EMA21_PERIOD = 21
RSI_PERIOD = 14
SWING_LOOKBACK = 5

# ADX for TQS (period=14, matching existing data)
ADX_PERIOD = 14


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
    """
    Compute Chandelier Exit LONG state for each bar.
    CE_LONG: close > (highest_high_22 - mult * ATR)
    """
    atr = calc_atr(high, low, close, atr_period)
    hh = high.rolling(window=hh_lookback, min_periods=hh_lookback).max()
    ce_long_stop = hh - mult * atr
    return close > ce_long_stop


def calc_adx(high, low, close, period=14):
    """Compute ADX using Wilder smoothing."""
    n = len(close)
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    atr_s = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / atr_s
    minus_di = 100 * minus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / atr_s

    di_sum = plus_di + minus_di
    dx = (100 * (plus_di - minus_di).abs() / di_sum).where(di_sum > 0, 0.0)
    adx = dx.ewm(alpha=1.0 / period, adjust=False).mean()
    return adx, plus_di, minus_di


def calc_higher_low(low, lookback=5):
    """True if current low > min of previous `lookback` lows."""
    swing_low = low.rolling(window=lookback, min_periods=lookback).min().shift(1)
    return low > swing_low


# ── 4H EMA gate mapping ──────────────────────────────────────────────────────

def load_4h_bars(ticker):
    path = INDICATORS_4H_DIR / f"{ticker}_4h_indicators.csv"
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["date_str"] = df["timestamp"].dt.strftime("%Y-%m-%d")
    df["time_str"] = df["timestamp"].dt.strftime("%H:%M")
    return df


def map_m5_to_4h_ema_gate(m5_df, bars_4h):
    """
    For each M5 bar, determine if 4H EMA gate = UP on most recent completed bar.
    Uses same lookahead-safe mapping as Prompt 3.
    """
    bar_lookup = {}
    for i, row in bars_4h.iterrows():
        session = "AM" if row["time_str"] == "09:30" else "PM"
        bar_lookup[(row["date_str"], session)] = i

    trading_dates = sorted(bars_4h["date_str"].unique())
    date_to_prev = {}
    for j in range(1, len(trading_dates)):
        date_to_prev[trading_dates[j]] = trading_dates[j - 1]

    gate_up = []
    for _, m5_row in m5_df.iterrows():
        m5_ts = m5_row["Datetime"]
        m5_date = m5_ts.strftime("%Y-%m-%d")
        m5_minutes = m5_ts.hour * 60 + m5_ts.minute

        if m5_minutes < 13 * 60 + 30:
            prev_date = date_to_prev.get(m5_date)
            idx = bar_lookup.get((prev_date, "PM")) if prev_date else None
        else:
            idx = bar_lookup.get((m5_date, "AM"))

        if idx is not None:
            h4 = bars_4h.iloc[idx]
            ema9 = h4["ema_9"]
            ema21 = h4["ema_21"]
            if pd.notna(ema9) and pd.notna(ema21):
                gate_up.append(ema9 > ema21)
            else:
                gate_up.append(False)
        else:
            gate_up.append(False)

    return gate_up


# ── TQS computation ──────────────────────────────────────────────────────────

def compute_tqs(rsi, adx):
    """
    TQS_quant = 0.76 * RSI_phase + 0.24 * DMI_alignment
    RSI_phase = abs(RSI - 50) / 50  (0=neutral, 1=extreme)
    DMI_alignment = min(ADX / 50, 1.0)  (0=no trend, 1=strong trend)
    """
    rsi_phase = (rsi - 50).abs() / 50.0
    dmi_alignment = (adx / 50.0).clip(upper=1.0)
    tqs = 0.76 * rsi_phase + 0.24 * dmi_alignment
    return tqs


def classify_tqs(tqs_series):
    """Grade A (top third), B (middle), C (bottom third) using terciles."""
    q33 = tqs_series.quantile(0.333)
    q66 = tqs_series.quantile(0.666)
    grades = pd.Series("B", index=tqs_series.index)
    grades[tqs_series <= q33] = "C"
    grades[tqs_series >= q66] = "A"
    return grades


# ── Forward returns ───────────────────────────────────────────────────────────

def compute_forward_returns(closes, horizons):
    result = {}
    vals = closes.values
    n = len(vals)
    for h in horizons:
        fwd = np.full(n, np.nan)
        for i in range(n - h):
            fwd[i] = (vals[i + h] - vals[i]) / vals[i] * 100
        result[h] = fwd
    return result


# ── Main analysis ─────────────────────────────────────────────────────────────

def run_analysis():
    all_rows = []

    for ticker in TICKERS:
        print(f"Processing {ticker}...")

        bars_4h = load_4h_bars(ticker)

        try:
            m5_df = load_m5_regsess(ticker)
        except (FileNotFoundError, ValueError) as e:
            print(f"  SKIP {ticker}: {e}")
            continue

        # 4H EMA gate mapping
        gate_up = map_m5_to_4h_ema_gate(m5_df, bars_4h)

        # M5 indicators
        close = m5_df["Close"]
        high = m5_df["High"]
        low = m5_df["Low"]

        ema9 = calc_ema(close, EMA9_PERIOD)
        ema21 = calc_ema(close, EMA21_PERIOD)
        rsi = calc_rsi(close, RSI_PERIOD)
        ce_long = calc_chandelier_state(high, low, close, CE_ATR_PERIOD, CE_HH_LOOKBACK, CE_MULT)
        higher_low = calc_higher_low(low, SWING_LOOKBACK)
        adx, plus_di, minus_di = calc_adx(high, low, close, ADX_PERIOD)

        # TQS
        tqs = compute_tqs(rsi, adx)

        # Forward returns
        fwd_rets = compute_forward_returns(close, FORWARD_BARS)

        # Build rows
        for i in range(len(m5_df)):
            if not gate_up[i]:
                continue  # Pre-filter: 4H EMA gate must be UP

            row = {
                "ticker": ticker,
                "T1_ema9_reclaim": bool(close.iloc[i] > ema9.iloc[i]) if pd.notna(ema9.iloc[i]) else None,
                "T2_rsi_above_50": bool(rsi.iloc[i] > 50) if pd.notna(rsi.iloc[i]) else None,
                "T3_ce_long": bool(ce_long.iloc[i]) if pd.notna(ce_long.iloc[i]) else None,
                "T4_higher_low": bool(higher_low.iloc[i]) if pd.notna(higher_low.iloc[i]) else None,
                "T5_ema_trend": bool(ema9.iloc[i] > ema21.iloc[i]) if (pd.notna(ema9.iloc[i]) and pd.notna(ema21.iloc[i])) else None,
                "tqs": tqs.iloc[i] if pd.notna(tqs.iloc[i]) else None,
            }

            for h in FORWARD_BARS:
                row[f"fwd_{h}"] = fwd_rets[h][i]

            all_rows.append(row)

    print(f"\nTotal M5 bars with 4H EMA gate UP: {len(all_rows):,}")
    df = pd.DataFrame(all_rows)

    # TQS grades (computed on the filtered dataset)
    valid_tqs = df["tqs"].dropna()
    if len(valid_tqs) > 0:
        df["tqs_grade"] = classify_tqs(df["tqs"])
    else:
        df["tqs_grade"] = "B"

    return df


# ── Metrics ───────────────────────────────────────────────────────────────────

def group_metrics(vals):
    vals = vals.dropna()
    n = len(vals)
    if n < 3:
        return {"N": n, "mean": np.nan, "wr": np.nan, "std": np.nan, "p": np.nan}
    mean = vals.mean()
    wr = (vals > 0).sum() / n * 100
    std = vals.std()
    _, p = stats.ttest_1samp(vals, 0)
    p = p / 2 if mean > 0 else 1 - p / 2
    return {"N": n, "mean": mean, "wr": wr, "std": std, "p": p}


def separation_test(on_vals, off_vals):
    """Two-sample t-test for separation between ON and OFF groups."""
    on = on_vals.dropna()
    off = off_vals.dropna()
    if len(on) < 3 or len(off) < 3:
        return np.nan
    _, p = stats.ttest_ind(on, off, equal_var=False)
    return p


# ── Report ────────────────────────────────────────────────────────────────────

def generate_report(df):
    lines = []
    lines.append("# S44 M5 Binary Triggers — TQS Replacement Analysis")
    lines.append("")
    lines.append(f"**Date:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Pre-filter:** 4H EMA gate = UP (EMA9 > EMA21 on completed 4H bar)")
    lines.append(f"**Total qualifying M5 bars:** {len(df):,}")
    lines.append(f"**Tickers:** {df['ticker'].nunique()}/25")
    lines.append("")

    trigger_cols = {
        "T1": "T1_ema9_reclaim",
        "T2": "T2_rsi_above_50",
        "T3": "T3_ce_long",
        "T4": "T4_higher_low",
        "T5": "T5_ema_trend",
    }
    trigger_names = {
        "T1": "EMA9 reclaim (close > EMA9)",
        "T2": "RSI > 50",
        "T3": "CE LONG state",
        "T4": "Higher low (5-bar)",
        "T5": "EMA trend (EMA9 > EMA21)",
    }

    # ── Section 1: Individual trigger results ──
    lines.append("## 1. Individual Binary Triggers")
    lines.append("")

    # Collect separation data for ranking
    separations = {}

    for tname, tcol in trigger_cols.items():
        lines.append(f"### {tname}: {trigger_names[tname]}")
        lines.append("")

        valid = df[df[tcol].notna()]
        on = valid[valid[tcol] == True]
        off = valid[valid[tcol] == False]

        lines.append(f"ON: {len(on):,} bars ({len(on)/len(valid)*100:.1f}%) | OFF: {len(off):,} bars ({len(off)/len(valid)*100:.1f}%)")
        lines.append("")
        lines.append("| Horizon | ON Mean% | ON WR% | OFF Mean% | OFF WR% | Sep% | Sep p-val |")
        lines.append("|---------|----------|--------|-----------|---------|------|-----------|")

        for h in FORWARD_BARS:
            col = f"fwd_{h}"
            m_on = group_metrics(on[col])
            m_off = group_metrics(off[col])
            sep = m_on["mean"] - m_off["mean"] if not (np.isnan(m_on["mean"]) or np.isnan(m_off["mean"])) else np.nan
            sep_p = separation_test(on[col], off[col])
            sig = "***" if sep_p < 0.001 else ("**" if sep_p < 0.01 else ("*" if sep_p < 0.05 else ""))

            lines.append(
                f"| {FORWARD_LABELS[h]} | {m_on['mean']:+.4f} | {m_on['wr']:.1f} | "
                f"{m_off['mean']:+.4f} | {m_off['wr']:.1f} | "
                f"{sep:+.4f} | {sep_p:.4f}{sig} |"
                if not np.isnan(sep) else
                f"| {FORWARD_LABELS[h]} | — | — | — | — | — | — |"
            )

            if h == 24:  # Track +2hr separation for ranking
                separations[tname] = {"sep": sep, "p": sep_p}

        lines.append("")

    # ── Section 2: Ranking ──
    lines.append("## 2. Trigger Ranking (by +2hr separation)")
    lines.append("")
    lines.append("| Rank | Trigger | Description | Sep% | p-val | Significant? |")
    lines.append("|------|---------|-------------|------|-------|--------------|")

    ranked = sorted(separations.items(), key=lambda x: abs(x[1]["sep"]) if not np.isnan(x[1]["sep"]) else 0, reverse=True)
    sig_triggers = []
    for rank, (tname, data) in enumerate(ranked, 1):
        is_sig = data["p"] < 0.05 if not np.isnan(data["p"]) else False
        sig_mark = "YES" if is_sig else "no"
        if is_sig:
            sig_triggers.append(tname)
        lines.append(
            f"| {rank} | {tname} | {trigger_names[tname]} | "
            f"{data['sep']:+.4f} | {data['p']:.4f} | {sig_mark} |"
            if not np.isnan(data["sep"]) else
            f"| {rank} | {tname} | {trigger_names[tname]} | — | — | no |"
        )
    lines.append("")

    # ── Section 3: Combination test ──
    lines.append("## 3. Combination Test (Top Significant Triggers)")
    lines.append("")

    if len(sig_triggers) >= 2:
        combo_triggers = sig_triggers[:3]  # Top 2-3
        lines.append(f"**Combined triggers:** {' + '.join(combo_triggers)}")
        lines.append("")

        combo_mask = pd.Series(True, index=df.index)
        for tname in combo_triggers:
            tcol = trigger_cols[tname]
            combo_mask = combo_mask & (df[tcol] == True)

        combo_on = df[combo_mask]
        combo_off = df[~combo_mask & df[trigger_cols[combo_triggers[0]]].notna()]

        lines.append(f"ALL ON: {len(combo_on):,} bars | Any OFF: {len(combo_off):,} bars")
        lines.append("")
        lines.append("| Horizon | ALL ON Mean% | ALL ON WR% | Any OFF Mean% | Any OFF WR% | Sep% | Sep p-val |")
        lines.append("|---------|-------------|------------|--------------|-------------|------|-----------|")

        for h in FORWARD_BARS:
            col = f"fwd_{h}"
            m_on = group_metrics(combo_on[col])
            m_off = group_metrics(combo_off[col])
            sep = m_on["mean"] - m_off["mean"] if not (np.isnan(m_on["mean"]) or np.isnan(m_off["mean"])) else np.nan
            sep_p = separation_test(combo_on[col], combo_off[col])
            sig = "***" if sep_p < 0.001 else ("**" if sep_p < 0.01 else ("*" if sep_p < 0.05 else ""))
            if not np.isnan(sep):
                lines.append(
                    f"| {FORWARD_LABELS[h]} | {m_on['mean']:+.4f} | {m_on['wr']:.1f} | "
                    f"{m_off['mean']:+.4f} | {m_off['wr']:.1f} | "
                    f"{sep:+.4f} | {sep_p:.4f}{sig} |"
                )
            else:
                lines.append(f"| {FORWARD_LABELS[h]} | — | — | — | — | — | — |")
        lines.append("")
    elif len(sig_triggers) == 1:
        lines.append(f"Only 1 significant trigger ({sig_triggers[0]}). No combination test needed.")
        lines.append("")
    else:
        lines.append("No triggers reached p < 0.05. No combination test possible.")
        lines.append("")

    # ── Section 4: TQS head-to-head ──
    lines.append("## 4. Head-to-Head: Binary Triggers vs TQS A/B/C")
    lines.append("")
    lines.append("TQS formula: `TQS_quant = 0.76 * RSI_phase + 0.24 * DMI_alignment`")
    lines.append("- RSI_phase = |RSI(14) - 50| / 50")
    lines.append("- DMI_alignment = min(ADX(14) / 50, 1.0)")
    lines.append("- Grades: A (top tercile), B (middle), C (bottom tercile)")
    lines.append("")

    lines.append("### TQS Grades")
    lines.append("")
    lines.append("| Grade | Horizon | N | Mean% | WR% | Std% | p-val |")
    lines.append("|-------|---------|---|-------|-----|------|-------|")

    tqs_valid = df[df["tqs"].notna()]
    for grade in ["A", "B", "C"]:
        sub = tqs_valid[tqs_valid["tqs_grade"] == grade]
        for h in FORWARD_BARS:
            m = group_metrics(sub[f"fwd_{h}"])
            sig = "***" if m["p"] < 0.001 else ("**" if m["p"] < 0.01 else ("*" if m["p"] < 0.05 else ""))
            if not np.isnan(m["mean"]):
                lines.append(
                    f"| {grade} | {FORWARD_LABELS[h]} | {m['N']:,} | "
                    f"{m['mean']:+.4f} | {m['wr']:.1f} | {m['std']:.4f} | {m['p']:.4f}{sig} |"
                )
            else:
                lines.append(f"| {grade} | {FORWARD_LABELS[h]} | {m['N']} | — | — | — | — |")
    lines.append("")

    # TQS separation (A vs C at +2hr)
    tqs_a = tqs_valid[tqs_valid["tqs_grade"] == "A"]["fwd_24"].dropna()
    tqs_c = tqs_valid[tqs_valid["tqs_grade"] == "C"]["fwd_24"].dropna()
    if len(tqs_a) > 2 and len(tqs_c) > 2:
        tqs_sep = tqs_a.mean() - tqs_c.mean()
        tqs_sep_p = separation_test(tqs_a, tqs_c)
        lines.append(f"**TQS A-vs-C separation at +2hr:** {tqs_sep:+.4f}% (p={tqs_sep_p:.4f})")
    else:
        tqs_sep = 0
        tqs_sep_p = 1
        lines.append("**TQS A-vs-C separation:** insufficient data")
    lines.append("")

    # Best binary trigger separation
    if sig_triggers:
        best_t = sig_triggers[0]
        best_sep = separations[best_t]["sep"]
        best_p = separations[best_t]["p"]
        lines.append(f"**Best binary trigger ({best_t}) separation at +2hr:** {best_sep:+.4f}% (p={best_p:.4f})")
    else:
        best_sep = 0
        lines.append("**Best binary trigger:** none significant")
    lines.append("")

    # ── Section 5: Verdict ──
    lines.append("## 5. Verdict")
    lines.append("")

    if sig_triggers:
        if len(sig_triggers) >= 2 and abs(best_sep) > abs(tqs_sep):
            combo_str = "+".join(sig_triggers[:3])
            lines.append(f"**Replace TQS with {combo_str}.**")
            lines.append("")
            lines.append(f"Binary triggers produce {abs(best_sep):.4f}% separation vs TQS {abs(tqs_sep):.4f}%.")
            lines.append("Simple binary gates are more interpretable and produce equal or better signal separation.")
        elif abs(best_sep) > abs(tqs_sep):
            lines.append(f"**Replace TQS with {sig_triggers[0]}.**")
            lines.append("")
            lines.append(f"Single trigger {sig_triggers[0]} ({abs(best_sep):.4f}%) outperforms TQS ({abs(tqs_sep):.4f}%).")
        else:
            lines.append("**TQS still wins marginally.**")
            lines.append("")
            lines.append(f"TQS separation ({abs(tqs_sep):.4f}%) exceeds best binary trigger ({abs(best_sep):.4f}%).")
    else:
        lines.append("**Neither TQS nor binary triggers produce meaningful M5-level separation under 4H EMA gate UP.**")
        lines.append("")
        lines.append("This confirms S44: M5 should only decide HOW you get in, not WHETHER.")
    lines.append("")

    # ── Section 6: Rule definition (if replacement) ──
    if sig_triggers:
        lines.append("## 6. Implementation Rule")
        lines.append("")
        lines.append("```python")
        lines.append("# Replace TQS with binary gate(s)")
        for t in sig_triggers[:3]:
            lines.append(f"# {t}: {trigger_names[t]}")
        lines.append("")
        lines.append("def m5_entry_gate(m5_bar, m5_ema9, m5_ema21, m5_rsi, m5_ce_long, m5_low_prev5):")
        lines.append("    \"\"\"Returns True if M5 binary gate passes (all significant triggers ON).\"\"\"")
        for t in sig_triggers[:3]:
            if t == "T1":
                lines.append("    if m5_bar.close <= m5_ema9: return False  # T1: EMA9 reclaim")
            elif t == "T2":
                lines.append("    if m5_rsi <= 50: return False  # T2: RSI above 50")
            elif t == "T3":
                lines.append("    if not m5_ce_long: return False  # T3: CE LONG")
            elif t == "T4":
                lines.append("    if m5_bar.low <= m5_low_prev5: return False  # T4: Higher low")
            elif t == "T5":
                lines.append("    if m5_ema9 <= m5_ema21: return False  # T5: EMA trend")
        lines.append("    return True")
        lines.append("```")
        lines.append("")

    # ── Integration note ──
    lines.append("## 7. Integration with Prompt 3 (4H RSI/ADX Bins)")
    lines.append("")
    lines.append("From Prompt 3: 4H RSI bins × VIX regime dominate forward returns.")
    lines.append("STRETCHED_DOWN + VIX>=25 = +0.73% at +2hr (p<0.0001).")
    lines.append("")
    lines.append("The M5 binary triggers operate WITHIN a given 4H context.")
    lines.append("If both layers show edge, a Multi-TF Intelligence Module should:")
    lines.append("1. **Outer gate:** 4H RSI bin + VIX regime (decides WHETHER to trade)")
    lines.append("2. **Inner gate:** M5 binary triggers (decides HOW to enter)")
    lines.append("")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    df = run_analysis()
    report = generate_report(df)

    output_path = RESULTS_DIR / "S44_Binary_Triggers_Results.md"
    output_path.write_text(report)
    print(f"\nResults saved to {output_path}")
    print("\n" + report)
