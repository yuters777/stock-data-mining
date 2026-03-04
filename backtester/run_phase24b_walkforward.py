"""
Phase 2.4b — Full Walk-Forward with ADX + ATR Expansion Filters

Exact same 6 windows as Phase 2.3 (3mo train, 1mo test, rolling):
  W1: Train 2025-02-10→2025-05-10, Test 2025-05-10→2025-06-10
  W2: Train 2025-03-10→2025-06-10, Test 2025-06-10→2025-07-10
  W3: Train 2025-04-10→2025-07-10, Test 2025-07-10→2025-08-10
  W4: Train 2025-05-10→2025-08-10, Test 2025-08-10→2025-09-10
  W5: Train 2025-06-10→2025-09-10, Test 2025-09-10→2025-10-10
  W6: Train 2025-07-10→2025-10-10, Test 2025-10-10→2025-11-10

Fixed params Config A: FD=10, ATR_ENTRY=0.60, RR=2.0, TAIL=0.15, STOP=0.15
NO per-window optimization — all params fixed.

Three runs:
  (1) Config A, no filters           (baseline)
  (2) Config A + ADX<=27 + ATR<=1.3  (tight filters)
  (3) Config A with relaxed filters  (ADX<=30, ATR<=1.5)

Also: Trade count concern — full-period analysis with relaxed thresholds.
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

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

TICKERS = ['TSLA', 'AMZN', 'GOOGL', 'META', 'MSFT', 'NVDA']

FULL_START = '2025-02-10'
FULL_END = '2026-01-31'

# Exact Phase 2.3 windows
WF_WINDOWS = [
    {'id': 1, 'train_start': '2025-02-10', 'train_end': '2025-05-10',
     'test_start': '2025-05-10', 'test_end': '2025-06-10'},
    {'id': 2, 'train_start': '2025-03-10', 'train_end': '2025-06-10',
     'test_start': '2025-06-10', 'test_end': '2025-07-10'},
    {'id': 3, 'train_start': '2025-04-10', 'train_end': '2025-07-10',
     'test_start': '2025-07-10', 'test_end': '2025-08-10'},
    {'id': 4, 'train_start': '2025-05-10', 'train_end': '2025-08-10',
     'test_start': '2025-08-10', 'test_end': '2025-09-10'},
    {'id': 5, 'train_start': '2025-06-10', 'train_end': '2025-09-10',
     'test_start': '2025-09-10', 'test_end': '2025-10-10'},
    {'id': 6, 'train_start': '2025-07-10', 'train_end': '2025-10-10',
     'test_start': '2025-10-10', 'test_end': '2025-11-10'},
]

LOG = []


def log(msg=''):
    LOG.append(msg)
    print(msg)


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG A
# ═══════════════════════════════════════════════════════════════════════════

def make_config_a(name='ConfigA') -> BacktestConfig:
    """Config A: FD=10, ATR_ENTRY=0.60, RR=2.0, TAIL=0.15, STOP=0.15"""
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
        direction_filter=None,
        name=name,
    )


# ═══════════════════════════════════════════════════════════════════════════
# INDICATOR CALCULATIONS
# ═══════════════════════════════════════════════════════════════════════════

def compute_atr_series(daily, period):
    """ATR rolling mean of TR."""
    high = daily['High'].values
    low = daily['Low'].values
    close = daily['Close'].values
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(high - low,
                    np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    return pd.Series(tr, index=daily.index).rolling(window=period, min_periods=1).mean()


def compute_adx(daily, period=14):
    """ADX(period) via Wilder's smoothing."""
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
    """M5 → D1 (regular session 16:30-23:00 IST)."""
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
# TRADE EXTRACTION WITH INDICATORS
# ═══════════════════════════════════════════════════════════════════════════

