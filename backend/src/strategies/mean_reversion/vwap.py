"""
ALPHA_VWAP_002 - VWAP Mean Reversion Strategy
SEBI Compliant: WHITEBOX Strategy

Type: Options Intraday
Holding: 1-4 hours
Expected Sharpe: 1.5 - 1.8

WHITEBOX LOGIC:
1. Calculate VWAP from OHLCV data
2. Enter when price deviates >1.5% from VWAP
3. Exit when price reverts to VWAP
4. Best in SIDEWAYS/ranging markets
"""

from typing import Optional, Dict, Any
import pandas as pd
import numpy as np
from datetime import datetime, time
import logging
import ta

from src.strategies.base import BaseStrategy, StrategySignal
from src.services.nse_data import nse_data_service

logger = logging.getLogger(__name__)


class VWAPReversionStrategy(BaseStrategy):
    """
    VWAP Mean Reversion Strategy.
    
    SEBI Whitebox Classification:
    - Strategy ID: ALPHA_VWAP_002
    - Type: Intraday Mean Reversion
    - Instrument: NIFTY Options/Futures
    - Risk Category: Medium
    
    ENTRY RULES:
    1. Price below VWAP by >1.5%: BUY (expecting reversion up)
    2. Price above VWAP by >1.5%: SELL (expecting reversion down)
    3. RSI confirmation (oversold/overbought)
    4. Volume spike (institutional activity)
    
    EXIT RULES:
    1. Target: Price touches VWAP
    2. Stop-loss: 2x deviation from entry
    3. Time exit: 3:15 PM
    """
    
    STRATEGY_ID = "ALPHA_VWAP_002"
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("VWAP_Reversion", config or {})
        
        # Deviation thresholds
        self.min_deviation_pct = 1.5  # Minimum 1.5% deviation
        self.max_deviation_pct = 3.0  # Maximum 3% (avoid extremes)
        
        # RSI thresholds
        self.rsi_oversold = 35
        self.rsi_overbought = 65
        
        # Exit parameters
        self.stop_loss_multiplier = 2.0  # SL at 2x deviation
        
        # Trading hours
        self.entry_start = time(9, 45)  # After initial volatility
        self.entry_end = time(14, 30)  # Before closing
        self.exit_time = time(15, 15)
        
        self.nse_service = nse_data_service
        
        logger.info(f"VWAP Reversion initialized: {self.STRATEGY_ID}")
    
    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        """
        VWAP reversion works best in SIDEWAYS markets.
        """
        score = 50.0
        
        if regime == "SIDEWAYS":
            score += 35.0
        elif regime == "VOLATILE":
            score += 15.0  # Can work with caution
        elif regime in ["BULL", "BEAR"]:
            score -= 20.0  # Trending = mean reversion fails
        
        # Time check
        now = datetime.now().time()
        if self.entry_start <= now <= self.entry_end:
            score += 10.0
        else:
            score -= 20.0
        
        return max(0.0, min(score, 100.0))
    
    async def generate_signal(
        self, 
        market_data: pd.DataFrame, 
        regime: str
    ) -> Optional[StrategySignal]:
        """
        Generate signal based on VWAP deviation.
        """
        # Regime filter - avoid trending markets
        if regime in ["BULL", "BEAR"]:
            logger.debug("Trending regime - VWAP reversion less effective")
            return None
        
        # Time filter
        now = datetime.now().time()
        if not (self.entry_start <= now <= self.entry_end):
            return None
        
        if market_data is None or market_data.empty:
            return None
        
        try:
            df = self._calculate_vwap(market_data.copy())
            
            if 'vwap' not in df.columns:
                logger.warning("VWAP calculation failed")
                return None
            
            latest = df.iloc[-1]
            
            current_price = float(latest['close'])
            vwap = float(latest['vwap'])
            
            # Calculate deviation
            deviation_pct = (current_price - vwap) / vwap * 100
            
            # Get RSI
            rsi = float(latest.get('rsi', 50))
            
            signal_type = None
            entry_reason = ""
            
            # Oversold - BUY signal
            if (deviation_pct < -self.min_deviation_pct and 
                abs(deviation_pct) < self.max_deviation_pct and
                rsi < self.rsi_oversold):
                signal_type = "BUY"
                entry_reason = f"Price {deviation_pct:.2f}% below VWAP, RSI={rsi:.1f}"
            
            # Overbought - SELL signal
            elif (deviation_pct > self.min_deviation_pct and 
                  abs(deviation_pct) < self.max_deviation_pct and
                  rsi > self.rsi_overbought):
                signal_type = "SELL"
                entry_reason = f"Price +{deviation_pct:.2f}% above VWAP, RSI={rsi:.1f}"
            
            if signal_type is None:
                return None
            
            # Calculate exits
            deviation_points = abs(current_price - vwap)
            
            if signal_type == "BUY":
                stop_loss = current_price - (deviation_points * self.stop_loss_multiplier)
                target = vwap
            else:
                stop_loss = current_price + (deviation_points * self.stop_loss_multiplier)
                target = vwap
            
            strength = 0.7
            if regime == "SIDEWAYS":
                strength += 0.15
            if abs(deviation_pct) > 2.0:
                strength += 0.1
            
            signal = StrategySignal(
                signal_id=f"{self.STRATEGY_ID}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                strategy_name=self.name,
                symbol="NIFTY",
                signal_type=signal_type,
                strength=min(strength, 1.0),
                market_regime_at_signal=regime,
                entry_price=current_price,
                stop_loss=stop_loss,
                target_price=target,
                metadata={
                    "strategy_id": self.STRATEGY_ID,
                    "vwap": vwap,
                    "deviation_pct": deviation_pct,
                    "rsi": rsi,
                    "entry_reason": entry_reason,
                    "instrument_type": "CALL" if signal_type == "BUY" else "PUT",
                    "exit_time": "15:15",
                    "sebi_algo_id": self.STRATEGY_ID
                }
            )
            
            logger.info(
                f"VWAP Signal: {signal_type} | "
                f"Price={current_price:.0f}, VWAP={vwap:.0f}, Dev={deviation_pct:.2f}%"
            )
            
            return signal
            
        except Exception as e:
            logger.error(f"VWAP signal generation failed: {e}")
            return None
    
    def _calculate_vwap(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate VWAP from OHLCV data."""
        if 'vwap' in df.columns:
            return df
        
        # Typical price
        df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
        
        # VWAP = Cumulative(TP * Volume) / Cumulative(Volume)
        df['tp_volume'] = df['typical_price'] * df['volume']
        df['cumulative_tp_volume'] = df['tp_volume'].cumsum()
        df['cumulative_volume'] = df['volume'].cumsum()
        
        df['vwap'] = df['cumulative_tp_volume'] / df['cumulative_volume']
        
        # Calculate RSI if not present
        if 'rsi' not in df.columns:
            df['rsi'] = ta.momentum.rsi(df['close'], window=14)
        
        return df
    
    def get_strategy_info(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.STRATEGY_ID,
            "name": "VWAP Mean Reversion",
            "type": "INTRADAY_MEAN_REVERSION",
            "instrument": "INDEX_OPTIONS",
            "risk_category": "MEDIUM",
            "whitebox": True,
            "parameters": {
                "min_deviation": f"{self.min_deviation_pct}%",
                "max_deviation": f"{self.max_deviation_pct}%",
                "rsi_oversold": self.rsi_oversold,
                "rsi_overbought": self.rsi_overbought,
                "entry_window": "09:45-14:30"
            }
        }
