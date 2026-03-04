"""
Trade Manager for the False Breakout Strategy Backtester.

Handles trade execution, partial take-profit, breakeven stop movement,
Nison invalidation exit, and EOD exit logic.
Manages the lifecycle of each trade from entry to exit.

Exit precedence: SL → TP → Mirror/Nison → Breakeven → EOD
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional

from backtester.data_types import Signal, SignalDirection, LevelStatus
from backtester.core.risk_manager import RiskParams, RiskManager, calculate_slippage

# Backwards-compatible alias used throughout this module
TradeDirection = SignalDirection

# Use canonical ExitReason from data_types
from backtester.data_types import ExitReason


@dataclass
class Trade:
    """Represents a complete trade from entry to exit."""
    signal: Signal
    risk_params: RiskParams
    entry_price: float
    entry_time: pd.Timestamp
    exit_price: float = 0.0
    exit_time: Optional[pd.Timestamp] = None
    exit_reason: Optional[ExitReason] = None
    direction: TradeDirection = TradeDirection.SHORT
    position_size: int = 0
    remaining_size: int = 0
    pnl: float = 0.0
    pnl_r: float = 0.0  # P&L in R-multiples
    partial_exits: list = field(default_factory=list)
    is_breakeven: bool = False
    stop_price: float = 0.0
    target_price: float = 0.0
    max_favorable: float = 0.0  # max favorable excursion
    max_adverse: float = 0.0    # max adverse excursion
    # Tiered target tracking
    tier_exits_done: int = 0  # how many tiers have been hit
    trailing_stop_active: bool = False
    trailing_stop_price: float = 0.0

    @property
    def is_winner(self) -> bool:
        return self.pnl > 0

    @property
    def is_closed(self) -> bool:
        return self.exit_time is not None and self.remaining_size == 0


# IST market hours — data timestamps are IST
# ET 15:55 = IST 22:55 (winter/EST), IST 21:55 (summer/EDT)
# We use winter IST (22:55) as default since most of the year is EST
EOD_EXIT_HOUR_IST = 22
EOD_EXIT_MINUTE_IST = 55
ENTRY_CUTOFF_HOUR_IST = 22
ENTRY_CUTOFF_MINUTE_IST = 45


class TradeManagerConfig:
    def __init__(self, **kwargs):
        self.partial_tp_at_r = kwargs.get('partial_tp_at_r', 2.0)
        self.partial_tp_pct = kwargs.get('partial_tp_pct', 0.50)
        self.breakeven_stop_dist_mult = kwargs.get('breakeven_stop_dist_mult', 2.0)
        self.breakeven_tp_path_pct = kwargs.get('breakeven_tp_path_pct', 0.50)
        # IST hours (22:55 IST = 15:55 ET winter)
        self.eod_exit_hour = kwargs.get('eod_exit_hour', EOD_EXIT_HOUR_IST)
        self.eod_exit_minute = kwargs.get('eod_exit_minute', EOD_EXIT_MINUTE_IST)
        self.entry_cutoff_hour = kwargs.get('entry_cutoff_hour', ENTRY_CUTOFF_HOUR_IST)
        self.entry_cutoff_minute = kwargs.get('entry_cutoff_minute', ENTRY_CUTOFF_MINUTE_IST)


class TradeManager:
    def __init__(self, config: Optional[TradeManagerConfig] = None,
                 risk_manager: Optional[RiskManager] = None,
                 tier_config: Optional[dict] = None):
        self.config = config or TradeManagerConfig()
        self.risk_manager = risk_manager
        self.open_trades: list[Trade] = []
        self.closed_trades: list[Trade] = []
        # Trail parameters from tier_config
        self._trail_factor = (tier_config or {}).get('trail_factor', 1.0)
        self._trail_activation_r = (tier_config or {}).get('trail_activation_r', 0.0)
        # Pending entries: signals waiting for next bar open
        self._pending_entries: list[tuple[Signal, RiskParams]] = []

    def queue_entry(self, signal: Signal, risk_params: RiskParams):
        """Queue a signal for entry at the NEXT bar's open + slippage.

        Per L-005.1 §7: entry must be at next bar open, not signal bar.
        Call this when a signal passes all filters. The actual trade is
        opened on the next call to update_trades().
        """
        self._pending_entries.append((signal, risk_params))

    def _is_past_entry_cutoff(self, timestamp: pd.Timestamp) -> bool:
        """Check if we're past the entry cutoff (22:45 IST = 15:45 ET winter)."""
        return (timestamp.hour > self.config.entry_cutoff_hour or
                (timestamp.hour == self.config.entry_cutoff_hour and
                 timestamp.minute >= self.config.entry_cutoff_minute))

    def open_trade(self, signal: Signal, risk_params: RiskParams,
                   entry_price: float, entry_time: pd.Timestamp) -> Trade:
        """Create and register a new trade.

        Args:
            signal: The signal that triggered the trade
            risk_params: Calculated risk parameters
            entry_price: The next bar's open price (before slippage)
            entry_time: The next bar's timestamp
        """
        assert not any(
            t.signal.ticker == signal.ticker for t in self.open_trades
        ), f"Already in position for {signal.ticker}"

        # Apply entry slippage: MAX(1¢, 0.02% of price)
        slippage = calculate_slippage(entry_price)
        if signal.direction == TradeDirection.SHORT:
            fill_price = entry_price - slippage  # worse fill for short
        else:
            fill_price = entry_price + slippage  # worse fill for long

        trade = Trade(
            signal=signal,
            risk_params=risk_params,
            entry_price=fill_price,
            entry_time=entry_time,
            direction=signal.direction,
            position_size=risk_params.position_size,
            remaining_size=risk_params.position_size,
            stop_price=risk_params.stop_price,
            target_price=risk_params.target_price,
        )

        self.open_trades.append(trade)

        if self.risk_manager:
            self.risk_manager.cb_state.set_position(signal.ticker, True)

        return trade

    def _calculate_unrealized_pnl(self, trade: Trade, current_price: float) -> float:
        """Calculate unrealized P&L for remaining position."""
        if trade.direction == TradeDirection.SHORT:
            return (trade.entry_price - current_price) * trade.remaining_size
        else:
            return (current_price - trade.entry_price) * trade.remaining_size

    def _apply_exit_slippage(self, price: float, direction: TradeDirection) -> float:
        """Apply slippage on exit: MAX(1¢, 0.02% of price)."""
        slippage = calculate_slippage(price)
        if direction == TradeDirection.SHORT:
            return price + slippage  # buying back at higher price
        else:
            return price - slippage  # selling at lower price

    def _close_trade(self, trade: Trade, exit_price: float,
                     exit_time: pd.Timestamp, reason: ExitReason):
        """Fully close a trade."""
        exit_price = self._apply_exit_slippage(exit_price, trade.direction)
        trade.exit_price = exit_price
        trade.exit_time = exit_time
        trade.exit_reason = reason

        # Calculate total P&L including partial exits
        total_pnl = 0.0
        for partial in trade.partial_exits:
            total_pnl += partial['pnl']

        # Remaining position P&L
        if trade.remaining_size > 0:
            if trade.direction == TradeDirection.SHORT:
                remaining_pnl = (trade.entry_price - exit_price) * trade.remaining_size
            else:
                remaining_pnl = (exit_price - trade.entry_price) * trade.remaining_size
            total_pnl += remaining_pnl

        trade.pnl = total_pnl
        trade.remaining_size = 0

        # P&L in R-multiples
        risk = trade.risk_params.risk_per_share * trade.risk_params.position_size
        trade.pnl_r = total_pnl / risk if risk > 0 else 0.0

        # Move to closed
        self.open_trades = [t for t in self.open_trades if t is not trade]
        self.closed_trades.append(trade)

        if self.risk_manager:
            self.risk_manager.cb_state.set_position(trade.signal.ticker, False)
            was_stop = reason == ExitReason.STOP_LOSS
            self.risk_manager.cb_state.record_trade_result(
                trade.signal.ticker, exit_time, trade.pnl, was_stop
            )
            if was_stop:
                self.risk_manager.cb_state.record_stop_at_level(
                    trade.signal.ticker, trade.signal.level.price, exit_time
                )

    def _partial_take_profit(self, trade: Trade, current_price: float,
                             current_time: pd.Timestamp) -> bool:
        """Execute partial take profit at configured R-multiple."""
        if trade.partial_exits:
            return False  # Already took partial

        stop_dist = trade.risk_params.stop_distance
        entry = trade.entry_price

        if trade.direction == TradeDirection.SHORT:
            favorable_move = entry - current_price
        else:
            favorable_move = current_price - entry

        r_multiple = favorable_move / stop_dist if stop_dist > 0 else 0

        if r_multiple >= self.config.partial_tp_at_r:
            partial_size = int(trade.position_size * self.config.partial_tp_pct)
            if partial_size < 1:
                partial_size = 1

            exit_price = self._apply_exit_slippage(current_price, trade.direction)
            if trade.direction == TradeDirection.SHORT:
                pnl = (entry - exit_price) * partial_size
            else:
                pnl = (exit_price - entry) * partial_size

            trade.partial_exits.append({
                'time': current_time,
                'price': exit_price,
                'size': partial_size,
                'pnl': pnl,
                'r_multiple': r_multiple,
            })
            trade.remaining_size -= partial_size
            return True

        return False

    def _check_breakeven(self, trade: Trade, current_price: float) -> bool:
        """Move stop to breakeven when conditions are met."""
        if trade.is_breakeven:
            return False

        stop_dist = trade.risk_params.stop_distance
        entry = trade.entry_price
        target = trade.target_price

        if trade.direction == TradeDirection.SHORT:
            favorable_move = entry - current_price
            tp_path = entry - target
        else:
            favorable_move = current_price - entry
            tp_path = target - entry

        # Condition 1: favorable move >= 2× stop distance
        cond1 = favorable_move >= self.config.breakeven_stop_dist_mult * stop_dist

        # Condition 2: favorable move >= 50% of TP path
        cond2 = tp_path > 0 and favorable_move >= self.config.breakeven_tp_path_pct * tp_path

        if cond1 or cond2:
            # Move stop to entry (breakeven) + tiny buffer
            buffer = calculate_slippage(entry)
            if trade.direction == TradeDirection.SHORT:
                trade.stop_price = entry - buffer  # slightly profitable
            else:
                trade.stop_price = entry + buffer
            trade.is_breakeven = True
            return True

        return False

    def _check_nison_exit(self, trade: Trade, close: float,
                          bar_time: pd.Timestamp) -> bool:
        """Check if trade's mirror level has been invalidated (Nison).

        Per L-005.1: if a mirror level is invalidated (close beyond level),
        exit the trade at next bar open. We detect the condition here and
        mark the trade for exit.
        """
        level = trade.signal.level
        if not level.is_mirror:
            return False

        # Check if level status is INVALIDATED (set by level_detector.check_nison_invalidation)
        if level.status == LevelStatus.INVALIDATED:
            self._close_trade(trade, close, bar_time, ExitReason.NISON_EXIT)
            return True

        return False

    def _check_tiered_targets(self, trade: Trade, high: float, low: float,
                              close: float, bar_time: pd.Timestamp) -> bool:
        """Check if any tiered target has been hit. Execute partial exits.
        Returns True if any tier was hit this bar.
        """
        tiers = trade.risk_params.target_tiers
        if not tiers:
            return False

        any_hit = False
        while trade.tier_exits_done < len(tiers) and trade.remaining_size > 0:
            tier = tiers[trade.tier_exits_done]

            # Skip trail tiers (handled by trailing stop)
            if tier.source == "trail":
                if not trade.trailing_stop_active:
                    trade.trailing_stop_active = True
                    # Set initial trailing stop at breakeven
                    buffer = calculate_slippage(trade.entry_price)
                    if trade.direction == TradeDirection.SHORT:
                        trade.trailing_stop_price = trade.entry_price - buffer
                    else:
                        trade.trailing_stop_price = trade.entry_price + buffer
                trade.tier_exits_done += 1
                continue

            hit = False
            if trade.direction == TradeDirection.SHORT:
                hit = low <= tier.price
            else:
                hit = high >= tier.price

            if not hit:
                break

            # Execute partial exit at this tier
            exit_size = int(trade.position_size * tier.exit_pct)
            exit_size = min(exit_size, trade.remaining_size)
            if exit_size < 1:
                exit_size = 1

            exit_price = self._apply_exit_slippage(tier.price, trade.direction)
            if trade.direction == TradeDirection.SHORT:
                pnl = (trade.entry_price - exit_price) * exit_size
            else:
                pnl = (exit_price - trade.entry_price) * exit_size

            trade.partial_exits.append({
                'time': bar_time,
                'price': exit_price,
                'size': exit_size,
                'pnl': pnl,
                'tier': trade.tier_exits_done + 1,
                'source': tier.source,
            })
            trade.remaining_size -= exit_size
            trade.tier_exits_done += 1
            any_hit = True

            # If position fully closed, finalize
            if trade.remaining_size <= 0:
                trade.exit_time = bar_time
                trade.exit_price = exit_price
                trade.exit_reason = ExitReason.TARGET_HIT
                trade.pnl = sum(p['pnl'] for p in trade.partial_exits)
                risk = trade.risk_params.risk_per_share * trade.risk_params.position_size
                trade.pnl_r = trade.pnl / risk if risk > 0 else 0.0
                self.open_trades = [t for t in self.open_trades if t is not trade]
                self.closed_trades.append(trade)
                if self.risk_manager:
                    self.risk_manager.cb_state.set_position(trade.signal.ticker, False)
                    self.risk_manager.cb_state.record_trade_result(
                        trade.signal.ticker, bar_time, trade.pnl, False
                    )
                break

        return any_hit

    def _update_trailing_stop(self, trade: Trade, high: float, low: float):
        """Update trailing stop price for trail tier.

        Uses trail_factor from tier_config to control trail distance:
          trail_dist = trail_factor * stop_distance
        Uses trail_activation_r to delay trail movement until price moves
          favorably by at least trail_activation_r * stop_distance.
        """
        if not trade.trailing_stop_active:
            return

        trail_factor = self._trail_factor
        trail_activation_r = self._trail_activation_r
        trail_dist = trail_factor * trade.risk_params.stop_distance

        # Check activation threshold
        if trail_activation_r > 0:
            activation_dist = trail_activation_r * trade.risk_params.stop_distance
            if trade.direction == TradeDirection.SHORT:
                favorable = trade.entry_price - low
            else:
                favorable = high - trade.entry_price
            if favorable < activation_dist:
                return  # Not enough favorable movement to start trailing

        if trade.direction == TradeDirection.SHORT:
            # Trail down: stop follows price down
            new_stop = low + trail_dist
            if new_stop < trade.trailing_stop_price:
                trade.trailing_stop_price = new_stop
        else:
            # Trail up: stop follows price up
            new_stop = high - trail_dist
            if new_stop > trade.trailing_stop_price:
                trade.trailing_stop_price = new_stop

    def _is_eod(self, timestamp: pd.Timestamp) -> bool:
        """Check if we should force exit (end of day). IST hours."""
        return (timestamp.hour > self.config.eod_exit_hour or
                (timestamp.hour == self.config.eod_exit_hour and
                 timestamp.minute >= self.config.eod_exit_minute))

    def _process_pending_entries(self, m5_bar: pd.Series,
                                 bar_time: pd.Timestamp) -> list[Trade]:
        """Process pending entries using this bar's open as entry price.

        Per L-005.1 §7: entry at NEXT bar open + slippage.
        """
        opened = []
        remaining = []

        for signal, risk_params in self._pending_entries:
            # Skip if past entry cutoff
            if self._is_past_entry_cutoff(bar_time):
                continue

            # Skip if ticker doesn't match this bar
            if signal.ticker != m5_bar['Ticker']:
                remaining.append((signal, risk_params))
                continue

            # Skip if already in position
            if any(t.signal.ticker == signal.ticker for t in self.open_trades):
                continue

            # Enter at this bar's open
            entry_price = m5_bar['Open']
            trade = self.open_trade(signal, risk_params, entry_price, bar_time)
            opened.append(trade)

        self._pending_entries = remaining
        return opened

    def update_trades(self, m5_bar: pd.Series,
                      bar_time: pd.Timestamp) -> list[Trade]:
        """Update all open trades with a new M5 bar.

        Exit precedence: SL → TP → Mirror/Nison → Breakeven → EOD

        Also processes pending entries (next-bar-open execution).
        Returns list of trades that were closed this bar.
        """
        # Process pending entries first (enter at this bar's open)
        self._process_pending_entries(m5_bar, bar_time)

        closed_this_bar = []

        for trade in list(self.open_trades):
            if trade.signal.ticker != m5_bar['Ticker']:
                continue

            high = m5_bar['High']
            low = m5_bar['Low']
            close = m5_bar['Close']

            # Update max favorable/adverse excursion
            if trade.direction == TradeDirection.SHORT:
                favorable = trade.entry_price - low
                adverse = high - trade.entry_price
            else:
                favorable = high - trade.entry_price
                adverse = trade.entry_price - low

            trade.max_favorable = max(trade.max_favorable, favorable)
            trade.max_adverse = max(trade.max_adverse, adverse)

            # === EXIT PRECEDENCE: SL → TP → Mirror/Nison → Breakeven → EOD ===

            # 1. STOP LOSS (highest priority — worst case assumption)
            effective_stop = (trade.trailing_stop_price
                              if trade.trailing_stop_active
                              else trade.stop_price)
            stopped = False
            if trade.direction == TradeDirection.SHORT:
                if high >= effective_stop:
                    reason = ExitReason.TRAIL_STOP if trade.trailing_stop_active else ExitReason.STOP_LOSS
                    self._close_trade(trade, effective_stop, bar_time, reason)
                    closed_this_bar.append(trade)
                    stopped = True
            else:
                if low <= effective_stop:
                    reason = ExitReason.TRAIL_STOP if trade.trailing_stop_active else ExitReason.STOP_LOSS
                    self._close_trade(trade, effective_stop, bar_time, reason)
                    closed_this_bar.append(trade)
                    stopped = True

            if stopped:
                continue

            # 2. TARGET PROFIT
            tier_closed = False
            if trade.risk_params.target_tiers:
                tier_closed = self._check_tiered_targets(
                    trade, high, low, close, bar_time)
                if trade.remaining_size <= 0:
                    closed_this_bar.append(trade)
                    continue

                # Update trailing stop if applicable
                if trade.trailing_stop_active:
                    self._update_trailing_stop(trade, high, low)
            else:
                # Original single-target behavior
                target_hit = False
                if trade.direction == TradeDirection.SHORT:
                    if low <= trade.target_price:
                        self._close_trade(trade, trade.target_price, bar_time,
                                          ExitReason.TARGET_HIT)
                        closed_this_bar.append(trade)
                        target_hit = True
                else:
                    if high >= trade.target_price:
                        self._close_trade(trade, trade.target_price, bar_time,
                                          ExitReason.TARGET_HIT)
                        closed_this_bar.append(trade)
                        target_hit = True

                if target_hit:
                    continue

                # Partial take profit (original behavior for non-tiered)
                self._partial_take_profit(trade, close, bar_time)

            # 3. MIRROR/NISON INVALIDATION EXIT
            if self._check_nison_exit(trade, close, bar_time):
                closed_this_bar.append(trade)
                continue

            # 4. BREAKEVEN CHECK (move stop, not an exit)
            self._check_breakeven(trade, close)

            # 5. EOD EXIT (lowest priority)
            if self._is_eod(bar_time):
                self._close_trade(trade, close, bar_time, ExitReason.EOD_EXIT)
                closed_this_bar.append(trade)

        return closed_this_bar

    def get_portfolio_exposure(self) -> tuple[float, float]:
        """Calculate unrealized P&L and worst-case P&L for all open trades.

        Returns (unrealized_pnl, worst_case_pnl) for circuit breaker use.
        worst_case = P&L if all stops are hit simultaneously.
        """
        unrealized = 0.0
        worst_case = 0.0

        for trade in self.open_trades:
            # Unrealized uses last known close (approximate with entry for now)
            # In practice, caller should pass current prices
            stop_dist = trade.risk_params.stop_distance
            slippage = calculate_slippage(trade.entry_price)

            # Worst case: all stops hit
            wc_loss = -(stop_dist + slippage) * trade.remaining_size
            worst_case += wc_loss

        return unrealized, worst_case

    def get_open_trade(self, ticker: str) -> Optional[Trade]:
        for trade in self.open_trades:
            if trade.signal.ticker == ticker:
                return trade
        return None

    def get_trade_stats(self) -> dict:
        """Get summary statistics for all closed trades."""
        if not self.closed_trades:
            return {
                'total_trades': 0, 'winners': 0, 'losers': 0,
                'win_rate': 0.0, 'avg_r': 0.0, 'total_pnl': 0.0,
            }

        winners = [t for t in self.closed_trades if t.is_winner]
        losers = [t for t in self.closed_trades if not t.is_winner]

        total_pnl = sum(t.pnl for t in self.closed_trades)
        gross_profit = sum(t.pnl for t in winners)
        gross_loss = abs(sum(t.pnl for t in losers))

        return {
            'total_trades': len(self.closed_trades),
            'winners': len(winners),
            'losers': len(losers),
            'eod_exits': sum(1 for t in self.closed_trades if t.exit_reason == ExitReason.EOD_EXIT),
            'nison_exits': sum(1 for t in self.closed_trades if t.exit_reason == ExitReason.NISON_EXIT),
            'win_rate': len(winners) / len(self.closed_trades) if self.closed_trades else 0.0,
            'avg_r': np.mean([t.pnl_r for t in self.closed_trades]) if self.closed_trades else 0.0,
            'total_pnl': total_pnl,
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
            'profit_factor': gross_profit / gross_loss if gross_loss > 0 else float('inf'),
            'avg_winner': np.mean([t.pnl for t in winners]) if winners else 0.0,
            'avg_loser': np.mean([t.pnl for t in losers]) if losers else 0.0,
            'max_winner': max([t.pnl for t in winners], default=0.0),
            'max_loser': min([t.pnl for t in losers], default=0.0),
        }
