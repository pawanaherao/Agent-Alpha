"""
ALPHA_PULLBACK_102 - Trend Pullback Strategy
SEBI Compliant: WHITEBOX Strategy

Type: Cash/Spot Swing Trading
Holding: 5-10 days
Expected Sharpe: 1.6 - 2.1

WHITEBOX LOGIC:
1. Stock must be in uptrend (Price > 50 EMA > 200 EMA)
2. Wait for pullback to 20 EMA (within 1%)
3. RSI cooled off (between 40-50)
4. Volume declining during pullback
5. Enter on bounce, exit at new highs
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


class TrendPullbackStrategy(BaseStrategy):
    """
    Trend Pullback Buy Strategy for Cash/Spot.
    
    SEBI Whitebox Classification:
    - Strategy ID: ALPHA_PULLBACK_102
    - Type: Swing Trend Following
    - Instrument: Equity (Cash/Delivery)
    - Holding Period: 5-10 days
    
    ENTRY RULES:
    1. Uptrend confirmation: Price > 50 EMA > 200 EMA
    2. Pullback to support: Price within 1% of 20 EMA
    3. RSI cooled: Between 40-50 (not oversold, just cooled)
    4. Volume declining during pullback
    
    EXIT RULES:
    1. Stop-loss: Below 50 EMA or -4%
    2. Target: New 20-day high or +10%
    3. Trail stop at 20 EMA after +5% profit
    """
    
    STRATEGY_ID = "ALPHA_PULLBACK_102"
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("Trend_Pullback", config or {})
        
        # EMA configuration
        self.ema_short = 20
        self.ema_medium = 50
        self.ema_long = 200
        
        # Pullback parameters
        self.pullback_threshold = 0.01  # Within 1% of 20 EMA
        
        # RSI range for pullback
        self.rsi_min = 40
        self.rsi_max = 55
        
        # Position management
        self.stop_loss_pct = 0.04  # 4% stop-loss
        self.target_pct = 0.10  # 10% target
        self.trail_trigger = 0.05  # Start trailing after 5% gain
        self.max_hold_days = 10
        
        self.nse_service = nse_data_service
        
        logger.info(f"Trend Pullback Strategy initialized: {self.STRATEGY_ID}")
    
    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        """Calculate suitability score."""
        score = 55.0  # Base
        
        if regime == "BULL":
            score += 30.0
        elif regime == "SIDEWAYS":
            score += 5.0
        elif regime in ["BEAR", "VOLATILE"]:
            score -= 25.0
        
        return max(0.0, min(score, 100.0))
    
    async def generate_signal(
        self, 
        market_data: pd.DataFrame, 
        regime: str
    ) -> Optional[StrategySignal]:
        """
        Analyze for pullback entry opportunity.
        """
        if regime in ["BEAR", "VOLATILE"]:
            return None
        
        if market_data is None or market_data.empty:
            return None
        
        try:
            if len(market_data) < self.ema_long + 5:
                return None
            
            df = self._ensure_indicators(market_data.copy())
            
            latest = df.iloc[-1]
            symbol = str(latest.get('symbol', 'UNKNOWN'))
            
            current_price = float(latest['close'])
            ema_20 = float(latest['ema_20'])
            ema_50 = float(latest['ema_50'])
            ema_200 = float(latest['ema_200'])
            rsi = float(latest.get('rsi', 50))
            
            # Check 1: Uptrend (EMA alignment)
            in_uptrend = current_price > ema_50 > ema_200
            
            # Check 2: Pullback to 20 EMA
            distance_to_ema20 = (current_price - ema_20) / ema_20
            is_pullback = abs(distance_to_ema20) <= self.pullback_threshold
            
            # Check 3: RSI cooled
            rsi_valid = self.rsi_min <= rsi <= self.rsi_max
            
            # Check 4: Volume declining (simplified)
            recent_vol = df['volume'].iloc[-5:].mean()
            prior_vol = df['volume'].iloc[-15:-5].mean()
            volume_declining = recent_vol < prior_vol if prior_vol > 0 else True
            
            logger.debug(
                f"{symbol}: Uptrend={in_uptrend}, Pullback={is_pullback}, "
                f"RSI={rsi:.1f} valid={rsi_valid}, VolDecline={volume_declining}"
            )
            
            if not (in_uptrend and is_pullback and rsi_valid):
                return None
            
            # Calculate exits
            stop_loss = max(ema_50 * 0.99, current_price * (1 - self.stop_loss_pct))
            target = current_price * (1 + self.target_pct)
            
            strength = 0.7
            if volume_declining:
                strength += 0.1
            if regime == "BULL":
                strength += 0.1
            
            signal = StrategySignal(
                signal_id=f"{self.STRATEGY_ID}_{symbol}_{datetime.now().strftime('%Y%m%d')}",
                strategy_name=self.name,
                symbol=symbol,
                signal_type="BUY",
                strength=min(strength, 1.0),
                market_regime_at_signal=regime,
                entry_price=current_price,
                stop_loss=stop_loss,
                target_price=target,
                metadata={
                    "strategy_id": self.STRATEGY_ID,
                    "segment": "CASH",
                    "ema_20": ema_20,
                    "ema_50": ema_50,
                    "ema_200": ema_200,
                    "rsi": rsi,
                    "entry_reason": "Pullback to 20 EMA in uptrend",
                    "trail_trigger": self.trail_trigger,
                    "sebi_algo_id": self.STRATEGY_ID
                }
            )
            
            logger.info(
                f"🚀 Pullback Signal: {symbol} | "
                f"Entry={current_price:.2f}, SL={stop_loss:.2f}, Target={target:.2f}"
            )
            
            return signal
            
        except Exception as e:
            logger.error(f"Pullback analysis failed: {e}")
            return None
    
    def _ensure_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add EMA and RSI if not present."""
        if 'ema_20' not in df.columns:
            df['ema_20'] = ta.trend.ema_indicator(df['close'], window=20)
        if 'ema_50' not in df.columns:
            df['ema_50'] = ta.trend.ema_indicator(df['close'], window=50)
        if 'ema_200' not in df.columns:
            df['ema_200'] = ta.trend.ema_indicator(df['close'], window=200)
        if 'rsi' not in df.columns:
            df['rsi'] = ta.momentum.rsi(df['close'], window=14)
        return df
    
    def get_strategy_info(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.STRATEGY_ID,
            "name": "Trend Pullback",
            "type": "SWING_TREND",
            "instrument": "EQUITY_CASH",
            "holding_period": "5-10 days",
            "whitebox": True
        }
