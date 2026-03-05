"""
Main Backtester Orchestrator for the False Breakout Strategy.

Wires together: data loading → D1 level detection → M5 signal scanning →
filter chain → risk management → trade execution → results collection.
"""

import pandas as pd
import numpy as np
from typing import Optional
from dataclasses import dataclass, field

from backtester.data_types import (
    Level, LevelType, LevelStatus, Signal, SignalDirection,
)
from backtester.core.level_detector import LevelDetector, LevelDetectorConfig
from backtester.core.pattern_engine import PatternEngine, PatternEngineConfig
from backtester.core.filter_chain import FilterChain, FilterChainConfig, SignalFunnelEntry
from backtester.core.risk_manager import RiskManager, RiskManagerConfig
from backtester.core.trade_manager import TradeManager, TradeManagerConfig, Trade, ExitReason
from backtester.core.intraday_levels import IntradayLevelDetector, IntradayLevelConfig
from backtester.earnings import EarningsCalendar

# Backwards-compatible alias
TradeDirection = SignalDirection


@dataclass
class BacktestConfig:
    """Master configuration for the entire backtest."""
    # Sub-configs
    level_config: LevelDetectorConfig = field(default_factory=LevelDetectorConfig)
    pattern_config: PatternEngineConfig = field(default_factory=PatternEngineConfig)
    filter_config: FilterChainConfig = field(default_factory=FilterChainConfig)
    risk_config: RiskManagerConfig = field(default_factory=RiskManagerConfig)
    trade_config: TradeManagerConfig = field(default_factory=TradeManagerConfig)
    intraday_config: Optional[IntradayLevelConfig] = None

    # Tiered target configuration
    tier_config: Optional[dict] = None  # None = original D1-only targeting

    # Direction filter: None = both, "long" = long only, "short" = short only
    # Can also be a dict mapping ticker -> direction, e.g. {"TSLA": "long", "DEFAULT": "short"}
    direction_filter: object = None

    # Earnings calendar: pre-loaded EarningsCalendar instance, or None to skip
    earnings_calendar: Optional[EarningsCalendar] = None

    # Data split
    in_sample_end: str = '2025-10-01'  # 70% IS
    out_of_sample_start: str = '2025-10-01'  # 30% OOS

    # Run mode
    name: str = "baseline_v1"


@dataclass
class BacktestResult:
    """Aggregated results from a backtest run."""
    config_name: str
    ticker: str
    trades: list
    funnel_entries: list
    level_stats: dict
    performance: dict
    equity_curve: list
    daily_pnl: dict


