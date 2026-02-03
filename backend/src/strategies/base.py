from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
import pandas as pd
import logging

logger = logging.getLogger(__name__)

class StrategySignal(BaseModel):
    """
    Standard output from any strategy.
    """
    signal_id: str = Field(..., description="Unique ID for this signal event")
    strategy_name: str
    symbol: str
    signal_type: str  # BUY, SELL, HOLD
    strength: float = Field(0.0, ge=0.0, le=1.0, description="Confidence score")
    
    # Execution details
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None
    quantity: int = 1
    
    # Metadata
    timestamp: datetime = Field(default_factory=datetime.now)
    market_regime_at_signal: str  # BULL, BEAR, SIDEWAYS
    metadata: Dict[str, Any] = {}

class BaseStrategy(ABC):
    """
    Abstract Base Class for all Trading Strategies.
    Enforces the 'Dynamic Strategy' interface.
    """
    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.config = config
        self.logger = logging.getLogger(f"strategy.{name}")

    @abstractmethod
    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        """
        Dynamic Selection Logic:
        Returns a score (0.0 - 100.0) indicating how well this strategy 
        fits the CURRENT market conditions.
        
        Args:
            market_data: OHLCV data + indicators
            regime: Current market state (BULL, BEAR, SIDEWAYS, VOLATILE)
        """
        pass

    @abstractmethod
    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        """
        Core Trading Logic:
        Analyzes data and returns a Signal object if entry criteria are met.
        """
        pass

    def backtest(self, data: pd.DataFrame) -> Dict[str, Any]:
        """
        Run vectorbt backtest on historical data.
        Optional override for complex strategies.
        """
        self.logger.warning(f"{self.name} has not implemented backtest logic.")
        return {}
