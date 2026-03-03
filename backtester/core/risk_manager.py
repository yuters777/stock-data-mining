"""
Risk Manager for the False Breakout Strategy Backtester.

Handles stop loss calculation (dynamic + hard cap), target placement,
position sizing, R:R validation, and circuit breakers.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional

from backtester.core.pattern_engine import Signal, TradeDirection


@dataclass
class TargetTier:
    """A single tier in the tiered target system."""
    price: float
    exit_pct: float  # fraction of position to exit at this tier (0.0-1.0)
    source: str  # "M5", "H1", "D1", "trail"
    r_multiple: float = 0.0  # R-multiple at this target


@dataclass
class RiskParams:
    """Calculated risk parameters for a trade."""
    stop_price: float
    target_price: float
    stop_distance: float
    target_distance: float
    rr_ratio: float
    position_size: int
    risk_per_share: float
    slippage_total: float  # total slippage cost for the trade
    # Tiered targets (empty = single D1 target, original behavior)
    target_tiers: list = None

    def __post_init__(self):
        if self.target_tiers is None:
            self.target_tiers = []


# Min R:R
MIN_RISK_REWARD = 3.0

# Stop caps by price range
HARD_STOP_CAPS = [
    (20, 50, 0.15),    # $20-50 → 15¢
    (50, 100, 0.25),   # $50-100 → 25¢
    (100, 200, 0.40),  # $100-200 → 40¢
]

# Slippage
SLIPPAGE_PER_SHARE = 0.02  # $0.02 each way

# Position sizing
DEFAULT_RISK_PCT = 0.003  # 0.3% of capital per trade


class RiskManagerConfig:
    def __init__(self, **kwargs):
        self.min_rr = kwargs.get('min_rr', MIN_RISK_REWARD)
        self.max_stop_atr_pct = kwargs.get('max_stop_atr_pct', 0.15)  # 15% of ATR_D1
        self.stop_buffer_min = kwargs.get('stop_buffer_min', 0.02)
        self.stop_buffer_atr_mult = kwargs.get('stop_buffer_atr_mult', 0.10)
        self.min_stop_atr_mult = kwargs.get('min_stop_atr_mult', 0.15)  # min 15% of ATR_M5
        self.min_stop_absolute = kwargs.get('min_stop_absolute', 0.05)
        self.slippage_per_share = kwargs.get('slippage_per_share', SLIPPAGE_PER_SHARE)
        self.risk_pct = kwargs.get('risk_pct', DEFAULT_RISK_PCT)
        self.capital = kwargs.get('capital', 100000.0)
        self.partial_tp_at = kwargs.get('partial_tp_at', 2.0)  # Take 50% at 2R
        self.partial_tp_pct = kwargs.get('partial_tp_pct', 0.50)
        # Circuit breakers
        self.max_consecutive_stops = kwargs.get('max_consecutive_stops', 3)
        self.max_daily_loss_pct = kwargs.get('max_daily_loss_pct', 0.01)   # 1%
        self.max_weekly_loss_pct = kwargs.get('max_weekly_loss_pct', 0.02)  # 2%
        self.max_monthly_loss_pct = kwargs.get('max_monthly_loss_pct', 0.08)  # 8%
        # Model4 size multiplier
        self.model4_size_mult = kwargs.get('model4_size_mult', 1.5)


class CircuitBreakerState:
    """Tracks circuit breaker conditions."""

    def __init__(self, config: RiskManagerConfig):
        self.config = config
        self.consecutive_stops = 0
        self.daily_pnl: dict[str, float] = {}   # date_str -> pnl
        self.weekly_pnl: dict[str, float] = {}   # week_str -> pnl
        self.monthly_pnl: dict[str, float] = {}  # month_str -> pnl
        self.stopped_today: set[str] = set()      # "ticker|level_price|date" combos
        self.open_positions: dict[str, bool] = {}  # ticker -> has_position

    def record_trade_result(self, ticker: str, date: pd.Timestamp,
                            pnl: float, was_stop: bool):
        date_str = date.strftime('%Y-%m-%d')
        week_str = f"{date.year}-W{date.isocalendar()[1]:02d}"
        month_str = date.strftime('%Y-%m')

        self.daily_pnl[date_str] = self.daily_pnl.get(date_str, 0.0) + pnl
        self.weekly_pnl[week_str] = self.weekly_pnl.get(week_str, 0.0) + pnl
        self.monthly_pnl[month_str] = self.monthly_pnl.get(month_str, 0.0) + pnl

        if was_stop:
            self.consecutive_stops += 1
        else:
            self.consecutive_stops = 0

    def record_stop_at_level(self, ticker: str, level_price: float,
                             date: pd.Timestamp):
        key = f"{ticker}|{level_price:.2f}|{date.strftime('%Y-%m-%d')}"
        self.stopped_today.add(key)

    def is_stopped_at_level_today(self, ticker: str, level_price: float,
                                  date: pd.Timestamp) -> bool:
        key = f"{ticker}|{level_price:.2f}|{date.strftime('%Y-%m-%d')}"
        return key in self.stopped_today

    def set_position(self, ticker: str, has_position: bool):
        self.open_positions[ticker] = has_position

    def has_open_position(self, ticker: str) -> bool:
        return self.open_positions.get(ticker, False)

    def check_circuit_breakers(self, date: pd.Timestamp,
                               capital: float) -> tuple[bool, str]:
        """Check if any circuit breaker is triggered.
        Returns (is_blocked, reason).
        """
        # Consecutive stops
        if self.consecutive_stops >= self.config.max_consecutive_stops:
            return True, f"{self.consecutive_stops} consecutive stops (max={self.config.max_consecutive_stops})"

        date_str = date.strftime('%Y-%m-%d')
        week_str = f"{date.year}-W{date.isocalendar()[1]:02d}"
        month_str = date.strftime('%Y-%m')

        # Daily loss
        daily = self.daily_pnl.get(date_str, 0.0)
        if daily < 0 and abs(daily) / capital >= self.config.max_daily_loss_pct:
            return True, f"Daily loss {daily:.2f} exceeds {self.config.max_daily_loss_pct*100:.1f}%"

        # Weekly loss
        weekly = self.weekly_pnl.get(week_str, 0.0)
        if weekly < 0 and abs(weekly) / capital >= self.config.max_weekly_loss_pct:
            return True, f"Weekly loss {weekly:.2f} exceeds {self.config.max_weekly_loss_pct*100:.1f}%"

        # Monthly loss
        monthly = self.monthly_pnl.get(month_str, 0.0)
        if monthly < 0 and abs(monthly) / capital >= self.config.max_monthly_loss_pct:
            return True, f"Monthly loss {monthly:.2f} exceeds {self.config.max_monthly_loss_pct*100:.1f}%"

        return False, ""

    def reset_daily(self, date: pd.Timestamp):
        """Reset daily state (consecutive stops reset on new day)."""
        self.consecutive_stops = 0
        # Clean old stopped-at-level entries
        date_str = date.strftime('%Y-%m-%d')
        self.stopped_today = {
            k for k in self.stopped_today if k.endswith(date_str)
        }


class RiskManager:
    def __init__(self, config: Optional[RiskManagerConfig] = None):
        self.config = config or RiskManagerConfig()
        self.cb_state = CircuitBreakerState(self.config)

    def _get_hard_stop_cap(self, price: float) -> Optional[float]:
        """Get hard stop cap based on price range."""
        for low, high, cap in HARD_STOP_CAPS:
            if low <= price < high:
                return cap
        return None  # > $200: dynamic only

    def calculate_stop(self, signal: Signal, m5_bars: pd.DataFrame,
                       atr_m5: float, atr_d1: float) -> float:
        """Calculate stop price based on LP candle extreme + buffer."""
        bar = m5_bars.iloc[signal.trigger_bar_idx]
        buffer = max(self.config.stop_buffer_min,
                     self.config.stop_buffer_atr_mult * atr_m5)

        if signal.direction == TradeDirection.SHORT:
            # Stop above the high of the trigger candle
            raw_stop = bar['High'] + buffer
        else:
            # Stop below the low of the trigger candle
            raw_stop = bar['Low'] - buffer

        stop_distance = abs(signal.entry_price - raw_stop)

        # Dynamic cap: stop ≤ 15% of ATR_D1
        dynamic_cap = self.config.max_stop_atr_pct * atr_d1

        # Hard cap by price range
        hard_cap = self._get_hard_stop_cap(signal.entry_price)

        # Min stop: prevents micro-stops
        min_stop = max(self.config.min_stop_atr_mult * atr_m5,
                       self.config.min_stop_absolute)

        # Apply caps: final = MIN(dynamic, hard) but at least min_stop
        max_stop = dynamic_cap
        if hard_cap is not None:
            max_stop = min(max_stop, hard_cap)

        # Clamp stop distance
        final_stop_dist = max(min(stop_distance, max_stop), min_stop)

        # Convert back to price
        if signal.direction == TradeDirection.SHORT:
            return signal.entry_price + final_stop_dist
        else:
            return signal.entry_price - final_stop_dist

    def calculate_target(self, signal: Signal, opposing_levels: list,
                         atr_d1: float) -> float:
        """Calculate target price: nearest opposing D1 level minus offset."""
        offset = 0.02 * atr_d1  # Small offset from level

        # Default stop distance estimate for fallback target
        default_stop_dist = self.config.max_stop_atr_pct * atr_d1 if atr_d1 > 0 else 1.0

        if signal.direction == TradeDirection.SHORT:
            # Target is below entry — find nearest support level below
            candidates = [
                lvl.price for lvl in opposing_levels
                if lvl.price < signal.entry_price
            ]
            if candidates:
                target = max(candidates) + offset  # Nearest below + offset
            else:
                # Default: 3R target based on estimated stop distance
                target = signal.entry_price - 3.0 * default_stop_dist
        else:
            # Target is above entry — find nearest resistance level above
            candidates = [
                lvl.price for lvl in opposing_levels
                if lvl.price > signal.entry_price
            ]
            if candidates:
                target = min(candidates) - offset
            else:
                target = signal.entry_price + 3.0 * default_stop_dist

        return target

    def calculate_risk_params(self, signal: Signal, m5_bars: pd.DataFrame,
                              atr_m5: float, atr_d1: float,
                              opposing_levels: list) -> Optional[RiskParams]:
        """Calculate full risk parameters for a trade. Returns None if R:R fails."""
        stop_price = self.calculate_stop(signal, m5_bars, atr_m5, atr_d1)
        target_price = self.calculate_target(signal, opposing_levels, atr_d1)

        stop_distance = abs(signal.entry_price - stop_price)
        target_distance = abs(target_price - signal.entry_price)

        # Include slippage in effective costs
        slippage = 2 * self.config.slippage_per_share  # entry + exit

        # Effective stop distance (including slippage)
        effective_stop = stop_distance + slippage

        if effective_stop <= 0:
            return None

        rr_ratio = target_distance / effective_stop

        if rr_ratio < self.config.min_rr:
            return None

        # Validate stop cap: min_stop can override hard cap, reject if so
        max_stop = self.config.max_stop_atr_pct * atr_d1
        hard_cap = self._get_hard_stop_cap(signal.entry_price)
        if hard_cap is not None:
            max_stop = min(max_stop, hard_cap)
        if stop_distance > max_stop + 0.001:
            # Stop exceeds cap (min_stop overrode hard cap) — skip trade
            return None

        # Position sizing: Capital × 0.3% / |Entry - Stop|
        risk_amount = self.config.capital * self.config.risk_pct
        position_size = int(risk_amount / effective_stop)

        # Model4 multiplier
        if signal.is_model4:
            position_size = int(position_size * self.config.model4_size_mult)

        position_size = max(position_size, 1)

        return RiskParams(
            stop_price=stop_price,
            target_price=target_price,
            stop_distance=stop_distance,
            target_distance=target_distance,
            rr_ratio=rr_ratio,
            position_size=position_size,
            risk_per_share=effective_stop,
            slippage_total=slippage * position_size,
        )

    def calculate_tiered_targets(self, signal: Signal, stop_distance: float,
                                d1_target: float,
                                intraday_targets: list,
                                tier_config: dict = None) -> list:
        """Build tiered target list from intraday levels.

        Args:
            signal: the trade signal
            stop_distance: absolute stop distance
            d1_target: original D1 target price
            intraday_targets: list of IntradayLevel objects (nearest first)
            tier_config: dict with 'mode' and allocation params

        Returns:
            list of TargetTier objects
        """
        from backtester.core.intraday_levels import IntradayLevel
        if tier_config is None:
            tier_config = {'mode': 'single_intraday'}

        mode = tier_config.get('mode', 'single_intraday')
        tiers = []

        if mode == 'single_intraday':
            # Replace D1 target with nearest intraday target
            if intraday_targets:
                t = intraday_targets[0]
                dist = abs(t.price - signal.entry_price)
                r_mult = dist / stop_distance if stop_distance > 0 else 0
                tiers.append(TargetTier(
                    price=t.price, exit_pct=1.0,
                    source=t.timeframe, r_multiple=r_mult
                ))
            else:
                # Fallback to D1
                dist = abs(d1_target - signal.entry_price)
                r_mult = dist / stop_distance if stop_distance > 0 else 0
                tiers.append(TargetTier(
                    price=d1_target, exit_pct=1.0,
                    source="D1", r_multiple=r_mult
                ))

        elif mode == '2tier':
            pct1 = tier_config.get('t1_pct', 0.50)
            pct2 = 1.0 - pct1
            if intraday_targets:
                t = intraday_targets[0]
                dist = abs(t.price - signal.entry_price)
                r_mult = dist / stop_distance if stop_distance > 0 else 0
                tiers.append(TargetTier(
                    price=t.price, exit_pct=pct1,
                    source=t.timeframe, r_multiple=r_mult
                ))
            else:
                # No intraday target — put everything on D1
                pct2 = 1.0

            dist_d1 = abs(d1_target - signal.entry_price)
            r_d1 = dist_d1 / stop_distance if stop_distance > 0 else 0
            tiers.append(TargetTier(
                price=d1_target, exit_pct=pct2,
                source="D1", r_multiple=r_d1
            ))

        elif mode == '3tier':
            pct1 = tier_config.get('t1_pct', 0.40)
            pct2 = tier_config.get('t2_pct', 0.30)
            pct3 = 1.0 - pct1 - pct2

            used = 0.0
            # T1: nearest M5
            if intraday_targets:
                t = intraday_targets[0]
                dist = abs(t.price - signal.entry_price)
                r_mult = dist / stop_distance if stop_distance > 0 else 0
                tiers.append(TargetTier(
                    price=t.price, exit_pct=pct1,
                    source=t.timeframe, r_multiple=r_mult
                ))
                used += pct1

            # T2: second intraday or H1 level
            h1_targets = [x for x in intraday_targets[1:] if x.timeframe == "H1"]
            m5_next = intraday_targets[1:2] if len(intraday_targets) > 1 else []
            t2_src = h1_targets[0] if h1_targets else (m5_next[0] if m5_next else None)

            if t2_src:
                dist = abs(t2_src.price - signal.entry_price)
                r_mult = dist / stop_distance if stop_distance > 0 else 0
                tiers.append(TargetTier(
                    price=t2_src.price, exit_pct=pct2,
                    source=t2_src.timeframe, r_multiple=r_mult
                ))
                used += pct2

            # T3: D1
            dist_d1 = abs(d1_target - signal.entry_price)
            r_d1 = dist_d1 / stop_distance if stop_distance > 0 else 0
            tiers.append(TargetTier(
                price=d1_target, exit_pct=1.0 - used,
                source="D1", r_multiple=r_d1
            ))

        elif mode == '2tier_trail':
            pct1 = tier_config.get('t1_pct', 0.50)
            if intraday_targets:
                t = intraday_targets[0]
                dist = abs(t.price - signal.entry_price)
                r_mult = dist / stop_distance if stop_distance > 0 else 0
                tiers.append(TargetTier(
                    price=t.price, exit_pct=pct1,
                    source=t.timeframe, r_multiple=r_mult
                ))
            # Remainder uses trailing stop (no fixed target)
            tiers.append(TargetTier(
                price=d1_target, exit_pct=1.0 - pct1,
                source="trail", r_multiple=0
            ))

        return tiers

    def calculate_risk_params_tiered(self, signal: Signal, m5_bars: pd.DataFrame,
                                     atr_m5: float, atr_d1: float,
                                     opposing_levels: list,
                                     intraday_targets: list = None,
                                     tier_config: dict = None) -> Optional[RiskParams]:
        """Calculate risk params with tiered target support.

        Like calculate_risk_params but uses intraday levels for targets
        and has a lower min R:R since targets are closer.
        """
        stop_price = self.calculate_stop(signal, m5_bars, atr_m5, atr_d1)
        d1_target = self.calculate_target(signal, opposing_levels, atr_d1)

        stop_distance = abs(signal.entry_price - stop_price)
        slippage = 2 * self.config.slippage_per_share
        effective_stop = stop_distance + slippage

        if effective_stop <= 0:
            return None

        # Build tiered targets
        target_tiers = []
        if intraday_targets and tier_config:
            target_tiers = self.calculate_tiered_targets(
                signal, stop_distance, d1_target, intraday_targets, tier_config
            )

        # Determine primary target for R:R check
        if target_tiers:
            primary_target = target_tiers[0].price
        else:
            primary_target = d1_target

        target_distance = abs(primary_target - signal.entry_price)
        rr_ratio = target_distance / effective_stop

        # Use tier-specific min R:R (typically lower than D1-only)
        min_rr = tier_config.get('min_rr', self.config.min_rr) if tier_config else self.config.min_rr
        if rr_ratio < min_rr:
            return None

        # Validate stop caps
        max_stop = self.config.max_stop_atr_pct * atr_d1
        hard_cap = self._get_hard_stop_cap(signal.entry_price)
        if hard_cap is not None:
            max_stop = min(max_stop, hard_cap)
        if stop_distance > max_stop + 0.001:
            return None

        # Position sizing
        risk_amount = self.config.capital * self.config.risk_pct
        position_size = int(risk_amount / effective_stop)
        if signal.is_model4:
            position_size = int(position_size * self.config.model4_size_mult)
        position_size = max(position_size, 1)

        return RiskParams(
            stop_price=stop_price,
            target_price=primary_target,
            stop_distance=stop_distance,
            target_distance=target_distance,
            rr_ratio=rr_ratio,
            position_size=position_size,
            risk_per_share=effective_stop,
            slippage_total=slippage * position_size,
            target_tiers=target_tiers,
        )

    def check_position_limits(self, signal: Signal,
                              date: pd.Timestamp) -> tuple[bool, str]:
        """Check position-level circuit breakers."""
        ticker = signal.ticker

        # One trade per ticker at a time
        if self.cb_state.has_open_position(ticker):
            return False, f"Already in position for {ticker}"

        # No re-entry at same level same day after stop
        if self.cb_state.is_stopped_at_level_today(
                ticker, signal.level.price, date):
            return False, f"Already stopped at level {signal.level.price:.2f} today"

        # Global circuit breakers
        blocked, reason = self.cb_state.check_circuit_breakers(
            date, self.config.capital)
        if blocked:
            return False, f"Circuit breaker: {reason}"

        return True, ""
