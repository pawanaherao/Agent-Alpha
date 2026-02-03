"""
Regime Agent - Market Regime Classification
SEBI Compliant: Whitebox logic with transparent rules

Classifies market into: BULL, BEAR, SIDEWAYS, VOLATILE
Based on: ADX (trend strength), EMA alignment, RSI, VIX
"""

from typing import Dict, Any, Optional
import pandas as pd
import ta
from datetime import datetime

from src.agents.base import BaseAgent
from src.core.config import settings
from src.services.nse_data import nse_data_service


class RegimeAgent(BaseAgent):
    """
    Agent responsible for classifying Market Regime.
    
    WHITEBOX LOGIC (SEBI Compliant):
    - Uses ADX for trend strength
    - Uses EMA(20,50) alignment for trend direction
    - Uses RSI for momentum
    - Uses VIX for volatility context
    
    OUTPUTS:
    - BULL: Strong uptrend (ADX>25, Price>EMA20>EMA50)
    - BEAR: Strong downtrend (ADX>25, Price<EMA20<EMA50)
    - SIDEWAYS: No clear trend (ADX<25, RSI between 40-60)
    - VOLATILE: High uncertainty (VIX>20 or mixed signals)
    """
    
    def __init__(self, name: str = "RegimeAgent", config: Dict[str, Any] = None):
        super().__init__(name, config)
        self.current_regime = "SIDEWAYS"
        self.current_vix = 15.0
        self.nse_service = nse_data_service
    
    async def analyze_with_real_data(self, index: str = "NIFTY 50") -> str:
        """
        Classify regime using REAL NSE data.
        
        Args:
            index: Index to analyze (default NIFTY 50)
            
        Returns:
            Regime string: BULL, BEAR, SIDEWAYS, VOLATILE
        """
        try:
            # 1. Fetch real data from NSE
            self.logger.info(f"Fetching real data for {index}...")
            df = await self.nse_service.get_index_ohlc(index, period="3M")
            
            if df.empty:
                self.logger.warning("No data received from NSE, using fallback")
                return self.current_regime
            
            # 2. Get VIX for volatility context
            try:
                self.current_vix = await self.nse_service.get_india_vix()
            except:
                self.current_vix = 15.0  # Default
            
            # 3. Classify regime
            regime = await self.classify_regime(df)
            
            self.logger.info(f"Regime: {regime}, VIX: {self.current_vix:.2f}")
            return regime
            
        except Exception as e:
            self.logger.error(f"Real data analysis failed: {e}")
            return self.current_regime
    
    async def classify_regime(self, market_data: pd.DataFrame) -> str:
        """
        Classify the current market regime based on technical indicators.
        
        WHITEBOX RULES:
        1. ADX > 25 = Trending market
        2. Price > EMA20 > EMA50 = BULL
        3. Price < EMA20 < EMA50 = BEAR
        4. VIX > 25 = VOLATILE override
        5. Otherwise = SIDEWAYS
        
        Args:
            market_data: DataFrame with OHLC columns
            
        Returns:
            Regime string
        """
        try:
            # Ensure we have required columns
            if 'close' not in market_data.columns:
                self.logger.error("Missing 'close' column in market data")
                return "SIDEWAYS"
            
            if len(market_data) < 50:
                self.logger.warning(f"Insufficient data: {len(market_data)} rows")
                return "SIDEWAYS"
            
            close = market_data['close'].astype(float)
            high = market_data.get('high', close).astype(float)
            low = market_data.get('low', close).astype(float)
            
            # 1. Calculate Indicators using 'ta' library
            # ADX for trend strength
            adx_indicator = ta.trend.ADXIndicator(high, low, close, window=14)
            adx_values = adx_indicator.adx()
            
            # RSI for momentum
            rsi_values = ta.momentum.rsi(close, window=14)
            
            # EMAs for trend direction
            ema_20 = ta.trend.ema_indicator(close, window=20)
            ema_50 = ta.trend.ema_indicator(close, window=50)
            
            # Get latest values
            current_adx = adx_values.iloc[-1] if not adx_values.empty else 20
            current_rsi = rsi_values.iloc[-1] if not rsi_values.empty else 50
            current_price = close.iloc[-1]
            current_ema_20 = ema_20.iloc[-1] if not ema_20.empty else current_price
            current_ema_50 = ema_50.iloc[-1] if not ema_50.empty else current_price
            
            # 2. Apply WHITEBOX Logic Rules
            
            # VIX Override: High volatility = VOLATILE
            if self.current_vix > 25:
                regime = "VOLATILE"
                self.logger.info(f"VIX Override: {self.current_vix:.2f} > 25")
            
            # Trend Classification
            elif current_adx > 25:  # Strong trend
                if current_price > current_ema_20 > current_ema_50:
                    regime = "BULL"
                elif current_price < current_ema_20 < current_ema_50:
                    regime = "BEAR"
                else:
                    regime = "VOLATILE"  # Trending but unclear direction
            
            # Non-trending (Sideways) Classification
            else:
                if current_rsi > 60 and current_price > current_ema_20:
                    regime = "BULL"  # Sideways with bullish bias
                elif current_rsi < 40 and current_price < current_ema_20:
                    regime = "BEAR"  # Sideways with bearish bias
                else:
                    regime = "SIDEWAYS"
            
            # Update state
            self.current_regime = regime
            
            # Log decision rationale (SEBI whitebox requirement)
            self.logger.info(
                f"Regime Decision: {regime} | "
                f"ADX={current_adx:.1f}, RSI={current_rsi:.1f}, "
                f"Price={current_price:.1f}, EMA20={current_ema_20:.1f}, EMA50={current_ema_50:.1f}, "
                f"VIX={self.current_vix:.1f}"
            )
            
            # 3. Publish Event
            await self.publish_event("REGIME_UPDATED", {
                "regime": regime,
                "adx": float(current_adx),
                "rsi": float(current_rsi),
                "vix": float(self.current_vix),
                "price": float(current_price),
                "ema_20": float(current_ema_20),
                "ema_50": float(current_ema_50),
                "timestamp": datetime.now().isoformat()
            })
            
            return regime

        except Exception as e:
            self.logger.error(f"Regime Classification Failed: {e}", exc_info=True)
            return "SIDEWAYS"  # Safe fallback
    
    def get_regime_strategy_weights(self) -> Dict[str, float]:
        """
        Get strategy type weights based on current regime.
        Used by Risk Agent for dynamic allocation.
        
        Returns:
            Dict with weights for each strategy type
        """
        weights = {
            "BULL": {
                "momentum": 0.4,
                "trend": 0.3,
                "mean_reversion": 0.1,
                "theta": 0.1,
                "hedge": 0.1
            },
            "BEAR": {
                "momentum": 0.1,
                "trend": 0.1,
                "mean_reversion": 0.1,
                "theta": 0.2,
                "hedge": 0.5
            },
            "SIDEWAYS": {
                "momentum": 0.1,
                "trend": 0.1,
                "mean_reversion": 0.3,
                "theta": 0.4,
                "hedge": 0.1
            },
            "VOLATILE": {
                "momentum": 0.2,
                "trend": 0.1,
                "mean_reversion": 0.1,
                "theta": 0.1,
                "hedge": 0.5
            }
        }
        
        return weights.get(self.current_regime, weights["SIDEWAYS"])
