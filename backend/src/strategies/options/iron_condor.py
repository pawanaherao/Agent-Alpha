from typing import Optional, Dict, Any
import pandas as pd
from datetime import datetime

from src.strategies.base import BaseStrategy, StrategySignal

class IronCondorStrategy(BaseStrategy):
    """
    Iron Condor Strategy.
    Type: Options / Mean Reversion
    Logic: Sell OTM Call + Sell OTM Put (with hedges) when market is SIDEWAYS.
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("Iron_Condor_Sideways", config or {})

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        """
        High suitability in SIDEWAYS regimes.
        """
        score = 40.0
        
        if regime == "SIDEWAYS":
            score += 50.0
        elif regime == "VOLATILE":
            score -= 30.0 # Dangerous
            
        # B21 fix: VIX Check — handle DataFrame correctly
        vix = 14.0  # default
        if isinstance(market_data, pd.DataFrame):
            if 'vix' in market_data.columns:
                vix = float(market_data['vix'].iloc[-1])
        elif isinstance(market_data, dict):
            vix = market_data.get('vix', 14.0)
        if vix > 12:
            score += 10.0
            
        return min(score, 100.0)

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        # Only fires if score was high, which implies Sideays
        
        current_price = market_data['close'].iloc[-1]
        
        # Logic: Create a 4-legged structure
        # Simplified as a single "SELL" signal for the strategy wrapper to interpret
        
        return StrategySignal(
            signal_id=f"IC_{datetime.now().timestamp()}",
            strategy_name=self.name,
            symbol="BANKNIFTY", # Usually better premiums
            signal_type="SELL", # Selling the strategy (Credit)
            strength=0.75,
            market_regime_at_signal=regime,
            metadata={
                "strategy_type": "IRON_CONDOR",
                "legs": [
                    {"type": "CE", "action": "SELL", "strike": current_price * 1.02},
                    {"type": "PE", "action": "SELL", "strike": current_price * 0.98},
                    {"type": "CE", "action": "BUY", "strike": current_price * 1.04}, # Hedge
                    {"type": "PE", "action": "BUY", "strike": current_price * 0.96}  # Hedge
                ]
            }
        )
