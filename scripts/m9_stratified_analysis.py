#!/usr/bin/env python3
"""M9 Stratified Analysis — 5 Pre-Registered Hypotheses (Limited Variant C).

Strict methodology:
  Train = 2021-2024  |  Test = 2025 OOS
  Acceptance: PF >= 1.5, N >= 30, WR >= 40 % in BOTH periods.
  Exactly 5 hypotheses — no additions.

Usage: python scripts/m9_stratified_analysis.py
"""
import sys
import os

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_utils_extended import (
    load_extended_data,
    build_4h_extended,
    compute_indicators,
    apply_ema21_warmup_mask,
)

_BASE   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EV_DIR = os.path.join(_BASE, 'results', 'extended_validation')
RTH_CSV = os.path.join(_EV_DIR, 'm9_rth_trades.csv')
OUT_MD  = os.path.join(_EV_DIR, 'm9_stratified_report.md')

TRAIN_YEARS = {2021, 2022, 2023, 2024}
TEST_YEAR   = 2025
MIN_PF      = 1.5
MIN_N       = 30
MIN_WR      = 40.0

# ── Statistics helpers ─────────────────────────────────────────────────────────

def stats(df: pd.DataFrame) -> dict:
    """N, PF, WR%, Mean% for an executed-trade slice."""
    n = len(df)
    if n == 0:
        return {'N': 0, 'PF': 0.0, 'WR': 0.0, 'Mean': 0.0}
    rets     = df['return_pct'].values.astype(float)
    wins     = rets[rets > 0]
    loss_sum = abs(rets[rets <= 0].sum())
    pf = float(wins.sum() / loss_sum) if loss_sum > 0 else float('inf')
    return {
        'N':    n,
        'PF':   round(pf, 2),
        'WR':   round(float((rets > 0).mean() * 100), 1),
        'Mean': round(float(rets.mean()), 4),
    }


def is_robust(s_tr: dict, s_te: dict) -> bool:
    """True iff both periods pass PF/N/WR acceptance criteria."""
    return (s_tr['N'] >= MIN_N  and s_te['N'] >= MIN_N and
            s_tr['PF'] >= MIN_PF and s_te['PF'] >= MIN_PF and
            s_tr['WR'] >= MIN_WR and s_te['WR'] >= MIN_WR)


# Shared markdown table header + separator for stratum tables
_TH = [
    '| Stratum | Tr N | Tr PF | Tr WR% | Tr Mean% '
    '| Te N | Te PF | Te WR% | Te Mean% | ROBUST |',
    '|---------|------|-------|--------|----------'
    '|------|-------|--------|----------|--------|',
]


def _strat_rows(df: pd.DataFrame, col: str, labels: list, robust_set: set) -> list:
    """Markdown table rows for each stratum (train + test side-by-side)."""
    rows = []
    for lbl in labels:
        sub  = df[df[col] == lbl]
        s_tr = stats(sub[sub['_year'].isin(TRAIN_YEARS)])
        s_te = stats(sub[sub['_year'] == TEST_YEAR])
        rob  = '**YES**' if lbl in robust_set else 'no'
        rows.append(
            f'| {lbl} '
            f'| {s_tr["N"]} | {s_tr["PF"]:.2f} | {s_tr["WR"]:.1f}% | {s_tr["Mean"]:+.3f}% '
            f'| {s_te["N"]} | {s_te["PF"]:.2f} | {s_te["WR"]:.1f}% | {s_te["Mean"]:+.3f}% '
            f'| {rob} |'
        )
    return rows


def _find_robust(df: pd.DataFrame, col: str, labels: list) -> set:
    """Return labels whose both-period stats pass acceptance criteria."""
    robust = set()
    for lbl in labels:
        sub = df[df[col] == lbl]
        if is_robust(stats(sub[sub['_year'].isin(TRAIN_YEARS)]),
                     stats(sub[sub['_year'] == TEST_YEAR])):
            robust.add(lbl)
    return robust


# ── Bar-level enrichment (re-loads 4H bars to get ATR / EMA indicators) ───────

