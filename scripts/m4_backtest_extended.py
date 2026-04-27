#!/usr/bin/env python3
"""M4 Mean-Reversion backtest on extended hours 4H bars.
Compares extended (4 bars/day) vs RTH (2 bars/day).

Usage: python scripts/m4_backtest_extended.py
"""
import sys
import os

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_utils_extended import (
    load_vix_daily,
    load_extended_data,
    build_4h_extended,
    compute_indicators,
    flag_corrupt,
    apply_ema21_warmup_mask,
    load_earnings,
    is_earnings_window,
)

# 22 tickers that have _m5_full.csv in Fetched_Data — matches m4_backtest_5yr.py baseline.
# Excluded (no _m5_full.csv): ARM, INTC, JD, MSTR, SMCI
TICKERS = ['AAPL', 'AMD', 'AMZN', 'AVGO', 'BA', 'BABA', 'BIDU',
           'C', 'COIN', 'COST', 'GOOGL', 'GS', 'JPM',
           'MARA', 'META', 'MSFT', 'MU', 'NVDA', 'PLTR',
           'TSLA', 'TSM', 'V']  # 22 equity, matching baseline

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(_BASE, 'results', 'extended_validation')

# Bar label -> (hour, minute) ET for canonical timestamp reconstruction.
# RTH bars use :30 offsets matching m4_backtest_5yr.py (Bar1=09:30, Bar2=13:30).
_BAR_TIME = {
    'A': (4, 0), 'B': (8, 0), 'C': (12, 0), 'D': (16, 0),
    '1': (9, 30), '2': (13, 30),
}

