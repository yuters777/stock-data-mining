"""
Phase 3 Pre-Freeze Diagnostics — 4 tests before Config C freeze.

D1: Counterfactual — are blocked trades actually bad?
D2: Remove-top-5 stress test — profitable without tail?
D3: Quarterly stability — is edge episodic?
D4: Manual audit — top 5 winners legitimate?
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import numpy as np
import pandas as pd
from collections import defaultdict

from backtester.backtester import Backtester, BacktestConfig
from backtester.core.level_detector import LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngineConfig
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig
from backtester.core.intraday_levels import IntradayLevelConfig
from backtester.earnings import EarningsCalendar
from backtester.optimizer import load_ticker_data
from backtester.run_phase3_25ticker import TICKERS, FULL_START, FULL_END

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'results', 'phase3_diagnostics')
os.makedirs(RESULTS_DIR, exist_ok=True)


def make_config(variant, earnings_calendar=None):
    atr_settings = {
        'A': {'enable_atr_filter': False, 'atr_block_threshold': 0.20, 'atr_entry_threshold': 0.60},
        'C': {'enable_atr_filter': True,  'atr_block_threshold': 0.10, 'atr_entry_threshold': 0.40},
    }[variant]
    return BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=10, tolerance_cents=0.05, tolerance_pct=0.001,
            atr_period=5, min_level_score=5,
        ),
        pattern_config=PatternEngineConfig(
            tail_ratio_min=0.15, lp2_engulfing_required=True,
            clp_min_bars=3, clp_max_bars=7,
        ),
        filter_config=FilterChainConfig(
            enable_atr_filter=atr_settings['enable_atr_filter'],
            atr_block_threshold=atr_settings['atr_block_threshold'],
            atr_entry_threshold=atr_settings['atr_entry_threshold'],
            enable_volume_filter=True,
            enable_time_filter=True,
            enable_squeeze_filter=False,
        ),
        risk_config=RiskManagerConfig(
            min_rr=2.0, max_stop_atr_pct=0.15, capital=100000.0, risk_pct=0.003,
        ),
        trade_config=TradeManagerConfig(
            slippage_per_share=0.02, partial_tp_at_r=2.0, partial_tp_pct=0.50,
        ),
        intraday_config=IntradayLevelConfig(
            fractal_depth_m5=5, fractal_depth_h1=3, enable_h1=True,
            min_target_r=1.0, lookback_bars=1000,
        ),
        tier_config={
            'mode': '2tier_trail', 't1_pct': 0.30, 'min_rr': 2.0,
            'trail_factor': 0.7, 'trail_activation_r': 0.0,
        },
        direction_filter=None,
        earnings_calendar=earnings_calendar,
        name=f'ConfigA_Variant_{variant}',
    )


def collect_trades(config, label):
    """Run backtest, return list of trade dicts with full details."""
    print(f"  Running {label}...")
    trades = []
    for ticker in TICKERS:
        try:
            m5_df = load_ticker_data(ticker)
            bt = Backtester(config)
            result = bt.run(m5_df, start_date=FULL_START, end_date=FULL_END)
            for t in result.trades:
                trades.append({
                    'ticker': ticker,
                    'direction': t.direction.value,
                    'pattern': t.signal.pattern.value if t.signal else '',
                    'entry_time': str(t.entry_time),
                    'exit_time': str(t.exit_time),
                    'entry_price': t.entry_price,
                    'exit_price': t.exit_price,
                    'stop_price': t.stop_price,
                    'target_price': t.target_price,
                    'position_size': t.position_size,
                    'pnl': t.pnl,
                    'pnl_r': t.pnl_r,
                    'is_winner': t.is_winner,
                    'exit_reason': t.exit_reason.value if t.exit_reason else '',
                    'max_favorable': t.max_favorable,
                    'max_adverse': t.max_adverse,
                    'trailing_stop_price': getattr(t, 'trailing_stop_price', 0.0),
                    'slippage_total': getattr(t, 'slippage_total', 0.0),
                })
        except Exception as e:
            print(f"    {ticker}: FAILED — {e}")
    print(f"    → {len(trades)} trades")
    return trades


def calc_metrics(trades):
    if not trades:
        return {'trades': 0, 'wr': 0.0, 'pf': 0.0, 'pnl': 0.0,
                'max_dd': 0.0, 'avg_r': 0.0}
    pnls = np.array([t['pnl'] for t in trades])
    winners = pnls[pnls > 0]
    losers = pnls[pnls <= 0]
    gp = winners.sum()
    gl = abs(losers.sum())
    pf = gp / gl if gl > 0 else (float('inf') if gp > 0 else 0.0)
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    max_dd = float((peak - cum).max()) if len(cum) > 0 else 0.0
    r_vals = [t['pnl_r'] for t in trades]
    return {
        'trades': len(trades),
        'wr': float(len(winners) / len(pnls)),
        'pf': float(pf),
        'pnl': float(pnls.sum()),
        'max_dd': max_dd,
        'avg_r': float(np.mean(r_vals)) if r_vals else 0.0,
    }


def trade_key(t):
    """Create a matching key for a trade (ticker + entry_time is unique)."""
    return (t['ticker'], t['entry_time'])


# ═══════════════════════════════════════════════════════════════════════════
# DIAGNOSTIC 1: Counterfactual — Blocked Trades
# ═══════════════════════════════════════════════════════════════════════════

def diagnostic_1(trades_a, trades_c):
    print("\n" + "=" * 80)
    print("  DIAGNOSTIC 1: Counterfactual — Blocked Trades Analysis")
    print("=" * 80)

    c_keys = set(trade_key(t) for t in trades_c)
    blocked = [t for t in trades_a if trade_key(t) not in c_keys]
    kept = [t for t in trades_a if trade_key(t) in c_keys]

    m_blocked = calc_metrics(blocked)
    m_kept = calc_metrics(kept)
    m_all = calc_metrics(trades_a)

    pf_b = f"{m_blocked['pf']:.2f}" if m_blocked['pf'] != float('inf') else "inf"
    pf_k = f"{m_kept['pf']:.2f}" if m_kept['pf'] != float('inf') else "inf"

    print(f"\n  Variant A total: {m_all['trades']} trades, P&L=${m_all['pnl']:,.0f}")
    print(f"  Variant C kept:  {m_kept['trades']} trades, P&L=${m_kept['pnl']:,.0f}, PF={pf_k}")
    print(f"  Blocked by ATR:  {m_blocked['trades']} trades, P&L=${m_blocked['pnl']:,.0f}, "
          f"PF={pf_b}, WR={m_blocked['wr']*100:.1f}%, AvgR={m_blocked['avg_r']:.2f}")

    # Breakdown: how many blocked winners vs losers
    blocked_winners = [t for t in blocked if t['is_winner']]
    blocked_losers = [t for t in blocked if not t['is_winner']]
    print(f"\n  Blocked winners: {len(blocked_winners)} (P&L=${sum(t['pnl'] for t in blocked_winners):,.0f})")
    print(f"  Blocked losers:  {len(blocked_losers)} (P&L=${sum(t['pnl'] for t in blocked_losers):,.0f})")

    if m_blocked['pnl'] < 0:
        verdict = "GENUINE FILTER"
        reason = "Blocked trades are net negative — ATR gate removes bad trades"
    elif m_blocked['pf'] > 1.0:
        verdict = "SUPPRESSIVE"
        reason = "Blocked trades are net profitable — ATR gate kills good trades"
    else:
        verdict = "MIXED"
        reason = "Blocked trades are marginally positive but PF < 1.0"

    print(f"\n  VERDICT: {verdict}")
    print(f"  {reason}")

    result = {
        'all_trades': m_all,
        'kept_trades': m_kept,
        'blocked_trades': m_blocked,
        'blocked_winners': len(blocked_winners),
        'blocked_losers': len(blocked_losers),
        'blocked_winner_pnl': sum(t['pnl'] for t in blocked_winners),
        'blocked_loser_pnl': sum(t['pnl'] for t in blocked_losers),
        'verdict': verdict,
        'reason': reason,
    }
    with open(os.path.join(RESULTS_DIR, 'counterfactual_blocked_trades.json'), 'w') as f:
        json.dump(result, f, indent=2, default=str)

    return verdict


# ═══════════════════════════════════════════════════════════════════════════
# DIAGNOSTIC 2: Remove-Top-5 Stress Test
# ═══════════════════════════════════════════════════════════════════════════

def diagnostic_2(trades_a, trades_c):
    print("\n" + "=" * 80)
    print("  DIAGNOSTIC 2: Remove-Top-5 Stress Test")
    print("=" * 80)

    results = {}
    for label, trades in [('A', trades_a), ('C', trades_c)]:
        sorted_trades = sorted(trades, key=lambda t: t['pnl'], reverse=True)
        top5 = sorted_trades[:5]
        remaining = sorted_trades[5:]

        m_full = calc_metrics(trades)
        m_sans = calc_metrics(remaining)
        m_top5 = calc_metrics(top5)

        pf_full = f"{m_full['pf']:.2f}" if m_full['pf'] != float('inf') else "inf"
        pf_sans = f"{m_sans['pf']:.2f}" if m_sans['pf'] != float('inf') else "inf"

        print(f"\n  Variant {label}:")
        print(f"    Full:        {m_full['trades']}t  PF={pf_full}  P&L=${m_full['pnl']:,.0f}")
        print(f"    Without top5: {m_sans['trades']}t  PF={pf_sans}  P&L=${m_sans['pnl']:,.0f}")
        print(f"    Top 5 alone:  P&L=${m_top5['pnl']:,.0f} ({m_top5['pnl']/m_full['pnl']*100:.0f}% of total)" if m_full['pnl'] != 0 else "")
        print(f"    Top 5 trades:")
        for i, t in enumerate(top5):
            print(f"      #{i+1}: {t['ticker']} {t['pattern']} {t['direction']} "
                  f"{t['entry_time'][:10]} P&L=${t['pnl']:,.0f} ({t['pnl_r']:+.1f}R)")

        results[label] = {
            'full': m_full,
            'without_top5': m_sans,
            'top5': m_top5,
            'top5_pct_of_total': m_top5['pnl'] / m_full['pnl'] * 100 if m_full['pnl'] != 0 else 0,
            'top5_trades': [{'ticker': t['ticker'], 'pattern': t['pattern'],
                            'direction': t['direction'], 'entry_time': t['entry_time'],
                            'pnl': t['pnl'], 'pnl_r': t['pnl_r']} for t in top5],
        }

    # Verdicts
    for label in ['A', 'C']:
        r = results[label]
        if r['without_top5']['pf'] > 1.0:
            results[label]['verdict'] = 'STILL PROFITABLE'
        else:
            results[label]['verdict'] = 'TAIL-ONLY STRATEGY'

    print(f"\n  Variant A verdict: {results['A']['verdict']}")
    print(f"  Variant C verdict: {results['C']['verdict']}")

    with open(os.path.join(RESULTS_DIR, 'remove_top5_stress_test.json'), 'w') as f:
        json.dump(results, f, indent=2, default=str)

    return results['C']['verdict']


# ═══════════════════════════════════════════════════════════════════════════
# DIAGNOSTIC 3: Quarterly Stability
# ═══════════════════════════════════════════════════════════════════════════

def diagnostic_3(trades_a, trades_c):
    print("\n" + "=" * 80)
    print("  DIAGNOSTIC 3: Quarterly Stability")
    print("=" * 80)

    quarters = [
        ('Q1 (Feb-Apr)', '2025-02-01', '2025-05-01'),
        ('Q2 (May-Jul)', '2025-05-01', '2025-08-01'),
        ('Q3 (Aug-Oct)', '2025-08-01', '2025-11-01'),
        ('Q4 (Nov-Jan)', '2025-11-01', '2026-02-01'),
    ]

    results = {}
    for label, trades in [('A', trades_a), ('C', trades_c)]:
        q_data = []
        total_pnl = sum(t['pnl'] for t in trades)
        for q_name, q_start, q_end in quarters:
            q_trades = [t for t in trades
                       if q_start <= t['entry_time'][:10] < q_end]
            m = calc_metrics(q_trades)
            pct = m['pnl'] / total_pnl * 100 if total_pnl != 0 else 0
            q_data.append({
                'quarter': q_name,
                'metrics': m,
                'pct_of_total': pct,
            })
        results[label] = q_data

    # Print table
    print(f"\n  {'Quarter':<16} {'C Trades':>8} {'C PF':>7} {'C P&L':>10} {'C %':>6} "
          f"{'A Trades':>8} {'A PF':>7} {'A P&L':>10} {'A %':>6}")
    print(f"  {'-' * 82}")

    for i, (q_name, _, _) in enumerate(quarters):
        c = results['C'][i]['metrics']
        a = results['A'][i]['metrics']
        c_pf = f"{c['pf']:.2f}" if c['pf'] != float('inf') else "inf"
        a_pf = f"{a['pf']:.2f}" if a['pf'] != float('inf') else "inf"
        c_pct = results['C'][i]['pct_of_total']
        a_pct = results['A'][i]['pct_of_total']
        print(f"  {q_name:<16} {c['trades']:>8} {c_pf:>7} ${c['pnl']:>9,.0f} {c_pct:>5.0f}% "
              f"{a['trades']:>8} {a_pf:>7} ${a['pnl']:>9,.0f} {a_pct:>5.0f}%")

    # Check: does any quarter carry >80% of C's P&L?
    max_q_pct = max(abs(q['pct_of_total']) for q in results['C'])
    if max_q_pct > 80:
        verdict = "EPISODIC EDGE"
        reason = f"One quarter carries {max_q_pct:.0f}% of total P&L"
    else:
        verdict = "DISTRIBUTED"
        reason = f"No quarter > 80% of total P&L (max: {max_q_pct:.0f}%)"

    print(f"\n  Variant C verdict: {verdict}")
    print(f"  {reason}")

    save = {'A': results['A'], 'C': results['C'],
            'verdict': verdict, 'reason': reason, 'max_quarter_pct': max_q_pct}
    with open(os.path.join(RESULTS_DIR, 'quarterly_stability.json'), 'w') as f:
        json.dump(save, f, indent=2, default=str)

    return verdict


# ═══════════════════════════════════════════════════════════════════════════
# DIAGNOSTIC 4: Manual Audit — Top 5 Winners
# ═══════════════════════════════════════════════════════════════════════════

def diagnostic_4(trades_c, config_c):
    print("\n" + "=" * 80)
    print("  DIAGNOSTIC 4: Manual Audit — Top 5 Winners (Variant C)")
    print("=" * 80)

    sorted_trades = sorted(trades_c, key=lambda t: t['pnl'], reverse=True)
    top5 = sorted_trades[:5]

    audit_lines = []
    verdicts = []

    for i, t in enumerate(top5):
        ticker = t['ticker']
        entry_ts = pd.Timestamp(t['entry_time'])
        exit_ts = pd.Timestamp(t['exit_time'])
        issues = []

        audit_lines.append(f"\n{'=' * 70}")
        audit_lines.append(
            f"TRADE #{i+1}: {ticker} {t['pattern']} {t['direction']} "
            f"P&L=${t['pnl']:,.0f} ({t['pnl_r']:+.1f}R)")
        audit_lines.append(f"{'=' * 70}")
        audit_lines.append(f"  Entry: {t['entry_time']}  Price: {t['entry_price']:.4f}")
        audit_lines.append(f"  Exit:  {t['exit_time']}  Price: {t['exit_price']:.4f}")
        audit_lines.append(f"  Stop:  {t['stop_price']:.4f}  Target: {t['target_price']:.4f}")
        audit_lines.append(f"  Position: {t['position_size']} shares  Slippage: ${t['slippage_total']:.2f}")
        audit_lines.append(f"  Exit reason: {t['exit_reason']}")
        audit_lines.append(f"  Max favorable: {t['max_favorable']:.4f}  Max adverse: {t['max_adverse']:.4f}")

        # ── Check 1: Entry timing (IST hours, data is IST timezone-naive)
        # Market open: 16:30 IST (9:30 ET), earliest signal: 16:35
        # Market close: 23:00 IST (4:00 PM ET)
        entry_minutes = entry_ts.hour * 60 + entry_ts.minute
        # 16:35 IST = 995 minutes, 23:00 IST = 1380 minutes
        entry_ok = 995 <= entry_minutes < 1380
        audit_lines.append(f"\n  [1] Entry timing: {entry_ts.strftime('%H:%M')} IST "
                          f"({'within session' if entry_ok else 'OUTSIDE SESSION'})")
        if not entry_ok:
            issues.append("Entry outside regular session hours")

        # ── Check 2: Exit timing
        exit_minutes = exit_ts.hour * 60 + exit_ts.minute
        exit_ok = 990 <= exit_minutes < 1380  # slightly relaxed for EOD exits
        audit_lines.append(f"  [2] Exit timing:  {exit_ts.strftime('%H:%M')} IST "
                          f"({'within session' if exit_ok else 'OUTSIDE SESSION'})")
        if not exit_ok:
            issues.append("Exit outside regular session hours")

        # ── Check 3: No overnight span
        entry_date = entry_ts.normalize()
        exit_date = exit_ts.normalize()
        same_day = entry_date == exit_date
        audit_lines.append(f"  [3] Same-day trade: {'Yes' if same_day else 'NO — spans overnight'}")
        if not same_day:
            issues.append("Trade spans overnight")

        # ── Check 4: Slippage applied
        slippage_ok = t['slippage_total'] > 0
        audit_lines.append(f"  [4] Slippage applied: {'Yes' if slippage_ok else 'NO — zero slippage'} "
                          f"(${t['slippage_total']:.2f})")
        if not slippage_ok:
            issues.append("Zero slippage — may be unrealistic")

        # ── Check 5: Exit reason consistent
        if t['exit_reason'] == 'target_hit':
            # For longs, exit_price should be near target
            # For shorts, exit_price should be near target (lower)
            target_dist = abs(t['exit_price'] - t['target_price'])
            close_to_target = target_dist < abs(t['target_price'] - t['entry_price']) * 0.1
            audit_lines.append(f"  [5] Target hit verification: exit={t['exit_price']:.4f} "
                              f"target={t['target_price']:.4f} "
                              f"({'consistent' if close_to_target else 'DISTANT'})")
            if not close_to_target:
                issues.append("Exit price not near target")
        elif t['exit_reason'] == 'trail_stop':
            trail_ok = t['trailing_stop_price'] > 0
            audit_lines.append(f"  [5] Trail stop verification: trail_price={t['trailing_stop_price']:.4f} "
                              f"({'active' if trail_ok else 'NOT SET'})")
            if not trail_ok:
                issues.append("Trail stop exit but no trailing stop price set")
        elif t['exit_reason'] == 'stop_loss':
            # Stop hit — exit price should be near stop
            stop_dist = abs(t['exit_price'] - t['stop_price'])
            entry_stop_dist = abs(t['entry_price'] - t['stop_price'])
            close_to_stop = stop_dist < entry_stop_dist * 0.2 if entry_stop_dist > 0 else True
            audit_lines.append(f"  [5] Stop loss verification: exit={t['exit_price']:.4f} "
                              f"stop={t['stop_price']:.4f} "
                              f"({'consistent' if close_to_stop else 'DISTANT'})")
        else:
            audit_lines.append(f"  [5] Exit reason: {t['exit_reason']}")

        # ── Check 6: R-multiple sanity
        r_extreme = abs(t['pnl_r']) > 20
        audit_lines.append(f"  [6] R-multiple: {t['pnl_r']:.1f}R "
                          f"({'EXTREME — verify manually' if r_extreme else 'reasonable'})")
        if r_extreme:
            issues.append(f"Extreme R-multiple ({t['pnl_r']:.1f}R)")

        # ── Check 7: ATR exhaustion at entry (re-compute)
        # Load data and compute ATR ratio for this specific signal
        try:
            m5_df = load_ticker_data(ticker)
            bt = Backtester(config_c)
            m5_rth, daily_df, levels = bt.prepare_data(m5_df)
            m5_rth = m5_rth.reset_index(drop=True)

            # Find the entry bar
            entry_mask = (m5_rth['Datetime'] <= entry_ts) & (m5_rth['Ticker'] == ticker)
            if entry_mask.any():
                bar_idx = entry_mask[entry_mask].index[-1]
                bar = m5_rth.iloc[bar_idx]
                bar_date = pd.Timestamp(bar['Datetime']).normalize()

                # Get ATR D1
                day_row = daily_df[
                    (daily_df['Ticker'] == ticker) & (daily_df['Date'] == bar_date)
                ]
                if day_row.empty:
                    day_row = daily_df[
                        (daily_df['Ticker'] == ticker) & (daily_df['Date'] < bar_date)
                    ].tail(1)

                if not day_row.empty:
                    atr_d1 = day_row.iloc[0].get('ModifiedATR', day_row.iloc[0].get('ATR', 0))

                    day_bars = m5_rth[
                        (m5_rth['Ticker'] == ticker) &
                        (pd.to_datetime(m5_rth['Datetime']).dt.normalize() == bar_date)
                    ]
                    day_bars_to = day_bars.loc[:bar_idx]

                    if not day_bars_to.empty and atr_d1 > 0:
                        from backtester.data_types import SignalDirection
                        if t['direction'] == 'short':
                            day_low = day_bars_to['Low'].min()
                            distance = bar['Close'] - day_low  # approximate
                            # Use level price if available, but we approximate
                        else:
                            day_high = day_bars_to['High'].max()
                            distance = day_high - bar['Close']
                        distance = max(distance, 0)
                        atr_ratio = distance / atr_d1

                        atr_pass = atr_ratio >= 0.40
                        audit_lines.append(
                            f"  [7] ATR exhaustion at entry: {atr_ratio:.4f} "
                            f"(threshold=0.40, {'PASS' if atr_pass else 'FAIL'})")
                        audit_lines.append(
                            f"      ATR_D1={atr_d1:.4f}, distance={distance:.4f}, "
                            f"day_bars_used={len(day_bars_to)} (not full day → no lookahead)")
                        if not atr_pass:
                            issues.append(f"ATR ratio {atr_ratio:.4f} < 0.40 threshold")
                    else:
                        audit_lines.append(f"  [7] ATR: insufficient data for verification")
                else:
                    audit_lines.append(f"  [7] ATR: no daily data for {bar_date.date()}")
            else:
                audit_lines.append(f"  [7] ATR: could not find entry bar in RTH data")
        except Exception as e:
            audit_lines.append(f"  [7] ATR verification error: {e}")
            issues.append(f"ATR verification failed: {e}")

        # ── Verdict
        if not issues:
            verdict = "VALID"
        elif any("OUTSIDE SESSION" in i or "spans overnight" in i or "FAIL" in i for i in issues):
            verdict = "SUSPICIOUS"
        else:
            verdict = "VALID (minor notes)"

        audit_lines.append(f"\n  ISSUES: {issues if issues else 'None'}")
        audit_lines.append(f"  VERDICT: {verdict}")
        verdicts.append({'trade': i + 1, 'ticker': ticker, 'pnl': t['pnl'],
                        'verdict': verdict, 'issues': issues})

    # Print and save
    audit_text = '\n'.join(audit_lines)
    print(audit_text)

    with open(os.path.join(RESULTS_DIR, 'top5_audit.txt'), 'w') as f:
        f.write(audit_text)

    all_valid = all(v['verdict'].startswith('VALID') for v in verdicts)
    overall = "ALL VALID" if all_valid else "ISSUES FOUND"
    print(f"\n  OVERALL: {overall}")

    return overall, verdicts


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 80)
    print("  PHASE 3 PRE-FREEZE DIAGNOSTICS — 4 Tests")
    print("=" * 80)

    # Load earnings (sandbox-blocked, will be empty)
    cache_dir = os.path.join(RESULTS_DIR, 'cache')
    calendar = EarningsCalendar(cache_dir=cache_dir)
    calendar.load(TICKERS)

    config_a = make_config('A', calendar)
    config_c = make_config('C', calendar)

    # Suppress ATR debug output for clean diagnostics
    config_a.filter_config._atr_debug_limit = 0
    config_c.filter_config._atr_debug_limit = 0

    # Collect trades
    trades_a = collect_trades(config_a, "Variant A (ATR OFF)")
    trades_c = collect_trades(config_c, "Variant C (ATR 0.40/0.10)")

    # Run diagnostics
    v1 = diagnostic_1(trades_a, trades_c)
    v2 = diagnostic_2(trades_a, trades_c)
    v3 = diagnostic_3(trades_a, trades_c)
    v4_overall, v4_details = diagnostic_4(trades_c, config_c)

    # ══════════════════════════════════════════════════════════════════════
    # SUMMARY
    # ══════════════════════════════════════════════════════════════════════

    print("\n\n" + "=" * 80)
    print("  DIAGNOSTICS SUMMARY")
    print("=" * 80)

    d_results = {
        'D1_counterfactual': {'verdict': v1, 'pass': v1 == 'GENUINE FILTER'},
        'D2_remove_top5': {'verdict': v2, 'pass': v2 == 'STILL PROFITABLE'},
        'D3_quarterly': {'verdict': v3, 'pass': v3 == 'DISTRIBUTED'},
        'D4_audit': {'verdict': v4_overall, 'pass': v4_overall == 'ALL VALID',
                     'details': v4_details},
    }

    all_pass = all(d['pass'] for d in d_results.values())

    print(f"\n  {'Diagnostic':<30} {'Verdict':<25} {'Pass?':<6}")
    print(f"  {'-' * 60}")
    for name, d in d_results.items():
        status = "PASS" if d['pass'] else "FAIL"
        print(f"  {name:<30} {d['verdict']:<25} {status}")

    print(f"\n  {'=' * 60}")
    if all_pass:
        print(f"  ALL 4 DIAGNOSTICS PASS → Variant C is safe to freeze")
    else:
        failed = [n for n, d in d_results.items() if not d['pass']]
        print(f"  FAILED: {', '.join(failed)}")
        print(f"  DO NOT FREEZE — address failed diagnostics first")
    print(f"  {'=' * 60}")

    # Save summary
    with open(os.path.join(RESULTS_DIR, 'diagnostics_summary.json'), 'w') as f:
        json.dump({
            'all_pass': all_pass,
            'diagnostics': d_results,
            'recommendation': 'FREEZE Variant C' if all_pass else 'DO NOT FREEZE',
        }, f, indent=2, default=str)

    print(f"\n  Results saved to: {RESULTS_DIR}/")


if __name__ == '__main__':
    main()