def extract_trades(config, tickers, start_date, end_date, daily_indicators):
    """Run backtest, extract trades, annotate with ADX and ATR ratio."""
    all_trades = []
    for ticker in tickers:
        m5_df = load_ticker_data(ticker)
        bt = Backtester(config)
        result = bt.run(m5_df, start_date=start_date, end_date=end_date)
        for trade in result.trades:
            entry_date = trade.entry_time.normalize().date() if trade.entry_time else None

            # Look up indicators
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

            all_trades.append({
                'ticker': ticker,
                'entry_time': trade.entry_time,
                'entry_date': entry_date,
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

    return pd.DataFrame(all_trades) if all_trades else pd.DataFrame()


def apply_filters(trades_df, adx_max=None, atr_ratio_max=None):
    """Filter trades by ADX and/or ATR ratio thresholds."""
    if trades_df.empty:
        return trades_df

    filtered = trades_df.copy()
    if adx_max is not None:
        # Keep trades with valid ADX <= threshold, OR trades with no ADX data (warmup)
        has_adx = filtered['ADX'].notna()
        filtered = filtered[~has_adx | (filtered['ADX'] <= adx_max)]
    if atr_ratio_max is not None:
        has_ratio = filtered['ATR_ratio'].notna()
        filtered = filtered[~has_ratio | (filtered['ATR_ratio'] <= atr_ratio_max)]

    return filtered


def compute_metrics(trades_df):
    """Standard metrics dict from trades DataFrame."""
    if trades_df.empty:
        return {'trades': 0, 'wr': 0.0, 'pf': 0.0, 'pnl': 0.0,
                'max_dd': 0.0, 'sharpe': 0.0, 'gross_profit': 0.0,
                'gross_loss': 0.0}

    n = len(trades_df)
    winners = trades_df[trades_df['pnl'] > 0]
    losers = trades_df[trades_df['pnl'] <= 0]
    gp = winners['pnl'].sum()
    gl = abs(losers['pnl'].sum())
    pf = gp / gl if gl > 0 else (float('inf') if gp > 0 else 0.0)
    total_pnl = trades_df['pnl'].sum()

    # Max drawdown
    cum = trades_df['pnl'].cumsum()
    peak = cum.cummax()
    max_dd = (peak - cum).max()

    # Sharpe from per-trade P&L (simpler, avoids same-day edge cases)
    if n >= 5:
        pnl_arr = trades_df['pnl'].values
        if np.std(pnl_arr) > 0:
            sharpe = np.mean(pnl_arr) / np.std(pnl_arr) * np.sqrt(n)
        else:
            sharpe = 0.0
    else:
        sharpe = 0.0

    return {
        'trades': n,
        'wr': len(winners) / n,
        'pf': pf,
        'pnl': total_pnl,
        'max_dd': max_dd,
        'sharpe': sharpe,
        'gross_profit': gp,
        'gross_loss': gl,
    }


def fmt(m):
    """Short format for metrics."""
    pf_s = f"{m['pf']:.2f}" if m['pf'] != float('inf') else "inf"
    return (f"{m['trades']:>4}t  WR={m['wr']*100:>5.1f}%  PF={pf_s:>6}  "
            f"P&L=${m['pnl']:>8.0f}  DD=${m['max_dd']:>7.0f}  Sh={m['sharpe']:>6.2f}")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()

    log("=" * 90)
    log("  PHASE 2.4b — Full Walk-Forward: Config A + ADX + ATR Expansion Filters")
    log("=" * 90)
    log(f"  Config A: FD=10, ATR_ENTRY=0.60, RR=2.0, TAIL=0.15, STOP=0.15")
    log(f"  Tickers: {', '.join(TICKERS)}")
    log(f"  Windows: {len(WF_WINDOWS)} (same as Phase 2.3)")
    log(f"  NO per-window optimization — all params fixed")

    # ── Precompute daily indicators for all tickers ─────────────────────
    log(f"\n  Precomputing D1 indicators...")
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
        log(f"    {ticker}: {len(daily)} D1 bars, ADX mean={daily['ADX'][daily['ADX']>0].mean():.1f}")

    config = make_config_a()

    # ══════════════════════════════════════════════════════════════════════
    # PART 1: FULL-PERIOD BASELINE + FILTER COMPARISON
    # ══════════════════════════════════════════════════════════════════════

    log(f"\n{'━' * 90}")
    log(f"  PART 1: FULL-PERIOD TRADE COUNT & FILTER IMPACT")
    log(f"{'━' * 90}")

    log(f"\n  Running Config A on full period ({FULL_START} → {FULL_END})...")
    full_trades = extract_trades(config, TICKERS, FULL_START, FULL_END, daily_indicators)
    baseline_m = compute_metrics(full_trades)
    log(f"  Baseline (no filters):  {fmt(baseline_m)}")

    # ── TRADE COUNT CONCERN: Threshold relaxation sweep ────────────────
    log(f"\n  ── TRADE COUNT CONCERN: Threshold Relaxation Sweep ──")
    log(f"  {'ADX':>5} {'ATR_r':>6}  {'Trades':>6}  {'Blkd':>5}  {'WR':>6}  {'PF':>7}  "
        f"{'P&L':>10}  {'MaxDD':>8}  {'Sharpe':>7}")
    log(f"  {'-' * 80}")

    # No filter
    log(f"  {'none':>5} {'none':>6}  {fmt(baseline_m)}")

    sweep_results = []
    for adx_t in [25, 27, 30, 35, 40, None]:
        for atr_t in [1.2, 1.3, 1.5, 1.7, 2.0, None]:
            filtered = apply_filters(full_trades, adx_max=adx_t, atr_ratio_max=atr_t)
            m = compute_metrics(filtered)
            blocked = baseline_m['trades'] - m['trades']

            adx_s = str(adx_t) if adx_t else 'none'
            atr_s = str(atr_t) if atr_t else 'none'
            pf_s = f"{m['pf']:.2f}" if m['pf'] != float('inf') else "inf"

            sweep_results.append({
                'adx': adx_t, 'atr_ratio': atr_t,
                'trades': m['trades'], 'blocked': blocked,
                'wr': m['wr'], 'pf': m['pf'], 'pnl': m['pnl'],
                'max_dd': m['max_dd'], 'sharpe': m['sharpe'],
            })

            log(f"  {adx_s:>5} {atr_s:>6}  {m['trades']:>6}  {blocked:>5}  "
                f"{m['wr']*100:>5.1f}%  {pf_s:>6}  ${m['pnl']:>9.0f}  "
                f"${m['max_dd']:>7.0f}  {m['sharpe']:>7.2f}")

    # ── Specific requested comparisons ─────────────────────────────────
    log(f"\n  ── Requested Comparisons (full period) ──")

    # a) ADX<=30 vs ADX<=27
    for label, adx_t, atr_t in [
        ("ADX<=27 + ATR<=1.3 (tight)", 27, 1.3),
        ("ADX<=30 + ATR<=1.3 (relax ADX)", 30, 1.3),
        ("ADX<=27 + ATR<=1.5 (relax ATR)", 27, 1.5),
        ("ADX<=30 + ATR<=1.5 (relax both)", 30, 1.5),
        ("ADX<=30 only", 30, None),
        ("ATR<=1.5 only", None, 1.5),
    ]:
        filtered = apply_filters(full_trades, adx_max=adx_t, atr_ratio_max=atr_t)
        m = compute_metrics(filtered)
        log(f"    {label:>35}: {fmt(m)}")

    # ══════════════════════════════════════════════════════════════════════
    # PART 2: FULL 6-WINDOW WALK-FORWARD
    # ══════════════════════════════════════════════════════════════════════

    log(f"\n{'━' * 90}")
    log(f"  PART 2: 6-WINDOW WALK-FORWARD (Fixed Config A)")
    log(f"{'━' * 90}")

    filter_configs = [
        ("No filters (baseline)", None, None),
        ("ADX<=27 + ATR<=1.3 (tight)", 27, 1.3),
        ("ADX<=30 + ATR<=1.5 (relaxed)", 30, 1.5),
        ("ADX<=30 + ATR<=1.3", 30, 1.3),
        ("ADX<=27 + ATR<=1.5", 27, 1.5),
    ]

    all_wf_results = {}  # label -> list of window results

    for fc_label, fc_adx, fc_atr in filter_configs:
        log(f"\n  ── {fc_label} ──")
        log(f"  {'Win':>4} {'Test Period':>26} {'Trades':>7} {'WR':>7} {'PF':>7} "
            f"{'P&L':>10} {'MaxDD':>8} {'Sharpe':>7}")
        log(f"  {'-' * 80}")

        window_results = []
        for w in WF_WINDOWS:
            trades = extract_trades(config, TICKERS,
                                     w['test_start'], w['test_end'],
                                     daily_indicators)
            filtered = apply_filters(trades, adx_max=fc_adx, atr_ratio_max=fc_atr)
            m = compute_metrics(filtered)
            m['window'] = w['id']
            m['test_start'] = w['test_start']
            m['test_end'] = w['test_end']
            window_results.append(m)

            pf_s = f"{m['pf']:.2f}" if m['pf'] != float('inf') else "inf"
            log(f"  W{w['id']:>2}  {w['test_start']}→{w['test_end']}  "
                f"{m['trades']:>6}  {m['wr']*100:>5.1f}%  {pf_s:>6}  "
                f"${m['pnl']:>9.0f}  ${m['max_dd']:>7.0f}  {m['sharpe']:>7.2f}")

        all_wf_results[fc_label] = window_results

        # Aggregate
        total_trades = sum(w['trades'] for w in window_results)
        total_pnl = sum(w['pnl'] for w in window_results)
        total_gp = sum(w['gross_profit'] for w in window_results)
        total_gl = sum(w['gross_loss'] for w in window_results)
        agg_pf = total_gp / total_gl if total_gl > 0 else (float('inf') if total_gp > 0 else 0)
        positive = sum(1 for w in window_results if w['pnl'] > 0)
        profitable = sum(1 for w in window_results if w['pf'] > 1.0)

        # Aggregate Sharpe from all window trades
        all_window_sharpes = [w['sharpe'] for w in window_results if w['trades'] > 0]
        mean_sharpe = np.mean(all_window_sharpes) if all_window_sharpes else 0

        # Max drawdown across windows (cumulative P&L)
        cum_pnl = np.cumsum([w['pnl'] for w in window_results])
        peak = np.maximum.accumulate(cum_pnl)
        total_dd = np.max(peak - cum_pnl) if len(cum_pnl) > 0 else 0

        pf_s = f"{agg_pf:.2f}" if agg_pf != float('inf') else "inf"
        log(f"  {'─' * 80}")
        log(f"  TOTAL: {total_trades}t, PF={pf_s}, P&L=${total_pnl:.0f}, "
            f"DD=${total_dd:.0f}, Sharpe_mean={mean_sharpe:.2f}, "
            f"Positive={positive}/{len(WF_WINDOWS)}, PF>1={profitable}/{len(WF_WINDOWS)}")

    # ══════════════════════════════════════════════════════════════════════
    # PART 3: COMPARISON TABLE
    # ══════════════════════════════════════════════════════════════════════

    log(f"\n{'━' * 90}")
    log(f"  PART 3: COMPARISON vs PRIOR RESULTS")
    log(f"{'━' * 90}")

    # Phase 2.3 adaptive WF results
    log(f"\n  {'Approach':>40} {'OOS Trades':>10} {'OOS PF':>8} {'OOS P&L':>10} "
        f"{'Positive':>9} {'Mean Sh':>8}")
    log(f"  {'─' * 90}")

    log(f"  {'Phase 2.3 Adaptive WF (from JSON)':>40} "
        f"{'150':>10} {'0.89':>8} {'$-6,251':>10} {'3/6':>9} {'-2.23':>8}")

    for fc_label in all_wf_results:
        wr = all_wf_results[fc_label]
        tt = sum(w['trades'] for w in wr)
        tp = sum(w['pnl'] for w in wr)
        tgp = sum(w['gross_profit'] for w in wr)
        tgl = sum(w['gross_loss'] for w in wr)
        apf = tgp / tgl if tgl > 0 else 0
        pos = sum(1 for w in wr if w['pnl'] > 0)
        ms = np.mean([w['sharpe'] for w in wr if w['trades'] > 0])

        pf_s = f"{apf:.2f}" if apf != float('inf') else "inf"
        log(f"  {fc_label:>40} "
            f"{tt:>10} {pf_s:>8} ${tp:>9,.0f} "
            f"{pos}/{len(WF_WINDOWS):>7} {ms:>8.2f}")

    # ══════════════════════════════════════════════════════════════════════
    # PART 4: PER-TICKER BREAKDOWN (full period, best filter)
    # ══════════════════════════════════════════════════════════════════════

    log(f"\n{'━' * 90}")
    log(f"  PART 4: PER-TICKER BREAKDOWN (Full Period)")
    log(f"{'━' * 90}")

    for label, adx_t, atr_t in [("No filter", None, None),
                                  ("ADX<=30 + ATR<=1.5", 30, 1.5)]:
        log(f"\n  ── {label} ──")
        log(f"  {'Ticker':>8} {'Trades':>7} {'WR':>7} {'PF':>7} {'P&L':>10}")
        log(f"  {'-' * 45}")
        for ticker in TICKERS:
            ticker_trades = full_trades[full_trades['ticker'] == ticker]
            filtered = apply_filters(ticker_trades, adx_max=adx_t, atr_ratio_max=atr_t)
            m = compute_metrics(filtered)
            pf_s = f"{m['pf']:.2f}" if m['pf'] != float('inf') else "inf"
            log(f"  {ticker:>8} {m['trades']:>7} {m['wr']*100:>6.1f}% {pf_s:>6} "
                f"${m['pnl']:>9.0f}")

    # ══════════════════════════════════════════════════════════════════════
    # PART 5: ADX/ATR DISTRIBUTION OF ALL TRADES (for statistical insight)
    # ══════════════════════════════════════════════════════════════════════

    log(f"\n{'━' * 90}")
    log(f"  PART 5: INDICATOR VALUE DISTRIBUTIONS (Full Period, {len(full_trades)} trades)")
    log(f"{'━' * 90}")

    valid_adx = full_trades.dropna(subset=['ADX'])
    valid_adx = valid_adx[valid_adx['ADX'] > 0]
    valid_atr = full_trades.dropna(subset=['ATR_ratio'])

    if not valid_adx.empty:
        log(f"\n  ADX at entry — all {len(valid_adx)} trades:")
        for pct in [5, 10, 25, 50, 75, 90, 95]:
            log(f"    P{pct:>2}: {valid_adx['ADX'].quantile(pct/100):.1f}")
        log(f"    Mean: {valid_adx['ADX'].mean():.1f}")
        w = valid_adx[valid_adx['is_winner']]
        l = valid_adx[~valid_adx['is_winner']]
        log(f"    Winner ADX: mean={w['ADX'].mean():.1f}, median={w['ADX'].median():.1f} (n={len(w)})")
        log(f"    Loser ADX:  mean={l['ADX'].mean():.1f}, median={l['ADX'].median():.1f} (n={len(l)})")

    if not valid_atr.empty:
        log(f"\n  ATR(5)/ATR(20) ratio at entry — all {len(valid_atr)} trades:")
        for pct in [5, 10, 25, 50, 75, 90, 95]:
            log(f"    P{pct:>2}: {valid_atr['ATR_ratio'].quantile(pct/100):.2f}")
        log(f"    Mean: {valid_atr['ATR_ratio'].mean():.2f}")
        w = valid_atr[valid_atr['is_winner']]
        l = valid_atr[~valid_atr['is_winner']]
        log(f"    Winner ratio: mean={w['ATR_ratio'].mean():.2f}, median={w['ATR_ratio'].median():.2f} (n={len(w)})")
        log(f"    Loser ratio:  mean={l['ATR_ratio'].mean():.2f}, median={l['ATR_ratio'].median():.2f} (n={len(l)})")

    # ══════════════════════════════════════════════════════════════════════
    # DONE
    # ══════════════════════════════════════════════════════════════════════

    elapsed = time.time() - t0
    log(f"\n{'=' * 90}")
    log(f"  PHASE 2.4b COMPLETE — {elapsed:.0f}s ({elapsed/60:.1f}min)")
    log(f"{'=' * 90}")

    # Save
    report_path = os.path.join(RESULTS_DIR, 'phase24b_walkforward.txt')
    with open(report_path, 'w') as f:
        f.write('\n'.join(LOG))
    log(f"  Report saved: {report_path}")


if __name__ == '__main__':
    main()
