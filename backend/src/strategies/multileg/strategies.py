from typing import Optional, Dict, Any
import pandas as pd
from src.strategies.base import BaseStrategy, StrategySignal

class IronCondor(BaseStrategy):
    """
    11. Iron Condor
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_IRON_011", config or {})

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        return 95.0 if regime == "SIDEWAYS" else 10.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        return None

class ButterflySpread(BaseStrategy):
    """
    12. Butterfly Spread
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_BUTTERFLY_012", config or {})

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        return 85.0 if regime == "SIDEWAYS" else 10.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        return None

class LongStrangle(BaseStrategy):
    """
    13. Long Strangle
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_STRANGLE_013", config or {})

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        return 90.0 if regime == "VOLATILE" else 10.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        return None
