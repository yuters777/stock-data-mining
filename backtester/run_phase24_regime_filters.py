"""
Phase 2.4 — Additional Indicators Research

Four regime filter experiments to find filters that block trades during
strong directional moves WITHOUT killing winners in range-bound markets.

Config A (fixed params): FD=10, ATR=0.60, RR=2.0, TAIL=0.15, STOP=0.15
Run on full period, all available tickers, both directions.
Baseline reference: 113 trades, +$1,533.

EXPERIMENT 1: ADX Regime Filter
EXPERIMENT 2: VWAP Filter
EXPERIMENT 3: Volatility Regime (ATR Expansion)
EXPERIMENT 4: Multi-Timeframe Trend (H1)

Then: combine best 1-2 filters and re-run walk-forward.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import json
import numpy as np
import pandas as pd
from copy import deepcopy
from collections import defaultdict

from backtester.backtester import Backtester, BacktestConfig
from backtester.core.level_detector import LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngineConfig
from backtester.core.filter_chain import FilterChainConfig
from backtester.core.risk_manager import RiskManagerConfig
from backtester.core.trade_manager import TradeManagerConfig
from backtester.core.intraday_levels import IntradayLevelConfig
from backtester.optimizer import load_ticker_data, run_single_backtest, aggregate_metrics

# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

# All tickers with available data
TICKERS = ['TSLA', 'AMZN', 'GOOGL', 'META', 'MSFT', 'NVDA']
FULL_START = '2025-02-10'
FULL_END = '2026-01-31'

LOG = []


def log(msg=''):
    LOG.append(msg)
    print(msg)


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG A BUILDER
# ═══════════════════════════════════════════════════════════════════════════

def make_config_a(name='ConfigA') -> BacktestConfig:
    """Config A: FD=10, ATR=0.60, RR=2.0, TAIL=0.15, STOP=0.15"""
    return BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=10,
            tolerance_cents=0.05,
            tolerance_pct=0.001,
            atr_period=5,
            min_level_score=5,
        ),
        pattern_config=PatternEngineConfig(
            tail_ratio_min=0.15,
            lp2_engulfing_required=True,
            clp_min_bars=3,
            clp_max_bars=7,
        ),
        filter_config=FilterChainConfig(
            atr_block_threshold=0.30,
            atr_entry_threshold=0.60,
            enable_volume_filter=True,
            enable_time_filter=True,
            enable_squeeze_filter=True,
        ),
        risk_config=RiskManagerConfig(
            min_rr=2.0,
            max_stop_atr_pct=0.15,
            capital=100000.0,
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
        direction_filter=None,  # both directions
        name=name,
    )


# ═══════════════════════════════════════════════════════════════════════════
# INDICATOR CALCULATIONS
# ═══════════════════════════════════════════════════════════════════════════

def compute_atr_series(daily, period=14):
    """Compute ATR series on daily DataFrame."""
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
    """Compute ADX(period) using Wilder's smoothing. Returns Series."""
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
    """Aggregate M5 bars to daily OHLCV (regular session only: 16:30-23:00 IST)."""
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


def aggregate_m5_to_h1(m5_df):
    """Aggregate M5 bars to H1 OHLCV."""
    df = m5_df.copy()
    df['Datetime'] = pd.to_datetime(df['Datetime'])
    df['Hour'] = df['Datetime'].dt.floor('h')
    h1 = df.groupby('Hour').agg(
        Open=('Open', 'first'), High=('High', 'max'),
        Low=('Low', 'min'), Close=('Close', 'last'),
        Volume=('Volume', 'sum'),
    ).reset_index()
    h1 = h1.rename(columns={'Hour': 'Datetime'})
    return h1


def compute_vwap(m5_df):
    """Compute intraday VWAP for each M5 bar, resetting at session start."""
    df = m5_df.copy()
    df['Datetime'] = pd.to_datetime(df['Datetime'])
    df['Date'] = df['Datetime'].dt.date
    df['TypicalPrice'] = (df['High'] + df['Low'] + df['Close']) / 3.0
    df['TPxV'] = df['TypicalPrice'] * df['Volume']

    # Cumulative within each day
    df['CumTPxV'] = df.groupby('Date')['TPxV'].cumsum()
    df['CumVol'] = df.groupby('Date')['Volume'].cumsum()
    df['VWAP'] = df['CumTPxV'] / df['CumVol'].replace(0, np.nan)
    df['VWAP'] = df['VWAP'].fillna(df['Close'])
    return df


# ═══════════════════════════════════════════════════════════════════════════
# BASELINE + TRADE EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════

def run_baseline_get_trades(config, tickers, start_date, end_date):
    """Run baseline backtest and extract per-trade data with entry timestamps."""
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


