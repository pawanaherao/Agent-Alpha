from typing import Optional, Dict, Any
import pandas as pd
from src.strategies.base import BaseStrategy, StrategySignal

class BullCallSpread(BaseStrategy):
    """
    7. Bull Call Spread
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_BCS_007", config or {})

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        return 90.0 if regime == "BULL" else 10.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        return None

class BearPutSpread(BaseStrategy):
    """
    8. Bear Put Spread
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_BPS_008", config or {})

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        return 90.0 if regime == "BEAR" else 10.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        return None

class RatioSpread(BaseStrategy):
    """
    9. Ratio Spread
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_RATIO_009", config or {})

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        return 70.0 if regime == "SIDEWAYS" else 30.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        return None

class CalendarSpread(BaseStrategy):
    """
    10. Calendar Spread
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_CALENDAR_010", config or {})

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        # Good for low IV environments anticipating IV rise
        return 60.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        return None