class Backtester:
    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()
        self.level_detector = LevelDetector(self.config.level_config)
        self.pattern_engine = PatternEngine(self.config.pattern_config)
        self.filter_chain = FilterChain(self.config.filter_config)
        self.risk_manager = RiskManager(self.config.risk_config)
        self.trade_manager = TradeManager(self.config.trade_config, self.risk_manager,
                                                tier_config=self.config.tier_config)

        # Intraday level detector (for tiered targets)
        self.intraday_detector = None
        if self.config.intraday_config:
            self.intraday_detector = IntradayLevelDetector(self.config.intraday_config)

        self.m5_df: Optional[pd.DataFrame] = None
        self.daily_df: Optional[pd.DataFrame] = None
        self.levels: list[Level] = []

        # Tracking
        self.proximity_events = 0
        self.patterns_found = 0
        self.signals_blocked: dict[str, int] = {}
        self.intraday_targets_found = 0
        self.intraday_targets_used = 0

    def load_data(self, csv_path: str) -> pd.DataFrame:
        """Load M5 OHLCV data from CSV."""
        df = pd.read_csv(csv_path)
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        df = df.sort_values(['Ticker', 'Datetime']).reset_index(drop=True)
        return df

    @staticmethod
    def filter_rth(m5_df: pd.DataFrame,
                   rth_start_hour: int = 16, rth_start_min: int = 30,
                   rth_end_hour: int = 23, rth_end_min: int = 0) -> pd.DataFrame:
        """Filter M5 data to regular trading hours (IST: 16:30-23:00 = 9:30-4:00 ET)."""
        minutes = m5_df['Datetime'].dt.hour * 60 + m5_df['Datetime'].dt.minute
        start_min = rth_start_hour * 60 + rth_start_min
        end_min = rth_end_hour * 60 + rth_end_min
        mask = (minutes >= start_min) & (minutes < end_min)
        return m5_df[mask].reset_index(drop=True)

    def prepare_data(self, m5_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[Level]]:
        """Run the full data preparation pipeline.

        Uses data_loader for session tagging and D1 aggregation (no duplicate logic).
        """
        from backtester.data_loader import tag_dataframe, aggregate_d1

        self.m5_df = self.filter_rth(m5_df)
        tagged = tag_dataframe(self.m5_df)
        raw_daily = aggregate_d1(tagged)
        # Rename trading_day → Date for level detector compatibility
        if 'trading_day' in raw_daily.columns and 'Date' not in raw_daily.columns:
            raw_daily = raw_daily.rename(columns={'trading_day': 'Date'})
        raw_daily['Date'] = pd.to_datetime(raw_daily['Date'])
        self.levels, self.daily_df = self.level_detector.detect_levels(raw_daily)
        return self.m5_df, self.daily_df, self.levels

    def _get_opposing_levels(self, signal: Signal, active_levels: list[Level]) -> list[Level]:
        """Get levels that could serve as targets (opposing direction)."""
        opposing = []
        for lvl in active_levels:
            if lvl.ticker != signal.ticker:
                continue
            if signal.direction == TradeDirection.SHORT:
                # Target below: support levels or mirror levels below entry
                if lvl.price < signal.entry_price and lvl.level_type in (
                        LevelType.SUPPORT, LevelType.MIRROR):
                    opposing.append(lvl)
            else:
                # Target above: resistance levels or mirror levels above entry
                if lvl.price > signal.entry_price and lvl.level_type in (
                        LevelType.RESISTANCE, LevelType.MIRROR):
                    opposing.append(lvl)
        return opposing

    def run(self, m5_df: pd.DataFrame, start_date: str = None,
            end_date: str = None) -> BacktestResult:
        """Execute the backtest over the given data range."""
        m5_df, daily_df, levels = self.prepare_data(m5_df)

        # Filter date range
        if start_date:
            m5_df = m5_df[m5_df['Datetime'] >= pd.Timestamp(start_date)]
        if end_date:
            m5_df = m5_df[m5_df['Datetime'] < pd.Timestamp(end_date)]
        # Reset index so positional indices match label indices —
        # needed by filter_chain._calc_atr_ratio which uses .loc[:trigger_bar_idx]
        m5_df = m5_df.reset_index(drop=True)

        if m5_df.empty:
            return self._empty_result()

        # Inject earnings dates into filter chain if calendar is provided
        if self.config.earnings_calendar is not None:
            tickers_in_data = list(m5_df['Ticker'].unique())
            self.config.earnings_calendar.load(tickers_in_data)
            self.filter_chain.config.earnings_dates = (
                self.config.earnings_calendar.as_filter_config()
            )

        ticker = m5_df['Ticker'].iloc[0]
        tol_func = self.config.level_config.get_tolerance

        # Precompute M5 ATR for each ticker
        m5_atr_cache = {}
        for tkr in m5_df['Ticker'].unique():
            m5_atr_cache[tkr] = self.pattern_engine.calculate_m5_atr(m5_df, tkr)

        # Pre-index daily data for fast lookups
        daily_index = self.level_detector.build_daily_index(daily_df)

        # Reset filter chain funnel
        self.filter_chain.reset_funnel()
        self.proximity_events = 0
        self.patterns_found = 0
        self.signals_blocked = {}

        # Equity tracking
        equity = self.config.risk_config.capital
        equity_curve = [(m5_df['Datetime'].iloc[0], equity)]
        daily_pnl = {}

        prev_date = None
        # Cache: recompute active levels only when day changes
        cached_active_levels = {}  # ticker -> list[Level]
        cached_date = None

        # Convert m5_df to numpy arrays for fast access
        m5_datetimes = pd.to_datetime(m5_df['Datetime']).values
        m5_highs = m5_df['High'].values
        m5_lows = m5_df['Low'].values
        m5_closes = m5_df['Close'].values
        m5_tickers = m5_df['Ticker'].values

        # Track last bar per ticker for EOD flatten on day change
        last_bar_by_ticker = {}  # ticker -> (close_price, bar_time)

        # Process each M5 bar
        for bar_idx in range(len(m5_df)):
            bar = m5_df.iloc[bar_idx]
            bar_time = pd.Timestamp(m5_datetimes[bar_idx])
            bar_date = bar_time.normalize()
            bar_ticker = m5_tickers[bar_idx]

            # Force-flatten open trades on day change if their last bar
            # didn't reach EOD (22:55 IST). This prevents overnight holding
            # when data is truncated (bars end before market close).
            if prev_date is not None and bar_date != prev_date:
                for trade in list(self.trade_manager.open_trades):
                    trade_ticker = trade.signal.ticker if trade.signal else None
                    if trade_ticker and trade_ticker in last_bar_by_ticker:
                        lclose, ltime = last_bar_by_ticker[trade_ticker]
                    else:
                        # Fallback: use previous bar
                        lclose = m5_closes[bar_idx - 1] if bar_idx > 0 else bar['Close']
                        ltime = pd.Timestamp(m5_datetimes[bar_idx - 1]) if bar_idx > 0 else bar_time
                    self.trade_manager._close_trade(
                        trade, lclose, ltime, ExitReason.EOD_EXIT
                    )
                    equity += trade.pnl
                    equity_curve.append((ltime, equity))
                    date_str = prev_date.strftime('%Y-%m-%d')
                    daily_pnl[date_str] = daily_pnl.get(date_str, 0.0) + trade.pnl

                self.risk_manager.cb_state.reset_daily(bar_date)
                cached_active_levels = {}
                cached_date = None
                last_bar_by_ticker = {}
            prev_date = bar_date

            # Track last bar for each ticker (for EOD flatten)
            last_bar_by_ticker[bar_ticker] = (m5_closes[bar_idx], bar_time)

            # Update existing open trades
            closed_trades = self.trade_manager.update_trades(bar, bar_time)
            for trade in closed_trades:
                equity += trade.pnl
                equity_curve.append((bar_time, equity))
                date_str = bar_date.strftime('%Y-%m-%d')
                daily_pnl[date_str] = daily_pnl.get(date_str, 0.0) + trade.pnl

            # Skip if already in position for this ticker
            if self.risk_manager.cb_state.has_open_position(bar_ticker):
                continue

            # Get active levels (cached per day per ticker)
            if bar_ticker not in cached_active_levels or cached_date != bar_date:
                active_levels = self.level_detector.get_active_levels(
                    bar_ticker, bar_date, daily_df, daily_index
                )
                # Check anti-sawing once per day
                active_levels = [
                    lvl for lvl in active_levels
                    if not self.level_detector.check_anti_sawing(lvl, daily_df, bar_date, daily_index)
                ]
                cached_active_levels[bar_ticker] = active_levels
                cached_date = bar_date

            active_levels = cached_active_levels.get(bar_ticker, [])

            if not active_levels:
                continue

            # Check proximity to any level using pre-extracted values
            bar_high = m5_highs[bar_idx]
            bar_low = m5_lows[bar_idx]
            for level in active_levels:
                tol = tol_func(level.price)
                if bar_low - tol <= level.price <= bar_high + tol:
                    self.proximity_events += 1
                    break  # count once per bar

            # Scan for patterns
            atr_m5 = m5_atr_cache.get(bar_ticker, pd.Series())
            signals = self.pattern_engine.scan_bar(
                m5_df, bar_idx, active_levels, atr_m5, tol_func
            )

            if not signals:
                continue

            self.patterns_found += len(signals)

            # Take best signal (highest priority)
            signals.sort(key=lambda s: s.priority, reverse=True)
            signal = signals[0]

            # Direction filter (str or dict)
            if self.config.direction_filter:
                df = self.config.direction_filter
                if isinstance(df, dict):
                    allowed = df.get(bar_ticker, df.get('DEFAULT', None))
                else:
                    allowed = df
                if allowed:
                    if (allowed == 'long' and
                            signal.direction != TradeDirection.LONG):
                        self.signals_blocked['direction_filter'] = \
                            self.signals_blocked.get('direction_filter', 0) + 1
                        continue
                    if (allowed == 'short' and
                            signal.direction != TradeDirection.SHORT):
                        self.signals_blocked['direction_filter'] = \
                            self.signals_blocked.get('direction_filter', 0) + 1
                        continue

            # Check position limits
            can_trade, reason = self.risk_manager.check_position_limits(
                signal, bar_date
            )
            if not can_trade:
                self.signals_blocked['position_limit'] = \
                    self.signals_blocked.get('position_limit', 0) + 1
                continue

            # Apply filter chain
            passed, funnel_entry = self.filter_chain.apply_filters(
                signal, m5_df, daily_df
            )

            if not passed:
                self.signals_blocked[funnel_entry.blocked_by] = \
                    self.signals_blocked.get(funnel_entry.blocked_by, 0) + 1
                continue

            # Calculate risk parameters
            atr_m5_val = atr_m5.iloc[bar_idx] if bar_idx < len(atr_m5) else 0.5
            if pd.isna(atr_m5_val) or atr_m5_val <= 0:
                atr_m5_val = 0.5

            opposing = self._get_opposing_levels(signal, active_levels)

            # Calculate risk parameters with tiered targets if configured
            risk_params = None
            intraday_targets = []

            if self.intraday_detector and self.config.tier_config:
                # Find the M5 bar index within the ticker's data
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
                    self.intraday_targets_found += 1

                d1_target = self.risk_manager.calculate_target(
                    signal, opposing, signal.level.atr_d1
                )
                stop_price = self.risk_manager.calculate_stop(
                    signal, m5_df, atr_m5_val, signal.level.atr_d1
                )
                stop_dist = abs(signal.entry_price - stop_price)

                direction_str = "short" if signal.direction == TradeDirection.SHORT else "long"
                intraday_targets = self.intraday_detector.get_intraday_targets(
                    intraday_levels, signal.entry_price, direction_str,
                    stop_dist, d1_target
                )

                if intraday_targets:
                    self.intraday_targets_used += 1

            if self.config.tier_config:
                # Tiered path: use intraday targets if available, D1-only otherwise
                risk_params = self.risk_manager.calculate_risk_params_tiered(
                    signal, m5_df, atr_m5_val, signal.level.atr_d1,
                    opposing, intraday_targets, self.config.tier_config
                )
            else:
                # Original D1-only targeting (no tiers)
                risk_params = self.risk_manager.calculate_risk_params(
                    signal, m5_df, atr_m5_val, signal.level.atr_d1, opposing
                )

            if risk_params is None:
                self.signals_blocked['risk_rr'] = \
                    self.signals_blocked.get('risk_rr', 0) + 1
                continue

            # Queue for next-bar-open execution (L-005.1 §7)
            self.trade_manager.queue_entry(signal, risk_params)

        # Force close any remaining open trades at last bar
        if self.trade_manager.open_trades:
            last_bar = m5_df.iloc[-1]
            last_time = pd.Timestamp(last_bar['Datetime'])
            for trade in list(self.trade_manager.open_trades):
                self.trade_manager._close_trade(
                    trade, last_bar['Close'], last_time, ExitReason.EOD_EXIT
                )
                equity += trade.pnl

        # Compile level stats
        level_stats = self._compile_level_stats()

        # Compile performance
        performance = self.trade_manager.get_trade_stats()
        performance['equity_final'] = equity
        performance['equity_start'] = self.config.risk_config.capital
        performance['net_return_pct'] = (
            (equity - self.config.risk_config.capital) /
            self.config.risk_config.capital * 100
        )

        # Compute drawdown
        if equity_curve:
            eq_values = [e[1] for e in equity_curve]
            peak = eq_values[0]
            max_dd = 0
            for v in eq_values:
                peak = max(peak, v)
                dd = (peak - v) / peak
                max_dd = max(max_dd, dd)
            performance['max_drawdown_pct'] = max_dd * 100
        else:
            performance['max_drawdown_pct'] = 0.0

        # Compute Sharpe ratio (annualized from daily returns)
        if daily_pnl:
            daily_returns = list(daily_pnl.values())
            if len(daily_returns) > 1 and np.std(daily_returns) > 0:
                performance['sharpe'] = (
                    np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252)
                )
            else:
                performance['sharpe'] = 0.0
        else:
            performance['sharpe'] = 0.0

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

    def _compile_level_stats(self) -> dict:
        """Compile level detection statistics."""
        total = len(self.levels)
        confirmed = sum(1 for l in self.levels if l.touches >= 1)
        mirrors = sum(1 for l in self.levels if l.is_mirror)
        invalidated = sum(1 for l in self.levels if l.status == LevelStatus.INVALIDATED)

        return {
            'total_levels': total,
            'confirmed_bpu': confirmed,
            'mirrors': mirrors,
            'invalidated_sawing': invalidated,
            'avg_score': np.mean([l.score for l in self.levels]) if self.levels else 0,
            'avg_touches': np.mean([l.touches for l in self.levels]) if self.levels else 0,
        }

    def _empty_result(self) -> BacktestResult:
        return BacktestResult(
            config_name=self.config.name,
            ticker="",
            trades=[],
            funnel_entries=[],
            level_stats={},
            performance={'total_trades': 0},
            equity_curve=[],
            daily_pnl={},
        )