def compute_trade_metrics(trades_df):
    """Compute standard metrics from a trades DataFrame."""
    if trades_df.empty:
        return {'trades': 0, 'wr': 0, 'pf': 0, 'pnl': 0, 'max_dd': 0}
    n = len(trades_df)
    winners = trades_df[trades_df['pnl'] > 0]
    losers = trades_df[trades_df['pnl'] <= 0]
    gp = winners['pnl'].sum()
    gl = abs(losers['pnl'].sum())
    pf = gp / gl if gl > 0 else (float('inf') if gp > 0 else 0)
    pnl = trades_df['pnl'].sum()

    # Max drawdown from cumulative P&L
    cum_pnl = trades_df['pnl'].cumsum()
    peak = cum_pnl.cummax()
    dd = peak - cum_pnl
    max_dd = dd.max() if len(dd) > 0 else 0

    return {
        'trades': n,
        'wr': len(winners) / n if n > 0 else 0,
        'pf': pf,
        'pnl': pnl,
        'max_dd': max_dd,
        'gross_profit': gp,
        'gross_loss': gl,
    }


def format_metrics(m):
    """Format metrics dict for display."""
    pf_str = f"{m['pf']:.2f}" if m['pf'] != float('inf') else "inf"
    return (f"{m['trades']}t, WR={m['wr']*100:.1f}%, PF={pf_str}, "
            f"P&L=${m['pnl']:.0f}, MaxDD=${m['max_dd']:.0f}")


# ═══════════════════════════════════════════════════════════════════════════
# EXPERIMENT 1: ADX REGIME FILTER
# ═══════════════════════════════════════════════════════════════════════════

def experiment_1_adx(trades_df, daily_data):
    """
    ADX(14) on D1 bars. High ADX = strong trend = bad for mean-reversion.
    For each trade, record ADX at signal time. Find threshold.
    """
    log("\n" + "=" * 80)
    log("  EXPERIMENT 1: ADX Regime Filter")
    log("=" * 80)

    if trades_df.empty:
        log("  No trades to analyze!")
        return trades_df, None

    # Merge ADX values at entry date
    trades = trades_df.copy()
    adx_values = []

    for _, trade in trades.iterrows():
        ticker = trade['ticker']
        entry_date = pd.Timestamp(trade['entry_date'])
        if ticker in daily_data:
            d = daily_data[ticker]
            match = d[d['Date'] == entry_date]
            if not match.empty:
                adx_values.append(match['ADX'].iloc[0])
            else:
                # Find nearest prior date
                prior = d[d['Date'] <= entry_date]
                adx_values.append(prior['ADX'].iloc[-1] if not prior.empty else np.nan)
        else:
            adx_values.append(np.nan)

    trades['ADX'] = adx_values

    # Remove trades with no ADX data (warmup period)
    valid = trades.dropna(subset=['ADX'])
    valid = valid[valid['ADX'] > 0]
    log(f"\n  Trades with valid ADX: {len(valid)} / {len(trades)}")

    # Distribution: winners vs losers by ADX
    log(f"\n  ADX Distribution — Winners vs Losers:")
    log(f"  {'ADX Range':>12} {'Total':>6} {'Winners':>8} {'Losers':>7} {'WR':>7} {'PF':>7} {'P&L':>10}")
    log(f"  {'-'*65}")

    buckets = [(0, 15), (15, 20), (20, 25), (25, 30), (30, 40), (40, 100)]
    for lo, hi in buckets:
        mask = (valid['ADX'] >= lo) & (valid['ADX'] < hi)
        bucket = valid[mask]
        if len(bucket) == 0:
            log(f"  {lo:>3}-{hi:<3}       {0:>6} {0:>8} {0:>7}     —      —         —")
            continue
        m = compute_trade_metrics(bucket)
        pf_str = f"{m['pf']:.2f}" if m['pf'] != float('inf') else "inf"
        log(f"  {lo:>3}-{hi:<3}       {m['trades']:>6} "
            f"{bucket['is_winner'].sum():>8} {(~bucket['is_winner']).sum():>7} "
            f"{m['wr']*100:>6.1f}% {pf_str:>6} ${m['pnl']:>9.0f}")

    # Percentile analysis
    log(f"\n  ADX Percentiles:")
    for pct in [10, 25, 50, 75, 90]:
        v = valid['ADX'].quantile(pct / 100)
        log(f"    P{pct}: {v:.1f}")

    winner_adx = valid[valid['is_winner']]['ADX']
    loser_adx = valid[~valid['is_winner']]['ADX']
    log(f"\n  Winner mean ADX: {winner_adx.mean():.1f} (median: {winner_adx.median():.1f})")
    log(f"  Loser mean ADX:  {loser_adx.mean():.1f} (median: {loser_adx.median():.1f})")

    # Test ADX thresholds
    log(f"\n  ADX Threshold Sweep (block when ADX > threshold):")
    log(f"  {'Threshold':>10} {'Trades':>7} {'Blocked':>8} {'WR':>7} {'PF':>7} {'P&L':>10} {'MaxDD':>8}")
    log(f"  {'-'*65}")

    baseline_m = compute_trade_metrics(valid)
    log(f"  {'No filter':>10} {format_metrics(baseline_m)}")

    best_pf = 0
    best_threshold = None
    threshold_results = {}

    for threshold in [20, 22, 25, 27, 30, 35, 40]:
        filtered = valid[valid['ADX'] <= threshold]
        blocked = len(valid) - len(filtered)
        m = compute_trade_metrics(filtered)
        pf_str = f"{m['pf']:.2f}" if m['pf'] != float('inf') else "inf"
        log(f"  ADX<={threshold:>3}     {m['trades']:>7} {blocked:>8} "
            f"{m['wr']*100:>6.1f}% {pf_str:>6} ${m['pnl']:>9.0f} ${m['max_dd']:>7.0f}")
        threshold_results[threshold] = m

        effective_pf = m['pf'] if m['pf'] != float('inf') else 10.0
        if m['trades'] >= 10 and effective_pf > best_pf:
            best_pf = effective_pf
            best_threshold = threshold

    log(f"\n  >> Best ADX threshold: {best_threshold} (PF={best_pf:.2f})")
    return trades, {'best_threshold': best_threshold, 'results': threshold_results}