def enrich_signal_bar(df: pd.DataFrame, mode: str = 'rth') -> pd.DataFrame:
    """Join atr14, ema9, ema21 at the signal bar onto each trade row.

    Loads 4H bars for each unique ticker and merges by (entry_date, entry_bar).
    Rows with no matching bar (ticker missing or end-of-data edge) get NaN.
    """
    new_cols = ['atr14_at_signal', 'ema9_at_signal', 'ema21_at_signal']
    pieces: list = []

    for ticker in df['ticker'].unique():
        subset = df[df['ticker'] == ticker].copy()
        try:
            df_m5 = load_extended_data(ticker)
            bars = build_4h_extended(df_m5, mode=mode)
            bars = compute_indicators(bars, warmup_rows=0 if mode == 'rth' else 25)
            if mode == 'rth':
                bars['ema21'] = apply_ema21_warmup_mask(bars)

            ref = (
                bars[['date', 'bar_label', 'atr14', 'ema9', 'ema21']]
                .copy()
                .assign(entry_date=bars['date'].astype(str))
                .rename(columns={'bar_label': 'entry_bar',
                                 'atr14': 'atr14_at_signal',
                                 'ema9':  'ema9_at_signal',
                                 'ema21': 'ema21_at_signal'})
                .drop(columns='date')
                .drop_duplicates(subset=['entry_date', 'entry_bar'])
            )
            subset = subset.merge(ref, on=['entry_date', 'entry_bar'], how='left')
        except FileNotFoundError:
            for c in new_cols:
                subset[c] = np.nan
        pieces.append(subset)

    if not pieces:
        for c in new_cols:
            df[c] = np.nan
        return df
    out = pd.concat(pieces, ignore_index=True)
    for c in new_cols:
        if c not in out.columns:
            out[c] = np.nan
    return out


# ── Quartile helper (train-boundary only) ─────────────────────────────────────

def _quartile_labels(df: pd.DataFrame, metric_col: str) -> pd.Series:
    """Label each row Q1–Q4 using quartile boundaries from TRAIN period only."""
    tr_vals = df.loc[df['_year'].isin(TRAIN_YEARS), metric_col].dropna()
    if len(tr_vals) < 20:
        return pd.Series(np.nan, index=df.index)
    q = tr_vals.quantile([0.25, 0.5, 0.75])
    q25, q50, q75 = q[0.25], q[0.5], q[0.75]

    def _label(v):
        if pd.isna(v):   return np.nan
        if v <= q25:     return 'Q1'
        elif v <= q50:   return 'Q2'
        elif v <= q75:   return 'Q3'
        else:            return 'Q4'

    return df[metric_col].map(_label)


# ── Hypotheses ─────────────────────────────────────────────────────────────────

def h1_pullback_depth_atr(df: pd.DataFrame, report: list) -> list:
    """H1: pullback depth (price) / ATR at signal → Q1-Q4."""
    report += ['\n## H1: Pullback Depth in ATR Units\n',
               '> `pullback_depth_atr = (entry_price − pullback_low) / atr14_at_signal`  ',
               '> `entry_price` used as proxy for `pre_pullback_close` (not in CSV).\n']

    df = df.copy()
    df['_metric'] = (df['entry_price'] - df['pullback_low']) / df['atr14_at_signal']
    df = df.dropna(subset=['_metric'])
    if df['_year'].isin(TRAIN_YEARS).sum() < 20:
        report.append('_Insufficient train data after ATR enrichment — skipped._\n')
        return []

    df['_strat'] = _quartile_labels(df, '_metric')
    df = df.dropna(subset=['_strat'])
    labels = ['Q1', 'Q2', 'Q3', 'Q4']
    robust_set = _find_robust(df, '_strat', labels)

    report += _TH + _strat_rows(df, '_strat', labels, robust_set) + ['']
    report.append('_Hypothesis: Q4 (deeper pullbacks) outperform Q1 (shallow)._\n')
    findings = [f'H1/{g}' for g in sorted(robust_set)]
    if findings:
        report.append(f'**Robust**: {", ".join(findings)}\n')
    return findings


