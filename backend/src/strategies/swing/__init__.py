"""
Swing Trading Strategies for Cash/Spot Segment
SEBI Compliant: WHITEBOX strategies for equity delivery

Strategies included:
- ALPHA_BREAKOUT_101: Swing Breakout (20-day high breakout)
- ALPHA_PULLBACK_102: Trend Pullback (EMA pullback in uptrend)
- ALPHA_EMA_CROSS_104: EMA Crossover (9/21 EMA cross)
"""

from src.strategies.swing.breakout import SwingBreakoutStrategy
from src.strategies.swing.pullback import TrendPullbackStrategy
from src.strategies.swing.ema_crossover import EMACrossoverStrategy

__all__ = [
    "SwingBreakoutStrategy",
    "TrendPullbackStrategy",
    "EMACrossoverStrategy"
]
