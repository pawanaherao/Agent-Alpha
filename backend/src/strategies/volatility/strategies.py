from typing import Optional, Dict, Any
import pandas as pd
from src.strategies.base import BaseStrategy, StrategySignal

class LongStraddle(BaseStrategy):
    """
    14. Long Straddle
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_STRADDLE_014", config or {})

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        # High VIX expectation
        return 80.0 if regime == "VOLATILE" else 10.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        return None

class VIXTrading(BaseStrategy):
    """
    15. VIX Trading
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_VIX_015", config or {})

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        return 50.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        return None
