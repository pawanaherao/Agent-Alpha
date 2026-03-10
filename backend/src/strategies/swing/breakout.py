"""
ALPHA_BREAKOUT_101 - Swing Breakout Strategy
SEBI Compliant: WHITEBOX Strategy

Type: Cash/Spot Swing Trading
Holding: 3-7 days
Expected Sharpe: 1.5 - 2.0

WHITEBOX LOGIC:
1. Scan for stocks making 20-day high
2. Confirm with volume surge (>2x average)
3. RSI not overbought (<70)
4. ADX showing trend strength (>25)
5. Hold for 3-7 days, trail stop at 2x ATR

SEBI Compliance:
- All logic transparent and documented
- Unique algo ID for all orders
- Full audit trail
"""

from typing import Optional, Dict, Any, List
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import ta

from src.strategies.base import BaseStrategy, StrategySignal
from src.services.nse_data import nse_data_service

logger = logging.getLogger(__name__)


class SwingBreakoutStrategy(BaseStrategy):
    """
    Swing Breakout Strategy for Cash/Spot Segment.
    
    SEBI Whitebox Classification:
    - Strategy ID: ALPHA_BREAKOUT_101
    - Type: Swing Momentum
    - Instrument: Equity (Cash/Delivery)
    - Risk Category: Medium
    - Holding Period: 3-7 days
    
    ENTRY RULES (All must be met):
    1. Price closes above 20-day high
    2. Volume > 2x 20-day average
    3. RSI > 50 but < 70 (momentum but not overbought)
    4. ADX > 25 (confirming trend strength)
    5. Regime: BULL or SIDEWAYS (not BEAR)
    
    EXIT RULES:
    1. Stop-loss: 20-day low or -3% (whichever tighter)
    2. Target: +8% or trailing stop (2x ATR)
    3. Time exit: 7 days max hold
    """
    
    STRATEGY_ID = "ALPHA_BREAKOUT_101"
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("Swing_Breakout", config or {})
        
        # Strategy parameters
        self.lookback_period = 20  # 20-day high breakout
        self.volume_multiplier = 2.0  # Volume > 2x average
        
        # RSI thresholds
        self.rsi_min = 50  # Minimum RSI for momentum
        self.rsi_max = 70  # Maximum RSI (not overbought)
        
        # ADX threshold
        self.adx_threshold = 25  # Minimum for trend confirmation
        
        # Position management
        self.stop_loss_pct = 0.03  # 3% stop-loss
        self.target_pct = 0.08  # 8% target
        self.max_hold_days = 7  # Maximum holding period
        self.position_size_pct = 0.05  # 5% of capital per trade
        self.max_positions = 10  # Maximum concurrent positions
        
        # Universe
        self.nse_service = nse_data_service
        
        logger.info(f"Swing Breakout Strategy initialized: {self.STRATEGY_ID}")
    
    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        """
        Calculate suitability for swing breakout strategy.
        
        WHITEBOX SCORING:
        - Base: 60 points (swing strategies generally suitable)
        - BULL regime: +25 points
        - SIDEWAYS regime: +10 points
        - BEAR regime: -30 points (not suitable)
        - VOLATILE: -10 points (risky for swing)
        """
        score = 60.0  # Base score
        
        # Regime scoring
        if regime == "BULL":
            score += 25.0
            logger.debug("BULL regime: +25 points")
        elif regime == "SIDEWAYS":
            score += 10.0
            logger.debug("SIDEWAYS regime: +10 points")
        elif regime == "BEAR":
            score -= 30.0
            logger.debug("BEAR regime: -30 points (avoid longs)")
        elif regime == "VOLATILE":
            score -= 10.0
            logger.debug("VOLATILE regime: -10 points")
        
        final_score = max(0.0, min(score, 100.0))
        
        logger.info(f"Swing Breakout Suitability: {final_score:.1f}/100 | Regime={regime}")
        
        return final_score
    
    async def generate_signal(
        self, 
        market_data: pd.DataFrame, 
        regime: str
    ) -> Optional[StrategySignal]:
        """
        Scan universe for breakout candidates and generate signal.
        
        In production, this scans all NIFTY 100 stocks.
        For now, analyzes provided market_data.
        
        Returns:
            StrategySignal if breakout detected, None otherwise
        """
        # Skip in BEAR regime
        if regime == "BEAR":
            logger.debug("BEAR regime - skipping long setups")
            return None
        
        # If market_data is provided, analyze it
        if market_data is not None and not market_data.empty:
            return await self._analyze_stock(market_data, regime)
        
        # Otherwise, scan universe for opportunities
        return await self._scan_universe_for_breakouts(regime)
    
    async def scan_universe(self, regime: str) -> List[StrategySignal]:
        """
        Scan entire universe for breakout candidates.
        Returns list of signals for all qualifying stocks.
        """
        signals = []
        
        if regime == "BEAR":
            logger.info("BEAR regime - no swing long scans")
            return signals
        
        universe = self.nse_service.get_nifty_100_stocks()
        logger.info(f"Scanning {len(universe)} stocks for breakouts...")
        
        for symbol in universe[:20]:  # Limit to top 20 for performance
            try:
                df = await self.nse_service.get_stock_with_indicators(symbol, period="3M")
                
                if df.empty or len(df) < self.lookback_period:
                    continue
                
                signal = await self._analyze_stock(df, regime, symbol)
                
                if signal:
                    signals.append(signal)
                    logger.info(f"✅ Breakout signal: {symbol}")
                    
            except Exception as e:
                logger.error(f"Failed to scan {symbol}: {e}")
                continue
        
        logger.info(f"Universe scan complete: {len(signals)} breakout candidates")
        return signals
    
    async def _scan_universe_for_breakouts(self, regime: str) -> Optional[StrategySignal]:
        """
        Scan universe and return first qualifying signal.
        """
        signals = await self.scan_universe(regime)
        return signals[0] if signals else None
    
    async def _analyze_stock(
        self, 
        df: pd.DataFrame, 
        regime: str,
        symbol: str = "UNKNOWN"
    ) -> Optional[StrategySignal]:
        """
        Analyze single stock for breakout setup.
        
        WHITEBOX LOGIC:
        1. Check if price > 20-day high
        2. Check volume confirmation
        3. Check RSI range
        4. Check ADX strength
        5. Calculate stop-loss and target
        """
        try:
            if len(df) < self.lookback_period + 5:
                return None
            
            # Get symbol if available
            if 'symbol' in df.columns:
                symbol = df['symbol'].iloc[-1]
            
            # Ensure required columns
            required_cols = ['close', 'high', 'low', 'volume']
            if not all(col in df.columns for col in required_cols):
                logger.warning(f"Missing columns in {symbol}")
                return None
            
            # Calculate indicators if not present
            df = self._ensure_indicators(df)
            
            # Get latest values
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            
            current_price = float(latest['close'])
            current_volume = float(latest.get('volume', 0))
            
            # Calculate 20-day high
            high_20d = float(df['high'].iloc[-self.lookback_period:].max())
            
            # Calculate average volume
            avg_volume = float(df['volume'].iloc[-self.lookback_period:].mean())
            
            # Get indicators
            rsi = float(latest.get('rsi', 50))
            adx = float(latest.get('adx', 20))
            
            # ===== WHITEBOX ENTRY CHECKS =====
            
            # Check 1: Price breakout
            is_breakout = current_price > high_20d
            
            # Check 2: Volume confirmation
            volume_confirmed = current_volume > (avg_volume * self.volume_multiplier) if avg_volume > 0 else True
            
            # Check 3: RSI in range
            rsi_valid = self.rsi_min <= rsi <= self.rsi_max
            
            # Check 4: ADX strength
            adx_valid = adx > self.adx_threshold
            
            # Log decision factors
            logger.debug(
                f"{symbol}: Breakout={is_breakout}, Vol={volume_confirmed}, "
                f"RSI={rsi:.1f} valid={rsi_valid}, ADX={adx:.1f} valid={adx_valid}"
            )
            
            # All conditions must be met (WHITEBOX: breakout + volume + RSI + ADX)
            if not (is_breakout and volume_confirmed and rsi_valid and adx_valid):
                return None
            
            # Calculate stop-loss and target
            low_20d = float(df['low'].iloc[-self.lookback_period:].min())
            atr = float(latest.get('atr', current_price * 0.02))
            
            # Stop-loss: 20-day low or 3%, whichever is tighter
            stop_by_level = low_20d
            stop_by_pct = current_price * (1 - self.stop_loss_pct)
            stop_loss = max(stop_by_level, stop_by_pct)  # Tighter stop
            
            # Target: 8% gain
            target = current_price * (1 + self.target_pct)
            
            # Calculate strength
            strength = self._calculate_signal_strength(
                is_breakout, volume_confirmed, rsi, adx, regime
            )
            
            # Create signal
            signal = StrategySignal(
                signal_id=f"{self.STRATEGY_ID}_{symbol}_{datetime.now().strftime('%Y%m%d')}",
                strategy_name=self.name,
                symbol=symbol,
                signal_type="BUY",
                strength=strength,
                market_regime_at_signal=regime,
                entry_price=current_price,
                stop_loss=stop_loss,
                target_price=target,
                metadata={
                    "strategy_id": self.STRATEGY_ID,
                    "segment": "CASH",
                    "holding_period": f"{self.max_hold_days} days",
                    "breakout_high_20d": high_20d,
                    "volume_ratio": current_volume / avg_volume if avg_volume > 0 else 0,
                    "rsi": rsi,
                    "adx": adx,
                    "atr": atr,
                    "entry_reason": f"20-day breakout at {high_20d:.2f}",
                    "sebi_algo_id": self.STRATEGY_ID
                }
            )
            
            logger.info(
                f"🚀 Swing Breakout Signal: {symbol} | "
                f"Entry={current_price:.2f}, SL={stop_loss:.2f}, Target={target:.2f} | "
                f"RSI={rsi:.1f}, ADX={adx:.1f}"
            )
            
            return signal
            
        except Exception as e:
            logger.error(f"Analysis failed for {symbol}: {e}")
            return None
    
    def _ensure_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add technical indicators if not present."""
        
        if 'rsi' not in df.columns:
            df['rsi'] = ta.momentum.rsi(df['close'], window=14)
        
        if 'adx' not in df.columns:
            df['adx'] = ta.trend.adx(df['high'], df['low'], df['close'], window=14)
        
        if 'atr' not in df.columns:
            df['atr'] = ta.volatility.average_true_range(
                df['high'], df['low'], df['close'], window=14
            )
        
        return df
    
    def _calculate_signal_strength(
        self,
        is_breakout: bool,
        volume_confirmed: bool,
        rsi: float,
        adx: float,
        regime: str
    ) -> float:
        """
        Calculate signal strength (0.0 - 1.0).
        
        WHITEBOX FACTORS:
        - Base: 0.6
        - Volume confirmed: +0.15
        - ADX > 30: +0.1
        - BULL regime: +0.1
        - RSI in sweet spot (55-65): +0.05
        """
        strength = 0.6  # Base
        
        if volume_confirmed:
            strength += 0.15
        
        if adx > 30:
            strength += 0.1
        elif adx > 25:
            strength += 0.05
        
        if regime == "BULL":
            strength += 0.1
        
        if 55 <= rsi <= 65:
            strength += 0.05
        
        return min(strength, 1.0)
    
    def get_strategy_info(self) -> Dict[str, Any]:
        """Return strategy metadata for SEBI compliance."""
        return {
            "strategy_id": self.STRATEGY_ID,
            "name": "Swing Breakout",
            "type": "SWING_MOMENTUM",
            "instrument": "EQUITY_CASH",
            "segment": "CASH",
            "risk_category": "MEDIUM",
            "whitebox": True,
            "holding_period": "3-7 days",
            "parameters": {
                "lookback_period": self.lookback_period,
                "volume_multiplier": self.volume_multiplier,
                "rsi_min": self.rsi_min,
                "rsi_max": self.rsi_max,
                "adx_threshold": self.adx_threshold,
                "stop_loss_pct": self.stop_loss_pct,
                "target_pct": self.target_pct,
                "max_hold_days": self.max_hold_days
            }
        }
