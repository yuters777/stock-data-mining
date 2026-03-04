"""
Phase 2.6 — Ablation Study: Filter Chain Value Analysis

Run the 6-window walk-forward (fixed params, FD=10) with each filter
REMOVED one at a time to quantify each filter's contribution to P&L.

BASELINE (Phase 2.5 best config):
  FD=10, ATR_ENTRY=0.60, ATR_BLOCK=0.20, RR=2.0, TAIL=0.15, STOP=0.15
  SAWING=5/30, same-level limit=2
  ADX<=27, ATR expansion ratio<=1.3
  All 6 tickers, BOTH directions (no per-ticker direction filter)
  BASELINE = 54 OOS trades, PF 1.45, +$4,355

Ablation runs (remove ONE filter at a time):
  1. Earnings filter — set earnings_dates={}  (already empty in practice)
  2. Open delay — set open_delay_minutes=0
  3. Squeeze detection — disable squeeze filter
  4. Breakaway gap block — N/A (not implemented)
  5. ATR energy gate — set thresholds to 0 (pass everything)
  6. Volume VSA — disable volume filter
  7. R:R feasibility — set min_rr=0 (accept any R:R)
  8. Regime filters (combined) — disable ADX + ATR expansion post-filters
  9. Same-level limit — set cross_count_invalidate=999

Nuclear test:
 10. REMOVE ALL filters except core pattern detection + risk sizing
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import json
import numpy as np
import pandas as pd

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

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

TICKERS = ['TSLA', 'AMZN', 'GOOGL', 'META', 'MSFT', 'NVDA']
FULL_START = '2025-02-10'
FULL_END = '2026-01-31'
TRAIN_MONTHS = 3
TEST_MONTHS = 1
MAX_WINDOWS = 6

# Regime filter thresholds (Phase 2.5)
ADX_THRESHOLD = 27
ATR_RATIO_THRESHOLD = 1.3

LOG = []


def log(msg=''):
    LOG.append(msg)
    print(msg)


# ═══════════════════════════════════════════════════════════════════════════
# INDICATOR CALCULATIONS (reused from Phase 2.4)
# ═══════════════════════════════════════════════════════════════════════════

def compute_atr_series(daily, period=14):
    high = daily['High'].values
    low = daily['Low'].values
    close = daily['Close'].values
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close))
    )
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
# CONFIG BUILDER
# ═══════════════════════════════════════════════════════════════════════════

def make_baseline_config(name='Baseline', overrides=None):
    """Phase 2.5 baseline config: FD=10 + all filters enabled."""
    o = overrides or {}

    level_cfg = LevelDetectorConfig(
        fractal_depth=o.get('fractal_depth', 10),
        tolerance_cents=0.05,
        tolerance_pct=0.001,
        atr_period=5,
        min_level_score=o.get('min_level_score', 5),
        cross_count_invalidate=o.get('cross_count_invalidate', 5),
        cross_count_window=o.get('cross_count_window', 30),
    )

    pattern_cfg = PatternEngineConfig(
        tail_ratio_min=o.get('tail_ratio_min', 0.15),
        lp2_engulfing_required=True,
        clp_min_bars=3,
        clp_max_bars=7,
    )

    filter_cfg = FilterChainConfig(
        atr_block_threshold=o.get('atr_block_threshold', 0.20),
        atr_entry_threshold=o.get('atr_entry_threshold', 0.60),
        enable_volume_filter=o.get('enable_volume_filter', True),
        enable_time_filter=o.get('enable_time_filter', True),
        enable_squeeze_filter=o.get('enable_squeeze_filter', True),
        open_delay_minutes=o.get('open_delay_minutes', 5),
        earnings_dates=o.get('earnings_dates', {}),
    )

    risk_cfg = RiskManagerConfig(
        min_rr=o.get('min_rr', 2.0),
        max_stop_atr_pct=o.get('max_stop_atr_pct', 0.15),
        capital=100000.0,
        risk_pct=0.003,
    )

    trade_cfg = TradeManagerConfig(
        slippage_per_share=0.02,
        partial_tp_at_r=2.0,
        partial_tp_pct=0.50,
    )

    intraday_cfg = IntradayLevelConfig(
        fractal_depth_m5=5, fractal_depth_h1=3, enable_h1=True,
        min_target_r=1.0, lookback_bars=1000,
    )

    return BacktestConfig(
        level_config=level_cfg,
        pattern_config=pattern_cfg,
        filter_config=filter_cfg,
        risk_config=risk_cfg,
        trade_config=trade_cfg,
        intraday_config=intraday_cfg,
        tier_config={
            'mode': '2tier_trail', 't1_pct': 0.30, 'min_rr': 2.0,
            'trail_factor': 0.7, 'trail_activation_r': 0.0,
        },
        direction_filter=None,  # BOTH directions
        name=name,
    )


# ═══════════════════════════════════════════════════════════════════════════
# TRADE EXTRACTION + METRICS
# ═══════════════════════════════════════════════════════════════════════════

def run_and_get_trades(config, tickers, start_date, end_date):
    """Run backtest and return per-trade DataFrame."""
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


def compute_metrics(trades_df):
    """Compute standard trade metrics."""
    if trades_df.empty:
        return {'trades': 0, 'wr': 0.0, 'pf': 0.0, 'pnl': 0.0, 'max_dd': 0.0}
    n = len(trades_df)
    winners = trades_df[trades_df['pnl'] > 0]
    losers = trades_df[trades_df['pnl'] <= 0]
    gp = winners['pnl'].sum()
    gl = abs(losers['pnl'].sum())
    pf = gp / gl if gl > 0 else (float('inf') if gp > 0 else 0.0)
    pnl = trades_df['pnl'].sum()
    cum_pnl = trades_df['pnl'].cumsum()
    peak = cum_pnl.cummax()
    dd = peak - cum_pnl
    max_dd = dd.max() if len(dd) > 0 else 0
    return {'trades': n, 'wr': len(winners) / n, 'pf': pf, 'pnl': pnl, 'max_dd': max_dd}


def apply_regime_filters(trades_df, daily_data, adx_thresh=None, atr_thresh=None):
    """Apply ADX and/or ATR ratio post-filters."""
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
# ABLATION RUN ENGINE
# ═══════════════════════════════════════════════════════════════════════════

def run_walkforward_ablation(label, config, daily_data, windows,
                              use_adx=True, use_atr_ratio=True):
    """Run 6-window walk-forward with given config and optional regime filters.

    Returns dict with aggregate OOS metrics.
    """
    adx_thresh = ADX_THRESHOLD if use_adx else None
    atr_thresh = ATR_RATIO_THRESHOLD if use_atr_ratio else None

    window_results = []

    for wi, w in enumerate(windows):
        trades = run_and_get_trades(config, TICKERS,
                                     w['test_start'], w['test_end'])

        # Apply post-trade regime filters
        filtered = apply_regime_filters(trades, daily_data,
                                         adx_thresh=adx_thresh,
                                         atr_thresh=atr_thresh)
        m = compute_metrics(filtered)
        window_results.append({
            'window': wi + 1,
            'test_start': w['test_start'],
            'test_end': w['test_end'],
            **m,
        })

    # Aggregate
    total_trades = sum(w['trades'] for w in window_results)
    total_pnl = sum(w['pnl'] for w in window_results)
    positive_windows = sum(1 for w in window_results if w['pnl'] > 0)

    # Compute aggregate PF from window-level gross profit/loss
    all_window_pnls = [w['pnl'] for w in window_results]
    gross_profit = sum(p for p in all_window_pnls if p > 0)
    gross_loss = abs(sum(p for p in all_window_pnls if p < 0))
    agg_pf = gross_profit / gross_loss if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0.0)

    # Compute per-trade PF using individual window trade-level PFs is misleading,
    # so we'll re-run the full OOS aggregation to get true trade-level PF
    # But for efficiency, we compute from window_results
    pfs = [w['pf'] for w in window_results if w['pf'] != float('inf') and w['trades'] > 0]

    return {
        'label': label,
        'total_trades': total_trades,
        'total_pnl': total_pnl,
        'agg_pf': agg_pf,
        'mean_pf': np.mean(pfs) if pfs else 0.0,
        'positive_windows': positive_windows,
        'window_results': window_results,
    }


# ═══════════════════════════════════════════════════════════════════════════
# ABLATION DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════

def define_ablation_runs():
    """Define all ablation configurations.

    Each entry: (label, config_overrides, use_adx, use_atr_ratio)
    """
    ablations = []

    # 0. BASELINE — all filters on
    ablations.append({
        'id': 0,
        'label': 'BASELINE (all filters)',
        'overrides': {},
        'use_adx': True,
        'use_atr_ratio': True,
    })

    # 1. Remove Earnings filter
    # Earnings filter works via earnings_dates dict in FilterChainConfig.
    # In practice, earnings_dates is empty (no earnings data loaded),
    # so this filter is effectively a no-op. We include it for completeness.
    ablations.append({
        'id': 1,
        'label': 'No Earnings filter',
        'overrides': {'earnings_dates': {}},
        'use_adx': True,
        'use_atr_ratio': True,
    })

    # 2. Remove Open delay (stage 1)
    ablations.append({
        'id': 2,
        'label': 'No Open delay',
        'overrides': {'open_delay_minutes': 0},
        'use_adx': True,
        'use_atr_ratio': True,
    })

    # 3. Remove Squeeze detection (stage 2)
    ablations.append({
        'id': 3,
        'label': 'No Squeeze filter',
        'overrides': {'enable_squeeze_filter': False},
        'use_adx': True,
        'use_atr_ratio': True,
    })

    # 4. Breakaway gap block — NOT IMPLEMENTED in codebase
    # Included as placeholder; result = same as baseline
    ablations.append({
        'id': 4,
        'label': 'No Breakaway gap (N/A)',
        'overrides': {},
        'use_adx': True,
        'use_atr_ratio': True,
        'skip': True,
    })

    # 5. Remove ATR energy gate (stage 4)
    # Set both thresholds to 0 so everything passes
    ablations.append({
        'id': 5,
        'label': 'No ATR energy gate',
        'overrides': {'atr_block_threshold': 0.0, 'atr_entry_threshold': 0.0},
        'use_adx': True,
        'use_atr_ratio': True,
    })

    # 6. Remove Volume VSA (stage 5)
    ablations.append({
        'id': 6,
        'label': 'No Volume VSA',
        'overrides': {'enable_volume_filter': False},
        'use_adx': True,
        'use_atr_ratio': True,
    })

    # 7. Remove R:R feasibility (stage 6-7)
    # Set min_rr to near-zero so any R:R is accepted
    ablations.append({
        'id': 7,
        'label': 'No R:R filter (min_rr=0.01)',
        'overrides': {'min_rr': 0.01},
        'use_adx': True,
        'use_atr_ratio': True,
    })

    # 8. Remove Regime filters (ADX + ATR expansion) — disable post-filters
    ablations.append({
        'id': 8,
        'label': 'No Regime filters',
        'overrides': {},
        'use_adx': False,
        'use_atr_ratio': False,
    })

    # 9. Remove Same-level limit (anti-sawing)
    # Set cross_count_invalidate very high so it never triggers
    ablations.append({
        'id': 9,
        'label': 'No Same-level limit',
        'overrides': {'cross_count_invalidate': 999},
        'use_adx': True,
        'use_atr_ratio': True,
    })

    # 10. NUCLEAR: Remove ALL filters except core pattern + risk sizing
    # Keep: level detection, pattern engine, stop/target calculation
    # Remove: earnings, time, squeeze, ATR gate, volume, regime, sawing
    ablations.append({
        'id': 10,
        'label': 'NUCLEAR (patterns only)',
        'overrides': {
            'earnings_dates': {},
            'open_delay_minutes': 0,
            'enable_squeeze_filter': False,
            'atr_block_threshold': 0.0,
            'atr_entry_threshold': 0.0,
            'enable_volume_filter': False,
            'enable_time_filter': False,
            'min_rr': 0.01,
            'cross_count_invalidate': 999,
        },
        'use_adx': False,
        'use_atr_ratio': False,
    })

    return ablations


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    total_start = time.time()

    log("=" * 90)
    log("  PHASE 2.6 — ABLATION STUDY: Filter Chain Value Analysis")
    log("=" * 90)
    log(f"  Baseline: FD=10, ATR_ENTRY=0.60, ATR_BLOCK=0.20, RR=2.0, TAIL=0.15, STOP=0.15")
    log(f"            SAWING=5/30, ADX<=27, ATR_ratio<=1.3")
    log(f"  Tickers:  {', '.join(TICKERS)}  |  Direction: BOTH")
    log(f"  Period:   {FULL_START} -> {FULL_END}  |  Windows: {MAX_WINDOWS}")
    log(f"  Reference Baseline: 54 OOS trades, PF 1.45, +$4,355")
    log("")

    # ── Step 1: Precompute daily indicators for regime filters ─────────
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

    # ── Step 2: Generate windows ──────────────────────────────────────
    windows = generate_windows()
    log(f"\n  Step 2: Walk-forward windows ({len(windows)} windows)")
    for i, w in enumerate(windows):
        log(f"    W{i+1}: Test {w['test_start']} -> {w['test_end']}")

    # ── Step 3: Run all ablation experiments ──────────────────────────
    ablations = define_ablation_runs()
    results = []

    log(f"\n  Step 3: Running {len(ablations)} ablation experiments...")
    log(f"{'━' * 90}")

    for abl in ablations:
        if abl.get('skip'):
            log(f"\n  [{abl['id']:>2}] {abl['label']} — SKIPPED (not implemented)")
            results.append({
                'id': abl['id'],
                'label': abl['label'],
                'total_trades': '-',
                'total_pnl': '-',
                'agg_pf': '-',
                'delta_pnl': '-',
                'skipped': True,
            })
            continue

        abl_start = time.time()
        log(f"\n  [{abl['id']:>2}] {abl['label']}...")

        config = make_baseline_config(
            name=f"Ablation_{abl['id']}",
            overrides=abl['overrides'],
        )

        result = run_walkforward_ablation(
            label=abl['label'],
            config=config,
            daily_data=daily_data,
            windows=windows,
            use_adx=abl['use_adx'],
            use_atr_ratio=abl['use_atr_ratio'],
        )

        elapsed = time.time() - abl_start

        # Per-window detail
        for wr in result['window_results']:
            pf_str = fmt_pf(wr['pf'])
            log(f"      W{wr['window']}: {wr['trades']:>3}t  PF={pf_str:>6}  "
                f"P&L=${wr['pnl']:>8.0f}  WR={wr['wr']*100:>5.1f}%")

        log(f"      Total: {result['total_trades']}t  PF={fmt_pf(result['agg_pf'])}  "
            f"P&L=${result['total_pnl']:.0f}  [{elapsed:.1f}s]")

        results.append({
            'id': abl['id'],
            'label': abl['label'],
            'total_trades': result['total_trades'],
            'total_pnl': result['total_pnl'],
            'agg_pf': result['agg_pf'],
            'mean_pf': result['mean_pf'],
            'positive_windows': result['positive_windows'],
            'window_results': result['window_results'],
            'skipped': False,
        })

    # ── Step 4: Summary Table ─────────────────────────────────────────
    log(f"\n\n{'=' * 90}")
    log(f"  ABLATION RESULTS SUMMARY")
    log(f"{'=' * 90}")

    # Get baseline result for delta calculation
    baseline = next(r for r in results if r['id'] == 0)
    baseline_pnl = baseline['total_pnl']
    baseline_trades = baseline['total_trades']
    baseline_pf = baseline['agg_pf']

    log(f"\n  BASELINE: {baseline_trades} OOS trades, PF={fmt_pf(baseline_pf)}, "
        f"P&L=${baseline_pnl:.0f}")

    log(f"\n  {'#':>3} {'Filter Removed':<30} {'OOS Trades':>10} {'OOS PF':>8} "
        f"{'OOS P&L':>10} {'Delta P&L':>12} {'Verdict':>12}")
    log(f"  {'─' * 96}")

    for r in results:
        if r['skipped']:
            log(f"  {r['id']:>3} {r['label']:<30} {'N/A':>10} {'N/A':>8} "
                f"{'N/A':>10} {'N/A':>12} {'N/A':>12}")
            continue

        trades_str = str(r['total_trades'])
        pf_str = fmt_pf(r['agg_pf'])
        pnl_str = f"${r['total_pnl']:,.0f}"
        delta = r['total_pnl'] - baseline_pnl

        if r['id'] == 0:
            delta_str = "—"
            verdict = "BASELINE"
        else:
            delta_str = f"{'+'if delta>=0 else ''}${delta:,.0f}"
            if delta < -500:
                verdict = "PROTECTS"
            elif delta > 500:
                verdict = "SUPPRESSES"
            else:
                verdict = "NEUTRAL"

        log(f"  {r['id']:>3} {r['label']:<30} {trades_str:>10} {pf_str:>8} "
            f"{pnl_str:>10} {delta_str:>12} {verdict:>12}")

    log(f"  {'─' * 96}")

    # ── Step 5: Analysis ──────────────────────────────────────────────
    log(f"\n{'=' * 90}")
    log(f"  ANALYSIS")
    log(f"{'=' * 90}")

    # Categorize filters
    protectors = []
    suppressors = []
    neutrals = []
    for r in results:
        if r['skipped'] or r['id'] == 0:
            continue
        delta = r['total_pnl'] - baseline_pnl
        if delta < -500:
            protectors.append((r['label'], delta))
        elif delta > 500:
            suppressors.append((r['label'], delta))
        else:
            neutrals.append((r['label'], delta))

    log(f"\n  PROTECTORS (removing them hurts P&L by >$500):")
    if protectors:
        for label, delta in sorted(protectors, key=lambda x: x[1]):
            log(f"    {label:<35} Delta: ${delta:,.0f}")
    else:
        log(f"    (none)")

    log(f"\n  SUPPRESSORS (removing them improves P&L by >$500):")
    if suppressors:
        for label, delta in sorted(suppressors, key=lambda x: -x[1]):
            log(f"    {label:<35} Delta: +${delta:,.0f}")
    else:
        log(f"    (none)")

    log(f"\n  NEUTRAL (removing them changes P&L by <$500):")
    if neutrals:
        for label, delta in sorted(neutrals, key=lambda x: abs(x[1])):
            log(f"    {label:<35} Delta: {'+'if delta>=0 else ''}${delta:,.0f}")
    else:
        log(f"    (none)")

    # Nuclear test analysis
    nuclear = next((r for r in results if r['id'] == 10), None)
    if nuclear and not nuclear['skipped']:
        nuclear_delta = nuclear['total_pnl'] - baseline_pnl
        log(f"\n  NUCLEAR TEST (all filters removed):")
        log(f"    Trades: {nuclear['total_trades']} (vs baseline {baseline_trades})")
        log(f"    P&L:    ${nuclear['total_pnl']:,.0f} (vs baseline ${baseline_pnl:,.0f})")
        log(f"    Delta:  {'+'if nuclear_delta>=0 else ''}${nuclear_delta:,.0f}")

        if nuclear['total_pnl'] > baseline_pnl:
            log(f"    >> Edge lives in PATTERN DETECTION — filters are net-negative")
        elif nuclear['total_pnl'] > 0:
            log(f"    >> Edge lives in BOTH pattern detection and filtering")
            filter_value = baseline_pnl - nuclear['total_pnl']
            log(f"    >> Filter chain adds ${filter_value:,.0f} of value")
        else:
            log(f"    >> Edge lives primarily in FILTERING — patterns alone lose money")
            log(f"    >> Filters transform a ${nuclear['total_pnl']:,.0f} loss into "
                f"a ${baseline_pnl:,.0f} gain")

    elapsed = time.time() - total_start
    log(f"\n{'=' * 90}")
    log(f"  COMPLETE — {elapsed:.0f}s ({elapsed/60:.1f}min)")
    log(f"{'=' * 90}")

    # Save report
    report_path = os.path.join(RESULTS_DIR, 'phase26_ablation_study.txt')
    with open(report_path, 'w') as f:
        f.write('\n'.join(LOG))
    log(f"\n  Report saved: {report_path}")

    # Save JSON
    json_results = []
    for r in results:
        entry = {
            'id': r['id'],
            'label': r['label'],
            'skipped': r['skipped'],
        }
        if not r['skipped']:
            entry.update({
                'total_trades': r['total_trades'],
                'total_pnl': float(r['total_pnl']),
                'agg_pf': float(r['agg_pf']) if r['agg_pf'] != float('inf') else 'inf',
                'delta_pnl': float(r['total_pnl'] - baseline_pnl) if r['id'] != 0 else 0,
                'positive_windows': r['positive_windows'],
            })
        json_results.append(entry)

    json_path = os.path.join(RESULTS_DIR, 'phase26_ablation_study.json')
    with open(json_path, 'w') as f:
        json.dump({
            'phase': '2.6',
            'description': 'Ablation study: filter chain value analysis',
            'baseline_ref': {
                'trades': baseline_trades,
                'pf': float(baseline_pf) if baseline_pf != float('inf') else 'inf',
                'pnl': float(baseline_pnl),
            },
            'ablation_results': json_results,
        }, f, indent=2)
    log(f"  JSON saved: {json_path}")


if __name__ == '__main__':
    main()