def h2_ema_separation(df: pd.DataFrame, report: list) -> list:
    """H2: EMA9-EMA21 separation % at signal → Q1-Q4."""
    report += ['\n## H2: EMA9–EMA21 Separation at Signal\n',
               '> `ema_separation_pct = (ema9 − ema21) / ema21 × 100` at entry bar\n']

    df = df.copy()
    df['_metric'] = ((df['ema9_at_signal'] - df['ema21_at_signal'])
                     / df['ema21_at_signal'] * 100)
    df = df.dropna(subset=['_metric'])
    if df['_year'].isin(TRAIN_YEARS).sum() < 20:
        report.append('_Insufficient train data after EMA enrichment — skipped._\n')
        return []

    df['_strat'] = _quartile_labels(df, '_metric')
    df = df.dropna(subset=['_strat'])
    labels = ['Q1', 'Q2', 'Q3', 'Q4']
    robust_set = _find_robust(df, '_strat', labels)

    report += _TH + _strat_rows(df, '_strat', labels, robust_set) + ['']
    report.append('_Hypothesis: Q4 (strongest EMA separation) = best continuation._\n')
    findings = [f'H2/{g}' for g in sorted(robust_set)]
    if findings:
        report.append(f'**Robust**: {", ".join(findings)}\n')
    return findings


def h3_streak_length(df: pd.DataFrame, report: list) -> list:
    """H3: streak_len 1 vs 2."""
    report += ['\n## H3: Pullback Streak Length (1-bar vs 2-bar)\n',
               '> Hypothesis: 2-bar pullbacks (deeper consolidation) work better.\n']

    df = df.copy()
    df['_strat'] = df['streak_len'].map({1: '1-bar', 2: '2-bar'})
    labels = ['1-bar', '2-bar']
    robust_set = _find_robust(df, '_strat', labels)

    report += _TH + _strat_rows(df, '_strat', labels, robust_set) + ['']
    findings = [f'H3/{g}' for g in sorted(robust_set)]
    if findings:
        report.append(f'**Robust**: {", ".join(findings)}\n')
    return findings


def h4_vix_bucket(df: pd.DataFrame, report: list) -> list:
    """H4: VIX at entry — 12-15 vs 15-20 buckets (plus residual)."""
    report += ['\n## H4: VIX Bucket at Entry\n',
               '> Hypothesis: VIX 12-15 (calmer trend) outperforms VIX 15-20.\n']

    def _bucket(v):
        if   v < 12: return 'VIX <12'
        elif v < 15: return 'VIX 12–15'
        elif v < 20: return 'VIX 15–20'
        else:        return 'VIX ≥20'

    df = df.copy()
    df['_strat'] = df['vix_at_entry'].map(_bucket)
    labels = [b for b in ['VIX <12', 'VIX 12–15', 'VIX 15–20', 'VIX ≥20']
              if (df['_strat'] == b).any()]
    robust_set = _find_robust(df, '_strat', labels)

    report += _TH + _strat_rows(df, '_strat', labels, robust_set) + ['']
    findings = [f'H4/{g}' for g in sorted(robust_set)]
    if findings:
        report.append(f'**Robust**: {", ".join(findings)}\n')
    return findings


