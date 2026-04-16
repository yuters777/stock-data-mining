#!/usr/bin/env python3
"""Temporary verification: run the EXACT m4_backtest_5yr.py M4 logic
on _m5_extended.csv data (ET-timezone), falling back to _data.csv if
_m5_extended.csv is absent.

Purpose: determine whether N=28 (baseline) vs N=47 (new RTH script)
is caused by (a) different data source or (b) logic difference.

If this script gives ~47 in 2025-2026 window when _m5_extended.csv is
present → pure data-source effect, logic is equivalent.
If it gives ~28 → logic difference remains.

Do NOT commit this script.
Usage: python scripts/verify_orig_logic_on_extended.py
"""

import os
import sys
import numpy as np
import pandas as pd

BASE    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA    = os.path.join(BASE, 'Fetched_Data')
SCRIPTS = os.path.join(BASE, 'scripts')
sys.path.insert(0, SCRIPTS)

# ── Same 22 tickers as baseline (those with _m5_full.csv / _data.csv) ─────────
TICKERS_22 = [
    'AAPL', 'AMD', 'AMZN', 'AVGO', 'BA', 'BABA', 'BIDU',
    'C', 'COIN', 'COST', 'GOOGL', 'GS', 'JPM',
    'MARA', 'META', 'MSFT', 'MU', 'NVDA', 'PLTR',
    'TSLA', 'TSM', 'V',
]

# ── Import exact baseline helpers (unchanged from m4_backtest_5yr.py) ──────────
from m4_backtest_5yr import (
    rsi14, calc_streak, flag_corrupt,
    apply_ema21_warmup_mask, load_vix, prior_vix,
)

# ── Import ET-aware data loader from backtest_utils_extended ───────────────────
from backtest_utils_extended import (
    load_extended_data,     # loads _m5_extended.csv with correct ET timestamps
    build_4h_extended,      # builds RTH or extended bars from ET M5 data
    load_vix_daily,
)


def _load_ticker_rth_bars(ticker: str):
    """Load RTH 4H bars for ticker, preferring _m5_extended.csv over _data.csv.

    Returns (bars_df, source_label) where bars_df has columns matching
    what m4_backtest_5yr.backtest_ticker() produces:
      ts (Timestamp), Open, High, Low, Close, session (0=Bar1, 1=Bar2)

    For _m5_extended.csv: uses build_4h_extended(mode='rth') — correct ET handling.
    For _data.csv fallback: uses m4_backtest_5yr.build_4h() — correct UTC handling.
    """
    # ── Prefer _m5_extended.csv ────────────────────────────────────────────────
    ext_path = os.path.join(DATA, f'{ticker}_m5_extended.csv')
    if os.path.exists(ext_path):
        df_m5 = load_extended_data(ticker)               # ET-aware loader
        bars  = build_4h_extended(df_m5, mode='rth')    # correct ET RTH filter

        # build_4h_extended returns lowercase columns + date/bar_label.
        # Convert to the format expected by the baseline indicator/streak code.
        bars = bars.rename(columns={
            'open': 'Open', 'high': 'High', 'low': 'Low',
            'close': 'Close', 'volume': 'Volume',
        })

        # Reconstruct a canonical 'ts' timestamp (09:30 for Bar1, 13:30 for Bar2)
        # matching m4_backtest_5yr.build_4h() output so calc_streak() gap logic works.
        _label_to_session = {'1': 0, '2': 1}
        bars['session'] = bars['bar_label'].map(_label_to_session)

        _label_to_hm = {'1': (9, 30), '2': (13, 30)}
        bars['ts'] = bars.apply(
            lambda r: pd.Timestamp(str(r['date'])) + pd.Timedelta(
                hours=_label_to_hm[r['bar_label']][0],
                minutes=_label_to_hm[r['bar_label']][1]
            ),
            axis=1,
        )
        bars = bars.sort_values('ts').reset_index(drop=True)
        return bars, '_m5_extended.csv'

    # ── Fallback: _data.csv (UTC, handled by original build_4h) ───────────────
    from m4_backtest_5yr import build_4h, _norm_m5
    data_path = os.path.join(DATA, f'{ticker}_data.csv')
    if os.path.exists(data_path):
        raw  = _norm_m5(pd.read_csv(data_path))
        bars = build_4h(raw)
        return bars, '_data.csv'

    return pd.DataFrame(), 'NOT_FOUND'


