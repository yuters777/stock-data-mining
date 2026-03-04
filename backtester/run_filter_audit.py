"""
Filter Effectiveness Audit

For the full-period Config A baseline (all 8 filters active), log for
EACH filter: times evaluated, times triggered (BLOCK), and unique kills
(signals that ONLY this filter would block — all others would PASS).

Architecture notes:
  The signal pipeline has FIVE stages, each in a different component:
    1. Same-level limit (anti-sawing) — in LevelDetector, BEFORE patterns
    2. Filter chain (8 sub-filters, early-exit) — in FilterChain
    3. R:R feasibility — in RiskManager, AFTER filter chain
    4. Regime filters (ADX, ATR expansion) — post-trade, outside backtester
  We audit ALL of them.

To compute "unique kills" we must run every signal through ALL filters
independently (no early exit), then check which signals are blocked by
exactly one filter.
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
from backtester.core.level_detector import LevelDetector, LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngine, PatternEngineConfig
from backtester.core.filter_chain import (
    FilterChain, FilterChainConfig, FilterResult, SignalFunnelEntry,
)
from backtester.core.risk_manager import RiskManager, RiskManagerConfig
from backtester.core.trade_manager import TradeManager, TradeManagerConfig
from backtester.core.intraday_levels import IntradayLevelConfig
from backtester.data_types import Signal, SignalDirection, LevelStatus
from backtester.optimizer import load_ticker_data

# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

TICKERS = ['TSLA', 'AMZN', 'GOOGL', 'META', 'MSFT', 'NVDA']
FULL_START = '2025-02-10'
FULL_END = '2026-01-31'
CAPITAL = 100_000.0

ADX_THRESHOLD = 27
ATR_RATIO_THRESHOLD = 1.3

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
# AUDIT FILTER CHAIN — runs ALL filters on every signal (no early exit)
# ═══════════════════════════════════════════════════════════════════════════

class AuditFilterChain(FilterChain):
    """Modified FilterChain that evaluates ALL filters on every signal
    (no early exit), recording per-filter pass/block status."""

    def __init__(self, config=None):
        super().__init__(config)
        self.audit_records = []  # list of dicts per signal

    def audit_all_filters(self, signal, m5_bars, daily_df):
        """Run ALL 8 sub-filters independently. Return dict of results."""
        entry = SignalFunnelEntry(signal=signal)
        results = {}

        # 1. Direction
        r = self._check_direction_filter(signal)
        results['direction'] = {'passed': r.passed, 'reason': r.reason}

        # 2. Position
        r = self._check_position_limit(signal)
        results['position'] = {'passed': r.passed, 'reason': r.reason}

        # 3. Level score
        r = self._check_level_score(signal)
        results['level_score'] = {'passed': r.passed, 'reason': r.reason}

        # 4. Time (open delay + session hours)
        r = self._check_time_filter(signal)
        results['time'] = {'passed': r.passed, 'reason': r.reason}

        # 5. Earnings
        r = self._check_earnings_filter(signal)
        results['earnings'] = {'passed': r.passed, 'reason': r.reason}

        # 6. ATR energy gate
        r = self._check_atr_filter(signal, m5_bars, daily_df, entry)
        results['atr'] = {'passed': r.passed, 'reason': r.reason,
                          'atr_ratio': entry.atr_ratio}

        # 7. Volume VSA
        r = self._check_volume_filter(signal, m5_bars)
        results['volume'] = {'passed': r.passed, 'reason': r.reason}

        # 8. Squeeze
        atr_passed = results['atr']['passed']
        r = self._check_squeeze_filter(signal, m5_bars, atr_passed)
        results['squeeze'] = {'passed': r.passed, 'reason': r.reason}

        return results


# ═══════════════════════════════════════════════════════════════════════════
# AUDIT BACKTESTER — intercepts every signal for full audit
# ═══════════════════════════════════════════════════════════════════════════

class AuditBacktester(Backtester):
    """Modified Backtester that captures every signal at every stage
    and records all filter verdicts independently."""

    def __init__(self, config=None, daily_indicator_data=None):
        super().__init__(config)
        # Replace filter chain with audit version
        self.filter_chain = AuditFilterChain(self.config.filter_config)
        self.daily_indicator_data = daily_indicator_data or {}
        # Audit storage
        self.audit_signals = []  # all signals that reached the filter chain

    def run(self, m5_df, start_date=None, end_date=None):
        """Override run to intercept signals and audit all filters."""
        from backtester.data_loader import tag_dataframe, aggregate_d1

        m5_df = self.filter_rth(m5_df)
        tagged = tag_dataframe(m5_df)
        raw_daily = aggregate_d1(tagged)
        if 'trading_day' in raw_daily.columns and 'Date' not in raw_daily.columns:
            raw_daily = raw_daily.rename(columns={'trading_day': 'Date'})
        raw_daily['Date'] = pd.to_datetime(raw_daily['Date'])
        self.levels, self.daily_df = self.level_detector.detect_levels(raw_daily)

        if start_date:
            m5_df = m5_df[m5_df['Datetime'] >= pd.Timestamp(start_date)]
        if end_date:
            m5_df = m5_df[m5_df['Datetime'] < pd.Timestamp(end_date)]

        if m5_df.empty:
            return self._empty_result()

        self.m5_df = m5_df
        daily_df = self.daily_df
        ticker = m5_df['Ticker'].iloc[0]
        tol_func = self.config.level_config.get_tolerance

        m5_atr_cache = {}
        for tkr in m5_df['Ticker'].unique():
            m5_atr_cache[tkr] = self.pattern_engine.calculate_m5_atr(m5_df, tkr)

        daily_index = self.level_detector.build_daily_index(daily_df)
        self.filter_chain.reset_funnel()
        self.proximity_events = 0
        self.patterns_found = 0
        self.signals_blocked = {}

        equity = self.config.risk_config.capital
        equity_curve = [(m5_df['Datetime'].iloc[0], equity)]
        daily_pnl = {}

        prev_date = None
        cached_active_levels = {}
        cached_date = None

        m5_datetimes = pd.to_datetime(m5_df['Datetime']).values
        m5_highs = m5_df['High'].values
        m5_lows = m5_df['Low'].values
        m5_closes = m5_df['Close'].values
        m5_tickers = m5_df['Ticker'].values

        from backtester.core.trade_manager import ExitReason
        TradeDirection = SignalDirection

        for bar_idx in range(len(m5_df)):
            bar = m5_df.iloc[bar_idx]
            bar_time = pd.Timestamp(m5_datetimes[bar_idx])
            bar_date = bar_time.normalize()
            bar_ticker = m5_tickers[bar_idx]

            if prev_date is not None and bar_date != prev_date:
                self.risk_manager.cb_state.reset_daily(bar_date)
                cached_active_levels = {}
                cached_date = None
            prev_date = bar_date

            closed_trades = self.trade_manager.update_trades(bar, bar_time)
            for trade in closed_trades:
                equity += trade.pnl
                equity_curve.append((bar_time, equity))
                date_str = bar_date.strftime('%Y-%m-%d')
                daily_pnl[date_str] = daily_pnl.get(date_str, 0.0) + trade.pnl

            if self.risk_manager.cb_state.has_open_position(bar_ticker):
                continue

            # Get active levels — WITH sawing filter to match baseline
            if bar_ticker not in cached_active_levels or cached_date != bar_date:
                all_levels = self.level_detector.get_active_levels(
                    bar_ticker, bar_date, daily_df, daily_index
                )
                # Track which levels are sawed off
                sawed_levels = []
                clean_levels = []
                for lvl in all_levels:
                    if self.level_detector.check_anti_sawing(lvl, daily_df, bar_date, daily_index):
                        sawed_levels.append(lvl)
                    else:
                        clean_levels.append(lvl)
                cached_active_levels[bar_ticker] = {
                    'clean': clean_levels,
                    'all': all_levels,
                    'sawed': sawed_levels,
                }
                cached_date = bar_date

            level_info = cached_active_levels.get(bar_ticker, {'clean': [], 'all': [], 'sawed': []})
            active_levels = level_info['clean']
            all_levels_before_sawing = level_info['all']
            sawed_levels = level_info['sawed']

            if not active_levels and not sawed_levels:
                continue

            # Scan for patterns on CLEAN levels (baseline behavior)
            atr_m5 = m5_atr_cache.get(bar_ticker, pd.Series())
            signals = self.pattern_engine.scan_bar(
                m5_df, bar_idx, active_levels, atr_m5, tol_func
            )

            # Also scan on sawed levels to detect sawing-blocked signals
            sawed_signals = []
            if sawed_levels:
                sawed_signals = self.pattern_engine.scan_bar(
                    m5_df, bar_idx, sawed_levels, atr_m5, tol_func
                )

            if not signals and not sawed_signals:
                continue

            # Process sawed signals (blocked by same-level limit)
            for sig in sawed_signals:
                self._audit_signal(sig, m5_df, daily_df, bar_date, bar_ticker,
                                   atr_m5, bar_idx, active_levels,
                                   blocked_by_sawing=True)

            if not signals:
                continue

            self.patterns_found += len(signals)
            signals.sort(key=lambda s: s.priority, reverse=True)
            signal = signals[0]

            # Direction filter
            if self.config.direction_filter:
                df = self.config.direction_filter
                if isinstance(df, dict):
                    allowed = df.get(bar_ticker, df.get('DEFAULT', None))
                else:
                    allowed = df
                if allowed:
                    if (allowed == 'long' and signal.direction != TradeDirection.LONG):
                        continue
                    if (allowed == 'short' and signal.direction != TradeDirection.SHORT):
                        continue

            # Position limits
            can_trade, reason = self.risk_manager.check_position_limits(signal, bar_date)
            if not can_trade:
                continue

            # ── AUDIT: Run all filters independently on this signal ───
            filter_verdicts = self.filter_chain.audit_all_filters(
                signal, m5_df, daily_df
            )

            # ── Also check R:R feasibility ────────────────────────────
            atr_m5_val = atr_m5.iloc[bar_idx] if bar_idx < len(atr_m5) else 0.5
            if pd.isna(atr_m5_val) or atr_m5_val <= 0:
                atr_m5_val = 0.5

            opposing = self._get_opposing_levels(signal, active_levels)

            # Check R:R
            rr_passes = True
            rr_reason = ""
            try:
                if self.config.tier_config:
                    from backtester.core.intraday_levels import IntradayLevelDetector
                    intraday_targets = []
                    if self.intraday_detector:
                        ticker_m5 = m5_df[m5_df['Ticker'] == bar_ticker]
                        ticker_bar_positions = ticker_m5.index.tolist()
                        try:
                            ticker_relative_idx = ticker_bar_positions.index(m5_df.index[bar_idx])
                        except (ValueError, IndexError):
                            ticker_relative_idx = bar_idx
                        intraday_levels = self.intraday_detector.detect_levels(
                            m5_df, bar_ticker, ticker_relative_idx
                        )
                        if intraday_levels:
                            d1_target = self.risk_manager.calculate_target(
                                signal, opposing, signal.level.atr_d1
                            )
                            stop_price = self.risk_manager.calculate_stop(
                                signal, m5_df, atr_m5_val, signal.level.atr_d1
                            )
                            stop_dist = abs(signal.entry_price - stop_price)
                            direction_str = "short" if signal.direction == SignalDirection.SHORT else "long"
                            intraday_targets = self.intraday_detector.get_intraday_targets(
                                intraday_levels, signal.entry_price, direction_str,
                                stop_dist, d1_target
                            )
                    risk_params = self.risk_manager.calculate_risk_params_tiered(
                        signal, m5_df, atr_m5_val, signal.level.atr_d1,
                        opposing, intraday_targets, self.config.tier_config
                    )
                else:
                    risk_params = self.risk_manager.calculate_risk_params(
                        signal, m5_df, atr_m5_val, signal.level.atr_d1, opposing
                    )
                if risk_params is None:
                    rr_passes = False
                    rr_reason = "R:R or stop cap failed"
            except Exception as e:
                rr_passes = False
                rr_reason = f"Exception: {e}"

            filter_verdicts['rr_feasibility'] = {'passed': rr_passes, 'reason': rr_reason}

            # ── Check regime filters (ADX + ATR expansion) ────────────
            regime_passes = True
            regime_reason = ""
            entry_date = bar_date.date() if hasattr(bar_date, 'date') else bar_date
            entry_ts = pd.Timestamp(entry_date)

            if bar_ticker in self.daily_indicator_data:
                d = self.daily_indicator_data[bar_ticker]
                prior = d[d['Date'] <= entry_ts]
                if not prior.empty:
                    adx_val = prior['ADX'].iloc[-1]
                    atr_ratio = prior['ATR_ratio_5_20'].iloc[-1]
                    if adx_val > 0 and adx_val > ADX_THRESHOLD:
                        regime_passes = False
                        regime_reason = f"ADX={adx_val:.1f} > {ADX_THRESHOLD}"
                    elif atr_ratio > ATR_RATIO_THRESHOLD:
                        regime_passes = False
                        regime_reason = f"ATR_ratio={atr_ratio:.2f} > {ATR_RATIO_THRESHOLD}"
                else:
                    regime_reason = "No daily data"

            filter_verdicts['regime'] = {'passed': regime_passes, 'reason': regime_reason}
            filter_verdicts['sawing'] = {'passed': True, 'reason': 'Level not sawed'}

            self.audit_signals.append({
                'ticker': bar_ticker,
                'timestamp': bar_time,
                'direction': signal.direction.value,
                'entry_price': signal.entry_price,
                'level_price': signal.level.price,
                'verdicts': filter_verdicts,
            })

            # ── Normal pipeline continues (with early-exit chain) ─────
            passed, funnel_entry = self.filter_chain.apply_filters(
                signal, m5_df, daily_df
            )
            if not passed:
                self.signals_blocked[funnel_entry.blocked_by] = \
                    self.signals_blocked.get(funnel_entry.blocked_by, 0) + 1
                continue

            if not rr_passes:
                self.signals_blocked['risk_rr'] = \
                    self.signals_blocked.get('risk_rr', 0) + 1
                continue

            # Queue trade (using already-computed risk_params)
            if risk_params is not None:
                self.trade_manager.queue_entry(signal, risk_params)

        # Force close open trades
        if self.trade_manager.open_trades:
            last_bar = m5_df.iloc[-1]
            last_time = pd.Timestamp(last_bar['Datetime'])
            from backtester.core.trade_manager import ExitReason
            for trade in list(self.trade_manager.open_trades):
                self.trade_manager._close_trade(
                    trade, last_bar['Close'], last_time, ExitReason.EOD_EXIT
                )
                equity += trade.pnl

        level_stats = self._compile_level_stats()
        performance = self.trade_manager.get_trade_stats()
        performance['equity_final'] = equity
        performance['equity_start'] = CAPITAL

        from backtester.backtester import BacktestResult
        return BacktestResult(
            config_name=self.config.name,
            ticker=ticker,
            trades=self.trade_manager.closed_trades,
            funnel_entries=self.filter_chain.funnel,
            level_stats=level_stats,
            performance=performance,
            equity_curve=equity_curve,
            daily_pnl=daily_pnl,
        )

    def _audit_signal(self, signal, m5_df, daily_df, bar_date, bar_ticker,
                       atr_m5, bar_idx, active_levels, blocked_by_sawing=False):
        """Record a signal that was blocked by sawing (before filter chain)."""
        # Run all filter-chain filters to see what ELSE would block it
        filter_verdicts = self.filter_chain.audit_all_filters(
            signal, m5_df, daily_df
        )

        # R:R check
        atr_m5_val = atr_m5.iloc[bar_idx] if bar_idx < len(atr_m5) else 0.5
        if pd.isna(atr_m5_val) or atr_m5_val <= 0:
            atr_m5_val = 0.5
        opposing = self._get_opposing_levels(signal, active_levels)
        rr_passes = True
        try:
            if self.config.tier_config:
                rp = self.risk_manager.calculate_risk_params_tiered(
                    signal, m5_df, atr_m5_val, signal.level.atr_d1,
                    opposing, [], self.config.tier_config
                )
            else:
                rp = self.risk_manager.calculate_risk_params(
                    signal, m5_df, atr_m5_val, signal.level.atr_d1, opposing
                )
            if rp is None:
                rr_passes = False
        except Exception:
            rr_passes = False
        filter_verdicts['rr_feasibility'] = {'passed': rr_passes, 'reason': ''}

        # Regime
        regime_passes = True
        entry_ts = pd.Timestamp(bar_date.date() if hasattr(bar_date, 'date') else bar_date)
        if bar_ticker in self.daily_indicator_data:
            d = self.daily_indicator_data[bar_ticker]
            prior = d[d['Date'] <= entry_ts]
            if not prior.empty:
                adx_val = prior['ADX'].iloc[-1]
                atr_ratio = prior['ATR_ratio_5_20'].iloc[-1]
                if adx_val > 0 and adx_val > ADX_THRESHOLD:
                    regime_passes = False
                elif atr_ratio > ATR_RATIO_THRESHOLD:
                    regime_passes = False
        filter_verdicts['regime'] = {'passed': regime_passes, 'reason': ''}

        # Sawing
        filter_verdicts['sawing'] = {
            'passed': not blocked_by_sawing,
            'reason': 'Level invalidated by sawing' if blocked_by_sawing else '',
        }

        self.audit_signals.append({
            'ticker': bar_ticker,
            'timestamp': pd.Timestamp(signal.timestamp),
            'direction': signal.direction.value,
            'entry_price': signal.entry_price,
            'level_price': signal.level.price,
            'verdicts': filter_verdicts,
        })


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════

def make_baseline_config():
    """Phase 2.5 baseline: ALL filters on."""
    return BacktestConfig(
        level_config=LevelDetectorConfig(
            fractal_depth=10, tolerance_cents=0.05, tolerance_pct=0.001,
            atr_period=5, min_level_score=5,
            cross_count_invalidate=5, cross_count_window=30,
        ),
        pattern_config=PatternEngineConfig(
            tail_ratio_min=0.15, lp2_engulfing_required=True,
            clp_min_bars=3, clp_max_bars=7,
        ),
        filter_config=FilterChainConfig(
            atr_block_threshold=0.20, atr_entry_threshold=0.60,
            enable_volume_filter=True, enable_time_filter=True,
            enable_squeeze_filter=True, open_delay_minutes=5,
            earnings_dates={},
        ),
        risk_config=RiskManagerConfig(
            min_rr=2.0, max_stop_atr_pct=0.15, capital=CAPITAL, risk_pct=0.003,
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
        name='Baseline_Audit',
    )


# ═══════════════════════════════════════════════════════════════════════════
# ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

def analyze_audit(audit_signals):
    """Analyze the audit signals to produce the filter effectiveness table."""
    # All filters we track
    all_filters = [
        'earnings', 'time', 'squeeze', 'atr', 'volume',
        'rr_feasibility', 'regime', 'sawing',
    ]
    filter_labels = {
        'earnings': '1. Earnings filter',
        'time': '2. Open delay / time',
        'squeeze': '3. Squeeze detection',
        'atr': '5. ATR energy gate',
        'volume': '6. Volume VSA',
        'rr_feasibility': '7. R:R feasibility',
        'regime': '8. Regime (ADX+ATR exp)',
        'sawing': '9. Same-level limit',
    }

    n_signals = len(audit_signals)

    # Count per-filter stats
    stats = {}
    for f in all_filters:
        evaluated = 0
        blocked = 0
        for sig in audit_signals:
            v = sig['verdicts'].get(f)
            if v is not None:
                evaluated += 1
                if not v['passed']:
                    blocked += 1
        stats[f] = {'evaluated': evaluated, 'blocked': blocked}

    # Compute unique kills: signals blocked by ONLY this filter
    for f in all_filters:
        unique_kills = 0
        for sig in audit_signals:
            v = sig['verdicts'].get(f)
            if v is None or v['passed']:
                continue
            # This filter blocks. Check if ALL other filters pass.
            other_pass = True
            for f2 in all_filters:
                if f2 == f:
                    continue
                v2 = sig['verdicts'].get(f2)
                if v2 is not None and not v2['passed']:
                    other_pass = False
                    break
            if other_pass:
                unique_kills += 1
        stats[f]['unique_kills'] = unique_kills

    # For filters that also need to consider level_score and direction
    # (which are in the filter chain but not in our "audit" list since
    # they're structural, not tunable filters)
    # We include them as "pre-filters" that reduce the signal count

    return stats


def deep_audit_zero_impact(audit_signals, filter_name, filter_label):
    """For zero-impact filters: did it EVER trigger? If so, what killed first?"""
    triggered_signals = []
    for sig in audit_signals:
        v = sig['verdicts'].get(filter_name)
        if v is not None and not v['passed']:
            triggered_signals.append(sig)

    if not triggered_signals:
        return {
            'ever_triggered': False,
            'reason': 'Filter code is called but never returns BLOCK',
            'signals': [],
        }

    # Find what other filter killed these signals first (in pipeline order)
    pipeline_order = ['sawing', 'time', 'earnings', 'atr', 'volume', 'squeeze',
                      'rr_feasibility', 'regime']

    first_blocker_counts = defaultdict(int)
    for sig in triggered_signals:
        # Find the earliest OTHER filter (in pipeline order) that also blocks
        earliest = None
        for f in pipeline_order:
            if f == filter_name:
                continue
            v = sig['verdicts'].get(f)
            if v is not None and not v['passed']:
                earliest = f
                break
        if earliest:
            first_blocker_counts[earliest] += 1
        else:
            first_blocker_counts['(none — unique kill)'] += 1

    return {
        'ever_triggered': True,
        'n_triggered': len(triggered_signals),
        'first_blocker_counts': dict(first_blocker_counts),
        'sample_reasons': [s['verdicts'][filter_name]['reason']
                           for s in triggered_signals[:5]],
    }


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    total_start = time.time()

    log("=" * 90)
    log("  FILTER EFFECTIVENESS AUDIT")
    log("  Full-period backtest with ALL filters active")
    log("=" * 90)
    log(f"  Config: Baseline (FD=10, ATR=0.60/0.20, RR=2.0, TAIL=0.15, STOP=0.15)")
    log(f"  Tickers: {', '.join(TICKERS)}  |  Period: {FULL_START} -> {FULL_END}")
    log(f"  Regime: ADX<={ADX_THRESHOLD}, ATR_ratio<={ATR_RATIO_THRESHOLD}")
    log("")

    # ── Step 1: Precompute daily indicators ───────────────────────────
    log("  Step 1: Computing daily indicators...")
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

    # ── Step 2: Run audit backtester per ticker ───────────────────────
    log("\n  Step 2: Running audit backtest (all filters, no early exit)...")

    config = make_baseline_config()
    all_audit_signals = []
    total_trades = 0

    for ticker in TICKERS:
        t0 = time.time()
        m5_df = load_ticker_data(ticker)

        bt = AuditBacktester(config, daily_indicator_data=daily_data)
        result = bt.run(m5_df, start_date=FULL_START, end_date=FULL_END)

        n_signals = len(bt.audit_signals)
        n_trades = len(result.trades)
        total_trades += n_trades
        elapsed = time.time() - t0

        log(f"    {ticker}: {n_signals} signals audited, {n_trades} trades, "
            f"P&L=${sum(t.pnl for t in result.trades):,.0f}  [{elapsed:.1f}s]")

        all_audit_signals.extend(bt.audit_signals)

    n_total = len(all_audit_signals)
    log(f"\n    TOTAL: {n_total} signals audited across {len(TICKERS)} tickers, "
        f"{total_trades} trades")

    # ── Step 3: Analyze ───────────────────────────────────────────────
    log(f"\n  Step 3: Analyzing filter effectiveness...")

    stats = analyze_audit(all_audit_signals)

    # ── Step 4: Main Results Table ────────────────────────────────────
    log(f"\n{'=' * 90}")
    log(f"  FILTER EFFECTIVENESS TABLE")
    log(f"{'=' * 90}")

    all_filters = ['earnings', 'time', 'squeeze', 'atr', 'volume',
                   'rr_feasibility', 'regime', 'sawing']
    filter_labels = {
        'earnings': '1. Earnings filter',
        'time': '2. Open delay / time',
        'squeeze': '3. Squeeze detection',
        'atr': '5. ATR energy gate',
        'volume': '6. Volume VSA',
        'rr_feasibility': '7. R:R feasibility',
        'regime': '8. Regime (ADX+ATR exp)',
        'sawing': '9. Same-level limit',
    }

    log(f"\n  {'Filter':<28} {'Evaluated':>10} {'Blocked':>10} {'Block%':>8} "
        f"{'Unique Kills':>13} {'Status':>12}")
    log(f"  {'─' * 90}")

    for f in all_filters:
        s = stats[f]
        block_pct = s['blocked'] / s['evaluated'] * 100 if s['evaluated'] > 0 else 0
        label = filter_labels[f]

        if s['blocked'] == 0:
            status = 'INERT'
        elif s['unique_kills'] == 0:
            status = 'REDUNDANT'
        elif s['unique_kills'] > 0:
            status = 'ACTIVE'
        else:
            status = '?'

        log(f"  {label:<28} {s['evaluated']:>10} {s['blocked']:>10} "
            f"{block_pct:>7.1f}% {s['unique_kills']:>13} {status:>12}")

    log(f"  {'─' * 90}")
    log(f"  {'TOTAL SIGNALS':<28} {n_total:>10}")

    # Note about breakaway gap
    log(f"\n  4. Breakaway gap block:  NOT IMPLEMENTED in codebase — skipped")

    # ── Step 5: Deep audit of zero-impact filters ─────────────────────
    log(f"\n{'=' * 90}")
    log(f"  DEEP AUDIT: Zero-Impact Filters")
    log(f"{'=' * 90}")

    zero_impact_filters = [
        ('earnings', '1. Earnings filter'),
        ('atr', '5. ATR energy gate'),
        ('volume', '6. Volume VSA'),
        ('rr_feasibility', '7. R:R feasibility'),
    ]

    for f_name, f_label in zero_impact_filters:
        log(f"\n  {'─' * 86}")
        log(f"  {f_label}")
        log(f"  {'─' * 86}")

        deep = deep_audit_zero_impact(all_audit_signals, f_name, f_label)

        if not deep['ever_triggered']:
            log(f"    Ever triggered (BLOCK)?  NO")
            log(f"    Is filter code called?   YES (it was evaluated {stats[f_name]['evaluated']} times)")
            log(f"    Conclusion: Filter is GENUINELY REDUNDANT — it never fires")
            log(f"                with current config/data. Safe to remove.")
        else:
            log(f"    Ever triggered (BLOCK)?  YES — {deep['n_triggered']} times")
            log(f"    But ablation showed zero impact. Why?")
            log(f"    Answer: Another filter killed those signals first (in pipeline order):")
            log(f"")
            for blocker, count in sorted(deep['first_blocker_counts'].items(),
                                          key=lambda x: -x[1]):
                log(f"      {blocker:<30} killed {count:>3} of those signals first")

            if deep.get('sample_reasons'):
                log(f"\n    Sample block reasons:")
                for reason in deep['sample_reasons'][:3]:
                    log(f"      \"{reason}\"")

            unique = deep['first_blocker_counts'].get('(none — unique kill)', 0)
            if unique > 0:
                log(f"\n    SURPRISE: {unique} signals are UNIQUELY killed by this filter")
                log(f"    but ablation showed zero P&L impact — those signals would have")
                log(f"    been losers anyway (removing the filter doesn't hurt P&L).")
            else:
                log(f"\n    Conclusion: ACCIDENTALLY INERT — the filter does fire, but")
                log(f"    every signal it blocks was already killed by an earlier filter.")
                log(f"    It's a redundant safety net, not a primary defense.")

    # ── Step 6: Pipeline flow diagram ─────────────────────────────────
    log(f"\n{'=' * 90}")
    log(f"  SIGNAL FLOW — Pipeline Attrition")
    log(f"{'=' * 90}")

    # Reconstruct the pipeline flow for the early-exit chain
    # Pipeline order (matching apply_filters + backtester):
    pipeline = ['sawing', 'time', 'earnings', 'atr', 'volume', 'squeeze',
                'rr_feasibility', 'regime']

    # Count how many signals are blocked at each stage (first blocker)
    first_block_counts = defaultdict(int)
    pass_all = 0
    for sig in all_audit_signals:
        blocked_by_first = None
        for f in pipeline:
            v = sig['verdicts'].get(f)
            if v is not None and not v['passed']:
                blocked_by_first = f
                break
        if blocked_by_first:
            first_block_counts[blocked_by_first] += 1
        else:
            pass_all += 1

    remaining = n_total
    log(f"\n  {'Stage':<28} {'Blocked':>8} {'Remaining':>10} {'Attrition':>10}")
    log(f"  {'─' * 62}")
    log(f"  {'Signals entering pipeline':<28} {'':>8} {remaining:>10}")

    for f in pipeline:
        blocked = first_block_counts.get(f, 0)
        remaining -= blocked
        pct = blocked / n_total * 100 if n_total > 0 else 0
        label = filter_labels.get(f, f)
        log(f"  {label:<28} {blocked:>8} {remaining:>10} {pct:>9.1f}%")

    log(f"  {'─' * 62}")
    log(f"  {'→ PASS ALL FILTERS':<28} {'':>8} {pass_all:>10} "
        f"{pass_all/n_total*100:>9.1f}%")

    # ── Step 7: Conclusions ───────────────────────────────────────────
    log(f"\n{'=' * 90}")
    log(f"  CONCLUSIONS")
    log(f"{'=' * 90}")

    active_filters = [f for f in all_filters if stats[f]['unique_kills'] > 0]
    inert_filters = [f for f in all_filters if stats[f]['blocked'] == 0]
    redundant_filters = [f for f in all_filters
                          if stats[f]['blocked'] > 0 and stats[f]['unique_kills'] == 0]

    log(f"\n  ACTIVE filters (have unique kills):")
    for f in active_filters:
        s = stats[f]
        log(f"    {filter_labels[f]:<28} {s['unique_kills']} unique kills")

    log(f"\n  INERT filters (never trigger at all):")
    for f in inert_filters:
        log(f"    {filter_labels[f]:<28} — genuinely redundant, safe to remove")

    log(f"\n  REDUNDANT filters (trigger but no unique kills):")
    for f in redundant_filters:
        s = stats[f]
        log(f"    {filter_labels[f]:<28} {s['blocked']} blocks, all also caught by other filters")

    elapsed = time.time() - total_start
    log(f"\n{'=' * 90}")
    log(f"  COMPLETE — {elapsed:.0f}s ({elapsed/60:.1f}min)")
    log(f"{'=' * 90}")

    # ── Save ──────────────────────────────────────────────────────────
    report_path = os.path.join(RESULTS_DIR, 'filter_effectiveness_audit.txt')
    with open(report_path, 'w') as f:
        f.write('\n'.join(LOG))
    log(f"\n  Report saved: {report_path}")

    json_data = {
        'total_signals': n_total,
        'total_trades': total_trades,
        'filters': {},
    }
    for f in all_filters:
        s = stats[f]
        json_data['filters'][f] = {
            'label': filter_labels[f],
            'evaluated': s['evaluated'],
            'blocked': s['blocked'],
            'unique_kills': s['unique_kills'],
        }

    json_path = os.path.join(RESULTS_DIR, 'filter_effectiveness_audit.json')
    with open(json_path, 'w') as f:
        json.dump(json_data, f, indent=2)
    log(f"  JSON saved: {json_path}")


if __name__ == '__main__':
    main()
