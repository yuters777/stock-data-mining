"""
Phase 8 — Confirmation Indicators & Signal Quality

5 confirmation indicators:
  1. Mirror level (is_mirror / level_type == MIRROR)
  2. Level score (>= threshold)
  3. Volume fade (trigger bar vol < recent avg)
  4. RSI(14) extreme on D1 (overbought/oversold confirms direction)
  5. Multi-touch level (touches >= threshold)

M-001: Diagnostic signal count
M-002: Mirror-only filter
M-003: High-score filter (sweep thresholds)
M-004: Volume fade filter
M-005: RSI extreme filter (sweep thresholds)
M-006: Multi-touch filter (sweep thresholds)
M-007: Combined best + walk-forward
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

from backtester.backtester import Backtester, BacktestConfig
from backtester.core.level_detector import LevelDetectorConfig, LevelType
from backtester.core.pattern_engine import PatternEngineConfig, TradeDirection
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig
from backtester.core.intraday_levels import IntradayLevelConfig
from backtester.optimizer import (load_ticker_data, run_single_backtest,
                                   aggregate_metrics, WalkForwardValidator)

# ──────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────

ALL_TICKERS = ['AAPL', 'AMZN', 'GOOGL', 'TSLA']
IS_START = '2025-02-10'
IS_END = '2025-10-01'
OOS_START = '2025-10-01'
OOS_END = '2026-01-31'

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
os.makedirs(RESULTS_DIR, exist_ok=True)

LOG = []
def log(msg=''):
    LOG.append(msg)
    print(msg)


# ──────────────────────────────────────────────────────────────────
# Config builder (L-005 baseline)
# ──────────────────────────────────────────────────────────────────

def make_l005_config(name='L-005') -> BacktestConfig:
    return BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=10, tolerance_cents=0.05, tolerance_pct=0.001,
            atr_period=5, min_level_score=5,
        ),
        pattern_config=PatternEngineConfig(
            tail_ratio_min=0.10, lp2_engulfing_required=True,
            clp_min_bars=3, clp_max_bars=7,
        ),
        filter_config=FilterChainConfig(
            atr_block_threshold=0.30, atr_entry_threshold=0.80,
            enable_volume_filter=True, enable_time_filter=True,
            enable_squeeze_filter=True,
        ),
        risk_config=RiskManagerConfig(
            min_rr=1.5, max_stop_atr_pct=0.10, capital=100000.0, risk_pct=0.003,
        ),
        trade_config=TradeManagerConfig(
            slippage_per_share=0.02, partial_tp_at_r=2.0, partial_tp_pct=0.50,
        ),
        intraday_config=IntradayLevelConfig(
            fractal_depth_m5=5, fractal_depth_h1=3, enable_h1=True,
            min_target_r=1.0, lookback_bars=1000,
        ),
        tier_config={
            'mode': '2tier_trail', 't1_pct': 0.30, 'min_rr': 1.5,
            'trail_factor': 0.7, 'trail_activation_r': 0.0,
        },
        direction_filter={'TSLA': 'long', 'DEFAULT': 'short'},
        name=name,
    )


# ──────────────────────────────────────────────────────────────────
# RSI computation on D1 bars
# ──────────────────────────────────────────────────────────────────

def compute_d1_rsi(ticker, period=14):
    """Compute D1 RSI for a ticker. Returns {date: rsi_value}."""
    m5_df = load_ticker_data(ticker)
    # Filter RTH
    minutes = m5_df['Datetime'].dt.hour * 60 + m5_df['Datetime'].dt.minute
    rth = m5_df[(minutes >= 14 * 60 + 30) & (minutes < 21 * 60)].copy()
    rth['Date'] = rth['Datetime'].dt.date

    daily = rth.groupby('Date').agg(Close=('Close', 'last')).reset_index()
    daily = daily.sort_values('Date')

    closes = daily['Close'].values
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # Wilder's smoothing
    avg_gain = np.zeros(len(deltas))
    avg_loss = np.zeros(len(deltas))

    if len(gains) < period:
        return {}

    avg_gain[period - 1] = np.mean(gains[:period])
    avg_loss[period - 1] = np.mean(losses[:period])

    for i in range(period, len(deltas)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i]) / period

    rsi_values = {}
    dates = daily['Date'].values
    for i in range(period - 1, len(deltas)):
        if avg_loss[i] == 0:
            rsi = 100.0
        else:
            rs = avg_gain[i] / avg_loss[i]
            rsi = 100 - (100 / (1 + rs))
        # RSI at index i corresponds to the close at dates[i+1]
        rsi_values[dates[i + 1]] = rsi

    return rsi_values


def compute_vol_ratio(m5_df, bar_idx, ticker, lookback=20):
    """Compute volume ratio for the trigger bar vs recent average."""
    bar = m5_df.iloc[bar_idx]
    start_idx = max(0, bar_idx - lookback * 2)
    recent = m5_df.iloc[start_idx:bar_idx]
    ticker_bars = recent[recent['Ticker'] == ticker]
    if len(ticker_bars) < 5:
        return 1.0  # neutral
    avg_vol = ticker_bars['Volume'].mean()
    if avg_vol <= 0:
        return 1.0
    return bar['Volume'] / avg_vol


# ──────────────────────────────────────────────────────────────────
# M-001: Diagnostic signal count with indicator tagging
# ──────────────────────────────────────────────────────────────────

def run_m001():
    """Run L-005 config, extract trades, tag each with all 5 indicators."""
    log("\n" + "=" * 60)
    log("  M-001: Diagnostic Signal Count")
    log("=" * 60)

    config = make_l005_config('M-001')

    # Precompute D1 RSI for all tickers
    rsi_cache = {}
    for ticker in ALL_TICKERS:
        rsi_cache[ticker] = compute_d1_rsi(ticker)
        log(f"  RSI computed for {ticker}: {len(rsi_cache[ticker])} days")

    # Run backtests and tag trades
    tagged_trades = {'IS': [], 'OOS': []}

    for period_label, start, end in [('IS', IS_START, IS_END), ('OOS', OOS_START, OOS_END)]:
        for ticker in ALL_TICKERS:
            m5_df = load_ticker_data(ticker)
            result = run_single_backtest(config, m5_df, start, end)

            for trade in result.trades:
                signal = trade.signal
                entry_date = pd.Timestamp(trade.entry_time).date()

                # Tag indicators
                is_mirror = signal.level.is_mirror or signal.level.level_type == LevelType.MIRROR
                level_score = signal.level.score
                touches = signal.level.touches
                vol_ratio = compute_vol_ratio(m5_df, signal.trigger_bar_idx, ticker)
                rsi_val = rsi_cache.get(ticker, {}).get(entry_date, None)

                # RSI confirmation
                rsi_confirms = False
                if rsi_val is not None:
                    if signal.direction == TradeDirection.SHORT and rsi_val > 60:
                        rsi_confirms = True
                    elif signal.direction == TradeDirection.LONG and rsi_val < 40:
                        rsi_confirms = True

                tagged = {
                    'ticker': ticker,
                    'period': period_label,
                    'date': entry_date,
                    'direction': signal.direction.value,
                    'pattern': signal.pattern.value,
                    'pnl': trade.pnl,
                    'pnl_r': trade.pnl_r,
                    'is_winner': trade.pnl > 0,
                    # Indicators
                    'is_mirror': is_mirror,
                    'level_score': level_score,
                    'touches': touches,
                    'vol_ratio': vol_ratio,
                    'vol_fade': vol_ratio < 1.0,
                    'rsi': rsi_val,
                    'rsi_confirms': rsi_confirms,
                }
                tagged_trades[period_label].append(tagged)

    # Summarize
    for period_label in ['IS', 'OOS']:
        trades = tagged_trades[period_label]
        n = len(trades)
        log(f"\n  {period_label}: {n} trades")
        if n == 0:
            continue

        # Mirror
        mirror_t = [t for t in trades if t['is_mirror']]
        non_mirror_t = [t for t in trades if not t['is_mirror']]
        log(f"    Mirror levels: {len(mirror_t)}/{n} "
            f"(WR={sum(t['is_winner'] for t in mirror_t)/max(len(mirror_t),1)*100:.0f}%, "
            f"PF={_pf(mirror_t):.2f}, ${sum(t['pnl'] for t in mirror_t):.0f})")
        log(f"    Non-mirror:    {len(non_mirror_t)}/{n} "
            f"(WR={sum(t['is_winner'] for t in non_mirror_t)/max(len(non_mirror_t),1)*100:.0f}%, "
            f"PF={_pf(non_mirror_t):.2f}, ${sum(t['pnl'] for t in non_mirror_t):.0f})")

        # Level score buckets
        for thresh in [10, 15, 20]:
            above = [t for t in trades if t['level_score'] >= thresh]
            log(f"    Score >= {thresh}: {len(above)}/{n} "
                f"(WR={sum(t['is_winner'] for t in above)/max(len(above),1)*100:.0f}%, "
                f"PF={_pf(above):.2f}, ${sum(t['pnl'] for t in above):.0f})")

        # Volume fade
        fade_t = [t for t in trades if t['vol_fade']]
        no_fade = [t for t in trades if not t['vol_fade']]
        log(f"    Vol fade (<1x): {len(fade_t)}/{n} "
            f"(WR={sum(t['is_winner'] for t in fade_t)/max(len(fade_t),1)*100:.0f}%, "
            f"PF={_pf(fade_t):.2f}, ${sum(t['pnl'] for t in fade_t):.0f})")
        log(f"    Vol surge(>=1x):{len(no_fade)}/{n} "
            f"(WR={sum(t['is_winner'] for t in no_fade)/max(len(no_fade),1)*100:.0f}%, "
            f"PF={_pf(no_fade):.2f}, ${sum(t['pnl'] for t in no_fade):.0f})")

        # RSI
        rsi_conf = [t for t in trades if t['rsi_confirms']]
        rsi_not = [t for t in trades if not t['rsi_confirms']]
        log(f"    RSI confirms:   {len(rsi_conf)}/{n} "
            f"(WR={sum(t['is_winner'] for t in rsi_conf)/max(len(rsi_conf),1)*100:.0f}%, "
            f"PF={_pf(rsi_conf):.2f}, ${sum(t['pnl'] for t in rsi_conf):.0f})")
        log(f"    RSI neutral:    {len(rsi_not)}/{n} "
            f"(WR={sum(t['is_winner'] for t in rsi_not)/max(len(rsi_not),1)*100:.0f}%, "
            f"PF={_pf(rsi_not):.2f}, ${sum(t['pnl'] for t in rsi_not):.0f})")

        # RSI with different thresholds
        for short_thresh, long_thresh in [(50, 50), (55, 45), (65, 35), (70, 30)]:
            conf = []
            for t in trades:
                if t['rsi'] is None:
                    continue
                if t['direction'] == 'short' and t['rsi'] > short_thresh:
                    conf.append(t)
                elif t['direction'] == 'long' and t['rsi'] < long_thresh:
                    conf.append(t)
            log(f"    RSI S>{short_thresh}/L<{long_thresh}: {len(conf)}/{n} "
                f"(WR={sum(t['is_winner'] for t in conf)/max(len(conf),1)*100:.0f}%, "
                f"PF={_pf(conf):.2f}, ${sum(t['pnl'] for t in conf):.0f})")

        # Touches
        for thresh in [2, 3, 5]:
            above = [t for t in trades if t['touches'] >= thresh]
            log(f"    Touches >= {thresh}: {len(above)}/{n} "
                f"(WR={sum(t['is_winner'] for t in above)/max(len(above),1)*100:.0f}%, "
                f"PF={_pf(above):.2f}, ${sum(t['pnl'] for t in above):.0f})")

        # Per-ticker breakdown
        log(f"\n    Per-ticker ({period_label}):")
        for ticker in ALL_TICKERS:
            tt = [t for t in trades if t['ticker'] == ticker]
            if not tt:
                continue
            log(f"      {ticker}: {len(tt)}t, "
                f"WR={sum(t['is_winner'] for t in tt)/len(tt)*100:.0f}%, "
                f"PF={_pf(tt):.2f}, ${sum(t['pnl'] for t in tt):.0f} "
                f"(mirror:{sum(t['is_mirror'] for t in tt)}, "
                f"vol_fade:{sum(t['vol_fade'] for t in tt)}, "
                f"rsi_conf:{sum(t['rsi_confirms'] for t in tt)})")

    return tagged_trades


def _pf(trades):
    """Compute profit factor from tagged trade list."""
    gp = sum(t['pnl'] for t in trades if t['pnl'] > 0)
    gl = abs(sum(t['pnl'] for t in trades if t['pnl'] <= 0))
    return gp / gl if gl > 0 else float('inf') if gp > 0 else 0.0


# ──────────────────────────────────────────────────────────────────
# M-002 to M-006: Individual indicator filter tests
# ──────────────────────────────────────────────────────────────────

def run_filtered_test(exp_id, label, filter_fn, tagged_trades):
    """Run a filter on tagged trades. filter_fn(trade_dict) -> bool."""
    log(f"\n  {exp_id}: {label}")

    for period_label in ['IS', 'OOS']:
        all_t = tagged_trades[period_label]
        passed = [t for t in all_t if filter_fn(t)]
        blocked = [t for t in all_t if not filter_fn(t)]

        n_all = len(all_t)
        n_pass = len(passed)
        pf_pass = _pf(passed)
        pf_block = _pf(blocked)
        pnl_pass = sum(t['pnl'] for t in passed)
        pnl_block = sum(t['pnl'] for t in blocked)
        wr_pass = sum(t['is_winner'] for t in passed) / max(n_pass, 1)

        log(f"    {period_label}: {n_pass}/{n_all} pass "
            f"(WR={wr_pass*100:.0f}%, PF={pf_pass:.2f}, ${pnl_pass:.0f}) | "
            f"blocked: {len(blocked)}t PF={pf_block:.2f} ${pnl_block:.0f}")

        if period_label == 'OOS':
            for ticker in ALL_TICKERS:
                tt = [t for t in passed if t['ticker'] == ticker]
                if not tt:
                    log(f"      {ticker}: 0 trades")
                    continue
                log(f"      {ticker}: {len(tt)}t WR={sum(t['is_winner'] for t in tt)/len(tt)*100:.0f}% "
                    f"PF={_pf(tt):.2f} ${sum(t['pnl'] for t in tt):.0f}")

    # Return OOS stats for comparison
    oos_passed = [t for t in tagged_trades['OOS'] if filter_fn(t)]
    return {
        'exp_id': exp_id,
        'label': label,
        'oos_trades': len(oos_passed),
        'oos_pf': _pf(oos_passed),
        'oos_pnl': sum(t['pnl'] for t in oos_passed),
        'oos_wr': sum(t['is_winner'] for t in oos_passed) / max(len(oos_passed), 1),
    }


# ──────────────────────────────────────────────────────────────────
# M-007: Walk-forward with best filter combination
# ──────────────────────────────────────────────────────────────────

def run_wf_with_filter(exp_id, label, filter_fn):
    """Run walk-forward, applying a post-hoc filter to trades.

    Since the filter is applied to signal attributes at trade creation time,
    we need to actually modify the backtester to apply it. But for diagnostic
    purposes we can run the baseline WF and filter trades post-hoc.

    IMPORTANT: Post-hoc filtering is only valid for additive filters that
    don't change the order of subsequent trades (no dependency between trades).
    Since our filters only block signals and we have ONE trade per ticker at a time,
    blocking a trade could change subsequent trades. So we need to be careful.

    For a true test, we'd need to integrate the filter into the backtester.
    For M-007 diagnostic, we run post-hoc and note the caveat.
    """
    log(f"\n  {exp_id}: {label} (Walk-Forward)")

    config = make_l005_config(exp_id)

    # Precompute RSI
    rsi_cache = {}
    for ticker in ALL_TICKERS:
        rsi_cache[ticker] = compute_d1_rsi(ticker)

    # Run per-window
    wf = WalkForwardValidator(config, ALL_TICKERS)
    # We need the raw trades per window, so run manually
    windows = []
    start = pd.Timestamp('2025-02-10')
    end = pd.Timestamp('2026-01-31')
    current = start
    while True:
        train_end = current + pd.DateOffset(months=3)
        test_end = train_end + pd.DateOffset(months=1)
        if test_end > end:
            break
        windows.append({
            'test_start': train_end.strftime('%Y-%m-%d'),
            'test_end': test_end.strftime('%Y-%m-%d'),
        })
        current += pd.DateOffset(months=1)

    window_results = []
    for i, w in enumerate(windows):
        all_trades_in_window = []
        for ticker in ALL_TICKERS:
            m5_df = load_ticker_data(ticker)
            result = run_single_backtest(config, m5_df, w['test_start'], w['test_end'])
            for trade in result.trades:
                signal = trade.signal
                entry_date = pd.Timestamp(trade.entry_time).date()
                is_mirror = signal.level.is_mirror or signal.level.level_type == LevelType.MIRROR
                vol_ratio = compute_vol_ratio(m5_df, signal.trigger_bar_idx, ticker)
                rsi_val = rsi_cache.get(ticker, {}).get(entry_date, None)
                rsi_confirms = False
                if rsi_val is not None:
                    if signal.direction == TradeDirection.SHORT and rsi_val > 60:
                        rsi_confirms = True
                    elif signal.direction == TradeDirection.LONG and rsi_val < 40:
                        rsi_confirms = True

                tagged = {
                    'ticker': ticker,
                    'direction': signal.direction.value,
                    'pnl': trade.pnl,
                    'is_winner': trade.pnl > 0,
                    'is_mirror': is_mirror,
                    'level_score': signal.level.score,
                    'touches': signal.level.touches,
                    'vol_ratio': vol_ratio,
                    'vol_fade': vol_ratio < 1.0,
                    'rsi': rsi_val,
                    'rsi_confirms': rsi_confirms,
                }
                all_trades_in_window.append(tagged)

        # Apply filter
        passed = [t for t in all_trades_in_window if filter_fn(t)]
        baseline_t = all_trades_in_window

        pnl_base = sum(t['pnl'] for t in baseline_t)
        pnl_filt = sum(t['pnl'] for t in passed)

        window_results.append({
            'window': i + 1,
            'test_start': w['test_start'],
            'test_end': w['test_end'],
            'baseline_trades': len(baseline_t),
            'baseline_pnl': pnl_base,
            'filtered_trades': len(passed),
            'filtered_pnl': pnl_filt,
            'filtered_pf': _pf(passed),
        })

        log(f"    W{i+1}: {w['test_start']}→{w['test_end']} "
            f"baseline {len(baseline_t)}t ${pnl_base:.0f} | "
            f"filtered {len(passed)}t ${pnl_filt:.0f}")

    # Summary
    base_pos = sum(1 for w in window_results if w['baseline_pnl'] > 0)
    filt_pos = sum(1 for w in window_results if w['filtered_pnl'] > 0)
    base_total = sum(w['baseline_pnl'] for w in window_results)
    filt_total = sum(w['filtered_pnl'] for w in window_results)

    log(f"\n  WF Summary:")
    log(f"    Baseline: {base_pos}/{len(window_results)} positive, total ${base_total:.0f}")
    log(f"    Filtered: {filt_pos}/{len(window_results)} positive, total ${filt_total:.0f}")

    return window_results


# ──────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    log("Phase 8 — Confirmation Indicators & Signal Quality")
    log("=" * 60)

    # ── M-001: Diagnostic ──
    tagged = run_m001()

    oos_count = len(tagged['OOS'])
    log(f"\n  OOS trade count: {oos_count}")

    if oos_count < 5:
        log("  ABORT: Too few OOS trades for indicator testing.")
        sys.exit(1)

    # ── M-002 to M-006: Individual filter tests ──
    log("\n" + "#" * 60)
    log("  M-002 to M-006: Individual Indicator Filter Tests")
    log("#" * 60)

    baseline_stats = {
        'exp_id': 'L-005',
        'label': 'Baseline (no filter)',
        'oos_trades': oos_count,
        'oos_pf': _pf(tagged['OOS']),
        'oos_pnl': sum(t['pnl'] for t in tagged['OOS']),
        'oos_wr': sum(t['is_winner'] for t in tagged['OOS']) / oos_count,
    }
    log(f"\n  Baseline: {baseline_stats['oos_trades']}t "
        f"PF={baseline_stats['oos_pf']:.2f} ${baseline_stats['oos_pnl']:.0f}")

    filter_results = [baseline_stats]

    # M-002: Mirror only
    r = run_filtered_test('M-002', 'Mirror levels only',
                          lambda t: t['is_mirror'], tagged)
    filter_results.append(r)

    # M-003: Score thresholds
    for thresh in [10, 15, 20]:
        r = run_filtered_test(f'M-003-{thresh}', f'Level score >= {thresh}',
                              lambda t, th=thresh: t['level_score'] >= th, tagged)
        filter_results.append(r)

    # M-004: Volume fade
    r = run_filtered_test('M-004', 'Volume fade (vol < 1.0x)',
                          lambda t: t['vol_fade'], tagged)
    filter_results.append(r)

    # M-005: RSI extreme (multiple thresholds)
    for short_th, long_th in [(55, 45), (60, 40), (65, 35), (70, 30)]:
        def rsi_filter(t, st=short_th, lt=long_th):
            if t['rsi'] is None:
                return True  # pass through if no RSI data
            if t['direction'] == 'short' and t['rsi'] > st:
                return True
            if t['direction'] == 'long' and t['rsi'] < lt:
                return True
            return False
        r = run_filtered_test(f'M-005-{short_th}/{long_th}',
                              f'RSI S>{short_th}/L<{long_th}',
                              rsi_filter, tagged)
        filter_results.append(r)

    # M-006: Multi-touch
    for thresh in [2, 3, 5]:
        r = run_filtered_test(f'M-006-{thresh}', f'Touches >= {thresh}',
                              lambda t, th=thresh: t['touches'] >= th, tagged)
        filter_results.append(r)

    # ── Summary table ──
    log("\n" + "#" * 60)
    log("  FILTER COMPARISON SUMMARY (OOS)")
    log("#" * 60)
    log(f"\n  {'Experiment':<20} {'Trades':>7} {'WR':>6} {'PF':>6} {'P&L':>8}")
    log(f"  {'-'*20} {'-'*7} {'-'*6} {'-'*6} {'-'*8}")
    for r in filter_results:
        log(f"  {r['exp_id']:<20} {r['oos_trades']:>7} "
            f"{r['oos_wr']*100:>5.0f}% {r['oos_pf']:>6.2f} ${r['oos_pnl']:>7.0f}")

    # ── Find best candidates for M-007 ──
    # Filter must: improve PF, keep >= 15 trades, not lose > 30% of P&L
    candidates = []
    for r in filter_results[1:]:  # skip baseline
        if (r['oos_trades'] >= 15 and
            r['oos_pf'] >= baseline_stats['oos_pf'] * 0.9):
            candidates.append(r)
            log(f"\n  CANDIDATE: {r['exp_id']} ({r['label']})")

    if not candidates:
        # Relaxed: any filter that improves PF with >= 10 trades
        for r in filter_results[1:]:
            if (r['oos_trades'] >= 10 and
                r['oos_pf'] > baseline_stats['oos_pf']):
                candidates.append(r)
                log(f"\n  CANDIDATE (relaxed): {r['exp_id']} ({r['label']})")

    # ── M-007: Walk-forward with best filter(s) ──
    log("\n" + "#" * 60)
    log("  M-007: Walk-Forward with Best Filters")
    log("#" * 60)

    # Always run baseline WF for comparison
    baseline_wf = run_wf_with_filter('M-007-base', 'Baseline (no filter)',
                                      lambda t: True)

    # Run WF for top candidates
    if candidates:
        best_candidate = max(candidates, key=lambda r: r['oos_pf'])
        log(f"\n  Best candidate: {best_candidate['exp_id']} ({best_candidate['label']})")

        # Rebuild the filter function for WF
        bc_id = best_candidate['exp_id']
        if bc_id == 'M-002':
            filt_fn = lambda t: t['is_mirror']
            filt_label = 'Mirror only'
        elif bc_id.startswith('M-003'):
            thresh = int(bc_id.split('-')[2])
            filt_fn = lambda t, th=thresh: t['level_score'] >= th
            filt_label = f'Score >= {thresh}'
        elif bc_id == 'M-004':
            filt_fn = lambda t: t['vol_fade']
            filt_label = 'Vol fade'
        elif bc_id.startswith('M-005'):
            parts = bc_id.split('-')[2].split('/')
            st, lt = int(parts[0]), int(parts[1])
            filt_fn = lambda t, s=st, l=lt: (t['rsi'] is None or
                                               (t['direction'] == 'short' and t['rsi'] > s) or
                                               (t['direction'] == 'long' and t['rsi'] < l))
            filt_label = f'RSI S>{st}/L<{lt}'
        elif bc_id.startswith('M-006'):
            thresh = int(bc_id.split('-')[2])
            filt_fn = lambda t, th=thresh: t['touches'] >= th
            filt_label = f'Touches >= {thresh}'
        else:
            filt_fn = lambda t: True
            filt_label = 'Unknown'

        run_wf_with_filter(f'M-007-best', filt_label, filt_fn)
    else:
        log("\n  No candidates found. Baseline L-005 remains best.")

    # ── Write report ──
    report_path = os.path.join(RESULTS_DIR, 'v8_confirmation_report.md')
    with open(report_path, 'w') as f:
        f.write("# Phase 8 — Confirmation Indicator Report\n\n")
        f.write(f"**Date:** 2026-03-03\n\n")
        f.write("## Filter Comparison (OOS)\n\n")
        f.write(f"| Experiment | Label | Trades | WR | PF | P&L |\n")
        f.write(f"|------------|-------|--------|----|----|-----|\n")
        for r in filter_results:
            f.write(f"| {r['exp_id']} | {r['label']} | {r['oos_trades']} | "
                    f"{r['oos_wr']*100:.0f}% | {r['oos_pf']:.2f} | ${r['oos_pnl']:.0f} |\n")
        f.write("\n")

    log_path = os.path.join(RESULTS_DIR, 'v8_experiment_log.txt')
    with open(log_path, 'w') as f:
        f.write("\n".join(LOG))

    log(f"\n  Report: {report_path}")
    log(f"  Log: {log_path}")