# ═══════════════════════════════════════════════════════════════════════════
# EXPERIMENT 2: VWAP FILTER
# ═══════════════════════════════════════════════════════════════════════════

def experiment_2_vwap(trades_df, vwap_data):
    """
    VWAP = Volume Weighted Average Price. Institutional benchmark.
    SHORT when price > VWAP (overextended) should be better.
    Block SHORT when price < VWAP, block LONG when price > VWAP.
    """
    log("\n" + "=" * 80)
    log("  EXPERIMENT 2: VWAP Filter")
    log("=" * 80)

    if trades_df.empty:
        log("  No trades to analyze!")
        return trades_df, None

    trades = trades_df.copy()
    vwap_at_entry = []
    price_vs_vwap = []  # 'above' or 'below'

    for _, trade in trades.iterrows():
        ticker = trade['ticker']
        entry_time = pd.Timestamp(trade['entry_time'])
        if ticker in vwap_data:
            vdf = vwap_data[ticker]
            # Find the M5 bar at or just before entry time
            prior = vdf[vdf['Datetime'] <= entry_time]
            if not prior.empty:
                vwap_val = prior['VWAP'].iloc[-1]
                vwap_at_entry.append(vwap_val)
                price_vs_vwap.append('above' if trade['entry_price'] >= vwap_val else 'below')
            else:
                vwap_at_entry.append(np.nan)
                price_vs_vwap.append(np.nan)
        else:
            vwap_at_entry.append(np.nan)
            price_vs_vwap.append(np.nan)

    trades['VWAP'] = vwap_at_entry
    trades['price_vs_vwap'] = price_vs_vwap

    valid = trades.dropna(subset=['VWAP'])
    log(f"\n  Trades with valid VWAP: {len(valid)} / {len(trades)}")

    # Analysis: price vs VWAP for shorts and longs
    for direction in ['short', 'long']:
        dir_trades = valid[valid['direction'] == direction]
        if dir_trades.empty:
            continue

        log(f"\n  {direction.upper()} trades vs VWAP:")
        for position in ['above', 'below']:
            subset = dir_trades[dir_trades['price_vs_vwap'] == position]
            if subset.empty:
                log(f"    Price {position} VWAP: 0 trades")
                continue
            m = compute_trade_metrics(subset)
            log(f"    Price {position} VWAP: {format_metrics(m)}")

    # Apply VWAP filter: block SHORT when price < VWAP, block LONG when price > VWAP
    log(f"\n  VWAP Filter Test (block counter-VWAP signals):")

    filtered = valid[
        ((valid['direction'] == 'short') & (valid['price_vs_vwap'] == 'above')) |
        ((valid['direction'] == 'long') & (valid['price_vs_vwap'] == 'below'))
    ]
    blocked = len(valid) - len(filtered)
    baseline_m = compute_trade_metrics(valid)
    filtered_m = compute_trade_metrics(filtered)

    log(f"    Baseline (no filter):   {format_metrics(baseline_m)}")
    log(f"    With VWAP filter:       {format_metrics(filtered_m)} (blocked {blocked})")

    # Also test inverse (sanity check)
    inverse = valid[
        ((valid['direction'] == 'short') & (valid['price_vs_vwap'] == 'below')) |
        ((valid['direction'] == 'long') & (valid['price_vs_vwap'] == 'above'))
    ]
    inverse_m = compute_trade_metrics(inverse)
    log(f"    Inverse (counter-hypo): {format_metrics(inverse_m)}")

    # Distance from VWAP analysis
    valid_copy = valid.copy()
    valid_copy['vwap_dist_pct'] = (valid_copy['entry_price'] - valid_copy['VWAP']) / valid_copy['VWAP'] * 100
    log(f"\n  Distance from VWAP at entry:")
    log(f"    Mean:   {valid_copy['vwap_dist_pct'].mean():.3f}%")
    log(f"    Median: {valid_copy['vwap_dist_pct'].median():.3f}%")
    log(f"    Winners mean: {valid_copy[valid_copy['is_winner']]['vwap_dist_pct'].mean():.3f}%")
    log(f"    Losers mean:  {valid_copy[~valid_copy['is_winner']]['vwap_dist_pct'].mean():.3f}%")

    return trades, {
        'baseline': baseline_m,
        'filtered': filtered_m,
        'blocked': blocked,
    }


# ═══════════════════════════════════════════════════════════════════════════
# EXPERIMENT 3: VOLATILITY REGIME (ATR EXPANSION)
# ═══════════════════════════════════════════════════════════════════════════

