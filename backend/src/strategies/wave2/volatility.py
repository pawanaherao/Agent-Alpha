"""
Wave 2 Strategies - Volatility Based
Target Sharpe: 1.5+

Strategies:
1. ALPHA_ATR_207 - ATR Breakout
2. ALPHA_VOL_CRUSH_208 - Volatility Crush (Replaces Iron Condor concept)
"""

from typing import Optional, Dict, Any
import pandas as pd
import numpy as np
from datetime import datetime
import logging
import ta

from src.strategies.base import BaseStrategy, StrategySignal
from src.services.nse_data import nse_data_service

logger = logging.getLogger(__name__)


class ATRBreakoutStrategy(BaseStrategy):
    """
    ALPHA_ATR_207 - ATR Breakout Strategy
    
    WHITEBOX LOGIC:
    1. Buy when price breaks above: Previous Close + 1.5*ATR
    2. Sell when price breaks below: Previous Close - 1.5*ATR
    3. Trailing stop at 2*ATR
    4. Best in VOLATILE regime
    """
    
    STRATEGY_ID = "ALPHA_ATR_207"
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ATR_Breakout", config or {})
        
        self.atr_period = 14
        self.breakout_multiplier = 1.5
        self.stop_multiplier = 2.0
        self.target_multiplier = 3.0
        
        self.nse_service = nse_data_service
    
    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        score = 50.0
        if regime == "VOLATILE":
            score += 35.0
        elif regime in ["BULL", "BEAR"]:
            score += 20.0
        elif regime == "SIDEWAYS":
            score -= 10.0
        return min(100.0, max(0.0, score))
    
    async def generate_signal(
        self, 
        market_data: pd.DataFrame, 
        regime: str
    ) -> Optional[StrategySignal]:
        if market_data is None or market_data.empty:
            return None
        
        try:
            if len(market_data) < self.atr_period + 5:
                return None
            
            symbol = str(market_data.get('symbol', pd.Series(['UNKNOWN'])).iloc[-1])
            df = market_data.copy()
            
            # Calculate ATR
            df['atr'] = ta.volatility.average_true_range(
                df['high'], df['low'], df['close'], window=self.atr_period
            )
            
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            
            current_price = float(latest['close'])
            prev_close = float(prev['close'])
            atr = float(latest['atr'])
            
            upper_breakout = prev_close + (self.breakout_multiplier * atr)
            lower_breakout = prev_close - (self.breakout_multiplier * atr)
            
            signal_type = None
            
            if current_price > upper_breakout:
                signal_type = "BUY"
                stop_loss = current_price - (self.stop_multiplier * atr)
                target = current_price + (self.target_multiplier * atr)
            elif current_price < lower_breakout:
                signal_type = "SELL"
                stop_loss = current_price + (self.stop_multiplier * atr)
                target = current_price - (self.target_multiplier * atr)
            
            if signal_type is None:
                return None
            
            breakout_strength = abs(current_price - prev_close) / atr
            strength = 0.6 + min(0.3, breakout_strength / 3)
            
            return StrategySignal(
                signal_id=f"{self.STRATEGY_ID}_{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                strategy_name=self.name,
                symbol=symbol,
                signal_type=signal_type,
                strength=min(1.0, strength),
                market_regime_at_signal=regime,
                entry_price=current_price,
                stop_loss=stop_loss,
                target_price=target,
                metadata={
                    "strategy_id": self.STRATEGY_ID,
                    "atr": atr,
                    "breakout_level": upper_breakout if signal_type == "BUY" else lower_breakout,
                    "breakout_atr_multiple": breakout_strength,
                    "trailing_stop": True,
                    "sebi_algo_id": self.STRATEGY_ID
                }
            )
            
        except Exception as e:
            logger.error(f"ATR Breakout error: {e}")
            return None
    
    def get_strategy_info(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.STRATEGY_ID,
            "name": "ATR Breakout",
            "type": "VOLATILITY",
            "segment": "CASH/OPTIONS",
            "whitebox": True
        }


