"""Strategy Agent Factory - Initialize all Wave 1 & Wave 2 Strategies
Total: 15 Active Strategies (Iron Condor REMOVED per SEBI compliance)

Wave 1 (7): ORB, VWAP, Bull Call Spread, Swing Breakout, Pullback, EMA Cross, Portfolio Hedge
Wave 2 (8): Momentum Rotation, Sector Rotation, BB Squeeze, RSI Divergence, Earnings Mom, Gap Fill, ATR Breakout, Vol Crush

SEBI COMPLIANCE NOTE (Jan 2026):
- Iron Condor REMOVED: Same structure used in Jane Street manipulation (SEBI ban Jul 2025)
- Options strategies have expiry-day safeguards
- All strategies have position limits
"""

from typing import Dict, Any
from src.agents.strategy import StrategyAgent

# Wave 1 Strategies
from src.strategies.momentum.orb import ORBStrategy

# Wave 3 / Phase 6 Strategies (imported here for the factory)
try:
    from src.strategies.quant.statistical_arbitrage import StatisticalArbitrageStrategy
    from src.strategies.quant.volatility_arbitrage import VolatilityArbitrageStrategy
    from src.strategies.quant.momentum import CrossSectionalMomentumStrategy
except ImportError:
    StatisticalArbitrageStrategy = None
    VolatilityArbitrageStrategy = None
    CrossSectionalMomentumStrategy = None

try:
    from src.strategies.universal_strategy import UniversalStrategy
except ImportError:
    UniversalStrategy = None
from src.strategies.multileg.iron_condor import IronCondorStrategy
from src.strategies.mean_reversion.vwap import VWAPReversionStrategy
from src.strategies.spreads.bull_call_spread import BullCallSpreadStrategy
from src.strategies.swing.breakout import SwingBreakoutStrategy
from src.strategies.swing.pullback import TrendPullbackStrategy
from src.strategies.swing.ema_crossover import EMACrossoverStrategy
from src.strategies.hedging.portfolio_hedge import PortfolioHedgeStrategy

# Wave 2 Strategies
from src.strategies.wave2.momentum import MomentumRotationStrategy, SectorRotationStrategy
from src.strategies.wave2.mean_reversion import BBSqueezeStrategy, RSIDivergenceStrategy
from src.strategies.wave2.event_driven import EarningsMomentumStrategy, GapFillStrategy
from src.strategies.wave2.volatility import ATRBreakoutStrategy, VolatilityCrushStrategy

# Legacy strategies (keeping for comparison)
from src.strategies.directional.strategies import (
    VWAPBounceStrategy, TrendFollowingStrategy, 
    OrderFlowStrategy, SentimentDivergenceStrategy
)
from src.strategies.spreads.strategies import BearPutSpread
from src.strategies.multileg.strategies import ButterflySpread, LongStrangle
from src.strategies.volatility.strategies import LongStraddle, VIXTrading


