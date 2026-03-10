from typing import Optional, Dict, Any
import pandas as pd
import numpy as np
from datetime import datetime
from src.strategies.base import BaseStrategy, StrategySignal

class BullCallSpread(BaseStrategy):
    """
    7. Bull Call Spread
    Sell OTM Call, Buy ATM/ITM Call
    Profit: Spread between strikes
    Max Loss: Difference between strikes - Net Debit
    Best for: Bullish, Defined Risk
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_BCS_007", config or {})
        self.strike_gap = config.get("strike_gap", 100) if config else 100

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        if regime == "BULL":
            return 90.0
        elif regime == "SIDEWAYS":
            return 60.0
        return 10.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        """Generate Bull Call Spread signal: Buy ATM Call, Sell OTM Call"""
        try:
            if market_data.empty or len(market_data) < 2:
                return None
            
            current_close = market_data['close'].iloc[-1]
            prev_close = market_data['close'].iloc[-2]
            
            # Signal when price is trending up
            if current_close > prev_close and regime in ["BULL", "SIDEWAYS"]:
                _sym = market_data['symbol'].iloc[-1] if 'symbol' in market_data.columns else 'NIFTY'
                return StrategySignal(
                    signal_id=f"BCS_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    strategy_name=self.name,
                    symbol=_sym,
                    signal_type="BUY",
                    market_regime_at_signal=regime,
                    entry_price=current_close,
                    quantity=1,
                    strength=0.75,
                    stop_loss=current_close - (self.strike_gap * 0.5),
                    target_price=current_close + (self.strike_gap * 0.7),
                    metadata={
                        "entry_type": "BUY_SPREAD",
                        "spread_type": "bull_call",
                        "long_strike": round(current_close),
                        "short_strike": round(current_close + self.strike_gap),
                    }
                )
            return None
        except Exception as e:
            self.logger.error(f"Bull Call Spread error: {e}")
            return None

class BearPutSpread(BaseStrategy):
    """
    8. Bear Put Spread
    Sell ATM/ITM Put, Buy OTM Put
    Profit: Net Credit (Premium Collected)
    Max Loss: Spread between strikes - Net Credit
    Best for: Bearish/Neutral, High Probability, Defined Risk
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_BPS_008", config or {})
        self.strike_gap = config.get("strike_gap", 100) if config else 100

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        if regime == "BEAR":
            return 90.0
        elif regime == "SIDEWAYS":
            return 70.0
        return 10.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        """Generate Bear Put Spread signal: Sell ATM Put, Buy OTM Put"""
        try:
            if market_data.empty or len(market_data) < 2:
                return None
            
            current_close = market_data['close'].iloc[-1]
            prev_close = market_data['close'].iloc[-2]
            
            # Signal when price is trending down or stable
            if current_close <= prev_close and regime in ["BEAR", "SIDEWAYS"]:
                _sym = market_data['symbol'].iloc[-1] if 'symbol' in market_data.columns else 'NIFTY'
                return StrategySignal(
                    signal_id=f"BPS_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    strategy_name=self.name,
                    symbol=_sym,
                    signal_type="SELL",
                    market_regime_at_signal=regime,
                    entry_price=current_close,
                    quantity=1,
                    strength=0.75,
                    stop_loss=current_close + (self.strike_gap * 0.5),
                    target_price=current_close - (self.strike_gap * 0.7),
                    metadata={
                        "entry_type": "SELL_SPREAD",
                        "spread_type": "bear_put",
                        "short_strike": round(current_close),
                        "long_strike": round(current_close - self.strike_gap),
                    }
                )
            return None
        except Exception as e:
            self.logger.error(f"Bear Put Spread error: {e}")
            return None

class RatioSpread(BaseStrategy):
    """
    9. Ratio Spread
    (1x2 or 2x1 Call/Put ratio)
    Limited Profit, Unlimited Risk
    Best for: Experienced traders, Sideways markets with good support/resistance
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_RATIO_009", config or {})
        self.ratio = config.get("ratio", 2) if config else 2
        self.strike_gap = config.get("strike_gap", 100) if config else 100

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        if regime == "SIDEWAYS":
            return 70.0
        return 30.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        """Generate Ratio Spread signal"""
        try:
            if market_data.empty or len(market_data) < 3:
                return None
            
            current_close = market_data['close'].iloc[-1]
            recent_high = market_data['high'].iloc[-3:].max()
            recent_low = market_data['low'].iloc[-3:].min()
            
            # Signal in tight sideways range
            range_pct = ((recent_high - recent_low) / current_close) * 100
            
            if regime == "SIDEWAYS" and range_pct < 5:
                _sym = market_data['symbol'].iloc[-1] if 'symbol' in market_data.columns else 'NIFTY'
                return StrategySignal(
                    signal_id=f"RATIO_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    strategy_name=self.name,
                    symbol=_sym,
                    signal_type="SELL",
                    market_regime_at_signal=regime,
                    entry_price=current_close,
                    quantity=self.ratio,
                    strength=0.65,
                    stop_loss=recent_high + self.strike_gap,
                    target_price=current_close,
                    metadata={
                        "entry_type": "RATIO_SPREAD",
                        "spread_type": "ratio",
                        "ratio": f"1x{self.ratio}",
                        "long_strike": round(current_close),
                        "short_strikes": self.ratio,
                    }
                )
            return None
        except Exception as e:
            self.logger.error(f"Ratio Spread error: {e}")
            return None

class CalendarSpread(BaseStrategy):
    """
    10. Calendar Spread (Time Decay Play)
    Sell Near-Term Options, Buy Far-Term Options (same strike)
    Profit from: Time Decay & IV changes
    Best for: Neutral outlook, Taking advantage of time decay
    """
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ALPHA_CALENDAR_010", config or {})
        self.dte_short = config.get("dte_short", 15) if config else 15
        self.dte_long = config.get("dte_long", 45) if config else 45

    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        # Good for low IV environments anticipating IV rise
        return 60.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        """Generate Calendar Spread signal: Focus on IV environment"""
        try:
            if market_data.empty or len(market_data) < 5:
                return None
            
            current_close = market_data['close'].iloc[-1]
            
            # Calculate simple volatility proxy using ATR
            high_low_diff = (market_data['high'] - market_data['low']).iloc[-5:].mean()
            volatility_proxy = (high_low_diff / current_close) * 100
            
            # Signal when IV is expected to rise (low current volatility)
            if volatility_proxy < 2.0:
                _sym = market_data['symbol'].iloc[-1] if 'symbol' in market_data.columns else 'NIFTY'
                return StrategySignal(
                    signal_id=f"CALENDAR_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    strategy_name=self.name,
                    symbol=_sym,
                    signal_type="SELL",
                    market_regime_at_signal=regime,
                    entry_price=current_close,
                    quantity=1,
                    strength=0.70,
                    stop_loss=current_close + (current_close * 0.05),
                    target_price=current_close + (current_close * 0.02),
                    metadata={
                        "entry_type": "CALENDAR_SPREAD",
                        "spread_type": "calendar",
                        "strike": round(current_close),
                        "short_dte": self.dte_short,
                        "long_dte": self.dte_long,
                        "iv_proxy": round(volatility_proxy, 2),
                    }
                )
            return None
        except Exception as e:
            self.logger.error(f"Calendar Spread error: {e}")
            return None

