"""
S45 — Triple Confirmation on 4H: Detection + Forward Returns
=============================================================
Hypothesis: Multi-day trend entry when THREE indicators confirm
simultaneously on 4H within a 2-bar window:
  1. EMA9 crosses above EMA21
  2. RSI(14) crosses above 50
  3. +DI(14) crosses above -DI(14)

Tasks:
  A) Detection (bullish + bearish)
  B) Forward returns vs baseline (bullish only)
  C) ADX-bin split
"""

import os
import sys
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings('ignore', category=RuntimeWarning, message='invalid value encountered')
from scipy import stats
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'indicators_4h')
RESULTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'results')

HORIZONS = [1, 2, 3, 5, 10, 20]
ADX_BINS = [(0, 15, '<15'), (15, 20, '15-20'), (20, 30, '20-30'), (30, 999, '>30')]


# ── DI+/DI- Computation ──────────────────────────────────────────────

def compute_di(df, period=14):
    """Compute +DI and -DI from OHLC data using Wilder's smoothing."""
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values

    n = len(df)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)

    for i in range(1, n):
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]

        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0

        tr[i] = max(high[i] - low[i],
                     abs(high[i] - close[i - 1]),
                     abs(low[i] - close[i - 1]))

    # Wilder's smoothing
    smooth_plus_dm = np.zeros(n)
    smooth_minus_dm = np.zeros(n)
    smooth_tr = np.zeros(n)

    if n < period + 1:
        df['plus_di'] = np.nan
        df['minus_di'] = np.nan
        return df

    smooth_plus_dm[period] = np.sum(plus_dm[1:period + 1])
    smooth_minus_dm[period] = np.sum(minus_dm[1:period + 1])
    smooth_tr[period] = np.sum(tr[1:period + 1])

    for i in range(period + 1, n):
        smooth_plus_dm[i] = smooth_plus_dm[i - 1] - (smooth_plus_dm[i - 1] / period) + plus_dm[i]
        smooth_minus_dm[i] = smooth_minus_dm[i - 1] - (smooth_minus_dm[i - 1] / period) + minus_dm[i]
        smooth_tr[i] = smooth_tr[i - 1] - (smooth_tr[i - 1] / period) + tr[i]

    plus_di = np.where(smooth_tr > 0, 100 * smooth_plus_dm / smooth_tr, 0.0)
    minus_di = np.where(smooth_tr > 0, 100 * smooth_minus_dm / smooth_tr, 0.0)

    # Set initial period to NaN
    plus_di[:period] = np.nan
    minus_di[:period] = np.nan

    df['plus_di'] = plus_di
    df['minus_di'] = minus_di
    return df


# ── Data Loading ─────────────────────────────────────────────────────

def load_all_tickers():
    """Load all 4H indicator files and compute DI+/DI-."""
    frames = {}
    for fname in sorted(os.listdir(DATA_DIR)):
        if not fname.endswith('_4h_indicators.csv'):
            continue
        ticker = fname.replace('_4h_indicators.csv', '')
        df = pd.read_csv(os.path.join(DATA_DIR, fname), parse_dates=['timestamp'])
        df = df.sort_values('timestamp').reset_index(drop=True)
        df = compute_di(df, period=14)
        df['ticker'] = ticker
        frames[ticker] = df
    return frames


# ── Task A: Signal Detection ─────────────────────────────────────────