async def initialize_strategy_agent(config: Dict[str, Any]) -> StrategyAgent:
    """
    Factory function to create StrategyAgent with all strategies.
    
    MEDALLION-LEVEL CONFIGURATION:
    - Primary (Wave 1 + Wave 2): 16 strategies
    - Legacy (for comparison): Additional strategies
    """
    agent = StrategyAgent("StrategyAgent", config)
    
    # === WAVE 1 STRATEGIES (8) ===
    
    # 1. ORB - Options Intraday Momentum
    await agent.register_strategy(ORBStrategy())
    
    # 2. Iron Condor - DISABLED (SEBI Manipulation Risk)
    # Same structure as Jane Street manipulation (banned Jul 2025)
    # await agent.register_strategy(IronCondorStrategy())  # REMOVED
    
    # 3. VWAP Mean Reversion - TOP PERFORMER (Sharpe 10.74)
    await agent.register_strategy(VWAPReversionStrategy())
    
    # 4. Bull Call Spread - Directional
    await agent.register_strategy(BullCallSpreadStrategy())
    
    # 5. Swing Breakout - Cash
    await agent.register_strategy(SwingBreakoutStrategy())
    
    # 6. Trend Pullback - Cash
    await agent.register_strategy(TrendPullbackStrategy())
    
    # 7. EMA Crossover - Cash
    await agent.register_strategy(EMACrossoverStrategy())
    
    # 8. Portfolio Hedge - Protective
    await agent.register_strategy(PortfolioHedgeStrategy())
    
    # === WAVE 2 STRATEGIES (8) ===
    
    # 9. Momentum Rotation
    await agent.register_strategy(MomentumRotationStrategy())
    
    # 10. Sector Rotation
    await agent.register_strategy(SectorRotationStrategy())
    
    # 11. Bollinger Band Squeeze
    await agent.register_strategy(BBSqueezeStrategy())
    
    # 12. RSI Divergence
    await agent.register_strategy(RSIDivergenceStrategy())
    
    # 13. Earnings Momentum
    await agent.register_strategy(EarningsMomentumStrategy())
    
    # 14. Gap Fill
    await agent.register_strategy(GapFillStrategy())
    
    # 15. ATR Breakout
    await agent.register_strategy(ATRBreakoutStrategy())
    
    # 16. Volatility Crush (Replaces Iron Condor risk)
    await agent.register_strategy(VolatilityCrushStrategy())
    
    # === WAVE 3 STRATEGIES (Phase 6 - Institutional) ===

    # 17-20. Optional Wave 3 / Universal strategies
    if StatisticalArbitrageStrategy is not None:
        await agent.register_strategy(StatisticalArbitrageStrategy())
    if VolatilityArbitrageStrategy is not None:
        await agent.register_strategy(VolatilityArbitrageStrategy())
    if CrossSectionalMomentumStrategy is not None:
        await agent.register_strategy(CrossSectionalMomentumStrategy())
    if UniversalStrategy is not None:
        # ── Equity mode (explicit config — avoids defaulting to empty dict) ──
        equity_strategy = UniversalStrategy({
            "mode": "equity",
            "stop_loss_pct": 1.5,
            "take_profit_pct": 3.0,
        })
        equity_strategy.name = "UniversalStrategy_Equity"
        await agent.register_strategy(equity_strategy)

        # ── Options mode instances (one per supported structure) ──
        # Each gets regime-context and structure at scan time via chain_data injection.
        options_configs = [
            {
                "strategy_name": "UniversalStrategy_BullCallSpread",
                "mode": "options",
                "structure": "BULL_CALL_SPREAD",
                "options_config": {
                    "wing_width": 100,   # strike distance in rupees
                    "short_delta": 0.35,
                    "expiry_type": "WEEKLY",
                },
            },
            {
                "strategy_name": "UniversalStrategy_BearPutSpread",
                "mode": "options",
                "structure": "BEAR_PUT_SPREAD",
                "options_config": {
                    "wing_width": 100,
                    "short_delta": 0.35,
                    "expiry_type": "WEEKLY",
                },
            },
            {
                "strategy_name": "UniversalStrategy_Straddle",
                "mode": "options",
                "structure": "STRADDLE",
                "options_config": {
                    "expiry_type": "WEEKLY",
                },
            },
        ]
        for ocfg in options_configs:
            strat = UniversalStrategy(ocfg)
            strat.name = ocfg["strategy_name"]
            await agent.register_strategy(strat)
    
    # === LEGACY (For Comparison) ===
    await agent.register_strategy(VWAPBounceStrategy())
    await agent.register_strategy(TrendFollowingStrategy())
    await agent.register_strategy(BearPutSpread())
    await agent.register_strategy(ButterflySpread())
    await agent.register_strategy(LongStrangle())
    await agent.register_strategy(LongStraddle())
    await agent.register_strategy(VIXTrading())
    
    return agent


def get_all_strategy_ids():
    """Return all strategy IDs for backtesting."""
    return {
        # Wave 1
        "ALPHA_ORB_001": "ORB Strategy",
        # "ALPHA_IRON_011": "Iron Condor",  # REMOVED - SEBI manipulation risk
        "ALPHA_VWAP_002": "VWAP Mean Reversion",
        "ALPHA_BCS_007": "Bull Call Spread",
        "ALPHA_BREAKOUT_101": "Swing Breakout",
        "ALPHA_PULLBACK_102": "Trend Pullback",
        "ALPHA_EMA_CROSS_104": "EMA Crossover",
        "ALPHA_PORT_017": "Portfolio Hedge",
        
        # Wave 2
        "ALPHA_MOMENTUM_201": "Momentum Rotation",
        "ALPHA_SECTOR_202": "Sector Rotation",
        "ALPHA_BB_203": "BB Squeeze",
        "ALPHA_RSI_DIV_204": "RSI Divergence",
        "ALPHA_EARN_205": "Earnings Momentum",
        "ALPHA_GAP_206": "Gap Fill",
        "ALPHA_ATR_207": "ATR Breakout",
        "ALPHA_VOL_CRUSH_208": "Volatility Crush",
    }
