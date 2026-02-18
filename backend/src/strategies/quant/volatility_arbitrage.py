import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, Optional

from src.strategies.base import BaseStrategy, StrategySignal
from src.strategies.quant.vol_surface import VolSurfaceBuilder

logger = logging.getLogger(__name__)

class VolatilityArbitrageStrategy(BaseStrategy):
    """
    Volatility Arbitrage Strategy.
    
    Logic:
    1. Build Volatility Surface using VolSurfaceBuilder.
    2. Detect "expensive" options (IV > Model + Threshold).
    3. Detect "cheap" options (IV < Model - Threshold).
    4. Execution: Delta-Hedged Short/Long relative to surface.
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("VolatilityArbitrage", config or {})
        self.builder = VolSurfaceBuilder()
        self.iv_threshold = 0.02 # 2% IV deviation
        
    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        """
        Vol Arb works best in high volatility or earnings seasons.
        """
        suitability_map = {
            "VOLATILE": 95.0,
            "SIDEWAYS": 70.0, # Good for collecting premium
            "BULL": 50.0,
            "BEAR": 50.0
        }
        return suitability_map.get(regime, 60.0)

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        """
        Symbol-level check (e.g. NIFTY)
        """
        try:
            # We assume this is called for an Index or Liquid Stock
            symbol = self.config.get('symbol', 'NIFTY') 
            
            # 1. Build Surface
            self.builder.symbol = symbol
            anomalies = await self.builder.build_surface()
            
            if not anomalies:
                return None
                
            # 2. Pick best anomaly
            # For MVP, we just take the first significant one
            # In production, we'd rank by liquidity and edge
            best_opp = anomalies[0]
            
            signal_type = "SELL" if best_opp['type'] == 'expensive' else "BUY"
            
            return StrategySignal(
                signal_id=f"VOL_ARB_{int(pd.Timestamp.now().timestamp())}",
                strategy_name=self.name,
                symbol=best_opp['symbol'], # Likely an Option Contract Symbol
                signal_type=signal_type,
                strength=0.8,
                metadata={
                    "implied_vol": best_opp['market_iv'],
                    "theoretical_vol": best_opp['model_iv'],
                    "edge": best_opp['edge'],
                    "strike": best_opp['strike'],
                    "expiry": best_opp['expiry']
                }
            )

        except Exception as e:
            logger.debug(f"Vol Arb signal gen failed: {e}")
            return None
