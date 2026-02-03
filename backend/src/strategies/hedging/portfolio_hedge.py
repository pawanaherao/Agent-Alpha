"""
ALPHA_PORT_017 - Portfolio Hedge Strategy
SEBI Compliant: WHITEBOX Strategy

Type: Protective Options
Holding: Active during BEAR/VOLATILE regimes
Expected: Reduces portfolio drawdown by 20-40%

WHITEBOX LOGIC:
1. Buy OTM NIFTY Puts as crash insurance
2. Activate when VIX spikes or regime turns BEAR
3. Hedge 20-30% of portfolio value
4. Cost: 1-2% of portfolio annually
"""

from typing import Optional, Dict, Any
import pandas as pd
from datetime import datetime
import logging

from src.strategies.base import BaseStrategy, StrategySignal
from src.services.nse_data import nse_data_service

logger = logging.getLogger(__name__)


class PortfolioHedgeStrategy(BaseStrategy):
    """
    Portfolio Hedge using Index Puts.
    
    SEBI Whitebox Classification:
    - Strategy ID: ALPHA_PORT_017
    - Type: Protective/Hedging
    - Instrument: NIFTY Put Options
    - Risk Category: Low (insurance)
    
    HEDGE STRUCTURE:
    - Buy OTM NIFTY Put (5-10% OTM)
    - Expiry: 1-3 months out (cheaper theta)
    - Quantity: Hedge 20-30% of portfolio notional
    
    ACTIVATION RULES:
    1. VIX > 18: Start hedging
    2. Regime BEAR: Increase hedge
    3. VIX > 25: Full hedge deployed
    4. BULL/SIDEWAYS: Reduce or remove hedge
    """
    
    STRATEGY_ID = "ALPHA_PORT_017"
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("Portfolio_Hedge", config or {})
        
        # Hedge configuration
        self.otm_distance_pct = 5.0  # 5% OTM puts
        self.hedge_ratio_normal = 0.20  # 20% hedge in normal times
        self.hedge_ratio_high = 0.30    # 30% hedge when VIX high
        
        # VIX thresholds
        self.vix_activate = 18.0  # Start hedging
        self.vix_increase = 22.0  # Increase hedge
        self.vix_full = 25.0      # Full hedge
        
        # Cost budget (% of portfolio per year)
        self.max_hedge_cost_pct = 2.0
        
        self.nse_service = nse_data_service
        
        logger.info(f"Portfolio Hedge initialized: {self.STRATEGY_ID}")
    
    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        """
        Hedge suitability based on regime and VIX.
        
        WHITEBOX SCORING:
        - BEAR regime: 90 points (need protection)
        - VOLATILE: 80 points  
        - High VIX (>20): +20 points
        - BULL: 30 points (hedge costs money)
        - SIDEWAYS: 40 points
        """
        score = 30.0  # Base (hedging has cost)
        
        if regime == "BEAR":
            score = 90.0
        elif regime == "VOLATILE":
            score = 80.0
        elif regime == "SIDEWAYS":
            score = 40.0
        elif regime == "BULL":
            score = 30.0  # Low priority but still valid
        
        # VIX adjustment
        try:
            vix = await self.nse_service.get_india_vix()
            if vix >= self.vix_full:
                score = min(100.0, score + 30.0)
            elif vix >= self.vix_increase:
                score += 20.0
            elif vix >= self.vix_activate:
                score += 10.0
        except:
            pass
        
        return max(0.0, min(score, 100.0))
    
    async def generate_signal(
        self, 
        market_data: pd.DataFrame, 
        regime: str
    ) -> Optional[StrategySignal]:
        """Generate hedge signal based on market conditions."""
        
        # Get VIX
        try:
            vix = await self.nse_service.get_india_vix()
        except:
            vix = 15.0
        
        # Determine hedge level
        if vix < self.vix_activate and regime not in ["BEAR", "VOLATILE"]:
            logger.debug(f"No hedge needed: VIX={vix:.1f}, Regime={regime}")
            return None
        
        # Get spot price
        try:
            latest = await self.nse_service.get_latest_index_value("NIFTY 50")
            spot_price = latest.get('ltp', 0)
        except:
            if market_data is not None and not market_data.empty:
                spot_price = float(market_data['close'].iloc[-1])
            else:
                return None
        
        if spot_price == 0:
            return None
        
        # Calculate hedge ratio
        if vix >= self.vix_full or regime == "BEAR":
            hedge_ratio = self.hedge_ratio_high
        else:
            hedge_ratio = self.hedge_ratio_normal
        
        # Calculate put strike (OTM)
        otm_strike = round((spot_price * (1 - self.otm_distance_pct/100)) / 50) * 50
        
        # Estimate put premium (simplified)
        put_premium = max(20, (spot_price - otm_strike) * 0.05 + 50)
        
        # Calculate protection value
        protection_start = otm_strike
        protection_end = 0  # Full protection below strike
        
        strength = 0.6
        if regime == "BEAR":
            strength += 0.2
        if vix > 20:
            strength += 0.15
        
        signal = StrategySignal(
            signal_id=f"{self.STRATEGY_ID}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            strategy_name=self.name,
            symbol="NIFTY",
            signal_type="HEDGE_PUT",
            strength=min(strength, 1.0),
            market_regime_at_signal=regime,
            entry_price=spot_price,
            stop_loss=put_premium,  # Max loss is premium
            target_price=protection_start,
            metadata={
                "strategy_id": self.STRATEGY_ID,
                "hedge_type": "PROTECTIVE_PUT",
                "action": "BUY",
                "option_type": "PE",
                "strike": otm_strike,
                "premium": put_premium,
                "otm_distance_pct": self.otm_distance_pct,
                "hedge_ratio": hedge_ratio,
                "protection_level": f"Below {otm_strike}",
                "vix_at_entry": vix,
                "rationale": f"Portfolio hedge at {hedge_ratio*100:.0f}% due to VIX={vix:.1f} and {regime} regime",
                "sebi_algo_id": self.STRATEGY_ID
            }
        )
        
        logger.info(
            f"Hedge Signal: Buy {otm_strike}PE @ {put_premium} | "
            f"VIX={vix:.1f}, Regime={regime}, Hedge={hedge_ratio*100:.0f}%"
        )
        
        return signal
    
    def get_strategy_info(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.STRATEGY_ID,
            "name": "Portfolio Hedge",
            "type": "PROTECTIVE_PUT",
            "instrument": "INDEX_OPTIONS",
            "risk_category": "LOW",
            "whitebox": True,
            "parameters": {
                "otm_distance_pct": self.otm_distance_pct,
                "hedge_ratio_normal": f"{self.hedge_ratio_normal * 100}%",
                "hedge_ratio_high": f"{self.hedge_ratio_high * 100}%",
                "vix_activate": self.vix_activate,
                "vix_increase": self.vix_increase,
                "vix_full": self.vix_full
            }
        }