def experiment_3_atr_expansion(trades_df, daily_data):
    """
    ATR_D1(5) / ATR_D1(20) ratio — "volatility expansion".
    If ratio > 1.5: volatility expanding = trending = bad for LP.
    """
    log("\n" + "=" * 80)
    log("  EXPERIMENT 3: Volatility Regime (ATR Expansion)")
    log("=" * 80)

    if trades_df.empty:
        log("  No trades to analyze!")
        return trades_df, None

    trades = trades_df.copy()
    atr_ratios = []

    for _, trade in trades.iterrows():
        ticker = trade['ticker']
        entry_date = pd.Timestamp(trade['entry_date'])
        if ticker in daily_data:
            d = daily_data[ticker]
            match = d[d['Date'] == entry_date]
            if not match.empty:
                atr_ratios.append(match['ATR_ratio_5_20'].iloc[0])
            else:
                prior = d[d['Date'] <= entry_date]
                atr_ratios.append(prior['ATR_ratio_5_20'].iloc[-1] if not prior.empty else np.nan)
        else:
            atr_ratios.append(np.nan)

    trades['ATR_ratio'] = atr_ratios
    valid = trades.dropna(subset=['ATR_ratio'])
    log(f"\n  Trades with valid ATR ratio: {len(valid)} / {len(trades)}")

    # Distribution
    log(f"\n  ATR(5)/ATR(20) Distribution — Winners vs Losers:")
    log(f"  {'Ratio Range':>14} {'Total':>6} {'Winners':>8} {'Losers':>7} {'WR':>7} {'PF':>7} {'P&L':>10}")
    log(f"  {'-'*67}")

    ratio_buckets = [(0, 0.7), (0.7, 0.9), (0.9, 1.1), (1.1, 1.3), (1.3, 1.5), (1.5, 3.0)]
    for lo, hi in ratio_buckets:
        mask = (valid['ATR_ratio'] >= lo) & (valid['ATR_ratio'] < hi)
        bucket = valid[mask]
        if len(bucket) == 0:
            log(f"  {lo:.1f}-{hi:.1f}         {0:>6} {0:>8} {0:>7}     —      —         —")
            continue
        m = compute_trade_metrics(bucket)
        pf_str = f"{m['pf']:.2f}" if m['pf'] != float('inf') else "inf"
        log(f"  {lo:.1f}-{hi:.1f}         {m['trades']:>6} "
            f"{bucket['is_winner'].sum():>8} {(~bucket['is_winner']).sum():>7} "
            f"{m['wr']*100:>6.1f}% {pf_str:>6} ${m['pnl']:>9.0f}")

    winner_ratio = valid[valid['is_winner']]['ATR_ratio']
    loser_ratio = valid[~valid['is_winner']]['ATR_ratio']
    log(f"\n  Winner mean ratio: {winner_ratio.mean():.2f} (median: {winner_ratio.median():.2f})")
    log(f"  Loser mean ratio:  {loser_ratio.mean():.2f} (median: {loser_ratio.median():.2f})")

    # Threshold sweep
    log(f"\n  ATR Ratio Threshold Sweep (block when ratio > threshold):")
    log(f"  {'Threshold':>10} {'Trades':>7} {'Blocked':>8} {'WR':>7} {'PF':>7} {'P&L':>10} {'MaxDD':>8}")
    log(f"  {'-'*65}")

    baseline_m = compute_trade_metrics(valid)
    log(f"  {'No filter':>10} {format_metrics(baseline_m)}")

    best_pf = 0
    best_threshold = None
    threshold_results = {}

    for threshold in [1.0, 1.1, 1.2, 1.3, 1.5, 1.7, 2.0]:
        filtered = valid[valid['ATR_ratio'] <= threshold]
        blocked = len(valid) - len(filtered)
        m = compute_trade_metrics(filtered)
        pf_str = f"{m['pf']:.2f}" if m['pf'] != float('inf') else "inf"
        log(f"  ratio<={threshold:.1f}    {m['trades']:>7} {blocked:>8} "
            f"{m['wr']*100:>6.1f}% {pf_str:>6} ${m['pnl']:>9.0f} ${m['max_dd']:>7.0f}")
        threshold_results[threshold] = m

        effective_pf = m['pf'] if m['pf'] != float('inf') else 10.0
        if m['trades'] >= 10 and effective_pf > best_pf:
            best_pf = effective_pf
            best_threshold = threshold

    log(f"\n  >> Best ATR ratio threshold: {best_threshold} (PF={best_pf:.2f})")
    return trades, {'best_threshold': best_threshold, 'results': threshold_results}


# ═══════════════════════════════════════════════════════════════════════════
# EXPERIMENT 4: MULTI-TIMEFRAME TREND (H1)
# ═══════════════════════════════════════════════════════════════════════════

