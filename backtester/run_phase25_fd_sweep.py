"""
Phase 2.5 — Fractal Depth Sweep: FD=5, 7, 10 across all available tickers.

Config (fixed for all runs):
  ATR_ENTRY=0.60, ATR_BLOCK=0.20, MIN_RR=2.0, TAIL=0.15, STOP=0.15
  ADX <= 27, ATR expansion ratio <= 1.3
  Direction: BOTH, SAWING_THRESHOLD=5, SAWING_PERIOD=30

Three runs: FD=5, FD=7, FD=10

Reports:
  1. Total trades, WR, PF, Sharpe, DD, P&L per run
  2. Per-ticker breakdown
  3. Levels detected vs surviving
  4. Signal funnel summary
  5. Best run → 6-window walk-forward (fixed params)
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
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

# All tickers with available data (AAPL has no data file)
TICKERS = ['TSLA', 'AMZN', 'GOOGL', 'META', 'MSFT', 'NVDA']

FULL_START = '2025-02-10'
FULL_END = '2026-01-31'

# Phase 2.3 walk-forward windows
WF_WINDOWS = [
    {'id': 1, 'test_start': '2025-05-10', 'test_end': '2025-06-10'},
    {'id': 2, 'test_start': '2025-06-10', 'test_end': '2025-07-10'},
    {'id': 3, 'test_start': '2025-07-10', 'test_end': '2025-08-10'},
    {'id': 4, 'test_start': '2025-08-10', 'test_end': '2025-09-10'},
    {'id': 5, 'test_start': '2025-09-10', 'test_end': '2025-10-10'},
    {'id': 6, 'test_start': '2025-10-10', 'test_end': '2025-11-10'},
]

LOG = []


def log(msg=''):
    LOG.append(msg)
    print(msg)


# ═══════════════════════════════════════════════════════════════════════════
# INDICATOR CALCULATIONS (for post-hoc ADX + ATR ratio filtering)
# ═══════════════════════════════════════════════════════════════════════════

def compute_atr_series(daily, period):
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
        up = high[i] - high[i - 1]
        dn = low[i - 1] - low[i]
        plus_dm[i] = up if (up > dn and up > 0) else 0.0
        minus_dm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]),
                     abs(low[i] - close[i - 1]))

    def wilder(arr, p):
        out = np.zeros(len(arr))
        if p < len(arr):
            out[p] = np.sum(arr[1:p + 1])
            for i in range(p + 1, len(arr)):
                out[i] = out[i - 1] - out[i - 1] / p + arr[i]
        return out

    s_tr = wilder(tr, period)
    s_pdm = wilder(plus_dm, period)
    s_mdm = wilder(minus_dm, period)

    plus_di = np.zeros(n)
    minus_di = np.zeros(n)
    dx = np.zeros(n)

    for i in range(period, n):
        if s_tr[i] > 0:
            plus_di[i] = 100 * s_pdm[i] / s_tr[i]
            minus_di[i] = 100 * s_mdm[i] / s_tr[i]
        s = plus_di[i] + minus_di[i]
        if s > 0:
            dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / s

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
    rth = df[(minutes >= 16 * 60 + 30) & (minutes < 23 * 60)].copy()
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

def make_config(fractal_depth, name=''):
    """Build config with given FD. All other params fixed."""
    return BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=fractal_depth,
            tolerance_cents=0.05,
            tolerance_pct=0.001,
            atr_period=5,
            min_level_score=5,
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
            atr_block_threshold=0.20,   # ATR_BLOCK
            atr_entry_threshold=0.60,   # ATR_ENTRY
            enable_volume_filter=True,
            enable_time_filter=True,
            enable_squeeze_filter=True,
        ),
        risk_config=RiskManagerConfig(
            min_rr=2.0,
            max_stop_atr_pct=0.15,      # STOP
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
        direction_filter=None,
        name=name or f'FD{fractal_depth}',
    )


# ═══════════════════════════════════════════════════════════════════════════
# RUN A SINGLE BACKTEST (returns rich result per ticker)
# ═══════════════════════════════════════════════════════════════════════════

def run_backtest(config, tickers, start_date, end_date, daily_indicators):
    """Run backtest on all tickers, return list of per-ticker result dicts."""
    results = []
    for ticker in tickers:
        m5_df = load_ticker_data(ticker)
        bt = Backtester(config)
        result = bt.run(m5_df, start_date=start_date, end_date=end_date)

        # Get funnel summary
        funnel = bt.filter_chain.get_funnel_summary()

        # Get level stats
        level_stats = result.level_stats

        # Annotate trades with ADX + ATR ratio
        trades = []
        for trade in result.trades:
            entry_date = trade.entry_time.normalize().date() if trade.entry_time else None
            adx_val = np.nan
            atr_ratio_val = np.nan
            if ticker in daily_indicators and entry_date is not None:
                d = daily_indicators[ticker]
                entry_ts = pd.Timestamp(entry_date)
                prior = d[d['Date'] <= entry_ts]
                if not prior.empty:
                    row = prior.iloc[-1]
                    adx_val = row.get('ADX', np.nan)
                    if adx_val == 0:
                        adx_val = np.nan
                    atr_ratio_val = row.get('ATR_ratio_5_20', np.nan)

            trades.append({
                'ticker': ticker,
                'entry_time': trade.entry_time,
                'exit_time': trade.exit_time,
                'direction': trade.direction.value,
                'entry_price': trade.entry_price,
                'exit_price': trade.exit_price,
                'pnl': trade.pnl,
                'pnl_r': trade.pnl_r,
                'is_winner': trade.pnl > 0,
                'ADX': adx_val,
                'ATR_ratio': atr_ratio_val,
            })

        results.append({
            'ticker': ticker,
            'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
            'funnel': funnel,
            'level_stats': level_stats,
            'proximity_events': bt.proximity_events,
            'patterns_found': bt.patterns_found,
        })

    return results


def apply_filters(trades_df, adx_max=None, atr_ratio_max=None):
    if trades_df.empty:
        return trades_df
    filtered = trades_df.copy()
    if adx_max is not None:
        has_adx = filtered['ADX'].notna()
        filtered = filtered[~has_adx | (filtered['ADX'] <= adx_max)]
    if atr_ratio_max is not None:
        has_ratio = filtered['ATR_ratio'].notna()
        filtered = filtered[~has_ratio | (filtered['ATR_ratio'] <= atr_ratio_max)]
    return filtered


def compute_metrics(trades_df):
    if trades_df.empty:
        return {'trades': 0, 'wr': 0.0, 'pf': 0.0, 'pnl': 0.0,
                'max_dd': 0.0, 'sharpe': 0.0, 'gross_profit': 0.0, 'gross_loss': 0.0}
    n = len(trades_df)
    winners = trades_df[trades_df['pnl'] > 0]
    losers = trades_df[trades_df['pnl'] <= 0]
    gp = winners['pnl'].sum()
    gl = abs(losers['pnl'].sum())
    pf = gp / gl if gl > 0 else (float('inf') if gp > 0 else 0.0)
    total_pnl = trades_df['pnl'].sum()
    cum = trades_df['pnl'].cumsum()
    peak = cum.cummax()
    max_dd = (peak - cum).max()
    if n >= 5:
        pnl_arr = trades_df['pnl'].values
        sharpe = np.mean(pnl_arr) / np.std(pnl_arr) * np.sqrt(n) if np.std(pnl_arr) > 0 else 0.0
    else:
        sharpe = 0.0
    return {
        'trades': n, 'wr': len(winners) / n, 'pf': pf, 'pnl': total_pnl,
        'max_dd': max_dd, 'sharpe': sharpe, 'gross_profit': gp, 'gross_loss': gl,
    }


def pf_str(pf):
    return f"{pf:.2f}" if pf != float('inf') else "inf"


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()

    log("=" * 95)
    log("  PHASE 2.5 — Fractal Depth Sweep: FD=5, 7, 10")
    log("=" * 95)
    log("  Fixed params: ATR_ENTRY=0.60, ATR_BLOCK=0.20, RR=2.0, TAIL=0.15, STOP=0.15")
    log("  Filters: ADX<=27, ATR_ratio<=1.3 (post-hoc)")
    log("  Sawing: cross_count_invalidate=5, cross_count_window=30")
    log("  Direction: BOTH for all tickers")
    log(f"  Tickers: {', '.join(TICKERS)}  (AAPL data file not available)")
    log(f"  Period: {FULL_START} → {FULL_END}")
    log()

    # ── Precompute daily indicators ────────────────────────────────────
    log("  Precomputing D1 indicators...")
    daily_indicators = {}
    for ticker in TICKERS:
        m5_df = load_ticker_data(ticker)
        daily = aggregate_m5_to_daily(m5_df)
        daily['ADX'] = compute_adx(daily, 14)
        daily['ATR5'] = compute_atr_series(daily, 5)
        daily['ATR20'] = compute_atr_series(daily, 20)
        daily['ATR_ratio_5_20'] = daily['ATR5'] / daily['ATR20'].replace(0, np.nan)
        daily['ATR_ratio_5_20'] = daily['ATR_ratio_5_20'].fillna(1.0)
        daily_indicators[ticker] = daily
    log("  Done.\n")

    # ══════════════════════════════════════════════════════════════════════
    # RUN A/B/C
    # ══════════════════════════════════════════════════════════════════════

    RUNS = [
        ('A', 5),
        ('B', 7),
        ('C', 10),
    ]

    ADX_MAX = 27
    ATR_MAX = 1.3

    run_summaries = {}  # run_label -> {metrics, per_ticker, ...}

    for run_label, fd in RUNS:
        log("━" * 95)
        log(f"  RUN {run_label}: FRACTAL_DEPTH = {fd}")
        log("━" * 95)

        config = make_config(fd, name=f'Run{run_label}_FD{fd}')
        ticker_results = run_backtest(config, TICKERS, FULL_START, FULL_END, daily_indicators)

        # ── Aggregate all trades ───────────────────────────────────────
        all_trades_raw = pd.concat([r['trades'] for r in ticker_results if not r['trades'].empty],
                                   ignore_index=True)
        all_trades_filtered = apply_filters(all_trades_raw, adx_max=ADX_MAX, atr_ratio_max=ATR_MAX)

        raw_m = compute_metrics(all_trades_raw)
        filt_m = compute_metrics(all_trades_filtered)

        # ── 1. Summary ─────────────────────────────────────────────────
        log(f"\n  ┌─ SUMMARY (FD={fd}) ─────────────────────────────────────────────────────┐")
        log(f"  │  Raw (no regime filter):     {raw_m['trades']:>4}t  WR={raw_m['wr']*100:>5.1f}%  "
            f"PF={pf_str(raw_m['pf']):>6}  P&L=${raw_m['pnl']:>9,.0f}  DD=${raw_m['max_dd']:>7,.0f}  "
            f"Sh={raw_m['sharpe']:>5.2f}  │")
        log(f"  │  + ADX<=27 + ATR<=1.3:       {filt_m['trades']:>4}t  WR={filt_m['wr']*100:>5.1f}%  "
            f"PF={pf_str(filt_m['pf']):>6}  P&L=${filt_m['pnl']:>9,.0f}  DD=${filt_m['max_dd']:>7,.0f}  "
            f"Sh={filt_m['sharpe']:>5.2f}  │")
        blocked = raw_m['trades'] - filt_m['trades']
        log(f"  │  Regime filter blocked: {blocked} trades                                          │")
        log(f"  └──────────────────────────────────────────────────────────────────────────┘")

        # ── 2. Per-ticker breakdown ────────────────────────────────────
        log(f"\n  Per-Ticker Breakdown (with ADX+ATR filter):")
        log(f"  {'Ticker':>8} {'Raw':>5} {'Filt':>5} {'WR':>7} {'PF':>7} {'P&L':>10} {'DD':>8} {'Sh':>6}")
        log(f"  {'─' * 60}")

        per_ticker = {}
        for r in ticker_results:
            ticker = r['ticker']
            raw_t = r['trades']
            filt_t = apply_filters(raw_t, adx_max=ADX_MAX, atr_ratio_max=ATR_MAX)
            raw_n = len(raw_t)
            m = compute_metrics(filt_t)
            per_ticker[ticker] = m
            log(f"  {ticker:>8} {raw_n:>5} {m['trades']:>5} {m['wr']*100:>6.1f}% "
                f"{pf_str(m['pf']):>6} ${m['pnl']:>9,.0f} ${m['max_dd']:>7,.0f} {m['sharpe']:>6.2f}")

        # ── 3. Levels detected vs surviving ────────────────────────────
        log(f"\n  Level Statistics:")
        log(f"  {'Ticker':>8} {'Total':>7} {'Confirmed':>10} {'Mirrors':>8} "
            f"{'Invalidated':>12} {'AvgScore':>9} {'AvgTouch':>9}")
        log(f"  {'─' * 70}")

        total_levels = 0
        total_confirmed = 0
        total_mirrors = 0
        total_invalidated = 0

        for r in ticker_results:
            ls = r['level_stats']
            total_levels += ls.get('total_levels', 0)
            total_confirmed += ls.get('confirmed_bpu', 0)
            total_mirrors += ls.get('mirrors', 0)
            total_invalidated += ls.get('invalidated_sawing', 0)
            log(f"  {r['ticker']:>8} {ls.get('total_levels',0):>7} "
                f"{ls.get('confirmed_bpu',0):>10} {ls.get('mirrors',0):>8} "
                f"{ls.get('invalidated_sawing',0):>12} "
                f"{ls.get('avg_score',0):>9.1f} {ls.get('avg_touches',0):>9.2f}")

        log(f"  {'TOTAL':>8} {total_levels:>7} {total_confirmed:>10} "
            f"{total_mirrors:>8} {total_invalidated:>12}")

        # ── 4. Signal funnel summary ───────────────────────────────────
        log(f"\n  Signal Funnel (aggregate across tickers):")

        # Aggregate funnel
        agg_funnel = {}
        for r in ticker_results:
            for k, v in r['funnel'].items():
                agg_funnel[k] = agg_funnel.get(k, 0) + v

        total_sig = agg_funnel.get('total_signals', 0)
        passed = agg_funnel.get('passed', 0)
        log(f"    Total signals generated:       {total_sig:>6}")
        log(f"    Passed all filters → trades:   {passed:>6}")
        if total_sig > 0:
            log(f"    Pass rate:                     {passed/total_sig*100:>5.1f}%")
        log(f"    ────────────────────────────────────")

        # Print all blocked_by entries
        for k in sorted(agg_funnel.keys()):
            if k.startswith('blocked_by_') and agg_funnel[k] > 0:
                name = k.replace('blocked_by_', '')
                pct = agg_funnel[k] / total_sig * 100 if total_sig > 0 else 0
                log(f"    Blocked by {name:>18}: {agg_funnel[k]:>6} ({pct:>5.1f}%)")

        # Also show proximity and pattern counts
        total_prox = sum(r['proximity_events'] for r in ticker_results)
        total_pat = sum(r['patterns_found'] for r in ticker_results)
        log(f"    ────────────────────────────────────")
        log(f"    Proximity events (bar near lvl): {total_prox:>6}")
        log(f"    M5 patterns found:               {total_pat:>6}")
        log(f"    Signals from patterns:           {total_sig:>6}")

        run_summaries[run_label] = {
            'fd': fd,
            'raw_metrics': raw_m,
            'filtered_metrics': filt_m,
            'per_ticker': per_ticker,
            'total_levels': total_levels,
            'total_confirmed': total_confirmed,
            'funnel': agg_funnel,
        }

        log()

    # ══════════════════════════════════════════════════════════════════════
    # COMPARISON TABLE
    # ══════════════════════════════════════════════════════════════════════

    log("=" * 95)
    log("  COMPARISON: ALL THREE RUNS (with ADX<=27 + ATR<=1.3 filter)")
    log("=" * 95)
    log(f"\n  {'Run':>4} {'FD':>4} {'Trades':>7} {'WR':>7} {'PF':>7} {'P&L':>10} "
        f"{'MaxDD':>8} {'Sharpe':>7} {'Levels':>7} {'Sigs':>6} {'PassRate':>9}")
    log(f"  {'─' * 85}")

    best_run = None
    best_pf = 0

    for run_label in ['A', 'B', 'C']:
        s = run_summaries[run_label]
        m = s['filtered_metrics']
        f = s['funnel']
        total_sig = f.get('total_signals', 0)
        passed = f.get('passed', 0)
        pr = f"{passed/total_sig*100:.1f}%" if total_sig > 0 else "n/a"

        log(f"  {run_label:>4} {s['fd']:>4} {m['trades']:>7} {m['wr']*100:>6.1f}% "
            f"{pf_str(m['pf']):>6} ${m['pnl']:>9,.0f} ${m['max_dd']:>7,.0f} "
            f"{m['sharpe']:>7.2f} {s['total_levels']:>7} {total_sig:>6} {pr:>9}")

        # Pick best by PF (must have >= 10 trades)
        if m['trades'] >= 10 and m['pf'] > best_pf:
            best_pf = m['pf']
            best_run = run_label

    if best_run is None:
        # Fallback: pick run with most trades
        best_run = max(run_summaries, key=lambda k: run_summaries[k]['filtered_metrics']['trades'])

    log(f"\n  >>> BEST RUN: {best_run} (FD={run_summaries[best_run]['fd']}) — "
        f"PF={pf_str(run_summaries[best_run]['filtered_metrics']['pf'])}, "
        f"{run_summaries[best_run]['filtered_metrics']['trades']} trades")

    # ══════════════════════════════════════════════════════════════════════
    # WALK-FORWARD ON BEST RUN
    # ══════════════════════════════════════════════════════════════════════

    best_fd = run_summaries[best_run]['fd']
    log(f"\n{'━' * 95}")
    log(f"  6-WINDOW WALK-FORWARD — Best Run {best_run} (FD={best_fd}), Fixed Params")
    log(f"{'━' * 95}")
    log(f"  No per-window optimization. ADX<=27 + ATR<=1.3 regime filter applied.")
    log(f"\n  {'Win':>4} {'Test Period':>26} {'Raw':>5} {'Filt':>5} {'WR':>7} "
        f"{'PF':>7} {'P&L':>10} {'DD':>8} {'Sh':>7}")
    log(f"  {'─' * 85}")

    config = make_config(best_fd, name=f'WF_FD{best_fd}')
    wf_results = []

    for w in WF_WINDOWS:
        ticker_results = run_backtest(config, TICKERS, w['test_start'], w['test_end'],
                                       daily_indicators)
        all_raw = pd.concat([r['trades'] for r in ticker_results if not r['trades'].empty],
                             ignore_index=True) if any(not r['trades'].empty for r in ticker_results) else pd.DataFrame()
        all_filt = apply_filters(all_raw, adx_max=ADX_MAX, atr_ratio_max=ATR_MAX)
        raw_n = len(all_raw)
        m = compute_metrics(all_filt)
        m['window'] = w['id']
        m['test_start'] = w['test_start']
        m['test_end'] = w['test_end']
        m['raw_trades'] = raw_n
        wf_results.append(m)

        log(f"  W{w['id']:>2}  {w['test_start']}→{w['test_end']}  "
            f"{raw_n:>4} {m['trades']:>5} {m['wr']*100:>6.1f}% "
            f"{pf_str(m['pf']):>6} ${m['pnl']:>9,.0f} ${m['max_dd']:>7,.0f} "
            f"{m['sharpe']:>7.2f}")

    # Aggregate
    total_trades = sum(w['trades'] for w in wf_results)
    total_raw = sum(w['raw_trades'] for w in wf_results)
    total_pnl = sum(w['pnl'] for w in wf_results)
    total_gp = sum(w['gross_profit'] for w in wf_results)
    total_gl = sum(w['gross_loss'] for w in wf_results)
    agg_pf = total_gp / total_gl if total_gl > 0 else (float('inf') if total_gp > 0 else 0)
    positive = sum(1 for w in wf_results if w['pnl'] > 0)
    pf_gt1 = sum(1 for w in wf_results if w['pf'] > 1.0)
    mean_sharpe = np.mean([w['sharpe'] for w in wf_results if w['trades'] >= 5])

    cum_pnl = np.cumsum([w['pnl'] for w in wf_results])
    peak = np.maximum.accumulate(cum_pnl)
    total_dd = np.max(peak - cum_pnl) if len(cum_pnl) > 0 else 0

    log(f"  {'─' * 85}")
    log(f"  AGGREGATE: {total_raw} raw → {total_trades} filtered trades")
    log(f"  PF={pf_str(agg_pf)}, P&L=${total_pnl:,.0f}, DD=${total_dd:,.0f}, "
        f"Mean Sharpe={mean_sharpe:.2f}")
    log(f"  Positive windows: {positive}/{len(WF_WINDOWS)}, PF>1: {pf_gt1}/{len(WF_WINDOWS)}")

    # ── Compare to Phase 2.3 and 2.4b ─────────────────────────────────
    log(f"\n  ── Walk-Forward Comparison ──")
    log(f"  {'Approach':>45} {'Trades':>7} {'PF':>7} {'P&L':>10} {'Pos':>5} {'Sh':>7}")
    log(f"  {'─' * 85}")
    log(f"  {'Phase 2.3 Adaptive WF':>45} {'150':>7} {'0.89':>7} {'$-6,251':>10} {'3/6':>5} {'-2.23':>7}")
    log(f"  {'Phase 2.4b FD=10 no filter':>45} {'62':>7} {'1.06':>7} {'$653':>10} {'4/6':>5} {'0.08':>7}")
    log(f"  {'Phase 2.4b FD=10 + ADX+ATR':>45} {'44':>7} {'1.14':>7} {'$1,082':>10} {'3/6':>5} {'0.17':>7}")
    ms_s = f"{mean_sharpe:.2f}" if not np.isnan(mean_sharpe) else "n/a"
    log(f"  {'Phase 2.5 FD=' + str(best_fd) + ' + ADX+ATR (THIS)':>45} "
        f"{total_trades:>7} {pf_str(agg_pf):>7} ${total_pnl:>9,.0f} "
        f"{positive}/{len(WF_WINDOWS):>3} {ms_s:>7}")

    # ══════════════════════════════════════════════════════════════════════
    # DONE
    # ══════════════════════════════════════════════════════════════════════

    elapsed = time.time() - t0
    log(f"\n{'=' * 95}")
    log(f"  PHASE 2.5 COMPLETE — {elapsed:.0f}s ({elapsed/60:.1f}min)")
    log(f"{'=' * 95}")

    # Save results
    report_path = os.path.join(RESULTS_DIR, 'phase25_fd_sweep.txt')
    with open(report_path, 'w') as f:
        f.write('\n'.join(LOG))
    log(f"  Report saved: {report_path}")

    # Also save JSON summary
    json_data = {
        'phase': '2.5',
        'description': 'Fractal depth sweep FD=5,7,10 with regime filters',
        'tickers': TICKERS,
        'period': f'{FULL_START} to {FULL_END}',
        'fixed_params': {
            'atr_entry': 0.60, 'atr_block': 0.20, 'min_rr': 2.0,
            'tail_ratio_min': 0.15, 'max_stop_atr_pct': 0.15,
            'adx_max': ADX_MAX, 'atr_ratio_max': ATR_MAX,
            'cross_count_invalidate': 5, 'cross_count_window': 30,
        },
        'runs': {},
        'best_run': best_run,
        'best_fd': best_fd,
        'walkforward': {
            'windows': wf_results,
            'aggregate': {
                'total_trades': total_trades,
                'pf': agg_pf,
                'pnl': total_pnl,
                'dd': total_dd,
                'positive_windows': positive,
            },
        },
    }
    for rl in ['A', 'B', 'C']:
        s = run_summaries[rl]
        json_data['runs'][rl] = {
            'fractal_depth': s['fd'],
            'raw': s['raw_metrics'],
            'filtered': s['filtered_metrics'],
            'levels': s['total_levels'],
            'confirmed': s['total_confirmed'],
        }

    json_path = os.path.join(RESULTS_DIR, 'phase25_fd_sweep.json')
    with open(json_path, 'w') as f:
        json.dump(json_data, f, indent=2, default=str)
    log(f"  JSON saved: {json_path}")


if __name__ == '__main__':
    main()
