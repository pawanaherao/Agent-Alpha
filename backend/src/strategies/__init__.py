"""
Agentic Alpha Trading Strategies.
All 25 strategies organized by category.
"""

# ============================================================================
# BASE CLASSES & CORE
# ============================================================================
from .base import BaseStrategy, StrategySignal
from .universal_strategy import UniversalStrategy

# ============================================================================
# DIRECTIONAL STRATEGIES (Trend Following)
# ============================================================================
try:
    from .directional.strategies import (
        ORBStrategy,
        VWAPBounceStrategy,
        TrendFollowingStrategy,
        OrderFlowStrategy
    )
except ImportError:
    pass

# ============================================================================
# SWING TRADING STRATEGIES
# ============================================================================
from .swing.breakout import SwingBreakoutStrategy
from .swing.ema_crossover import EMACrossoverStrategy
try:
    from .swing.pullback import TrendPullbackStrategy
    PullbackStrategy = TrendPullbackStrategy
except ImportError:
    pass

# ============================================================================
# INTRADAY MOMENTUM STRATEGIES
# ============================================================================
from .momentum.orb import ORBStrategy as ORBMomentumStrategy
from .mean_reversion.vwap import VWAPReversionStrategy

# ============================================================================
# MULTI-LEG OPTIONS STRATEGIES
# ============================================================================
try:
    from .multileg.strategies import (
        IronCondor,
        ButterflySpread,
        LongStrangle
    )
except ImportError:
    pass

# ============================================================================
# SPREAD STRATEGIES
# ============================================================================
try:
    from .spreads.strategies import (
        BullCallSpread,
        BearPutSpread,
        RatioSpread,
        CalendarSpread
    )
except ImportError:
    pass

# ============================================================================
# OPTIONS & VOLATILITY STRATEGIES
# ============================================================================
try:
    from .options.iron_condor import IronCondorStrategy
except ImportError:
    pass

try:
    from .volatility.strategies import (
        LongStraddle,
        VIXTrading
    )
except ImportError:
    pass

# ============================================================================
# HEDGING STRATEGIES
# ============================================================================
try:
    from .hedging.strategies import (
        DeltaHedging,
        PortfolioHedge,
        PairTrading
    )
except ImportError:
    pass

# ============================================================================
# QUANTITATIVE/STATISTICAL STRATEGIES
# ============================================================================
try:
    from .quant.momentum import CrossSectionalMomentumStrategy
    from .quant.volatility_arbitrage import VolatilityArbitrageStrategy
    from .quant.pairs_finder import PairsFinder
except ImportError:
    pass

# ============================================================================
# WAVE 2 STRATEGIES (Advanced)
# ============================================================================
try:
    from .wave2.event_driven import (
        EarningsMomentumStrategy,
        GapFillStrategy
    )
except ImportError:
    pass

try:
    from .wave2.momentum import (
        MomentumRotationStrategy,
        SectorRotationStrategy
    )
except ImportError:
    pass

# ============================================================================
# STRATEGY REGISTRY
# ============================================================================
# Dictionary of all available strategies for dynamic loading
_STRATEGY_REGISTRY_CANDIDATES = {
    # Directional (4)
    "ORB": globals().get("ORBMomentumStrategy"),
    "VWAPBounce": globals().get("VWAPBounceStrategy"),
    "TrendFollowing": globals().get("TrendFollowingStrategy"),
    "OrderFlow": globals().get("OrderFlowStrategy"),

    # Swing (3)
    "SwingBreakout": globals().get("SwingBreakoutStrategy"),
    "EMACrossover": globals().get("EMACrossoverStrategy"),
    "Pullback": globals().get("PullbackStrategy"),

    # Intraday (2)
    "ORBIntraday": globals().get("ORBMomentumStrategy"),
    "VWAPReversion": globals().get("VWAPReversionStrategy"),

    # Multi-Leg (3)
    "IronCondor": globals().get("IronCondor"),
    "Butterfly": globals().get("ButterflySpread"),
    "LongStrangle": globals().get("LongStrangle"),

    # Spreads (4)
    "BullCallSpread": globals().get("BullCallSpread"),
    "BearPutSpread": globals().get("BearPutSpread"),
    "RatioSpread": globals().get("RatioSpread"),
    "CalendarSpread": globals().get("CalendarSpread"),

    # Volatility (2)
    "LongStraddle": globals().get("LongStraddle"),
    "VIXTrading": globals().get("VIXTrading"),

    # Hedging (3)
    "DeltaHedging": globals().get("DeltaHedging"),
    "PortfolioHedge": globals().get("PortfolioHedge"),
    "PairTrading": globals().get("PairTrading"),

    # Quant (3)
    "CrossSectionalMomentum": globals().get("CrossSectionalMomentumStrategy"),
    "VolatilityArbitrage": globals().get("VolatilityArbitrageStrategy"),
    "PairsFinder": globals().get("PairsFinder"),

    # Wave 2 (4)
    "EarningsMomentum": globals().get("EarningsMomentumStrategy"),
    "GapFill": globals().get("GapFillStrategy"),
    "MomentumRotation": globals().get("MomentumRotationStrategy"),
    "SectorRotation": globals().get("SectorRotationStrategy"),

    # Core (1)
    "Universal": globals().get("UniversalStrategy"),
}

STRATEGY_REGISTRY = {
    key: strategy
    for key, strategy in _STRATEGY_REGISTRY_CANDIDATES.items()
    if strategy is not None
}

# ============================================================================
# EXPORTS
# ============================================================================
__all__ = [
    # Base
    "BaseStrategy",
    "StrategySignal",
    "UniversalStrategy",
    
    # Directional
    "ORBStrategy",
    "VWAPBounceStrategy",
    "TrendFollowingStrategy",
    "OrderFlowStrategy",
    
    # Swing
    "SwingBreakoutStrategy",
    "EMACrossoverStrategy",
    "PullbackStrategy",
    
    # Intraday/Momentum
    "ORBMomentumStrategy",
    "VWAPReversionStrategy",
    
    # Multi-Leg
    "IronCondor",
    "ButterflySpread",
    "LongStrangle",
    
    # Spreads
    "BullCallSpread",
    "BearPutSpread",
    "RatioSpread",
    "CalendarSpread",
    
    # Volatility
    "LongStraddle",
    "VIXTrading",
    
    # Hedging
    "DeltaHedging",
    "PortfolioHedge",
    "PairTrading",
    
    # Quant
    "CrossSectionalMomentumStrategy",
    "VolatilityArbitrageStrategy",
    "PairsFinder",
    
    # Wave 2
    "EarningsMomentumStrategy",
    "GapFillStrategy",
    "MomentumRotationStrategy",
    "SectorRotationStrategy",
    
    # Utilities
    "STRATEGY_REGISTRY",
]
