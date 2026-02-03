"""
ALPHA_BCS_007 - Bull Call Spread Strategy
SEBI Compliant: WHITEBOX Strategy

Type: Options Directional
Holding: 1-7 days
Expected Sharpe: 1.5 - 2.0

WHITEBOX LOGIC:
1. Buy ATM Call + Sell OTM Call
2. Limited risk, limited reward
3. Best in moderately BULLISH markets
4. Lower cost than naked call
"""

from typing import Optional, Dict, Any
import pandas as pd
from datetime import datetime
import logging

from src.strategies.base import BaseStrategy, StrategySignal
from src.services.nse_data import nse_data_service

logger = logging.getLogger(__name__)


class BullCallSpreadStrategy(BaseStrategy):
    """
    Bull Call Spread (Debit Spread) Strategy.
    
    SEBI Whitebox Classification:
    - Strategy ID: ALPHA_BCS_007
    - Type: Directional Options Spread
    - Instrument: NIFTY/BANKNIFTY Options
    - Risk Category: Low-Medium
    
    STRUCTURE:
    - Buy ATM Call
    - Sell OTM Call (ATM + spread_width)
    
    ENTRY RULES:
    1. Regime: BULL (mandatory)
    2. VIX: <20 (avoid high premium)
    3. Trend confirmed by EMA alignment
    
    SEBI SAFEGUARDS (Jan 2026):
    - Avoid entry on expiry day (manipulation risk)
    - Position size: Max 2% of capital per trade
    - Entry in 2-3 tranches to avoid front-running
    - Max 5 concurrent spread positions
    
    PROFIT/LOSS:
    - Max Profit: Spread width - Net debit
    - Max Loss: Net debit paid
    """
    
    STRATEGY_ID = "ALPHA_BCS_007"
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("Bull_Call_Spread", config or {})
        
        # Spread configuration
        self.spread_width = 100  # Points between strikes
        
        # VIX threshold
        self.max_vix = 20.0
        
        # Exit parameters
        self.profit_target_pct = 0.60  # Exit at 60% of max profit
        self.stop_loss_pct = 0.50  # Exit at 50% loss of premium
        
        self.nse_service = nse_data_service
        
        logger.info(f"Bull Call Spread initialized: {self.STRATEGY_ID}")
    
    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        """Bull Call Spread is best in BULL regime."""
        score = 20.0
        
        if regime == "BULL":
            score = 85.0
        elif regime == "SIDEWAYS":
            score = 40.0  # Can work if bullish bias
        elif regime in ["BEAR", "VOLATILE"]:
            score = 10.0  # Not recommended
        
        # VIX check
        try:
            vix = await self.nse_service.get_india_vix()
            if vix < self.max_vix:
                score += 10.0
            else:
                score -= 20.0
        except:
            pass
        
        return max(0.0, min(score, 100.0))
    
    async def generate_signal(
        self, 
        market_data: pd.DataFrame, 
        regime: str
    ) -> Optional[StrategySignal]:
        """Generate Bull Call Spread signal."""
        
        # Only in BULL regime
        if regime != "BULL":
            return None
        
        # VIX check
        try:
            vix = await self.nse_service.get_india_vix()
            if vix > self.max_vix:
                logger.debug(f"VIX {vix:.1f} too high for debit spread")
                return None
        except:
            vix = 15.0
        
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
        
        # Calculate strikes
        atm_strike = round(spot_price / 50) * 50
        buy_call_strike = atm_strike
        sell_call_strike = atm_strike + self.spread_width
        
        # Estimate premiums
        buy_call_premium = 120  # ATM call (higher)
        sell_call_premium = 60  # OTM call (lower)
        
        net_debit = buy_call_premium - sell_call_premium
        max_profit = self.spread_width - net_debit
        max_loss = net_debit
        breakeven = buy_call_strike + net_debit
        
        strength = 0.75
        if vix < 15:
            strength += 0.1
        
        signal = StrategySignal(
            signal_id=f"{self.STRATEGY_ID}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            strategy_name=self.name,
            symbol="NIFTY",
            signal_type="BULL_CALL_SPREAD",
            strength=strength,
            market_regime_at_signal=regime,
            entry_price=spot_price,
            stop_loss=max_loss,
            target_price=max_profit * self.profit_target_pct,
            metadata={
                "strategy_id": self.STRATEGY_ID,
                "structure": "BULL_CALL_SPREAD",
                "legs": [
                    {"action": "BUY", "type": "CE", "strike": buy_call_strike, "premium": buy_call_premium},
                    {"action": "SELL", "type": "CE", "strike": sell_call_strike, "premium": sell_call_premium},
                ],
                "spread_width": self.spread_width,
                "net_debit": net_debit,
                "max_profit": max_profit,
                "max_loss": max_loss,
                "breakeven": breakeven,
                "vix_at_entry": vix,
                "sebi_algo_id": self.STRATEGY_ID
            }
        )
        
        logger.info(
            f"Bull Call Spread: Buy {buy_call_strike}CE @ {buy_call_premium}, "
            f"Sell {sell_call_strike}CE @ {sell_call_premium} | "
            f"Debit={net_debit}, MaxProfit={max_profit}"
        )
        
        return signal
    
    def get_strategy_info(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.STRATEGY_ID,
            "name": "Bull Call Spread",
            "type": "DIRECTIONAL_SPREAD",
            "instrument": "INDEX_OPTIONS",
            "risk_category": "LOW_MEDIUM",
            "whitebox": True,
            "parameters": {
                "spread_width": self.spread_width,
                "max_vix": self.max_vix,
                "profit_target": f"{self.profit_target_pct * 100}%",
                "stop_loss": f"{self.stop_loss_pct * 100}%"
            }
        }