def h5_per_ticker(df: pd.DataFrame, report: list) -> list:
    """H5: identify good tickers in train (PF > 1.5, N >= 15); verify in test."""
    report += ['\n## H5: Per-Ticker Stratification\n',
               '> "Good ticker" = PF > 1.5 AND N ≥ 15 in train period (2021–2024).\n']

    df_tr = df[df['_year'].isin(TRAIN_YEARS)]
    df_te = df[df['_year'] == TEST_YEAR]

    # Per-ticker train stats table
    report += ['### Train Period — All Tickers\n',
               '| Ticker | N | PF | WR% | Mean% | Good |',
               '|--------|---|----|----|-------|------|']
    good_tickers = []
    for tk in sorted(df_tr['ticker'].unique()):
        s = stats(df_tr[df_tr['ticker'] == tk])
        good = s['PF'] > 1.5 and s['N'] >= 15
        if good:
            good_tickers.append(tk)
        mark = '✓' if good else ''
        report.append(
            f'| {tk} | {s["N"]} | {s["PF"]:.2f} | {s["WR"]:.1f}% '
            f'| {s["Mean"]:+.3f}% | {mark} |'
        )
    report.append('')

    if not good_tickers:
        report.append('_No tickers pass train threshold — H5 inconclusive._\n')
        return []

    report.append(f'**Good tickers ({len(good_tickers)})**: {", ".join(good_tickers)}\n')

    # Good-ticker aggregate: train vs test
    s_good_tr = stats(df_tr[df_tr['ticker'].isin(good_tickers)])
    s_good_te = stats(df_te[df_te['ticker'].isin(good_tickers)])
    s_rest_te = stats(df_te[~df_te['ticker'].isin(good_tickers)])

    report += ['### Good-Ticker Aggregate: Train vs Test\n',
               '| Period | N | PF | WR% | Mean% |',
               '|--------|---|----|----|-------|',
               f'| Train 2021–2024 | {s_good_tr["N"]} | {s_good_tr["PF"]:.2f} '
               f'| {s_good_tr["WR"]:.1f}% | {s_good_tr["Mean"]:+.3f}% |',
               f'| Test  2025      | {s_good_te["N"]} | {s_good_te["PF"]:.2f} '
               f'| {s_good_te["WR"]:.1f}% | {s_good_te["Mean"]:+.3f}% |',
               f'| Non-good (test) | {s_rest_te["N"]} | {s_rest_te["PF"]:.2f} '
               f'| {s_rest_te["WR"]:.1f}% | {s_rest_te["Mean"]:+.3f}% |',
               '']

    if is_robust(s_good_tr, s_good_te):
        tks = ', '.join(good_tickers)
        report.append(f'**Robust**: H5 good-ticker subset — {tks}\n')
        return [f'H5/good_tickers({tks})']
    return []


# ── Stdout print helpers ───────────────────────────────────────────────────────