def _run_m4_on_bars(ticker: str, bars: pd.DataFrame,
                    vix: pd.Series, source: str) -> list[dict]:
    """Apply EXACT m4_backtest_5yr.backtest_ticker() M4 logic to pre-built bars.

    Identical to backtest_ticker() except:
    - bars already built (avoids double file I/O)
    - treats every file as 'full-coverage' (no apply_ema21_warmup_mask)
      to match the _m5_full.csv path in the original
    """
    if bars.empty or len(bars) < 20:
        return []

    is_full_coverage = source.endswith('_m5_full.csv') or source.endswith('_m5_extended.csv')

    corrupt       = flag_corrupt(bars['Close']).values
    bars['ema21'] = bars['Close'].ewm(span=21, adjust=False).mean()
    if not is_full_coverage:
        bars['ema21'] = apply_ema21_warmup_mask(bars)   # only for _data.csv
    bars['rsi']    = rsi14(bars['Close'])
    bars['streak'] = calc_streak(bars)                  # uses bars['ts'] for gaps

    closes  = bars['Close'].values
    emas    = bars['ema21'].values
    rsis    = bars['rsi'].values
    streaks = bars['streak']
    dates   = [ts.date() for ts in bars['ts']]

    trades = []
    i = 0
    while i < len(bars):
        if corrupt[i]:
            i += 1; continue
        vix_val = prior_vix(dates[i], vix)
        if np.isnan(vix_val) or vix_val < 25:
            i += 1; continue
        rsi_val = rsis[i]
        if np.isnan(rsi_val) or rsi_val >= 35:
            i += 1; continue
        if streaks.iloc[i] < 3:
            i += 1; continue
        if np.isnan(emas[i]):
            i += 1; continue

        entry_price = float(closes[i])
        entry_date  = dates[i]
        exit_price  = exit_date = exit_type = None
        bars_held   = 0

        for j in range(i + 1, min(i + 11, len(bars))):
            bars_held += 1
            if corrupt[j]:
                exit_price, exit_date, exit_type = float(closes[j]), dates[j], 'hard_max'; break
            if closes[j] >= emas[j]:
                exit_price, exit_date, exit_type = float(closes[j]), dates[j], 'ema21';    break
            if bars_held == 10:
                exit_price, exit_date, exit_type = float(closes[j]), dates[j], 'hard_max'; break

        if exit_price is None:
            i += 1; continue

        ret = (exit_price - entry_price) / entry_price * 100
        trades.append({
            'ticker':       ticker,
            'entry_date':   str(entry_date),
            'entry_price':  round(entry_price, 4),
            'exit_date':    str(exit_date),
            'exit_price':   round(exit_price, 4),
            'return_pct':   round(ret, 4),
            'bars_held':    int(bars_held),
            'exit_type':    exit_type,
            'rsi_at_entry': round(float(rsis[i]), 2),
            'vix_at_entry': round(float(vix_val), 2),
            'source':       source,
        })
        i += bars_held + 1

    return trades


def _stats(trades: list) -> dict:
    if not trades:
        return dict(N=0, PF=0.0, WR=0.0, Mean=0.0, Avg_Hold=0.0)
    rets  = np.array([t['return_pct'] for t in trades], dtype=float)
    holds = np.array([t['bars_held']  for t in trades], dtype=float)
    wins  = rets[rets > 0];  losses = rets[rets <= 0]
    pf    = float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float('inf')
    return dict(
        N=len(rets), PF=round(pf, 2),
        WR=round(float((rets > 0).mean() * 100), 2),
        Mean=round(float(rets.mean()), 4),
        Avg_Hold=round(float(holds.mean()), 2),
    )


