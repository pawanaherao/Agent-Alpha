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
    from .swing.pullback import PullbackStrategy
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
STRATEGY_REGISTRY = {
    # Directional (4)
    "ORB": ORBMomentumStrategy,
    "VWAPBounce": VWAPBounceStrategy,
    "TrendFollowing": TrendFollowingStrategy,
    "OrderFlow": OrderFlowStrategy,
    
    # Swing (3)
    "SwingBreakout": SwingBreakoutStrategy,
    "EMACrossover": EMACrossoverStrategy,
    "Pullback": PullbackStrategy,
    
    # Intraday (2)
    "ORBIntraday": ORBMomentumStrategy,
    "VWAPReversion": VWAPReversionStrategy,
    
    # Multi-Leg (3)
    "IronCondor": IronCondor,
    "Butterfly": ButterflySpread,
    "LongStrangle": LongStrangle,
    
    # Spreads (4)
    "BullCallSpread": BullCallSpread,
    "BearPutSpread": BearPutSpread,
    "RatioSpread": RatioSpread,
    "CalendarSpread": CalendarSpread,
    
    # Volatility (2)
    "LongStraddle": LongStraddle,
    "VIXTrading": VIXTrading,
    
    # Hedging (3)
    "DeltaHedging": DeltaHedging,
    "PortfolioHedge": PortfolioHedge,
    "PairTrading": PairTrading,
    
    # Quant (3)
    "CrossSectionalMomentum": CrossSectionalMomentumStrategy,
    "VolatilityArbitrage": VolatilityArbitrageStrategy,
    "PairsFinder": PairsFinder,
    
    # Wave 2 (4)
    "EarningsMomentum": EarningsMomentumStrategy,
    "GapFill": GapFillStrategy,
    "MomentumRotation": MomentumRotationStrategy,
    "SectorRotation": SectorRotationStrategy,
    
    # Core (1)
    "Universal": UniversalStrategy,
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