class VolatilityCrushStrategy(BaseStrategy):
    """
    ALPHA_VOL_CRUSH_208 - Volatility Crush Strategy
    
    REPLACES: Iron Condor (manipulated post Q3 2024)
    
    WHITEBOX LOGIC:
    1. Enter when VIX spikes >20
    2. Buy when VIX starts declining (mean reversion)
    3. Exit when VIX returns to normal (<15)
    4. Works because high VIX reverts to mean
    
    This is SIMPLER and less susceptible to manipulation than Iron Condor.
    """
    
    STRATEGY_ID = "ALPHA_VOL_CRUSH_208"
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("Volatility_Crush", config or {})
        
        self.vix_entry = 20.0  # Enter when VIX > 20
        self.vix_peak = 25.0   # VIX must have peaked above this
        self.vix_exit = 15.0   # Exit when VIX < 15
        
        self.nse_service = nse_data_service
    
    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        score = 40.0
        if regime == "VOLATILE":
            score += 40.0
        elif regime == "BEAR":
            score += 25.0
        return min(100.0, max(0.0, score))
    
    async def generate_signal(
        self, 
        market_data: pd.DataFrame, 
        regime: str
    ) -> Optional[StrategySignal]:
        if regime not in ["VOLATILE", "BEAR"]:
            return None
        
        try:
            # Get current VIX
            vix = await self.nse_service.get_india_vix()
            
            if vix is None or vix < self.vix_entry:
                return None
            
            # B17 fix: Check that VIX is actually declining (not just above threshold)
            # Use NIFTY data as proxy — if recent VIX was higher, we are on the decline
            try:
                vix_data = await self.nse_service.get_index_ohlc("INDIA VIX", "1M")
                if vix_data is not None and len(vix_data) >= 5:
                    recent_vix_high = float(vix_data['high'].iloc[-5:].max())
                    if vix < recent_vix_high * 0.95:  # VIX must be ≥5% below recent peak
                        logger.info(f"VIX declining: current {vix:.1f} < 5d high {recent_vix_high:.1f}")
                    else:
                        logger.debug(f"VIX {vix:.1f} not declining from peak {recent_vix_high:.1f}, skipping")
                        return None
            except Exception:
                # If VIX data unavailable, allow trade based on threshold alone
                pass
            
            # Get NIFTY data
            if market_data is None or market_data.empty:
                latest = await self.nse_service.get_latest_index_value("NIFTY 50")
                current_price = latest.get('ltp', 0)
            else:
                current_price = float(market_data['close'].iloc[-1])
            
            if current_price == 0:
                return None
            
            # VIX crush trade: Buy NIFTY when VIX is high and declining
            # This benefits from volatility normalization
            
            stop_loss = current_price * 0.95  # 5% stop
            target = current_price * 1.08  # 8% target
            
            # Calculate strength based on VIX level
            strength = 0.6 + min(0.3, (vix - 20) / 20)
            
            return StrategySignal(
                signal_id=f"{self.STRATEGY_ID}_NIFTY_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                strategy_name=self.name,
                symbol="NIFTY",
                signal_type="BUY",
                strength=min(1.0, strength),
                market_regime_at_signal=regime,
                entry_price=current_price,
                stop_loss=stop_loss,
                target_price=target,
                metadata={
                    "strategy_id": self.STRATEGY_ID,
                    "vix_at_entry": vix,
                    "vix_exit_target": self.vix_exit,
                    "trade_thesis": "VIX mean reversion - high VIX reverts to mean",
                    "replaces": "Iron Condor (ALPHA_IRON_011)",
                    "manipulation_resistant": True,
                    "sebi_algo_id": self.STRATEGY_ID
                }
            )
            
        except Exception as e:
            logger.error(f"Volatility Crush error: {e}")
            return None
    
    def get_strategy_info(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.STRATEGY_ID,
            "name": "Volatility Crush",
            "type": "VOLATILITY_MEAN_REVERSION",
            "segment": "OPTIONS/CASH",
            "whitebox": True,
            "replaces": "Iron Condor"
        }