def detect_signals(frames):
    """Detect triple bullish/bearish confirmation within 2-bar window."""
    all_bull = []
    all_bear = []

    for ticker, df in frames.items():
        # Need valid EMA, RSI, DI values
        mask = df['ema_9'].notna() & df['ema_21'].notna() & \
               df['rsi_14'].notna() & df['plus_di'].notna() & df['minus_di'].notna()
        valid = df[mask].reset_index(drop=True)

        if len(valid) < 3:
            continue

        # State columns (current bar)
        ema_up = (valid['ema_9'] >= valid['ema_21']).values
        rsi_up = (valid['rsi_14'] >= 50).values
        di_up = (valid['plus_di'] >= valid['minus_di']).values

        for i in range(1, len(valid)):
            # ── BULLISH: cross UP within 2-bar window (bar i-1 to bar i)
            # At least one condition was OFF at bar i-1, now all ON at bar i
            # AND each condition was OFF at bar i-1 OR bar i-2 (if exists)
            ema_cross_bull = (not ema_up[i - 1]) and ema_up[i]
            rsi_cross_bull = (not rsi_up[i - 1]) and rsi_up[i]
            di_cross_bull = (not di_up[i - 1]) and di_up[i]

            # 2-bar window: each crosses within bar i or bar i-1
            # All three must be ON at bar i, and each must have been OFF
            # at bar i-1 or bar i-2
            if ema_up[i] and rsi_up[i] and di_up[i]:
                # Check each crossed in 2-bar window
                ema_ok = ema_cross_bull
                rsi_ok = rsi_cross_bull
                di_ok = di_cross_bull

                if i >= 2:
                    # Also allow cross at bar i-1 (was off at i-2, on at i-1, still on at i)
                    if not ema_ok:
                        ema_ok = (not ema_up[i - 2]) and ema_up[i - 1] and ema_up[i]
                    if not rsi_ok:
                        rsi_ok = (not rsi_up[i - 2]) and rsi_up[i - 1] and rsi_up[i]
                    if not di_ok:
                        di_ok = (not di_up[i - 2]) and di_up[i - 1] and di_up[i]

                if ema_ok and rsi_ok and di_ok:
                    row = valid.iloc[i]
                    all_bull.append({
                        'ticker': ticker,
                        'timestamp': row['timestamp'],
                        'close': row['close'],
                        'adx': row['adx_14'],
                        'rsi': row['rsi_14'],
                        'plus_di': row['plus_di'],
                        'minus_di': row['minus_di'],
                        'ema_9': row['ema_9'],
                        'ema_21': row['ema_21'],
                        'bar_idx': i,
                    })

            # ── BEARISH: cross DOWN within 2-bar window
            ema_dn = (not ema_up[i])
            rsi_dn = (not rsi_up[i])
            di_dn = (not di_up[i])

            if ema_dn and rsi_dn and di_dn:
                ema_cross_bear = ema_up[i - 1] and (not ema_up[i])
                rsi_cross_bear = rsi_up[i - 1] and (not rsi_up[i])
                di_cross_bear = di_up[i - 1] and (not di_up[i])

                ema_ok = ema_cross_bear
                rsi_ok = rsi_cross_bear
                di_ok = di_cross_bear

                if i >= 2:
                    if not ema_ok:
                        ema_ok = ema_up[i - 2] and (not ema_up[i - 1]) and (not ema_up[i])
                    if not rsi_ok:
                        rsi_ok = rsi_up[i - 2] and (not rsi_up[i - 1]) and (not rsi_up[i])
                    if not di_ok:
                        di_ok = di_up[i - 2] and (not di_up[i - 1]) and (not di_up[i])

                if ema_ok and rsi_ok and di_ok:
                    row = valid.iloc[i]
                    all_bear.append({
                        'ticker': ticker,
                        'timestamp': row['timestamp'],
                        'close': row['close'],
                        'adx': row['adx_14'],
                        'rsi': row['rsi_14'],
                        'bar_idx': i,
                    })

    return pd.DataFrame(all_bull), pd.DataFrame(all_bear)


# ── Task B: Forward Returns ──────────────────────────────────────────

def compute_forward_returns(signals_df, frames, horizons=HORIZONS):
    """Compute forward returns for each signal."""
    results = {h: [] for h in horizons}

    for _, sig in signals_df.iterrows():
        ticker = sig['ticker']
        df = frames[ticker]
        # Find the bar in the original dataframe
        idx = df.index[df['timestamp'] == sig['timestamp']]
        if len(idx) == 0:
            continue
        idx = idx[0]
        entry_price = sig['close']

        for h in horizons:
            future_idx = idx + h
            if future_idx < len(df):
                future_close = df.loc[future_idx, 'close']
                ret = (future_close - entry_price) / entry_price * 100
                results[h].append(ret)
            else:
                results[h].append(np.nan)

    for h in horizons:
        signals_df[f'fwd_{h}'] = results[h]

    return signals_df


