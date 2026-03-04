"""
Phase 2.2 REDO — Parameter re-optimization on corrected codebase.
All previous results invalidated by stop-anchoring, Nison, CLP, mirror bugs.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import time

from backtester.backtester import Backtester, BacktestConfig
from backtester.core.level_detector import LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngineConfig
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
TICKERS = ['TSLA', 'AMZN', 'GOOGL', 'META', 'MSFT', 'NVDA']
START = '2025-02-10'
END = '2026-02-01'

# ═══════════════════════════════════════════════════════════════════════
# DEFAULT CONFIG — baseline for all experiments
# ═══════════════════════════════════════════════════════════════════════
DEFAULT = dict(
    fractal_depth=5,
    tolerance_cents=0.05,
    tolerance_pct=0.001,
    atr_period=5,
    min_level_score=5,
    cross_count_invalidate=5,
    cross_count_window=30,
    tail_ratio_min=0.15,
    lp2_engulfing_required=True,
    clp_min_bars=3,
    clp_max_bars=7,
    atr_block_threshold=0.25,
    atr_entry_threshold=0.70,
    max_stop_atr_pct=0.10,
    min_rr=3.0,
    capital=100000.0,
    risk_pct=0.003,
    tier_mode='2tier_trail',
    t1_pct=0.30,
    trail_factor=0.7,
    trail_activation_r=0.0,
    tier_min_rr=1.5,
)


def build_config(name, overrides=None):
    p = {**DEFAULT, **(overrides or {})}
    return BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=p['fractal_depth'],
            tolerance_cents=p['tolerance_cents'],
            tolerance_pct=p['tolerance_pct'],
            atr_period=p['atr_period'],
            min_level_score=p['min_level_score'],
            cross_count_invalidate=p['cross_count_invalidate'],
            cross_count_window=p['cross_count_window'],
        ),
        pattern_config=PatternEngineConfig(
            tail_ratio_min=p['tail_ratio_min'],
            lp2_engulfing_required=p['lp2_engulfing_required'],
            clp_min_bars=p['clp_min_bars'],
            clp_max_bars=p['clp_max_bars'],
        ),
        filter_config=FilterChainConfig(
            atr_block_threshold=p['atr_block_threshold'],
            atr_entry_threshold=p['atr_entry_threshold'],
            enable_volume_filter=True,
            enable_time_filter=True,
            enable_squeeze_filter=True,
        ),
        risk_config=RiskManagerConfig(
            min_rr=p['min_rr'],
            max_stop_atr_pct=p['max_stop_atr_pct'],
            capital=p['capital'],
            risk_pct=p['risk_pct'],
        ),
        trade_config=TradeManagerConfig(),
        tier_config={
            'mode': p['tier_mode'],
            't1_pct': p['t1_pct'],
            'trail_factor': p['trail_factor'],
            'trail_activation_r': p['trail_activation_r'],
            'min_rr': p['tier_min_rr'],
        },
        direction_filter=None,  # BOTH directions, all tickers
        name=name,
    )


def load_data():
    frames = []
    for ticker in TICKERS:
        path = os.path.join(DATA_DIR, f'{ticker}_data.csv')
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path)
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        df = df.sort_values('Datetime').reset_index(drop=True)
        frames.append(df)
    return pd.concat(frames, ignore_index=True).sort_values(
        ['Ticker', 'Datetime']).reset_index(drop=True)


def run_one(name, m5_df, overrides=None):
    cfg = build_config(name, overrides)
    bt = Backtester(cfg)
    t0 = time.time()
    result = bt.run(m5_df, start_date=START, end_date=END)
    elapsed = time.time() - t0
    trades = result.trades
    p = result.performance

    n = len(trades)
    if n == 0:
        return dict(name=name, trades=0, wr=0, pf=0, avg_r=0, maxdd=0,
                    sharpe=0, pnl=0, elapsed=elapsed)

    winners = [t for t in trades if t.pnl > 0]
    losers = [t for t in trades if t.pnl <= 0]
    gross_p = sum(t.pnl for t in winners)
    gross_l = abs(sum(t.pnl for t in losers))
    pf = gross_p / gross_l if gross_l > 0 else (float('inf') if gross_p > 0 else 0)

    return dict(
        name=name,
        trades=n,
        wr=len(winners) / n * 100,
        pf=pf,
        avg_r=p.get('avg_r', 0),
        maxdd=p.get('max_drawdown_pct', 0),
        sharpe=p.get('sharpe', 0),
        pnl=p.get('total_pnl', 0),
        elapsed=elapsed,
    )


def print_table(title, results):
    print(f"\n{'='*90}")
    print(f"  {title}")
    print(f"{'='*90}")
    print(f"  {'Run':>4} {'Trades':>7} {'WR%':>6} {'PF':>7} {'AvgR':>7} {'MaxDD%':>7} {'Sharpe':>7} {'P&L':>12} {'Time':>5}")
    print(f"  {'-'*72}")
    for r in results:
        print(f"  {r['name']:>4} {r['trades']:>7} {r['wr']:>5.1f}% {r['pf']:>7.2f} "
              f"{r['avg_r']:>7.2f}R {r['maxdd']:>6.2f}% {r['sharpe']:>7.2f} "
              f"${r['pnl']:>11.2f} {r['elapsed']:>4.0f}s")
    # Highlight best by PF (min 20 trades)
    valid = [r for r in results if r['trades'] >= 20]
    if valid:
        best = max(valid, key=lambda r: r['pf'])
        print(f"\n  → Best: {best['name']} (PF={best['pf']:.2f}, {best['trades']} trades, P&L=${best['pnl']:.2f})")
    return valid


def main():
    print("=" * 90)
    print("PHASE 2.2 REDO — Parameter Re-optimization (Corrected Codebase)")
    print("=" * 90)
    print(f"Tickers: {', '.join(TICKERS)}")
    print(f"Period: {START} to {END}")
    print(f"Direction: BOTH (no filter)")
    print(f"All params start from DEFAULT, vary ONE at a time")

    m5_df = load_data()
    print(f"Loaded {len(m5_df)} bars\n")

    all_results = {}

    # ═══════════════════════════════════════════════════════════════════
    # EXPERIMENT 1: ATR Sensitivity
    # ═══════════════════════════════════════════════════════════════════
    print("\n>>> EXPERIMENT 1: ATR Sensitivity")
    exp1 = []
    for name, entry, block in [
        ('A', 0.80, 0.30), ('B', 0.70, 0.25), ('C', 0.60, 0.20),
        ('D', 0.50, 0.15), ('E', 0.40, 0.10),
    ]:
        r = run_one(name, m5_df, {'atr_entry_threshold': entry, 'atr_block_threshold': block})
        exp1.append(r)
        print(f"  {name}: {r['trades']} trades, PF={r['pf']:.2f}, P&L=${r['pnl']:.2f}")
    valid1 = print_table("EXPERIMENT 1: ATR Sensitivity", exp1)
    best_atr = max(valid1, key=lambda r: r['pf']) if valid1 else exp1[1]
    # Extract ATR params from best
    atr_map = {'A': (0.80, 0.30), 'B': (0.70, 0.25), 'C': (0.60, 0.20),
               'D': (0.50, 0.15), 'E': (0.40, 0.10)}
    best_entry, best_block = atr_map[best_atr['name']]
    all_results['exp1'] = exp1

    # ═══════════════════════════════════════════════════════════════════
    # EXPERIMENT 2: Fractal Depth
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n>>> EXPERIMENT 2: Fractal Depth (ATR: entry={best_entry}, block={best_block})")
    exp2 = []
    for name, fd in [('F', 3), ('G', 5), ('H', 7), ('I', 10)]:
        r = run_one(name, m5_df, {
            'atr_entry_threshold': best_entry, 'atr_block_threshold': best_block,
            'fractal_depth': fd,
        })
        exp2.append(r)
        print(f"  {name}: {r['trades']} trades, PF={r['pf']:.2f}, P&L=${r['pnl']:.2f}")
    valid2 = print_table("EXPERIMENT 2: Fractal Depth", exp2)
    best_fd_r = max(valid2, key=lambda r: r['pf']) if valid2 else exp2[1]
    fd_map = {'F': 3, 'G': 5, 'H': 7, 'I': 10}
    best_fd = fd_map[best_fd_r['name']]
    all_results['exp2'] = exp2

    # ═══════════════════════════════════════════════════════════════════
    # EXPERIMENT 3: Sawing
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n>>> EXPERIMENT 3: Sawing (ATR: {best_entry}/{best_block}, FD={best_fd})")
    exp3 = []
    for name, thresh, window in [
        ('J', 3, 20), ('K', 4, 25), ('L', 5, 30), ('M', 6, 30), ('N', 999, 20),
    ]:
        r = run_one(name, m5_df, {
            'atr_entry_threshold': best_entry, 'atr_block_threshold': best_block,
            'fractal_depth': best_fd,
            'cross_count_invalidate': thresh, 'cross_count_window': window,
        })
        exp3.append(r)
        print(f"  {name}: {r['trades']} trades, PF={r['pf']:.2f}, P&L=${r['pnl']:.2f}")
    valid3 = print_table("EXPERIMENT 3: Sawing", exp3)
    best_saw_r = max(valid3, key=lambda r: r['pf']) if valid3 else exp3[2]
    saw_map = {'J': (3, 20), 'K': (4, 25), 'L': (5, 30), 'M': (6, 30), 'N': (999, 20)}
    best_saw_thresh, best_saw_window = saw_map[best_saw_r['name']]
    all_results['exp3'] = exp3

    # ═══════════════════════════════════════════════════════════════════
    # EXPERIMENT 4: Risk/Stop
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n>>> EXPERIMENT 4: Risk/Stop (ATR: {best_entry}/{best_block}, FD={best_fd}, SAW={best_saw_thresh}/{best_saw_window})")
    exp4 = []
    for name, msp, mrr in [
        ('O', 0.10, 3.0), ('P', 0.15, 3.0), ('Q', 0.20, 3.0),
        ('R', 0.15, 2.5), ('S', 0.15, 2.0),
    ]:
        r = run_one(name, m5_df, {
            'atr_entry_threshold': best_entry, 'atr_block_threshold': best_block,
            'fractal_depth': best_fd,
            'cross_count_invalidate': best_saw_thresh, 'cross_count_window': best_saw_window,
            'max_stop_atr_pct': msp, 'min_rr': mrr,
        })
        exp4.append(r)
        print(f"  {name}: {r['trades']} trades, PF={r['pf']:.2f}, P&L=${r['pnl']:.2f}")
    valid4 = print_table("EXPERIMENT 4: Risk/Stop", exp4)
    best_risk_r = max(valid4, key=lambda r: r['pf']) if valid4 else exp4[0]
    risk_map = {'O': (0.10, 3.0), 'P': (0.15, 3.0), 'Q': (0.20, 3.0),
                'R': (0.15, 2.5), 'S': (0.15, 2.0)}
    best_msp, best_mrr = risk_map[best_risk_r['name']]
    all_results['exp4'] = exp4

    # ═══════════════════════════════════════════════════════════════════
    # EXPERIMENT 5: Tail Ratio + CLP
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n>>> EXPERIMENT 5: Tail/CLP (best structural: ATR={best_entry}/{best_block}, "
          f"FD={best_fd}, SAW={best_saw_thresh}/{best_saw_window}, "
          f"STOP={best_msp}, RR={best_mrr})")
    exp5 = []
    for name, tail, clp_min in [('T', 0.10, 3), ('U', 0.15, 3), ('V', 0.20, 3), ('W', 0.15, 2)]:
        r = run_one(name, m5_df, {
            'atr_entry_threshold': best_entry, 'atr_block_threshold': best_block,
            'fractal_depth': best_fd,
            'cross_count_invalidate': best_saw_thresh, 'cross_count_window': best_saw_window,
            'max_stop_atr_pct': best_msp, 'min_rr': best_mrr,
            'tail_ratio_min': tail, 'clp_min_bars': clp_min,
        })
        exp5.append(r)
        print(f"  {name}: {r['trades']} trades, PF={r['pf']:.2f}, P&L=${r['pnl']:.2f}")
    valid5 = print_table("EXPERIMENT 5: Tail Ratio + CLP", exp5)
    best_tail_r = max(valid5, key=lambda r: r['pf']) if valid5 else exp5[1]
    tail_map = {'T': (0.10, 3), 'U': (0.15, 3), 'V': (0.20, 3), 'W': (0.15, 2)}
    best_tail, best_clp_min = tail_map[best_tail_r['name']]
    all_results['exp5'] = exp5

    # ═══════════════════════════════════════════════════════════════════
    # FINAL: RECOMMENDED CONFIG
    # ═══════════════════════════════════════════════════════════════════
    print("\n\n" + "=" * 90)
    print("  RECOMMENDED CONFIG")
    print("=" * 90)
    final_overrides = {
        'atr_entry_threshold': best_entry,
        'atr_block_threshold': best_block,
        'fractal_depth': best_fd,
        'cross_count_invalidate': best_saw_thresh,
        'cross_count_window': best_saw_window,
        'max_stop_atr_pct': best_msp,
        'min_rr': best_mrr,
        'tail_ratio_min': best_tail,
        'clp_min_bars': best_clp_min,
    }
    print(f"\n  Parameters:")
    for k, v in sorted(final_overrides.items()):
        d = DEFAULT.get(k, '?')
        changed = " *** CHANGED" if v != d else ""
        print(f"    {k:>30}: {v}{changed}")

    print(f"\n  Winner path: Exp1→{best_atr['name']} Exp2→{best_fd_r['name']} "
          f"Exp3→{best_saw_r['name']} Exp4→{best_risk_r['name']} Exp5→{best_tail_r['name']}")

    # Full report with final config
    print(f"\n\n>>> FINAL BACKTEST — Recommended Config")
    final = run_one('FINAL', m5_df, final_overrides)
    print_table("FINAL RECOMMENDED CONFIG", [final])

    # Per-ticker breakdown
    cfg = build_config('FINAL', final_overrides)
    bt = Backtester(cfg)
    result = bt.run(m5_df, start_date=START, end_date=END)
    trades = result.trades
    p = result.performance

    from collections import defaultdict
    from backtester.data_types import ExitReason, PatternType, SignalDirection

    print(f"\n  Per-Ticker:")
    print(f"  {'Ticker':>6} {'Trades':>7} {'W':>4} {'L':>4} {'WR%':>6} {'PF':>7} {'P&L':>12}")
    print(f"  {'-'*55}")
    for ticker in TICKERS:
        tt = [t for t in trades if t.signal.ticker == ticker]
        if not tt:
            print(f"  {ticker:>6} {'0':>7}")
            continue
        w = sum(1 for t in tt if t.pnl > 0)
        l = sum(1 for t in tt if t.pnl <= 0)
        wr = w / len(tt) * 100
        gp = sum(t.pnl for t in tt if t.pnl > 0)
        gl = abs(sum(t.pnl for t in tt if t.pnl < 0))
        pf = gp / gl if gl > 0 else float('inf') if gp > 0 else 0
        pnl = sum(t.pnl for t in tt)
        print(f"  {ticker:>6} {len(tt):>7} {w:>4} {l:>4} {wr:>5.1f}% {pf:>7.2f} ${pnl:>11.2f}")

    print(f"\n  Exit Reasons:")
    exit_counts = defaultdict(lambda: {'count': 0, 'pnl': 0.0})
    for t in trades:
        reason = t.exit_reason.value if t.exit_reason else 'unknown'
        exit_counts[reason]['count'] += 1
        exit_counts[reason]['pnl'] += t.pnl
    print(f"  {'Reason':>16} {'Count':>6} {'%':>6} {'P&L':>12}")
    print(f"  {'-'*45}")
    for reason in ['stop_loss', 'target_hit', 'trail_stop', 'breakeven_stop',
                    'nison_exit', 'eod_exit']:
        d = exit_counts.get(reason, {'count': 0, 'pnl': 0.0})
        if d['count'] == 0:
            continue
        pct = d['count'] / len(trades) * 100
        print(f"  {reason:>16} {d['count']:>6} {pct:>5.1f}% ${d['pnl']:>11.2f}")

    print(f"\n  Per-Pattern:")
    for pat in [PatternType.LP1, PatternType.LP2, PatternType.CLP]:
        pt = [t for t in trades if t.signal.pattern == pat]
        if not pt:
            continue
        w = sum(1 for t in pt if t.pnl > 0)
        gp = sum(t.pnl for t in pt if t.pnl > 0)
        gl = abs(sum(t.pnl for t in pt if t.pnl < 0))
        pf = gp / gl if gl > 0 else float('inf') if gp > 0 else 0
        pnl = sum(t.pnl for t in pt)
        print(f"  {pat.value:>8} {len(pt):>5} trades, {w:>3}W, PF={pf:.2f}, P&L=${pnl:.2f}")

    print(f"\n  Signals blocked: {bt.signals_blocked}")

    print("\n" + "=" * 90)
    print("DONE")
    print("=" * 90)


if __name__ == '__main__':
    main()
