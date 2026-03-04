"""
Walk-Forward Validation — FD=5 Fixed-Param Test

Same 6-window walk-forward as Phase 2.3, but with FIXED parameters
(no per-window grid optimization). Applies ADX + ATR expansion regime
filters as post-trade filters.

Config: FD=5, ATR_ENTRY=0.60, ATR_BLOCK=0.20, MIN_RR=2.0,
        TAIL=0.15, STOP=0.15, SAWING=5/30, same-level limit=2
Filters: ADX<=27, ATR_ratio<=1.3
Direction: BOTH, all 6 tickers
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

# Regime filter thresholds (same as FD=10 run)
ADX_THRESHOLD = 27
ATR_RATIO_THRESHOLD = 1.3

LOG = []


def log(msg=''):
    LOG.append(msg)
    print(msg)


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG BUILDERS
# ═══════════════════════════════════════════════════════════════════════════

def make_config(name='FD5_Config', fractal_depth=5) -> BacktestConfig:
    """Build config with specified FD and fixed params."""
    return BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=fractal_depth,
            tolerance_cents=0.05,
            tolerance_pct=0.001,
            atr_period=5,
            min_level_score=2,
            cross_count_invalidate=5,   # SAWING_THRESHOLD
            cross_count_window=30,      # SAWING_PERIOD
        ),
        pattern_config=PatternEngineConfig(
            tail_ratio_min=0.15,
            lp2_engulfing_required=True,
            clp_min_bars=3,
            clp_max_bars=7,
        ),
        filter_config=FilterChainConfig(
            atr_block_threshold=0.20,
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
        direction_filter=None,  # BOTH directions
        name=name,
    )


# ═══════════════════════════════════════════════════════════════════════════
# INDICATOR CALCULATIONS (same as Phase 2.4)
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


def compute_metrics(trades_df):
    if trades_df.empty:
        return {'trades': 0, 'wr': 0, 'pf': 0, 'pnl': 0, 'max_dd': 0}
    n = len(trades_df)
    winners = trades_df[trades_df['pnl'] > 0]
    losers = trades_df[trades_df['pnl'] <= 0]
    gp = winners['pnl'].sum()
    gl = abs(losers['pnl'].sum())
    pf = gp / gl if gl > 0 else (float('inf') if gp > 0 else 0)
    pnl = trades_df['pnl'].sum()
    cum_pnl = trades_df['pnl'].cumsum()
    peak = cum_pnl.cummax()
    dd = peak - cum_pnl
    max_dd = dd.max() if len(dd) > 0 else 0
    return {'trades': n, 'wr': len(winners) / n, 'pf': pf, 'pnl': pnl, 'max_dd': max_dd}


def fmt(m):
    pf_str = f"{m['pf']:.2f}" if m['pf'] != float('inf') else "inf"
    return f"{m['trades']}t, WR={m['wr']*100:.1f}%, PF={pf_str}, P&L=${m['pnl']:.0f}"


def apply_regime_filters(trades_df, daily_data, adx_thresh=None, atr_thresh=None):
    """Apply ADX and/or ATR ratio post-filters to a trades DataFrame."""
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
# FD=10 REFERENCE DATA (from Phase 2.4 walk-forward with ADX+ATR combined)
# ═══════════════════════════════════════════════════════════════════════════

# Phase 2.4 used 8 windows; we map to the 6-window schedule for comparison.
# Windows from Phase 2.4 ADX+ATR combined (8 windows):
FD10_WF_REFERENCE = {
    # Window test periods that overlap with our 6-window schedule
    # Phase 2.4 W1: 2025-05-10→06-10 (our W1)
    # Phase 2.4 W2: 2025-06-10→07-10 (our W2)
    # Phase 2.4 W3: 2025-07-10→08-10 (our W3)
    # Phase 2.4 W4: 2025-08-10→09-10 (our W4)
    # Phase 2.4 W5: 2025-09-10→10-10 (our W5)
    # Phase 2.4 W6: 2025-10-10→11-10 (our W6)
    'baseline': {  # FD=10 baseline (no filters)
        'W1': {'trades': 12, 'pf': 1.13, 'pnl': 339},
        'W2': {'trades': 7, 'pf': 0.37, 'pnl': -876},
        'W3': {'trades': 7, 'pf': 1.56, 'pnl': 611},
        'W4': {'trades': 8, 'pf': 1.52, 'pnl': 708},
        'W5': {'trades': 6, 'pf': 4.57, 'pnl': 1918},
        'W6': {'trades': 22, 'pf': 0.54, 'pnl': -2048},
    },
    'filtered': {  # FD=10 with ADX<=27 + ATR_ratio<=1.3
        'W1': {'trades': 9, 'pf': 1.07, 'pnl': 144},
        'W2': {'trades': 7, 'pf': 0.37, 'pnl': -876},
        'W3': {'trades': 2, 'pf': 0.00, 'pnl': -532},
        'W4': {'trades': 6, 'pf': 2.49, 'pnl': 1238},
        'W5': {'trades': 6, 'pf': 4.57, 'pnl': 1918},
        'W6': {'trades': 14, 'pf': 0.68, 'pnl': -811},
    },
}


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    total_start = time.time()

    log("=" * 90)
    log("  WALK-FORWARD VALIDATION — FD=5 Fixed-Param Test")
    log("=" * 90)
    log(f"  Config: FD=5, ATR_ENTRY=0.60, ATR_BLOCK=0.20, MIN_RR=2.0")
    log(f"          TAIL=0.15, STOP=0.15, SAWING=5/30, same-level limit=2")
    log(f"  Filters: ADX<={ADX_THRESHOLD}, ATR_ratio<={ATR_RATIO_THRESHOLD}")
    log(f"  Direction: BOTH | Tickers: {', '.join(TICKERS)}")
    log(f"  Period: {FULL_START} → {FULL_END}")
    log(f"  Windows: {MAX_WINDOWS} (3-month train, 1-month test)")
    log("")

    # ── Step 1: Precompute daily indicators ────────────────────────────
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
        log(f"    {ticker}: {len(daily)} days, ADX mean={daily['ADX'][daily['ADX']>0].mean():.1f}")

    # ── Step 2: Full-period baseline (FD=5) ────────────────────────────
    log(f"\n  Step 2: Full-period baseline (FD=5)...")
    config_fd5 = make_config('FD5_full', fractal_depth=5)
    full_trades = run_and_get_trades(config_fd5, TICKERS, FULL_START, FULL_END)
    full_m = compute_metrics(full_trades)
    log(f"    Baseline: {fmt(full_m)}, MaxDD=${full_m['max_dd']:.0f}")

    if not full_trades.empty:
        full_filtered = apply_regime_filters(full_trades, daily_data,
                                              adx_thresh=ADX_THRESHOLD,
                                              atr_thresh=ATR_RATIO_THRESHOLD)
        full_filt_m = compute_metrics(full_filtered)
        log(f"    +Filters: {fmt(full_filt_m)}, MaxDD=${full_filt_m['max_dd']:.0f}")

    # ── Step 3: 6-window walk-forward ──────────────────────────────────
    windows = generate_windows()
    log(f"\n  Step 3: Walk-forward ({len(windows)} windows, fixed params)")
    for i, w in enumerate(windows):
        log(f"    W{i+1}: Train {w['train_start']}→{w['train_end']}, "
            f"Test {w['test_start']}→{w['test_end']}")

    config = make_config('FD5_WF', fractal_depth=5)

    # Results storage
    wf_base = []   # baseline (no filters)
    wf_filt = []   # with ADX + ATR ratio filters

    log(f"\n{'━' * 90}")
    log(f"  {'Win':>4} {'Test Period':>25} {'Base':>6} {'B.PF':>6} {'B.P&L':>9} "
        f"{'Filt':>6} {'F.PF':>6} {'F.P&L':>9} {'F.WR':>6}")
    log(f"{'━' * 90}")

    for wi, w in enumerate(windows):
        # Run backtest on OOS (test) period with fixed config
        trades = run_and_get_trades(config, TICKERS,
                                     w['test_start'], w['test_end'])
        base_m = compute_metrics(trades)

        # Apply regime filters
        filtered = apply_regime_filters(trades, daily_data,
                                         adx_thresh=ADX_THRESHOLD,
                                         atr_thresh=ATR_RATIO_THRESHOLD)
        filt_m = compute_metrics(filtered)

        wf_base.append({'window': wi+1, **w, **base_m})
        wf_filt.append({'window': wi+1, **w, **filt_m})

        b_pf = f"{base_m['pf']:.2f}" if base_m['pf'] != float('inf') else "inf"
        f_pf = f"{filt_m['pf']:.2f}" if filt_m['pf'] != float('inf') else "inf"

        log(f"  W{wi+1:>2}  {w['test_start']}→{w['test_end']}  "
            f"{base_m['trades']:>5} {b_pf:>6} ${base_m['pnl']:>8.0f}  "
            f"{filt_m['trades']:>5} {f_pf:>6} ${filt_m['pnl']:>8.0f} "
            f"{filt_m['wr']*100:>5.1f}%")

    # ── Summary ────────────────────────────────────────────────────────
    log(f"\n{'━' * 90}")

    total_base_pnl = sum(w['pnl'] for w in wf_base)
    total_base_trades = sum(w['trades'] for w in wf_base)
    pos_base = sum(1 for w in wf_base if w['pnl'] > 0)
    base_pfs = [w['pf'] for w in wf_base if w['pf'] != float('inf') and w['trades'] > 0]

    total_filt_pnl = sum(w['pnl'] for w in wf_filt)
    total_filt_trades = sum(w['trades'] for w in wf_filt)
    pos_filt = sum(1 for w in wf_filt if w['pnl'] > 0)
    filt_pfs = [w['pf'] for w in wf_filt if w['pf'] != float('inf') and w['trades'] > 0]

    log(f"\n  FD=5 Walk-Forward Summary:")
    log(f"    Baseline: {total_base_trades}t, ${total_base_pnl:.0f}, "
        f"{pos_base}/{len(windows)} positive, mean PF={np.mean(base_pfs):.2f}")
    log(f"    +Filters: {total_filt_trades}t, ${total_filt_pnl:.0f}, "
        f"{pos_filt}/{len(windows)} positive, mean PF={np.mean(filt_pfs):.2f}")

    # ── Step 4: Comparison with FD=10 ──────────────────────────────────
    log(f"\n{'=' * 90}")
    log(f"  COMPARISON: FD=5 vs FD=10 (per-window)")
    log(f"{'=' * 90}")

    # Compare baseline (no filters)
    log(f"\n  --- Baseline (no filters) ---")
    log(f"  {'Win':>4} {'Period':>25} {'FD5 Tr':>7} {'FD5 PF':>7} {'FD5 P&L':>9} "
        f"{'FD10 Tr':>8} {'FD10 PF':>8} {'FD10 P&L':>9} {'Delta':>8}")
    log(f"  {'─' * 95}")

    fd10_base_total = 0
    fd10_base_trades = 0
    for wi, w in enumerate(wf_base):
        wkey = f"W{wi+1}"
        fd10 = FD10_WF_REFERENCE['baseline'].get(wkey, {})
        fd10_pnl = fd10.get('pnl', 0)
        fd10_tr = fd10.get('trades', 0)
        fd10_pf_val = fd10.get('pf', 0)
        fd10_base_total += fd10_pnl
        fd10_base_trades += fd10_tr

        fd5_pf = f"{w['pf']:.2f}" if w['pf'] != float('inf') else "inf"
        fd10_pf = f"{fd10_pf_val:.2f}" if fd10_pf_val != float('inf') else "inf"
        delta = w['pnl'] - fd10_pnl

        log(f"  W{wi+1:>2}  {w['test_start']}→{w['test_end']}  "
            f"{w['trades']:>6} {fd5_pf:>7} ${w['pnl']:>8.0f}  "
            f"{fd10_tr:>7} {fd10_pf:>8} ${fd10_pnl:>8.0f} "
            f"{'+'if delta>=0 else ''}${delta:>7.0f}")

    log(f"  {'─' * 95}")
    base_delta = total_base_pnl - fd10_base_total
    log(f"  Total: FD5={total_base_trades}t ${total_base_pnl:.0f} | "
        f"FD10={fd10_base_trades}t ${fd10_base_total:.0f} | "
        f"Delta={'+'if base_delta>=0 else ''}${base_delta:.0f}")

    # Compare filtered (ADX+ATR)
    log(f"\n  --- With ADX<={ADX_THRESHOLD} + ATR_ratio<={ATR_RATIO_THRESHOLD} ---")
    log(f"  {'Win':>4} {'Period':>25} {'FD5 Tr':>7} {'FD5 PF':>7} {'FD5 P&L':>9} "
        f"{'FD10 Tr':>8} {'FD10 PF':>8} {'FD10 P&L':>9} {'Delta':>8}")
    log(f"  {'─' * 95}")

    fd10_filt_total = 0
    fd10_filt_trades = 0
    for wi, w in enumerate(wf_filt):
        wkey = f"W{wi+1}"
        fd10 = FD10_WF_REFERENCE['filtered'].get(wkey, {})
        fd10_pnl = fd10.get('pnl', 0)
        fd10_tr = fd10.get('trades', 0)
        fd10_pf_val = fd10.get('pf', 0)
        fd10_filt_total += fd10_pnl
        fd10_filt_trades += fd10_tr

        fd5_pf = f"{w['pf']:.2f}" if w['pf'] != float('inf') else "inf"
        fd10_pf = f"{fd10_pf_val:.2f}" if fd10_pf_val != float('inf') else "inf"
        delta = w['pnl'] - fd10_pnl

        log(f"  W{wi+1:>2}  {w['test_start']}→{w['test_end']}  "
            f"{w['trades']:>6} {fd5_pf:>7} ${w['pnl']:>8.0f}  "
            f"{fd10_tr:>7} {fd10_pf:>8} ${fd10_pnl:>8.0f} "
            f"{'+'if delta>=0 else ''}${delta:>7.0f}")

    log(f"  {'─' * 95}")
    filt_delta = total_filt_pnl - fd10_filt_total
    log(f"  Total: FD5={total_filt_trades}t ${total_filt_pnl:.0f} | "
        f"FD10={fd10_filt_trades}t ${fd10_filt_total:.0f} | "
        f"Delta={'+'if filt_delta>=0 else ''}${filt_delta:.0f}")

    # ── Verdict ────────────────────────────────────────────────────────
    log(f"\n{'=' * 90}")
    log(f"  VERDICT")
    log(f"{'=' * 90}")
    log(f"  FD=5 Baseline:  {total_base_trades}t, ${total_base_pnl:.0f}, {pos_base}/{len(windows)} positive")
    log(f"  FD=5 Filtered:  {total_filt_trades}t, ${total_filt_pnl:.0f}, {pos_filt}/{len(windows)} positive")
    log(f"  FD=10 Baseline: {fd10_base_trades}t, ${fd10_base_total:.0f}")
    log(f"  FD=10 Filtered: {fd10_filt_trades}t, ${fd10_filt_total:.0f}")
    log(f"")

    if total_filt_pnl > 0 and pos_filt >= len(windows) / 2:
        if np.mean(filt_pfs) > 1.5:
            log(f"  >> FD=5 filtered: ROBUST — positive P&L, {pos_filt}/{len(windows)} positive, "
                f"mean PF={np.mean(filt_pfs):.2f}")
        else:
            log(f"  >> FD=5 filtered: MARGINAL — positive P&L but mean PF={np.mean(filt_pfs):.2f}")
    else:
        log(f"  >> FD=5 filtered: FRAGILE — ${total_filt_pnl:.0f} P&L, "
            f"{pos_filt}/{len(windows)} positive")

    if total_filt_pnl > fd10_filt_total:
        log(f"  >> FD=5 OUTPERFORMS FD=10 by ${total_filt_pnl - fd10_filt_total:.0f} (filtered)")
    else:
        log(f"  >> FD=10 outperforms FD=5 by ${fd10_filt_total - total_filt_pnl:.0f} (filtered)")

    elapsed = time.time() - total_start
    log(f"\n{'=' * 90}")
    log(f"  COMPLETE — {elapsed:.0f}s ({elapsed/60:.1f}min)")
    log(f"{'=' * 90}")

    # Save report
    report_path = os.path.join(RESULTS_DIR, 'walkforward_fd5_test.txt')
    with open(report_path, 'w') as f:
        f.write('\n'.join(LOG))
    log(f"\n  Report saved: {report_path}")


if __name__ == '__main__':
    main()