def _print_strat(df: pd.DataFrame, col: str, labels: list) -> None:
    """Print stratum stats table to stdout."""
    w = [22, 6, 6, 7, 9, 6, 6, 7, 9, 8]
    hdr = (f'  {"Stratum":<{w[0]}} {"Tr N":>{w[1]}} {"Tr PF":>{w[2]}} '
           f'{"Tr WR%":>{w[3]}} {"Tr Mean%":>{w[4]}} '
           f'{"Te N":>{w[5]}} {"Te PF":>{w[6]}} {"Te WR%":>{w[7]}} '
           f'{"Te Mean%":>{w[8]}} {"ROBUST":>{w[9]}}')
    print(hdr)
    print('  ' + '-' * (sum(w) + len(w) - 1))
    for lbl in labels:
        sub  = df[df[col] == lbl]
        s_tr = stats(sub[sub['_year'].isin(TRAIN_YEARS)])
        s_te = stats(sub[sub['_year'] == TEST_YEAR])
        rob  = 'YES' if is_robust(s_tr, s_te) else ''
        print(
            f'  {str(lbl):<{w[0]}} {s_tr["N"]:>{w[1]}} {s_tr["PF"]:>{w[2]}.2f} '
            f'{s_tr["WR"]:>{w[3]}.1f}% {s_tr["Mean"]:>{w[4]}+.3f}% '
            f'{s_te["N"]:>{w[5]}} {s_te["PF"]:>{w[6]}.2f} '
            f'{s_te["WR"]:>{w[7]}.1f}% {s_te["Mean"]:>{w[8]}+.3f}% '
            f'{rob:>{w[9]}}'
        )


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('=' * 65)
    print('M9 STRATIFIED ANALYSIS — 5 PRE-REGISTERED HYPOTHESES')
    print(f'Train: 2021-2024  |  Test: {TEST_YEAR}  |  '
          f'Accept: PF≥{MIN_PF}, N≥{MIN_N}, WR≥{MIN_WR}%')
    print('=' * 65)

    # Load and filter to executed trades
    print(f'\nLoading {RTH_CSV}...')
    df = pd.read_csv(RTH_CSV)
    df = df[df['return_pct'].notna()].copy()
    df['_year'] = pd.to_datetime(df['entry_date']).dt.year
    df_tr_raw = df[df['_year'].isin(TRAIN_YEARS)]
    df_te_raw = df[df['_year'] == TEST_YEAR]
    print(f'  {len(df)} executed trades  '
          f'(train={len(df_tr_raw)}, test={len(df_te_raw)})')

    # Overall baseline (no stratification)
    s_all_tr = stats(df_tr_raw)
    s_all_te = stats(df_te_raw)
    print(f'\n  Baseline ALL  Train: N={s_all_tr["N"]} PF={s_all_tr["PF"]:.2f} '
          f'WR={s_all_tr["WR"]:.1f}%')
    print(f'  Baseline ALL  Test : N={s_all_te["N"]} PF={s_all_te["PF"]:.2f} '
          f'WR={s_all_te["WR"]:.1f}%')

    # Enrich with bar indicators for H1 and H2
    print('\nEnriching with signal-bar indicators (ATR, EMA9, EMA21)...')
    df = enrich_signal_bar(df, mode='rth')
    print('  Done.')

    report: list = [
        '# M9 Stratified Analysis — Pre-Registered Hypotheses (Limited Variant C)',
        '',
        f'**Source**: `m9_rth_trades.csv` — RTH mode  '
        f'(N={len(df)} executed trades)',
        f'**Train**: 2021–2024 (N={len(df[df["_year"].isin(TRAIN_YEARS)])})  '
        f'| **Test**: 2025 OOS (N={len(df[df["_year"]==TEST_YEAR])})',
        f'**Acceptance**: PF ≥ {MIN_PF}, N ≥ {MIN_N}, WR ≥ {MIN_WR}% in BOTH periods',
        '',
        '## Baseline (No Stratification)',
        '',
        '| Period | N | PF | WR% | Mean% |',
        '|--------|---|----|----|-------|',
        f'| Train 2021–2024 | {s_all_tr["N"]} | {s_all_tr["PF"]:.2f} '
        f'| {s_all_tr["WR"]:.1f}% | {s_all_tr["Mean"]:+.3f}% |',
        f'| Test  2025      | {s_all_te["N"]} | {s_all_te["PF"]:.2f} '
        f'| {s_all_te["WR"]:.1f}% | {s_all_te["Mean"]:+.3f}% |',
        '',
    ]

    all_robust: list = []
    hypotheses = [
        ('H1', h1_pullback_depth_atr),
        ('H2', h2_ema_separation),
        ('H3', h3_streak_length),
        ('H4', h4_vix_bucket),
        ('H5', h5_per_ticker),
    ]
    for tag, fn in hypotheses:
        print(f'\n{"=" * 65}\n{tag}: {fn.__doc__.splitlines()[0].strip()}')
        findings = fn(df, report)
        all_robust.extend(findings)
        if findings:
            print(f'  ROBUST: {findings}')
        else:
            print('  → no stratum passed acceptance criteria')

    # ── Summary ───────────────────────────────────────────────────────────────
    report += [
        '\n---\n',
        '## Summary\n',
        f'**Acceptance criteria**: PF ≥ {MIN_PF}, N ≥ {MIN_N}, '
        f'WR ≥ {MIN_WR}% in BOTH train AND test.\n',
    ]
    print('\n' + '=' * 65)
    if not all_robust:
        verdict = '**M9 NO SALVAGEABLE EDGE — recommend SHELVE**'
        report.append(verdict)
        print(f'\n{verdict}')
    else:
        report += ['### Robust Findings (DR M9 v0.3 candidates)\n']
        for f in all_robust:
            report.append(f'- {f}')
        report.append(
            '\n> Flag these strata for DR M9 v0.3 with pre-registered hypothesis.\n'
        )
        print(f'\nROBUST FINDINGS ({len(all_robust)}): {all_robust}')

    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    with open(OUT_MD, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(report))
    print(f'\nReport → {OUT_MD}')
