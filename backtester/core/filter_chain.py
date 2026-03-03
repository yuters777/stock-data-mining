"""
Filter Chain for the False Breakout Strategy Backtester.

Applies sequential filters to signals: ATR ratio, volume (VSA),
time of day, earnings, squeeze detection. Each filter either passes
or blocks a signal, with the reason logged for the signal funnel.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional

from backtester.core.pattern_engine import Signal, TradeDirection


class FilterResult:
    __slots__ = ('passed', 'reason')

    def __init__(self, passed: bool, reason: str = ""):
        self.passed = passed
        self.reason = reason


@dataclass
class SignalFunnelEntry:
    """Tracks where a signal was blocked or passed."""
    signal: Signal
    atr_ratio: float = 0.0
    filters_passed: list = None
    blocked_by: str = ""
    blocked_reason: str = ""

    def __post_init__(self):
        if self.filters_passed is None:
            self.filters_passed = []


# ATR thresholds
ATR_BLOCK_THRESHOLD = 0.30
ATR_DEFAULT_ENTRY_THRESHOLD = 0.75

# Volume thresholds
VOL_CLIMAX_MULT = 2.0
VOL_LOW_MULT = 0.7
VOL_AVG_PERIOD = 20


class FilterChainConfig:
    def __init__(self, **kwargs):
        self.atr_block_threshold = kwargs.get('atr_block_threshold', ATR_BLOCK_THRESHOLD)
        self.atr_entry_threshold = kwargs.get('atr_entry_threshold', ATR_DEFAULT_ENTRY_THRESHOLD)
        self.vol_climax_mult = kwargs.get('vol_climax_mult', VOL_CLIMAX_MULT)
        self.vol_low_mult = kwargs.get('vol_low_mult', VOL_LOW_MULT)
        self.vol_avg_period = kwargs.get('vol_avg_period', VOL_AVG_PERIOD)
        self.open_delay_minutes = kwargs.get('open_delay_minutes', 5)  # 09:35 ET = 14:35 UTC
        self.market_open_hour = kwargs.get('market_open_hour', 14)   # 9:30 ET = 14:30 UTC
        self.market_open_minute = kwargs.get('market_open_minute', 30)
        self.market_close_hour = kwargs.get('market_close_hour', 21)  # 4:00 PM ET = 21:00 UTC
        self.earnings_dates: dict[str, set] = kwargs.get('earnings_dates', {})
        self.enable_volume_filter = kwargs.get('enable_volume_filter', True)
        self.enable_time_filter = kwargs.get('enable_time_filter', True)
        self.enable_squeeze_filter = kwargs.get('enable_squeeze_filter', True)
        self.squeeze_bb_period = kwargs.get('squeeze_bb_period', 20)
        self.squeeze_bb_mult = kwargs.get('squeeze_bb_mult', 2.0)
        self.squeeze_kc_mult = kwargs.get('squeeze_kc_mult', 1.5)


class FilterChain:
    def __init__(self, config: Optional[FilterChainConfig] = None):
        self.config = config or FilterChainConfig()
        self.funnel: list[SignalFunnelEntry] = []

    def reset_funnel(self):
        self.funnel = []

    def _check_atr_filter(self, signal: Signal, m5_bars: pd.DataFrame,
                          daily_df: pd.DataFrame) -> FilterResult:
        """Check ATR ratio filter. This IS the strategy — never skip."""
        bar = m5_bars.iloc[signal.trigger_bar_idx]
        bar_date = pd.Timestamp(bar['Datetime']).normalize()

        # Get D1 ATR for this day
        day_row = daily_df[
            (daily_df['Ticker'] == signal.ticker) &
            (daily_df['Date'] == bar_date)
        ]
        if day_row.empty:
            # Try previous day
            day_row = daily_df[
                (daily_df['Ticker'] == signal.ticker) &
                (daily_df['Date'] < bar_date)
            ].tail(1)

        if day_row.empty:
            return FilterResult(False, "No D1 ATR available")

        atr_d1 = day_row.iloc[0].get('ModifiedATR', day_row.iloc[0].get('ATR', 0))
        if pd.isna(atr_d1) or atr_d1 <= 0:
            return FilterResult(False, "D1 ATR is zero or NaN")

        # Distance traveled: from day's extreme to level in trade direction
        # Get all M5 bars for this day up to the signal bar
        day_bars = m5_bars[
            (m5_bars['Ticker'] == signal.ticker) &
            (pd.to_datetime(m5_bars['Datetime']).dt.normalize() == bar_date)
        ]
        day_bars_to_signal = day_bars.loc[:signal.trigger_bar_idx]

        if signal.direction == TradeDirection.SHORT:
            # For short at resistance: price traveled UP from day low to level
            # Higher ratio = more energy spent = better false breakout setup
            day_low = day_bars_to_signal['Low'].min()
            distance = signal.level.price - day_low
        else:
            # For long at support: price traveled DOWN from day high to level
            day_high = day_bars_to_signal['High'].max()
            distance = day_high - signal.level.price

        distance = max(distance, 0)
        atr_ratio = distance / atr_d1

        # Hard block
        if atr_ratio < self.config.atr_block_threshold:
            assert atr_ratio < self.config.atr_block_threshold, \
                f"ATR {atr_ratio:.3f} should be below block zone {self.config.atr_block_threshold}"
            return FilterResult(False, f"ATR ratio {atr_ratio:.3f} < {self.config.atr_block_threshold} (HARD BLOCK)")

        # Entry threshold
        if atr_ratio < self.config.atr_entry_threshold:
            return FilterResult(False, f"ATR ratio {atr_ratio:.3f} < {self.config.atr_entry_threshold} (below entry threshold)")

        return FilterResult(True, f"ATR ratio {atr_ratio:.3f} OK")

    def _check_volume_filter(self, signal: Signal, m5_bars: pd.DataFrame) -> FilterResult:
        """VSA-based volume filter."""
        if not self.config.enable_volume_filter:
            return FilterResult(True, "Volume filter disabled")

        bar_idx = signal.trigger_bar_idx
        bar = m5_bars.iloc[bar_idx]

        # Calculate average volume over lookback
        lookback = self.config.vol_avg_period
        start_idx = max(0, bar_idx - lookback)
        recent_bars = m5_bars.iloc[start_idx:bar_idx]
        ticker_bars = recent_bars[recent_bars['Ticker'] == signal.ticker]

        if len(ticker_bars) < 5:
            return FilterResult(True, "Insufficient volume history")

        avg_vol = ticker_bars['Volume'].mean()
        if avg_vol <= 0:
            return FilterResult(True, "Zero average volume")

        vol_ratio = bar['Volume'] / avg_vol
        level_price = signal.level.price

        # V > 2x AND Close > Level → true breakout → BLOCK
        if signal.direction == TradeDirection.SHORT:
            if vol_ratio >= self.config.vol_climax_mult and bar['Close'] > level_price:
                return FilterResult(False, f"True breakout (V={vol_ratio:.1f}x, Close above level)")

        if signal.direction == TradeDirection.LONG:
            if vol_ratio >= self.config.vol_climax_mult and bar['Close'] < level_price:
                return FilterResult(False, f"True breakout (V={vol_ratio:.1f}x, Close below level)")

        return FilterResult(True, f"Volume OK (ratio={vol_ratio:.1f}x)")

    def _check_time_filter(self, signal: Signal) -> FilterResult:
        """Time-of-day filter: no signals before 09:35 ET."""
        if not self.config.enable_time_filter:
            return FilterResult(True, "Time filter disabled")

        ts = pd.Timestamp(signal.timestamp)
        open_h = self.config.market_open_hour
        open_m = self.config.market_open_minute
        delay = self.config.open_delay_minutes

        earliest_minute = open_m + delay
        earliest_hour = open_h
        if earliest_minute >= 60:
            earliest_hour += 1
            earliest_minute -= 60

        bar_minutes = ts.hour * 60 + ts.minute
        earliest_minutes = earliest_hour * 60 + earliest_minute

        if bar_minutes < earliest_minutes:
            return FilterResult(False, f"Before open delay ({ts.strftime('%H:%M')} < {earliest_hour}:{earliest_minute:02d})")

        # After market close
        close_minutes = self.config.market_close_hour * 60
        if bar_minutes >= close_minutes:
            return FilterResult(False, f"After market close ({ts.strftime('%H:%M')})")

        return FilterResult(True, f"Time OK ({ts.strftime('%H:%M')})")

    def _check_earnings_filter(self, signal: Signal) -> FilterResult:
        """Block trading on earnings days."""
        ts = pd.Timestamp(signal.timestamp)
        trade_date = ts.normalize()
        ticker = signal.ticker

        earnings = self.config.earnings_dates.get(ticker, set())
        if trade_date in earnings or ts.date() in earnings:
            return FilterResult(False, f"Earnings day for {ticker}")

        return FilterResult(True, "No earnings conflict")

    def _check_squeeze_filter(self, signal: Signal, m5_bars: pd.DataFrame) -> FilterResult:
        """Bollinger Band squeeze detection — tight range may lead to breakout."""
        if not self.config.enable_squeeze_filter:
            return FilterResult(True, "Squeeze filter disabled")

        bar_idx = signal.trigger_bar_idx
        period = self.config.squeeze_bb_period

        if bar_idx < period:
            return FilterResult(True, "Insufficient data for squeeze")

        ticker_bars = m5_bars.iloc[max(0, bar_idx - period * 2):bar_idx + 1]
        ticker_bars = ticker_bars[ticker_bars['Ticker'] == signal.ticker]

        if len(ticker_bars) < period:
            return FilterResult(True, "Insufficient ticker bars for squeeze")

        closes = ticker_bars['Close'].values[-period:]
        bb_std = np.std(closes, ddof=1)
        bb_mean = np.mean(closes)

        if bb_mean <= 0:
            return FilterResult(True, "Zero mean price")

        # BB width as % of price
        bb_width = (2 * self.config.squeeze_bb_mult * bb_std) / bb_mean

        # If BB is very tight, price might break out — risky for FB strategy
        if bb_width < 0.005:  # < 0.5% width
            return FilterResult(False, f"Squeeze detected (BB width={bb_width:.4f})")

        return FilterResult(True, f"No squeeze (BB width={bb_width:.4f})")

    def apply_filters(self, signal: Signal, m5_bars: pd.DataFrame,
                      daily_df: pd.DataFrame) -> tuple[bool, SignalFunnelEntry]:
        """Apply all filters to a signal. Returns (passed, funnel_entry)."""
        entry = SignalFunnelEntry(signal=signal)

        filters = [
            ('time', lambda: self._check_time_filter(signal)),
            ('earnings', lambda: self._check_earnings_filter(signal)),
            ('atr', lambda: self._check_atr_filter(signal, m5_bars, daily_df)),
            ('volume', lambda: self._check_volume_filter(signal, m5_bars)),
            ('squeeze', lambda: self._check_squeeze_filter(signal, m5_bars)),
        ]

        for name, check_fn in filters:
            result = check_fn()
            if not result.passed:
                entry.blocked_by = name
                entry.blocked_reason = result.reason
                self.funnel.append(entry)
                return False, entry
            entry.filters_passed.append(name)

        self.funnel.append(entry)
        return True, entry

    def get_time_bucket(self, timestamp: pd.Timestamp) -> str:
        """Classify signal time into Open/Midday/Close bucket."""
        minutes = timestamp.hour * 60 + timestamp.minute
        if minutes < 10 * 60 + 30:  # < 10:30
            return "Open"
        elif minutes < 14 * 60:  # < 14:00
            return "Midday"
        else:
            return "Close"

    def get_funnel_summary(self) -> dict:
        """Summarize the signal funnel counts."""
        summary = {
            'total_signals': len(self.funnel),
            'passed': sum(1 for e in self.funnel if not e.blocked_by),
            'blocked_by_time': sum(1 for e in self.funnel if e.blocked_by == 'time'),
            'blocked_by_earnings': sum(1 for e in self.funnel if e.blocked_by == 'earnings'),
            'blocked_by_atr_hard': sum(1 for e in self.funnel if e.blocked_by == 'atr' and 'HARD BLOCK' in e.blocked_reason),
            'blocked_by_atr_threshold': sum(1 for e in self.funnel if e.blocked_by == 'atr' and 'below entry' in e.blocked_reason),
            'blocked_by_volume': sum(1 for e in self.funnel if e.blocked_by == 'volume'),
            'blocked_by_squeeze': sum(1 for e in self.funnel if e.blocked_by == 'squeeze'),
        }
        return summary
