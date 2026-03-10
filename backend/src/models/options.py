"""
Options trading models: Greeks, legs, positions, signals, adjustments.
"""
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# ENUMS
# ---------------------------------------------------------------------------

class OptionType(str, Enum):
    """Call or Put option."""
    CE = "CE"  # Call
    PE = "PE"  # Put


class LegAction(str, Enum):
    """Buy or Sell leg."""
    BUY = "BUY"
    SELL = "SELL"


class PositionStatus(str, Enum):
    """Options position lifecycle status."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ADJUSTED = "ADJUSTED"
    EXPIRED = "EXPIRED"


class StructureType(str, Enum):
    """Multi-leg option structures."""
    IRON_CONDOR = "IRON_CONDOR"
    IRON_BUTTERFLY = "IRON_BUTTERFLY"
    BUTTERFLY = "BUTTERFLY"
    LONG_CALL_SPREAD = "LONG_CALL_SPREAD"
    LONG_PUT_SPREAD = "LONG_PUT_SPREAD"
    SHORT_CALL_SPREAD = "SHORT_CALL_SPREAD"
    SHORT_PUT_SPREAD = "SHORT_PUT_SPREAD"
    LONG_STRADDLE = "LONG_STRADDLE"
    SHORT_STRADDLE = "SHORT_STRADDLE"
    LONG_STRANGLE = "LONG_STRANGLE"
    SHORT_STRANGLE = "SHORT_STRANGLE"
    RATIO_SPREAD = "RATIO_SPREAD"
    CALENDAR_SPREAD = "CALENDAR_SPREAD"
    DIAGONAL_SPREAD = "DIAGONAL_SPREAD"
    CUSTOM = "CUSTOM"


class AdjustmentType(str, Enum):
    """Types of position adjustments."""
    ROLL_UP = "ROLL_UP"         # Roll sold leg to higher strike
    ROLL_DOWN = "ROLL_DOWN"     # Roll sold leg to lower strike
    ROLL_OUT = "ROLL_OUT"       # Extend expiry (buy back + sell further)
    CLOSE_HALF = "CLOSE_HALF"   # Close half position
    CLOSE_ALL = "CLOSE_ALL"     # Close entire position
    CONVERT = "CONVERT"         # Convert to different structure
    ADD_HEDGE = "ADD_HEDGE"     # Add protective leg


# ---------------------------------------------------------------------------
# Data Models (Pydantic)
# ---------------------------------------------------------------------------

class Greeks(BaseModel):
    """Options Greeks: price sensitivity metrics."""
    delta: float = 0.0       # Price sensitivity (-1 to 1)
    gamma: float = 0.0       # Delta acceleration
    vega: float = 0.0        # IV sensitivity
    theta: float = 0.0       # Time decay (daily)
    rho: float = 0.0         # Interest rate sensitivity
    iv_rank: float = 0.0     # IV percentile (0-100)
    iv: float = 0.0          # Implied volatility (%)
    
    class Config:
        frozen = False


class OptionChainItem(BaseModel):
    """Single option contract in a chain (strike + Greeks)."""
    symbol: str              # Underlying (e.g., NIFTY50)
    strike: float            # Strike price
    option_type: OptionType  # CE or PE
    expiry: str              # DDMMMYY format
    bid: float = 0.0         # Bid price
    ask: float = 0.0         # Ask price
    last_price: float = 0.0  # LTP
    open_interest: int = 0   # OI
    volume: int = 0          # Volume
    lot_size: int = 1        # Lot size
    greeks: Optional[Greeks] = None  # Greeks data
    
    class Config:
        frozen = False


class OptionChain(BaseModel):
    """Complete option chain for an underlying."""
    symbol: str
    spot_price: float
    expiry_dates: List[str]
    atm_strike: float
    items: List[OptionChainItem]
    fetched_at: datetime = field(default_factory=datetime.now)
    
    class Config:
        frozen = False


class LegSignal(BaseModel):
    """Single leg of a multi-leg options signal."""
    leg_id: str
    symbol: str              # Underlying
    option_type: str         # CE or PE
    strike: float
    expiry: str              # DDMMMYY
    action: str              # BUY or SELL
    quantity: int
    lot_size: int = 1
    premium: float = 0.0     # Premium (for reference)
    greeks: Optional[Greeks] = None
    
    class Config:
        frozen = False


class OptionsSignal(BaseModel):
    """Complete multi-leg options trading signal."""
    signal_id: str
    strategy_name: str
    symbol: str
    legs: List[LegSignal]
    structure_type: str          # From StructureType enum
    net_premium: float           # Total debit/credit
    max_profit: Optional[float] = None
    max_loss: Optional[float] = None
    breakevens: Optional[List[float]] = None
    expiry: Optional[str] = None
    entry_price: Optional[float] = None  # Spot at signal time
    entry_time: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    class Config:
        frozen = False


# ---------------------------------------------------------------------------
# Dataclasses (for position tracking)
# ---------------------------------------------------------------------------

@dataclass
class LegPosition:
    """Tracked leg in an open multi-leg position."""
    leg_id: str
    symbol: str
    option_type: OptionType
    strike: float
    expiry: str
    action: LegAction
    quantity: int
    lot_size: int
    premium_paid: float           # Entry premium
    current_premium: float = 0.0  # Latest premium
    greeks: Optional[Greeks] = None
    entry_time: datetime = field(default_factory=datetime.now)
    order_id: Optional[str] = None
    status: str = "OPEN"  # OPEN, FILLED, EXITED


@dataclass
class MultiLegPosition:
    """Complete open multi-leg options position."""
    position_id: str
    symbol: str
    strategy_id: str
    strategy_name: str
    structure_type: StructureType
    legs: List[LegPosition]
    net_premium_paid: float       # Total debit/credit
    max_profit: Optional[float] = None
    max_loss: Optional[float] = None
    breakevens: Optional[List[float]] = None
    entry_price: float = 0.0      # Spot at entry
    entry_time: datetime = field(default_factory=datetime.now)
    status: PositionStatus = PositionStatus.OPEN
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    adjustments_count: int = 0
    adjustment_history: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def portfolio_greeks(self) -> Greeks:
        """Aggregate Greeks across all legs."""
        agg = Greeks()
        for leg in self.legs:
            if leg.greeks:
                sign = 1 if leg.action == LegAction.BUY else -1
                agg.delta += leg.greeks.delta * sign * leg.quantity
                agg.gamma += leg.greeks.gamma * sign * leg.quantity
                agg.vega += leg.greeks.vega * sign * leg.quantity
                agg.theta += leg.greeks.theta * sign * leg.quantity
                agg.rho += leg.greeks.rho * sign * leg.quantity
        return agg
    
    def is_at_expiry(self, today: str) -> bool:
        """Check if any leg is at expiry today (DDMMMYY format)."""
        return any(leg.expiry == today for leg in self.legs)


@dataclass
class AdjustmentRequest:
    """Request to adjust an open options position."""
    position_id: str
    adjustment_type: AdjustmentType
    trigger_reason: str
    affected_legs: List[str]  # leg_ids to adjust
    new_strike: Optional[float] = None
    new_expiry: Optional[str] = None
    close_quantity: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    requested_at: datetime = field(default_factory=datetime.now)
    status: str = "PENDING"  # PENDING, APPROVED, REJECTED, EXECUTED
    approval_reason: Optional[str] = None
    execution_result: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Portfolio Tracking
# ---------------------------------------------------------------------------

@dataclass
class OptionsPortfolioSummary:
    """Snapshot of all open multi-leg positions."""
    total_positions: int = 0
    open_count: int = 0
    total_net_premium: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_realized_pnl: float = 0.0
    portfolio_greeks: Optional[Greeks] = None
    positions_by_structure: Dict[str, int] = field(default_factory=dict)
    expiring_today: List[str] = field(default_factory=list)  # position IDs
    requiring_adjustment: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Validation & SEBI Compliance
# ---------------------------------------------------------------------------

@dataclass
class OptionsValidationResult:
    """Result of SEBI options pre-trade validation."""
    is_valid: bool
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    position_counts: Dict[str, int] = field(default_factory=dict)  # Per-underlying lot counts
    margin_requirement: float = 0.0
    estimated_margin_available: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