def experiment_4_h1_trend(trades_df, h1_data):
    """
    H1 trend: price vs SMA(20) on H1 bars.
    Block counter-trend signals on H1 timeframe.
    """
    log("\n" + "=" * 80)
    log("  EXPERIMENT 4: Multi-Timeframe Trend (H1)")
    log("=" * 80)

    if trades_df.empty:
        log("  No trades to analyze!")
        return trades_df, None

    trades = trades_df.copy()
    h1_trend_values = []  # 'up', 'down', or nan

    for _, trade in trades.iterrows():
        ticker = trade['ticker']
        entry_time = pd.Timestamp(trade['entry_time'])
        if ticker in h1_data:
            hdf = h1_data[ticker]
            prior = hdf[hdf['Datetime'] <= entry_time]
            if len(prior) >= 20:
                sma20 = prior['Close'].iloc[-20:].mean()
                current_price = prior['Close'].iloc[-1]
                h1_trend_values.append('up' if current_price > sma20 else 'down')
            else:
                h1_trend_values.append(np.nan)
        else:
            h1_trend_values.append(np.nan)

    trades['h1_trend'] = h1_trend_values
    valid = trades.dropna(subset=['h1_trend'])
    log(f"\n  Trades with valid H1 trend: {len(valid)} / {len(trades)}")

    # Analysis: trend alignment
    log(f"\n  H1 Trend Alignment Analysis:")

    for direction in ['short', 'long']:
        dir_trades = valid[valid['direction'] == direction]
        if dir_trades.empty:
            continue

        log(f"\n  {direction.upper()} trades:")
        for trend in ['up', 'down']:
            subset = dir_trades[dir_trades['h1_trend'] == trend]
            if subset.empty:
                log(f"    H1 trend={trend}: 0 trades")
                continue
            m = compute_trade_metrics(subset)
            aligned = ((direction == 'short' and trend == 'down') or
                       (direction == 'long' and trend == 'up'))
            marker = " [WITH-TREND]" if aligned else " [COUNTER-TREND]"
            log(f"    H1 trend={trend}: {format_metrics(m)}{marker}")

    # Apply filter: block counter-H1-trend signals
    # SHORT only when H1 trend is down, LONG only when H1 trend is up
    with_trend = valid[
        ((valid['direction'] == 'short') & (valid['h1_trend'] == 'down')) |
        ((valid['direction'] == 'long') & (valid['h1_trend'] == 'up'))
    ]

    # Counter-trend: SHORT when H1 trend is up, LONG when H1 trend is down
    # (these are what our MEAN-REVERSION strategy wants!)
    counter_trend = valid[
        ((valid['direction'] == 'short') & (valid['h1_trend'] == 'up')) |
        ((valid['direction'] == 'long') & (valid['h1_trend'] == 'down'))
    ]

    baseline_m = compute_trade_metrics(valid)
    with_trend_m = compute_trade_metrics(with_trend)
    counter_trend_m = compute_trade_metrics(counter_trend)

    log(f"\n  Filter Results:")
    log(f"    Baseline (no filter):    {format_metrics(baseline_m)}")
    log(f"    WITH-trend only:         {format_metrics(with_trend_m)} (blocked {len(valid) - len(with_trend)})")
    log(f"    COUNTER-trend only:      {format_metrics(counter_trend_m)} (blocked {len(valid) - len(counter_trend)})")

    log(f"\n  Note: For mean-reversion, COUNTER-trend entries (SHORT on H1 uptrend,")
    log(f"  LONG on H1 downtrend) capture overextended moves snapping back.")

    # Also test with SMA(10) for faster H1 trend
    log(f"\n  --- SMA(10) variant ---")
    h1_trend_fast = []
    for _, trade in trades.iterrows():
        ticker = trade['ticker']
        entry_time = pd.Timestamp(trade['entry_time'])
        if ticker in h1_data:
            hdf = h1_data[ticker]
            prior = hdf[hdf['Datetime'] <= entry_time]
            if len(prior) >= 10:
                sma10 = prior['Close'].iloc[-10:].mean()
                current_price = prior['Close'].iloc[-1]
                h1_trend_fast.append('up' if current_price > sma10 else 'down')
            else:
                h1_trend_fast.append(np.nan)
        else:
            h1_trend_fast.append(np.nan)

    trades['h1_trend_fast'] = h1_trend_fast
    valid_fast = trades.dropna(subset=['h1_trend_fast'])

    counter_trend_fast = valid_fast[
        ((valid_fast['direction'] == 'short') & (valid_fast['h1_trend_fast'] == 'up')) |
        ((valid_fast['direction'] == 'long') & (valid_fast['h1_trend_fast'] == 'down'))
    ]
    with_trend_fast = valid_fast[
        ((valid_fast['direction'] == 'short') & (valid_fast['h1_trend_fast'] == 'down')) |
        ((valid_fast['direction'] == 'long') & (valid_fast['h1_trend_fast'] == 'up'))
    ]

    counter_m_fast = compute_trade_metrics(counter_trend_fast)
    with_m_fast = compute_trade_metrics(with_trend_fast)
    log(f"    WITH-trend SMA(10):      {format_metrics(with_m_fast)}")
    log(f"    COUNTER-trend SMA(10):   {format_metrics(counter_m_fast)}")

    return trades, {
        'baseline': baseline_m,
        'with_trend': with_trend_m,
        'counter_trend': counter_trend_m,
        'counter_trend_fast': counter_m_fast,
        'with_trend_fast': with_m_fast,
    }


# ═══════════════════════════════════════════════════════════════════════════
# COMBINATION + WALK-FORWARD
# ═══════════════════════════════════════════════════════════════════════════

