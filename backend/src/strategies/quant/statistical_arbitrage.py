import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, Optional

from src.strategies.base import BaseStrategy, StrategySignal
from src.strategies.quant.pairs_finder import PairsFinder

logger = logging.getLogger(__name__)

class StatisticalArbitrageStrategy(BaseStrategy):
    """
    Statistical Arbitrage (Pairs Trading) Strategy.
    
    Logic:
    1. Scan for cointegrated pairs using PairsFinder (Engle-Granger).
    2. Monitor Z-Score of the spread (Stock A - HedgeRatio * Stock B).
    3. Signal Entry if Z-Score > 2 (Short Spread) or < -2 (Long Spread).
    4. Signal Exit if Z-Score reverts to 0.
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("StatisticalArbitrage", config or {})
        self.finder = PairsFinder() # Initialize engine
        self.z_entry = 2.0
        self.z_exit = 0.0
        self.lookback = "1y"
        
    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        """
        Pairs trading works best in SIDEWAYS or VOLATILE markets (Mean Reversion).
        Fails in strong trending markets where correlations break.
        """
        suitability_map = {
            "SIDEWAYS": 95.0,
            "VOLATILE": 85.0,
            "BULL": 40.0,
            "BEAR": 40.0
        }
        return suitability_map.get(regime, 50.0)

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        """
        Note: This strategy operates on PAIRS, not single stocks.
        The StrategyAgent usually calls this with single symbol data.
        
        For Phase 6, we implement a 'Discovery' mode where it runs the batch finder
        and returns a signal only if the current symbol is part of a mispriced pair.
        """
        # Complex logic: Check if current symbol is in active pairs list
        # For MVP, we defer the heavy lifting to a background task or portfolio manager
        return None 
        
    async def run_batch_analysis(self) -> list:
        """
        Primary execution method for this strategy.
        Returns a list of trade instructions For the Portfolio Manager.
        """
        try:
            # 1. Update Pairs (Re-scan daily/weekly)
            # In production, this would be cached
            pairs = await self.finder.find_pairs()
            
            signals = []
            
            # 2. Check Z-Score for each pair
            for pair in pairs:
                # We need live data for both stocks to calc z-score
                # This is a heavy operation, effectively done in finder for checks
                z_score = pair.get('z_score_current', 0)
                s1 = pair['stock1']
                s2 = pair['stock2']
                
                if z_score > self.z_entry:
                    # Short Spread: Sell S1, Buy S2
                    signals.append({
                        "type": "PAIR_TRADE",
                        "pair": f"{s1}-{s2}",
                        "action": "SHORT_SPREAD",
                        "legs": [
                            {"symbol": s1, "side": "SELL"},
                            {"symbol": s2, "side": "BUY", "ratio": pair['hedge_ratio']}
                        ],
                        "reason": f"Z-Score {z_score:.2f} > {self.z_entry}"
                    })
                elif z_score < -self.z_entry:
                    # Long Spread: Buy S1, Sell S2
                    signals.append({
                        "type": "PAIR_TRADE",
                        "pair": f"{s1}-{s2}",
                        "action": "LONG_SPREAD",
                        "legs": [
                            {"symbol": s1, "side": "BUY"},
                            {"symbol": s2, "side": "SELL", "ratio": pair['hedge_ratio']}
                        ],
                        "reason": f"Z-Score {z_score:.2f} < -{self.z_entry}"
                    })
                    
            return signals
            
        except Exception as e:
            logger.error(f"StatArb analysis failed: {e}")
            return []