KNOWN_BASELINE = {
    'N': 28,       # actual run of m4_backtest_5yr.py (2025-2026 VIX≥25 window, 22 tickers)
    'PF': 4.95,
    'WR': 71.43,
    'Mean': 4.63,
    'Avg_Hold': 8.75,
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _bar_timestamp(date, bar_label: str) -> pd.Timestamp:
    """Reconstruct a full Timestamp from bar date + label (for gap checks)."""
    h, m = _BAR_TIME.get(str(bar_label), (9, 30))
    return pd.Timestamp(str(date)) + pd.Timedelta(hours=h, minutes=m)


def _prior_vix(bar_date, vix_df: pd.DataFrame) -> float:
    """Return VIX close from the last trading day strictly before bar_date.

    bar_date may be a datetime.date or anything comparable to vix_df['date'].
    vix_df must be sorted ascending by 'date'.
    Returns np.nan if no prior date exists.
    """
    mask = vix_df['date'] < bar_date
    if not mask.any():
        return np.nan
    return float(vix_df.loc[mask, 'vix_close'].iloc[-1])


def _calc_streak(bars: pd.DataFrame) -> np.ndarray:
    """Consecutive 4H down bars (close < open).

    Streak increments on each consecutive down bar.
    Resets on:
      - a non-down bar (close >= open), OR
      - a time gap > 30 hours between consecutive bars
        (Fri→Mon RTH gap is ~68h, so streaks always reset over weekends —
         matching m4_backtest_5yr.calc_streak() exactly)
    """
    n = len(bars)
    streaks = np.zeros(n, dtype=np.int32)
    dates = bars['date'].tolist()
    labels = bars['bar_label'].tolist()
    closes = bars['close'].values
    opens = bars['open'].values

    s = 0
    prev_ts = None
    for i in range(n):
        ts = _bar_timestamp(dates[i], labels[i])
        if prev_ts is not None:
            gap_hours = (ts - prev_ts).total_seconds() / 3600
            if gap_hours > 30:
                s = 0
        if closes[i] < opens[i]:
            s += 1
        else:
            s = 0
        streaks[i] = s
        prev_ts = ts
    return streaks


def _compute_stats(trades: list) -> dict:
    """Aggregate N, PF, WR, Mean, Avg_Hold from a list of trade dicts."""
    if not trades:
        return {'N': 0, 'PF': 0.0, 'WR': 0.0, 'Mean': 0.0, 'Avg_Hold': 0.0}
    rets = np.array([t['return_pct'] for t in trades], dtype=float)
    holds = np.array([t['hold_bars'] for t in trades], dtype=float)
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    pf = float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float('inf')
    wr = float((rets > 0).mean() * 100)
    return {
        'N': len(rets),
        'PF': round(pf, 2),
        'WR': round(wr, 2),
        'Mean': round(float(rets.mean()), 4),
        'Avg_Hold': round(float(holds.mean()), 2),
    }


# ── Per-ticker backtest ────────────────────────────────────────────────────────

def run_m4_single_ticker(ticker: str, bars: pd.DataFrame,
                         vix_df: pd.DataFrame,
                         earnings_dict: dict = None, buffer_days: int = 0) -> list:
    """Run M4 backtest on a single ticker's pre-built 4H bars.

    M4 Entry (ALL must be true):
      1. 3+ consecutive 4H down bars (close < open)
      2. Prior-day VIX close >= 25
      3. RSI(14) < 35 at trigger bar
      4. EMA21 valid (not NaN — warmup guard)

    M4 Exit (first triggered):
      1. 4H close >= EMA21
      2. 10-bar hard maximum

    Rules:
      - One position per ticker at a time; no overlap/stacking
      - Entry price  = trigger bar close
      - Exit price   = exit bar close
      - "Down bar"   = close < open
      - Streak resets on non-down bar OR time gap > 30 hours (resets on weekends)
      - VIX          = prior trading-day close (not intraday)
      - No earnings filter for M4

    Returns list of trade dicts.
    """
    if bars.empty or len(bars) < 30:
        return []

    streaks = _calc_streak(bars)
    corrupt = flag_corrupt(bars['close']).values
    dates = bars['date'].tolist()
    labels = bars['bar_label'].tolist()
    closes = bars['close'].values
    emas = bars['ema21'].values
    rsis = bars['rsi14'].values
    n = len(bars)

    trades = []
    i = 0
    while i < n:
        # Gate 0: skip corrupt bars (split artefacts / bad data)
        if corrupt[i]:
            i += 1
            continue

        # Gate 1: streak >= 3
        if streaks[i] < 3:
            i += 1
            continue

        # Gate 2: EMA21 valid (warmup guard)
        if np.isnan(emas[i]):
            i += 1
            continue

        # Gate 3: RSI(14) < 35  (frozen hard gate)
        rsi_val = rsis[i]
        if np.isnan(rsi_val) or rsi_val >= 35.0:
            i += 1
            continue

        # Gate 4: prior-day VIX >= 25
        bar_date = dates[i]
        vix_val = _prior_vix(bar_date, vix_df)
        if np.isnan(vix_val) or vix_val < 25.0:
            i += 1
            continue

        if buffer_days > 0 and earnings_dict is not None:
            if is_earnings_window(ticker, bar_date, earnings_dict, buffer_days=buffer_days):
                i += 1
                continue  # Retroactive filter: skip valid M4 signal due to earnings proximity

        # ── All gates passed — open trade ──────────────────────────────────
        entry_price = closes[i]
        entry_date = dates[i]
        entry_bar = labels[i]
        conviction_tier = 'TIER_B' if rsi_val < 25.0 else 'TIER_A'

        exit_price = None
        exit_date = None
        exit_bar = None
        exit_reason = None
        bars_held = 0

        for j in range(i + 1, min(i + 11, n)):
            bars_held += 1
            # Corrupt bar during hold → hard_max exit immediately
            if corrupt[j]:
                exit_price = closes[j]
                exit_date = dates[j]
                exit_bar = labels[j]
                exit_reason = 'hard_max'
                break
            # EMA21 exit: close >= EMA21 (skip if EMA still in warmup)
            if not np.isnan(emas[j]) and closes[j] >= emas[j]:
                exit_price = closes[j]
                exit_date = dates[j]
                exit_bar = labels[j]
                exit_reason = 'ema21'
                break
            # Hard max: 10-bar limit
            if bars_held == 10:
                exit_price = closes[j]
                exit_date = dates[j]
                exit_bar = labels[j]
                exit_reason = 'hard_max'
                break

        if exit_price is None:
            # Not enough bars remaining after trigger — skip
            i += 1
            continue

        ret_pct = (exit_price - entry_price) / entry_price * 100
        trades.append({
            'ticker': ticker,
            'entry_date': str(entry_date),
            'entry_bar': entry_bar,
            'entry_price': round(float(entry_price), 4),
            'exit_date': str(exit_date),
            'exit_bar': exit_bar,
            'exit_price': round(float(exit_price), 4),
            'exit_reason': exit_reason,
            'return_pct': round(float(ret_pct), 4),
            'hold_bars': int(bars_held),
            'rsi_at_entry': round(float(rsi_val), 2),
            'vix_at_entry': round(float(vix_val), 2),
            'conviction_tier': conviction_tier,
        })

        # Advance past exit bar — one position per ticker, no stacking
        i += bars_held + 1

    return trades


# ── Multi-ticker runner ────────────────────────────────────────────────────────

def run_m4_backtest(mode: str = 'extended', vix_df: pd.DataFrame = None,
                    earnings_dict: dict = None, buffer_days: int = 0) -> list:
    """Run M4 backtest for all tickers in the given bar mode.

    Parameters
    ----------
    mode   : 'extended' (4 bars/day) or 'rth' (2 bars/day)
    vix_df : pre-loaded VIX DataFrame from load_vix_daily()

    Returns list of trade dicts across all tickers.
    """
    if vix_df is None:
        raise ValueError("vix_df must be provided — call load_vix_daily() first")

    all_trades = []
    for ticker in TICKERS:
        print(f'  {ticker}...', end=' ', flush=True)
        try:
            df = load_extended_data(ticker)
        except FileNotFoundError:
            print('SKIP (no data)')
            continue

        bars = build_4h_extended(df, mode=mode)
        if mode == 'rth':
            # RTH: no static warmup blanket — use gap-based masking only,
            # matching m4_backtest_5yr.py behaviour for _m5_full.csv files.
            bars = compute_indicators(bars, warmup_rows=0)
            bars['ema21'] = apply_ema21_warmup_mask(bars)
        else:
            bars = compute_indicators(bars)  # static 25-row warmup for extended
        trades = run_m4_single_ticker(ticker, bars, vix_df,
                                       earnings_dict=earnings_dict, buffer_days=buffer_days)
        all_trades.extend(trades)
        print(f'{len(trades)} trades')

    return all_trades


# ── Output helpers ─────────────────────────────────────────────────────────────

def _print_comparison(stats_rth: dict, stats_ext: dict) -> None:
    """Print aligned comparison table to stdout."""
    bl = KNOWN_BASELINE
    col_w = [22, 18, 20, 16]
    header = (f'{"Metric":<{col_w[0]}} {"RTH (2 bars/day)":>{col_w[1]}}'
              f' {"Extended (4 bars/day)":>{col_w[2]}} {"Known Baseline":>{col_w[3]}}')
    sep = '-' * sum(col_w)
    print()
    print(header)
    print(sep)

    def row(label, rth_val, ext_val, bl_val):
        print(f'{label:<{col_w[0]}} {rth_val:>{col_w[1]}} {ext_val:>{col_w[2]}} {bl_val:>{col_w[3]}}')

    row('N', str(stats_rth['N']), str(stats_ext['N']), str(bl['N']))
    row('PF',
        f'{stats_rth["PF"]:.2f}',
        f'{stats_ext["PF"]:.2f}',
        f'{bl["PF"]:.2f}')
    row('WR %',
        f'{stats_rth["WR"]:.1f}%',
        f'{stats_ext["WR"]:.1f}%',
        f'{bl["WR"]:.1f}%')
    row('Mean %',
        f'{stats_rth["Mean"]:+.2f}%',
        f'{stats_ext["Mean"]:+.2f}%',
        f'+{bl["Mean"]:.2f}%')
    row('Avg Hold (bars)',
        f'{stats_rth["Avg_Hold"]:.1f}',
        f'{stats_ext["Avg_Hold"]:.1f}',
        f'{bl["Avg_Hold"]:.1f}')


def _build_comparison_md(stats_rth: dict, stats_ext: dict) -> str:
    """Build markdown comparison table string."""
    bl = KNOWN_BASELINE
    lines = [
        '# M4 Mean-Reversion: Extended Hours 4H Backtest — Comparison',
        '',
        '| Metric | RTH (2 bars/day) | Extended (4 bars/day) | Known Baseline |',
        '|--------|-------------------|----------------------|----------------|',
        f'| N | {stats_rth["N"]} | {stats_ext["N"]} | {bl["N"]} |',
        f'| PF | {stats_rth["PF"]:.2f} | {stats_ext["PF"]:.2f} | {bl["PF"]:.2f} |',
        f'| WR % | {stats_rth["WR"]:.1f}% | {stats_ext["WR"]:.1f}% | {bl["WR"]:.1f}% |',
        f'| Mean % | {stats_rth["Mean"]:+.2f}% | {stats_ext["Mean"]:+.2f}% | +{bl["Mean"]:.2f}% |',
        f'| Avg Hold (bars) | {stats_rth["Avg_Hold"]:.1f} | {stats_ext["Avg_Hold"]:.1f} | {bl["Avg_Hold"]:.1f} |',
        '',
        '## Configuration',
        '',
        '- **RTH mode**: 2 bars/day — Bar 1 (09:30–13:25 ET), Bar 2 (13:30–15:55 ET)',
        '- **Extended mode**: 4 bars/day — Bar A (04:00–07:55 ET), Bar B (08:00–11:55 ET),'
        ' Bar C (12:00–15:55 ET), Bar D (16:00–19:55 ET)',
        '- **Known Baseline**: RTH-only result from prior 1-year backtest run',
        '',
        '## Entry Rules (ALL required)',
        '',
        '1. 3+ consecutive 4H down bars (close < open)',
        '2. Prior-day VIX close >= 25',
        '3. RSI(14) < 35 at trigger bar  *(frozen hard gate)*',
        '4. EMA21 valid (not in warmup)',
        '',
        '## Exit Rules (first triggered)',
        '',
        '1. 4H close >= EMA21',
        '2. 10-bar hard maximum',
        '',
        '## Streak Definition',
        '',
        '- Down bar: close < open',
        '- Streak resets on: non-down bar OR time gap > 30 hours (resets every weekend)',
        '',
        '## Conviction Tiers',
        '',
        '- **TIER_A**: RSI 25–35 at entry',
        '- **TIER_B**: RSI < 25 at entry',
        '',
        '## Notes',
        '',
        '- No earnings filter for M4',
        '- One position per ticker at a time (no stacking)',
        '- Entry price = trigger bar close; Exit price = exit bar close',
        '- VIX = prior trading-day close (max vix_date strictly before bar date)',
    ]
    return '\n'.join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('=' * 60)
    print('M4 EXTENDED HOURS BACKTEST')
    print('=' * 60)

    print('\nLoading VIX data...')
    vix_df = load_vix_daily()
    print(f'  VIX: {len(vix_df)} rows, '
          f'{vix_df["date"].min()} to {vix_df["date"].max()}')

    print('\nLoading earnings data...')
    earnings_dict = load_earnings()
    print(f'  Earnings: {len(earnings_dict)} tickers covered.')

    print('\n--- Mode: EXTENDED (4 bars/day) ---')
    trades_ext = run_m4_backtest('extended', vix_df=vix_df,
                                 earnings_dict=earnings_dict, buffer_days=0)

    print('\n--- Mode: RTH (2 bars/day) ---')
    trades_rth = run_m4_backtest('rth', vix_df=vix_df,
                                 earnings_dict=earnings_dict, buffer_days=0)

    stats_ext = _compute_stats(trades_ext)
    stats_rth = _compute_stats(trades_rth)

    print('\n' + '=' * 60)
    print('COMPARISON TABLE  (all dates)')
    print('=' * 60)
    _print_comparison(stats_rth, stats_ext)

    # ── 2025-2026 window (apples-to-apples with baseline) ─────────────────────
    def _filter_window(trades, year_start=2025, year_end=2026):
        return [t for t in trades
                if year_start <= int(t['entry_date'][:4]) <= year_end]

    trades_rth_25  = _filter_window(trades_rth)
    trades_ext_25  = _filter_window(trades_ext)
    stats_rth_25   = _compute_stats(trades_rth_25)
    stats_ext_25   = _compute_stats(trades_ext_25)

    print('\n' + '=' * 60)
    print('COMPARISON TABLE  (2025-2026 only — same window as baseline)')
    print('=' * 60)
    bl = KNOWN_BASELINE
    col_w = [22, 18, 20, 16]
    header = (f'{"Metric":<{col_w[0]}} {"RTH 2025-26":>{col_w[1]}}'
              f' {"Ext 2025-26":>{col_w[2]}} {"Baseline 22T":>{col_w[3]}}')
    print(header)
    print('-' * sum(col_w))
    for label, rv, ev, bv in [
        ('N',               str(stats_rth_25['N']),                str(stats_ext_25['N']),                str(bl['N'])),
        ('PF',              f'{stats_rth_25["PF"]:.2f}',           f'{stats_ext_25["PF"]:.2f}',           f'{bl["PF"]:.2f}'),
        ('WR %',            f'{stats_rth_25["WR"]:.1f}%',          f'{stats_ext_25["WR"]:.1f}%',          f'{bl["WR"]:.1f}%'),
        ('Mean %',          f'{stats_rth_25["Mean"]:+.2f}%',       f'{stats_ext_25["Mean"]:+.2f}%',       f'+{bl["Mean"]:.2f}%'),
        ('Avg Hold (bars)', f'{stats_rth_25["Avg_Hold"]:.1f}',     f'{stats_ext_25["Avg_Hold"]:.1f}',     f'{bl["Avg_Hold"]:.1f}'),
    ]:
        print(f'{label:<{col_w[0]}} {rv:>{col_w[1]}} {ev:>{col_w[2]}} {bv:>{col_w[3]}}')

    # ── Per-ticker breakdown ───────────────────────────────────────────────────
    print('\n' + '=' * 60)
    print('PER-TICKER TRADE COUNT  (all dates | 2025-26)')
    print('=' * 60)
    print(f'  {"Ticker":<8} {"RTH-all":>8} {"RTH-25":>8} {"EXT-all":>8} {"EXT-25":>8}')
    print('  ' + '-' * 44)
    for tk in TICKERS:
        rth_a = sum(1 for t in trades_rth if t['ticker'] == tk)
        rth_2 = sum(1 for t in trades_rth_25 if t['ticker'] == tk)
        ext_a = sum(1 for t in trades_ext if t['ticker'] == tk)
        ext_2 = sum(1 for t in trades_ext_25 if t['ticker'] == tk)
        print(f'  {tk:<8} {rth_a:>8} {rth_2:>8} {ext_a:>8} {ext_2:>8}')

    # ── Save outputs ──────────────────────────────────────────────────────────
    os.makedirs(OUT_DIR, exist_ok=True)

    if trades_ext:
        ext_path = os.path.join(OUT_DIR, 'm4_extended_trades.csv')
        pd.DataFrame(trades_ext).to_csv(ext_path, index=False)
        print(f'\nExtended trades ({stats_ext["N"]}) -> {ext_path}')

    if trades_rth:
        rth_path = os.path.join(OUT_DIR, 'm4_rth_trades.csv')
        pd.DataFrame(trades_rth).to_csv(rth_path, index=False)
        print(f'RTH trades      ({stats_rth["N"]}) -> {rth_path}')

    comp_path = os.path.join(OUT_DIR, 'm4_comparison.md')
    with open(comp_path, 'w') as f:
        f.write(_build_comparison_md(stats_rth, stats_ext))
    print(f'Comparison      -> {comp_path}')