def combine_best_filters(trades_df, daily_data, vwap_data, h1_data,
                          adx_result, atr_result, vwap_result, h1_result):
    """Combine the best 1-2 filters and report impact."""
    log("\n" + "=" * 80)
    log("  COMBINATION: Best Filters Together")
    log("=" * 80)

    trades = trades_df.copy()

    # Collect all indicator values
    adx_vals = []
    atr_ratio_vals = []
    vwap_position = []
    h1_trend_vals = []

    for _, trade in trades.iterrows():
        ticker = trade['ticker']
        entry_date = pd.Timestamp(trade['entry_date'])
        entry_time = pd.Timestamp(trade['entry_time'])

        # ADX
        if ticker in daily_data:
            d = daily_data[ticker]
            prior = d[d['Date'] <= entry_date]
            adx_vals.append(prior['ADX'].iloc[-1] if not prior.empty and prior['ADX'].iloc[-1] > 0 else np.nan)
        else:
            adx_vals.append(np.nan)

        # ATR ratio
        if ticker in daily_data:
            d = daily_data[ticker]
            prior = d[d['Date'] <= entry_date]
            atr_ratio_vals.append(prior['ATR_ratio_5_20'].iloc[-1] if not prior.empty else np.nan)
        else:
            atr_ratio_vals.append(np.nan)

        # VWAP
        if ticker in vwap_data:
            vdf = vwap_data[ticker]
            prior = vdf[vdf['Datetime'] <= entry_time]
            if not prior.empty:
                vwap_val = prior['VWAP'].iloc[-1]
                vwap_position.append('above' if trade['entry_price'] >= vwap_val else 'below')
            else:
                vwap_position.append(np.nan)
        else:
            vwap_position.append(np.nan)

        # H1 trend
        if ticker in h1_data:
            hdf = h1_data[ticker]
            prior = hdf[hdf['Datetime'] <= entry_time]
            if len(prior) >= 20:
                sma20 = prior['Close'].iloc[-20:].mean()
                h1_trend_vals.append('up' if prior['Close'].iloc[-1] > sma20 else 'down')
            else:
                h1_trend_vals.append(np.nan)
        else:
            h1_trend_vals.append(np.nan)

    trades['ADX'] = adx_vals
    trades['ATR_ratio'] = atr_ratio_vals
    trades['vwap_pos'] = vwap_position
    trades['h1_trend'] = h1_trend_vals

    valid = trades.dropna(subset=['ADX', 'ATR_ratio'])

    baseline_m = compute_trade_metrics(valid)
    log(f"\n  Baseline (all filters off): {format_metrics(baseline_m)}")

    # Test combinations
    combos = []

    # ADX only (best threshold)
    if adx_result and adx_result['best_threshold']:
        adx_thresh = adx_result['best_threshold']
        f1 = valid[valid['ADX'] <= adx_thresh]
        m1 = compute_trade_metrics(f1)
        log(f"\n  ADX<={adx_thresh} only:             {format_metrics(m1)} (blocked {len(valid)-len(f1)})")
        combos.append(('ADX', adx_thresh, m1, f1))

    # ATR ratio only (best threshold)
    if atr_result and atr_result['best_threshold']:
        atr_thresh = atr_result['best_threshold']
        f2 = valid[valid['ATR_ratio'] <= atr_thresh]
        m2 = compute_trade_metrics(f2)
        log(f"  ATR_ratio<={atr_thresh} only:        {format_metrics(m2)} (blocked {len(valid)-len(f2)})")
        combos.append(('ATR_ratio', atr_thresh, m2, f2))

    # VWAP filter
    vwap_valid = valid.dropna(subset=['vwap_pos'])
    f3 = vwap_valid[
        ((vwap_valid['direction'] == 'short') & (vwap_valid['vwap_pos'] == 'above')) |
        ((vwap_valid['direction'] == 'long') & (vwap_valid['vwap_pos'] == 'below'))
    ]
    m3 = compute_trade_metrics(f3)
    log(f"  VWAP filter only:           {format_metrics(m3)} (blocked {len(vwap_valid)-len(f3)})")
    combos.append(('VWAP', None, m3, f3))

    # H1 counter-trend filter
    h1_valid = valid.dropna(subset=['h1_trend'])
    f4 = h1_valid[
        ((h1_valid['direction'] == 'short') & (h1_valid['h1_trend'] == 'up')) |
        ((h1_valid['direction'] == 'long') & (h1_valid['h1_trend'] == 'down'))
    ]
    m4 = compute_trade_metrics(f4)
    log(f"  H1 counter-trend only:      {format_metrics(m4)} (blocked {len(h1_valid)-len(f4)})")
    combos.append(('H1_counter', None, m4, f4))

    # Pairwise combinations of the best individual filters
    log(f"\n  --- Pairwise Combinations ---")

    if adx_result and adx_result['best_threshold'] and atr_result and atr_result['best_threshold']:
        adx_t = adx_result['best_threshold']
        atr_t = atr_result['best_threshold']
        fc = valid[(valid['ADX'] <= adx_t) & (valid['ATR_ratio'] <= atr_t)]
        mc = compute_trade_metrics(fc)
        log(f"  ADX<={adx_t} + ATR_ratio<={atr_t}: {format_metrics(mc)} (blocked {len(valid)-len(fc)})")

    if adx_result and adx_result['best_threshold']:
        adx_t = adx_result['best_threshold']
        vwap_adx = vwap_valid[vwap_valid['ADX'] <= adx_t]
        fc2 = vwap_adx[
            ((vwap_adx['direction'] == 'short') & (vwap_adx['vwap_pos'] == 'above')) |
            ((vwap_adx['direction'] == 'long') & (vwap_adx['vwap_pos'] == 'below'))
        ]
        mc2 = compute_trade_metrics(fc2)
        log(f"  ADX<={adx_t} + VWAP:            {format_metrics(mc2)} (blocked {len(vwap_valid)-len(fc2)})")

    if adx_result and adx_result['best_threshold']:
        adx_t = adx_result['best_threshold']
        h1_adx = h1_valid[h1_valid['ADX'] <= adx_t]
        fc3 = h1_adx[
            ((h1_adx['direction'] == 'short') & (h1_adx['h1_trend'] == 'up')) |
            ((h1_adx['direction'] == 'long') & (h1_adx['h1_trend'] == 'down'))
        ]
        mc3 = compute_trade_metrics(fc3)
        log(f"  ADX<={adx_t} + H1 counter:      {format_metrics(mc3)} (blocked {len(h1_valid)-len(fc3)})")

    return trades