def main():
    SEP = '=' * 65
    print(SEP)
    print('VERIFICATION: original M4 logic on _m5_extended.csv')
    print(SEP)

    print('\nLoading VIX (baseline format — pd.Series)...')
    vix = load_vix()

    all_trades = []
    sources    = {}

    print(f'\n{"Ticker":<8}  {"Source":<22}  {"Bars":>5}  {"N":>3}')
    print('─' * 45)

    for ticker in TICKERS_22:
        bars, source = _load_ticker_rth_bars(ticker)
        sources[ticker] = source

        if bars.empty:
            print(f'{ticker:<8}  {"NOT FOUND":<22}  {"---":>5}  {"---":>3}')
            continue

        trades = _run_m4_on_bars(ticker, bars, vix, source)
        all_trades.extend(trades)
        print(f'{ticker:<8}  {source:<22}  {len(bars):>5}  {len(trades):>3}')

    # ── Summary: all dates ─────────────────────────────────────────────────────
    print(f'\n{SEP}')
    print('RESULTS — ALL DATES')
    print(SEP)
    s_all = _stats(all_trades)
    print(f'  N={s_all["N"]}  PF={s_all["PF"]}  WR={s_all["WR"]}%  '
          f'Mean={s_all["Mean"]:+.4f}%  Avg_Hold={s_all["Avg_Hold"]} bars')

    # ── Summary: 2025-2026 only ────────────────────────────────────────────────
    trades_25 = [t for t in all_trades if t['entry_date'][:4] in ('2025', '2026')]
    s_25 = _stats(trades_25)
    print(f'\nRESULTS — 2025-2026 ONLY (baseline VIX≥25 window)')
    print(f'  N={s_25["N"]}  PF={s_25["PF"]}  WR={s_25["WR"]}%  '
          f'Mean={s_25["Mean"]:+.4f}%  Avg_Hold={s_25["Avg_Hold"]} bars')

    # ── Per-ticker breakdown ───────────────────────────────────────────────────
    print(f'\n{SEP}')
    print('PER-TICKER  (all-dates N  |  2025-26 N)')
    print(SEP)
    for ticker in TICKERS_22:
        t_all = [t for t in all_trades if t['ticker'] == ticker]
        t_25  = [t for t in t_all      if t['entry_date'][:4] in ('2025', '2026')]
        src   = sources.get(ticker, 'NOT_FOUND')
        print(f'  {ticker:<6}  {len(t_all):>3}  {len(t_25):>3}   ({src})')

    # ── Year breakdown ─────────────────────────────────────────────────────────
    df = pd.DataFrame(all_trades) if all_trades else pd.DataFrame()
    if not df.empty:
        df['year'] = df['entry_date'].str[:4]
        print(f'\n{SEP}')
        print('BY YEAR')
        print(SEP)
        for yr, grp in df.groupby('year'):
            s = _stats(grp.to_dict('records'))
            print(f'  {yr}  N={s["N"]}  Mean={s["Mean"]:+.4f}%  WR={s["WR"]}%')

    # ── Data source summary ────────────────────────────────────────────────────
    from collections import Counter
    src_counts = Counter(sources.values())
    print(f'\n{SEP}')
    print('DATA SOURCE USED PER TICKER')
    print(SEP)
    for src, cnt in sorted(src_counts.items()):
        print(f'  {src:<25}  {cnt} tickers')

    # ── Comparison table ───────────────────────────────────────────────────────
    print(f'\n{SEP}')
    print('COMPARISON TABLE  (2025-2026 window)')
    print(SEP)
    rows = [
        ('Metric',      'Baseline (_data.csv)',  'This run',            'New RTH script'),
        ('N',           '28',                    str(s_25["N"]),        '47 (from local run)'),
        ('PF',          '4.95',                  f'{s_25["PF"]:.2f}',  '?'),
        ('WR %',        '71.43%',                f'{s_25["WR"]:.2f}%', '?'),
        ('Mean %',      '+4.63%',                f'{s_25["Mean"]:+.2f}%', '?'),
        ('Avg Hold',    '8.75',                  f'{s_25["Avg_Hold"]:.2f}', '?'),
    ]
    col = [22, 22, 16, 20]
    print(f'  {"Metric":<{col[0]}} {"Baseline (_data.csv)":<{col[1]}} '
          f'{"This run":<{col[2]}} {"New RTH script":<{col[3]}}')
    print('  ' + '─' * sum(col))
    for label, v1, v2, v3 in rows[1:]:
        print(f'  {label:<{col[0]}} {v1:<{col[1]}} {v2:<{col[2]}} {v3:<{col[3]}}')


if __name__ == '__main__':
    main()
