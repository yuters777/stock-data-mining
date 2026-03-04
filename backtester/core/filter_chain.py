"""
Filter Chain for the False Breakout Strategy Backtester.

Applies 8 sequential filters to signals. Each filter either passes or blocks.
BLOCK propagation: first block stops the chain (early exit).

Filter order (L-005.1 §6):
  1. Direction   — signal matches ticker's allowed direction
  2. Position    — no duplicate position for ticker, circuit breaker checks
  3. Level Score — level score >= min_level_score
  4. Time        — within trading hours (IST-based)
  5. Earnings    — not on earnings day
  6. ATR         — ATR exhaustion ratio check (THE STRATEGY)
  7. Volume      — VSA: block true breakouts (high volume beyond level)
  8. Squeeze     — Bollinger Band width check; squeeze overrides ATR pass

Reference: L-005.1 §6, data is IST timezone-naive.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional

from backtester.data_types import (
    Level, LevelType, Signal, SignalDirection, PatternType,
)


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


# Volume thresholds
VOL_CLIMAX_MULT = 2.0
VOL_LOW_MULT = 0.7
VOL_AVG_PERIOD = 20


class FilterChainConfig:
    def __init__(self, **kwargs):
        # ATR thresholds (from config, no hardcoded defaults that conflict)
        self.atr_block_threshold = kwargs.get('atr_block_threshold', 0.30)
        self.atr_entry_threshold = kwargs.get('atr_entry_threshold', 0.80)

        # Volume
        self.vol_climax_mult = kwargs.get('vol_climax_mult', VOL_CLIMAX_MULT)
        self.vol_low_mult = kwargs.get('vol_low_mult', VOL_LOW_MULT)
        self.vol_avg_period = kwargs.get('vol_avg_period', VOL_AVG_PERIOD)

        # Time filter — IST hours (data is IST timezone-naive)
        self.open_delay_minutes = kwargs.get('open_delay_minutes', 5)
        self.market_open_hour_ist = kwargs.get('market_open_hour_ist', 16)
        self.market_open_minute = kwargs.get('market_open_minute', 30)
        self.market_close_hour_ist = kwargs.get('market_close_hour_ist', 23)

        # Earnings
        self.earnings_dates: dict[str, set] = kwargs.get('earnings_dates', {})

        # Feature toggles
        self.enable_volume_filter = kwargs.get('enable_volume_filter', True)
        self.enable_time_filter = kwargs.get('enable_time_filter', True)
        self.enable_squeeze_filter = kwargs.get('enable_squeeze_filter', True)

        # Squeeze
        self.squeeze_bb_period = kwargs.get('squeeze_bb_period', 20)
        self.squeeze_bb_mult = kwargs.get('squeeze_bb_mult', 2.0)
        self.squeeze_bb_width_threshold = kwargs.get('squeeze_bb_width_threshold', 0.005)

        # Direction filter: dict mapping ticker -> "long"/"short", or None
        self.direction_filter = kwargs.get('direction_filter', None)

        # Level score minimum
        self.min_level_score = kwargs.get('min_level_score', 5)

        # Position limits (callback-based, set by orchestrator)
        self.position_check_fn = kwargs.get('position_check_fn', None)


class FilterChain:
    def __init__(self, config: Optional[FilterChainConfig] = None):
        self.config = config or FilterChainConfig()
        self.funnel: list[SignalFunnelEntry] = []

    def reset_funnel(self):
        self.funnel = []

    def _check_direction_filter(self, signal: Signal) -> FilterResult:
        """Stage 1: Check if signal direction matches ticker's allowed direction."""
        df = self.config.direction_filter
        if df is None:
            return FilterResult(True, "No direction filter configured")

        if isinstance(df, dict):
            allowed = df.get(signal.ticker, df.get('DEFAULT', None))
        else:
            allowed = df

        if allowed is None:
            return FilterResult(True, "No direction restriction for ticker")

        if allowed == 'excluded':
            return FilterResult(False, f"Direction filter: {signal.ticker} is EXCLUDED")
        if allowed == 'long' and signal.direction != SignalDirection.LONG:
            return FilterResult(False, f"Direction filter: {signal.ticker} allows long only")
        if allowed == 'short' and signal.direction != SignalDirection.SHORT:
            return FilterResult(False, f"Direction filter: {signal.ticker} allows short only")

        return FilterResult(True, f"Direction OK ({signal.direction.value})")

    def _check_position_limit(self, signal: Signal) -> FilterResult:
        """Stage 2: Check position limits (no duplicate, circuit breakers)."""
        check_fn = self.config.position_check_fn
        if check_fn is None:
            return FilterResult(True, "No position check configured")

        can_trade, reason = check_fn(signal)
        if not can_trade:
            return FilterResult(False, f"Position limit: {reason}")

        return FilterResult(True, "Position OK")

    def _check_level_score(self, signal: Signal) -> FilterResult:
        """Stage 3: Check level score meets minimum threshold."""
        min_score = self.config.min_level_score
        level_score = signal.level.score

        if level_score < min_score:
            return FilterResult(False,
                                f"Level score {level_score} < {min_score}")

        return FilterResult(True, f"Level score {level_score} OK")

    def _check_time_filter(self, signal: Signal) -> FilterResult:
        """Stage 4: Time-of-day filter in IST.

        Market open: 16:30 IST (9:30 ET).
        Earliest signal: 16:35 IST (with 5-min delay).
        Market close: 23:00 IST (4:00 PM ET).
        """
        if not self.config.enable_time_filter:
            return FilterResult(True, "Time filter disabled")

        ts = pd.Timestamp(signal.timestamp)
        open_h = self.config.market_open_hour_ist
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
            return FilterResult(
                False,
                f"Before open delay ({ts.strftime('%H:%M')} IST < "
                f"{earliest_hour}:{earliest_minute:02d} IST)")

        close_minutes = self.config.market_close_hour_ist * 60
        if bar_minutes >= close_minutes:
            return FilterResult(
                False, f"After market close ({ts.strftime('%H:%M')} IST)")

        return FilterResult(True, f"Time OK ({ts.strftime('%H:%M')} IST)")

    def _check_earnings_filter(self, signal: Signal) -> FilterResult:
        """Stage 5: Block trading on earnings days."""
        ts = pd.Timestamp(signal.timestamp)
        trade_date = ts.normalize()
        ticker = signal.ticker

        earnings = self.config.earnings_dates.get(ticker, set())
        if trade_date in earnings or ts.date() in earnings:
            return FilterResult(False, f"Earnings day for {ticker}")

        return FilterResult(True, "No earnings conflict")

    def _calc_atr_ratio(self, signal: Signal, m5_bars: pd.DataFrame,
                        daily_df: pd.DataFrame) -> tuple[float, str]:
        """Calculate ATR exhaustion ratio for a signal.

        Returns (atr_ratio, error_msg). error_msg is empty if OK.
        """
        bar = m5_bars.iloc[signal.trigger_bar_idx]
        bar_date = pd.Timestamp(bar['Datetime']).normalize()

        day_row = daily_df[
            (daily_df['Ticker'] == signal.ticker) &
            (daily_df['Date'] == bar_date)
        ]
        if day_row.empty:
            day_row = daily_df[
                (daily_df['Ticker'] == signal.ticker) &
                (daily_df['Date'] < bar_date)
            ].tail(1)

        if day_row.empty:
            return 0.0, "No D1 ATR available"

        atr_d1 = day_row.iloc[0].get('ModifiedATR', day_row.iloc[0].get('ATR', 0))
        if pd.isna(atr_d1) or atr_d1 <= 0:
            return 0.0, "D1 ATR is zero or NaN"

        day_bars = m5_bars[
            (m5_bars['Ticker'] == signal.ticker) &
            (pd.to_datetime(m5_bars['Datetime']).dt.normalize() == bar_date)
        ]
        day_bars_to_signal = day_bars.loc[:signal.trigger_bar_idx]

        if signal.direction == SignalDirection.SHORT:
            day_low = day_bars_to_signal['Low'].min()
            distance = signal.level.price - day_low
        else:
            day_high = day_bars_to_signal['High'].max()
            distance = day_high - signal.level.price

        distance = max(distance, 0)
        return distance / atr_d1, ""

    def _check_atr_filter(self, signal: Signal, m5_bars: pd.DataFrame,
                          daily_df: pd.DataFrame,
                          funnel_entry: SignalFunnelEntry) -> FilterResult:
        """Stage 6: ATR exhaustion ratio filter — this IS the strategy.

        Hard block if ratio < atr_block_threshold (0.30).
        Reject if ratio < atr_entry_threshold (0.80).
        """
        atr_ratio, error = self._calc_atr_ratio(signal, m5_bars, daily_df)
        funnel_entry.atr_ratio = atr_ratio

        if error:
            return FilterResult(False, error)

        if atr_ratio < self.config.atr_block_threshold:
            return FilterResult(
                False,
                f"ATR ratio {atr_ratio:.3f} < {self.config.atr_block_threshold} (HARD BLOCK)")

        if atr_ratio < self.config.atr_entry_threshold:
            return FilterResult(
                False,
                f"ATR ratio {atr_ratio:.3f} < {self.config.atr_entry_threshold} "
                f"(below entry threshold)")

        return FilterResult(True, f"ATR ratio {atr_ratio:.3f} OK")

    def _check_volume_filter(self, signal: Signal, m5_bars: pd.DataFrame) -> FilterResult:
        """Stage 7: VSA-based volume filter."""
        if not self.config.enable_volume_filter:
            return FilterResult(True, "Volume filter disabled")

        bar_idx = signal.trigger_bar_idx
        bar = m5_bars.iloc[bar_idx]

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

        if signal.direction == SignalDirection.SHORT:
            if vol_ratio >= self.config.vol_climax_mult and bar['Close'] > level_price:
                return FilterResult(
                    False, f"True breakout (V={vol_ratio:.1f}x, Close above level)")

        if signal.direction == SignalDirection.LONG:
            if vol_ratio >= self.config.vol_climax_mult and bar['Close'] < level_price:
                return FilterResult(
                    False, f"True breakout (V={vol_ratio:.1f}x, Close below level)")

        return FilterResult(True, f"Volume OK (ratio={vol_ratio:.1f}x)")

    def _check_squeeze_filter(self, signal: Signal, m5_bars: pd.DataFrame,
                              atr_passed: bool) -> FilterResult:
        """Stage 8: Bollinger Band squeeze detection.

        If BB width < threshold → BLOCK (squeeze about to break out).
        Squeeze overrides ATR: if squeeze is detected, block even if ATR passed.
        """
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

        bb_width = (2 * self.config.squeeze_bb_mult * bb_std) / bb_mean

        if bb_width < self.config.squeeze_bb_width_threshold:
            return FilterResult(
                False,
                f"Squeeze detected (BB width={bb_width:.4f})"
                f"{' — overrides ATR pass' if atr_passed else ''}")

        return FilterResult(True, f"No squeeze (BB width={bb_width:.4f})")

    def apply_filters(self, signal: Signal, m5_bars: pd.DataFrame,
                      daily_df: pd.DataFrame) -> tuple[bool, SignalFunnelEntry]:
        """Apply all 8 filters to a signal. Returns (passed, funnel_entry).

        BLOCK propagation: first failure stops the chain.
        """
        entry = SignalFunnelEntry(signal=signal)
        atr_passed = False

        filters = [
            ('direction', lambda: self._check_direction_filter(signal)),
            ('position', lambda: self._check_position_limit(signal)),
            ('level_score', lambda: self._check_level_score(signal)),
            ('time', lambda: self._check_time_filter(signal)),
            ('earnings', lambda: self._check_earnings_filter(signal)),
            ('atr', lambda: self._check_atr_filter(signal, m5_bars, daily_df, entry)),
            ('volume', lambda: self._check_volume_filter(signal, m5_bars)),
            ('squeeze', lambda: self._check_squeeze_filter(signal, m5_bars, atr_passed)),
        ]

        for name, check_fn in filters:
            result = check_fn()
            if not result.passed:
                entry.blocked_by = name
                entry.blocked_reason = result.reason
                self.funnel.append(entry)
                return False, entry
            entry.filters_passed.append(name)
            if name == 'atr':
                atr_passed = True

        self.funnel.append(entry)
        return True, entry

    def get_time_bucket(self, timestamp: pd.Timestamp) -> str:
        """Classify signal time into Open/Midday/Close bucket (IST)."""
        minutes = timestamp.hour * 60 + timestamp.minute
        # IST: open ~16:30, midday ~18:30, close ~21:00+
        if minutes < 18 * 60 + 30:
            return "Open"
        elif minutes < 21 * 60:
            return "Midday"
        else:
            return "Close"

    def get_funnel_summary(self) -> dict:
        """Summarize the signal funnel counts."""
        summary = {
            'total_signals': len(self.funnel),
            'passed': sum(1 for e in self.funnel if not e.blocked_by),
            'blocked_by_direction': sum(1 for e in self.funnel if e.blocked_by == 'direction'),
            'blocked_by_position': sum(1 for e in self.funnel if e.blocked_by == 'position'),
            'blocked_by_level_score': sum(1 for e in self.funnel if e.blocked_by == 'level_score'),
            'blocked_by_time': sum(1 for e in self.funnel if e.blocked_by == 'time'),
            'blocked_by_earnings': sum(1 for e in self.funnel if e.blocked_by == 'earnings'),
            'blocked_by_atr_hard': sum(1 for e in self.funnel
                                       if e.blocked_by == 'atr' and 'HARD BLOCK' in e.blocked_reason),
            'blocked_by_atr_threshold': sum(1 for e in self.funnel
                                            if e.blocked_by == 'atr' and 'below entry' in e.blocked_reason),
            'blocked_by_volume': sum(1 for e in self.funnel if e.blocked_by == 'volume'),
            'blocked_by_squeeze': sum(1 for e in self.funnel if e.blocked_by == 'squeeze'),
        }
        return summary
