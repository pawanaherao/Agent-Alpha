"""
ALPHA_EMA_CROSS_104 - EMA Crossover Strategy (FINE-TUNED)
SEBI Compliant: WHITEBOX Strategy

Type: Cash/Spot Swing Trading
Holding: 5-15 days
Expected Sharpe: 1.4 - 1.8

FINE-TUNED (Jan 2026 Audit):
- ADX threshold: 20 → 25 (stronger trend requirement)
- SIDEWAYS penalty: -15 → -30 (avoid choppy markets)
- ADX filter now MANDATORY for entry

WHITEBOX LOGIC:
1. 9 EMA crosses above 21 EMA (bullish signal)
2. Price above 50 EMA (trend filter)
3. ADX > 25 (MANDATORY - trending market)
4. Exit when 9 EMA crosses below 21 EMA
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


class EMACrossoverStrategy(BaseStrategy):
    """
    EMA Crossover Strategy for Cash/Spot.
    
    SEBI Whitebox Classification:
    - Strategy ID: ALPHA_EMA_CROSS_104
    - Type: Swing Trend Following
    - Instrument: Equity (Cash/Delivery)
    - Holding Period: 5-15 days
    
    ENTRY RULES:
    1. 9 EMA crosses above 21 EMA (today)
    2. Price > 50 EMA (trend filter)
    3. ADX > 20 (trending, not ranging)
    
    EXIT RULES:
    1. 9 EMA crosses below 21 EMA
    2. Stop-loss: -5% from entry
    3. Trail stop at 21 EMA after +5% profit
    """
    
    STRATEGY_ID = "ALPHA_EMA_CROSS_104"
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("EMA_Crossover", config or {})
        
        # EMA periods
        self.ema_fast = 9
        self.ema_slow = 21
        self.ema_trend = 50
        
        # ADX threshold (FINE-TUNED: increased from 20 to 25)
        self.adx_threshold = 25  # Stronger trend requirement
        
        # Position management
        self.stop_loss_pct = 0.05  # 5% stop-loss
        self.trail_trigger = 0.05  # Trail at 21 EMA after 5% gain
        self.max_hold_days = 15
        
        self.nse_service = nse_data_service
        
        logger.info(f"EMA Crossover Strategy initialized: {self.STRATEGY_ID}")
    
    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        """Calculate suitability score."""
        score = 50.0
        
        if regime in ["BULL", "BEAR"]:
            score += 25.0  # Works in both trends
        elif regime == "SIDEWAYS":
            score -= 30.0  # FINE-TUNED: Stronger penalty for choppy markets
        elif regime == "VOLATILE":
            score -= 10.0
        
        return max(0.0, min(score, 100.0))
    
    async def generate_signal(
        self, 
        market_data: pd.DataFrame, 
        regime: str
    ) -> Optional[StrategySignal]:
        """
        Detect EMA crossover and generate signal.
        """
        if market_data is None or market_data.empty:
            return None
        
        try:
            if len(market_data) < self.ema_trend + 5:
                return None
            
            df = self._ensure_indicators(market_data.copy())
            
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            symbol = str(latest.get('symbol', 'UNKNOWN'))
            
            current_price = float(latest['close'])
            
            # Current EMAs
            ema_9_now = float(latest['ema_9'])
            ema_21_now = float(latest['ema_21'])
            ema_50 = float(latest.get('ema_50', current_price))
            adx = float(latest.get('adx', 25))
            
            # Previous EMAs
            ema_9_prev = float(prev['ema_9'])
            ema_21_prev = float(prev['ema_21'])
            
            # Check for bullish crossover
            bullish_cross = (ema_9_prev <= ema_21_prev) and (ema_9_now > ema_21_now)
            
            # Check for bearish crossover (for exit signal)
            bearish_cross = (ema_9_prev >= ema_21_prev) and (ema_9_now < ema_21_now)
            
            # Trend filter
            in_uptrend = current_price > ema_50
            
            # ADX filter
            adx_valid = adx > self.adx_threshold
            
            logger.debug(
                f"{symbol}: BullCross={bullish_cross}, BearCross={bearish_cross}, "
                f"Uptrend={in_uptrend}, ADX={adx:.1f}"
            )
            
            if not bullish_cross:
                return None
            
            if not in_uptrend:
                logger.debug(f"{symbol}: Crossover but below 50 EMA, skipping")
                return None
            
            # FINE-TUNED: ADX filter now MANDATORY (was optional)
            if not adx_valid:
                logger.debug(f"{symbol}: ADX {adx:.1f} < {self.adx_threshold}, skipping (not trending)")
                return None
            
            # Calculate stops
            stop_loss = current_price * (1 - self.stop_loss_pct)
            
            strength = 0.65
            if adx_valid:
                strength += 0.15
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
                metadata={
                    "strategy_id": self.STRATEGY_ID,
                    "segment": "CASH",
                    "ema_9": ema_9_now,
                    "ema_21": ema_21_now,
                    "ema_50": ema_50,
                    "adx": adx,
                    "entry_reason": "9/21 EMA bullish crossover",
                    "exit_condition": "9 EMA crosses below 21 EMA",
                    "trail_at": "21 EMA after +5% profit",
                    "sebi_algo_id": self.STRATEGY_ID
                }
            )
            
            logger.info(
                f"🚀 EMA Cross Signal: {symbol} | "
                f"Entry={current_price:.2f}, SL={stop_loss:.2f} | "
                f"9EMA={ema_9_now:.2f}, 21EMA={ema_21_now:.2f}"
            )
            
            return signal
            
        except Exception as e:
            logger.error(f"EMA cross analysis failed: {e}")
            return None
    
    def _ensure_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add EMAs and ADX if not present."""
        if 'ema_9' not in df.columns:
            df['ema_9'] = ta.trend.ema_indicator(df['close'], window=9)
        if 'ema_21' not in df.columns:
            df['ema_21'] = ta.trend.ema_indicator(df['close'], window=21)
        if 'ema_50' not in df.columns:
            df['ema_50'] = ta.trend.ema_indicator(df['close'], window=50)
        if 'adx' not in df.columns:
            df['adx'] = ta.trend.adx(df['high'], df['low'], df['close'], window=14)
        return df
    
    def get_strategy_info(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.STRATEGY_ID,
            "name": "EMA Crossover",
            "type": "SWING_TREND",
            "instrument": "EQUITY_CASH",
            "holding_period": "5-15 days",
            "whitebox": True
        }