def compute_baseline_returns(frames, horizons=HORIZONS):
    """Baseline: bars where EMA gate is already UP (not a fresh cross)."""
    baseline = {h: [] for h in horizons}

    for ticker, df in frames.items():
        df_reset = df.reset_index(drop=True)
        ema_9 = df_reset['ema_9'].values
        ema_21 = df_reset['ema_21'].values
        close = df_reset['close'].values
        n = len(df_reset)

        for i in range(2, n):
            if np.isnan(ema_9[i]) or np.isnan(ema_21[i]) or np.isnan(ema_9[i-1]) or np.isnan(ema_21[i-1]):
                continue
            # EMA gate already UP (not a fresh cross) — was UP at i-1 too
            if ema_9[i] >= ema_21[i] and ema_9[i-1] >= ema_21[i-1]:
                entry_price = close[i]
                for h in horizons:
                    future_idx = i + h
                    if future_idx < n:
                        ret = (close[future_idx] - entry_price) / entry_price * 100
                        baseline[h].append(ret)

    return baseline


def calc_stats(returns):
    """Calculate N, Mean%, WR%, PF from a list of returns."""
    arr = np.array([r for r in returns if not np.isnan(r)])
    if len(arr) == 0:
        return {'N': 0, 'Mean': np.nan, 'WR': np.nan, 'PF': np.nan}
    n = len(arr)
    mean = np.mean(arr)
    wr = np.sum(arr > 0) / n * 100
    gains = arr[arr > 0]
    losses = arr[arr < 0]
    pf = np.sum(gains) / abs(np.sum(losses)) if len(losses) > 0 and np.sum(losses) != 0 else np.inf
    return {'N': n, 'Mean': mean, 'WR': wr, 'PF': pf}


# ── Reporting ─────────────────────────────────────────────────────────

