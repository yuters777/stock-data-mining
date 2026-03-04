"""
Canonical data types for the False Breakout Strategy Backtester.

All dataclasses, enums, and type definitions used across backtester modules.
Reference: L-005.1 spec, Backtester Architecture v1 §3.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import pandas as pd


# ── Enums ──────────────────────────────────────────────────────────────────

class LevelType(Enum):
    """Type of price level detected on D1 chart."""
    RESISTANCE = "R"
    SUPPORT = "S"
    MIRROR = "M"


class LevelStatus(Enum):
    """Lifecycle status of a detected level.

    Lifecycle: ACTIVE → BROKEN → MIRROR_CANDIDATE → MIRROR_CONFIRMED
               ACTIVE → INVALIDATED (sawing or Nison)
    """
    ACTIVE = "active"
    BROKEN = "broken"                    # price broke through level
    INVALIDATED = "invalidated"
    MIRROR_CANDIDATE = "mirror_candidate"
    MIRROR_CONFIRMED = "mirror_confirmed"


class PatternType(Enum):
    """M5 false-breakout pattern types (L-005.1 §5)."""
    LP1 = "LP1"       # 1-bar reversal
    LP2 = "LP2"       # 2-bar reversal (engulfing)
    CLP = "CLP"       # 3-7 bar consolidation at level
    MODEL4 = "MODEL4" # multi-bar model-4 pattern


class SignalDirection(Enum):
    """Trade direction for a signal."""
    LONG = "long"
    SHORT = "short"


class LP2Quality(Enum):
    """Quality classification for LP2 patterns (L-005.1 §5).

    IDEAL:      Close_Bar2 < Open_Bar1 (full engulfing) → size mult 1.0
    ACCEPTABLE: Close_Bar2 < Close_Bar1 (partial)       → size mult 0.7
    WEAK:       Close_Bar2 < Level only (minimal)        → size mult 0.5
    """
    IDEAL = "ideal"          # 1.0x position sizing
    ACCEPTABLE = "acceptable"  # 0.7x position sizing
    WEAK = "weak"            # 0.5x position sizing


class SignalStatus(Enum):
    """Processing status of a signal through the filter chain."""
    PENDING = "pending"
    PASSED = "passed"
    BLOCKED = "blocked"
    EXECUTED = "executed"


class TradeStatus(Enum):
    """Lifecycle status of a trade."""
    OPEN = "open"
    CLOSED = "closed"
    PARTIAL = "partial"  # partially closed (tier 1 hit)


class ExitReason(Enum):
    """Reason a trade was closed.

    Exit precedence: SL → TP → Mirror/Nison → Time → EOD
    """
    STOP_LOSS = "stop_loss"
    TARGET_HIT = "target_hit"
    PARTIAL_TP = "partial_tp"
    BREAKEVEN = "breakeven_stop"
    NISON_EXIT = "nison_exit"        # mirror level invalidated mid-trade
    TRAIL_STOP = "trail_stop"
    EOD_EXIT = "eod_exit"
    CIRCUIT_BREAKER = "circuit_breaker"


# ── Dataclasses ────────────────────────────────────────────────────────────

@dataclass
class Bar:
    """Single OHLCV bar (M5, H1, or D1)."""
    symbol: str
    timestamp: pd.Timestamp
    timeframe: str           # "M5", "H1", "D1"
    open: float
    high: float
    low: float
    close: float
    volume: int = 0

    @property
    def range(self) -> float:
        """Bar range (high - low)."""
        return self.high - self.low

    @property
    def body(self) -> float:
        """Absolute body size."""
        return abs(self.close - self.open)

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low


@dataclass
class Level:
    """A detected support/resistance level on D1."""
    price: float
    level_type: LevelType
    status: LevelStatus = LevelStatus.ACTIVE
    score: int = 0
    confirmed_at: Optional[pd.Timestamp] = None
    ticker: str = ""
    date: Optional[pd.Timestamp] = None
    bsu_index: int = 0
    atr_d1: float = 0.0
    is_paranormal: bool = False
    touches: int = 0
    is_round_number: bool = False
    is_mirror: bool = False
    cross_count: int = 0
    last_cross_bar: int = -1
    mirror_breakout_date: Optional[pd.Timestamp] = None
    mirror_max_distance_atr: float = 0.0
    mirror_days_beyond: int = 0
    score_breakdown: dict = field(default_factory=dict)


@dataclass
class Signal:
    """A detected false-breakout signal on M5."""
    pattern: PatternType
    direction: SignalDirection
    level: Level
    timestamp: Optional[pd.Timestamp] = None
    ticker: str = ""
    entry_price: float = 0.0
    trigger_bar_idx: int = 0
    tail_ratio: float = 0.0
    bars_beyond: int = 0
    is_model4: bool = False
    lp2_quality: Optional['LP2Quality'] = None
    position_size_mult: float = 1.0  # LP2 quality adjustment
    status: SignalStatus = SignalStatus.PENDING
    filter_results: dict = field(default_factory=dict)
    # Risk sizing (populated by risk manager)
    stop_price: float = 0.0
    target_price: float = 0.0
    position_size: int = 0
    risk_per_share: float = 0.0
    rr_ratio: float = 0.0
    priority: int = 0
    meta: dict = field(default_factory=dict)


@dataclass
class Trade:
    """A complete trade from entry to exit."""
    signal: Signal
    entry_price: float = 0.0
    entry_time: Optional[pd.Timestamp] = None
    exit_price: float = 0.0
    exit_time: Optional[pd.Timestamp] = None
    exit_reason: Optional[ExitReason] = None
    direction: SignalDirection = SignalDirection.SHORT
    status: TradeStatus = TradeStatus.OPEN
    position_size: int = 0
    remaining_size: int = 0
    # P&L
    pnl: float = 0.0
    pnl_r: float = 0.0
    # Stops & targets
    stop_price: float = 0.0
    target_price: float = 0.0
    # Excursion tracking
    max_favorable: float = 0.0
    max_adverse: float = 0.0
    # Tiered target tracking
    tier_exits_done: int = 0
    trailing_stop_active: bool = False
    trailing_stop_price: float = 0.0
    partial_exits: list = field(default_factory=list)
    is_breakeven: bool = False
    # Slippage
    slippage_total: float = 0.0
    # Sector for portfolio analysis
    sector: str = ""

    @property
    def is_winner(self) -> bool:
        return self.pnl > 0

    @property
    def is_closed(self) -> bool:
        return self.status == TradeStatus.CLOSED


@dataclass
class EquitySnapshot:
    """Portfolio equity state at a point in time."""
    timestamp: pd.Timestamp
    cash: float
    unrealized_pnl: float = 0.0
    total_equity: float = 0.0
    drawdown: float = 0.0
    drawdown_pct: float = 0.0
    peak_equity: float = 0.0

    def __post_init__(self):
        if self.total_equity == 0.0:
            self.total_equity = self.cash + self.unrealized_pnl
