"""
Deep analysis of Walk-Forward Window 6 (Oct 10 – Nov 10 2025).

Compares W5 (best) vs W6 (worst) and runs fixed-params comparison.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from collections import defaultdict

from backtester.backtester import Backtester, BacktestConfig
from backtester.core.level_detector import LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngineConfig
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
TICKERS = ['TSLA', 'AMZN', 'GOOGL', 'META', 'MSFT', 'NVDA']

# Window definitions
W5 = {'train_start': '2025-06-10', 'train_end': '2025-09-10',
      'test_start': '2025-09-10', 'test_end': '2025-10-10'}
W6 = {'train_start': '2025-07-10', 'train_end': '2025-10-10',
      'test_start': '2025-10-10', 'test_end': '2025-11-10'}

# Best IS params selected by walk-forward for each window
W5_PARAMS = {
    'atr_entry_threshold': 0.6,
    'fractal_depth': 10,
    'max_stop_atr_pct': 0.1,
    'min_rr': 2.0,
    'tail_ratio_min': 0.2,
}
W6_PARAMS = {
    'atr_entry_threshold': 0.6,
    'fractal_depth': 10,
    'max_stop_atr_pct': 0.1,
    'min_rr': 2.0,
    'tail_ratio_min': 0.1,
}

# Baseline defaults (same as run_walkforward.py)
BASELINE = dict(
    fractal_depth=5, tolerance_cents=0.05, tolerance_pct=0.001,
    atr_period=5, min_level_score=5, cross_count_invalidate=5,
    cross_count_window=30, tail_ratio_min=0.15, lp2_engulfing_required=True,
    clp_min_bars=3, clp_max_bars=7, atr_block_threshold=0.25,
    atr_entry_threshold=0.70, max_stop_atr_pct=0.10, min_rr=3.0,
    capital=100000.0, risk_pct=0.003, tier_mode='2tier_trail',
    t1_pct=0.30, trail_factor=0.7, trail_activation_r=0.0, tier_min_rr=1.5,
)

# All 6 windows for the fixed-params comparison
ALL_WINDOWS = [
    {'test_start': '2025-05-10', 'test_end': '2025-06-10'},
    {'test_start': '2025-06-10', 'test_end': '2025-07-10'},
    {'test_start': '2025-07-10', 'test_end': '2025-08-10'},
    {'test_start': '2025-08-10', 'test_end': '2025-09-10'},
    {'test_start': '2025-09-10', 'test_end': '2025-10-10'},
    {'test_start': '2025-10-10', 'test_end': '2025-11-10'},
]


def build_config(name, overrides=None):
    p = {**BASELINE, **(overrides or {})}
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
        direction_filter=None,
        name=name,
    )


def load_all_data():
    data = {}
    for ticker in TICKERS:
        path = os.path.join(DATA_DIR, f'{ticker}_data.csv')
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path)
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        df = df.sort_values('Datetime').reset_index(drop=True)
        data[ticker] = df
    return data


def run_with_trades(config, ticker_data, start_date, end_date):
    """Run backtest, return list of all Trade objects with ticker attached."""
    all_trades = []
    for ticker, m5_df in ticker_data.items():
        bt = Backtester(config)
        result = bt.run(m5_df, start_date=start_date, end_date=end_date)
        for t in result.trades:
            t.sector = ticker  # reuse sector field for ticker
        all_trades.extend(result.trades)
    return all_trades


def print_trade_log(trades, label):
    """Print detailed trade log."""
    print(f"\n{'=' * 120}")
    print(f"  {label} — {len(trades)} TRADES")
    print(f"{'=' * 120}")

    if not trades:
        print("  No trades.")
        return

    # Sort by entry time
    trades_sorted = sorted(trades, key=lambda t: t.entry_time if t.entry_time else pd.Timestamp.min)

    print(f"  {'#':>3} {'Ticker':>6} {'Dir':>5} {'Pattern':>5} {'LvlScr':>6} "
          f"{'Entry':>9} {'Stop':>9} {'Target':>9} {'Exit':>9} "
          f"{'ExitReason':>15} {'P&L':>10} {'R':>6} {'W/L':>3}")
    print(f"  {'─' * 115}")

    cum_pnl = 0
    consecutive_losses = 0
    max_consecutive_losses = 0
    loss_streak_pnl = 0
    worst_streak_pnl = 0

    for i, t in enumerate(trades_sorted):
        ticker = t.sector or '?'
        direction = t.direction.value if t.direction else '?'
        pattern = t.signal.pattern.value if t.signal and t.signal.pattern else '?'
        level_score = t.signal.level.score if t.signal and t.signal.level else 0
        entry = t.entry_price
        stop = t.stop_price
        target = t.target_price
        exit_p = t.exit_price
        exit_reason = t.exit_reason.value if t.exit_reason else '?'
        pnl = t.pnl
        pnl_r = t.pnl_r
        wl = 'W' if pnl > 0 else 'L'
        cum_pnl += pnl

        if pnl <= 0:
            consecutive_losses += 1
            loss_streak_pnl += pnl
            if consecutive_losses > max_consecutive_losses:
                max_consecutive_losses = consecutive_losses
            if loss_streak_pnl < worst_streak_pnl:
                worst_streak_pnl = loss_streak_pnl
        else:
            consecutive_losses = 0
            loss_streak_pnl = 0

        entry_time = t.entry_time.strftime('%m/%d %H:%M') if t.entry_time else '?'

        print(f"  {i+1:>3} {ticker:>6} {direction:>5} {pattern:>5} {level_score:>6} "
              f"${entry:>8.2f} ${stop:>8.2f} ${target:>8.2f} ${exit_p:>8.2f} "
              f"{exit_reason:>15} ${pnl:>9.2f} {pnl_r:>5.2f}R {wl:>3}")

    print(f"  {'─' * 115}")
    print(f"  Cumulative P&L: ${cum_pnl:,.2f}")
    print(f"  Max consecutive losses: {max_consecutive_losses}")
    print(f"  Worst loss streak P&L: ${worst_streak_pnl:,.2f}")

    return max_consecutive_losses, worst_streak_pnl


def analyze_by_ticker(trades, label):
    """Break down by ticker."""
    print(f"\n  {label} — BY TICKER:")
    by_ticker = defaultdict(list)
    for t in trades:
        by_ticker[t.sector or '?'].append(t)

    print(f"  {'Ticker':>8} {'Trades':>6} {'Winners':>7} {'WR':>6} {'PF':>6} "
          f"{'P&L':>10} {'AvgR':>6}")
    print(f"  {'─' * 55}")

    for ticker in sorted(by_ticker.keys()):
        tt = by_ticker[ticker]
        n = len(tt)
        winners = [t for t in tt if t.pnl > 0]
        losers = [t for t in tt if t.pnl <= 0]
        wr = len(winners) / n if n > 0 else 0
        gp = sum(t.pnl for t in winners)
        gl = abs(sum(t.pnl for t in losers))
        pf = gp / gl if gl > 0 else (float('inf') if gp > 0 else 0)
        total_pnl = sum(t.pnl for t in tt)
        avg_r = np.mean([t.pnl_r for t in tt]) if tt else 0

        print(f"  {ticker:>8} {n:>6} {len(winners):>7} {wr*100:>5.1f}% {pf:>6.2f} "
              f"${total_pnl:>9.2f} {avg_r:>5.2f}R")


def analyze_by_pattern(trades, label):
    """Break down by pattern type."""
    print(f"\n  {label} — BY PATTERN:")
    by_pattern = defaultdict(list)
    for t in trades:
        pat = t.signal.pattern.value if t.signal and t.signal.pattern else '?'
        by_pattern[pat].append(t)

    print(f"  {'Pattern':>8} {'Trades':>6} {'Winners':>7} {'WR':>6} {'PF':>6} {'P&L':>10}")
    print(f"  {'─' * 45}")

    for pat in sorted(by_pattern.keys()):
        tt = by_pattern[pat]
        n = len(tt)
        winners = [t for t in tt if t.pnl > 0]
        losers = [t for t in tt if t.pnl <= 0]
        wr = len(winners) / n if n > 0 else 0
        gp = sum(t.pnl for t in winners)
        gl = abs(sum(t.pnl for t in losers))
        pf = gp / gl if gl > 0 else (float('inf') if gp > 0 else 0)
        total_pnl = sum(t.pnl for t in tt)

        print(f"  {pat:>8} {n:>6} {len(winners):>7} {wr*100:>5.1f}% {pf:>6.2f} ${total_pnl:>9.2f}")


def analyze_by_exit_reason(trades, label):
    """Break down by exit reason."""
    print(f"\n  {label} — BY EXIT REASON:")
    by_reason = defaultdict(list)
    for t in trades:
        reason = t.exit_reason.value if t.exit_reason else '?'
        by_reason[reason].append(t)

    print(f"  {'Exit Reason':>18} {'Count':>6} {'P&L':>10} {'AvgR':>6}")
    print(f"  {'─' * 45}")

    for reason in sorted(by_reason.keys()):
        tt = by_reason[reason]
        total_pnl = sum(t.pnl for t in tt)
        avg_r = np.mean([t.pnl_r for t in tt]) if tt else 0
        print(f"  {reason:>18} {len(tt):>6} ${total_pnl:>9.2f} {avg_r:>5.2f}R")


def analyze_levels(trades, label):
    """Check for same-level repeats."""
    print(f"\n  {label} — LEVEL ANALYSIS:")
    level_trades = defaultdict(list)
    for t in trades:
        if t.signal and t.signal.level:
            key = f"{t.sector}_{t.signal.level.price:.2f}_{t.signal.level.level_type.value}"
            level_trades[key].append(t)

    repeat_levels = {k: v for k, v in level_trades.items() if len(v) > 1}
    print(f"  Total unique levels traded: {len(level_trades)}")
    print(f"  Levels traded multiple times: {len(repeat_levels)}")

    if repeat_levels:
        print(f"\n  Repeated levels:")
        for key in sorted(repeat_levels.keys(), key=lambda k: len(repeat_levels[k]), reverse=True):
            tt = repeat_levels[key]
            total_pnl = sum(t.pnl for t in tt)
            print(f"    {key}: {len(tt)} trades, P&L=${total_pnl:.2f} "
                  f"[{', '.join(('W' if t.pnl > 0 else 'L') for t in tt)}]")


def analyze_market_regime(ticker_data, period_start, period_end, label):
    """Analyze market regime: ATR, trend, volatility."""
    print(f"\n  {label} — MARKET REGIME ({period_start} → {period_end}):")
    print(f"  {'Ticker':>8} {'ATR_D1':>8} {'Move%':>8} {'Direction':>10} {'StartPx':>9} {'EndPx':>9}")
    print(f"  {'─' * 60}")

    for ticker in sorted(ticker_data.keys()):
        m5_df = ticker_data[ticker]
        mask = (m5_df['Datetime'] >= period_start) & (m5_df['Datetime'] < period_end)
        period_df = m5_df[mask]

        if period_df.empty:
            continue

        # Build daily bars
        daily_rows = []
        for date, group in period_df.groupby(period_df['Datetime'].dt.date):
            daily_rows.append({
                'Date': date,
                'Open': group['Open'].iloc[0],
                'High': group['High'].max(),
                'Low': group['Low'].min(),
                'Close': group['Close'].iloc[-1],
            })

        if not daily_rows:
            continue

        daily = pd.DataFrame(daily_rows)
        daily['TR'] = daily['High'] - daily['Low']
        atr_d1 = daily['TR'].mean()

        start_px = daily['Open'].iloc[0]
        end_px = daily['Close'].iloc[-1]
        move_pct = (end_px - start_px) / start_px * 100

        direction = "BULLISH" if move_pct > 2 else ("BEARISH" if move_pct < -2 else "RANGING")

        print(f"  {ticker:>8} ${atr_d1:>7.2f} {move_pct:>7.1f}% {direction:>10} "
              f"${start_px:>8.2f} ${end_px:>8.2f}")


def run_fixed_params_all_windows(ticker_data, fixed_params, label):
    """Run the SAME params across ALL 6 windows."""
    print(f"\n{'=' * 90}")
    print(f"  FIXED-PARAMS COMPARISON: {label}")
    print(f"  Params: {fixed_params}")
    print(f"{'=' * 90}")

    config = build_config("fixed", fixed_params)

    print(f"\n  {'Win':>4} {'Test Period':>25} {'Trades':>6} {'WR':>6} "
          f"{'PF':>6} {'P&L':>10} {'Sharpe':>7}")
    print(f"  {'─' * 70}")

    total_pnl = 0
    total_trades = 0

    for i, w in enumerate(ALL_WINDOWS):
        trades = run_with_trades(config, ticker_data,
                                 w['test_start'], w['test_end'])
        n = len(trades)
        total_trades += n

        if n == 0:
            print(f"  W{i+1:>2}  {w['test_start']}→{w['test_end']}  {0:>5}    —      —          —       —")
            continue

        winners = [t for t in trades if t.pnl > 0]
        losers = [t for t in trades if t.pnl <= 0]
        wr = len(winners) / n
        gp = sum(t.pnl for t in winners)
        gl = abs(sum(t.pnl for t in losers))
        pf = gp / gl if gl > 0 else (float('inf') if gp > 0 else 0)
        pnl = sum(t.pnl for t in trades)
        total_pnl += pnl

        daily_pnl = defaultdict(float)
        for t in trades:
            day = str(t.exit_time.date()) if t.exit_time else 'unknown'
            daily_pnl[day] += t.pnl
        daily_vals = list(daily_pnl.values())
        if len(daily_vals) > 1 and np.std(daily_vals) > 0:
            sharpe = np.mean(daily_vals) / np.std(daily_vals) * np.sqrt(252)
        else:
            sharpe = 0.0

        pf_str = f"{pf:.2f}" if pf != float('inf') else "inf"
        print(f"  W{i+1:>2}  {w['test_start']}→{w['test_end']}  {n:>5} {wr*100:>5.1f}% "
              f"{pf_str:>6} ${pnl:>9.2f} {sharpe:>7.2f}")

    print(f"  {'─' * 70}")
    print(f"  Total: {total_trades} trades, P&L=${total_pnl:,.2f}")


def main():
    print("Loading data...")
    ticker_data = load_all_data()
    print(f"Loaded {len(ticker_data)} tickers\n")

    # ════════════════════════════════════════════════════════════════════
    # 1. W6 DETAILED TRADE LOG
    # ════════════════════════════════════════════════════════════════════
    print("\n" + "█" * 90)
    print("  SECTION 1: W6 DETAILED TRADE LOG")
    print("█" * 90)

    w6_config = build_config("W6_OOS", W6_PARAMS)
    w6_trades = run_with_trades(w6_config, ticker_data,
                                 W6['test_start'], W6['test_end'])

    max_consec, worst_streak = print_trade_log(w6_trades, "W6 OOS (Oct 10 – Nov 10)")
    analyze_by_ticker(w6_trades, "W6 OOS")
    analyze_by_pattern(w6_trades, "W6 OOS")
    analyze_by_exit_reason(w6_trades, "W6 OOS")
    analyze_levels(w6_trades, "W6 OOS")

    # ════════════════════════════════════════════════════════════════════
    # 2. W5 DETAILED TRADE LOG (for comparison)
    # ════════════════════════════════════════════════════════════════════
    print("\n\n" + "█" * 90)
    print("  SECTION 2: W5 DETAILED TRADE LOG (BEST WINDOW)")
    print("█" * 90)

    w5_config = build_config("W5_OOS", W5_PARAMS)
    w5_trades = run_with_trades(w5_config, ticker_data,
                                 W5['test_start'], W5['test_end'])

    print_trade_log(w5_trades, "W5 OOS (Sep 10 – Oct 10)")
    analyze_by_ticker(w5_trades, "W5 OOS")
    analyze_by_pattern(w5_trades, "W5 OOS")
    analyze_by_exit_reason(w5_trades, "W5 OOS")
    analyze_levels(w5_trades, "W5 OOS")

    # ════════════════════════════════════════════════════════════════════
    # 3. W5 vs W6 DIRECT COMPARISON
    # ════════════════════════════════════════════════════════════════════
    print("\n\n" + "█" * 90)
    print("  SECTION 3: W5 vs W6 HEAD-TO-HEAD COMPARISON")
    print("█" * 90)

    print(f"\n  Parameter differences:")
    for key in sorted(set(list(W5_PARAMS.keys()) + list(W6_PARAMS.keys()))):
        v5 = W5_PARAMS.get(key, '—')
        v6 = W6_PARAMS.get(key, '—')
        marker = " ← DIFFERENT" if v5 != v6 else ""
        print(f"    {key:>25}: W5={v5}  W6={v6}{marker}")

    w5_pnl = sum(t.pnl for t in w5_trades)
    w6_pnl = sum(t.pnl for t in w6_trades)
    w5_winners = sum(1 for t in w5_trades if t.pnl > 0)
    w6_winners = sum(1 for t in w6_trades if t.pnl > 0)

    print(f"\n  {'Metric':>25} {'W5 (Best)':>12} {'W6 (Worst)':>12}")
    print(f"  {'─' * 52}")
    print(f"  {'Trades':>25} {len(w5_trades):>12} {len(w6_trades):>12}")
    print(f"  {'Winners':>25} {w5_winners:>12} {w6_winners:>12}")
    print(f"  {'Win Rate':>25} {w5_winners/max(len(w5_trades),1)*100:>11.1f}% "
          f"{w6_winners/max(len(w6_trades),1)*100:>11.1f}%")
    print(f"  {'Total P&L':>25} ${w5_pnl:>11.2f} ${w6_pnl:>11.2f}")

    # ════════════════════════════════════════════════════════════════════
    # 4. MARKET REGIME COMPARISON
    # ════════════════════════════════════════════════════════════════════
    print("\n\n" + "█" * 90)
    print("  SECTION 4: MARKET REGIME — W5 vs W6")
    print("█" * 90)

    analyze_market_regime(ticker_data, W5['test_start'], W5['test_end'],
                          "W5 (Sep 10 – Oct 10)")
    analyze_market_regime(ticker_data, W6['test_start'], W6['test_end'],
                          "W6 (Oct 10 – Nov 10)")

    # ════════════════════════════════════════════════════════════════════
    # 5. CIRCUIT BREAKER / LOSING STREAKS
    # ════════════════════════════════════════════════════════════════════
    print("\n\n" + "█" * 90)
    print("  SECTION 5: CIRCUIT BREAKERS & LOSING STREAKS (W6)")
    print("█" * 90)

    cb_trades = [t for t in w6_trades if t.exit_reason and
                 t.exit_reason.value == 'circuit_breaker']
    print(f"\n  Circuit breaker exits in W6: {len(cb_trades)}")

    # Daily P&L breakdown
    daily_pnl = defaultdict(lambda: {'trades': 0, 'pnl': 0.0, 'winners': 0})
    for t in sorted(w6_trades, key=lambda t: t.entry_time if t.entry_time else pd.Timestamp.min):
        day = str(t.exit_time.date()) if t.exit_time else 'unknown'
        daily_pnl[day]['trades'] += 1
        daily_pnl[day]['pnl'] += t.pnl
        if t.pnl > 0:
            daily_pnl[day]['winners'] += 1

    print(f"\n  Daily P&L breakdown (W6):")
    print(f"  {'Date':>12} {'Trades':>6} {'Winners':>7} {'P&L':>10} {'CumP&L':>10}")
    print(f"  {'─' * 50}")
    cum = 0
    for day in sorted(daily_pnl.keys()):
        d = daily_pnl[day]
        cum += d['pnl']
        print(f"  {day:>12} {d['trades']:>6} {d['winners']:>7} ${d['pnl']:>9.2f} ${cum:>9.2f}")

    # ════════════════════════════════════════════════════════════════════
    # 6. FIXED-PARAMS COMPARISON
    # ════════════════════════════════════════════════════════════════════
    print("\n\n" + "█" * 90)
    print("  SECTION 6: FIXED-PARAMS COMPARISON ACROSS ALL WINDOWS")
    print("█" * 90)

    # A: Use W5 params (best window) for all windows
    run_fixed_params_all_windows(ticker_data, W5_PARAMS, "W5 params for all windows")

    # B: Use W6 params for all windows
    run_fixed_params_all_windows(ticker_data, W6_PARAMS, "W6 params for all windows")

    # C: Use baseline defaults (no overrides, original Phase 2.2)
    run_fixed_params_all_windows(ticker_data, {}, "BASELINE defaults (Phase 2.2)")

    # D: Use overall best IS params (FD=10, ATR_entry=0.6, etc.)
    overall_best = {
        'atr_entry_threshold': 0.6,
        'fractal_depth': 10,
        'max_stop_atr_pct': 0.1,
        'min_rr': 2.0,
        'tail_ratio_min': 0.15,
    }
    run_fixed_params_all_windows(ticker_data, overall_best,
                                  "Overall best IS (FD=10, ATR=0.6, RR=2.0)")

    print("\n\nDone.")


if __name__ == '__main__':
    main()