def generate_report(bull_df, bear_df, frames, baseline):
    """Generate the full markdown report."""
    lines = []
    lines.append("# S45 Triple Confirmation on 4H — Detection + Forward Returns")
    lines.append("")
    lines.append(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Tickers:** {len(frames)}/25")
    lines.append(f"**Hypothesis:** Multi-day trend entry when EMA cross + RSI>50 cross + DI cross")
    lines.append(f"  fire within a 2-bar window on 4H timeframe.")
    lines.append("")

    # ── Task A: Detection ──
    lines.append("---")
    lines.append("## Task A: Detection")
    lines.append("")
    lines.append(f"**Total bullish signals:** {len(bull_df)}")
    lines.append(f"**Total bearish signals:** {len(bear_df)}")
    lines.append("")

    # Signals per ticker
    lines.append("### Signals per Ticker")
    lines.append("")
    lines.append("| Ticker | Bullish | Bearish | Total |")
    lines.append("|--------|---------|---------|-------|")
    all_tickers = sorted(frames.keys())
    for t in all_tickers:
        b = len(bull_df[bull_df['ticker'] == t]) if len(bull_df) > 0 else 0
        s = len(bear_df[bear_df['ticker'] == t]) if len(bear_df) > 0 else 0
        lines.append(f"| {t} | {b} | {s} | {b + s} |")
    lines.append("")

    # Signals per month
    lines.append("### Signals per Month")
    lines.append("")
    lines.append("| Month | Bullish | Bearish |")
    lines.append("|-------|---------|---------|")
    if len(bull_df) > 0:
        bull_df['month'] = bull_df['timestamp'].dt.to_period('M')
    if len(bear_df) > 0:
        bear_df['month'] = bear_df['timestamp'].dt.to_period('M')

    all_months = set()
    if len(bull_df) > 0:
        all_months.update(bull_df['month'].unique())
    if len(bear_df) > 0:
        all_months.update(bear_df['month'].unique())

    for m in sorted(all_months):
        b = len(bull_df[bull_df['month'] == m]) if len(bull_df) > 0 else 0
        s = len(bear_df[bear_df['month'] == m]) if len(bear_df) > 0 else 0
        lines.append(f"| {m} | {b} | {s} |")
    lines.append("")

    # Average ADX at trigger
    if len(bull_df) > 0:
        avg_adx_bull = bull_df['adx'].mean()
        lines.append(f"**Average ADX at bullish trigger:** {avg_adx_bull:.2f}")
    if len(bear_df) > 0:
        avg_adx_bear = bear_df['adx'].mean()
        lines.append(f"**Average ADX at bearish trigger:** {avg_adx_bear:.2f}")
    lines.append("")

    # ── Task B: Forward Returns ──
    lines.append("---")
    lines.append("## Task B: Forward Returns (Bullish Only)")
    lines.append("")

    if len(bull_df) == 0:
        lines.append("*No bullish signals detected.*")
    else:
        lines.append("| Horizon | N | Mean% | WR% | PF | Base Mean% | Base WR% | Sep% | p-value |")
        lines.append("|---------|---|-------|-----|-----|------------|----------|------|---------|")

        best_h = None
        best_sep = -999

        for h in HORIZONS:
            col = f'fwd_{h}'
            sig_rets = bull_df[col].dropna().values
            base_rets = np.array(baseline[h])

            sig_stats = calc_stats(sig_rets)
            base_stats = calc_stats(base_rets)

            # t-test
            if len(sig_rets) >= 2 and len(base_rets) >= 2:
                t_stat, p_val = stats.ttest_ind(sig_rets, base_rets, equal_var=False)
            else:
                p_val = np.nan

            sep = sig_stats['Mean'] - base_stats['Mean'] if not np.isnan(sig_stats['Mean']) else np.nan

            stars = ''
            if not np.isnan(p_val):
                if p_val < 0.001:
                    stars = '***'
                elif p_val < 0.01:
                    stars = '**'
                elif p_val < 0.05:
                    stars = '*'

            pf_str = f"{sig_stats['PF']:.2f}" if sig_stats['PF'] != np.inf else 'inf'
            p_str = f"{p_val:.4f}{stars}" if not np.isnan(p_val) else 'N/A'

            lines.append(f"| +{h} bars | {sig_stats['N']} | "
                         f"{sig_stats['Mean']:+.4f} | {sig_stats['WR']:.1f} | {pf_str} | "
                         f"{base_stats['Mean']:+.4f} | {base_stats['WR']:.1f} | "
                         f"{sep:+.4f} | {p_str} |")

            if not np.isnan(sep) and sep > best_sep:
                best_sep = sep
                best_h = h

        lines.append("")
        if best_h:
            lines.append(f"**Best horizon:** +{best_h} bars (separation = {best_sep:+.4f}%)")
        lines.append("")

    # ── Task C: ADX Split ──
    lines.append("---")
    lines.append("## Task C: ADX Bin Split")
    lines.append("")

    if len(bull_df) == 0:
        lines.append("*No bullish signals detected.*")
    else:
        lines.append("### Forward Returns by ADX Bin (+5 and +10 bars)")
        lines.append("")
        lines.append("| ADX Bin | N | +5 Mean% | +5 WR% | +5 PF | +10 Mean% | +10 WR% | +10 PF |")
        lines.append("|---------|---|----------|--------|-------|-----------|---------|--------|")

        for lo, hi, label in ADX_BINS:
            mask = (bull_df['adx'] >= lo) & (bull_df['adx'] < hi)
            subset = bull_df[mask]
            n = len(subset)

            if n == 0:
                lines.append(f"| {label} | 0 | — | — | — | — | — | — |")
                continue

            s5 = calc_stats(subset['fwd_5'].dropna().values)
            s10 = calc_stats(subset['fwd_10'].dropna().values)

            pf5 = f"{s5['PF']:.2f}" if s5['PF'] != np.inf else 'inf'
            pf10 = f"{s10['PF']:.2f}" if s10['PF'] != np.inf else 'inf'

            lines.append(f"| {label} | {n} | "
                         f"{s5['Mean']:+.4f} | {s5['WR']:.1f} | {pf5} | "
                         f"{s10['Mean']:+.4f} | {s10['WR']:.1f} | {pf10} |")

        lines.append("")

    # ── Key Answer ──
    lines.append("---")
    lines.append("## Key Answer")
    lines.append("")

    if len(bull_df) > 0:
        # Determine significance
        sig_results = {}
        for h in HORIZONS:
            sig_rets = bull_df[f'fwd_{h}'].dropna().values
            base_rets = np.array(baseline[h])
            if len(sig_rets) >= 2 and len(base_rets) >= 2:
                _, p = stats.ttest_ind(sig_rets, base_rets, equal_var=False)
                sig_results[h] = p
            else:
                sig_results[h] = np.nan

        any_sig = any(p < 0.05 for p in sig_results.values() if not np.isnan(p))
        n_sig = len(bull_df)
        mean_5 = bull_df['fwd_5'].dropna().mean()
        mean_10 = bull_df['fwd_10'].dropna().mean()

        lines.append(f"- **N = {n_sig}** bullish triple confirmation signals detected")
        lines.append(f"- +5 bar mean return: **{mean_5:+.4f}%**")
        lines.append(f"- +10 bar mean return: **{mean_10:+.4f}%**")

        if any_sig:
            sig_horizons = [f"+{h}" for h, p in sig_results.items() if not np.isnan(p) and p < 0.05]
            lines.append(f"- **Significant** vs baseline at horizons: {', '.join(sig_horizons)}")
            lines.append(f"- **VERDICT: YES** — triple confirmation produces statistically significant")
            lines.append(f"  forward returns on multi-day hold at certain horizons.")
        else:
            lines.append(f"- **No significant** separation from baseline at any horizon (p < 0.05)")
            lines.append(f"- **VERDICT: NO** — triple confirmation does not produce significant")
            lines.append(f"  forward returns vs the EMA-gate-UP baseline on multi-day hold.")
    else:
        lines.append("- No bullish signals detected — cannot evaluate hypothesis.")

    lines.append("")

    # ── Signal details (top 10) ──
    if len(bull_df) > 0:
        lines.append("---")
        lines.append("## Appendix: Sample Bullish Signals (first 15)")
        lines.append("")
        lines.append("| Ticker | Timestamp | Close | ADX | RSI | +DI | -DI | +5 ret% | +10 ret% |")
        lines.append("|--------|-----------|-------|-----|-----|-----|-----|---------|----------|")
        for _, row in bull_df.head(15).iterrows():
            fwd5 = f"{row['fwd_5']:+.2f}" if not np.isnan(row['fwd_5']) else '—'
            fwd10 = f"{row['fwd_10']:+.2f}" if not np.isnan(row['fwd_10']) else '—'
            lines.append(f"| {row['ticker']} | {row['timestamp']} | {row['close']:.2f} | "
                         f"{row['adx']:.1f} | {row['rsi']:.1f} | {row['plus_di']:.1f} | "
                         f"{row['minus_di']:.1f} | {fwd5} | {fwd10} |")
        lines.append("")

    return '\n'.join(lines)


# ── Main ──────────────────────────────────────────────────────────────

def main():
    print("Loading 4H data for 25 tickers...")
    frames = load_all_tickers()
    print(f"  Loaded {len(frames)} tickers")

    print("Detecting triple confirmation signals...")
    bull_df, bear_df = detect_signals(frames)
    print(f"  Bullish: {len(bull_df)}  |  Bearish: {len(bear_df)}")

    if len(bull_df) > 0:
        print("Computing forward returns (bullish signals)...")
        bull_df = compute_forward_returns(bull_df, frames)

        print("Computing baseline returns (EMA gate UP, no fresh cross)...")
        baseline = compute_baseline_returns(frames)
        print(f"  Baseline bars: {len(baseline[1])}")
    else:
        baseline = {h: [] for h in HORIZONS}

    print("Generating report...")
    report = generate_report(bull_df, bear_df, frames, baseline)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    out_path = os.path.join(RESULTS_DIR, 'S45_Triple_Confirmation_Results.md')
    with open(out_path, 'w') as f:
        f.write(report)
    print(f"\nReport saved to: {out_path}")
    print("\n" + report)


if __name__ == '__main__':
    main()
