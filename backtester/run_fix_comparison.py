"""
FIX Comparison Backtest: Isolate effect of same-level limit + direction filter.

Runs 4 configurations side by side:
  A) Baseline (no fixes) — 6 tickers, no level limit, no direction filter
  B) Same-level limit ONLY — 6 tickers, MAX_CONSECUTIVE_LOSSES_PER_LEVEL=2
  C) Same-level limit + direction filter — 6 tickers (NVDA included)
  D) Same-level limit + direction filter — 5 tickers (NVDA excluded)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from collections import defaultdict

from backtester.backtester import Backtester, BacktestConfig
from backtester.core.level_detector import LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngineConfig
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig
from backtester.data_types import ExitReason, SignalDirection

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
TICKERS_6 = ['TSLA', 'AMZN', 'GOOGL', 'META', 'MSFT', 'NVDA']
START_DATE = '2025-02-10'
END_DATE = '2026-02-01'


def load_tickers(tickers):
    frames = []
    for ticker in tickers:
        path = os.path.join(DATA_DIR, f'{ticker}_data.csv')
        if not os.path.exists(path):
            print(f"  SKIP: {path} not found")
            continue
        df = pd.read_csv(path)
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        df = df.sort_values('Datetime').reset_index(drop=True)
        frames.append(df)
    return pd.concat(frames, ignore_index=True).sort_values(
        ['Ticker', 'Datetime']).reset_index(drop=True)


def make_config(name, direction_filter=None, max_level_losses=None):
    """Build a BacktestConfig with Phase 2.2 params."""
    risk_kwargs = dict(
        min_rr=3.0,
        max_stop_atr_pct=0.10,
        capital=100000.0,
        risk_pct=0.003,
    )
    if max_level_losses is not None:
        risk_kwargs['max_consecutive_losses_per_level'] = max_level_losses

    return BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=5,
            tolerance_cents=0.05,
            tolerance_pct=0.001,
            atr_period=5,
            min_level_score=5,
            cross_count_invalidate=5,
            cross_count_window=30,
        ),
        pattern_config=PatternEngineConfig(
            tail_ratio_min=0.15,
            lp2_engulfing_required=True,
            clp_min_bars=3,
            clp_max_bars=7,
        ),
        filter_config=FilterChainConfig(
            atr_block_threshold=0.25,
            atr_entry_threshold=0.70,
            enable_volume_filter=True,
            enable_time_filter=True,
            enable_squeeze_filter=True,
        ),
        risk_config=RiskManagerConfig(**risk_kwargs),
        trade_config=TradeManagerConfig(
            slippage_per_share=0.02,
            partial_tp_at_r=2.0,
            partial_tp_pct=0.50,
        ),
        tier_config={
            'mode': '2tier_trail',
            't1_pct': 0.30,
            'trail_factor': 0.7,
            'trail_activation_r': 0.0,
            'min_rr': 1.5,
        },
        direction_filter=direction_filter,
        name=name,
    )


def calc_pf(trades):
    gross_p = sum(t.pnl for t in trades if t.pnl > 0)
    gross_l = abs(sum(t.pnl for t in trades if t.pnl < 0))
    return gross_p / gross_l if gross_l > 0 else float('inf') if gross_p > 0 else 0.0


def calc_sharpe(daily_pnl):
    if not daily_pnl:
        return 0.0
    vals = list(daily_pnl.values())
    if len(vals) < 2 or np.std(vals) == 0:
        return 0.0
    return np.mean(vals) / np.std(vals) * np.sqrt(252)


def calc_max_dd(equity_curve):
    if not equity_curve:
        return 0.0
    eq = [e[1] for e in equity_curve]
    peak = eq[0]
    max_dd = 0
    for v in eq:
        peak = max(peak, v)
        dd = (peak - v) / peak
        max_dd = max(max_dd, dd)
    return max_dd * 100


def run_one(config, m5_df):
    """Run a single backtest and return summary dict."""
    bt = Backtester(config)
    result = bt.run(m5_df, start_date=START_DATE, end_date=END_DATE)
    trades = result.trades
    p = result.performance

    # Per-ticker breakdown
    ticker_stats = {}
    for t in trades:
        tk = t.signal.ticker
        if tk not in ticker_stats:
            ticker_stats[tk] = {'trades': 0, 'w': 0, 'l': 0, 'pnl': 0.0}
        ticker_stats[tk]['trades'] += 1
        ticker_stats[tk]['pnl'] += t.pnl
        if t.pnl > 0:
            ticker_stats[tk]['w'] += 1
        else:
            ticker_stats[tk]['l'] += 1

    # Count exhausted levels
    exhausted_count = len(bt.risk_manager.cb_state.exhausted_levels)
    level_exhausted_blocked = bt.signals_blocked.get('level_exhausted', 0)

    return {
        'name': config.name,
        'trades': len(trades),
        'winners': p.get('winners', 0),
        'losers': p.get('losers', 0),
        'win_rate': p.get('win_rate', 0) * 100,
        'pf': p.get('profit_factor', 0),
        'pnl': p.get('total_pnl', 0),
        'sharpe': calc_sharpe(result.daily_pnl),
        'max_dd': calc_max_dd(result.equity_curve),
        'avg_r': p.get('avg_r', 0),
        'ticker_stats': ticker_stats,
        'exhausted_levels': exhausted_count,
        'signals_blocked_exhausted': level_exhausted_blocked,
        'signals_blocked_direction': bt.signals_blocked.get('direction_filter', 0),
        'exit_reasons': {
            'stop_loss': sum(1 for t in trades if t.exit_reason == ExitReason.STOP_LOSS),
            'target_hit': sum(1 for t in trades if t.exit_reason == ExitReason.TARGET_HIT),
            'trail_stop': sum(1 for t in trades if t.exit_reason == ExitReason.TRAIL_STOP),
            'breakeven': sum(1 for t in trades if t.exit_reason == ExitReason.BREAKEVEN),
            'eod_exit': sum(1 for t in trades if t.exit_reason == ExitReason.EOD_EXIT),
            'nison_exit': sum(1 for t in trades if t.exit_reason == ExitReason.NISON_EXIT),
        },
        'result': result,
    }


def print_comparison(results):
    """Print side-by-side comparison."""
    labels = [r['name'] for r in results]
    w = 14

    print("\n" + "=" * 80)
    print("SIDE-BY-SIDE COMPARISON")
    print("=" * 80)

    # Header
    print(f"\n  {'Metric':<22}", end="")
    for lbl in labels:
        print(f"  {lbl:>{w}}", end="")
    print()
    print(f"  {'-'*22}", end="")
    for _ in labels:
        print(f"  {'-'*w}", end="")
    print()

    # Rows
    rows = [
        ('Trades', 'trades', 'd', ''),
        ('Winners', 'winners', 'd', ''),
        ('Losers', 'losers', 'd', ''),
        ('Win Rate', 'win_rate', '.1f', '%'),
        ('Profit Factor', 'pf', '.2f', ''),
        ('Total P&L', 'pnl', '.0f', '$'),
        ('Sharpe', 'sharpe', '.2f', ''),
        ('Max DD %', 'max_dd', '.2f', '%'),
        ('Avg R', 'avg_r', '.2f', 'R'),
        ('Exhausted Levels', 'exhausted_levels', 'd', ''),
        ('Blocked (exhaust)', 'signals_blocked_exhausted', 'd', ''),
        ('Blocked (direction)', 'signals_blocked_direction', 'd', ''),
    ]

    for label, key, fmt, suffix in rows:
        print(f"  {label:<22}", end="")
        for r in results:
            val = r[key]
            if suffix == '$':
                s = f"${val:>{w-1}{fmt}}"
            elif suffix:
                s = f"{val:>{w-len(suffix)}{fmt}}{suffix}"
            else:
                s = f"{val:>{w}{fmt}}"
            print(f"  {s}", end="")
        print()

    # Per-ticker P&L
    all_tickers = sorted(set(tk for r in results for tk in r['ticker_stats']))
    if all_tickers:
        print(f"\n  {'TICKER P&L':<22}", end="")
        for lbl in labels:
            print(f"  {lbl:>{w}}", end="")
        print()
        print(f"  {'-'*22}", end="")
        for _ in labels:
            print(f"  {'-'*w}", end="")
        print()

        for tk in all_tickers:
            print(f"  {tk:<22}", end="")
            for r in results:
                ts = r['ticker_stats'].get(tk, {})
                n = ts.get('trades', 0)
                pnl = ts.get('pnl', 0)
                w_count = ts.get('w', 0)
                l_count = ts.get('l', 0)
                if n > 0:
                    s = f"{w_count}W/{l_count}L ${pnl:+.0f}"
                else:
                    s = "—"
                print(f"  {s:>{w}}", end="")
            print()

    # Exit reasons
    reason_keys = ['stop_loss', 'target_hit', 'trail_stop', 'breakeven', 'eod_exit', 'nison_exit']
    print(f"\n  {'EXIT REASONS':<22}", end="")
    for lbl in labels:
        print(f"  {lbl:>{w}}", end="")
    print()
    print(f"  {'-'*22}", end="")
    for _ in labels:
        print(f"  {'-'*w}", end="")
    print()
    for reason in reason_keys:
        print(f"  {reason:<22}", end="")
        for r in results:
            val = r['exit_reasons'].get(reason, 0)
            print(f"  {val:>{w}d}", end="")
        print()


def main():
    print("=" * 80)
    print("FIX COMPARISON: Same-Level Limit + Direction Filter")
    print("=" * 80)
    print(f"Period: {START_DATE} to {END_DATE}")
    print(f"Tickers: {', '.join(TICKERS_6)}")

    print(f"\nLoading data (6 tickers)...")
    m5_all = load_tickers(TICKERS_6)
    print(f"Total M5 bars: {len(m5_all)}")

    # ── Config A: Baseline (no fixes) ──
    print("\n\n" + "─" * 60)
    print("Running A: Baseline (no level limit, no direction filter)...")
    cfg_a = make_config("A_baseline", direction_filter=None, max_level_losses=999)
    res_a = run_one(cfg_a, m5_all)

    # ── Config B: Same-level limit only ──
    print("Running B: Same-level limit only (max_level_losses=2)...")
    cfg_b = make_config("B_lvl_limit", direction_filter=None, max_level_losses=2)
    res_b = run_one(cfg_b, m5_all)

    # ── Config C: Same-level limit + direction filter (6 tickers) ──
    dir_filter_6 = {
        'TSLA': 'long',
        'NVDA': 'both',     # keep NVDA, let level limit help
        'GOOGL': 'both',
        'MSFT': 'both',
        'META': 'both',
        'AMZN': 'both',
        'DEFAULT': 'both',
    }
    print("Running C: Level limit + direction filter (6 tickers, NVDA=both)...")
    cfg_c = make_config("C_6tk_dir", direction_filter=dir_filter_6, max_level_losses=2)
    res_c = run_one(cfg_c, m5_all)

    # ── Config D: Same-level limit + direction filter (NVDA excluded) ──
    dir_filter_5 = {
        'TSLA': 'long',
        'NVDA': 'excluded',
        'GOOGL': 'both',
        'MSFT': 'both',
        'META': 'both',
        'AMZN': 'both',
        'DEFAULT': 'both',
    }
    print("Running D: Level limit + direction filter (NVDA excluded)...")
    cfg_d = make_config("D_5tk_excl", direction_filter=dir_filter_5, max_level_losses=2)
    res_d = run_one(cfg_d, m5_all)

    # ── Print comparison ──
    print_comparison([res_a, res_b, res_c, res_d])

    # ── Delta analysis ──
    print("\n\n" + "=" * 80)
    print("DELTA ANALYSIS")
    print("=" * 80)
    print(f"\n  Effect of same-level limit (B vs A):")
    print(f"    Trades: {res_a['trades']} → {res_b['trades']} ({res_b['trades']-res_a['trades']:+d})")
    print(f"    P&L:    ${res_a['pnl']:+.0f} → ${res_b['pnl']:+.0f} ({res_b['pnl']-res_a['pnl']:+.0f})")
    print(f"    PF:     {res_a['pf']:.2f} → {res_b['pf']:.2f} ({res_b['pf']-res_a['pf']:+.2f})")
    print(f"    Levels exhausted: {res_b['exhausted_levels']}")
    print(f"    Signals blocked by exhaustion: {res_b['signals_blocked_exhausted']}")

    print(f"\n  Effect of direction filter on top (C vs B):")
    print(f"    Trades: {res_b['trades']} → {res_c['trades']} ({res_c['trades']-res_b['trades']:+d})")
    print(f"    P&L:    ${res_b['pnl']:+.0f} → ${res_c['pnl']:+.0f} ({res_c['pnl']-res_b['pnl']:+.0f})")
    print(f"    PF:     {res_b['pf']:.2f} → {res_c['pf']:.2f} ({res_c['pf']-res_b['pf']:+.2f})")

    print(f"\n  Effect of excluding NVDA (D vs C):")
    print(f"    Trades: {res_c['trades']} → {res_d['trades']} ({res_d['trades']-res_c['trades']:+d})")
    print(f"    P&L:    ${res_c['pnl']:+.0f} → ${res_d['pnl']:+.0f} ({res_d['pnl']-res_c['pnl']:+.0f})")
    print(f"    PF:     {res_c['pf']:.2f} → {res_d['pf']:.2f} ({res_d['pf']-res_c['pf']:+.2f})")

    print(f"\n  Full improvement (D vs A):")
    print(f"    Trades: {res_a['trades']} → {res_d['trades']} ({res_d['trades']-res_a['trades']:+d})")
    print(f"    P&L:    ${res_a['pnl']:+.0f} → ${res_d['pnl']:+.0f} ({res_d['pnl']-res_a['pnl']:+.0f})")
    print(f"    PF:     {res_a['pf']:.2f} → {res_d['pf']:.2f} ({res_d['pf']-res_a['pf']:+.2f})")
    print(f"    Sharpe: {res_a['sharpe']:.2f} → {res_d['sharpe']:.2f} ({res_d['sharpe']-res_a['sharpe']:+.2f})")
    print(f"    MaxDD:  {res_a['max_dd']:.2f}% → {res_d['max_dd']:.2f}% ({res_d['max_dd']-res_a['max_dd']:+.2f}%)")

    print("\n" + "=" * 80)
    print("DONE")
    print("=" * 80)


if __name__ == '__main__':
    main()
