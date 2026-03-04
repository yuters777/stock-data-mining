"""
Full Audit Backtest: All fixes applied (Nison + CLP + Mirror lifecycle).
Phase 2.2 optimized params. 6-ticker portfolio.
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
from backtester.core.trade_manager import TradeManagerConfig, Trade
from backtester.data_types import LevelStatus, ExitReason, PatternType, SignalDirection
from backtester.analyzer import Analyzer


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
TICKERS = ['TSLA', 'AMZN', 'GOOGL', 'META', 'MSFT', 'NVDA']

config = BacktestConfig(
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
    risk_config=RiskManagerConfig(
        min_rr=3.0,
        max_stop_atr_pct=0.10,
        capital=100000.0,
        risk_pct=0.003,
    ),
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
    direction_filter={'TSLA': 'long', 'DEFAULT': 'short'},
    name="all_fixes_p2.2",
)


def load_all_tickers():
    frames = []
    for ticker in TICKERS:
        path = os.path.join(DATA_DIR, f'{ticker}_data.csv')
        if not os.path.exists(path):
            print(f"  SKIP: {path} not found")
            continue
        df = pd.read_csv(path)
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        df = df.sort_values('Datetime').reset_index(drop=True)
        frames.append(df)
        print(f"  Loaded {ticker}: {len(df)} bars")
    return pd.concat(frames, ignore_index=True).sort_values(
        ['Ticker', 'Datetime']).reset_index(drop=True)


def count_level_invalidations(backtester):
    stats = defaultdict(int)
    for lvl in backtester.levels:
        stats['total'] += 1
        if lvl.status == LevelStatus.ACTIVE:
            stats['active'] += 1
        elif lvl.status == LevelStatus.BROKEN:
            stats['broken'] += 1
        elif lvl.status == LevelStatus.MIRROR_CANDIDATE:
            stats['mirror_candidate'] += 1
        elif lvl.status == LevelStatus.MIRROR_CONFIRMED:
            stats['mirror_confirmed'] += 1
        elif lvl.status == LevelStatus.INVALIDATED:
            if lvl.cross_count >= backtester.config.level_config.cross_count_invalidate:
                stats['inv_sawing'] += 1
            elif lvl.mirror_breakout_side:
                stats['inv_nison'] += 1
            else:
                stats['inv_other'] += 1
    stats['surviving'] = stats['active'] + stats['broken'] + stats['mirror_candidate'] + stats['mirror_confirmed']
    stats['inv_total'] = stats['inv_sawing'] + stats['inv_nison'] + stats['inv_other']
    return stats


def calc_pf(trades):
    gross_p = sum(t.pnl for t in trades if t.pnl > 0)
    gross_l = abs(sum(t.pnl for t in trades if t.pnl < 0))
    return gross_p / gross_l if gross_l > 0 else float('inf') if gross_p > 0 else 0.0


def main():
    print("=" * 80)
    print("FULL AUDIT BACKTEST — All Fixes Applied — Phase 2.2 Params")
    print("=" * 80)
    print(f"\nFixes: Nison 3-step, CLP MaxDev→CLOSE, CLP trigger gate, Mirror CLOSE+BPU")
    print(f"Params: FD=5, ATR_ENTRY=0.70, ATR_BLOCK=0.25, SAWING=5/30, TAIL=0.15, RR=3.0")
    print(f"Direction: TSLA=long, others=short")
    print(f"Tickers: {', '.join(TICKERS)}")

    start_date = '2025-02-10'
    end_date = '2026-02-01'
    print(f"Period: {start_date} to {end_date}")

    print(f"\nLoading data...")
    m5_df = load_all_tickers()
    print(f"Total M5 bars: {len(m5_df)}")

    print(f"\nRunning backtest...")
    backtester = Backtester(config)
    result = backtester.run(m5_df, start_date=start_date, end_date=end_date)
    result.performance['proximity_events'] = backtester.proximity_events
    trades = result.trades
    p = result.performance

    # ═══════════════════════════════════════════════════════════════════════
    # 1. LEVELS
    # ═══════════════════════════════════════════════════════════════════════
    print("\n\n" + "=" * 80)
    print("1. LEVEL BREAKDOWN")
    print("=" * 80)

    ls = count_level_invalidations(backtester)
    print(f"""
  Total levels detected:       {ls['total']}
  ├─ Active:                   {ls['active']}
  ├─ Broken:                   {ls['broken']}
  ├─ Mirror Candidate:         {ls['mirror_candidate']}
  ├─ Mirror Confirmed:         {ls['mirror_confirmed']}
  ├─ Invalidated (sawing):     {ls['inv_sawing']}
  ├─ Invalidated (Nison):      {ls['inv_nison']}
  └─ Invalidated (other):      {ls['inv_other']}

  Surviving:                   {ls['surviving']} ({ls['surviving']/max(ls['total'],1)*100:.1f}%)
  Invalidated:                 {ls['inv_total']} ({ls['inv_total']/max(ls['total'],1)*100:.1f}%)
  Nison kill rate:             {ls['inv_nison']/max(ls['total'],1)*100:.1f}%""")

    print(f"\n  Per-ticker:")
    print(f"  {'Ticker':>6} {'Total':>6} {'Mirror':>7} {'Sawing':>7} {'Nison':>6} {'Surv':>6}")
    print(f"  {'-'*40}")
    for ticker in TICKERS:
        tl = [l for l in backtester.levels if l.ticker == ticker]
        tm = sum(1 for l in tl if l.is_mirror)
        ts = sum(1 for l in tl if l.status == LevelStatus.INVALIDATED
                 and l.cross_count >= backtester.config.level_config.cross_count_invalidate)
        tn = sum(1 for l in tl if l.status == LevelStatus.INVALIDATED
                 and l.mirror_breakout_side
                 and l.cross_count < backtester.config.level_config.cross_count_invalidate)
        surv = len(tl) - sum(1 for l in tl if l.status == LevelStatus.INVALIDATED)
        print(f"  {ticker:>6} {len(tl):>6} {tm:>7} {ts:>7} {tn:>6} {surv:>6}")

    # ═══════════════════════════════════════════════════════════════════════
    # 2. SIGNAL FUNNEL
    # ═══════════════════════════════════════════════════════════════════════
    print("\n\n" + "=" * 80)
    print("2. SIGNAL FUNNEL")
    print("=" * 80)
    print(Analyzer.signal_funnel_report(result))

    # Direction filter blocked (not in standard funnel)
    dir_blocked = backtester.signals_blocked.get('direction_filter', 0)
    rr_blocked = backtester.signals_blocked.get('risk_rr', 0)
    pos_blocked = backtester.signals_blocked.get('position_limit', 0)
    print(f"\n  Additional blocks (pre-filter-chain):")
    print(f"    Direction filter:          {dir_blocked}")
    print(f"    Risk R:R < min:            {rr_blocked}")
    print(f"    Position limit:            {pos_blocked}")

    # ═══════════════════════════════════════════════════════════════════════
    # 3. PERFORMANCE
    # ═══════════════════════════════════════════════════════════════════════
    print("\n\n" + "=" * 80)
    print("3. PERFORMANCE")
    print("=" * 80)
    print(Analyzer.performance_report(result))

    # ═══════════════════════════════════════════════════════════════════════
    # 4. PER-TICKER BREAKDOWN
    # ═══════════════════════════════════════════════════════════════════════
    print("\n\n" + "=" * 80)
    print("4. PER-TICKER BREAKDOWN")
    print("=" * 80)
    print(f"\n  {'Ticker':>6} {'Dir':>5} {'Trades':>7} {'W':>4} {'L':>4} {'WR%':>6} {'PF':>7} {'P&L':>10}")
    print(f"  {'-'*55}")
    for ticker in TICKERS:
        tt = [t for t in trades if t.signal.ticker == ticker]
        if not tt:
            d = config.direction_filter.get(ticker, config.direction_filter.get('DEFAULT', '?'))
            print(f"  {ticker:>6} {d:>5} {'0':>7} {'-':>4} {'-':>4} {'-':>6} {'-':>7} {'$0.00':>10}")
            continue
        w = sum(1 for t in tt if t.pnl > 0)
        l = sum(1 for t in tt if t.pnl <= 0)
        wr = w / len(tt) * 100
        pf = calc_pf(tt)
        pnl = sum(t.pnl for t in tt)
        d = 'L' if tt[0].direction == SignalDirection.LONG else 'S'
        print(f"  {ticker:>6} {d:>5} {len(tt):>7} {w:>4} {l:>4} {wr:>5.1f}% {pf:>7.2f} ${pnl:>9.2f}")

    total_pnl = sum(t.pnl for t in trades)
    total_w = sum(1 for t in trades if t.pnl > 0)
    total_l = sum(1 for t in trades if t.pnl <= 0)
    print(f"  {'-'*55}")
    print(f"  {'TOTAL':>6} {'':>5} {len(trades):>7} {total_w:>4} {total_l:>4} "
          f"{total_w/max(len(trades),1)*100:>5.1f}% {calc_pf(trades):>7.2f} ${total_pnl:>9.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 5. PER-PATTERN BREAKDOWN
    # ═══════════════════════════════════════════════════════════════════════
    print("\n\n" + "=" * 80)
    print("5. PER-PATTERN BREAKDOWN")
    print("=" * 80)
    print(f"\n  {'Pattern':>8} {'Trades':>7} {'W':>4} {'L':>4} {'WR%':>6} {'PF':>7} {'P&L':>10} {'AvgR':>6}")
    print(f"  {'-'*55}")
    for pat in [PatternType.LP1, PatternType.LP2, PatternType.CLP]:
        pt = [t for t in trades if t.signal.pattern == pat]
        if not pt:
            print(f"  {pat.value:>8} {'0':>7}")
            continue
        w = sum(1 for t in pt if t.pnl > 0)
        l = sum(1 for t in pt if t.pnl <= 0)
        wr = w / len(pt) * 100
        pf = calc_pf(pt)
        pnl = sum(t.pnl for t in pt)
        avg_r = np.mean([t.pnl_r for t in pt])
        print(f"  {pat.value:>8} {len(pt):>7} {w:>4} {l:>4} {wr:>5.1f}% {pf:>7.2f} ${pnl:>9.2f} {avg_r:>5.2f}R")

    # Check for Model4
    m4 = [t for t in trades if t.signal.pattern == PatternType.MODEL4]
    if m4:
        w = sum(1 for t in m4 if t.pnl > 0)
        l = sum(1 for t in m4 if t.pnl <= 0)
        pf = calc_pf(m4)
        pnl = sum(t.pnl for t in m4)
        avg_r = np.mean([t.pnl_r for t in m4])
        print(f"  {'model4':>8} {len(m4):>7} {w:>4} {l:>4} "
              f"{w/len(m4)*100:>5.1f}% {pf:>7.2f} ${pnl:>9.2f} {avg_r:>5.2f}R")

    # ═══════════════════════════════════════════════════════════════════════
    # 6. EXIT REASONS
    # ═══════════════════════════════════════════════════════════════════════
    print("\n\n" + "=" * 80)
    print("6. EXIT REASONS BREAKDOWN")
    print("=" * 80)
    exit_counts = defaultdict(lambda: {'count': 0, 'pnl': 0.0, 'winners': 0})
    for t in trades:
        reason = t.exit_reason.value if t.exit_reason else 'unknown'
        exit_counts[reason]['count'] += 1
        exit_counts[reason]['pnl'] += t.pnl
        if t.pnl > 0:
            exit_counts[reason]['winners'] += 1

    print(f"\n  {'Reason':>16} {'Count':>6} {'%':>6} {'Winners':>8} {'P&L':>12} {'Avg P&L':>10}")
    print(f"  {'-'*60}")
    for reason in ['stop_loss', 'target_hit', 'trail_stop', 'nison_exit',
                    'eod_exit', 'breakeven_stop', 'partial_tp', 'circuit_breaker']:
        d = exit_counts.get(reason, {'count': 0, 'pnl': 0.0, 'winners': 0})
        if d['count'] == 0:
            continue
        pct = d['count'] / len(trades) * 100
        avg = d['pnl'] / d['count']
        print(f"  {reason:>16} {d['count']:>6} {pct:>5.1f}% {d['winners']:>8} ${d['pnl']:>11.2f} ${avg:>9.2f}")

    # ═══════════════════════════════════════════════════════════════════════
    # 7. COMPARISON TO PRE-FIX RUN
    # ═══════════════════════════════════════════════════════════════════════
    print("\n\n" + "=" * 80)
    print("7. COMPARISON — Pre-Fix (Nison only) vs All Fixes")
    print("=" * 80)
    prev = {
        'trades': 171, 'pf': 1.23, 'wr': 33.3, 'pnl': 7716.51,
        'sharpe': 1.31, 'dd': 5.84, 'avg_winner': 729.21, 'avg_loser': -296.92,
    }
    curr = {
        'trades': p.get('total_trades', 0),
        'pf': p.get('profit_factor', 0),
        'wr': p.get('win_rate', 0) * 100,
        'pnl': p.get('total_pnl', 0),
        'sharpe': p.get('sharpe', 0),
        'dd': p.get('max_drawdown_pct', 0),
        'avg_winner': p.get('avg_winner', 0),
        'avg_loser': p.get('avg_loser', 0),
    }

    print(f"\n  {'Metric':>18} {'Pre-Fix':>12} {'All-Fix':>12} {'Delta':>12}")
    print(f"  {'-'*56}")
    for label, key, fmt in [
        ('Trades', 'trades', 'd'),
        ('Win Rate', 'wr', '.1f'),
        ('Profit Factor', 'pf', '.2f'),
        ('Total P&L', 'pnl', '.2f'),
        ('Sharpe', 'sharpe', '.2f'),
        ('Max DD %', 'dd', '.2f'),
        ('Avg Winner', 'avg_winner', '.2f'),
        ('Avg Loser', 'avg_loser', '.2f'),
    ]:
        pv = prev[key]
        cv = curr[key]
        delta = cv - pv
        if fmt == 'd':
            print(f"  {label:>18} {pv:>12d} {cv:>12d} {delta:>+12d}")
        elif label in ('Total P&L', 'Avg Winner', 'Avg Loser'):
            print(f"  {label:>18} ${pv:>11{fmt}} ${cv:>11{fmt}} ${delta:>+11{fmt}}")
        elif label == 'Win Rate' or label == 'Max DD %':
            print(f"  {label:>18} {pv:>11{fmt}}% {cv:>11{fmt}}% {delta:>+11{fmt}}%")
        else:
            print(f"  {label:>18} {pv:>12{fmt}} {cv:>12{fmt}} {delta:>+12{fmt}}")

    # ═══════════════════════════════════════════════════════════════════════
    # TRADE LIST (compact)
    # ═══════════════════════════════════════════════════════════════════════
    if trades:
        print("\n\n" + "=" * 80)
        print("TRADE LIST")
        print("=" * 80)
        print(Analyzer.trade_list_report(result))

    print("\n" + "=" * 80)
    print("DONE")
    print("=" * 80)
    return result


if __name__ == '__main__':
    result = main()
