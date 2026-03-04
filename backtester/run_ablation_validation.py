"""
Phase 2.6b — Ablation Validation: Simplified Filter Chain

Based on Phase 2.6 ablation results, test 3 simplified configurations
through the same 6-window walk-forward to see if removing zero-impact
filters improves or hurts OOS performance.

CONFIG A — "Simplified" (keep only proven filters):
  KEEP: Same-level limit (anti-sawing 5/30)
  KEEP: Regime filters (ADX<=27, ATR ratio<=1.3)
  KEEP: Open delay, time filter (session policy)
  KEEP: Risk sizing (stop cap, position sizing — core, not filter)
  REMOVE: Earnings filter, ATR energy gate, Volume VSA, R:R filter, Squeeze

CONFIG B — "Simplified + No Squeeze" (confirm squeeze removal):
  Identical to Config A — squeeze is already removed in A.
  This exists to double-confirm by running the exact same config.

CONFIG C — "Minimal" (nuclear + same-level limit only):
  Pattern detection + risk sizing + same-level limit
  All other filters removed (including regime post-filters)
  Tests whether same-level limit alone captures most filter value.

REFERENCE:
  BASELINE  = 54 OOS trades, PF 2.60, +$4,355
  NUCLEAR   = 84 OOS trades, PF 1.72, +$3,101
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import json
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from backtester.backtester import Backtester, BacktestConfig
from backtester.core.level_detector import LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngineConfig
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig
from backtester.core.intraday_levels import IntradayLevelConfig
from backtester.optimizer import load_ticker_data

# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

TICKERS = ['TSLA', 'AMZN', 'GOOGL', 'META', 'MSFT', 'NVDA']
FULL_START = '2025-02-10'
FULL_END = '2026-01-31'
TRAIN_MONTHS = 3
TEST_MONTHS = 1
MAX_WINDOWS = 6

ADX_THRESHOLD = 27
ATR_RATIO_THRESHOLD = 1.3
CAPITAL = 100_000.0

LOG = []


def log(msg=''):
    LOG.append(msg)
    print(msg)


# ═══════════════════════════════════════════════════════════════════════════
# INDICATOR CALCULATIONS
# ═══════════════════════════════════════════════════════════════════════════

def compute_atr_series(daily, period=14):
    high = daily['High'].values
    low = daily['Low'].values
    close = daily['Close'].values
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(high - low,
                    np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    return pd.Series(tr, index=daily.index).rolling(window=period, min_periods=1).mean()


def compute_adx(daily, period=14):
    high = daily['High'].values.astype(float)
    low = daily['Low'].values.astype(float)
    close = daily['Close'].values.astype(float)
    n = len(high)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)
    for i in range(1, n):
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]),
                     abs(low[i] - close[i - 1]))

    def wilder_smooth(arr, p):
        out = np.zeros(len(arr))
        if p < len(arr):
            out[p] = np.sum(arr[1:p + 1])
            for i in range(p + 1, len(arr)):
                out[i] = out[i - 1] - out[i - 1] / p + arr[i]
        return out

    smooth_tr = wilder_smooth(tr, period)
    smooth_plus_dm = wilder_smooth(plus_dm, period)
    smooth_minus_dm = wilder_smooth(minus_dm, period)
    plus_di = np.zeros(n)
    minus_di = np.zeros(n)
    dx = np.zeros(n)
    for i in range(period, n):
        if smooth_tr[i] > 0:
            plus_di[i] = 100 * smooth_plus_dm[i] / smooth_tr[i]
            minus_di[i] = 100 * smooth_minus_dm[i] / smooth_tr[i]
        di_sum = plus_di[i] + minus_di[i]
        if di_sum > 0:
            dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / di_sum
    adx = np.zeros(n)
    start = 2 * period
    if start < n:
        adx[start] = np.mean(dx[period:start + 1])
        for i in range(start + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
    return pd.Series(adx, index=daily.index)


def aggregate_m5_to_daily(m5_df):
    df = m5_df.copy()
    df['Datetime'] = pd.to_datetime(df['Datetime'])
    minutes = df['Datetime'].dt.hour * 60 + df['Datetime'].dt.minute
    rth_mask = (minutes >= 16 * 60 + 30) & (minutes < 23 * 60)
    rth = df[rth_mask].copy()
    rth['Date'] = rth['Datetime'].dt.date
    daily = rth.groupby('Date').agg(
        Open=('Open', 'first'), High=('High', 'max'),
        Low=('Low', 'min'), Close=('Close', 'last'),
        Volume=('Volume', 'sum'),
    ).reset_index()
    daily['Date'] = pd.to_datetime(daily['Date'])
    return daily


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG BUILDERS
# ═══════════════════════════════════════════════════════════════════════════

def _base_config(name, filter_overrides=None, level_overrides=None,
                 risk_overrides=None):
    """Build a BacktestConfig with selective overrides."""
    fo = filter_overrides or {}
    lo = level_overrides or {}
    ro = risk_overrides or {}

    return BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=lo.get('fractal_depth', 10),
            tolerance_cents=0.05,
            tolerance_pct=0.001,
            atr_period=5,
            min_level_score=lo.get('min_level_score', 5),
            cross_count_invalidate=lo.get('cross_count_invalidate', 5),
            cross_count_window=lo.get('cross_count_window', 30),
        ),
        pattern_config=PatternEngineConfig(
            tail_ratio_min=0.15,
            lp2_engulfing_required=True,
            clp_min_bars=3,
            clp_max_bars=7,
        ),
        filter_config=FilterChainConfig(
            atr_block_threshold=fo.get('atr_block_threshold', 0.20),
            atr_entry_threshold=fo.get('atr_entry_threshold', 0.60),
            enable_volume_filter=fo.get('enable_volume_filter', True),
            enable_time_filter=fo.get('enable_time_filter', True),
            enable_squeeze_filter=fo.get('enable_squeeze_filter', True),
            open_delay_minutes=fo.get('open_delay_minutes', 5),
            earnings_dates=fo.get('earnings_dates', {}),
        ),
        risk_config=RiskManagerConfig(
            min_rr=ro.get('min_rr', 2.0),
            max_stop_atr_pct=0.15,
            capital=CAPITAL,
            risk_pct=0.003,
        ),
        trade_config=TradeManagerConfig(
            slippage_per_share=0.02,
            partial_tp_at_r=2.0,
            partial_tp_pct=0.50,
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
        name=name,
    )


def make_baseline():
    """Phase 2.5 BASELINE: all filters on."""
    return _base_config('BASELINE')


def make_config_a():
    """CONFIG A — Simplified: keep proven filters, remove zero-impact ones.

    KEEP:  time filter (open delay + session policy), same-level limit, regime post-filters
    REMOVE: earnings (zero impact), ATR energy gate (zero impact),
            volume VSA (zero impact), R:R filter (zero impact),
            squeeze (possibly suppressive)
    """
    return _base_config(
        'Config_A_Simplified',
        filter_overrides={
            'earnings_dates': {},          # no-op (already empty), explicit
            'atr_block_threshold': 0.0,    # disable ATR energy gate
            'atr_entry_threshold': 0.0,    # disable ATR energy gate
            'enable_volume_filter': False,  # disable VSA
            'enable_squeeze_filter': False, # disable squeeze
            'enable_time_filter': True,     # KEEP session policy
            'open_delay_minutes': 5,        # KEEP open delay
        },
        risk_overrides={
            'min_rr': 0.01,  # effectively disable R:R filter
        },
    )


def make_config_b():
    """CONFIG B — Identical to Config A (squeeze already removed).

    This exists purely as confirmation that A and B produce the same result,
    validating that squeeze removal is correctly captured in A.
    """
    return _base_config(
        'Config_B_Simplified_NoSqueeze',
        filter_overrides={
            'earnings_dates': {},
            'atr_block_threshold': 0.0,
            'atr_entry_threshold': 0.0,
            'enable_volume_filter': False,
            'enable_squeeze_filter': False,
            'enable_time_filter': True,
            'open_delay_minutes': 5,
        },
        risk_overrides={
            'min_rr': 0.01,
        },
    )


def make_config_c():
    """CONFIG C — Minimal: nuclear + only same-level limit.

    Pattern detection + risk sizing + same-level limit ONLY.
    All filter chain filters disabled. No regime post-filters.
    """
    return _base_config(
        'Config_C_Minimal',
        filter_overrides={
            'earnings_dates': {},
            'atr_block_threshold': 0.0,
            'atr_entry_threshold': 0.0,
            'enable_volume_filter': False,
            'enable_squeeze_filter': False,
            'enable_time_filter': False,     # disable all time checks
            'open_delay_minutes': 0,
        },
        risk_overrides={
            'min_rr': 0.01,
        },
        # same-level limit stays at default 5/30
    )


def make_nuclear():
    """NUCLEAR reference: all filters removed including same-level limit."""
    return _base_config(
        'NUCLEAR',
        filter_overrides={
            'earnings_dates': {},
            'atr_block_threshold': 0.0,
            'atr_entry_threshold': 0.0,
            'enable_volume_filter': False,
            'enable_squeeze_filter': False,
            'enable_time_filter': False,
            'open_delay_minutes': 0,
        },
        level_overrides={
            'cross_count_invalidate': 999,  # disable same-level limit
        },
        risk_overrides={
            'min_rr': 0.01,
        },
    )


# ═══════════════════════════════════════════════════════════════════════════
# TRADE EXTRACTION + METRICS
# ═══════════════════════════════════════════════════════════════════════════

def run_and_get_trades(config, tickers, start_date, end_date):
    all_trades = []
    for ticker in tickers:
        m5_df = load_ticker_data(ticker)
        bt = Backtester(config)
        result = bt.run(m5_df, start_date=start_date, end_date=end_date)
        for trade in result.trades:
            all_trades.append({
                'ticker': trade.signal.ticker,
                'entry_time': trade.entry_time,
                'entry_date': trade.entry_time.normalize().date() if trade.entry_time else None,
                'exit_time': trade.exit_time,
                'direction': trade.direction.value,
                'entry_price': trade.entry_price,
                'exit_price': trade.exit_price,
                'pnl': trade.pnl,
                'pnl_r': trade.pnl_r,
                'is_winner': trade.pnl > 0,
                'position_size': trade.position_size,
            })
    return pd.DataFrame(all_trades) if all_trades else pd.DataFrame()


def apply_regime_filters(trades_df, daily_data, adx_thresh=None, atr_thresh=None):
    if trades_df.empty:
        return trades_df
    filtered = trades_df.copy()

    if adx_thresh is not None:
        adx_vals = []
        for _, trade in filtered.iterrows():
            ticker = trade['ticker']
            entry_date = pd.Timestamp(trade['entry_date'])
            if ticker in daily_data:
                d = daily_data[ticker]
                prior = d[d['Date'] <= entry_date]
                val = prior['ADX'].iloc[-1] if not prior.empty and prior['ADX'].iloc[-1] > 0 else np.nan
                adx_vals.append(val)
            else:
                adx_vals.append(np.nan)
        filtered['ADX'] = adx_vals
        filtered = filtered.dropna(subset=['ADX'])
        filtered = filtered[filtered['ADX'] <= adx_thresh]

    if atr_thresh is not None:
        atr_vals = []
        for _, trade in filtered.iterrows():
            ticker = trade['ticker']
            entry_date = pd.Timestamp(trade['entry_date'])
            if ticker in daily_data:
                d = daily_data[ticker]
                prior = d[d['Date'] <= entry_date]
                val = prior['ATR_ratio_5_20'].iloc[-1] if not prior.empty else np.nan
                atr_vals.append(val)
            else:
                atr_vals.append(np.nan)
        filtered['ATR_ratio'] = atr_vals
        filtered = filtered.dropna(subset=['ATR_ratio'])
        filtered = filtered[filtered['ATR_ratio'] <= atr_thresh]

    return filtered


def compute_full_metrics(trades_df):
    """Compute comprehensive metrics: trades, WR, PF, P&L, Sharpe, MaxDD."""
    if trades_df.empty:
        return {
            'trades': 0, 'wr': 0.0, 'pf': 0.0, 'pnl': 0.0,
            'sharpe': 0.0, 'max_dd': 0.0, 'avg_pnl': 0.0,
            'gross_profit': 0.0, 'gross_loss': 0.0,
        }

    n = len(trades_df)
    winners = trades_df[trades_df['pnl'] > 0]
    losers = trades_df[trades_df['pnl'] <= 0]
    gp = winners['pnl'].sum()
    gl = abs(losers['pnl'].sum())
    pf = gp / gl if gl > 0 else (float('inf') if gp > 0 else 0.0)
    pnl = trades_df['pnl'].sum()
    avg_pnl = pnl / n

    # Max drawdown from trade-level cumulative P&L
    cum_pnl = trades_df['pnl'].cumsum()
    peak = cum_pnl.cummax()
    dd = peak - cum_pnl
    max_dd = dd.max() if len(dd) > 0 else 0.0

    # Sharpe: per-trade P&L as returns on capital
    trade_returns = trades_df['pnl'].values / CAPITAL
    if len(trade_returns) > 1 and np.std(trade_returns, ddof=1) > 0:
        sharpe = (np.mean(trade_returns) / np.std(trade_returns, ddof=1)) * np.sqrt(252)
    else:
        sharpe = 0.0

    return {
        'trades': n,
        'wr': len(winners) / n,
        'pf': pf,
        'pnl': pnl,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'avg_pnl': avg_pnl,
        'gross_profit': gp,
        'gross_loss': gl,
    }


def fmt_pf(pf):
    return f"{pf:.2f}" if pf != float('inf') else "inf"


# ═══════════════════════════════════════════════════════════════════════════
# WINDOW GENERATION
# ═══════════════════════════════════════════════════════════════════════════

def generate_windows():
    start = pd.Timestamp(FULL_START)
    end = pd.Timestamp(FULL_END)
    windows = []
    current = start
    while True:
        train_end = current + pd.DateOffset(months=TRAIN_MONTHS)
        test_end = train_end + pd.DateOffset(months=TEST_MONTHS)
        if test_end > end:
            break
        windows.append({
            'train_start': current.strftime('%Y-%m-%d'),
            'train_end': train_end.strftime('%Y-%m-%d'),
            'test_start': train_end.strftime('%Y-%m-%d'),
            'test_end': test_end.strftime('%Y-%m-%d'),
        })
        current += pd.DateOffset(months=TEST_MONTHS)
        if MAX_WINDOWS and len(windows) >= MAX_WINDOWS:
            break
    return windows


# ═══════════════════════════════════════════════════════════════════════════
# WALK-FORWARD ENGINE
# ═══════════════════════════════════════════════════════════════════════════

def run_walkforward(label, config, daily_data, windows,
                    use_adx=True, use_atr_ratio=True):
    """Run 6-window walk-forward and return detailed results."""
    adx_thresh = ADX_THRESHOLD if use_adx else None
    atr_thresh = ATR_RATIO_THRESHOLD if use_atr_ratio else None

    window_results = []
    all_trades_combined = []

    for wi, w in enumerate(windows):
        trades = run_and_get_trades(config, TICKERS,
                                     w['test_start'], w['test_end'])
        filtered = apply_regime_filters(trades, daily_data,
                                         adx_thresh=adx_thresh,
                                         atr_thresh=atr_thresh)
        m = compute_full_metrics(filtered)
        window_results.append({
            'window': wi + 1,
            'test_start': w['test_start'],
            'test_end': w['test_end'],
            **m,
        })
        if not filtered.empty:
            all_trades_combined.append(filtered)

    # Compute aggregate metrics from combined trade list
    if all_trades_combined:
        combined_df = pd.concat(all_trades_combined, ignore_index=True)
        agg = compute_full_metrics(combined_df)
    else:
        combined_df = pd.DataFrame()
        agg = compute_full_metrics(pd.DataFrame())

    # Window-level Sharpe (from per-window P&L)
    window_pnls = np.array([w['pnl'] for w in window_results])
    window_returns = window_pnls / CAPITAL
    if len(window_returns) > 1 and np.std(window_returns, ddof=1) > 0:
        window_sharpe = (np.mean(window_returns) / np.std(window_returns, ddof=1)) * np.sqrt(12)
    else:
        window_sharpe = 0.0

    return {
        'label': label,
        'window_results': window_results,
        'agg': agg,
        'window_sharpe': window_sharpe,
        'window_pnls': window_pnls,
        'positive_windows': sum(1 for w in window_results if w['pnl'] > 0),
    }


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    total_start = time.time()

    log("=" * 90)
    log("  PHASE 2.6b — ABLATION VALIDATION: Simplified Filter Chain")
    log("=" * 90)
    log(f"  6-window walk-forward, FD=10, fixed params, 6 tickers, BOTH directions")
    log(f"  Period: {FULL_START} -> {FULL_END}")
    log(f"  Reference BASELINE: 54 OOS trades, PF 2.60, +$4,355")
    log(f"  Reference NUCLEAR:  84 OOS trades, PF 1.72, +$3,101")
    log("")

    # ── Step 1: Precompute daily indicators ───────────────────────────
    log("  Step 1: Loading data and computing indicators...")
    daily_data = {}
    for ticker in TICKERS:
        m5_df = load_ticker_data(ticker)
        daily = aggregate_m5_to_daily(m5_df)
        daily['ADX'] = compute_adx(daily, period=14)
        daily['ATR5'] = compute_atr_series(daily, period=5)
        daily['ATR20'] = compute_atr_series(daily, period=20)
        daily['ATR_ratio_5_20'] = daily['ATR5'] / daily['ATR20'].replace(0, np.nan)
        daily['ATR_ratio_5_20'] = daily['ATR_ratio_5_20'].fillna(1.0)
        daily_data[ticker] = daily
        log(f"    {ticker}: {len(daily)} days")

    windows = generate_windows()
    log(f"\n  Walk-forward windows: {len(windows)}")
    for i, w in enumerate(windows):
        log(f"    W{i+1}: Test {w['test_start']} -> {w['test_end']}")

    # ── Step 2: Define and run all configurations ─────────────────────
    configs = [
        {
            'label': 'BASELINE (all filters)',
            'config': make_baseline(),
            'use_adx': True,
            'use_atr_ratio': True,
        },
        {
            'label': 'Config A — Simplified',
            'config': make_config_a(),
            'use_adx': True,
            'use_atr_ratio': True,
        },
        {
            'label': 'Config B — Simplified+NoSqueeze',
            'config': make_config_b(),
            'use_adx': True,
            'use_atr_ratio': True,
        },
        {
            'label': 'Config C — Minimal (nuclear+sawing)',
            'config': make_config_c(),
            'use_adx': False,
            'use_atr_ratio': False,
        },
        {
            'label': 'NUCLEAR (reference)',
            'config': make_nuclear(),
            'use_adx': False,
            'use_atr_ratio': False,
        },
    ]

    results = []

    log(f"\n  Step 2: Running {len(configs)} configurations...")
    log(f"{'━' * 90}")

    for ci, cfg in enumerate(configs):
        run_start = time.time()
        log(f"\n  {'─' * 86}")
        log(f"  [{ci}] {cfg['label']}")
        log(f"  {'─' * 86}")

        r = run_walkforward(
            label=cfg['label'],
            config=cfg['config'],
            daily_data=daily_data,
            windows=windows,
            use_adx=cfg['use_adx'],
            use_atr_ratio=cfg['use_atr_ratio'],
        )

        elapsed = time.time() - run_start

        # Per-window detail
        log(f"  {'Window':>8} {'Trades':>7} {'WR':>7} {'PF':>7} {'P&L':>10} {'MaxDD':>8} {'Sharpe':>8}")
        log(f"  {'─' * 58}")
        for wr in r['window_results']:
            log(f"  W{wr['window']:>6}  {wr['trades']:>6}  {wr['wr']*100:>5.1f}%  "
                f"{fmt_pf(wr['pf']):>6}  ${wr['pnl']:>8,.0f}  ${wr['max_dd']:>6,.0f}  "
                f"{wr['sharpe']:>7.2f}")

        agg = r['agg']
        log(f"  {'─' * 58}")
        log(f"  {'TOTAL':>8}  {agg['trades']:>6}  {agg['wr']*100:>5.1f}%  "
            f"{fmt_pf(agg['pf']):>6}  ${agg['pnl']:>8,.0f}  ${agg['max_dd']:>6,.0f}  "
            f"{agg['sharpe']:>7.2f}")
        log(f"  Window Sharpe (annualized): {r['window_sharpe']:.2f}")
        log(f"  Positive windows: {r['positive_windows']}/{len(windows)}")
        log(f"  Avg P&L per trade: ${agg['avg_pnl']:.0f}")
        log(f"  [{elapsed:.1f}s]")

        results.append(r)

    # ── Step 3: Comparison Table ──────────────────────────────────────
    baseline_r = results[0]
    nuclear_r = results[4]
    baseline_pnl = baseline_r['agg']['pnl']
    nuclear_pnl = nuclear_r['agg']['pnl']

    log(f"\n\n{'=' * 90}")
    log(f"  COMPARISON TABLE")
    log(f"{'=' * 90}")

    header = (f"  {'Config':<35} {'Trades':>7} {'WR':>6} {'PF':>6} "
              f"{'P&L':>10} {'Sharpe':>7} {'MaxDD':>8} "
              f"{'vs BASE':>10} {'vs NUC':>10}")
    log(f"\n{header}")
    log(f"  {'─' * 102}")

    for r in results:
        a = r['agg']
        delta_base = a['pnl'] - baseline_pnl
        delta_nuc = a['pnl'] - nuclear_pnl

        if r['label'] == baseline_r['label']:
            db_str = "—"
        else:
            db_str = f"{'+'if delta_base>=0 else ''}${delta_base:,.0f}"

        if r['label'] == nuclear_r['label']:
            dn_str = "—"
        else:
            dn_str = f"{'+'if delta_nuc>=0 else ''}${delta_nuc:,.0f}"

        log(f"  {r['label']:<35} {a['trades']:>7} {a['wr']*100:>5.1f}% "
            f"{fmt_pf(a['pf']):>6} ${a['pnl']:>8,.0f} {a['sharpe']:>7.2f} "
            f"${a['max_dd']:>6,.0f} {db_str:>10} {dn_str:>10}")

    log(f"  {'─' * 102}")

    # ── Step 4: Window-by-Window Comparison ───────────────────────────
    log(f"\n{'=' * 90}")
    log(f"  WINDOW-BY-WINDOW P&L COMPARISON")
    log(f"{'=' * 90}")

    labels_short = ['BASE', 'Cfg A', 'Cfg B', 'Cfg C', 'NUCL']
    header_parts = [f"  {'Window':>8}"]
    for lbl in labels_short:
        header_parts.append(f"{lbl:>12}")
    log(''.join(header_parts))
    log(f"  {'─' * 72}")

    for wi in range(len(windows)):
        parts = [f"  W{wi+1:>6} "]
        for ri, r in enumerate(results):
            pnl = r['window_results'][wi]['pnl']
            parts.append(f"${pnl:>10,.0f}  ")
        log(''.join(parts))

    # Totals row
    parts = [f"  {'TOTAL':>8}"]
    for r in results:
        parts.append(f"${r['agg']['pnl']:>10,.0f}  ")
    log(f"  {'─' * 72}")
    log(''.join(parts))

    # ── Step 5: Analysis ──────────────────────────────────────────────
    log(f"\n{'=' * 90}")
    log(f"  ANALYSIS & CONCLUSIONS")
    log(f"{'=' * 90}")

    config_a = results[1]
    config_b = results[2]
    config_c = results[3]

    # A vs Baseline
    a_delta = config_a['agg']['pnl'] - baseline_pnl
    log(f"\n  CONFIG A (Simplified) vs BASELINE:")
    log(f"    P&L delta:   {'+'if a_delta>=0 else ''}${a_delta:,.0f}")
    log(f"    Trade delta: {config_a['agg']['trades'] - baseline_r['agg']['trades']:+d}")
    log(f"    PF:          {fmt_pf(config_a['agg']['pf'])} vs {fmt_pf(baseline_r['agg']['pf'])}")
    if a_delta >= 0:
        log(f"    >> Simplification HELPS or is neutral — zero-impact filters can be safely removed")
    else:
        log(f"    >> Simplification HURTS — some 'zero-impact' filters have interactive effects")

    # A == B confirmation
    ab_match = (config_a['agg']['trades'] == config_b['agg']['trades'] and
                abs(config_a['agg']['pnl'] - config_b['agg']['pnl']) < 1.0)
    log(f"\n  CONFIG A == CONFIG B (squeeze confirmation):")
    log(f"    Match: {'YES' if ab_match else 'NO'}")
    if ab_match:
        log(f"    >> Confirmed: A and B are identical — squeeze removal is correctly captured")
    else:
        log(f"    >> MISMATCH — investigate configuration differences")

    # C vs Nuclear (same-level limit value)
    c_delta_nuc = config_c['agg']['pnl'] - nuclear_pnl
    c_delta_base = config_c['agg']['pnl'] - baseline_pnl
    log(f"\n  CONFIG C (Minimal) vs NUCLEAR:")
    log(f"    P&L delta:   {'+'if c_delta_nuc>=0 else ''}${c_delta_nuc:,.0f}")
    log(f"    Trade delta: {config_c['agg']['trades'] - nuclear_r['agg']['trades']:+d}")
    if c_delta_nuc > 0:
        log(f"    >> Same-level limit alone adds ${c_delta_nuc:,.0f} to nuclear config")
    else:
        log(f"    >> Same-level limit hurts in isolation (unexpected)")

    log(f"\n  CONFIG C (Minimal) vs BASELINE:")
    log(f"    P&L delta:   {'+'if c_delta_base>=0 else ''}${c_delta_base:,.0f}")
    if c_delta_base > -500:
        log(f"    >> Same-level limit captures most of the filter chain's value")
    else:
        log(f"    >> Same-level limit alone is NOT enough — regime filters add significant value")

    # Recommended config
    log(f"\n  RECOMMENDATION:")
    best_r = max(results, key=lambda r: r['agg']['pnl'])
    log(f"    Best config: {best_r['label']}")
    log(f"    P&L: ${best_r['agg']['pnl']:,.0f}, PF: {fmt_pf(best_r['agg']['pf'])}, "
        f"Trades: {best_r['agg']['trades']}, Sharpe: {best_r['agg']['sharpe']:.2f}")

    if best_r == config_a or best_r == config_b:
        log(f"    >> SIMPLIFICATION VALIDATED — use simplified filter chain going forward")
    elif best_r == baseline_r:
        log(f"    >> Keep current filter chain — simplification doesn't improve results")
    else:
        log(f"    >> Minimal config outperforms — consider aggressive simplification")

    elapsed = time.time() - total_start
    log(f"\n{'=' * 90}")
    log(f"  COMPLETE — {elapsed:.0f}s ({elapsed/60:.1f}min)")
    log(f"{'=' * 90}")

    # ── Save results ──────────────────────────────────────────────────
    report_path = os.path.join(RESULTS_DIR, 'phase26b_ablation_validation.txt')
    with open(report_path, 'w') as f:
        f.write('\n'.join(LOG))
    log(f"\n  Report saved: {report_path}")

    json_results = []
    for r in results:
        a = r['agg']
        json_results.append({
            'label': r['label'],
            'trades': a['trades'],
            'wr': round(a['wr'], 4),
            'pf': round(float(a['pf']), 4) if a['pf'] != float('inf') else 'inf',
            'pnl': round(float(a['pnl']), 2),
            'sharpe_trade': round(float(a['sharpe']), 4),
            'sharpe_window': round(float(r['window_sharpe']), 4),
            'max_dd': round(float(a['max_dd']), 2),
            'positive_windows': r['positive_windows'],
            'window_pnls': [round(float(p), 2) for p in r['window_pnls']],
            'delta_vs_baseline': round(float(a['pnl'] - baseline_pnl), 2),
            'delta_vs_nuclear': round(float(a['pnl'] - nuclear_pnl), 2),
        })

    json_path = os.path.join(RESULTS_DIR, 'phase26b_ablation_validation.json')
    with open(json_path, 'w') as f:
        json.dump({
            'phase': '2.6b',
            'description': 'Ablation validation: simplified filter chain',
            'configs': {
                'baseline': 'All filters on (Phase 2.5)',
                'config_a': 'Simplified: remove earnings, ATR gate, volume, R:R, squeeze; keep regime + sawing',
                'config_b': 'Same as A (squeeze confirmation)',
                'config_c': 'Minimal: nuclear + same-level limit only (no regime post-filters)',
                'nuclear': 'All filters removed',
            },
            'results': json_results,
        }, f, indent=2)
    log(f"  JSON saved: {json_path}")


if __name__ == '__main__':
    main()
