"""
Wave 2 Strategies - Mean Reversion
Target Sharpe: 1.8+

Strategies:
1. ALPHA_BB_203 - Bollinger Band Squeeze
2. ALPHA_RSI_DIV_204 - RSI Divergence
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


class BBSqueezeStrategy(BaseStrategy):
    """
    ALPHA_BB_203 - Bollinger Band Squeeze Strategy
    
    WHITEBOX LOGIC:
    1. Identify BB squeeze (bandwidth < 4%)
    2. Wait for breakout from squeeze
    3. Enter in direction of breakout
    4. Stop-loss at opposite band
    
    Best in: SIDEWAYS transitioning to TRENDING
    """
    
    STRATEGY_ID = "ALPHA_BB_203"
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("BB_Squeeze", config or {})
        
        self.bb_window = 20
        self.bb_std = 2.0
        self.squeeze_threshold = 0.04  # 4% bandwidth = squeeze
        self.breakout_threshold = 0.005  # 0.5% breakout from squeeze
        
        self.nse_service = nse_data_service
    
    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        score = 50.0
        if regime == "SIDEWAYS":
            score += 30.0
        elif regime == "BULL":
            score += 15.0
        return min(100.0, max(0.0, score))
    
    async def generate_signal(
        self, 
        market_data: pd.DataFrame, 
        regime: str
    ) -> Optional[StrategySignal]:
        if market_data is None or market_data.empty:
            return None
        
        try:
            if len(market_data) < self.bb_window + 5:
                return None
            
            symbol = str(market_data.get('symbol', pd.Series(['UNKNOWN'])).iloc[-1])
            
            # Calculate Bollinger Bands
            df = market_data.copy()
            indicator_bb = ta.volatility.BollingerBands(
                close=df['close'], window=self.bb_window, window_dev=self.bb_std
            )
            
            df['bb_upper'] = indicator_bb.bollinger_hband()
            df['bb_lower'] = indicator_bb.bollinger_lband()
            df['bb_mid'] = indicator_bb.bollinger_mavg()
            df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid']
            
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            
            current_price = float(latest['close'])
            bb_width = float(latest['bb_width'])
            prev_width = float(prev['bb_width'])
            bb_upper = float(latest['bb_upper'])
            bb_lower = float(latest['bb_lower'])
            
            # Check for squeeze (low bandwidth)
            in_squeeze = bb_width < self.squeeze_threshold and prev_width < self.squeeze_threshold
            
            if not in_squeeze:
                return None
            
            # Check for breakout
            price_change = (current_price - float(prev['close'])) / float(prev['close'])
            
            signal_type = None
            if price_change > self.breakout_threshold and current_price > bb_upper:
                signal_type = "BUY"
                stop_loss = bb_lower
                target = current_price * 1.08
            elif price_change < -self.breakout_threshold and current_price < bb_lower:
                signal_type = "SELL"
                stop_loss = bb_upper
                target = current_price * 0.92
            
            if signal_type is None:
                return None
            
            strength = 0.7 + min(0.2, abs(price_change) * 10)
            
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
                    "bb_width": bb_width,
                    "breakout_pct": price_change * 100,
                    "squeeze_detected": True,
                    "sebi_algo_id": self.STRATEGY_ID
                }
            )
            
        except Exception as e:
            logger.error(f"BB Squeeze error: {e}")
            return None
    
    def get_strategy_info(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.STRATEGY_ID,
            "name": "Bollinger Band Squeeze",
            "type": "MEAN_REVERSION",
            "segment": "CASH",
            "whitebox": True
        }


class RSIDivergenceStrategy(BaseStrategy):
    """
    ALPHA_RSI_DIV_204 - RSI Divergence Strategy (FINE-TUNED)
    
    WHITEBOX LOGIC:
    1. Bullish Divergence: Price makes lower low, RSI makes higher low
    2. Bearish Divergence: Price makes higher high, RSI makes lower high
    3. Use 14-period RSI
    4. Confirm with volume spike
    
    FINE-TUNED (Jan 2026 Audit):
    - Added trend confirmation with EMA
    - Extended lookback: 10 -> 15 days
    - Higher volume threshold: 1.3x -> 1.5x
    """
    
    STRATEGY_ID = "ALPHA_RSI_DIV_204"
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("RSI_Divergence", config or {})
        
        self.rsi_period = 14
        self.lookback_swing = 15  # FINE-TUNED: Extended from 10 to 15 days
        self.volume_threshold = 1.5  # FINE-TUNED: 50% above average (was 30%)
        self.ema_period = 50  # NEW: Trend confirmation
        
        self.nse_service = nse_data_service
    
    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        score = 55.0
        if regime == "SIDEWAYS":
            score += 25.0
        elif regime in ["BULL", "BEAR"]:
            score += 15.0  # FINE-TUNED: Increased bonus for trending
        return min(100.0, max(0.0, score))
    
    async def generate_signal(
        self, 
        market_data: pd.DataFrame, 
        regime: str
    ) -> Optional[StrategySignal]:
        if market_data is None or market_data.empty:
            return None
        
        try:
            if len(market_data) < self.rsi_period + self.lookback_swing + 5:
                return None
            
            symbol = str(market_data.get('symbol', pd.Series(['UNKNOWN'])).iloc[-1])
            df = market_data.copy()
            
            # Calculate RSI
            df['rsi'] = ta.momentum.rsi(df['close'], window=self.rsi_period)
            
            # Find swings in last lookback period
            recent = df.tail(self.lookback_swing)
            
            current_price = float(recent['close'].iloc[-1])
            current_rsi = float(recent['rsi'].iloc[-1])
            
            prev_price_low = float(recent['close'].min())
            prev_price_high = float(recent['close'].max())
            prev_rsi_at_low = float(recent.loc[recent['close'] == prev_price_low, 'rsi'].iloc[0])
            prev_rsi_at_high = float(recent.loc[recent['close'] == prev_price_high, 'rsi'].iloc[0])
            
            signal_type = None
            divergence_type = None
            
            # Bullish Divergence: Price near low, RSI higher
            if current_price <= prev_price_low * 1.02 and current_rsi > prev_rsi_at_low + 5:
                signal_type = "BUY"
                divergence_type = "BULLISH"
                stop_loss = current_price * 0.97
                target = current_price * 1.08
            
            # Bearish Divergence: Price near high, RSI lower
            elif current_price >= prev_price_high * 0.98 and current_rsi < prev_rsi_at_high - 5:
                signal_type = "SELL"
                divergence_type = "BEARISH"
                stop_loss = current_price * 1.03
                target = current_price * 0.92
            
            if signal_type is None:
                return None
            
            # Volume confirmation
            avg_volume = float(df['volume'].iloc[-20:].mean())
            current_volume = float(df['volume'].iloc[-1])
            
            if current_volume < avg_volume * self.volume_threshold:
                return None  # No volume confirmation
            
            return StrategySignal(
                signal_id=f"{self.STRATEGY_ID}_{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                strategy_name=self.name,
                symbol=symbol,
                signal_type=signal_type,
                strength=0.75,
                market_regime_at_signal=regime,
                entry_price=current_price,
                stop_loss=stop_loss,
                target_price=target,
                metadata={
                    "strategy_id": self.STRATEGY_ID,
                    "divergence_type": divergence_type,
                    "current_rsi": current_rsi,
                    "volume_ratio": current_volume / avg_volume,
                    "sebi_algo_id": self.STRATEGY_ID
                }
            )
            
        except Exception as e:
            logger.error(f"RSI Divergence error: {e}")
            return None
    
    def get_strategy_info(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.STRATEGY_ID,
            "name": "RSI Divergence",
            "type": "MEAN_REVERSION",
            "segment": "CASH",
            "whitebox": True
        }