# ═══════════════════════════════════════════════════════════════════════════
# WALK-FORWARD WITH BEST FILTER
# ═══════════════════════════════════════════════════════════════════════════

def run_walkforward_with_filter(daily_data, vwap_data, h1_data,
                                 adx_threshold=None, atr_threshold=None):
    """
    Run walk-forward validation with the best regime filter(s) applied
    as a post-filter on trades.
    """
    log("\n" + "=" * 80)
    log("  WALK-FORWARD WITH BEST FILTER(S)")
    if adx_threshold:
        log(f"  ADX threshold: {adx_threshold}")
    if atr_threshold:
        log(f"  ATR ratio threshold: {atr_threshold}")
    log("=" * 80)

    # Generate windows (same as Phase 2.3: 3mo train, 1mo test)
    overall_start = pd.Timestamp(FULL_START)
    overall_end = pd.Timestamp(FULL_END)

    windows = []
    current = overall_start
    while True:
        train_end = current + pd.DateOffset(months=3)
        test_end = train_end + pd.DateOffset(months=1)
        if test_end > overall_end:
            break
        windows.append({
            'test_start': train_end.strftime('%Y-%m-%d'),
            'test_end': test_end.strftime('%Y-%m-%d'),
        })
        current += pd.DateOffset(months=1)

    config = make_config_a('WF_filtered')

    wf_baseline = []
    wf_filtered = []

    for wi, w in enumerate(windows):
        # Get trades for this window
        trades = run_baseline_get_trades(config, TICKERS,
                                          w['test_start'], w['test_end'])
        baseline_m = compute_trade_metrics(trades)

        if trades.empty:
            wf_baseline.append({'window': wi+1, **w, **baseline_m})
            wf_filtered.append({'window': wi+1, **w, **baseline_m})
            continue

        # Apply filters
        filtered = trades.copy()

        # Add ADX
        if adx_threshold:
            adx_vals = []
            for _, trade in filtered.iterrows():
                ticker = trade['ticker']
                entry_date = pd.Timestamp(trade['entry_date'])
                if ticker in daily_data:
                    d = daily_data[ticker]
                    prior = d[d['Date'] <= entry_date]
                    adx_vals.append(prior['ADX'].iloc[-1] if not prior.empty and prior['ADX'].iloc[-1] > 0 else np.nan)
                else:
                    adx_vals.append(np.nan)
            filtered['ADX'] = adx_vals
            filtered = filtered.dropna(subset=['ADX'])
            filtered = filtered[filtered['ADX'] <= adx_threshold]

        # Add ATR ratio
        if atr_threshold:
            atr_vals = []
            for _, trade in filtered.iterrows():
                ticker = trade['ticker']
                entry_date = pd.Timestamp(trade['entry_date'])
                if ticker in daily_data:
                    d = daily_data[ticker]
                    prior = d[d['Date'] <= entry_date]
                    atr_vals.append(prior['ATR_ratio_5_20'].iloc[-1] if not prior.empty else np.nan)
                else:
                    atr_vals.append(np.nan)
            filtered['ATR_ratio'] = atr_vals
            filtered = filtered.dropna(subset=['ATR_ratio'])
            filtered = filtered[filtered['ATR_ratio'] <= atr_threshold]

        filtered_m = compute_trade_metrics(filtered)

        wf_baseline.append({'window': wi+1, **w, **baseline_m})
        wf_filtered.append({'window': wi+1, **w, **filtered_m})

        b_pf = f"{baseline_m['pf']:.2f}" if baseline_m['pf'] != float('inf') else "inf"
        f_pf = f"{filtered_m['pf']:.2f}" if filtered_m['pf'] != float('inf') else "inf"
        log(f"  W{wi+1} {w['test_start']}→{w['test_end']}: "
            f"Base {baseline_m['trades']}t PF={b_pf} ${baseline_m['pnl']:.0f} | "
            f"Filt {filtered_m['trades']}t PF={f_pf} ${filtered_m['pnl']:.0f}")

    # Summary
    total_base_pnl = sum(w['pnl'] for w in wf_baseline)
    total_filt_pnl = sum(w['pnl'] for w in wf_filtered)
    total_base_trades = sum(w['trades'] for w in wf_baseline)
    total_filt_trades = sum(w['trades'] for w in wf_filtered)
    positive_base = sum(1 for w in wf_baseline if w['pnl'] > 0)
    positive_filt = sum(1 for w in wf_filtered if w['pnl'] > 0)

    log(f"\n  Walk-Forward Summary:")
    log(f"    Baseline: {total_base_trades}t, ${total_base_pnl:.0f}, "
        f"{positive_base}/{len(windows)} positive windows")
    log(f"    Filtered: {total_filt_trades}t, ${total_filt_pnl:.0f}, "
        f"{positive_filt}/{len(windows)} positive windows")

    return wf_baseline, wf_filtered


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    total_start = time.time()

    log("=" * 80)
    log("  PHASE 2.4 — Additional Indicators Research")
    log("  Config A: FD=10, ATR=0.60, RR=2.0, TAIL=0.15, STOP=0.15")
    log(f"  Tickers: {', '.join(TICKERS)}")
    log(f"  Period: {FULL_START} → {FULL_END}")
    log("=" * 80)

    # ── Step 1: Run baseline and extract trades ───────────────────────
    log("\n  Step 1: Running Config A baseline...")
    config = make_config_a()
    trades_df = run_baseline_get_trades(config, TICKERS, FULL_START, FULL_END)
    baseline_m = compute_trade_metrics(trades_df)
    log(f"  Baseline: {format_metrics(baseline_m)}")

    # ── Step 2: Precompute indicators for all tickers ─────────────────
    log("\n  Step 2: Computing indicators...")

    daily_data = {}  # {ticker: DataFrame with ADX, ATR_ratio, etc.}
    vwap_data = {}   # {ticker: M5 DataFrame with VWAP column}
    h1_data = {}     # {ticker: H1 DataFrame}

    for ticker in TICKERS:
        log(f"    {ticker}...")
        m5_df = load_ticker_data(ticker)

        # Daily aggregation + indicators
        daily = aggregate_m5_to_daily(m5_df)
        daily['ADX'] = compute_adx(daily, period=14)
        daily['ATR5'] = compute_atr_series(daily, period=5)
        daily['ATR20'] = compute_atr_series(daily, period=20)
        daily['ATR_ratio_5_20'] = daily['ATR5'] / daily['ATR20'].replace(0, np.nan)
        daily['ATR_ratio_5_20'] = daily['ATR_ratio_5_20'].fillna(1.0)
        daily['SMA20'] = daily['Close'].rolling(20).mean()
        daily_data[ticker] = daily

        # VWAP on M5
        vwap_df = compute_vwap(m5_df)
        vwap_data[ticker] = vwap_df

        # H1 aggregation + SMA
        h1 = aggregate_m5_to_h1(m5_df)
        h1_data[ticker] = h1

        log(f"      D1: {len(daily)} days, H1: {len(h1)} bars, "
            f"ADX mean={daily['ADX'][daily['ADX']>0].mean():.1f}")

    # ── Step 3: Run experiments ───────────────────────────────────────

    # EXPERIMENT 1: ADX
    trades_1, adx_result = experiment_1_adx(trades_df, daily_data)

    # EXPERIMENT 2: VWAP
    trades_2, vwap_result = experiment_2_vwap(trades_df, vwap_data)

    # EXPERIMENT 3: ATR Expansion
    trades_3, atr_result = experiment_3_atr_expansion(trades_df, daily_data)

    # EXPERIMENT 4: H1 Trend
    trades_4, h1_result = experiment_4_h1_trend(trades_df, h1_data)

    # ── Step 4: Combine best filters ──────────────────────────────────
    combine_best_filters(trades_df, daily_data, vwap_data, h1_data,
                          adx_result, atr_result, vwap_result, h1_result)

    # ── Step 5: Walk-forward with best filter(s) ─────────────────────
    adx_thresh = adx_result['best_threshold'] if adx_result else None
    atr_thresh = atr_result['best_threshold'] if atr_result else None

    if adx_thresh:
        log("\n  --- Walk-forward with ADX filter only ---")
        run_walkforward_with_filter(daily_data, vwap_data, h1_data,
                                     adx_threshold=adx_thresh)

    if atr_thresh:
        log("\n  --- Walk-forward with ATR ratio filter only ---")
        run_walkforward_with_filter(daily_data, vwap_data, h1_data,
                                     atr_threshold=atr_thresh)

    if adx_thresh and atr_thresh:
        log("\n  --- Walk-forward with ADX + ATR ratio combined ---")
        run_walkforward_with_filter(daily_data, vwap_data, h1_data,
                                     adx_threshold=adx_thresh,
                                     atr_threshold=atr_thresh)

    # ── Final summary ─────────────────────────────────────────────────
    elapsed = time.time() - total_start
    log(f"\n{'=' * 80}")
    log(f"  PHASE 2.4 COMPLETE — {elapsed:.0f}s ({elapsed/60:.1f}min)")
    log(f"{'=' * 80}")

    # Save report
    report_path = os.path.join(RESULTS_DIR, 'phase24_regime_filters.txt')
    with open(report_path, 'w') as f:
        f.write('\n'.join(LOG))
    log(f"\n  Report saved: {report_path}")


if __name__ == '__main__':
    main()
